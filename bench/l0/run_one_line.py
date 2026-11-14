#!/usr/bin/env python3
"""Cross-check the one-line label of Lair (oneLine in src/backend/engine-import/tail.ts).

Each (text, max) pair goes to Pruv (one_line.pruv: one pass that folds JS whitespace runs, trims and
counts UTF-16 units), to the TypeScript copy (one_line.mjs, run in Lair's Electron when available) and to
an independent oracle: Python re over the JS whitespace set, strip with the same set, then the first
2*max bytes of the UTF-16LE encoding decoded with surrogatepass (which keeps a lone high surrogate the
way slice does).
Known difference: when slice stops between the halves of a surrogate pair, TS keeps a lone high
surrogate that a Pruv str cannot hold; Pruv stops before the pair. The check counts those cases and
requires Pruv to equal the TS result without its last unit there, and to equal it exactly everywhere else.
Domain: any Unicode text without lone surrogates, max an integer in 0..=10^11. Inputs: edge pairs
(empty and all-whitespace text, every JS whitespace character, look-alikes that JS does not count such
as U+0085, U+180E, U+200B and U+001C, cuts on a folded space and inside a pair, a large max) and random
pairs (seed 12345) mixing whitespace, ASCII, 2-, 3- and 4-byte characters.
"""
import argparse
import json
import re
import random
import sys

sys.dont_write_bytecode = True

NAME = 'one_line'

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
    let max: i64 = parts.next().unwrap().parse().unwrap();
    let r = sol::one_line(&text, max);
    let hex: String = r.as_bytes().iter().map(|b| format!("{:02x}", b)).collect();
    writeln!(out, "x{}", hex).unwrap();
  }
}
'''

JS_WS = ('\t\n\v\f\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a'
         '\u2028\u2029\u202f\u205f\u3000\ufeff')
LOOKALIKE = '\x85\u180e\u200b\x1c\x1f'
ALPHABET = ['a', 'Z', '0', '\x00', 'é', '한', '€', '\U00010000', '\U0001F600', '\U0010FFFF'] + list(JS_WS) + list(LOOKALIKE)
RUN = re.compile('[' + re.escape(JS_WS) + ']+')


def oracle(text, max_):
    folded = RUN.sub(' ', text).strip(JS_WS)
    return folded.encode('utf-16-le', 'surrogatepass')[:2 * max_].decode('utf-16-le', 'surrogatepass')


def split(ts):
    return bool(ts) and 0xd800 <= ord(ts[-1]) <= 0xdbff


def pruv_expected(ts):
    return ts[:-1] if split(ts) else ts


def units(text):
    return len(text.encode('utf-16-le', 'surrogatepass')) // 2


def cases(n, seed):
    r = random.Random(seed)
    E = '\U0001F600'
    rows = [('', 0), ('', 5), (' ', 3), (JS_WS, 10), (JS_WS + 'a' + JS_WS, 10), ('a' + JS_WS + 'b', 3),
            ('a' + JS_WS + 'b', 2), ('a  b', 1), ('a\r\n\tb', 2), (LOOKALIKE, 10), ('a\x85b', 3),
            ('a\u200bb\u180ec', 10), (E, 0), (E, 1), (E, 2), ('a ' + E, 3), ('a ' + E, 4), (' ' + E + ' ', 1),
            ('\ufeffx\ufeff', 5), ('x\u3000\u3000y', 3), ('abc', 100_000_000_000),
            ((E + '\n') * 10, 100_000_000_000), ('a' * 300 + ' ' + E, 302), ('a' * 300 + ' ' + E, 303),
            ('한 글', 2)]
    rows += [('a' + ch + 'b', 3) for ch in JS_WS + LOOKALIKE]
    edges = len(rows)
    for _ in range(n):
        u = r.random()
        if u < 0.5:
            pool = [r.choice(ALPHABET), r.choice(JS_WS), r.choice(ALPHABET), '\U0001F600', ' ']
        else:
            pool = ALPHABET
        text = ''.join(r.choice(pool) for _ in range(r.randint(0, r.choice([2, 8, 30, 120]))))
        m = units(RUN.sub(' ', text).strip(JS_WS))
        v = r.random()
        if v < 0.4:
            max_ = max(0, m + r.randint(-3, 1))
        elif v < 0.85:
            max_ = r.randint(0, max(0, m))
        else:
            max_ = r.choice([0, m + r.randint(1, 50), 100_000_000_000])
        rows.append((text, max_))
    return rows, edges


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--seed', type=int, default=12345)
    ap.add_argument('--n', type=int, default=20000)
    ap.add_argument('--emit', action='store_true',
                    help='only print JSON lines [text, max, ts oracle, pruv oracle] (Node bridge test)')
    args = ap.parse_args()
    if args.n < 0:
        ap.error('--n must be nonnegative')
    if args.emit:
        for text, max_ in cases(args.n, args.seed)[0]:
            want = oracle(text, max_)
            sys.stdout.write(json.dumps([text, max_, want, pruv_expected(want)]) + '\n')
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
        summary['folded_cases'] = sum(RUN.sub(' ', t).strip(JS_WS) != t for t, c in inputs)
        summary['cut_cases'] = sum(units(e) < units(RUN.sub(' ', t).strip(JS_WS)) for e, (t, c) in zip(expected, inputs))
        summary['split_pair_cases'] = sum(split(e) for e in expected)
        summary['astral_cases'] = sum(any(ord(ch) > 0xffff for ch in t) for t, c in inputs)
        summary['lookalike_cases'] = sum(any(ch in LOOKALIKE for ch in t) for t, c in inputs)
        pruv_want = [pruv_expected(e) for e in expected]
        node, summary['ts_runtime'] = ts_runtime()
        ts = [json.loads(x) for x in run(node + [HERE / (NAME+'.mjs')],
                                         ''.join(json.dumps({'text': t, 'max': c})+'\n'
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
                    pruv = [bytes.fromhex(line[1:]).decode() for line in lines]
                    for i, ((t, c), p, s, want, pw) in enumerate(zip(inputs, pruv, ts, expected, pruv_want)):
                        if s != want or p != pw:
                            differences.append(dict(compiler_backend=key, case_index=i, text=t, max=c,
                                                    pruv=p, ts=s, expected=want, pruv_expected=pw))
                    row.update(cases=len(inputs), pruv_oracle_pass=sum(p == w for p, w in zip(pruv, pruv_want)),
                               ts_oracle_pass=sum(t == w for t, w in zip(ts, expected)),
                               pruv_ts_pass=sum(p == pruv_expected(t) for p, t in zip(pruv, ts)),
                               pruv_ts_exact=sum(p == t for p, t in zip(pruv, ts)))
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
    differences.sort(key=lambda d: (len(d['text']), d['text'], d['max'], d['compiler_backend']))
    summary.update(status='error' if failed else 'ok', difference_records_total=len(differences),
                   difference_records_saved=min(50, len(differences)),
                   difference_order='text length, text, max, compiler/backend')
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / (NAME+'_summary.json')).write_text(json.dumps(summary, indent=2)+'\n')
    (RESULTS / (NAME+'_differences.jsonl')).write_text(''.join(json.dumps(d)+'\n' for d in differences[:50]))
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
