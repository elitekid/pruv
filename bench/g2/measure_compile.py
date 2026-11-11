# -*- coding: utf-8 -*-
"""Compare compile (verify + Rust emit) wall time of two pruvc builds.

usage: measure_compile.py OUT.json --base PRUVC_BASE --head PRUVC_HEAD
           [--reps 5] [--inputs tests/smt_snapshot_inputs.txt] [--root REPO] [--limit N]
"""
import argparse
import datetime
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time

TIMEOUT = 600


def run_once(exe, src, out, cwd):
    t0 = time.perf_counter()
    try:
        p = subprocess.run([exe, src, "-o", out], cwd=cwd, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=TIMEOUT)
        rc = p.returncode
    except subprocess.TimeoutExpired:
        rc = -1
    return time.perf_counter() - t0, rc


def p90(vals):
    s = sorted(vals)
    if not s:
        return 0.0
    rank = -(-90 * len(s) // 100)  # nearest rank: ceil(0.9 * n)
    return s[max(rank, 1) - 1]


def loadavg():
    try:
        return list(os.getloadavg())
    except (OSError, AttributeError):
        return None


def side_summary(files, side):
    meds = {f: d[side]["median"] for f, d in files.items()}
    vals = list(meds.values())
    if not vals:
        return {"sum_of_medians": 0.0, "median_of_medians": 0.0, "p90_of_medians": 0.0,
                "max_of_medians": None}
    mx = max(meds, key=lambda f: meds[f])
    return {"sum_of_medians": sum(vals), "median_of_medians": statistics.median(vals),
            "p90_of_medians": p90(vals), "max_of_medians": {"file": mx, "seconds": meds[mx]}}


def ratio(a, b):
    return a / b if b else None


def main(argv):
    ap = argparse.ArgumentParser(allow_abbrev=False)
    ap.add_argument("out")
    ap.add_argument("--base", required=True)
    ap.add_argument("--head", required=True)
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--inputs", default="tests/smt_snapshot_inputs.txt")
    ap.add_argument("--root", default=os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))))
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args(argv)

    root = os.path.abspath(a.root)
    inputs_path = a.inputs if os.path.isabs(a.inputs) else os.path.join(root, a.inputs)
    with open(inputs_path, encoding="utf-8") as fh:
        rels = [ln.strip() for ln in fh if ln.strip() and not ln.strip().startswith("#")]
    if a.limit is not None:
        rels = rels[:a.limit]
    exes = {"base": os.path.abspath(a.base), "head": os.path.abspath(a.head)}

    started = datetime.datetime.now().isoformat()
    load0 = loadavg()
    data = {r: {"base": {"times": [], "rc": []}, "head": {"times": [], "rc": []}} for r in rels}
    with tempfile.TemporaryDirectory(prefix="measure_compile_") as tmp:
        for rep in range(1, a.reps + 1):
            for i, rel in enumerate(rels):
                order = ("base", "head") if (rep + i) % 2 == 0 else ("head", "base")
                for side in order:
                    out = os.path.join(tmp, "%s_%d.rs" % (side, i))
                    dt, rc = run_once(exes[side], os.path.join(root, rel), out, tmp)
                    data[rel][side]["times"].append(dt)
                    data[rel][side]["rc"].append(rc)
            sys.stderr.write("rep %d/%d done\n" % (rep, a.reps))
    for d in data.values():
        for side in ("base", "head"):
            d[side]["median"] = statistics.median(d[side]["times"]) if d[side]["times"] else 0.0

    summary = {"base": side_summary(data, "base"), "head": side_summary(data, "head")}
    summary["ratio_sum"] = ratio(summary["head"]["sum_of_medians"], summary["base"]["sum_of_medians"])
    summary["ratio_median"] = ratio(summary["head"]["median_of_medians"],
                                    summary["base"]["median_of_medians"])
    slower, mismatch = [], []
    for rel, d in data.items():
        b, h = d["base"]["median"], d["head"]["median"]
        if h > 1.10 * b and h - b > 0.05:
            slower.append({"file": rel, "base_median": b, "head_median": h})
        rb, rh = set(d["base"]["rc"]), set(d["head"]["rc"])
        if rb != rh or len(rb) > 1 or len(rh) > 1:
            mismatch.append({"file": rel, "base_rc": d["base"]["rc"], "head_rc": d["head"]["rc"]})
    summary["slower_files"] = slower
    summary["rc_mismatch"] = mismatch
    rs = summary["ratio_sum"]
    summary["gate_sum_ratio_le_1_10"] = rs is not None and rs <= 1.10

    meta = {"base": exes["base"], "head": exes["head"], "reps": a.reps, "inputs": len(rels),
            "started": started, "finished": datetime.datetime.now().isoformat(),
            "host": platform.platform(), "cpu_count": os.cpu_count(),
            "loadavg_start": load0, "loadavg_end": loadavg()}
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump({"meta": meta, "files": data, "summary": summary}, fh, indent=1, ensure_ascii=False)

    print("files=%d reps=%d load %s -> %s" % (len(rels), a.reps, meta["loadavg_start"], meta["loadavg_end"]))
    for side in ("base", "head"):
        s = summary[side]
        print("%s: sum=%.3f median=%.3f p90=%.3f max=%s" % (
            side, s["sum_of_medians"], s["median_of_medians"], s["p90_of_medians"], s["max_of_medians"]))
    print("ratio head/base: sum=%s median=%s" % (summary["ratio_sum"], summary["ratio_median"]))
    print("gate sum ratio <= 1.10: %s" % summary["gate_sum_ratio_le_1_10"])
    print("slower files: %d, rc mismatch: %d" % (len(slower), len(mismatch)))
    return 1 if mismatch else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
