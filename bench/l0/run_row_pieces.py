#!/usr/bin/env python3
"""Cross-check Lair rowPieces (src/documents/sheets.ts, behind extractSheets).

Each [cells, rowNo, max] goes to Pruv (row_pieces.pruv: the cellText of every cell joined with '\\n' as
UTF-8 plus the byte end of every cell; per piece [col1, col2, nseg] and nseg segments [label column,
start, end], every read proved in bounds and every cut on a character boundary), to the TypeScript copy
(row_pieces.mjs, run in Lair's Electron when available, which applies cellText itself) and to an
independent oracle that builds the piece strings with Python lengths in UTF-16 units and reuses the
code-point splitText oracle of run_split_text.py. Cells are strings, null, booleans and integers.
Domain: integer 1 <= max <= 2^40, integer 1 <= rowNo <= 10^15.
Inputs: empty rows, empty and blank cells, column 1 and gaps (labels), parts that land exactly on
max - head, max below the head (every part alone), cells longer than the inner split width
max(max - head - 12, 100), 4-byte characters, inner newlines, columns past Z, ZZ and long rows.
"""
import argparse
import json
import random
import re
import sys

sys.dont_write_bytecode = True

from run_split_text import oracle as split_oracle, gen_text, JS_WS

NAME = 'row_pieces'

HARNESS = '''#![allow(dead_code, unused_imports)]
#[path = "@SOL@"] mod sol;
use std::io::{self, BufRead, Write};
fn main() {
  let out = io::stdout(); let mut out = out.lock();
  for line in io::stdin().lock().lines() {
    let line = line.unwrap();
    let mut it = line.split(' ');
    let row: i64 = it.next().unwrap().parse().unwrap();
    let max: i64 = it.next().unwrap().parse().unwrap();
    let n: usize = it.next().unwrap().parse().unwrap();
    let ends: Vec<i64> = (0..n).map(|_| it.next().unwrap().parse().unwrap()).collect();
    let hex = &it.next().unwrap()[1..];
    let data: Vec<u8> = (0..hex.len()).step_by(2).map(|i| u8::from_str_radix(&hex[i..i+2], 16).unwrap()).collect();
    let s = String::from_utf8(data).unwrap();
    let r = sol::row_bounds(&s, &ends, row, max);
    let v: Vec<String> = r.iter().map(|x| x.to_string()).collect();
    writeln!(out, "x {}", v.join(" ")).unwrap();
  }
}
'''


def u16(t):
    return sum(2 if ord(c) > 0xffff else 1 for c in t)


def letters(col):
    """Bijective base 26: A..Z, AA.. (length blocks of 26^k)."""
    k, size, rest = 1, 26, col - 1
    while rest >= size:
        rest -= size
        k += 1
        size *= 26
    out = ''
    for _ in range(k):
        out = chr(65 + rest % 26) + out
        rest //= 26
    return out


def js_trim(t):
    a, b = 0, len(t)
    while a < b and ord(t[a]) in JS_WS:
        a += 1
    while b > a and ord(t[b - 1]) in JS_WS:
        b -= 1
    return t[a:b]


def cell_text(v):
    """cellText for the JSON cell kinds used here (strings, null, booleans, integers)."""
    if v is None:
        return ''
    if isinstance(v, bool):
        return 'TRUE' if v else 'FALSE'
    if isinstance(v, int):
        return str(v)
    return js_trim(re.sub('\r?\n', ' ', v))


def oracle(texts, row, mx):
    head = '행 %d: ' % row
    room = mx - u16(head)
    width = max(mx - u16(head) - 12, 100)
    out = []
    cur = []          # segments of the open piece: (column, string)
    for i, value in enumerate(texts):
        if not value:
            continue
        col = i + 1
        for part in split_oracle(value, width):
            last = cur[-1][0] if cur else None
            labelled = (last != col and col != last + 1) if cur else col != 1
            seg = letters(col) + '=' + part if labelled else part
            if cur and u16(' | '.join(s for _, s in cur)) + u16(seg) + 3 > room:
                out.append([row, cur[0][0], cur[-1][0], head + ' | '.join(s for _, s in cur)])
                cur = []
                seg = letters(col) + '=' + part if col != 1 else part
            cur.append((col, seg))
    if cur:
        out.append([row, cur[0][0], cur[-1][0], head + ' | '.join(s for _, s in cur)])
    return out


def joined(texts):
    """The Pruv input: UTF-8 of the texts joined with '\\n' and the byte end of each text."""
    ends, at = [], 0
    for k, t in enumerate(texts):
        at += (1 if k else 0) + len(t.encode())
        ends.append(at)
    return '\n'.join(texts).encode(), ends


def decode(v, raw, row):
    """Pruv slots back to [row, col1, col2, text]."""
    head = '행 %d: ' % row
    out, k = [], 0
    while k < len(v):
        col1, col2, nseg = v[k:k + 3]
        segs = []
        for q in range(nseg):
            lab, a, b = v[k + 3 + 3 * q:k + 6 + 3 * q]
            segs.append((letters(lab) + '=' if lab else '') + raw[a:b].decode())
        out.append([row, col1, col2, head + ' | '.join(segs)])
        k += 3 + 3 * nseg
    return out


def cases(n, seed):
    r = random.Random(seed)
    rows = []
    for mx in (1, 5, 8, 9, 10, 12, 20, 40, 116, 117, 118, 200):
        for cells in ([], [''], [None], ['a'], ['', 'a'], ['a', 'b'], ['a', '', 'b'], ['', '', 'a', 'b', '', 'c'],
                      [' ', '\t', '　'], ['a\nb', 'c\r\nd', 'e\rf'], [True, False, 0, -7, 123456789012345],
                      ['\U0001f600' * 3, 'x'], ['a' * 101, 'b'], ['', 'a' * 250 + ' ' + 'b' * 30],
                      ['x' * 400], ['a b ' * 60, None, 'c']):
            for row in (1, 9, 10, 12345):
                rows.append((list(cells), row, mx))
    # Two and three parts that land exactly on max - head, one under and one over (head 5 at row 1).
    for mx in range(5, 24):
        for a in range(1, mx + 2):
            for b in range(1, 5):
                rows.append((['a' * a, 'b' * b, 'c'], 1, mx))
                rows.append((['a' * a, '', 'b' * b, 'c'], 1, mx))
    # Columns past Z, ZZ.
    for col in (26, 27, 52, 53, 702, 703, 731):
        rows.append(([None] * (col - 1) + ['v', 'w', None, 'x'], 3, 60))
        rows.append((['a'] + [None] * (col - 2) + ['v'], 3, 9))
    for row in (1, 9, 10, 99, 100, 10**15 - 1, 10**15):
        rows.append((['a', '', 'b' * 30], row, 30))
    edges = len(rows)
    for i in range(n):
        weights = [r.randrange(1, 12), r.randrange(3), r.randrange(2), r.randrange(3), r.randrange(2), r.randrange(4)]
        mx = r.choice([r.randrange(1, 30), r.randrange(1, 60), r.randrange(100, 400), r.randrange(100, 2000)])
        row = r.choice([1, r.randrange(1, 1000), r.randrange(1, 10**6), r.randrange(1, 10**15 + 1)])
        ncell = r.choice([r.randrange(0, 8), r.randrange(0, 30)]) if i % 100 else r.randrange(100, 800)
        cells = []
        for _ in range(ncell):
            kind = r.randrange(12)
            if kind < 3:
                cells.append(None if kind else '')
            elif kind == 3:
                cells.append(r.choice([True, False, r.randrange(-10**6, 10**6)]))
            else:
                length = r.choice([1, r.randrange(0, 12), r.randrange(0, 40), r.randrange(0, 3 * max(mx, 100))])
                cells.append(gen_text(r, length, weights))
        rows.append((cells, row, mx))
    return rows, edges


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--seed', type=int, default=12345)
    ap.add_argument('--n', type=int, default=20000)
    ap.add_argument('--emit', action='store_true',
                    help='only print JSON lines [cells, rowNo, max, oracle pieces] (Node bridge test)')
    args = ap.parse_args()
    if args.n < 0:
        ap.error('--n must be nonnegative')
    if args.emit:
        for cells, row, mx in cases(args.n, args.seed)[0]:
            sys.stdout.write(json.dumps([cells, row, mx, oracle([cell_text(c) for c in cells], row, mx)]) + '\n')
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
        summary['cells'] = sum(len(c) for c, _, _ in inputs)
        texts = [[cell_text(c) for c in cells] for cells, _, _ in inputs]
        expected = [oracle(t, row, m) for t, (_, row, m) in zip(texts, inputs)]
        summary['oracle_pieces'] = sum(map(len, expected))
        node, summary['ts_runtime'] = ts_runtime()
        ts = [json.loads(x) for x in run(node + [HERE / (NAME+'.mjs')],
                                         ''.join(json.dumps(list(x))+'\n' for x in inputs)).split('\n')[:-1]]
        assert len(ts) == len(inputs)
        payload = []
        for t, (_, row, m) in zip(texts, inputs):
            raw, ends = joined(t)
            payload.append(' '.join([str(row), str(m), str(len(ends))] + [str(e) for e in ends] + ['x' + raw.hex()]) + '\n')
        payload = ''.join(payload)
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
                    pruv = [decode([int(y) for y in line[2:].split()], joined(t)[0], x[1])
                            for t, x, line in zip(texts, inputs, lines)]
                    for i, ((c, rw, m), p, s, want) in enumerate(zip(inputs, pruv, ts, expected)):
                        if p != s or p != want:
                            differences.append(dict(compiler_backend=key, case_index=i, cells=c, row=rw, max=m,
                                                    pruv=p, ts=s, expected=want))
                    row_.update(cases=len(inputs), pruv_oracle_pass=sum(p == w for p, w in zip(pruv, expected)),
                                ts_oracle_pass=sum(t == w for t, w in zip(ts, expected)),
                                pruv_ts_pass=sum(p == t for p, t in zip(pruv, ts)))
                    row_['status'] = 'ok' if row_['pruv_oracle_pass'] == len(inputs) else 'wrong'
                    failed |= row_['status'] != 'ok'
                    print(key+': '+json.dumps(row_), flush=True)
                except Exception as exc:
                    row_['error'] = portable(str(exc))
                    failed = True
                    print(key+': '+row_['error'], flush=True)
    except Exception as exc:
        summary['error'] = portable(str(exc))
        failed = True
    differences.sort(key=lambda d: (len(json.dumps(d['cells'])), d['max'], d['compiler_backend']))
    summary.update(status='error' if failed else 'ok', difference_records_total=len(differences),
                   difference_records_saved=min(50, len(differences)),
                   difference_order='JSON length of the cells, max, compiler/backend')
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / (NAME+'_summary.json')).write_text(json.dumps(summary, indent=2)+'\n')
    (RESULTS / (NAME+'_differences.jsonl')).write_text(''.join(json.dumps(d)+'\n' for d in differences[:50]))
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
