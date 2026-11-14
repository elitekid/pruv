#!/usr/bin/env python3
"""Cross-check the conversation number shape check of Lair (validThread in src/backend/engine-import/tail.ts).

Each text goes to Pruv (valid_thread.pruv: a byte pass over 1 to 128 ASCII bytes), to the TypeScript copy
(valid_thread.mjs, run in Lair's Electron when available) and to an independent oracle written from the
rule with Python re.fullmatch over [A-Za-z0-9][A-Za-z0-9_-]{0,127} (fullmatch, so a trailing line break
fails as it does with JS $ without the m flag).
Domain: any Unicode text without lone surrogates. Inputs: edge texts (empty, lengths 1, 127, 128, 129,
leading '_', '-', '.', path characters, trailing line breaks, non-ASCII letters and digits) and random
texts (seed 12345): valid shapes near the length limit, valid shapes with one changed character, and
mixed text over ASCII, 2-, 3- and 4-byte characters.
"""
import argparse
import json
import random
import sys

sys.dont_write_bytecode = True

NAME = 'valid_thread'

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
    writeln!(out, "{}", if sol::valid_thread(&s) { 1 } else { 0 }).unwrap();
  }
}
'''

import re

OK = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}')
FIRST = 'abzAZ09'
REST = 'abzAZ09_-'
ALPHABET = ['a', 'Z', '0', '9', '_', '-', '.', '/', '\\', ' ', '\n', '\r', '\t', '\x00', '\x7f', '@', ':',
            'é', 'ſ', 'K', '١', '０', '한', '￿', '\U0001F600', '\U0010FFFF']


def oracle(text):
    return OK.fullmatch(text) is not None


def shape(r, length):
    return r.choice(FIRST) + ''.join(r.choice(REST) for _ in range(length - 1))


def cases(n, seed):
    r = random.Random(seed)
    rows = ['', 'a', 'Z', '0', '_', '-', '.', 'a_', 'a-', 'a.', '_a', '-a', '.a', '..', 'a/b', 'a\\b',
            'a b', 'a\n', 'a\r\n', '\na', 'a\x00', 'é', 'aé', 'ſ', 'K', '١', '０', 'a\U0001F600',
            'a' * 127, 'a' * 128, 'a' * 129, '0' + '-' * 127, '0' + '-' * 128, 'a' * 128 + '\n',
            'sess_1787058448-16231', '019a3b2c-7d4e-7f00-8a1b-2c3d4e5f6a7b']
    edges = len(rows)
    for _ in range(n):
        u = r.random()
        if u < 0.35:
            text = shape(r, r.choice([1, 2, 8, 36, r.randint(1, 140), 126, 127, 128, 129, 130]))
        elif u < 0.65:
            t = list(shape(r, r.randint(1, 130)))
            t[r.randrange(len(t))] = r.choice(ALPHABET)
            text = ''.join(t)
        else:
            text = ''.join(r.choice(ALPHABET) for _ in range(r.randint(0, r.choice([1, 3, 10, 30, 140]))))
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
        summary['length_128_cases'] = sum(len(t) == 128 for t in inputs)
        summary['length_over_128_cases'] = sum(len(t) > 128 for t in inputs)
        summary['non_ascii_cases'] = sum(not t.isascii() for t in inputs)
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
