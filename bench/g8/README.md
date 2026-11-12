# bench/g8 — verified standard module benchmark

Two problems, verified reference implementations and bundle-body mutations for
G8_SPEC section 14 Q. Python 3 stdlib only; existing z3/toolchain required.

| File | Purpose |
|---|---|
| PROBLEMS.md | Statements, frozen host contracts, Python oracle and tests |
| solutions/q01/root.pruv | First duplicate index and checked addition |
| solutions/q02/root.pruv | Bounded sum, nonempty maximum and reversal |
| run.py | py-rust, py-llvm, rs-rust, rs-llvm grader |
| mutate_ops.py | Isolated bundle edits, safe truth and four-configuration verdicts |
| results/solutions.json | Verified results and separate safe_results |
| results/mutants.json | Edits/hashes, truth evidence, verdicts and counts |

Separate fault-injection work lives in faults/.
Separate performance work lives in perf.py and perf/.

## Commands

From the repository root:

```sh
.venv/bin/python bench/g8/run.py bench/g8/solutions
.venv/bin/python bench/g8/run.py bench/g8/solutions --no-verify
.venv/bin/python bench/g8/mutate_ops.py --self-test
.venv/bin/python bench/g8/mutate_ops.py --list
.venv/bin/python bench/g8/mutate_ops.py --jobs 8
```

The grader accepts an optional JSON output path, --compiler py|rs|both and
--backend rust|llvm|both. Safe mode adds safe_results without replacing verified
results. PRUV_PYTHON, PRUVC_RS, RUSTC and CLANG select existing tools.
If the local Rust binary is absent, the fallback is
solutions/.work/target/release/pruvc. In this isolated workspace Python runs
from /Users/spica4345/Projects/pruv/.venv/bin/python (read only); the Rust
compiler is built offline from this checkout with CARGO_TARGET_DIR and TMPDIR
under solutions/.work. Bytecode is disabled and temporary artifacts stay under
that owned directory. No compiler, stdlib or test source is modified.

## Mutants and classification

The catalogue contains 44 incorrect bodies, one weak-contract control and one
equivalent control. Every body mutant retains the exact approved headers.
Each safe truth run uses a disposable pruvc/ + stdlib/ distribution with the
mutated bundle replacing only that copy. Each Rust binary is copied, its single
embedded bundle replaced with equal-length bytes, and signed again on macOS.
Only body whitespace is compacted if needed; trailing spaces pad shorter
bundles. Oversized variants are explicitly marked py-only.

Truth comes from executing the affected function through a public wrapper in
Python/Rust-backend --no-verify mode, against independent Python value oracles.
A caught panic is incorrect. Inputs cover empty/singleton arrays, duplicates,
signed endpoints, absent matches, all-negative maxima, sorted and unsorted
arrays, and exact checked arithmetic overflow boundaries. JSON records test
counts and failing case indices; `inputs(function)` reconstructs the cases.

Every mutant then compiles with both compilers and both backends. Class is the
worst configuration in this order: wrong_but_proved, crash, timeout,
unsupported, unknown, unexecuted, accepted_correct, rejected_checker,
rejected_verify. Verified acceptance of a safe-mode incorrect body is
wrong_but_proved even if verified execution passes. Unknown, timeout, crash
and generated-code build failures never count as successful rejections.
Weak-contract and equivalent controls are excluded from the incorrect count.

--self-test checks uniqueness, exact headers, embedded lengths and classification.
--list prints the catalogue. --limit N is for development and cannot meet the
36-incorrect gate if N is smaller. The full run fails on wrong proofs, unknown
truth, intent mismatch, unresolved configurations or fewer than 36 observed
incorrect mutants. Only the listed checks belong to this worker; independent
author work, fuzzing, faults, performance and the full suite are outside scope.

## Recorded results

| Configuration | q01 verified | q02 verified | q01 safe | q02 safe |
|---|---:|---:|---:|---:|
| py-rust | 141/141 | 179/179 | 141/141 | 179/179 |
| py-llvm | 141/141 | 179/179 | 141/141 | 179/179 |
| rs-rust | 141/141 | 179/179 | 141/141 | 179/179 |
| rs-llvm | 141/141 | 179/179 | 141/141 | 179/179 |

Self-test, --list and the complete --jobs 8 run exited 0. All 44 observed
incorrect mutants were rejected by verification in every configuration.
The weak-contract and equivalent controls each passed in all configurations.
There are 0 wrong_but_proved, 0 unknown truths, 0 unresolved cases, 0 intent
mismatches and 0 py-only mutants. No full suite was run.
