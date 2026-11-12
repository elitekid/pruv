"""G7 repeatable two-array benchmark. All build products remain in perf/."""
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
HERE = ROOT / 'bench/g7'
PY = os.environ.get('PRUV_PYTHON', str(ROOT / '.venv/bin/python'))
RS = os.environ.get('PRUVC_RS', str(ROOT / 'pruvc-rs/target/release/pruvc'))
RUSTC = os.environ.get('RUSTC', str(Path.home() / '.cargo/bin/rustc'))
CLANG = os.environ.get('CLANG', shutil.which('clang') or 'clang')

def run(cmd, timeout=180, cwd=None):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', TMPDIR=str(HERE / 'perf'), CLANG_MODULE_CACHE_PATH=str(HERE / 'perf/clang-cache'))
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

def expose(rs, ll, backend):
    # Benchmark-only adapters in disposable generated artifacts, not compiler changes.
    if backend == 'rust':
        with rs.open('a') as f:
            for name in ['parallel', 'sequential']:
                f.write(f'\npub fn bench_{name}(a: &mut [i64], b: &mut [i64]) {{ {name}(a,b); }}\n')
    else:
        with ll.open('a') as f:
            for name in ['parallel', 'sequential']:
                f.write(f'\ndefine void @bench_{name}(ptr %a, i64 %n, ptr %b, i64 %m) {{\n call void @{name}__pruv_body(ptr %a, i64 %n, ptr %b, i64 %m)\n ret void\n}}\n')
        with rs.open('a') as f:
            for name in ['parallel', 'sequential']:
                f.write(f'\npub fn bench_{name}(a: &mut [i64], b: &mut [i64]) {{ unsafe {{ extern "C" {{ #[link_name="bench_{name}"] fn raw(a:*mut i64,n:i64,b:*mut i64,m:i64); }} raw(a.as_mut_ptr(),a.len() as i64,b.as_mut_ptr(),b.len() as i64); }} }}\n')

def summarize(data):
    data['comparisons'] = []
    for n in sorted({r['size'] for r in data['rows']}):
        rows = {r['variant']:r for r in data['rows'] if r['size']==n}
        for metric in ['kernel','inclusive']:
            med = {k:r[metric]['median_ms'] for k,r in rows.items()}
            ratio = med['pruv_par']/med['rust_par']
            data['comparisons'].append(dict(size=n,timing=metric,pruv_to_native_parallel=ratio,
                speedup_over_pruv_sequential=med['pruv_seq']/med['pruv_par'],within_1_5x=ratio<=1.5))
    data['method'] = dict(warmup=2,order='rotating',mode='safe',setup='two clones of same input',
        inclusive_excludes=['checksum','comparison','deallocation'],scheduler_allocations='not instrumented',
        caveat='Large timing spread; no affinity/frequency control or host-load isolation. Medians are descriptive, not a stable speedup guarantee.')

def report():
    lines = ['# G7 parallel performance', '',
      'Run `PRUV_PYTHON=/path/to/python python -B bench/g7/perf.py --backend both`.',
      'Optional port spot run: `PRUVC_RS=/path/to/pruvc PRUV_PYTHON=/path/to/python python -B bench/g7/perf.py --compiler rs --backend both --sizes 1000`.',
      '', 'Two independent i64 arrays; 32 rounds of `(x * 251 + 17) % 65521` per element.',
      'Pruv safe mode (`--no-verify`), no user requires/ensures; Rust uses checked multiply/add and nonnegative remainder checks.',
      'All builds: rustc `-C opt-level=3 -C overflow-checks=yes`; LLVM and C runtime: clang `-O3`.',
      'Two warmup iterations, then ten measured iterations, rotating the four variants in each iteration.',
      'Two workers for both parallel implementations. Each sample clones the same source into two fresh arrays.',
      'Kernel time excludes copies; inclusive time includes allocation/copy and the kernel, but excludes checksum, comparison and deallocation.',
      'Every output element is compared with an independently computed Rust result; both arrays contribute to an observable checksum.',
      'Benchmark-only adapters expose private generated functions in disposable artifacts. No compiler or public API is changed.',
      'Adapters pass distinct, live arrays and preserve safe body checks; LLVM calls still traverse generated trampolines and the Rust bridge.',
      'Two array allocations per sample; scheduler allocations are not instrumented. For n elements, setup copies 16n bytes and the kernel reads/writes at least 32n bytes.',
      'Source/expected fixtures are allocated outside timing. Peak live array storage is approximately 32n bytes (256 MB at n=8,000,000).',
      '', '| Compiler/backend | Elements per array | Variant | Kernel median ms [min,max] | Inclusive median ms [min,max] |', '|---|---:|---|---:|---:|']
    ratios = []
    machines = []
    for path in sorted((HERE/'results').glob('perf_*.json')):
        data = json.loads(path.read_text())
        if 'rows' not in data or not isinstance(data['rows'],list): continue
        label = data['compiler']+'/'+data['backend']
        machine = data['machine']
        machine_line = f"OS: {machine['os']}; logical cores: {machine['cores']}; {machine['rustc']['stdout'].strip()}; {machine['clang']['stdout'].splitlines()[0]}."
        if machine_line not in machines: machines.append(machine_line)
        if data['status'] != 'ok': lines.append(f'| {label} | - | ERROR: see {path.name} | - | - |')
        for r in data['rows']:
            values = [f"{r[m]['median_ms']:.3f} [{r[m]['min_ms']:.3f},{r[m]['max_ms']:.3f}]" for m in ['kernel','inclusive']]
            lines.append(f"| {label} | {r['size']} | {r['variant']} | {' | '.join(values)} |")
        for n in sorted({r['size'] for r in data['rows']}):
            rows = {r['variant']:r for r in data['rows'] if r['size']==n}
            for metric in ['kernel','inclusive']:
                med = {k:r[metric]['median_ms'] for k,r in rows.items()}
                ratio = med['pruv_par']/med['rust_par']
                ratios.append(f"| {label} | {n} | {metric} | {ratio:.3f}x | {med['pruv_seq']/med['pruv_par']:.3f}x | {'met' if ratio<=1.5 else 'missed'} |")
    lines += ['', '| Compiler/backend | Size | Timing | Pruv par / Rust par | Sequential Pruv / parallel Pruv | 1.5x target |','|---|---:|---|---:|---:|---|', *ratios,
      '', *machines, '', 'Machine/tool versions, raw samples, checksums and spread are in `../results/perf_*.json`.',
      'CPU model sysctl is blocked in this delegated sandbox; logical core count and OS are recorded. No affinity or frequency control is claimed.',
      'Only this macOS arm64 host was executed. Timings are local observations, not confidence intervals or cross-platform guarantees.',
      'Observed large-input ranges span several times their minima, including native Rust baselines. Host load/frequency/scheduling were not isolated.',
      'The large-size median target was met on both backends, but these noisy runs do not establish a stable speedup or an intrinsic backend performance difference.',
      'The Rust-port spot runs compare generated artifacts byte-for-byte with Python before building; see byte_identical_to_python in their JSON.',
      'Small-input timing includes thread spawn/join overhead. If a target is missed, inspect optimizer output and safe-check costs before attributing it to bandwidth or the bridge.', '']
    (HERE/'perf/README.md').write_text('\n'.join(lines))

def main():
    p = argparse.ArgumentParser(__doc__)
    p.add_argument('--backend', choices=['rust','llvm','both'], default='both')
    p.add_argument('--compiler', choices=['py','rs'], default='py')
    p.add_argument('--repeat', type=int, default=10)
    p.add_argument('--sizes', type=int, nargs='+', default=[1000,8000000])
    a = p.parse_args()
    if a.repeat < 10 or min(a.sizes) < 1: p.error('at least ten repeats and positive sizes required')
    machine = dict(os=platform.platform(), cpu=run(['sysctl','-n','machdep.cpu.brand_string']), cores=os.cpu_count(), rustc=run([RUSTC,'--version']), clang=run([CLANG,'--version']))
    failed = False
    for backend in ['rust','llvm'] if a.backend == 'both' else [a.backend]:
        result = dict(compiler=a.compiler, backend=backend, machine=machine, repeat=a.repeat, warmup=2, source_sha256=hashlib.sha256((HERE/'perf/mix.pruv').read_bytes()).hexdigest(), flags=['--no-verify','rustc -C opt-level=3 -C overflow-checks=yes','clang -O3'], rows=[])
        try:
            with tempfile.TemporaryDirectory(dir=HERE / 'perf', prefix='work_') as tmp:
                wd = Path(tmp)
                rs,ll = compile_source(HERE/'perf/mix.pruv',wd,backend, [RS] if a.compiler == 'rs' else None)
                if a.compiler == 'rs':
                    comparison = wd/'py'; comparison.mkdir()
                    prs,pll = compile_source(HERE/'perf/mix.pruv',comparison,backend)
                    result['byte_identical_to_python'] = rs.read_bytes()==prs.read_bytes() and (backend!='llvm' or ll.read_bytes()==pll.read_bytes())
                    assert result['byte_identical_to_python'], 'port artifact mismatch'
                expose(rs,ll,backend)
                exe = build(rs,ll,wd,(HERE/'perf/driver.rs').read_text(),backend)
                for n in a.sizes:
                    samples = [[] for _ in range(4)]
                    for line in require([exe,n,a.repeat],timeout=540).splitlines():
                        v,k,t,c = map(int,line.split()); samples[v].append(dict(kernel_ns=k,inclusive_ns=t,checksum=c))
                    for v,name in enumerate(['pruv_par','pruv_seq','rust_seq','rust_par']):
                        raw = samples[v]
                        assert len(raw) == a.repeat
                        row = dict(size=n,variant=name,raw=raw,bytes_per_array=n*8,setup_copy_bytes=n*16,minimum_kernel_read_write_bytes=n*32,setup_allocations=2)
                        for metric in ['kernel','inclusive']:
                            values = [s[metric+'_ns']/1e6 for s in raw]
                            row[metric] = dict(median_ms=statistics.median(values),min_ms=min(values),max_ms=max(values),stdev_ms=statistics.stdev(values))
                        result['rows'].append(row)
            result['status'] = 'ok'
        except (RuntimeError, AssertionError) as e:
            result.update(status='error', error=str(e)); failed = True
        summarize(result)
        out = HERE / 'results' / ('perf_'+backend+('_rs_spot' if a.compiler=='rs' else '')+'.json')
        out.write_text(json.dumps(result,indent=2)+'\n')
        print(backend,result['status'],flush=True)
    report()
    return int(failed)

if __name__ == '__main__': sys.exit(main())
