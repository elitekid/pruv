#!/usr/bin/env python3
"""Cross-check the string branch of cellText (Lair src/documents/sheets.ts).

A string goes to Pruv (cell_str.pruv: newline replacement and trim on UTF-8 bytes, result proved no longer
than the input), to the TypeScript copy (cell_str.mjs, run in Lair's Electron when available) and to an
independent oracle that replaces "\\r\\n" and then "\\n" by a space with str.replace and strips an explicit
list of the ECMAScript white space and line terminator characters, not by copying the TS expression.
Domain: well-formed strings (no lone surrogates).
Inputs: the empty string, every trim character alone and around text, near misses that are not trimmed
(U+0085, U+180E, U+200B, U+2060, U+001C..U+001F, U+00A1, U+1681, U+200C, U+2030, U+3001, U+FEFE), lone and
doubled "\\r", "\\r\\r\\n", "\\n\\r", long runs, random mixes of white space, near misses, text, Korean and
emoji with lengths up to 2,000 characters.
"""
import argparse
import json
import random
import sys

sys.dont_write_bytecode = True

NAME = 'cell_str'

HARNESS = '''#![allow(dead_code, unused_imports)]
#[path = "@SOL@"] mod sol;
use std::io::{self, BufRead, Write};
fn hex(s: &str) -> String { s.bytes().map(|b| format!("{:02x}", b)).collect() }
fn main() {
  let out = io::stdout(); let mut out = out.lock();
  for line in io::stdin().lock().lines() {
    let line = line.unwrap();
    let buf: Vec<u8> = line[1..].as_bytes().chunks(2).map(|p| u8::from_str_radix(std::str::from_utf8(p).unwrap(), 16).unwrap()).collect();
    let text = std::str::from_utf8(&buf).unwrap();
    writeln!(out, "x{}", hex(&sol::cell_str(text))).unwrap();
  }
}
'''

# ECMAScript WhiteSpace (TAB, VT, FF, SP, NBSP, ZWNBSP, Zs) and LineTerminator (LF, CR, LS, PS).
TRIM = ('\t\n\v\f\r   ' + ''.join(chr(c) for c in range(0x2000, 0x200b))
        + '    　﻿')
NEAR = ['\u0085', '᠎', '​', '⁠', '\x1c', '\x1d', '\x1e', '\x1f', '¡', 'ᚁ',
        '‌', '‰', '、', '﻾', '⁞', '‧', '‮', '\x08', '\x0e']
TEXT = ['a', 'Z', '7', ',', '표', '한', 'é', '…', '\U0001f600', '\U00010348', '�']
SPACES = list(TRIM) + ['\r\n']


def oracle(text):
    return text.replace('\r\n', ' ').replace('\n', ' ').strip(TRIM)


def outcome(text, want):
    if want == '':
        return 'empty'
    replaced = text.replace('\r\n', ' ').replace('\n', ' ')
    if want == text:
        return 'unchanged'
    if want == replaced:
        return 'newlines_only'
    return 'trimmed'


def piece(r, mix):
    x = r.random()
    if x < mix[0]:
        return r.choice(SPACES)
    if x < mix[0] + mix[1]:
        return r.choice(NEAR)
    return r.choice(TEXT)


def rand_text(r):
    kind = r.randrange(5)
    mix = r.choice([(0.3, 0.1), (0.6, 0.2), (0.1, 0.1), (0.9, 0.05), (0.4, 0.4)])
    if kind == 0:
        return ''.join(piece(r, mix) for _ in range(r.randrange(0, 12)))
    if kind == 1:
        return ''.join(piece(r, mix) for _ in range(r.randrange(0, 200)))
    if kind == 2:   # white space on both ends around a core
        side = lambda: ''.join(r.choice(SPACES) for _ in range(r.randrange(0, 8)))
        core = ''.join(piece(r, (0.2, 0.3)) for _ in range(r.randrange(0, 20)))
        return side() + core + side()
    if kind == 3:   # near misses at the ends
        return r.choice(NEAR) + ''.join(piece(r, mix) for _ in range(r.randrange(0, 20))) + r.choice(NEAR)
    return ''.join(piece(r, mix) for _ in range(r.randrange(500, 2000)))


def edge_cases():
    rows = ['', 'a', ' a ', '\r', '\n', '\r\n', '\r\r\n', '\n\r', '\r\r', 'a\rb', 'a\r\nb', 'a\nb', 'a\r\r\nb',
            'a\n\rb', '\r a \r', '\ra\r', 'a\r', '\ra', ' \r\n a \r\n ', '\n\n\n', '\r\n\r\n', 'x\n\ny']
    for c in TRIM:
        rows += [c, c + 'a', 'a' + c, c + 'a' + c, 'a' + c + 'b', c * 3]
    for c in NEAR:
        rows += [c, ' ' + c + ' ', c + 'a' + c]
    rows += [TRIM, TRIM + 'x' + TRIM, TRIM[::-1] + '표' + TRIM, ''.join(NEAR), ' ' * 100000,
             '　' * 50000 + 'a', 'a' + '﻿' * 50000, '\r\n' * 30000, '\U0001f600' * 1000,
             ' \U0001f600 ', ' ¡', '¡ ']
    return rows


def cases(n, seed):
    rows = edge_cases()
    edges = len(rows)
    r = random.Random(seed)
    for _ in range(n):
        rows.append(rand_text(r))
    for t in rows:
        t.encode('utf-8')   # well-formed: raises on a lone surrogate
    return rows, edges


def ts_line(text):
    return json.dumps(dict(text=text))


def harness_line(text):
    return 'n' + text.encode().hex()


def brief(text):
    return dict(chars=len(text), head=text[:60], tail=text[-60:])


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--seed', type=int, default=12345)
    ap.add_argument('--n', type=int, default=20000)
    ap.add_argument('--emit', action='store_true', help='only print JSON lines [text, oracle]')
    args = ap.parse_args()
    if args.n < 0:
        ap.error('--n must be nonnegative')
    if args.emit:
        for text in cases(args.n, args.seed)[0]:
            sys.stdout.write(json.dumps([text, oracle(text)]) + '\n')
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
        want = [oracle(text) for text in inputs]
        kinds = [outcome(t, w) for t, w in zip(inputs, want)]
        summary['oracle_outcomes'] = {k: kinds.count(k) for k in ('unchanged', 'newlines_only', 'trimmed', 'empty')}
        summary['oracle_outcomes'].update(
            kept_lone_cr=sum(1 for w in want if '\r' in w),
            max_input_utf8_bytes=max(len(t.encode()) for t in inputs))
        node, summary['ts_runtime'] = ts_runtime()
        # not splitlines: U+2028 stays in a JSON string
        ts = [json.loads(x) for x in run(node + [HERE / (NAME+'.mjs')], ''.join(ts_line(text)+'\n' for text in inputs)).split('\n')[:-1]]
        assert len(ts) == len(inputs)
        summary['ts_oracle_pass'] = sum(t == w for t, w in zip(ts, want))
        payload = ''.join(harness_line(text) + '\n' for text in inputs)
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
                    for i, (text, p, t, w) in enumerate(zip(inputs, pruv, ts, want)):
                        if p != t or p != w:
                            differences.append(dict(compiler_backend=key, case_index=i, input=brief(text), pruv=p, ts=t, expected=w))
                    row_.update(cases=len(inputs), pruv_oracle_pass=sum(p == w for p, w in zip(pruv, want)),
                                ts_oracle_pass=summary['ts_oracle_pass'],
                                pruv_ts_pass=sum(p == t for p, t in zip(pruv, ts)))
                    row_['status'] = 'ok' if row_['pruv_oracle_pass'] == len(inputs) and row_['pruv_ts_pass'] == len(inputs) else 'wrong'
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
