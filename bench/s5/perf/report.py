"""Render the recorded Stage 5 measurements and fault results; never rerun tests."""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[1]
perf = [json.loads(p.read_text()) for p in sorted((HERE/'results').glob('perf_*.json'))]
lines = ['# Stage 5 cost measurement','',
 'Run `python3 -B bench/s5/perf.py --backend both`.',
 'Port spot: `PRUVC_RS=/path/to/pruvc python3 -B bench/s5/perf.py --compiler rs --backend rust --sizes 100`.',
 'Python falls back to the existing z3 site-packages path documented in the brief; PRUV_PYTHON/PYTHONPATH can override it.',
 '',
 'The costed mix.pruv performs n outer iterations, each with 32 inner iterations and a call to step.',
 'Its exact budget is 65*n: one outer unit and 32 pairs of inner-loop/call units; step has cost zero.',
 'The recurrence is (x*251+17)%65521. A separate native Rust recurrence computes the expected checksum.',
 'twin.pruv removes only cost and spent lines. The verified Rust, LLVM IR and Rust bindings are compared as bytes before building.',
 'Exact generated artifacts are retained here as {compiler}_{backend}_{mode}_{variant}.{rs,ll}.',
 'Both verified binaries execute at both input sizes and check the same checksum. Byte identity, rather than timing ratios, establishes zero added runtime code.',
 '',
 'Safe mode uses --no-verify for both variants. Builds use rustc -C opt-level=3 -C overflow-checks=yes and clang -O3.',
 'Each executable receives two warmup calls then ten measured calls. black_box protects runtime inputs and the result.',
 'Timing excludes startup, independent checksum computation and checksum assertions. The complete raw samples and spread are in ../results/perf_*.json.',
 'Variant order is costed then twin; no CPU affinity, frequency control or load isolation. Ratios are local observations, not stable cross-machine estimates.',
 'Even byte-identical verified artifacts show timing differences of about 15% in small samples; the measured LLVM safe ratio of 1.17x cannot isolate counter cost from host frequency/order effects.',
 '', '| Compiler/backend | Mode | Outer iterations | Costed median ms [min,max] | Twin median ms [min,max] | Ratio | Checksum |',
 '|---|---|---:|---:|---:|---:|---:|']
for data in perf:
    for row in data['rows']:
        cells = ['%.6f [%.6f,%.6f]' % (row[k]['median_ms'],row[k]['min_ms'],row[k]['max_ms']) for k in ['costed','twin']]
        lines.append('| %s/%s | %s | %s | %s | %s | %.4fx | %s |' %
            (data['compiler'],data['backend'],row['mode'],row['size'],*cells,row['overhead_ratio'],row['costed']['raw'][0][1]))
machine = perf[0]['machine']
lines += ['', 'Machine: %s; %s; %s logical cores.' % (machine['os'],machine['architecture'],machine['cores']),
          'CPU model: unavailable (sysctl denied by sandbox).',
          machine['rustc']['stdout'].strip()+'.', machine['clang']['stdout'].splitlines()[0]+'.',
          'The Rust-port spot used the already-built binary from /Users/spica4345/Projects/pruv/pruvc-rs/target/release/pruvc read-only; it was not rebuilt in this copy.',
          'All four spot artifacts (verified/safe, costed/twin) were compared byte-for-byte with the Python compiler output before execution.',
          'No full suite, cross-platform run, CPU model lookup outside sandbox, or privileged operation was performed.', '']
(HERE/'perf/README.md').write_text('\n'.join(lines))
faults = json.loads((HERE/'results/faults.json').read_text())['rows']
out = ['# Stage 5 Q: compiler faults and performance','',
       '| Fault | Detected | Detecting named tests (modes/details in JSON) | Gap |',
       '|---|---|---|---|']
for row in faults:
    names = sorted(set(t.split('  -- ')[0].split(' [')[0] for t in row['detecting_tests']))
    out.append('| %s | %s | %s | %s |' % (row['id'],'yes' if row['detected'] else 'no',', '.join(names),row['gap'] or 'none observed'))
out += ['', 'Clean baselines passed before fault application. Full commands and failure diagnostics are in bench/s5/results/faults.json.',
        'A detected proof failure is a regression on an existing positive proof; it is not necessarily an incorrectly accepted negative program.',
        'The s5_proof runner tries Rust first and stops each row on failure, so those fault rows do not establish separate LLVM detection.',
        'The existing must_reject group compiles through the Rust source path even with --backend both; its findings concern the shared verifier, not independent backend coverage.',
        'No fixtures were added to tests/. Each fault is a standalone .diff against Python compiler sources.',
        'Isolation deviation: the user forbids writes outside this copy, so disposable compiler-only snapshots were created and deleted inside bench/s5/faults, following current G7 practice; /tmp and full-repository cp -R were not used.',
        '', *lines[1:]]
(ROOT/'.g9q_indep/s5-q-faults-perf-result.md').write_text('\n'.join(out))
