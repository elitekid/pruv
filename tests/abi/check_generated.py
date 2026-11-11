#!/usr/bin/env python3
"""Check the IR (sret wrapper) that the Rust implementation of pruvc generates for the Windows x64 target (standard library only, Python 3.9).

Usage: python3 tests/abi/check_generated.py [--pruvc PATH] [--keep DIR]
  --pruvc  default pruvc-rs/target/release/pruvc (relative to the repository root)
  --keep   keep the artifacts (.ll/.rs/.obj) in DIR
For each source (tests/abi/gen/*.pruv):
  (a) the first two lines of the Windows .ll = target datalayout / target triple
  (b) opt -passes=verify
  (c) pruv_abi_* definitions: Option/Result return = void + first arg `ptr sret({ i64, i64 }) align 8`, everything else = no sret
      (cross-checked via a regex on the source return type and `-> Pruv__Tagged` in the bindings .rs)
  (d) --emit obj --target Windows = COFF x86-64, with pruv_abi_* as defined symbols
  (e) host-target .ll: no triple line, no sret, Option/Result keep returning a `{ i64, i64 }` value
  (f) Option/Result-returning wrapper signature = the C reference signature (declare and define) that clang builds from ref.c
Exit: 0 pass / 1 fail / 2 tool missing.
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
sys.path.insert(0, str(HERE))
from check_abi import LLVM_BIN, TRIPLE, WIN, find_tool, parse_sigs  # noqa: E402

GEN = HERE / "gen"
REPO = HERE.parent.parent
TAGGED = "{ i64, i64 }"
FN_RE = re.compile(r"^fn\s+(\w+)\s*\((.*?)\)\s*->\s*([^!{]+?)\s*(?:!.*)?$")
# number of user args that have a reference in ref.c -> reference function
REF_BY_ARITY = {0: "pruv_abi_f0", 1: "pruv_abi_f1", 5: "pruv_abi_f5"}
LAST_LINE = "The Windows execution ABI cannot be verified on this Mac: Windows CI is required"


def run(argv, timeout=600):
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as e:
        return 127, "", str(e)
    return p.returncode, p.stdout, p.stderr


def source_fns(src):
    """From the source, {function name: return type string}. Assumes a signature is on one line (`fn ... -> T`)."""
    out = {}
    for line in src.read_text().splitlines():
        m = FN_RE.match(line.strip())
        if m:
            out[m.group(1)] = m.group(3).strip()
    return out


def is_tagged(ret_ty):
    """Only the legacy Option<i64> / Result<i64> are returned as the tagged pair ({ i64, i64 } / sret on Windows).
    G3 A4: Option<X> / Result<X> with X != i64 are word aggregates (void + trailing output pointer, no sret)."""
    return ret_ty.replace(" ", "") in ("Option<i64>", "Result<i64>")


def is_array(ret_ty):
    """Return through a trailing out pointer + void, no sret: arrays/str (`[i64]`, `[u8]`, refined
    `[u8 | L..=U; <=N]`, `str`) and, since G3 A4, any word aggregate (new Option/Result, generic nominal types)."""
    if ret_ty.startswith("[") or ret_ty == "str":
        return True
    return not is_tagged(ret_ty) and ret_ty not in ("i64", "bool", "()")


def expected_ret(ret_ty):
    """Expected return of a wrapper without sret: i64/bool = i64, everything else = void."""
    return "i64" if ret_ty in ("i64", "bool") else "void"


def abi_defs(ir_text):
    """{name: (normalized signature, original line)} - only define @pruv_abi_*."""
    sigs = parse_sigs(ir_text)
    lines = {}
    for ln in ir_text.splitlines():
        m = re.match(r"\s*define\b.*@(pruv_abi_[\w.$]+)\(", ln)
        if m:
            lines[m.group(1)] = ln.strip()
    return {n: (sigs[n], lines[n]) for n in lines if n in sigs}


def binding_typed(rs_text):
    """List of `pruv_abi_*__typed` extern names the bindings .rs calls (G2 A5, B2: functions with [bool] or str parameters)."""
    return sorted(set(re.findall(r"fn\s+(pruv_abi_\w+__typed)\s*\(", rs_text)))


def binding_tagged(rs_text):
    """From the extern declarations in the bindings .rs, {pruv_abi_name: whether the return is Pruv__Tagged}."""
    out = {}
    for m in re.finditer(r"fn\s+(pruv_abi_\w+)\s*\(([^)]*)\)\s*(->\s*[\w:<>\s*]+)?;", rs_text):
        # G2 A5: a function with a [bool] parameter is bound through pruv_abi_<f>__typed (same ABI, no byte check)
        name = m.group(1)[:-len("__typed")] if m.group(1).endswith("__typed") else m.group(1)
        out[name] = bool(m.group(3) and "Pruv__Tagged" in m.group(3))
    return out


def check_one(src, a, tools, ref_sigs, ref_err, work):
    fns = source_fns(src)
    stem = src.stem
    res = {"hdr": True, "ver": True, "sret": True, "obj": True, "host": True, "ref": True}
    notes = []
    typed_names = []

    def fail(k, msg):
        res[k] = False
        notes.append("%s: %s" % (k, msg))

    if not fns:
        for k in res:
            res[k] = False
        return res, ["could not read functions from the source"]
    want = {"pruv_abi_" + n: t for n, t in fns.items()}

    # ---- Windows .ll
    ll = work / (stem + ".win.ll")
    rs = work / (stem + ".win.rs")
    rc, _, err = run([a.pruvc, str(src), "--backend", "llvm", "--emit", "ll", "--target", TRIPLE,
                      "-o", str(ll), "--rust-bindings", str(rs)])
    text = ll.read_text() if rc == 0 and ll.exists() else None
    if text is None:
        for k in ("hdr", "ver", "sret", "ref"):
            res[k] = False
        notes.append("Windows .ll generation failed: " + err.strip()[:200])
    else:
        # (a)
        first = text.splitlines()[:2]
        if not (len(first) == 2 and first[0].startswith("target datalayout")
                and re.match(r'target triple = "%s"$' % re.escape(TRIPLE), first[1])):
            fail("hdr", "first two lines are not datalayout/triple: %r" % (first,))
        # (b)
        rc, _, err = run([tools["opt"], "-passes=verify", "-disable-output", str(ll)])
        if rc != 0:
            fail("ver", err.strip()[:160])
        # (c)
        defs = abi_defs(text)
        for name in sorted(want):
            if name not in defs:
                fail("sret", "no definition: " + name)
        for name, ((ret, params), line) in sorted(defs.items()):
            t = want.get(name)
            if t is None:
                continue
            nsret = sum(1 for p in params if "sret" in p)
            if is_tagged(t):
                if not (ret == "void" and params and params[0] == "ptr sret align8"
                        and nsret == 1 and "sret({ i64, i64 })" in line and "align 8" in line):
                    fail("sret", "%s: is Option/Result but not void + first sret({ i64, i64 }) align 8: %s" % (name, line[:120]))
            else:
                if nsret:
                    fail("sret", "%s: must not have sret" % name)
                if ret != expected_ret(t):
                    fail("sret", "%s: return %s (expected %s)" % (name, ret, expected_ret(t)))
                if is_array(t) and not (params and params[-1].startswith("ptr")):
                    fail("sret", "%s: returns an array but the last arg is not an out pointer (ptr): %s" % (name, line[:120]))
        # G2 B2: a `__typed` define must have the same signature as the original define, and a `__typed` the bindings call must be defined in the IR
        for name in sorted(defs):
            if name.endswith("__typed"):
                typed_names.append(name)
                base = name[:-len("__typed")]
                if base not in defs:
                    fail("sret", "no original definition for __typed: " + name)
                elif defs[base][0] != defs[name][0]:
                    fail("sret", "%s signature differs from the original: %s / %s" % (name, defs[name][0], defs[base][0]))
        if rs.exists():
            for tn in binding_typed(rs.read_text()):
                if tn not in defs:
                    fail("sret", "%s called by the bindings is not defined in the IR" % tn)
            bt = binding_tagged(rs.read_text())
            for name, t in sorted(want.items()):
                if name not in bt:
                    fail("sret", "no declaration in the bindings: " + name)
                elif bt[name] != is_tagged(t):
                    fail("sret", "bindings' Pruv__Tagged determination differs from the source: " + name)
        else:
            fail("sret", "no bindings .rs")
        # (f)
        if ref_sigs is None:
            fail("ref", ref_err)
        else:
            for name, t in sorted(want.items()):
                if not is_tagged(t) or name not in defs:
                    continue
                ours = defs[name][0]
                rest = ours[1][1:]
                if any(p != "i64" for p in rest) or len(rest) not in REF_BY_ARITY:
                    notes.append("ref: %s has no C reference (%d user args)" % (name, len(rest)))
                    continue
                base = REF_BY_ARITY[len(rest)]
                for tag, key in (("declare", base), ("define", "ref_" + base)):
                    r = ref_sigs.get(key)
                    if r is None:
                        fail("ref", "no C reference: " + key)
                    elif r != ours:
                        fail("ref", "%s mismatch %s: ours %s / C %s" % (tag, name, ours, r))

    # ---- (d) COFF object
    obj = work / (stem + ".win.obj")
    rc, _, err = run([a.pruvc, str(src), "--backend", "llvm", "--emit", "obj", "--target", TRIPLE, "-o", str(obj)])
    if rc != 0 or not obj.exists():
        fail("obj", "object generation failed: " + err.strip()[:200])
    else:
        rc, so, _ = run([tools["llvm-objdump"], "--file-headers", str(obj)])
        if not (rc == 0 and "coff-x86-64" in so):
            fail("obj", "not COFF x86-64")
        rc, so, _ = run([tools["llvm-nm"], "--defined-only", str(obj)])
        defined = {ln.split()[-1] for ln in so.splitlines() if ln.strip()}
        for name in sorted(list(want) + typed_names):
            if name not in defined:
                fail("obj", "defined symbol missing: " + name)

    # ---- (e) host .ll
    hll = work / (stem + ".host.ll")
    hrs = work / (stem + ".host.rs")
    rc, _, err = run([a.pruvc, str(src), "--backend", "llvm", "--emit", "ll",
                      "-o", str(hll), "--rust-bindings", str(hrs)])
    if rc != 0 or not hll.exists():
        fail("host", "host .ll generation failed: " + err.strip()[:200])
    else:
        htext = hll.read_text()
        if re.search(r"^target triple\b", htext, re.M):
            fail("host", "host .ll has a target triple line")
        if re.search(r"\bsret\(", htext):
            fail("host", "host .ll has sret")
        hdefs = abi_defs(htext)
        for name, t in sorted(want.items()):
            d = hdefs.get(name)
            if d is None:
                fail("host", "no definition: " + name)
            elif is_tagged(t) and d[0][0] != TAGGED:
                fail("host", "%s: host return is not %s: %s" % (name, TAGGED, d[0][0]))
    return res, notes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pruvc", default=str(REPO / "pruvc-rs" / "target" / "release" / ("pruvc.exe" if os.name == "nt" else "pruvc")))
    ap.add_argument("--keep", default=None)
    a = ap.parse_args()

    tools = {n: find_tool(n) for n in ("opt", "llvm-objdump", "llvm-nm", "clang")}
    missing = [n for n, t in tools.items() if not t]
    if not Path(a.pruvc).exists():
        missing.append("pruvc(%s)" % a.pruvc)
    sources = sorted(GEN.glob("*.pruv"))
    if not sources:
        missing.append("tests/abi/gen/*.pruv")
    if missing:
        print("required tools/inputs not found: " + ", ".join(missing))
        print("(LLVM in %s takes precedence)" % LLVM_BIN)
        print(LAST_LINE)
        return 2

    if a.keep:
        work = Path(a.keep)
        work.mkdir(parents=True, exist_ok=True)
        cleanup = False
    else:
        work = Path(tempfile.mkdtemp(prefix="pruv_gen_abi_"))
        cleanup = True
    try:
        ref_ll = work / "ref.ll"
        rc, _, err = run([tools["clang"], "--target=" + TRIPLE, "-O0", "-S", "-emit-llvm",
                          str(WIN / "ref.c"), "-o", str(ref_ll)])
        ref_sigs = parse_sigs(ref_ll.read_text()) if rc == 0 and ref_ll.exists() else None
        ref_err = "" if ref_sigs is not None else "clang ref.c failed: " + err.strip()[:200]

        cols = ("hdr", "ver", "sret", "obj", "host", "ref")
        rows, ok_all = [], True
        for src in sources:
            res, notes = check_one(src, a, tools, ref_sigs, ref_err, work)
            ok_all &= all(res.values())
            rows.append((src.name, res, notes))

        yn = lambda b: "OK" if b else "FAIL"
        print("%-18s %-5s %-7s %-5s %-5s %-5s %-5s %s" % ("source", "header", "verify", "sret", "COFF", "host", "C ref", "notes"))
        for name, res, notes in rows:
            print("%-18s %-5s %-7s %-5s %-5s %-5s %-5s %s" % (
                (name,) + tuple(yn(res[c]) for c in cols) + ("; ".join(notes) or "-",)))
        print("Total: " + ("pass" if ok_all else "fail"))
        if a.keep:
            print("artifacts: " + str(work))
        print(LAST_LINE)
        return 0 if ok_all else 1
    finally:
        if cleanup:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
