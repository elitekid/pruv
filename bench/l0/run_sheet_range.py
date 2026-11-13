#!/usr/bin/env python3
"""Cross-check the sheetWindow window arithmetic (Lair src/documents/preview.ts).

A sheet size and request (row, col, rows, cols, each absent, null or an integer) go to Pruv
(sheet_range.pruv: window proved inside the sheet, counts proved within 0..500 / 0..100), to the TypeScript
copy (sheet_range.mjs, run in Lair's Electron when available) and to an independent oracle that intersects
the wanted span [start, start + want - 1] with [1, total] as Python ranges, not by copying the TS
min/max chain. Absent and null fields both take their defaults (row/col 1, rows 200, cols 50).
Domain: integer request fields with |v| <= 2^53 - 1, sheet size 0..10^12.
Inputs: sizes 0..1200 and up to 10^12; fields absent, null, negative, 0, 1, around the defaults and caps
(199..201, 499..501, 49..51, 99..101), near the sheet end, and +/-(2^53 - 1).
"""
import argparse
import json
import random
import sys

sys.dont_write_bytecode = True

NAME = 'sheet_range'
SAFE = 2 ** 53 - 1
FIELDS = ('row', 'col', 'rows', 'cols')
DEFAULTS = dict(row=1, col=1, rows=200, cols=50)
CAPS = dict(rows=500, cols=100)

HARNESS = '''#![allow(dead_code, unused_imports)]
#[path = "@SOL@"] mod sol;
use std::io::{self, BufRead, Write};
fn main() {
  let out = io::stdout(); let mut out = out.lock();
  for line in io::stdin().lock().lines() {
    let line = line.unwrap();
    let v: Vec<i64> = line.split(' ').map(|x| x.parse().unwrap()).collect();
    let r = sol::sheet_range(v[0], v[1], v[2], v[3], v[4], v[5], v[6]);
    writeln!(out, "{} {} {} {}", r[0], r[1], r[2], r[3]).unwrap();
  }
}
'''


def value(request, field):
    v = request.get(field)
    return DEFAULTS[field] if v is None else v


def span(total, start, want):
    """How many of the rows start .. start + want - 1 lie in 1 .. total."""
    lo, hi = start, start + want - 1
    return len(range(max(lo, 1), min(hi, total) + 1))


def oracle(total_rows, total_cols, request):
    row = value(request, 'row') if value(request, 'row') >= 1 else 1
    col = value(request, 'col') if value(request, 'col') >= 1 else 1
    want_rows = sorted((1, value(request, 'rows'), CAPS['rows']))[1]
    want_cols = sorted((1, value(request, 'cols'), CAPS['cols']))[1]
    return [row, col, span(total_rows, row, want_rows), span(total_cols, col, want_cols)]


SPECIAL = [-SAFE, -SAFE + 1, -1000000, -501, -1, 0, 1, 2, 49, 50, 51, 99, 100, 101, 199, 200, 201,
           499, 500, 501, 1000, 10 ** 12, SAFE - 1, SAFE]


def rand_field(r, total):
    kind = r.randrange(7)
    if kind == 0:
        return 'absent'
    if kind == 1:
        return None
    if kind == 2:
        return r.choice(SPECIAL)
    if kind == 3:
        return r.randrange(-5, 30)
    if kind == 4 and total > 0:
        return total + r.randrange(-3, 4)
    if kind == 5:
        return r.randrange(-SAFE, SAFE + 1)
    return r.randrange(0, 1300)


def rand_case(r):
    total_rows = r.choice([0, 1, 2, r.randrange(0, 1200), r.randrange(0, 1200), 10 ** 12, r.randrange(0, 10 ** 12 + 1)])
    total_cols = r.choice([0, 1, 2, r.randrange(0, 200), r.randrange(0, 200), 10 ** 12, r.randrange(0, 10 ** 12 + 1)])
    request = {}
    for f in FIELDS:
        v = rand_field(r, total_rows if f in ('row', 'rows') else total_cols)
        if v != 'absent':
            request[f] = v
    return total_rows, total_cols, request


def edge_cases():
    rows = [(0, 0, {}), (1, 1, {}), (200, 50, {}), (201, 51, {}), (10 ** 12, 10 ** 12, {}),
            (0, 0, dict(row=None, col=None, rows=None, cols=None))]
    out = list(rows)
    for total in (0, 1, 199, 200, 201, 500, 501, 1000):
        for row in ('absent', None, -SAFE, -1, 0, 1, 2, total - 1, total, total + 1, SAFE):
            for want in ('absent', None, -1, 0, 1, 199, 200, 201, 499, 500, 501, SAFE):
                req = {}
                if row != 'absent':
                    req['row'] = row
                if want != 'absent':
                    req['rows'] = want
                out.append((total, 7, req))
    for total in (0, 1, 49, 50, 51, 99, 100, 101, 300):
        for col in ('absent', None, -SAFE, 0, 1, total - 1, total, total + 1, SAFE):
            for want in ('absent', None, -1, 0, 1, 49, 50, 51, 99, 100, 101, SAFE):
                req = {}
                if col != 'absent':
                    req['col'] = col
                if want != 'absent':
                    req['cols'] = want
                out.append((9, total, req))
    out += [(10 ** 12, 10 ** 12, dict(row=10 ** 12, col=10 ** 12, rows=SAFE, cols=SAFE)),
            (10 ** 12, 10 ** 12, dict(row=SAFE, col=SAFE, rows=SAFE, cols=SAFE)),
            (10 ** 12, 10 ** 12, dict(row=-SAFE, col=-SAFE, rows=-SAFE, cols=-SAFE)),
            (10 ** 12, 10 ** 12, dict(row=10 ** 12 - 499, rows=500, col=10 ** 12 - 99, cols=100))]
    return out


def cases(n, seed):
    rows = edge_cases()
    edges = len(rows)
    r = random.Random(seed)
    for _ in range(n):
        rows.append(rand_case(r))
    return rows, edges


def ts_line(case):
    total_rows, total_cols, request = case
    return json.dumps(dict(totalRows=total_rows, totalCols=total_cols, request=request))


def harness_line(case):
    total_rows, total_cols, request = case
    given = sum(1 << k for k, f in enumerate(FIELDS) if request.get(f) is not None)
    vals = [request.get(f) if request.get(f) is not None else 0 for f in FIELDS]
    return ' '.join(str(x) for x in [total_rows, total_cols] + vals + [given])


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--seed', type=int, default=12345)
    ap.add_argument('--n', type=int, default=20000)
    ap.add_argument('--emit', action='store_true', help='only print JSON lines [totalRows, totalCols, request, oracle]')
    args = ap.parse_args()
    if args.n < 0:
        ap.error('--n must be nonnegative')
    if args.emit:
        for c in cases(args.n, args.seed)[0]:
            sys.stdout.write(json.dumps([c[0], c[1], c[2], oracle(*c)]) + '\n')
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
        want = [oracle(*c) for c in inputs]
        summary['oracle_outcomes'] = dict(
            empty_rows=sum(1 for w in want if w[2] == 0),
            empty_cols=sum(1 for w in want if w[3] == 0),
            full_rows_500=sum(1 for w in want if w[2] == 500),
            full_cols_100=sum(1 for w in want if w[3] == 100),
            default_rows_200=sum(1 for w in want if w[2] == 200),
            default_cols_50=sum(1 for w in want if w[3] == 50),
            cut_by_sheet_end=sum(1 for c, w in zip(inputs, want) if 0 < w[2] and w[0] - 1 + w[2] == c[0]),
            start_clamped_to_1=sum(1 for c in inputs if c[2].get('row') is not None and c[2]['row'] < 1),
            max_start=max(max(w[0], w[1]) for w in want))
        node, summary['ts_runtime'] = ts_runtime()
        ts = [json.loads(x) for x in run(node + [HERE / (NAME+'.mjs')], ''.join(ts_line(c)+'\n' for c in inputs)).split('\n')[:-1]]
        assert len(ts) == len(inputs)
        summary['ts_oracle_pass'] = sum(t == w for t, w in zip(ts, want))
        payload = ''.join(harness_line(c) + '\n' for c in inputs)
        for compiler in ('py', 'rs'):
            for backend in ('rust', 'llvm'):
                key = compiler+'/'+backend
                row_ = summary['runs'][key] = dict(status='error')
                try:
                    work = WORK / (NAME+'_'+compiler+'_'+backend)
                    work.mkdir(exist_ok=True)
                    compiled = g2.compile_pruv(compiler, str(HERE / (NAME+'.pruv')), str(work), backend)
                    row_['verification'] = portable(compiled)
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
                    pruv = [[int(x) for x in line.split()] for line in lines]
                    for i, (c, p, t, w) in enumerate(zip(inputs, pruv, ts, want)):
                        if p != t or p != w:
                            differences.append(dict(compiler_backend=key, case_index=i, input=list(c), pruv=p, ts=t, expected=w))
                    row_.update(cases=len(inputs), pruv_oracle_pass=sum(p == w for p, w in zip(pruv, want)),
                                ts_oracle_pass=summary['ts_oracle_pass'],
                                pruv_ts_pass=sum(p == t for p, t in zip(pruv, ts)))
                    row_['status'] = 'ok' if row_['pruv_oracle_pass'] == len(inputs) and row_['pruv_ts_pass'] == len(inputs) else 'wrong'
                    failed |= row_['status'] != 'ok'
                    print(key+': '+json.dumps(row_), flush=True)
                except Exception as exc:
                    row_['error'] = portable(str(exc))
                    failed = True
                    print(key+': '+row_['error'], flush=True)
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
