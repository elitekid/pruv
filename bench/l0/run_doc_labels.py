#!/usr/bin/env python3
"""Cross-check Lair csvName (src/documents/sheets.ts) and countList (src/documents/context.ts).

csvName goes to Pruv (doc_labels.pruv csv_name: byte scan for the last '/' or '\\' and the last '.', result
proved at most len(name) + 3 bytes), to the TypeScript copy (doc_labels.mjs, run in Lair's Electron when
available) and to an independent oracle written with rfind (no regular expression). countList goes to Pruv
as count_list (the text, proved at most 39 bytes per shown item) and count_list_more, to the TS copy and to
a plain Python oracle.
Domain: csvName names are well-formed strings (no lone surrogates); countList pages and counts are
integers in -10^15..10^15, max an integer in 0..10^9.
Inputs: names with '/', '\\', dots in every position, unicode (Korean, emoji, accents), newlines and other
line terminators, the empty name and long names; item lists of 0..60 items with the domain ends, max 0..40,
the list length -1/0/+1 and large values.
"""
import argparse
import json
import random
import sys

sys.dont_write_bytecode = True

NAME = 'doc_labels'
LIMIT = 10 ** 15
FALLBACK = '표'

HARNESS = '''#![allow(dead_code, unused_imports)]
#[path = "@SOL@"] mod sol;
use std::io::{self, BufRead, Write};
fn hex(s: &str) -> String { s.bytes().map(|b| format!("{:02x}", b)).collect() }
fn main() {
  let out = io::stdout(); let mut out = out.lock();
  for line in io::stdin().lock().lines() {
    let line = line.unwrap();
    let rest = &line[1..];
    if line.starts_with('n') {
      let buf: Vec<u8> = rest.as_bytes().chunks(2).map(|p| u8::from_str_radix(std::str::from_utf8(p).unwrap(), 16).unwrap()).collect();
      let name = std::str::from_utf8(&buf).unwrap();
      writeln!(out, "x{}", hex(&sol::csv_name(name))).unwrap();
    } else {
      let v: Vec<i64> = rest.split_whitespace().map(|x| x.parse().unwrap()).collect();
      let max = v[0];
      let n = (v.len() - 1) / 2;
      let pages: Vec<i64> = (0..n).map(|k| v[1 + 2 * k]).collect();
      let counts: Vec<i64> = (0..n).map(|k| v[2 + 2 * k]).collect();
      writeln!(out, "x{} {}", hex(&sol::count_list(&pages, &counts, max)), sol::count_list_more(n as i64, max)).unwrap();
    }
  }
}
'''


def oracle_name(name):
    """csvName without a regular expression."""
    cut = max(name.rfind('/'), name.rfind('\\'))
    base = name[cut + 1:]
    dot = base.rfind('.')
    if 0 <= dot < len(base) - 1:   # the dot has at least one character after it
        base = base[:dot]
    return base or FALLBACK


def oracle_count(items, max_):
    shown = items[:max_]
    return dict(list=', '.join('%d (%d)' % (p, c) for p, c in shown), more=max(0, len(items) - max_))


PIECES = ['a', 'b', 'x', 'Z', '.', '.', '.', '/', '\\', '\n', '\r', ' ', '표', '한글', 'é', '\U0001f600', 'csv', 'tsv',
          '..', '\u2028', '\u00a0', '_', '-', '0']
EXTS = ['csv', 'tsv', 'xlsx', 'tar.gz', '', ' ', '\n', '표', 'a.b', '.']


def rand_name(r):
    kind = r.randrange(4)
    if kind == 0:   # free mix
        return ''.join(r.choice(PIECES) for _ in range(r.randrange(14)))
    if kind == 1:   # directory part, base, extension
        d = ''.join(r.choice(['a', 'b/', 'c\\', '표/', '.', 'd.e/', '\n/']) for _ in range(r.randrange(4)))
        base = ''.join(r.choice(['a', 'b', '표', '😀', 'x.y', '.', ' ', '\n']) for _ in range(r.randrange(4)))
        ext = r.choice(EXTS)
        return d + base + ('.' + ext if r.random() < 0.8 else ext)
    if kind == 2:   # dots and separators only
        return ''.join(r.choice(['.', '.', '/', '\\', 'a']) for _ in range(r.randrange(10)))
    return ''.join(chr(r.choice([r.randrange(32, 127), r.randrange(0xa0, 0x3000), r.randrange(0x10000, 0x10400)]))
                   for _ in range(r.randrange(20))) + r.choice(['', '.csv', '/', '.', '\\x.y'])


def rand_num(r):
    return r.choice([lambda: r.randrange(-3, 30), lambda: r.randrange(1, 10 ** r.randrange(1, 16)),
                     lambda: -r.randrange(1, 10 ** r.randrange(1, 16)),
                     lambda: r.choice([LIMIT, -LIMIT, LIMIT - 1, 1 - LIMIT, 0, 1, -1])])()


def rand_items(r):
    size = r.choice([r.randrange(6), r.randrange(30), r.randrange(61)])
    return [(rand_num(r), rand_num(r)) for _ in range(size)]


def rand_max(r, size):
    return r.choice([lambda: r.randrange(0, 41), lambda: r.randrange(0, 41), lambda: 20,
                     lambda: max(0, size + r.choice([-1, 0, 1])), lambda: r.choice([10 ** 9, 10 ** 9 - 1, 0, 1])])()


EDGE_NAMES = ['', 'a/b\\c.tsv', 'x.tar.gz', '.csv', 'a.', 'dir/', 'a.b.c.', '/', '\\', '.', '..', '...', 'a..',
              'a..b', '/.', '.a', 'a/.b', 'a/b.', 'a.b/', 'a.b/c', 'a\\b/c\\d.e', 'a.\n', 'a.\nb', '\n.csv', 'a\n.b',
              'a.b\n', '\n', '표', '표.csv', '표/표.한', '한글.csv', '😀.😀', '😀', 'dir.d/file', 'dir.d/',
              'C:\\x\\y.xlsx', ' .csv', '. ', ' . ', 'a.b.', 'noext', 'trailing/', 'ü.tsv', 'a.\u2028', 'a.\r',
              'a/\n', 'a/.\n', '.\n', '.\n.', 'x.csv.', 'x.csv..', 'x..csv', '\\.', '/.csv', 'a/b/c/d.e.f',
              'a' * 5000 + '.csv', '/' * 3000, '.' * 3000, 'x.' * 2000, 'a/' * 1000 + 'b.c', '표' * 1000 + '.표']


def edge_items():
    full = [(LIMIT, -LIMIT), (-LIMIT, LIMIT), (1 - LIMIT, LIMIT - 1), (0, 0), (-1, 1)]
    rows = []
    for items in ([], [(1, 1)], [(3, 2), (5, 1)], full, [(i, i * 1000) for i in range(60)],
                  [(LIMIT, LIMIT)] * 60, [(-LIMIT, -LIMIT)] * 60):
        for m in (0, 1, 2, 20, len(items) - 1, len(items), len(items) + 1, 10 ** 9 - 1, 10 ** 9):
            if m >= 0:
                rows.append(('countList', items, m))
    return rows


def cases(n, seed):
    rows = [('csvName', x) for x in EDGE_NAMES] + edge_items()
    edges = len(rows)
    r = random.Random(seed)
    for _ in range(n):
        if r.random() < 0.5:
            rows.append(('csvName', rand_name(r)))
        else:
            items = rand_items(r)
            rows.append(('countList', items, rand_max(r, len(items))))
    for row in rows:
        if row[0] == 'csvName':
            row[1].encode()   # well-formed
        else:
            assert all(-LIMIT <= x <= LIMIT for it in row[1] for x in it) and 0 <= row[2] <= 10 ** 9
    return rows, edges


def expected(row):
    return oracle_name(row[1]) if row[0] == 'csvName' else oracle_count(row[1], row[2])


def ts_line(row):
    if row[0] == 'csvName':
        return json.dumps(dict(f='csvName', name=row[1]))
    return json.dumps(dict(f='countList', items=[dict(page=p, count=c) for p, c in row[1]], max=row[2]))


def harness_line(row):
    if row[0] == 'csvName':
        return 'n' + row[1].encode().hex()
    return 'c%d' % row[2] + ''.join(' %d %d' % it for it in row[1])


def brief(row):
    return [row[0], row[1][:60] if row[0] == 'csvName' else row[1][:6]] + list(row[2:])


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--seed', type=int, default=12345)
    ap.add_argument('--n', type=int, default=20000)
    ap.add_argument('--emit', action='store_true',
                    help='only print JSON lines ["csvName", name, oracle] / ["countList", items, max, oracle]')
    args = ap.parse_args()
    if args.n < 0:
        ap.error('--n must be nonnegative')
    if args.emit:
        for row in cases(args.n, args.seed)[0]:
            want = expected(row)
            if row[0] == 'csvName':
                out = ['csvName', row[1], want]
            else:
                out = ['countList', [dict(page=p, count=c) for p, c in row[1]], row[2], want]
            sys.stdout.write(json.dumps(out) + '\n')
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
        want = [expected(row) for row in inputs]
        names = [w for row, w in zip(inputs, want) if row[0] == 'csvName']
        lists = [w for row, w in zip(inputs, want) if row[0] == 'countList']
        summary['csv_name_cases'] = len(names)
        summary['count_list_cases'] = len(lists)
        summary['oracle_outcomes'] = dict(
            fallback_label=sum(1 for x in names if x == FALLBACK),
            count_list_empty=sum(1 for x in lists if x['list'] == ''),
            count_list_with_more=sum(1 for x in lists if x['more'] > 0))
        node, summary['ts_runtime'] = ts_runtime()
        ts = [json.loads(x) for x in run(node + [HERE / (NAME+'.mjs')], ''.join(ts_line(row)+'\n' for row in inputs)).split('\n')[:-1]]  # not splitlines: U+2028 stays in a JSON string
        assert len(ts) == len(inputs)
        summary['ts_oracle_pass'] = sum(t == w for t, w in zip(ts, want))
        payload = ''.join(harness_line(row) + '\n' for row in inputs)
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
                    pruv = []
                    for row, line in zip(inputs, lines):
                        words = line[1:].split(' ')
                        text = bytes.fromhex(words[0]).decode()
                        pruv.append(text if row[0] == 'csvName' else dict(list=text, more=int(words[1])))
                    for i, (row, p, t, w) in enumerate(zip(inputs, pruv, ts, want)):
                        if p != t or p != w:
                            differences.append(dict(compiler_backend=key, case_index=i, input=brief(row), pruv=p, ts=t, expected=w))
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
