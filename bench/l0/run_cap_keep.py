#!/usr/bin/env python3
"""Cross-check the cut of Lair capChars (src/documents/extract.ts).

Each (chunk lengths, max) pair goes to Pruv (cap_keep.pruv: running total from the front, result proved to
keep a prefix whose total is within max with the next chunk going over), to the TypeScript copy
(cap_keep.mjs: verbatim capChars on chunks of that many characters, run in Lair's Electron when available)
and to an independent oracle, the number of nonempty prefixes whose total is within max (bisect over the
prefix totals), not by copying the TS loop.
The TS copy builds real strings, so it only runs on cases whose total is at most 10^6 characters; cases with
huge chunks (up to 10^9 characters) and maxes near +-10^15 are checked against the oracle only.
Inputs: no chunks, empty chunks, max below zero, max exactly at a running total and one below it, many
equal chunks, huge chunks, and random chunk lists with max drawn around their running totals.
"""
import argparse
import bisect
import itertools
import json
import random
import sys

sys.dont_write_bytecode = True

NAME = 'cap_keep'
TS_TOTAL = 10**6

HARNESS = '''#![allow(dead_code, unused_imports)]
#[path = "@SOL@"] mod sol;
use std::io::{self, BufRead, Write};
fn main() {
  let out = io::stdout(); let mut out = out.lock();
  for line in io::stdin().lock().lines() {
    let line = line.unwrap();
    let f: Vec<i64> = line.split(' ').skip(1).map(|x| x.parse().unwrap()).collect();
    writeln!(out, "{}", sol::cap_keep(&f[1..], f[0])).unwrap();
  }
}
'''


def oracle(lens, cap):
    totals = list(itertools.accumulate(lens))
    return bisect.bisect_right(totals, cap)


def cases(n, seed):
    g = 10**9
    rows = [([], 0), ([], -1), ([], 10**15), ([0], 0), ([0], -1), ([0, 0, 0], 0), ([0, 0, 0], -1), ([5], 5),
            ([5], 4), ([5], 6), ([1, 1, 1], 2), ([1, 1, 1], 3), ([1, 1, 1], 0), ([3, 4, 5], 7), ([3, 4, 5], 6),
            ([3, 4, 5], 12), ([3, 4, 5], 11), ([0, 5, 0], 4), ([0, 5, 0], 5), ([5, 0, 0, 1], 5), ([7], -10**15),
            ([1] * 1000, 999), ([1] * 1000, 1000), ([1000] * 1000, 500000), ([TS_TOTAL], TS_TOTAL),
            ([TS_TOTAL], TS_TOTAL - 1), ([g], g), ([g], g - 1), ([g] * 10, 5 * g), ([g] * 10, 10**15),
            ([g, 0, g], g), ([g] * 3, -10**15), ([0, g], 10**15 - 1), ([g] * 10000, 10**13),
            ([g] * 10000, 10**13 - 1)]
    edges = len(rows)
    r = random.Random(seed)
    for _ in range(n):
        lens = [r.choice([0, r.randrange(1, 4), r.randrange(1, 61), r.randrange(1, 400)])
                for _ in range(r.randrange(0, 13))]
        totals = list(itertools.accumulate(lens)) or [0]
        cap = r.choice([r.choice(totals), r.choice(totals) - 1, r.choice(totals) + 1,
                        r.randrange(-3, totals[-1] + 6), totals[-1], -r.randrange(1, 100)])
        rows.append((lens, cap))
    return rows, edges


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--seed', type=int, default=12345)
    ap.add_argument('--n', type=int, default=20000)
    ap.add_argument('--emit', action='store_true',
                    help='only print JSON lines [lens, max, oracle, TS runs (total <= 10^6)]')
    args = ap.parse_args()
    if args.n < 0:
        ap.error('--n must be nonnegative')
    if args.emit:
        for lens, cap in cases(args.n, args.seed)[0]:
            sys.stdout.write(json.dumps([lens, cap, oracle(lens, cap), sum(lens) <= TS_TOTAL]) + '\n')
        return 0
    from run import HERE, WORK, RESULTS, configure, run
    from run_host_within import portable
    from run_decode_bytes import ts_runtime
    summary = dict(seed=args.seed, random_cases=args.n, runs={})
    differences, failed = [], False
    try:
        g2, summary['tools'] = configure()
        inputs, summary['edge_cases'] = cases(args.n, args.seed)
        summary['cases'] = len(inputs)
        expected = [oracle(lens, cap) for lens, cap in inputs]
        summary['oracle_outcomes'] = dict(
            keep_all=sum(e == len(c[0]) for e, c in zip(expected, inputs)),
            keep_none=sum(e == 0 and c[0] != [] for e, c in zip(expected, inputs)),
            cut_inside=sum(0 < e < len(c[0]) for e, c in zip(expected, inputs)),
            max_chunks=max(len(c[0]) for c in inputs), max_total=max(sum(c[0]) for c in inputs))
        node, summary['ts_runtime'] = ts_runtime()
        ts_index = [i for i, (lens, _) in enumerate(inputs) if sum(lens) <= TS_TOTAL]
        summary['ts_cases'] = len(ts_index)
        ts_out = [json.loads(x) for x in run(node + [HERE / (NAME+'.mjs')],
                                             ''.join(json.dumps(dict(lens=inputs[i][0], max=inputs[i][1]))+'\n'
                                                     for i in ts_index)).splitlines()]
        assert len(ts_out) == len(ts_index)
        ts = [None] * len(inputs)
        for i, t in zip(ts_index, ts_out):
            ts[i] = t
        summary['ts_oracle_pass'] = sum(ts[i] == expected[i] for i in ts_index)
        failed |= summary['ts_oracle_pass'] != len(ts_index)
        payload = ''.join('x %d %s\n' % (cap, ' '.join(map(str, lens))) for lens, cap in inputs)
        payload = payload.replace(' \n', '\n')
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
                    pruv = [int(x) for x in run([exe], payload).splitlines()]
                    assert len(pruv) == len(inputs)
                    for i, ((lens, cap), got, t, want) in enumerate(zip(inputs, pruv, ts, expected)):
                        if got != want or (t is not None and got != t):
                            differences.append(dict(compiler_backend=key, case_index=i, chunks=len(lens),
                                                    lens=lens[:60], max=cap, pruv=got, ts=t, expected=want))
                    row.update(cases=len(inputs), pruv_oracle_pass=sum(g == w for g, w in zip(pruv, expected)),
                               ts_cases=len(ts_index), ts_oracle_pass=summary['ts_oracle_pass'],
                               pruv_ts_pass=sum(pruv[i] == ts[i] for i in ts_index))
                    row['status'] = 'ok' if (row['pruv_oracle_pass'] == len(inputs)
                                             and row['pruv_ts_pass'] == len(ts_index)) else 'wrong'
                    failed |= row['status'] != 'ok'
                    print(key+': '+json.dumps(row), flush=True)
                except Exception as exc:
                    row['error'] = portable(str(exc))
                    failed = True
                    print(key+': '+row['error'], flush=True)
    except Exception as exc:
        summary['error'] = portable(str(exc))
        failed = True
    differences.sort(key=lambda d: (d['chunks'], json.dumps(d['lens']), d['max'], d['compiler_backend']))
    summary.update(status='error' if failed else 'ok', difference_records_total=len(differences),
                   difference_records_saved=min(50, len(differences)),
                   difference_order='chunk count, lengths, max, compiler/backend')
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / (NAME+'_summary.json')).write_text(json.dumps(summary, indent=2, ensure_ascii=False)+'\n')
    (RESULTS / (NAME+'_differences.jsonl')).write_text(''.join(json.dumps(d, ensure_ascii=False)+'\n' for d in differences[:50]))
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
