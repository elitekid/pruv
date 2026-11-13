#!/usr/bin/env python3
"""Cross-check the choice Lair evict makes (src/documents/archive.ts).

Each case is a folder listing (names in folder order with mtime and stored size, some without meta.json and
some not version names), a limit, a pinned set and a version to keep. It goes to Pruv (evict_stop.pruv: the
stop index of the oldest-first walk over the stored versions, proved to be the first index whose total left is
within the limit), to the TypeScript copy (evict_stop.mjs: verbatim evict on an in-memory folder, run in Lair's
Electron when available) and to an independent oracle, a bisect over the totals left after each deletable
version, not a copy of the TS loop. Pruv's stop index s turns into the deleted names (the deletable versions
among the first s); those must equal the oracle's and the names the TS copy deleted, in order.
The TS copy only runs on folders of at most 2,000 entries; folders up to 10,000 versions of 10^9 bytes and limits
near +-10^15 are checked against the oracle only.
Inputs: empty folders, limit at the total and one below it, negative limits, all pinned, the kept version first,
zero-byte versions, equal mtimes (stable sort keeps folder order), folders without meta.json, non-version
names, huge versions, and random folders with limits drawn around the totals left.
"""
import argparse
import bisect
import json
import random
import sys

sys.dont_write_bytecode = True

NAME = 'evict_stop'
TS_ENTRIES = 2000

HARNESS = '''#![allow(dead_code, unused_imports)]
#[path = "@SOL@"] mod sol;
use std::io::{self, BufRead, Write};
fn main() {
  let out = io::stdout(); let mut out = out.lock();
  for line in io::stdin().lock().lines() {
    let line = line.unwrap();
    let f: Vec<i64> = line.split(' ').skip(1).map(|x| x.parse().unwrap()).collect();
    let n = f[1] as usize;
    writeln!(out, "{}", sol::evict_stop(&f[2..2 + n], &f[2 + n..2 + 2 * n], f[0])).unwrap();
  }
}
'''


def version(i):
    return format(i * 2654435761 % (1 << 64), '016x') * 4


def walk(case):
    """The stored versions in walk order: [(name, bytes, deletable)]."""
    entries, _, pinned, keep = case
    stored = [(e['mtime'], k, e) for k, e in enumerate(entries)
              if e['bytes'] is not None and len(e['name']) == 64 and all(c in '0123456789abcdef' for c in e['name'])]
    stored.sort(key=lambda t: (t[0], t[1]))
    return [(e['name'], e['bytes'], e['name'] not in pinned and e['name'] != keep) for _, _, e in stored]


def oracle(case):
    order = walk(case)
    total = sum(b for _, b, _ in order)
    left, run_left = [], total
    for _, b, d in order:
        left.append(-run_left)
        run_left -= b if d else 0
    s = bisect.bisect_left(left, -case[1])
    return s, [name for name, _, d in order[:s] if d]


def folder(r, n, sizes):
    entries, names = [], []
    for i in range(n):
        kind = r.choice(['v'] * 8 + ['nometa', 'noise'])
        name = version(r.randrange(1, 10**12)) if kind != 'noise' else r.choice(['.tmp-%d' % i, '.old-%d' % i, 'x%d' % i])
        entries.append(dict(name=name, mtime=r.choice([0, 1, 2, r.randrange(0, 50000)]),
                            bytes=None if kind != 'v' else sizes(r)))
        if kind == 'v':
            names.append(name)
    return entries, names


def cases(n, seed):
    a, b, c = version(1), version(2), version(3)
    g = 10**9

    def f(*items):
        return [dict(name=x, mtime=m, bytes=s) for x, m, s in items]
    three = f((a, 3, 10), (b, 1, 20), (c, 2, 30))
    rows = [([], 0, [], ''), ([], -1, [], ''), (f((a, 0, 5)), 5, [], ''), (f((a, 0, 5)), 4, [], ''),
            (f((a, 0, 5)), 4, [a], ''), (f((a, 0, 5)), 4, [], a), (f((a, 0, 0)), -1, [], ''),
            (three, 60, [], ''), (three, 59, [], ''), (three, 40, [], ''), (three, 39, [], ''), (three, 10, [], ''),
            (three, 9, [], ''), (three, 0, [], ''), (three, -1, [], ''), (three, 0, [b], ''), (three, 0, [], b),
            (three, 0, [a, b, c], ''), (three, 0, [b], c), (three, 30, [b], a),
            (f((a, 1, 10), (b, 1, 20), (c, 1, 30)), 35, [], ''), (f((c, 1, 10), (b, 1, 20), (a, 1, 30)), 35, [], ''),
            (f((a, 0, 0), (b, 0, 0), (c, 0, 7)), 6, [], ''), (f((a, 0, 0), (b, 0, 0), (c, 0, 7)), 7, [], ''),
            (f((a, 0, 5), ('.tmp-1', 0, 99), (b, 0, None), (c, 0, 5)), 5, [], ''),
            (f((a.upper(), 0, 5), (b, 0, 5)), 0, [], ''), (f((a, 0, g), (b, 1, g)), g, [], ''),
            (f((a, 0, g), (b, 1, g)), g - 1, [], ''), (f((a, 0, g)), -10**15, [], ''),
            ([dict(name=version(i), mtime=i % 7, bytes=g) for i in range(1, 10001)], 10**13, [], ''),
            ([dict(name=version(i), mtime=i % 7, bytes=g) for i in range(1, 10001)], 10**13 - 1, [], ''),
            ([dict(name=version(i), mtime=0, bytes=g) for i in range(1, 10001)], 5 * 10**12, [], version(1)),
            ([dict(name=version(i), mtime=i, bytes=g) for i in range(1, 10001)], 10**15, [], ''),
            ([dict(name=version(i), mtime=i, bytes=1) for i in range(1, 2001)], 1000, [version(i) for i in range(1, 2001, 3)], ''),
            ([dict(name=version(i), mtime=-i, bytes=i) for i in range(1, 2001)], 0, [], version(2000))]
    edges = len(rows)
    r = random.Random(seed)
    for _ in range(n):
        entries, names = folder(r, r.randrange(0, 14), lambda r: r.choice([0, r.randrange(1, 4), r.randrange(1, 400)]))
        pinned = r.sample(names, r.randrange(0, len(names) + 1)) if names and r.random() < 0.5 else []
        keep = r.choice(names) if names and r.random() < 0.5 else r.choice(['', version(0)])
        case = (entries, 0, pinned, keep)
        order = walk(case)
        total = sum(x for _, x, _ in order)
        lefts, run_left = [total], total
        for _, x, d in order:
            run_left -= x if d else 0
            lefts.append(run_left)
        limit = r.choice([r.choice(lefts), r.choice(lefts) - 1, r.choice(lefts) + 1, r.randrange(-3, total + 6),
                          total, -r.randrange(1, 100)])
        rows.append((entries, limit, pinned, keep))
    return rows, edges


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--seed', type=int, default=12345)
    ap.add_argument('--n', type=int, default=20000)
    ap.add_argument('--emit', action='store_true',
                    help='only print JSON lines [bytes, free, limit, oracle stop, TS runs (at most 2,000 entries)]')
    args = ap.parse_args()
    if args.n < 0:
        ap.error('--n must be nonnegative')
    inputs, edges = cases(args.n, args.seed)
    expected = [oracle(c) for c in inputs]
    walks = [walk(c) for c in inputs]
    if args.emit:
        for case, w, (s, names) in zip(inputs, walks, expected):
            sys.stdout.write(json.dumps([[x for _, x, _ in w], [x if d else 0 for _, x, d in w], case[1], s,
                                         len(case[0]) <= TS_ENTRIES]) + '\n')
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
        summary['oracle_outcomes'] = dict(
            delete_none=sum(not names for _, names in expected),
            stop_inside=sum(s < len(w) for (s, _), w in zip(expected, walks)),
            walk_to_end=sum(s == len(w) and len(w) > 0 for (s, _), w in zip(expected, walks)),
            skipped_some=sum(any(not d for _, _, d in w[:s]) for (s, _), w in zip(expected, walks)),
            max_versions=max(len(w) for w in walks), max_total=max(sum(x for _, x, _ in w) for w in walks),
            max_deleted=max(len(names) for _, names in expected))
        node, summary['ts_runtime'] = ts_runtime()
        ts_index = [i for i, c in enumerate(inputs) if len(c[0]) <= TS_ENTRIES]
        summary['ts_cases'] = len(ts_index)
        ts_out = [json.loads(x) for x in run(node + [HERE / (NAME+'.mjs')],
                                             ''.join(json.dumps(dict(entries=inputs[i][0], limit=inputs[i][1],
                                                                     pinned=inputs[i][2], keep=inputs[i][3]))+'\n'
                                                     for i in ts_index)).splitlines()]
        assert len(ts_out) == len(ts_index)
        ts = [None] * len(inputs)
        for i, t in zip(ts_index, ts_out):
            ts[i] = t[1] if t[0] == len(t[1]) else ['count mismatch', t[0]]
        summary['ts_oracle_pass'] = sum(ts[i] == expected[i][1] for i in ts_index)
        failed |= summary['ts_oracle_pass'] != len(ts_index)
        payload = ''.join('x %d %d %s\n' % (c[1], len(w), ' '.join([str(x) for _, x, _ in w] +
                                                                    [str(x if d else 0) for _, x, d in w]))
                          for c, w in zip(inputs, walks)).replace(' \n', '\n')
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
                    names = [[name for name, _, d in w[:s] if d] for w, s in zip(walks, pruv)]
                    for i, (case, got, gnames, t, (want, wnames)) in enumerate(zip(inputs, pruv, names, ts, expected)):
                        if got != want or gnames != wnames or (t is not None and gnames != t):
                            differences.append(dict(compiler_backend=key, case_index=i, versions=len(walks[i]),
                                                    walk=[[x, d] for _, x, d in walks[i][:60]], limit=case[1],
                                                    pruv=got, expected=want, pruv_deleted=len(gnames),
                                                    ts_deleted=None if t is None else len(t), oracle_deleted=len(wnames)))
                    row.update(cases=len(inputs), pruv_oracle_pass=sum(g == w[0] for g, w in zip(pruv, expected)),
                               ts_cases=len(ts_index), ts_oracle_pass=summary['ts_oracle_pass'],
                               pruv_ts_pass=sum(names[i] == ts[i] for i in ts_index))
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
    differences.sort(key=lambda d: (d['versions'], json.dumps(d['walk']), d['limit'], d['compiler_backend']))
    summary.update(status='error' if failed else 'ok', difference_records_total=len(differences),
                   difference_records_saved=min(50, len(differences)),
                   difference_order='version count, walk, limit, compiler/backend')
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / (NAME+'_summary.json')).write_text(json.dumps(summary, indent=2, ensure_ascii=False)+'\n')
    (RESULTS / (NAME+'_differences.jsonl')).write_text(''.join(json.dumps(d, ensure_ascii=False)+'\n' for d in differences[:50]))
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
