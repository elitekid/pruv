#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""str raw ABI 표현(UTF-8) 검사 시험 (docs/G2_B2_IMPL.md 0절 결정 5·4절·5.3절; 표준 라이브러리만, Python 3.9).

사용: python3 tests/abi/check_utf8_repr.py [--pruvc PATH] [--py-pruvc PATH] [--keep DIR]
  --pruvc     Rust 판 pruvc (기본 pruvc-rs/target/release/pruvc)
  --py-pruvc  Python 판 pruvc.py (기본 pruvc/pruvc.py, 파이썬은 .venv 가 있으면 그것)
  --keep      산출물을 DIR 에 남김
두 컴파일러(py·rs)가 같은 str 인자 함수에서 낸 .ll 을 일반 런타임(pruvc/runtime.c, RUST_ALLOCATOR 아님)과
C 호출자에 링크해 `pruv_abi_tlen(const uint8_t *, int64_t)` 를 직접 부른다. 호출자는 argv 의 16진 바이트를
버퍼에 채운다(쓰기 어려운 바이트도 16진 글자로만 다룬다). 소스: len(s) >= 1 && s[0] != 120 (120 = 'x').
경우(컴파일러마다, 기본 빌드와 --trust-callers 빌드):
  ok_a, ok_nul, ok_2byte, ok_4byte   유효 61 / 61 00 62 (NUL 안 잘림: 3) / C3 A9 / F0 9F 98 80 → 종료 0
  bad_cont      61 80        → 101, `invalid representation: 1 (str UTF-8, byte offset)`
  bad_trunc     E3 81        → K=0   bad_overlong2 C0 AF → K=0   bad_overlong3 E0 80 AF → K=0
  bad_surrogate ED A0 80     → K=0   bad_range F4 90 80 80 → K=0   bad_lead F5 80 80 80 → K=0
  ok_c2_80 ok_e0_a0_80 ok_ed_9f_bf ok_ef_bf_bf ok_f0_90_80_80 ok_f4_8f_bf_bf  Table 3-7 경계의 유효 끝값
  bad_c1 61 C1 BF → K=1   bad_f0_8f F0 8F BF BF → K=0   bad_third E3 81 41 → K=0
  bad_trunc4 61 62 F0 9F 98 → K=2   bad_fourth F0 9F 98 41 → K=0
  repr_first    78 FF        → 표현 오류가 먼저(K=1, `requires violated` 없음)
  neg_len       길이 -1      → 101, `invalid representation: -1 (str length)`(감사 뒤 추가)
  null_data     (NULL, 1)    → 101, `invalid representation: 1 (str NULL data)`
  trust_*       같은 경우를 --trust-callers 빌드로(표현 검사는 trust 와 무관)
  requires_x    78 (표현은 정상, requires 거짓) → 101, `requires violated`; empty_req(바이트 없음) 도 같다
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
REPR_MSG = "pruv: invalid representation: %d (str UTF-8, byte offset)"

SOURCE = """// str raw ABI 표현 검사용: 길이를 돌려준다 (requires 가 str 바이트를 읽는다)
fn tlen(s: str) -> i64
  requires len(s) >= 1 && s[0] != 120
{
  return len(s);
}
"""

CALLER = """#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
extern int64_t pruv_abi_tlen(const uint8_t *a, int64_t n);
int main(int argc, char **argv) {
    uint8_t buf[32];
    if (argc == 2 && argv[1][0] == 'n' && argv[1][1] == 'e') { /* "neg": negative length */
        printf("%lld\\n", (long long)pruv_abi_tlen(buf, -1));
        return 0;
    }
    if (argc == 2 && argv[1][0] == 'n' && argv[1][1] == 'u') { /* "null": NULL data with length 1 */
        printf("%lld\\n", (long long)pruv_abi_tlen(NULL, 1));
        return 0;
    }
    int n = argc - 1;
    if (n > 32) n = 32;
    for (int k = 0; k < n; k++) buf[k] = (uint8_t)strtol(argv[k + 1], NULL, 16);
    printf("%lld\\n", (long long)pruv_abi_tlen(buf, (int64_t)n));
    return 0;
}
"""

# (이름, 바이트 16진 인자, 기대 종료, 기대 stdout(None=검사 안 함), stderr 에 있어야 할 글, stderr 에 없어야 할 글)
VALID = [
    ("ok_a", ["61"], "1"),
    ("ok_nul", ["61", "00", "62"], "3"),
    ("ok_2byte", ["C3", "A9"], "2"),
    ("ok_4byte", ["F0", "9F", "98", "80"], "4"),
    ("ok_c2_80", ["C2", "80"], "2"),
    ("ok_e0_a0_80", ["E0", "A0", "80"], "3"),
    ("ok_ed_9f_bf", ["ED", "9F", "BF"], "3"),
    ("ok_ef_bf_bf", ["EF", "BF", "BF"], "3"),
    ("ok_f0_90_80_80", ["F0", "90", "80", "80"], "4"),
    ("ok_f4_8f_bf_bf", ["F4", "8F", "BF", "BF"], "4"),
]
BAD = [
    ("bad_cont", ["61", "80"], 1),
    ("bad_trunc", ["E3", "81"], 0),
    ("bad_overlong2", ["C0", "AF"], 0),
    ("bad_overlong3", ["E0", "80", "AF"], 0),
    ("bad_surrogate", ["ED", "A0", "80"], 0),
    ("bad_range", ["F4", "90", "80", "80"], 0),
    ("bad_lead", ["F5", "80", "80", "80"], 0),
    ("bad_c1", ["61", "C1", "BF"], 1),
    ("bad_f0_8f", ["F0", "8F", "BF", "BF"], 0),
    ("bad_third", ["E3", "81", "41"], 0),
    ("bad_trunc4", ["61", "62", "F0", "9F", "98"], 2),
    ("bad_fourth", ["F0", "9F", "98", "41"], 0),
]

# (이름, trust 빌드인가, 바이트 16진 인자, 기대 종료, 기대 stdout, stderr 에 있어야 할 글, stderr 에 없어야 할 글)
CASES = []
for trust in (False, True):
    pre = "trust_" if trust else ""
    for name, data, out in VALID:
        CASES.append((pre + name, trust, data, 0, out, None, None))
    for name, data, k in BAD:
        CASES.append((pre + name, trust, data, 101, "", REPR_MSG % k, None))
    CASES.append((pre + "repr_first", trust, ["78", "FF"], 101, "", REPR_MSG % 1, "requires violated"))
    CASES.append((pre + "neg_len", trust, ["neg"], 101, "", "pruv: invalid representation: -1 (str length)",
                  "requires violated"))
    CASES.append((pre + "null_data", trust, ["null"], 101, "", "pruv: invalid representation: 1 (str NULL data)",
                  "requires violated"))
CASES.append(("requires_x", False, ["78"], 101, "", "requires violated", "invalid representation"))
CASES.append(("empty_req", False, [], 101, "", "requires violated", "invalid representation"))


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
        self.src = work / "tlen.pruv"
        self.src.write_text(SOURCE, encoding="utf-8")
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
    rc, out, e = run([str(exe)] + list(data), timeout=60)
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
        work = Path(tempfile.mkdtemp(prefix="pruv_utf8_repr_"))
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
