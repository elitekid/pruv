#!/usr/bin/env python3
"""JSON batch A0: verify json.pruv with both compilers and run hand-built tape fixtures.

For compiler py|rs and backend rust|llvm, json.pruv is compiled (the compile step verifies it), a small
Rust harness feeds every fixture to check_tape (one line per fixture: input_length then the tape slots)
and the true/false answers are compared with the expected ones. Valid tapes must give true, malformed
tapes false. All writes stay in bench/l3/json/work.
Usage: run_a0.py [--verify-only]
"""
import argparse
import importlib.util
import os
from pathlib import Path
import subprocess
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = HERE / 'work'

HARNESS = '''#![allow(dead_code, unused_imports)]
#[path = "@SOL@"] mod sol;
use std::io::{self, BufRead};
fn main() {
  for line in io::stdin().lock().lines() {
    let line = line.unwrap();
    let mut it = line.split(' ');
    let len: i64 = it.next().unwrap().parse().unwrap();
    let v: Vec<i64> = it.filter(|x| !x.is_empty()).map(|x| x.parse().unwrap()).collect();
    println!("{}", sol::check_tape(&v, len));
  }
}
'''

NUL, FALSE, TRUE, NUM, STR, ARR, OBJ, KEY = range(8)


def tape(*records):
    return [x for rec in records for x in rec]


# `{"a":[1,true],"b":null}` (23 bytes): object, key, array, number, true, key, null
MIX = [[OBJ, 0, 23, 7, -1, 2], [KEY, 1, 4, 2, 0, 0], [ARR, 5, 13, 5, 0, 2], [NUM, 6, 7, 4, 2, 0],
       [TRUE, 8, 12, 5, 2, 0], [KEY, 14, 17, 6, 0, 0], [NUL, 18, 22, 7, 0, 0]]
# `{"a":1,"a":2}` (13 bytes): duplicate keys stay on the tape
DUP = [[OBJ, 0, 13, 5, -1, 2], [KEY, 1, 4, 2, 0, 0], [NUM, 5, 6, 3, 0, 0], [KEY, 7, 10, 4, 0, 0],
       [NUM, 11, 12, 5, 0, 0]]
# `[[],{}]` (7 bytes)
NEST = [[ARR, 0, 7, 3, -1, 2], [ARR, 1, 3, 2, 0, 0], [OBJ, 4, 6, 3, 0, 0]]


def mut(base, rec, slot, value):
    t = list(base) if base and isinstance(base[0], int) else tape(*base)
    t[6 * rec + slot] = value
    return t


# (name, expected, input_length, flat tape)
FIXTURES = [
    ('valid scalar root', True, 1, tape([NUM, 0, 1, 1, -1, 0])),
    ('valid string root', True, 5, tape([STR, 0, 5, 1, -1, 0])),
    ('valid empty array', True, 2, tape([ARR, 0, 2, 1, -1, 0])),
    ('valid empty object', True, 2, tape([OBJ, 0, 2, 1, -1, 0])),
    ('valid nested mix', True, 23, tape(*MIX)),
    ('valid duplicate keys', True, 13, tape(*DUP)),
    ('valid empty containers in array', True, 7, tape(*NEST)),

    ('bad kind 8', False, 1, tape([8, 0, 1, 1, -1, 0])),
    ('bad kind -1', False, 1, tape([-1, 0, 1, 1, -1, 0])),
    ('root is a key', False, 1, tape([KEY, 0, 1, 1, -1, 0])),
    ('bad span empty', False, 1, tape([NUM, 1, 1, 1, -1, 0])),
    ('bad span negative start', False, 1, tape([NUM, -1, 1, 1, -1, 0])),
    ('bad span past input', False, 1, tape([NUM, 0, 2, 1, -1, 0])),
    ('input length zero', False, 0, tape([NUM, 0, 1, 1, -1, 0])),
    ('span end outside parent', False, 23, mut(MIX, 3, 2, 14)),
    ('span start before parent', False, 23, mut(MIX, 3, 1, 4)),
    ('parent is a later record', False, 23, mut(MIX, 3, 4, 4)),
    ('parent is a scalar', False, 23, mut(MIX, 4, 4, 3)),
    ('non-root parent -1', False, 23, mut(MIX, 4, 4, -1)),
    ('root has a parent', False, 23, mut(MIX, 0, 4, 0)),
    ('skip equals record', False, 23, mut(MIX, 3, 3, 3)),
    ('skip before record', False, 23, mut(MIX, 3, 3, 1)),
    ('skip past record count', False, 23, mut(MIX, 6, 3, 8)),
    ('root skip not record count', False, 23, mut(MIX, 0, 3, 6)),
    ('scalar skip not next record', False, 23, mut(MIX, 3, 3, 5)),
    ('child outside parent skip', False, 23, mut(MIX, 2, 3, 4)),
    ('crossing subtrees', False, 23, mut(mut(MIX, 2, 2, 20), 2, 3, 6)),
    ('wrong object count', False, 23, mut(MIX, 0, 5, 3)),
    ('wrong array count', False, 23, mut(MIX, 2, 5, 1)),
    ('empty array nonzero count', False, 2, tape([ARR, 0, 2, 1, -1, 1])),
    ('scalar nonzero count', False, 1, tape([NUM, 0, 1, 1, -1, 1])),
    ('object value in key slot', False, 13, mut(DUP, 1, 0, NUM)),
    ('object key in value slot', False, 13, mut(DUP, 2, 0, KEY)),
    ('key as array child', False, 7, mut(NEST, 1, 0, KEY)),
    ('wrong length too short', False, 23, tape(*MIX)[:-1]),
    ('wrong length too long', False, 23, tape(*MIX) + [0]),
    ('empty tape', False, 1, []),
]


def configure():
    WORK.mkdir(exist_ok=True)
    os.environ['TMPDIR'] = str(WORK)
    spec = importlib.util.spec_from_file_location('g2', ROOT / 'bench/g2/run.py')
    g2 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(g2)
    main = ROOT  # a worktree can read the main checkout's installed tools
    git = ROOT / '.git'
    if git.is_file() and git.read_text().startswith('gitdir: '):
        main = Path(git.read_text().strip()[8:]).resolve().parents[2]
    py = os.environ.get('PRUV_PYTHON') or next(
        (str(p) for p in [ROOT / '.venv/bin/python', main / '.venv/bin/python'] if p.exists()), sys.executable)
    binary = Path(os.environ.get('PRUVC_RS', ROOT / 'pruvc-rs/target/release/pruvc'))
    if not binary.exists():
        binary = main / 'pruvc-rs/target/release/pruvc'
    if not binary.exists():
        raise RuntimeError('pruvc-rs binary not found; build it or set PRUVC_RS')
    g2.COMPILERS = {'py': [py, str(ROOT / 'pruvc/pruvc.py')], 'rs': [str(binary)]}
    return g2


def run(cmd, data=None):
    p = subprocess.run([str(x) for x in cmd], input=data, text=True, capture_output=True, timeout=600)
    if p.returncode:
        raise RuntimeError(f'{cmd}: exit {p.returncode}\n{p.stdout}\n{p.stderr}')
    return p.stdout


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--verify-only', action='store_true', help='only compile (verify) json.pruv')
    args = ap.parse_args()
    g2 = configure()
    payload = ''.join(f'{n} {" ".join(map(str, t))}\n' for _, _, n, t in FIXTURES)
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
                print(f'{key}: json.pruv verified and compiled (rc 0)', flush=True)
                if args.verify_only:
                    continue
                harness = work / 'main.rs'
                harness.write_text(HARNESS.replace('@SOL@', compiled['rs']))
                extra = []
                if compiled['ll']:
                    extra, error = g2.build_llvm_objects(compiled['ll'], 'json', str(work))
                    if error:
                        raise RuntimeError(error)
                exe = work / 'runner'
                run([g2.RUSTC, '-O', '--edition', '2021', harness, '-o', exe] + extra)
                got = run([exe], payload).split()
                if len(got) != len(FIXTURES):
                    raise RuntimeError(f'{len(got)} answers for {len(FIXTURES)} fixtures')
                bad = [(f[0], f[1], g) for f, g in zip(FIXTURES, got) if g != str(f[1]).lower()]
                for name, want, g in bad:
                    print(f'{key}: MISMATCH {name}: expected {str(want).lower()}, got {g}')
                failed |= bool(bad)
                valid = sum(f[1] for f in FIXTURES)
                print(f'{key}: {len(FIXTURES) - len(bad)}/{len(FIXTURES)} fixtures as expected '
                      f'({valid} valid, {len(FIXTURES) - valid} malformed)', flush=True)
            except Exception as exc:
                failed = True
                print(f'{key}: ERROR {exc}', file=sys.stderr, flush=True)
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
