"""Tests for the hidden `--also-llvm LL RS` option of pruvc.
Run from the repo root: .venv/bin/python tests/cli_also_llvm.py

a. accepted examples x {default, --no-verify, --trust-callers}: one --also-llvm run writes
   exactly what the separate rust run and llvm run write.
   Exception: examples listed in tests/llvm_pending.txt (G2 A3, [u8] not yet in the llvm backend) use pending_case:
   the plain rust run exits 0, the --also-llvm run exits 1 with a codegen/unsupported_type diagnostic and no files.
b. must-reject programs (tests/must_reject/*.pruv and examples/bad_index.pruv): exit 1,
   no output file at all, same diagnostics as the plain run.
c. usage errors exit 2 and write no output file.
d. fuzz-shaped programs (generate.generate_case(56, i), i < 40) x {default, --no-verify}:
   exit 0 -> three files byte-identical; exit 1 -> also-llvm exits 1, same stdout, no files.
e. --backend omitted == explicit --backend rust (one case: same stdout and output bytes).
Prints each failure and a final line "cli_also_llvm: P/T passed"; exit 1 on any failure."""
import concurrent.futures
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "bench", "fuzz"))
import generate  # noqa: E402
sys.path.append(HERE)
import compiler_driver as CD  # noqa: E402
MODES = [("default", []), ("no-verify", ["--no-verify"]), ("trust-callers", ["--trust-callers"])]
OK_LINE = json.dumps({"ok": True})
DRIVER = None  # set in main() from --compiler/--compiler-path (default rs)


def run(args, keep_default_backend=False):
    """args[0] is the input file. --backend is always explicit (inserted as rust right after the
    input when the caller gave none; pruvc.py's default is rust, so this changes nothing).
    keep_default_backend=True leaves --backend out (only default_backend_case uses it)."""
    args = list(args)
    if "--backend" not in args and not keep_default_backend:
        args[1:1] = ["--backend", "rust"]
    d = DRIVER or CD.default_driver()
    return d.run(d.argv_raw(args), timeout=300).raise_if_timeout()


def read(p):
    with open(p, "rb") as fh:
        return fh.read()


def diag_keys(stdout):
    """List of (stage, code, line, col) from the diagnostics. Counterexample values and messages can
    differ from run to run depending on the z3 model (even for repeated identical calls), so they are not compared."""
    keys = []
    for line in stdout.splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            keys.append(("raw", line))
            continue
        if isinstance(d, dict):
            keys.append((d.get("stage"), d.get("code"), d.get("line"), d.get("col")))
    return keys


def accepted_case(f, mode, flags, work):
    stem = os.path.splitext(os.path.basename(f))[0] + "_" + mode
    d = os.path.join(work, stem)
    os.makedirs(d)
    P = lambda n: os.path.join(d, n)
    r1 = run([f, "-o", P("a.rs")] + flags)
    r2 = run([f, "-o", P("b.ll"), "--backend", "llvm", "--rust-bindings", P("b.rs")] + flags)
    r3 = run([f, "-o", P("c.rs"), "--also-llvm", P("c.ll"), P("c_bind.rs")] + flags)
    for n, r in (("rust run", r1), ("llvm run", r2), ("also-llvm run", r3)):
        if r.returncode != 0:
            return False, "%s exit %d %s" % (n, r.returncode, r.stdout + r.stderr)
    probs = []
    if read(P("c.rs")) != read(P("a.rs")):
        probs.append("c.rs != a.rs")
    if read(P("c.ll")) != read(P("b.ll")):
        probs.append("c.ll != b.ll")
    if read(P("c_bind.rs")) != read(P("b.rs")):
        probs.append("c_bind.rs != b.rs")
    if r3.stdout != r1.stdout or r3.stdout.strip() != OK_LINE:
        probs.append("stdout %r vs %r" % (r3.stdout, r1.stdout))
    return not probs, "; ".join(probs)


def llvm_pending():
    """Repo-relative sample paths listed in tests/llvm_pending.txt (empty set if the file is missing)."""
    found = set()
    try:
        with open(os.path.join(HERE, "llvm_pending.txt"), encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#"):
                    found.add(line)
    except OSError:
        pass
    return found


def pending_case(f, mode, flags, work):
    """Example whose llvm side is not open yet: rust run exits 0; --also-llvm exits 1 with
    codegen/unsupported_type on stdout and writes no file."""
    stem = os.path.splitext(os.path.basename(f))[0] + "_" + mode
    d = os.path.join(work, stem)
    os.makedirs(d)
    P = lambda n: os.path.join(d, n)
    r1 = run([f, "-o", P("a.rs")] + flags)
    r3 = run([f, "-o", P("c.rs"), "--also-llvm", P("c.ll"), P("c_bind.rs")] + flags)
    probs = []
    if r1.returncode != 0:
        probs.append("rust run exit %d %s" % (r1.returncode, r1.stdout + r1.stderr))
    elif r1.stdout.strip() != OK_LINE or not os.path.exists(P("a.rs")):
        probs.append("rust run: stdout %r, a.rs exists %s" % (r1.stdout, os.path.exists(P("a.rs"))))
    if r3.returncode != 1:
        probs.append("also-llvm exit %d (expected 1) %s" % (r3.returncode, r3.stdout + r3.stderr))
    if ("codegen", "unsupported_type") not in [k[:2] for k in diag_keys(r3.stdout)]:
        probs.append("no codegen/unsupported_type diagnostic: %r" % (diag_keys(r3.stdout),))
    elif "the llvm codegen layer" not in r3.stdout:
        probs.append("unsupported_type diagnostic does not name the llvm codegen layer: %r" % r3.stdout[:300])
    left = [n for n in ("c.rs", "c.ll", "c_bind.rs") if os.path.exists(P(n))]
    if left:
        probs.append("files written: %s" % left)
    return not probs, "; ".join(probs)


def reject_case(f, work):
    d = os.path.join(work, "rej_" + hash_name(f))
    os.makedirs(d)
    P = lambda n: os.path.join(d, n)
    r1 = run([f, "-o", P("x.rs")])
    if r1.returncode != 1:
        return False, "plain run exit %d (expected 1) %s" % (r1.returncode, r1.stdout + r1.stderr)
    r2 = run([f, "-o", P("c.rs"), "--also-llvm", P("c.ll"), P("c_bind.rs")])
    probs = []
    if r2.returncode != 1:
        probs.append("also-llvm exit %d (expected 1)" % r2.returncode)
    left = [n for n in ("c.rs", "c.ll", "c_bind.rs") if os.path.exists(P(n))]
    if left:
        probs.append("files written: %s" % left)
    if diag_keys(r2.stdout) != diag_keys(r1.stdout):
        probs.append("diagnostics differ: %r vs %r" % (diag_keys(r2.stdout), diag_keys(r1.stdout)))
    return not probs, "; ".join(probs)


def default_backend_case(f, work):
    """--backend omitted must behave as --backend rust: same stdout, exit code and output bytes."""
    d = os.path.join(work, "defbackend")
    os.makedirs(d)
    P = lambda n: os.path.join(d, n)
    r1 = run([f, "-o", P("explicit.rs"), "--backend", "rust"])
    r2 = run([f, "-o", P("omitted.rs")], keep_default_backend=True)
    probs = []
    for n, r in (("explicit", r1), ("omitted", r2)):
        if r.returncode != 0:
            probs.append("%s run exit %d %s" % (n, r.returncode, r.stdout + r.stderr))
    if not probs:
        if read(P("omitted.rs")) != read(P("explicit.rs")):
            probs.append("omitted.rs != explicit.rs")
        if r2.stdout != r1.stdout:
            probs.append("stdout %r vs %r" % (r2.stdout, r1.stdout))
    return not probs, "; ".join(probs)


def hash_name(f):
    return os.path.relpath(f, ROOT).replace(os.sep, "_")


def usage_case(args_fn, work, tag):
    d = os.path.join(work, "usage_" + tag)
    os.makedirs(d)
    src = os.path.join(ROOT, "examples", "bad_index.pruv")
    cands = sorted(glob.glob(os.path.join(ROOT, "examples/*.pruv")))
    for c in cands:
        if os.path.basename(c) != "bad_index.pruv":
            src = c
            break
    r = run(args_fn(src, d))
    probs = []
    if r.returncode != 2:
        probs.append("exit %d (expected 2) %s" % (r.returncode, r.stdout + r.stderr))
    left = [n for n in ("o.rs", "o.ll", "l.ll", "r.rs") if os.path.exists(os.path.join(d, n))]
    if left:
        probs.append("files written: %s" % left)
    return not probs, "; ".join(probs)


def fuzz_case(i, mode, flags, work):
    case = generate.generate_case(56, i)
    d = os.path.join(work, "fuzz_%d_%s" % (i, mode))
    os.makedirs(d)
    P = lambda n: os.path.join(d, n)
    src = P("p.pruv")
    with open(src, "w") as fh:
        fh.write(case["src"])
    r1 = run([src, "-o", P("a.rs")] + flags)
    r2 = run([src, "-o", P("b.ll"), "--backend", "llvm", "--rust-bindings", P("b.rs")] + flags)
    r3 = run([src, "-o", P("c.rs"), "--also-llvm", P("c.ll"), P("c_bind.rs")] + flags)
    if r1.returncode == 0:
        for n, r in (("llvm run", r2), ("also-llvm run", r3)):
            if r.returncode != 0:
                return False, "%s exit %d %s" % (n, r.returncode, r.stdout + r.stderr)
        probs = []
        if read(P("c.rs")) != read(P("a.rs")):
            probs.append("c.rs != a.rs")
        if read(P("c.ll")) != read(P("b.ll")):
            probs.append("c.ll != b.ll")
        if read(P("c_bind.rs")) != read(P("b.rs")):
            probs.append("c_bind.rs != b.rs")
        if r3.stdout != r1.stdout:
            probs.append("stdout %r vs %r" % (r3.stdout, r1.stdout))
        return not probs, "; ".join(probs)
    if r1.returncode == 1:
        probs = []
        if r3.returncode != 1:
            probs.append("also-llvm exit %d (expected 1) %s" % (r3.returncode, r3.stderr))
        left = [n for n in ("c.rs", "c.ll", "c_bind.rs") if os.path.exists(P(n))]
        if left:
            probs.append("files written: %s" % left)
        if diag_keys(r3.stdout) != diag_keys(r1.stdout):
            probs.append("diagnostics differ: %r vs %r" % (diag_keys(r3.stdout), diag_keys(r1.stdout)))
        return not probs, "; ".join(probs)
    return False, "plain run exit %d %s" % (r1.returncode, r1.stdout + r1.stderr)


def main():
    global DRIVER
    DRIVER = CD.from_argv(sys.argv)  # --compiler py|rs, --compiler-path PATH (removed from sys.argv)
    if len(sys.argv) > 1:
        print("usage: cli_also_llvm.py [--compiler py|rs] [--compiler-path PATH]")
        return 2
    work = tempfile.mkdtemp(prefix="cli_also_llvm_")
    jobs = []
    try:
        examples = sorted(glob.glob(os.path.join(ROOT, "examples/*.pruv")))
        rejects = sorted(glob.glob(os.path.join(ROOT, "tests/must_reject/*.pruv")))
        pending = llvm_pending()
        for f in examples:
            base = os.path.basename(f)
            if base == "bad_index.pruv":
                rejects.append(f)  # rejected example: handled as must-reject
                continue
            case = pending_case if "examples/" + base in pending else accepted_case
            for mode, flags in MODES:
                jobs.append(("examples/%s [%s]" % (base, mode),
                             lambda f=f, m=mode, fl=flags, case=case: case(f, m, fl, work)))
        for f in rejects:
            jobs.append(("reject/" + os.path.relpath(f, ROOT), lambda f=f: reject_case(f, work)))
        usage = [
            ("llvm backend", lambda s, d: [s, "-o", d + "/o.ll", "--backend", "llvm",
                                           "--also-llvm", d + "/l.ll", d + "/r.rs"]),
            ("LL == OUT", lambda s, d: [s, "-o", d + "/o.rs", "--also-llvm", d + "/o.rs", d + "/r.rs"]),
            ("RS == OUT", lambda s, d: [s, "-o", d + "/o.rs", "--also-llvm", d + "/l.ll", d + "/o.rs"]),
            ("LL == RS", lambda s, d: [s, "-o", d + "/o.rs", "--also-llvm", d + "/l.ll", d + "/l.ll"]),
            ("one path", lambda s, d: [s, "-o", d + "/o.rs", "--also-llvm", d + "/l.ll"]),
        ]
        for tag, fn in usage:
            jobs.append(("usage/" + tag, lambda fn=fn, tag=tag: usage_case(fn, work, tag.replace(" ", "_"))))

        accepted = [f for f in examples if os.path.basename(f) != "bad_index.pruv"]
        if accepted:
            jobs.append(("default_backend/omitted == explicit rust",
                         lambda f=accepted[0]: default_backend_case(f, work)))

        for i in range(40):
            for mode, flags in MODES[:2]:
                jobs.append(("fuzz/c56_%d [%s]" % (i, mode),
                             lambda i=i, m=mode, fl=flags: fuzz_case(i, m, fl, work)))

        def wrap(name, fn):
            try:
                ok, detail = fn()
            except Exception as e:
                ok, detail = False, repr(e)
            return name, ok, detail

        passed = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            for name, ok, detail in pool.map(lambda j: wrap(*j), jobs):
                if ok:
                    passed += 1
                else:
                    print("FAIL %s -- %s" % (name, detail.strip().replace("\n", " ")[:400]))
        print("cli_also_llvm: %d/%d passed" % (passed, len(jobs)))
        return 0 if passed == len(jobs) else 1
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
