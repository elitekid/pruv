#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""[bool] raw ABI 표현 검사 시험 (docs/G2_A5_IMPL.md 0절 결정 5·4.2·4.3·5절; 표준 라이브러리만, Python 3.9).

사용: python3 tests/abi/check_bool_repr.py [--pruvc PATH] [--py-pruvc PATH] [--keep DIR]
  --pruvc     Rust 판 pruvc (기본 pruvc-rs/target/release/pruvc)
  --py-pruvc  Python 판 pruvc.py (기본 pruvc/pruvc.py, 파이썬은 .venv 가 있으면 그것)
  --keep      산출물을 DIR 에 남김
두 컴파일러(py·rs)가 같은 [bool] 인자 함수에서 낸 .ll 을 일반 런타임(pruvc/runtime.c, RUST_ALLOCATOR 아님)과
C 호출자에 링크해 `pruv_abi_tcount(const uint8_t *, int64_t)` 를 직접 부른다. 경우(컴파일러마다):
  ok            바이트 1 0 1           → 종료 0, stdout 2
  ok_all_true   바이트 1 1 1 1         → 종료 0, stdout 4
  bad_byte      바이트 1 2 1           → 종료 101, stderr `pruv: invalid representation: 2 (bool 0..=1)`
  bad_last      바이트 1 0 255         → 종료 101, stderr `pruv: invalid representation: 255 (bool 0..=1)`
  trust_bad     --trust-callers 빌드, 바이트 1 2 1 → bad_byte 와 같은 결과 (표현 검사는 trust 와 무관)
  trust_ok      --trust-callers 빌드, 바이트 1 0 1 → 종료 0, stdout 2
  repr_first    바이트 0 2 (requires 도 거짓) → 표현 오류가 먼저(`requires violated` 가 없어야 함)
  requires_ok   바이트 0 1 (표현은 정상, requires 거짓) → 종료 101, stderr `requires violated`
경우마다 `ok <컴파일러>/<이름>` / `FAIL <컴파일러>/<이름>: 이유` 한 줄, 끝에 `N/N ok`.
종료: 0 전부 통과 / 1 실패 있음 / 2 도구·입력 없음.
"""
import argparse
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
RUNTIME = REPO / "pruvc" / "runtime.c"
CPU_FLAG = "-mcpu=native" if platform.machine().lower() in ("arm64", "aarch64") else "-march=native"
REPR_MSG = "pruv: invalid representation: %d (bool 0..=1)"

SOURCE = """// [bool] raw ABI 표현 검사용: 참 개수를 센다 (requires 가 [bool] 원소를 읽는다)
fn tcount(a: [bool]) -> i64
  requires len(a) >= 1 && a[0]
  ensures 0 <= result && result <= len(a)
{
  let mut c: i64 = 0;
  let mut i: i64 = 0;
  while i < len(a)
    invariant 0 <= i && i <= len(a)
    invariant 0 <= c && c <= i
    decreases len(a) - i
  {
    if a[i] {
      c = c + 1;
    }
    i = i + 1;
  }
  return c;
}
"""

CALLER = """#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
extern int64_t pruv_abi_tcount(const uint8_t *a, int64_t n);
int main(int argc, char **argv) {
    uint8_t buf[32];
    int n = argc - 1;
    if (n > 32) n = 32;
    for (int k = 0; k < n; k++) buf[k] = (uint8_t)atoi(argv[k + 1]);
    printf("%lld\\n", (long long)pruv_abi_tcount(buf, (int64_t)n));
    return 0;
}
"""

# (이름, trust 빌드인가, 바이트 인자, 기대 종료, 기대 stdout 줄(None=검사 안 함), stderr 에 있어야 할 글, stderr 에 없어야 할 글)
CASES = [
    ("ok", False, [1, 0, 1], 0, "2", None, None),
    ("ok_all_true", False, [1, 1, 1, 1], 0, "4", None, None),
    ("bad_byte", False, [1, 2, 1], 101, "", REPR_MSG % 2, None),
    ("bad_last", False, [1, 0, 255], 101, "", REPR_MSG % 255, None),
    ("trust_bad", True, [1, 2, 1], 101, "", REPR_MSG % 2, None),
    ("trust_ok", True, [1, 0, 1], 0, "2", None, None),
    ("repr_first", False, [0, 2], 101, "", REPR_MSG % 2, "requires violated"),
    ("requires_ok", False, [0, 1], 101, "", "requires violated", "invalid representation"),
]


def run(argv, timeout=600):
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as e:
        return 127, "", str(e)
    return p.returncode, p.stdout, p.stderr


def py_python():
    for cand in (REPO / ".venv" / "bin" / "python", REPO / ".venv" / "Scripts" / "python.exe"):
        if cand.exists():
            return str(cand)
    return sys.executable


class Ctx:
    def __init__(self, a, work):
        self.a = a
        self.work = work
        self.src = work / "tcount.pruv"
        self.src.write_text(SOURCE)
        self.objs = {}  # (compiler, trust) -> (exe, error)
        self.rt_obj = None
        self.caller_obj = None

    def common(self):
        """(runtime 객체, C 호출자 객체, 오류)"""
        if self.rt_obj is None:
            rt = self.work / "rt_plain.o"
            rc, _, err = run([self.a.clang, "-O2", CPU_FLAG, "-std=c11", "-c", str(RUNTIME), "-o", str(rt)])
            if rc != 0:
                return None, None, "clang(runtime.c) 실패: " + err.strip()[-300:]
            cs = self.work / "caller.c"
            cs.write_text(CALLER)
            co = self.work / "caller.o"
            rc, _, err = run([self.a.clang, "-O2", "-c", str(cs), "-o", str(co)])
            if rc != 0:
                return None, None, "clang(caller.c) 실패: " + err.strip()[-300:]
            self.rt_obj, self.caller_obj = rt, co
        return self.rt_obj, self.caller_obj, None

    def exe(self, comp, trust):
        k = (comp, trust)
        if k in self.objs:
            return self.objs[k]
        tag = "%s_%s" % (comp, "trust" if trust else "plain")
        ll = self.work / (tag + ".ll")
        flags = ["--backend", "llvm", "-o", str(ll)] + (["--trust-callers"] if trust else [])
        if comp == "rs":
            argv = [self.a.pruvc, str(self.src), "--emit", "ll"] + flags
        else:  # pruvc.py has no --emit; `--backend llvm -o X.ll` writes the IR
            argv = [py_python(), self.a.py_pruvc, str(self.src)] + flags
        rc, out, err = run(argv)
        if rc != 0 or not ll.exists():
            self.objs[k] = (None, "pruvc(%s) 실패(%d): %s" % (comp, rc, (out + err).strip()[-300:]))
            return self.objs[k]
        rt, co, e = self.common()
        if e:
            self.objs[k] = (None, e)
            return self.objs[k]
        gen = self.work / (tag + "_gen.o")
        rc, _, err = run([self.a.clang, "-O2", CPU_FLAG, "-Wno-override-module", "-c", str(ll), "-o", str(gen)])
        if rc != 0:
            self.objs[k] = (None, "clang(.ll) 실패: " + err.strip()[-300:])
            return self.objs[k]
        exe = self.work / (tag + (".exe" if os.name == "nt" else ""))
        rc, _, err = run([self.a.clang, str(co), str(gen), str(rt), "-o", str(exe)])
        if rc != 0:
            self.objs[k] = (None, "링크 실패: " + err.strip()[-300:])
            return self.objs[k]
        self.objs[k] = (exe, None)
        return self.objs[k]


def run_case(ctx, comp, case):
    name, trust, data, want_exit, want_out, want_err, absent_err = case
    exe, err = ctx.exe(comp, trust)
    if err:
        return err
    rc, out, e = run([str(exe)] + [str(b) for b in data], timeout=60)
    if rc != want_exit:
        return "종료 코드 %d (기대 %d) stderr=%r" % (rc, want_exit, e.strip()[-200:])
    if want_out is not None and out.strip() != want_out:
        return "stdout %r (기대 %r)" % (out.strip(), want_out)
    if want_err is not None and want_err not in e:
        return "stderr %r 에 %r 가 없음" % (e.strip()[-200:], want_err)
    if absent_err is not None and absent_err in e:
        return "stderr %r 에 있으면 안 되는 %r 가 있음" % (e.strip()[-200:], absent_err)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pruvc", default=str(REPO / "pruvc-rs" / "target" / "release" / ("pruvc.exe" if os.name == "nt" else "pruvc")))
    ap.add_argument("--py-pruvc", default=str(REPO / "pruvc" / "pruvc.py"))
    ap.add_argument("--keep", default=None)
    a = ap.parse_args()
    a.clang = shutil.which("clang") or "/usr/bin/clang"

    missing = []
    if not Path(a.pruvc).exists():
        missing.append("pruvc(%s)" % a.pruvc)
    if not Path(a.py_pruvc).exists():
        missing.append("pruvc.py(%s)" % a.py_pruvc)
    if not (os.path.exists(a.clang) or shutil.which(a.clang)):
        missing.append("clang")
    if not RUNTIME.exists():
        missing.append(str(RUNTIME))
    if missing:
        print("필요한 도구/입력을 찾지 못함: " + ", ".join(missing))
        return 2

    if a.keep:
        work = Path(a.keep)
        work.mkdir(parents=True, exist_ok=True)
        cleanup = False
    else:
        work = Path(tempfile.mkdtemp(prefix="pruv_bool_repr_"))
        cleanup = True
    try:
        ctx = Ctx(a, work)
        total = ok = 0
        for comp in ("py", "rs"):
            for case in CASES:
                total += 1
                try:
                    why = run_case(ctx, comp, case)
                except Exception as e:  # 한 경우의 예외가 나머지를 가리지 않게
                    why = "예외: %r" % (e,)
                if why is None:
                    ok += 1
                    print("ok %s/%s" % (comp, case[0]))
                else:
                    print("FAIL %s/%s: %s" % (comp, case[0], why))
        print("%d/%d ok" % (ok, total))
        if a.keep:
            print("산출물: " + str(work))
        return 0 if ok == total else 1
    finally:
        if cleanup:
            shutil.rmtree(str(work), ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
