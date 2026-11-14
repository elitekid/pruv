#!/usr/bin/env python3
"""L3-1 Q measurement driver: warm latency, peak RSS and build time of the A4 pure API (a4_root.pruv).

Pairs: py/rust, py/llvm, rs/rust, rs/llvm (compiler/backend, as in test_a4.py, which is reused via importlib).
Inputs (work/qmeasure/inputs/<name>.jsonl): small, window_8MiB, long_text, block_arrays, ring_wrap, depth_limit.
Ops: window_packet (flag 0) on all six inputs; head_packet and tail_packet on small and window_8MiB
(the 8 MiB input exceeds the 64 KiB edge limit, so head/tail time the size rejection, not a scan).

Latency: one Rust process per (pair, input, op); it reads the file, then calls sol::<op>_packet once as warm-up and five
timed times with black_box (file IO and process start excluded); the driver reports median/min/max of the five.
Peak RSS: the process runs under `/usr/bin/time -l` (macOS, 'maximum resident set size' in bytes); without it the
driver uses os.wait4 rusage of exactly that child (ru_maxrss; bytes on macOS, KiB elsewhere). RSS covers the whole
process (file read, six calls, output packets), not only the timed region.
Build time: wall seconds of compile_pruv (compile + verify) and of rustc (+ LLVM object build), per pair.

The TS baseline is not timed here: only work/qmeasure/fixtures.json is written (reference.mjs format) and the
reference run is timed separately by hand.

Usage: python3 q_measure.py [--only SUBSTRING_OF_INPUT] [--pairs py/rust,rs/llvm]
"""
import argparse
import base64
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import statistics
import subprocess
import sys
import time

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
Q = HERE / 'work' / 'qmeasure'
INPUTS = Q / 'inputs'
RUNS = 5

_spec = importlib.util.spec_from_file_location('l3_test_a4', HERE / 'test_a4.py')
t4 = importlib.util.module_from_spec(_spec)
sys.modules['l3_test_a4'] = t4
_spec.loader.exec_module(t4)
oracle = t4.oracle
EDGE, WINDOW, LINE, LIM = t4.EDGE, t4.WINDOW, t4.LINE, t4.LIM
t4.WORK = Q  # configure() builds under work/qmeasure instead of work/a4

HARNESS = r'''#![allow(dead_code, unused_imports)]
#[path = "@SOL@"] mod sol;
use std::{env,fs,hint::black_box,time::Instant};
fn call(op: &str, data: &[u8]) -> Vec<i64> {
 match op {
  "head" => sol::head_packet(black_box(data), 0),
  "tail" => sol::tail_packet(black_box(data), 0),
  "window" => sol::window_packet(black_box(data), 0),
  _ => panic!("unknown op"),
 }
}
fn main() {
 let a: Vec<String> = env::args().collect();
 let data = fs::read(&a[1]).unwrap();
 let op = a[2].as_str();
 for i in 0..6 {
  let start = Instant::now();
  let out = black_box(call(op, &data));
  let ms = start.elapsed().as_secs_f64()*1000.0;
  println!("{} {} {} {}", if i == 0 { "warm" } else { "run" }, ms, out.len(), out[0]);
 }
}
'''


# ---------------- inputs ----------------
def build_inputs():
    user, asst, L, tx, tool_use, exact = t4.user, t4.asst, t4.L, t4.tx, t4.tool_use, t4.exact

    small = L(*[x for i in range(10) for x in (
        user(f'question number {i} about the build', cwd='/work', timestamp=1700000000000 + i * 2000),
        asst([tx(f'answer {i} with some detail'), tool_use('Bash', f't{i}')], model='claude-x', timestamp=1700000001000 + i * 2000))])
    assert len(small) <= EDGE

    # 8 MiB window of many short messages, just under oracle.WINDOW
    parts, total, i = [], 0, 0
    while True:
        chunk = L(user(f'q{i}', timestamp=1700000000000 + i * 1000), asst(f'a{i}', model='claude-x', timestamp=1700000000500 + i * 1000))
        if total + len(chunk) > WINDOW - 64:
            break
        parts.append(chunk)
        total += len(chunk)
        i += 1
    win = b''.join(parts)

    # lines just under the per-line cap (LINE - 1 raw bytes + LF); 7 lines stay inside the window
    apre = b'{"type":"assistant","message":{"model":"claude-x","content":"'
    long_lines = []
    for k in range(7):
        pre = t4.USER_PRE if k % 2 == 0 else apre
        long_lines.append(exact(pre, t4.USER_SUF, LINE - 1, b'a') + b'\n')
    long_text = b''.join(long_lines)

    # assistant messages with thousands of small blocks
    blocks = lambda n: [tx('x') if j % 2 == 0 else tool_use('Read', f't{j}') for j in range(n)]
    block_arrays = L(*[x for i in range(20) for x in (user(f'q{i}', timestamp=1700000000000 + i), asst(blocks(4000), model='claude-x', timestamp=1700000000500 + i))])

    # 2000 short pairs: the 200-draft ring wraps ten times
    ring = L(*[x for i in range(2000) for x in (user(f'p{i}', timestamp=1700000000000 + i), asst(f'r{i}', model='claude-x', timestamp=1700000000500 + i))])

    # lines nested to depth 128 (object = depth 1, 127 arrays)
    n = 127
    deep = b'[' * n + b'0' + b']' * n
    dlines = []
    for i in range(3000):
        if i % 2 == 0:
            dlines.append(b'{"type":"user","message":{"content":"d%d"},"x":' % i + deep + b'}')
        else:
            dlines.append(b'{"type":"assistant","message":{"model":"claude-x","content":"e%d"},"x":' % i + deep + b'}')
    depth = b'\n'.join(dlines) + b'\n'

    inputs = [('small', small), ('window_8MiB', win), ('long_text', long_text),
              ('block_arrays', block_arrays), ('ring_wrap', ring), ('depth_limit', depth)]
    for name, data in inputs:
        assert len(data) <= WINDOW, (name, len(data))
    return inputs


def plan(inputs):
    """(input, op) measurement list: window on all; head and tail on small and window_8MiB."""
    out = []
    for name, _ in inputs:
        out.append((name, 'window'))
        if name in ('small', 'window_8MiB'):
            out += [(name, 'head'), (name, 'tail')]
    return out


def write_inputs_and_fixtures(inputs, ops):
    INPUTS.mkdir(parents=True, exist_ok=True)
    byname = dict(inputs)
    for name, data in inputs:
        (INPUTS / (name + '.jsonl')).write_bytes(data)
    expected, fixtures = {}, []
    for name, op in ops:
        data = byname[name]
        want = oracle.api(op, 0, data)
        expected[(name, op)] = want
        fixtures.append({'name': f'{op}0: q_{name}', 'op': op, 'flag': 0, 'data': base64.b64encode(data).decode(), 'expected': want})
    (Q / 'fixtures.json').write_text(json.dumps(fixtures))
    return expected


# ---------------- process measurement ----------------
RSS_RE = re.compile(r'(\d+)\s+maximum resident set size')


def run_measured(cmd, timeout=600):
    """Run one child; return (stdout, peak_rss_bytes, method). Only the child started here is ever killed."""
    cmd = [str(c) for c in cmd]
    use_time = sys.platform == 'darwin' and os.path.exists('/usr/bin/time')
    full = ['/usr/bin/time', '-l'] + cmd if use_time else cmd
    p = subprocess.Popen(full, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    deadline = time.monotonic() + timeout
    if use_time:
        try:
            out, err = p.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, signal.SIGKILL)
            p.communicate()
            raise RuntimeError(f'timeout: {cmd}')
        if p.returncode:
            raise RuntimeError(f'{cmd}: exit {p.returncode}\n{out}\n{err[-2000:]}')
        m = RSS_RE.search(err)
        if not m:
            raise RuntimeError('no maximum resident set size in /usr/bin/time output: ' + err[-500:])
        return out, int(m.group(1)), '/usr/bin/time -l'
    while True:
        pid, status, ru = os.wait4(p.pid, os.WNOHANG)
        if pid:
            break
        if time.monotonic() > deadline:
            os.killpg(p.pid, signal.SIGKILL)
            os.wait4(p.pid, 0)
            raise RuntimeError(f'timeout: {cmd}')
        time.sleep(0.01)
    out, err = p.stdout.read(), p.stderr.read()
    p.stdout.close()
    p.stderr.close()
    if status:
        raise RuntimeError(f'{cmd}: status {status}\n{out}\n{err[-2000:]}')
    rss = ru.ru_maxrss if sys.platform == 'darwin' else ru.ru_maxrss * 1024
    return out, rss, 'wait4 ru_maxrss'


def measure_one(exe, name, op, want):
    out, rss, method = run_measured([exe, INPUTS / (name + '.jsonl'), op])
    rows = [l.split() for l in out.splitlines()]
    if len(rows) != 6 or rows[0][0] != 'warm' or any(r[0] != 'run' for r in rows[1:]):
        raise RuntimeError(f'unexpected harness output: {out!r}')
    ms = [float(r[1]) for r in rows[1:]]
    lens = {int(r[2]) for r in rows}
    codes = {int(r[3]) for r in rows}
    res = {'median_ms': statistics.median(ms), 'min_ms': min(ms), 'max_ms': max(ms), 'samples_ms': ms,
           'warmup_ms': float(rows[0][1]), 'packet_len': rows[0][2] and int(rows[0][2]),
           'peak_rss_bytes': rss, 'rss_method': method, 'code': int(rows[0][3]),
           'input_bytes': (INPUTS / (name + '.jsonl')).stat().st_size}
    if len(lens) != 1 or len(codes) != 1:
        raise RuntimeError(f'packet differs between calls: {lens} {codes}')
    res['expected_len'] = len(want)
    res['matches_oracle_shape'] = (res['packet_len'] == len(want) and res['code'] == want[0])
    return res


# ---------------- build ----------------
def build_pair(g2, run, compiler, backend, flags, rustflags):
    key = f'{compiler}/{backend}'
    work = Q / f'{compiler}_{backend}'
    work.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    compiled = g2.compile_pruv(compiler, str(HERE / 'a4_root.pruv'), str(work), backend, flags)
    compile_s = time.monotonic() - t0
    if compiled['rc'] != 0:
        raise RuntimeError(f'{key}: compile/verify failed: ' + str(compiled['errors'] or compiled['stderr']))
    harness = work / 'main.rs'
    harness.write_text(HARNESS.replace('@SOL@', compiled['rs']))
    extra, llvm_s = [], 0.0
    if compiled['ll']:
        t1 = time.monotonic()
        extra, error = g2.build_llvm_objects(compiled['ll'], 'a4', str(work))
        llvm_s = time.monotonic() - t1
        if error:
            raise RuntimeError(error)
    exe = work / 'runner'
    t2 = time.monotonic()
    run([g2.RUSTC, '-O', '--edition', '2021', harness, '-o', exe] + extra + rustflags)
    rustc_s = time.monotonic() - t2
    return exe, {'compile_verify_seconds': compile_s, 'llvm_objects_seconds': llvm_s, 'rustc_seconds': rustc_s,
                 'build_seconds': compile_s + llvm_s + rustc_s}


def tool_version(cmd):
    try:
        return subprocess.run([str(c) for c in cmd], capture_output=True, text=True, timeout=30).stdout.strip()
    except Exception as exc:
        return f'unavailable: {exc}'


def cpu_brand():
    try:
        p = subprocess.run(['sysctl', '-n', 'machdep.cpu.brand_string'], capture_output=True, text=True, timeout=10)
        return p.stdout.strip() if p.returncode == 0 and p.stdout.strip() else None
    except Exception:
        return None


def save(report):
    (Q / 'measure.json').write_text(json.dumps(report, indent=2) + '\n')


def print_table(report):
    print()
    print(f'{"pair":9} {"input":13} {"op":7} {"median":>9} {"min":>9} {"max":>9} {"pkt len":>10} {"rss MiB":>8} {"in bytes":>10}  ok')
    for pair, pr in report['pairs'].items():
        for key, r in pr.get('results', {}).items():
            name, op = key.split('/')
            if 'error' in r:
                print(f'{pair:9} {name:13} {op:7} ERROR {r["error"][:80]}')
                continue
            print(f'{pair:9} {name:13} {op:7} {r["median_ms"]:9.3f} {r["min_ms"]:9.3f} {r["max_ms"]:9.3f} {r["packet_len"]:10d} '
                  f'{r["peak_rss_bytes"] / 1048576:8.1f} {r["input_bytes"]:10d}  {"y" if r["matches_oracle_shape"] else "N"}')
    print()
    for pair, pr in report['pairs'].items():
        if 'build' in pr:
            b = pr['build']
            print(f'build {pair}: compile+verify {b["compile_verify_seconds"]:.1f}s, llvm objects {b["llvm_objects_seconds"]:.1f}s, '
                  f'rustc {b["rustc_seconds"]:.1f}s, total {b["build_seconds"]:.1f}s')
        if 'error' in pr:
            print(f'{pair}: ERROR {pr["error"][:200]}')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--only', default='', help='measure only inputs whose name contains this')
    ap.add_argument('--pairs', default='py/rust,py/llvm,rs/rust,rs/llvm')
    args = ap.parse_args()
    start = time.monotonic()
    Q.mkdir(parents=True, exist_ok=True)

    inputs = build_inputs()
    ops = plan(inputs)
    expected = write_inputs_and_fixtures(inputs, ops)
    print(f'{len(inputs)} inputs written to {INPUTS}; fixtures.json written for reference.mjs (TS timing is done separately)', flush=True)
    ops = [(n, o) for n, o in ops if args.only in n]

    g2, run = t4.configure()
    report = {
        'method': ('Per (pair,input,op) one process: read file, 1 warm-up + 5 timed calls of sol::<op>_packet with black_box '
                   '(Instant, ms); median/min/max of the 5. Peak RSS from /usr/bin/time -l (bytes) or wait4 ru_maxrss of that child; '
                   'covers the whole process. Build seconds: compile_pruv wall time and rustc wall time, separately.'),
        'machine': {'platform': platform.platform(), 'cpu': cpu_brand(), 'cpu_count': os.cpu_count()},
        'versions': {'python': platform.python_version(), 'rustc': tool_version([g2.RUSTC, '--version'])},
        'inputs': {n: {'bytes': len(d), 'file': f'inputs/{n}.jsonl'} for n, d in inputs},
        'notes': [
            'Fixed workspace: turns.new_buffer is 13,116,800 bytes (allocated per window collection regardless of input size).',
            'The i64 packet widens every output byte to 8 bytes (packet words are i64), so a packet of N text bytes costs 8*N bytes.',
            'Parsing vs collection cost: not separable without a new root (a4_root.pruv exposes only head/tail/window packets; no pub fn was added).',
            'head/tail on window_8MiB exceed the 64 KiB edge limit: they time the size rejection ([1,0]), not a scan.',
            'depth_limit uses 127 nested arrays inside an object line (total depth 128).',
            'Native TS baseline not timed here: work/qmeasure/fixtures.json is in the reference.mjs fixtures format; time reference.mjs runs separately.',
            'Cold first call is recorded as warmup_ms; median covers the five warm calls.',
        ],
        'pairs': {}, 'errors': [],
    }

    target = Q / 'str-adapter'
    cargo = shutil.which('cargo') or str(Path.home() / '.cargo/bin/cargo')
    run([cargo, 'build', '--release', '--offline', '--quiet', '--manifest-path', t4.JSON_DIR / 'str_adapter/Cargo.toml', '--target-dir', target])
    rlib, deps = target / 'release/libpruv_str.rlib', target / 'release/deps'
    flags = ['--rust-extern', f'pruv_str={rlib}', '--rust-search', str(deps)]
    rustflags = ['--extern', f'pruv_str={rlib}', '-L', f'dependency={deps}']

    failed = False
    for pair in [p for p in args.pairs.split(',') if p]:
        compiler, backend = pair.split('/')
        entry = report['pairs'].setdefault(pair, {'results': {}})
        try:
            exe, build = build_pair(g2, run, compiler, backend, flags, rustflags)
            entry['build'] = build
            print(f'{pair}: built in {build["build_seconds"]:.1f}s', flush=True)
        except Exception as exc:
            failed = True
            entry['error'] = str(exc)
            report['errors'].append(f'{pair}: {exc}')
            print(f'{pair}: ERROR {exc}', file=sys.stderr, flush=True)
            save(report)
            continue
        for name, op in ops:
            key = f'{name}/{op}'
            try:
                r = measure_one(exe, name, op, expected[(name, op)])
                if not r['matches_oracle_shape']:
                    report['errors'].append(f'{pair}/{key}: packet length/code differs from oracle ({r["packet_len"]} vs {r["expected_len"]})')
                    failed = True
                entry['results'][key] = r
                print(f'{pair} {key}: median {r["median_ms"]:.3f} ms, rss {r["peak_rss_bytes"] / 1048576:.1f} MiB', flush=True)
            except Exception as exc:
                failed = True
                entry['results'][key] = {'error': str(exc)}
                report['errors'].append(f'{pair}/{key}: {exc}')
                print(f'{pair} {key}: ERROR {exc}', file=sys.stderr, flush=True)
            save(report)
    report['elapsed_seconds'] = time.monotonic() - start
    save(report)
    print_table(report)
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
