"""G10 file benchmark; all generated files stay under bench/g10/.work.

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
WORK = HERE / '.work'
WORK.mkdir(exist_ok=True)
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
HEADERS = {
    'q01': 'pub fn transform(input: str, output: str) -> i64 ! fs, alloc ensures -3 <= result && result <= 0',
    'q02': 'pub fn count_fields(path: str) -> i64 ! fs, alloc ensures -2 <= result && result <= 4097 * 10001',
}


def run(cmd, timeout=180):
    try:
        r = subprocess.run([str(x) for x in cmd], capture_output=True, text=True, timeout=timeout)
        return {'rc': r.returncode, 'stdout': r.stdout, 'stderr': r.stderr}
    except subprocess.TimeoutExpired:
        return {'rc': -1, 'stdout': '', 'stderr': 'timeout'}
    except OSError as e:
        return {'rc': -2, 'stdout': '', 'stderr': str(e)}


def ref_transform(data):
    return bytes(255 - b for b in data)


def ref_count(data):
    if data is None:
        return -1
    if len(data) > 4096:
        return -2
    lines = data.count(b'\n') + int(bool(data) and not data.endswith(b'\n'))
    return 10000 * lines + lines + data.count(b',')


def cases():
    rng = random.Random(1010)
    return [b'', b'\0', b'\xff', b'a,b\n', b'\n', b',', b',,\n\n', b'a\r\nb,c',
            bytes(range(256)), b'\n' * 4096, b',' * 4096, b'x' * 4097,
            b'x' * 10000001] + [bytes(rng.randrange(256) for _ in range(n)) for n in (2, 17, 129, 1024)]


def driver(pid):
    # The executable, rather than the Python compiler process, creates all fixtures.
    lines = ['let dir = std::path::PathBuf::from(std::env::args().nth(1).unwrap());',
             'std::fs::create_dir_all(&dir).unwrap();', 'let mut passed = 0; let mut total = 0;']
    for i, data in enumerate(cases()):
        if len(data) > 1000 and len(set(data)) == 1:
            expr = f'vec![{data[0]}u8; {len(data)}]'
        else:
            expr = 'vec![' + ','.join(str(b) + 'u8' for b in data) + ']'
        lines += ['{', f'let data: Vec<u8> = {expr};',
                  f'let input = dir.join("input_{i}"); let output = dir.join("output_{i}");',
                  'std::fs::write(&input, &data).unwrap();']
        if pid == 'q01':
            status = -3 if len(data) > 10000000 else 0
            lines += ['std::fs::write(&output, b"sentinel old contents").unwrap();',
                      'let got = sol::transform(input.to_str().unwrap(), output.to_str().unwrap());',
                      f'check(&mut passed, &mut total, "status_{i}", got == {status});',
                      'let want: Vec<u8> = ' + ('b"sentinel old contents".to_vec();' if status else
                                                   'data.iter().map(|b| 255 - b).collect();'),
                      f'check(&mut passed, &mut total, "bytes_{i}", std::fs::read(&output).unwrap() == want);']
        else:
            lines += [f'check(&mut passed, &mut total, "count_{i}", sol::count_fields(input.to_str().unwrap()) == {ref_count(data)});']
        lines += ['}']
    lines += ['let missing = dir.join("missing");']
    if pid == 'q01':
        lines += ['let out = dir.join("untouched"); std::fs::write(&out, b"keep").unwrap();',
                  'check(&mut passed, &mut total, "missing", sol::transform(missing.to_str().unwrap(), out.to_str().unwrap()) == -1);',
                  'check(&mut passed, &mut total, "missing_preserves_output", std::fs::read(&out).unwrap() == b"keep");',
                  'let input = dir.join("valid"); std::fs::write(&input, [0, 127, 255]).unwrap();',
                  'check(&mut passed, &mut total, "write_directory", sol::transform(input.to_str().unwrap(), dir.to_str().unwrap()) == -2);',
                  'let bad = dir.join("absent_parent/out");',
                  'check(&mut passed, &mut total, "write_missing_parent", sol::transform(input.to_str().unwrap(), bad.to_str().unwrap()) == -2);',
                  'check(&mut passed, &mut total, "same_path_status", sol::transform(input.to_str().unwrap(), input.to_str().unwrap()) == 0);',
                  'check(&mut passed, &mut total, "same_path_bytes", std::fs::read(&input).unwrap() == [255,128,0]);']
    else:
        lines += ['check(&mut passed, &mut total, "missing", sol::count_fields(missing.to_str().unwrap()) == -1);']
    lines += ['println!("TESTS {} {}", passed, total);']
    return '''fn check(p: &mut usize, t: &mut usize, name: &str, ok: bool) {
        *t += 1; if ok { *p += 1; } else { println!("FAIL {}", name); }
    }
    fn main() {''' + '\n'.join(lines) + '\n}'


def build(c, wd, body):
    extra = []
    if c['ll']:
        try:
            extra, error = G2.build_llvm_objects(c['ll'], 'g10', str(wd))
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
    return m and ' '.join(m.group().split()) == HEADERS[pid]


def grade_one(src, pid, compiler, backend, flags=()):
    src = Path(src).resolve()
    if not src.exists():
        return {'status': 'missing'}
    if not check_header(src, pid):
        return {'status': 'harness_error', 'error': 'contract changed'}
    with tempfile.TemporaryDirectory(prefix='grade_', dir=WORK) as tmp:
        wd = Path(tmp)
        c = G2.compile_pruv(compiler, str(src), str(wd), backend, flags)
        if c['rc']:
            return dict(c, status='pruv_error')
        exe, error = build(c, wd, driver(pid))
        if error:
            return {'status': 'compile_error', 'error': error}
        r = run([exe, wd / 'fixtures'])
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
    out = a.out or HERE / 'results' / f'solutions_{a.compiler}_{a.backend}.json'
    out.write_text(json.dumps({'tools': G2.COMPILERS, 'results': results}, indent=2))
    return int(any(r['status'] != 'ok' for rows in results.values() for r in rows.values()))


if __name__ == '__main__':
    sys.exit(main())
