#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Runtime v2 link test (docs/G2_A4_IMPL.md section 6; standard library only, Python 3.9).

Usage: python3 tests/abi/check_runtime_v2.py [--pruvc PATH] [--keep DIR]
  --pruvc  default pruvc-rs/target/release/pruvc (relative to the repository root)
  --keep   keep the artifacts in DIR
On the host target, builds .ll + bindings with the Rust implementation of pruvc, compiles the .ll and runtime to objects with clang, then
links them with a Rust main program (`#[path=..] mod sol;`) using rustc. 6 cases:
  ok_u8      g2a_u8_ret new bindings + new runtime.c (rust allocator, count)  link and run succeed
  ok_i64     arr_ret    new bindings + new runtime.c (rust allocator)         link and run succeed
  old_rt_u8  g2a_u8_ret new bindings + runtime_v1.c (rust allocator)          link fails
  old_rt_i64 arr_ret    new bindings + runtime_v1.c (rust allocator)          link fails (no marker v2)
  old_bind   arr_ret    bindings with the three v2 helper blocks removed + new runtime  link fails (no helper v2)
  malloc_rt  g2a_u8_ret new bindings + new runtime.c (malloc)                 link fails (no marker)
Link-failure cases pass only if the rustc exit code != 0 and the error text contains an expected symbol name (at least one).
Passes -C link-dead-code to rustc so unused functions are not removed by gc, which would mask the failure.
For each case, one line `ok <name>` / `FAIL <name>: reason`. Exit: 0 pass / 1 fail / 2 tool or input missing.
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

# (name, source stem, runtime source key, is rust allocator, bindings variant, expectation)
#   expectation: None = success, tuple = link failure + the error text contains at least one of these
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
    """Remove the three pruv_host_*_v2 blocks (including the preceding #[allow..] and #[no_mangle] lines) from the new bindings. Returns (text, number removed)."""
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
        self.rt = {}    # (key, rust allocator) -> (obj, error)

    def generated(self, stem):
        if stem not in self.gen:
            ll, rs, obj = (self.work / (stem + ext) for ext in (".ll", ".rs", "_gen.o"))
            rc, _, err = run([self.a.pruvc, str(GEN / (stem + ".pruv")), "--backend", "llvm", "--emit", "ll",
                              "-o", str(ll), "--rust-bindings", str(rs)])
            if rc != 0 or not ll.exists() or not rs.exists():
                self.gen[stem] = (None, None, None, "pruvc failed (%d): %s" % (rc, err.strip()[-300:]))
            else:
                rc, _, err = run([self.a.clang, "-O2", CPU_FLAG, "-Wno-override-module", "-c", str(ll), "-o", str(obj)])
                if rc != 0:
                    self.gen[stem] = (None, None, None, "clang(.ll) failed: " + err.strip()[-300:])
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
            self.rt[k] = (obj, None) if rc == 0 else (None, "clang(%s) failed: %s" % (src.name, err.strip()[-300:]))
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
            return "removed only %d/%d v2 helper blocks from the bindings (binding text differs from spec section 4)" % (n, len(V2_HELPERS))
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
            return "link succeeded (it must fail)"
        if not any(s in err for s in want_fail):
            return "link failed but the error text does not contain %s: %s" % (" / ".join(want_fail), err.strip()[-300:])
        return None
    if rc != 0:
        return "link failed: " + err.strip()[-300:]
    p = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
    want_out = OUT_U8 if stem == "g2a_u8_ret" else OUT_I64
    if p.returncode != 0:
        return "run exit code %d: %s" % (p.returncode, p.stderr.strip()[-200:])
    if p.stdout.strip() != want_out:
        return "stdout %r != %r" % (p.stdout.strip(), want_out)
    if name == "ok_u8":
        # The returned array (one) is released by the Rust Vec, so it is not counted in the runtime's free count: allocs = frees + 1.
        # g2a_u8_ret releases one intermediate copy inside the runtime, so frees >= 1 (pruv_host_free_v2 path)
        m = re.search(r"pruv-alloc-balance: (\d+) (\d+)", p.stderr)
        if not m:
            return "no pruv-alloc-balance line in stderr: %r" % p.stderr[-150:]
        al, fr = int(m.group(1)), int(m.group(2))
        if fr < 1 or al != fr + 1:
            return "alloc balance %d allocs / %d frees (expected: frees >= 1, allocs == frees + 1)" % (al, fr)
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
        print("required tools/inputs not found: " + ", ".join(missing))
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
            except Exception as e:  # so one case's exception does not hide the rest
                why = "exception: %r" % (e,)
            if why is None:
                print("ok " + case[0])
            else:
                bad += 1
                print("FAIL %s: %s" % (case[0], why))
        if a.keep:
            print("artifacts: " + str(work))
        return 1 if bad else 0
    finally:
        if cleanup:
            shutil.rmtree(str(work), ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
