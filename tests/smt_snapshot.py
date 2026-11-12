# -*- coding: utf-8 -*-
"""SMT 231 snapshot: run `diff_py_adapter.py trace FILE [FLAGS]` over the 231 inputs listed in
tests/smt_snapshot_inputs.txt and keep only the verification-relevant part (errors without counterexample,
obligations as [fn, line, col, code, skipped, [[lemmas, smt2, result], ...]]).

  python tests/smt_snapshot.py run OUT.json [--root ROOT] [--python PY] [--jobs 8] [--abs-keys] [--g4] [--flags FLAG...]
     --g4 (G4 A1): also trace the tests/g4/proof project roots (listed in tests/g4/fixtures.json)
  python tests/smt_snapshot.py compare A.json B.json

run: keys are repo-relative paths (--abs-keys: os.path.join(ROOT, rel) with ROOT exactly as given, like the old
     script). Written with json.dump(out, f, sort_keys=True). Prints `N files M crash`.
     --flags takes everything after it and appends it to the trace command (use it last).
compare: keys are normalized to repo-relative paths (old files have absolute keys). Prints per-file differences
     and exits 1 when any; a file with a crash entry on either side (even the same crash) prints `crash in A/B`
     (sides that crashed) and counts as a failure; otherwise `same N` and exit 0.
run also exits 1 when any file crashed.
"""
import concurrent.futures
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ROOT = os.path.dirname(HERE)
INPUTS = os.path.join(HERE, "smt_snapshot_inputs.txt")
TIMEOUT = 600
USAGE = ("usage: smt_snapshot.py run OUT.json [--root ROOT] [--python PY] [--jobs 8] [--abs-keys] [--flags FLAG...]\n"
         "       smt_snapshot.py compare A.json B.json")

_REL = re.compile(r"(?:^|/)((?:tests/(?:must_reject|runtime|check_edge)|tests/g4/proof/[^/]+|examples|bench/solutions/(?:pruv_agg|pruv_refine))/[^/]+)$")


def read_inputs(g4=False):
    with open(INPUTS, encoding="utf-8") as fh:
        rels = [l.strip() for l in fh.read().splitlines() if l.strip()]
    if g4:
        # G4 A1: the proof projects of tests/g4/fixtures.json (roots only), appended after the fixed list
        sys.path.insert(0, HERE)
        import importlib
        rels += [e["root"] for e in importlib.import_module("g4.projects").proof()]
    return rels


def reduce_trace(data):
    errors = []
    for e in data.get("errors", []):
        errors.append({k: v for k, v in e.items() if k != "counterexample"})
    obs = []
    for o in data.get("obligations", []):
        row = [o["fn"], o["line"], o["col"], o["code"], o.get("skipped", False),
               [[a["lemmas"], a["smt2"], a["result"]] for a in o.get("attempts", [])]]
        if "file" in o:     # G4 A1: explicit-mode obligations only; legacy rows keep their exact shape
            row.append(o["file"])
        obs.append(row)
    return {"errors": errors, "obs": obs}


def one(python, root, rel, flags):
    path = os.path.join(root, *rel.split("/"))
    argv = [python, os.path.join(root, "tests", "diff_py_adapter.py"), "trace", path] + list(flags)
    try:
        p = subprocess.run(argv, capture_output=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return {"crash": "timeout %ds" % TIMEOUT}
    stderr_tail = p.stderr.decode("utf-8", "replace")[-300:]
    try:
        data = json.loads(p.stdout.decode("utf-8"))
    except ValueError:
        return {"crash": stderr_tail}
    if p.returncode != 0:
        return {"crash": stderr_tail}
    try:
        return reduce_trace(data)
    except (KeyError, TypeError, AttributeError) as e:
        return {"crash": "unexpected trace structure: %r" % (e,)}


def cmd_run(args):
    if not args:
        print(USAGE)
        return 2
    out_path = args[0]
    root, python, jobs, abs_keys, flags = DEFAULT_ROOT, sys.executable, 8, False, []
    g4 = False
    i = 1
    while i < len(args):
        a = args[i]
        if a == "--flags":
            flags = args[i + 1:]
            break
        if a == "--abs-keys":
            abs_keys = True
            i += 1
        elif a == "--g4":
            g4 = True
            i += 1
        elif a in ("--root", "--python", "--jobs"):
            if i + 1 >= len(args):
                print(USAGE)
                return 2
            v = args[i + 1]
            if a == "--root":
                root = v
            elif a == "--python":
                python = v
            else:
                try:
                    jobs = int(v)
                except ValueError:
                    print(USAGE)
                    return 2
            i += 2
        else:
            print(USAGE)
            return 2
    rels = read_inputs(g4)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        results = list(pool.map(lambda r: one(python, root, r, flags), rels))
    out = {}
    for rel, res in zip(rels, results):
        out[os.path.join(root, rel) if abs_keys else rel] = res
    with open(out_path, "w") as f:
        json.dump(out, f, sort_keys=True)
    crash = sum(1 for r in results if "crash" in r)
    print("%d files %d crash" % (len(rels), crash))
    return 1 if crash else 0


def norm_key(k):
    m = _REL.search(k.replace("\\", "/"))
    return m.group(1) if m else k


def load_norm(path):
    with open(path, encoding="utf-8") as fh:
        d = json.load(fh)
    return {norm_key(k): v for k, v in d.items()}


def cmd_compare(args):
    if len(args) != 2:
        print(USAGE)
        return 2
    a, b = load_norm(args[0]), load_norm(args[1])
    diffs = 0
    for k in sorted(set(a) | set(b)):
        if k not in a:
            print("%s: only in B" % k)
            diffs += 1
            continue
        if k not in b:
            print("%s: only in A" % k)
            diffs += 1
            continue
        x, y = a[k], b[k]
        if "crash" in x or "crash" in y:
            side = "/".join(n for n, v in (("A", x), ("B", y)) if "crash" in v)
            diffs += 1
            print("%s: crash in %s" % (k, side))
            continue
        if x == y:
            continue
        diffs += 1
        msgs = []
        if x.get("errors") != y.get("errors"):
            msgs.append("errors differ")
        xo, yo = x.get("obs", []), y.get("obs", [])
        if len(xo) != len(yo):
            msgs.append("obs count %d vs %d" % (len(xo), len(yo)))
        for n, (p, q) in enumerate(zip(xo, yo)):
            if p != q:
                msgs.append("first differing obs #%d: A fn=%s code=%s / B fn=%s code=%s" % (n, p[0], p[3], q[0], q[3]))
                break
        print("%s: %s" % (k, "; ".join(msgs) or "differs"))
    if diffs:
        print("%d of %d files differ" % (diffs, len(set(a) | set(b))))
        return 1
    print("same %d" % len(a))
    return 0


def main(argv):
    if not argv or argv[0] not in ("run", "compare"):
        print(USAGE)
        return 2
    return cmd_run(argv[1:]) if argv[0] == "run" else cmd_compare(argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
