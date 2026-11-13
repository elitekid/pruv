#!/usr/bin/env python3
"""Cross-check Lair rangeText (src/documents/pdf.ts).

Each list of integers goes to Pruv (page_ranges.pruv: decimal text and Korean page unit built in Pruv,
result proved at most 40 UTF-8 bytes per number), to the TypeScript copy (page_ranges.mjs, run in Lair's
Electron when available) and to an independent oracle that marks the indices where a new run starts
(the first index and every k with nums[k] != nums[k-1] + 1), slices between those marks and formats
each slice, not by copying the TS scan.
Domain: at most 10^7 integers in -10^15..10^15. Inputs: empty, single numbers, runs through zero, the
domain ends, unsorted lists and duplicates (the TS does not require order), long runs and lists up to
3,000 numbers.
"""
import argparse
import json
import random
import sys

sys.dont_write_bytecode = True

NAME = 'page_ranges'
LIMIT = 10 ** 15

HARNESS = '''#![allow(dead_code, unused_imports)]
#[path = "@SOL@"] mod sol;
use std::io::{self, BufRead, Write};
fn hex(s: &str) -> String { s.bytes().map(|b| format!("{:02x}", b)).collect() }
fn main() {
  let out = io::stdout(); let mut out = out.lock();
  for line in io::stdin().lock().lines() {
    let line = line.unwrap();
    let v: Vec<i64> = line.split(' ').skip(1).map(|x| x.parse().unwrap()).collect();
    writeln!(out, "x{}", hex(&sol::page_ranges(&v))).unwrap();
  }
}
'''


def oracle(nums):
    starts = [k for k in range(len(nums)) if k == 0 or nums[k] != nums[k - 1] + 1]
    bounds = list(zip(starts, starts[1:] + [len(nums)]))
    return ', '.join(f'{nums[a]}쪽' if b - a == 1 else f'{nums[a]}~{nums[b - 1]}쪽' for a, b in bounds)


def rand_num(r):
    return r.choice([lambda: r.randrange(-3, 30), lambda: r.randrange(1, 10 ** r.randrange(1, 16)),
                     lambda: -r.randrange(1, 10 ** r.randrange(1, 16)), lambda: r.choice([LIMIT, -LIMIT, LIMIT - 1, 1 - LIMIT])])()


def rand_list(r, size):
    kind = r.randrange(5)
    if kind == 0:   # ascending pages with runs (Lair's shape)
        v, out = r.randrange(1, 2000), []
        for _ in range(size):
            out.append(v)
            v += r.choice([1, 1, 1, 2, 3, r.randrange(1, 50)])
        return out
    if kind == 1:   # free numbers
        return [rand_num(r) for _ in range(size)]
    if kind == 2:   # duplicates and descents
        v, out = r.randrange(-20, 20), []
        for _ in range(size):
            out.append(v)
            v += r.choice([-1, 0, 1, 1, 2])
        return out
    if kind == 3:   # runs at the top or bottom of the domain
        base = r.choice([LIMIT - size, -LIMIT])
        return [base + i + (r.randrange(4) == 0) for i in range(size)]
    base = r.randrange(-LIMIT, LIMIT - 2 * size)
    return [base + i + (r.randrange(3) == 0) * i for i in range(size)]


def cases(n, seed):
    rows = [[], [0], [-0], [1], [-1], [LIMIT], [-LIMIT], [-LIMIT, 1 - LIMIT], [LIMIT - 1, LIMIT],
            [-2, -1, 0, 1, 2], [1, 2, 3, 5, 6, 8], [3, 3], [5, 4, 3], [1, 3, 2, 3, 4], [1, 2], [1, 3],
            [2, 1], [1, 2, 2, 3], list(range(1, 1000)), list(range(1, 2000, 2)), list(range(1, 3001)),
            [LIMIT] * 30, [-LIMIT, LIMIT] * 15, list(range(-LIMIT, -LIMIT + 50)), list(range(LIMIT - 49, LIMIT + 1))]
    for size in range(1, 12):
        for gaps in range(1 << (size - 1)):
            nums, v = [1], 1
            for k in range(size - 1):
                v += 2 if gaps >> k & 1 else 1
                nums.append(v)
            rows.append(nums)
    edges = len(rows)
    r = random.Random(seed)
    for _ in range(n):
        size = r.choice([r.randrange(6), r.randrange(40), r.randrange(10, 140), r.randrange(300)])
        rows.append(rand_list(r, size))
    assert all(all(-LIMIT <= x <= LIMIT for x in c) for c in rows)
    return rows, edges


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--seed', type=int, default=12345)
    ap.add_argument('--n', type=int, default=20000)
    ap.add_argument('--emit', action='store_true', help='only print JSON lines [numbers, oracle]')
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
            empty=sum(1 for x in expected if x == ''),
            with_run=sum(1 for x in expected if '~' in x),
            single_only=sum(1 for x in expected if x and '~' not in x),
            max_ranges=max(x.count('쪽') for x in expected),
            max_utf8_bytes=max(len(x.encode()) for x in expected))
        node, summary['ts_runtime'] = ts_runtime()
        ts = [json.loads(x) for x in run(node + [HERE / (NAME+'.mjs')], ''.join(json.dumps(c)+'\n' for c in inputs)).splitlines()]
        assert len(ts) == len(inputs)
        summary['ts_oracle_pass'] = sum(t == e for t, e in zip(ts, expected))
        payload = ''.join('n' + ''.join(' %d' % x for x in c) + '\n' for c in inputs)
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
                    pruv = [bytes.fromhex(line[1:]).decode() for line in run([exe], payload).splitlines()]
                    assert len(pruv) == len(inputs)
                    for i, (c, p, t, want) in enumerate(zip(inputs, pruv, ts, expected)):
                        if p != t or p != want:
                            differences.append(dict(compiler_backend=key, case_index=i, input=c[:60], pruv=p, ts=t, expected=want))
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
