#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""런타임 v2 링크 시험 (docs/G2_A4_IMPL.md 6절; 표준 라이브러리만, Python 3.9).

사용: python3 tests/abi/check_runtime_v2.py [--pruvc PATH] [--keep DIR]
  --pruvc  기본 pruvc-rs/target/release/pruvc (저장소 루트 기준)
  --keep   산출물을 DIR 에 남김
호스트 대상에서 Rust 판 pruvc 로 .ll + 바인딩을 만들고, clang 으로 .ll·런타임을 객체화한 뒤
rustc 로 Rust 주 프로그램(`#[path=..] mod sol;`)과 링크한다. 6경우:
  ok_u8      g2a_u8_ret 새 바인딩 + 새 runtime.c(rust allocator, count)  링크·실행 성공
  ok_i64     arr_ret    새 바인딩 + 새 runtime.c(rust allocator)         링크·실행 성공
  old_rt_u8  g2a_u8_ret 새 바인딩 + runtime_v1.c(rust allocator)         링크 실패
  old_rt_i64 arr_ret    새 바인딩 + runtime_v1.c(rust allocator)         링크 실패(marker v2 없음)
  old_bind   arr_ret    바인딩에서 v2 helper 세 블록을 지운 것 + 새 runtime  링크 실패(helper v2 없음)
  malloc_rt  g2a_u8_ret 새 바인딩 + 새 runtime.c(malloc)                 링크 실패(marker 없음)
링크 실패 경우: rustc 종료 코드 != 0 이고 오류 글에 기대 심볼 이름(하나 이상)이 있어야 통과.
rustc 에 -C link-dead-code 를 줘서, 쓰이지 않는 함수가 gc 로 지워져 실패가 가려지는 일을 막는다.
경우마다 `ok <이름>` / `FAIL <이름>: 이유` 한 줄. 종료: 0 통과 / 1 실패 / 2 도구·입력 없음.
"""
import argparse
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
GEN = HERE / "gen"
RUNTIME_NEW = REPO / "pruvc" / "runtime.c"
RUNTIME_OLD = HERE / "runtime_v1.c"
CPU_FLAG = "-mcpu=native" if platform.machine().lower() in ("arm64", "aarch64") else "-march=native"
V2_HELPERS = ("pruv_host_alloc_v2", "pruv_host_alloc_zeroed_v2", "pruv_host_free_v2")

MAIN_U8 = 'fn main() {\n    let v = sol::bytes(&[1u8, 2, 200]);\n    println!("{:?}", v);\n}\n'
MAIN_I64 = 'fn main() {\n    let v = sol::arr(&[5i64, 6, 7]);\n    println!("{:?}", v);\n}\n'
OUT_U8 = "[1, 2, 200]"
OUT_I64 = "[5, 6, 7]"

# (이름, 소스 stem, 런타임 소스 키, rust allocator 인가, 바인딩 변형, 기대)
#   기대: None = 성공, 튜플 = 링크 실패 + 오류 글에 이 중 하나 이상
CASES = [
    ("ok_u8", "g2a_u8_ret", "new", True, "new", None),
    ("ok_i64", "arr_ret", "new", True, "new", None),
    ("old_rt_u8", "g2a_u8_ret", "old", True, "new", ("pruv_runtime_rust_allocator_v2",)),
    ("old_rt_i64", "arr_ret", "old", True, "new", ("pruv_runtime_rust_allocator_v2",)),
    ("old_bind", "arr_ret", "new", True, "old", V2_HELPERS),
    ("malloc_rt", "g2a_u8_ret", "new", False, "new", ("pruv_runtime_rust_allocator_v2",)),
]


def run(argv, timeout=600):
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as e:
        return 127, "", str(e)
    return p.returncode, p.stdout, p.stderr


def strip_v2_helpers(text):
    """새 바인딩에서 pruv_host_*_v2 세 블록(앞의 #[allow..]·#[no_mangle] 줄 포함)을 지운다. (텍스트, 지운 개수)."""
    removed = 0
    for name in V2_HELPERS:
        pat = re.compile(r'#\[allow\([^\n]*\)\]\n#\[no_mangle\]\npub extern "C" fn ' + name + r'\(.*?\n\}\n', re.S)
        text, n = pat.subn("", text, count=1)
        removed += n
    return text, removed


class Ctx:
    def __init__(self, a, work):
        self.a = a
        self.work = work
        self.gen = {}   # stem -> (ll, rs, gen_obj, error)
        self.rt = {}    # (키, rust allocator) -> (obj, error)

    def generated(self, stem):
        if stem not in self.gen:
            ll, rs, obj = (self.work / (stem + ext) for ext in (".ll", ".rs", "_gen.o"))
            rc, _, err = run([self.a.pruvc, str(GEN / (stem + ".pruv")), "--backend", "llvm", "--emit", "ll",
                              "-o", str(ll), "--rust-bindings", str(rs)])
            if rc != 0 or not ll.exists() or not rs.exists():
                self.gen[stem] = (None, None, None, "pruvc 실패(%d): %s" % (rc, err.strip()[-300:]))
            else:
                rc, _, err = run([self.a.clang, "-O2", CPU_FLAG, "-Wno-override-module", "-c", str(ll), "-o", str(obj)])
                if rc != 0:
                    self.gen[stem] = (None, None, None, "clang(.ll) 실패: " + err.strip()[-300:])
                else:
                    self.gen[stem] = (ll, rs, obj, None)
        return self.gen[stem]

    def runtime(self, key, rust_alloc):
        k = (key, rust_alloc)
        if k not in self.rt:
            src = RUNTIME_NEW if key == "new" else RUNTIME_OLD
            obj = self.work / ("rt_%s_%s.o" % (key, "rust" if rust_alloc else "malloc"))
            flags = ["-DPRUV_RUST_ALLOCATOR"] if rust_alloc else []
            if key == "new" and rust_alloc:
                flags.append("-DPRUV_COUNT_ALLOCS")
            rc, _, err = run([self.a.clang, "-O2", CPU_FLAG, "-std=c11"] + flags + ["-c", str(src), "-o", str(obj)])
            self.rt[k] = (obj, None) if rc == 0 else (None, "clang(%s) 실패: %s" % (src.name, err.strip()[-300:]))
        return self.rt[k]


def run_case(ctx, case):
    name, stem, rt_key, rust_alloc, bind, want_fail = case
    ll, rs, gen_obj, err = ctx.generated(stem)
    if err:
        return err
    rt_obj, err = ctx.runtime(rt_key, rust_alloc)
    if err:
        return err
    bindings = rs.read_text()
    if bind == "old":
        bindings, n = strip_v2_helpers(bindings)
        if n != len(V2_HELPERS):
            return "바인딩에서 v2 helper 블록을 %d/%d 개만 지움(바인딩 글자가 명세 4절과 다름)" % (n, len(V2_HELPERS))
    sol = ctx.work / (name + "_sol.rs")
    sol.write_text(bindings)
    main = ctx.work / (name + "_main.rs")
    body = MAIN_U8 if stem == "g2a_u8_ret" else MAIN_I64
    main.write_text('#![allow(dead_code, unused_imports)]\n#[path = "%s"] mod sol;\n%s' % (str(sol).replace("\\", "/"), body))
    exe = ctx.work / (name + ("_bin.exe" if os.name == "nt" else "_bin"))
    rc, _, err = run([ctx.a.rustc, "-O", "--edition", "2021", str(main), "-o", str(exe),
                      "-C", "link-dead-code", "-C", "link-arg=" + str(gen_obj), "-C", "link-arg=" + str(rt_obj)])
    if want_fail is not None:
        if rc == 0:
            return "링크가 성공했음(실패해야 함)"
        if not any(s in err for s in want_fail):
            return "링크는 실패했지만 오류 글에 %s 가 없음: %s" % (" / ".join(want_fail), err.strip()[-300:])
        return None
    if rc != 0:
        return "링크 실패: " + err.strip()[-300:]
    p = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
    want_out = OUT_U8 if stem == "g2a_u8_ret" else OUT_I64
    if p.returncode != 0:
        return "실행 종료 코드 %d: %s" % (p.returncode, p.stderr.strip()[-200:])
    if p.stdout.strip() != want_out:
        return "stdout %r != %r" % (p.stdout.strip(), want_out)
    if name == "ok_u8":
        # 반환 배열(1개)은 Rust Vec 이 놓으므로 runtime 의 해제 횟수에 안 잡힌다: 할당 = 해제 + 1.
        # g2a_u8_ret 은 중간 copy 하나를 런타임 안에서 놓으므로 해제 >= 1 (pruv_host_free_v2 경로)
        m = re.search(r"pruv-alloc-balance: (\d+) (\d+)", p.stderr)
        if not m:
            return "stderr 에 pruv-alloc-balance 줄이 없음: %r" % p.stderr[-150:]
        al, fr = int(m.group(1)), int(m.group(2))
        if fr < 1 or al != fr + 1:
            return "alloc balance %d allocs / %d frees (기대: frees >= 1, allocs == frees + 1)" % (al, fr)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pruvc", default=str(REPO / "pruvc-rs" / "target" / "release" / ("pruvc.exe" if os.name == "nt" else "pruvc")))
    ap.add_argument("--keep", default=None)
    a = ap.parse_args()
    a.clang = shutil.which("clang") or "/usr/bin/clang"
    a.rustc = shutil.which("rustc") or os.path.expanduser("~/.cargo/bin/rustc")

    missing = []
    if not Path(a.pruvc).exists():
        missing.append("pruvc(%s)" % a.pruvc)
    if not (os.path.exists(a.clang) or shutil.which(a.clang)):
        missing.append("clang")
    if not (os.path.exists(a.rustc) or shutil.which(a.rustc)):
        missing.append("rustc")
    for p in (RUNTIME_NEW, RUNTIME_OLD, GEN / "g2a_u8_ret.pruv", GEN / "arr_ret.pruv"):
        if not p.exists():
            missing.append(str(p))
    if missing:
        print("필요한 도구/입력을 찾지 못함: " + ", ".join(missing))
        return 2

    if a.keep:
        work = Path(a.keep)
        work.mkdir(parents=True, exist_ok=True)
        cleanup = False
    else:
        work = Path(tempfile.mkdtemp(prefix="pruv_rt_v2_"))
        cleanup = True
    try:
        ctx = Ctx(a, work)
        bad = 0
        for case in CASES:
            try:
                why = run_case(ctx, case)
            except Exception as e:  # 한 경우의 예외가 나머지를 가리지 않게
                why = "예외: %r" % (e,)
            if why is None:
                print("ok " + case[0])
            else:
                bad += 1
                print("FAIL %s: %s" % (case[0], why))
        if a.keep:
            print("산출물: " + str(work))
        return 1 if bad else 0
    finally:
        if cleanup:
            shutil.rmtree(str(work), ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
