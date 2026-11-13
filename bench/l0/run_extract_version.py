#!/usr/bin/env python3
"""Cross-check the extraction version key (Lair src/documents/versions.ts: sha256, extractVersionOf).

Each case is either a string to hash (sha256 of its UTF-8 bytes) or a (sourceVersion, kind, variant) triple
for extractVersionOf, some with variant left out so the TS default '' is used. Every case goes to Pruv
(extract_version.pruv: SHA-256 written out with integer arithmetic, no bit operators), to the TypeScript copy
(extract_version.mjs, node:crypto, run in Lair's Electron when available) and to an independent oracle:
Python hashlib over the UTF-8 bytes, with the extractor version text rebuilt here from the part list.
Domain: well-formed strings (no lone surrogates).
Inputs: the FIPS 180-4 examples, texts of every UTF-8 length 0..300 (each padding case: length mod 64 =
55, 56, 63, 0 ...), Korean, accents, emoji, NUL and newlines, texts up to 1 MiB, and triples whose message
length sweeps all 64 residues, with real-looking source versions (64 hex), kinds and variants.
"""
import argparse
import hashlib
import json
import random
import sys

sys.dont_write_bytecode = True

NAME = 'extract_version'

PARTS = [('rev', '2'), ('pdfjs', '6.3.289'), ('tesseract', '7.0.0'), ('', 'kor+eng 4.0.0_best_int'),
         ('mammoth', '1.13.0'), ('rxl', '9.3.10'), ('papaparse', '5.7.0'), ('chunk', '1500'), ('scan', '100')]
EXTRACTOR = ';'.join(a + b for a, b in PARTS)

HARNESS = '''#![allow(dead_code, unused_imports)]
#[path = "@SOL@"] mod sol;
use std::io::{self, BufRead, Write};
fn unhex(h: &str) -> String {
  let buf: Vec<u8> = h.as_bytes().chunks(2).map(|p| u8::from_str_radix(std::str::from_utf8(p).unwrap(), 16).unwrap()).collect();
  String::from_utf8(buf).unwrap()
}
fn main() {
  let out = io::stdout(); let mut out = out.lock();
  for line in io::stdin().lock().lines() {
    let line = line.unwrap();
    let parts: Vec<String> = line[1..].split(',').map(unhex).collect();
    let r = if line.starts_with('s') { sol::sha256_hex(&parts[0]) }
            else { sol::extract_version_of(&parts[0], &parts[1], &parts[2]) };
    writeln!(out, "{}", r).unwrap();
  }
}
'''


def oracle(case):
    if case[0] == 's':
        data = case[1]
    else:
        data = '\n'.join([case[1], case[2], case[3] if case[3] is not None else '', EXTRACTOR])
    return hashlib.sha256(data.encode('utf-8')).hexdigest()


def message_bytes(case):
    if case[0] == 's':
        return len(case[1].encode())
    return len('\n'.join([case[1], case[2], case[3] or '', EXTRACTOR]).encode())


CHARS = ['a', 'Z', '0', ' ', '\n', '\t', '\0', '표', '한', 'é', '…', '�', '\U0001f600', ' ', ';', ',', '\\', '"']
KINDS = ['pdf', 'docx', 'txt', 'csv', 'tsv', 'xlsx', 'md', 'image', '', 'PDF']
VARIANTS = [None, '', '\t', ',', 'Sheet1', '시트 1', 'report.xlsx', 'ocr', 'a\nb']


def text(r, n):
    return ''.join(r.choice(CHARS) for _ in range(n))


def utf8_len_text(r, n):
    """A string whose UTF-8 encoding is exactly n bytes."""
    out, left = [], n
    while left > 0:
        c = r.choice(CHARS)
        b = len(c.encode())
        if b <= left:
            out.append(c)
            left -= b
    return ''.join(out)


def hex64(r):
    return ''.join(r.choice('0123456789abcdef') for _ in range(64))


def edge_cases():
    r = random.Random(7)
    rows = [('s', ''), ('s', 'abc'), ('s', 'abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq'),
            ('s', 'abcdefghbcdefghicdefghijdefghijkefghijklfghijklmghijklmnhijklmnoijklmnopjklmnopqklmnopqrlmnopqrsmnopqrstnopqrstu'),
            ('s', 'a' * 1000000), ('s', '표' * 300000), ('s', '\U0001f600' * 200000), ('s', '\0' * 64)]
    for n in range(0, 301):
        rows.append(('s', 'x' * n))
        rows.append(('s', utf8_len_text(r, n)))
    for n in range(0, 140):   # the message length steps through every residue mod 64 twice
        rows.append(('e', 'v' * n, '', ''))
        rows.append(('e', hex64(r), 'k' * (n % 70), None))
    for kind in KINDS:
        for variant in VARIANTS:
            rows.append(('e', hex64(r), kind, variant))
    rows += [('e', '', '', None), ('e', '', '', ''), ('e', '표' * 50, 'csv', '\t'), ('e', '\U0001f600', '😀', '😀'),
             ('e', 'x' * 100000, 'pdf', 'y' * 50000), ('e', EXTRACTOR, EXTRACTOR, EXTRACTOR)]
    return rows


def rand_case(r):
    kind = r.randrange(5)
    if kind == 0:
        return ('s', text(r, r.randrange(0, 200)))
    if kind == 1:
        return ('s', utf8_len_text(r, r.choice([55, 56, 63, 64, 119, 120, 127, 128]) + 64 * r.randrange(0, 4)))
    if kind == 2:
        return ('s', text(r, r.randrange(200, 5000)))
    if kind == 3:
        return ('e', hex64(r), r.choice(KINDS), r.choice(VARIANTS))
    return ('e', text(r, r.randrange(0, 150)), text(r, r.randrange(0, 20)), r.choice([None, text(r, r.randrange(0, 40))]))


def cases(n, seed):
    rows = edge_cases()
    edges = len(rows)
    r = random.Random(seed)
    for _ in range(n):
        rows.append(rand_case(r))
    for c in rows:
        for part in c[1:]:
            if part is not None:
                part.encode('utf-8')   # well-formed: raises on a lone surrogate
    return rows, edges


def ts_line(c):
    if c[0] == 's':
        return json.dumps(dict(f='sha256', text=c[1]))
    q = dict(f='extract', source=c[1], kind=c[2])
    if c[3] is not None:
        q['variant'] = c[3]
    return json.dumps(q)


def harness_line(c):
    if c[0] == 's':
        return 's' + c[1].encode().hex()
    return 'e' + ','.join((p or '').encode().hex() for p in c[1:])


def brief(c):
    return dict(f=c[0], bytes=message_bytes(c), parts=[(p[:60] if p is not None else None) for p in c[1:]])


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--seed', type=int, default=12345)
    ap.add_argument('--n', type=int, default=20000)
    ap.add_argument('--emit', action='store_true', help='only print JSON lines [case, oracle]')
    args = ap.parse_args()
    if args.n < 0:
        ap.error('--n must be nonnegative')
    if args.emit:
        for c in cases(args.n, args.seed)[0]:
            sys.stdout.write(json.dumps([list(c), oracle(c)]) + '\n')
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
        want = [oracle(c) for c in inputs]
        sizes = [message_bytes(c) for c in inputs]
        summary['oracle_outcomes'] = dict(
            sha256=sum(1 for c in inputs if c[0] == 's'),
            extract_version_of=sum(1 for c in inputs if c[0] == 'e'),
            extract_default_variant=sum(1 for c in inputs if c[0] == 'e' and c[3] is None),
            residues_mod_64_covered=len({s % 64 for s in sizes}),
            two_block_padding=sum(1 for s in sizes if s % 64 >= 56),
            max_message_bytes=max(sizes),
            distinct_digests=len(set(want)))
        node, summary['ts_runtime'] = ts_runtime()
        ts = [json.loads(x) for x in run(node + [HERE / (NAME+'.mjs')], ''.join(ts_line(c)+'\n' for c in inputs)).split('\n')[:-1]]
        assert len(ts) == len(inputs)
        summary['ts_oracle_pass'] = sum(t == w for t, w in zip(ts, want))
        payload = ''.join(harness_line(c) + '\n' for c in inputs)
        for compiler in ('py', 'rs'):
            for backend in ('rust', 'llvm'):
                key = compiler+'/'+backend
                row_ = summary['runs'][key] = dict(status='error')
                try:
                    work = WORK / (NAME+'_'+compiler+'_'+backend)
                    work.mkdir(exist_ok=True)
                    compiled = g2.compile_pruv(compiler, str(HERE / (NAME+'.pruv')), str(work), backend)
                    row_['verification'] = portable(compiled)
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
                    pruv = run([exe], payload).splitlines()
                    assert len(pruv) == len(inputs)
                    for i, (c, p, t, w) in enumerate(zip(inputs, pruv, ts, want)):
                        if p != t or p != w:
                            differences.append(dict(compiler_backend=key, case_index=i, input=brief(c), pruv=p, ts=t, expected=w))
                    row_.update(cases=len(inputs), pruv_oracle_pass=sum(p == w for p, w in zip(pruv, want)),
                                ts_oracle_pass=summary['ts_oracle_pass'],
                                pruv_ts_pass=sum(p == t for p, t in zip(pruv, ts)))
                    row_['status'] = 'ok' if row_['pruv_oracle_pass'] == len(inputs) else 'wrong'
                    failed |= row_['status'] != 'ok'
                    print(key+': '+json.dumps(row_), flush=True)
                except Exception as exc:
                    row_['error'] = portable(str(exc))
                    failed = True
                    print(key+': '+row_['error'], flush=True)
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
