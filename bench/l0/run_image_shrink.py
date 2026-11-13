#!/usr/bin/env python3
"""Cross-check Lair shrinkJpeg (src/documents/image-shrink.ts), the photo shrink before OCR.

Two kinds of cases go to Pruv (image_shrink.pruv: every read and write proved in bounds), to the
TypeScript copy (image_shrink.mjs, run in Lair's Electron when available) and to an independent oracle:
- EXIF orientation (readOrientation): crafted JPEG marker streams with APP1 Exif / TIFF headers. The
  oracle parses with struct and slices.
- Decoded RGBA pixels (the shrinkJpeg lines between jpeg-js decode and encode): scaled size, box shrink
  and orientation. The oracle rounds with Fraction and builds the eight orientations from list flips
  and transposes instead of index formulas.
JPEG decoding and encoding stay in the host (jpeg-js) and are not compared.
Inputs: fill bytes, RST/SOI/TEM markers, early SOS/EOI, segment lengths 0, 1 and past the end, Exif
headers cut at every length, II and MM, bad magic, IFD offsets past the end and near 2^32, entry counts
past the end, values 0..9 and 65535; images on both sides of the 2000 long side, every orientation,
scaled sides that are exact halves, box averages that are exact halves.
"""
import argparse
import json
import random
import struct
import sys
from fractions import Fraction

sys.dont_write_bytecode = True

NAME = 'image_shrink'

HARNESS = '''#![allow(dead_code, unused_imports)]
#[path = "@SOL@"] mod sol;
use std::io::{self, BufRead, Write};
fn unhex(hex: &str) -> Vec<u8> {
  (0..hex.len()).step_by(2).map(|i| u8::from_str_radix(&hex[i..i+2], 16).unwrap()).collect()
}
fn main() {
  let out = io::stdout(); let mut out = out.lock();
  for line in io::stdin().lock().lines() {
    let line = line.unwrap(); let f: Vec<&str> = line.split(' ').collect();
    if f[0] == "o" {
      writeln!(out, "{}", sol::jpeg_orientation(&unhex(&f[1][1..]))).unwrap();
    } else {
      let v: Vec<i64> = f[1..4].iter().map(|x| x.parse().unwrap()).collect();
      let data = unhex(&f[4][1..]);
      let raw = sol::shrink_pixels(&data, v[0], v[1], v[2]);
      let h: String = raw.iter().map(|b| format!("{:02x}", b)).collect();
      writeln!(out, "{} {} x{}", sol::shrink_width(v[0], v[1]), sol::shrink_height(v[0], v[1]), h).unwrap();
    }
  }
}
'''

LONG = 2000


def orientation_oracle(b):
    """Walk markers; the first APP1 whose payload starts with Exif\\0\\0 decides."""
    pos = 2
    while pos + 4 <= len(b):
        if b[pos] != 0xff:
            return 1
        m = b[pos + 1]
        if m == 0xff:
            pos += 1
            continue
        if m in (0xd8, 0x01) or 0xd0 <= m <= 0xd7:
            pos += 2
            continue
        if m in (0xda, 0xd9):
            return 1
        n, = struct.unpack_from('>H', b, pos + 2)
        if n < 2:
            return 1
        seg = b[pos + 4:pos + 2 + n]          # payload, cut at the end of the data
        if m == 0xe1 and seg[:6] == b'Exif\0\0':
            return tiff_oracle(seg[6:])
        pos += 2 + n
    return 1


def tiff_oracle(t):
    if len(t) < 8 or t[:2] not in (b'II', b'MM'):
        return 1
    e = '<' if t[:2] == b'II' else '>'
    magic, ifd = struct.unpack_from(e + 'HI', t, 2)
    if magic != 42 or ifd + 2 > len(t):
        return 1
    count, = struct.unpack_from(e + 'H', t, ifd)
    for i in range(count):
        at = ifd + 2 + 12 * i
        if at + 12 > len(t):
            return 1
        tag, _, _, value = struct.unpack_from(e + 'HHIH', t, at)
        if tag == 0x0112:
            return value if 1 <= value <= 8 else 1
    return 1


def half_up(q):
    """Math.round of a nonnegative rational: floor(q + 1/2)."""
    return int(q + Fraction(1, 2))


def transform(rows, o):
    """EXIF orientation o as flips and transposes of a list of pixel rows."""
    flip_h = lambda rs: [r[::-1] for r in rs]
    flip_v = lambda rs: rs[::-1]
    transpose = lambda rs: [list(c) for c in zip(*rs)]
    return {1: lambda rs: rs, 2: flip_h, 3: lambda rs: flip_v(flip_h(rs)), 4: flip_v, 5: transpose,
            6: lambda rs: flip_h(transpose(rs)), 7: lambda rs: flip_v(flip_h(transpose(rs))),
            8: lambda rs: flip_v(transpose(rs))}[o](rows)


def pixels_oracle(w, h, o, data):
    """(width, height, RGBA) of the upright, shrunk image, or None when nothing needs doing."""
    big = max(w, h)
    if big <= LONG and o == 1:
        return None
    sw, sh = w, h
    if big > LONG:
        sw = max(1, half_up(Fraction(w * LONG, big)))
        sh = max(1, half_up(Fraction(h * LONG, big)))
    px = lambda x, y: data[4 * (y * w + x):4 * (y * w + x) + 3]
    rows = []
    for oy in range(sh):
        ya = int(Fraction(oy * h, sh))
        yb = max(ya + 1, int(Fraction((oy + 1) * h, sh)))
        row = []
        for ox in range(sw):
            xa = int(Fraction(ox * w, sw))
            xb = max(xa + 1, int(Fraction((ox + 1) * w, sw)))
            box = [px(x, y) for y in range(ya, yb) for x in range(xa, xb)]
            row.append(bytes(half_up(Fraction(sum(p[c] for p in box), len(box))) for c in range(3)) + b'\xff')
        rows.append(row)
    rows = transform(rows, o)
    return len(rows[0]), len(rows), b''.join(b''.join(r) for r in rows)


def segment(r, marker, payload):
    return bytes([0xff, marker]) + struct.pack('>H', len(payload) + 2) + payload


def tiff(r, e, entries, ifd=None, magic=42, count=None):
    """A TIFF header with IFD0 holding (tag, value) entries."""
    body = b''.join(struct.pack(e + 'HHIHH', tag, 3, 1, value, 0) for tag, value in entries)
    off = 8 if ifd is None else ifd
    head = (b'II' if e == '<' else b'MM') + struct.pack(e + 'HI', magic, off)
    pad = bytes(r.randrange(256) for _ in range(max(0, off - 8))) if ifd is not None and off < 64 else b''
    return head + pad + struct.pack(e + 'H', len(entries) if count is None else count) + body


def exif_cases(r):
    rows = []
    soi = b'\xff\xd8'
    for e in '<>':
        for v in list(range(10)) + [65535, 256, 257]:
            for before in ([], [(0x100, 5)], [(0x10f, 1), (0x110, 2), (0x11a, 7)]):
                t = tiff(r, e, before + [(0x112, v)] + [(0x112, 3)])
                rows.append(soi + segment(r, 0xe1, b'Exif\0\0' + t))
                # Cut the Exif segment at every length: declared length kept, data ends early.
                full = soi + segment(r, 0xe1, b'Exif\0\0' + t)
                if v in (3, 6) and not before:
                    rows += [full[:k] for k in range(len(full))]
                # Declared segment length shorter than the TIFF data.
                seg = segment(r, 0xe1, b'Exif\0\0' + t)
                for cut in (8, 10, 16, 20, 25, 30):
                    rows.append(soi + seg[:2] + struct.pack('>H', cut) + seg[4:])
        t = tiff(r, e, [(0x112, 6)])
        rows.append(soi + segment(r, 0xe1, b'Exif\0\0' + t[:2] + struct.pack(e + 'H', 43) + t[4:]))
        rows.append(soi + segment(r, 0xe1, b'Exif\0\0' + tiff(r, e, [(0x112, 6)], magic=0x2a2a)))
        for ifd in (0, 1, 7, 9, 20, 2 ** 31, 2 ** 32 - 1, 2 ** 32 - 8, 2 ** 32 - 2):
            rows.append(soi + segment(r, 0xe1, b'Exif\0\0' + tiff(r, e, [(0x112, 6)], ifd=ifd)))
        for count in (0, 2, 5, 65535):
            rows.append(soi + segment(r, 0xe1, b'Exif\0\0' + tiff(r, e, [(0x112, 8)], count=count)))
            rows.append(soi + segment(r, 0xe1, b'Exif\0\0' + tiff(r, e, [(0x100, 8)], count=count)))
    t = tiff(r, '<', [(0x112, 6)])
    for head in (b'Exif\0\0', b'Exif\0\1', b'Exif\0', b'exif\0\0', b'Exif\x00\x00II', b''):
        rows.append(soi + segment(r, 0xe1, head + t))
    for mixed in (b'IM', b'MI', b'ii', b'\0\0'):
        rows.append(soi + segment(r, 0xe1, b'Exif\0\0' + mixed + t[2:]))
    exif = segment(r, 0xe1, b'Exif\0\0' + t)
    other = [b'\xff\xff', b'\xff\xd8', b'\xff\x01', b'\xff\xd0', b'\xff\xd7', segment(r, 0xe0, b'JFIF\0\1\1'),
             segment(r, 0xe1, b'http://ns.adobe.com/xap/1.0/\0'), segment(r, 0xdb, bytes(64)), b'\xff\xc0\x00\x02',
             b'\xff\x02\x00\x02']
    for a in other:
        for b in other:
            rows.append(soi + a + b + exif)
    for stop in (b'\xff\xda\x00\x02', b'\xff\xd9\x00\x00', b'\x00\xff', b'\xfe\xe1', b'\xff\xe0\x00\x00',
                 b'\xff\xe0\x00\x01', b'\xff\xe0\xff\xff', b'\xff\xd8\xff\xe1'):
        rows.append(soi + stop + exif)
    for n in range(8):
        rows.append(bytes(r.randrange(256) for _ in range(n)))
        rows.append(soi + exif[:n])
    return rows


def random_exif(r):
    soi = b'\xff\xd8'
    parts = []
    for _ in range(r.randrange(4)):
        parts.append(r.choice([b'\xff\xff', b'\xff\xd0', segment(r, r.choice([0xe0, 0xe2, 0xdb, 0xc4, 0xfe]),
                                                                    bytes(r.randrange(256) for _ in range(r.randrange(12))))]))
    e = r.choice('<>')
    entries = [(r.choice([0x112, 0x100, 0x101, 0x112, 0x1112, 0x1201]), r.choice([1, 2, 3, 6, 8, 0, 9, r.randrange(65536)]))
               for _ in range(r.randrange(5))]
    t = tiff(r, e, entries, ifd=r.choice([None, None, None, r.randrange(40)]), count=r.choice([None, None, r.randrange(8)]))
    seg = segment(r, 0xe1, b'Exif\0\0' + t)
    if r.random() < 0.2:
        k = r.randrange(len(seg))
        seg = seg[:k] + bytes([r.randrange(256)]) + seg[k + 1:]
    data = soi + b''.join(parts) + seg + b'\xff\xda'
    if r.random() < 0.2:
        data = data[:r.randrange(len(data) + 1)]
    return data


def gen_pixels(r, w, h):
    pool = r.choice([None, [0, 1], [0, 1, 254, 255], [127, 128]])
    if pool is None:
        return bytes(r.randrange(256) for _ in range(4 * w * h))
    return bytes(r.choice(pool) for _ in range(4 * w * h))


def cases(n, seed):
    r = random.Random(seed)
    rows = [('o', b) for b in exif_cases(r)]
    sizes = [(1, 1), (1, 2), (2, 1), (3, 5), (7, 4), (2000, 1), (1, 2000), (2000, 2), (2001, 1), (1, 2001),
             (2001, 2), (2002, 3), (4000, 1), (4000, 3), (3, 4000), (4000, 5), (4001, 2), (3999, 2), (6000, 3),
             (2500, 7), (7, 2500), (2047, 9), (8191, 1), (2000, 40), (2001, 40)]
    for w, h in sizes:
        for o in range(1, 9):
            rows.append(('p', w, h, o, gen_pixels(r, w, h)))
    edges = len(rows)
    for i in range(n):
        if i % 3 == 0:
            rows.append(('o', random_exif(r)))
        elif i % 50 == 1:
            w, h = r.randrange(2001, 9000), r.randrange(1, 4)
            if r.random() < 0.5:
                w, h = h, w
            rows.append(('p', w, h, 1 + r.randrange(8), gen_pixels(r, w, h)))
        else:
            w, h = 1 + r.randrange(r.choice([3, 12, 40])), 1 + r.randrange(r.choice([3, 12, 40]))
            rows.append(('p', w, h, 1 + r.randrange(8), gen_pixels(r, w, h)))
    return rows, edges


def oracle(c):
    if c[0] == 'o':
        return orientation_oracle(c[1])
    o = pixels_oracle(*c[1:])
    return None if o is None else [o[0], o[1], o[2].hex()]


def emit_row(c):
    return ['o', c[1].hex()] if c[0] == 'o' else ['p', c[1], c[2], c[3], c[4].hex()]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--seed', type=int, default=12345)
    ap.add_argument('--n', type=int, default=6000)
    ap.add_argument('--emit', action='store_true',
                    help='only print JSON lines ["o", hex, oracle] or ["p", w, h, orientation, hex, oracle]')
    args = ap.parse_args()
    if args.n < 0:
        ap.error('--n must be nonnegative')
    if args.emit:
        for c in cases(args.n, args.seed)[0]:
            sys.stdout.write(json.dumps(emit_row(c) + [oracle(c)]) + '\n')
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
            orientation={str(k): sum(1 for c, x in zip(inputs, expected) if c[0] == 'o' and x == k) for k in range(1, 9)},
            pixels=sum(1 for c, x in zip(inputs, expected) if c[0] == 'p' and x is not None),
            pixels_untouched=sum(1 for c, x in zip(inputs, expected) if c[0] == 'p' and x is None),
            shrunk=sum(1 for c in inputs if c[0] == 'p' and max(c[1], c[2]) > LONG))
        node, summary['ts_runtime'] = ts_runtime()
        ts = [json.loads(x) for x in run(node + [HERE / (NAME+'.mjs')], ''.join(json.dumps(emit_row(c))+'\n' for c in inputs)).splitlines()]
        assert len(ts) == len(inputs)
        summary['ts_oracle_pass'] = sum(t == e for t, e in zip(ts, expected))
        payload = ''.join(('o x%s\n' % c[1].hex()) if c[0] == 'o' else ('p %d %d %d x%s\n' % (c[1], c[2], c[3], c[4].hex()))
                          for c in inputs)
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
                    for c, line in zip(inputs, lines):
                        if c[0] == 'o':
                            pruv.append(int(line))
                            continue
                        sw, sh, raw = line.split(' ')
                        sw, sh, raw = int(sw), int(sh), raw[1:]
                        if c[3] >= 5:
                            sw, sh = sh, sw
                        pruv.append(None if not raw else [sw, sh, raw])
                    for i, (c, p, t, want) in enumerate(zip(inputs, pruv, ts, expected)):
                        if p != t or p != want:
                            cut = lambda x: x if not isinstance(x, list) else [x[0], x[1], x[2][:200]]
                            differences.append(dict(compiler_backend=key, case_index=i, input=[str(v)[:200] for v in emit_row(c)],
                                                    pruv=cut(p), ts=cut(t), expected=cut(want)))
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
    (RESULTS / (NAME+'_summary.json')).write_text(json.dumps(summary, indent=2)+'\n')
    (RESULTS / (NAME+'_differences.jsonl')).write_text(''.join(json.dumps(d)+'\n' for d in differences[:50]))
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
