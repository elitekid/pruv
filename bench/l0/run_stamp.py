#!/usr/bin/env python3
"""Cross-check the clip time label of Lair (stamp in src/backend/clip-notice.ts).

Each ms goes to Pruv (stamp.pruv: integer tenths, minutes and a fixed seconds field), to the TypeScript
copy (stamp.mjs, run in Lair's Electron when available) and to an independent oracle in exact
arithmetic: tenths = max(0, floor(ms / 100 + 1/2)) with fractions, and the label formats minutes and
Decimal(tenths % 600) / 10 with Python's '04.1f'.
Domain: ms an integer in -10^15..=10^15. Inputs: edge values (the ends of the domain, negatives, the
rounding points around +-50, minute and hour turns, ms = 100 * r for every tenth count r in 0..=599) and
random values (seed 12345): small, near a multiple of 50, and large.
"""
import argparse
import math
from decimal import Decimal
from fractions import Fraction
import json
import random
import sys

sys.dont_write_bytecode = True

NAME = 'stamp'

HARNESS = '''#![allow(dead_code, unused_imports)]
#[path = "@SOL@"] mod sol;
use std::io::{self, BufRead, Write};
fn unhex(hex: &str) -> String {
  let data: Vec<u8> = (0..hex.len()).step_by(2).map(|i| u8::from_str_radix(&hex[i..i+2], 16).unwrap()).collect();
  String::from_utf8(data).unwrap()
}
fn main() {
  let out = io::stdout(); let mut out = out.lock();
  for line in io::stdin().lock().lines() {
    let line = line.unwrap();
    let ms: i64 = line.trim().parse().unwrap();
    let r = sol::stamp(ms);
    let hex: String = r.as_bytes().iter().map(|b| format!("{:02x}", b)).collect();
    writeln!(out, "x{}", hex).unwrap();
  }
}
'''

def oracle(ms):
    tenths = max(0, math.floor(Fraction(ms, 100) + Fraction(1, 2)))
    return '%d:%s' % (tenths // 600, format(Decimal(tenths % 600) / 10, '04.1f'))


def cases(n, seed):
    r = random.Random(seed)
    B = 1_000_000_000_000_000
    rows = [-B, -10**12, -101, -51, -50, -49, -1, 0, 1, 49, 50, 51, 149, 150, 151, 3200, 59949, 59950,
            59999, 60000, 3_599_950, 3_600_000, B - 50, B - 51, B]
    rows += [100 * k for k in range(600)]
    edges = len(rows)
    for _ in range(n):
        u = r.random()
        if u < 0.4:
            ms = r.randint(-200, 200_000)
        elif u < 0.7:
            ms = 50 * r.randint(-10, 10**9) + r.choice([-1, 0, 1])
        else:
            ms = r.randint(-B, B)
        rows.append(max(-B, min(B, ms)))
    return rows, edges


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--seed', type=int, default=12345)
    ap.add_argument('--n', type=int, default=20000)
    ap.add_argument('--emit', action='store_true',
                    help='only print JSON lines [ms, oracle] (Node bridge test)')
    args = ap.parse_args()
    if args.n < 0:
        ap.error('--n must be nonnegative')
    if args.emit:
        for ms in cases(args.n, args.seed)[0]:
            sys.stdout.write(json.dumps([ms, oracle(ms)]) + '\n')
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
        expected = [oracle(m) for m in inputs]
        summary['negative_cases'] = sum(m < 0 for m in inputs)
        summary['half_round_cases'] = sum(m % 100 == 50 for m in inputs)
        summary['tenth_counts_covered'] = len({e.split(':')[1] for e in expected})
        summary['over_hour_cases'] = sum(int(e.split(':')[0]) >= 60 for e in expected)
        node, summary['ts_runtime'] = ts_runtime()
        ts = [json.loads(x) for x in run(node + [HERE / (NAME+'.mjs')],
                                         ''.join(json.dumps({'ms': m})+'\n' for m in inputs)).split('\n')[:-1]]
        assert len(ts) == len(inputs)
        payload = ''.join('%d\n' % m for m in inputs)
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
                    lines = run([exe], payload).splitlines()
                    assert len(lines) == len(inputs)
                    pruv = [bytes.fromhex(line[1:]).decode() for line in lines]
                    for i, (m, p, s, want) in enumerate(zip(inputs, pruv, ts, expected)):
                        if p != s or p != want:
                            differences.append(dict(compiler_backend=key, case_index=i, ms=m,
                                                    pruv=p, ts=s, expected=want))
                    row.update(cases=len(inputs), pruv_oracle_pass=sum(p == w for p, w in zip(pruv, expected)),
                               ts_oracle_pass=sum(t == w for t, w in zip(ts, expected)),
                               pruv_ts_pass=sum(p == t for p, t in zip(pruv, ts)))
                    ok = row['pruv_oracle_pass'] == row['ts_oracle_pass'] == row['pruv_ts_pass'] == len(inputs)
                    row['status'] = 'ok' if ok else 'wrong'
                    failed |= row['status'] != 'ok'
                    print(key+': '+json.dumps(row), flush=True)
                except Exception as exc:
                    row['error'] = portable(str(exc))
                    failed = True
                    print(key+': '+row['error'], flush=True)
    except Exception as exc:
        summary['error'] = portable(str(exc))
        failed = True
    differences.sort(key=lambda d: (d['ms'], d['compiler_backend']))
    summary.update(status='error' if failed else 'ok', difference_records_total=len(differences),
                   difference_records_saved=min(50, len(differences)),
                   difference_order='ms, compiler/backend')
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / (NAME+'_summary.json')).write_text(json.dumps(summary, indent=2)+'\n')
    (RESULTS / (NAME+'_differences.jsonl')).write_text(''.join(json.dumps(d)+'\n' for d in differences[:50]))
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
