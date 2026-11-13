#!/usr/bin/env python3
"""Cross-check Lair numberRanges (src/documents/context.ts, with joinRangeParts).

Each list of integers goes to Pruv (number_ranges.pruv: decimal text built in Pruv, result proved at
most 402 UTF-8 bytes), to the TypeScript copy (number_ranges.mjs, run in Lair's Electron when available)
and to an independent oracle that finds runs with itertools.groupby on value - index and picks the cut
as the largest prefix that fits by trying every prefix (not the TS early break).
Domain: integers in -10^15..10^15. Inputs: empty, single numbers, runs through zero, the domain ends,
unsorted lists and duplicates (the TS does not require order), and lists whose joined text is exactly
397..403 characters long or whose cut lands exactly on 397.
"""
import argparse
import itertools
import json
import random
import sys

sys.dont_write_bytecode = True

NAME = 'number_ranges'
LIMIT = 10 ** 15

HARNESS = '''#![allow(dead_code, unused_imports)]
#[path = "@SOL@"] mod sol;
use std::io::{self, BufRead, Write};
fn main() {
  let out = io::stdout(); let mut out = out.lock();
  for line in io::stdin().lock().lines() {
    let line = line.unwrap();
    let v: Vec<i64> = line.split(' ').skip(1).map(|x| x.parse().unwrap()).collect();
    writeln!(out, "x{}", sol::number_ranges(&v)).unwrap();
  }
}
'''


def oracle(nums):
    parts = []
    for _, g in itertools.groupby(enumerate(nums), key=lambda p: p[1] - p[0]):
        g = [v for _, v in g]
        parts.append(str(g[0]) if len(g) == 1 else '%d-%d' % (g[0], g[-1]))
    full = ', '.join(parts)
    if len(full) <= 400:
        return full
    best = max(k for k in range(len(parts) + 1) if len(', '.join(parts[:k])) + 3 <= 400 or k == 0)
    return ', '.join(parts[:best]) + ', …'


def rand_num(r):
    return r.choice([lambda: r.randrange(-3, 30), lambda: r.randrange(1, 10 ** r.randrange(1, 16)),
                     lambda: -r.randrange(1, 10 ** r.randrange(1, 16)), lambda: r.choice([LIMIT, -LIMIT, LIMIT - 1, 1 - LIMIT])])()


def rand_list(r, size):
    kind = r.randrange(4)
    if kind == 0:   # ascending with runs (Lair's shape)
        v, out = r.randrange(-5, 10 ** r.randrange(1, 15)), []
        for _ in range(size):
            out.append(v)
            v += r.choice([1, 1, 1, 2, 3, r.randrange(1, 10 ** r.randrange(1, 8))])
        return [x for x in out if -LIMIT <= x <= LIMIT]
    if kind == 1:   # free numbers
        return [rand_num(r) for _ in range(size)]
    if kind == 2:   # duplicates and descents
        v, out = r.randrange(-20, 20), []
        for _ in range(size):
            out.append(v)
            v += r.choice([-1, 0, 1, 1, 2])
        return out
    base = r.randrange(-LIMIT, LIMIT - size)
    return [base + i + (r.randrange(3) == 0) * i for i in range(size) if base + 2 * i <= LIMIT]


def cases(n, seed):
    rows = [[], [0], [-0], [1], [-1], [LIMIT], [-LIMIT], [-LIMIT, 1 - LIMIT], [LIMIT - 1, LIMIT],
            [-2, -1, 0, 1, 2], [1, 2, 3, 5, 6, 8], [3, 3], [5, 4, 3], [1, 3, 2, 3, 4],
            list(range(1, 1000)), list(range(1, 2000, 2)), [LIMIT] * 30, [-LIMIT, LIMIT] * 15]
    # Singles of d digits two apart: joined length n * d + 2 * (n - 1); then a last number one digit
    # longer or shorter tunes the length by one, so every total 390..410 and every cut 395..400 appears.
    for d in range(1, 16):
        for count in range(max(1, 380 // (d + 2)), 412 // (d + 2) + 2):
            for tail in (0, 1, -1):
                lo = 10 ** (d - 1) if d > 1 else 0
                nums = [lo + 2 * i for i in range(count)]
                if tail and count > 1:
                    td = d + tail
                    if not 1 <= td <= 15:
                        continue
                    nums[-1] = max(nums[-2] + 2, 10 ** (td - 1)) if tail > 0 else (10 ** (td - 1) if td > 1 else 0)
                for neg in (False, True):
                    rows.append([-x for x in nums] if neg else nums)
                    rows.append((nums + [nums[-1] + 2, nums[-1] + 3]) if not neg else [-x for x in nums] + [LIMIT])
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
            cut=sum(1 for x in expected if x.endswith('…')),
            length_396_to_400=sum(1 for x in expected if 396 <= len(x) <= 400),
            max_length=max(len(x) for x in expected))
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
                    pruv = [line[1:] for line in run([exe], payload).splitlines()]
                    assert len(pruv) == len(inputs)
                    for i, (c, p, t, want) in enumerate(zip(inputs, pruv, ts, expected)):
                        if p != t or p != want:
                            differences.append(dict(compiler_backend=key, case_index=i, input=c[:60], pruv=p, ts=t, expected=want))
                    row.update(cases=len(inputs), pruv_oracle_pass=sum(p == w for p, w in zip(pruv, expected)),
                               ts_oracle_pass=summary['ts_oracle_pass'],
                               pruv_ts_pass=sum(p == t for p, t in zip(pruv, ts)))
                    row['status'] = 'ok' if row['pruv_oracle_pass'] == len(inputs) else 'wrong'
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
