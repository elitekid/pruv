#!/usr/bin/env python3
"""Rust 판 pruvc 가 Windows x64 대상으로 만든 IR(sret wrapper) 검사 (표준 라이브러리만, Python 3.9).

사용: python3 tests/abi/check_generated.py [--pruvc PATH] [--keep DIR]
  --pruvc  기본 pruvc-rs/target/release/pruvc (저장소 루트 기준)
  --keep   산출물(.ll/.rs/.obj)을 DIR 에 남김
소스(tests/abi/gen/*.pruv)마다:
  (a) Windows .ll 첫 두 줄 = target datalayout / target triple
  (b) opt -passes=verify
  (c) pruv_abi_* 정의: Option/Result 반환 = void + 첫 인자 `ptr sret({ i64, i64 }) align 8`, 나머지 = sret 없음
      (소스 반환 타입 정규식 + 바인딩 .rs 의 `-> Pruv__Tagged` 교차 확인)
  (d) --emit obj --target Windows = COFF x86-64, pruv_abi_* 가 정의 기호
  (e) 호스트 대상 .ll: triple 줄 없음, sret 없음, Option/Result 는 `{ i64, i64 }` 값 반환 유지
  (f) Option/Result 반환 wrapper 서명 = ref.c 를 clang 이 만든 C 기준 서명(declare·define)
종료: 0 통과 / 1 실패 / 2 도구 없음.
"""
import argparse
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
# ref.c 에 기준이 있는 사용자 인자 수 -> 기준 함수
REF_BY_ARITY = {0: "pruv_abi_f0", 1: "pruv_abi_f1", 5: "pruv_abi_f5"}
LAST_LINE = "Windows 실행 ABI 는 이 맥에서 확인 불가: Windows CI 필요"


def run(argv, timeout=600):
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as e:
        return 127, "", str(e)
    return p.returncode, p.stdout, p.stderr


def source_fns(src):
    """소스에서 {함수명: 반환 타입 문자열}. 시그니처는 한 줄(`fn ... -> T`)이라고 가정."""
    out = {}
    for line in src.read_text().splitlines():
        m = FN_RE.match(line.strip())
        if m:
            out[m.group(1)] = m.group(3).strip()
    return out


def is_tagged(ret_ty):
    return ret_ty.startswith("Option<") or ret_ty.startswith("Result<")


def expected_ret(ret_ty):
    """sret 없는 wrapper 의 기대 반환: i64/bool = i64, 나머지 = void."""
    return "i64" if ret_ty in ("i64", "bool") else "void"


def abi_defs(ir_text):
    """{이름: (정규화 서명, 원문 줄)} — define @pruv_abi_* 만."""
    sigs = parse_sigs(ir_text)
    lines = {}
    for ln in ir_text.splitlines():
        m = re.match(r"\s*define\b.*@(pruv_abi_[\w.$]+)\(", ln)
        if m:
            lines[m.group(1)] = ln.strip()
    return {n: (sigs[n], lines[n]) for n in lines if n in sigs}


def binding_tagged(rs_text):
    """바인딩 .rs 의 extern 선언에서 {pruv_abi_이름: 반환이 Pruv__Tagged 인가}."""
    out = {}
    for m in re.finditer(r"fn\s+(pruv_abi_\w+)\s*\(([^)]*)\)\s*(->\s*[\w:<>\s*]+)?;", rs_text):
        out[m.group(1)] = bool(m.group(3) and "Pruv__Tagged" in m.group(3))
    return out


def check_one(src, a, tools, ref_sigs, ref_err, work):
    fns = source_fns(src)
    stem = src.stem
    res = {"hdr": True, "ver": True, "sret": True, "obj": True, "host": True, "ref": True}
    notes = []

    def fail(k, msg):
        res[k] = False
        notes.append("%s: %s" % (k, msg))

    if not fns:
        for k in res:
            res[k] = False
        return res, ["소스에서 함수를 못 읽음"]
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
        notes.append("Windows .ll 생성 실패: " + err.strip()[:200])
    else:
        # (a)
        first = text.splitlines()[:2]
        if not (len(first) == 2 and first[0].startswith("target datalayout")
                and re.match(r'target triple = "%s"$' % re.escape(TRIPLE), first[1])):
            fail("hdr", "첫 두 줄이 datalayout/triple 아님: %r" % (first,))
        # (b)
        rc, _, err = run([tools["opt"], "-passes=verify", "-disable-output", str(ll)])
        if rc != 0:
            fail("ver", err.strip()[:160])
        # (c)
        defs = abi_defs(text)
        for name in sorted(want):
            if name not in defs:
                fail("sret", "정의 없음: " + name)
        for name, ((ret, params), line) in sorted(defs.items()):
            t = want.get(name)
            if t is None:
                continue
            nsret = sum(1 for p in params if "sret" in p)
            if is_tagged(t):
                if not (ret == "void" and params and params[0] == "ptr sret align8"
                        and nsret == 1 and "sret({ i64, i64 })" in line and "align 8" in line):
                    fail("sret", "%s: Option/Result 인데 void+첫 sret({ i64, i64 }) align 8 아님: %s" % (name, line[:120]))
            else:
                if nsret:
                    fail("sret", "%s: sret 가 있으면 안 됨" % name)
                if ret != expected_ret(t):
                    fail("sret", "%s: 반환 %s (기대 %s)" % (name, ret, expected_ret(t)))
        if rs.exists():
            bt = binding_tagged(rs.read_text())
            for name, t in sorted(want.items()):
                if name not in bt:
                    fail("sret", "바인딩에 선언 없음: " + name)
                elif bt[name] != is_tagged(t):
                    fail("sret", "바인딩 Pruv__Tagged 판정이 소스와 다름: " + name)
        else:
            fail("sret", "바인딩 .rs 없음")
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
                    notes.append("ref: %s 는 C 기준 없음(사용자 인자 %d개)" % (name, len(rest)))
                    continue
                base = REF_BY_ARITY[len(rest)]
                for tag, key in (("declare", base), ("define", "ref_" + base)):
                    r = ref_sigs.get(key)
                    if r is None:
                        fail("ref", "C 기준 없음: " + key)
                    elif r != ours:
                        fail("ref", "%s 불일치 %s: 우리 %s / C %s" % (tag, name, ours, r))

    # ---- (d) COFF 객체
    obj = work / (stem + ".win.obj")
    rc, _, err = run([a.pruvc, str(src), "--backend", "llvm", "--emit", "obj", "--target", TRIPLE, "-o", str(obj)])
    if rc != 0 or not obj.exists():
        fail("obj", "객체 생성 실패: " + err.strip()[:200])
    else:
        rc, so, _ = run([tools["llvm-objdump"], "--file-headers", str(obj)])
        if not (rc == 0 and "coff-x86-64" in so):
            fail("obj", "COFF x86-64 아님")
        rc, so, _ = run([tools["llvm-nm"], "--defined-only", str(obj)])
        defined = {ln.split()[-1] for ln in so.splitlines() if ln.strip()}
        for name in sorted(want):
            if name not in defined:
                fail("obj", "정의 기호 없음: " + name)

    # ---- (e) 호스트 .ll
    hll = work / (stem + ".host.ll")
    hrs = work / (stem + ".host.rs")
    rc, _, err = run([a.pruvc, str(src), "--backend", "llvm", "--emit", "ll",
                      "-o", str(hll), "--rust-bindings", str(hrs)])
    if rc != 0 or not hll.exists():
        fail("host", "호스트 .ll 생성 실패: " + err.strip()[:200])
    else:
        htext = hll.read_text()
        if re.search(r"^target triple\b", htext, re.M):
            fail("host", "호스트 .ll 에 target triple 줄이 있음")
        if re.search(r"\bsret\(", htext):
            fail("host", "호스트 .ll 에 sret 가 있음")
        hdefs = abi_defs(htext)
        for name, t in sorted(want.items()):
            d = hdefs.get(name)
            if d is None:
                fail("host", "정의 없음: " + name)
            elif is_tagged(t) and d[0][0] != TAGGED:
                fail("host", "%s: 호스트 반환이 %s 아님: %s" % (name, TAGGED, d[0][0]))
    return res, notes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pruvc", default=str(REPO / "pruvc-rs" / "target" / "release" / "pruvc"))
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
        print("필요한 도구/입력을 찾지 못함: " + ", ".join(missing))
        print("(LLVM 은 %s 우선)" % LLVM_BIN)
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
        ref_err = "" if ref_sigs is not None else "clang ref.c 실패: " + err.strip()[:200]

        cols = ("hdr", "ver", "sret", "obj", "host", "ref")
        rows, ok_all = [], True
        for src in sources:
            res, notes = check_one(src, a, tools, ref_sigs, ref_err, work)
            ok_all &= all(res.values())
            rows.append((src.name, res, notes))

        yn = lambda b: "OK" if b else "FAIL"
        print("%-18s %-5s %-7s %-5s %-5s %-5s %-5s %s" % ("소스", "헤더", "verify", "sret", "COFF", "호스트", "C기준", "비고"))
        for name, res, notes in rows:
            print("%-18s %-5s %-7s %-5s %-5s %-5s %-5s %s" % (
                (name,) + tuple(yn(res[c]) for c in cols) + ("; ".join(notes) or "-",)))
        print("전체: " + ("통과" if ok_all else "실패"))
        if a.keep:
            print("산출물: " + str(work))
        print(LAST_LINE)
        return 0 if ok_all else 1
    finally:
        if cleanup:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
