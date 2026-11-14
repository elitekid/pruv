#!/usr/bin/env python3
"""Cross-check the Luhn card number check of Lair sensitiveReason (luhn in src/shared/common-memory.ts).

Each text goes to Pruv (luhn.pruv: one forward pass decoding UTF-8 into UTF-16 units with an even and an
odd doubled sum), to the TypeScript copy (luhn.mjs, run in Lair's Electron when available) and to an
independent oracle written from the Luhn rule: the UTF-16 units reversed, (unit - 48) with every second
one doubled and 9 taken off a doubled value over 9, the total divisible by 10.
Domain: any Unicode text without lone surrogates. Inputs: edge texts (empty, single digits, known card
numbers and their one-digit changes, 13- and 19-digit runs, letters, high BMP and 4-byte characters) and
random texts (seed 12345): digit runs of 13..19 digits (half made valid with a check digit) as
sensitiveReason passes them, shorter and longer digit runs, and mixed text over ASCII, 2-, 3- and 4-byte
characters.
"""
import argparse
import json
import random
import sys

sys.dont_write_bytecode = True

NAME = 'luhn'

HARNESS = '''#![allow(dead_code, unused_imports)]
#[path = "@SOL@"] mod sol;
use std::io::{self, BufRead, Write};
fn main() {
  let out = io::stdout(); let mut out = out.lock();
  for line in io::stdin().lock().lines() {
    let line = line.unwrap();
    let hex = &line[1..];
    let data: Vec<u8> = (0..hex.len()).step_by(2).map(|i| u8::from_str_radix(&hex[i..i+2], 16).unwrap()).collect();
    let s = String::from_utf8(data).unwrap();
    writeln!(out, "{}", if sol::luhn(&s) { 1 } else { 0 }).unwrap();
  }
}
'''

ALPHABET = ['0', '1', '5', '9', 'a', 'Z', ' ', '-', '/', ':', '\x7f', 'é', 'ÿ', '한', '\uffff', '\ue000',
            '\U0001F600', '\U00010348', '\U0010FFFF']


def units(text):
    data = text.encode('utf-16-le')
    return [data[i] | data[i + 1] << 8 for i in range(0, len(data), 2)]


def oracle(text):
    total = 0
    for pos, u in enumerate(reversed(units(text))):
        v = u - 48
        if pos % 2 == 1:
            v *= 2
            if v > 9:
                v -= 9
        total += v
    return total % 10 == 0


def with_check(body):
    for d in '0123456789':
        if oracle(body + d):
            return body + d
    raise AssertionError(body)


def cases(n, seed):
    r = random.Random(seed)
    rows = ['', '0', '1', '5', '9', '00', '18', '59', '4111111111111111', '4111111111111112',
            '5500000000000004', '378282246310005', '6011111111111117', '4012888888881881',
            '0000000000000', '9999999999999999999', '1234567890123', '1234567812345670',
            'abc', 'a', ' ', '\x00', '\x7f', 'é', '한', '\uffff', '\U0001F600', '\U0010FFFF',
            '4111 1111 1111 1111', '4111-1111-1111-1111', '\U0001F6004', '4\U0001F600']
    edges = len(rows)
    for _ in range(n):
        u = r.random()
        if u < 0.4:
            body = ''.join(r.choice('0123456789') for _ in range(r.randint(12, 18)))
            text = with_check(body) if r.random() < 0.5 else body + r.choice('0123456789')
        elif u < 0.6:
            text = ''.join(r.choice('0123456789') for _ in range(r.choice([0, 1, 2, 5, 12, 20, 40, 100])))
        else:
            text = ''.join(r.choice(ALPHABET) for _ in range(r.randint(0, r.choice([1, 3, 10, 30, 80]))))
        rows.append(text)
    return rows, edges


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--seed', type=int, default=12345)
    ap.add_argument('--n', type=int, default=20000)
    ap.add_argument('--emit', action='store_true',
                    help='only print JSON lines [text, oracle] (Node bridge test)')
    args = ap.parse_args()
    if args.n < 0:
        ap.error('--n must be nonnegative')
    if args.emit:
        for row in cases(args.n, args.seed)[0]:
            sys.stdout.write(json.dumps([row, oracle(row)]) + '\n')
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
        expected = [oracle(row) for row in inputs]
        summary['oracle_true'] = sum(expected)
        summary['card_shape_cases'] = sum(t.isascii() and t.isdigit() and 13 <= len(t) <= 19 for t in inputs)
        summary['card_shape_true'] = sum(e for t, e in zip(inputs, expected) if t.isascii() and t.isdigit() and 13 <= len(t) <= 19)
        summary['non_digit_cases'] = sum(not (t.isascii() and t.isdigit()) for t in inputs)
        node, summary['ts_runtime'] = ts_runtime()
        ts = [json.loads(x) for x in run(node + [HERE / (NAME+'.mjs')],
                                         ''.join(json.dumps({'text': t})+'\n' for t in inputs)).split('\n')[:-1]]
        assert len(ts) == len(inputs)
        payload = ''.join('x%s\n' % t.encode().hex() for t in inputs)
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
                    pruv = [line == '1' for line in lines]
                    for i, (inp, p, s, want) in enumerate(zip(inputs, pruv, ts, expected)):
                        if p != s or p != want:
                            differences.append(dict(compiler_backend=key, case_index=i, text=inp,
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
    differences.sort(key=lambda d: (len(d['text']), d['text'], d['compiler_backend']))
    summary.update(status='error' if failed else 'ok', difference_records_total=len(differences),
                   difference_records_saved=min(50, len(differences)),
                   difference_order='text length, text, compiler/backend')
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / (NAME+'_summary.json')).write_text(json.dumps(summary, indent=2)+'\n')
    (RESULTS / (NAME+'_differences.jsonl')).write_text(''.join(json.dumps(d)+'\n' for d in differences[:50]))
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
