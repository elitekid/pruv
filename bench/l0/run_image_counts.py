#!/usr/bin/env python3
"""Cross-check the Korean image count list of Lair extractPdf (listOf in src/documents/pdf.ts).

listOf goes to Pruv (image_counts.pruv image_counts: the first 20 items as "<page>쪽 <count>개" joined with
", " and " 외 <n - 20>쪽" for more than 20 items, proved at most 885 bytes), to the TypeScript copy
(image_counts.mjs, run in Lair's Electron when available) and to a plain Python oracle.
Domain: pages and counts integers in -10^15..10^15.
Inputs: item lists of 0..80 items with the domain ends, list lengths 19/20/21 and the large values.
"""
import argparse
import json
import random
import sys

sys.dont_write_bytecode = True

NAME = 'image_counts'
LIMIT = 10 ** 15
SHOWN = 20

HARNESS = '''#![allow(dead_code, unused_imports)]
#[path = "@SOL@"] mod sol;
use std::io::{self, BufRead, Write};
fn hex(s: &str) -> String { s.bytes().map(|b| format!("{:02x}", b)).collect() }
fn main() {
  let out = io::stdout(); let mut out = out.lock();
  for line in io::stdin().lock().lines() {
    let line = line.unwrap();
    let v: Vec<i64> = line[1..].split_whitespace().map(|x| x.parse().unwrap()).collect();
    let n = v.len() / 2;
    let pages: Vec<i64> = (0..n).map(|k| v[2 * k]).collect();
    let counts: Vec<i64> = (0..n).map(|k| v[2 * k + 1]).collect();
    writeln!(out, "x{}", hex(&sol::image_counts(&pages, &counts))).unwrap();
  }
}
'''


def oracle(items):
    text = ', '.join('%d쪽 %d개' % (p, c) for p, c in items[:SHOWN])
    if len(items) > SHOWN:
        text += ' 외 %d쪽' % (len(items) - SHOWN)
    return text


def rand_num(r):
    return r.choice([lambda: r.randrange(-3, 30), lambda: r.randrange(1, 10 ** r.randrange(1, 16)),
                     lambda: -r.randrange(1, 10 ** r.randrange(1, 16)),
                     lambda: r.choice([LIMIT, -LIMIT, LIMIT - 1, 1 - LIMIT, 0, 1, -1])])()


def rand_items(r):
    size = r.choice([r.randrange(6), r.randrange(30), r.randrange(81), r.choice([19, 20, 21, 22])])
    return [(rand_num(r), rand_num(r)) for _ in range(size)]


def edge_items():
    full = [(LIMIT, -LIMIT), (-LIMIT, LIMIT), (1 - LIMIT, LIMIT - 1), (0, 0), (-1, 1)]
    rows = [[], [(1, 1)], [(3, 2), (5, 1)], full]
    for n in (19, 20, 21, 22, 40, 79, 80, 1000):
        rows.append([(i + 1, i * 1000) for i in range(n)])
        rows.append([(LIMIT, LIMIT)] * n)
        rows.append([(-LIMIT, -LIMIT)] * n)
    return rows


def cases(n, seed):
    rows = edge_items()
    edges = len(rows)
    r = random.Random(seed)
    rows += [rand_items(r) for _ in range(n)]
    for row in rows:
        assert all(-LIMIT <= x <= LIMIT for it in row for x in it)
    return rows, edges


def ts_line(row):
    return json.dumps(dict(items=[dict(page=p, count=c) for p, c in row]))


def harness_line(row):
    return 'c' + ''.join(' %d %d' % it for it in row)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--seed', type=int, default=12345)
    ap.add_argument('--n', type=int, default=20000)
    ap.add_argument('--emit', action='store_true', help='only print JSON lines [items, oracle]')
    args = ap.parse_args()
    if args.n < 0:
        ap.error('--n must be nonnegative')
    if args.emit:
        for row in cases(args.n, args.seed)[0]:
            sys.stdout.write(json.dumps([[dict(page=p, count=c) for p, c in row], oracle(row)], ensure_ascii=False) + '\n')
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
        want = [oracle(row) for row in inputs]
        summary['oracle_outcomes'] = dict(
            empty=sum(1 for row in inputs if not row),
            with_more=sum(1 for row in inputs if len(row) > SHOWN),
            items_total=sum(len(row) for row in inputs))
        node, summary['ts_runtime'] = ts_runtime()
        ts = [json.loads(x) for x in run(node + [HERE / (NAME+'.mjs')], ''.join(ts_line(row)+'\n' for row in inputs)).split('\n')[:-1]]
        assert len(ts) == len(inputs)
        summary['ts_oracle_pass'] = sum(t == w for t, w in zip(ts, want))
        payload = ''.join(harness_line(row) + '\n' for row in inputs)
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
                    pruv = [bytes.fromhex(line[1:]).decode() for line in lines]
                    for i, (row, p, t, w) in enumerate(zip(inputs, pruv, ts, want)):
                        if p != t or p != w:
                            differences.append(dict(compiler_backend=key, case_index=i, input=row[:6], items=len(row), pruv=p, ts=t, expected=w))
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
    differences.sort(key=lambda d: (d['items'], json.dumps(d['input']), d['compiler_backend']))
    summary.update(status='error' if failed else 'ok', difference_records_total=len(differences),
                   difference_records_saved=min(50, len(differences)),
                   difference_order='item count, input, compiler/backend')
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / (NAME+'_summary.json')).write_text(json.dumps(summary, indent=2, ensure_ascii=False)+'\n')
    (RESULTS / (NAME+'_differences.jsonl')).write_text(''.join(json.dumps(d, ensure_ascii=False)+'\n' for d in differences[:50]))
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
