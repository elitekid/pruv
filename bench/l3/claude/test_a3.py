#!/usr/bin/env python3
"""L3-1 A3 fixtures: the turn collector (turns.pruv) on py/rust, py/llvm, rs/rust, rs/llvm.

Each fixture is a transition program (see a3_root.pruv) run on fresh collector state. The oracle is independent of
the Pruv code: drafts are an ordinary Python list, transitions follow tail.ts TurnCollector with the spec policies
(longest whole-scalar prefix, genuine U+FFFD kept), and the final suffix is selected from the END of the list; there
is no ring, no slot arithmetic and no packing cursor shared with the implementation. Inputs and outputs travel as
decimal words with `v*k` run-length repeats.

Program words: [base, ops...]; ops [1,text,stamp] begin, [2] skip_user, [3,text,stamp] answer, [4] tool, [5] snapshot;
spec [n, plen, pattern...] = n bytes cycling through the pattern. Result:
[0, nsnap, kept, trimmed, total, ...snapshots(12 each), ...turns(10 each), ...text bytes].
"""
import importlib.util
from itertools import groupby
import os
from pathlib import Path
import shutil
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
JSON_DIR = HERE.parent / 'json'
WORK = HERE / 'work' / 'a3'

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
fn rle(v: &[i64]) -> String {
 let mut parts: Vec<String> = Vec::new();
 let mut i = 0;
 while i < v.len() {
  let mut j = i;
  while j < v.len() && v[j] == v[i] { j += 1; }
  let k = j - i;
  if k >= 4 { parts.push(format!("{}*{}", v[i], k)); } else { for _ in 0..k { parts.push(v[i].to_string()); } }
  i = j;
 }
 parts.join(" ")
}
fn main() {
 for line in io::stdin().lock().lines() {
  let line = line.unwrap();
  let mut words = line.split_whitespace();
  let op = words.next().unwrap();
  let prog = expand(words.collect());
  let out: Vec<i64> = match op {
   "run" => sol::run(&prog),
   _ => panic!("unknown fixture"),
  };
  println!("{}", rle(&out));
 }
}
'''

LIM = 32768          # prompt and reply cap per draft
TOTAL = 2097152      # retained prompt+reply bytes
MAXTURNS = 200


def enc(values):
    """Run-length word encoding of an int sequence (same grouping as the Rust harness)."""
    words = []
    for v, grp in groupby(values):
        k = len(list(grp))
        words.append(f'{v}*{k}' if k >= 4 else ' '.join([str(v)] * k))
    return ' '.join(w for w in words if w)


# ---------------- program construction ----------------
class Tx:
    """n bytes, byte i = pat[i % len(pat)]."""

    def __init__(self, pat, n):
        self.pat, self.n = pat, n

    def data(self):
        if self.n == 0:
            return b''
        return (self.pat * (self.n // len(self.pat) + 1))[:self.n]


def T(x):
    if isinstance(x, Tx):
        t = x
    else:
        b = b'' if x is None else x.encode() if isinstance(x, str) else bytes(x)
        if len(b) > 4096:
            raise ValueError('literal too long, use rep()')
        t = Tx(b, len(b))
    t.data().decode('utf-8')  # every fixture text must be valid UTF-8 (the root rejects anything else)
    return t


def rep(pattern, n):
    return Tx(pattern.encode(), n)


def ts(i):
    s = f'2025-02-{i:02d}T10:20:30.{i:03d}Z'
    assert len(s) == 24
    return s


def S(stamp):
    t = T(stamp)
    assert t.n in (0, 24), 'a stamp is absent or 24 bytes'
    return t


def B(prompt, stamp=None):
    return ('begin', T(prompt), S(stamp))


def A(text, stamp=None):
    return ('answer', T(text), S(stamp))


SK = ('skip',)
TL = ('tool',)
SN = ('snap',)


def spec(t):
    return [t.n, len(t.pat)] + list(t.pat)


def words(base, ops):
    w = [base]
    for op in ops:
        if op[0] == 'begin':
            w += [1] + spec(op[1]) + spec(op[2])
        elif op[0] == 'skip':
            w += [2]
        elif op[0] == 'answer':
            w += [3] + spec(op[1]) + spec(op[2])
        elif op[0] == 'tool':
            w += [4]
        elif op[0] == 'snap':
            w += [5]
        else:
            raise ValueError(op)
    return w


# ---------------- oracle (plain list of drafts, suffix chosen from the end) ----------------
def clip(b, mx):
    """Longest whole-scalar UTF-8 prefix within mx bytes (valid input only; genuine U+FFFD is kept)."""
    if len(b) <= mx:
        return b
    return b[:mx].decode('utf-8', 'ignore').encode('utf-8')


def oracle(base, ops):
    drafts, cur, lost, snaps = [], None, False, []
    for op in ops:
        kind = op[0]
        if kind == 'begin':
            prompt, stamp = op[1].data(), op[2].data()
            long = len(prompt) > LIM or lost
            lost = False
            cur = {'prompt': clip(prompt, LIM), 'reply': b'', 'used': 0, 'tools': 0, 'created': stamp or None,
                   'completed': None, 'clipped': long}
            drafts.append(cur)
        elif kind == 'skip':
            cur, lost = None, True
        elif kind == 'answer':
            text, stamp = op[1].data(), op[2].data()
            if cur is None:
                continue
            if stamp:
                cur['completed'] = stamp
            if not text or cur['used'] >= LIM:
                continue
            piece = b'\n\n' + text if cur['reply'] else text
            room = LIM - cur['used']
            if len(piece) <= room:
                cur['reply'] += piece
                cur['used'] += len(piece)
            else:
                cur['reply'] += clip(piece, room)
                cur['used'] = LIM
                cur['clipped'] = True
        elif kind == 'tool':
            if cur is not None:
                cur['tools'] += 1
        elif kind == 'snap':
            if not drafts:
                snaps.append([0, 0, int(lost), 0, 0, 0, 0, 0, 0, 0, 0, -1])
            else:
                d = drafts[-1]
                snaps.append([len(drafts), int(cur is not None), int(lost), (len(drafts) - 1) % 200, len(d['prompt']),
                              len(d['reply']), d['used'], d['tools'], int(d['clipped']), int(d['created'] is not None),
                              int(d['completed'] is not None), len(drafts) - 1])
    # newest-first scan on the plain list; stop at the first draft that does not fit
    kept, total = [], 0
    for d in reversed(drafts):
        if len(kept) >= MAXTURNS:
            break
        size = len(d['prompt']) + len(d['reply'])
        if total + size > TOTAL:
            break
        total += size
        kept.append(d)
    kept.reverse()
    cursor, turns, text = base, [], bytearray()
    for d in kept:
        rec = [cursor, len(d['prompt'])]
        cursor += len(d['prompt'])
        rec += [cursor, len(d['reply'])]
        cursor += len(d['reply'])
        for stamp in (d['created'], d['completed']):
            if stamp is None:
                rec += [-1, 0]
            else:
                rec += [cursor, len(stamp)]
                cursor += len(stamp)
        rec += [d['tools'], int(d['clipped'])]
        turns += rec
        text += d['prompt'] + d['reply'] + (d['created'] or b'') + (d['completed'] or b'')
    flat = [x for s in snaps for x in s]
    return [0, len(snaps), len(kept), int(len(kept) < len(drafts)), total] + flat + turns + list(text)


def selfcheck():
    """Hand-derived expectations that keep the oracle itself honest."""
    B8 = lambda s: list(s.encode())
    # prompt "ab", replies "cd","ef": reply "cd\n\nef", total 2+6
    got = oracle(0, [B('ab'), A('cd'), A('ef')])
    assert got == [0, 0, 1, 0, 8] + [0, 2, 2, 6, -1, 0, -1, 0, 0, 0] + B8('abcd') + [10, 10] + B8('ef'), got
    # a skipped user marks the next draft clipped
    got = oracle(0, [SK, B('a')])
    assert got == [0, 0, 1, 0, 1] + [0, 1, 1, 0, -1, 0, -1, 0, 0, 1] + [97], got
    # separator-only partial append: room 2, piece "\n\nbb" cut to "\n\n"
    got = oracle(0, [B('a'), A(rep('x', 32766)), A('bb')])
    assert got[:5] == [0, 0, 1, 0, 32769] and got[5:15] == [0, 1, 1, 32768, -1, 0, -1, 0, 0, 1], got[:15]
    assert len(got) == 15 + 32769 and got[-2:] == [10, 10]
    # multibyte saturation gap: room 4, piece "\n\n€" (5 bytes) cuts to "\n\n"; a later answer is ignored
    got = oracle(0, [B('p'), A(rep('a', 32764)), A('€'), A('z'), SN])
    assert got[5:17] == [1, 1, 0, 0, 1, 32766, 32768, 0, 1, 0, 0, 0], got[5:17]
    assert got[17:27] == [0, 1, 1, 32766, -1, 0, -1, 0, 0, 1] and got[-2:] == [10, 10]
    # empty text and orphan updates: stamp of the empty answer is kept, orphan answer is dropped
    got = oracle(0, [A('x', ts(1)), B('p', ts(2)), A('', ts(3))])
    assert got[5:15] == [0, 1, 1, 0, 1, 24, 25, 24, 0, 0], got[5:15]
    assert bytes(got[15:]) == b'p' + ts(2).encode() + ts(3).encode()
    # 32 full drafts hit the total cap exactly, a 33rd evicts the oldest by size
    full = [x for _ in range(32) for x in (B(rep('a', LIM)), A(rep('b', LIM)))]
    assert oracle(0, full)[2:5] == [32, 0, TOTAL]
    assert oracle(0, full + [B(rep('a', LIM)), A(rep('b', LIM))])[2:5] == [32, 1, TOTAL]
    # 201 drafts: the oldest falls off the 200 cap
    got = oracle(0, [B(f'q{i}') for i in range(201)])
    assert got[2:4] == [200, 1], got[:5]
    # the oldest kept draft (q1) starts the text; the newest (q200) is last
    assert got[5] == 0 and got[6] == 2 and bytes(got[5 + 2000:5 + 2000 + 2]) == b'q1', got[5:8]
    assert bytes(got[5 + 2000:])[-4:] == b'q200'


# ---------------- fixtures ----------------
def sized(pairs, stamps=False):
    ops = []
    for p, r in pairs:
        ops.append(B(rep('a', p), ts(1) if stamps else None))
        if r:
            ops.append(A(rep('b', r), ts(2) if stamps else None))
    ops.append(SN)
    return ops


def many(n, skips=False):
    ops = []
    for i in range(n):
        if skips and i % 7 == 3:
            ops.append(SK)
        ops.append(B(f'prompt {i}', ts(i % 28 + 1) if i % 3 == 0 else None))
        if i % 2 == 0:
            ops.append(A(f'reply {i}', ts((i + 5) % 28 + 1)))
        if i % 5 == 0:
            ops.append(TL)
    ops.append(SN)
    return ops


def fixtures():
    cases = []

    def add(name, ops, base=0):
        cases.append((name, words(base, ops), oracle(base, ops)))

    # orphans before any draft
    add('orphan answer/tool', [A('x', ts(1)), TL, SN, A('y'), SN, TL, SN])
    add('orphan then begin', [A('o', ts(1)), TL, B('p'), SN, A('a'), TL, SN])
    # repeated skips and lost_before
    add('repeated skips', [B('a'), A('r1'), SK, SK, A('lost', ts(1)), TL, SN, B('b'), SN, A('r2'), B('c'), SN])
    add('skip first', [SK, B('a'), SN, A('x'), SN])
    add('skip skip begin', [SK, SK, SK, B('a'), SN, B('b'), SN])
    add('skip keeps earlier draft', [B('a'), A('r'), SK, SN, A('ignored'), TL, SN, B('b'), A('s'), SN])
    add('skip after skip then answer', [B('a'), SK, A('x'), SK, TL, SN])
    add('skip only', [SK, SN, SK, SN])
    # prompt clipped but reply grows
    add('clipped prompt, growing reply', [B(rep('a', 40000)), SN, A('x'), SN, A('y'), SN, A('z', ts(3)), SN])
    add('lost clip, short prompt, reply grows', [SK, B('short'), SN, A('x'), A('y'), SN])
    add('lost clip, long prompt', [SK, B(rep('a', LIM + 1)), SN])
    # cap +-1 for prompts (including multibyte cuts)
    for pat, ns in [('a', (LIM - 1, LIM, LIM + 1, LIM + 2)), ('é', (16383 * 2, 16384 * 2, 16385 * 2)),
                    ('€', (10921 * 3, 10922 * 3, 10923 * 3, 10924 * 3)), ('\U0001F600', (8191 * 4, 8192 * 4, 8193 * 4)),
                    ('ab€', (6553 * 5, 6553 * 5 + 5 - 3 + 0, 6554 * 5)), ('a€', (8191 * 4, 8192 * 4, 8193 * 4))]:
        for n in ns:
            try:
                add(f'prompt cap {pat!r}*{n}', [B(rep(pat, n)), SN, A('r'), SN])
            except UnicodeDecodeError:
                pass
    add('prompt cut mid scalar', [B(Tx('ab€'.encode(), 6553 * 5 + 5)), SN])
    add('prompt cut mid scalar 2', [B(Tx('a\U0001F600'.encode(), 6554 * 5)), SN])
    # reply cap +-1: one answer
    for pat, ns in [('a', (LIM - 1, LIM, LIM + 1, LIM + 2)), ('€', (10922 * 3, 10923 * 3)), ('é', (16384 * 2, 16385 * 2)),
                    ('\U0001F600', (8192 * 4, 8193 * 4, 8194 * 4))]:
        for n in ns:
            add(f'reply cap {pat!r}*{n}', [B('p'), A(rep(pat, n)), SN, A('more', ts(1)), SN])
    # reply cap +-1: second answer with separator (room exactly fits / one short / one more)
    for first in (LIM - 7, LIM - 6, LIM - 5, LIM - 4, LIM - 3, LIM - 2, LIM - 1, LIM):
        for text in ('b', 'bb', 'bbb', 'bbbb'):
            add(f'sep room first={first} text={text}', [B('p'), A(rep('a', first)), SN, A(text), SN, A('z'), SN])
    # separator-only and one-byte partial append
    add('separator only partial', [B('p'), A(rep('a', LIM - 2)), A('bb'), SN, A('c', ts(1)), SN])
    add('one separator byte partial', [B('p'), A(rep('a', LIM - 1)), A('b'), SN])
    add('one separator byte before scalar', [B('p'), A(rep('a', LIM - 1)), A('€'), SN])
    # multibyte saturation gap: counter saturates though actual length is shorter
    add('gap after separator + 3-byte scalar', [B('p'), A(rep('a', LIM - 4)), A('€'), SN, A('z'), SN])
    add('gap after separator + 4-byte scalar', [B('p'), A(rep('a', LIM - 5)), A('\U0001F600'), SN, A('z', ts(1)), SN])
    add('gap first piece 3-byte cut', [B('p'), A(rep('€', 10923 * 3)), SN, A('z'), SN, A(''), SN])
    add('gap first piece 4-byte cut', [B('p'), A(rep('\U0001F600', 8193 * 4)), SN, A('z'), SN])
    add('gap with room for 2 after separator', [B('p'), A(rep('a', LIM - 6)), A('€€'), SN, A('q'), SN])
    add('gap multibyte then another draft', [B('p'), A(rep('a', LIM - 4)), A('€'), B('q'), A('r'), SN])
    # time updates
    add('empty text updates time', [B('p'), A('', ts(1)), SN, A('', None), SN, A('x', ts(2)), SN, A('', ts(3)), SN])
    add('empty text without time', [B('p'), A(''), SN, A('', None), SN])
    add('full reply updates time', [B('p'), A(rep('a', LIM)), SN, A('late', ts(1)), SN, A('', ts(2)), SN, A('later'), SN])
    add('clipped reply updates time', [B('p'), A(rep('a', LIM + 5)), SN, A('late', ts(4)), SN])
    add('time replaced each answer', [B('p', ts(1)), A('a', ts(2)), A('b', ts(3)), A('c'), SN])
    add('created kept, completed reset per draft', [B('a', ts(1)), A('x', ts(2)), B('b'), SN, A('y'), B('c', ts(5)), SN])
    add('tool does not update time', [B('p', ts(1)), TL, TL, SN, A('x'), TL, SN])
    # tools
    add('tools counting', [TL, B('p'), TL, TL, A('x'), TL, SN, SK, TL, TL, SN, B('q'), TL, SN])
    add('tools survive finish', [B('a'), TL, TL, TL, B('b'), B('c'), TL])
    # answers join with separators
    add('pieces join', [B('p'), A('a'), A('b'), A(''), A('c'), SN])
    add('empty first piece then text', [B('p'), A(''), A('a'), A(''), SN, A('b'), SN])
    add('utf-8 pieces', [B('café €'), A('\U0001F600 x', ts(1)), A('あ', ts(2)), SN], base=1234)
    add('base offset', [B('a', ts(1)), A('b', ts(2)), B('c'), A('d')], base=7)
    add('base offset large', [B('a'), A('b', ts(2))], base=3500000)
    add('empty prompt', [B(''), A('x'), SN])
    add('FFFD kept', [B('a��'), A(rep('�', 10923 * 3)), SN])
    # draft counts and the 200 ring
    for n in (1, 2, 199, 200, 201, 202, 399, 400, 401, 450):
        add(f'{n} drafts', many(n))
    add('201 drafts with skips', many(201, skips=True))
    add('250 drafts with skips', many(250, skips=True))
    ops = [B(f'p{i}') for i in range(200)] + [SN, A('late', ts(1)), SN]
    add('answer to newest after exactly 200', ops)
    ops = [B(f'p{i}') for i in range(201)] + [SN, A('late', ts(1)), TL, SN]
    add('answer to newest after eviction', ops)
    add('skip after 200 drafts', [B(f'p{i}') for i in range(200)] + [SK, SN, B('x'), SN])
    add('skip after 201 drafts', [B(f'p{i}') for i in range(201)] + [SK, A('no'), SN, B('x'), A('yes'), SN])
    # total cap: exact, overflow, stop at the first unfit draft
    big = (LIM, LIM)
    add('32 full drafts exact cap', sized([big] * 32))
    add('33 full drafts overflow', sized([big] * 33))
    add('31 full drafts', sized([big] * 31))
    add('tiny oldest excluded at exact cap', sized([(1, 0)] + [big] * 32))
    add('tiny newest then 31 full', sized([big] * 32 + [(1, 1)]))
    add('exact cap by 65535 + 1', sized([(LIM, LIM - 1)] + [big] * 31 + [(1, 0)]))
    add('stop at first unfit (older small fits)', sized([(10, 10), big] + [big] * 31 + [(1, 1)]))
    add('stop at first unfit, no older', sized([big] + [big] * 31 + [(1, 1)]))
    add('cap with stamps (not counted)', sized([big] * 33, stamps=True))
    add('stamps with exact cap', sized([big] * 32, stamps=True))
    add('250 drafts of 10000 bytes (200 cap first)', sized([(5000, 5000)] * 250))
    add('250 drafts of 40000 bytes (total cap first)', sized([(20000, 20000)] * 250))
    add('wrap then cap', sized([(30000, 20000)] * 450))
    add('mixed sizes at the cap', sized([(10, 0), (32768, 32768), (5, 5), (32768, 32767), (7, 7)] * 8))
    add('empty replies at the cap', sized([(LIM, 0)] * 80))
    add('unanswered last prompt', [B('a'), A('x'), B('b')])
    add('lost clip only on next draft', [B('a'), SK, B('b'), B('c')])
    return cases


def configure():
    WORK.mkdir(parents=True, exist_ok=True)
    os.environ['TMPDIR'] = str(WORK)
    spec_ = importlib.util.spec_from_file_location('a2_setup', JSON_DIR / 'run_a2.py')
    setup = importlib.util.module_from_spec(spec_)
    spec_.loader.exec_module(setup)
    setup.WORK = WORK
    return setup.configure(), setup.run


def main():
    selfcheck()
    cases = fixtures()
    g2, run = configure()
    # The str adapter crate (UTF-8 representation conversion), as in test_a1.py.
    target = WORK / 'str-adapter'
    run([shutil.which('cargo') or str(Path.home() / '.cargo/bin/cargo'), 'build', '--release', '--offline', '--quiet',
         '--manifest-path', JSON_DIR / 'str_adapter/Cargo.toml', '--target-dir', target])
    rlib, deps = target / 'release/libpruv_str.rlib', target / 'release/deps'
    flags = ['--rust-extern', f'pruv_str={rlib}', '--rust-search', str(deps)]
    rustflags = ['--extern', f'pruv_str={rlib}', '-L', f'dependency={deps}']
    payload = ''.join('run ' + enc(w) + '\n' for _, w, _ in cases)
    expected = [enc(want) for *_, want in cases]
    failed = False
    for compiler in ('py', 'rs'):
        for backend in ('rust', 'llvm'):
            key = f'{compiler}/{backend}'
            try:
                work = WORK / f'{compiler}_{backend}'
                work.mkdir(exist_ok=True)
                compiled = g2.compile_pruv(compiler, str(HERE / 'a3_root.pruv'), str(work), backend, flags)
                if compiled['rc'] != 0:
                    raise RuntimeError('compile/verify failed: ' + str(compiled['errors'] or compiled['stderr']))
                print(f'{key}: verified and compiled', flush=True)
                harness = work / 'main.rs'
                harness.write_text(HARNESS.replace('@SOL@', compiled['rs']))
                extra = []
                if compiled['ll']:
                    extra, error = g2.build_llvm_objects(compiled['ll'], 'a3', str(work))
                    if error:
                        raise RuntimeError(error)
                exe = work / 'runner'
                run([g2.RUSTC, '-O', '--edition', '2021', harness, '-o', exe] + extra + rustflags)
                got = run([exe], payload).splitlines()
                if len(got) != len(expected):
                    raise RuntimeError(f'{len(got)} answers for {len(expected)} fixtures')
                bad = [(i, w, g) for i, (w, g) in enumerate(zip(expected, got)) if w != g]
                for i, w, g in bad[:20]:
                    print(f'{key}: fixture {i} {cases[i][0]}: expected {w[:240]}, got {g[:240]}')
                failed |= bool(bad)
                print(f'{key}: {len(cases) - len(bad)}/{len(cases)} fixtures passed', flush=True)
            except Exception as exc:
                failed = True
                print(f'{key}: ERROR {exc}', file=sys.stderr, flush=True)
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
