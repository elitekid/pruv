# bench/s5 — cost-bound benchmark

Two problems, verified reference implementations, and explicit source mutations
for STAGE5_SPEC section 8 Q. Python 3 stdlib only; existing z3/toolchain required.

| File | Purpose |
|---|---|
| PROBLEMS.md | Statements, frozen host contracts, cost bounds, Python oracle and tests |
| solutions/q01/root.pruv | Nested square-grid traversal |
| solutions/q02/root.pruv | Copy and elementwise costed helper calls |
| run.py | py-rust, py-llvm, rs-rust, rs-llvm grader |
| mutate_ops.py | Explicit edits, safe-mode truth, four-configuration verdicts |
| results/solutions.json | Verified results and separate safe_results |
| results/mutants.json | Edits/hashes, truth evidence, all verdicts and counts |

Separate fault-injection work lives in faults/.
Separate performance work lives in perf.py and perf/.

## Commands

From the repository root:

```sh
.venv/bin/python bench/s5/run.py bench/s5/solutions
.venv/bin/python bench/s5/run.py bench/s5/solutions --no-verify
.venv/bin/python bench/s5/mutate_ops.py --self-test
.venv/bin/python bench/s5/mutate_ops.py --list
.venv/bin/python bench/s5/mutate_ops.py --jobs 8
```

When .venv is absent, use python3 with
PYTHONPATH=/Users/spica4345/Projects/pruv/.venv/lib/python3.9/site-packages,
as specified by the worker brief. PRUV_PYTHON, PRUVC_RS, RUSTC and CLANG
can select existing tools. The default Rust compiler path is
pruvc-rs/target/release/pruvc, falling back to
solutions/.work/target/release/pruvc under this benchmark. In this isolated
copy the compiler is built offline with CARGO_TARGET_DIR pointing there.
No compiler source is edited. Temporary files and build products stay under
solutions/.work; bytecode generation is disabled. Existing G2 build helpers
are reused, following G7's host driver and JSON layout.

The grader accepts an optional output path, --compiler py|rs|both and
--backend rust|llvm|both (both by default). --no-verify adds safe_results
without replacing verified results. The mutant tool accepts an optional
output path and --limit N; a limited run cannot establish the full gate.

## Grading and classification

Each problem has 38 calls and 76 assertions per configuration, including
empty inputs, all lengths through the maximum 32, mixed signs and endpoints.
The driver compares the full result and unchanged input. Panics are caught
per case so remaining cases, including maximum-cost inputs, still execute.
The public header including the exact cost text is frozen by the grader.
The stated implementation structure is reviewed in source.

The catalogue contains 50 unique deliberate exact edits: 42 incorrect
programs, six false spent annotations, one weak helper contract and one
equivalent control. Behavioral edits retain adequate exact postconditions.
The cost-header mutations bypass only the frozen cost-text submission rule;
the compiler still verifies their actual mutated bound. Header mutations
must not be rejected by the harness in place of a compiler proof obligation.

Truth is obtained independently from rs/rust --no-verify over the problem
tests and maximum-cost inputs. A cost-exceeded panic is incorrect even when
the returned values would otherwise be right. Truth categories are correct,
incorrect, not_compilable and unknown; a timeout is unknown.

Class is the worst of all four configurations in G7 order:
wrong_but_proved, crash, timeout, unsupported, unknown, unexecuted,
accepted_correct, rejected_checker, rejected_verify. A verified acceptance
of a safe-mode incorrect mutant is wrong_but_proved even when cost erasure
lets its verified executable pass the behavioral tests.

Wrong unit counting in an erased invariant may preserve runtime behavior;
these six false annotations are reported under contract intent, not padded
into the incorrect denominator. Weak-contract and equivalent controls are
separate too. Other operators include missing loops/bodies, extra calls,
C-1 bounds, wrong multipliers, extra alloc/copy, increased loop bounds,
wrong values and wrong indices. JSON records all source edits and hashes.

Crashes, unknowns, timeouts and build failures are not successful rejections.
The command fails on wrong proofs, unresolved incorrect cases, incorrect
acceptance, accepted false annotations, unknown truth, intent mismatch or
fewer than 40 observed incorrect programs.

Only the listed solution and mutant commands belong to this worker's checks.
Independent-author work, fault injections, fuzzing, performance measurements,
the full test suite and other platforms are outside this report.

## Recorded results

| Configuration | q01 verified | q02 verified | q01 safe | q02 safe |
|---|---:|---:|---:|---:|
| py-rust | 76/76 | 76/76 | 76/76 | 76/76 |
| py-llvm | 76/76 | 76/76 | 76/76 | 76/76 |
| rs-rust | 76/76 | 76/76 | 76/76 | 76/76 |
| rs-llvm | 76/76 | 76/76 | 76/76 | 76/76 |

Self-test and the full --jobs 8 mutant run exited 0.

| Intent | Count | rejected_verify | accepted_correct |
|---|---:|---:|---:|
| contract | 6 | 6 | 0 |
| incorrect | 42 | 42 | 0 |
| weak | 1 | 1 | 0 |
| correct | 1 | 0 | 1 |

| Operator | Total | Incorrect |
|---|---:|---:|
| wrong_unit | 6 | 0 |
| missing_loop | 3 | 3 |
| missing_body | 2 | 2 |
| extra_call | 3 | 3 |
| bound_minus_one | 2 | 2 |
| wrong_multiplier | 4 | 4 |
| extra_alloc | 2 | 2 |
| extra_copy | 2 | 2 |
| loop_plus_one | 3 | 3 |
| wrong_value | 19 | 19 |
| wrong_index | 2 | 2 |
| weak_contract | 1 | 0 |
| equivalent | 1 | 0 |

All 42 observed incorrect programs were rejected by verification in all
four configurations. Overall: 49 rejected_verify, 1 accepted_correct and
0 wrong_but_proved; all other classes have count zero. No unknown truth,
configuration differences, intent mismatches or unresolved cases.
The six false annotations and weak-contract case are excluded from the
incorrect denominator; the equivalent control is accepted.

The first development grader invocation ran before the Rust build completed
and therefore recorded missing-binary errors for the Rust configurations.
The final complete rerun replaced those results after the offline build
finished successfully (6m 25s). Shell heredoc creation was blocked by the
sandbox; file writes used allowed workspace operations instead. Toolchain
temporary-cache warnings did not prevent the final builds or checks.
