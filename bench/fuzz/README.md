# Pruv compiler differential fuzzing

Run randomly generated Pruv programs through both the compiler and an independent oracle (`oracle.py`), and compare the results. The default compiler is the Rust implementation (`pruvc-rs/target/release/pruvc`),
`--compiler py` selects the Python implementation (`pruvc/pruvc.py`), and `--compiler-path PATH` selects another location (`tests/compiler_driver.py`, default rs).

## Promises checked

A program accepted by the verifier (pruvc default mode, exit 0) must satisfy the following.

- For every input that satisfies `requires`, there is no out-of-range index, no overflow, and no division-domain violation.
- `ensures` (and invariant/assert/decreases) hold.
- The output equals the oracle's.

Each mode is compared with **its own oracle**. The proof modes (`rust-proof`/`llvm-proof`) use `oracle.run(..., mode="proof")`
(skips the run-time requires checks of inner calls and records `call_requires ...` contract failures), and the safe modes use the `mode="safe"` result.
A verified program gets two results per input (`oracle_proof`, `oracle_safe`), and a rejected program uses only the safe result.
(`oracle` in `results.json` is the safe result, for compatibility.)

- Modes whose oracle result (kind, value, output, detail prefix) is the same must have exactly the same (exit code, stdout, `pruv: ...` line).
  `rust-X == llvm-X` (X = proof, safe) is always required, and proof == safe is required only when the two oracle results are the same.
  When the two oracle results differ, as when an inner call's run-time requires hits the i128 limit, the proof and safe modes may legitimately differ.
- If the oracle says ok: exit 0, the expected stdout, and an **empty** `pruv:` line. If the oracle says error: exit 101, the `pruv:` line starts with the expected prefix,
  and stdout must equal the lines the oracle printed just before the error (each line + newline, or an empty string if none).
- If the oracle says `limit` (step limit exceeded), it counts as not compared in `incomplete` (neither a failure nor a pass).

| Mode | backend | Proof |
|---|---|---|
| `rust-proof` | rust | default (only programs that pass the verifier) |
| `rust-safe` | rust | `--no-verify` |
| `llvm-proof` | llvm | default (only programs that pass the verifier) |
| `llvm-safe` | llvm | `--no-verify` |

Of the programs the verifier rejected, `--rejected-sample` of them get only the 2 safe modes built and compared with the oracle.

## Running

```
python bench/fuzz/run.py [--seed 1] [--programs 100] [--inputs 8] [--max-candidates 400] \
                         [--rejected-sample 30] [--jobs N] [--out DIR] [--keep-work] [--compiler py|rs]
# default output folder: Rust implementation bench/fuzz/out/<seed>_rs, Python implementation (--compiler py) bench/fuzz/out/<seed>
python bench/fuzz/run.py --seed 32 --programs 600 --max-candidates 3000 --avoid-known fz01   # avoid the defect shape already reported
python bench/fuzz/run.py --replay bench/fuzz/out/1_rs/failures/unsound_c1_17     # rerun a saved case
python bench/fuzz/run.py --replay path/to/case.pruv                             # uses the inputs.json next to it
python bench/fuzz/generate.py --seed 1 --count 20 --out /tmp/pruvgen            # only inspect the generated .pruv files
```

- Tools needed: `rustc`, `clang`, Python 3.9 (when choosing the Python implementation, `--compiler py` runs pruvc with `.venv/bin/python` if it exists). Only the standard library is used.
- The `runtime.c` object is built once and reused.
- Exit code: 1 if there is any failure.

### Stages

1. Generate candidates (index 0,1,2,...) and parse them with `oracle.parse_program`. If the oracle does not support one, it is skipped and counted.
2. Run `pruvc --no-verify` (type checking) and the default mode (verification). Both calls also produce the LLVM output (`llvm-safe.ll`/`llvm-proof.ll` and the bindings) in the same run through the hidden test option
   `--also-llvm LL RS`. So the z3 verification runs only once
   per program, and stage 4 hands these files to clang without calling pruvc again. When verification fails pruvc writes no file at all,
   the harness deletes the output paths before the call, and the `llvm-proof` file is written only when the status is `verified` (otherwise `harness_error`).
   If `--no-verify` exits 1 and the stage in the diagnostic JSON is only
   parse/type/effect, it is `generator_invalid`. Any other exit code (negative = signal/crash, 2 = usage, 3 = internal error, etc.) or
   an exit 1 at another stage is an `internal_error` failure, and a time-out (120 seconds) is a `timeout` failure.
   Candidates are issued as a stream: at most `jobs*2` are kept in flight and the next candidate is submitted each time one finishes.
   When `--programs` of them pass verification or `--max-candidates` is reached, only the submitting stops, and the results of the candidates already issued are all collected
   (failures are recorded too). Passing programs beyond `--programs` are not built. If too few pass, a warning is printed and `programs_short` is set.
3. For each program, draw 300 inputs and split them with `check_requires`; 3/4 of `--inputs` are chosen from the satisfying inputs and the rest from violating/undefined inputs (filled with what exists if there are not enough).
4. Build 1 binary per (program, mode). The generated `main` receives the input number as `argv[1]`.
5. Run the binary once per input (limit 10 seconds). Record (exit code, stdout, the first `pruv: ` line).
6. Check and save the failures.
7. Write `summary.json` and a short summary. The work folder is deleted unless `--keep-work` is given.

## Output structure

```
OUT/summary.json                  number of candidates, generator errors, verification passes, rejections (by error code), number of inputs run, number of failures by kind, time per stage (seconds),
                                  incomplete (number of (input, mode) pairs not compared because of the oracle limit),
                                  no_sat_inputs ({count, first 20 names}: programs with no input that satisfies requires),
                                  programs_short (true if the verification passes are fewer than --programs)
OUT/failures/<kind>_<case>/       for each failed case
    case.pruv                     the program
    inputs.json                   lists of arguments
    results.json                  (exit, stdout, pruv line) per mode and input, the oracle results, failure details
    pruvc_output.txt              pruvc output (--no-verify, verification)
OUT/generator_invalid/            the first 10 generated programs that did not pass type checking
```

## G2 mode (`--g2`)

A separate mode that generates G2 types (`[u8]`, `[bool]`, `str`, string literals in code, `substr`, `is_char_boundary`). The spec is `docs/G2_Q1_IMPL.md` §5.
Run without `--g2`, the behavior, output folder, and `summary.json` keys are the same as before (G2 templates are not put into the existing material list).

```
python bench/fuzz/run.py --g2 --seed 41 --programs 200 --rejected-sample 30 [--compiler py|rs]
python bench/fuzz/generate.py --g2 --seed 41 --count 20 --out /tmp/pruvgen_g2
python bench/fuzz/run.py --replay bench/fuzz/out/41_rs_g2/failures/<kind>_<case>   # G2 cases work as is
```

- Generation: `generate_case(seed, index, g2=True)`. The rng is `"g2:<seed>:<index>"`, and picks only from `G2_TEMPLATES`. The input rng name also has the `"g2:"` prefix.
  The default output folder ends with `_g2` (Rust implementation `out/<seed>_rs_g2`, Python implementation `out/<seed>_g2`).
- Type strings: `array_u8`, `array_bool`, `str`. Input JSON: `array_u8` = a list of 0..255 integers, `array_bool` = a list of bools,
  `str` = a JSON string (no surrogates).
- Driver: `array_u8` → `let aJ: Vec<u8> = vec![..];` + `&aJ`, `array_bool` → `Vec<bool>`, `str` → `let aJ: &str = "..";` + `aJ`
  (a character in 0x20..=0x7E that is not `"` or `\` is written as is, the rest as `\u{lowercase hex}`). If the return type is `str`, `println!("{:?}", f(..).as_bytes())`
  (a list of byte integers), `[u8]` is a list of integers, and `[bool]` is `[true, false]` (the oracle's `format_value` has the same shape).
- Safe-mode failure messages (exit 101, `pruv: ` line prefix): `elem_range` → `pruv: element out of range: v (u8 0..=255)`,
  `slice_range` → `pruv: string slice out of bounds: lo..hi (len n)`, `slice_cut` → `pruv: UTF-8 boundary error: lo..hi (len n)`,
  `oob` (including str indexing) → `pruv: index out of bounds:`.
- LLVM backend: the bindings use `Pruv__Str`, `pruv_check_utf8`, `pruv_check_bool`, and `pruv_abi_<f>__typed`. The harness changes only the `pruv_abi_` prefix, so
  `__typed` changes along with it, and the check, copy, and boundary symbols are defined by the shared `runtime.o`.
- Keys added to `summary.json` only in g2 mode: `g2`, `g2_verified` (counted verification passes: a g2 case, at least `--inputs` inputs, run results exist for all modes with no time-out or harness exception, and at least 1 input that satisfies requires and is not an oracle limit; rejections must meet the same condition in safe modes), `g2_rejected_built_safe_modes`,
  `g2_features_verified` (verification passes per tag), `g2_inputs_per_program_min`, `g2_short_inputs` (number of programs whose inputs fell short of `--inputs`).
- Gate: if `g2_verified < --programs` or `g2_rejected_built_safe_modes < --rejected-sample`, it leaves
  `failures_by_kind["g2_shortfall"]` (the sum of the shortfall program counts; details in `summary["g2_shortfall"]`) and exits 1.
  Oracle unsupported, parse error, incomplete, and timeout are not put into the pass count and are counted separately as now.
  To make up for the share dropped from the counted conditions, only in g2 mode it collects verification passes up to 110% of `--programs` and rejected samples up to `--rejected-sample + 5`, so `verified_used` and `rejected_built` can be larger than the requested numbers.
- `results.json` gets `g2` and `g2_features` only for a g2 case. `--replay` recognizes G2 types from the source signature.

### G2 run log (filled in by the main)

| Seed | Compiler | Verification passes | Rejected safe builds | Minimum inputs per program | Short of inputs | Passes per tag | Failures |
|---|---|---|---|---|---|---|---|

## Failure kinds

| kind | Meaning |
|---|---|
| `mode_mismatch` | Modes with the same expected oracle result (or rust-X/llvm-X) differ from each other in (exit code, stdout, `pruv:` line) |
| `oracle_mismatch` | Differs from the per-mode oracle: if ok, exit 0 + the expected stdout + an empty `pruv:` line; if error, exit 101 + a line starting with `expected_stderr_prefix` + the same stdout as the output just before the error (`limit` counts as `incomplete`) |
| `unsound` | Verified + the input satisfies requires, but `oracle_proof` gives an error (oob/overflow/div_domain/internal requires) or there are `contract_failures` (ensures, invariant, assert, decreases, including `call_requires ...`). A `limit` result is also checked first |
| `internal_error` | The pruvc exit code is not 0/1 (3, negative = signal, 2 = usage, etc.), `--no-verify` exits 1 but the diagnostic stage is not parse/type/effect, or the stage of the verifier error JSON is `internal`. An LLVM generator error also arises in the pruvc call of stage 1–2, so it comes here (the details have `rust+llvm` and the tail of the pruvc output) |
| `build_error` | clang/rustc failed although the verifier (or `--no-verify`) accepted it |
| `timeout` | pruvc did not finish within 120 seconds |
| `run_timeout` | The binary did not finish within 10 seconds (if the oracle is `limit`, it counts as `incomplete`) |
| `oracle_error` | The oracle threw an exception (suspect an oracle bug) |
| `harness_error` | An exception of this tool itself |
| `g2_shortfall` | (`--g2` only) Fewer verification-passing g2 programs than `--programs`, or fewer rejected safe-mode builds than `--rejected-sample`. The value is the sum of the shortfalls |

## Oracle independence

`oracle.py` has its own parser and interpreter and imports nothing from `pruvc`.
So it does not share the compiler's bugs. The oracle prints values in the Rust `println!("{}")` format
and supplies the prefix of the `pruv: ...` message. The oracle itself may be wrong, so for an `oracle_mismatch` suspect the oracle first.

## Generator material (`generate.py`)

- Body: straight-line code with `let mut` locals (+ - * / % unary -), `a[e]` indexing (guarded/unguarded), if/else, 1–3 integer/array parameters, returning i64 or bool.
- requires: integer ranges (10, 1000, 10^6, 2^31), `len(a) <= N`, `len(a) >= k`, element-range `forall`, `x < y`, guarded/unguarded `a[x] > 0`, `(y != 0) && ((x / y) > 2)` and an unprotected `/`, `(x % 3) == 1` (Euclidean), `sum`, `count`, guarded/unguarded `max`/`min`, `exists`, sortedness (`j in i..len(a)`, `j in (i + 1)..len(a)`), `==>`.
- Loop templates (with correct invariants): sum (SPEC §9), counting, maximum scan, linear search (`return i` / `-1`), countdown (`while m > 0 decreases m`), last value - first value of a sorted array.
- Mutations (about 35%): drop one invariant, change the last `<=` to `<`, change the condition `i < len(a)` → `i <= len(a)`, step `+1` → `+2`, a wrong decreases, flip a comparison, a mismatched return value.
- Helper function `fn g(p, q)` (about 30%, with its own requires/ensures, called by f).
- ensures (about 60%): ones guaranteed true (`result == <return expression>`, per-template ensures) and random bounds that may be false.
- Inputs: near the requires bounds, 0, ±1, small values, occasionally i64 extremes. Array length 0..8. A parameter that decides the number of iterations has an upper limit (3000).

- Generator-4 material (about 30%): 2 array parameters (`twoarr`), array return and reassignment (`arrret`), Option/Result return (`option`) and
  parameters (`optparam`), structs and enums (`struct`: struct arguments/returns at the f boundary 70%, struct literals, enums, and Option comparisons inside requires,
  observing evaluation order and single evaluation with `tap(v) ! io`, empty structs, Result fields, enum fields).
- Input value formats: Option/Result `{"tag": "Some", "v": 3}` / `{"tag": "None"}` / `{"tag": "Ok", "v": 3}` / `{"tag": "Err", "v": -2}`,
  struct `{"struct": "Point", "fields": {...}}`, enum `{"enum": "Event", "variant": "Hit", "fields": {...}}` (fields in declaration order).
  The case's params types are "i64", "bool", "array", "Option<i64>", "Result<i64>", or a type name, and when a struct is at the f boundary, case["types"].
- The driver prints the return value with `{:?}` (oracle.format_value has the same shape).

## Known limitations

- Neither the generator nor the oracle uses function calls inside contracts. Effects (print/io, alloc/copy), local arrays, assert, nested loops, and
  bool parameters are generated starting with generator 3 (about 20%).
- Array length is at most 8 and value ranges are skewed toward the bounds, so it cannot touch large arrays or resource limits such as the `2^30` iteration budget.
- The oracle's `limit` (step limit exceeded) is not compared and is only counted as `incomplete` (but the `contract_failures` of a `limit` result are used for the `unsound` check).
  Modes that are `limit` are not assumed to have the same expected result, so proof == safe is not required either (rust-X == llvm-X is required).
- Only the first line of stderr that starts with `pruv: ` is looked at for the `pruv: ` line.

## Failures found

- **fz01 — index-assignment evaluation order** (`tests/runtime/fz01_index_assign_order.{pruv,rs,json}`).
  In `b[i] = v`, the proof mode evaluates the value (`v`) first and the safe mode evaluates the index (`i`) first, so the side effects and failure order differ.
  Status: **fixed** (RESULTS.md §10: source order in all modes, the same kind `alloc(n, v)` fz04 too, pinned by `r34_eval_order`).
  Below is the cause record from when it was found. The verified branch of `IndexAssign` in `codegen.py` emits
  `*a.get_unchecked_mut(i) = v`, and Rust evaluates the right side first in this case. `IndexAssign` in `llvmgen.py` follows this as is.
  Generator 3 (the effects material) finds this by itself in 5 of 100. It has already been reported, so it can be avoided with `--avoid-known fz01`
  (bind the value to a local first and then assign).
- **fz02 / fz03 — lints rustc denies in the proof-mode Rust backend** (`tests/runtime/fz02_const_div_zero`, `fz03_const_overflow`).
  If the body of a function whose verification passed vacuously because its requires is contradictory has an operation that folds to a constant such as `x % 0` or `i64::MAX + 1`,
  rustc refuses to compile the proof-mode Rust output (unchecked `%` and `+`) because of the deny-by-default lints `unconditional_panic` and `arithmetic_overflow`.
  The LLVM backend and the safe mode are fine (101 from the entry requires violation). Status: **fixed** (RESULTS.md §10: `unconditional_panic` and `arithmetic_overflow` were added to the Rust backend's allow list,
  and in verified code that operation is unreachable). In fuzzing it appeared in 1 of 600 with generator-2 material (the division material picked constant 0 + a contradictory requires).

## Turning a failure into a regression test

1. Reproduce it with `--replay OUT/failures/<kind>_<case>` and, if possible, shrink the program.
2. For a program the verifier must not accept (a wrong verification among `unsound`): create `tests/must_reject/<name>.pruv` and
   `tests/must_reject/<name>.json` (`{"stage": "verify", "code": "<expected error code>"}`). Follow the existing file format.
3. For run-time behavior (mode mismatch, message, exit code): create `tests/runtime/<name>.pruv`, `tests/runtime/<name>.rs` that calls with one input
   (`fn main() { ... println!("{}", sol::f(...)); }`), and `tests/runtime/<name>.json` stating the expectation
   (e.g. `{"flags": [], "exit": 101, "stdout_contains": null, "stderr_contains": "requires violated"}`).
   For `--no-verify` behavior use `"flags": ["--no-verify"]`, and split multiple inputs into multiple tests.
4. Check with `python tests/run_all.py` (`--backend both` for both backends). A feature that went into the Python implementation first is checked with `--compiler py`.

## Run log

2026-11-10, Mac mini (10 cores), `--jobs 10`. Times are wall-clock.

| Seed | Generator | Passing programs | Candidates | Inputs | Process runs | Time (generate+verify / build / run) | Failures |
|---|---|---|---|---|---|---|---|
| 1 | Generator 1, one binary per program × mode | 100 | 277 | 1,040 | 3,680 | 188 s (13 / 25 / 150) | 0 |
| 1 | Generator 1, `--batch 25` | 100 | 277 | 1,040 | 3,680 | 34 s (14 / 10 / 9) | 0 |
| 3 | Generator 1 | 500 | 1,320 | 5,200 | 18,400 | 326 s (210 / 51 / 65) | 0 |
| 11 | Generator 2 (material expanded) | 100 | 259 | 1,280 | 4,160 | 42 s (21 / 9 / 12) | 0 |
| 12 | Generator 2 | 600 | 1,594 | 6,400 | 22,400 | 177 s (78 / 44 / 54) | 0 |
| 21 | Generator 2, harness with the audit applied (per-mode oracle, streaming) | 66 | 193 | 640 | 2,240 | 21 s (9 / 5 / 6) | 0 |
| 31 | Generator 3 (local arrays, effects, assert, nested loops, bool, helper functions) | 114 | 231 | 1,120 | 3,840 | 23 s (8 / 7 / 9) | fz01 in 5 programs |
| 32 | Generator 3, `--avoid-known fz01` | 606 | 1,325 | 6,370 | 22,264 | 151 s (53 / 36 / 63) | fz02 in 1 program |
| 52 | Generator 4 (2 arrays, array return, Option/Result, struct) | 809 | 1,497 | 6,586 | 25,864 | 132 s (35 / 38 / 59) | 0 |
| 54 | Generator 4, struct at the f boundary 70% | 808 | 1,466 | 6,610 | 25,960 | 145 s (43 / 39 / 63) | 0 |
| 56 | Generator 4, audit applied (requires comparison, tap) | 805 | 1,526 | 6,550 | 25,720 | 154 s (46 / 44 / 64) | 0 |

- After one pruvc call started producing the Rust and LLVM outputs together (`--also-llvm`, RESULTS.md §12), the same seed 56 was measured as two pairs, before and after the change.
  The results are the same (0 failures, 808 passes, 6,550 inputs, 25,720 process runs, same distribution of input results), and the CPU time (user+sys)
  fell from 805 to 645 s and from 876 to 671 s. The wall-clock fluctuated because of other workloads (the run stage of the same code took 81–138 s): 232 → 200 s, 291 → 264 s.
  The difference of 1,519/1,520 candidates is the tail at the point where streaming submission stops (1 rejected candidate), and the build targets are the same.
- The 210 s of generate+verify for seed 3 is due to a few candidates on which z3 took long (2 `verify_unknown`). Generator 2 took 78 s at the same scale.
- Generator 2 input results (seed 12): among verified programs, requires satisfied 3,839 / violated 900 / undefined 61 (all i128 limits,
  a resource limit the spec allows); among rejected programs in safe mode, div_domain 294, oob 43, overflow 25, call-requires violation 25,
  requires undefined 36.
- Detection check: when the oracle's output format is deliberately changed to a wrong one, 8 `oracle_mismatch` cases are caught and reproduced with `--replay`.
- If rustc is not on PATH, run with `PATH=$HOME/.cargo/bin:$PATH` (run.py also looks for `~/.cargo/bin/rustc`).
