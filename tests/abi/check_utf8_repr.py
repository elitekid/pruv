#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""str raw ABI representation (UTF-8) check test (docs/G2_B2_IMPL.md section 0 decision 5, sections 4 and 5.3; standard library only, Python 3.9).

Usage: python3 tests/abi/check_utf8_repr.py [--pruvc PATH] [--py-pruvc PATH] [--keep DIR]
  --pruvc     Rust implementation of pruvc (default pruvc-rs/target/release/pruvc)
  --py-pruvc  Python implementation pruvc.py (default pruvc/pruvc.py; uses the .venv Python if present)
  --keep      keep the artifacts in DIR
Links the .ll that both compilers (py, rs) emit for the same str-argument function with the plain runtime
(pruvc/runtime.c, not RUST_ALLOCATOR) and a C caller, and calls `pruv_abi_tlen(const uint8_t *, int64_t)` directly. The caller fills
the buffer from hex bytes in argv (even hard-to-type bytes are handled only as hex characters). Source: len(s) >= 1 && s[0] != 120 (120 = 'x').
Cases (per compiler, for the default build and the --trust-callers build):
  ok_a, ok_nul, ok_2byte, ok_4byte   valid: 61 / 61 00 62 (NUL does not truncate: 3) / C3 A9 / F0 9F 98 80 -> exit 0
  bad_cont      61 80        -> 101, `invalid representation: 1 (str UTF-8, byte offset)`
  bad_trunc     E3 81        -> K=0   bad_overlong2 C0 AF -> K=0   bad_overlong3 E0 80 AF -> K=0
  bad_surrogate ED A0 80     -> K=0   bad_range F4 90 80 80 -> K=0   bad_lead F5 80 80 80 -> K=0
  ok_c2_80 ok_e0_a0_80 ok_ed_9f_bf ok_ef_bf_bf ok_f0_90_80_80 ok_f4_8f_bf_bf  valid end values at the Table 3-7 boundaries
  bad_c1 61 C1 BF -> K=1   bad_f0_8f F0 8F BF BF -> K=0   bad_third E3 81 41 -> K=0
  bad_trunc4 61 62 F0 9F 98 -> K=2   bad_fourth F0 9F 98 41 -> K=0
  repr_first    78 FF        -> the representation error comes first (K=1, no `requires violated`)
  neg_len       length -1    -> 101, `invalid representation: -1 (str length)` (added after the audit)
  null_data     (NULL, 1)    -> 101, `invalid representation: 1 (str NULL data)`
  trust_*       the same cases with a --trust-callers build (the representation check is independent of trust)
  requires_x    78 (representation is valid, requires is false) -> 101, `requires violated`; empty_req (no bytes) is the same
For each case, one line `ok <compiler>/<name>` / `FAIL <compiler>/<name>: reason`, and `N/N ok` at the end.
Exit: 0 all pass / 1 some fail / 2 tool or input missing.
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

SOURCE = """// For the str raw ABI representation check: returns the length (requires reads a str byte)
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

# (name, hex byte args, expected exit, expected stdout (None = not checked), text that must be in stderr, text that must not be in stderr)
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

# (name, is a trust build, hex byte args, expected exit, expected stdout, text that must be in stderr, text that must not be in stderr)
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
        """(runtime object, C caller object, error)"""
        if self.rt_obj is None:
            rt = self.work / "rt_plain.o"
            rc, _, err = run([self.a.clang, "-O2", CPU_FLAG, "-std=c11", "-c", str(RUNTIME), "-o", str(rt)])
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
            self.objs[k] = (None, "pruvc(%s) failed (%d): %s" % (comp, rc, (out + err).strip()[-300:]))
            return self.objs[k]
        rt, co, e = self.common()
        if e:
            self.objs[k] = (None, e)
            return self.objs[k]
        gen = self.work / (tag + "_gen.o")
        rc, _, err = run([self.a.clang, "-O2", CPU_FLAG, "-Wno-override-module", "-c", str(ll), "-o", str(gen)])
        if rc != 0:
            self.objs[k] = (None, "clang(.ll) failed: " + err.strip()[-300:])
            return self.objs[k]
        exe = self.work / (tag + (".exe" if os.name == "nt" else ""))
        rc, _, err = run([self.a.clang, str(co), str(gen), str(rt), "-o", str(exe)])
        if rc != 0:
            self.objs[k] = (None, "link failed: " + err.strip()[-300:])
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
        return "exit code %d (expected %d) stderr=%r" % (rc, want_exit, e.strip()[-200:])
    if want_out is not None and out.strip() != want_out:
        return "stdout %r (expected %r)" % (out.strip(), want_out)
    if want_err is not None and want_err not in e:
        return "stderr %r does not contain %r" % (e.strip()[-200:], want_err)
    if absent_err is not None and absent_err in e:
        return "stderr %r contains %r, which must be absent" % (e.strip()[-200:], absent_err)
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
        print("required tools/inputs not found: " + ", ".join(missing))
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
                except Exception as e:  # so one case's exception does not hide the rest
                    why = "exception: %r" % (e,)
                if why is None:
                    ok += 1
                    print("ok %s/%s" % (comp, case[0]))
                else:
                    print("FAIL %s/%s: %s" % (comp, case[0], why))
        print("%d/%d ok" % (ok, total))
        if a.keep:
            print("artifacts: " + str(work))
        return 0 if ok == total else 1
    finally:
        if cleanup:
            shutil.rmtree(str(work), ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
