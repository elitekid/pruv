#!/usr/bin/env python3
"""Cross-check the UTF-16 offset fix of Lair (alignOffset in src/backend/requests/ai-result.ts).

Each (text, offset) pair goes to Pruv (align_offset.pruv: a character walk counting 2 units for 4-byte
characters), to the TypeScript copy (align_offset.mjs, run in Lair's Electron when available) and to an
independent oracle written over the UTF-16LE encoding: offset - 1 when 0 < offset < unit count, the unit
at offset is a low surrogate and the unit before it a high surrogate, otherwise offset.
Domain: any Unicode text without lone surrogates, offset an integer in 0..=10^11. Inputs: edge pairs
(empty text, offset 0, offsets before, inside and after surrogate pairs, at and past the end, a large
offset) and random pairs (seed 12345) over ASCII, 2-, 3- and 4-byte characters with offsets inside the
UTF-16 length or past it.
"""
import argparse
import json
import random
import sys

sys.dont_write_bytecode = True

NAME = 'align_offset'

HARNESS = '''#![allow(dead_code, unused_imports)]
#[path = "@SOL@"] mod sol;
use std::io::{self, BufRead, Write};
fn unhex(hex: &str) -> String {
  let data: Vec<u8> = (0..hex.len()).step_by(2).map(|i| u8::from_str_radix(&hex[i..i+2], 16).unwrap()).collect();
  String::from_utf8(data).unwrap()
}
fn main() {
  let out = io::stdout(); let mut out = out.lock();
  for line in io::stdin().lock().lines() {
    let line = line.unwrap();
    let mut parts = line.split(' ');
    let text = unhex(&parts.next().unwrap()[1..]);
    let offset: i64 = parts.next().unwrap().parse().unwrap();
    writeln!(out, "{}", sol::align_offset(&text, offset)).unwrap();
  }
}
'''

ALPHABET = ['a', 'Z', '0', ' ', '\n', '\x00', 'é', 'ß', '한', '€', '￿', '\U00010000', '\U0001F600',
            '\U0010FFFF']


def oracle(text, offset):
    data = text.encode('utf-16-le', 'surrogatepass')
    unit = [int.from_bytes(data[k:k + 2], 'little') for k in range(0, len(data), 2)]
    if 0 < offset < len(unit) and 0xdc00 <= unit[offset] <= 0xdfff and 0xd800 <= unit[offset - 1] <= 0xdbff:
        return offset - 1
    return offset


def units(text):
    return len(text.encode('utf-16-le', 'surrogatepass')) // 2


def cases(n, seed):
    r = random.Random(seed)
    E = '\U0001F600'
    rows = [('', 0), ('', 5), ('a', 0), ('a', 1), ('ab', 1), (E, 0), (E, 1), (E, 2), (E, 3),
            ('a' + E, 1), ('a' + E, 2), ('a' + E, 3), (E + 'a', 1), (E + 'a', 2), (E + E, 3), (E + E, 4),
            ('한글', 1), ('한글', 2), ('é' * 5, 4), ('\U0010FFFF' * 3, 5), ('\U00010000b', 1),
            ('abc', 100_000_000_000), (E * 10, 100_000_000_000), ('a' * 300 + E, 300), ('a' * 300 + E, 301),
            (E, 100), ('a' * 300 + E, 302)]
    edges = len(rows)
    for _ in range(n):
        u = r.random()
        if u < 0.5:
            pool = [r.choice(ALPHABET), r.choice(ALPHABET), '\U0001F600']
        else:
            pool = ALPHABET
        text = ''.join(r.choice(pool) for _ in range(r.randint(0, r.choice([2, 8, 30, 120]))))
        m = units(text)
        v = r.random()
        if v < 0.85:
            offset = r.randint(0, max(0, m))
        else:
            offset = r.choice([0, m, m + r.randint(1, 50), 100_000_000_000])
        rows.append((text, offset))
    return rows, edges


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--seed', type=int, default=12345)
    ap.add_argument('--n', type=int, default=20000)
    ap.add_argument('--emit', action='store_true',
                    help='only print JSON lines [text, offset, oracle] (Node bridge test)')
    args = ap.parse_args()
    if args.n < 0:
        ap.error('--n must be nonnegative')
    if args.emit:
        for text, offset in cases(args.n, args.seed)[0]:
            sys.stdout.write(json.dumps([text, offset, oracle(text, offset)]) + '\n')
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
        expected = [oracle(t, c) for t, c in inputs]
        summary['moved_cases'] = sum(e != c for e, (t, c) in zip(expected, inputs))
        summary['past_end_cases'] = sum(c >= units(t) for t, c in inputs)
        summary['astral_cases'] = sum(any(ord(ch) > 0xffff for ch in t) for t, c in inputs)
        node, summary['ts_runtime'] = ts_runtime()
        ts = [json.loads(x) for x in run(node + [HERE / (NAME+'.mjs')],
                                         ''.join(json.dumps({'text': t, 'offset': c})+'\n'
                                                 for t, c in inputs)).split('\n')[:-1]]
        assert len(ts) == len(inputs)
        payload = ''.join('x%s %d\n' % (t.encode().hex(), c) for t, c in inputs)
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
                    pruv = [int(line) for line in lines]
                    for i, ((t, c), p, s, want) in enumerate(zip(inputs, pruv, ts, expected)):
                        if p != s or p != want:
                            differences.append(dict(compiler_backend=key, case_index=i, text=t, offset=c,
                                                    pruv=p, ts=s, expected=want))
                    row.update(cases=len(inputs), pruv_oracle_pass=sum(p == w for p, w in zip(pruv, expected)),
                               ts_oracle_pass=sum(t == w for t, w in zip(ts, expected)),
                               pruv_ts_pass=sum(p == t for p, t in zip(pruv, ts)))
                    ok = row['pruv_oracle_pass'] == row['ts_oracle_pass'] == row['pruv_ts_pass'] == len(inputs)
                    row['status'] = 'ok' if ok else 'wrong'
                    failed |= row['status'] != 'ok'
                    print(key+': '+json.dumps(row), flush=True)
                except Exception as exc:
                    row['error'] = portable(str(exc))
                    failed = True
                    print(key+': '+row['error'], flush=True)
    except Exception as exc:
        summary['error'] = portable(str(exc))
        failed = True
    differences.sort(key=lambda d: (len(d['text']), d['text'], d['offset'], d['compiler_backend']))
    summary.update(status='error' if failed else 'ok', difference_records_total=len(differences),
                   difference_records_saved=min(50, len(differences)),
                   difference_order='text length, text, offset, compiler/backend')
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / (NAME+'_summary.json')).write_text(json.dumps(summary, indent=2)+'\n')
    (RESULTS / (NAME+'_differences.jsonl')).write_text(''.join(json.dumps(d)+'\n' for d in differences[:50]))
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
