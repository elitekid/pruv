#!/usr/bin/env python3
"""Cross-check the integer part of Lair buildIndex (src/documents/search.ts).

Each case is a list of chunk texts. The host tokenizes them with the tokenize oracle (run_tokenize.py), numbers the
distinct token strings of the case by first appearance and sends each chunk's ids to Pruv (index_terms.pruv: the
chunk's distinct ids in order of first appearance with their counts). The host turns those pairs into buildIndex's
terms, lens and count and compares them with the TypeScript copy (index_terms.mjs: verbatim tokenize and buildIndex,
run in Lair's Electron when available). The per-chunk pairs are also compared, in order, with an independent oracle
(collections.Counter for the counts, a reversed walk for the first positions, then a sort), not a copy of the TS
Map loop. avg is a float and stays in the host; it is compared too.
The JSON object from the TS copy holds integer-like keys ("12") first, so terms are compared as dicts, not in key
order. Inputs: no chunks, empty chunks, one repeated word, Hangul bigrams, integer-like tokens, "constructor" and
"tostring" as tokens ("__proto__" tokenizes to "proto"), a 100,000-token chunk, and random corpora of up to 8 chunks drawn from small word pools
(many repeats) and from the tokenize runner's random texts.
"""
import argparse
import collections
import json
import random
import sys

sys.dont_write_bytecode = True

import run_tokenize

NAME = 'index_terms'

HARNESS = '''#![allow(dead_code, unused_imports)]
#[path = "@SOL@"] mod sol;
use std::io::{self, BufRead, Write};
fn main() {
  let out = io::stdout(); let mut out = out.lock();
  for line in io::stdin().lock().lines() {
    let line = line.unwrap();
    let f: Vec<i64> = line.split(' ').skip(1).map(|x| x.parse().unwrap()).collect();
    let n = f[1] as usize;
    let r = sol::index_terms(&f[2..2 + n], f[0]);
    let s: Vec<String> = r.iter().map(|x| x.to_string()).collect();
    writeln!(out, "{}", s.join(" ")).unwrap();
  }
}
'''

WORDS = ['a', 'b', 'ab', 'A', '12', '007', '0', 'constructor', '__proto__', 'toString', 'hasOwnProperty', '한국', '한국어',
         '가나다', '日本', 'Σ', 'σ', 'ς', 'x1', '１２']


def tokens(text):
    return run_tokenize.strings(run_tokenize.oracle(text))


def oracle_pairs(toks):
    """(token, count) pairs in order of first appearance, without a running map of the walk."""
    counts = collections.Counter(toks)
    first = {}
    for k in range(len(toks) - 1, -1, -1):
        first[toks[k]] = k
    return [(t, counts[t]) for t in sorted(counts, key=first.__getitem__)]


def numbering(chunks):
    ids = {}
    for toks in chunks:
        for t in toks:
            if t not in ids:
                ids[t] = len(ids)
    return ids


def assemble(chunk_pairs, lens):
    terms = {}
    for i, pairs in enumerate(chunk_pairs):
        for t, c in pairs:
            terms.setdefault(t, []).extend([i, c])
    n = len(lens)
    return dict(v=1, count=n, avg=max(sum(lens) / n, 1) if n else 1, lens=lens, terms=terms)


def word_text(r):
    return r.choice([' ', ', ', '.', '\n']).join(r.choice(WORDS) for _ in range(r.randrange(0, 30)))


def cases(n, seed):
    rows = [[], [''], ['', ''], ['a'], ['a a a'], ['a', 'a'], ['a b', 'b a'], ['A a'], ['한국어'], ['한국어 한국'],
            ['가가가가'], ['12 12 007 0'], ['12', '7 12'], ['constructor'], ['__proto__ __proto__', 'constructor'],
            ['toString hasOwnProperty valueOf'], ['Σ σ ς ΟΔΟΣ'], ['１２ 12'], ['a ' * 100000],
            ['가' * 50000, '가가'], [w for w in WORDS], ['x'] * 50, [run_tokenize.EDGE[k] for k in range(0, 40)],
            run_tokenize.EDGE[40:]]
    edges = len(rows)
    r = random.Random(seed)
    for _ in range(n):
        k = r.randrange(0, 9)
        if r.random() < 0.6:
            rows.append([word_text(r) for _ in range(k)])
        else:
            rows.append([run_tokenize.rand_text(r) if r.random() < 0.8 else run_tokenize.sigma_text(r) for _ in range(k)])
    return rows, edges


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--seed', type=int, default=12345)
    ap.add_argument('--n', type=int, default=20000)
    ap.add_argument('--emit', action='store_true',
                    help='only print JSON lines [vocab, token string of each id, chunk id lists, oracle flat results per chunk, texts]')
    args = ap.parse_args()
    if args.n < 0:
        ap.error('--n must be nonnegative')
    inputs, edges = cases(args.n, args.seed)
    toks = [[tokens(x) for x in c] for c in inputs]
    ids = [numbering(t) for t in toks]
    expected = [[oracle_pairs(x) for x in t] for t in toks]
    flat_want = [[[len(p)] + [v for tc in p for v in (d[tc[0]], tc[1])] for p in e] for e, d in zip(expected, ids)]
    if args.emit:
        for c, t, d, f in zip(inputs, toks, ids, flat_want):
            sys.stdout.write(json.dumps([max(len(d), 1), list(d), [[d[x] for x in tt] for tt in t], f, c], ensure_ascii=False) + '\n')
        return 0
    from run import HERE, WORK, RESULTS, configure, run
    from run_host_within import portable
    from run_decode_bytes import ts_runtime
    summary = dict(seed=args.seed, random_cases=args.n, runs={})
    differences, failed = [], False
    try:
        g2, summary['tools'] = configure()
        summary['edge_cases'] = edges
        summary['cases'] = len(inputs)
        summary['chunks'] = sum(len(c) for c in inputs)
        summary['oracle_outcomes'] = dict(
            empty_cases=sum(not c for c in inputs), empty_chunks=sum(not x for t in toks for x in t),
            chunks_with_repeats=sum(len(p) < len(x) for e, t in zip(expected, toks) for p, x in zip(e, t)),
            max_tokens=max((len(x) for t in toks for x in t), default=0),
            max_distinct=max((len(p) for e in expected for p in e), default=0),
            max_vocab=max(len(d) for d in ids))
        want = [assemble(e, [len(x) for x in t]) for e, t in zip(expected, toks)]
        node, summary['ts_runtime'] = ts_runtime()
        ts = [json.loads(x) for x in run(node + [HERE / (NAME+'.mjs')],
                                         ''.join(json.dumps(c) + '\n' for c in inputs)).splitlines()]
        assert len(ts) == len(inputs)
        summary['ts_oracle_pass'] = sum(t == w for t, w in zip(ts, want))
        failed |= summary['ts_oracle_pass'] != len(inputs)
        lines, owner = [], []
        for ci, (t, d) in enumerate(zip(toks, ids)):
            for x in t:
                lines.append('x %d %d %s\n' % (max(len(d), 1), len(x), ' '.join(str(d[s]) for s in x)))
                owner.append(ci)
        payload = ''.join(lines).replace(' \n', '\n')
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
                    out = [[int(v) for v in x.split()] for x in run([exe], payload).splitlines()]
                    assert len(out) == len(lines)
                    got = [[] for _ in inputs]
                    for ci, o in zip(owner, out):
                        got[ci].append(o)
                    chunk_pass, ts_pass = 0, 0
                    for i, (g, f, d, t, w) in enumerate(zip(got, flat_want, ids, ts, want)):
                        names = {v: s for s, v in d.items()}
                        built = assemble([[(names[o[1 + 2 * p]], o[2 + 2 * p]) for p in range(o[0])] for o in g],
                                         [len(x) for x in toks[i]])
                        ok_chunks = sum(a == b for a, b in zip(g, f))
                        chunk_pass += ok_chunks
                        ts_pass += built == t
                        if ok_chunks != len(f) or built != t:
                            differences.append(dict(compiler_backend=key, case_index=i, chunks=len(f),
                                                    texts=[x[:200] for x in inputs[i][:8]], pruv=[o[:41] for o in g],
                                                    expected=[o[:41] for o in f], ts_matches=built == t))
                    row.update(cases=len(inputs), chunks=len(lines), pruv_oracle_chunk_pass=chunk_pass,
                               ts_oracle_pass=summary['ts_oracle_pass'], pruv_ts_pass=ts_pass)
                    row['status'] = 'ok' if chunk_pass == len(lines) and ts_pass == len(inputs) else 'wrong'
                    failed |= row['status'] != 'ok'
                    print(key+': '+json.dumps(row), flush=True)
                except Exception as exc:
                    row['error'] = portable(str(exc))
                    failed = True
                    print(key+': '+row['error'], flush=True)
    except Exception as exc:
        summary['error'] = portable(str(exc))
        failed = True
    differences.sort(key=lambda d: (d['chunks'], json.dumps(d['texts'], ensure_ascii=False), d['compiler_backend']))
    summary.update(status='error' if failed else 'ok', difference_records_total=len(differences),
                   difference_records_saved=min(50, len(differences)),
                   difference_order='chunk count, texts, compiler/backend')
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / (NAME+'_summary.json')).write_text(json.dumps(summary, indent=2, ensure_ascii=False)+'\n')
    (RESULTS / (NAME+'_differences.jsonl')).write_text(''.join(json.dumps(d, ensure_ascii=False)+'\n' for d in differences[:50]))
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
