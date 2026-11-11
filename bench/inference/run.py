#!/usr/bin/env python3
"""Stage 1 B measurement: compile the copy of pruv_agg with all invariant clauses removed (bench/inference/agg_noinv) without inference and with --infer.

    .venv/bin/python bench/inference/run.py [--compiler py|rs] [--repeat N] [--json OUT]

Per input: whether the no-inference compile succeeds, whether the --infer compile succeeds, per-loop counts of generated / kept / dropped / capped
candidates, rounds, and search queries, median compile time (no inference / --infer, wall clock, N runs), and verification trace size
(bytes output by pruv-trace-dump or the adapter, no inference / --infer).
Python 3.9 standard library only.
"""
import argparse
import glob
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tests"))
import compiler_driver as CD  # noqa: E402


def compile_once(drv, src, flags):
    with tempfile.TemporaryDirectory(prefix="pruv_binf_") as tmp:
        t0 = time.perf_counter()
        res = drv.run(drv.argv(src, os.path.join(tmp, "o.rs"), flags, "rust"), timeout=600)
        return res, time.perf_counter() - t0


def trace_bytes(compiler, src, infer):
    flags = ["--infer"] if infer else []
    if compiler == "rs":
        argv = [os.path.join(ROOT, "pruvc-rs", "target", "release", "pruv-trace-dump")] + flags + [src]
    else:
        argv = [CD.pinned_python(), os.path.join(ROOT, "tests", "diff_py_adapter.py"), "trace"] + flags + [src]
    p = subprocess.run(argv, capture_output=True, timeout=600)
    return len(p.stdout) if p.returncode == 0 else None


def main():
    ap = argparse.ArgumentParser()
    CD.add_args(ap)
    ap.add_argument("--repeat", type=int, default=5)
    ap.add_argument("--json", default=None)
    ns = ap.parse_args()
    drv = CD.from_args(ns)
    rows = []
    for src in sorted(glob.glob(os.path.join(HERE, "agg_noinv", "*.pruv"))):
        name = os.path.splitext(os.path.basename(src))[0]
        t_off, t_on = [], []
        for _ in range(ns.repeat):
            r0, d0 = compile_once(drv, src, [])
            r1, d1 = compile_once(drv, src, ["--infer", "--show-inferred"])
            t_off.append(d0)
            t_on.append(d1)
        recs = [json.loads(l) for l in r1.stderr.splitlines() if l.startswith("{")]
        recs = [r for r in recs if "loop" in r]
        errs = [json.loads(l).get("code") for l in r1.stdout.splitlines() if l.startswith("{") and "code" in l]
        rows.append({
            "name": name, "noinfer_ok": r0.returncode == 0, "infer_ok": r1.returncode == 0,
            "infer_errors": errs,
            "loops": [dict({k: r[k] for k in ("loop", "status", "generated", "kept", "capped", "rounds", "queries")},
                           dropped=len(r["dropped"])) for r in recs],
            "ms_noinfer": round(statistics.median(t_off) * 1000), "ms_infer": round(statistics.median(t_on) * 1000),
            "trace_bytes_noinfer": trace_bytes(ns.compiler, src, False),
            "trace_bytes_infer": trace_bytes(ns.compiler, src, True),
        })
    print("compiler=%s repeat=%d" % (ns.compiler, ns.repeat))
    print("%-5s %-7s %-6s %-46s %8s %8s %10s %10s" % ("name", "noinfer", "infer", "loops(gen/kept/drop/cap/rounds/q)",
                                                     "ms_off", "ms_on", "trace_off", "trace_on"))
    for r in rows:
        lp = ";".join("L%d %s %d/%d/%d/%d/%d/%d" % (l["loop"], l["status"], l["generated"], l["kept"], l["dropped"],
                                                    l["capped"], l["rounds"], l["queries"]) for l in r["loops"])
        print("%-5s %-7s %-6s %-46s %8d %8d %10s %10s" % (r["name"], r["noinfer_ok"], r["infer_ok"], lp,
                                                         r["ms_noinfer"], r["ms_infer"], r["trace_bytes_noinfer"],
                                                         r["trace_bytes_infer"]))
    print("infer success: %d/%d, no-inference success: %d/%d" % (sum(r["infer_ok"] for r in rows), len(rows),
                                                 sum(r["noinfer_ok"] for r in rows), len(rows)))
    if ns.json:
        with open(ns.json, "w", encoding="utf-8") as fh:
            json.dump(rows, fh, ensure_ascii=False, indent=1, sort_keys=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
