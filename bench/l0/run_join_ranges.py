#!/usr/bin/env python3
"""Cross-check Lair joinRangeParts (src/documents/context.ts).

A list of strings goes to Pruv (join_ranges.pruv: the parts are passed as the concatenated text plus the
byte end of every part; UTF-16 lengths counted on UTF-8, result proved at most 1200 UTF-8 bytes), to the
TypeScript copy (join_ranges.mjs, run in Lair's Electron when available) and to an independent oracle that
measures UTF-16 lengths with len(s.encode('utf-16-le')) // 2 and picks the cut by trying every prefix of
parts (the text kept after k parts is the join of the parts from the first nonempty one on, which is how the
TS "no separator while kept is empty" rule works out), not by copying the TS loop.
Domain: lists of well-formed strings (no lone surrogates).
Inputs: the empty list, empty parts (alone and many, also leading a long total), ASCII ranges like "3-5",
Korean, accents, emoji (4 bytes, 2 units), ", ", "…", newlines and U+2028, parts of 100..450 units, lists of
0..300 parts, and lists whose joined length is exactly 398..403 units or whose cut candidate (kept text plus
3) lands on 397..401, a first part longer than 397 units, an emoji straddling the limit.
"""
import argparse
import json
import random
import sys

sys.dont_write_bytecode = True

NAME = 'join_ranges'
LIMIT = 400
SEP = ', '
TAIL = ', …'

HARNESS = '''#![allow(dead_code, unused_imports)]
#[path = "@SOL@"] mod sol;
use std::io::{self, BufRead, Write};
fn hex(s: &str) -> String { s.bytes().map(|b| format!("{:02x}", b)).collect() }
fn main() {
  let out = io::stdout(); let mut out = out.lock();
  for line in io::stdin().lock().lines() {
    let line = line.unwrap();
    let mut words = line[1..].split(' ');
    let text_hex = words.next().unwrap();
    let buf: Vec<u8> = text_hex.as_bytes().chunks(2).map(|p| u8::from_str_radix(std::str::from_utf8(p).unwrap(), 16).unwrap()).collect();
    let text = std::str::from_utf8(&buf).unwrap();
    let ends: Vec<i64> = words.filter(|w| !w.is_empty()).map(|w| w.parse().unwrap()).collect();
    writeln!(out, "x{}", hex(&sol::join_ranges(text, &ends))).unwrap();
  }
}
'''


def u16(s):
    """UTF-16 length of a well-formed string."""
    return len(s.encode('utf-16-le')) // 2


def kept_text(prefix):
    """What the TS loop holds after the parts of prefix: leading empty parts vanish, no separator before the
    first nonempty part, ", " before every later part (empty or not)."""
    first = next((j for j, p in enumerate(prefix) if p), None)
    return '' if first is None else SEP.join(prefix[first:])


def oracle(parts):
    full = SEP.join(parts)
    if u16(full) <= LIMIT:
        return full
    best, chars = 0, 0
    for k in range(1, len(parts) + 1):
        chars += len(parts[k - 1])
        if chars > LIMIT:   # more than 400 code points: more than 400 units, here and for every larger k
            break
        if u16(kept_text(parts[:k])) + 3 <= LIMIT:
            best = k
    return kept_text(parts[:best]) + TAIL


def is_cut(parts):
    return u16(SEP.join(parts)) > LIMIT


SMALL = ['', '', '', '0', '1', '3-5', '12', '120-130', '7', ', ', '…', '\n', ' ', '표', '한글', 'é', 'é',
         '\U0001f600', '\U0001f44d', 'a', 'x', ' ', '-', ' ', '﻿']
ONE_UNIT = ['a', 'b', '7', '표', 'é', '…', '\n', ' ', ',', ' ']
TWO_UNITS = ['\U0001f600', '\U0001f44d', '\U00010348']


def exact(r, n):
    """A well-formed string of exactly n UTF-16 units."""
    out = []
    while n > 0:
        if n >= 2 and r.random() < 0.2:
            out.append(r.choice(TWO_UNITS))
            n -= 2
        else:
            out.append(r.choice(ONE_UNIT))
            n -= 1
    return ''.join(out)


def rand_small(r):
    if r.random() < 0.4:
        return r.choice(SMALL)
    return ''.join(r.choice(SMALL) for _ in range(r.randrange(2, 5)))


def rand_range(r):
    a = r.randrange(1, 10 ** r.randrange(1, 7))
    return str(a) if r.random() < 0.4 else '%d-%d' % (a, a + r.randrange(1, 50))


def rand_long(r):
    return exact(r, r.randrange(100, 451))


def tuned(r):
    """Parts whose joined length is 394..407 units."""
    parts = [rand_small(r) for _ in range(r.randrange(1, 9))]
    delta = r.randrange(394, 408) - u16(SEP.join(parts))
    last = parts[-1]
    if delta >= 0:
        parts[-1] = last + exact(r, delta)
    elif u16(last) + delta >= 0:
        parts[-1] = exact(r, u16(last) + delta)
    return parts


def rand_parts(r):
    kind = r.randrange(6)
    if kind == 0:
        return [rand_small(r) for _ in range(r.randrange(8))]
    if kind == 1:   # Lair's shape: page ranges, often past the limit
        return [rand_range(r) for _ in range(r.randrange(20, 301))]
    if kind == 2:
        return [rand_long(r) if r.random() < 0.04 else rand_small(r) for _ in range(r.randrange(301))]
    if kind == 3:   # mostly empty parts
        return [('' if r.random() < 0.7 else r.choice([rand_small(r), rand_range(r), rand_long(r)]))
                for _ in range(r.randrange(1, 300))]
    if kind == 4:
        return tuned(r)
    return [''] * r.randrange(5) + [exact(r, r.randrange(300, 420))] + [rand_small(r) for _ in range(r.randrange(4))]


def edge_cases():
    rows = [[], [''], [''] * 2, [''] * 5, [''] * 200, [''] * 201, [''] * 202, [''] * 300,
            ['a'], ['3-5', '8'], ['3-5', '', '8'], ['', 'a'], ['', '', 'a'], ['a', ''], ['a', '', ''], ['', ''],
            ['…'], ['a', '…'], [', '], [', ', ', '], ['\n', ' '], ['표', '한글', 'é', '\U0001f600']]
    # One part of 396..404 units (ASCII, then emoji pairs).
    for n in range(396, 405):
        rows.append(['a' * n])
    for n in range(197, 203):
        rows.append(['\U0001f600' * n])
    # A first part of 392..399 units ending in an emoji, followed by little.
    for n in range(390, 399):
        for tail in ([], [''], ['b'], ['\U0001f600'], ['bb', 'c']):
            rows.append(['a' * n + '\U0001f600'] + tail)
    # Two parts whose joined length is 396..404.
    for total in range(396, 405):
        for a in (0, 1, 2, 100, total // 2, total - 4, total - 3):
            b = total - 2 - a
            if b >= 0:
                rows.append(['a' * a, 'b' * b])
    # Three parts where the second part makes kept + ", " + part 394..400 units (so next + 3 is 397..403).
    for t in range(394, 401):
        for a in (0, 1, 50, t // 2, t - 3):
            b = t - 2 - a
            if b >= 0:
                for c in (1, 2, 5, 10, 400):
                    rows.append(['a' * a, 'b' * b, 'c' * c])
    # The same landing with emoji inside the second part.
    for t in range(394, 401):
        for a in (1, 60):
            b = t - 2 - a
            if b >= 2:
                rows.append(['a' * a, 'b' * (b - 2) + '\U0001f600', 'cc'])
                rows.append(['a' * a, '\U0001f600' + 'b' * (b - 2), '\U0001f600'])
    # A first part longer than 397 units: the result is ", …".
    rows += [['a' * 397, 'b'], ['a' * 398, 'b'], ['a' * 397], ['a' * 450], ['a' * 1000], ['\U0001f600' * 199],
             ['\U0001f600' * 200], ['\U0001f600' * 201, 'x'], ['a' * 396 + '\U0001f600', 'x'],
             ['a' * 395 + '\U0001f600', 'x']]
    # Leading empty parts with a long total.
    rows += [['', 'a' * 397, 'x'], ['', 'a' * 398, 'x'], ['', '', 'a' * 390, 'b' * 50], [''] * 150 + ['a' * 390],
             [''] * 3 + ['a' * 396, 'b'], ['', 'a' * 395, 'b', 'c'], [''] * 100 + ['a' * 100, '', 'b' * 300],
             [''] * 201 + ['a'], [''] * 200 + ['a'], ['a' * 100, '', '', '', 'b' * 290], ['a' * 394, '', ''],
             ['a' * 394, '', '', ''], ['a' * 395, ''], ['a' * 396, ''], ['a' * 395, '', 'b']]
    # Many-byte text: 400 units of 3 bytes are 1200 bytes, the longest kept text 397 units, 1191 bytes.
    rows += [['표' * 400], ['표' * 399], ['표' * 401], ['표' * 397, 'x'], ['표' * 397, '표'], ['표' * 396, '표', '표'],
             ['표' * 200, '표' * 196, '표'], ['한글' * 100, '표' * 190, 'x']]
    # Separators and the ellipsis inside parts.
    rows += [['a' * 390, ', …', 'bb', 'c' * 20], ['…' * 200, '…' * 200], ['…' * 199, '…' * 199, '…'],
             [', ' * 100, ', ' * 100], ['\n' * 150, ' ' * 150, 'x' * 50]]
    return rows


def cases(n, seed):
    rows = edge_cases()
    edges = len(rows)
    r = random.Random(seed)
    for _ in range(n):
        rows.append(rand_parts(r))
    for parts in rows:
        assert all(isinstance(p, str) for p in parts)
        for p in parts:
            p.encode('utf-8')   # well-formed: raises on a lone surrogate
    return rows, edges


def ts_line(parts):
    return json.dumps(dict(parts=parts))


def harness_line(parts):
    ends, at = [], 0
    for p in parts:
        at += len(p.encode())
        ends.append(at)
    return 'n' + ''.join(parts).encode().hex() + ''.join(' %d' % e for e in ends)


def brief(parts):
    return [p[:60] for p in parts[:6]]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--seed', type=int, default=12345)
    ap.add_argument('--n', type=int, default=20000)
    ap.add_argument('--emit', action='store_true', help='only print JSON lines [parts, oracle]')
    args = ap.parse_args()
    if args.n < 0:
        ap.error('--n must be nonnegative')
    if args.emit:
        for parts in cases(args.n, args.seed)[0]:
            sys.stdout.write(json.dumps([parts, oracle(parts)]) + '\n')
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
        want = [oracle(parts) for parts in inputs]
        cut = [is_cut(parts) for parts in inputs]
        summary['oracle_outcomes'] = dict(
            full=sum(1 for c in cut if not c),
            cut=sum(1 for c in cut if c),
            cut_to_empty=sum(1 for c, w in zip(cut, want) if c and w == TAIL),
            full_units_398_to_400=sum(1 for w, c in zip(want, cut) if not c and 398 <= u16(w) <= 400),
            result_units_396_to_400=sum(1 for w in want if 396 <= u16(w) <= 400),
            max_result_units=max(u16(w) for w in want),
            max_result_utf8_bytes=max(len(w.encode()) for w in want))
        node, summary['ts_runtime'] = ts_runtime()
        # not splitlines: U+2028 stays in a JSON string
        ts = [json.loads(x) for x in run(node + [HERE / (NAME+'.mjs')], ''.join(ts_line(parts)+'\n' for parts in inputs)).split('\n')[:-1]]
        assert len(ts) == len(inputs)
        summary['ts_oracle_pass'] = sum(t == w for t, w in zip(ts, want))
        payload = ''.join(harness_line(parts) + '\n' for parts in inputs)
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
                    pruv = [bytes.fromhex(line[1:]).decode() for line in lines]
                    for i, (parts, p, t, w) in enumerate(zip(inputs, pruv, ts, want)):
                        if p != t or p != w:
                            differences.append(dict(compiler_backend=key, case_index=i, input=brief(parts), pruv=p, ts=t, expected=w))
                    row_.update(cases=len(inputs), pruv_oracle_pass=sum(p == w for p, w in zip(pruv, want)),
                                ts_oracle_pass=summary['ts_oracle_pass'],
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
