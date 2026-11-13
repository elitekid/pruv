#!/usr/bin/env python3
"""Cross-check Lair extensionOf and kindOf (src/documents/kinds.ts).

Each file name goes to Pruv (kind_of.pruv: kind_of gives the kind code, extension_at the UTF-16 index of
the extension text, both proved in range), to the TypeScript copy (kind_of.mjs, run in Lair's Electron
when available) and to an independent oracle that splits with re.split, finds the dot with str.rfind,
lowercases with Python str.lower and looks the extension up in the three word sets.
The bridge glue name.slice(at).toLowerCase() is run in the same JS runtime with the oracle's index and
must equal the TS extensionOf.
Inputs: empty names, every word in every case, the Kelvin sign for k, U+0130, dotfiles, trailing dots,
several dots, '/' and '\\' paths with dots in folders, Hangul, emoji, words with extra letters, and
extensions longer than any word.
"""
import argparse
import json
import random
import re
import sys

sys.dont_write_bytecode = True

NAME = 'kind_of'
KINDS = ['unknown', 'pdf', 'docx', 'xlsx', 'csv', 'image', 'text', 'unsupported']
IMAGE = 'png jpg jpeg webp gif bmp tif tiff'.split()
TEXT = ('txt md markdown log json jsonl yaml yml xml html htm css ini toml cfg conf env rst tex srt vtt '
        'js mjs cjs ts tsx jsx py rb go rs java kt swift c h cc cpp hpp cs php sh bat ps1 sql svg').split()
UNSUPPORTED = 'pptx ppt hwp hwpx doc xls odt ods odp rtf pages numbers key zip epub'.split()
WORDS = ['pdf', 'docx', 'xlsx', 'csv', 'tsv'] + IMAGE + TEXT + UNSUPPORTED

HARNESS = '''#![allow(dead_code, unused_imports)]
#[path = "@SOL@"] mod sol;
use std::io::{self, BufRead, Write};
fn main() {
  let out = io::stdout(); let mut out = out.lock();
  for line in io::stdin().lock().lines() {
    let line = line.unwrap();
    let hex = &line[1..];
    let data: Vec<u8> = (0..hex.len()).step_by(2).map(|i| u8::from_str_radix(&hex[i..i+2], 16).unwrap()).collect();
    let s = String::from_utf8(data).unwrap();
    writeln!(out, "x {} {}", sol::kind_of(&s), sol::extension_at(&s)).unwrap();
  }
}
'''


def units(s):
    return len(s.encode('utf-16-le')) // 2


def oracle(name):
    """(UTF-16 index of the extension or -1, extensionOf, kindOf)."""
    base = re.split(r'[\\/]', name)[-1]
    dot = base.rfind('.')
    if dot <= 0:
        return -1, '', 'unknown'
    raw = base[dot + 1:]
    ext = raw.lower()
    kind = ('pdf' if ext == 'pdf' else 'docx' if ext == 'docx' else 'xlsx' if ext == 'xlsx'
            else 'csv' if ext in ('csv', 'tsv') else 'image' if ext in IMAGE else 'text' if ext in TEXT
            else 'unsupported' if ext in UNSUPPORTED else 'unknown')
    return units(name) - units(raw), ext, kind


ODD = ['\u212a', '\u0130', 'İ', 'ı', 'ß', 'Σ', 'ς', '한', '글', '😀', '\u0307', 'é', 'E\u0301', '\u00a0', ' ', '\t', '\ufeff']


def cased(r, w):
    out = ''
    for ch in w:
        if ch == 'k' and r.randrange(3) == 0:
            out += '\u212a'
        else:
            out += ch.upper() if r.randrange(2) else ch
    return out


def rand_name(r):
    parts = []
    for _ in range(r.choice([0, 0, 1, 2, 4])):
        folder = r.choice(['dir', 'a.b', '.git', 'x.pdf', '한글', '', '..', '.']) + r.choice(['', '.png', ''])
        parts.append(folder + r.choice(['/', '\\']))
    stem = r.choice(['', 'a', 'file', 'report.final', '.hidden', 'x..y', '사진', '😀', '.', '..', 'name.' + r.choice(WORDS)])
    ext = r.choice(WORDS)
    kind = r.randrange(8)
    if kind == 0:
        ext = cased(r, ext)
    elif kind == 1:
        ext = ext + r.choice(['x', 's', '1', '.', '/', ' ', ''])
    elif kind == 2:
        pos = r.randrange(len(ext) + 1)
        ext = ext[:pos] + r.choice(ODD) + ext[pos:]
    elif kind == 3:
        ext = ''.join(r.choice('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_') for _ in range(r.randrange(0, 14)))
    elif kind == 4:
        ext = ''.join(r.choice(ODD + list('akpdfxlsmt')) for _ in range(r.randrange(1, 10)))
    sep = r.choice(['.', '.', '.', '', '..'])
    return ''.join(parts) + stem + sep + ext


def cases(n, seed):
    rows = ['', '.', '..', '...', 'a.', '.pdf', '..pdf', 'a.pdf', 'A.PDF', 'a/b.pdf', 'a\\b.pdf', 'a.pdf/', 'a.pdf\\',
            'x.pdf/README', 'dir.txt/file', 'C:\\Users\\x\\a.Docx', '/abs/path/.env', 'a/.env', 'a.ENV', 'a.b.c.tiff',
            'a.\u212aEY', 'a.\u212at', 'a.K\u212a', 'a.\u0130ni', 'a.ini\u0307', 'a.pdf ', ' a.pdf', 'a.pdf\u00a0',
            'a.markdown', 'a.markdowns', 'a.numbers', 'a.numberz', 'a.jsonl', 'a.json.', '사진.JPG', '😀.png', 'a.😀',
            'a.ps1', 'a.PS1', 'a.c', 'a.C', 'a.h', 'a.H', 'a.cs', 'a.cc', 'a.abcdefgh', 'a.abcdefghi', 'a.' + 'x' * 100,
            'a' * 1000 + '.txt', '/' * 5, '\\', 'a\\', 'a.b\\c', 'a.b/c.', 'a./b']
    for w in WORDS:
        rows += ['f.' + w, 'f.' + w.upper(), 'f.' + w.capitalize(), w, '.' + w, 'f.' + w + 'x', 'f.x' + w]
        if 'k' in w:
            rows.append('f.' + w.replace('k', '\u212a'))
    edges = len(rows)
    r = random.Random(seed)
    rows += [rand_name(r) for _ in range(n)]
    return rows, edges


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--seed', type=int, default=12345)
    ap.add_argument('--n', type=int, default=20000)
    ap.add_argument('--emit', action='store_true', help='only print JSON lines [name, at, extension, kind]')
    args = ap.parse_args()
    if args.n < 0:
        ap.error('--n must be nonnegative')
    if args.emit:
        for c in cases(args.n, args.seed)[0]:
            sys.stdout.write(json.dumps([c, *oracle(c)]) + '\n')
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
        expected = [oracle(c) for c in inputs]
        summary['oracle_kinds'] = {k: sum(1 for e in expected if e[2] == k) for k in KINDS}
        node, summary['ts_runtime'] = ts_runtime()
        ts = [json.loads(x) for x in run(node + [HERE / (NAME+'.mjs')], ''.join(json.dumps([c, e[0]])+'\n' for c, e in zip(inputs, expected))).splitlines()]
        assert len(ts) == len(inputs)
        summary['ts_oracle_pass'] = sum(t[0] == e[1] and t[1] == e[2] for t, e in zip(ts, expected))
        summary['glue_ts_pass'] = sum(t[2] == t[0] for t in ts)
        failed |= summary['glue_ts_pass'] != len(inputs)
        payload = ''.join('h' + c.encode().hex() + '\n' for c in inputs)
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
                    pruv = [tuple(int(x) for x in line.split()[1:]) for line in run([exe], payload).splitlines()]
                    assert len(pruv) == len(inputs)
                    ok = 0
                    for i, (c, p, t, e) in enumerate(zip(inputs, pruv, ts, expected)):
                        good = KINDS[p[0]] == e[2] and p[1] == e[0]
                        ok += good
                        if not good or KINDS[p[0]] != t[1] or t[0] != e[1]:
                            differences.append(dict(compiler_backend=key, case_index=i, input=c[:120], pruv=[KINDS[p[0]], p[1]],
                                                    ts=t[:2], expected=[e[2], e[0], e[1]]))
                    row.update(cases=len(inputs), pruv_oracle_pass=ok, ts_oracle_pass=summary['ts_oracle_pass'],
                               pruv_ts_kind_pass=sum(KINDS[p[0]] == t[1] for p, t in zip(pruv, ts)))
                    row['status'] = 'ok' if ok == len(inputs) else 'wrong'
                    failed |= row['status'] != 'ok'
                    print(key+': '+json.dumps(row), flush=True)
                except Exception as exc:
                    row['error'] = portable(str(exc))
                    failed = True
                    print(key+': '+row['error'], flush=True)
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
