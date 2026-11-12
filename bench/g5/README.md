# bench/g5 - inout benchmark (docs/G5_SPEC.md section 14, items 4 and 6)

Two fresh problems (statements in `PROBLEMS.md`), reference solutions, a grader and source mutants for G5 (inout
parameters, exclusive access, `old(a)`; docs/G5_SPEC.md). `perf.py` measures section 14 item 7.

| File | What it is |
|---|---|
| `PROBLEMS.md` | q01 (bounded byte-range transformation over `[u8]`) and q02 (module-based recursive array transformation over `[i64]`), statements only |
| `solutions/q01/`, `solutions/q02/` | reference solutions (`q01/root.pruv`; `q02/root.pruv` plus the child module `q02/xform.pruv`) |
| `run.py` | grader |
| `mutate_ops.py` | source mutants of the reference solutions and their classification |
| `results/` | JSON written by the commands below (empty in the repository, `.gitkeep` only) |

The grader needs the same tools as `bench/g4`: `pruvc/pruvc.py`, `pruvc-rs/target/release/pruvc`, `rustc`, `clang`, `z3`
(through the compilers). Run all commands from the repository root.

## Commands

```
# grade the reference solutions: 2 problems x (py, rs) x (rust, llvm) = 8 runs, exit 1 unless all are ok
python3 bench/g5/run.py bench/g5/solutions                      # -> results/solutions.json
python3 bench/g5/run.py bench/g5/solutions out.json --compiler rs --backend llvm q02
python3 bench/g5/run.py <dir> --no-verify                       # safe mode (checks every call's requires)

# mutation test
python3 bench/g5/mutate_ops.py --self-test                      # catalogue and anchors only, no compiler
python3 bench/g5/mutate_ops.py --list
python3 bench/g5/mutate_ops.py                                  # -> results/mutants.json
python3 bench/g5/mutate_ops.py --only q02 --jobs 8 --timeout 60
```

A solutions directory holds one project directory per problem: `<dir>/q01/root.pruv`, `<dir>/q02/root.pruv`,
`<dir>/q02/xform.pruv`. The grader passes `--rust-bindings` with the LLVM backend, builds the objects with clang and links
a generated Rust test program that calls the root host entries (`sol::<entry>(..)`) and compares the results with the Python
reference of `PROBLEMS.md`.

## Result files

- `results/<dir name>.json` (from `run.py`; `solutions.json` for the reference): `{"solutions", "flags", "results"}`,
  `results[config][problem]` with `config` in `py-rust, py-llvm, rs-rust, rs-llvm`. `status` is `ok` (all tests pass and
  the required structure is present), `wrong` (a test failed, a panic, a crash, or a required construct is missing: see
  `first_failure`), `pruv_error` (the compiler rejected the project or the grader found a changed entry contract or a
  missing module file: see `pruv_errors`), `compile_error`, `timeout`, `missing`.
- `results/mutants.json` (from `mutate_ops.py`): same layout as `bench/g4`: `summary`, `fault_injections` (names only, not
  executed here) and one item per mutant with `operator`, `intent`, `truth`, per-configuration `runs` and the overall
  `class`.
  - `truth` is the independent ground truth from a `--no-verify` run of the grader (rs compiler, rust backend):
    `incorrect`, `correct`, `not_compilable`, `unknown`. The G5 entry contracts are exact, so there is no
    `contract_weak` truth.
  - `class` is the worst verifier/grader outcome over the four configurations: `rejected_verify` / `rejected_checker`
    (successful rejections), `accepted_correct`, `wrong_but_proved` (must be zero), `unknown`, `timeout`, `crash`,
    `unsupported`, `unexecuted` (reported separately, never counted as rejections).
  - `intent` is the author's label. `incorrect`: behaviour differs from the reference (at least 40 explicit ones; fault
    kinds `wrong_index`, `missing_store`, `wrong_frame`, `old_current`, `omitted_call`, `reordered`, plus `wrong_callee` and
    `wrong_value`; counted per kind in `summary.incorrect_by_fault_kind`). `contract`: behaviour unchanged, a contract or
    annotation is falsified or weakened (wrong frame clause, `old(a)` replaced by the current contents, dropped
    invariant, non-shrinking `decreases`), so the modular proof must fail. `correct`: equivalent mutant, a rejection is
    only reported as a false rejection (`summary.correct_rejected_ids`). `weak`: behaviour unchanged, a contract or
    annotation weakened in a way the verifier may legitimately accept (redundant invariant conjuncts, built-in facts);
    recorded separately in `summary.weak_contract`, accepted or rejected is no failure. `auto`: generic regex mutants.
  - Exit code 1 on any `wrong_but_proved`, on an incorrect mutant with an unresolved class or accepted with passing tests,
    on an accepted `contract` mutant, or (without `--only/--limit`) with fewer than 50 mutants or 40 incorrect.

## Assumptions to check first

- Nothing here was run when it was written (no shell). Run `mutate_ops.py --self-test` first (anchors, structure, fault-kind
  coverage), then the grader on `bench/g5/solutions`; fix the reference solutions before reading any mutant result.
- The quantifier-heavy loop proofs (`add_range_sat`, `add_range_wrap`, `fill_range`) and the recursive proofs of
  `rev_range` and `add_from` were written in the style of `examples/g5_reverse.pruv` and `tests/runtime/g5_r07_recursive_call.pruv`
  but not verified. Mutants of intent `correct`/`weak` may be rejected by the verifier (incompleteness); that is reported,
  not a failure.
- These problems are the statements and reference solutions for the independent-author exercise of section 14 item 6;
  the independent attempts, feedback and revisions are recorded elsewhere, not here.
