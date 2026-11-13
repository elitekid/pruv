#!/usr/bin/env python3
"""Cross-check Lair encodePng (src/documents/png.ts), pdf.js page image -> PNG for OCR.

Each image goes to Pruv (encode_png.pruv: downsampling step and scanlines, every read and write proved
in bounds), to the TypeScript copy (encode_png.mjs, run in Lair's Electron when available) and to an
independent oracle (exact integer step with math.isqrt, Fraction rounding, Python bit operations).
The comparison is on content: TS's PNG is parsed (signature, chunk CRCs, IHDR, IEND) and its IDAT
inflated; Pruv's scanlines get the geometry width / step, height / step from png_step. Deflate and
CRC stay in the host (zlib), so only their output, not their bytes, is compared.
Inputs: all three kinds with exact, short, empty and overlong data, step boundaries (w * h = max * k^2
and one more), large dimensions with tiny outputs, inversion on both sides of the half-white line.
"""
import argparse
import json
import math
import random
import struct
import sys
import zlib
from fractions import Fraction

sys.dont_write_bytecode = True

NAME = 'encode_png'
SIG = bytes([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])

HARNESS = '''#![allow(dead_code, unused_imports)]
#[path = "@SOL@"] mod sol;
use std::io::{self, BufRead, Write};
fn main() {
  let out = io::stdout(); let mut out = out.lock();
  for line in io::stdin().lock().lines() {
    let line = line.unwrap(); let f: Vec<&str> = line.split(' ').collect();
    let v: Vec<i64> = f[..4].iter().map(|x| x.parse().unwrap()).collect();
    let hex = &f[4][1..];
    let data: Vec<u8> = (0..hex.len()).step_by(2).map(|i| u8::from_str_radix(&hex[i..i+2], 16).unwrap()).collect();
    let step = sol::png_step(v[0], v[1], v[3]);
    let raw = sol::png_scanlines(&data, v[0], v[1], v[2], v[3]);
    let h: String = raw.iter().map(|b| format!("{:02x}", b)).collect();
    writeln!(out, "{} x{}", step, h).unwrap();
  }
}
'''


def oracle(w, h, kind, data, mx, invert=True):
    """(out_w, out_h, color, scanlines) or None."""
    wh = w * h
    if wh <= mx:
        step = 1
    else:
        q = -(-wh // mx)
        step = math.isqrt(q - 1) + 1
    ow, oh = w // step, h // step
    if ow < 1 or oh < 1:
        return None
    get = lambda i: data[i] if i < len(data) else None
    rows, white = [], 0
    for y in range(oh):
        sy, row = y * step, bytearray([0])
        for x in range(ow):
            sx = x * step
            if kind == 1:
                b = get(sy * ((w + 7) // 8) + sx // 8)
                bit = 0 if b is None else (b >> (7 - sx % 8)) & 1
                row.append(255 if bit else 0)
                white += bit
            elif kind == 2:
                at = (sy * w + sx) * 3
                row += bytes(get(at + i) or 0 for i in range(3))
            else:
                at = (sy * w + sx) * 4
                a = get(at + 3)
                if a is None:
                    row += bytes(3)
                else:
                    row += bytes(round(Fraction(data[at + i] * a, 255) + 255 - Fraction(255 * a, 255)) for i in range(3))
        rows.append(row)
    if invert and kind == 1 and 2 * white < ow * oh:
        rows = [row[:1] + bytes(255 - v for v in row[1:]) for row in rows]
    return ow, oh, 0 if kind == 1 else 2, bytes(b''.join(rows))


def parse_png(png):
    """(out_w, out_h, color, inflated IDAT) after checking the layout TS writes."""
    assert png[:8] == SIG, 'signature'
    at, chunks = 8, []
    while at < len(png):
        n, = struct.unpack_from('>I', png, at)
        kind, body = png[at+4:at+8], png[at+8:at+8+n]
        crc, = struct.unpack_from('>I', png, at+8+n)
        assert crc == zlib.crc32(kind + body), 'crc ' + kind.decode()
        chunks.append((kind, body))
        at += 12 + n
    assert [k for k, _ in chunks] == [b'IHDR', b'IDAT', b'IEND'] and chunks[2][1] == b'', 'chunks'
    w, h, depth, color, comp, filt, lace = struct.unpack('>IIBBBBB', chunks[0][1])
    assert (depth, comp, filt, lace) == (8, 0, 0, 0), 'IHDR'
    return w, h, color, zlib.decompress(chunks[1][1])


def image(r, w, h, kind, mode):
    full = ((w + 7) // 8) * h if kind == 1 else w * h * (3 if kind == 2 else 4)
    if kind == 1:
        dense = r.choice([0.1, 0.5, 0.9, 0.0, 1.0])
        gen = lambda: sum((r.random() < dense) << k for k in range(8))
    elif kind == 3 and r.random() < 0.5:
        gen = lambda: r.choice([0, 1, 127, 128, 254, 255, r.randrange(256)])
    else:
        gen = lambda: r.randrange(256)
    n = {'exact': full, 'short': r.randrange(full + 1) if full else 0, 'empty': 0,
         'long': full + r.randrange(1, 9), 'cut': max(0, full - r.randrange(1, 5))}[mode]
    return bytes(gen() for _ in range(n))


def cases(n, seed):
    r = random.Random(seed)
    rows = []
    for kind in (1, 2, 3):
        for w, h in ((1, 1), (1, 7), (7, 1), (8, 2), (9, 3), (16, 16), (17, 5)):
            for mode in ('exact', 'short', 'empty', 'long', 'cut'):
                for mx in (1, 2, 3, 4, w * h - 1, w * h, 25_000_000):
                    if mx >= 1:
                        rows.append((w, h, kind, image(r, w, h, kind, mode), mx))
    # Step boundaries: w * h exactly max * k^2 (step k) and one pixel more (step k + 1).
    for k in (1, 2, 3, 5, 7):
        for mx in (1, 2, 3, 6):
            for w, h in ((k * k * mx, 1), (k * mx, k), (k, k * mx)):
                for extra in (0, 1):
                    kind = 1 + r.randrange(3)
                    hh = h + extra if extra and w == 1 else h
                    ww = w + extra if hh == h else w
                    rows.append((ww, hh, kind, image(r, ww, hh, kind, 'exact'), mx))
    # Large dimensions, tiny outputs (data far shorter than the image).
    for w, h, mx in ((1 << 20, 1 << 20, 100), (1 << 40, 1, 1), (1 << 30, 1024, 1024), (1 << 20, 1 << 20, 4097),
                     (1000003, 999983, 10_000), (25_000_000, 1, 1000), (1 << 20, 1 << 20, 1 << 14),
                     (5000, 5000, 2500), (5001, 5000, 2500), (3, (1 << 40) // 3, 7), (1 << 40, 1, 1 << 20)):
        if w * h <= 1 << 40:
            for kind in (1, 2, 3):
                rows.append((w, h, kind, bytes(r.randrange(256) for _ in range(r.randrange(64))), mx))
    edges = len(rows)
    for _ in range(n):
        kind = 1 + r.randrange(3)
        w, h = 1 + r.randrange(r.choice([4, 24, 80])), 1 + r.randrange(r.choice([4, 24, 80]))
        mx = r.choice([w * h, w * h + 1, 25_000_000, 1 + r.randrange(w * h), 1 + r.randrange(max(1, w * h // 9))])
        rows.append((w, h, kind, image(r, w, h, kind, r.choice(['exact', 'exact', 'short', 'empty', 'long', 'cut'])), mx))
    return rows, edges


def emit_row(c):
    w, h, kind, data, mx = c
    return [w, h, kind, data.hex(), mx]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--seed', type=int, default=12345)
    ap.add_argument('--n', type=int, default=6000)
    ap.add_argument('--emit', action='store_true',
                    help='only print JSON lines [w, h, kind, data hex, max, oracle] (Node bridge test)')
    args = ap.parse_args()
    if args.n < 0:
        ap.error('--n must be nonnegative')
    if args.emit:
        for c in cases(args.n, args.seed)[0]:
            o = oracle(*c)
            sys.stdout.write(json.dumps(emit_row(c) + [None if o is None else [o[0], o[1], o[2], o[3].hex()]]) + '\n')
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
        expected = [oracle(*c) for c in inputs]
        summary['oracle_outcomes'] = dict(png=sum(x is not None for x in expected), null=expected.count(None),
                                          inverted=sum(x is not None and x != oracle(*c, invert=False)
                                                       for c, x in zip(inputs, expected)))
        node, summary['ts_runtime'] = ts_runtime()
        ts_out = run(node + [HERE / (NAME+'.mjs')], ''.join(json.dumps(emit_row(c))+'\n' for c in inputs)).splitlines()
        assert len(ts_out) == len(inputs)
        ts = []
        for line in ts_out:
            v = json.loads(line)
            ts.append(v if v is None or v.startswith('throw:') else parse_png(bytes.fromhex(v)))
        summary['ts_oracle_pass'] = sum(t == e for t, e in zip(ts, expected))
        payload = ''.join('%d %d %d %d x%s\n' % (w, h, k, mx, d.hex()) for w, h, k, d, mx in inputs)
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
                    for (w, h, k, d, mx), line in zip(inputs, lines):
                        step, raw = line.split(' ')
                        raw = bytes.fromhex(raw[1:])
                        pruv.append(None if not raw else (w // int(step), h // int(step), 0 if k == 1 else 2, raw))
                    for i, (c, p, t, want) in enumerate(zip(inputs, pruv, ts, expected)):
                        if p != t or p != want:
                            show = lambda x: x if x is None or isinstance(x, str) else [x[0], x[1], x[2], x[3].hex()[:200]]
                            differences.append(dict(compiler_backend=key, case_index=i, input=emit_row(c)[:3] + [c[3].hex()[:200], c[4]],
                                input_bytes=len(c[3]), pruv=show(p), ts=show(t), expected=show(want)))
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
    differences.sort(key=lambda d: (d['input_bytes'], json.dumps(d['input']), d['compiler_backend']))
    summary.update(status='error' if failed else 'ok', difference_records_total=len(differences),
                   difference_records_saved=min(50, len(differences)),
                   difference_order='input bytes, input, compiler/backend')
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / (NAME+'_summary.json')).write_text(json.dumps(summary, indent=2)+'\n')
    (RESULTS / (NAME+'_differences.jsonl')).write_text(''.join(json.dumps(d)+'\n' for d in differences[:50]))
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
