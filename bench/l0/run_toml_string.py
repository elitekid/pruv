#!/usr/bin/env python3
"""Cross-check the TOML basic string of Lair (tomlString in src/backend/provider-accounts.ts).

Each value goes to Pruv (toml_string.pruv: one pass over the UTF-8 value that puts a backslash before `"`
and `\\` and writes U+0000..U+001F, U+007F, U+2028 and U+2029 as `\\u` with four lowercase hex digits),
to the TypeScript copy (toml_string.mjs, run in Lair's Electron when available) and to an independent
oracle that maps code points through a table written from the TOML rule (Python format(code, '04x')).
Domain: any Unicode value without lone surrogates. Inputs: edge values (empty, every C0 control, DEL,
U+0080..U+009F which are not escaped, U+2027..U+202A, quotes, backslashes, 4-byte characters) and random
values (seed 12345) over an alphabet of controls, quotes, backslashes, line separators and 1- to 4-byte
characters.
"""
import argparse
import json
import random
import sys

sys.dont_write_bytecode = True

NAME = 'toml_string'

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
    let value = unhex(&line[1..]);
    let r = sol::toml_string(&value);
    let hex: String = r.as_bytes().iter().map(|b| format!("{:02x}", b)).collect();
    writeln!(out, "x{}", hex).unwrap();
  }
}
'''

ALPHABET = ['a', 'Z', '0', ' ', '"', "'", '\\', '\x00', '\x01', '\t', '\n', '\r', '\x1b', '\x1f', '\x7f',
            '\x80', '\x85', '\x9f', '\xa0', 'é', '한', '\u2027', '\u2028', '\u2029', '\u202a', '\ufeff',
            '\uffff', '\U0001F600', '\U0010FFFF', 'u', '{', '}']


def oracle(value):
    out = ['"']
    for ch in value:
        code = ord(ch)
        if ch == '"':
            out.append('\\"')
        elif ch == '\\':
            out.append('\\\\')
        elif code < 0x20 or code == 0x7f or code in (0x2028, 0x2029):
            out.append('\\u' + format(code, '04x'))
        else:
            out.append(ch)
    out.append('"')
    return ''.join(out)


def cases(n, seed):
    r = random.Random(seed)
    rows = ['', 'a', '"', '\\', '\\"', '""', 'a"b\\c', ''.join(chr(c) for c in range(0x20)), '\x7f',
            ''.join(chr(c) for c in range(0x80, 0xa0)), '\u2027\u2028\u2029\u202a', '\U0001F600"\U0010FFFF',
            'C:\\Users\\x\\.codex', 'line1\nline2\r\n', '\\u0041', '\x00\x00']
    edges = len(rows)
    for _ in range(n):
        rows.append(''.join(r.choice(ALPHABET) for _ in range(r.randint(0, r.choice([1, 3, 10, 30, 80])))))
    return rows, edges

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--seed', type=int, default=12345)
    ap.add_argument('--n', type=int, default=20000)
    ap.add_argument('--emit', action='store_true',
                    help='only print JSON lines [value, oracle] (Node bridge test)')
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
        summary['control_values'] = sum(any(ord(ch) < 0x20 or ch == '\x7f' for ch in v) for v in inputs)
        summary['quote_or_backslash_values'] = sum(any(ch in v for ch in '"\\') for v in inputs)
        summary['line_separator_values'] = sum(any(ch in v for ch in '\u2028\u2029') for v in inputs)
        summary['unchanged_values'] = sum(e == '"' + v + '"' for v, e in zip(inputs, expected))
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
                            differences.append(dict(compiler_backend=key, case_index=i, value=inp,
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
    differences.sort(key=lambda d: (len(d['value']), d['value'], d['compiler_backend']))
    summary.update(status='error' if failed else 'ok', difference_records_total=len(differences),
                   difference_records_saved=min(50, len(differences)),
                   difference_order='value length, value, compiler/backend')
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / (NAME+'_summary.json')).write_text(json.dumps(summary, indent=2)+'\n')
    (RESULTS / (NAME+'_differences.jsonl')).write_text(''.join(json.dumps(d)+'\n' for d in differences[:50]))
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
