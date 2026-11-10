#!/usr/bin/env python3
"""Windows x64 실행 ABI 확인 (windows-latest 러너, 표준 라이브러리만).

사용: python tests/abi/winci/run_windows.py [--skip-c] [--keep DIR] [--only 이름 ...]
out/<이름>.win.ll -> clang -> .obj, pruvc/runtime.c -> .obj(PRUV_RUST_ALLOCATOR), rustc 로 <이름>_main.rs 를
`-C link-arg=<obj>` 와 빌드·실행해 stdout 을 out/<이름>.expected 와 비교. 선택: C 호출자(c_caller.c) 사례.
하나라도 다르면 exit 1.
"""
import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent.parent
OUT = HERE / "out"
RUNTIME_C = REPO / "pruvc" / "runtime.c"
TRIPLE = "x86_64-pc-windows-msvc"
# rustc 는 동적 CRT(msvcrt)를 쓰므로 C 객체도 같게 맞춘다(libcmt 와 섞이면 링크 경고/중복 기호).
C_FLAGS = ["--target=" + TRIPLE, "-O2", "-std=c11", "-fms-runtime-lib=dll", "-D_CRT_SECURE_NO_WARNINGS"]


def run(argv, timeout=600):
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except OSError as e:
        return 127, "", str(e)
    return p.returncode, p.stdout, p.stderr


def tail(*parts, n=1500):
    return "".join(parts).strip()[-n:]


def norm(s):
    return s.replace("\r\n", "\n")


def first_diff(got, want):
    g, w = got.split("\n"), want.split("\n")
    for i in range(max(len(g), len(w))):
        a = g[i] if i < len(g) else "<없음>"
        b = w[i] if i < len(w) else "<없음>"
        if a != b:
            return "줄 %d: 실제 %r / 기대 %r" % (i + 1, a, b)
    return "?"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-c", action="store_true")
    ap.add_argument("--keep", default=None)
    ap.add_argument("--only", nargs="*", default=None)
    a = ap.parse_args()

    clang, rustc = shutil.which("clang"), shutil.which("rustc")
    if not clang or not rustc:
        print("도구 없음: clang=%s rustc=%s" % (clang, rustc))
        return 1
    stems = sorted(p.name[: -len(".win.ll")] for p in OUT.glob("*.win.ll"))
    if a.only:
        stems = [s for s in stems if s in a.only]
    if not stems:
        print("out/*.win.ll 이 없음 (맥에서 prepare.py 를 돌려 커밋해야 함)")
        return 1

    work = Path(a.keep) if a.keep else Path(tempfile.mkdtemp(prefix="pruv_winci_"))
    work.mkdir(parents=True, exist_ok=True)
    rows = []
    try:
        rt_o = work / "runtime.obj"
        rc, so, se = run([clang] + C_FLAGS + ["-DPRUV_RUST_ALLOCATOR", "-c", str(RUNTIME_C), "-o", str(rt_o)])
        if rc != 0:
            print("runtime.c 컴파일 실패:\n" + tail(so, se))
            return 1

        for stem in stems:
            gen_o = work / (stem + "_gen.obj")
            exe = work / (stem + ".exe")
            detail = ""
            rc, so, se = run([clang, "--target=" + TRIPLE, "-O2", "-Wno-override-module", "-c",
                              str(OUT / (stem + ".win.ll")), "-o", str(gen_o)])
            if rc != 0:
                rows.append((stem, "FAIL", "clang(.ll): " + tail(so, se)))
                continue
            rc, so, se = run([rustc, "-O", "--edition", "2021", "--target", TRIPLE, str(OUT / (stem + "_main.rs")),
                              "-o", str(exe), "-C", "link-arg=" + str(gen_o), "-C", "link-arg=" + str(rt_o)])
            if rc != 0:
                rows.append((stem, "FAIL", "rustc/link: " + tail(so, se)))
                continue
            rc, so, se = run([str(exe)], timeout=300)
            if rc != 0:
                rows.append((stem, "FAIL", "실행 exit %d (%#x): %s" % (rc, rc & 0xFFFFFFFF, tail(se, so, n=600))))
                continue
            want = norm((OUT / (stem + ".expected")).read_text(encoding="utf-8"))
            got = norm(so)
            if got == want:
                rows.append((stem, "OK", "%d 줄 일치" % want.count("\n")))
            else:
                rows.append((stem, "FAIL", "stdout 다름 — " + first_diff(got, want)))

        if not a.skip_c:
            stem = "args_0_1_5"
            gen_o = work / (stem + "_gen.obj")
            rt_c = work / "runtime_c.obj"
            exe = work / "c_caller.exe"
            if not gen_o.exists():
                rows.append(("c_caller", "FAIL", "args_0_1_5 객체 없음(앞 단계 실패)"))
            else:
                # Rust allocator 변형이 아닌 기본 runtime(호스트 기호 불필요)을 C 호출자와 링크한다.
                rc, so, se = run([clang] + C_FLAGS + ["-c", str(RUNTIME_C), "-o", str(rt_c)])
                if rc == 0:
                    rc, so, se = run([clang, "--target=" + TRIPLE, "-O1", "-fms-runtime-lib=dll", "-fuse-ld=lld",
                                      str(HERE / "c_caller.c"), str(gen_o), str(rt_c), "-o", str(exe)])
                if rc != 0:
                    rows.append(("c_caller", "FAIL", "clang 빌드/링크: " + tail(so, se)))
                else:
                    rc, so, se = run([str(exe)], timeout=120)
                    rows.append(("c_caller", "OK" if rc == 0 else "FAIL", tail(so, se, n=600).replace("\n", " | ")))
    finally:
        if not a.keep:
            shutil.rmtree(work, ignore_errors=True)

    print("%-18s %-5s %s" % ("이름", "결과", "상세"))
    for stem, res, detail in rows:
        print("%-18s %-5s %s" % (stem, res, detail if res != "OK" else detail.splitlines()[0] if detail else ""))
    bad = [r for r in rows if r[1] != "OK"]
    for stem, res, detail in bad:
        print("\n--- %s ---\n%s" % (stem, detail))
    print("\n전체: %s (%d/%d)" % ("통과" if not bad else "실패", len(rows) - len(bad), len(rows)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
