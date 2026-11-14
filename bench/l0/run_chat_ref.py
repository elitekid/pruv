#!/usr/bin/env python3
"""Cross-check the chat reference text of Lair (chatRefText in src/shared/chat-ref.ts).

Each (title, id) goes to Pruv (chat_ref.pruv: one pass over the UTF-8 title that folds each whitespace run
holding a CR or LF to one space and puts a backslash before backslash and square brackets), to the
TypeScript copy (chat_ref.mjs, run in Lair's Electron when available) and to an independent oracle that
splits the title into maximal runs of the ECMAScript whitespace set (WhiteSpace and LineTerminator code
points, listed by hand) and rebuilds the text.
Domain: any Unicode title and id without lone surrogates. Inputs: edge titles (empty, CR, LF, CRLF, runs
of every whitespace code point with and without a line break, brackets and backslashes, U+0085 and
U+180E which are not whitespace, 4-byte characters) and random titles (seed 12345) over an alphabet of
whitespace, line breaks, brackets, backslashes and 1- to 4-byte characters, with lowercase UUID ids,
empty ids and random ids.
"""
import argparse
import json
import random
import sys
import uuid

sys.dont_write_bytecode = True

NAME = 'chat_ref'

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
    let mut parts = line[1..].split(' ');
    let title = unhex(parts.next().unwrap());
    let id = unhex(parts.next().unwrap());
    let r = sol::chat_ref_text(&title, &id);
    let hex: String = r.as_bytes().iter().map(|b| format!("{:02x}", b)).collect();
    writeln!(out, "x{}", hex).unwrap();
  }
}
'''

SPACES = set('\t\n\x0b\x0c\r \xa0\u1680\u2028\u2029\u202f\u205f\u3000\ufeff') | {chr(c) for c in range(0x2000, 0x200b)}
ALPHABET = ['a', 'Z', '0', ' ', '\t', '\n', '\r', '\x0b', '\x0c', '\\', '[', ']', '(', ')', '@', ':', '\x85',
            '\xa0', '\u1680', '\u180e', '\u2000', '\u200a', '\u200b', '\u2028', '\u2029', '\u202f', '\u205f',
            '\u3000', '\ufeff', 'é', '한', '\uffff', '\U0001F600', '\U0010FFFF']


def oracle(title, cid):
    out, i = [], 0
    while i < len(title):
        if title[i] in SPACES:
            j = i
            while j < len(title) and title[j] in SPACES:
                j += 1
            run = title[i:j]
            out.append(' ' if ('\r' in run or '\n' in run) else run)
            i = j
        else:
            out.append('\\' + title[i] if title[i] in '\\[]' else title[i])
            i += 1
    return '@[' + ''.join(out) + '](chat:' + cid + ')'


def cases(n, seed):
    r = random.Random(seed)
    ref = '0f8b2c4e-1a2b-4c3d-8e9f-0123456789ab'
    titles = ['', 'a', '\r', '\n', '\r\n', ' \n ', 'a\nb', 'a \r\n\t b', 'a  b', ' a ', '\t\x0b\x0c',
              '[x]', '\\', 'a\\[b]\\', '@[t](chat:x)', '\x85', 'a\x85b', '\u180e\n\u180e', '\u200b\n',
              '\u2028', '\u2029\n\u2029', '\ufeff\r\ufeff', '\U0001F600\n\U0001F600',
              ''.join(sorted(SPACES)), ''.join(sorted(SPACES - {'\r', '\n'})), 'x' + ''.join(sorted(SPACES)) + 'y']
    rows = [(t, ref) for t in titles] + [('a', ''), ('[a]', '[b]\n'), ('t', '\U0001F600')]
    edges = len(rows)
    for _ in range(n):
        title = ''.join(r.choice(ALPHABET) for _ in range(r.randint(0, r.choice([1, 3, 10, 30, 80]))))
        u = r.random()
        if u < 0.8:
            cid = str(uuid.UUID(int=r.getrandbits(128)))
        elif u < 0.9:
            cid = ''
        else:
            cid = ''.join(r.choice(ALPHABET) for _ in range(r.randint(0, 12)))
        rows.append((title, cid))
    return rows, edges

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--seed', type=int, default=12345)
    ap.add_argument('--n', type=int, default=20000)
    ap.add_argument('--emit', action='store_true',
                    help='only print JSON lines [title, id, oracle] (Node bridge test)')
    args = ap.parse_args()
    if args.n < 0:
        ap.error('--n must be nonnegative')
    if args.emit:
        for t, c in cases(args.n, args.seed)[0]:
            sys.stdout.write(json.dumps([t, c, oracle(t, c)]) + '\n')
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
        summary['line_break_titles'] = sum(('\r' in t or '\n' in t) for t, _ in inputs)
        summary['escaped_titles'] = sum(any(ch in t for ch in '\\[]') for t, _ in inputs)
        summary['non_ascii_space_titles'] = sum(any(ch in SPACES and ch > '~' for ch in t) for t, _ in inputs)
        summary['changed_titles'] = sum(e != '@[' + t + '](chat:' + c + ')' for (t, c), e in zip(inputs, expected))
        node, summary['ts_runtime'] = ts_runtime()
        ts = [json.loads(x) for x in run(node + [HERE / (NAME+'.mjs')],
                                         ''.join(json.dumps({'title': t, 'id': c})+'\n' for t, c in inputs)).split('\n')[:-1]]
        assert len(ts) == len(inputs)
        payload = ''.join('x%s %s\n' % (t.encode().hex(), c.encode().hex()) for t, c in inputs)
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
                            differences.append(dict(compiler_backend=key, case_index=i, title=inp[0], id=inp[1],
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
    differences.sort(key=lambda d: (len(d['title']), d['title'], d['id'], d['compiler_backend']))
    summary.update(status='error' if failed else 'ok', difference_records_total=len(differences),
                   difference_records_saved=min(50, len(differences)),
                   difference_order='title length, title, id, compiler/backend')
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / (NAME+'_summary.json')).write_text(json.dumps(summary, indent=2)+'\n')
    (RESULTS / (NAME+'_differences.jsonl')).write_text(''.join(json.dumps(d)+'\n' for d in differences[:50]))
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
