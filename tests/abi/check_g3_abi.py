#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""G3 A4 host execution check of the generic-value ABI (docs/G3_SPEC.md 5.4, 5.5, 7.6; standard library only, Python 3.9).

Usage: python3 tests/abi/check_g3_abi.py [--py-pruvc PATH] [--with-rs] [--pruvc PATH] [--keep DIR]
  --py-pruvc  Python implementation pruvc.py (default pruvc/pruvc.py; uses the .venv Python if present)
  --with-rs   also run the Rust implementation (--pruvc, default pruvc-rs/target/release/pruvc)
  --keep      keep the artifacts in DIR
Links the .ll of one program with the counting runtime (pruvc/runtime.c -DPRUV_COUNT_ALLOCS) and a C caller that
calls the raw pruv_abi_* wrappers with word arrays. This is HOST execution only; Windows execution is a separate
CI report and cross-compilation is not recorded as Windows execution.

Case groups (every case once per compiler):
  tag / inactive words   Option<bool> and Result<bool>: tags normalize by nonzero-to-true, inactive words are
                         read as zero and written as zero (an outgoing word array is pre-filled with garbage)
  active-payload ==      `requires a == b` ignores the inactive payload and the inactive error word
  invalid enum ordinals  a generic enum instance (also nested in Option) is rejected before requires/body, with and
                         without --trust-callers; an inactive Option payload is not checked
  nested values          Pair<Option<bool>, Result<i64>> round trip
  legacy                 Option<i64> keeps the two-register form
  allocation balance     generic [T] copies, reassignment and early return free everything they allocate
Each case prints `ok <compiler>/<name>` / `FAIL <compiler>/<name>: reason`, then `N/N ok`.
Exit: 0 all pass / 1 some fail / 2 tool or input missing.
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
RUNTIME = REPO / "pruvc" / "runtime.c"
CPU_FLAG = "-mcpu=native" if platform.machine().lower() in ("arm64", "aarch64") else "-march=native"
BOOL_MSG = "invalid representation: 2 (bool 0..=1)"

SOURCE = """// G3 A4 ABI execution program (tests/abi/check_g3_abi.py)
struct Pair<A, B> {
  first: A,
  second: B,
}

enum Choice<A, B> {
  Left(value: A),
  Right(value: B),
}

fn same<T>(a: T, b: T) -> T
  requires a == b
{
  return a;
}

fn same_opt(a: Option<bool>, b: Option<bool>) -> Option<bool>
  requires a == b
{
  return same::<Option<bool>>(a, b);
}

fn same_res(a: Result<bool>, b: Result<bool>) -> Result<bool>
  requires a == b
{
  return same::<Result<bool>>(a, b);
}

fn opt_bool(x: Option<bool>) -> Option<bool>
{
  return x;
}

fn res_bool(r: Result<bool>) -> Result<bool>
{
  return r;
}

fn nest_id(p: Pair<Option<bool>, Result<i64>>) -> Pair<Option<bool>, Result<i64>>
{
  return p;
}

fn left_bool(c: Choice<bool, i64>) -> bool
  requires is_variant(c, Choice::Left)
{
  match c {
    Choice::Left(x) => { return x; }
    Choice::Right(y) => { return false; }
  }
}

fn is_left(c: Choice<bool, i64>) -> bool
{
  match c {
    Choice::Left(x) => { return true; }
    Choice::Right(y) => { return false; }
  }
}

fn opt_is_left(o: Option<Choice<bool, i64>>) -> bool
{
  match o {
    Some(c) => { return is_left(c); }
    None => { return false; }
  }
}

fn legacy_opt(o: Option<i64>) -> Option<i64>
{
  return o;
}

fn dup<T: Element>(a: [T]) -> [T] ! alloc
  requires len(a) <= 100
  ensures len(result) == len(a)
{
  let mut c: [T] = copy(a);
  c = copy(a);
  return c;
}

fn pick<T: Element>(a: [T], early: bool) -> [T] ! alloc
  requires len(a) <= 100
  ensures len(result) == len(a)
{
  let t: [T] = copy(a);
  if early {
    let e: [T] = copy(a);
    return e;
  }
  return t;
}

fn dup_bool(a: [bool]) -> [bool] ! alloc
  requires len(a) <= 100
  ensures len(result) == len(a)
{
  let r: [bool] = dup::<bool>(a);
  return r;
}

fn dup_int(a: [i64]) -> [i64] ! alloc
  requires len(a) <= 100
  ensures len(result) == len(a)
{
  let r: [i64] = dup::<i64>(a);
  return r;
}

fn pick_bool(a: [bool], early: bool) -> [bool] ! alloc
  requires len(a) <= 100
  ensures len(result) == len(a)
{
  let r: [bool] = pick::<bool>(a, early);
  return r;
}
"""

CALLER = """#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef struct { int64_t tag, value; } Tagged;
typedef struct { uint8_t *data; int64_t len; } ArrU8;
typedef struct { int64_t *data; int64_t len; } ArrI64;
extern void pruv_abi_opt_bool(const int64_t *, int64_t *);
extern void pruv_abi_res_bool(const int64_t *, int64_t *);
extern void pruv_abi_same_opt(const int64_t *, const int64_t *, int64_t *);
extern void pruv_abi_same_res(const int64_t *, const int64_t *, int64_t *);
extern void pruv_abi_nest_id(const int64_t *, int64_t *);
extern int64_t pruv_abi_left_bool(const int64_t *);
extern int64_t pruv_abi_opt_is_left(const int64_t *);
extern Tagged pruv_abi_legacy_opt(int64_t, int64_t);
extern void pruv_abi_dup_bool(const uint8_t *, int64_t, ArrU8 *);
extern void pruv_abi_dup_int(const int64_t *, int64_t, ArrI64 *);
extern void pruv_abi_pick_bool(const uint8_t *, int64_t, int64_t, ArrU8 *);
extern void pruv_free_v2(void *, int64_t, int64_t, int64_t);
extern void pruv_free(int64_t *, int64_t);
#define IS(n) (strcmp(fn, n) == 0)
/* argv: fn  na a-words...  nb b-words...  nout */
int main(int argc, char **argv) {
    const char *fn = argv[1];
    int64_t a[16], b[16], out[16];
    int k = 2, na, nb, nout;
    for (int i = 0; i < 16; i++) { a[i] = 0; b[i] = 0; out[i] = 0x5a5a5a5a; }
    na = atoi(argv[k++]);
    for (int i = 0; i < na; i++) a[i] = atoll(argv[k++]);
    nb = atoi(argv[k++]);
    for (int i = 0; i < nb; i++) b[i] = atoll(argv[k++]);
    nout = atoi(argv[k++]);
    if (IS("opt_bool")) pruv_abi_opt_bool(a, out);
    else if (IS("res_bool")) pruv_abi_res_bool(a, out);
    else if (IS("same_opt")) pruv_abi_same_opt(a, b, out);
    else if (IS("same_res")) pruv_abi_same_res(a, b, out);
    else if (IS("nest_id")) pruv_abi_nest_id(a, out);
    else if (IS("left_bool")) { printf("%lld\\n", (long long)pruv_abi_left_bool(a)); return 0; }
    else if (IS("opt_is_left")) { printf("%lld\\n", (long long)pruv_abi_opt_is_left(a)); return 0; }
    else if (IS("legacy_opt")) {
        Tagged t = pruv_abi_legacy_opt(a[0], a[1]);
        printf("%lld %lld\\n", (long long)t.tag, (long long)t.value);
        return 0;
    }
    else if (IS("dup_bool") || IS("pick_bool")) {
        uint8_t buf[16];
        for (int i = 0; i < na; i++) buf[i] = (uint8_t)a[i];
        ArrU8 r = { 0, 0 };
        if (IS("dup_bool")) pruv_abi_dup_bool(buf, na, &r);
        else pruv_abi_pick_bool(buf, na, b[0], &r);
        printf("%lld", (long long)r.len);
        for (int64_t i = 0; i < r.len; i++) printf(" %d", (int)r.data[i]);
        printf("\\n");
        if (r.len > 0) pruv_free_v2(r.data, r.len, 1, 1);
        return 0;
    }
    else if (IS("dup_int")) {
        ArrI64 r = { 0, 0 };
        pruv_abi_dup_int(a, na, &r);
        printf("%lld", (long long)r.len);
        for (int64_t i = 0; i < r.len; i++) printf(" %lld", (long long)r.data[i]);
        printf("\\n");
        if (r.len > 0) pruv_free(r.data, r.len);
        return 0;
    }
    else return 64;
    for (int i = 0; i < nout; i++) printf(i ? " %lld" : "%lld", (long long)out[i]);
    printf("\\n");
    return 0;
}
"""


class Case:
    def __init__(self, name, fn, a=(), b=(), nout=0, exit=0, out=None, err=None, err_absent=None, trust=False,
                 balance=False):
        self.name, self.fn, self.a, self.b, self.nout = name, fn, list(a), list(b), nout
        self.exit, self.out, self.err, self.err_absent = exit, out, err, err_absent
        self.trust, self.balance = trust, balance

    def argv(self):
        return ([self.fn, str(len(self.a))] + [str(x) for x in self.a] + [str(len(self.b))] +
                [str(x) for x in self.b] + [str(self.nout)])


CASES = [
    # tags and inactive words (Option<bool> = 2 words, Result<bool> = 3 words: tag, ok payload, error word)
    Case("opt_some", "opt_bool", [1, 1], nout=2, out="1 1"),
    Case("opt_none_dirty_payload", "opt_bool", [0, 7], nout=2, out="0 0"),
    Case("opt_tag_nonzero_is_some", "opt_bool", [5, 9], nout=2, out="1 1"),
    Case("res_err_dirty_ok_word", "res_bool", [0, 7, 42], nout=3, out="0 0 42"),
    Case("res_ok_dirty_error_word", "res_bool", [1, 0, 99], nout=3, out="1 0 0"),
    Case("res_tags_normalize", "res_bool", [3, 8, 5], nout=3, out="1 1 0"),
    # equality in requires looks only at the active payload
    Case("eq_none_dirty_payload", "same_opt", [0, 0], [0, 1], nout=2, out="0 0"),
    Case("eq_some_differs", "same_opt", [1, 1], [1, 0], exit=101, err="requires violated"),
    Case("eq_err_dirty_ok_word", "same_res", [0, 1, 5], [0, 0, 5], nout=3, out="0 0 5"),
    Case("eq_ok_vs_err", "same_res", [1, 1, 0], [0, 1, 0], exit=101, err="requires violated"),
    Case("eq_err_code_differs", "same_res", [0, 0, 5], [0, 0, 6], exit=101, err="requires violated"),
    # invalid generic enum ordinals are rejected before requires / body; Choice<bool, i64> = 3 words
    Case("enum_ok", "left_bool", [0, 1, 0], out="1"),
    Case("enum_inactive_variant_word_ignored", "left_bool", [0, 1, 123], out="1"),
    Case("enum_bad_ordinal", "left_bool", [7, 1, 0], exit=101, err="invalid representation: 7",
         err_absent="requires violated"),
    Case("enum_bad_ordinal_trust", "left_bool", [7, 1, 0], exit=101, err="invalid representation: 7", trust=True),
    Case("enum_valid_requires_fails", "left_bool", [1, 1, 0], exit=101, err="requires violated",
         err_absent="invalid representation"),
    Case("enum_nested_bad_ordinal", "opt_is_left", [1, 9, 0, 0], exit=101, err="invalid representation: 9"),
    Case("enum_nested_inactive_not_checked", "opt_is_left", [0, 9, 0, 0], out="0"),
    Case("enum_nested_some_left", "opt_is_left", [1, 0, 1, 0], out="1"),
    # nested values: Pair<Option<bool>, Result<i64>> = 4 words
    Case("nest_round_trip", "nest_id", [1, 1, 0, 5], nout=4, out="1 1 0 5"),
    Case("nest_inactive_payload_zeroed", "nest_id", [0, 1, 1, 7], nout=4, out="0 0 1 7"),
    # legacy Option<i64>: two argument words, { i64, i64 } by value
    Case("legacy_some", "legacy_opt", [1, 9], out="1 9"),
    Case("legacy_none", "legacy_opt", [0, 3], out="0 3"),
    # existing G2 [bool] entry check keeps running under --trust-callers
    Case("bool_array_bad_byte_trust", "dup_bool", [1, 2, 1], exit=101, err=BOOL_MSG, trust=True),
    # allocation / free balance of generic array code (copy, reassignment, early return)
    Case("alloc_dup_bool", "dup_bool", [1, 0, 1], out="3 1 0 1", balance=True),
    Case("alloc_dup_int", "dup_int", [4, 5], out="2 4 5", balance=True),
    Case("alloc_pick_early", "pick_bool", [1, 1], [1], out="2 1 1", balance=True),
    Case("alloc_pick_late", "pick_bool", [1, 0], [0], out="2 1 0", balance=True),
    Case("alloc_empty", "dup_bool", [], out="0", balance=True),
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
        self.a, self.work = a, work
        self.src = work / "g3_exec.pruv"
        self.src.write_text(SOURCE)
        self.exes = {}
        self.rt_obj = self.caller_obj = None

    def common(self):
        if self.rt_obj is None:
            rt = self.work / "rt_count.o"
            rc, _, err = run([self.a.clang, "-O2", CPU_FLAG, "-std=c11", "-DPRUV_COUNT_ALLOCS", "-c", str(RUNTIME),
                              "-o", str(rt)])
            if rc != 0:
                return None, None, "clang(runtime.c) failed: " + err.strip()[-300:]
            cs = self.work / "caller.c"
            cs.write_text(CALLER)
            co = self.work / "caller.o"
            rc, _, err = run([self.a.clang, "-O2", "-c", str(cs), "-o", str(co)])
            if rc != 0:
                return None, None, "clang(caller.c) failed: " + err.strip()[-300:]
            self.rt_obj, self.caller_obj = rt, co
        return self.rt_obj, self.caller_obj, None

    def exe(self, comp, trust):
        k = (comp, trust)
        if k in self.exes:
            return self.exes[k]
        tag = "%s_%s" % (comp, "trust" if trust else "plain")
        ll = self.work / (tag + ".ll")
        flags = ["--backend", "llvm", "-o", str(ll)] + (["--trust-callers"] if trust else [])
        if comp == "rs":
            argv = [self.a.pruvc, str(self.src), "--emit", "ll"] + flags
        else:
            argv = [py_python(), self.a.py_pruvc, str(self.src)] + flags
        rc, out, err = run(argv)
        if rc != 0 or not ll.exists():
            self.exes[k] = (None, "pruvc(%s) failed (%d): %s" % (comp, rc, (out + err).strip()[-400:]))
            return self.exes[k]
        rt, co, e = self.common()
        if e:
            self.exes[k] = (None, e)
            return self.exes[k]
        gen = self.work / (tag + "_gen.o")
        rc, _, err = run([self.a.clang, "-O2", CPU_FLAG, "-Wno-override-module", "-c", str(ll), "-o", str(gen)])
        if rc != 0:
            self.exes[k] = (None, "clang(.ll) failed: " + err.strip()[-300:])
            return self.exes[k]
        exe = self.work / (tag + (".exe" if os.name == "nt" else ""))
        rc, _, err = run([self.a.clang, str(co), str(gen), str(rt), "-o", str(exe)])
        if rc != 0:
            self.exes[k] = (None, "link failed: " + err.strip()[-300:])
            return self.exes[k]
        self.exes[k] = (exe, None)
        return self.exes[k]


def run_case(ctx, comp, c):
    exe, err = ctx.exe(comp, c.trust)
    if err:
        return err
    rc, out, e = run([str(exe)] + c.argv(), timeout=60)
    if rc != c.exit:
        return "exit code %d (expected %d) stderr=%r" % (rc, c.exit, e.strip()[-200:])
    if c.out is not None and out.strip() != c.out:
        return "stdout %r (expected %r)" % (out.strip(), c.out)
    if c.err is not None and c.err not in e:
        return "stderr %r does not contain %r" % (e.strip()[-200:], c.err)
    if c.err_absent is not None and c.err_absent in e:
        return "stderr %r contains %r, which must be absent" % (e.strip()[-200:], c.err_absent)
    if c.balance:
        m = re.search(r"pruv-alloc-balance: (\d+) (\d+)", e)
        if not m:
            return "no pruv-alloc-balance line in stderr %r" % e.strip()[-200:]
        if m.group(1) != m.group(2):
            return "alloc balance %s allocs / %s frees" % (m.group(1), m.group(2))
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pruvc", default=str(REPO / "pruvc-rs" / "target" / "release" /
                                           ("pruvc.exe" if os.name == "nt" else "pruvc")))
    ap.add_argument("--py-pruvc", default=str(REPO / "pruvc" / "pruvc.py"))
    ap.add_argument("--with-rs", action="store_true")
    ap.add_argument("--keep", default=None)
    a = ap.parse_args()
    a.clang = shutil.which("clang") or "/usr/bin/clang"

    missing = []
    if a.with_rs and not Path(a.pruvc).exists():
        missing.append("pruvc(%s)" % a.pruvc)
    if not Path(a.py_pruvc).exists():
        missing.append("pruvc.py(%s)" % a.py_pruvc)
    if not (os.path.exists(a.clang) or shutil.which(a.clang)):
        missing.append("clang")
    if not RUNTIME.exists():
        missing.append(str(RUNTIME))
    if missing:
        print("required tools/inputs not found: " + ", ".join(missing))
        return 2

    if a.keep:
        work = Path(a.keep)
        work.mkdir(parents=True, exist_ok=True)
        cleanup = False
    else:
        work = Path(tempfile.mkdtemp(prefix="pruv_g3_abi_"))
        cleanup = True
    try:
        ctx = Ctx(a, work)
        total = ok = 0
        for comp in ("py", "rs") if a.with_rs else ("py",):
            for case in CASES:
                total += 1
                try:
                    why = run_case(ctx, comp, case)
                except Exception as e:  # one case's exception must not hide the rest
                    why = "exception: %r" % (e,)
                if why is None:
                    ok += 1
                    print("ok %s/%s" % (comp, case.name))
                else:
                    print("FAIL %s/%s: %s" % (comp, case.name, why))
        print("%d/%d ok" % (ok, total))
        print("host execution only: Windows CI execution is reported separately")
        if a.keep:
            print("artifacts: " + str(work))
        return 0 if ok == total else 1
    finally:
        if cleanup:
            shutil.rmtree(str(work), ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
