# -*- coding: utf-8 -*-
"""Per-file solver statistics from `tests/diff_py_adapter.py trace`.

usage: solver_stats.py OUT.json FILE_OR_DIR... [--infer] [--python PY]
"""
import argparse
import glob
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ADAPTER = os.path.join(ROOT, "tests", "diff_py_adapter.py")
TIMEOUT = 600


def expand(paths):
    files = []
    for p in paths:
        if os.path.isdir(p):
            files.extend(sorted(glob.glob(os.path.join(p, "*.pruv"))))
        else:
            files.append(p)
    return files


def bump(d, k, n=1):
    d[k] = d.get(k, 0) + n


def stats_for(path, py, infer):
    rec = {"file": path, "obligations": 0, "skipped": 0, "attempts": 0, "results": {},
           "final_results": {}, "forall": 0, "exists": 0, "errors": [], "wall": 0.0, "rc": None}
    cmd = [py, ADAPTER, "trace", path] + (["--infer"] if infer else [])
    t0 = time.perf_counter()
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=TIMEOUT)
        rec["rc"] = p.returncode
        out = p.stdout.decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        rec["rc"], out = -1, ""
        rec["crash"] = "timeout"
    rec["wall"] = time.perf_counter() - t0
    if rec["rc"] != 0 and "crash" not in rec:
        rec["crash"] = "rc=%s: %s" % (rec["rc"], p.stderr.decode("utf-8", "replace")[-300:])
    if not out.strip():
        return rec
    try:
        tr = json.loads(out)
    except ValueError as e:
        rec["crash"] = "bad json: %s" % e
        return rec
    tr = tr.get("trace") or tr  # tolerate the snapshot-item wrapper
    rec["errors"] = [e.get("code") for e in tr.get("errors", [])]
    for o in tr.get("obligations", []):
        rec["obligations"] += 1
        if o.get("skipped"):
            rec["skipped"] += 1
            continue
        atts = o.get("attempts", [])
        for at in atts:
            rec["attempts"] += 1
            bump(rec["results"], at.get("result"))
            text = at.get("smt2", "")
            rec["forall"] += text.count("(forall")
            rec["exists"] += text.count("(exists")
        if atts:
            bump(rec["final_results"], atts[-1].get("result"))
    return rec


def merge(dst, src):
    for k, v in src.items():
        bump(dst, k, v)


def main(argv):
    ap = argparse.ArgumentParser(allow_abbrev=False)
    ap.add_argument("out")
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--infer", action="store_true")
    ap.add_argument("--python", default=sys.executable)
    a = ap.parse_args(argv)

    rows = [stats_for(f, a.python, a.infer) for f in expand(a.paths)]
    tot = {"file": "TOTAL", "obligations": 0, "skipped": 0, "attempts": 0, "results": {},
           "final_results": {}, "forall": 0, "exists": 0, "errors": [], "wall": 0.0,
           "crashes": sum(1 for r in rows if "crash" in r)}
    for r in rows:
        for k in ("obligations", "skipped", "attempts", "forall", "exists", "wall"):
            tot[k] += r[k]
        merge(tot["results"], r["results"])
        merge(tot["final_results"], r["final_results"])
        tot["errors"].extend(r["errors"])
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump({"meta": {"infer": a.infer, "python": a.python, "files": len(rows)},
                   "files": rows, "total": tot}, fh, indent=1, ensure_ascii=False)

    print("%-50s %5s %5s %5s %5s %5s %7s  %s" % ("file", "obl", "skip", "att", "fa", "ex", "wall", "results"))
    for r in rows + [tot]:
        name = r["file"] if len(r["file"]) <= 50 else "..." + r["file"][-47:]
        res = ",".join("%s=%d" % kv for kv in sorted(r["results"].items(), key=lambda kv: str(kv[0])))
        flag = "  CRASH(%s)" % r["crash"][:40] if "crash" in r else ""
        print("%-50s %5d %5d %5d %5d %5d %7.2f  %s%s" % (
            name, r["obligations"], r["skipped"], r["attempts"], r["forall"], r["exists"],
            r["wall"], res, flag))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
