#!/usr/bin/env python3
"""Stage 1 B2 (--infer) test runner. Uses only the Python 3.9 standard library.

    .venv/bin/python tests/inference/run.py --compiler py|rs [--regress] [--jobs N] [NAME ...]

See tests/inference/README.md for the format.
"""
import argparse
import glob
import json
import os
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tests"))
import compiler_driver as CD  # noqa: E402

DEFAULT_FLAGS = ["--infer", "--show-inferred"]
TIMEOUT = 300


def json_lines(text):
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            v = json.loads(line)
        except ValueError:
            continue
        if isinstance(v, dict):
            out.append(v)
    return out


def compile_one(drv, src, flags):
    with tempfile.TemporaryDirectory(prefix="pruv_inf_") as tmp:
        out = os.path.join(tmp, "out.rs")
        res = drv.run(drv.argv(src, out, flags, "rust"), timeout=TIMEOUT)
    errors = [d for d in json_lines(res.stdout) if "code" in d or "stage" in d]
    records = [d for d in json_lines(res.stderr) if "fn" in d and "loop" in d]
    return res, errors, records


def has_error(errors, stage, code):
    for e in errors:
        if (stage is None or e.get("stage") == stage) and (code is None or e.get("code") == code):
            return True
    return False


def fmt_errors(errors):
    return ", ".join("%s/%s" % (e.get("stage"), e.get("code")) for e in errors) or "(none)"


def check_expect(res, errors, expect, fails, label=""):
    if expect == "ok":
        if res.returncode != 0:
            fails.append("%sexit code %s (expected 0), errors: %s" % (label, res.returncode, fmt_errors(errors)))
    elif isinstance(expect, dict):
        if res.returncode != 1:
            fails.append("%sexit code %s (expected 1)" % (label, res.returncode))
        if not has_error(errors, expect.get("stage"), expect.get("code")):
            fails.append("%serror %s/%s missing, actual: %s" % (label, expect.get("stage"), expect.get("code"),
                                                             fmt_errors(errors)))
    else:
        fails.append("%sjson expect format error: %r" % (label, expect))


def run_case(drv, pruv):
    name = os.path.splitext(os.path.basename(pruv))[0]
    fails = []
    try:
        with open(os.path.splitext(pruv)[0] + ".json", encoding="utf-8") as fh:
            spec = json.load(fh)
    except (OSError, ValueError) as e:
        return name, ["failed to read json: %s" % e]
    flags = spec.get("flags", DEFAULT_FLAGS)
    res, errors, records = compile_one(drv, pruv, flags)
    if res.crashed:
        return name, ["compiler crashed/timed out: rc=%s %s" % (res.returncode, res.stderr[-300:])]
    check_expect(res, errors, spec.get("expect", "ok"), fails)

    if "--show-inferred" in flags:
        if not records:
            fails.append("no --show-inferred record on stderr")
        have_inv = set()
        have_drop = set()
        for r in records:
            for t in r.get("invariants", []):
                have_inv.add(t)
            for d in r.get("dropped", []):
                have_drop.add(d.get("text"))
        for k in spec.get("kept", []):
            if k not in have_inv:
                fails.append("kept missing: %r (actual %s)" % (k, sorted(have_inv)))
        for d in spec.get("dropped", []):
            if d not in have_drop:
                fails.append("dropped missing: %r (actual %s)" % (d, sorted(x for x in have_drop if x)))
        for t in spec.get("absent", []):
            if "invariant " + t in have_inv or t in have_drop:
                fails.append("listed as absent but was generated: %r" % t)
        for fn, want in (spec.get("fallback") or {}).items():
            mine = [r for r in records if r.get("fn") == fn]
            got = bool(mine) and all(r.get("fallback") == "v1" for r in mine)
            has_any = any("fallback" in r for r in mine)
            if not mine:
                fails.append("fallback[%s]: no record for that function" % fn)
            elif want and not got:
                fails.append("fallback[%s] expected true but the \"fallback\": \"v1\" key is missing" % fn)
            elif not want and has_any:
                fails.append("fallback[%s] expected false but a fallback key is present" % fn)
        rounds = {}
        for r in records:
            for d in r.get("dropped", []):
                rounds.setdefault(d.get("text"), d.get("round"))
        for t, want in (spec.get("dropped_round") or {}).items():
            if rounds.get(t) != want:
                fails.append("dropped_round[%r] expected %s actual %s" % (t, want, rounds.get(t)))
        for fn, st in (spec.get("status") or {}).items():
            got = sorted(set(r.get("status") for r in records if r.get("fn") == fn))
            if got != [st]:
                fails.append("status[%s] expected %s actual %s" % (fn, st, got))
    elif spec.get("kept") or spec.get("dropped") or spec.get("status") or spec.get("absent") \
            or spec.get("fallback"):
        fails.append("flags lacks --show-inferred, so kept/dropped/status/absent/fallback cannot be checked")

    ni = spec.get("noinfer")
    if ni:
        res2, errors2, _ = compile_one(drv, pruv, [])
        want = 0 if ni == "ok" else 1
        if res2.crashed or res2.returncode != want:
            fails.append("noinfer expected %s but exit code was %s (%s)" % (ni, res2.returncode, fmt_errors(errors2)))
    return name, fails


def run_regress_reject(drv, pruv):
    name = "must_reject/" + os.path.splitext(os.path.basename(pruv))[0]
    fails = []
    expect = {}
    jp = os.path.splitext(pruv)[0] + ".json"
    if os.path.exists(jp):
        try:
            with open(jp, encoding="utf-8") as fh:
                v = json.load(fh)
            if isinstance(v, dict):
                expect = v
        except (OSError, ValueError):
            pass
    extra = expect.get("flags")  # optional key flags of the must_reject sample json (same meaning as in run_all)
    extra = list(extra) if isinstance(extra, list) and all(isinstance(x, str) for x in extra) else []
    res, errors, _ = compile_one(drv, pruv, ["--infer"] + extra)
    if res.crashed:
        return name, ["compiler crashed/timed out: rc=%s" % res.returncode]
    if res.returncode != 1:
        fails.append("not rejected under --infer (exit %s) — soundness regression" % res.returncode)
    elif expect.get("stage") or expect.get("code"):
        if not has_error(errors, expect.get("stage"), expect.get("code")):
            fails.append("error %s/%s missing, actual: %s" % (expect.get("stage"), expect.get("code"), fmt_errors(errors)))
    return name, fails


def run_regress_compile(drv, pruv, label):
    name = label + "/" + os.path.splitext(os.path.basename(pruv))[0]
    res, errors, _ = compile_one(drv, pruv, ["--infer"])
    if res.crashed:
        return name, ["compiler crashed/timed out: rc=%s" % res.returncode]
    if res.returncode != 0:
        return name, ["compilation failed under --infer (exit %s): %s" % (res.returncode, fmt_errors(errors))]
    return name, []


def has_exit_key(pruv):
    jp = os.path.splitext(pruv)[0] + ".json"
    try:
        with open(jp, encoding="utf-8") as fh:
            v = json.load(fh)
    except (OSError, ValueError):
        return False
    if not isinstance(v, dict) or "exit" not in v:
        return False
    # only tests that are compiled with the proof on at least once (a --no-verify-only test is expected to fail it)
    rows = v.get("flags_matrix") or [v.get("flags", [])]
    return any("--no-verify" not in row for row in rows)


def main():
    ap = argparse.ArgumentParser(description="--infer test runner")
    CD.add_args(ap)
    ap.add_argument("--regress", action="store_true", help="also check regressions in must_reject/examples/runtime/bench")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("names", nargs="*", help="inf_ sample names (all if omitted)")
    ns = ap.parse_args()
    drv = CD.from_args(ns)

    cases = sorted(glob.glob(os.path.join(HERE, "inf_*.pruv")))
    if ns.names:
        want = set(ns.names)
        cases = [c for c in cases if os.path.splitext(os.path.basename(c))[0] in want]
    tasks = [(run_case, c) for c in cases]

    if ns.regress:
        for p in sorted(glob.glob(os.path.join(ROOT, "tests", "must_reject", "*.pruv"))):
            tasks.append((run_regress_reject, p))
        for label, pat in (("examples", os.path.join(ROOT, "examples", "*.pruv")),
                           ("runtime", os.path.join(ROOT, "tests", "runtime", "*.pruv"))):
            for p in sorted(glob.glob(pat)):
                if has_exit_key(p):
                    tasks.append((run_regress_compile, p, label))
        for p in sorted(glob.glob(os.path.join(ROOT, "bench", "solutions", "pruv_agg", "*.pruv"))):
            tasks.append((run_regress_compile, p, "bench/pruv_agg"))

    def go(t):
        return t[0](drv, *t[1:]) if t[0] is not run_regress_compile else t[0](drv, t[1], t[2])

    results = []
    with ThreadPoolExecutor(max_workers=max(1, ns.jobs)) as ex:
        for name, fails in ex.map(go, tasks):
            results.append((name, fails))
            print("%s %s" % ("PASS" if not fails else "FAIL", name), flush=True)

    bad = [(n, f) for n, f in results if f]
    print()
    print("TOTAL %d/%d" % (len(results) - len(bad), len(results)))
    if bad:
        print("failures:")
        for n, f in bad:
            print("  %s" % n)
            for line in f:
                print("    - %s" % line)
    return 0 if not bad and results else 1


if __name__ == "__main__":
    sys.exit(main())
