#!/usr/bin/env python3
"""Cross-check the Date branch of Lair cellText (src/documents/sheets.ts).

Each time value (integer milliseconds since 1970-01-01 UTC) goes to Pruv (cell_date.pruv: civil date
from days in Pruv, result proved at most 35 bytes), to the TypeScript copy (cell_date.mjs, cellText of
new Date(ms), run in Lair's Electron when available) and to an independent oracle, not by copying the TS:
Python's datetime.date.fromordinal after moving the day by whole 400-year cycles (146097 days, the
Gregorian calendar repeats) into datetime's years 1..400, then adding the cycles back to the year.
Domain: every valid Date, |ms| <= 8.64e15. Inputs: the domain ends, the epoch, year 0 and the years
around it, 9999/10000, leap days of 1900/2000/2100, the last millisecond of a day, times where only the
second or only the millisecond is nonzero, and random values over the whole range, near the epoch, on
whole days and on whole seconds.
"""
import argparse
import datetime
import json
import random
import sys

sys.dont_write_bytecode = True

NAME = 'cell_date'
LIMIT = 8_640_000_000_000_000
DAY = 86_400_000

HARNESS = '''#![allow(dead_code, unused_imports)]
#[path = "@SOL@"] mod sol;
use std::io::{self, BufRead, Write};
fn main() {
  let out = io::stdout(); let mut out = out.lock();
  for line in io::stdin().lock().lines() {
    let line = line.unwrap();
    writeln!(out, "x{}", sol::cell_date(line.trim().parse().unwrap())).unwrap();
  }
}
'''


def oracle(t):
    days, ms = divmod(t, DAY)
    ordinal = days + datetime.date(1970, 1, 1).toordinal()
    cycles, rest = divmod(ordinal - 1, 146097)
    d = datetime.date.fromordinal(rest + 1)
    text = '%d-%02d-%02d' % (d.year + 400 * cycles, d.month, d.day)
    hours, minutes, seconds = ms // 3_600_000, ms // 60_000 % 60, ms // 1000 % 60
    if hours or minutes or seconds:
        text += ' %02d:%02d' % (hours, minutes)
    return text


def ms_of(y, m, d):
    # Days from 1970-01-01 to y-m-d of the proleptic Gregorian calendar, any year, via 400-year cycles.
    cycles = (y - 1) // 400
    base = datetime.date(y - 400 * cycles, m, d).toordinal() + 146097 * cycles
    return (base - datetime.date(1970, 1, 1).toordinal()) * DAY


def cases(n, seed):
    rows = [0, 1, -1, 999, 1000, -1000, 60000, -60000, DAY - 1, DAY, -DAY, 1 - DAY,
            LIMIT, -LIMIT, LIMIT - 1, 1 - LIMIT, LIMIT - DAY, DAY - LIMIT]
    for y, m, d in [(0, 1, 1), (0, 2, 29), (0, 3, 1), (-1, 12, 31), (1, 1, 1), (-1, 1, 1), (-4, 2, 29),
                    (9999, 12, 31), (10000, 1, 1), (1900, 2, 28), (1900, 3, 1), (2000, 2, 29),
                    (2100, 2, 28), (2100, 3, 1), (1969, 12, 31), (2024, 2, 29), (-100, 3, 1),
                    (-271821, 4, 20), (275760, 9, 13), (-99999, 1, 1), (100000, 12, 31)]:
        base = ms_of(y, m, d)
        for off in (0, 1, 999, 1000, 59999, 60000, 3_600_000, DAY - 1):
            for v in (base + off, base - off):
                if -LIMIT <= v <= LIMIT:
                    rows.append(v)
    edges = len(rows)
    r = random.Random(seed)
    for _ in range(n):
        v = r.choice([lambda: r.randrange(-LIMIT, LIMIT + 1),
                      lambda: r.randrange(-4 * 10 ** 12, 4 * 10 ** 12),
                      lambda: r.randrange(-LIMIT // DAY, LIMIT // DAY + 1) * DAY,
                      lambda: r.randrange(-LIMIT // 1000, LIMIT // 1000 + 1) * 1000,
                      lambda: r.randrange(-10 ** 8, 10 ** 8) * DAY + r.choice([0, 1, 999, 1000, 59999])])()
        rows.append(max(-LIMIT, min(LIMIT, v)))
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
            negative_year=sum(1 for x in expected if x.startswith('-')),
            year_over_9999=sum(1 for x in expected if not x.startswith('-') and int(x.split('-')[0]) > 9999),
            with_time=sum(1 for x in expected if ' ' in x),
            date_only=sum(1 for x in expected if ' ' not in x),
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
