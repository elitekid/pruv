#!/usr/bin/env python3
"""Cross-check Lair chunkPage and chunkImage (src/documents/chunker.ts), the PDF page and OCR image chunkers.

Each [kind, page, text, max, ocr] goes to Pruv (chunk_page.pruv: chunk_page returns [page, start, end]
records and proves every record carries the page, chunk_image returns byte ranges), to the TypeScript
copy (chunk_page.mjs, run in Lair's Electron when available) and to an independent oracle: the code point
splitter of run_split_text.py (written from the description, not from the TS) plus the draft shape
{loc, text, ocr?} built here. The runner slices the UTF-8 text with the Pruv ranges and attaches the OCR
info the same way the bridge does. Drafts are compared as parsed JSON.
Domain: integer max >= 2, page a safe integer, ocr undefined (null in the JSON line) or
{confidence, blurry}. Inputs: the split_text edge texts and random texts (seed 12345), each with a
random kind, page and OCR info, plus page edges (0, 1, -1, 2^31, +-(2^53 - 1)) and OCR edges.
"""
import argparse
import json
import random
import sys

sys.dont_write_bytecode = True

from run_split_text import cases as split_cases, oracle as split_oracle

NAME = 'chunk_page'

HARNESS = '''#![allow(dead_code, unused_imports)]
#[path = "@SOL@"] mod sol;
use std::io::{self, BufRead, Write};
fn main() {
  let out = io::stdout(); let mut out = out.lock();
  for line in io::stdin().lock().lines() {
    let line = line.unwrap();
    let mut it = line.splitn(4, ' ');
    let kind = it.next().unwrap(); let page: i64 = it.next().unwrap().parse().unwrap();
    let max: i64 = it.next().unwrap().parse().unwrap(); let hex = &it.next().unwrap()[1..];
    let data: Vec<u8> = (0..hex.len()).step_by(2).map(|i| u8::from_str_radix(&hex[i..i+2], 16).unwrap()).collect();
    let s = String::from_utf8(data).unwrap();
    let r = if kind == "p" { sol::chunk_page(page, &s, max) } else { sol::chunk_image(&s, max) };
    let v: Vec<String> = r.iter().map(|x| x.to_string()).collect();
    writeln!(out, "x {}", v.join(" ")).unwrap();
  }
}
'''

SAFE = 2**53 - 1
PAGES = [1, 2, 3, 10, 99, 100, 101, 999, 0, -1, 2**31 - 1, 2**31, 2**32, SAFE, -SAFE]
OCRS = [None, {'confidence': 0, 'blurry': False}, {'confidence': 100, 'blurry': True},
        {'confidence': 87.5, 'blurry': False}, {'confidence': 12.25, 'blurry': True}, {}]


def draft_loc(kind, page):
    return {'kind': 'page', 'page': page} if kind == 'page' else {'kind': 'image'}


def oracle(kind, page, text, mx, ocr):
    drafts = []
    for piece in split_oracle(text, mx):
        d = {'loc': draft_loc(kind, page), 'text': piece}
        if ocr is not None:       # every object is truthy in JS, undefined is not
            d['ocr'] = ocr
        drafts.append(d)
    return drafts


def cases(n, seed):
    texts, split_edges = split_cases(n, seed)
    r = random.Random(seed + 1)
    rows = []
    # Page and OCR edges on a few texts that give zero, one and several pieces.
    for text, mx in [('', 4), ('  ', 4), ('a', 4), ('ab cd ef gh', 4), ('x' * 30 + '\n' + 'y' * 30, 16)]:
        for page in PAGES:
            for ocr in OCRS:
                rows.append(('page', page, text, mx, ocr))
        for ocr in OCRS:
            rows.append(('image', 0, text, mx, ocr))
    edges = len(rows) + split_edges
    for i, (text, mx) in enumerate(texts):
        kind = r.choice(('page', 'image'))
        page = r.choice(PAGES) if r.random() < 0.2 else r.randrange(1, 2000)
        ocr = None if r.random() < 0.5 else {'confidence': r.choice([r.randrange(101), round(r.uniform(0, 100), 2)]),
                                              'blurry': r.random() < 0.5}
        rows.append((kind, page if kind == 'page' else 0, text, mx, ocr))
    return rows, edges


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--seed', type=int, default=12345)
    ap.add_argument('--n', type=int, default=20000)
    ap.add_argument('--emit', action='store_true',
                    help='only print JSON lines [kind, page, text, max, ocr, oracle drafts] (Node bridge test)')
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
        summary['oracle_drafts'] = sum(map(len, expected))
        summary['page_cases'] = sum(row[0] == 'page' for row in inputs)
        summary['image_cases'] = sum(row[0] == 'image' for row in inputs)
        summary['ocr_cases'] = sum(row[4] is not None for row in inputs)
        node, summary['ts_runtime'] = ts_runtime()
        ts = [json.loads(x) for x in run(node + [HERE / (NAME+'.mjs')], ''.join(json.dumps(list(row))+'\n' for row in inputs)).split('\n')[:-1]]
        assert len(ts) == len(inputs)
        payload = ''.join('%s %d %d x%s\n' % (k[0], p, m, t.encode().hex()) for k, p, t, m, o in inputs)
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
                    for (kind, page, t, m, ocr), line in zip(inputs, lines):
                        v = [int(x) for x in line[2:].split()]
                        raw = t.encode()
                        step = 3 if kind == 'page' else 2
                        drafts = []
                        for k in range(0, len(v), step):
                            a, b = v[k + step - 2], v[k + step - 1]
                            loc = {'kind': 'page', 'page': v[k]} if kind == 'page' else {'kind': 'image'}
                            d = {'loc': loc, 'text': raw[a:b].decode()}
                            if ocr is not None:
                                d['ocr'] = ocr
                            drafts.append(d)
                        pruv.append(drafts)
                    for i, (inp, p, s, want) in enumerate(zip(inputs, pruv, ts, expected)):
                        if p != s or p != want:
                            differences.append(dict(compiler_backend=key, case_index=i, kind=inp[0], page=inp[1],
                                                    text=inp[2], max=inp[3], ocr=inp[4], pruv=p, ts=s, expected=want))
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
