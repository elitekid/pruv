# bench/g7 - scoped parallel-call benchmark

Two fresh problems and verified reference solutions for G7_SPEC section 8 Q
items 2 and 4. All benchmark source and documentation use English.

| File | Purpose |
|---|---|
| `PROBLEMS.md` | Statements, frozen host contracts, exact Python references and test domains |
| `solutions/q01/root.pruv` | Saturating and wrapping byte-range transforms, exact frames |
| `solutions/q02/root.pruv` | Two output arrays sharing one immutable integer input |
| `run.py` | Four-configuration grader, verified and safe modes |
| `mutate_ops.py` | 59 unique explicit source mutations, ground truth and classification |
| `results/solutions.json` | Verified results and separate `safe_results` |
| `results/mutants.json` | Per-mutant source edits/hashes, truth run, four verdicts and summary |

Separate compiler fault-injection work lives in `faults/`.
Separate performance work lives in `perf.py` and `perf/`.

## Commands

Run from the repository root using the existing Python environment with z3,
the existing Rust compiler port, rustc and clang. No dependencies are installed
and no compiler is rebuilt.

```sh
.venv/bin/python bench/g7/run.py bench/g7/solutions
.venv/bin/python bench/g7/run.py bench/g7/solutions --no-verify
.venv/bin/python bench/g7/mutate_ops.py --self-test
.venv/bin/python bench/g7/mutate_ops.py --list
.venv/bin/python bench/g7/mutate_ops.py --jobs 8
```

`run.py` accepts an optional output JSON path and
`--compiler py|rs|both --backend rust|llvm|both`. Both default to `both`.
A verified invocation writes `results`; a safe invocation adds/replaces
`safe_results` in the same JSON, preserving the verified results.
`mutate_ops.py` accepts an optional output JSON path and `--limit N` for
diagnosis; limited runs do not establish the full count gate.

`PRUV_PYTHON`, `PRUVC_RS`, `RUSTC` and `CLANG` override tool paths.
Recorded runs used `.venv/bin/python` and `pruvc-rs/target/release/pruvc` via those
environment variables.
Python compiler source is always taken from this checkout.
Build products, generated mutant roots, compiler output, and temporary/cache
files are placed under ignored `solutions/.work/` within this checkout.
Bytecode generation is disabled. The grader reuses the existing G2 build
helpers and the G10 host-build approach.

## Contracts and oracle

Each reference executes both computations in one par group, then selects a
result through an immutable host entry. Both selectors are tested. The grader
requires the exact public entry contract and a par construct after comment
removal. It compares complete returned arrays with Python-computed expectations,
including frame positions and lengths, and checks inputs remain unchanged.
The Rust driver uses one loop over literal cases, avoiding repeated optimized
host-call code for each test case.

q01 has 248 calls / 744 assertions per configuration; q02 has 26 calls / 52
assertions. Tests include empty ranges/arrays, unequal lengths, byte endpoints,
all byte values, bounded integer extremes, both selectors, and deterministic
random inputs (seed 7007). Tests and proof obligations are complementary;
finite tests alone are not a universal correctness claim.

## Mutant classification

The catalogue contains only deliberate exact source edits, with unique hashes
and unchanged public contracts. No regex or equivalent mutants pad the
incorrect denominator.

- `truth` comes from an independent `--no-verify` rs/rust compile and run:
  `incorrect`, `correct`, `not_compilable`, or `unknown`.
- `class` is the worst of py-rust, py-llvm, rs-rust and rs-llvm in G5 order:
  `wrong_but_proved`, `crash`, `timeout`, `unsupported`, `unknown`,
  `unexecuted`, `accepted_correct`, `rejected_checker`, `rejected_verify`.
- `intent` distinguishes 51 behavioral errors, four static-invalid cases,
  two false-contract cases, one weak-contract case and one equivalent control.
  Static-invalid and behavior-preserving cases are excluded from the
  >=40 behaviorally incorrect denominator.
- Fault kinds cover wrong values/indices/targets, missing stores/branches,
  writes outside the promised frame, old/current confusion, duplicate writable
  arguments, declared io effects and reachable foreign calls.
  Missing-branch mutants substitute a no-op worker, retaining a real two-branch
  group. Foreign leakage is a pure declared Rust call reached from a worker.
  Alloc alone is permitted by G7 and is not treated as a forbidden effect.
- Weak contracts may legitimately fail modular proof at a caller; they are
  reported separately. Equivalent controls must be considered separately from
  incorrect mutations.
- Crashes, unknowns, timeouts, build failures and harness errors are never
  counted as successful rejections. The command fails for unresolved
  incorrect cases, incorrect acceptance, accepted false contracts, unrejected
  static cases, unknown ground truth or fewer than 40 observed incorrect cases.

The first development run exposed a summary-name error before saving results.
One whole-range wrong-target mutant also yielded a solver unknown; the final
catalogue expresses that wrong target at the element helper call instead,
retaining its adequate contracts. The full final catalogue is rerun; results
do not reuse verdicts from that development run.

## Scope

Only these reference solutions and source-mutant checks are claimed here.
Independent-author attempts, compiler fault injections, fuzzing, performance
measurements, the full repository suite and other execution platforms are
outside this worker's checks.


## Recorded results

The final catalogue self-test and full --jobs 8 mutation run exited 0.

| Compiler/backend | q01 verified | q02 verified |
|---|---:|---:|
| py-rust | 744/744 | 52/52 |
| py-llvm | 744/744 | 52/52 |
| rs-rust | 744/744 | 52/52 |
| rs-llvm | 744/744 | 52/52 |

51 behaviorally incorrect mutants are rejected by verification in all four
configurations. The four static-invalid mutants are rejected by the checker.
Both false contracts and the weakened helper contract are rejected by
verification; the equivalent control is accepted. Overall: 54 rejected_verify,
4 rejected_checker, 1 accepted_correct, **0 wrong_but_proved**. No unknowns,
timeouts, crashes, unexecuted cases, intent mismatches or configuration
differences remain.

| Fault kind | Total | Behaviorally incorrect |
|---|---:|---:|
| duplicate_writable | 2 | 0 |
| effect_leakage | 1 | 0 |
| equivalent | 1 | 0 |
| false_frame | 1 | 1 |
| false_frame_contract | 1 | 0 |
| foreign_leakage | 1 | 0 |
| missing_branch | 2 | 2 |
| missing_store | 5 | 5 |
| old_current | 2 | 2 |
| old_current_contract | 1 | 0 |
| weak_contract | 1 | 0 |
| wrong_index | 4 | 4 |
| wrong_target | 4 | 4 |
| wrong_value | 33 | 33 |

Safe mode also passed all eight problem/configuration runs with the same assertion counts. Static io leakage is rejected by effect propagation (missing_effect); the foreign case uses a valid trusted declaration to exercise parallel_foreign.
