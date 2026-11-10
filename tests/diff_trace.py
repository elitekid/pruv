#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Python 정본 검증기 trace 와 Rust pruv-trace-dump 의 trace 를 입력마다 비교한다 (M3 3단계).

  python tests/diff_trace.py [--rs-path P] [--python P] [--only GROUP[,GROUP]] [--seeds 41,56,57]
                             [--fuzz-count 40] [--jobs N] [--save-dir DIR] [--input FILE ...]

그룹: must_reject examples runtime bench check_edge fuzz input
  (--input 만 주고 --only 가 없으면 input 그룹만 돈다)
입력마다 Python(`PY tests/diff_py_adapter.py trace FILE`)과 Rust(`pruv-trace-dump FILE`)를 각각
새 프로세스로 돌린다(셸 없음, timeout 300). 한 입력의 두 실행은 같은 작업자에서 차례로 한다.

분류 (입력 하나당 하나):
  same          두 stdout 한 줄이 바이트 동일
  cex_only      errors 의 counterexample 값만 다르고 나머지 동일(통과로 침, 수는 따로 보고)
  flaky_unknown 어느 쪽 attempt result 가 "unknown" 이고 그 차이 때문에 다름 -> 그 입력만 직렬(--jobs 1)로
                한 번 다시 돌려 재판정. same/cex_only 로 풀리면 이 칸에 센다(통과). 그래도 다르면 diff.
  diff          그 밖의 차이
  py_crash / rs_crash   종료 코드≠0, 출력 줄 없음, JSON 아님
  timeout       어느 쪽이든 시간 초과
종료 코드: 0 = diff·crash·timeout 0, 1 = 그 외, 2 = 인자/바이너리 없음.
Python 3.9 표준 라이브러리만 쓴다.
"""
import argparse
import collections
import concurrent.futures
import glob
import json
import os
import re
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

PROC_TIMEOUT = 300
MAX_SHOWN = 10
CEX_KEY = "counterexample"
GROUP_DIRS = [
    ("must_reject", "tests/must_reject", "*.pruv"),
    ("examples", "examples", "*.pruv"),
    ("runtime", "tests/runtime", "*.pruv"),
    ("bench", "bench/solutions/pruv_agg", "*.pruv"),
    ("check_edge", "tests/check_edge", "ok_*.pruv"),
]
ALL_GROUPS = [g for g, _, _ in GROUP_DIRS] + ["fuzz", "input"]
COLS = ("inputs", "same", "cex_only", "flaky_unknown", "diff", "py_crash", "rs_crash", "timeout")


class Case(object):
    def __init__(self, group, name, path):
        self.group, self.name, self.path = group, name, path
        self.status = None
        self.note = ""
        self.py_raw = None      # bytes (한 줄, 개행 제외) 또는 None
        self.rs_raw = None
        self.py_obj = None
        self.rs_obj = None
        self.flaky_first = False   # 처음에 flaky_unknown 으로 판정돼 재시도 했는가


def rel(path):
    return os.path.relpath(path, ROOT).replace(os.sep, "/")


def safe(name):
    return re.sub(r"[^A-Za-z0-9_.+-]", "_", name)[:80]


def parse_seed(tok):
    return int(tok) if re.fullmatch(r"-?[0-9]+", tok) else tok


# ---------------------------------------------------------------------------
# 입력 모으기
# ---------------------------------------------------------------------------
def build_cases(selected, args, tmp):
    per_group = collections.OrderedDict((g, []) for g in ALL_GROUPS)
    notes = []
    for g, sub, pat in GROUP_DIRS:
        if g not in selected:
            continue
        files = sorted(glob.glob(os.path.join(ROOT, *sub.split("/"), pat)))
        if not files:
            notes.append("경고: %s 에 %s 가 없다(%s)" % (g, pat, sub))
        for p in files:
            per_group[g].append(Case(g, rel(p), p))
    if "fuzz" in selected:
        d = os.path.join(tmp, "fuzz")
        os.makedirs(d)
        sys.path.insert(0, os.path.join(ROOT, "bench", "fuzz"))
        try:
            import generate
        except Exception as e:   # noqa: BLE001
            print("오류: 퍼저 생성기를 불러오지 못했다: %s: %s" % (type(e).__name__, e), file=sys.stderr)
            raise SystemExit(2)
        skipped = 0
        for seed in args.seeds:
            for idx in range(args.fuzz_count):
                try:
                    data = generate.generate_case(seed, idx)["src"].encode("utf-8")
                except Exception:   # noqa: BLE001
                    skipped += 1
                    continue
                p = os.path.join(d, "s%s_%05d.pruv" % (safe(str(seed)), idx))
                with open(p, "wb") as fh:
                    fh.write(data)
                per_group["fuzz"].append(Case("fuzz", "fuzz:%s:%d" % (seed, idx), p))
        notes.append("fuzz: 생성기 예외로 건너뛴 index %d개 (seeds=%s, count=%d)" % (
            skipped, ",".join(str(s) for s in args.seeds), args.fuzz_count))
    if "input" in selected:
        for p in args.input:
            per_group["input"].append(Case("input", os.path.abspath(p), os.path.abspath(p)))
    return per_group, notes


# ---------------------------------------------------------------------------
# 실행
# ---------------------------------------------------------------------------
def run_one_proc(argv, env):
    """-> (kind, raw_line|None, obj|None, note)  kind: ok / crash / timeout"""
    try:
        p = subprocess.run(argv, capture_output=True, timeout=PROC_TIMEOUT, env=env)
    except subprocess.TimeoutExpired:
        return "timeout", None, None, "시간 초과(%d초)" % PROC_TIMEOUT
    except OSError as e:
        return "crash", None, None, "실행 실패: %s" % e
    tail = p.stderr.decode("utf-8", "replace")[-300:].strip()
    if p.returncode != 0:
        return "crash", None, None, "종료 코드 %d: %s" % (p.returncode, tail)
    out = p.stdout
    if out.endswith(b"\n"):
        out = out[:-1]
    if not out or b"\n" in out:
        return "crash", None, None, "stdout 이 한 줄이 아니다(%d바이트) %s" % (len(p.stdout), tail)
    try:
        obj = json.loads(out.decode("utf-8"))
    except (ValueError, RecursionError):
        return "crash", None, None, "JSON 아님: %s" % out[:200].decode("utf-8", "replace")
    if not isinstance(obj, dict):
        return "crash", None, None, "JSON 객체가 아님"
    return "ok", out, obj, ""


def evaluate(case, py_argv, rs_argv, env):
    case.py_raw = case.rs_raw = case.py_obj = case.rs_obj = None
    case.note = ""
    k, case.py_raw, case.py_obj, note = run_one_proc(py_argv + [case.path], env)
    if k != "ok":
        case.status = "timeout" if k == "timeout" else "py_crash"
        case.note = "py: " + note
        # Rust 도 돌려 저장 사례에 남긴다
    k2, case.rs_raw, case.rs_obj, note2 = run_one_proc(rs_argv + [case.path], env)
    if k != "ok":
        return
    if k2 != "ok":
        case.status = "timeout" if k2 == "timeout" else "rs_crash"
        case.note = "rs: " + note2
        return
    case.status = classify(case)


def strip_cex(obj):
    """errors 의 counterexample 값을 자리표시자로 바꾼 복사본(키 유무는 그대로 비교된다)"""
    o = dict(obj)
    errs = []
    for e in o.get("errors", []):
        if isinstance(e, dict) and CEX_KEY in e:
            e = dict(e)
            e[CEX_KEY] = "<cex>"
        errs.append(e)
    o["errors"] = errs
    return o


def canon(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False)


def results_of(o):
    for ob in o.get("obligations", []):
        for a in ob.get("attempts", []):
            yield a.get("result")


def unknown_involved(py, rs):
    """결과(result)가 다른 attempt 쌍에 "unknown" 이 끼었거나, 개수가 달라 보이는데 unknown 이 있는가"""
    po, ro = py.get("obligations", []), rs.get("obligations", [])
    seen_unknown = "unknown" in set(results_of(py)) or "unknown" in set(results_of(rs))
    if not seen_unknown:
        return False
    if len(po) != len(ro):
        return True
    for a, b in zip(po, ro):
        aa, ba = a.get("attempts", []), b.get("attempts", [])
        if len(aa) != len(ba):
            return True
        for x, y in zip(aa, ba):
            if x.get("result") != y.get("result") and "unknown" in (x.get("result"), y.get("result")):
                return True
    return False


def classify(case):
    if case.py_raw == case.rs_raw:
        return "same"
    if canon(strip_cex(case.py_obj)) == canon(strip_cex(case.rs_obj)):
        return "cex_only"
    if unknown_involved(case.py_obj, case.rs_obj):
        return "flaky_unknown"
    return "diff"


# ---------------------------------------------------------------------------
# diff 요약
# ---------------------------------------------------------------------------
def smt_context(a, b):
    la, lb = a.split("\n"), b.split("\n")
    i = 0
    n = min(len(la), len(lb))
    while i < n and la[i] == lb[i]:
        i += 1
    lo, hi = max(0, i - 3), i + 4
    out = ["    첫 다른 줄 번호 %d (py %d줄, rs %d줄)" % (i + 1, len(la), len(lb))]
    out.append("    py:")
    out += ["      %s%s" % ("> " if lo + k == i else "  ", s) for k, s in enumerate(la[lo:hi])]
    out.append("    rs:")
    out += ["      %s%s" % ("> " if lo + k == i else "  ", s) for k, s in enumerate(lb[lo:hi])]
    return out


def short(v, n=200):
    s = json.dumps(v, ensure_ascii=False, sort_keys=True)
    return s if len(s) <= n else s[:n] + "..."


def diff_summary(py, rs):
    lines = []
    po, ro = py.get("obligations", []), rs.get("obligations", [])
    lines.append("의무 수: py %d / rs %d" % (len(po), len(ro)))
    for k in sorted(set(py) | set(rs)):
        if k in ("errors", "obligations"):
            continue
        if py.get(k) != rs.get(k):
            lines.append("최상위 키 %s 다름: py=%s rs=%s" % (k, short(py.get(k)), short(rs.get(k))))
    pe, re_ = py.get("errors", []), rs.get("errors", [])
    pes, res = strip_cex(py).get("errors", []), strip_cex(rs).get("errors", [])
    if pes != res:
        lines.append("errors 수: py %d / rs %d" % (len(pe), len(re_)))
        for i in range(max(len(pes), len(res))):
            a = pes[i] if i < len(pes) else None
            b = res[i] if i < len(res) else None
            if a != b:
                keys = sorted(set(a or {}) | set(b or {})) if isinstance(a, dict) and isinstance(b, dict) else []
                lines.append("첫 다른 오류 #%d (counterexample 값 제외 비교)" % i)
                if keys:
                    for k in keys:
                        if a.get(k) != b.get(k):
                            lines.append("  키 %s: py=%s rs=%s" % (k, short(a.get(k)), short(b.get(k))))
                else:
                    lines.append("  py=%s rs=%s" % (short(a), short(b)))
                break
    pm = {o.get("seq"): o for o in po}
    rm = {o.get("seq"): o for o in ro}
    seqs = sorted(set(pm) | set(rm), key=lambda x: (x is None, x))
    shown = False
    for sq in seqs:
        a, b = pm.get(sq), rm.get(sq)
        if a is None or b is None:
            lines.append("처음 다른 의무 seq=%s: %s에만 있음" % (sq, "py" if b is None else "rs"))
            lines.append("  있는 쪽: %s" % short({k: v for k, v in (a or b).items() if k != "attempts"}))
            shown = True
            break
        if a == b:
            continue
        lines.append("처음 다른 의무 seq=%s (fn=%s line=%s)" % (sq, a.get("fn"), a.get("line")))
        for k in ("code", "line", "col", "fn", "skipped"):
            if a.get(k) != b.get(k):
                lines.append("  %s: py=%s rs=%s" % (k, short(a.get(k)), short(b.get(k))))
        aa, ba = a.get("attempts", []), b.get("attempts", [])
        if len(aa) != len(ba):
            lines.append("  attempt 수: py %d / rs %d" % (len(aa), len(ba)))
        for j in range(min(len(aa), len(ba))):
            x, y = aa[j], ba[j]
            if x == y:
                continue
            lines.append("  attempt #%d 다름:" % j)
            for k in ("lemmas", "result"):
                if x.get(k) != y.get(k):
                    lines.append("    %s: py=%s rs=%s" % (k, short(x.get(k)), short(y.get(k))))
            if x.get("smt2") != y.get("smt2"):
                lines.append("    smt2 다름:")
                lines += smt_context(str(x.get("smt2")), str(y.get("smt2")))
            break
        shown = True
        break
    if not shown and not any(l.startswith("첫 다른 오류") for l in lines):
        lines.append("(구조 요약에서 차이를 찾지 못함: 키 순서·공백 등 바이트 차이일 수 있다)")
    return lines


def case_summary(case):
    lines = ["group: %s" % case.group, "name: %s" % case.name, "status: %s" % case.status]
    if case.flaky_first:
        lines.append("처음 flaky_unknown 으로 판정돼 직렬 재시도 했다")
    if case.note:
        lines.append("note: " + case.note)
    if case.status == "diff":
        lines += diff_summary(case.py_obj, case.rs_obj)
    return lines


def save_case(save_dir, seq, case):
    d = os.path.join(save_dir, case.group, "%04d_%s" % (seq, safe(case.name)))
    os.makedirs(d, exist_ok=True)
    with open(case.path, "rb") as fh, open(os.path.join(d, "input.pruv"), "wb") as out:
        out.write(fh.read())
    for fn, raw in (("py.json", case.py_raw), ("rs.json", case.rs_raw)):
        if raw is not None:
            with open(os.path.join(d, fn), "wb") as out:
                out.write(raw + b"\n")
    with open(os.path.join(d, "diff.txt"), "wb") as out:
        out.write(("\n".join(case_summary(case)) + "\n").encode("utf-8"))


# ---------------------------------------------------------------------------
def default_rs_path():
    base = os.path.join(ROOT, "pruvc-rs", "target", "release", "pruv-trace-dump")
    if not os.path.isfile(base) and os.path.isfile(base + ".exe"):
        return base + ".exe"
    return base


def default_python(explicit):
    want = explicit or os.environ.get("PRUV_PYTHON")
    if want:
        return want
    for r in (".venv/bin/python", ".venv/Scripts/python.exe"):
        p = os.path.join(ROOT, r)
        if os.path.isfile(p):
            return p
    return sys.executable


def main(argv):
    ap = argparse.ArgumentParser(prog="diff_trace.py", description="Python/Rust 검증기 trace 비교")
    ap.add_argument("--rs-path", default=None, help="pruv-trace-dump 경로")
    ap.add_argument("--python", default=None, help="정본을 돌릴 Python (기본 .venv/bin/python)")
    ap.add_argument("--only", default=None, help="그룹(쉼표 목록): " + " ".join(ALL_GROUPS))
    ap.add_argument("--seeds", default="41,56,57")
    ap.add_argument("--fuzz-count", type=int, default=40)
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) // 2))
    ap.add_argument("--save-dir", default=None)
    ap.add_argument("--input", action="append", default=[], metavar="FILE", help="input 그룹 파일(여러 번 가능)")
    args = ap.parse_args(argv)

    args.seeds = [parse_seed(t) for t in args.seeds.split(",") if t.strip() != ""]
    if args.fuzz_count < 0 or args.jobs < 1:
        ap.error("--fuzz-count 는 0 이상, --jobs 는 1 이상이어야 한다")
    if args.only is None:
        selected = ["input"] if args.input else [g for g in ALL_GROUPS if g != "input"]
    else:
        selected = [t.strip() for t in args.only.split(",") if t.strip()]
        bad = [t for t in selected if t not in ALL_GROUPS]
        if bad or not selected:
            ap.error("--only: 알 수 없는 그룹 %s (가능: %s)" % (bad, " ".join(ALL_GROUPS)))
    if "input" in selected and not args.input:
        ap.error("input 그룹에는 --input FILE 이 필요하다")
    for p in args.input:
        if not os.path.isfile(p):
            print("오류: --input 파일이 없다: %s" % p, file=sys.stderr)
            return 2

    rs = os.path.abspath(args.rs_path) if args.rs_path else default_rs_path()
    if not os.path.isfile(rs) or not os.access(rs, os.X_OK):
        print("오류: Rust 바이너리를 찾을 수 없거나 실행할 수 없다: %s\n"
              "  먼저 빌드하거나 --rs-path 로 pruv-trace-dump 경로를 준다." % rs, file=sys.stderr)
        return 2
    py = default_python(args.python)
    if os.sep in py or "/" in py:
        if not os.path.isfile(py):
            print("오류: Python 을 찾을 수 없다: %s" % py, file=sys.stderr)
            return 2
    adapter = os.path.join(HERE, "diff_py_adapter.py")
    if not os.path.isfile(adapter):
        print("오류: %s 가 없다" % adapter, file=sys.stderr)
        return 2
    py_argv = [py, adapter, "trace"]
    rs_argv = [rs]
    env = dict(os.environ)
    env.setdefault("PYTHONUTF8", "1")

    t0 = time.time()
    with tempfile.TemporaryDirectory(prefix="diff_trace_") as tmp:
        per_group, notes = build_cases(set(selected), args, tmp)
        all_cases = [c for g in ALL_GROUPS for c in per_group[g]]

        def work(c):
            evaluate(c, py_argv, rs_argv, env)
            return c

        with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as ex:
            list(ex.map(work, all_cases))

        # flaky_unknown 재시도: 직렬(--jobs 1)
        flaky = [c for c in all_cases if c.status == "flaky_unknown"]
        for c in flaky:
            c.flaky_first = True
            evaluate(c, py_argv, rs_argv, env)
            if c.status in ("same", "cex_only"):
                c.status = "flaky_unknown"     # 재시도로 풀림
            elif c.status == "flaky_unknown":
                c.status = "diff"              # 그래도 다름
            c.note = (c.note + " " if c.note else "") + "(재시도 후)"

        diffs = [c for c in all_cases if c.status == "diff"]
        crashes = [c for c in all_cases if c.status in ("py_crash", "rs_crash", "timeout")]
        saved = 0
        if args.save_dir:
            for c in diffs + crashes:
                save_case(args.save_dir, saved, c)
                saved += 1

        print("rs: %s" % rs)
        print("py: %s" % py)
        print("jobs: %d" % args.jobs)
        print("")
        print("%-12s" % "group" + "".join("%15s" % c for c in COLS))
        total = collections.Counter()
        for g in ALL_GROUPS:
            if g not in selected:
                continue
            st = collections.Counter(c.status for c in per_group[g])
            st["inputs"] = len(per_group[g])
            print("%-12s" % g + "".join("%15d" % st[c] for c in COLS))
            total.update(st)
        print("%-12s" % "TOTAL" + "".join("%15d" % total[c] for c in COLS))
        print("(cex_only %d건은 통과로 친다; flaky_unknown 은 직렬 재시도로 풀린 수)" % total["cex_only"])
        for n in notes:
            print(n)

        # 집계: 정본(py) 출력 기준
        n_obl = n_att = n_retry = n_skipped = 0
        res = collections.Counter()
        codes = collections.Counter()
        stages = collections.Counter()
        for c in all_cases:
            o = c.py_obj
            if not o:
                continue
            for ob in o.get("obligations", []):
                n_obl += 1
                if ob.get("skipped"):
                    n_skipped += 1
                for a in ob.get("attempts", []):
                    n_att += 1
                    if a.get("lemmas"):
                        n_retry += 1
                    res[a.get("result")] += 1
            for e in o.get("errors", []):
                if isinstance(e, dict):
                    codes[e.get("code")] += 1
                    stages[e.get("stage")] += 1
        print("")
        print("== 정본(py) 기준 집계 ==")
        print("의무 %d (skipped %d), attempt %d, 재시도(lemmas true) %d" % (n_obl, n_skipped, n_att, n_retry))
        print("결과별: sat=%d unsat=%d unknown=%d 그 밖=%d" % (
            res["sat"], res["unsat"], res["unknown"],
            sum(v for k, v in res.items() if k not in ("sat", "unsat", "unknown"))))
        print("오류 code %d종, %d건:" % (len(codes), sum(codes.values())))
        for code, n in sorted(codes.items(), key=lambda kv: (-kv[1], str(kv[0]))):
            print("  %-24s %d" % (code, n))
        print("오류 stage: %s" % (", ".join("%s=%d" % kv for kv in sorted(stages.items(), key=lambda kv: str(kv[0]))) or "없음"))

        if diffs:
            print("")
            print("== diff (최대 %d개 / 전체 %d) ==" % (MAX_SHOWN, len(diffs)))
            for c in diffs[:MAX_SHOWN]:
                print("[%s] %s" % (c.group, c.name))
                for ln in diff_summary(c.py_obj, c.rs_obj):
                    print("  " + ln)
        if crashes:
            print("")
            print("== crash/timeout (최대 %d개 / 전체 %d) ==" % (MAX_SHOWN, len(crashes)))
            for c in crashes[:MAX_SHOWN]:
                print("[%s] %s: %s %s" % (c.group, c.name, c.status, c.note))
        if args.save_dir:
            print("")
            print("저장: 사례 %d개 -> %s" % (saved, args.save_dir))
        print("")
        print("걸린 시간: %.1f초" % (time.time() - t0))

    clean = all(total[k] == 0 for k in ("diff", "py_crash", "rs_crash", "timeout"))
    print("결과: %s" % ("성공" if clean else "실패"))
    return 0 if clean else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
