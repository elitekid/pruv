#!/usr/bin/env python3
"""1단계 B2(--infer) 시험 실행기. Python 3.9 표준 라이브러리만 쓴다.

    .venv/bin/python tests/inference/run.py --compiler py|rs [--regress] [--jobs N] [이름 ...]

형식은 tests/inference/README.md 참고.
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
    return ", ".join("%s/%s" % (e.get("stage"), e.get("code")) for e in errors) or "(없음)"


def check_expect(res, errors, expect, fails, label=""):
    if expect == "ok":
        if res.returncode != 0:
            fails.append("%s종료 코드 %s (기대 0), 오류: %s" % (label, res.returncode, fmt_errors(errors)))
    elif isinstance(expect, dict):
        if res.returncode != 1:
            fails.append("%s종료 코드 %s (기대 1)" % (label, res.returncode))
        if not has_error(errors, expect.get("stage"), expect.get("code")):
            fails.append("%s오류 %s/%s 없음, 실제: %s" % (label, expect.get("stage"), expect.get("code"),
                                                       fmt_errors(errors)))
    else:
        fails.append("%sjson expect 형식 오류: %r" % (label, expect))


def run_case(drv, pruv):
    name = os.path.splitext(os.path.basename(pruv))[0]
    fails = []
    try:
        with open(os.path.splitext(pruv)[0] + ".json", encoding="utf-8") as fh:
            spec = json.load(fh)
    except (OSError, ValueError) as e:
        return name, ["json 읽기 실패: %s" % e]
    flags = spec.get("flags", DEFAULT_FLAGS)
    res, errors, records = compile_one(drv, pruv, flags)
    if res.crashed:
        return name, ["컴파일러 비정상 종료/시간 초과: rc=%s %s" % (res.returncode, res.stderr[-300:])]
    check_expect(res, errors, spec.get("expect", "ok"), fails)

    if "--show-inferred" in flags:
        if not records:
            fails.append("--show-inferred 레코드가 stderr 에 없음")
        have_inv = set()
        have_drop = set()
        for r in records:
            for t in r.get("invariants", []):
                have_inv.add(t)
            for d in r.get("dropped", []):
                have_drop.add(d.get("text"))
        for k in spec.get("kept", []):
            if k not in have_inv:
                fails.append("kept 없음: %r (실제 %s)" % (k, sorted(have_inv)))
        for d in spec.get("dropped", []):
            if d not in have_drop:
                fails.append("dropped 없음: %r (실제 %s)" % (d, sorted(x for x in have_drop if x)))
        for t in spec.get("absent", []):
            if "invariant " + t in have_inv or t in have_drop:
                fails.append("absent 인데 생성됨: %r" % t)
        for fn, want in (spec.get("fallback") or {}).items():
            mine = [r for r in records if r.get("fn") == fn]
            got = bool(mine) and all(r.get("fallback") == "v1" for r in mine)
            has_any = any("fallback" in r for r in mine)
            if not mine:
                fails.append("fallback[%s]: 그 함수 레코드 없음" % fn)
            elif want and not got:
                fails.append("fallback[%s] 기대 true 인데 \"fallback\": \"v1\" 키가 없음" % fn)
            elif not want and has_any:
                fails.append("fallback[%s] 기대 false 인데 fallback 키가 있음" % fn)
        rounds = {}
        for r in records:
            for d in r.get("dropped", []):
                rounds.setdefault(d.get("text"), d.get("round"))
        for t, want in (spec.get("dropped_round") or {}).items():
            if rounds.get(t) != want:
                fails.append("dropped_round[%r] 기대 %s 실제 %s" % (t, want, rounds.get(t)))
        for fn, st in (spec.get("status") or {}).items():
            got = sorted(set(r.get("status") for r in records if r.get("fn") == fn))
            if got != [st]:
                fails.append("status[%s] 기대 %s 실제 %s" % (fn, st, got))
    elif spec.get("kept") or spec.get("dropped") or spec.get("status") or spec.get("absent") \
            or spec.get("fallback"):
        fails.append("flags 에 --show-inferred 가 없어 kept/dropped/status/absent/fallback 을 볼 수 없음")

    ni = spec.get("noinfer")
    if ni:
        res2, errors2, _ = compile_one(drv, pruv, [])
        want = 0 if ni == "ok" else 1
        if res2.crashed or res2.returncode != want:
            fails.append("noinfer %s 기대인데 종료 코드 %s (%s)" % (ni, res2.returncode, fmt_errors(errors2)))
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
    extra = expect.get("flags")  # must_reject 표본 json 의 선택 키 flags(run_all 과 같은 뜻)
    extra = list(extra) if isinstance(extra, list) and all(isinstance(x, str) for x in extra) else []
    res, errors, _ = compile_one(drv, pruv, ["--infer"] + extra)
    if res.crashed:
        return name, ["컴파일러 비정상 종료/시간 초과: rc=%s" % res.returncode]
    if res.returncode != 1:
        fails.append("--infer 에서 거부되지 않음(종료 %s) — 건전성 회귀" % res.returncode)
    elif expect.get("stage") or expect.get("code"):
        if not has_error(errors, expect.get("stage"), expect.get("code")):
            fails.append("오류 %s/%s 없음, 실제: %s" % (expect.get("stage"), expect.get("code"), fmt_errors(errors)))
    return name, fails


def run_regress_compile(drv, pruv, label):
    name = label + "/" + os.path.splitext(os.path.basename(pruv))[0]
    res, errors, _ = compile_one(drv, pruv, ["--infer"])
    if res.crashed:
        return name, ["컴파일러 비정상 종료/시간 초과: rc=%s" % res.returncode]
    if res.returncode != 0:
        return name, ["--infer 에서 컴파일 실패(종료 %s): %s" % (res.returncode, fmt_errors(errors))]
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
    ap = argparse.ArgumentParser(description="--infer 시험 실행기")
    CD.add_args(ap)
    ap.add_argument("--regress", action="store_true", help="must_reject/examples/runtime/bench 회귀도 본다")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("names", nargs="*", help="inf_ 표본 이름(생략하면 전부)")
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
        print("실패 목록:")
        for n, f in bad:
            print("  %s" % n)
            for line in f:
                print("    - %s" % line)
    return 0 if not bad and results else 1


if __name__ == "__main__":
    sys.exit(main())
