#!/usr/bin/env python3
"""Cross-check Lair splitText (src/documents/chunker.ts), the page-text splitter for document search.

Each [text, max] goes to Pruv (split_text.pruv: UTF-8 bytes with UTF-16 unit counting, every read
proved in bounds and every cut on a character boundary), to the TypeScript copy (split_text.mjs, run
in Lair's Electron when available) and to an independent oracle that works on a list of code points
with their UTF-16 widths and an explicit JS whitespace table. Pruv returns byte ranges; the runner
slices the UTF-8 text with them. Domain: integer max >= 2 (TS can loop forever below that).
Inputs: every JS trim whitespace character and near misses (U+0085, U+180E, U+200B, ...), 4-byte
characters at the cut, lines and spaces just below and at max / 2, max 2 and 3, long pages.
"""
import argparse
import json
import random
import sys

sys.dont_write_bytecode = True

NAME = 'split_text'

HARNESS = '''#![allow(dead_code, unused_imports)]
#[path = "@SOL@"] mod sol;
use std::io::{self, BufRead, Write};
fn main() {
  let out = io::stdout(); let mut out = out.lock();
  for line in io::stdin().lock().lines() {
    let line = line.unwrap(); let (max, hex) = line.split_once(' ').unwrap();
    let hex = &hex[1..];
    let data: Vec<u8> = (0..hex.len()).step_by(2).map(|i| u8::from_str_radix(&hex[i..i+2], 16).unwrap()).collect();
    let s = String::from_utf8(data).unwrap();
    let r = sol::split_bounds(&s, max.parse().unwrap());
    let v: Vec<String> = r.iter().map(|x| x.to_string()).collect();
    writeln!(out, "x {}", v.join(" ")).unwrap();
  }
}
'''

# ECMAScript WhiteSpace and LineTerminator, the set String.prototype.trim removes.
JS_WS = {0x09, 0x0a, 0x0b, 0x0c, 0x0d, 0x20, 0xa0, 0x1680, *range(0x2000, 0x200b),
         0x2028, 0x2029, 0x202f, 0x205f, 0x3000, 0xfeff}
NEAR = [0x85, 0x180e, 0x200b, 0x200c, 0x2027, 0x202a, 0x205e, 0x2060, 0x3001, 0xfefe, 0x1681,
        0xa1, 0x9f, 0x1c, 0x1f, 0x7f, 0x2080]
WORD = [ord(c) for c in 'abcXYZ09.,-'] + [0xac00, 0xd55c, 0x4e2d, 0xe9, 0x3b1]
ASTRAL = [0x1f600, 0x1d400, 0x10000, 0x10ffff, 0x20000]


def oracle(text, mx):
    """Code points with UTF-16 widths. A unit position p maps to the code point holding it."""
    cps = [ord(c) for c in text]
    lo, hi = 0, len(cps)
    while lo < hi and cps[lo] in JS_WS:
        lo += 1
    while hi > lo and cps[hi-1] in JS_WS:
        hi -= 1
    out = []
    while True:
        rest = cps[lo:hi]
        starts, u = [], 0              # unit position of each code point of rest
        for c in rest:
            starts.append(u)
            u += 2 if c > 0xffff else 1
        if u <= mx:
            break

        def last(ch):
            hits = [k for k, c in enumerate(rest) if c == ch and starts[k] <= mx]
            return (starts[hits[-1]], hits[-1]) if hits else (-1, -1)
        cut_u, cut_k = last(10)
        if 2 * cut_u < mx:
            cut_u, cut_k = last(32)
        if 2 * cut_u < mx:
            # unit mx: the code point starting there, or the one it falls inside (moved back to its start)
            cut_k = max(k for k in range(len(rest)) if starts[k] <= mx)
        piece = rest[:cut_k]
        a, b = 0, len(piece)
        while a < b and piece[a] in JS_WS:
            a += 1
        while b > a and piece[b-1] in JS_WS:
            b -= 1
        if b > a:
            out.append(''.join(map(chr, piece[a:b])))
        lo += cut_k
        while lo < hi and cps[lo] in JS_WS:
            lo += 1
    if hi > lo:
        out.append(''.join(map(chr, cps[lo:hi])))
    return out


def gen_text(r, n, weights):
    pools = [WORD, sorted(JS_WS), NEAR, ASTRAL, [10], [32]]
    return ''.join(chr(r.choice(pools[r.choices(range(6), weights)[0]])) for _ in range(n))


def cases(n, seed):
    r = random.Random(seed)
    rows = []
    for mx in (2, 3, 4, 5):
        for t in ('', ' ', '\n\n', 'a', 'ab', 'abc', 'abcd', 'abcde', '\U0001f600', 'a\U0001f600',
                  '\U0001f600\U0001f600', 'a\U0001f600b', 'ab\U0001f600', 'a b', 'a\nb', 'ab cd', 'ab\ncd',
                  ' 　x﻿ ', '\u0085x\u0085', '​x​', 'x y z', '\U0001f600 \U0001f600'):
            rows.append((t, mx))
    for ws in sorted(JS_WS) + NEAR:
        for mx in (2, 3, 6):
            rows.append((chr(ws) + 'ab' + chr(ws) + 'cd' + chr(ws) + 'ef' + chr(ws), mx))
    # Newline or space exactly at max / 2, just below, at max and just after max.
    for mx in range(2, 13):
        for pos in sorted({mx // 2 - 1, mx // 2, (mx + 1) // 2, mx - 1, mx, mx + 1}):
            for sep in '\n ':
                if pos >= 1:
                    rows.append(('a' * pos + sep + 'b' * (2 * mx), mx))
                    rows.append(('a' * pos + sep + 'b' * 3 + '\n' + 'c' * mx, mx))
    # 4-byte characters around unit max.
    for mx in range(2, 9):
        for k in range(mx + 2):
            rows.append(('a' * k + '\U0001f600' * (mx + 2), mx))
            rows.append(('\U0001f600' * k + 'a' * (mx + 1), mx))
    edges = len(rows)
    for i in range(n):
        weights = [r.randrange(1, 10), r.randrange(4), r.randrange(3), r.randrange(4), r.randrange(4), r.randrange(5)]
        if i % 50 == 0:
            text, mx = gen_text(r, r.randrange(2000, 6000), weights), r.randrange(50, 1600)
        else:
            text, mx = gen_text(r, r.randrange(0, 120), weights), r.choice([2, 3, 4, r.randrange(2, 40)])
        rows.append((text, mx))
    return rows, edges


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--seed', type=int, default=12345)
    ap.add_argument('--n', type=int, default=20000)
    ap.add_argument('--emit', action='store_true',
                    help='only print JSON lines [text, max, oracle pieces] (Node bridge test)')
    args = ap.parse_args()
    if args.n < 0:
        ap.error('--n must be nonnegative')
    if args.emit:
        for text, mx in cases(args.n, args.seed)[0]:
            sys.stdout.write(json.dumps([text, mx, oracle(text, mx)]) + '\n')
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
        expected = [oracle(t, m) for t, m in inputs]
        summary['oracle_pieces'] = sum(map(len, expected))
        node, summary['ts_runtime'] = ts_runtime()
        ts = [json.loads(x) for x in run(node + [HERE / (NAME+'.mjs')], ''.join(json.dumps([t, m])+'\n' for t, m in inputs)).split('\n')[:-1]]
        assert len(ts) == len(inputs)
        payload = ''.join('%d x%s\n' % (m, t.encode().hex()) for t, m in inputs)
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
                    for (t, m), line in zip(inputs, lines):
                        v = [int(x) for x in line[2:].split()]
                        raw = t.encode()
                        pruv.append([raw[v[k]:v[k+1]].decode() for k in range(0, len(v), 2)])
                    for i, ((t, m), p, s, want) in enumerate(zip(inputs, pruv, ts, expected)):
                        if p != s or p != want:
                            differences.append(dict(compiler_backend=key, case_index=i, text=t, max=m,
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
    differences.sort(key=lambda d: (len(d['text']), d['text'], d['max'], d['compiler_backend']))
    summary.update(status='error' if failed else 'ok', difference_records_total=len(differences),
                   difference_records_saved=min(50, len(differences)),
                   difference_order='text length, text, max, compiler/backend')
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / (NAME+'_summary.json')).write_text(json.dumps(summary, indent=2)+'\n')
    (RESULTS / (NAME+'_differences.jsonl')).write_text(''.join(json.dumps(d)+'\n' for d in differences[:50]))
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
