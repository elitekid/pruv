#!/usr/bin/env python3
"""A5 JSON Lines fixtures on Python/Rust compilers and Rust/LLVM backends."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = HERE / 'work' / 'a5'

HARNESS = r'''#![allow(dead_code, unused_imports)]
#[path = "@SOL@"] mod sol;
use std::io::{self, BufRead};
fn main() {
 for line in io::stdin().lock().lines() {
  let line = line.unwrap();
  let mut words = line.split_whitespace();
  let op = words.next().unwrap();
  let a: i64 = words.next().unwrap().parse().unwrap();
  let b: i64 = words.next().unwrap().parse().unwrap();
  let c: i64 = words.next().unwrap().parse().unwrap();
  let data: Vec<u8> = words.map(|x| x.parse().unwrap()).collect();
  let out = match op {
   "split" => sol::split(&data,a != 0),
   "import" => sol::import_lines(&data,a),
   "range" => sol::range_summary(&data,a,b),
   "absolute" => vec![sol::absolute_offset(a,b,c)],
   "limit" => {
    // One oversized-range fixture, with enclosing bytes outside the selected range.
    let mut big = vec![b' ';16777219]; big[0] = 255;
    sol::range_summary(&big,1,16777218)
   },
   _ => panic!("unknown fixture"),
  };
  println!("{}",out.iter().map(|x| x.to_string()).collect::<Vec<_>>().join(" "));
 }
}
'''


def split_oracle(data, final):
    """Independent delimiter slicing, including the retained nonfinal tail offset."""
    out = []
    start = 0
    for end, byte in enumerate(data):
        if byte == 10:
            stop = end - 1 if end > start and data[end - 1] == 13 else end
            out.extend((start, stop, end + 1))
            start = end + 1
    if final and start < len(data):
        out.extend((start, len(data), len(data)))
        start = len(data)
    return out + [0 if final else 1, start]


class Number(str):
    pass


class Object(list):
    pass


def reject_constant(value):
    raise ValueError(value)


def record_count(value):
    if isinstance(value, Object):
        return 1 + sum(1 + record_count(v) for _, v in value)
    if isinstance(value, list):
        return 1 + sum(map(record_count, value))
    return 1


def accepted(data):
    try:
        value = json.loads(data.decode('utf-8', errors='strict'), strict=True,
                           parse_int=Number, parse_float=Number,
                           parse_constant=reject_constant, object_pairs_hook=Object)
        return record_count(value)
    except (UnicodeDecodeError, ValueError):
        return 0


# Exact Pruv diagnostics are fixed expectations, independent of host error wording.
ERRORS = {b'': (0, 5), b' \t': (2, 5), b'\r': (1, 5),
          b'{bad}': (1, 7), b'{"x":': (5, 5), b'"x\ry"': (2, 16),
          b'\xff': (0, 4), b'NaN': (0, 6), b'[1,]': (3, 10),
          b'\xef\xbb\xbfnull': (0, 6)}


def import_oracle(data, base):
    triples = split_oracle(data, True)[:-2]
    out = []
    for i in range(0, len(triples), 3):
        start, end, _ = triples[i:i + 3]
        record = data[start:end]
        count = accepted(record)
        if count:
            out.extend((i // 3 + 1, 1, -1, 0, count))
        else:
            pos, kind = ERRORS[record]
            absolute = base + start + pos
            if base < 0 or absolute > 2**63 - 1:
                absolute = -1
            out.extend((i // 3 + 1, 0, absolute, kind, 0))
    return out


def fixtures():
    cases = []
    def add(op, data, want, a=0, b=0, c=0):
        cases.append((op, a, b, c, data, want))
    files = [b'', b'0', b'0\n', b'0\r\n', b'0\ntrue\r\nnull',
             b'\n', b'\r\n', b'\n\n', b' \t\n0\n', b'0\r', b'\r',
             b'"x\ry"\nnull', b'0\n{bad}\ntrue\n', b'0\n{"x":',
             b'{"x":', b'0\n\n', b'0\r\r\n', b'\xff\ntrue',
             b'NaN\n[1,]\nnull', b'\xef\xbb\xbfnull\n0',
             '"한글"\n{"a": [1,true],"a":null}\r\n'.encode(),
             b'{"n":0}\n' * 2000]
    for data in files:
        for final in (False, True):
            add('split', data, split_oracle(data, final), int(final))
        add('import', data, import_oracle(data, 123), 123)
    add('import', b'0\n{bad}\ntrue', import_oracle(b'0\n{bad}\ntrue', -1), -1)
    add('import', b'0\n{bad}', import_oracle(b'0\n{bad}', 2**63-1), 2**63-1)
    for data, lo, hi, want in [
        (b'xx[1,]yy', 2, 6, [0, 3, 10, 0, 0]),
        (b'\xff {"a":0}garbage', 2, 9, [1, -1, 0, 3, 7]),
        (b'xx\xffyy', 2, 3, [0, 0, 4, 0, 0]),
        (b'xx', 1, 1, [0, 0, 5, 0, 0])]:
        add('range', data, want, lo, hi)
    add('limit', b'', [0, 0, 1, 0, 0])
    for a, b, c in [(0,0,0),(100,20,3),(2**63-1,0,0),(2**63-2,1,1),
                    (2**63-1,1,0),(0,2**63-1,1),(-1,0,0),(0,-1,0),
                    (0,0,-1),(-2**63,0,0)]:
        want = a+b+c if min(a,b,c) >= 0 and a+b+c <= 2**63-1 else -1
        add('absolute', b'', [want], a, b, c)
    return cases


def configure():
    WORK.mkdir(parents=True, exist_ok=True)
    os.environ['TMPDIR'] = str(WORK)
    spec = importlib.util.spec_from_file_location('a2_setup', HERE / 'run_a2.py')
    setup = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(setup)
    setup.WORK = WORK
    return setup.configure(), setup.run


def main():
    g2, run = configure()
    cases = fixtures()
    payload = ''.join(' '.join(map(str, (op,a,b,c,*data)))+'\n'
                      for op,a,b,c,data,_ in cases)
    expected = [' '.join(map(str, want)) for *_, want in cases]
    failed = False
    for compiler in ('py', 'rs'):
        for backend in ('rust', 'llvm'):
            key = f'{compiler}/{backend}'
            try:
                work = WORK / f'{compiler}_{backend}'
                work.mkdir(exist_ok=True)
                compiled = g2.compile_pruv(compiler, str(HERE/'a5_root.pruv'), str(work), backend)
                if compiled['rc'] != 0:
                    raise RuntimeError('compile/verify failed: '+str(compiled['errors'] or compiled['stderr']))
                print(f'{key}: verified and compiled', flush=True)
                harness = work/'main.rs'
                harness.write_text(HARNESS.replace('@SOL@', compiled['rs']))
                extra = []
                if compiled['ll']:
                    extra, error = g2.build_llvm_objects(compiled['ll'], 'a5', str(work))
                    if error:
                        raise RuntimeError(error)
                exe = work/'runner'
                run([g2.RUSTC, '-O', '--edition', '2021', harness, '-o', exe]+extra)
                got = run([exe], payload).splitlines()
                if len(got) != len(expected):
                    raise RuntimeError(f'{len(got)} answers for {len(expected)} fixtures')
                bad = [(i,w,g) for i,(w,g) in enumerate(zip(expected,got)) if w != g]
                for i,w,g in bad:
                    print(f'{key}: fixture {i} {cases[i][0]}: expected {w[:200]}, got {g[:200]}')
                failed |= bool(bad)
                print(f'{key}: {len(cases)-len(bad)}/{len(cases)} fixtures passed', flush=True)
            except Exception as exc:
                failed = True
                print(f'{key}: ERROR {exc}', file=sys.stderr, flush=True)
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
