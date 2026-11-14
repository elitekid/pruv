#!/usr/bin/env python3
"""L3-1 A0 fixtures: edge/window framing, packet checking and copy_span on py/rust, py/llvm, rs/rust, rs/llvm.

Oracles are independent of the Pruv code: the edge oracle follows the TS split/pop/shift rules, the window
oracle is a literal port of the TS openLineWindow chunk loop, and the packet checker is a separate Python
implementation. Inputs travel as decimal words; `v*k` repeats value v k times.
"""
import importlib.util
from itertools import groupby
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
WORK = HERE / 'work' / 'a0'

HARNESS = r'''#![allow(dead_code, unused_imports)]
#[path = "@SOL@"] mod sol;
use std::io::{self, BufRead};
fn expand(words: Vec<&str>) -> Vec<i64> {
 let mut out = Vec::new();
 for w in words {
  match w.split_once('*') {
   Some((v, k)) => { let v: i64 = v.parse().unwrap(); for _ in 0..k.parse::<usize>().unwrap() { out.push(v); } }
   None => out.push(w.parse().unwrap()),
  }
 }
 out
}
fn bytes(v: &[i64]) -> Vec<u8> { v.iter().map(|&x| x as u8).collect() }
fn main() {
 for line in io::stdin().lock().lines() {
  let line = line.unwrap();
  let mut words = line.split_whitespace();
  let op = words.next().unwrap();
  let a: i64 = words.next().unwrap().parse().unwrap();
  let b: i64 = words.next().unwrap().parse().unwrap();
  let c: i64 = words.next().unwrap().parse().unwrap();
  let vals = expand(words.collect());
  let out: Vec<i64> = match op {
   "edge" => sol::edge_frames(&bytes(&vals), a != 0, b != 0),
   "window" => sol::window_frames(&bytes(&vals), a != 0),
   "limit" => { let big = vec![97u8; 8388609]; sol::window_frames(&big, false) },
   "packet" => {
    let meta: Vec<i64> = vals[..a as usize].to_vec();
    let turns: Vec<i64> = vals[a as usize..(a + b) as usize].to_vec();
    let text = bytes(&vals[(a + b) as usize..]);
    sol::packet(&meta, &turns, &text)
   },
   "failed" => sol::failed_packet(a, b),
   "probe" => {
    let d = vals[0] as usize;
    let dst = bytes(&vals[1..1 + d]);
    let src = bytes(&vals[1 + d..]);
    sol::copy_probe(&dst, a, &src, b, c)
   },
   _ => panic!("unknown fixture"),
  };
  println!("{}", out.iter().map(|x| x.to_string()).collect::<Vec<_>>().join(" "));
 }
}
'''

EDGE, LINE, DROP = 65536, 1048576, 8192


def enc(values):
    """Run-length word encoding of an int sequence (bytes or list)."""
    words = []
    for v, grp in groupby(values):
        k = len(list(grp))
        words.append(f'{v}*{k}' if k >= 4 else ' '.join([str(v)] * k))
    return ' '.join(w for w in words if w)


# ---------------- edge oracle (TS readEdgeLines rules, mirroring jsonl_next frames) ----------------
def edge_oracle(data, tail, cut):
    if len(data) > EDGE:
        return [1, EDGE]
    pieces = []  # (start, stop, terminated)
    s = 0
    for i, b in enumerate(data):
        if b == 10:
            pieces.append((s, i, True))
            s = i + 1
    pieces.append((s, len(data), False))  # the last piece after the final LF, possibly empty
    if tail and cut:
        pieces = pieces[1:]
    if not tail and cut:
        pieces = pieces[:-1]
    out = [0]
    for s, stop, term in pieces:
        if term:
            end = stop - 1 if stop > s and data[stop - 1] == 13 else stop
            out += [s, end, stop + 1]
        elif stop > s:
            out += [s, stop, stop]
    return out


# ---------------- window oracle (literal port of TS openLineWindow) ----------------
def window_ts(data, cut, chunk):
    out, parts, length, skipping, line_start, pending = [], [], 0, cut, 0, None
    for ci in range(0, len(data), chunk):
        d = data[ci:ci + chunk]
        frm = 0
        while True:
            at = d.find(b'\n', frm)
            if at < 0:
                if not skipping:
                    length += len(d) - frm
                    if length > LINE:
                        head = (b''.join(parts) + d[frm:])[:DROP]
                        out.append([1, line_start, line_start + len(head), None])
                        pending = len(out) - 1
                        skipping, parts, length = True, [], 0
                    else:
                        parts.append(d[frm:])
                break
            absat = ci + at
            if skipping:
                skipping = False
                if pending is not None:
                    out[pending][3] = absat + 1
                    pending = None
            elif length + (at - frm) <= LINE:
                parts.append(d[frm:at])
                line = b''.join(parts)
                end = line_start + len(line) - (1 if line.endswith(b'\r') else 0)
                out.append([0, line_start, end, absat + 1])
            else:
                head = (b''.join(parts) + d[frm:at])[:DROP]
                out.append([1, line_start, line_start + len(head), absat + 1])
            parts, length, frm, line_start = [], 0, at + 1, absat + 1
    if pending is not None:
        out[pending][3] = len(data)
    return [0] + [x for q in out for x in q]


def window_oracle(data, cut):
    if len(data) > 8388608:
        return [1, 8388608]
    sizes = (1, 7, 4096, 262144) if len(data) <= 100000 else (4096, 262144, 1000003)
    results = [window_ts(data, cut, n) for n in sizes]
    if any(r != results[0] for r in results):
        raise RuntimeError(f'window oracle disagrees across chunk sizes for {data[:30]!r} len {len(data)}')
    return results[0]


# ---------------- packet oracle ----------------
class Bad(Exception):
    pass


def check_packet(meta, turns, text):
    n = len(text)
    if len(meta) != 14 or meta[0] != 1 or meta[1] not in (0, 1, 2) or meta[2] not in (0, 1):
        raise Bad
    mode, count = meta[1], meta[3]
    if mode != 2 and (meta[2] != 0 or count != 0):
        raise Bad
    if not 0 <= count <= 200 or len(turns) != 10 * count or n > 5646080:
        raise Bad
    order = []

    def ref(s, l, allowed=True, exact=None, required=False):
        if (s, l) == (-1, 0):
            if required:
                raise Bad
            return
        if not (s >= 0 and l >= 0 and s + l <= n) or not allowed or (exact is not None and l != exact):
            raise Bad
        order.append((s, l))

    ref(meta[4], meta[5])
    ref(meta[6], meta[7], mode == 0)
    ref(meta[8], meta[9], mode == 0)
    ref(meta[10], meta[11], mode == 1, 24)
    ref(meta[12], meta[13], mode == 2)
    total = 0
    for i in range(count):
        ps, pl, rs, rl, cs, cl, ks, kl, tools, clipped = turns[10 * i:10 * i + 10]
        if pl > 32768 or rl > 32768 or tools < 0 or clipped not in (0, 1):
            raise Bad
        ref(ps, pl, required=True)
        ref(rs, rl, required=True)
        ref(cs, cl, exact=24)
        ref(ks, kl, exact=24)
        total += pl + rl
    if total > 2097152:
        raise Bad
    cur = 0
    for s, l in order:
        if s != cur:
            raise Bad
        cur += l
    if cur != n:
        raise Bad


def packet_expect(meta, turns, text):
    try:
        check_packet(meta, turns, text)
    except Bad:
        return [2, 0]
    return [0, 14, len(turns), len(text)] + list(meta) + list(turns) + list(text)


def build(mode, title=None, cwd=None, entry=None, last=None, model=None, turns=(), omit=0):
    """A correctly tiled output; strings are placed in packing order."""
    text = bytearray()

    def put(v):
        if v is None:
            return [-1, 0]
        start = len(text)
        text.extend(v)
        return [start, len(v)]
    refs = [put(title), put(cwd), put(entry), put(last), put(model)]
    meta = [1, mode, omit, len(turns)] + [x for r in refs for x in r]
    flat = []
    for t in turns:
        p, r, c, k = put(t['p']), put(t['r']), put(t.get('c')), put(t.get('k'))
        flat += p + r + c + k + [t.get('tools', 0), t.get('clip', 0)]
    return meta, flat, bytes(text)


def with_gap(meta, turns, text, at):
    """Insert a stray text byte at `at`, shifting later present refs, so tiling has a gap."""
    meta, turns = list(meta), list(turns)
    for i in (4, 6, 8, 10, 12):
        if meta[i] >= at:
            meta[i] += 1
    for i in range(0, len(turns), 10):
        for j in (0, 2, 4, 6):
            if turns[i + j] >= at:
                turns[i + j] += 1
    return meta, turns, text[:at] + b'!' + text[at:]


TS24 = b'2026-11-14T01:02:03.004Z'
TS24B = b'2025-01-02T03:04:05.006Z'


def packet_cases():
    cases = []  # (name, meta, turns, text, must_be_valid or None)

    def add(name, parts, valid=None):
        meta, turns, text = parts
        cases.append((name, list(meta), list(turns), bytes(text), valid))

    two = [dict(p=b'hi', r=b'yo'), dict(p=b'a', r=b'', c=TS24, k=TS24B, tools=3, clip=1)]
    add('head empty', build(0), True)
    add('head all present', build(0, title=b'T', cwd=b'/home', entry=b'cli'), True)
    add('head present empty', build(0, title=b'', cwd=b'', entry=b'x'), True)
    add('head title only', build(0, title=b'only'), True)
    add('tail empty', build(1), True)
    add('tail title+lastAt', build(1, title=b'T', last=TS24), True)
    add('tail lastAt only', build(1, last=TS24), True)
    add('window empty', build(2), True)
    add('window omitted', build(2, omit=1), True)
    add('window model only', build(2, model=b'claude'), True)
    add('window two turns', build(2, title=b'T', model=b'm', turns=two, omit=1), True)
    add('window prompt empty', build(2, turns=[dict(p=b'', r=b'')]), True)
    add('window 200 turns', build(2, turns=[dict(p=b'a', r=b'b')] * 200), True)
    add('window 32 full turns', build(2, turns=[dict(p=b'p' * 32768, r=b'r' * 32768)] * 32), True)
    add('window title+model+turns tail', build(2, title=b'x', model=b'', turns=two), True)
    add('output cap exact', build(2, model=b'm' * 5646080), True)
    add('output cap over', build(2, model=b'm' * 5646081), False)
    add('window 33 full turns', build(2, turns=[dict(p=b'p' * 32768, r=b'r' * 32768)] * 33), False)

    base = build(2, title=b'T', model=b'm', turns=two, omit=1)
    tbase = build(1, title=b'T', last=TS24)
    hbase = build(0, title=b'T', cwd=b'/h', entry=b'e')

    def mut(src, fn):
        meta, turns, text = list(src[0]), list(src[1]), bytearray(src[2])
        fn(meta, turns, text)
        return meta, turns, bytes(text)

    def meta_set(i, v):
        def f(m, t, x): m[i] = v
        return f

    def turn_set(i, v):
        def f(m, t, x): t[i] = v
        return f
    add('meta length 13', mut(base, lambda m, t, x: m.pop()), False)
    add('meta length 15', mut(base, lambda m, t, x: m.append(0)), False)
    add('meta empty', ([], [], b''), False)
    add('version 2', mut(base, meta_set(0, 2)), False)
    add('version 0', mut(base, meta_set(0, 0)), False)
    add('mode 3', mut(base, meta_set(1, 3)), False)
    add('mode -1', mut(base, meta_set(1, -1)), False)
    add('omitted 2', mut(base, meta_set(2, 2)), False)
    add('omitted -1', mut(base, meta_set(2, -1)), False)
    add('head omitted flag', mut(hbase, meta_set(2, 1)), False)
    add('tail omitted flag', mut(tbase, meta_set(2, 1)), False)
    add('head with turn count', mut(hbase, meta_set(3, 1)), False)
    add('tail with turns', build(1, title=b'T') and ([1, 1, 0, 1] + [0, 1] + [-1, 0] * 4, [0, 0, 0, 0, -1, 0, -1, 0, 0, 0], b'T'), False)
    add('turn count 201', build(2, turns=[dict(p=b'a', r=b'b')] * 201), False)
    add('turn count negative', mut(base, meta_set(3, -1)), False)
    add('turns too short for count', mut(base, lambda m, t, x: t.__delitem__(slice(0, 10))), False)
    add('turns too long for count', mut(base, lambda m, t, x: t.extend([0] * 10)), False)
    add('turns slot missing', mut(base, lambda m, t, x: t.pop()), False)
    add('title (-1,1)', mut(base, lambda m, t, x: (m.__setitem__(4, -1), m.__setitem__(5, 1))), False)
    add('title (-2,0)', mut(base, lambda m, t, x: (m.__setitem__(4, -2), m.__setitem__(5, 0))), False)
    add('title negative length', mut(base, lambda m, t, x: (m.__setitem__(4, 1), m.__setitem__(5, -1))), False)
    add('title past end', mut(base, meta_set(5, 10000)), False)
    add('title start past end', mut(base, lambda m, t, x: (m.__setitem__(4, len(x) + 1), m.__setitem__(5, 0))), False)
    add('title huge length', mut(base, meta_set(5, 2**62)), False)
    add('title huge start', mut(base, lambda m, t, x: (m.__setitem__(4, 2**63 - 1), m.__setitem__(5, 1))), False)
    add('cwd in tail', mut(tbase, lambda m, t, x: (m.__setitem__(6, 1), m.__setitem__(7, 0))), False)
    add('entrypoint in tail', mut(tbase, lambda m, t, x: (m.__setitem__(8, 1), m.__setitem__(9, 0))), False)
    add('cwd in window', build(2, title=b'T') and ([1, 2, 0, 0, 0, 1, 1, 1, -1, 0, -1, 0, -1, 0], [], b'Tc'), False)
    add('model in head', ([1, 0, 0, 0, -1, 0, -1, 0, -1, 0, -1, 0, 0, 1], [], b'm'), False)
    add('model in tail', ([1, 1, 0, 0, -1, 0, -1, 0, -1, 0, -1, 0, 0, 1], [], b'm'), False)
    add('lastAt in head', ([1, 0, 0, 0, -1, 0, -1, 0, -1, 0, 0, 24, -1, 0], [], TS24), False)
    add('lastAt in window', ([1, 2, 0, 0, -1, 0, -1, 0, -1, 0, 0, 24, -1, 0], [], TS24), False)
    add('lastAt length 23', build(1, last=TS24[:23]), False)
    add('lastAt length 25', build(1, last=TS24 + b'0'), False)
    add('lastAt empty present', build(1, last=b''), False)
    add('prompt absent', mut(base, lambda m, t, x: (t.__setitem__(0, -1), t.__setitem__(1, 0))), False)
    add('reply absent', mut(base, lambda m, t, x: (t.__setitem__(2, -1), t.__setitem__(3, 0))), False)
    add('prompt 32769', build(2, turns=[dict(p=b'p' * 32769, r=b'r')]), False)
    add('reply 32769', build(2, turns=[dict(p=b'p', r=b'r' * 32769)]), False)
    add('prompt 32768 ok', build(2, turns=[dict(p=b'p' * 32768, r=b'r' * 32768)]), True)
    add('total 2097153', build(2, turns=[dict(p=b'p' * 32768, r=b'r' * 32768)] * 32 + [dict(p=b'p', r=b'')]), False)
    add('created present empty', build(2, turns=[dict(p=b'a', r=b'b', c=b'')]), False)
    add('created length 23', build(2, turns=[dict(p=b'a', r=b'b', c=TS24[:23])]), False)
    add('completed length 25', build(2, turns=[dict(p=b'a', r=b'b', k=TS24 + b'0')]), False)
    add('created (-1,24)', mut(base, lambda m, t, x: (t.__setitem__(14, -1), t.__setitem__(15, 24))), False)
    add('tools -1', mut(base, turn_set(8, -1)), False)
    add('clipped 2', mut(base, turn_set(9, 2)), False)
    add('clipped -1', mut(base, turn_set(19, -1)), False)
    add('gap between turns', with_gap(*base, base[1][10]), False)
    add('gap before first ref', with_gap(*hbase, 1), False)
    add('overlap reply on prompt', mut(base, turn_set(2, base[1][0])), False)
    add('overlap title on cwd', mut(hbase, meta_set(6, 0)), False)
    add('trailing unused byte', mut(base, lambda m, t, x: x.extend(b'z')), False)
    add('trailing unused byte head', mut(hbase, lambda m, t, x: x.extend(b'z')), False)
    add('refs out of packing order', mut(hbase, lambda m, t, x: (m.__setitem__(4, 2), m.__setitem__(6, 0), m.__setitem__(8, 1))), False)
    for name, meta, turns, text, valid in cases:
        if valid is not None:
            ok = packet_expect(meta, turns, text)[0] == 0
            if ok != valid:
                raise RuntimeError(f'packet fixture {name!r}: declared valid={valid} but checker says {ok}')
    return cases


def probe_expect(dst, at, src, lo, hi):
    if lo < 0 or lo > hi or hi > len(src) or at < 0 or at > len(dst) or hi - lo > len(dst) - at:
        return [-1]
    out = bytearray(dst)
    out[at:at + hi - lo] = src[lo:hi]
    return list(out)


def big_line(raw, cr, fill=b'a'):
    return fill * (raw - 1) + b'\r' if cr else fill * raw


def fixtures():
    cases = []  # (op, a, b, c, word string, expected list)

    def add(op, a, b, c, words, want):
        cases.append((op, a, b, c, words, want))

    # edge framing
    edge_inputs = [b'', b'\n', b'\r\n', b'\r', b'\n\n', b'a', b'a\n', b'a\r\n', b'a\r', b'a\nb', b'a\nb\n', b'\nb',
                   b'ab\r\ncd\r\n', b'a\n\r\nb\n\nc', b'x\r\r\n', b'{"a":1}\n{"b":2}\n{"c"',
                   b'a' * 65535 + b'\n', b'a' * 65536, b'ab\n' * 21845 + b'a', b'\n' * 65536,
                   b'a' * 65537, b'a\n' * 32768 + b'b']
    for data in edge_inputs:
        for tail in (False, True):
            for cut in (False, True):
                add('edge', int(tail), int(cut), 0, enc(data), edge_oracle(data, tail, cut))

    # window framing
    small = [b'', b'\n', b'\r\n', b'\r', b'\n\n', b'a', b'a\n', b'a\nb', b'a\r\nb\r\n', b'abc\ndef\n', b'\nabc\n',
             b'abc\n', b'x\r\r\n', b'a\n\nb\n', b'ab\ncd\nef', b'\r\n\r\n', b'{"x":1}\r\n{"y":2}\n{"z"']
    big = []
    for raw in (1048575, 1048576, 1048577):
        for cr in (False, True):
            line = big_line(raw, cr)
            big += [line + b'\n', line + b'\nok\n', b'k\n' + line + b'\nz\ny\n']
    big += [b'a\n' + b'a' * 1048577,                       # oversized unterminated final range
            b'a\n' + b'a' * 1048576,                       # short enough: ignored
            b'a\n' + b'a' * 1048575 + b'\r',               # CR counts, still ignored
            b'a' * 1048577, b'a' * 1048576, b'a' * 9000 + b'\n',
            b'a' * 1048577 + b'\n' + b'b' * 1048580 + b'\nz\n',   # two oversized lines: one event each
            b'a' * 1048577 + b'\n\n' + b'c' * 1048577,
            b'\n' + b'a' * 1048577 + b'\nq\n',
            b'a' * 8388608]
    for data in small + big:
        for cut in (False, True):
            add('window', int(cut), 0, 0, enc(data), window_oracle(data, cut))
    add('limit', 0, 0, 0, '', [1, 8388608])

    # packets
    for name, meta, turns, text, valid in packet_cases():
        add('packet', len(meta), len(turns), 0, enc(list(meta) + list(turns) + list(text)),
            packet_expect(meta, turns, text))
    for code, pos in [(1, 5), (2, 0), (1, 0), (2, 123456)]:
        add('failed', code, pos, 0, '', [code, pos])
    add('failed', 0, 7, 0, '', [2, 7])  # code 0 would collide with the success tag

    # copy_span through copy_probe
    for dst, at, src, lo, hi in [
            (b'abcdef', 2, b'XYZW', 1, 3), (b'abcdef', 0, b'XYZW', 0, 0), (b'ab', 0, b'cd', 0, 2),
            (b'abcdef', 4, b'XY', 0, 2), (b'abcdef', 6, b'XY', 1, 1), (b'', 0, b'', 0, 0), (b'abc', 1, b'', 0, 0),
            (b'abcdef', 5, b'XY', 0, 2), (b'abcdef', 0, b'XY', 1, 0), (b'abcdef', 0, b'XY', 0, 3),
            (b'abcdef', -1, b'XY', 0, 1), (b'abcdef', 7, b'XY', 0, 0), (b'abcdef', 0, b'XY', -1, 1),
            (b'abcdef', 0, b'XYZ', 0, 7), (b'a\x00\xff', 1, b'\xfe\x00', 0, 2)]:
        add('probe', at, lo, hi, enc([len(dst)] + list(dst) + list(src)), probe_expect(dst, at, src, lo, hi))
    return cases


def configure():
    WORK.mkdir(parents=True, exist_ok=True)
    os.environ['TMPDIR'] = str(WORK)
    spec = importlib.util.spec_from_file_location('a2_setup', HERE.parent / 'json' / 'run_a2.py')
    setup = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(setup)
    setup.WORK = WORK
    return setup.configure(), setup.run


def main():
    g2, run = configure()
    cases = fixtures()
    payload = ''.join(f'{op} {a} {b} {c} {words}\n' for op, a, b, c, words, _ in cases)
    expected = [' '.join(map(str, want)) for *_, want in cases]
    failed = False
    for compiler in ('py', 'rs'):
        for backend in ('rust', 'llvm'):
            key = f'{compiler}/{backend}'
            try:
                work = WORK / f'{compiler}_{backend}'
                work.mkdir(exist_ok=True)
                compiled = g2.compile_pruv(compiler, str(HERE / 'a0_root.pruv'), str(work), backend)
                if compiled['rc'] != 0:
                    raise RuntimeError('compile/verify failed: ' + str(compiled['errors'] or compiled['stderr']))
                print(f'{key}: verified and compiled', flush=True)
                harness = work / 'main.rs'
                harness.write_text(HARNESS.replace('@SOL@', compiled['rs']))
                extra = []
                if compiled['ll']:
                    extra, error = g2.build_llvm_objects(compiled['ll'], 'a0', str(work))
                    if error:
                        raise RuntimeError(error)
                exe = work / 'runner'
                run([g2.RUSTC, '-O', '--edition', '2021', harness, '-o', exe] + extra)
                got = run([exe], payload).splitlines()
                if len(got) != len(expected):
                    raise RuntimeError(f'{len(got)} answers for {len(expected)} fixtures')
                bad = [(i, w, g) for i, (w, g) in enumerate(zip(expected, got)) if w != g]
                for i, w, g in bad:
                    print(f'{key}: fixture {i} {cases[i][0]}: expected {w[:200]}, got {g[:200]}')
                failed |= bool(bad)
                print(f'{key}: {len(cases) - len(bad)}/{len(cases)} fixtures passed', flush=True)
            except Exception as exc:
                failed = True
                print(f'{key}: ERROR {exc}', file=sys.stderr, flush=True)
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
