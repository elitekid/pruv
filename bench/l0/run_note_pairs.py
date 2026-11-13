#!/usr/bin/env python3
"""Cross-check Lair addNote / addMissing and their helper padded (src/documents/context.ts).

Each case is a draft list with n0 texts, an optional key list beside it (has, pre) and a run of calls, each with a
key or none. The host numbers the keys ({"key": "k7"} is 7, null is 0) and sends n0, has, pre and the call keys to
Pruv (note_pairs.pruv: [0] when the key list stays absent, else [1, final key list...]). Pruv's result is compared
with an independent oracle written from the ensures, not from the TS loop (absent unless the list existed or some
call carried a key; with no calls the old entries as they are; otherwise the old entries, nulls up to the old text
count, then every call's key), and with the
TypeScript copy (note_pairs.mjs: verbatim padded, addNote and addMissing, run in Lair's Electron when available),
whose final text list is checked too. Inputs: no calls (an existing shorter key list then stays short), no keys at all, a key only on the last call, an existing
key list that is shorter, equal or longer than the text list (longer is never built by addNote alone), a 100,000
text list and a 50,000 entry key list, and random runs of up to 12 calls over lists of up to 8 texts.
"""
import argparse
import json
import random
import sys

sys.dont_write_bytecode = True

NAME = 'note_pairs'

HARNESS = '''#![allow(dead_code, unused_imports)]
#[path = "@SOL@"] mod sol;
use std::io::{self, BufRead, Write};
fn main() {
  let out = io::stdout(); let mut out = out.lock();
  for line in io::stdin().lock().lines() {
    let line = line.unwrap();
    let f: Vec<i64> = line.split(' ').skip(1).map(|x| x.parse().unwrap()).collect();
    let p = f[2] as usize;
    let m = f[3] as usize;
    let r = sol::note_pairs(f[0], f[1], &f[4..4 + p], &f[4 + p..4 + p + m]);
    let s: Vec<String> = r.iter().map(|x| x.to_string()).collect();
    writeln!(out, "{}", s.join(" ")).unwrap();
  }
}
'''


def oracle(n0, has, pre, keys):
    if not has and not any(keys):
        return [0]
    return [1] + pre + [0] * (max(0, n0 - len(pre)) if keys else 0) + keys


def cases(n, seed):
    rows = [(0, 0, [], []), (0, 0, [], [0]), (0, 0, [], [3]), (2, 0, [], [0, 0, 0]), (2, 0, [], [0, 0, 5]),
            (3, 0, [], [4]), (0, 1, [], []), (3, 1, [], []), (4, 1, [2], []), (0, 1, [], [0]), (3, 1, [], [0]), (3, 1, [1], [2]),
            (3, 1, [1, 0, 2], [0, 7]), (1, 1, [1, 2, 3], [4]), (0, 1, [5, 5], [0, 0]), (2, 1, [0, 0], [0]),
            (100000, 0, [], [0] * 5 + [9]), (10, 1, [1] * 50000, [2, 0]), (0, 0, [], [1000000000]),
            (5, 1, [1000000000], [1000000000, 0])]
    edges = len(rows)
    r = random.Random(seed)
    for _ in range(n):
        n0 = r.randrange(0, 9)
        has = int(r.random() < 0.4)
        pre = [r.choice([0, 0, r.randrange(1, 6)]) for _ in range(r.randrange(0, n0 + 3))] if has else []
        density = r.choice([0.0, 0.1, 0.5, 1.0])
        keys = [r.randrange(1, 6) if r.random() < density else 0 for _ in range(r.randrange(0, 13))]
        rows.append((n0, has, pre, keys))
    return rows, edges


def ts_input(i, case):
    n0, has, pre, keys = case
    key = lambda k: {'key': 'k%d' % k} if k else None
    return dict(f='addNote' if i % 2 == 0 else 'addMissing', list=['t%d' % k for k in range(n0)],
                pairs=[key(k) for k in pre] if has else None,
                calls=[['c%d' % j, key(k)] for j, k in enumerate(keys)])


def ts_result(case, got):
    n0, has, pre, keys = case
    if got['list'] != ['t%d' % k for k in range(n0)] + ['c%d' % j for j in range(len(keys))]:
        return None
    if got['pairs'] is None:
        return [0]
    return [1] + [int(x['key'][1:]) if x else 0 for x in got['pairs']]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--seed', type=int, default=12345)
    ap.add_argument('--n', type=int, default=20000)
    ap.add_argument('--emit', action='store_true', help='only print JSON lines [n0, has, pre, keys, oracle result]')
    args = ap.parse_args()
    if args.n < 0:
        ap.error('--n must be nonnegative')
    inputs, edges = cases(args.n, args.seed)
    want = [oracle(*c) for c in inputs]
    if args.emit:
        for c, w in zip(inputs, want):
            sys.stdout.write(json.dumps(list(c) + [w]) + '\n')
        return 0
    from run import HERE, WORK, RESULTS, configure, run
    from run_host_within import portable
    from run_decode_bytes import ts_runtime
    summary = dict(seed=args.seed, random_cases=args.n, runs={})
    differences, failed = [], False
    try:
        g2, summary['tools'] = configure()
        summary['edge_cases'] = edges
        summary['cases'] = len(inputs)
        summary['calls'] = sum(len(c[3]) for c in inputs)
        summary['oracle_outcomes'] = dict(
            absent=sum(w == [0] for w in want),
            created_by_call=sum(not c[1] and w != [0] for c, w in zip(inputs, want)),
            same_length=sum(w != [0] and len(w) - 1 == c[0] + len(c[3]) for c, w in zip(inputs, want)),
            longer_than_texts=sum(w != [0] and len(w) - 1 > c[0] + len(c[3]) for c, w in zip(inputs, want)),
            max_texts=max(c[0] + len(c[3]) for c in inputs), max_pairs=max(len(w) - 1 for w in want))
        node, summary['ts_runtime'] = ts_runtime()
        ts = [json.loads(x) for x in run(node + [HERE / (NAME+'.mjs')],
                                         ''.join(json.dumps(ts_input(i, c)) + '\n' for i, c in enumerate(inputs))).splitlines()]
        assert len(ts) == len(inputs)
        ts = [ts_result(c, t) for c, t in zip(inputs, ts)]
        summary['ts_oracle_pass'] = sum(t == w for t, w in zip(ts, want))
        failed |= summary['ts_oracle_pass'] != len(inputs)
        payload = ''.join(('x %d %d %d %d %s\n' % (n0, has, len(pre), len(keys), ' '.join(map(str, pre + keys)))).replace(' \n', '\n')
                          for n0, has, pre, keys in inputs)
        for compiler in ('py', 'rs'):
            for backend in ('rust', 'llvm'):
                key = compiler+'/'+backend
                row = summary['runs'][key] = dict(status='error')
                try:
                    work = WORK / (NAME+'_'+compiler+'_'+backend)
                    work.mkdir(exist_ok=True)
                    compiled = g2.compile_pruv(compiler, str(HERE / (NAME+'.pruv')), str(work), backend)
                    row['verification'] = portable(compiled)
                    if compiled['rc'] != 0:
                        raise RuntimeError(json.dumps(portable(compiled)))
                    harness = work / 'main.rs'
                    harness.write_text(HARNESS.replace('@SOL@', compiled['rs']))
                    extra = []
                    if compiled['ll']:
                        extra, error = g2.build_llvm_objects(compiled['ll'], NAME, str(work))
                        if error:
                            raise RuntimeError(error)
                    exe = work / 'runner'
                    run([g2.RUSTC, '-O', '--edition', '2021', '-C', 'target-cpu=native', harness, '-o', exe]+extra)
                    out = [[int(v) for v in x.split()] for x in run([exe], payload).splitlines()]
                    assert len(out) == len(inputs)
                    oracle_pass = sum(o == w for o, w in zip(out, want))
                    ts_pass = sum(o == t for o, t in zip(out, ts))
                    for i, (o, w, t) in enumerate(zip(out, want, ts)):
                        if o != w or o != t:
                            n0, has, pre, keys = inputs[i]
                            differences.append(dict(compiler_backend=key, case_index=i, n0=n0, has=has, pre=pre[:40],
                                                    keys=keys[:40], pruv=o[:41], expected=w[:41], ts_matches=o == t))
                    row.update(cases=len(inputs), pruv_oracle_pass=oracle_pass,
                               ts_oracle_pass=summary['ts_oracle_pass'], pruv_ts_pass=ts_pass)
                    row['status'] = 'ok' if oracle_pass == len(inputs) and ts_pass == len(inputs) else 'wrong'
                    failed |= row['status'] != 'ok'
                    print(key+': '+json.dumps(row), flush=True)
                except Exception as exc:
                    row['error'] = portable(str(exc))
                    failed = True
                    print(key+': '+row['error'], flush=True)
    except Exception as exc:
        summary['error'] = portable(str(exc))
        failed = True
    differences.sort(key=lambda d: (d['n0'], len(d['keys']), d['case_index'], d['compiler_backend']))
    summary.update(status='error' if failed else 'ok', difference_records_total=len(differences),
                   difference_records_saved=min(50, len(differences)),
                   difference_order='n0, call count, case index, compiler/backend')
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / (NAME+'_summary.json')).write_text(json.dumps(summary, indent=2, ensure_ascii=False)+'\n')
    (RESULTS / (NAME+'_differences.jsonl')).write_text(''.join(json.dumps(d, ensure_ascii=False)+'\n' for d in differences[:50]))
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
