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

## G3 mode (`--g3`)

A separate mode for generics (`docs/G3_SPEC.md` §7.8, `SPEC.md` §6c). Without `--g3` the generator, the output folder and the `summary.json` keys are unchanged
(the same seed generates the same programs; `generate_case(seed, index, g2=False, g3=False)`).

```
python bench/fuzz/run.py --g3 --seed 41 --programs 100 --compiler rs     # then again with --compiler py
python bench/fuzz/run.py --g3 --seeds 41,56,57 --programs 100 --max-candidates 400 --compiler rs
python bench/fuzz/generate.py --g3 --seed 41 --count 20 --out /tmp/pruvgen_g3
python bench/fuzz/oracle.py                                               # oracle self-test, includes the G3 cases
python bench/fuzz/run.py --replay bench/fuzz/out/41_rs_g3/failures/<kind>_<case>
```

(`--seeds` runs one child process per seed with the other options unchanged, and with `--out DIR` each seed writes to `DIR/<seed>`. The default output folder ends with `_g3`:
`out/<seed>_rs_g3`, `out/<seed>_g3` for `--compiler py`.)

**Generator** (`generate.py`, `generate_g3_case`, rng `"g3:<seed>:<index>"`). Each case is a few verified generic *fragments* (`G3_FRAGS`) plus one concrete entry `fn f(..)`:

- generic functions over `T`, `T: Element`, `A, B`: `id`, `wrap`, `get_or`, `forward`, `wrap_twice`, `result_or`, `fail`, `to_result`, `first`, `last`, `len_of`, `set_first`,
  `swap_ends`, `copy_all`, `copy_loop`, `rev`, `repeat`, `fill_loop`, `mk_pair`, `swap`, `fst`, `snd`, `set_pair_first`, `pick_by`, `left_or`, `flip`, `bump_tag`, `retag`;
- generic structs/enums `Pair<A, B>`, `Choice<A, B>`, `Tagged<T>`, and `Option<X>` / `Result<X>` with `X` in `i64`, `bool`, `Pair<..>`, `Option<..>`;
- explicit type arguments everywhere, nested generic calls (`get_or::<Option<X>>(wrap::<Option<X>>(o), None::<X>)`), `[T]` reads/copies/stores/`alloc`;
- contracts with abstract equality, guarded payload access (`is_some(o) ==> result == some_val(o)`, `is_variant`/`variant_field`), bounded `forall` over `[T]`,
  `count` over equality, loops with invariants (`copy_loop`, `rev`, `fill_loop`, counting loops over `[bool]`/`[i64]` that read the length through `len_of::<T>`);
- the entry `f` is a non-generic wrapper (generic functions are not exported) that calls instances at `i64` and `bool`. Values at the `f` boundary are
  `i64`, `bool`, `[i64]`, `[bool]`, `Option<i64|bool>`, `Result<i64|bool>` (inputs as `{"tag": "Some", "v": ..}`); `Pair`/`Choice`/`Tagged` stay inside the body because
  the Rust name of a struct instance (`pruv_g3_t_4_Pair_2_i_b`) is compiler-defined. A case with only bool-like parameters gets an unused `pad: i64` parameter so that at least 8 distinct inputs exist;
- 11 scenario families (`G3_SCENARIOS`: ident, optfallback, optret, arrfirst, dual, arrays, loopcount, pairs, choice, tagged, forward); occasionally an extra unused fragment is added
  (an unused definition is still proved).
- **About 30% are deliberately unproved but well-typed** (`g3_defect`): a dropped `requires` clause, a false `ensures`, a dropped loop invariant, or a defective fragment
  (`G3_BAD_FRAGS`: deleted bounds guard, wrong element, wrong active payload, store at the wrong index, off-by-one index, wrong length, `tag + 2`). They are expected to be rejected
  and are then built/run only in the two safe modes. `case["g3_bad"]` and `case["g3_mutation"]` say what was done (also in the first source line as a comment). If the verifier accepts one anyway it is treated as any verified program.

**Oracle** (`oracle.py`). The existing independent interpreter (own lexer/parser/interpreter written from `SPEC.md`, no import from `pruvc`) got a generic mode that is switched on
only when the source has generic syntax (`fn f<T>`, `struct S<A>`, `enum E<A>` or an explicit `::<..>`), so non-generic sources behave exactly as before:
`<T, U: Element>` declaration lists, type applications (`Pair<i64, bool>`, `Option<Option<T>>`, `[T]`), explicit instantiations `f::<..>(..)`, `Some::<T>(x)`, `None::<T>`,
`Ok::<T>(x)`, `Err::<T>(c)`, `Pair::<A, B> { .. }`, `Choice::<A, B>::Left(x)`. Values are untyped at run time, so type arguments are parsed and dropped; equality of abstract values in contracts is
structural (an enum compares only its active payload). It evaluates code in i64 (overflow/`oob`/`div_domain` faults, safe mode checks every call's `requires`, proof mode records
`call_requires` instead) and contracts over unbounded integers, exactly as in the other modes. Anything it cannot evaluate raises `OracleUnsupported`, which is a failure in G3 mode.
`python bench/fuzz/oracle.py` runs `_selftest_g3` (Option fallback at bool, nested `Option<Option<i64>>`, `Pair` swap with a false-ensures check, `Choice` + `variant_field`, `rev` over `[bool]`).

**Harness** (`run.py --g3`).

- Per program: at least 8 inputs (`--inputs` is raised to 8), 3/4 satisfying `requires`; verified programs run in 4 modes (`rust-proof`, `rust-safe`, `llvm-proof`, `llvm-safe`), unproved ones in the 2 safe modes. Each mode is compared with its own oracle result (proof/safe), rust-X == llvm-X, as in the other modes.
- Both compilers: run the same seed once with `--compiler rs` and once with `--compiler py`. Programs and inputs are identical (the generator and the input rng do not depend on the compiler),
  and `summary.json` has `g3_digest` (hash of status, exit code, stdout and the `pruv:` line per mode and input) and `g3_digest_exit_stdout` (without the `pruv:` line); equal digests mean the two compilers did exactly the same.
- `--g3-safe-only N` (default 20): number of deliberately unproved programs that must be built and run in safe mode. Generation continues until `--programs` (+10%) programs verified and `N` (+5) unproved ones were rejected
  (or `--max-candidates` is reached; raise it, about 1.6 candidates per verified program are needed). A few rejected programs that were meant to verify are also run in safe mode and their source + verifier output saved in `unexpected_rejects/`.
- In G3 mode the callee name in `pruv: requires violated: <fn>` is matched without the trailing colon, because the run-time name of a generic instance is compiler-defined.
- Counted as success (`g3_verified`, `g3_safe_only`): a g3 case with at least `--inputs` inputs, run results for all modes without timeout or harness exception, no recorded failure, and (verified) at least one input that satisfies `requires`
  and that the proof-mode oracle compared to the end (not `limit`, not an oracle error). Crashes, timeouts, `limit`, oracle errors, unsupported or unparsable programs are never counted as success.
- Report per seed (printed, and as keys in `summary.json`): `g3_generated`, `g3_verified`, `g3_safe_only`, `g3_executions_compared` (and `g3_executions_not_compared`), `g3_failures`, plus `g3_kinds_verified`, `g3_features_verified`,
  `g3_inputs_per_program_min`, `g3_unproved_by_design_verified_anyway`, `g3_unexpected_rejects` (count, names, error codes), `compiler`.
- Gate / extra failure kinds: `g3_shortfall` (fewer counted verified programs than `--programs` or fewer counted safe-only programs than `--g3-safe-only`; the value is the sum of the shortfalls, details in `summary["g3_shortfall"]`),
  `g3_generator_invalid` (a generated program did not type-check; the first 10 are in `generator_invalid/`), `g3_oracle_gap` (the oracle could not parse/evaluate a generated program; the first 10 are in `oracle_gap/`).
  The other failure kinds are those of the table below. Exit code 1 if any failure.
- `results.json` of a g3 case also has `g3`, `g3_features`, `g3_unproved_by_design`, `g3_mutation`. `--replay` treats a source with `::<` as a G3 case.

**Known gaps (G3).**

- `main` is not generated or run (the driver calls `f`); struct/enum instances do not cross the `f` boundary (see above), so the ABI of generic struct instances is not exercised by this mode.
- The generator is template-based (fragments + 11 families with random type choices), not a free-form grammar; type errors (`generic_bound`, `type_arity`, ...) and contract-domain errors are not generated on purpose.
- Specialization limits, resource limits of the contract iteration budget (2^30) and arrays above 100 elements are not reached (loops are capped at 100 iterations, arrays at 8 elements).
- Unproved cases are only well-typed mutations of the templates; a mutant the verifier proves anyway (a redundant `requires`) is simply checked as a verified program.
- Unverified assumption: unused parameters (`pad`) and forward references to generic functions are accepted by the type checker; if not, `g3_generator_invalid` shows it immediately.

### G3 run log (filled in by the main)

| Seed | Compiler | Generated | Verified | Safe-only | Executions compared | Failures | Digest |
|---|---|---|---|---|---|---|---|

## G6 mode (`--g6`)

A separate mode for trusted Rust calls and standard collections (`SPEC.md` §6d, `docs/G6_SPEC.md` §10–§13): `trusted rust fn` declarations
(`::std::cmp::min` / `::std::cmp::max`), `Vec<T>`, `HashMap<K, V>`, `String` with the catalog (`vec_new/vec_push/vec_get`, `map_new/map_insert/map_get`,
`string_new/string_push_str/string_byte/string_to_str`, `len`), explicit type arguments, `take` parameters, `move x`, the contract-only `v[i]`, `s[i]`,
`map_lookup`, `map_updated`. Without `--g6` nothing changes (`generate_case(seed, index, g2=False, g3=False, g6=False)`; same seeds, same programs).

```
python bench/fuzz/run.py --g6 --seed 41 --programs 100 --compiler rs      # then again with --compiler py
python bench/fuzz/run.py --g6 --seeds 41,56 --programs 100 --max-candidates 400 --compiler py
python bench/fuzz/generate.py --g6 --seed 41 --count 20 --out /tmp/pruvgen_g6
python bench/fuzz/oracle.py                                               # oracle self-test, includes the G6 cases
python bench/fuzz/run.py --replay bench/fuzz/out/g6_41_rs/failures/<kind>_<case>
```

Output folder: `out/g6_<seed>` (`--compiler py`) and `out/g6_<seed>_rs` (default compiler). Options as for `--g3` (`--programs`, `--inputs` raised to 8, `--max-candidates`,
`--jobs`, `--batch`, `--keep-work`, `--seeds`, `--out`), plus `--g6-safe-only N` (default 20: deliberately unproved programs that must be built and run in the safe modes).
The default `--max-candidates 400` is enough for about 100 verified programs only if most candidates verify; raise it (`--max-candidates 600`) when `g6_shortfall` appears.

**Generator** (`generate.py`, `generate_g6_case`, rng `"g6:<seed>:<index>"`, input rng `"g6:<seed>:<name>:inputs"`). One public entry `fn f(..)` with parameters
`i64`, `bool`, `[i64]`, `str` and result `i64`, `bool` or `str`, plus 0–3 private helpers/trusted declarations (`G6_FRAGS`: `rust_min`, `rust_max`, `keep`, `grow`, `grow_twice`, `fill`,
`bump`, `count_of`, `put`). Collection-bearing functions are private (G6_SPEC §3.2), so no collection crosses the `f` boundary. Everything stays inside the LLVM subset
(§13.1): `Vec<i64|bool>`, `HashMap<i64|bool, i64|bool>`, `String`; private helpers use only `len(..)` in `requires` (LLVM run-time requires cannot evaluate `v[i]`/`map_lookup`). Eight scenario families
(`G6_SCENARIOS`):

- `vecfill`: `vec_push` in a loop with invariants (`len(v) == i`, `v[k] == a[k] + C`, element bounds; also `Vec<bool>` with `v[k] == (a[k] > T)`), then read back with `vec_get` (length, running sum, last element, guarded parameter index, count of `true`);
- `vecguard`: `Vec` of `i * M` built up to a parameter `n`, read at a parameter index `k` behind a guard (`0 <= k && k < len(v)`);
- `histogram`: counting with the taken map of `bump(take m, k)` and the borrowed `count_of(m, k)` (duplicate keys likely), `len(m)` bounds;
- `mapladder`: 2–4 `map_insert`/`put` calls with `i64` or `bool` keys and `i64`/`bool` values (parameters or literals as keys, so duplicate keys replace values), then `map_get` + `match`
  with the *exact* contract of the result (one implication per insert, later inserts win, plus the missing-key case), or `len(m)` bounds; `put(take m, ..)` carries `map_updated`;
- `strbuild`: `String` assembled from `str` parameters and ASCII/multibyte literals (`é`, `→`, `日本語`, `😀`), optional `if flag {..} else {..}` branch, read as `len`, `string_to_str` (also returned as `str`), guarded `string_byte`
  (with `result == a[q]` content claim when the parameter is pushed first), or a `bool` comparison of the length; ensures state exact byte lengths;
- `strloop`: a literal (and optionally a `str` parameter) pushed `n` times, linear length invariants, `len` / `string_to_str` / `string_byte(s, 0)` behind `len(s) > 0`;
- `take`: `take` helpers that return `move` values (`keep`, `grow`, `grow_twice`, `fill` with an inner loop), a branch that moves a binding into a local and reinitializes it (`let t = move v; v = grow(move t, y)`), early `return` inside a loop while an owner is live;
- `minmax`: `trusted rust fn rust_min/rust_max` under their exact contracts: `clamp`, min/max of three, and clipping the elements pushed into a `Vec` before a max scan.

Programs are well-typed and satisfy the ownership rules (§10.4) by construction: consuming arguments are always `move x` or fresh call results, every `move` is followed by an immediate reassignment (or the path returns), every branch and loop body leaves
the same bindings live, no unused call statement, every effect is declared. **About 30% are deliberately unproved but well-typed** (`g6_bad`, `g6_mutation`, also the first source line): a dropped `requires`, a false `ensures`, a dropped `invariant`, or a body mutation
(`unguarded_get`/`unguarded_byte`: the guard before `vec_get`/`string_byte` is weakened, `oob_get`: index `j + 1` / `len(v)`, `payload_plus_one`, `dropped_insert`, `dropped_bump`). They are expected to be rejected and are then built/run in the two safe modes, where they reach
the run-time failures `pruv: foreign requires violated:` (index outside `0..len` at `vec_get`/`string_byte`), `requires violated`, overflow. A mutant that the verifier proves anyway is treated like any verified program.
Inputs (`g6_candidate_inputs`): small integers (so map keys collide), values just outside the requires ranges, arrays up to 20 elements (a few longer than the `len(a) <= 20` bound), strings from a pool with multibyte text (a few longer than the `len(s) <= 100` bound), 3/4 satisfying `requires` as in the other modes. A case with only `bool` parameters gets an unused `pad: i64`.

**Oracle** (`oracle.py`). Switched on by the catalog names, `trusted`, `Vec`, `HashMap`, `String` (they imply the G3 parsing mode: explicit type arguments, `Option<bool>`). `Vec` = Python list, `String`/`str` = `bytes`, `HashMap` = `_GMap` (a wrapper around a dict, so it is never mistaken for an
Option/struct dict); every catalog operation builds a new object, so `move`d or copied values are never aliased (liveness itself is the compiler's job; the oracle does not model use-after-move). `take` is parsed and has no run-time meaning. `vec_get` / `string_byte` with an index outside `0..len` fault with kind
`foreign_requires` (stderr prefix `pruv: foreign requires violated:`) **in both modes**: foreign requires are checked at run time in verified builds too (G6_SPEC §5.1, §12.2); inside contracts `len`, `v[i]`, `s[i]`, `map_lookup`, `map_updated` are evaluated exactly (map update = same dict with `k` set;
size, domain and payload compared). `trusted rust fn` calls evaluate their `requires` (violation → `foreign_requires`) and compute `::std::cmp::min`/`max` natively; the trusted `ensures` are never evaluated. Any other path raises `OracleUnsupported`. `python bench/fuzz/oracle.py` runs `_selftest_g6` (the four `examples/g6_*.pruv` programs, vec_get/string_byte faults in both modes, `map_updated` with a false ensures, bool-keyed maps with take/move branches).

**Harness** (`run.py --g6`). Same pipeline and gate as `--g3`: verified programs run in 4 modes (`rust-proof`, `rust-safe`, `llvm-proof`, `llvm-safe`), unproved ones in the 2 safe modes, each mode compared with its own oracle result, `rust-X == llvm-X` required, both compilers must give the same `g6_digest`
(the generator and the inputs do not depend on the compiler). Counting, shortfall and report keys mirror G3 with the prefix `g6_` (`g6_generated`, `g6_verified`, `g6_safe_only`, `g6_executions_compared`, `g6_failures`, `g6_kinds_verified`, `g6_features_verified`, `g6_inputs_per_program_min`,
`g6_unproved_by_design_verified_anyway`, `g6_unexpected_rejects`, `g6_digest`, `g6_digest_exit_stdout`) plus `g6_foreign_requires_inputs` (how many inputs the oracle expects to end in a foreign-requires failure, safe and proof oracle). Extra failure kinds: `g6_shortfall`, `g6_generator_invalid`, `g6_oracle_gap`.
G6-specific harness details:

- The LLVM bindings of a G6 program contain `mod pruv_g6_shim` with `#[no_mangle]` adapters `pruv_g6_v1_<helper>` and `pruv_g6_bridge_v1`, which the `.ll` calls. Because several modules (proof and safe of one program, other programs of the batch) are linked into one executable, `prep_llvm` renames these symbols per module
  (`pruv_g6_v1_<tag>_..`, `pruv_g6_bridge_v1_<tag>`, in the `.ll` and the bindings; same idea as `pruv_abi_`), and the "keep `#[no_mangle]` only on the first module" rule is applied to the `pruv_host_*` functions only (`NO_MANGLE_HOST_RE`), not to the shim adapters.
- Source files are written/read as UTF-8 (multibyte literals); `--replay` detects a G6 source by `vec_new`/`map_new`/`string_new`/`trusted rust fn`.
- The callee name in `pruv: requires violated: <fn>:` is compared exactly (no generics in G6).

**Known gaps (G6).**

- Not run by this tool (nothing here was executed when it was written; run `python bench/fuzz/oracle.py` and a small `--g6 --programs 5` first): the generator's well-typedness rests on SPEC/G6_SPEC §10.4 as read, not on a type-checker run, so `g6_generator_invalid` shows any misreading immediately;
  likewise which programs the verifier accepts is a guess (quantifier-heavy ones such as the `result == a[q]` string content claim or the `forall` invariants over `Vec<bool>` may be rejected; they then appear in `g6_unexpected_rejects`, run in the safe modes, and may reduce `g6_verified`).
- Only `i64`/`bool` elements, keys and values (the LLVM subset); no `Vec<Option<..>>`, no struct payloads, no generic helpers (`grow<T>`), no `--foreign-checks all|off`, no user trusted functions other than `std::cmp::min/max` (no extern crates, no trusted `requires`/panic/`ensures`-violation cases), no `--trust-callers`.
- Contract-only observers are generated only in `ensures`/`invariant`, never in `requires` (they are outside the LLVM run-time subset), and `map_lookup` is exercised only through the oracle selftest, not by the generator.
- Programs are template-based (8 scenarios with random constants/shapes), at most about 4 helper calls and 20 loop iterations; the 2^40 length limit, the contract budget and allocation failure are not reachable. Drop-balance (`PRUV_G6_COUNT=1`) is not checked.
- Ownership *errors* (use after move, borrow/move overlap, loop moves) are not generated here: those are must_reject territory (`tests/g6/`).

### G6 run log (filled in by the main)

| Seed | Compiler | Generated | Verified | Safe-only | Executions compared | Failures | Digest |
|---|---|---|---|---|---|---|---|

## G9 mode (`--g9`)

A separate mode for recursion, recursive types and buffer fields (`SPEC.md` §6e, `docs/G9_SPEC.md` §10–§14, binding design §15.1): direct recursion over an array
cursor, mutual recursion with phase measures, bounded finite trees / linked lists built from scalar inputs and walked with `decreases size(t)`, JSON-like token cursor
descent, clone isolation and buffer-field replacement. `--g9` is not combinable with `--g2`/`--g3`/`--g6`. Without `--g9` nothing changes
(`generate_case(seed, index, g2=False, g3=False, g6=False, g9=False)`; same seeds, same programs).

```
python bench/fuzz/run.py --g9 --seed 41 --programs 100 --compiler rs      # then again with --compiler py
python bench/fuzz/run.py --g9 --seed 41 --programs 100 --compiler py
python bench/fuzz/run.py --g9 --seed 56 --programs 100 --compiler rs      # and --compiler py
python bench/fuzz/run.py --g9 --seed 57 --programs 100 --compiler rs      # and --compiler py
python bench/fuzz/run.py --g9 --seeds 41,56,57 --programs 100 --max-candidates 600 --compiler rs
python bench/fuzz/generate.py --g9 --seed 41 --count 24 --out /tmp/pruvgen_g9
python bench/fuzz/oracle.py                                               # oracle self-test, includes the G9 cases
python bench/fuzz/run.py --replay bench/fuzz/out/g9_41_rs/failures/<kind>_<case>
```

Output folder: `out/g9_<seed>` (`--compiler py`) and `out/g9_<seed>_rs` (default compiler). Options as for `--g6` (`--programs`, `--inputs` raised to 8, `--max-candidates`,
`--jobs`, `--batch`, `--keep-work`, `--seeds`, `--out`), plus `--g9-safe-only N` (default 20: deliberately unproved programs that must be built and run in the safe modes).
About 1.4 candidates per verified program are needed; raise `--max-candidates` (e.g. 600) when `g9_shortfall` appears.

**Generator** (`generate.py`, `generate_g9_case`, rng `"g9:<seed>:<index>"`, input rng `"g9:<seed>:<name>:inputs"`). One public entry `fn f(..)` with parameters `i64` / `[i64]` and result `i64` / `bool`
(recursive and buffer-field types cannot be in exported signatures), plus helper declarations. The shape rotates with the candidate index (`G9_SHAPES`, 8 shapes), the sub-variant and the constants come from the rng:

- `arr`: direct recursion over an array cursor with `decreases len(a) - i` and `requires len(a) <= N` (N = 8..20): suffix `sum` (range-bounded elements, also negative), `count` of `a[k] OP t`, `find` (`exists`/`forall` ensures), `index` (first match, quantified postconditions), `below`, `max`;
- `mutual`: `ping`/`pong` with phase measures `2*n+1` / `2*n` (`result == C*n + D`, optionally two calls), `even`/`odd` with a shared measure, and `alt_a`/`alt_b` alternating over an array with measures `2*(len(a)-i)+1` / `2*(len(a)-i)`;
- `list`: `Node <-> Link` list built by `grow(k)` (`size(result) == 2*k + 2`, `requires 0 <= k && k <= K`, K = 8..16), walked by `node_len`/`link_len` (exact) or `node_sum`/`link_sum` with a clamped value (bounded by `CL * size`);
- `tree`: `build(d)` as spine / mirrored spine / chain (`size(result) == 4*d+1` or `2*d+1`) called with `0 <= n <= D` (D = 6..10), walked by `tree_nodes` (`2*result + 1 == size(t)`, so `f` states an exact count), `tree_sum` (clamped), `tree_count` (`v OP x`) or `tree_depth`;
- `bst`: 2–4 `insert` calls on scalar inputs (`size(result) == size(t) + 2`), then `tree_nodes` (`result == m`) or `tree_count`;
- `tokens`: JSON-like token cursor descent over `[i64]` (atom / open / close codes drawn from 0..3, mutual `value_end`/`items_end`, measures `2*(len-i)+1` / `2*(len-j)+2`), returned as `end position` or `is_value`;
- `clone_bag`: `struct Bag { items: [i64], tag: i64 }`, `with_first` copies the buffer into a mutable local and replaces the field; `f` reads the original, the clone, the tag, both lengths or the sum;
- `clone_other`: the same with `struct Packet { bytes: [u8], label: str }` (`alloc(n, x)` typed as `[u8]`, label replaced by `copy("new")`), or a deep clone of a built `Tree` (`let mut c: Tree = a; c = fill(c, x);`) and a walk of the original or the clone.

All recursion depths and tree sizes are bounded by small constants in `f`'s `requires` (arrays up to 20 elements, trees up to 41 nodes, ping/pong up to 40 calls), so the compiled programs and the oracle's Python recursion stay small; arrays up to 3 longer than the bound and
values just outside the ranges are also generated (3/4 of the inputs satisfy `requires`, as in the other modes). Every verified-by-design program has an `ensures` that follows from the generator's own model (exact sums/counts/sizes where the verifier can prove them, bounds otherwise); the oracle evaluates every
`ensures` at run time too (proof mode), so a claim that is false for some input shows up as `unsound`. The contracts are modelled on programs known to verify (`examples/g9_*.pruv`, `tests/runtime/g9_*.pruv`, `bench/g9/solutions/ref/*.pruv`): `0 - 1` for -1, exactly one `decreases e` per recursive function, `! alloc` wherever a recursive/buffer value is built or copied.

**About 30% are deliberately unproved but well-typed** (`g9_bad`, `g9_mutation`, also the first source line): a false `ensures` (`false_ensures`) or a source mutation on the rendered program (`body_mut:<label>`): `wrong_decreases` (measure `0`), `wrong_phase`, `wrong_return`, `wrong_base`, `missing_base` (reaches an out-of-range index or a callee `requires` failure, never infinite recursion),
`weak_helper_ensures` / `dropped_helper_requires` / `dropped_walker_bound` (stale facts: the program is true but unprovable), `wrong_store`, `lost_field_replacement`, `lost_clone_isolation`, `stale_field_read`, `duplicated_child`, `wrong_clone_child`, `missing_error_check`. A *missing* `decreases` is the type error `recursive_decreases` (also with `--no-verify`), so it is not generated.
They are expected to be rejected and are then built/run in the two safe modes (`--no-verify` does not check `decreases`). A mutant that the verifier proves anyway is treated like any verified program (`g9_unproved_by_design_verified_anyway`). A candidate that the verifier rejects although it was meant to verify is not a pass: it lands in `g9_unexpected_rejects`
(source + verifier output in `unexpected_rejects/`), is run in the safe modes only, and the run continues with more candidates (`--max-candidates`); a program rejected by parse/type/effect checking is `generator_invalid`.

**Oracle** (`oracle.py`). The existing independent interpreter (own lexer/parser/value interpreter written from SPEC, no import from `pruvc`, no SMT terms, no compiler helpers) evaluates the generated source. G9 needed three additions that do not change other modes: the function-level `decreases e` clause is parsed (not evaluated; the oracle is a value interpreter),
`size(x)` in contracts (number of struct/enum constructors in the value, only active payloads; one budget unit per node), and the already existing deep-copy value semantics (let/assignment/argument/return copy, `copy(view)`, whole-field assignment `q.f = e`, `match` on recursive enums, struct literals with `[i64]`/`[u8]`/`str` fields) are what clone isolation relies on.
The oracle returns the expected `f` result for every concrete input in both modes (`safe` and `proof`), including `requires_violated`, `oob`, `overflow` faults and recorded contract failures. `python bench/fuzz/oracle.py` runs `_selftest_g9` (linked list with `size`, ping/pong, token descent, buffer-field clone).

**Harness** (`run.py --g9`). Same pipeline and gate as `--g6`: each program is compiled with the chosen compiler (`--compiler py|rs`) to both backends (rust and llvm), verified runs in 4 modes (`rust-proof`, `rust-safe`, `llvm-proof`, `llvm-safe`), unproved ones in the 2 safe modes (`--no-verify`),
all on the same 8 inputs, each mode compared with its own oracle result, `rust-X == llvm-X` required; both compilers must give the same `g9_digest` (the generator and the inputs do not depend on the compiler). Counting, shortfall and report keys mirror G6 with the prefix `g9_`:
`g9_generated`, `g9_verified`, `g9_safe_only`, `g9_executions_compared` (and `g9_executions_not_compared`), `g9_failures`, `g9_kinds_verified`, `g9_features_verified`, `g9_inputs_per_program_min`, `g9_unproved_by_design_verified_anyway`, `g9_unexpected_rejects`, `g9_digest`, `g9_digest_exit_stdout`,
plus `g9_mismatches` (`backend_or_mode_mismatch`, `oracle_mismatch`, `unsound`) and `g9_timeouts`. Extra failure kinds: `g9_shortfall`, `g9_generator_invalid`, `g9_oracle_gap`. A resource timeout (pruvc 120 s, rustc build, a run above 10 s) is a failure of its own (`timeout`, `build_error`, `run_timeout`), never a pass: a program with a timed-out run is not counted in `g9_verified`/`g9_safe_only`, and an oracle `limit` or exception is not counted either.
G9-specific details: the oracle runs recursive Pruv calls as nested Python calls, so `--g9` raises the Python recursion limit and gives worker threads a 128 MB stack (`g9_prepare_process`); `--replay` detects a G9 source by its first line (`// g9 fuzz case`).
The G9 LLVM output defines its clone/drop/node helpers as `internal` symbols, so (unlike G6) no per-module symbol renaming is done beyond the existing `pruv_abi_` prefix.

**Known gaps (G9).**

- Not run by this tool when it was written (nothing here was executed; run `python bench/fuzz/oracle.py` and a small `--g9 --programs 5` first): which programs the verifier accepts is a guess based on programs that are known to verify, so a systematic rejection of one shape shows up as `g9_unexpected_rejects` and reduces `g9_verified`;
  the generator's well-typedness rests on SPEC §6e as read (`g9_generator_invalid` shows any misreading). The `copy(a)`-based element claims (`clone_bag`), the `result.items[0] == v` / `result.bytes[0] == v` ensures of `with_first`/`replaced` and the `len(p.label) + len(q.label) == 5` claim are the least certain contracts.
- No exported recursive-type values (not allowed), no `main`, no generics, no collections inside recursive values, no `str` token parsers (`examples/g9_parser.pruv` shape), no `[bool]` fields, no recursion through `Option`/`Result` (all rejected by SPEC §6e), no mutation of a recursive value in place through a `match` view (`type/recursive_borrow` is must_reject territory).
- Resource failures that SPEC §6e declares (stack overflow on very deep recursion, contract budget 2^30) are not reachable by design (depths and sizes are bounded); `--no-verify` programs with a wrong `decreases` always terminate on the generated inputs.
- The oracle does not check `decreases` at run time; wrong measures are only exercised through the verifier (unproved programs), and the oracle's `size` is written from the SPEC sentence ("number of struct/enum constructors, only active payloads") so a disagreement with the compiler shows up as `unsound`/`oracle_mismatch`.

### G9 run log (filled in by the main)

| Seed | Compiler | Generated | Verified | Safe-only | Executions compared | Failures | Digest |
|---|---|---|---|---|---|---|---|

## G4 mode (`--g4`)

Multi-file module programs (SPEC §6f, `docs/G4_SPEC.md` §2-§4, §14 item 2). `--g4` is a separate mode (not combinable with `--g2`/`--g3`/`--g6`/`--g9`);
without it nothing changes.

```
python bench/fuzz/run.py --g4 --seed 41 --programs 30 --inputs 8 --compiler rs     # then again with --compiler py
python bench/fuzz/run.py --g4 --seeds 41,56,57 --compiler rs
python bench/fuzz/generate.py --g4 --seed 41 --count 6 --out /tmp/pruvgen_g4         # one folder per program
python bench/fuzz/run.py --replay bench/fuzz/out/g4_41_rs/failures/<kind>_<case>      # a saved program folder (root.pruv inside)
python bench/fuzz/oracle.py                                                           # includes _selftest_g4
```

`--programs` defaults to 30 with `--g4`. Output folder `out/g4_<seed>[_rs]`; options as for `--g9` (no `--g4-safe-only`).

**Layout of a program.** One directory per program (`g4c<seed>_<index>/`), 2-5 modules in all (root counts): `root.pruv`, `<m>.pruv`, and for nested
modules `<m>/<n>.pruv` (a `mod n;` inside `m.pruv` loads `m/n.pruv`); some programs reuse a leaf module name under two parents (`a/util`, `b/util`).
The compiler is called on `<dir>/root.pruv`; its output files land next to it. Failures are saved as whole program folders
(`failures/<kind>_<name>/root.pruv, a.pruv, a/b.pruv, ..., inputs.json, results.json`), `unexpected_rejects/<name>/` and `oracle_gap/<name>/` the same way.

**Generator** (`generate_g4_case`, class `G4Gen`; rng `"g4:<seed>:<index>:single"`, inputs `"g4:<seed>:<name>:inputs"`). The root has one host entry
`pub fn f(x, ..) -> i64` (1-3 `i64` parameters, so the existing driver shim `<mod>::f(..)` is reused unchanged), often a root `pub` scalar helper that child
modules call as `crate::h(..)`, sometimes a private root helper. Variety: private and `pub` helpers; the same leaf function name (`helper`, even `f`) and the
same struct/enum leaf (`Pair`, `Mode`, ...) in several modules with different bodies/fields; generic calls by path (`crate::g::pick::<i64>(..)`, `id::<bool>`,
`Boxed<i64>`, `repeat::<i64>` + `first::<i64>` over an array); structs and enums by full path (types, qualified literals `crate::m::Pair { v: a, w: b }`,
`match` patterns `crate::m::Mode::Low`, `is_variant` contracts); calls to the parent/root (`call_to_ancestor`), to children (`call_to_descendant`) and sideways.
Function-level calls are acyclic (a function only calls functions created before it), so no `decreases` is needed for recursion; module-level cycles do occur
(root `f` -> child -> root `h`). Every contract is an exact `result == <affine expression>` or a range, and each call's arguments are built so that the
callee's `requires` follow from the caller's parameter ranges (shifted values or constants otherwise); loops carry invariants/`decreases`.
All programs are meant to verify (no deliberately unproved ones).

**Twins (contract-preserving body replacement).** For about 30% of the program numbers `2k` and `2k+1` are a pair, identical except one pub callee whose body is replaced
by a different one with the same functional contract (`k*x+c` as a formula / unrolled assignments / an `if`; `k*n+c` as a formula / counting loop / counting-down loop). They get the
same inputs (`input_key`) and `twin_mismatch` is reported if any mode/input differs (`g4_twin_pairs_compared` counts the pairs that were really compared).

**Oracle** (`oracle.py`: `parse_modules`, `flatten_modules`, `_selftest_g4`). It loads the files itself (`mod name;` -> `P/name.pruv`), resolves `crate::a::b::item[::Variant]`
to the item of that module, resolves an unqualified name only in the same module, and keeps same-named items of different modules distinct by giving every non-root item
a unique name (`m<module no>_<name>`) in a flattened single-file program that the ordinary interpreter runs; root names (`f`) are kept. It imports nothing from the compiler
and does not check visibility (the compiler does; the generator only emits legal programs).

**Harness.** Same pipeline as `--g9`: each program is compiled with `--compiler py|rs` to both backends, verified programs run in `rust-proof`, `rust-safe`, `llvm-proof`,
`llvm-safe`, each mode compared with its own oracle result and `rust-X == llvm-X`; a rejected program (all rejects are "meant to verify" ones) is run in the safe modes only and reported.
`requires violated` is compared by message kind only (`pruv: requires violated: `). Summary keys with prefix `g4_`: `g4_generated`, `g4_verified`, `g4_executions_compared`
(and `_not_compared`), `g4_failures`, `g4_kinds_verified`, `g4_features_verified`, `g4_inputs_per_program_min`, `g4_twin_pairs_compared`, `g4_unexpected_rejects`, `g4_timeouts`,
`g4_digest`, `g4_digest_exit_stdout`, and `g4_mismatches` = `backend_or_mode_mismatch` / `oracle_mismatch` / `unsound` / `twin_mismatch`. The digest depends only on generated programs
and run results, so `--compiler py` and `--compiler rs` with the same seed must print the same `G4 digest`.

**Limits / assumptions** (nothing here was executed when it was written): which programs the verifier accepts is a guess modelled on `tests/g4/*`, `tests/runtime/g4_*` and the G3
fragments, so a systematic rejection shows up as `g4_unexpected_rejects`; the least certain shapes are the `repeat::<i64>` + `first::<i64>` array case (needs quantifier
instantiation), `match` on a cross-module enum with `x > 0 ==> result == k` ensures, and qualified literals/types of the root (`crate::Name`, avoided). Only `i64` scalars cross the host boundary;
no recursion, no `main`, no foreign (`trusted`) functions, no negative (must-reject) module cases; the oracle does not check privacy.

### G4 run log (filled in by the main)

| Seed | Compiler | Generated | Verified | Executions compared | Failures | Digest |
|---|---|---|---|---|---|---|

## G5 mode (`--g5`)

Programs with `inout` parameters (mutable array borrows, `docs/G5_SPEC.md` §2-§7 and §14 items 2-3). `--g5` is a separate mode (not combinable with
`--g2`/`--g3`/`--g6`/`--g9`/`--g4`); without it nothing changes. It follows `--g4`: one directory per program, the compiler is called on `<dir>/root.pruv`, failures are saved as whole
program folders.

```
python bench/fuzz/run.py --g5 --seed 41 --programs 30 --inputs 8 --compiler rs     # then again with --compiler py
python bench/fuzz/run.py --g5 --seeds 41,56,57 --compiler rs
python bench/fuzz/generate.py --g5 --seed 41 --count 6 --out /tmp/pruvgen_g5        # one folder per program
python bench/fuzz/run.py --replay bench/fuzz/out/g5_41_rs/failures/<kind>_<case>     # a saved program folder (root.pruv + inputs.json inside)
python bench/fuzz/oracle.py                                                          # includes _selftest_g5
```

`--programs` defaults to 30, `--inputs` is raised to 8. Output folder `out/g5_<seed>[_rs]`; options as for `--g4` (no `--g?-safe-only`, no `--rejected-sample`).
Files in the output folder: `summary.json` (all `g5_*` keys below), `g5_results.json` (seed, compiler, per-program feature lists and completed comparisons, shortfalls,
infer probe results, saved failures with their replay commands), `failures/<kind>_<name>/` (program folder, `inputs.json`, `results.json` with `g5_features` and a `replay` command,
`pruvc_output.txt`, `gen/`), `unexpected_rejects/<name>/`, `oracle_gap/<name>/`, `generator_invalid/<name>/`.

**Generator** (`generate_g5_case`, rng `"g5:<seed>:<index>:single"`, inputs `"g5:<seed>:<name>:inputs"`). The host entry is an ordinary root `pub fn f(..)` (explicit mode, so every function symbol is
mangled and `inout` helpers are never host-visible): it copies its array arguments into `let mut` owners (`! alloc`), calls inout helpers and returns an array (`[i64]`, `[u8]`, `[bool]`) or a scalar.
Every inout helper has contracts that are meant to verify: `len(a) == len(old(a))`, the exact new content, and a `forall` frame over `old(a)`; the host `requires` imply the helper
`requires`. Inout calls are always whole statements (`let`, expression statement, `return`), never nested in an expression. Programs are picked by rotating through 22 (scenario, type) combinations (index + seed), so every
22 consecutive non-twin programs cover everything; a twin pair is drawn from the scenarios that have an alternative body.

| scenario | what it exercises |
|---|---|
| `pairs` (i64, u8, bool) | `put_at` + `put_pair` (the inout parameter is forwarded twice to an inout callee = nested-function reborrow), repeated calls on one owner (0-2 extra calls) |
| `swapgen` (root / child module) | `exchange<T: Element>` called at `i64` and `bool` (two generic instances, one used twice), bool owner decides a conditional call |
| `loopfill` (i64, u8, bool) | loop with an inout call per iteration (`fill_all` via `put_at`, invariants over `old(a)`), then another call; array or scalar result |
| `loopbump` (i64, u8, bool) | `step_all` loop over `step_at` (`+1` below the limit, or flip for bool; `requires forall`, flipped twice for bool); array or scalar result |
| `reverse` (i64) | in-place reversal with the invariant against `old(a)` (swap helper or inline stores), once or twice |
| `recur` (i64, u8, bool) | recursion that reborrows the same inout parameter at every level (`fill_from`, `decreases len(a) - i`), or the equivalent loop |
| `multi` (i64) | two owners, a call with two inout arguments and swapped roles (`fill_pair`), an inout destination + read-only other owner (`blit`), `print` of the second owner (`dump`) |
| `cond` (i64) | an inout function with a `bool` result used as a `let` initializer (`order_pair`) |
| `modules` / `modules_nested` (i64, u8, bool) | helpers in child module `ops` (and `ops/deep`), called by `crate::ops::..` paths from the root host and between modules |

Feature tags per program (`g5_features`): `type_i64`, `type_u8`, `type_bool`, `generic_instance`, `repeated_reborrow`, `nested_reborrow`, `multi_owner`, `two_inout_args`, `swapped_roles`, `readonly_other_owner`, `loop`,
`recursion`, `module_call`, `nested_module`, `old_contract`, `frame_forall`, `bool_result_call`, `print_output`, `array_return`, `scalar_return`, `body_replacement_twin`, `alternative_body`, `files_<n>`.
`g5_features_verified` counts them over the counted verified programs of a run, `g5_program_features` lists them per program, and `g5_features_missing` names required tags
(`type_*`, `generic_instance`, `repeated_reborrow`, `nested_reborrow`, `multi_owner`, `loop`, `recursion`, `module_call`, `old_contract`, and `body_replacement_twin` = at least one twin pair compared) that no counted program carries.

**Twins (contract-preserving body replacement).** For about 30% of the program numbers `2k` and `2k+1` are a pair, identical except for one callee body (`put_at` store with/without a temporary, `exchange` store order, `fill_all`/`step_all`
loop body = inout call vs inline store, `reverse` swap helper vs inline stores, `fill_from` recursion vs loop, `step_at` variant) that satisfies the same contract. They get the same inputs (`input_key`) and a difference in (exit code, stdout, `pruv:` line) of any mode/input is a `twin_mismatch`
(the check is the G4 one, `g4_twin_check`); `g5_twin_pairs_compared` counts the pairs that were really compared. Other programs pick the body variant at random.

**Oracle** (`oracle.py`). The independent interpreter got `inout` parameters (`_Fn.inout`, `_Parser.call_arg`, marker check in `_Interp.call`): a marked argument is the caller's own list, so element stores mutate the owner in
place and a forwarded `inout a` reaches the same list; `old(a)` is a list copied at function entry (after the requires check) and is evaluated in ensures, invariants and asserts; ensures see the final contents. `run()` returns the usual
`kind/value/output/contract_failures` plus, only for inout programs, `inout_final` (final arrays of the top-level function's own inout parameters) and `inout_calls`. Final arrays of the host's owners show up through the returned array / printed output, which the harness compares byte for byte.
Expected values come from this interpreter only (no compiler output, SMT term or generated code). A missing or extra `inout` marker, `old` of a non-inout name, or an inout parameter of a non-array type raises `OracleUnsupported`.
`python bench/fuzz/oracle.py` runs `_selftest_g5` (in-place mutation, caller input untouched, old frozen vs final, top-level `inout_final`, marker mismatch, recursion + loop invariants over `old`, generic instance statements, `[u8]`/`[bool]`).

**Harness** (`run.py --g5`). Same pipeline as `--g4` (verified programs in `rust-proof`, `rust-safe`, `llvm-proof`, `llvm-safe`, each mode compared with its own oracle result, `rust-X == llvm-X`; `requires violated` is compared by message kind only; a rejected
program is an "unexpected reject": run in the two safe modes as a rider, saved, never counted). Use `--compiler rs` and `--compiler py` on the same seed: programs and inputs do not depend on the compiler, and `g5_digest` / `g5_digest_exit_stdout` / `g5_program_digest` must agree.

- `g5_verified`: counted programs (a g5 case, at least `--inputs` inputs, run results for all four modes without timeout or harness exception, no recorded failure, and at least one input that satisfies `requires` and that the proof oracle compared to the end).
- `g5_comparisons_completed`: (program, mode, input) executions that were compared with the oracle, **only on counted verified programs**. Oracle gaps (`oracle_unsupported`/`oracle_parse_error`), rejected programs, oracle `limit`/error, timeouts and harness exceptions never contribute.
  `g5_comparisons_target` = `--programs` × `--inputs` × 4. The whole §14 item 3 count (at least 5,760) is the sum of `g5_comparisons_completed` over the six runs (seeds 41, 56, 57 × `--compiler rs`/`py`) at 30 programs and 8 inputs: 3 × 2 × 960.
- `--infer` probe: the first 12 verified programs are compiled again with `--infer` (the program as generated: must still verify, emitted Rust compared with the plain one) and, if the program has loop invariants, a copy with every `invariant` line removed (rejection allowed;
  an accepted copy's Rust is compared with the explicit program's and a difference is listed in `g5_infer.stripped_rust_differs`, not counted as a failure). Result in `g5_infer` (`programs_probed`, `verified_with_infer`, `same_rust_as_explicit`, `stripped_*`) and `g5_results.json` (`infer_per_program`). A crash or rejection of the explicit program under `--infer` is an `infer_failure` (a timeout is a `timeout`).
- Other report keys: `g5_generated`, `g5_executions_compared` / `_not_compared` (all built programs, riders included), `g5_kinds_verified`, `g5_features_verified`, `g5_features_missing`, `g5_program_features`, `g5_inputs_per_program_min`, `g5_twin_pairs_compared`, `g5_mismatches`
  (`backend_or_mode_mismatch`, `oracle_mismatch`, `unsound`, `twin_mismatch`), `g5_timeouts`, `g5_unexpected_rejects`, `g5_oracle_gaps`, `g5_shortfall`, `g5_failures`, `g5_saved_failures` (directory + replay command for each, also printed and in `g5_results.json` as `replay_commands`).
- Gates (extra failure kinds, exit code 1): `g5_shortfall` (fewer counted verified programs than `--programs`), `g5_comparison_shortfall` (value = missing comparisons), `g5_infer_shortfall` (fewer than 10 programs verified with `--infer`), `g5_feature_shortfall` (value = number of missing feature tags),
  `g5_generator_invalid`, `g5_oracle_gap`, `infer_failure`. With `--programs` below ~25 the feature gate may legitimately fire because not every scenario was drawn.
- Replay: `python bench/fuzz/run.py --replay <failure folder> [--compiler py|rs]` (a program folder with `root.pruv` is a G4/G5 program; a source with `inout name:` marks it as G5).

**Limits / assumptions** (nothing here was executed when it was written, there was no shell): which programs the verifier accepts is a guess modelled on `examples/g5_*.pruv`, `tests/runtime/g5_r*` and the G4 shapes, so a systematic rejection shows up as `g5_unexpected_rejects`
and as `g5_shortfall`. The least certain shapes: the `forall` frame of the nested `put_pair`, the `reverse` loop with inline stores, the `fill_from` loop variant (no `decreases` on a non-recursive function), `result ==> ...` ensures of `order_pair`, `-> [u8]`
scalar `w[0]` results, `ensures len(result) == len(a)` on host entries, and `print` inside a loop of `dump`. Not generated: mutation through `match` roots, inout on `str`/Vec/aggregates (rejected by the spec), inout host entries (`type/entry_signature` is must_reject territory), `--trust-callers`/`--no-verify`-only exclusivity cases,
nested mutating calls inside expressions (rejected by §2.1), refined locals (`verify/refinement_assign`), negative (must-reject) programs and mutants (those belong to `bench/g5`), arrays above 8 elements, and the per-element-type generic `exchange` for `u8` (not an Element).
The oracle does not check the static exclusivity/context rules (the generator emits only legal programs) and does not model the safe-mode checked wrapper separately: a requires violation of an inner call is the same `requires violated` fault as at the entry.

### G5 run log (filled in by the main)

| Seed | Compiler | Generated | Verified | Comparisons completed | Infer verified | Failures | Digest |
|---|---|---|---|---|---|---|---|
| 41 | rs | 52 | 33 | 1056 | 12/12 | 0 | `09647ffcb5ab4077` |
| 41 | py | 52 | 33 | 1056 | 12/12 | 0 | `09647ffcb5ab4077` |
| 56 | rs | 52 | 33 | 1056 | 12/12 | 0 | `4016f7031ba6ec8f` |
| 56 | py | 52 | 33 | 1056 | 12/12 | 0 | `4016f7031ba6ec8f` |
| 57 | rs | 51 | 33 | 1056 | 12/12 | 0 | `1c1536ce58fc102f` |
| 57 | py | 51 | 33 | 1056 | 12/12 | 0 | `1c1536ce58fc102f` |

Total 6,336 comparisons (target 5,760), 0 failures, 0 mismatches of any kind; rs and py digests are identical per seed (2026-11-12).

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
| `g3_shortfall` | (`--g3` only) Fewer counted verified programs than `--programs`, or fewer counted unproved safe-only programs than `--g3-safe-only`. The value is the sum of the shortfalls |
| `g3_generator_invalid` | (`--g3` only) A generated program did not pass parse/type/effect checking (the generator must only produce well-typed programs) |
| `g3_oracle_gap` | (`--g3` only) The oracle could not parse or evaluate a generated program (`oracle_unsupported` / `oracle_parse_error`) |
| `g6_shortfall` | (`--g6` only) Fewer counted verified programs than `--programs` or fewer counted unproved safe-only programs than `--g6-safe-only`. The value is the sum of the shortfalls |
| `g6_generator_invalid` | (`--g6` only) A generated program did not pass parse/type/effect checking (ownership errors count here too) |
| `g6_oracle_gap` | (`--g6` only) The oracle could not parse or evaluate a generated program |
| `g9_shortfall` | (`--g9` only) Fewer counted verified programs than `--programs` or fewer counted unproved safe-only programs than `--g9-safe-only`. The value is the sum of the shortfalls |
| `g9_generator_invalid` | (`--g9` only) A generated program did not pass parse/type/effect checking |
| `g9_oracle_gap` | (`--g9` only) The oracle could not parse or evaluate a generated program |
| `twin_mismatch` | (`--g4` only) Two programs that differ only in one contract-preserving callee body gave different (exit code, stdout, `pruv:` line) for the same mode and input |
| `g4_shortfall` | (`--g4` only) Fewer counted verified programs than `--programs`. The value is the shortfall |
| `g4_generator_invalid` | (`--g4` only) A generated program did not pass parse/type/effect checking |
| `g4_oracle_gap` | (`--g4` only) The oracle could not load, resolve or evaluate a generated program |
| `g5_shortfall` | (`--g5` only) Fewer counted verified programs than `--programs`. The value is the shortfall |
| `g5_comparison_shortfall` | (`--g5` only) Fewer completed comparisons than `--programs` x `--inputs` x 4 (counted verified programs only). The value is the number missing |
| `g5_infer_shortfall` | (`--g5` only) Fewer than 10 programs verified when compiled with `--infer`. The value is the number missing |
| `g5_feature_shortfall` | (`--g5` only) A required feature tag (types, generic instances, reborrows, owners, loops, recursion, module calls, old contracts, twins) is carried by no counted program. The value is the number of missing tags |
| `g5_generator_invalid` | (`--g5` only) A generated program did not pass parse/type/effect checking |
| `g5_oracle_gap` | (`--g5` only) The oracle could not load, resolve or evaluate a generated program |
| `infer_failure` | (`--g5` only) `--infer` rejected or crashed on a program that verifies without it (or crashed on its invariant-free copy); a timeout is recorded as `timeout` |

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
# G7 scoped parallel differential fuzzing

`--g7` is a separate mode (cannot be combined with the other `--gN` flags):

```sh
.venv/bin/python bench/fuzz/generate.py --g7 --seed 71 --count 30 --out bench/fuzz/out/g7_generated
.venv/bin/python bench/fuzz/oracle.py
.venv/bin/python bench/fuzz/run.py --g7 --seed 71 --programs 30 --inputs 8 --compiler py --jobs 12
.venv/bin/python bench/fuzz/run.py --g7 --seed 71 --programs 30 --inputs 8 --compiler rs --jobs 12
```

Repeat for seeds 72 and 73. Generation stops at the requested number of candidates;
rejections and oracle gaps are reported instead of replacing them with extra candidates.
The six families cover two/three branches, loop groups, multi-array branches, shared
immutable inputs, two generic specializations, i64/u8/bool elements, exact write/frame
contracts, and sequential helper calls inside workers. All selected inputs satisfy the
entry preconditions. Each program prints lengths and every element of its final owners
and shared input, including untouched tails, before returning.

The independent oracle captures branch arguments at group entry and executes calls in
source order. Inout views preserve owner identity; immutable array views forbid direct
stores. The compiler remains responsible for rejecting illegal source programs. The
oracle is a sequential reference, not a race detector or a model of allocation/spawn
failure. Its G7 self-test includes all generator families and explicit owner/frame checks.

Each rust-proof, rust-safe, llvm-proof, and llvm-safe binary runs twice per input in fresh
processes, concurrently with other jobs so OS scheduling can vary. `repeat_mismatch` is
reported separately from oracle and backend/mode mismatches. Repetition does not double
the comparison denominator: 30 programs × 8 inputs × 4 modes = 960 per run, or 5,760 for
three seeds and two compilers. Limits, missing builds and timeouts are not completed
comparisons. This sampling cannot establish correctness for every possible schedule.

Default output is `out/g7_<seed>[_rs]/summary.json`. G7 summary fields record generated,
verified/rejected counts, completed/target/incomplete comparisons, feature coverage,
oracle gaps, repeat counts and mismatches; common fields retain build/runtime failures.
Failures preserve source, inputs, diagnostics, first results and repeat results. Replay:

```sh
.venv/bin/python bench/fuzz/run.py --g7 --compiler py --replay PATH_TO_FAILURE
```

The recorded seed summaries live in `results_g7/<seed>_<compiler>.json`; only summaries
and any necessary reproducers belong there, not generated build trees.

## G8 bundled standard module

`--g8` is a separate mode with 30 verified-intended clients per seed: twelve
individual functions and three compositions, each called directly and through a
generated child module. Root and child preconditions bound sum elements and array
lengths, exclude empty maxima and abs(MIN), and order clamp bounds. Compositions
cover checked addition of two sums, clamping an array maximum, and first-index
search in a reversed array. Constants and random interior inputs are seed-stable.

```sh
python bench/fuzz/oracle.py
python bench/fuzz/generate.py --g8 --seed 41 --count 30 --out bench/fuzz/out/g8_generated
python bench/fuzz/run.py --g8 --seed 41 --programs 30 --inputs 8 --compiler py --jobs 4
python bench/fuzz/run.py --g8 --seed 41 --programs 30 --inputs 8 --compiler rs --jobs 4
```

Repeat for seeds 56 and 57. Each run targets 960 comparisons (5,760 overall).
The independent `g8_value` oracle uses Python arbitrary-precision arithmetic and
direct array operations, without parsing the bundle or consulting SMT/emitted
code. `_selftest_g8` checks all twelve operations and the three compositions.
Eight mandatory witnesses include MIN/MAX overflow pairs, abs(MIN+1), empty,
duplicate, descending and all-equal arrays, and sums at both element bounds.
Smaller `--inputs` truncates these witnesses. Arrays are at most eight elements;
million-element performance, allocation failure and invalid caller inputs are
outside this corpus.

Default compilation must verify before rust-proof, rust-safe, llvm-proof and
llvm-safe are compared against the oracle. Rejected/unknown/unsupported/failed
programs and incomplete comparisons are separate counters, never padded with
replacement programs. Summaries go to `results_g8/<seed>_<compiler>.json` and
include compiler identity, bundle SHA-256, coverage, inputs and source hashes.
Transient build trees are removed. Failures preserve sources, inputs, logs,
actual outputs and exact replay argv under `results_g8/repro/`; replay with
`--g8 --replay DIR --compiler py|rs` (and `--compiler-path` when needed).

## Stage 5 cost-bound differential fuzzing

`--s5` is a separate mode. Run `python bench/fuzz/oracle.py` for all oracle self-tests,
then (repeat for seeds 81, 82, 83 and compilers py, rs):

```sh
python bench/fuzz/generate.py --s5 --seed 81 --count 30 --out bench/fuzz/out/s5_generated
python bench/fuzz/run.py --s5 --seed 81 --programs 30 --inputs 8 --compiler py --jobs 4
```

The nine families cover single/nested loops, calls in loops with multiplied callee
bounds, decreasing recursion, generic calls, length-dependent alloc/copy, par groups,
slack bounds and conditional spending. Every function under test prints observable
values. Exact-bound cases have a twin changing only the entry function's bound by
exactly one. Always-slack cases have no twin. Boundary inputs include zero, maxima,
and both conditional paths; interior inputs and constants vary deterministically.
There is no replacement of rejected candidates or padding of completed comparisons.

Originals must verify and agree with the independent oracle in rust-proof,
rust-safe, llvm-proof and llvm-safe. Twins must be rejected with `verify/cost_bound`,
and both safe backends must panic with exit 101 and `pruv: cost exceeded` exactly
when predicted by the oracle, preserving output before the fault. A wrongly accepted
twin is a failure even if its runtime checks work. Thirty originals produce 27 twins:
960 original comparisons plus 432 twin comparisons per run.

The oracle records each call's frozen bound and exact modular `spent` in `cost_calls`:
calls charge the declared callee bound, including slack, rather than its actual work.
Loop entry, alloc/copy and sequentially interpreted par calls use the Stage 5 units.
Safe-mode counters detect negative bounds and u128 overflow; contract bounds use the
existing i128 evaluator. This corpus uses small i64 parameters, arrays of length at
most 12, pure par workers, and direct recursion; it does not test scheduling,
allocation failure, mutable par-bound capture, large-counter performance, or every
possible contract-domain expression. The oracle is not a static legality checker.

Summaries default to `results_s5/<seed>_<compiler>.json`; transient build trees are
removed. Failures preserve source, exact inputs, diagnostics, oracle traces and
actual outputs under `results_s5/repro/`. Replay a saved case with:

```sh
python bench/fuzz/run.py --s5 --compiler py --replay bench/fuzz/results_s5/repro/CASE
```

`--out DIR` changes the summary/reproducer destination. Summary counts distinguish
verification outcomes, completed/target/incomplete comparisons, oracle gaps,
mismatches, expected/observed safe panics and unexpected original-program panics.
