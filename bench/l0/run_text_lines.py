#!/usr/bin/env python3
"""Cross-check the line part of Lair textDraft (src/documents/extract.ts), the plain text extractor.

Each [text, chars] goes to Pruv (text_lines.pruv: one pass over the UTF-8 bytes, returns [line count,
kept line count]), to the TypeScript copy (text_lines.mjs, run in Lair's Electron when available) and to
an independent oracle written from the description: Python str.split on LF, one trailing CR removed per
line, the last line dropped if empty, then the kept count from the running total of UTF-16 length + 1.
Domain: integer chars in -10^15..10^15, text any Unicode string without lone surrogates. Inputs: edge
texts (empty, lone CR/LF, CRLF endings, double CR, 4-byte characters at line ends) with limits around
each running total and +-10^15, and random texts (seed 12345) over ASCII, CR, LF, 2-, 3- and 4-byte
characters with random limits.
"""
import argparse
import json
import random
import sys

sys.dont_write_bytecode = True

NAME = 'text_lines'

HARNESS = '''#![allow(dead_code, unused_imports)]
#[path = "@SOL@"] mod sol;
use std::io::{self, BufRead, Write};
fn main() {
  let out = io::stdout(); let mut out = out.lock();
  for line in io::stdin().lock().lines() {
    let line = line.unwrap();
    let mut it = line.splitn(2, ' ');
    let chars: i64 = it.next().unwrap().parse().unwrap(); let hex = &it.next().unwrap()[1..];
    let data: Vec<u8> = (0..hex.len()).step_by(2).map(|i| u8::from_str_radix(&hex[i..i+2], 16).unwrap()).collect();
    let s = String::from_utf8(data).unwrap();
    let r = sol::text_lines(&s, chars);
    writeln!(out, "x {} {}", r[0], r[1]).unwrap();
  }
}
'''

BIG = 10**15
ALPHABET = ['a', 'b', 'Z', ' ', '\t', '\n', '\n', '\r', '\r\n', 'é', '한', ' ', '\U0001F600', '\U00010348']


def units(line):
    return len(line.encode('utf-16-le')) // 2


def oracle(text, chars):
    lines = [x[:-1] if x.endswith('\r') else x for x in text.split('\n')]
    if lines and lines[-1] == '':
        lines.pop()
    total = 0
    for i, line in enumerate(lines):
        total += units(line) + 1
        if total > chars:
            return [len(lines), i]
    return [len(lines), len(lines)]


def totals(text):
    lines = [x[:-1] if x.endswith('\r') else x for x in text.split('\n')]
    if lines and lines[-1] == '':
        lines.pop()
    out, t = [0], 0
    for line in lines:
        t += units(line) + 1
        out.append(t)
    return out


def cases(n, seed):
    r = random.Random(seed)
    texts = ['', '\n', '\r', '\r\n', '\n\n', '\r\r', '\r\r\n', '\n\r', 'a', 'a\n', 'a\r\n', 'a\r', 'a\n\r',
             'a\nb', 'a\r\nb\r\n', '\n\nx\n\n', '\U0001F600', '\U0001F600\r\n\U0001F600', 'é\n한\r',
             ' \r \n', ' \n ', 'abc\r\r\ndef']
    rows = []
    for text in texts:
        limits = {-BIG, BIG, -1, 0}
        for t in totals(text):
            limits |= {t - 1, t, t + 1}
        rows += [(text, c) for c in sorted(limits)]
    edges = len(rows)
    for _ in range(n):
        k = r.choice([0, 1, 2, 5, 10, 30, 80])
        text = ''.join(r.choice(ALPHABET) for _ in range(r.randint(0, k)))
        top = totals(text)[-1]
        u = r.random()
        chars = r.choice([-BIG, BIG]) if u < 0.05 else r.randint(-3, top + 3)
        rows.append((text, chars))
    return rows, edges


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--seed', type=int, default=12345)
    ap.add_argument('--n', type=int, default=20000)
    ap.add_argument('--emit', action='store_true',
                    help='only print JSON lines [text, chars, oracle] (Node bridge test)')
    args = ap.parse_args()
    if args.n < 0:
        ap.error('--n must be nonnegative')
    if args.emit:
        for row in cases(args.n, args.seed)[0]:
            sys.stdout.write(json.dumps([*row, oracle(*row)]) + '\n')
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
        expected = [oracle(*row) for row in inputs]
        summary['oracle_lines'] = sum(e[0] for e in expected)
        summary['oracle_kept_lines'] = sum(e[1] for e in expected)
        summary['cut_cases'] = sum(e[1] < e[0] for e in expected)
        summary['crlf_cases'] = sum('\r\n' in row[0] for row in inputs)
        node, summary['ts_runtime'] = ts_runtime()
        ts = [json.loads(x) for x in run(node + [HERE / (NAME+'.mjs')],
                                         ''.join(json.dumps({'text': t, 'chars': c})+'\n' for t, c in inputs)).split('\n')[:-1]]
        assert len(ts) == len(inputs)
        payload = ''.join('%d x%s\n' % (c, t.encode().hex()) for t, c in inputs)
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
                    pruv = [[int(x) for x in line[2:].split()] for line in lines]
                    for i, (inp, p, s, want) in enumerate(zip(inputs, pruv, ts, expected)):
                        if p != s or p != want:
                            differences.append(dict(compiler_backend=key, case_index=i, text=inp[0], chars=inp[1],
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
    differences.sort(key=lambda d: (len(d['text']), d['text'], d['chars'], d['compiler_backend']))
    summary.update(status='error' if failed else 'ok', difference_records_total=len(differences),
                   difference_records_saved=min(50, len(differences)),
                   difference_order='text length, text, chars, compiler/backend')
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / (NAME+'_summary.json')).write_text(json.dumps(summary, indent=2)+'\n')
    (RESULTS / (NAME+'_differences.jsonl')).write_text(''.join(json.dumps(d)+'\n' for d in differences[:50]))
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
