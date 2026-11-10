#!/usr/bin/env python3
"""Windows x64 wrapper 표본 검사 (표준 라이브러리만, 셸 없이 argv).

사용: .venv/bin/python tests/abi/check_abi.py [--ir-tool PATH]   (환경변수 PRUV_IR_TOOL 도 가능)
각 표본: 객체화 -> opt verify -> COFF x86-64 확인 -> pruv_abi_* 정의 기호 -> C 기준 서명 비교.
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

# 표본 파일 -> [(우리 외부 함수, ref.c 의 기준 구현 이름, ref.c 의 extern 선언 이름)]
SAMPLES = {
    "opt_ret.ll": [("pruv_abi_get_opt",)],
    "res_ret.ll": [("pruv_abi_get_res",)],
    "args_0_1_5.ll": [("pruv_abi_f0",), ("pruv_abi_f1",), ("pruv_abi_f5",)],
    "arr_ret.ll": [("pruv_abi_arr",)],
    "struct_opt.ll": [("pruv_abi_bump",)],
}
# sret 가 있어야 하는 표본
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
    """IR 텍스트에서 {함수명: 정규화 서명}. 서명 = (반환, [인자...]); 인자는 'ptr sret align8' 식."""
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
        print("필요한 도구를 찾지 못함: " + ", ".join(missing))
        print("Windows 실행 ABI 는 이 맥에서 확인 불가: Windows CI 필요")
        return 1

    tmp = Path(tempfile.mkdtemp(prefix="pruv_abi_"))
    try:
        return check_samples(a, tmp, llc, opt, objdump, nm, clang)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def check_samples(a, tmp, llc, opt, objdump, nm, clang):
    # C 기준 IR
    ref_ir = tmp / "ref.ll"
    rc, _, err = run([clang, "--target=" + TRIPLE, "-O0", "-S", "-emit-llvm", str(WIN / "ref.c"), "-o", str(ref_ir)])
    ref_sigs = parse_sigs(ref_ir.read_text()) if rc == 0 and ref_ir.exists() else None
    ref_err = "" if ref_sigs is not None else "clang ref.c 실패: " + err.strip()[:200]

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
                notes.append("COFF x86-64 아님")
            rc, so, se = run([nm, "--defined-only", str(obj)])
            defined = {ln.split()[-1] for ln in so.splitlines() if ln.strip()}
            for (fn,) in funcs:
                if fn not in defined:
                    obj_ok = False
                    notes.append("기호 없음: " + fn)
        else:
            notes.append("객체화 실패: " + err[:160])

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
                # extern 선언(호출 규약)과 기준 구현(ref_ 정의) 둘 다와 비교
                for tag, key in (("declare", fn), ("define", "ref_" + fn)):
                    r = ref_sigs.get(key)
                    if o is None or r is None:
                        sig_ok = False
                        notes.append("%s 서명 못 찾음 (%s)" % (tag, key))
                    elif o != r:
                        sig_ok = False
                        notes.append("%s 불일치 %s: 우리 %s / C %s" % (tag, fn, o, r))
                if o is not None:
                    has_sret = any("sret" in p for p in o[1])
                    if (fname in SRET) != has_sret:
                        sig_ok = False
                        notes.append("sret 유무 기대와 다름: " + fn)
                    if fname in SRET and not (o[0] == "void" and o[1][0] == "ptr sret align8"):
                        sig_ok = False
                        notes.append("sret 첫 인자/void 아님: " + fn)
                    if fname not in SRET and o[0] != "void":
                        sig_ok = False
                        notes.append("void 반환 아님: " + fn)
        ok = obj_ok and ver_ok and sig_ok
        ok_all &= ok
        rows.append((fname, obj_ok, ver_ok, sig_ok, "; ".join(notes) or "-"))

    yn = lambda b: "OK" if b else "FAIL"
    print("%-16s %-8s %-10s %-10s %s" % ("표본", "객체", "verify", "서명 일치", "비고"))
    for f, o, v, s, n in rows:
        print("%-16s %-8s %-10s %-10s %s" % (f, yn(o), yn(v), yn(s), n))
    print("전체: " + ("통과" if ok_all else "실패"))
    print("Windows 실행 ABI 는 이 맥에서 확인 불가: Windows CI 필요")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
