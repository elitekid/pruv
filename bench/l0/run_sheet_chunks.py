#!/usr/bin/env python3
"""Cross-check the Lair extractSheets grouping and rangeOf (src/documents/sheets.ts).

Each [sheetName, rows, max] (one sheet, limits never reached) goes to the TypeScript copy
(sheet_chunks.mjs, run in Lair's Electron when available: the verbatim extractSheets with its rowPieces),
to Pruv and to an independent oracle. The row pieces come from the rowPieces oracle of run_row_pieces.py
(cross-checked against Pruv row_pieces.pruv in the eleventh bundle); Pruv sheet_chunks.pruv groups them
(sheet_groups: per piece the row, col1, col2 and the UTF-16 length of the text, plus the UTF-16 length of
the header "[시트: name]\\n" and max) and names the ranges (range_of); the runner joins the piece texts of
each group under the header. The oracle groups with Python list sums and min/max. range_of is also checked
alone for rows and columns up to 10^15 against a Python bijective base 26, and malformed piece arrays
must give [-1].
Domain: integer 1 <= max <= 2^40.
Inputs: empty sheets, empty rows, row gaps of 49 to 52 rows (FAR_ROWS = 50), chunks landing exactly on max,
max below the header (every piece alone), long rows cut into several pieces, columns past Z and ZZ, sheet
names with 4-byte characters and the empty name.
"""
import argparse
import json
import random
import sys

sys.dont_write_bytecode = True

from run_split_text import gen_text
from run_row_pieces import oracle as row_oracle, cell_text, letters, u16

NAME = 'sheet_chunks'

HARNESS = '''#![allow(dead_code, unused_imports)]
#[path = "@SOL@"] mod sol;
use std::io::{self, BufRead, Write};
fn main() {
  let out = io::stdout(); let mut out = out.lock();
  for line in io::stdin().lock().lines() {
    let line = line.unwrap();
    let mut it = line.split(' ');
    let kind = it.next().unwrap();
    let mut v: Vec<i64> = it.map(|x| x.parse().unwrap()).collect();
    if kind == "r" {
      writeln!(out, "x {}", sol::range_of(v[0], v[1], v[2], v[3])).unwrap();
      continue;
    }
    let header = v.remove(0); let max = v.remove(0);
    let n = [v.remove(0) as usize, v.remove(0) as usize, v.remove(0) as usize, v.remove(0) as usize];
    let mut at = 0; let mut a: Vec<Vec<i64>> = Vec::new();
    for k in n { a.push(v[at..at+k].to_vec()); at += k; }
    let r = sol::sheet_groups(&a[0], &a[1], &a[2], &a[3], header, max);
    let mut words: Vec<String> = Vec::new();
    if r.len() == 1 { words.push("-1".into()); }
    for g in r.chunks(6) {
      if g.len() < 6 { break; }
      for x in g { words.push(x.to_string()); }
      words.push(sol::range_of(g[2], g[3], g[4], g[5]).to_string());
    }
    writeln!(out, "x {}", words.join(" ")).unwrap();
  }
}
'''

FAR_ROWS = 50


def range_text(r1, r2, c1, c2):
    if r1 == r2 and c1 == c2:
        return '%s%d' % (letters(c1), r1)
    return '%s%d:%s%d' % (letters(c1), r1, letters(c2), r2)


def pieces(rows, mx):
    out = []
    for r, row in enumerate(rows):
        out.extend(row_oracle([cell_text(c) for c in row], r + 1, mx))
    return out


def oracle(name, rows, mx):
    header = '[시트: %s]\n' % name
    groups, cur = [], []

    def close():
        if cur:
            r1, r2 = min(p[0] for p in cur), max(p[0] for p in cur)
            c1, c2 = min(p[1] for p in cur), max(p[2] for p in cur)
            groups.append([range_text(r1, r2, c1, c2), r1, r2, c1, c2, header + '\n'.join(p[3] for p in cur)])

    for p in pieces(rows, mx):
        if cur and (u16(header) + sum(u16(q[3]) + 1 for q in cur) + u16(p[3]) + 1 > mx or p[0] - cur[-1][0] > FAR_ROWS):
            close()
            cur = []
        cur.append(p)
    close()
    return groups


def payload_line(name, ps, mx):
    cols = [[p[0] for p in ps], [p[1] for p in ps], [p[2] for p in ps], [u16(p[3]) for p in ps]]
    return 'g ' + ' '.join(map(str, [u16('[시트: %s]\n' % name), mx] + [len(c) for c in cols] + sum(cols, []))) + '\n'


def decode(words, name, ps):
    header = '[시트: %s]\n' % name
    out = []
    for k in range(0, len(words), 7):
        f, t, r1, r2, c1, c2 = map(int, words[k:k + 6])
        out.append([words[k + 6], r1, r2, c1, c2, header + '\n'.join(p[3] for p in ps[f:t + 1])])
    return out


def cases(n, seed):
    r = random.Random(seed)
    out = []
    for mx in (1, 5, 9, 12, 20, 30, 40, 60, 200):
        for name in ('S', '', '시트1', '\U0001f600x'):
            for rows in ([], [[]], [[None]], [['a']], [['a'], ['b']], [['a', None, 'b'], [], [1, 2]],
                         [[None] * 30 + ['z']], [['x' * 300]], [['a b ' * 40, 'c']]):
                out.append((name, rows, mx))
    # Gaps around FAR_ROWS, with a chunk large enough not to be the reason.
    for gap in (1, 48, 49, 50, 51, 52, 100):
        for second in (['b'], [None, 'b'], [None, None, None, 'b', 'c']):
            out.append(('S', [['a']] + [[]] * (gap - 1) + [second], 1000))
            out.append(('S', [['a'], ['c']] + [[]] * (gap - 1) + [second] + [[]] * gap + [['d']], 1000))
    # Chunk size exactly at max, one under and one over (header 4 for name 'S', pieces '행 R: ' + text).
    for mx in range(5, 40):
        for a in range(1, 12):
            for b in range(1, 6):
                out.append(('S', [['a' * a], ['b' * b]], mx))
                out.append(('S', [['a' * a], ['b' * b], ['c']], mx))
    # Columns past Z and ZZ in the ranges.
    for col in (26, 27, 52, 53, 702, 703, 731):
        out.append(('S', [[None] * (col - 1) + ['v'], ['w'] + [None] * (col + 1) + ['x']], 60))
        out.append(('S', [[None] * (col - 1) + ['v']], 1000))
    edges = len(out)
    for i in range(n):
        weights = [r.randrange(1, 12), r.randrange(3), r.randrange(2), r.randrange(3), r.randrange(2), r.randrange(4)]
        mx = r.choice([r.randrange(1, 30), r.randrange(1, 100), r.randrange(100, 400), r.randrange(100, 3000)])
        name = gen_text(r, r.choice([0, 1, 3, r.randrange(0, 20)]), weights).replace('\n', ' ')
        rows = []
        for _ in range(r.choice([r.randrange(0, 6), r.randrange(0, 30), r.randrange(0, 150)])):
            if r.randrange(4) == 0:
                rows.extend([[]] * r.choice([1, r.randrange(1, 60), r.randrange(40, 60)]))
            cells = []
            for _ in range(r.choice([r.randrange(0, 4), r.randrange(0, 12)])):
                kind = r.randrange(10)
                if kind < 3:
                    cells.append(None if kind else '')
                elif kind == 3:
                    cells.append(r.choice([True, False, r.randrange(-10**6, 10**6)]))
                else:
                    cells.append(gen_text(r, r.choice([1, r.randrange(0, 12), r.randrange(0, 2 * max(mx, 100))]), weights))
            rows.append(cells)
        out.append((name, rows, mx))
    return out, edges


def range_cases(seed):
    r = random.Random(seed)
    vals = [1, 2, 9, 10, 25, 26, 27, 51, 52, 53, 701, 702, 703, 18278, 18279, 10**6, 10**15 - 1, 10**15]
    out = [(a, b, c, d) for a in (1, 26, 10**15) for b in (1, 26, 10**15) for c in vals for d in (1, 702, 10**15)]
    for _ in range(4000):
        out.append(tuple(r.choice([r.randrange(1, 100), r.randrange(1, 10**6), r.randrange(1, 10**15 + 1)]) for _ in range(4)))
    for a, b in ((7, 7), (3, 9), (10**15, 10**15)):
        out.append((a, a, b, b))
    return out


# Malformed piece arrays: [header, max, rows, col1s, col2s, lens]; each must give [-1].
BAD = [(4, 10, [1], [1], [1], []), (4, 10, [1, 2], [1], [1, 1], [1, 1]), (4, 10, [0], [1], [1], [1]),
       (4, 10, [1], [0], [1], [1]), (4, 10, [1], [1], [0], [1]), (4, 10, [1], [1], [1], [-1]),
       (4, 10, [10**15 + 1], [1], [1], [1]), (4, 10, [1], [1], [1], [2**40 + 1]), (4, 10, [1, -5], [1, 1], [1, 1], [1, 1])]


def bad_line(b):
    h, m, *cols = b
    return 'g ' + ' '.join(map(str, [h, m] + [len(c) for c in cols] + sum(cols, []))) + '\n'


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--seed', type=int, default=12345)
    ap.add_argument('--n', type=int, default=20000)
    ap.add_argument('--emit', action='store_true',
                    help='only print JSON lines [name, rows, max, oracle chunks] and then '
                         '["range", row1, row2, col1, col2, text] (Node bridge test)')
    args = ap.parse_args()
    if args.n < 0:
        ap.error('--n must be nonnegative')
    if args.emit:
        for name, rows, mx in cases(args.n, args.seed)[0]:
            sys.stdout.write(json.dumps([name, rows, mx, oracle(name, rows, mx)]) + '\n')
        for x in range_cases(args.seed):
            sys.stdout.write(json.dumps(['range', *x, range_text(*x)]) + '\n')
        return 0
    from run import HERE, WORK, RESULTS, configure, run
    from run_host_within import portable
    from run_decode_bytes import ts_runtime
    summary = dict(seed=args.seed, random_cases=args.n, runs={})
    differences, failed = [], False
    try:
        g2, summary['tools'] = configure()
        inputs, summary['edge_cases'] = cases(args.n, args.seed)
        ranges = range_cases(args.seed)
        summary.update(cases=len(inputs), rows=sum(len(x[1]) for x in inputs), range_cases=len(ranges),
                       malformed_cases=len(BAD))
        ps = [pieces(rows, m) for _, rows, m in inputs]
        summary['pieces'] = sum(map(len, ps))
        expected = [oracle(*x) for x in inputs]
        summary['oracle_chunks'] = sum(map(len, expected))
        node, summary['ts_runtime'] = ts_runtime()
        ts = [json.loads(x) for x in run(node + [HERE / (NAME+'.mjs')],
                                         ''.join(json.dumps(list(x))+'\n' for x in inputs)).split('\n')[:-1]]
        assert len(ts) == len(inputs)
        payload = (''.join(payload_line(x[0], p, x[2]) for x, p in zip(inputs, ps))
                   + ''.join('r %d %d %d %d\n' % x for x in ranges) + ''.join(map(bad_line, BAD)))
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
                    lines = run([exe], payload).split('\n')[:-1]
                    assert len(lines) == len(inputs) + len(ranges) + len(BAD)
                    words = [line[2:].split(' ') if len(line) > 2 else [] for line in lines]
                    pruv = [decode(w, x[0], p) for w, x, p in zip(words, inputs, ps)]
                    for i, ((nm, rows, m), p, s, want) in enumerate(zip(inputs, pruv, ts, expected)):
                        if p != s or p != want:
                            differences.append(dict(compiler_backend=key, case_index=i, name=nm, rows=rows, max=m,
                                                    pruv=p, ts=s, expected=want))
                    got_ranges = [line[2:] for line in lines[len(inputs):len(inputs) + len(ranges)]]
                    for x, g in zip(ranges, got_ranges):
                        if g != range_text(*x):
                            differences.append(dict(compiler_backend=key, range=x, pruv=g, expected=range_text(*x)))
                    got_bad = [w for w in words[len(inputs) + len(ranges):]]
                    for b, g in zip(BAD, got_bad):
                        if g != ['-1']:
                            differences.append(dict(compiler_backend=key, malformed=b, pruv=g, expected=['-1']))
                    row_.update(cases=len(inputs), pruv_oracle_pass=sum(p == w for p, w in zip(pruv, expected)),
                                ts_oracle_pass=sum(t == w for t, w in zip(ts, expected)),
                                pruv_ts_pass=sum(p == t for p, t in zip(pruv, ts)),
                                range_pass=sum(g == range_text(*x) for x, g in zip(ranges, got_ranges)),
                                malformed_pass=sum(g == ['-1'] for g in got_bad))
                    ok = (row_['pruv_oracle_pass'] == len(inputs) and row_['range_pass'] == len(ranges)
                          and row_['malformed_pass'] == len(BAD))
                    row_['status'] = 'ok' if ok else 'wrong'
                    failed |= not ok
                    print(key+': '+json.dumps(row_), flush=True)
                except Exception as exc:
                    row_['error'] = portable(str(exc))
                    failed = True
                    print(key+': '+row_['error'], flush=True)
    except Exception as exc:
        summary['error'] = portable(str(exc))
        failed = True
    differences.sort(key=lambda d: (len(json.dumps(d)), d['compiler_backend']))
    summary.update(status='error' if failed else 'ok', difference_records_total=len(differences),
                   difference_records_saved=min(50, len(differences)),
                   difference_order='JSON length of the record, compiler/backend')
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / (NAME+'_summary.json')).write_text(json.dumps(summary, indent=2)+'\n')
    (RESULTS / (NAME+'_differences.jsonl')).write_text(''.join(json.dumps(d)+'\n' for d in differences[:50]))
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
