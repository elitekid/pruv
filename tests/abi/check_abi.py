#!/usr/bin/env python3
"""Check the Windows x64 wrapper samples (standard library only, argv without a shell).

Usage: .venv/bin/python tests/abi/check_abi.py [--ir-tool PATH]   (the PRUV_IR_TOOL environment variable also works)
Per sample: compile to object -> opt verify -> confirm COFF x86-64 -> pruv_abi_* defined symbols -> cross-check against the C reference signature.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
WIN = HERE / "win_x64"
TRIPLE = "x86_64-pc-windows-msvc"
LLVM_BIN = Path("/opt/homebrew/opt/llvm@22/bin")

# sample file -> [(our external function, reference implementation name in ref.c, extern declaration name in ref.c)]
SAMPLES = {
    "opt_ret.ll": [("pruv_abi_get_opt",)],
    "res_ret.ll": [("pruv_abi_get_res",)],
    "args_0_1_5.ll": [("pruv_abi_f0",), ("pruv_abi_f1",), ("pruv_abi_f5",)],
    "arr_ret.ll": [("pruv_abi_arr",)],
    "struct_opt.ll": [("pruv_abi_bump",)],
}
# samples that must have sret
SRET = {"opt_ret.ll", "res_ret.ll", "args_0_1_5.ll"}


def find_tool(name):
    cand = LLVM_BIN / name
    if cand.exists():
        return str(cand)
    return shutil.which(name)


def run(argv):
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as e:
        return 127, "", str(e)
    return p.returncode, p.stdout, p.stderr


def split_params(s):
    out, depth, cur = [], 0, ""
    for ch in s:
        if ch in "({[<":
            depth += 1
        elif ch in ")}]>":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


DEF_RE = re.compile(r"^(define|declare)\s+(.*?)@([\w.$]+)\((.*)\)[^()]*?\{?\s*$")
DROP = {"dso_local", "internal", "private", "noundef", "signext", "zeroext", "noalias", "nonnull"}


def parse_sigs(ir_text):
    """From IR text, {function name: normalized signature}. Signature = (return, [args...]); an arg looks like 'ptr sret align8'."""
    sigs = {}
    for line in ir_text.splitlines():
        m = DEF_RE.match(line.strip())
        if not m:
            continue
        _, pre, name, params = m.groups()
        ret = " ".join(t for t in pre.split() if t not in DROP and not t.startswith("#"))
        norm = []
        for p in split_params(params):
            ty = p.split()[0]
            if re.search(r"\bsret\(", p):
                al = re.search(r"\balign (\d+)", p)
                norm.append("%s sret align%s" % (ty, al.group(1) if al else "?"))
            else:
                norm.append(ty)
        sigs[name] = (ret, norm)
    return sigs


def objectify(ll, obj, ir_tool, llc):
    if ir_tool:
        argv = [ir_tool, "obj", str(ll), "-o", str(obj), "--target", TRIPLE]
    else:
        argv = [llc, "-mtriple=" + TRIPLE, "-filetype=obj", "-O2", str(ll), "-o", str(obj)]
    rc, _, err = run(argv)
    return rc == 0 and obj.exists(), err.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ir-tool", default=os.environ.get("PRUV_IR_TOOL"))
    a = ap.parse_args()

    llc, opt = find_tool("llc"), find_tool("opt")
    objdump, nm, clang = find_tool("llvm-objdump"), find_tool("llvm-nm"), find_tool("clang")
    missing = [n for n, t in (("opt", opt), ("llvm-objdump", objdump), ("llvm-nm", nm), ("clang", clang)) if not t]
    if not a.ir_tool and not llc:
        missing.append("llc")
    if missing:
        print("required tools not found: " + ", ".join(missing))
        print("The Windows execution ABI cannot be verified on this Mac: Windows CI is required")
        return 1

    tmp = Path(tempfile.mkdtemp(prefix="pruv_abi_"))
    try:
        return check_samples(a, tmp, llc, opt, objdump, nm, clang)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def check_samples(a, tmp, llc, opt, objdump, nm, clang):
    # C reference IR
    ref_ir = tmp / "ref.ll"
    rc, _, err = run([clang, "--target=" + TRIPLE, "-O0", "-S", "-emit-llvm", str(WIN / "ref.c"), "-o", str(ref_ir)])
    ref_sigs = parse_sigs(ref_ir.read_text()) if rc == 0 and ref_ir.exists() else None
    ref_err = "" if ref_sigs is not None else "clang ref.c failed: " + err.strip()[:200]

    rows, ok_all = [], True
    for fname, funcs in SAMPLES.items():
        ll = WIN / fname
        notes = []
        obj_ok = ver_ok = sig_ok = False
        obj = tmp / (ll.stem + ".o")

        obj_ok, err = objectify(ll, obj, a.ir_tool, llc)
        if obj_ok:
            rc, so, se = run([objdump, "--file-headers", str(obj)])
            if not (rc == 0 and re.search(r"coff-x86-64", so)):
                obj_ok = False
                notes.append("not COFF x86-64")
            rc, so, se = run([nm, "--defined-only", str(obj)])
            defined = {ln.split()[-1] for ln in so.splitlines() if ln.strip()}
            for (fn,) in funcs:
                if fn not in defined:
                    obj_ok = False
                    notes.append("symbol missing: " + fn)
        else:
            notes.append("object generation failed: " + err[:160])

        rc, _, err = run([opt, "-passes=verify", "-disable-output", str(ll)])
        ver_ok = rc == 0
        if not ver_ok:
            notes.append("verify: " + err.strip()[:160])

        ours = parse_sigs(ll.read_text())
        if ref_sigs is None:
            notes.append(ref_err)
        else:
            sig_ok = True
            for (fn,) in funcs:
                o = ours.get(fn)
                # cross-check against both the extern declaration (calling convention) and the reference implementation (ref_ definition)
                for tag, key in (("declare", fn), ("define", "ref_" + fn)):
                    r = ref_sigs.get(key)
                    if o is None or r is None:
                        sig_ok = False
                        notes.append("%s signature not found (%s)" % (tag, key))
                    elif o != r:
                        sig_ok = False
                        notes.append("%s mismatch %s: ours %s / C %s" % (tag, fn, o, r))
                if o is not None:
                    has_sret = any("sret" in p for p in o[1])
                    if (fname in SRET) != has_sret:
                        sig_ok = False
                        notes.append("sret presence differs from expectation: " + fn)
                    if fname in SRET and not (o[0] == "void" and o[1][0] == "ptr sret align8"):
                        sig_ok = False
                        notes.append("first arg is not sret / return is not void: " + fn)
                    if fname not in SRET and o[0] != "void":
                        sig_ok = False
                        notes.append("return is not void: " + fn)
        ok = obj_ok and ver_ok and sig_ok
        ok_all &= ok
        rows.append((fname, obj_ok, ver_ok, sig_ok, "; ".join(notes) or "-"))

    yn = lambda b: "OK" if b else "FAIL"
    print("%-16s %-8s %-10s %-10s %s" % ("sample", "object", "verify", "sig match", "notes"))
    for f, o, v, s, n in rows:
        print("%-16s %-8s %-10s %-10s %s" % (f, yn(o), yn(v), yn(s), n))
    print("Total: " + ("pass" if ok_all else "fail"))
    print("The Windows execution ABI cannot be verified on this Mac: Windows CI is required")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
