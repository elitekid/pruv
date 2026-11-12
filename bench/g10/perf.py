"""Read and sum a decimal 10 MB file; default verified builds, -O for both programs."""
import sys
sys.dont_write_bytecode = True
import argparse
import json
from pathlib import Path
import platform
import statistics
import tempfile
import run as G


def measure(compiler, backend, repeat):
    with tempfile.TemporaryDirectory(prefix='perf_', dir=G.WORK) as tmp:
        wd = Path(tmp)
        c = G.G2.compile_pruv(compiler, str(G.HERE / 'perf/sum.pruv'), str(wd), backend)
        if c['rc']:
            return dict(c, status='pruv_error')
        exe, error = G.build(c, wd, (G.HERE / 'perf/driver.rs').read_text())
        if error:
            return {'status': 'compile_error', 'error': error}
        r = G.run([exe, wd / 'ten_mb.bin', repeat], timeout=300)
        if r['rc']:
            return dict(r, status='run_error')
        data = json.loads(r['stdout'])
        p, native = statistics.median(data['pruv_ns']), statistics.median(data['rust_ns'])
        ratio = p / native
        return {'status': 'ok', 'pruv_median_ms': p / 1e6, 'rust_median_ms': native / 1e6,
                'ratio': ratio, 'within_1_5x': ratio <= 1.5, 'raw': data}


def main():
    p = argparse.ArgumentParser(__doc__)
    p.add_argument('out', type=Path, nargs='?')
    p.add_argument('--compiler', choices=['py', 'rs'], default='py')
    p.add_argument('--backend', choices=['rust', 'llvm', 'both'], default='both')
    p.add_argument('--repeat', type=int, default=10)
    a = p.parse_args()
    if a.repeat < 1:
        p.error('--repeat must be positive')
    rows = {b: measure(a.compiler, b, a.repeat) for b in
            (['rust', 'llvm'] if a.backend == 'both' else [a.backend])}
    result = {'compiler': a.compiler, 'verified': True, 'repeat': a.repeat,
              'tools': G.G2.COMPILERS, 'platform': platform.platform(),
              'rustc': G.run([G.G2.RUSTC, '--version']), 'clang': G.run([G.G2.CLANG, '--version']),
              'method': 'In-process full open/read/sum/drop; warmup; alternating order; cached file; rustc -O, clang -O2',
              'rows': rows}
    out = a.out or G.HERE / 'results' / f'perf_{a.compiler}_{a.backend}.json'
    out.write_text(json.dumps(result, indent=2))
    for backend, r in rows.items():
        print(a.compiler, backend, json.dumps({k: v for k, v in r.items() if k != 'raw'}))
    return int(any(r['status'] != 'ok' or not r.get('within_1_5x') for r in rows.values()))


if __name__ == '__main__':
    sys.exit(main())
