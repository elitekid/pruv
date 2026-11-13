# L0: Lair clipBytes cross-check
Compare Lair's unchanged JS body with a verified longest UTF-8 byte-prefix function.
Run: `python3 bench/l0/run.py` (options: `--seed 12345 --n 20000`).
Requires Node, Rust, Clang, and Python with z3; reuses `bench/g2/run.py` compilation/linking.
Tool overrides: `PRUV_PYTHON`, `PRUVC_RS`; a worktree may read main-checkout tools when Rust sources match.
Missing Rust binaries build offline with Cargo into `work/`; all generated files stay under this folder.
Recorded run: seed 12345, 20,000 random cases plus 83 edges = 20,083 cases per combination.
Python/Rust compiler × Rust/LLVM backend: all four verified the contracts without bypass flags.
Each combination: equal 14,157; TS shorter 5,926; TS longer 0; TS invalid 0.
Pruv met the independent longest-prefix oracle in 20,083/20,083 cases; TS in 14,157/20,083.
Minimal differing input hex `efbfbd61` (U+FFFD then `a`), max 3: TS `""`, Pruv/expected `efbfbd`.
The trailing replacement-character regex removes genuine U+FFFD as well as truncated-character replacements.
Thus TS remains a valid bounded prefix here but violates maximality; whole-string fast paths preserve U+FFFD.
`results/summary.json` records tools/counts; `differences.jsonl` holds the smallest 50 case/build differences.
Scope: valid UTF-8, nonnegative budgets and byte lengths up to 1,000,000; no full-suite tests were run.

## hostWithin
Compare Lair's TS with proved ASCII-folded host equality/subdomain matching (UTF-8 lengths <= 4096).
Run: `python3 bench/l0/run_host_within.py` (`--seed 12345 --n 20000`, random cases per mode).
Seed 12345: direct 20,020 cases; real path 20,018 URLs, 12,147 tested and 7,871 undefined hosts skipped.
Python/Rust compilers × Rust/LLVM backends all proved the contracts and exited successfully.
Each combination: direct equal 19,469, TS true/Pruv false 551, TS false/Pruv true 0.
Minimal difference: host `K` (hex `e284aa`), site `k` (hex `6b`): TS true, Pruv/oracle false.
JS Unicode lowercase maps Kelvin sign to ASCII k; the intended ASCII-only fold preserves it. No reverse-class example occurred.
Real path: all 12,147 equal, both difference classes zero; `https://K/` normalizes to host `k` and both return true.
Pruv matched the independent oracle in all 32,167 tested cases per combination; no difference reached the tested real path.
`results/host_within_summary.json` records counts; `host_within_differences.jsonl` stores the shortest 50 differences, without absolute paths.

## versionAtLeast (L1 second bundle)

Run: `python3 bench/l0/run_version_at_least.py --seed 12345 --n 20000`.
The JS function bodies are verbatim Lair code, with TypeScript signature annotations removed.
Pruv trims only ASCII TAB/LF/VT/FF/CR/SPACE, accepts three nonempty ASCII decimal
components, and compares significant digit lengths and bytes without integer conversion.
Precondition: each UTF-8 input length <= 4096. Both compilers prove byte access
safety, arithmetic safety, helper index bounds, call preconditions and termination.
There is no functional postcondition for this function: well-formedness and exact
ordering are cross-checked, not claimed as a formal proof.

Recorded seed 12345: 1,089 edge pairs + 20,000 random pairs = 21,089 cases.
All four compiler/backend combinations verified (exit 0); Pruv matched the Python
big-integer oracle in 21,089/21,089 cases per combination. TS matched 16,452;
3,615 differences were Unicode whitespace, 1,022 were Number precision, other 0.
Shortest observed difference: `a="0.0.0"`, `b="\u00a00.0.0\u00a0"` (14 total UTF-8
bytes): TS true, Pruv/oracle false. Shortest means within the sampled corpus.
`results/version_at_least_summary.json` records counts and verification exit codes;
`results/version_at_least_differences.jsonl` holds the shortest 50 case/build records.

## colLetters (L1 second bundle)

Run: `python3 bench/l0/run_col_letters.py --seed 12345 --n 20000`.
Precondition: `0 <= col <= 1000000000000000`; allocation effect: `! alloc`.
Both compilers prove every result byte is 65..90, `(len(result)==0)==(col==0)`,
`len(result)<=col`, and `col<26^k ==> len(result)<=k` for every k from 1 through 11.
Byte access, UTF-8 substring boundaries, allocation call preconditions, arithmetic
safety and recursive termination (`decreases col`) also verify. The exact bijective
base-26 value is checked against an independent length-block Python integer oracle.

Recorded seed 12345: dense 0..100000, 70 power-boundary cases, two upper-limit
cases and 20,000 random inputs = 120,073 cases. All four compiler/backend
combinations verified (exit 0); both Pruv and TS matched 120,073/120,073.
All difference classes are zero; there is no differing input.
`results/col_letters_summary.json` records counts and verification exit codes;
`results/col_letters_differences.jsonl` is empty.

Both drivers reuse the G2 harness and run JS once per driver. Each driver exited 0.
With compiler command `$C` (Python interpreter plus `pruvc/pruvc.py`, or the Rust
compiler binary), G2 ran the following for each `NAME` and compiler, all exit 0:

```sh
$C bench/l0/NAME.pruv -o bench/l0/work/NAME_COMPILER_rust/NAME_gen.rs
$C bench/l0/NAME.pruv -o bench/l0/work/NAME_COMPILER_llvm/NAME_gen.ll --backend llvm --rust-bindings bench/l0/work/NAME_COMPILER_llvm/NAME_gen.rs
```

Use `PRUV_PYTHON` and `PRUVC_RS` to select installed tools; add Cargo's bin directory
to PATH. No bypass flags, full suites, compiler edits or Lair edits were used.
