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
