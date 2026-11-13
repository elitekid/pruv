#!/usr/bin/env python3
"""Cross-check the Lair textAround byte window (src/documents/preview.ts).

Each case is the bytes of a file and a request [line, before, after, maxBytes]. The TypeScript copy
(text_around.mjs, run in Lair's Electron when available: the verbatim textAround on a temporary file)
gives the TextAround. Pruv text_around.pruv (around_plan) plans which bytes are shown; the plan must equal
an independent oracle (Python bytes.split lines, slices, find/rfind and a regular expression for the
UTF-8 cut), and the TextAround that fromPlan builds from the Pruv plan (the same tail steps as
textAround, in the same Electron) must equal the verbatim TextAround.
Domain: integer 1 <= line <= 10^15, 0 <= before, after <= 10^15, 0 <= maxBytes <= 2^40 and files of
at most 2^40 bytes (the bridge glue keeps Lair's defaults and line flooring before the domain check).
Inputs: empty files, files of only newlines, files with and without a final newline, CRLF, UTF-8
characters of 2 to 4 bytes cut at every byte budget, invalid UTF-8 and EUC-KR bytes, targets past the
end and first shown lines past the end, budgets of 0 to 10 bytes and the 256 KiB default, before/after
of 0 to 10^15 and files over the 1 MiB read block of textAround with newlines on the block edge.
"""
import argparse
import json
import random
import re
import sys

sys.dont_write_bytecode = True

NAME = 'text_around'

HARNESS = '''#![allow(dead_code, unused_imports)]
#[path = "@SOL@"] mod sol;
use std::io::{self, BufRead, Write};
fn main() {
  let out = io::stdout(); let mut out = out.lock();
  for line in io::stdin().lock().lines() {
    let line = line.unwrap();
    let mut it = line.split(' ');
    let v: Vec<i64> = (0..4).map(|_| it.next().unwrap().parse().unwrap()).collect();
    let hex = it.next().unwrap_or("").as_bytes();
    let buf: Vec<u8> = hex.chunks(2).map(|p| u8::from_str_radix(std::str::from_utf8(p).unwrap(), 16).unwrap()).collect();
    let r = sol::around_plan(&buf, v[0], v[1], v[2], v[3]);
    let words: Vec<String> = r.iter().map(|x| x.to_string()).collect();
    writeln!(out, "x {}", words.join(" ")).unwrap();
  }
}
'''


def oracle(buf, target, before, after, max_bytes):
    """The plan record from line slices (no newline counting scan)."""
    segs = buf.split(b'\n')
    # bytes.split gives one more piece than there are newlines; a final newline leaves an empty last piece.
    total = 0 if not buf else len(segs) - (1 if buf.endswith(b'\n') else 0)
    starts = [0]
    for s in segs[:-1]:
        starts.append(starts[-1] + len(s) + 1)
    first = max(1, target - before)
    last_line = target + after

    def start_of(k):  # offset of line k (1-based) when the file has at least k - 1 newlines
        return starts[k - 1] if k - 1 < len(starts) else None

    if total == 0 or first > total or start_of(first) is None:
        return [0, total]
    shown = min(target, total)
    line = target if target <= total else total
    t1 = starts[line - 1]
    t2 = starts[line] if target <= total and line < len(starts) else len(buf)
    end = starts[last_line] if last_line < len(starts) else len(buf)
    s0 = starts[first - 1]
    cut = t2 - t1 > max_bytes
    tlen = max_bytes if cut else t2 - t1
    need_b, need_a = t1 - s0, max(0, end - t2)
    rest = max_bytes - tlen
    bb, ab = rest // 2, rest - rest // 2
    if need_b < bb:
        ab += bb - need_b
    elif need_a < ab:
        bb += ab - need_a
    blen, alen = min(need_b, bb), min(need_a, ab)
    truncated = cut
    b1 = t1 - blen
    if blen < need_b:
        if buf[b1 - 1] != 10:
            k = buf[b1:t1].find(b'\n')
            b1 = b1 + k + 1 if k >= 0 else t1
        truncated = True
    a2 = t2 + alen
    if alen < need_a:
        k = buf[t2:a2].rfind(b'\n')
        a2 = t2 + k + 1 if k >= 0 else t2
        truncated = True
    te = t1 + tlen
    if cut:
        m = re.search(rb'([\xc0-\xff])([\x80-\xbf]*)\Z', buf[t1:te])
        if m:
            lead = m.group(1)[0]
            need = 4 if lead >= 0xf0 else 3 if lead >= 0xe0 else 2
            if len(m.group(2)) < need - 1:
                te = t1 + m.start(1)
    return [1, total, shown, b1, t1, t1, te, t2, a2, buf[b1:t1].count(b'\n'), int(truncated), int(cut)]


BIG = 10**15


def gen_bytes(r):
    kind = r.randrange(6)
    lines = r.choice([0, 1, 2, r.randrange(0, 8), r.randrange(0, 40), r.randrange(0, 200)])
    parts = []
    for _ in range(lines):
        width = r.choice([0, 1, r.randrange(0, 6), r.randrange(0, 30), r.randrange(0, 300)])
        if kind == 0:
            s = bytes(r.randrange(256) for _ in range(width))
        elif kind == 1:
            s = ''.join(chr(r.choice([r.randrange(97, 123), r.randrange(0xac00, 0xd7a4), r.randrange(0x80, 0x800),
                                      r.randrange(0x1f600, 0x1f650), 32])) for _ in range(width)).encode('utf-8')
        elif kind == 2:
            s = ''.join(chr(r.randrange(0xac00, 0xd7a4)) for _ in range(width)).encode('euc-kr', 'replace')
        else:
            s = bytes(r.choice([97, 98, 32, 13, 0xea, 0xb0, 0x80, 0xf0, 0x9f]) for _ in range(width))
        parts.append(s + r.choice([b'\n', b'\n', b'\r\n', b'']))
    return b''.join(parts)


def cases(n, seed):
    r = random.Random(seed)
    files = [b'', b'\n', b'\n\n\n', b'a', b'a\n', b'a\nb', b'a\nb\n', b'a\r\nb\r\n', b'ab\ncd\nef\ngh\nij',
             '가나\n다라마\n바'.encode(), '\U0001f600\U0001f600\nééé\n'.encode(),
             b'x' * 40 + b'\n' + b'y' * 3, '하'.encode('euc-kr') * 5 + b'\n\xff\xfe\n', b'\xef\xbb\xbfa\nb\n',
             ('줄' * 9 + '\n') .encode() * 6]
    out = []
    for buf in files:
        total = buf.count(b'\n') + (0 if not buf or buf.endswith(b'\n') else 1)
        for target in sorted({1, 2, total, total + 1, total + 3}):
            if target < 1:
                continue
            for before in (0, 1, 3, 200):
                for after in (0, 1, 3, 200):
                    for mb in (0, 1, 2, 3, 5, 8, 262144):
                        out.append((buf, target, before, after, mb))
    # Every byte budget through a line of 2-, 3- and 4-byte characters.
    for ch in ('é', '가', '\U0001f600'):
        buf = ('a\n' + ch * 5 + '\nb\n').encode()
        for mb in range(0, 30):
            for before, after in ((0, 0), (1, 1), (5, 0)):
                out.append((buf, 2, before, after, mb))
    for target, before, after in ((BIG, 0, 0), (BIG, BIG, 0), (1, 0, BIG), (BIG, BIG, BIG), (3, BIG, BIG)):
        for mb in (0, 4, 2**40):
            out.append((b'a\nb\nc\nd', target, before, after, mb))
    # Over the 1 MiB read block, newlines on and around its edge.
    block = 1 << 20
    for edge in (block - 1, block, block + 1):
        buf = b'q' * (edge - 5) + b'\n' + b'w' * 4 + b'\n' + b'e' * 100 + b'\n' + b'r' * 300
        for target, mb in ((1, 64), (2, 64), (3, 262144), (4, 10), (3, 2 * block)):
            out.append((buf, target, 1, 1, mb))
    edges = len(out)
    for _ in range(n):
        buf = gen_bytes(r)
        total = buf.count(b'\n') + 1
        target = r.choice([1, r.randrange(1, total + 3), r.randrange(1, 2 * total + 3), BIG])
        before = r.choice([0, 200, r.randrange(0, 5), r.randrange(0, total + 3), BIG])
        after = r.choice([0, 200, r.randrange(0, 5), r.randrange(0, total + 3), BIG])
        mb = r.choice([0, 262144, r.randrange(0, 12), r.randrange(0, 200), r.randrange(0, len(buf) + 2)])
        out.append((buf, target, before, after, mb))
    return out, edges


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--seed', type=int, default=12345)
    ap.add_argument('--n', type=int, default=20000)
    ap.add_argument('--emit', action='store_true',
                    help='only print JSON lines [hexBytes, line, before, after, maxBytes, oracle plan] '
                         '(Node bridge test)')
    args = ap.parse_args()
    if args.n < 0:
        ap.error('--n must be nonnegative')
    if args.emit:
        for x in cases(args.n, args.seed)[0]:
            sys.stdout.write(json.dumps([x[0].hex(), *x[1:], oracle(*x)]) + '\n')
        return 0
    from run import HERE, WORK, RESULTS, configure, run
    from run_host_within import portable
    from run_decode_bytes import ts_runtime
    summary = dict(seed=args.seed, random_cases=args.n, runs={})
    differences, failed = [], False
    try:
        g2, summary['tools'] = configure()
        inputs, summary['edge_cases'] = cases(args.n, args.seed)
        summary.update(cases=len(inputs), bytes=sum(len(x[0]) for x in inputs))
        expected = [oracle(*x) for x in inputs]
        summary.update(oracle_shown=sum(e[0] == 1 for e in expected),
                       oracle_target_cut=sum(e[0] == 1 and e[11] == 1 for e in expected),
                       oracle_truncated=sum(e[0] == 1 and e[10] == 1 for e in expected))
        node, summary['ts_runtime'] = ts_runtime()
        script = [HERE / (NAME+'.mjs')]
        ts = [json.loads(x) for x in run(node + script, ''.join(
            json.dumps([x[0].hex(), *x[1:], None]) + '\n' for x in inputs)).split('\n')[:-1]]
        assert len(ts) == len(inputs)
        payload = ''.join('%d %d %d %d %s\n' % (*x[1:], x[0].hex()) for x in inputs)
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
                    lines = run([exe], payload).split('\n')[:-1]
                    assert len(lines) == len(inputs)
                    plans = [[int(w) for w in line[2:].split(' ')] for line in lines]
                    built = [json.loads(x) for x in run(node + script, ''.join(
                        json.dumps(['plan', x[0].hex(), p]) + '\n' for x, p in zip(inputs, plans))).split('\n')[:-1]]
                    assert len(built) == len(inputs)
                    for i, (x, p, b, s, want) in enumerate(zip(inputs, plans, built, ts, expected)):
                        if p != want or b != s:
                            d = dict(compiler_backend=key, case_index=i, bytes_hex=x[0].hex()[:400], file_bytes=len(x[0]),
                                     request=list(x[1:]), pruv=p, expected=want)
                            if b != s:
                                d.update(from_plan=b, ts=s)
                            differences.append(d)
                    row_.update(cases=len(inputs), pruv_oracle_pass=sum(p == w for p, w in zip(plans, expected)),
                                from_plan_ts_pass=sum(b == s for b, s in zip(built, ts)),
                                odd_plans=sum(p == [-2] for p in plans))
                    ok = row_['pruv_oracle_pass'] == len(inputs) and row_['from_plan_ts_pass'] == len(inputs)
                    row_['status'] = 'ok' if ok else 'wrong'
                    failed |= not ok
                    print(key+': '+json.dumps(row_), flush=True)
                except Exception as exc:
                    row_['error'] = portable(str(exc))
                    failed = True
                    print(key+': '+row_['error'], flush=True)
    except Exception as exc:
        summary['error'] = portable(str(exc))
        failed = True
    differences.sort(key=lambda d: (len(json.dumps(d)), d['compiler_backend']))
    summary.update(status='error' if failed else 'ok', difference_records_total=len(differences),
                   difference_records_saved=min(50, len(differences)),
                   difference_order='JSON length of the record, compiler/backend')
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / (NAME+'_summary.json')).write_text(json.dumps(summary, indent=2)+'\n')
    (RESULTS / (NAME+'_differences.jsonl')).write_text(''.join(json.dumps(d)+'\n' for d in differences[:50]))
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
