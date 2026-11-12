# Stage 5 cost measurement

Run `python3 -B bench/s5/perf.py --backend both`.
Port spot: `PRUVC_RS=/path/to/pruvc python3 -B bench/s5/perf.py --compiler rs --backend rust --sizes 100`.
Python falls back to the existing z3 site-packages path documented in the brief; PRUV_PYTHON/PYTHONPATH can override it.

The costed mix.pruv performs n outer iterations, each with 32 inner iterations and a call to step.
Its exact budget is 65*n: one outer unit and 32 pairs of inner-loop/call units; step has cost zero.
The recurrence is (x*251+17)%65521. A separate native Rust recurrence computes the expected checksum.
twin.pruv removes only cost and spent lines. The verified Rust, LLVM IR and Rust bindings are compared as bytes before building.
Exact generated artifacts are retained here as {compiler}_{backend}_{mode}_{variant}.{rs,ll}.
Both verified binaries execute at both input sizes and check the same checksum. Byte identity, rather than timing ratios, establishes zero added runtime code.

Safe mode uses --no-verify for both variants. Builds use rustc -C opt-level=3 -C overflow-checks=yes and clang -O3.
Each executable receives two warmup calls then ten measured calls. black_box protects runtime inputs and the result.
Timing excludes startup, independent checksum computation and checksum assertions. The complete raw samples and spread are in ../results/perf_*.json.
Variant order is costed then twin; no CPU affinity, frequency control or load isolation. Ratios are local observations, not stable cross-machine estimates.
Even byte-identical verified artifacts show timing differences of about 15% in small samples; the measured LLVM safe ratio of 1.17x cannot isolate counter cost from host frequency/order effects.

| Compiler/backend | Mode | Outer iterations | Costed median ms [min,max] | Twin median ms [min,max] | Ratio | Checksum |
|---|---|---:|---:|---:|---:|---:|
| py/llvm | verified | 100 | 0.009833 [0.009792,0.009917] | 0.009833 [0.009833,0.009875] | 1.0000x | 39111 |
| py/llvm | verified | 20000 | 2.305438 [1.967167,2.310666] | 2.383792 [2.319667,2.640542] | 0.9671x | 29072 |
| py/llvm | safe | 100 | 0.009770 [0.009708,0.009792] | 0.009750 [0.009750,0.009791] | 1.0021x | 39111 |
| py/llvm | safe | 20000 | 2.283480 [2.280375,2.290417] | 1.951250 [1.951208,1.955292] | 1.1703x | 29072 |
| py/rust | verified | 100 | 0.009833 [0.009792,0.009875] | 0.011520 [0.011500,0.011625] | 0.8535x | 39111 |
| py/rust | verified | 20000 | 1.966500 [1.966416,1.969333] | 1.966500 [1.966458,1.969125] | 1.0000x | 29072 |
| py/rust | safe | 100 | 0.009750 [0.009708,0.009792] | 0.009750 [0.009709,0.009833] | 1.0000x | 39111 |
| py/rust | safe | 20000 | 1.951313 [1.951209,1.953875] | 1.954604 [1.951250,2.021875] | 0.9983x | 29072 |
| rs/rust | verified | 100 | 0.009833 [0.009792,0.011083] | 0.011625 [0.011541,0.011666] | 0.8458x | 39111 |
| rs/rust | safe | 100 | 0.011500 [0.011416,0.011583] | 0.009750 [0.009708,0.009792] | 1.1795x | 39111 |

Machine: macOS-26.5-arm64-arm-64bit; arm64; 10 logical cores.
CPU model: unavailable (sysctl denied by sandbox).
rustc 1.99.1 (58cf8f9c3 2026-10-13).
Apple clang version 17.0.0 (clang-1700.6.4.2).
The Rust-port spot used the already-built binary from /Users/spica4345/Projects/pruv/pruvc-rs/target/release/pruvc read-only; it was not rebuilt in this copy.
All four spot artifacts (verified/safe, costed/twin) were compared byte-for-byte with the Python compiler output before execution.
No full suite, cross-platform run, CPU model lookup outside sandbox, or privileged operation was performed.
