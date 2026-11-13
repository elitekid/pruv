#!/usr/bin/env python3
"""Cross-check the streaming terminal-text cleaner (Lair plainFromAnsi + applyCrLf).

Each case is an initial state 0..11 and a list of chunks. Pruv runs term_plain and
term_state chunk by chunk; the TypeScript copy streams the same chunks; the oracle
below processes the concatenated text in one pass, so it also checks that chunking
does not change the result.
"""
import argparse
import json
import random
import re
import sys

sys.dont_write_bytecode = True
from run import HERE, WORK, RESULTS, configure, run
from run_host_within import portable

NAME = 'term_plain'
STRING_INTRO = {']', 'P', 'X', '^', '_'}
C1_STRING = {'\x90', '\x98', '\x9d', '\x9e', '\x9f'}


def oracle(state, chunks):
    """Whole-text reference: a mode machine over code points, then a regex CR/LF fold."""
    mode = ['text', 'esc', 'escint', 'csi', 'str', 'strend'][state % 6]
    kept = []
    text = ''.join(chunks)
    pos = 0
    while pos < len(text):
        ch, o = text[pos], ord(text[pos])
        if mode == 'strend':
            mode = 'text' if ch == '\\' else 'str'
            if mode == 'text':
                pos += 1
                continue
        if mode in ('esc', 'escint'):
            if 0x20 <= o <= 0x2f:
                mode = 'escint'
            elif mode == 'esc' and ch == '[':
                mode = 'csi'
            elif mode == 'esc' and ch in STRING_INTRO:
                mode = 'str'
            elif 0x30 <= o <= 0x7e:
                mode = 'text'
            else:
                mode = 'text'
                continue  # not part of the sequence: look at it again as text
            pos += 1
            continue
        if mode == 'csi':
            if '@' <= ch <= '~':
                mode = 'text'
        elif mode == 'str':
            if ch in '\x07\x9c':
                mode = 'text'
            elif ch == '\x1b':
                mode = 'strend'
        elif ch == '\x1b':
            mode = 'esc'
        elif ch == '\x9b':
            mode = 'csi'
        elif ch in C1_STRING:
            mode = 'str'
        elif ch in '\t\n\r' or not (o < 0x20 or 0x7f <= o <= 0x9f):
            kept.append(ch)
        pos += 1
    raw = ''.join(kept)
    skip_in = state >= 6
    skip_out = raw.endswith('\r') or (raw == '' and skip_in)
    if skip_in and raw.startswith('\n'):
        raw = raw[1:]
    folded = re.sub('\r\n?', '\n', raw)
    final = ['text', 'esc', 'escint', 'csi', 'str', 'strend'].index(mode) + (6 if skip_out else 0)
    return [folded, final]


ALPHABET = (['\x1b'] * 6 + list('[]PX^_\\') * 2 + ['\x07', '\r', '\r', '\n', '\n', '\t']
            + list('0123;mAH~@') + [chr(c) for c in range(0x20, 0x30)] + ['\x7f', '\x00', '\x01', '\x08']
            + ['\x9b', '\x9c', '\x9d', '\x90', '\x98', '\x9e', '\x9f', '\x85', '\x80']
            + ['\xa0', 'é', '한', '😀', 'a', 'z'])


def cases(n, seed):
    r = random.Random(seed)
    pieces = ['', 'a', '\r', '\n', '\r\n', '\x1b', '\x1b\\', '\x1b[', '\x1b]0;t\x07', '\x1b]0;t\x1b',
              '\\', '\x1b(B', '\x1b #', '\x1b\x9b', '\x9b31m', '\x9d0;x\x9c', '\x1b[1;2~', '\x1bP?\x1b\\',
              '\x85', '\x7f', '\xa0', 'é', '한', '😀', '\x1b😀', '\x1b[😀m', '\x1b]\x1b\x1b\\']
    rows = [[st, [a, b]] for st in range(12) for a in pieces for b in pieces]
    edges = len(rows)
    for _ in range(n):
        text = ''.join(r.choice(ALPHABET) for _ in range(r.randrange(41)))
        cuts = sorted(r.sample(range(len(text) + 1), min(len(text) + 1, r.randrange(4))))
        bounds = [0] + cuts + [len(text)]
        rows.append([r.randrange(12), [text[a:b] for a, b in zip(bounds, bounds[1:])]])
    return rows, edges


HARNESS = '''#![allow(dead_code, unused_imports)]
#[path = "@SOL@"] mod sol;
use std::io::{self, BufRead, Write};
fn decode(s: &str) -> String { String::from_utf8((0..s.len()).step_by(2).map(|i| u8::from_str_radix(&s[i..i+2],16).unwrap()).collect()).unwrap() }
fn main() {
  let out = io::stdout(); let mut out = out.lock();
  for line in io::stdin().lock().lines() {
    let line = line.unwrap(); let mut parts = line.split(' ');
    let mut st: i64 = parts.next().unwrap().parse().unwrap();
    let mut text = String::new();
    for hex in parts { let chunk = decode(&hex[1..]); text.push_str(&sol::term_plain(st, &chunk)); st = sol::term_state(st, &chunk); }
    let hex: String = text.bytes().map(|b| format!("{:02x}", b)).collect();
    writeln!(out, "{} {}", st, hex).unwrap();
  }
}
'''


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--seed', type=int, default=12345)
    ap.add_argument('--n', type=int, default=20000)
    args = ap.parse_args()
    if args.n < 0:
        ap.error('--n must be nonnegative')
    summary = dict(seed=args.seed, random_cases=args.n, runs={})
    differences, failed = [], False
    try:
        g2, summary['tools'] = configure()
        inputs, summary['edge_cases'] = cases(args.n, args.seed)
        summary['cases'] = len(inputs)
        expected = [oracle(st, ch) for st, ch in inputs]
        ts = [json.loads(x) for x in run(['node', HERE / (NAME+'.mjs')], ''.join(json.dumps(x)+'\n' for x in inputs)).splitlines()]
        assert len(ts) == len(inputs)
        # Chunks are prefixed with 'x' so an empty chunk is still a separate field.
        payload = ''.join(str(st)+''.join(' x'+c.encode().hex() for c in ch)+'\n' for st, ch in inputs)
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
                    for x in lines:
                        st, _, hx = x.partition(' ')
                        pruv.append([bytes.fromhex(hx).decode(), int(st)])
                    for i, (c, p, t, want) in enumerate(zip(inputs, pruv, ts, expected)):
                        if p != t or p != want:
                            differences.append(dict(compiler_backend=key, case_index=i, input=c,
                                input_bytes=sum(len(s.encode()) for s in c[1]), pruv=p, ts=t, expected=want))
                    row.update(cases=len(inputs), pruv_oracle_pass=sum(p == w for p, w in zip(pruv, expected)),
                               ts_oracle_pass=sum(t == w for t, w in zip(ts, expected)),
                               pruv_ts_pass=sum(p == t for p, t in zip(pruv, ts)))
                    ok = row['pruv_oracle_pass'] == row['ts_oracle_pass'] == len(inputs)
                    row['status'] = 'ok' if ok else 'wrong'
                    failed |= not ok
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
                   difference_order='input bytes, serialized input, compiler/backend')
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / (NAME+'_summary.json')).write_text(json.dumps(summary, indent=2)+'\n')
    (RESULTS / (NAME+'_differences.jsonl')).write_text(''.join(json.dumps(d)+'\n' for d in differences[:50]))
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
