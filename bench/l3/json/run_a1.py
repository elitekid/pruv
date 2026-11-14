#!/usr/bin/env python3
"""A1 lexical fixtures: both compilers and backends; --verify-only skips host fixtures."""
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
    let v: Vec<i64> = line.split_whitespace().map(|x| x.parse().unwrap()).collect();
    let (op, lo, hi) = (v[0], v[1], v[2]);
    let data: Vec<u8> = v[3..].iter().map(|x| *x as u8).collect();
    let out = match op {
      0 => sol::utf8(&data, lo, hi),
      1 => sol::whitespace(&data, lo, hi),
      2 => sol::literal(&data, lo, hi),
      3 => sol::number(&data, lo, hi),
      4 => sol::string(&data, lo, hi),
      _ => panic!("invalid fixture operation"),
    };
    println!("{}", out);
  }
}
'''

def error(kind, position):
    return -(kind * 33554432 + position) - 1


# Expected values are fixed independently of the scanners, never computed by a parser.
# Each fixture is also run inside an offset range with invalid bytes outside it.
FIXTURES = []


def case(name, op, data, want):
    FIXTURES.append((name, op, data, 0, len(data), want))
    if op == 0:
        shifted = -1 if want == -1 else want + 2
    elif want >= 0:
        shifted = want + 2
    else:
        shifted = want - 2
    FIXTURES.append((name + ' offset range', op, b'\xff\x80' + data + b'\xff', 2,
                     len(data) + 2, shifted))


for data in [b'', b'ASCII\x00\x7f', b'\xc2\x80', b'\xdf\xbf', b'\xe0\xa0\x80',
             b'\xed\x9f\xbf', b'\xee\x80\x80', b'\xef\xbf\xbf',
             b'\xf0\x90\x80\x80', b'\xf4\x8f\xbf\xbf', b'A\xc2\xa2\xe2\x82\xac']:
    case('utf8 valid ' + data.hex(), 0, data, -1)
for data in [b'\x80', b'\xbf', b'\xc0\x80', b'\xc1\xbf', b'\xf5\x80\x80\x80',
             b'\xff', b'\xfe', b'\xe0\x80\x80', b'\xed\xa0\x80',
             b'\xf0\x80\x80\x80', b'\xf4\x90\x80\x80',
             b'\xc2', b'\xe2\x82', b'\xf0\x90\x80',
             b'\xc2A', b'\xe2A\x80', b'\xe2\x82A', b'\xf0\x90A\x80',
             b'\xf0\x90\x80A', b'\xe0', b'\xf4']:
    case('utf8 invalid ' + data.hex(), 0, data, 0)
    case('utf8 invalid after ASCII ' + data.hex(), 0, b'ab' + data, 2)
case('utf8 first invalid sequence', 0, b'\xc2\xa2\xed\xa0\x80\xff', 2)

for data, want in [(b'', 0), (b' \t\n\r', 4), (b' \tA ', 2), (b'\x0b', 0),
                   (b'\x0c', 0), (b'\xc2\xa0', 0), (b'\xef\xbb\xbf', 0)]:
    case('whitespace ' + data.hex(), 1, data, want)

for word in [b'true', b'false', b'null']:
    case('literal ' + word.decode(), 2, word, len(word))
    case('literal boundary ' + word.decode(), 2, word + b'X', len(word))
    for n in range(len(word)):
        case('literal truncated ' + str(word[:n]), 2, word[:n], error(5, n))
    for n in range(len(word)):
        bad = word[:n] + b'X' + word[n+1:]
        case('literal typo ' + str(bad), 2, bad, error(12, n))

for data in [b'0', b'-0', b'10', b'1.5', b'1e5', b'1E+5', b'-1.0e-10',
             b'1234567890', b'0.0', b'0e0', b'1e-5', b'1E05', b'9' * 5000,
             b'-' + b'9' * 200, b'1e' + b'9' * 200]:
    case('number valid ' + str(data[:30]), 3, data, len(data))
for data, want in [(b'01', error(13, 1)), (b'-01', error(13, 2)),
                   (b'-', error(5, 1)), (b'1.', error(5, 2)),
                   (b'1e', error(5, 2)), (b'1e+', error(5, 3)),
                   (b'1E-', error(5, 3)), (b'+1', error(13, 0)),
                   (b'.5', error(13, 0)), (b'1.e5', error(13, 2)),
                   (b'1ex', error(13, 2)), (b'1e+x', error(13, 3)),
                   (b'--1', error(13, 1)), (b'', error(5, 0)),
                   (b'1,', 1), (b'1x', 1), (b'1.2.3', 3),
                   (b'1e2e3', 3), (b'0x10', 1), (b'00', error(13, 1))]:
    case('number edge ' + str(data), 3, data, want)

for data in [b'""', b'"A"', b'"\\uD800"', b'"\\uDC00"', b'"\\uD800\\uDC00"',
             b'"\\u0000"', b'"\\uabcd"', b'"\x7f"', '"\u2028"'.encode(),
             '"\u2029"'.encode(), '"😀"'.encode(), b'"\\u12345"']:
    case('string valid ' + str(data), 4, data, len(data))
for escape in [b'\\"', b'\\\\', b'\\/', b'\\b', b'\\f', b'\\n', b'\\r', b'\\t']:
    data = b'"' + escape + b'"'
    case('string escape ' + str(escape), 4, data, len(data))
for data, want in [(b'"\\x"', error(14, 2)), (b'"\\u12', error(5, 5)),
                   (b'"\\u12"', error(15, 5)), (b'"\\u12G4"', error(15, 5)),
                   (b'"\\uG234"', error(15, 3)), (b'"\x1f"', error(16, 1)),
                   (b'"\x00"', error(16, 1)), (b'"A', error(17, 2)),
                   (b'"', error(17, 1)), (b'"\\', error(5, 2)),
                   (b'"\\u', error(5, 3)), (b'"\\u1', error(5, 4)),
                   (b'"\\u123', error(5, 6)), (b'"A"tail', 3)]:
    case('string edge ' + str(data), 4, data, want)



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
    ap.add_argument('--verify-only', action='store_true', help='only compile (verify) lex.pruv')
    args = ap.parse_args()
    g2 = configure()
    payload = ''.join(f'{op} {lo} {hi} ' + ' '.join(map(str, data)) + '\n' for _, op, data, lo, hi, _ in FIXTURES)
    failed = False
    for compiler in ('py', 'rs'):
        for backend in ('rust', 'llvm'):
            key = f'{compiler}/{backend}'
            try:
                work = WORK / f'a1_{compiler}_{backend}'
                work.mkdir(exist_ok=True)
                compiled = g2.compile_pruv(compiler, str(HERE / 'a1_root.pruv'), str(work), backend)
                if compiled['rc'] != 0:
                    raise RuntimeError('compile/verify failed: ' + str(compiled['errors'] or compiled['stderr']))
                print(f'{key}: lex.pruv verified and compiled (rc 0)', flush=True)
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
                bad = [(f[0], f[5], g) for f, g in zip(FIXTURES, got) if g != str(f[5])]
                for name, want, g in bad:
                    print(f'{key}: MISMATCH {name}: expected {str(want)}, got {g}')
                failed |= bool(bad)
                valid = sum(f[5] >= 0 or (f[1] == 0 and f[5] == -1) for f in FIXTURES)
                print(f'{key}: {len(FIXTURES) - len(bad)}/{len(FIXTURES)} fixtures as expected '
                      f'({valid} valid, {len(FIXTURES) - valid} malformed)', flush=True)
            except Exception as exc:
                failed = True
                print(f'{key}: ERROR {exc}', file=sys.stderr, flush=True)
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
