"""G7 parallel benchmark; generated files stay under solutions/.work.

PRUV_PYTHON, PRUVC_RS, RUSTC and CLANG can select existing tools without building/installing.
"""
import sys
sys.dont_write_bytecode = True
import argparse
import importlib.util
import json
import os
from pathlib import Path
import random
import re
import shutil
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
WORK = HERE / 'solutions/.work'
WORK.mkdir(parents=True, exist_ok=True)
os.environ['TMPDIR'] = str(WORK)
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
os.environ['CLANG_MODULE_CACHE_PATH'] = str(WORK / 'clang-cache')
tempfile.tempdir = str(WORK)
spec = importlib.util.spec_from_file_location('g2_run', ROOT / 'bench/g2/run.py')
G2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(G2)
G2.COMPILERS['py'] = [os.environ.get('PRUV_PYTHON', str(ROOT / '.venv/bin/python')
                         if (ROOT / '.venv/bin/python').exists() else sys.executable), str(ROOT / 'pruvc/pruvc.py')]
G2.COMPILERS['rs'] = [os.environ.get('PRUVC_RS', str(ROOT / 'pruvc-rs/target/release/pruvc'))]
G2.RUSTC = os.environ.get('RUSTC', G2.RUSTC)
G2.CLANG = os.environ.get('CLANG', G2.CLANG)
PROBLEMS = ['q01', 'q02']
HEADERS = {'q01': 'pub fn transform(a: [u8], b: [u8], lo: i64, hi: i64, c: i64, pick: i64) -> [u8] ! alloc requires 0 <= lo && lo <= hi && hi <= len(a) && hi <= len(b) && 0 <= c && c <= 255 requires pick == 0 || pick == 1 ensures pick == 0 ==> len(result) == len(a) ensures pick == 1 ==> len(result) == len(b) ensures forall k in 0..len(result): (pick == 0 && lo <= k && k < hi && a[k] + c <= 255) ==> result[k] == a[k] + c ensures forall k in 0..len(result): (pick == 0 && lo <= k && k < hi && a[k] + c > 255) ==> result[k] == 255 ensures forall k in 0..len(result): (pick == 1 && lo <= k && k < hi) ==> result[k] == (b[k] + c) % 256 ensures forall k in 0..len(result): (pick == 0 && (k < lo || k >= hi)) ==> result[k] == a[k] ensures forall k in 0..len(result): (pick == 1 && (k < lo || k >= hi)) ==> result[k] == b[k]', 'q02': 'pub fn compute(src: [i64], pick: i64) -> [i64] ! alloc requires len(src) <= 4096 && (pick == 0 || pick == 1) requires forall k in 0..len(src): -1000 <= src[k] && src[k] <= 1000 ensures len(result) == len(src) ensures forall k in 0..len(src): pick == 0 ==> result[k] == src[k] * 2 ensures forall k in 0..len(src): pick == 1 ==> result[k] == src[k] - src[0]'}

def run(cmd, timeout=180):
    try:
        r = subprocess.run([str(x) for x in cmd], capture_output=True, text=True, timeout=timeout)
        return {'rc': r.returncode, 'stdout': r.stdout, 'stderr': r.stderr}
    except subprocess.TimeoutExpired:
        return {'rc': -1, 'stdout': '', 'stderr': 'timeout'}
    except OSError as e:
        return {'rc': -2, 'stdout': '', 'stderr': str(e)}


def ref_transform(a, b, lo, hi, c, pick):
    left = [min(255, x + c) if lo <= k < hi else x for k, x in enumerate(a)]
    right = [(x + c) % 256 if lo <= k < hi else x for k, x in enumerate(b)]
    return (left, right)[pick]


def ref_compute(src, pick):
    return [2 * x if pick == 0 else x - src[0] for x in src]


def cases(pid):
    rng = random.Random(7007)
    if pid == 'q01':
        arrays = [[], [0], [255], [0, 1, 127, 128, 254, 255], list(range(256))]
        arrays += [[rng.randrange(256) for _ in range(n)] for n in (2, 7, 31, 64)]
        for a in arrays:
            b = list(reversed(a)) + [17, 239]
            n = len(a)
            for lo, hi in sorted({(0, 0), (0, n), (n, n), (n//3, 2*n//3)}):
                for c in (0, 1, 127, 255):
                    for pick in (0, 1):
                        yield (a, b, lo, hi, c, pick)
    else:
        arrays = [[], [0], [1], [-1000], [1000], [-1000, 0, 1000], [7, 7, 7], [3, -4, 8, 0]]
        arrays += [[rng.randrange(-1000, 1001) for _ in range(n)] for n in (2, 7, 31, 64, 4096)]
        for src in arrays:
            for pick in (0, 1):
                yield (src, pick)


def driver(pid):
    # One Rust loop keeps optimization cost independent of the number of cases.
    rows = []
    for args in cases(pid):
        want = ref_transform(*args) if pid == 'q01' else ref_compute(*args)
        fields = [('vec!' + str(v)) if isinstance(v, list) else str(v) for v in args]
        rows.append('(' + ','.join(fields + ['vec!' + str(want)]) + ')')
    if pid == 'q01':
        typ = '(Vec<u8>,Vec<u8>,i64,i64,i64,i64,Vec<u8>)'
        body = """
        for (i, (a,b,lo,hi,c,pick,want)) in cases.into_iter().enumerate() {
            let sa = a.clone(); let sb = b.clone();
            let got = sol::transform(&a,&b,lo,hi,c,pick);
            check(&mut passed,&mut total,i,got == want);
            check(&mut passed,&mut total,i,a == sa);
            check(&mut passed,&mut total,i,b == sb);
        }
        """
    else:
        typ = '(Vec<i64>,i64,Vec<i64>)'
        body = """
        for (i, (src,pick,want)) in cases.into_iter().enumerate() {
            let saved = src.clone();
            let got = sol::compute(&src,pick);
            check(&mut passed,&mut total,i,got == want);
            check(&mut passed,&mut total,i,src == saved);
        }
        """
    return ('fn check(p: &mut usize, t: &mut usize, i: usize, ok: bool) {'
            '*t += 1; if ok { *p += 1; } else { println!("FAIL case {}", i); } }'
            'fn main() { let mut passed = 0; let mut total = 0;'
            f'let cases: Vec<{typ}> = vec![' + ','.join(rows) + '];' + body +
            'println!("TESTS {} {}", passed, total); }')


def build(c, wd, body):
    extra = []
    if c['ll']:
        try:
            extra, error = G2.build_llvm_objects(c['ll'], 'g7', str(wd))
        except OSError as e:
            return None, str(e)
        if error:
            return None, error
    main, exe = wd / 'main.rs', wd / 'program'
    main.write_text('#![allow(dead_code,unused_imports,unused_parens)]\n#[path = ' + json.dumps(c['rs']) + '] mod sol;\n' + body)
    result = run([G2.RUSTC, '-O', '--edition=2021', main, '-o', exe] + extra)
    return (exe, None) if result['rc'] == 0 else (None, result['stderr'])


def check_header(src, pid):
    text = re.sub(r'//[^\n]*', '', src.read_text())
    m = re.search(r'pub\s+fn\s+\w+[^\{]*', text)
    return len(re.findall(r'\bpub\s+fn\b', text)) == 1 and m and ' '.join(m.group().split()) == HEADERS[pid]


def grade_one(src, pid, compiler, backend, flags=()):
    src = Path(src).resolve()
    if not src.exists():
        return {'status': 'missing'}
    if not check_header(src, pid):
        return {'status': 'harness_error', 'error': 'contract changed'}
    if not re.search(r'\bpar\s*\{', re.sub(r'//[^\n]*', '', src.read_text())):
        return {'status': 'harness_error', 'error': 'required par group missing'}
    with tempfile.TemporaryDirectory(prefix='grade_', dir=WORK) as tmp:
        wd = Path(tmp)
        c = G2.compile_pruv(compiler, str(src), str(wd), backend, flags)
        if c['rc']:
            return dict(c, status='pruv_error')
        exe, error = build(c, wd, driver(pid))
        if error:
            return {'status': 'compile_error', 'error': error}
        r = run([exe], timeout=60)
        if r['rc'] in (-1, -2):
            return dict(r, status='timeout' if r['rc'] == -1 else 'harness_error')
        m = re.search(r'TESTS (\d+) (\d+)', r['stdout'])
        passed, total = map(int, m.groups()) if m else (0, -1)
        return dict(r, status='ok' if r['rc'] == 0 and passed == total else 'wrong',
                    tests_passed=passed, tests_total=total)


def main():
    p = argparse.ArgumentParser(__doc__)
    p.add_argument('solutions', type=Path)
    p.add_argument('out', nargs='?', type=Path)
    p.add_argument('--compiler', choices=['py', 'rs', 'both'], default='both')
    p.add_argument('--backend', choices=['rust', 'llvm', 'both'], default='both')
    p.add_argument('--no-verify', action='store_true')
    a = p.parse_args()
    results = {}
    for comp in ['py', 'rs'] if a.compiler == 'both' else [a.compiler]:
        for backend in ['rust', 'llvm'] if a.backend == 'both' else [a.backend]:
            key = comp + '-' + backend
            results[key] = {}
            for pid in PROBLEMS:
                r = grade_one(a.solutions / pid / 'root.pruv', pid, comp, backend,
                              ['--no-verify'] if a.no_verify else [])
                results[key][pid] = r
                print(key, pid, r['status'], f"{r.get('tests_passed', '-')}/{r.get('tests_total', '-')}", flush=True)
                if r['status'] != 'ok':
                    print(r.get('stderr') or r.get('error') or r.get('errors'))
    out = a.out or HERE / 'results' / 'solutions.json'
    payload = {'tools': G2.COMPILERS, 'solutions': str(a.solutions), 'flags': [], 'results': results}
    if a.no_verify:
        payload = json.loads(out.read_text()) if out.exists() else {'tools': G2.COMPILERS}
        payload['safe_results'] = results
    out.write_text(json.dumps(payload, indent=2))
    return int(any(r['status'] != 'ok' for rows in results.values() for r in rows.values()))


if __name__ == '__main__':
    sys.exit(main())
