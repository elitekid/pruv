"""Stage 5 cost overhead benchmark. All build products remain in perf/."""
import sys
sys.dont_write_bytecode = True
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
HERE = ROOT / 'bench/s5'
PY = os.environ.get('PRUV_PYTHON', str(ROOT / '.venv/bin/python') if (ROOT / '.venv/bin/python').exists() else sys.executable)
RS = os.environ.get('PRUVC_RS', str(ROOT / 'pruvc-rs/target/release/pruvc'))
RUSTC = os.environ.get('RUSTC', str(Path.home() / '.cargo/bin/rustc'))
CLANG = os.environ.get('CLANG', shutil.which('clang') or 'clang')

def run(cmd, timeout=180, cwd=None):
    env = dict(os.environ, PYTHONPATH=os.environ.get('PYTHONPATH', '/Users/spica4345/Projects/pruv/.venv/lib/python3.9/site-packages'), PYTHONDONTWRITEBYTECODE='1', TMPDIR=str(HERE / 'perf'), CLANG_MODULE_CACHE_PATH=str(HERE / 'perf/clang-cache'))
    try:
        p = subprocess.run(list(map(str, cmd)), text=True, capture_output=True, timeout=timeout, env=env, cwd=cwd)
        return dict(command=list(map(str, cmd)), rc=p.returncode, stdout=p.stdout, stderr=p.stderr)
    except (OSError, subprocess.TimeoutExpired) as e:
        return dict(command=list(map(str, cmd)), rc=-1, stdout='', stderr=str(e))

def require(cmd, **kwargs):
    r = run(cmd, **kwargs)
    if r['rc']: raise RuntimeError(json.dumps(r))
    return r['stdout']

def compile_source(source, wd, backend, compiler=None, flags=('--no-verify',)):
    compiler = compiler or [PY, ROOT / 'pruvc/pruvc.py']
    rs, ll = wd / 'generated.rs', wd / 'generated.ll'
    cmd = list(compiler) + [source, '--backend', backend, '-o', ll if backend == 'llvm' else rs] + list(flags)
    if backend == 'llvm': cmd += ['--rust-bindings', rs]
    require(cmd)
    return rs, ll

def build(rs, ll, wd, driver, backend):
    links = []
    if backend == 'llvm':
        for name, src, flags in [('generated', ll, []), ('runtime', ROOT / 'pruvc/runtime.c', ['-std=c11', '-DPRUV_RUST_ALLOCATOR'])]:
            obj = wd / (name + '.o')
            require([CLANG, '-O3', '-Wno-override-module', *flags, '-c', src, '-o', obj])
            links += ['-C', 'link-arg=' + str(obj)]
    main = wd / 'main.rs'
    main.write_text('#![allow(dead_code,unused_imports,unused_parens)]\n#[path = ' + json.dumps(str(rs)) + '] mod sol;\n' + driver)
    exe = wd / 'program'
    require([RUSTC, '--edition=2021', '-C', 'opt-level=3', '-C', 'overflow-checks=yes', main, '-o', exe, *links])
    return exe

def main():
    p = argparse.ArgumentParser(__doc__)
    p.add_argument('--backend', choices=['rust','llvm','both'], default='both')
    p.add_argument('--compiler', choices=['py','rs'], default='py')
    p.add_argument('--repeat', type=int, default=10)
    p.add_argument('--sizes', type=int, nargs='+', default=[100,20000])
    a = p.parse_args()
    if a.repeat < 10 or not all(0 < n <= 1000000 for n in a.sizes):
        p.error('at least ten repetitions; sizes in 1..1000000')
    source = HERE/'perf/mix.pruv'
    twin = HERE/'perf/twin.pruv'
    twin.write_text(''.join(line for line in source.read_text().splitlines(True)
                            if 'cost ' not in line and 'spent' not in line))
    machine = dict(os=platform.platform(), architecture=platform.machine(), cores=os.cpu_count(),
                   cpu=run(['sysctl','-n','machdep.cpu.brand_string']),
                   rustc=run([RUSTC,'--version']), clang=run([CLANG,'--version']))
    failed = False
    for backend in ['rust','llvm'] if a.backend == 'both' else [a.backend]:
        result = dict(compiler=a.compiler, backend=backend, machine=machine, repeat=a.repeat,
                      warmup=2, flags=['rustc -C opt-level=3 -C overflow-checks=yes','clang -O3'],
                      source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(), rows=[], artifacts=[])
        compiler_path = Path(RS) if a.compiler == 'rs' else ROOT/'pruvc/pruvc.py'
        result['compiler_path'] = str(compiler_path)
        if compiler_path.exists():
            result['compiler_sha256'] = hashlib.sha256(compiler_path.read_bytes()).hexdigest()
        try:
            with tempfile.TemporaryDirectory(dir=HERE/'perf', prefix='work_') as tmp:
                wd = Path(tmp)
                compiler = [RS] if a.compiler == 'rs' else None
                for mode, flags in [('verified',()),('safe',('--no-verify',))]:
                    built = {}
                    artifacts = {}
                    for variant, src in [('costed',source),('twin',twin)]:
                        dest = wd/(mode+'_'+variant); dest.mkdir()
                        rs,ll = compile_source(src,dest,backend,compiler,flags)
                        artifacts[variant] = [rs.read_bytes()] + ([ll.read_bytes()] if backend == 'llvm' else [])
                        # Keep exact generated evidence, before any build adapters.
                        for file in [rs] + ([ll] if backend == 'llvm' else []):
                            evidence = HERE/'perf'/(a.compiler+'_'+backend+'_'+mode+'_'+variant+file.suffix)
                            evidence.write_bytes(file.read_bytes())
                        if a.compiler == 'rs':
                            pywd = dest/'py'; pywd.mkdir()
                            prs,pll = compile_source(src,pywd,backend,None,flags)
                            same = artifacts[variant] == [prs.read_bytes()] + ([pll.read_bytes()] if backend == 'llvm' else [])
                            result['artifacts'].append(dict(mode=mode,variant=variant,byte_identical_to_python=same))
                            assert same, 'Rust port artifact mismatch'
                        built[variant] = build(rs,ll,dest,(HERE/'perf/driver.rs').read_text(),backend)
                    if mode == 'verified':
                        result['verified_byte_identical'] = artifacts['costed'] == artifacts['twin']
                        assert result['verified_byte_identical'], 'verified erasure mismatch'
                    for n in a.sizes:
                        row = dict(mode=mode,size=n)
                        for variant in ['costed','twin']:
                            samples = [list(map(int,line.split())) for line in require([built[variant],n,a.repeat]).splitlines()]
                            assert len(samples) == a.repeat
                            values = [s[0]/1e6 for s in samples]
                            row[variant] = dict(raw=samples,median_ms=statistics.median(values),min_ms=min(values),
                                                max_ms=max(values),stdev_ms=statistics.stdev(values))
                        assert [v[1] for v in row['costed']['raw']] == [v[1] for v in row['twin']['raw']]
                        row['overhead_ratio'] = row['costed']['median_ms']/row['twin']['median_ms']
                        result['rows'].append(row)
            result['status'] = 'ok'
        except (RuntimeError, AssertionError) as e:
            result.update(status='error',error=str(e)); failed = True
        result['method'] = 'Two in-process warmups, ten timed calls per executable; costed then twin; scalar checksum checked against independent Rust recurrence. No affinity/frequency control. Timings exclude process startup, reference computation and checksum checks.'
        result['artifact_hashes'] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                     for p in (HERE/'perf').glob(a.compiler+'_'+backend+'_*')}
        out = HERE/'results'/('perf_'+backend+('_rs_spot' if a.compiler == 'rs' else '')+'.json')
        out.write_text(json.dumps(result,indent=2)+'\n')
        print(backend,result['status'], result.get('error',''),flush=True)
    return int(failed)

if __name__ == '__main__':
    sys.exit(main())

