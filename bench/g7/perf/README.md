# G7 parallel performance

Run `PRUV_PYTHON=/path/to/python python -B bench/g7/perf.py --backend both`.
Optional port spot run: `PRUVC_RS=/path/to/pruvc PRUV_PYTHON=/path/to/python python -B bench/g7/perf.py --compiler rs --backend both --sizes 1000`.

Two independent i64 arrays; 32 rounds of `(x * 251 + 17) % 65521` per element.
Pruv safe mode (`--no-verify`), no user requires/ensures; Rust uses checked multiply/add and nonnegative remainder checks.
All builds: rustc `-C opt-level=3 -C overflow-checks=yes`; LLVM and C runtime: clang `-O3`.
Two warmup iterations, then ten measured iterations, rotating the four variants in each iteration.
Two workers for both parallel implementations. Each sample clones the same source into two fresh arrays.
Kernel time excludes copies; inclusive time includes allocation/copy and the kernel, but excludes checksum, comparison and deallocation.
Every output element is compared with an independently computed Rust result; both arrays contribute to an observable checksum.
Benchmark-only adapters expose private generated functions in disposable artifacts. No compiler or public API is changed.
Adapters pass distinct, live arrays and preserve safe body checks; LLVM calls still traverse generated trampolines and the Rust bridge.
Two array allocations per sample; scheduler allocations are not instrumented. For n elements, setup copies 16n bytes and the kernel reads/writes at least 32n bytes.
Source/expected fixtures are allocated outside timing. Peak live array storage is approximately 32n bytes (256 MB at n=8,000,000).

| Compiler/backend | Elements per array | Variant | Kernel median ms [min,max] | Inclusive median ms [min,max] |
|---|---:|---|---:|---:|
| py/llvm | 1000 | pruv_par | 0.197 [0.084,1.162] | 0.197 [0.085,1.163] |
| py/llvm | 1000 | pruv_seq | 0.218 [0.110,0.219] | 0.219 [0.111,0.220] |
| py/llvm | 1000 | rust_seq | 0.218 [0.110,0.249] | 0.219 [0.110,0.250] |
| py/llvm | 1000 | rust_par | 0.218 [0.153,0.355] | 0.218 [0.153,0.356] |
| py/llvm | 8000000 | pruv_par | 1173.719 [574.334,2191.010] | 1188.470 [580.117,2209.713] |
| py/llvm | 8000000 | pruv_seq | 2841.322 [1132.901,6143.969] | 2854.403 [1136.838,6162.659] |
| py/llvm | 8000000 | rust_seq | 2992.257 [1809.072,4383.406] | 3021.051 [1815.577,4411.789] |
| py/llvm | 8000000 | rust_par | 1132.053 [668.146,1898.180] | 1178.315 [683.269,1904.292] |
| rs/llvm | 1000 | pruv_par | 0.147 [0.084,0.187] | 0.148 [0.085,0.189] |
| rs/llvm | 1000 | pruv_seq | 0.117 [0.110,0.234] | 0.118 [0.110,0.236] |
| rs/llvm | 1000 | rust_seq | 0.127 [0.110,0.232] | 0.127 [0.110,0.232] |
| rs/llvm | 1000 | rust_par | 0.167 [0.137,0.254] | 0.168 [0.138,0.255] |
| py/rust | 1000 | pruv_par | 0.082 [0.078,0.112] | 0.082 [0.078,0.113] |
| py/rust | 1000 | pruv_seq | 0.115 [0.109,0.117] | 0.115 [0.110,0.117] |
| py/rust | 1000 | rust_seq | 0.113 [0.110,0.117] | 0.114 [0.111,0.117] |
| py/rust | 1000 | rust_par | 0.079 [0.078,0.135] | 0.079 [0.078,0.135] |
| py/rust | 8000000 | pruv_par | 531.349 [456.769,2263.355] | 535.151 [460.150,2273.470] |
| py/rust | 8000000 | pruv_seq | 1023.990 [908.795,2957.932] | 1028.095 [912.871,2967.734] |
| py/rust | 8000000 | rust_seq | 1088.117 [908.028,3357.621] | 1093.047 [912.745,3382.514] |
| py/rust | 8000000 | rust_par | 531.395 [459.398,2851.728] | 537.100 [462.811,2858.229] |
| rs/rust | 1000 | pruv_par | 0.339 [0.172,1.999] | 0.339 [0.173,2.002] |
| rs/rust | 1000 | pruv_seq | 0.110 [0.110,0.382] | 0.111 [0.111,0.383] |
| rs/rust | 1000 | rust_seq | 0.110 [0.110,0.219] | 0.111 [0.110,0.221] |
| rs/rust | 1000 | rust_par | 0.663 [0.216,4.163] | 0.663 [0.217,4.163] |

| Compiler/backend | Size | Timing | Pruv par / Rust par | Sequential Pruv / parallel Pruv | 1.5x target |
|---|---:|---|---:|---:|---|
| py/llvm | 1000 | kernel | 0.905x | 1.106x | met |
| py/llvm | 1000 | inclusive | 0.905x | 1.109x | met |
| py/llvm | 8000000 | kernel | 1.037x | 2.421x | met |
| py/llvm | 8000000 | inclusive | 1.009x | 2.402x | met |
| rs/llvm | 1000 | kernel | 0.879x | 0.799x | met |
| rs/llvm | 1000 | inclusive | 0.881x | 0.800x | met |
| py/rust | 1000 | kernel | 1.032x | 1.412x | met |
| py/rust | 1000 | inclusive | 1.033x | 1.409x | met |
| py/rust | 8000000 | kernel | 1.000x | 1.927x | met |
| py/rust | 8000000 | inclusive | 0.996x | 1.921x | met |
| rs/rust | 1000 | kernel | 0.511x | 0.325x | met |
| rs/rust | 1000 | inclusive | 0.512x | 0.327x | met |

OS: macOS-26.5-arm64-arm-64bit; logical cores: 10; rustc 1.99.1 (58cf8f9c3 2026-10-13); Apple clang version 17.0.0 (clang-1700.6.4.2).

Machine/tool versions, raw samples, checksums and spread are in `../results/perf_*.json`.
CPU model sysctl is blocked in this delegated sandbox; logical core count and OS are recorded. No affinity or frequency control is claimed.
Only this macOS arm64 host was executed. Timings are local observations, not confidence intervals or cross-platform guarantees.
Observed large-input ranges span several times their minima, including native Rust baselines. Host load/frequency/scheduling were not isolated.
The large-size median target was met on both backends, but these noisy runs do not establish a stable speedup or an intrinsic backend performance difference.
The Rust-port spot runs compare generated artifacts byte-for-byte with Python before building; see byte_identical_to_python in their JSON.
Small-input timing includes thread spawn/join overhead. If a target is missed, inspect optimizer output and safe-check costs before attributing it to bandwidth or the bridge.
