"""Explicit Stage 5 source mutants, with G5 truth and worst-configuration classification."""
import sys
sys.dont_write_bytecode = True
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import tempfile
import run as G

CONFIGS = [(c, b) for c in ("py", "rs") for b in ("rust", "llvm")]
CHECK_STAGES = ("parse", "type", "effect")
UNDECIDED_CODES = ("inference_timeout", "verify_unknown", "solver_unknown", "solver_timeout")
RJ_V, RJ_C, ACC, WBP, UNK, TMO, CRA, UNS, UNE = ("rejected_verify", "rejected_checker", "accepted_correct",
                                             "wrong_but_proved", "unknown", "timeout", "crash", "unsupported", "unexecuted")
SEVERITY = [WBP, CRA, TMO, UNS, UNK, UNE, ACC, RJ_C, RJ_V]
UNRESOLVED = (CRA, TMO, UNS, UNK, UNE)
# Exact, deliberate edits. Cost-header mutants bypass only the frozen cost check.
EXPLICIT = [
('q01','wrong_unit','contract','spent == i * (n + 1)','spent == i * n'),
('q01','wrong_unit','contract','spent == i * (n + 1) + 1 + j','spent == i * (n + 1) + j'),
('q01','wrong_unit','contract','spent == i * (n + 1) + 1 + j','spent == i * (n + 1) + 1 + 2 * j'),
('q02','wrong_unit','contract','spent == len(src) + 1 + 2 * i','spent == len(src) + 1 + i'),
('q02','wrong_unit','contract','spent == len(src) + 1 + 2 * i','spent == len(src) + 2 * i'),
('q02','wrong_unit','contract','spent == len(src) + 1 + 2 * i','spent == 1 + 2 * i'),
('q01','missing_loop','incorrect','while j < n','while j < 0'),
('q01','missing_loop','incorrect','while i < n','while i < 0'),
('q02','missing_loop','incorrect','while i < len(src)','while i < 0'),
('q01','missing_body','incorrect','total = total + 1;',''),
('q02','missing_body','incorrect','dst[i] = twice(src[i]);',''),
('q02','extra_call','incorrect','dst[i] = twice(src[i]);','let unused: i64 = twice(0); dst[i] = twice(src[i]);'),
('q02','extra_call','incorrect','return dst;','let unused: i64 = twice(0); return dst;'),
('q02','extra_call','incorrect','let mut i: i64 = 0;','let unused: i64 = twice(1); let mut i: i64 = 0;'),
('q01','bound_minus_one','incorrect','cost len(a) * (len(a) + 1)','cost len(a) * (len(a) + 1) - 1'),
('q02','bound_minus_one','incorrect','cost 3 * len(src) + 1','cost 3 * len(src) + 1 - 1'),
('q01','wrong_multiplier','incorrect','cost len(a) * (len(a) + 1)','cost len(a) * len(a)'),
('q01','wrong_multiplier','incorrect','cost len(a) * (len(a) + 1)','cost len(a)'),
('q02','wrong_multiplier','incorrect','cost 3 * len(src) + 1','cost 2 * len(src) + 1'),
('q02','wrong_multiplier','incorrect','cost 3 * len(src) + 1','cost len(src) + 1'),
('q02','extra_alloc','incorrect','return dst;','let unused: [i64] = alloc(0, 0); return dst;'),
('q02','extra_alloc','incorrect','return dst;','let unused: [i64] = alloc(len(src), 0); return dst;'),
('q02','extra_copy','incorrect','return dst;','let unused: [i64] = copy(src); return dst;'),
('q02','extra_copy','incorrect','return dst;','let unused: [i64] = copy(dst); return dst;'),
('q01','loop_plus_one','incorrect','while i < n','while i < n + 1'),
('q01','loop_plus_one','incorrect','while j < n','while j < n + 1'),
('q02','loop_plus_one','incorrect','while i < len(src)','while i < len(src) + 1'),
('q01','wrong_value','incorrect','total = total + 1;','total = total + 2;'),
('q01','wrong_value','incorrect','total = total + 1;','total = total + 3;'),
('q01','wrong_value','incorrect','total = total + 1;','total = total - 1;'),
('q01','wrong_value','incorrect','total = total + 1;','total = total + i;'),
('q01','wrong_value','incorrect','total = total + 1;','total = total + j;'),
('q01','wrong_value','incorrect','return total;','return total + 1;'),
('q01','wrong_value','incorrect','return total;','return total - 1;'),
('q01','wrong_value','incorrect','return total;','return 0;'),
('q02','wrong_value','incorrect','return x * 2;','return x;'),
('q02','wrong_value','incorrect','return x * 2;','return 0;'),
('q02','wrong_value','incorrect','return x * 2;','return 1;'),
('q02','wrong_value','incorrect','return x * 2;','return -1;'),
('q02','wrong_value','incorrect','return x * 2;','return x * 3;'),
('q02','wrong_value','incorrect','return x * 2;','return x + 2;'),
('q02','wrong_value','incorrect','return x * 2;','return x * -2;'),
('q02','wrong_value','incorrect','return x * 2;','return x * 2 + 1;'),
('q02','wrong_value','incorrect','dst[i] = twice(src[i]);','dst[i] = twice(0);'),
('q02','wrong_index','incorrect','dst[i] = twice(src[i]);','dst[i] = twice(src[0]);'),
('q02','wrong_index','incorrect','dst[i] = twice(src[i]);','dst[0] = twice(src[i]);'),
('q02','wrong_value','incorrect','dst[i] = twice(src[i]);','dst[i] = src[i];'),
('q02','wrong_value','incorrect','dst[i] = twice(src[i]);','dst[i] = 0;'),
('q02','weak_contract','weak','ensures result == x * 2','ensures true'),
('q02','equivalent','correct','return x * 2;','return x + x;'),
]

def catalogue():
    items = []
    for index, (pid, op, intent, old, new) in enumerate(EXPLICIT, 1):
        base = (G.HERE / 'solutions' / pid / 'root.pruv').read_text()
        assert base.count(old) == (2 if old == 'spent == i * (n + 1)' else 1), (op, old, base.count(old))
        source = base.replace(old, new, 1)
        items.append(dict(id=f'm{index:03}', pid=pid, operator=op, intent=intent, kind='explicit',
                          desc=op + ': ' + new, edit=[dict(file='root.pruv', old=old, new=new)],
                          source=source, sha256=hashlib.sha256(source.encode()).hexdigest()))
    assert len({i['sha256'] for i in items}) == len(items)
    return items


def config_class(r):
    """(class, detail) of one grade_one result."""
    st = r.get("status")
    if st == "pruv_error":
        rc, errs = r.get("rc"), [e for e in (r.get("errors") or []) if isinstance(e, dict)]
        if rc == -1:
            return TMO, "compiler timeout"
        if rc == -2:
            return CRA, "compiler could not be started"
        if not errs:
            return CRA, "exit %s without a diagnostic: %s" % (rc, (r.get("stderr") or "")[-120:])
        e = errs[0]
        stage, code = e.get("stage"), e.get("code")
        if stage == "grader":
            return CRA, "harness: %s" % e.get("message")
        if rc != 1 or any(x.get("stage") == "internal" for x in errs):
            return CRA, "internal error: %s" % (e.get("message") or code)
        if any(x.get("code") in UNDECIDED_CODES for x in errs):
            return UNK, "%s/%s" % (stage, code)
        if any(x.get("stage") == "codegen" or "unsupported" in str(x.get("code")) for x in errs):
            return UNS, "%s/%s" % (stage, code)
        return (RJ_C if stage in CHECK_STAGES else RJ_V), "%s/%s" % (stage, code)
    if st == "ok":
        return ACC, "tests pass"
    if st == "wrong":
        return WBP, "accepted but wrong: %s" % (r.get("first_failure") or r.get("first_panic") or
                                                 "exit %s" % r.get("exit_code"))
    if st == "timeout":
        return TMO, "test run timeout"
    if st == "compile_error":
        return UNE, "generated code did not build: %s" % (r.get("error") or "")[:100].replace("\n", " ")
    return CRA, "status %s" % st

def measure(item):
    with tempfile.TemporaryDirectory(prefix=item['id'] + '_', dir=G.WORK) as tmp:
        src = Path(tmp) / 'root.pruv'
        src.write_text(item['source'])
        truth_run = G.grade_one(src, item['pid'], 'rs', 'rust', ['--no-verify'], enforce_header=False)
        status = truth_run['status']
        truth = {'ok': 'correct', 'wrong': 'incorrect', 'timeout': 'unknown'}.get(status, 'unknown')
        if status == 'pruv_error' and truth_run.get('rc') == 1 and truth_run.get('errors'):
            truth = 'not_compilable'
        runs = {}
        for compiler, backend in CONFIGS:
            r = G.grade_one(src, item['pid'], compiler, backend, enforce_header=False)
            cls, detail = config_class(r)
            if truth == 'incorrect' and cls == ACC:
                cls, detail = WBP, 'verified despite safe-mode behavioral/cost counterexample'
            runs[compiler + '-' + backend] = dict(class_=cls, detail=detail, grader=r)
            runs[compiler + '-' + backend]['class'] = runs[compiler + '-' + backend].pop('class_')
        classes = [r['class'] for r in runs.values()]
        return {k: v for k, v in item.items() if k != 'source'} | dict(
            truth=truth, truth_detail=truth_run, runs=runs,
            config_diff=len(set(classes)) > 1, **{'class': min(classes, key=SEVERITY.index)})


INTENT_TRUTH = {"incorrect": ("incorrect",), "weak": ("correct",), "contract": ("correct",), "correct": ("correct",)}


def summarize(results):
    inc = [r for r in results if r["truth"] == "incorrect"]
    s = {"total": len(results), "incorrect": len(inc),
         "correct": sum(r["truth"] == "correct" for r in results),
         "not_compilable": sum(r["truth"] == "not_compilable" for r in results),
         "truth_unknown": sum(r["truth"] == "unknown" for r in results)}
    s["incorrect_by_class"] = {c: sum(r["class"] == c for r in inc) for c in SEVERITY}
    s["rejected_per_class"] = {c: s["incorrect_by_class"][c] for c in (RJ_V, RJ_C)}
    s["incorrect_by_config"] = {}
    for comp, backend in CONFIGS:
        k = "%s-%s" % (comp, backend)
        s["incorrect_by_config"][k] = {c: sum(r["runs"][k]["class"] == c for r in inc) for c in SEVERITY}
    s["all_by_class"] = {c: sum(r["class"] == c for r in results) for c in SEVERITY}
    wbp = [r["id"] for r in results if any(v["class"] == WBP for v in r["runs"].values())]
    s["wrong_but_proved"] = len(wbp)
    s["wrong_but_proved_ids"] = wbp
    s["unresolved_incorrect"] = [{"id": r["id"], "class": r["class"], "detail": [v["detail"] for v in r["runs"].values()
                                                                                   if v["class"] in UNRESOLVED][:1]}
                                 for r in inc if r["class"] in UNRESOLVED]
    s["incorrect_accepted_with_passing_tests"] = [r["id"] for r in inc if r["class"] == ACC]
    s["config_diffs"] = [r["id"] for r in results if r["config_diff"]]
    s["by_intent"] = {}
    for r in results:
        s["by_intent"][r["intent"]] = s["by_intent"].get(r["intent"], 0) + 1
    s["intent_mismatch"] = [{"id": r["id"], "intent": r["intent"], "truth": r["truth"]} for r in results
                            if r["intent"] in INTENT_TRUTH and r["truth"] not in INTENT_TRUTH[r["intent"]]]
    # contract mutants (behaviour unchanged, contract or annotation falsified/weakened) must not be accepted
    s["contract_mutants_accepted"] = [r["id"] for r in results
                                      if r["intent"] == "contract" and any(v["class"] in (ACC, WBP)
                                                                           for v in r["runs"].values())]
    s["contract_mutants_rejected"] = sum(r["intent"] == "contract" and r["class"] in (RJ_V, RJ_C) for r in results)
    # weak-contract mutants are recorded separately (accepted or rejected is informational)
    weak = [r for r in results if r["intent"] == "weak"]
    s["weak_contract"] = {"total": len(weak), "rejected_ids": [r["id"] for r in weak if r["class"] in (RJ_V, RJ_C)],
                          "accepted_ids": [r["id"] for r in weak if r["class"] == ACC]}
    # correct mutants the verifier rejected: false rejections (incompleteness), informational only
    s["correct_rejected_ids"] = [r["id"] for r in results
                                 if r["intent"] == "correct" and r["class"] in (RJ_V, RJ_C)]
    s["correct_accepted_ids"] = [r["id"] for r in results if r["intent"] == "correct" and r["class"] == ACC]
    ops = {}
    for r in results:
        o = ops.setdefault(r["operator"], {"total": 0, "incorrect": 0, "rejected": 0})
        o["total"] += 1
        o["incorrect"] += r["truth"] == "incorrect"
        o["rejected"] += r["class"] in (RJ_V, RJ_C)
    s["by_operator"] = ops
    s["incorrect_by_fault_kind"] = {k: sum(r["truth"] == "incorrect" and r["operator"] == k for r in results)
                                    for k in sorted({r["operator"] for r in results})}
    return s


def main():
    p = argparse.ArgumentParser(__doc__)
    p.add_argument('out', nargs='?', type=Path, default=G.HERE / 'results/mutants.json')
    p.add_argument('--jobs', type=int, default=8)
    p.add_argument('--self-test', action='store_true')
    p.add_argument('--list', action='store_true')
    p.add_argument('--limit', type=int)
    a = p.parse_args()
    items = catalogue()
    if a.self_test:
        assert sum(i['intent'] == 'incorrect' for i in items) >= 40
        assert {'wrong_unit','missing_loop','extra_call','bound_minus_one','wrong_multiplier',
                'extra_alloc','extra_copy','loop_plus_one'} <= {i['operator'] for i in items}
        for item in items:
            assert 'cost ' in item['source']
        assert G.ref_grid([1, 2]) == 4
        assert G.ref_compute([-1000, 0, 1000]) == [-2000, 0, 2000]
        print('self-test: PASS;', len(items), 'unique explicit mutants')
        return 0
    if a.list:
        for item in items:
            print(item['id'], item['pid'], item['intent'], item['operator'])
        return 0
    if a.limit:
        items = items[:a.limit]
    def task(item):
        try:
            row = measure(item)
        except Exception as e:
            row = {k: v for k, v in item.items() if k != 'source'}
            row.update(truth='unknown', truth_detail=repr(e), config_diff=False,
                       runs={c+'-'+b: {'class': CRA, 'detail': repr(e), 'grader': {}} for c,b in CONFIGS},
                       **{'class': CRA})
        print(row['id'], row['truth'], row['class'], flush=True)
        return row
    with ThreadPoolExecutor(max_workers=max(1, a.jobs)) as pool:
        rows = list(pool.map(task, items))
    summary = summarize(rows)
    summary['all_by_fault_kind'] = {k: sum(i['operator'] == k for i in rows) for k in sorted({i['operator'] for i in rows})}
    summary['static_unrejected'] = [i['id'] for i in rows if i['intent'] == 'static' and
                                  any(r['class'] != RJ_C for r in i['runs'].values())]
    a.out.write_text(json.dumps(dict(tools=G.G2.COMPILERS, summary=summary, items=rows), indent=2))
    print(json.dumps(summary, indent=2))
    return int(bool(summary['wrong_but_proved'] or summary['unresolved_incorrect'] or
                    summary['incorrect_accepted_with_passing_tests'] or summary['contract_mutants_accepted'] or
                    summary['static_unrejected'] or summary['truth_unknown'] or summary['intent_mismatch'] or
                    (not a.limit and summary['incorrect'] < 40)))


if __name__ == '__main__':
    sys.exit(main())
