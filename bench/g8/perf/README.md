# G8 performance measurements

Commands (repository root; existing Python/z3 environment and Rust toolchain required):

```sh
python3 -B bench/g8/perf.py --part compile --compiler py --repeat 10
python3 -B bench/g8/perf.py --part compile --compiler rs --repeat 10
python3 -B bench/g8/perf.py --part runtime --backend rust --repeat 10
python3 -B bench/g8/perf.py --part runtime --backend llvm --repeat 10
python3 -B bench/g8/perf/report.py
```

PRUV_PYTHON, PRUVC_RS, RUSTC, CLANG and PYTHONPATH override tools. In this delegated copy, missing Python/Rust binaries use the existing original-repository tools read-only. No build outside owned paths. See JSON for exact paths and compiler hashes.
All timings are milliseconds: median [min, max], ten repetitions. Raw samples and standard deviations are in ../results/perf_*.json.

| Compiler | Matched client | Compile + proof ms |
|---|---|---:|
| py | none | 91.031437 [89.920625, 101.614042] |
| py | unused | 261.092312 [256.485666, 331.206334] |
| py | calls | 261.082478 [258.326708, 292.514667] |
| rs | none | 10.001562 [9.628667, 20.345583] |
| rs | unused | 128.321313 [127.101958, 138.339917] |
| rs | calls | 129.640166 [126.443583, 135.150708] |

All clients clamp x into [0,100]. None uses inline branches, unused adds only mod std, calls uses std min/max. Fresh compiler process for each sample; rotating client order; default verification and Rust source emission, excluding native rustc build. No proof cache claim. Import-only cost includes reproving all twelve bodies.

| Backend | Operation | Implementation | Entry | Runtime ms, 1M elements | Binary bytes |
|---|---|---|---|---:|---:|
| rust | sum | std | body | 0.880916 [0.670542, 0.966375] | 492296 |
| rust | sum | std | checked | 1.765855 [1.447583, 2.006541] | 492408 |
| rust | sum | local | body | 0.565146 [0.563167, 0.570958] | 492296 |
| rust | sum | local | checked | 1.710646 [1.453750, 2.090375] | 492408 |
| rust | reverse | std | body | 0.315146 [0.273209, 1.155834] | 492488 |
| rust | reverse | std | checked | 0.327041 [0.283875, 1.323292] | 492488 |
| rust | reverse | local | body | 0.317708 [0.281917, 0.366583] | 492488 |
| rust | reverse | local | checked | 0.316458 [0.279000, 0.551458] | 492488 |
| llvm | sum | std | body | 0.192708 [0.191292, 0.279167] | 492360 |
| llvm | sum | std | checked | 1.406770 [1.102625, 1.902083] | 493576 |
| llvm | sum | local | body | 0.187188 [0.163042, 0.200792] | 492360 |
| llvm | sum | local | checked | 1.476834 [1.210875, 2.414416] | 493576 |
| llvm | reverse | std | body | 0.291000 [0.264166, 0.377458] | 493992 |
| llvm | reverse | std | checked | 0.312208 [0.270375, 1.279541] | 493992 |
| llvm | reverse | local | body | 0.285709 [0.256000, 0.322167] | 493992 |
| llvm | reverse | local | checked | 0.321041 [0.283583, 0.440625] | 493992 |

| Backend | Operation | Implementation | Checked minus body median ms |
|---|---|---|---:|
| rust | sum | std | 0.884938 |
| rust | sum | local | 1.145500 |
| rust | reverse | std | 0.011895 |
| rust | reverse | local | -0.001250 |
| llvm | sum | std | 1.214062 |
| llvm | sum | local | 1.289646 |
| llvm | reverse | std | 0.021208 |
| llvm | reverse | local | 0.035333 |

Body uses --trust-callers; checked uses default verified host entry. The difference estimates host contract cost, not a separately instrumented contract timer. Reverse has no host requires, so its difference measures noise/code layout. Both variants use the same wrapper and equivalent local bodies copied from std, with normal proof enabled.
Runtime builds use rustc --edition=2021 -C opt-level=3 -C overflow-checks=yes and clang -O3 (LLVM C runtime uses PRUV_RUST_ALLOCATOR). Two warmups precede ten in-process measurements. Input[i] = ((i*251+17)%2001)-1000 for i in 0..1,000,000. black_box protects input/output. Sum is checked independently; reverse is checked element-by-element against reversed input and consumed into an index-weighted checksum. Setup, output validation and freeing are outside the timer; reverse allocation is inside.

| Backend | Reverse implementation | Entry | Allocations / allocated bytes per call |
|---|---|---|---|
| rust | std | body | 1 / 8000000 |
| rust | std | checked | 1 / 8000000 |
| rust | local | body | 1 / 8000000 |
| rust | local | checked | 1 / 8000000 |
| llvm | std | body | 1 / 8000000 |
| llvm | std | checked | 1 / 8000000 |
| llvm | local | body | 1 / 8000000 |
| llvm | local | checked | 1 / 8000000 |

Allocation counts use separate instrumented binaries, excluding input creation; the LLVM allocator bridge is counted too. Actual copied bytes are not instrumented and remain unknown. Binary bytes are whole executable file sizes, including host harness and runtime; they are not isolated function text sizes.
Fixed runtime variant order; no CPU affinity, frequency control or system-load isolation. Backend and std/local differences are local observations, not speedup targets. Unexplained slowdowns are explicitly reported below; no causal explanation or cross-machine claim is established.

- rust sum std/local body ratio: 1.559x; timing alone does not identify a cause.
- rust reverse std/local body ratio: 0.992x; timing alone does not identify a cause.
- llvm sum std/local body ratio: 1.029x; timing alone does not identify a cause.
- llvm reverse std/local body ratio: 1.019x; timing alone does not identify a cause.

Machine: macOS-26.5-arm64-arm-64bit; arm64; 10 logical CPUs.
CPU: unavailable (sandbox denied sysctl).
rustc 1.99.1 (58cf8f9c3 2026-10-13)
Apple clang version 17.0.0 (clang-1700.6.4.2)

Not run: full test suite, other platforms, privileged profiling, direct copy-byte instrumentation. Rust compiler was not rebuilt: existing binary used read-only; embedded bundle identity recorded.
