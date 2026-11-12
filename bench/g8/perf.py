"""G8 fresh-process proof and million-element runtime measurements."""
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
import time

ROOT = Path(__file__).resolve().parents[2]
HERE = ROOT / 'bench/g8'
PY = os.environ.get('PRUV_PYTHON', str(ROOT / '.venv/bin/python') if (ROOT / '.venv/bin/python').exists() else '/Users/spica4345/Projects/pruv/.venv/bin/python')
RS = os.environ.get('PRUVC_RS', str(ROOT / 'pruvc-rs/target/release/pruvc') if (ROOT / 'pruvc-rs/target/release/pruvc').exists() else '/Users/spica4345/Projects/pruv/pruvc-rs/target/release/pruvc')
RUSTC = os.environ.get('RUSTC', str(Path.home() / '.cargo/bin/rustc'))
CLANG = os.environ.get('CLANG', shutil.which('clang') or 'clang')

def run(cmd, timeout=180, cwd=None):
    env = dict(os.environ, PYTHONPATH=os.environ.get('PYTHONPATH', '/Users/spica4345/Projects/pruv/.venv/lib/python3.9/site-packages'), PYTHONDONTWRITEBYTECODE='1', PATH=str(Path.home()/'.cargo/bin')+os.pathsep+os.environ.get('PATH',''), TMPDIR=str(HERE / 'perf'), CLANG_MODULE_CACHE_PATH=str(HERE / 'perf/clang-cache'))
    try:
        p = subprocess.run(list(map(str, cmd)), text=True, capture_output=True, timeout=timeout, env=env, cwd=cwd)
        return dict(command=list(map(str, cmd)), rc=p.returncode, stdout=p.stdout, stderr=p.stderr)
    except (OSError, subprocess.TimeoutExpired) as e:
        return dict(command=list(map(str, cmd)), rc=-1, stdout='', stderr=str(e))

def require(cmd, **kwargs):
    r = run(cmd, **kwargs)
    if r['rc']: raise RuntimeError(json.dumps(r))
    return r['stdout']

def compile_source(source, wd, backend, compiler=None, flags=()):
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

def stats(values):
    return dict(raw_ms=values, median_ms=statistics.median(values), min_ms=min(values),
                max_ms=max(values), stdev_ms=statistics.stdev(values))

def machine():
    return dict(os=platform.platform(), architecture=platform.machine(), cores=os.cpu_count(),
                cpu=run(['/usr/sbin/sysctl','-n','machdep.cpu.brand_string']),
                rustc=run([RUSTC,'--version']),clang=run([CLANG,'--version']))

def sources():
    dest = HERE/'perf'
    simple = 'pub fn run(x: i64) -> i64 { if x < 0 { return 0; } if x > 100 { return 100; } return x; }\n'
    clients = {'none':simple, 'unused':'mod std;\n'+simple,
      'calls':'mod std;\npub fn run(x: i64) -> i64 { return crate::std::max_i64(crate::std::min_i64(x, 100), 0); }\n'}
    for name, source in clients.items():
        (dest/('compile_'+name+'.pruv')).write_text(source)
    bundle = (ROOT/'stdlib/std.pruv').read_text()
    for op in ('sum','reverse'):
        name = op+'_i64'
        body = bundle[bundle.index('pub fn '+name):].split('\npub fn ',1)[0].replace('pub fn '+name,'fn local_'+name)
        wrapper = (ROOT/('tests/runtime/g8_r07_sum_i64/root.pruv' if op == 'sum' else 'tests/runtime/g8_r12_reverse_i64/root.pruv')).read_text()
        (dest/(op+'_std.pruv')).write_text(wrapper)
        (dest/(op+'_local.pruv')).write_text(body+'\n'+wrapper.replace('mod std;','').replace('crate::std::'+name,'local_'+name))

def compile_bench(repeat, compiler):
    result = dict(machine=machine(),repeat=repeat,compiler=compiler,backend='rust',mode='verified',rows=[],status='ok')
    command = [PY,ROOT/'pruvc/pruvc.py'] if compiler == 'py' else [RS]
    result['compiler_path'] = str(command[-1])
    result['compiler_sha256'] = hashlib.sha256(Path(command[-1]).read_bytes()).hexdigest()
    if compiler == 'rs':
        result['embedded_bundle_matches'] = (ROOT/'stdlib/std.pruv').read_bytes() in Path(RS).read_bytes()
    try:
        with tempfile.TemporaryDirectory(dir=HERE/'perf',prefix='compile_') as tmp:
            # Rotate order to reduce drift; every sample starts a fresh process.
            samples = {k:[] for k in ('none','unused','calls')}
            for i in range(repeat):
                keys = list(samples); keys = keys[i%3:]+keys[:i%3]
                for name in keys:
                    start = time.perf_counter()
                    compile_source(HERE/'perf'/('compile_'+name+'.pruv'),Path(tmp),'rust',command)
                    samples[name].append((time.perf_counter()-start)*1000)
            result['rows'] = [dict(client=k,**stats(v)) for k,v in samples.items()]
    except RuntimeError as e:
        result.update(status='error',error=str(e))
    result['method'] = 'Fresh process parse/check/prove/Rust emission, no native build, no proof cache. Rotating client order. Existing toolchain read-only when absent in copy.'
    save('compile_'+compiler,result)
    return result['status'] == 'ok'

def driver(op):
    # Counters are sampled separately from wall-clock timings; atomic allocation
    # bookkeeping therefore does not perturb the timed binaries.
    call = 'let output = sol::run(std::hint::black_box(&input));'
    check = ('assert_eq!(output, expected); let checksum = output;' if op == 'sum' else
             'assert!(output.iter().eq(input.iter().rev())); let checksum: i64 = output.iter().enumerate().map(|(i,x)| (i as i64+1)*x).sum(); assert_eq!(checksum, expected);')
    expected = ('input.iter().sum()' if op == 'sum' else 'input.iter().rev().enumerate().map(|(i,x)| (i as i64+1)*x).sum()')
    return '''
fn main() {
 let input: Vec<i64> = (0..1_000_000).map(|i| ((i as i64 * 251 + 17) % 2001) - 1000).collect();
 let expected: i64 = EXPECTED;
 let repeats: usize = std::env::args().nth(1).unwrap().parse().unwrap();
 for i in 0..repeats+2 {
  #[cfg(count_alloc)] { CALLS.store(0, std::sync::atomic::Ordering::Relaxed); BYTES.store(0, std::sync::atomic::Ordering::Relaxed); }
  let start = std::time::Instant::now();
  CALL
  std::hint::black_box(&output);
  let ns = start.elapsed().as_nanos();
  #[cfg(count_alloc)] let counts = (CALLS.load(std::sync::atomic::Ordering::Relaxed), BYTES.load(std::sync::atomic::Ordering::Relaxed));
  CHECK
  if i >= 2 {
   #[cfg(not(count_alloc))] println!("{} {}", ns, checksum);
   #[cfg(count_alloc)] println!("{} {}", counts.0, counts.1);
  }
 }
}
'''.replace('EXPECTED',expected).replace('CALL\n',call+'\n').replace('CHECK',check)

ALLOCATOR = '''
use std::alloc::{GlobalAlloc, Layout, System};
use std::sync::atomic::{AtomicUsize, Ordering};
static CALLS: AtomicUsize = AtomicUsize::new(0);
static BYTES: AtomicUsize = AtomicUsize::new(0);
struct Counting;
unsafe impl GlobalAlloc for Counting {
 unsafe fn alloc(&self,l:Layout)->*mut u8 { CALLS.fetch_add(1,Ordering::Relaxed); BYTES.fetch_add(l.size(),Ordering::Relaxed); System.alloc(l) }
 unsafe fn alloc_zeroed(&self,l:Layout)->*mut u8 { CALLS.fetch_add(1,Ordering::Relaxed); BYTES.fetch_add(l.size(),Ordering::Relaxed); System.alloc_zeroed(l) }
 unsafe fn realloc(&self,p:*mut u8,l:Layout,n:usize)->*mut u8 { CALLS.fetch_add(1,Ordering::Relaxed); BYTES.fetch_add(n,Ordering::Relaxed); System.realloc(p,l,n) }
 unsafe fn dealloc(&self,p:*mut u8,l:Layout) { System.dealloc(p,l) }
}
#[global_allocator] static GLOBAL: Counting = Counting;
'''

def runtime_bench(repeat, backend):
    result = dict(machine=machine(),repeat=repeat,warmup=2,size=1000000,backend=backend,
                  compiler='py',mode='verified',rows=[],status='ok',
                  flags=['rustc -C opt-level=3 -C overflow-checks=yes','clang -O3'])
    try:
        with tempfile.TemporaryDirectory(dir=HERE/'perf',prefix='runtime_') as tmp:
            for op in ('sum','reverse'):
                for variant in ('std','local'):
                    for mode,flags in [('body',('--trust-callers',)),('checked',())]:
                        wd = Path(tmp)/(op+'_'+variant+'_'+mode); wd.mkdir()
                        source = HERE/'perf'/(op+'_'+variant+'.pruv')
                        rs,ll = compile_source(source,wd,backend,flags=flags)
                        exe = build(rs,ll,wd,driver(op),backend)
                        samples = [list(map(int,l.split())) for l in require([exe,repeat]).splitlines()]
                        assert len(samples) == repeat and len({s[1] for s in samples}) == 1
                        row = dict(operation=op,variant=variant,entry=mode,checksum=samples[0][1],
                                   binary_bytes=exe.stat().st_size,**stats([s[0]/1e6 for s in samples]))
                        if op == 'reverse':
                            # Rebuild only the host with counters, retaining verified generated code.
                            main = wd/'main.rs'; main.write_text(main.read_text()+ALLOCATOR)
                            links = []
                            if backend == 'llvm':
                                for name in ('generated','runtime'):
                                    links += ['-C','link-arg='+str(wd/(name+'.o'))]
                            require([RUSTC,'--edition=2021','--cfg','count_alloc','-C','opt-level=3','-C','overflow-checks=yes',main,'-o',exe,*links])
                            counts = [list(map(int,l.split())) for l in require([exe,repeat]).splitlines()]
                            row['allocation_samples'] = counts
                            row['copied_bytes'] = None
                            row['copy_note'] = 'No byte-copy instrumentation. Allocation counters count Rust allocator calls/bytes, including LLVM PRUV_RUST_ALLOCATOR bridge; input setup excluded.'
                        result['rows'].append(row)
                        print(backend,op,variant,mode,row['median_ms'],flush=True)
    except (RuntimeError,AssertionError) as e:
        result.update(status='error',error=str(e))
    result['method'] = 'Two warmups then >=10 in-process samples; deterministic million-element input. black_box inputs/results; independent sum or full reversal and weighted checksum checked outside timing. Input construction, validation and result drop excluded. Body includes reverse allocation; checked-minus-body is an estimate of host-check overhead (no host preconditions for reverse). Allocation counts from separate instrumented binaries. Fixed variant order; no affinity/frequency/load control.'
    save('runtime_'+backend,result)
    return result['status'] == 'ok'

def save(part,result):
    result['python_compiler_hashes'] = {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'pruvc').glob('*.py')}
    result['bundle_sha256'] = hashlib.sha256((ROOT/'stdlib/std.pruv').read_bytes()).hexdigest()
    result['source_hashes'] = {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (HERE/'perf').glob('*.pruv')}
    (HERE/'results'/('perf_'+part+'.json')).write_text(json.dumps(result,indent=2)+'\n')
    print(part,result['status'],result.get('error',''),flush=True)

def main():
    p = argparse.ArgumentParser(__doc__)
    p.add_argument('--part',choices=['compile','runtime'],required=True)
    p.add_argument('--compiler',choices=['py','rs'],default='py')
    p.add_argument('--backend',choices=['rust','llvm'],default='rust')
    p.add_argument('--repeat',type=int,default=10)
    a = p.parse_args()
    if a.repeat < 10: p.error('at least ten repetitions required')
    sources()
    ok = compile_bench(a.repeat,a.compiler) if a.part == 'compile' else runtime_bench(a.repeat,a.backend)
    return int(not ok)

if __name__ == '__main__':
    sys.exit(main())

