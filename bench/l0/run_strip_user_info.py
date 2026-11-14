#!/usr/bin/env python3
"""Cross-check the URL user info strip of Lair (stripUserInfo in src/backend/git-changes.ts).

Each text goes to Pruv (strip_user_info.pruv: one pass over the UTF-8 text that finds a scheme run after a
non-word character, `://`, and the last `@` before the next JS whitespace or `/`), to the TypeScript copy
(strip_user_info.mjs, run in Lair's Electron when available) and to an independent oracle built on Python's
re module with the JS whitespace set written out and a lookbehind in place of `\\b`.
Domain: any Unicode text without lone surrogates. Inputs: edge texts (Git remote lines, several URLs, `@`
after `/` or whitespace, word characters before the scheme, schemes with `+.-`, Unicode spaces) and random
texts (seed 12345) built from URL pieces, letters, digits, separators and 1- to 4-byte characters.
"""
import argparse
import json
import random
import re
import sys

sys.dont_write_bytecode = True

NAME = 'strip_user_info'

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
    let text = unhex(&line[1..]);
    let r = sol::strip_user_info(&text);
    let hex: String = r.as_bytes().iter().map(|b| format!("{:02x}", b)).collect();
    writeln!(out, "x{}", hex).unwrap();
  }
}
'''

# JS \\s: ECMAScript WhiteSpace and LineTerminator code points.
JS_SPACE = '\t\n\x0b\x0c\r \xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff'
STRIP = re.compile('(?<![A-Za-z0-9_])([A-Za-z][A-Za-z0-9+.\\-]*://)[^/' + JS_SPACE + ']*@')

PIECES = ['https://', 'http://', 'ssh://', 'git+ssh://', 'svn+ssh://', 'a.b-c://', '://', ':/', ':', '/', '//',
          '@', '@@', 'user', 'user:pw@', 'tok@', 'x', 'Z', 'h', '0', '9', '_', '-', '+', '.', ' ', '\t', '\n',
          '\r', '\x0b', '\xa0', '\u1680', '\u2000', '\u200a', '\u200b', '\u2028', '\u3000', '\ufeff',
          'é', 'ſ', '\u212a', '한', '\U0001F600', 'github.com', 'git@github.com:', 'HTTPS://', '\\']


def oracle(text):
    return STRIP.sub(lambda m: m.group(1), text)


def cases(n, seed):
    r = random.Random(seed)
    rows = ['', 'https://github.com/a/b', 'https://user:token@github.com/a/b.git',
            "fatal: unable to access 'https://x:y@host/r.git/': 403", 'HTTPS://U@H', 'git+ssh://git@h/r',
            'a.b-c://u@h', 'xhttps://u@h', '_https://u@h', '-https://u@h', 'https://a@b@c/d@e',
            'https://u v@h', 'https://u/@h', 'http://u@h http://v@h', 'https://u\u3000x@h', 'https://u\u200bx@h',
            '1http://u@h', 'ſhttps://u@h', 'é://u@h', 'https:/u@h', 'https://@h', 'h://://u@x', 'https://u@',
            'git@github.com:a/b.git']
    edges = len(rows)
    for _ in range(n):
        rows.append(''.join(r.choice(PIECES) for _ in range(r.randint(0, r.choice([1, 3, 8, 20, 40])))))
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
        for v in cases(args.n, args.seed)[0]:
            sys.stdout.write(json.dumps([v, oracle(v)]) + '\n')
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
        expected = [oracle(v) for v in inputs]
        summary['scheme_values'] = sum('://' in v for v in inputs)
        summary['changed_values'] = sum(e != v for v, e in zip(inputs, expected))
        summary['multiple_strip_values'] = sum(len(STRIP.findall(v)) > 1 for v in inputs)
        node, summary['ts_runtime'] = ts_runtime()
        ts = [json.loads(x) for x in run(node + [HERE / (NAME+'.mjs')],
                                         ''.join(json.dumps(v)+'\n' for v in inputs)).split('\n')[:-1]]
        assert len(ts) == len(inputs)
        payload = ''.join('x%s\n' % v.encode().hex() for v in inputs)
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
                    pruv = [bytes.fromhex(line[1:]).decode() for line in lines]
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
