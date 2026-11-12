"""Stage 5 cost benchmark; generated files stay under solutions/.work.

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
if not Path(G2.COMPILERS['rs'][0]).exists():
    G2.COMPILERS['rs'] = [str(WORK / 'target/release/pruvc')]
G2.RUSTC = os.environ.get('RUSTC', G2.RUSTC)
G2.CLANG = os.environ.get('CLANG', G2.CLANG)
PROBLEMS = ['q01', 'q02']
HEADERS = {'q01': 'pub fn grid(a: [i64]) -> i64 requires len(a) <= 32 ensures result == len(a) * len(a) cost len(a) * (len(a) + 1)', 'q02': 'pub fn compute(src: [i64]) -> [i64] ! alloc requires len(src) <= 32 requires forall k in 0..len(src): -1000 <= src[k] && src[k] <= 1000 ensures len(result) == len(src) ensures forall k in 0..len(src): result[k] == src[k] * 2 cost 3 * len(src) + 1'}

def run(cmd, timeout=180):
    try:
        r = subprocess.run([str(x) for x in cmd], capture_output=True, text=True, timeout=timeout)
        return {'rc': r.returncode, 'stdout': r.stdout, 'stderr': r.stderr}
    except subprocess.TimeoutExpired:
        return {'rc': -1, 'stdout': '', 'stderr': 'timeout'}
    except OSError as e:
        return {'rc': -2, 'stdout': '', 'stderr': str(e)}


def ref_grid(a):
    return sum(1 for i in range(len(a)) for j in range(len(a)))


def ref_compute(src):
    return [x * 2 for x in src]


def cases(pid):
    rng = random.Random(5005)
    yield []
    yield [-1000]
    yield [1000]
    yield [0]
    yield [-1000, 0, 1000]
    for n in range(2, 33):
        yield [rng.randrange(-1000, 1001) for _ in range(n)]
    yield [1000] * 32
    yield [-1000] * 32


def driver(pid):
    rows = []
    for a in cases(pid):
        want = str(ref_grid(a)) if pid == 'q01' else 'vec!' + str(ref_compute(a))
        rows.append('(vec!' + str(a) + ',' + want + ')')
    typ = 'i64' if pid == 'q01' else 'Vec<i64>'
    fn = 'grid' if pid == 'q01' else 'compute'
    return ('fn main() { let mut passed = 0; let mut total = 0;'
            'let cases: Vec<(Vec<i64>,' + typ + ')> = vec![' + ','.join(rows) + '];'
            'for (i,(a,want)) in cases.into_iter().enumerate() {'
            'let saved = a.clone(); let got = std::panic::catch_unwind(|| sol::' + fn + '(&a));'
            'total += 2; if got.map(|v| v == want).unwrap_or(false) { passed += 1; } else { println!("FAIL {}",i); }'
            'if a == saved { passed += 1; }} println!("TESTS {} {}",passed,total); }')


def build(c, wd, body):
    extra = []
    if c['ll']:
        try:
            extra, error = G2.build_llvm_objects(c['ll'], 's5', str(wd))
        except OSError as e:
            return None, str(e)
        if error:
            return None, error
    main, exe = wd / 'main.rs', wd / 'program'
    main.write_text('#![allow(dead_code,unused_imports,unused_parens)]\n#[path = ' + json.dumps(c['rs']) + '] mod sol;\n' + body)
    result = run([G2.RUSTC, '-O', '--edition=2021', main, '-o', exe] + extra)
    return (exe, None) if result['rc'] == 0 else (None, result['stderr'])


def check_header(src, pid, enforce_cost=True):
    text = re.sub(r'//[^\n]*', '', src.read_text())
    m = re.search(r'pub\s+fn\s+\w+[^\{]*', text)
    if not enforce_cost and m:
        actual = ' '.join(m.group().split()).split(' cost ')[0]
        expected = HEADERS[pid].split(' cost ')[0]
        return len(re.findall(r'\bpub\s+fn\b', text)) == 1 and actual == expected
    return len(re.findall(r'\bpub\s+fn\b', text)) == 1 and m and ' '.join(m.group().split()) == HEADERS[pid]


def grade_one(src, pid, compiler, backend, flags=(), enforce_header=True):
    src = Path(src).resolve()
    if not src.exists():
        return {'status': 'missing'}
    if not check_header(src, pid, enforce_cost=enforce_header):
        return {'status': 'harness_error', 'error': 'contract changed'}
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
