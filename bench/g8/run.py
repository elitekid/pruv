"""G8 standard module benchmark; generated files stay under solutions/.work.

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
HEADERS = {'q01': ['pub fn first_duplicate(a: [i64]) -> Option<i64> ensures is_some(result) == (exists i in 0..len(a): exists j in i + 1..len(a): a[i] == a[j]) ensures is_some(result) ==> (0 <= some_val(result) && some_val(result) < len(a)) ensures is_some(result) ==> (exists j in some_val(result) + 1..len(a): a[some_val(result)] == a[j]) ensures is_some(result) ==> (forall k in 0..some_val(result): forall j in k + 1..len(a): a[k] != a[j])', 'pub fn checked_total(a: i64, b: i64) -> Option<i64> ensures is_some(result) == (-9223372036854775808 <= a + b && a + b <= 9223372036854775807) ensures is_some(result) ==> some_val(result) == a + b'], 'q02': ['pub fn bounded_sum(a: [i64]) -> i64 requires len(a) <= 1000000 requires forall k in 0..len(a): -1000000000 <= a[k] && a[k] <= 1000000000 ensures result == sum(k in 0..len(a): a[k])', 'pub fn maximum(a: [i64]) -> i64 requires len(a) > 0 ensures result == max(k in 0..len(a): a[k])', 'pub fn reversed(a: [i64]) -> [i64] ! alloc ensures len(result) == len(a) ensures forall k in 0..len(a): result[k] == a[len(a) - 1 - k]']}

def run(cmd, timeout=180):
    try:
        r = subprocess.run([str(x) for x in cmd], capture_output=True, text=True, timeout=timeout)
        return {'rc': r.returncode, 'stdout': r.stdout, 'stderr': r.stderr}
    except subprocess.TimeoutExpired:
        return {'rc': -1, 'stdout': '', 'stderr': 'timeout'}
    except OSError as e:
        return {'rc': -2, 'stdout': '', 'stderr': str(e)}


MIN, MAX = -(2**63), 2**63 - 1

def ref_duplicate(a):
    return next((i for i, x in enumerate(a) if x in a[i+1:]), None)

def ref_checked(a, b):
    return a+b if MIN <= a+b <= MAX else None

def cases(pid):
    edges = [[], [0], [1], [-1], [1,2,1], [3,2,2,3], [1,1,1], [-9,-2,-7], [3,2,1], [1,2,3], [0,0]]
    rng = random.Random(8008)
    edges += [[rng.randrange(-5,6) for _ in range(n)] for n in range(2,33)]
    edges += [[-1000000000,1000000000], [1000000000]*32, [-1000000000]*32]
    if pid == 'q01': edges += [[MIN,MAX,MIN], [MAX,MIN], [MIN]]
    return edges

def literal(x):
    if x is None: return 'None'
    if isinstance(x,bool): return str(x).lower()
    if isinstance(x,list): return 'vec!' + str(x)
    return str(x)

def assertion(call, want):
    return ('total += 1; if std::panic::catch_unwind(|| ' + call + ').map(|v| v == ' + want + ').unwrap_or(false) { passed += 1; } else { println!("FAIL {}",total); }')

def driver(pid):
    body = 'fn main() { std::panic::set_hook(Box::new(|_| {})); let mut passed=0; let mut total=0;'
    for a in cases(pid):
        body += '{ let a: Vec<i64> = '+literal(a)+'; let saved=a.clone();'
        if pid == 'q01':
            x=ref_duplicate(a)
            body += assertion('sol::first_duplicate(&a)', 'None' if x is None else 'Some('+str(x)+')')
        else:
            body += assertion('sol::bounded_sum(&a)', str(sum(a)))
            if a: body += assertion('sol::maximum(&a)', str(max(a)))
            body += assertion('sol::reversed(&a)', literal(a[::-1]))
        body += assertion('a == saved', 'true') + '}'
    if pid == 'q01':
        for a in [MIN,MIN+1,-2,-1,0,1,2,MAX-1,MAX]:
            for b in [MIN,-1,0,1,MAX]:
                x=ref_checked(a,b)
                body += assertion(f'sol::checked_total({a},{b})', 'None' if x is None else 'Some('+str(x)+')')
    return body + 'println!("TESTS {} {}",passed,total); }'


def build(c, wd, body):
    extra = []
    if c['ll']:
        try:
            extra, error = G2.build_llvm_objects(c['ll'], 'g8', str(wd))
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
    return [' '.join(x.split()) for x in re.findall(r'pub\s+fn\s+\w+[^\{]*', text)] == HEADERS[pid]


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
