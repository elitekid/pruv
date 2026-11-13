#!/usr/bin/env python3
"""Cross-check Lair groupedNumber (src/documents/context.ts).

Each integer goes to Pruv (grouped_number.pruv: grouped decimal text built in Pruv, result proved at most
33 bytes), to the TypeScript copy (grouped_number.mjs, run in Lair's Electron when available, where
toLocaleString('en-US') goes through ICU) and to an independent oracle, Python's format(n, ','), not by
copying the TS.
Domain: integers in -10^15..10^15. Inputs: zero, every power of ten and its neighbours on both signs,
the group boundaries 999/1000, the domain ends, and random integers of every digit count.
"""
import argparse
import json
import random
import sys

sys.dont_write_bytecode = True

NAME = 'grouped_number'
LIMIT = 10 ** 15

HARNESS = '''#![allow(dead_code, unused_imports)]
#[path = "@SOL@"] mod sol;
use std::io::{self, BufRead, Write};
fn main() {
  let out = io::stdout(); let mut out = out.lock();
  for line in io::stdin().lock().lines() {
    let line = line.unwrap();
    writeln!(out, "x{}", sol::grouped_number(line.trim().parse().unwrap())).unwrap();
  }
}
'''


def oracle(n):
    return format(n, ',')


def cases(n, seed):
    rows = [0, 1, -1, LIMIT, -LIMIT, LIMIT - 1, 1 - LIMIT]
    for e in range(16):
        for d in (-1, 0, 1):
            v = 10 ** e + d
            if 0 <= v <= LIMIT:
                rows += [v, -v]
    rows += [999, 1000, 1001, 999999, 1000000, 123456789, 1234567890123456 % LIMIT, 20, 1048576, 2000000]
    edges = len(rows)
    r = random.Random(seed)
    for _ in range(n):
        v = r.choice([lambda: r.randrange(-3000, 3000), lambda: r.randrange(10 ** r.randrange(1, 16)),
                      lambda: r.randrange(LIMIT + 1)])()
        rows.append(-v if r.randrange(2) else v)
    assert all(-LIMIT <= x <= LIMIT for x in rows)
    return rows, edges


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--seed', type=int, default=12345)
    ap.add_argument('--n', type=int, default=20000)
    ap.add_argument('--emit', action='store_true', help='only print JSON lines [number, oracle]')
    args = ap.parse_args()
    if args.n < 0:
        ap.error('--n must be nonnegative')
    if args.emit:
        for c in cases(args.n, args.seed)[0]:
            sys.stdout.write(json.dumps([c, oracle(c)]) + '\n')
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
        expected = [oracle(c) for c in inputs]
        summary['oracle_outcomes'] = dict(
            negative=sum(1 for x in expected if x.startswith('-')),
            with_comma=sum(1 for x in expected if ',' in x),
            max_commas=max(x.count(',') for x in expected),
            max_bytes=max(len(x) for x in expected))
        node, summary['ts_runtime'] = ts_runtime()
        ts = [json.loads(x) for x in run(node + [HERE / (NAME+'.mjs')], ''.join(json.dumps(c)+'\n' for c in inputs)).splitlines()]
        assert len(ts) == len(inputs)
        summary['ts_oracle_pass'] = sum(t == e for t, e in zip(ts, expected))
        payload = ''.join('%d\n' % c for c in inputs)
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
                    pruv = [line[1:] for line in run([exe], payload).splitlines()]
                    assert len(pruv) == len(inputs)
                    for i, (c, p, t, want) in enumerate(zip(inputs, pruv, ts, expected)):
                        if p != t or p != want:
                            differences.append(dict(compiler_backend=key, case_index=i, input=c, pruv=p, ts=t, expected=want))
                    row.update(cases=len(inputs), pruv_oracle_pass=sum(p == w for p, w in zip(pruv, expected)),
                               ts_oracle_pass=summary['ts_oracle_pass'],
                               pruv_ts_pass=sum(p == t for p, t in zip(pruv, ts)))
                    row['status'] = 'ok' if row['pruv_oracle_pass'] == row['pruv_ts_pass'] == len(inputs) else 'wrong'
                    failed |= row['status'] != 'ok'
                    print(key+': '+json.dumps(row), flush=True)
                except Exception as exc:
                    row['error'] = portable(str(exc))
                    failed = True
                    print(key+': '+row['error'], flush=True)
    except Exception as exc:
        summary['error'] = portable(str(exc))
        failed = True
    differences.sort(key=lambda d: (len(json.dumps(d['input'])), json.dumps(d['input']), d['compiler_backend']))
    summary.update(status='error' if failed else 'ok', difference_records_total=len(differences),
                   difference_records_saved=min(50, len(differences)),
                   difference_order='input size, input, compiler/backend')
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / (NAME+'_summary.json')).write_text(json.dumps(summary, indent=2, ensure_ascii=False)+'\n')
    (RESULTS / (NAME+'_differences.jsonl')).write_text(''.join(json.dumps(d, ensure_ascii=False)+'\n' for d in differences[:50]))
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
