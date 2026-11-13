#!/usr/bin/env python3
"""Cross-check Lair zipUncompressedTotal (src/documents/zip.ts), the zip-bomb pre-check.

Each byte string goes to Pruv (zip_total.pruv, every read proved in bounds), to the TypeScript copy
(zip_total.mjs, run in Lair's Electron when available) and to an independent oracle written from the
PKWARE APPNOTE layout with struct/rfind. Results: a total, None (TS null) or 'Infinity'.
Inputs are real archives from Python's zipfile plus hostile edits: truncation, planted signatures in
comments, the 64 KiB search-window edge, zip64 markers, lying sizes and corrupt headers.
"""
import argparse
import io
import json
import random
import struct
import sys
import zipfile

sys.dont_write_bytecode = True

NAME = 'zip_total'
EOCD, CEN = b'PK\x05\x06', b'PK\x01\x02'

HARNESS = '''#![allow(dead_code, unused_imports)]
#[path = "@SOL@"] mod sol;
use std::io::{self, BufRead, Write};
fn main() {
  let out = io::stdout(); let mut out = out.lock();
  for line in io::stdin().lock().lines() {
    let line = line.unwrap(); let hex = &line[1..];
    let data: Vec<u8> = (0..hex.len()).step_by(2).map(|i| u8::from_str_radix(&hex[i..i+2], 16).unwrap()).collect();
    writeln!(out, "{}", sol::zip_uncompressed_total(&data)).unwrap();
  }
}
'''


def oracle(buf):
    """End of central directory: the last signature that starts at or before len-22 and no more than
    65535 bytes (the longest comment) before that. Then walk the central directory entries."""
    n = len(buf)
    if n < 22:
        return None
    e = buf.rfind(EOCD, max(0, n - 22 - 0xffff), n - 18)
    if e < 0:
        return None
    count, = struct.unpack_from('<H', buf, e + 10)
    offset, = struct.unpack_from('<I', buf, e + 16)
    if count == 0xffff or offset == 0xffffffff:
        return 'Infinity'
    total = 0
    for _ in range(count):
        if offset + 46 > n or buf[offset:offset+4] != CEN:
            return None
        usize, = struct.unpack_from('<I', buf, offset + 24)
        if usize == 0xffffffff:
            return 'Infinity'
        total += usize
        name, extra, comment = struct.unpack_from('<HHH', buf, offset + 28)
        offset += 46 + name + extra + comment
    return total


def make_zip(r, files, comment=b''):
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_STORED) as z:
        for i in range(files):
            info = zipfile.ZipInfo('f%d%s' % (i, 'x' * r.randrange(8)))
            if r.random() < 0.3:
                info.extra = struct.pack('<HH', 0xcafe, 4) + bytes(r.randrange(256) for _ in range(4))
            if r.random() < 0.3:
                info.comment = bytes(r.randrange(32, 127) for _ in range(r.randrange(12)))
            z.writestr(info, bytes(r.randrange(256) for _ in range(r.randrange(40))))
        z.comment = comment
    return bytearray(out.getvalue())


def entries(buf):
    """Offsets of the central directory entries of a well-formed archive."""
    e = buf.rfind(EOCD)
    count, = struct.unpack_from('<H', buf, e + 10)
    at, = struct.unpack_from('<I', buf, e + 16)
    seen = []
    for _ in range(count):
        seen.append(at)
        at += 46 + sum(struct.unpack_from('<HHH', buf, at + 28))
    return e, seen


def mutate(r, buf):
    e, cen = entries(buf)
    mode = r.randrange(12)
    if mode == 0 and cen:      # lying uncompressed size
        struct.pack_into('<I', buf, r.choice(cen) + 24, r.choice([0, 1, 0xfffffffe, 0xffffffff, r.randrange(2**32)]))
    elif mode == 1:            # zip64 markers in the EOCD
        if r.random() < 0.5:
            struct.pack_into('<H', buf, e + 10, 0xffff)
        else:
            struct.pack_into('<I', buf, e + 16, 0xffffffff)
    elif mode == 2:            # entry count too large or too small
        struct.pack_into('<H', buf, e + 10, max(0, len(cen) + r.choice([-2, -1, 1, 2, 500])))
    elif mode == 3:            # central directory offset moved
        struct.pack_into('<I', buf, e + 16, r.choice([0, len(buf), len(buf) - 45, len(buf) - 46, r.randrange(len(buf) + 100)]))
    elif mode == 4 and cen:    # corrupt entry signature
        buf[r.choice(cen) + r.randrange(4)] ^= 1 + r.randrange(255)
    elif mode == 5 and cen:    # huge name/extra/comment lengths
        struct.pack_into('<H', buf, r.choice(cen) + 28 + 2 * r.randrange(3), r.choice([0xffff, r.randrange(65536)]))
    elif mode == 6:            # truncation
        del buf[r.randrange(len(buf) + 1):]
    elif mode == 7:            # trailing junk after the archive
        buf += bytes(r.randrange(256) for _ in range(r.randrange(80)))
    elif mode == 8:            # random byte flips
        for _ in range(1 + r.randrange(4)):
            buf[r.randrange(len(buf))] = r.randrange(256)
    elif mode == 9:            # a second, later EOCD planted in trailing bytes
        fake = bytearray(EOCD + bytes(18))
        struct.pack_into('<HI', fake, 10, r.randrange(3), 0)
        struct.pack_into('<I', fake, 16, r.choice([0, cen[0] if cen else 0, r.randrange(len(buf))]))
        buf += fake + bytes(r.randrange(4))
    elif mode == 10:           # leading junk (self-extractor shape)
        buf[:0] = bytes(r.randrange(256) for _ in range(r.randrange(64)))
    return buf


def window_case(extra):
    """EOCD followed by `extra` junk bytes: found only while extra <= 65535."""
    buf = bytearray(make_zip(random.Random(extra), 2))
    return buf + bytes([0x41]) * extra


def cases(n, seed):
    r = random.Random(seed)
    rows = [bytes(k) for k in range(30)]
    rows += [EOCD + bytes(18), EOCD + bytes(17), b'x' + EOCD + bytes(18), EOCD + bytes(19)]
    rows += [EOCD + struct.pack('<HHHHIIH', 0, 0, c, c, 0, o, 0) for c in (0, 1, 0xfffe, 0xffff) for o in (0, 22, 0xffffffff)]
    for files in range(4):
        base = make_zip(r, files)
        rows.append(bytes(base))
        rows += [bytes(base[:k]) for k in range(len(base) + 1)]
        rows += [bytes(base[k:]) for k in range(0, len(base), 7)]
    for extra in (0, 1, 65512, 65513, 65534, 65535, 65536, 65537, 70000):
        rows.append(bytes(window_case(extra)))
    big = make_zip(r, 3, comment=b'C' * 65535)
    rows.append(bytes(big))
    planted = make_zip(r, 2, comment=EOCD + bytes(18))
    rows.append(bytes(planted))
    # Sizes that sum past 2^32 and to the 65534-entry maximum shape.
    many = bytearray(CEN + bytes(42))
    struct.pack_into('<I', many, 24, 0xfffffffe)
    for count in (1, 2, 100, 1000):
        rows.append(bytes(many * count + EOCD + struct.pack('<HHHHIIH', 0, 0, count, count, 46 * count, 0, 0)))
    edges = len(rows)
    for _ in range(n):
        buf = make_zip(r, r.randrange(6), comment=bytes(r.randrange(256) for _ in range(r.choice([0, 0, r.randrange(40)]))))
        for _ in range(r.choice([0, 1, 1, 1, 2, 3])):
            if not buf.count(EOCD):
                break
            try:
                buf = mutate(r, buf)
            except (struct.error, IndexError, ValueError):
                break
        rows.append(bytes(buf))
    return rows, edges


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--seed', type=int, default=12345)
    ap.add_argument('--n', type=int, default=20000)
    ap.add_argument('--emit', action='store_true',
                    help='only print JSON lines [input hex, oracle result] (Node bridge test)')
    args = ap.parse_args()
    if args.n < 0:
        ap.error('--n must be nonnegative')
    if args.emit:
        for row in cases(args.n, args.seed)[0]:
            sys.stdout.write(json.dumps([row.hex(), oracle(row)]) + '\n')
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
        expected = [oracle(x) for x in inputs]
        summary['oracle_outcomes'] = dict(total=sum(isinstance(x, int) for x in expected),
                                          null=expected.count(None), infinity=expected.count('Infinity'))
        node, summary['ts_runtime'] = ts_runtime()
        ts = [json.loads(x) for x in run(node + [HERE / (NAME+'.mjs')], ''.join(json.dumps(x.hex())+'\n' for x in inputs)).splitlines()]
        assert len(ts) == len(inputs)
        payload = ''.join('x'+x.hex()+'\n' for x in inputs)
        decode = {'-1': None, '-2': 'Infinity'}
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
                    pruv = [decode[x] if x in decode else int(x) for x in lines]
                    for i, (c, p, t, want) in enumerate(zip(inputs, pruv, ts, expected)):
                        if p != t or p != want:
                            differences.append(dict(compiler_backend=key, case_index=i, input=c.hex(),
                                input_bytes=len(c), pruv=p, ts=t, expected=want))
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
    differences.sort(key=lambda d: (d['input_bytes'], d['input'], d['compiler_backend']))
    summary.update(status='error' if failed else 'ok', difference_records_total=len(differences),
                   difference_records_saved=min(50, len(differences)),
                   difference_order='input bytes, input hex, compiler/backend')
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / (NAME+'_summary.json')).write_text(json.dumps(summary, indent=2)+'\n')
    (RESULTS / (NAME+'_differences.jsonl')).write_text(''.join(json.dumps(d)+'\n' for d in differences[:50]))
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
