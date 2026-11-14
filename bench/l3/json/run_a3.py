#!/usr/bin/env python3
"""A3 string decoding, verified with both compilers on both backends."""
import importlib.util
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = HERE / 'work'

def run(cmd, data=None):
    p = subprocess.run([str(x) for x in cmd], input=data, text=True,
                       capture_output=True, timeout=600)
    if p.returncode:
        raise RuntimeError(f'{cmd}: exit {p.returncode}\n{p.stdout}\n{p.stderr}')
    return p.stdout

def configure():
    WORK.mkdir(exist_ok=True)
    os.environ['TMPDIR'] = str(WORK)
    spec = importlib.util.spec_from_file_location('g2', ROOT / 'bench/g2/run.py')
    g2 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(g2)
    main = ROOT
    git = ROOT / '.git'
    if git.is_file() and git.read_text().startswith('gitdir: '):
        main = Path(git.read_text().strip()[8:]).resolve().parents[2]
    py = os.environ.get('PRUV_PYTHON') or next(
        (str(p) for p in [ROOT / '.venv/bin/python', main / '.venv/bin/python'] if p.exists()), sys.executable)
    binary = Path(os.environ.get('PRUVC_RS', ROOT / 'pruvc-rs/target/release/pruvc'))
    if not binary.exists():
        binary = main / 'pruvc-rs/target/release/pruvc'
    if not binary.exists():
        raise RuntimeError('pruvc-rs binary not found')
    g2.COMPILERS = {'py': [py, str(ROOT / 'pruvc/pruvc.py')], 'rs': [str(binary)]}
    return g2

HARNESS = r'''#![allow(dead_code, unused_imports)]
#[path = "@SOL@"] mod sol;
use std::io::{self, BufRead};
fn bytes(b: &[u8]) -> String { b.iter().map(|x| x.to_string()).collect::<Vec<_>>().join(" ") }
fn main() {
 for line in io::stdin().lock().lines() {
  let line = line.unwrap();
  let (op, data) = line.split_once(':').unwrap();
  let data: Vec<u8> = data.split_whitespace().map(|x| x.parse().unwrap()).collect();
  if op == "a" { println!("{}", bytes(sol::adapter_probe(&data).as_bytes())); }
  else {
   let u = sol::units_of(&data).iter().map(|x| x.to_string()).collect::<Vec<_>>().join(" ");
   println!("{}|{}", u, bytes(sol::text_of(&data).as_bytes()));
  }
 }
}
'''

def nums(a):
    return ' '.join(map(str, a))

def oracle(data):
    s = json.loads(data.decode('utf-8'), strict=True)
    raw = s.encode('utf-16-le', 'surrogatepass')
    units = [raw[i] + 256 * raw[i+1] for i in range(0, len(raw), 2)]
    text = []
    i = 0
    while i < len(units):
        v = units[i]
        if 0xD800 <= v <= 0xDBFF and i+1 < len(units) and 0xDC00 <= units[i+1] <= 0xDFFF:
            text.append(chr(0x10000 + (v-0xD800)*1024 + units[i+1]-0xDC00))
            i += 2
        else:
            text.append(chr(0xFFFD if 0xD800 <= v <= 0xDFFF else v))
            i += 1
    return nums(units) + '|' + nums(''.join(text).encode())

def fixtures():
    strings = [b'""', b'"\\\"\\\\\\/\\b\\f\\n\\r\\t"', b'"\\u0000"',
               b'"\\uAbCd\\uaBcD"', b'"\\uD800\\uDC00"', b'"\\uDBFF\\uDFFF"',
               b'"\\uD800"', b'"\\uDC00"', b'"\\uDC00\\uD800"',
               b'"\\uD800\\uD800\\uDC00"', b'"\\uDC00\\uDC00\\uD800"',
               b'"\\uD800a\\uDC00"', b'"\\uD800\\ufffd\\uDC00"',
               b'"' + b'a'*100000 + b'"', b'"' + b'\\u0061'*100000 + b'"']
    edges = [0x7F, 0x80, 0x7FF, 0x800, 0xFFFF, 0x10000, 0x10FFFF, 0xFFFD, 0x2028, 0x2029, 0xFEFF]
    for v in edges:
        for ascii_only in (True, False):
            strings.append(json.dumps(chr(v), ensure_ascii=ascii_only).encode())
    strings.append(json.dumps(''.join(map(chr, edges)), ensure_ascii=False).encode())
    rng = random.Random(314159)
    pool = edges + [0, 8, 9, 10, 12, 13, 34, 47, 92, 0xD800, 0xDBFF, 0xDC00, 0xDFFF]
    for _ in range(400):
        chars = [chr(rng.choice(pool) if rng.randrange(2) else rng.randrange(0x110000))
                 for _ in range(rng.randrange(80))]
        # Raw surrogate code points have no UTF-8 encoding; escape just those.
        parts = [json.dumps(c, ensure_ascii=(0xD800 <= ord(c) <= 0xDFFF or bool(rng.randrange(2))))[1:-1] for c in chars]
        strings.append(('"' + ''.join(parts) + '"').encode())
    cases = [('s', data, oracle(data)) for data in strings]
    cases += [('s', b' \t' + strings[4] + b'\r\n', oracle(strings[4]))]
    for data in [b'', b'abc', b'a\0b', ''.join(map(chr, edges)).encode(), b'\xef\xbb\xbf',
                 b'\xff', b'\xc0\x80', b'\xed\xa0\x80', b'\xf4\x90\x80\x80',
                 b'\x80', b'\xe2\x82', b'\xf0\x90\x80', b'a\xffb']:
        try:
            data.decode('utf-8')
            want = nums(data)
        except UnicodeDecodeError:
            want = ''
        cases.append(('a', data, want))
    cases += [('s', b'null', '-1 0|' + nums(b'NotString')),
              ('s', b'"\\x"', '-1 14|' + nums(b'ParseFailed'))]
    return cases

def main():
    g2 = configure()
    target = WORK / 'str-adapter'
    run([shutil.which('cargo') or str(Path.home()/'.cargo/bin/cargo'), 'build', '--release', '--offline',
         '--quiet', '--manifest-path', HERE/'str_adapter/Cargo.toml', '--target-dir', target])
    rlib, deps = target/'release/libpruv_str.rlib', target/'release/deps'
    flags = ['--rust-extern', f'pruv_str={rlib}', '--rust-search', str(deps)]
    rustflags = ['--extern', f'pruv_str={rlib}', '-L', f'dependency={deps}']
    cases = fixtures()
    payload = ''.join(op + ':' + nums(data) + '\n' for op, data, _ in cases)
    expected = [want for _, _, want in cases]
    failed = False
    for compiler in ('py', 'rs'):
        for backend in ('rust', 'llvm'):
            key = f'{compiler}/{backend}'
            try:
                work = WORK/f'a3_{compiler}_{backend}'
                work.mkdir(exist_ok=True)
                c = g2.compile_pruv(compiler, str(HERE/'a3_root.pruv'), str(work), backend, flags)
                if c['rc'] != 0:
                    raise RuntimeError('compile/verify failed: ' + str(c['errors'] or c['stderr']))
                print(f'{key}: A3 verified and compiled', flush=True)
                extra = []
                if c['ll']:
                    extra, error = g2.build_llvm_objects(c['ll'], 'json', str(work))
                    if error:
                        raise RuntimeError(error)
                harness = work/'main.rs'
                harness.write_text(HARNESS.replace('@SOL@', c['rs']))
                exe = work/'runner'
                run([g2.RUSTC, '-O', '--edition', '2021', harness, '-o', exe] + extra + rustflags)
                got = run([exe], payload).splitlines()
                if len(got) != len(expected):
                    raise RuntimeError(f'{len(got)} answers for {len(expected)} fixtures')
                bad = [i for i, (w, g) in enumerate(zip(expected, got)) if w != g]
                for i in bad[:10]:
                    print(f'{key}: MISMATCH {i}: expected {expected[i][:150]!r}, got {got[i][:150]!r}')
                failed |= bool(bad)
                print(f'{key}: {len(cases)-len(bad)}/{len(cases)} fixtures passing', flush=True)
            except Exception as exc:
                failed = True
                print(f'{key}: ERROR {exc}', file=sys.stderr, flush=True)
    return int(failed)

if __name__ == '__main__':
    raise SystemExit(main())
