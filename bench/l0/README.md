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
