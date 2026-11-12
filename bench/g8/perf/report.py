"""Render measured JSON; does not run benchmarks or edit other workers' files."""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
RESULTS = HERE.parent/'results'

def spread(r):
    return '%.6f [%.6f, %.6f]' % (r['median_ms'],r['min_ms'],r['max_ms'])

def main():
    lines = ['# G8 performance measurements','',
      'Commands (repository root; existing Python/z3 environment and Rust toolchain required):','',
      '```sh',
      'python3 -B bench/g8/perf.py --part compile --compiler py --repeat 10',
      'python3 -B bench/g8/perf.py --part compile --compiler rs --repeat 10',
      'python3 -B bench/g8/perf.py --part runtime --backend rust --repeat 10',
      'python3 -B bench/g8/perf.py --part runtime --backend llvm --repeat 10',
      'python3 -B bench/g8/perf/report.py','```','',
      'PRUV_PYTHON, PRUVC_RS, RUSTC, CLANG and PYTHONPATH override tools. In this delegated copy, missing Python/Rust binaries use the existing original-repository tools read-only. No build outside owned paths. See JSON for exact paths and compiler hashes.',
      'All timings are milliseconds: median [min, max], ten repetitions. Raw samples and standard deviations are in ../results/perf_*.json.','',
      '| Compiler | Matched client | Compile + proof ms |','|---|---|---:|']
    data = []
    for compiler in ('py','rs'):
        path = RESULTS/('perf_compile_'+compiler+'.json')
        if not path.exists(): continue
        d = json.loads(path.read_text()); data.append(d)
        for row in d['rows']:
            lines.append('| %s | %s | %s |' % (compiler,row['client'],spread(row)))
    lines += ['', 'All clients clamp x into [0,100]. None uses inline branches, unused adds only mod std, calls uses std min/max. Fresh compiler process for each sample; rotating client order; default verification and Rust source emission, excluding native rustc build. No proof cache claim. Import-only cost includes reproving all twelve bodies.', '',
      '| Backend | Operation | Implementation | Entry | Runtime ms, 1M elements | Binary bytes |',
      '|---|---|---|---|---:|---:|']
    runtimes = []
    for backend in ('rust','llvm'):
        path = RESULTS/('perf_runtime_'+backend+'.json')
        if not path.exists(): continue
        d = json.loads(path.read_text()); data.append(d); runtimes.append(d)
        for r in d['rows']:
            lines.append('| %s | %s | %s | %s | %s | %d |' % (backend,r['operation'],r['variant'],r['entry'],spread(r),r['binary_bytes']))
    lines += ['', '| Backend | Operation | Implementation | Checked minus body median ms |', '|---|---|---|---:|']
    for d in runtimes:
        for op in ('sum','reverse'):
            for variant in ('std','local'):
                rows = {r['entry']:r for r in d['rows'] if r['operation']==op and r['variant']==variant}
                if len(rows)==2:
                    lines.append('| %s | %s | %s | %.6f |' % (d['backend'],op,variant,rows['checked']['median_ms']-rows['body']['median_ms']))
    lines += ['', 'Body uses --trust-callers; checked uses default verified host entry. The difference estimates host contract cost, not a separately instrumented contract timer. Reverse has no host requires, so its difference measures noise/code layout. Both variants use the same wrapper and equivalent local bodies copied from std, with normal proof enabled.',
      'Runtime builds use rustc --edition=2021 -C opt-level=3 -C overflow-checks=yes and clang -O3 (LLVM C runtime uses PRUV_RUST_ALLOCATOR). Two warmups precede ten in-process measurements. Input[i] = ((i*251+17)%2001)-1000 for i in 0..1,000,000. black_box protects input/output. Sum is checked independently; reverse is checked element-by-element against reversed input and consumed into an index-weighted checksum. Setup, output validation and freeing are outside the timer; reverse allocation is inside.', '',
      '| Backend | Reverse implementation | Entry | Allocations / allocated bytes per call |', '|---|---|---|---|']
    for d in runtimes:
        for r in d['rows']:
            if 'allocation_samples' in r:
                values = sorted(set(tuple(x) for x in r['allocation_samples']))
                lines.append('| %s | %s | %s | %s |' % (d['backend'],r['variant'],r['entry'],', '.join('%d / %d'%v for v in values)))
    lines += ['', 'Allocation counts use separate instrumented binaries, excluding input creation; the LLVM allocator bridge is counted too. Actual copied bytes are not instrumented and remain unknown. Binary bytes are whole executable file sizes, including host harness and runtime; they are not isolated function text sizes.',
      'Fixed runtime variant order; no CPU affinity, frequency control or system-load isolation. Backend and std/local differences are local observations, not speedup targets. Unexplained slowdowns are explicitly reported below; no causal explanation or cross-machine claim is established.','']
    for d in runtimes:
        for op in ('sum','reverse'):
            rows = {r['variant']:r for r in d['rows'] if r['operation']==op and r['entry']=='body'}
            if len(rows)==2:
                ratio=rows['std']['median_ms']/rows['local']['median_ms']
                lines.append('- %s %s std/local body ratio: %.3fx; timing alone does not identify a cause.'%(d['backend'],op,ratio))
    if data:
        m=data[0]['machine']
        lines += ['', 'Machine: %s; %s; %s logical CPUs.'%(m['os'],m['architecture'],m['cores']),
          'CPU: '+(m['cpu']['stdout'].strip() or 'unavailable (sandbox denied sysctl).'),
          m['rustc']['stdout'].strip(), m['clang']['stdout'].splitlines()[0] if m['clang']['stdout'] else m['clang']['stderr']]
    for d in data:
        if d['status'] != 'ok': lines += ['', 'NOT COMPLETED: '+d.get('error','unknown')]
    lines += ['', 'Not run: full test suite, other platforms, privileged profiling, direct copy-byte instrumentation. Rust compiler was not rebuilt: existing binary used read-only; embedded bundle identity recorded.']
    (HERE/'README.md').write_text('\n'.join(lines)+'\n')
    faultpath=RESULTS/'faults.json'
    if faultpath.exists():
        faults=json.loads(faultpath.read_text())['rows']
        table=['# G8 Q faults and performance result','', '| Fault | Detected | Detecting tests | Gaps |','|---|---|---|---|']
        for r in faults:
            table.append('| %s | %s | %s | %s |'%(r['id'],'yes' if r['detected'] else 'no',', '.join(t.split('  -- ')[0] for t in r['detecting_tests']) or 'none',r['gap'] or 'none'))
        table += ['', 'Patch hashes and exact commands: bench/g8/faults/README.md and bench/g8/results/faults.json. All mutations applied independently to disposable copies under owned paths; copies removed. No compiler, stdlib or test source edited in the working tree.','']+lines
        (ROOT/'.g9q_indep/g8-q-faults-perf-result.md').write_text('\n'.join(table)+'\n')

if __name__=='__main__':
    main()
