# bench/g4 - modules benchmark (docs/G4_SPEC.md section 14, items 3-4)

Two fresh problems (statements in `PROBLEMS.md`), reference solutions, a grader, source mutants and a 100-module scale
fixture for G4 (modules, visibility, host entries; SPEC.md section 6f).

| File | What it is |
|---|---|
| `PROBLEMS.md` | q01 (bounded array service split over `store` and `store/check`) and q02 (recursive tree service, scalar host wrappers), statements only |
| `solutions/q01/`, `solutions/q02/` | reference multi-file solutions (`root.pruv` plus child modules) |
| `run.py` | grader; also the `--scale` measurement |
| `mutate_ops.py` | source mutants of the reference solutions and their classification |
| `results/` | JSON written by the commands below (empty in the repository, `.gitkeep` only) |

The grader needs the same tools as `bench/g9`: `.venv/bin/python` with `pruvc/pruvc.py`, `pruvc-rs/target/release/pruvc`,
`rustc`, `clang`, `z3` (through the compilers). Run all commands from the repository root.

## Commands

```
# grade the reference solutions: 2 problems x (py, rs) x (rust, llvm) = 8 runs, exit 1 unless all are ok
python3 bench/g4/run.py bench/g4/solutions                      # -> results/solutions.json
python3 bench/g4/run.py bench/g4/solutions out.json --compiler rs --backend llvm q02
python3 bench/g4/run.py <dir> --no-verify                       # safe mode (checks every call's requires)

# mutation test
python3 bench/g4/mutate_ops.py --self-test                      # catalogue and anchors only, no compiler
python3 bench/g4/mutate_ops.py --list
python3 bench/g4/mutate_ops.py                                  # -> results/mutants.json
python3 bench/g4/mutate_ops.py --only q02 --jobs 8 --timeout 60

# 100-module scale fixture (cold whole-program compiles, no incremental claim)
python3 bench/g4/run.py --scale                                 # -> results/scale.json
python3 bench/g4/run.py --scale --repeat 3 --backend rust --keep
```

A solutions directory holds one project directory per problem: `<dir>/q01/root.pruv`, `<dir>/q01/store.pruv`,
`<dir>/q01/store/check.pruv`, `<dir>/q02/...`. The compiler is started on `root.pruv` of the project; the grader
passes `--rust-bindings` with the LLVM backend, builds the objects with clang and links a generated Rust test program
that calls the root host entries (`sol::<entry>(..)`) and compares the results with the Python reference of
`PROBLEMS.md`.

## Result files

- `results/<dir name>.json` (from `run.py`; `solutions.json` for the reference): `{"solutions", "flags", "results"}`,
  `results[config][problem]` with `config` in `py-rust, py-llvm, rs-rust, rs-llvm`. `status` is `ok` (all tests
  pass and the required structure is present), `wrong` (a test failed, a panic, a crash, or a required construct is
  missing: see `first_failure`), `pruv_error` (the compiler rejected the project or the grader found a changed entry
  contract/missing module file: see `pruv_errors`), `compile_error` (generated Rust or LLVM did not build), `timeout`,
  `missing`. `tests_passed/tests_total` counts the checks.
- `results/mutants.json` (from `mutate_ops.py`): `summary`, `fault_injections` (names only, not executed here) and one
  item per mutant with `operator`, `intent`, `truth`, per-configuration `runs` and the overall `class`.
  - `truth` is the independent ground truth from a `--no-verify` run of the grader (rs compiler, rust backend):
    `incorrect`, `correct`, `contract_weak` (wrong results that keep every stated contract and whose every function
    contract, children included, the interpreter `bench/fuzz/oracle.py` finds satisfied; only q02 `tree_height` has such
    a gap), `not_compilable`, `unknown`.
  - `class` is the worst verifier/grader outcome over the four configurations: `rejected_verify` / `rejected_checker`
    (successful rejections), `accepted_correct`, `wrong_but_proved` (the failure the benchmark must never show),
    `unknown`, `timeout`, `crash`, `unsupported`, `unexecuted` (reported separately, never counted as rejections).
  - `intent` is the author's label: `incorrect`, `weak`, `contract` (behaviour unchanged but a contract or annotation
    is falsified or weakened, so the modular proof must fail), `correct` (equivalent; a rejection is only reported as
    a false rejection), `auto` (generic regex mutants). `summary.intent_mismatch` lists labels that disagree with the
    truth (informational).
  - Exit code 1 on any `wrong_but_proved`, on an incorrect mutant with an unresolved class or accepted with passing
    tests, on an accepted `contract` mutant, or (without `--only/--limit`) with fewer than 30 mutants or 20 incorrect.
- `results/scale.json` (from `run.py --scale`): fixture description (`modules`, `files`, `lines`) and one row per
  compiler x backend x mode (`proof`, `no-verify`) with `rc`, `min_s`, `median_s` of the compile (compiler start-up
  included). The fixture is a ternary tree of 99 modules plus the root: each module has a private helper `bump` and a
  public `step` whose exact contract (`result == N * x + E`) is proved from the children's contracts; the root entry
  `run` calls the first three modules. The output is deterministic (no randomness).

## Assumptions to check first

- Nothing here was run when it was written (no shell). Run `mutate_ops.py --self-test` first (anchors, structure), then
  the grader on `bench/g4/solutions`; fix the reference solutions before reading any mutant result.
- The quantifier-heavy proofs (`store::insert`, `store::range_sum`) and the cross-module `size`/`decreases` proofs in
  q02 are written in the style of the G9 references but were not verified.
- The oracle sees a module project only through `flatten()` in `mutate_ops.py` (one file, renamed items); if it cannot
  parse a mutant, that mutant is classified `incorrect` (never `contract_weak`).
