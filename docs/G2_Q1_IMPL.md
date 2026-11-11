# G2 Q1 Implementation Spec: 6 G2 Problems, Grader, G2 Mutation, G2 Fuzzer

Status: implementation contract (main-fixed). Basis: `docs/G2_SPEC.md` §0.0 decisions 11, 12, 15, 17, §7.7, §8.3. Q2 (measurement, independent authors, `SPEC.md` summary) is outside the scope of this document.

## 0. Scope

Q1 closes the G2_SPEC §8.3 (fuzzer/mutation) gate. Automatic true/false judgment of mutants (decision 17) needs reference tests, so Q1 builds first the **6 problems, reference implementation, grader, and reference Pruv solutions** that Q2's independent use needs (Q2 only adds independent-author solutions and measurement on top of this).

| Part | Files (boundary) |
|---|---|
| A. G2 problems and grader | `bench/g2/PROBLEMS.md`, `bench/g2/reference.rs`, `bench/g2/run.py`, `bench/g2/solutions/ref_pruv/q01..q06.pruv` |
| B. G2 mutation | `bench/g2/mutate_ops.py` (results in `bench/g2/results/`) |
| C. Fuzzer G2 | `bench/fuzz/{generate,oracle,run}.py`, `bench/fuzz/README.md` (§5, fixed after investigation) |

The existing `bench/mutate.py`, `bench/inference/mutate_infer.py`, and `bench/g1/**` are not modified (decision 17).

## 1. The 6 problems (G2_SPEC 8.4 + decision 15: i32 update → u8 update)

All function names and signatures are exactly as below. The grader compares results to the reference implementation as Rust `Debug` strings. Inputs always respect the constraints. A solution must pass verification and must not panic.

| id | Signature | Constraint | Meaning |
|---|---|---|---|
| q01 byte range conversion | `fn clamp_bytes(a: [i64]) -> [u8] ! alloc` | elements any i64, `len(a) <= 1_000_000` | same length, `out[k] = min(max(a[k], 0), 255)` |
| q02 ASCII filter | `fn ascii_mask(a: [u8]) -> [u8] ! alloc` | `len(a) <= 1_000_000` | same length, `a[k]` unchanged if `a[k] < 128`, otherwise 63 (`'?'`) |
| q03 u8 array update | `fn add_sat(a: [u8], d: i64) -> [u8] ! alloc` | `-255 <= d <= 255`, `len(a) <= 1_000_000` | same length, `out[k] = min(max(a[k] + d, 0), 255)` |
| q04 bool aggregate | `fn longest_true_run(a: [bool]) -> i64` | `len(a) <= 1_000_000` | length of the longest run of consecutive `true` (0 if none) |
| q05 UTF-8 byte scan | `fn count_chars(s: str) -> i64` | `len(s) <= 1_000_000` | number of characters (code points) = number of bytes that are not continuation bytes (128..=191) |
| q06 boundary-based substring | `fn prefix_chars(s: str, k: i64) -> str ! alloc` | `0 <= k <= 1_000_000`, `len(s) <= 1_000_000` | first k characters. If there are fewer than k characters, copy the whole string |

Grader-side Rust type mapping: `[i64]`→`&[i64]` (input `Vec<i64>`), `[u8]`→`&[u8]`/`Vec<u8>`, `[bool]`→`&[bool]`/`Vec<bool>`, `str`→`&str`/`String`. Both the rust backend output and the llvm `--rust-bindings` output emit a `pub fn` with this signature.

## 2. A. `bench/g2/` files

### 2.1 `PROBLEMS.md`
Same form as `bench/g1/PROBLEMS.md` (in English). Rules at the top: a solution is a single `qNN.pruv`, with the names and signatures exactly as in §1, helper functions allowed, constraints written with `requires`, meaning written with `ensures`. A paragraph on the grader type mapping. For each problem: signature, constraint, meaning, and 1–2 small examples. For language rules, point to `SPEC.md` (the G2 summary goes in at Q2).

### 2.2 `reference.rs`
Trusted Rust reference implementation. `pub fn clamp_bytes(a: &[i64]) -> Vec<u8>`, `pub fn ascii_mask(a: &[u8]) -> Vec<u8>`, `pub fn add_sat(a: &[u8], d: i64) -> Vec<u8>`, `pub fn longest_true_run(a: &[bool]) -> i64`, `pub fn count_chars(s: &str) -> i64` (= `s.chars().count()`), `pub fn prefix_chars(s: &str, k: i64) -> String` (= `s.chars().take(k as usize).collect()`). No external crates.

### 2.3 `run.py` (grader)
Modeled on `bench/g1/run.py`. Differences:

- Usage: `run.py <solutions_dir> <out.json> [--backend rust|llvm] [--compiler py|rs] [--no-verify] [--trust-callers] [qNN ...]`. `--compiler` defaults to `py`. `py` = `[ROOT/.venv/bin/python, ROOT/pruvc/pruvc.py]`, `rs` = `[ROOT/pruvc-rs/target/release/pruvc]`. Both compilers accept `IN -o OUT [--backend llvm --rust-bindings RS] [flags]`.
- Public functions to be imported as a module (B uses them; names and arguments fixed):
  - `P`: dict, keys `"q01".."q06"`.
  - `compile_pruv(compiler, src, workdir, backend="rust", flags=()) -> dict`: compiles only. Returns `{"rc": int, "errors": [JSON error dict...], "rs": path, "ll": path or None, "stderr": last 500 characters}`. On a 600-second timeout, `rc = -1`.
  - `build_and_run(sol_rs_path, pid, workdir, llvm_path=None) -> dict`: same return as g1 (`status` ok|wrong|compile_error|timeout, `tests_passed`, `tests_total`, `first_failure`, and on failure `exit_code` and `stderr`). Run timeout 120 seconds.
- Inputs: hand-written EDGE inputs per problem + 300 random ones (LCG seed 12345, `n = r.range(0, 50)`). Add helpers `bytes(n)` (0..=255), `bools(n)`, `utf8(n)` (n characters, distribution below) to Lcg.
  - `utf8` character distribution: 1/2 ASCII (all of 0x00..=0x7F, including NUL), 1/6 2-byte (U+0080..=U+07FF), 1/6 3-byte (U+0800..=U+FFFF excluding the surrogates U+D800..=U+DFFF), 1/6 4-byte (U+10000..=U+10FFFF). `char::from_u32(..).unwrap()`.
  - EDGE minimum: empty input, length 1, and the problem's boundary values (q01: `i64::MIN`, `i64::MAX`, -1, 0, 255, 256; q02: 127, 128, 255, 0; q03: d = ±255, 0, 0 and 255 in a; q04: all true, all false, last run is the longest; q05: `""`, `"é"`, `"😀"`, `"a\u{0}b"`, `"한글"`; q06: k = 0, k = number of characters, k > number of characters, boundary between 4-byte characters, `""`).
  - Number of inputs is 300 + EDGE per problem.
- The llvm backend build is g1's `build_llvm_objects` as is (runtime.c with `-DPRUV_RUST_ALLOCATOR`).
- Output and table format are the same as g1.

### 2.4 `solutions/ref_pruv/q01..q06.pruv`
Reference Pruv solutions. The end criterion is: passes verification in both compilers (without `--infer`), and passes all 300+EDGE grader inputs on both the rust and llvm backends (the main agent runs and confirms). They must state the constraint with `requires` and the core of the meaning with `ensures` (whichever of length, range, and element relations is provable). Since they are the originals for mutation testing, write them so that **each line does one thing** (when the condition, boundary, and constant each come on different lines, mutants are told apart well).

## 3. B. G2 mutation `bench/g2/mutate_ops.py`

### 3.1 Usage
`mutate_ops.py OUT.json [SRC_DIR] [--jobs N] [--retry] [--only qNN ...]`. `SRC_DIR` defaults to `bench/g2/solutions/ref_pruv`. Results go in `bench/g2/results/` (the main agent runs it).

### 3.2 Mutation operators (G2-specific list `G2_OPS`)
Each entry is `(name, function)`, and the function takes one line of string and returns a list of changed lines (unchanged ones are discarded). Contract lines (the `SKIP` regex: `^\s*(requires|ensures|invariant|decreases|fn |//)`) are not touched.

| Name | Change | Rationale |
|---|---|---|
| `byte_const_pm1` | integer tokens `127`, `128`, `191`, `192`, `255`, `256` each +1 and −1 | storage upper bound ±1 |
| `guard_true` / `guard_false` | the condition of `if condition {` to `true` / `false` (including `else if`) | delete range guard |
| `len_pm1` | `len(X)` to `(len(X) + 1)` / `(len(X) - 1)` (X is an argument with balanced parentheses) | change index end value |
| `substr_pm1` | lo and hi of `substr(s, lo, hi)` each to `(lo + 1)`, `(lo - 1)`, `(hi + 1)`, `(hi - 1)` (arguments split by top-level commas) | substring boundary ±1 |
| `boundary_drop` | `is_char_boundary(..)` calls to `true`, and `!is_char_boundary(..)` to `false` | delete boundary condition |
| `conj_drop` | if a `while` or `if` condition is `A && B`, only `A` / only `B` (one top-level `&&` at a time) | delete boundary condition |

In addition, the `OPS` of the existing `bench/mutate.py` is **read from the source as in mutate_infer.py** (no copy) and run together under the name `base`. If two or more produce the same result text, merge them into one and keep all the names.

### 3.3 Judgment
For each mutant:
1. Verification: compilers `py`, `rs` × `--infer` off, on = 4 runs, rust backend. Classification is the same as `classify` in `mutate_infer.py` (accepted / rejected / undecided (only `inference_timeout` and `verify_unknown`) / crash (exit code outside 0 and 1, 1 without JSON, `stage` internal, 600-second timeout, execution failure)). With `--retry`, undecided ones are run once more serially.
2. True/false (ground truth): compile with the `rs` compiler `--no-verify` rust backend → `run.build_and_run`. `ok` → `true_mutant` (observably the same as the original), `wrong`, `timeout` → `false_mutant`, compile rejected → `not_compilable`, compiler crash → `crash`. This is done for all mutants.
3. Summary (`summary`): per-operator and per-problem tables of truth × verdict, `false_accepted` (false mutants where at least one of the 4 runs accepted; list), `true_accepted` (count), `crash` (list), `py_rs_verdict_diff` (list), `undecided` (list), `versions` (same function as mutate_infer).
4. Exit code: 1 if there is any `false_accepted` or crash, otherwise 0.

Gate (G2_SPEC 8.3): `false_accepted` = 0, crash = 0, Python/Rust implementation verdict differences 0 (record the cause if any). Acceptance of true mutants is not counted as an error; only the count is recorded.

## 4. No degradation of the existing mutation corpus

The main agent runs the same command as in 31.1, `bench/inference/mutate_infer.py OUT bench/solutions/pruv_try1 bench/solutions/pruv_agg bench/inference/agg_noinv bench/g1/solutions/ref_pruv --jobs 8 --retry`, and checks that the verdicts equal `mutate_infer_32.json` (298 mutants, off 20/278, on 21/277).

## 5. C. Fuzzer G2

The current fuzzer generates no G2 at all (generated types are i64, bool, `[i64]`, Option/Result, and user types; the oracle lexer and `type_` filter G2 out as `OracleParseError` and `OracleUnsupported`). The three files are connected only through the `case` dict, input JSON, and oracle results, so the representation below is fixed and one worker edits each file.

### 5.0 Fixed rules (common to the three files)
1. **Existing output unchanged.** Run without `--g2`, the result of `generate_case(seed, index)` (the whole `case` dict), the behavior of `run.py`, and the `summary.json` keys are byte-for-byte the same as now. G2 templates are not put into the existing `FAMILY` and ingredient lists (the weighted selection would change and old-seed programs would differ).
2. **G2 mode.** `generate_case(seed, index, g2=False)`. If `g2=True`, the rng is created separately as `random.Random("g2:%s:%s" % (seed, index))` and chosen only from the G2 template list `G2_TEMPLATES`.
3. **Type strings** (types in `case["params"]`, `case["ret"]`): new `"array_u8"` (`[u8]`), `"array_bool"` (`[bool]`), `"str"`. The refinement `[u8 | ..]` is not produced by the fuzzer (the samples already cover it).
4. **Input JSON values**: `array_u8` = list of integers 0..255, `array_bool` = list of bools, `str` = JSON string (Python `str`, no surrogates, UTF-8 bytes when passed to execution).
5. **Keys added to `case`** (only in g2 mode): `"g2": True`, `"g2_features"`: sorted list of tags. Tags: `u8`, `bool_arr`, `str`, `lit` (string literal in code), `substr`, `boundary` (is_char_boundary), `store_u8`, `alloc_u8`, `alloc_bool`, `ret_u8`, `ret_bool`, `ret_str`.
6. **Return value comparison representation**: if the return type is `str`, the Rust driver prints `println!("{:?}", R.as_bytes())` (list of byte integers); otherwise `{:?}` as now. The oracle `format_value` prints str (internally `bytes`) in the form `[104, 105]`, `[u8]` as a list of integers, and `[bool]` as `[true, false]`. Empty ones are `[]`.
7. **Safe-mode failure messages** (exit 101, compare the prefix of the first `pruv: ` line of stderr):

| Oracle kind | detail | Expected prefix |
|---|---|---|
| `elem_range` | value v | `pruv: element out of range: v (u8 0..=255)` |
| `slice_range` | `"lo hi n"` | `pruv: string slice out of bounds: lo..hi (len n)` |
| `slice_cut` | `"lo hi n"` | `pruv: UTF-8 boundary error: lo..hi (len n)` |
| `oob` (including str index) | same as now | `pruv: index out of bounds:` |

### 5.1 Oracle `bench/fuzz/oracle.py` (compiler import forbidden, independent interpretation)
- Lexer: string literal `"…"`, escapes are only `\" \\ \n \r \t \0` (anything else is `OracleParseError`). The value is the UTF-8 bytes (`bytes`) of the source characters.
- `type_`: `[u8]`, `[bool]`, `str`. The `[u8 | …]` refinement is `OracleUnsupported`.
- Values: `[u8]` is an int list, `[bool]` is a bool list, `str` is immutable `bytes`. Keep the declared type of each variable in the function environment (parameters, `let` types, function return types).
- Narrow type of `alloc(n, v)` (G2_SPEC 0.0 decision 6): it has that array type only immediately right of a typed `let`, immediately right of a reassignment of that variable, and immediately after `return`; otherwise `[i64]`. If `[u8]`, the order is **length check → value range check** (the value check is done even when the length is 0). Out of range is `elem_range`.
- `[u8]` element store `a[i] = v`: keep the current evaluation order and do **index check → value range check**.
- `copy`: for arrays a list copy, for str the same bytes.
- str: `len` = number of bytes, `s[i]` = byte integer (out of range is `oob`), `is_char_boundary(s, i)` = the G2_SPEC 4.4 formula (i==0, or i==n, or 0<i<n and the byte is <128 or >=192; negative or greater than n is false; both in code and contracts), `substr(s, lo, hi)`: if not `0<=lo<=hi<=n`, `slice_range`; if either end is not a boundary, `slice_cut`; otherwise `s[lo:hi]`.
- In proof mode, the failures above arise with the same kind, and `run.py` judges as now: "verification passed + failure on an input satisfying requires = unsound".
- Contracts (`cev`): `len`, indexing, and `is_char_boundary` on str, `[u8]`, and `[bool]`. Literals inside contracts are bytes too.
- `expected_stderr_prefix`: the §5.0 table.
- `_check_arg`: input value format check for the new types (u8 range, bool, str).
- Add new cases to `_selftest` (boundary formula, the two substr failure orders, alloc length→value order, literal escapes, multi-byte characters).

### 5.2 Generator `bench/fuzz/generate.py`
- `G2_TEMPLATES` at least 10. Each template by default produces the correct version (goal: passes verification), and with probability about 0.3 produces a G2-specific error version (the "rejected version" below). You may use the existing `mutate` and `maybe_bad_ensures`.
  1. `[i64]`→`[u8]` clamping loop store (q01 form) / rejected version: store without the upper-bound guard
  2. `[u8]` parameter scan (sum, max, count; overflow proved from the fact that elements are 0..255) / rejected version: store after comparison with an out-of-range constant, etc.
  3. `[u8]` copy then element update (+d saturating) and return / rejected version: delete one side of the saturation
  4. build a `[u8]` with `alloc` and return it (`ret_u8`, value a constant or computed) / rejected version: initial value 256, etc.
  5. `[bool]` parameter aggregate (count, longest run)
  6. build a `[bool]` and return it (`alloc(n, false)` then conditional stores, `ret_bool`)
  7. str parameter byte scan (count of a specific byte, number of characters, first position) / rejected version: index end +1
  8. return (`ret_str`) a boundary substring (`substr` after a guard with `is_char_boundary`, or a loop advancing to the next boundary) / rejected version: delete boundary guard, end ±1
  9. `len`, bytes, and `substr` (a boundary known inside the literal) of a string literal in code (including escapes and multi-byte characters) / rejected version: cutting in the middle of a multi-byte character
  10. str → `[u8]` byte copy (`alloc(len(s), 0)` then `out[i] = s[i]`, `ret_u8`)
  11. (optional) a function with `requires is_char_boundary(s, i)` and a call to it
- Literal content mixes ASCII printable characters, `"`, `\`, newline, tab, NUL, and 2/3/4-byte characters (testing both the oracle and the Rust source escaping).
- Input candidates (`candidate_inputs`): `array_u8` length 0..8, each element with probability 1/2 from {0,1,127,128,191,192,254,255}, otherwise uniform 0..255. `array_bool` length 0..8. `str` has 0..8 characters: ASCII 1/2 (including, besides printable characters, `\0`, `\n`, `\t`, `"`, `\\`), 2-, 3-, and 4-byte each 1/6 (excluding surrogates). If an integer parameter is used as an index or boundary, mix values near 0..len+1 and -1 (via `input_hints`).
- Identifier rules: no `__`, no Rust keywords, no `pruv_` prefix, no shadowing in the same scope. If there is a literal in code, copy, substr, or alloc, the signature has `! alloc`. Each while has invariant and decreases.
- Add `--g2` to `main` (`generate.py --seed S --count N --out DIR`).

### 5.3 Runner `bench/fuzz/run.py` and `README.md`
- `--g2` flag: `generate_case(..., g2=True)`, and `_g2` at the end of the output folder name. The input rng name also gets the `"g2:"` prefix.
- `batch_driver_source`: `array_u8` → `let aJ: Vec<u8> = vec![..];` + `&aJ`, `array_bool` → `Vec<bool>`, `str` → `let aJ: &str = "<escaped>";` + `aJ` (a character in 0x20..=0x7E that is not `"` or `\` is kept as is, the rest as `\u{lowercase hex}`). If the return is `str`, use `.as_bytes()` as in §5.0 item 6. Pass the return type to specs.
- `signature_from_src`: picks up `[u8]`, `[bool]`, and `str` returns and parameters.
- Check that the llvm path such as `prep_llvm` links together with the str/u8/bool bindings (`Pruv__Str`, `pruv_check_utf8`, `pruv_check_bool`, `__typed`) (add to the symbol rewrite list if needed).
- `deep_copy_arg` and `_check_arg` integration: str is immutable, so as is.
- Aggregation (`summary.json`, keys added only in g2 mode): `g2_verified` (passes verification and `case["g2"]`), `g2_rejected_built_safe_modes`, `g2_features_verified` (verification-pass count per tag), `g2_inputs_per_program_min`. Gate: with `--g2`, if `g2_verified < --programs` or `g2_rejected_built_safe_modes < --rejected-sample`, leave the numbers in `failures_by_kind["g2_shortfall"]` and exit 1 (decision 11). Oracle unsupported, parse error, incomplete, and timeout are not put in the pass count and are counted separately as now.
- Number of inputs: `--inputs` per program (default 8) as is. The number of programs with fewer than 8 inputs is counted as `g2_short_inputs`.
- README: G2 mode usage, representation (§5.0), and a place for measurement records (the main agent fills it in).

### 5.3a Audit reflections (main)
- Added `elem_range`, `slice_range`, `slice_cut` to `FAULT_KINDS` in `run.py` (if missing, G2 safe-mode failures and proof-mode soundness are not compared — audit must-fix 1). The existing paths never produce these kinds, so behavior is the same.
- `g2_verified` and `g2_rejected_built_safe_modes` count **only counted programs**: a g2 case, at least `--inputs` inputs, results of running all modes of that program (for rejected ones, safe mode) all present, and for those that passed verification, at least one input that satisfies requires and for which the oracle is not `limit` (audit must-fix 2 and recommendation).
- To cover that, only in g2 mode, collect verification passes up to 110% of `--programs` and the rejected sample up to `--rejected-sample + 5`.
- The oracle `narrow` also narrows `(alloc(..))` (same as the compiler, recommendation). The generator's integer-violating inputs were widened to `-1·-2·-7` and `L+1·L+2·L+5` to reduce cases of fewer than 8 inputs.
- In the `mutate_ops.py` ground-truth judgment, a rustc `compile_error` is counted as `crash` (candidate code-generation defect) (recommendation).

### 2.4a `ensures` of the reference solutions (main)
Measuring G2 mutation with the first version (`ensures` only on length), 39 false mutants passed verification. This was not a compiler defect but because the contracts did not carry the meaning. So the `ensures` of q01–q06 were changed to the full meaning in PROBLEMS.md (per-element values; q04: every true run ≤ result + a run of the result's length exists (witnessed by the start-position variable `start`); q05: `count`; q06: prefix bytes equal, end is a boundary, number of boundaries ≤ k, and either whole or number of boundaries = k).

### 5.4 End criteria (main runs)
- `run.py --g2 --seed S --programs 200 --rejected-sample 30` (S = 41, 56, 57), for compilers py and rs each: 0 failures, no `g2_shortfall`, 8 inputs per program.
- `run.py --seed 41 --programs 200` without `--g2` has 0 failures, and the output of `generate.py --seed 41 --count 300` is byte-identical to before the change.
- The `oracle.py` self-test passes.
