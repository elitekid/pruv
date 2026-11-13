#!/usr/bin/env python3
"""Cross-check the number branch of Lair cellText (src/documents/sheets.ts) on safe integers.

Each integer n with |n| <= 2^53 - 1 goes to Pruv (cell_int.pruv: 15 significant digits with ties away
from zero, then decimal digits, result proved at most 17 bytes), to the TypeScript copy (cell_int.mjs,
cellText(n) = String(Number(n.toPrecision(15))), run in Lair's Electron when available) and to an
independent oracle, not by copying the TS: Python's decimal module with precision 15 and ROUND_HALF_UP
(which rounds ties away from zero), printed as a Python int. Inputs: 0, +-1, every power of ten and its
neighbours, the 15/16-digit border, 16-digit values ending in 4, 5 and 6 (ties), values that round up to
a new power of ten (9999999999999995), the domain ends +-9007199254740991, and random values over the
whole range, on 16 digits, on 15 digits and small.
"""
import argparse
import decimal
import json
import random
import sys

sys.dont_write_bytecode = True

NAME = 'cell_int'
LIMIT = 2 ** 53 - 1

HARNESS = '''#![allow(dead_code, unused_imports)]
#[path = "@SOL@"] mod sol;
use std::io::{self, BufRead, Write};
fn main() {
  let out = io::stdout(); let mut out = out.lock();
  for line in io::stdin().lock().lines() {
    let line = line.unwrap();
    writeln!(out, "x{}", sol::cell_int(line.trim().parse().unwrap())).unwrap();
  }
}
'''

CONTEXT = decimal.Context(prec=15, rounding=decimal.ROUND_HALF_UP)


def oracle(n):
    return str(int(CONTEXT.plus(decimal.Decimal(n))))


def cases(n, seed):
    rows = [0, 1, -1, LIMIT, -LIMIT, LIMIT - 1, 1 - LIMIT, LIMIT - 5, LIMIT - 4, LIMIT - 6,
            2 ** 53 - 10, 2 ** 52, 2 ** 52 + 5]
    for k in range(17):
        p = 10 ** k
        for v in (p - 1, p, p + 1, p + 4, p + 5, p + 6, p * 9 + 5, 10 * p - 5, 10 * p - 6):
            for s in (v, -v):
                if -LIMIT <= s <= LIMIT:
                    rows.append(s)
    for tail in range(10):
        for head in (100_000_000_000_000, 123_456_789_012_345, 899_999_999_999_999, 900_719_925_474_099):
            v = head * 10 + tail
            if v <= LIMIT:
                rows += [v, -v]
    rows = list(dict.fromkeys(rows))
    edges = len(rows)
    r = random.Random(seed)
    for _ in range(n):
        v = r.choice([lambda: r.randrange(-LIMIT, LIMIT + 1),
                      lambda: r.randrange(10 ** 15, LIMIT + 1),
                      lambda: r.randrange(10 ** 14, 10 ** 15),
                      lambda: r.randrange(-10 ** 6, 10 ** 6),
                      lambda: r.randrange(10 ** 14, LIMIT // 10 + 1) * 10 + 5])()
        rows.append(v if r.random() < 0.5 else -v)
    assert all(-LIMIT <= x <= LIMIT for x in rows)
    return rows, edges


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--seed', type=int, default=12345)
    ap.add_argument('--n', type=int, default=20000)
    ap.add_argument('--emit', action='store_true', help='only print JSON lines [ms, oracle]')
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
            unchanged=sum(1 for c, x in zip(inputs, expected) if x == str(c)),
            rounded_down=sum(1 for c, x in zip(inputs, expected) if abs(int(x)) < abs(c)),
            rounded_up=sum(1 for c, x in zip(inputs, expected) if abs(int(x)) > abs(c)),
            ties=sum(1 for c in inputs if abs(c) >= 10 ** 15 and abs(c) % 10 == 5),
            negative=sum(1 for x in expected if x.startswith('-')),
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
