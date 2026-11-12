"""Explicit G7 source mutants, with G5 truth and worst-configuration classification."""
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
# Exact source edits, never random/regex generation. Public contracts stay fixed.
# pid, fault kind, intent, old text, replacement
EXPLICIT = [
    ('q01', 'wrong_value', 'incorrect', 'b[i] = 255;', 'b[i] = 0;'),
    ('q01', 'wrong_value', 'incorrect', 'b[i] = 255;', 'b[i] = 1;'),
    ('q01', 'wrong_value', 'incorrect', 'b[i] = 255;', 'b[i] = 127;'),
    ('q01', 'wrong_value', 'incorrect', 'b[i] = 255;', 'b[i] = 254;'),
    ('q01', 'wrong_value', 'incorrect', 'b[i] = 255;', 'b[i] = b[i];'),
    ('q01', 'wrong_value', 'incorrect', 'b[i] = 255;', 'b[i] = c;'),
    ('q01', 'wrong_value', 'incorrect', 'b[i] = 255;', 'b[i] = (b[i] + c) % 256;'),
    ('q01', 'wrong_value', 'incorrect', '    b[i] = x;', '    b[i] = 0;'),
    ('q01', 'wrong_value', 'incorrect', '    b[i] = x;', '    b[i] = 1;'),
    ('q01', 'wrong_value', 'incorrect', '    b[i] = x;', '    b[i] = 255;'),
    ('q01', 'wrong_value', 'incorrect', '    b[i] = x;', '    b[i] = b[i];'),
    ('q01', 'wrong_value', 'incorrect', '    b[i] = x;', '    b[i] = c;'),
    ('q01', 'wrong_value', 'incorrect', '    b[i] = x;', '    b[i] = (x + 1) % 256;'),
    ('q01', 'wrong_value', 'incorrect', '    b[i] = x;', '    b[i] = (x + 255) % 256;'),
    ('q01', 'wrong_value', 'incorrect', '  b[i] = x;\n}', '  b[i] = 0;\n}'),
    ('q01', 'wrong_value', 'incorrect', '  b[i] = x;\n}', '  b[i] = 1;\n}'),
    ('q01', 'wrong_value', 'incorrect', '  b[i] = x;\n}', '  b[i] = 255;\n}'),
    ('q01', 'wrong_value', 'incorrect', '  b[i] = x;\n}', '  b[i] = b[i];\n}'),
    ('q01', 'wrong_value', 'incorrect', '  b[i] = x;\n}', '  b[i] = c;\n}'),
    ('q01', 'wrong_value', 'incorrect', '  b[i] = x;\n}', '  b[i] = (x + 1) % 256;\n}'),
    ('q01', 'wrong_value', 'incorrect', '  b[i] = x;\n}', '  b[i] = (x + 255) % 256;\n}'),
    ('q01', 'wrong_index', 'incorrect', 'b[i] = 255;', 'b[0] = 255;'),
    ('q01', 'wrong_index', 'incorrect', '    b[i] = x;', '    b[0] = x;'),
    ('q01', 'wrong_index', 'incorrect', '  b[i] = x;\n}', '  b[0] = x;\n}'),
    ('q01', 'missing_store', 'incorrect', 'b[i] = 255;', ''),
    ('q01', 'missing_store', 'incorrect', '    b[i] = x;', ''),
    ('q01', 'missing_store', 'incorrect', '  b[i] = x;\n}', '}'),
    ('q01', 'wrong_target', 'incorrect', 'bump_sat(inout b, i, c);', 'bump_wrap(inout b, i, c);'),
    ('q01', 'wrong_target', 'incorrect', 'add_range_wrap(inout right, lo, hi, c);', 'add_range_sat(inout right, lo, hi, c);'),
    ('q01', 'old_current', 'incorrect', '  b[i] = x;\n}', '  b[i] = x;\n  b[i] = (b[i] + c) % 256;\n}'),
    ('q01', 'false_frame', 'incorrect', '  let mut i: i64 = lo;\n  while i < hi', '  if lo > 0 { b[0] = (b[0] + 1) % 256; }\n  let mut i: i64 = lo;\n  while i < hi'),
    ('q02', 'wrong_value', 'incorrect', 'dst[i] = src[i] * 2;', 'dst[i] = src[i];'),
    ('q02', 'wrong_value', 'incorrect', 'dst[i] = src[i] * 2;', 'dst[i] = 0;'),
    ('q02', 'wrong_value', 'incorrect', 'dst[i] = src[i] * 2;', 'dst[i] = 1;'),
    ('q02', 'wrong_value', 'incorrect', 'dst[i] = src[i] * 2;', 'dst[i] = src[i] * 3;'),
    ('q02', 'wrong_value', 'incorrect', 'dst[i] = src[i] * 2;', 'dst[i] = src[i] + 2;'),
    ('q02', 'wrong_index', 'incorrect', 'dst[i] = src[i] * 2;', 'dst[i] = src[0] * 2;'),
    ('q02', 'wrong_value', 'incorrect', 'dst[i] = src[i] * 2;', 'dst[i] = src[i] * -2;'),
    ('q02', 'wrong_value', 'incorrect', 'dst[i] = src[i] - src[0];', 'dst[i] = src[i];'),
    ('q02', 'wrong_value', 'incorrect', 'dst[i] = src[i] - src[0];', 'dst[i] = src[0];'),
    ('q02', 'wrong_value', 'incorrect', 'dst[i] = src[i] - src[0];', 'dst[i] = 0;'),
    ('q02', 'wrong_value', 'incorrect', 'dst[i] = src[i] - src[0];', 'dst[i] = src[0] - src[i];'),
    ('q02', 'wrong_value', 'incorrect', 'dst[i] = src[i] - src[0];', 'dst[i] = src[i] + src[0];'),
    ('q02', 'wrong_value', 'incorrect', 'dst[i] = src[i] - src[0];', 'dst[i] = src[i] - 1;'),
    ('q02', 'missing_store', 'incorrect', 'dst[i] = src[i] * 2;', ''),
    ('q02', 'missing_store', 'incorrect', 'dst[i] = src[i] - src[0];', ''),
    ('q02', 'wrong_target', 'incorrect', 'scale(inout left, src);', 'difference(inout left, src);'),
    ('q02', 'wrong_target', 'incorrect', 'difference(inout right, src);', 'scale(inout right, src);'),
    ('q02', 'missing_branch', 'incorrect', 'scale(inout left, src);', 'noop(inout left, src);'),
    ('q02', 'missing_branch', 'incorrect', 'difference(inout right, src);', 'noop(inout right, src);'),
    ('q02', 'old_current', 'incorrect', 'dst[i] = src[i] * 2;', 'dst[i] = dst[i] * 2;'),
    ('q01', 'duplicate_writable', 'static', 'add_range_wrap(inout right, lo, hi, c);', 'add_range_wrap(inout left, lo, hi, c);'),
    ('q02', 'duplicate_writable', 'static', 'difference(inout right, src);', 'difference(inout left, src);'),
    ('q02', 'effect_leakage', 'static', 'fn scale(inout dst: [i64], src: [i64]) -> ()', 'fn scale(inout dst: [i64], src: [i64]) -> () ! io'),
    ('q02', 'foreign_leakage', 'static', 'dst[i] = src[i] * 2;', 'let hidden: i64 = foreign_min(1, 2);\n    dst[i] = src[i] * 2;'),
    ('q01', 'false_frame_contract', 'contract', 'ensures b[i] == (old(b)[i] + c) % 256', 'ensures b[i] == old(b)[i]'),
    ('q01', 'old_current_contract', 'contract', 'ensures b[i] == (old(b)[i] + c) % 256', 'ensures b[i] == (b[i] + c) % 256'),
    ('q02', 'weak_contract', 'weak', '  ensures forall k in 0..len(dst): dst[k] == src[k] * 2', '  ensures len(dst) == len(src)'),
    ('q02', 'equivalent', 'correct', 'dst[i] = src[i] * 2;', 'dst[i] = src[i] + src[i];'),
]

def catalogue():
    items = []
    for index, (pid, op, intent, old, new) in enumerate(EXPLICIT, 1):
        base = (G.HERE / 'solutions' / pid / 'root.pruv').read_text()
        count = base.count(old)
        assert count == (2 if op == 'false_frame' else 1), (op, old, count)
        source = base.replace(old, new, 1)
        if op == 'missing_branch':
            source += '\nfn noop(inout dst: [i64], src: [i64]) -> () {}\n'
        if op == 'foreign_leakage':
            source = 'trusted rust fn foreign_min(a: i64, b: i64) -> i64 ensures true = "::std::cmp::min";\n' + source
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
        truth_run = G.grade_one(src, item['pid'], 'rs', 'rust', ['--no-verify'])
        status = truth_run['status']
        truth = {'ok': 'correct', 'wrong': 'incorrect', 'timeout': 'incorrect'}.get(status, 'unknown')
        if status == 'pruv_error' and truth_run.get('rc') == 1 and truth_run.get('errors'):
            truth = 'not_compilable'
        runs = {}
        for compiler, backend in CONFIGS:
            r = G.grade_one(src, item['pid'], compiler, backend)
            cls, detail = config_class(r)
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
        assert {'wrong_target','wrong_index','wrong_value','missing_branch','missing_store',
                'false_frame','old_current','duplicate_writable','effect_leakage','foreign_leakage'} <= {i['operator'] for i in items}
        for item in items:
            text = item['source']
            assert G.HEADERS[item['pid']] in ' '.join(text.split())
            assert 'par {' in text
        assert G.ref_transform([254, 1], [255, 2], 0, 1, 2, 0) == [255, 1]
        assert G.ref_transform([254, 1], [255, 2], 0, 1, 2, 1) == [1, 2]
        assert G.ref_compute([3, -4], 1) == [0, -7]
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
                    summary['static_unrejected'] or summary['truth_unknown'] or
                    (not a.limit and summary['incorrect'] < 40)))


if __name__ == '__main__':
    sys.exit(main())
