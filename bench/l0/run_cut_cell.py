#!/usr/bin/env python3
"""Cross-check the sheetWindow cell cut (Lair src/documents/preview.ts).

A string goes to Pruv (cut_cell.pruv: UTF-16 lengths counted on UTF-8, result proved at most 606 UTF-8
bytes), to the TypeScript copy (cut_cell.mjs, run in Lair's Electron when available) and to an independent
oracle that encodes the text as UTF-16-LE, keeps the first 400 bytes when there are more than 400 and decodes
them back with lone surrogates allowed, not by copying the TS expression. TS and oracle results are compared
after UTF-8 encoding (a lone surrogate becomes U+FFFD, as Buffer.from and the bridge do).
Domain: well-formed strings (no lone surrogates).
Inputs: the empty string, ASCII, Korean, accents, emoji (4 bytes, 2 units), "…", U+FFFD, newlines and U+2028,
lengths 0..450 units, texts of exactly 198..203 units with an emoji at or across unit 200, long texts up to
200,000 units, texts that already end in "…" at 201 units.
"""
import argparse
import json
import random
import re
import sys

sys.dont_write_bytecode = True

NAME = 'cut_cell'
CUT = 200
TAIL = '…'

HARNESS = '''#![allow(dead_code, unused_imports)]
#[path = "@SOL@"] mod sol;
use std::io::{self, BufRead, Write};
fn hex(s: &str) -> String { s.bytes().map(|b| format!("{:02x}", b)).collect() }
fn main() {
  let out = io::stdout(); let mut out = out.lock();
  for line in io::stdin().lock().lines() {
    let line = line.unwrap();
    let buf: Vec<u8> = line[1..].as_bytes().chunks(2).map(|p| u8::from_str_radix(std::str::from_utf8(p).unwrap(), 16).unwrap()).collect();
    let text = std::str::from_utf8(&buf).unwrap();
    writeln!(out, "x{}", hex(&sol::cut_cell(text))).unwrap();
  }
}
'''

LONE = re.compile('[\ud800-\udfff]')


def utf8_view(s):
    """The string after UTF-8 encoding: a lone surrogate becomes U+FFFD."""
    return LONE.sub('\ufffd', s)


def u16(s):
    """UTF-16 length of a well-formed string."""
    return len(s.encode('utf-16-le')) // 2


def oracle(text):
    raw = text.encode('utf-16-le')
    if len(raw) <= 2 * CUT:
        return text
    return utf8_view(raw[:2 * CUT].decode('utf-16-le', 'surrogatepass')) + TAIL


def is_cut(text):
    return u16(text) > CUT


ONE_UNIT = ['a', 'b', '7', '표', '한', 'é', '…', '\n', ' ', ',', '\u2028', '\ufffd', 'ß', '\t']
TWO_UNITS = ['\U0001f600', '\U0001f44d', '\U00010348']


def exact(r, n, emoji=0.2):
    """A well-formed string of exactly n UTF-16 units."""
    out = []
    while n > 0:
        if n >= 2 and r.random() < emoji:
            out.append(r.choice(TWO_UNITS))
            n -= 2
        else:
            out.append(r.choice(ONE_UNIT))
            n -= 1
    return ''.join(out)


def rand_text(r):
    kind = r.randrange(6)
    if kind == 0:
        return exact(r, r.randrange(0, 30))
    if kind == 1:
        return exact(r, r.randrange(0, 451), r.choice([0, 0.05, 0.2, 0.6, 1]))
    if kind == 2:   # around the cut: 195..206 units
        return exact(r, r.randrange(195, 207), r.choice([0.2, 0.6, 1]))
    if kind == 3:   # 199 units then an emoji straddling unit 200
        return exact(r, 199, r.random() * 0.5) + r.choice(TWO_UNITS) + exact(r, r.randrange(0, 20))
    if kind == 4:
        return exact(r, r.randrange(1000, 5000), r.random())
    return r.choice(['', '표' * r.randrange(150, 260), 'a' * r.randrange(150, 260), '\U0001f600' * r.randrange(90, 130)])


def edge_cases():
    rows = ['', 'a', '…', '\ufffd', '\U0001f600', '\n', '\u2028']
    for n in range(195, 206):
        rows += ['a' * n, '표' * n, '…' * n]
    for n in range(97, 103):
        rows.append('\U0001f600' * n)
    for k in range(194, 202):
        for tail in ('', 'b', 'bb', '\U0001f600', '\U0001f600x'):
            rows.append('a' * k + '\U0001f600' + tail)
            rows.append('표' * k + '\U0001f600' + tail)
    rows += ['a' * 200 + '…', 'a' * 199 + '…', 'a' * 199 + '\U0001f600' + '…', 'a' * 200 + '\ufffd',
             'a' * 199 + '\ufffd…', '\U0001f600' * 100 + 'x', '\U0001f600' * 99 + 'a' + '\U0001f600',
             'a' * 100000, '표' * 200000, '\U0001f600' * 100000, '\U00010348' * 101]
    return rows


def cases(n, seed):
    rows = edge_cases()
    edges = len(rows)
    r = random.Random(seed)
    for _ in range(n):
        rows.append(rand_text(r))
    for t in rows:
        t.encode('utf-8')   # well-formed: raises on a lone surrogate
    return rows, edges


def ts_line(text):
    return json.dumps(dict(text=text))


def harness_line(text):
    return 'n' + text.encode().hex()


def brief(text):
    return dict(units=u16(text), head=text[:60], tail=text[-60:])


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--seed', type=int, default=12345)
    ap.add_argument('--n', type=int, default=20000)
    ap.add_argument('--emit', action='store_true', help='only print JSON lines [text, oracle]')
    args = ap.parse_args()
    if args.n < 0:
        ap.error('--n must be nonnegative')
    if args.emit:
        for text in cases(args.n, args.seed)[0]:
            sys.stdout.write(json.dumps([text, oracle(text)]) + '\n')
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
        want = [oracle(text) for text in inputs]
        cut = [is_cut(text) for text in inputs]
        summary['oracle_outcomes'] = dict(
            unchanged=sum(1 for c in cut if not c),
            cut=sum(1 for c in cut if c),
            cut_through_pair=sum(1 for c, w in zip(cut, want) if c and w.endswith('\ufffd' + TAIL)
                                 and u16(w) == CUT + 1),
            unchanged_units_198_to_200=sum(1 for w, c in zip(want, cut) if not c and 198 <= u16(w) <= CUT),
            max_result_units=max(u16(w) for w in want),
            max_result_utf8_bytes=max(len(w.encode()) for w in want))
        node, summary['ts_runtime'] = ts_runtime()
        # not splitlines: U+2028 stays in a JSON string
        ts = [utf8_view(json.loads(x)) for x in run(node + [HERE / (NAME+'.mjs')], ''.join(ts_line(text)+'\n' for text in inputs)).split('\n')[:-1]]
        assert len(ts) == len(inputs)
        summary['ts_oracle_pass'] = sum(t == w for t, w in zip(ts, want))
        payload = ''.join(harness_line(text) + '\n' for text in inputs)
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
                    lines = run([exe], payload).splitlines()
                    assert len(lines) == len(inputs)
                    pruv = [bytes.fromhex(line[1:]).decode() for line in lines]
                    for i, (text, p, t, w) in enumerate(zip(inputs, pruv, ts, want)):
                        if p != t or p != w:
                            differences.append(dict(compiler_backend=key, case_index=i, input=brief(text), pruv=p, ts=t, expected=w))
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
