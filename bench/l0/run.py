#!/usr/bin/env python3
"""Cross-check Lair against verified native Pruv builds; all writes stay here."""
import argparse
import hashlib
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
ROOT = HERE.parent.parent
WORK = HERE / "work"
RESULTS = HERE / "results"

HARNESS = r'''
#![allow(dead_code, unused_imports)]
#[path = "@SOL@"] mod sol;
use std::io::{self, BufRead};
fn main() {
    for line in io::stdin().lock().lines() {
        let line = line.unwrap();
        let (max, hex) = line.split_once(' ').unwrap();
        let bytes: Vec<u8> = (0..hex.len()).step_by(2)
            .map(|i| u8::from_str_radix(&hex[i..i+2], 16).unwrap()).collect();
        let s = String::from_utf8(bytes).unwrap();
        let result = sol::clip_bytes(&s, max.parse::<i64>().unwrap());
        let hex: String = result.as_bytes().iter().map(|b| format!("{:02x}", b)).collect();
        println!("{}", hex);
    }
}
'''


def run(cmd, data=None, timeout=180):
    p = subprocess.run([str(x) for x in cmd], input=data, text=True,
                       capture_output=True, timeout=timeout)
    if p.returncode:
        raise RuntimeError(f"{cmd}: exit {p.returncode}\n{p.stdout}\n{p.stderr}")
    return p.stdout


def source_digest(root):
    h = hashlib.sha256()
    for p in sorted(root.rglob('*')):
        if p.is_file() and p.suffix in ('.rs', '.toml', '.lock') and 'target' not in p.parts:
            h.update(str(p.relative_to(root)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def configure():
    WORK.mkdir(exist_ok=True)
    RESULTS.mkdir(exist_ok=True)
    os.environ['TMPDIR'] = str(WORK)
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    spec = importlib.util.spec_from_file_location('g2', ROOT / 'bench/g2/run.py')
    g2 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(g2)
    # A worktree can read the main checkout's installed tools without writing there.
    main = ROOT
    git = ROOT / '.git'
    if git.is_file() and git.read_text().startswith('gitdir: '):
        main = Path(git.read_text().strip()[8:]).resolve().parents[2]
    py = os.environ.get('PRUV_PYTHON')
    if not py:
        py = next((str(p) for p in [ROOT / '.venv/bin/python', main / '.venv/bin/python']
                   if p.exists()), sys.executable)
    binary = Path(os.environ.get('PRUVC_RS', ROOT / 'pruvc-rs/target/release/pruvc'))
    digest = source_digest(ROOT / 'pruvc-rs')
    if not binary.exists():
        installed = main / 'pruvc-rs/target/release/pruvc'
        if installed.exists() and source_digest(main / 'pruvc-rs') == digest:
            binary = installed
        else:
            cargo = shutil.which('cargo') or str(Path.home() / '.cargo/bin/cargo')
            target = WORK / 'cargo-target'
            run([cargo, 'build', '--release', '--locked', '--offline', '--manifest-path',
                 ROOT / 'pruvc-rs/Cargo.toml', '--target-dir', target], timeout=1200)
            binary = target / 'release/pruvc'
    g2.COMPILERS = {'py': [py, str(ROOT / 'pruvc/pruvc.py')], 'rs': [str(binary)]}
    # Record tool names only, so committed results carry no machine-specific paths.
    shown = {k: [Path(c).name for c in v] for k, v in g2.COMPILERS.items()}
    return g2, {'commands': shown, 'rust_source_sha256': digest,
                'rust_binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
                'node': run(['node', '--version']).strip()}


def build_decode_adapter():
    """Build the pruv_decode rlib (decode_adapter/, encoding_rs) for decode_bytes.pruv.
    Returns the pruvc flags and the matching final rustc flags."""
    cargo = shutil.which('cargo') or str(Path.home() / '.cargo/bin/cargo')
    target = WORK / 'decode-adapter'
    run([cargo, 'build', '--release', '--locked', '--quiet', '--manifest-path',
         HERE / 'decode_adapter/Cargo.toml', '--target-dir', target], timeout=900)
    rlib, deps = target / 'release/libpruv_decode.rlib', target / 'release/deps'
    return (['--rust-extern', f'pruv_decode={rlib}', '--rust-search', str(deps)],
            ['--extern', f'pruv_decode={rlib}', '-L', f'dependency={deps}'])


def cases(n, seed):
    edges = []
    for s in ['', 'a', '\ufffd', '\ufffda', '\ufffd\ufffd', '\ufffdé',
              '\ufffd😀', 'a\ufffdb', '\0é한😀', '\x7f\u0080\u07ff\u0800\uffff\U00010000\U0010ffff']:
        edges.extend((s, m) for m in range(len(s.encode()) + 2))
    edges.extend([('x', 1_000_000), ('a' * 1_000_000, 1_000_000),
                  ('a' * 999_996 + '\ufffdx', 999_999)])
    r = random.Random(seed)
    generated = []
    for _ in range(n):
        chars = []
        for _ in range(r.randrange(65)):
            kind = r.randrange(6)
            if kind < 2:
                cp = 0xfffd
            elif kind == 2:
                cp = r.randrange(128)
            elif kind == 3:
                cp = r.randrange(0x80, 0x800)
            elif kind == 4:
                cp = r.randrange(0x800, 0xf800)
                if cp >= 0xd800:
                    cp += 0x800
            else:
                cp = r.randrange(0x10000, 0x110000)
            chars.append(chr(cp))
        s = ''.join(chars)
        b = s.encode()
        mids = [i for i, v in enumerate(b) if v & 0xc0 == 0x80]
        m = r.choice(mids) if mids and r.random() < 0.7 else r.randrange(len(b) + 6)
        generated.append((s, m))
    return edges + generated, len(edges)


def oracle(s, maximum):
    # Independent spec: accumulate complete Unicode scalar encodings forwards.
    size = 0
    for c in s:
        width = len(c.encode('utf8'))
        if size + width > maximum:
            break
        size += width
    return s.encode('utf8')[:size]


def valid_prefix(source, maximum, got):
    try:
        got.decode('utf8', errors='strict')
    except UnicodeDecodeError:
        return False
    return len(got) <= maximum and source.startswith(got)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--n', type=int, default=20_000, help='random cases, in addition to edges')
    ap.add_argument('--seed', type=int, default=12345)
    args = ap.parse_args()
    if args.n < 0:
        ap.error('--n must be nonnegative')
    summary = {'seed': args.seed, 'random_cases': args.n, 'runs': {}}
    differences = []
    failed = False
    try:
        g2, summary['tools'] = configure()
        inputs, edge_count = cases(args.n, args.seed)
        summary.update(edge_cases=edge_count, total_cases=len(inputs),
                       difference_order='input byte length, max, input hex, compiler/backend',
                       difference_limit=50)
        expected = [oracle(s, m) for s, m in inputs]
        payload = ''.join(json.dumps({'hex': s.encode().hex(), 'max': m}) + '\n' for s, m in inputs)
        ts = [bytes.fromhex(json.loads(line)['hex']) for line in
              run(['node', HERE / 'clip_bytes.mjs'], payload).splitlines()]
        if len(ts) != len(inputs):
            raise RuntimeError('Node output count mismatch')
        native_input = ''.join(f'{m} {s.encode().hex()}\n' for s, m in inputs)
        for compiler in ('py', 'rs'):
            for backend in ('rust', 'llvm'):
                name = f'{compiler}/{backend}'
                work = WORK / f'{compiler}_{backend}'
                work.mkdir(exist_ok=True)
                row = summary['runs'][name] = {'status': 'error'}
                try:
                    compiled = g2.compile_pruv(compiler, str(HERE / 'clip_bytes.pruv'), str(work), backend)
                    (work / 'verification.json').write_text(json.dumps(compiled, indent=2) + '\n')
                    if compiled['rc'] != 0:
                        raise RuntimeError(json.dumps(compiled))
                    row['verified'] = True
                    harness = work / 'main.rs'
                    harness.write_text(HARNESS.replace('@SOL@', compiled['rs']))
                    extra = []
                    if compiled['ll']:
                        extra, error = g2.build_llvm_objects(compiled['ll'], 'clip', str(work))
                        if error:
                            raise RuntimeError(error)
                    exe = work / 'runner'
                    run([g2.RUSTC, '-O', '--edition', '2021', '-C', 'target-cpu=native',
                         harness, '-o', exe] + extra)
                    pruv = [bytes.fromhex(line) for line in run([exe], native_input).splitlines()]
                    if len(pruv) != len(inputs):
                        raise RuntimeError('Native output count mismatch')
                    counts = dict.fromkeys(['equal', 'TS shorter', 'TS longer', 'TS invalid'], 0)
                    pruv_ok = ts_ok = diff_count = 0
                    for index, ((s, m), t, p, want) in enumerate(zip(inputs, ts, pruv, expected)):
                        raw = s.encode()
                        category = ('TS invalid' if not valid_prefix(raw, m, t) else
                                    'equal' if t == p else 'TS shorter' if len(t) < len(p) else
                                    'TS longer' if len(t) > len(p) else 'TS invalid')
                        counts[category] += 1
                        pruv_ok += p == want
                        ts_ok += t == want
                        if t != p:
                            diff_count += 1
                            differences.append({'compiler_backend': name, 'case_index': index,
                                'input_hex': raw.hex(), 'input_bytes': len(raw), 'max': m,
                                'ts_hex': t.hex(), 'pruv_hex': p.hex(), 'expected_hex': want.hex(),
                                'classification': category, 'ts_meets_spec': t == want,
                                'pruv_meets_spec': p == want})
                    row.update(status='ok' if pruv_ok == len(inputs) else 'wrong',
                               cases=len(inputs), counts=counts, differences=diff_count,
                               pruv_spec_pass=pruv_ok, ts_spec_pass=ts_ok)
                    failed |= pruv_ok != len(inputs)
                    print(f'{name}: {json.dumps(row)}', flush=True)
                except Exception as exc:
                    row['error'] = str(exc)
                    failed = True
                    print(f'{name}: {exc}', file=sys.stderr, flush=True)
    except Exception as exc:
        summary['error'] = str(exc)
        failed = True
    differences.sort(key=lambda d: (d['input_bytes'], d['max'], d['input_hex'], d['compiler_backend']))
    summary['difference_records_total'] = len(differences)
    summary['difference_records_saved'] = min(50, len(differences))
    summary['status'] = 'error' if failed else 'ok'
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    (RESULTS / 'differences.jsonl').write_text(''.join(json.dumps(d) + '\n' for d in differences[:50]))
    if 'error' in summary:
        print(summary['error'], file=sys.stderr)
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
