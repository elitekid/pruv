#!/usr/bin/env python3
"""Cross-check Lair groupNumbered (src/documents/chunker.ts, behind chunkLines and chunkBlocks).

Each [lines, max] goes to Pruv (group_text.pruv: the lines joined with '\\n' as UTF-8 plus the byte end
of every line; records [from, to, start, end] with every read proved in bounds and every cut on a
character boundary), to the TypeScript copy (group_text.mjs, run in Lair's Electron when available)
and to an independent oracle that sums UTF-16 lengths per group and reuses the code-point splitText
oracle of run_split_text.py. Domain: integer max >= 2 (splitText can loop forever below that).
Inputs: empty lists, empty and blank lines, lines exactly at max and max + 1, groups that land exactly
on max, lines with 4-byte characters and inner newlines (DOCX blocks), long documents.
"""
import argparse
import json
import random
import sys

sys.dont_write_bytecode = True

from run_split_text import oracle as split_oracle, gen_text

NAME = 'group_text'

HARNESS = '''#![allow(dead_code, unused_imports)]
#[path = "@SOL@"] mod sol;
use std::io::{self, BufRead, Write};
fn main() {
  let out = io::stdout(); let mut out = out.lock();
  for line in io::stdin().lock().lines() {
    let line = line.unwrap();
    let mut it = line.split(' ');
    let max: i64 = it.next().unwrap().parse().unwrap();
    let n: usize = it.next().unwrap().parse().unwrap();
    let ends: Vec<i64> = (0..n).map(|_| it.next().unwrap().parse().unwrap()).collect();
    let hex = &it.next().unwrap()[1..];
    let data: Vec<u8> = (0..hex.len()).step_by(2).map(|i| u8::from_str_radix(&hex[i..i+2], 16).unwrap()).collect();
    let s = String::from_utf8(data).unwrap();
    let r = sol::group_bounds(&s, &ends, max);
    let v: Vec<String> = r.iter().map(|x| x.to_string()).collect();
    writeln!(out, "x {}", v.join(" ")).unwrap();
  }
}
'''


def u16(t):
    return sum(2 if ord(c) > 0xffff else 1 for c in t)


def oracle(lines, mx):
    """Groups as lists of line numbers; a group's cost is the sum of (length + 1) of its lines."""
    out, group, cost = [], [], 0

    def close():
        if group:
            text = '\n'.join(lines[g - 1] for g in group)
            pieces = split_oracle(text, 1 << 40)   # only the trim (no cut below 2^40 units)
            if pieces:
                out.append([group[0], group[-1], pieces[0]])

    for n, line in enumerate(lines, 1):
        length = u16(line)
        if length > mx:
            close()
            group, cost = [], 0
            out.extend([n, n, p] for p in split_oracle(line, mx))
        elif group and cost + length + 1 > mx:
            close()
            group, cost = [n], length + 1
        else:
            group.append(n)
            cost += length + 1
    close()
    return out


def joined(lines):
    """The Pruv input: UTF-8 of the lines joined with '\\n' and the byte end of each line."""
    ends, at = [], 0
    for k, line in enumerate(lines):
        at += (1 if k else 0) + len(line.encode())
        ends.append(at)
    return '\n'.join(lines).encode(), ends


def cases(n, seed):
    r = random.Random(seed)
    rows = []
    for mx in (2, 3, 4, 5, 8):
        for lines in ([], [''], ['', ''], [' '], ['a'], ['a' * mx], ['a' * (mx + 1)], ['a' * (mx - 1), 'b'],
                      ['a' * (mx - 2), 'b'], ['', 'a' * mx, ''], [' ', '\t', '　'], ['\U0001f600' * mx],
                      ['a\nb', 'c'], ['x', 'a' * (2 * mx + 1), 'y', 'z'], ['ab', 'cd', '', 'efghij']):
            rows.append((list(lines), mx))
    # Groups that land exactly on max, one under and one over.
    for mx in range(2, 14):
        for a in range(0, mx + 2):
            for b in range(0, mx + 2):
                rows.append((['a' * a, 'b' * b, 'c'], mx))
    edges = len(rows)
    for i in range(n):
        weights = [r.randrange(1, 10), r.randrange(4), r.randrange(3), r.randrange(4), r.randrange(3), r.randrange(5)]
        if i % 50 == 0:
            mx = r.randrange(50, 1600)
            lines = [gen_text(r, r.choice([0, r.randrange(0, 80), r.randrange(0, 3 * mx)]), weights)
                     for _ in range(r.randrange(20, 200))]
        else:
            mx = r.choice([2, 3, 4, r.randrange(2, 40)])
            lines = [gen_text(r, r.choice([0, 1, r.randrange(0, 2 * mx + 3)]), weights) for _ in range(r.randrange(0, 12))]
        rows.append((lines, mx))
    return rows, edges


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--seed', type=int, default=12345)
    ap.add_argument('--n', type=int, default=20000)
    ap.add_argument('--emit', action='store_true',
                    help='only print JSON lines [lines, max, oracle records] (Node bridge test)')
    args = ap.parse_args()
    if args.n < 0:
        ap.error('--n must be nonnegative')
    if args.emit:
        for lines, mx in cases(args.n, args.seed)[0]:
            sys.stdout.write(json.dumps([lines, mx, oracle(lines, mx)]) + '\n')
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
        summary['lines'] = sum(len(x) for x, _ in inputs)
        expected = [oracle(x, m) for x, m in inputs]
        summary['oracle_pieces'] = sum(map(len, expected))
        node, summary['ts_runtime'] = ts_runtime()
        ts = [json.loads(x) for x in run(node + [HERE / (NAME+'.mjs')], ''.join(json.dumps([x, m])+'\n' for x, m in inputs)).split('\n')[:-1]]
        assert len(ts) == len(inputs)
        payload = []
        for x, m in inputs:
            raw, ends = joined(x)
            payload.append(' '.join([str(m), str(len(ends))] + [str(e) for e in ends] + ['x' + raw.hex()]) + '\n')
        payload = ''.join(payload)
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
                    pruv = []
                    for (x, m), line in zip(inputs, lines):
                        v = [int(y) for y in line[2:].split()]
                        raw = joined(x)[0]
                        pruv.append([[v[k]+1, v[k+1]+1, raw[v[k+2]:v[k+3]].decode()] for k in range(0, len(v), 4)])
                    for i, ((x, m), p, s, want) in enumerate(zip(inputs, pruv, ts, expected)):
                        if p != s or p != want:
                            differences.append(dict(compiler_backend=key, case_index=i, lines=x, max=m,
                                                    pruv=p, ts=s, expected=want))
                    row.update(cases=len(inputs), pruv_oracle_pass=sum(p == w for p, w in zip(pruv, expected)),
                               ts_oracle_pass=sum(t == w for t, w in zip(ts, expected)),
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
    differences.sort(key=lambda d: (sum(map(len, d['lines'])), d['max'], d['compiler_backend']))
    summary.update(status='error' if failed else 'ok', difference_records_total=len(differences),
                   difference_records_saved=min(50, len(differences)),
                   difference_order='total line length, max, compiler/backend')
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / (NAME+'_summary.json')).write_text(json.dumps(summary, indent=2)+'\n')
    (RESULTS / (NAME+'_differences.jsonl')).write_text(''.join(json.dumps(d)+'\n' for d in differences[:50]))
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
