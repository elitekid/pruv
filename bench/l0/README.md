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

## termPlain (L2 first bundle)

Run: `python3 bench/l0/run_term_plain.py --seed 12345 --n 20000`.
Source: Lair `src/backend/engine-install.ts` `plainFromAnsi` + `applyCrLf`, copied with types
removed to `term_plain.mjs`. The streaming state is an integer 0..11
(0 plain, 1 ESC, 2 ESC + intermediate, 3 CSI, 4 control string, 5 control string after ESC;
plus 6 while an LF right after a CR is skipped).
`term_plain(state, data) -> str ! alloc` and `term_state(state, data)` both require
`0 <= state < 12` and `len(data) <= 10^12`. Proved: UTF-8 boundary slicing, `len(result) <= len(data)`,
the state stays in 0..11, arithmetic safety and termination. Exact behaviour is checked against an
independent whole-text Python oracle (a mode machine and a regex CR/LF fold), so chunking is also checked.

Recorded seed 12345: 8,748 edge cases plus 20,000 random chunked cases = 28,748. All four
compiler/backend combinations verified (exit 0). Pruv and TS both matched 28,748/28,748 in text and
final state. `results/term_plain_summary.json` records the counts; `results/term_plain_differences.jsonl` is empty.

## decodeBytes + looksBinary (L2 second bundle)

Run: `python3 bench/l0/run_decode_bytes.py --seed 12345 --n 20000`.
Target: Lair `src/documents/decode.ts` (BOM sniffing, strict UTF-8, else EUC-KR via
`TextDecoder`; binary = a NUL byte in the first 8 KiB). `decode_bytes.mjs` holds the body verbatim.
`decode_bytes.pruv` proves the BOM checks, a strict UTF-8 validator and `looks_binary` exactly,
and calls four trusted adapters in `decode_adapter/` (crate `pruv_decode`, built on `encoding_rs`)
that return owned `String` (G6b). `run.py:build_decode_adapter` builds the crate under `work/`.
Oracle: `decode_oracle.py`, written from the WHATWG Encoding Standard without Python codecs;
it reads `data/index-euc-kr.txt` (official index, SHA-256 checked, `-text` in `.gitattributes`).
The TS copy runs in Lair's Electron when available (`LAIR_ELECTRON`, then an installed Lair
Preview), because Homebrew Node 26's EUC-KR decoder is not WHATWG (0x80 gives U+0080).

Recorded seed 12345: 1,939 edge + 20,000 random byte strings = 21,939 cases. All four
compiler/backend combinations verified (exit 0). Pruv, the TS original (Electron 44.11.2,
Node 24.22.2, ICU 78.2) and the oracle agree on `[text, encoding, binary]` in 21,939/21,939.
`results/decode_bytes_summary.json` records counts; `decode_bytes_differences.jsonl` is empty.
