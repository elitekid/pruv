#!/usr/bin/env python3
"""Pruv performance standard driver (docs/PERF_SPEC.md).

Per program dir bench/perf/<p>/: <p>.pruv exports `pub fn bench(data: [u8], n: i64) -> [i64]` (or `-> [u8]`),
matched.rs exports `pub fn bench(data: &[u8], n: i64) -> Vec<i64>` (same result type), optionally secondary.rs (the
published reference when matched.rs had to change its algorithm; timed and reported for information), and gen.py, run as
`gen.py <dev|full> <out>` to make the input file (no gen.py: data is empty).

Builds matched Rust and the four Pruv pairs (py/rust, py/llvm, rs/rust, rs/llvm), checks every variant prints the
same digest, then times: 3 warm-up processes per variant, then ROUNDS rounds that run every variant once in a shuffled
order. Each process times one bench() call in-process (input read excluded). Reports mean ms per variant and the
Pruv/Rust ratio with a 95% t-interval on per-round log ratios, plus the median peak resident set size (max RSS of the
whole process, from wait4) per variant and its Pruv/Rust ratio, and the build time per variant (Pruv compiler, which
verifies and generates code, then rustc/clang).

Usage: python3 bench/perf/run.py [--dev] [--rounds N] [--pairs rs/rust,rs/llvm] [program ...]
"""
import argparse, json, math, os, platform, random, shutil, statistics, subprocess, sys, time
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
WORK = HERE / 'work'
sys.path.insert(0, str(ROOT / 'bench' / 'g2'))
import run as g2  # noqa: E402

# program: (dev n, full n)
PROGRAMS = {
    'fannkuch': (10, 12),
    'binarytrees': (18, 21),
    'revcomp': (0, 0),
    'brainfuck': (0, 0),
    'primes': (50000, 5000000),
    'sudoku': (2, 200),
    'nqueen': (12, 15),
    'base64': (64, 8192),
    'bedcov': (10000, 1000000),
}
PAIRS = ['py/rust', 'py/llvm', 'rs/rust', 'rs/llvm']
ARM = platform.machine().lower() in ('arm64', 'aarch64')
RUSTFLAGS = ['--edition', '2021', '-C', 'opt-level=3', '-C', 'codegen-units=1', '-C', 'target-cpu=native']

HARNESS = r'''#![allow(dead_code, unused_imports, unused_variables, unused_mut)]
#[path = "@SOL@"] mod sol;
use std::{env, fs, hint::black_box, time::Instant};
trait Digest { fn digest(&self) -> String; }
fn fnv(bytes: impl Iterator<Item = u64>) -> u64 {
    let mut h: u64 = 0xcbf29ce484222325;
    for b in bytes { h ^= b; h = h.wrapping_mul(0x100000001b3); }
    h
}
impl Digest for Vec<i64> {
    fn digest(&self) -> String {
        if self.len() <= 16 { format!("{:?}", self) } else { format!("i64x{}:{:016x}", self.len(), fnv(self.iter().map(|&x| x as u64))) }
    }
}
impl Digest for Vec<u8> {
    fn digest(&self) -> String { format!("u8x{}:{:016x}", self.len(), fnv(self.iter().map(|&x| x as u64))) }
}
fn main() {
    let a: Vec<String> = env::args().collect();
    let data: Vec<u8> = if a[1] == "-" { Vec::new() } else { fs::read(&a[1]).unwrap() };
    let n: i64 = a[2].parse().unwrap();
    let start = Instant::now();
    let out = black_box(sol::bench(black_box(&data), black_box(n)));
    let ms = start.elapsed().as_secs_f64() * 1000.0;
    println!("{} {}", ms, out.digest());
}
'''


def sh(cmd, **kw):
    c = subprocess.run([str(x) for x in cmd], capture_output=True, text=True, **kw)
    if c.returncode != 0:
        raise RuntimeError(f'{cmd[0]} failed ({c.returncode}): {(c.stdout + c.stderr)[-2000:]}')
    return c.stdout


def build_harness(sol, out, extra=()):
    main = out.parent / (out.name + '_main.rs')
    main.write_text(HARNESS.replace('@SOL@', str(sol)))
    sh([g2.RUSTC] + RUSTFLAGS + [main, '-o', out] + list(extra))
    return out


def llvm_objects(ll, work):
    cpu = '-mcpu=native' if ARM else '-march=native'
    gen_o, rt_o = work / 'gen.o', work / 'rt.o'
    sh([g2.CLANG, '-O3', cpu, '-Wno-override-module', '-c', ll, '-o', gen_o])
    sh([g2.CLANG, '-O3', cpu, '-std=c11', '-DPRUV_RUST_ALLOCATOR', '-c', ROOT / 'pruvc/runtime.c', '-o', rt_o])
    return ['-C', f'link-arg={gen_o}', '-C', f'link-arg={rt_o}']


def build(prog, pairs):
    src = HERE / prog
    work = WORK / prog
    work.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    exes = {'rust': build_harness(src / 'matched.rs', work / 'rust')}
    ctime = {'rust': {'rustc_s': time.perf_counter() - t0}}
    if (src / 'secondary.rs').exists():
        exes['secondary'] = build_harness(src / 'secondary.rs', work / 'secondary')
    for pair in pairs:
        compiler, backend = pair.split('/')
        w = work / f'{compiler}_{backend}'
        w.mkdir(exist_ok=True)
        t0 = time.perf_counter()
        c = g2.compile_pruv(compiler, str(src / f'{prog}.pruv'), str(w), backend)
        t1 = time.perf_counter()
        if c['rc'] != 0:
            raise RuntimeError(f'{prog} {pair}: compile/verify failed: {c["errors"] or c["stderr"]}')
        extra = llvm_objects(c['ll'], w) if c['ll'] else []
        exes[pair] = build_harness(c['rs'], w / 'runner', extra)
        ctime[pair] = {'pruvc_s': t1 - t0, 'rustc_s': time.perf_counter() - t1}
    return exes, ctime


def make_input(prog, mode):
    gen = HERE / prog / 'gen.py'
    if not gen.exists():
        return '-'
    out = WORK / prog / f'input_{mode}'
    if not out.exists():
        sh([sys.executable, gen, mode, out])
    return str(out)


RSS_UNIT = 1 if platform.system() == 'Darwin' else 1024  # ru_maxrss: bytes on macOS, KiB on Linux


def once(exe, inp, n):
    """Run one process: (bench ms, digest, peak resident set size in bytes of the whole process)."""
    p = subprocess.Popen([str(exe), str(inp), str(n)], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    out = p.stdout.read()  # output is one short line; read to EOF, then reap ourselves to get the child's rusage
    p.stdout.close()
    _, status, ru = os.wait4(p.pid, 0)
    p.returncode = os.waitstatus_to_exitcode(status)
    if p.returncode:
        raise RuntimeError(f'{exe} exit {p.returncode}')
    line = out.strip().split(' ', 1)
    return float(line[0]), line[1], ru.ru_maxrss * RSS_UNIT


T975 = {4: 2.776, 9: 2.262, 19: 2.093, 29: 2.045}


def tcrit(df):
    return T975.get(df) or (2.045 if df >= 29 else 2.262)


def measure(prog, exes, inp, n, rounds):
    digests = {v: once(e, inp, n)[1] for v, e in exes.items()}
    want = digests['rust']
    bad = {v: d for v, d in digests.items() if d != want}
    if bad:
        raise RuntimeError(f'{prog}: output differs from matched Rust ({want}): {bad}')
    names = list(exes)
    for _ in range(3):
        for v in names:
            once(exes[v], inp, n)
    times = {v: [] for v in names}
    rss = {v: [] for v in names}
    for _ in range(rounds):
        order = names[:]
        random.shuffle(order)
        for v in order:
            ms, _, peak = once(exes[v], inp, n)
            times[v].append(ms)
            rss[v].append(peak)
    res = {'digest': want, 'mean_ms': {v: statistics.mean(t) for v, t in times.items()}, 'ratio': {},
           'max_rss': {v: statistics.median(r) for v, r in rss.items()}, 'rss_ratio': {}}
    for v in names:
        if v != 'rust':
            res['rss_ratio'][v] = res['max_rss'][v] / res['max_rss']['rust']
    for v in names:
        if v == 'rust':
            continue
        logs = [math.log(a / b) for a, b in zip(times[v], times['rust'])]
        m = statistics.mean(logs)
        h = tcrit(len(logs) - 1) * statistics.stdev(logs) / math.sqrt(len(logs)) if len(logs) > 1 else 0.0
        res['ratio'][v] = (math.exp(m), math.exp(m - h), math.exp(m + h))
    return res


def verdict(hi):
    return 'faster' if hi < 1.0 else ('equal' if hi <= 1.05 else 'SLOWER')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dev', action='store_true')
    ap.add_argument('--rounds', type=int)
    ap.add_argument('--pairs', default=','.join(PAIRS))
    ap.add_argument('programs', nargs='*')
    a = ap.parse_args()
    mode = 'dev' if a.dev else 'full'
    rounds = a.rounds or (5 if a.dev else 30)
    pairs = a.pairs.split(',')
    progs = a.programs or [p for p in PROGRAMS if (HERE / p / f'{p}.pruv').exists()]
    rustc = sh([g2.RUSTC, '--version']).strip()
    print(f'{rustc}; mode {mode}; {rounds} rounds', flush=True)
    results, failed = {}, False
    for prog in progs:
        try:
            exes, ctime = build(prog, pairs)
            n = PROGRAMS[prog][0 if a.dev else 1]
            r = measure(prog, exes, make_input(prog, mode), n, rounds)
        except Exception as exc:
            failed = True
            print(f'{prog}: ERROR {exc}', flush=True)
            continue
        r['compile'] = ctime
        results[prog] = r
        cells = [f'rust {r["mean_ms"]["rust"]:.2f} ms']
        for v, (m, lo, hi) in r['ratio'].items():
            cells.append(f'{v} {m:.3f} [{lo:.3f},{hi:.3f}]' + ('' if v == 'secondary' else f' {verdict(hi)}'))
        print(f'{prog}: ' + ' | '.join(cells), flush=True)
        mem = [f'rust {r["max_rss"]["rust"] / 2**20:.1f} MiB']
        for v, q in r['rss_ratio'].items():
            mem.append(f'{v} {q:.3f}' + ('' if v == 'secondary' else f' {verdict(q)}'))
        print(f'{prog} max RSS: ' + ' | '.join(mem), flush=True)
        print(f'{prog} compile s: ' + ' | '.join(f'{v} ' + '+'.join(f'{x:.2f}' for x in t.values()) for v, t in ctime.items()), flush=True)
    for pair in pairs:
        rs = [results[p]['ratio'][pair][0] for p in results if pair in results[p]['ratio']]  # matched baseline only
        if rs:
            print(f'geomean {pair}: {math.exp(statistics.mean(math.log(x) for x in rs)):.3f} over {len(rs)}')
        qs = [results[p]['rss_ratio'][pair] for p in results if pair in results[p]['rss_ratio']]
        if qs:
            print(f'geomean max RSS {pair}: {math.exp(statistics.mean(math.log(x) for x in qs)):.3f} over {len(qs)}')
    WORK.mkdir(exist_ok=True)
    (WORK / f'results_{mode}.json').write_text(json.dumps({'rustc': rustc, 'rounds': rounds, 'results': results}, indent=1))
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
