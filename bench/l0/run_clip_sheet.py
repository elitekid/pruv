#!/usr/bin/env python3
"""Cross-check the pixels of Lair renderClipSheet (src/documents/clip-sheet.ts).

Each case is 1..4 cells (raw RGBA picture, number, label). The 1560 x 920 RGBA sheet before the JPEG
encode is compared by crc32 between Pruv (clip_sheet.pruv: clip_sheet_background, then clip_sheet_cell
per cell), the TypeScript copy (clip_sheet.mjs with pass-through jpeg-js stubs, run in Lair's Electron
when available) and an independent oracle that sums boxes with integral images, rounds with divmod and
fills rectangles by clipped slices of the linear sheet. The fitted size uses the TS double formula
(emulated here with Python floats); sizes where it differs from exact rounding are among the edge cases.
Labels: empty, time labels, digit runs wider than the cell (their x goes left of the cell and, near the
sheet's left edge, wraps into the row above), characters without a glyph, Korean and emoji (two UTF-16
units, one advance). Numbers: integers and floats whose JS String is known (2.5, 1e+21, 1.5e+300).
"""
import argparse
import json
import math
import random
import sys
import zlib

sys.dont_write_bytecode = True

NAME = 'clip_sheet'
W, H = 1560, 920
COLUMN_X, ROW_Y = (8, 784), (8, 468)

HARNESS = '''#![allow(dead_code, unused_imports)]
#[path = "@SOL@"] mod sol;
use std::io::{self, BufRead, Write};
fn hex(s: &str) -> Vec<u8> {
  if s == "-" { return Vec::new(); }
  (0..s.len()).step_by(2).map(|i| u8::from_str_radix(&s[i..i + 2], 16).unwrap()).collect()
}
fn crc32(d: &[u8]) -> u32 {
  let mut t = [0u32; 256];
  for i in 0..256 { let mut c = i as u32; for _ in 0..8 { c = if c & 1 != 0 { 0xEDB88320 ^ (c >> 1) } else { c >> 1 }; } t[i] = c; }
  let mut c = !0u32;
  for &b in d { c = t[((c ^ b as u32) & 0xff) as usize] ^ (c >> 8); }
  !c
}
fn main() {
  let out = io::stdout(); let mut out = out.lock();
  for line in io::stdin().lock().lines() {
    let line = line.unwrap();
    let f: Vec<&str> = line.split(' ').collect();
    let k: usize = f[0].parse().unwrap();
    let mut s = sol::clip_sheet_background();
    for i in 0..k {
      let b = 1 + 7 * i;
      let n = |j: usize| -> i64 { f[b + j].parse().unwrap() };
      let label = hex(f[b + 5]);
      let number = hex(f[b + 6]);
      s = sol::clip_sheet_cell(&s, i as i64, &hex(f[b + 4]), n(0), n(1), n(2), n(3),
                               std::str::from_utf8(&label).unwrap(), std::str::from_utf8(&number).unwrap());
    }
    writeln!(out, "x{:08x}", crc32(&s)).unwrap();
  }
}
'''

# The 5 x 7 font, rows left to right.
FONT = {
    '0': '01110 10001 10011 10101 11001 10001 01110', '1': '00100 01100 00100 00100 00100 00100 01110',
    '2': '01110 10001 00001 00010 00100 01000 11111', '3': '11110 00001 00001 01110 00001 00001 11110',
    '4': '00010 00110 01010 10010 11111 00010 00010', '5': '11111 10000 11110 00001 00001 10001 01110',
    '6': '00110 01000 10000 11110 10001 10001 01110', '7': '11111 00001 00010 00100 01000 01000 01000',
    '8': '01110 10001 10001 01110 10001 10001 01110', '9': '01110 10001 10001 01111 00001 00010 01100',
    ':': '00000 00100 00100 00000 00100 00100 00000', '.': '00000 00000 00000 00000 00000 01100 01100',
}
# JS String(number) for the numbers used.
NUMBER_TEXT = {2.5: '2.5', 1e21: '1e+21', 1.5e300: '1.5e+300', 0.5: '0.5'}


def number_text(v):
    return str(v) if isinstance(v, int) else NUMBER_TEXT[v]


def js_round(x):
    r = math.floor(x)
    return r + 1 if x - r >= 0.5 else r


def fitted_size(w, h):
    """drawFitted's size with doubles, as TS computes it."""
    ratio = min(768 / w, 432 / h)
    return max(1, min(768, js_round(w * ratio))), max(1, min(432, js_round(h * ratio)))


def exact_size(w, h):
    if 768 * h <= 432 * w:
        return 768, max(1, min(432, (2 * 768 * h + w) // (2 * w)))
    return max(1, min(768, (2 * 432 * w + h) // (2 * h))), 432


def units(text):
    return len(text.encode('utf-16-le')) // 2


def fill(sheet, x, y, w, h, color):
    pixel = bytes(color) + b'\xff'
    for row in range(y, y + h):
        start = (row * W + x) * 4
        lo, hi = max(start, 0), min(start + 4 * w, len(sheet))
        if lo < hi:
            sheet[lo:hi] = pixel * ((hi - lo) // 4)


def text(sheet, x, y, s):
    for i, ch in enumerate(s):
        rows = FONT.get(ch)
        if rows:
            for r, bits in enumerate(rows.split()):
                for c, bit in enumerate(bits):
                    if bit == '1':
                        fill(sheet, x + 12 * i + 2 * c, y + 2 * r, 2, 2, (255, 255, 255))


def fitted(sheet, w, h, data, left, top):
    ow, oh = fitted_size(w, h)
    ox0, oy0 = left + (768 - ow) // 2, top + (432 - oh) // 2
    # Integral images: P[c][y * (w + 1) + x] = sum of channel c over rows < y and columns < x.
    P = []
    for c in range(3):
        p = [0] * ((w + 1) * (h + 1))
        for y in range(h):
            run, base, prev = 0, (y + 1) * (w + 1), y * (w + 1)
            row = data[y * w * 4 + c:(y + 1) * w * 4:4]
            for x in range(w):
                run += row[x]
                p[base + x + 1] = p[prev + x + 1] + run
        P.append(p)
    xs = []
    for o in range(ow):
        a = o * w // ow
        xs.append((a, max(a + 1, (o + 1) * w // ow)))
    rows = {}
    for o in range(oh):
        y0 = o * h // oh
        y1 = max(y0 + 1, (o + 1) * h // oh)
        if (y0, y1) not in rows:
            cache, out = {}, bytearray()
            for x0, x1 in xs:
                px = cache.get((x0, x1))
                if px is None:
                    n = (y1 - y0) * (x1 - x0)
                    px = bytearray()
                    for p in P:
                        s = p[y1 * (w + 1) + x1] - p[y0 * (w + 1) + x1] - p[y1 * (w + 1) + x0] + p[y0 * (w + 1) + x0]
                        q, rem = divmod(s, n)
                        px.append(q + (2 * rem >= n))
                    px.append(255)
                    cache[(x0, x1)] = px = bytes(px)
                out += px
            rows[(y0, y1)] = bytes(out)
        at = ((oy0 + o) * W + ox0) * 4
        sheet[at:at + 4 * ow] = rows[(y0, y1)]


def oracle(cells):
    sheet = bytearray(b'\x0d\x11\x17\xff' * (W * H))
    for i, (w, h, data, number, label) in enumerate(cells):
        left, top = COLUMN_X[i % 2], ROW_Y[i // 2]
        fitted(sheet, w, h, data, left, top)
        fill(sheet, left, top + 432, 768, 20, (0, 0, 0))
        text(sheet, left + (768 - (12 * units(label) - 2)) // 2, top + 435, label)
        num = number_text(number)
        fill(sheet, left, top, 12 * units(num) - 2 + 8, 22, (0, 0, 0))
        text(sheet, left + 4, top + 4, num)
    return '%08x' % zlib.crc32(sheet)


EDGE_SIZES = [(1, 1), (2, 1), (1, 2), (768, 432), (769, 432), (768, 433), (1536, 864), (16, 9), (3, 7),
              (5632, 55), (49, 1568), (629, 544), (65535, 1), (1, 65535), (2, 1000), (1000, 2), (100, 1)]
EDGE_LABELS = ['', '0:12.4', '12:34.5', '1:02:03.9', '0123456789:.', '9' * 64, '9' * 65, '8' * 70, '7' * 1000,
               'abc 0:01', '한글 0:01.2', '🎬1.5', '🎬' * 40, 'x' * 5000, '0:0\N{COMBINING ACUTE ACCENT}1', '..::..']
EDGE_NUMBERS = [1, 2, 3, 4, 0, -1, 10, 99, 123456789, 9007199254740991, 2.5, 0.5, 1e21, 1.5e300]
LABEL_CHARS = '0123456789:.' * 4 + ' a한🎬'


def rand_label(r):
    n = r.choice([r.randrange(13), r.randrange(13), r.randrange(80), r.randrange(300)])
    return ''.join(r.choice(LABEL_CHARS) for _ in range(n))


def rand_size(r):
    kind = r.randrange(5)
    if kind == 0:
        return r.randrange(1, 41), r.randrange(1, 41)
    if kind == 1:
        return r.randrange(1, 401), r.randrange(1, 401)
    if kind == 2:
        k = r.randrange(1, 60)
        return 16 * k, 9 * k
    if kind == 3:
        return r.randrange(1, 3001), r.randrange(1, 9)
    return r.randrange(1, 9), r.randrange(1, 3001)


def cell(r, size, number, label):
    w, h = size
    return (w, h, r.randbytes(4 * w * h), number, label)


def cases(n, seed):
    r = random.Random(seed)
    rows = []
    for i, size in enumerate(EDGE_SIZES):
        rows.append([cell(r, size, EDGE_NUMBERS[i % len(EDGE_NUMBERS)], EDGE_LABELS[i % len(EDGE_LABELS)])])
    for i, label in enumerate(EDGE_LABELS):
        # every label in every column (the left column's long labels wrap into the row above)
        rows.append([cell(r, (4, 3), EDGE_NUMBERS[(i + k) % len(EDGE_NUMBERS)], label) for k in range(4)])
    for number in EDGE_NUMBERS:
        rows.append([cell(r, (2, 2), number, '0:01')] * 2)
    edges = len(rows)
    for _ in range(n):
        rows.append([cell(r, rand_size(r), r.choice([r.randrange(1, 5), r.randrange(0, 10 ** 6), r.choice(EDGE_NUMBERS)]),
                          rand_label(r)) for _ in range(r.randrange(1, 5))])
    return rows, edges


def ts_line(c):
    return json.dumps([[w, h, data.hex(), number, label] for w, h, data, number, label in c], ensure_ascii=False)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--seed', type=int, default=12345)
    ap.add_argument('--n', type=int, default=300)
    ap.add_argument('--emit', action='store_true', help='only print JSON lines [cells as TS driver input, oracle crc32]')
    args = ap.parse_args()
    if args.n < 0:
        ap.error('--n must be nonnegative')
    if args.emit:
        for c in cases(args.n, args.seed)[0]:
            sys.stdout.write('[%s, %s]\n' % (ts_line(c), json.dumps(oracle(c))))
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
        all_cells = [x for c in inputs for x in c]
        summary['cells'] = len(all_cells)
        summary['cell_outcomes'] = dict(
            double_size_differs_from_exact=sum(fitted_size(x[0], x[1]) != exact_size(x[0], x[1]) for x in all_cells),
            label_wider_than_cell=sum(12 * units(x[4]) - 2 > 768 for x in all_cells),
            label_without_glyph_chars=sum(any(ch not in FONT for ch in x[4]) for x in all_cells),
            max_label_units=max(units(x[4]) for x in all_cells))
        expected = [oracle(c) for c in inputs]
        node, summary['ts_runtime'] = ts_runtime()
        ts = [json.loads(x) for x in run(node + [HERE / (NAME+'.mjs')], ''.join(ts_line(c)+'\n' for c in inputs)).splitlines()]
        assert len(ts) == len(inputs)
        summary['ts_oracle_pass'] = sum(t == e for t, e in zip(ts, expected))
        payload = ''.join(str(len(c)) + ''.join(
            ' %d %d %d %d %s %s %s' % (w, h, *fitted_size(w, h), data.hex() or '-', label.encode().hex() or '-',
                                       number_text(number).encode().hex())
            for w, h, data, number, label in c) + '\n' for c in inputs)
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
                            differences.append(dict(compiler_backend=key, case_index=i,
                                                    cells=[[w, h, number, label[:60]] for w, h, _, number, label in c],
                                                    pruv=p, ts=t, expected=want))
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
    differences.sort(key=lambda d: (d['case_index'], d['compiler_backend']))
    summary.update(status='error' if failed else 'ok', difference_records_total=len(differences),
                   difference_records_saved=min(50, len(differences)),
                   difference_order='case index, compiler/backend')
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / (NAME+'_summary.json')).write_text(json.dumps(summary, indent=2, ensure_ascii=False)+'\n')
    (RESULTS / (NAME+'_differences.jsonl')).write_text(''.join(json.dumps(d, ensure_ascii=False)+'\n' for d in differences[:50]))
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
