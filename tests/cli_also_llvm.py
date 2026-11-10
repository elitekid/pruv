"""Tests for the hidden `--also-llvm LL RS` option of pruvc.
Run from the repo root: .venv/bin/python tests/cli_also_llvm.py

a. accepted examples x {default, --no-verify, --trust-callers}: one --also-llvm run writes
   exactly what the separate rust run and llvm run write.
b. must-reject programs (tests/must_reject/*.pruv and examples/bad_index.pruv): exit 1,
   no output file at all, same diagnostics as the plain run.
c. usage errors exit 2 and write no output file.
d. fuzz-shaped programs (generate.generate_case(56, i), i < 40) x {default, --no-verify}:
   exit 0 -> three files byte-identical; exit 1 -> also-llvm exits 1, same stdout, no files.
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
PRUVC = os.path.join(ROOT, "pruvc", "pruvc.py")
MODES = [("default", []), ("no-verify", ["--no-verify"]), ("trust-callers", ["--trust-callers"])]
OK_LINE = json.dumps({"ok": True})


def run(args):
    return subprocess.run([sys.executable, PRUVC] + args, capture_output=True, text=True, timeout=300)


def read(p):
    with open(p, "rb") as fh:
        return fh.read()


def diag_keys(stdout):
    """진단의 (stage, code, line, col) 목록. 반례 값과 메시지는 z3 모델에 따라 실행마다
    달라질 수 있어(같은 호출을 되풀이해도 바뀐다) 비교하지 않는다."""
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
    work = tempfile.mkdtemp(prefix="cli_also_llvm_")
    jobs = []
    try:
        examples = sorted(glob.glob(os.path.join(ROOT, "examples/*.pruv")))
        rejects = sorted(glob.glob(os.path.join(ROOT, "tests/must_reject/*.pruv")))
        for f in examples:
            base = os.path.basename(f)
            if base == "bad_index.pruv":
                rejects.append(f)  # rejected example: handled as must-reject
                continue
            for mode, flags in MODES:
                jobs.append(("examples/%s [%s]" % (base, mode),
                             lambda f=f, m=mode, fl=flags: accepted_case(f, m, fl, work)))
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
