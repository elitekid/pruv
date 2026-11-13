#!/usr/bin/env python3
"""Cross-check Lair under (src/documents/archive.ts).

Each (path, root) pair goes to Pruv (under_root.pruv: byte prefix check with the separator passed in,
result proved equal to the specification), to the TypeScript copy (under_root.mjs, run in Lair's Electron
when available, with that platform's node:path sep) and to an independent oracle, a regular expression
over code points ("root, then sep unless root already ends with it, then anything"), not by copying the TS.
Pruv is checked with both separators, "/" (POSIX) and "\\" (Windows); the TS copy only with its own.
Inputs: empty paths and roots, roots ending in a separator, doubled and mixed separators, sibling names that
share a prefix ("/ab" under "/a"), non-ASCII names, and random paths built from a small alphabet.
"""
import argparse
import json
import os
import random
import re
import sys

sys.dont_write_bytecode = True

NAME = 'under_root'
SEPS = ('/', '\\')

HARNESS = '''#![allow(dead_code, unused_imports)]
#[path = "@SOL@"] mod sol;
use std::io::{self, BufRead, Write};
fn decode(hex: &str) -> String {
    let hex = &hex[1..];
    String::from_utf8((0..hex.len()).step_by(2)
        .map(|i| u8::from_str_radix(&hex[i..i+2], 16).unwrap()).collect()).unwrap()
}
fn main() {
  let out = io::stdout(); let mut out = out.lock();
  for line in io::stdin().lock().lines() {
    let line = line.unwrap();
    let f: Vec<&str> = line.split(' ').collect();
    let (path, root) = (decode(f[0]), decode(f[1]));
    writeln!(out, "{} {}", sol::under(&path, &root, 47), sol::under(&path, &root, 92)).unwrap();
  }
}
'''


def oracle(path, root, sep):
    tail = '' if root[-1:] == sep else re.escape(sep)
    return path == root or re.fullmatch(re.escape(root) + tail + '.*', path, re.S) is not None


def cases(n, seed):
    rows = [('', ''), ('/', ''), ('a', ''), ('\\', ''), ('', '/'), ('/', '/'), ('/a', '/'), ('/a', '/a'),
            ('/a/', '/a'), ('/a/b', '/a'), ('/ab', '/a'), ('/a', '/a/'), ('/a/', '/a/'), ('/a/b', '/a/'),
            ('/a//b', '/a'), ('/a//', '/a/'), ('/a\\b', '/a'), ('C:\\x', 'C:\\'), ('C:\\x\\y', 'C:\\x'),
            ('C:\\xy', 'C:\\x'), ('C:/x', 'C:\\'), ('/tmp/é/1', '/tmp/é'), ('/tmp/éx', '/tmp/é'),
            ('/가/나', '/가'), ('/😀/x', '/😀'), ('/😀x', '/😀'), ('/a', '/a/b'), ('/b/a', '/a'),
            ('/A/b', '/a'), ('a/b', 'a'), ('/a/b/c/d/e', '/a/b'), ('x' * 4096 + '/y', 'x' * 4096)]
    edges = len(rows)
    r = random.Random(seed)
    alphabet = ['/', '\\', 'a', 'b', '.', 'é', '가', '😀', ':', ' ']
    word = lambda k: ''.join(r.choice(alphabet) for _ in range(k))
    for _ in range(n):
        root = word(r.randrange(0, 7))
        sep = r.choice(SEPS)
        path = r.choice([
            lambda: root, lambda: root + sep + word(r.randrange(0, 4)), lambda: root + word(r.randrange(1, 4)),
            lambda: root + sep, lambda: root[:-1], lambda: word(r.randrange(0, 8)),
            lambda: root[:r.randrange(len(root) + 1)] + r.choice(alphabet) + root[r.randrange(len(root) + 1):],
            lambda: root + sep + sep + word(r.randrange(0, 3))])()
        rows.append((path, root))
    return rows, edges


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--seed', type=int, default=12345)
    ap.add_argument('--n', type=int, default=20000)
    ap.add_argument('--emit', action='store_true',
                    help='only print JSON lines [path, root, oracle with "/", oracle with "\\\\"]')
    args = ap.parse_args()
    if args.n < 0:
        ap.error('--n must be nonnegative')
    if args.emit:
        for p, q in cases(args.n, args.seed)[0]:
            sys.stdout.write(json.dumps([p, q] + [oracle(p, q, s) for s in SEPS]) + '\n')
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
        expected = [[oracle(p, q, s) for s in SEPS] for p, q in inputs]
        summary['oracle_outcomes'] = dict(
            under_slash=sum(e[0] for e in expected), under_backslash=sum(e[1] for e in expected),
            equal=sum(p == q for p, q in inputs), non_ascii=sum(not (p + q).isascii() for p, q in inputs),
            max_path_bytes=max(len(p.encode()) for p, _ in inputs))
        node, summary['ts_runtime'] = ts_runtime()
        summary['ts_sep'] = os.sep
        ts_col = SEPS.index(os.sep)
        ts = [json.loads(x) for x in run(node + [HERE / (NAME+'.mjs')],
                                         ''.join(json.dumps([p, q])+'\n' for p, q in inputs)).splitlines()]
        assert len(ts) == len(inputs)
        summary['ts_oracle_pass'] = sum(t == e[ts_col] for t, e in zip(ts, expected))
        failed |= summary['ts_oracle_pass'] != len(inputs)
        payload = ''.join('x%s x%s\n' % (p.encode().hex(), q.encode().hex()) for p, q in inputs)
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
                    pruv = [[x == 'true' for x in line.split(' ')] for line in run([exe], payload).splitlines()]
                    assert len(pruv) == len(inputs)
                    for i, ((p, q), got, t, want) in enumerate(zip(inputs, pruv, ts, expected)):
                        if got != want or got[ts_col] != t:
                            differences.append(dict(compiler_backend=key, case_index=i, path=p, root=q,
                                                    path_hex=p.encode().hex(), root_hex=q.encode().hex(),
                                                    pruv=got, ts=t, expected=want))
                    row.update(cases=len(inputs),
                               pruv_oracle_pass_slash=sum(g[0] == w[0] for g, w in zip(pruv, expected)),
                               pruv_oracle_pass_backslash=sum(g[1] == w[1] for g, w in zip(pruv, expected)),
                               ts_oracle_pass=summary['ts_oracle_pass'],
                               pruv_ts_pass=sum(g[ts_col] == t for g, t in zip(pruv, ts)))
                    row['status'] = 'ok' if (row['pruv_oracle_pass_slash'] == row['pruv_oracle_pass_backslash']
                                             == row['pruv_ts_pass'] == len(inputs)) else 'wrong'
                    failed |= row['status'] != 'ok'
                    print(key+': '+json.dumps(row), flush=True)
                except Exception as exc:
                    row['error'] = portable(str(exc))
                    failed = True
                    print(key+': '+row['error'], flush=True)
    except Exception as exc:
        summary['error'] = portable(str(exc))
        failed = True
    differences.sort(key=lambda d: (len(d['path_hex']) + len(d['root_hex']), d['path_hex'], d['root_hex'],
                                    d['compiler_backend']))
    summary.update(status='error' if failed else 'ok', difference_records_total=len(differences),
                   difference_records_saved=min(50, len(differences)),
                   difference_order='input bytes, path hex, root hex, compiler/backend')
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / (NAME+'_summary.json')).write_text(json.dumps(summary, indent=2, ensure_ascii=False)+'\n')
    (RESULTS / (NAME+'_differences.jsonl')).write_text(''.join(json.dumps(d, ensure_ascii=False)+'\n' for d in differences[:50]))
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
