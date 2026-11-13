#!/usr/bin/env python3
"""Shared G2 cross-check machinery for the second bundle."""
import argparse
import json
import random
import re
import sys

sys.dont_write_bytecode = True
from run import HERE, WORK, RESULTS, configure, run
from run_host_within import portable


def version_oracle(pair):
    parts = [s.strip(' \t\n\v\f\r') for s in pair]
    if not all(re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', s) for s in parts):
        return False
    return tuple(map(int, parts[0].split('.'))) >= tuple(map(int, parts[1].split('.')))


def col_oracle(col):
    # Locate the length block, then use ordinary base-26 digits within it.
    width, block = 0, 1
    while col >= block:
        col -= block
        width += 1
        block *= 26
    return ''.join(chr(65 + col // 26**i % 26) for i in reversed(range(width)))


def cases(name, n, seed):
    r = random.Random(seed)
    if name == 'col_letters':
        rows = list(range(100001))
        rows += [26**k + d for k in range(1, 11) for d in range(-3, 4)
                 if 0 <= 26**k+d <= 10**15]
        rows += [10**15-1, 10**15]
        edges = len(rows)
        rows += [r.randrange(10**15+1) for _ in range(n)]
        return rows, edges
    pool = ['', '0.0.0', '1.2.3', '0001.02.003', '.1.2', '1..2', '1.2.',
            '1.2.3.4', '+1.2.3', '-1.2.3', '١.2.3', '１.2.3', '1.2.3x',
            '9'*4092+'.0.0', '0'*4092+'.0.0']
    pool += [str(2**53+d)+'.0.0' for d in range(-3, 5)]
    pool += [w+'0.0.0'+w for w in ['\t', '\n', '\v', '\f', '\r', ' ', '\u00a0', '\ufeff', '\u2028', '\u3000']]
    rows = [[a, b] for a in pool for b in pool]
    edges = len(rows)
    for _ in range(n):
        a = '.'.join('0'*r.randrange(5)+str(r.choice([r.randrange(100), 2**53+r.randrange(-20, 20), r.randrange(10**80)])) for _ in range(3))
        b = r.choice([a, '.'.join(str(r.randrange(100)) for _ in range(3)), r.choice(pool)])
        mode = r.randrange(5)
        if mode == 0:
            a = r.choice(['\u00a0', '\ufeff', '\u2028', '\u3000'])+a
        elif mode == 1:
            a = ''.join(r.choice('012xyz.+- \t١😀') for _ in range(r.randrange(30)))
        elif mode == 2:
            a = ' \t\r'+a+'\v\f\n'
        elif mode == 3:
            x = 2**53+r.randrange(-20, 20)
            a, b = str(x)+'.0.0', str(x+1)+'.0.0'
        rows.append([a, b])
    return rows, edges


def main(name):
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
        inputs, summary['edge_cases'] = cases(name, args.n, args.seed)
        summary['cases'] = len(inputs)
        oracle = version_oracle if name == 'version_at_least' else col_oracle
        expected = list(map(oracle, inputs))
        ts = [json.loads(x) for x in run(['node', HERE / (name+'.mjs')], ''.join(json.dumps(x)+'\n' for x in inputs)).splitlines()]
        assert len(ts) == len(inputs)
        if name == 'version_at_least':
            assert all(len(s.encode()) <= 4096 for pair in inputs for s in pair)
            payload = ''.join(' '.join(s.encode().hex() for s in pair)+'\n' for pair in inputs)
            body = 'let (a,b) = line.split_once(" ").unwrap(); println!("{}", sol::version_at_least(&decode(a), &decode(b)));'
        else:
            payload = ''.join(str(x)+'\n' for x in inputs)
            body = 'println!("{}", sol::col_letters(line.parse().unwrap()));'
        harness_text = '''#![allow(dead_code, unused_imports)]
#[path = "@SOL@"] mod sol;
use std::io::{self, BufRead};
fn decode(s: &str) -> String { String::from_utf8((0..s.len()).step_by(2).map(|i| u8::from_str_radix(&s[i..i+2],16).unwrap()).collect()).unwrap() }
fn main() { for line in io::stdin().lock().lines() { let line = line.unwrap(); @BODY@ } }
'''.replace('@BODY@', body)
        for compiler in ('py', 'rs'):
            for backend in ('rust', 'llvm'):
                key = compiler+'/'+backend
                row = summary['runs'][key] = dict(status='error')
                try:
                    work = WORK / (name+'_'+compiler+'_'+backend)
                    work.mkdir(exist_ok=True)
                    compiled = g2.compile_pruv(compiler, str(HERE / (name+'.pruv')), str(work), backend)
                    row['verification'] = portable(compiled)
                    if compiled['rc'] != 0:
                        raise RuntimeError(json.dumps(portable(compiled)))
                    harness = work / 'main.rs'
                    harness.write_text(harness_text.replace('@SOL@', compiled['rs']))
                    extra = []
                    if compiled['ll']:
                        extra, error = g2.build_llvm_objects(compiled['ll'], name, str(work))
                        if error:
                            raise RuntimeError(error)
                    exe = work / 'runner'
                    run([g2.RUSTC, '-O', '--edition', '2021', '-C', 'target-cpu=native', harness, '-o', exe]+extra)
                    lines = run([exe], payload).splitlines()
                    assert len(lines) == len(inputs)
                    pruv = [x == 'true' for x in lines] if name == 'version_at_least' else lines
                    if name == 'version_at_least':
                        assert all(x in ('true', 'false') for x in lines)
                    counts = dict(equal=0, unicode_whitespace=0, number_precision=0, other=0)
                    for i, (c, p, t, want) in enumerate(zip(inputs, pruv, ts, expected)):
                        category = 'equal' if t == want else 'other'
                        if t != want and name == 'version_at_least':
                            category = 'unicode_whitespace' if any(s.strip() != s.strip(' \t\n\v\f\r') or '\ufeff' in s for s in c) else 'number_precision'
                        counts[category] += 1
                        if p != t or p != want:
                            differences.append(dict(compiler_backend=key, case_index=i, input=c,
                                input_bytes=sum(len(s.encode()) for s in c) if isinstance(c,list) else len(str(c)),
                                classification=category, pruv=p, ts=t, expected=want))
                    row.update(cases=len(inputs), pruv_oracle_pass=sum(p == w for p,w in zip(pruv,expected)),
                               ts_oracle_pass=sum(t == w for t,w in zip(ts,expected)), counts=counts)
                    row['status'] = 'ok' if row['pruv_oracle_pass'] == len(inputs) else 'wrong'
                    failed |= row['status'] != 'ok'
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
                   difference_records_saved=min(50,len(differences)),
                   difference_order='input bytes, serialized input, compiler/backend')
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / (name+'_summary.json')).write_text(json.dumps(summary, indent=2)+'\n')
    (RESULTS / (name+'_differences.jsonl')).write_text(''.join(json.dumps(d)+'\n' for d in differences[:50]))
    return int(failed)
