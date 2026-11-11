# G2 Q2 Implementation Spec: Measurement, Independent Use, SPEC Summary

The last gate of G2_SPEC 7.7·8.4. The compilers (`pruvc/`·`pruvc-rs/`) are not changed. Only measurement tools and solutions are added.

## 0. Baseline

- **Pre-G2 baseline commit:** `5c65fe3` (right before G2 A0 `ea4efb5`; the compiler code is pre-G2). Worktree `/tmp/q2/base`; the Rust implementation is
  built with `CARGO_TARGET_DIR=/tmp/q2/base-target` to get `/tmp/q2/base-target/release/pruvc`.
- **Now:** `HEAD` (after Q1 `337ac05`), `pruvc-rs/target/release/pruvc`.
- The canonical implementation is the Rust one. The Python implementation is for cross-checking, so it is not the main subject of timing measurements (if re-measured, record it separately).
- Do not run measurements concurrently with other heavy work (serial, jobs 1). Record the machine load in the results.

## 1. Existing compile/proof time (`bench/g2/measure_compile.py`)

- Input: the 231 files in `tests/smt_snapshot_inputs.txt` (pre-G2 programs, fixed in A0, including rejection samples).
- Command: each implementation's `pruvc <file> -o <tmp>.rs` (verification + Rust source generation, no rustc). Wall-clock time (`time.perf_counter`), exit code.
- R repetitions (default 5). Within one repetition, run base → head alternately for each file so that load differences over time are spread evenly across both sides.
- Record: per file, each implementation's time list, median, and exit code. Summary: sum of per-file medians, median of the per-file medians, p90, maximum, implementation ratio (head/base),
  the list of files where head is more than 10% slower than base and the difference exceeds 0.05 s, and the list of files where the two implementations' exit codes differ (a failure if any).
- Gate: total ratio ≤ 1.10. If exceeded, find the cause and then decide (8.4).

## 2. Solver statistics (`bench/g2/solver_stats.py`)

- Means: the JSON of `tests/diff_py_adapter.py trace <file> [--infer]` (`obligations[].attempts[].{smt2,result,lemmas}`, `skipped`).
  The SMT snapshot of the existing 231 files is byte-identical to pre-G2 (Q1 reference values), so record that the statistics are also the same; the newly measured targets are the G2 programs.
- Targets: `bench/g2/solutions/ref_pruv/*.pruv`, the final version of the independent solutions, and the G2 positive samples in `examples/` (`g2*`).
- Per file: number of obligations, number of attempts, count per result kind (`unsat`/`sat`/`unknown`/anything else as is), number skipped, number of occurrences of `forall`·`exists` in smt2 (quantifier count),
  timeout indication (the result string as is). Total row.

## 3. Array run time and memory (`bench/g2/perf/arr_*.pruv`, `bench/g2/measure_run.py arrays`)

- Three `main` programs doing the same job with `[i64]`, `[u8]`, and `[bool]`: `alloc` an array of length N = 20_000_000 and fill it with a loop
  (i64·u8: `i % 200`, bool: `i % 2 == 0`), then scan it again and `print` the counted value (integer: the number of elements `>= 100`; bool: the number of true elements).
  It must pass verification in proof mode.
- Build standalone executables with both backends (rust, llvm) (`pruvc file -o exe`; the link path is the same as in the existing tests), run R times (default 5), and record the wall-clock median,
  the median of the maximum resident set size from `/usr/bin/time -l`, and whether the output value is the same for all three types (correctness check).
- Note: since filling and scanning are one program, this is the "allocate + fill + scan" time. Process start-up cost is included (we expect it to be small because N is large, but we record the number: also measure the time of a paired N=0 program).

## 4. String-processing cost (`bench/g2/perf/str_ops.pruv`, `bench/g2/measure_run.py strings`)

In a Rust driver (include the generated Rust as a `mod`, like the TEMPLATE in `bench/g2/run.py`), measure only the function calls with `std::time::Instant`.
The input String has length B bytes (1_000_000 and 8_000_000), half ASCII and half multi-byte (deterministic generation).

| Item | Pruv function | Meaning |
|---|---|---|
| Byte scan | `scan_str(s: str) -> i64` (the number of bytes ≥ 128) and `scan_u8(a: [u8]) -> i64`, which does the same job | whether reading a str costs the same as reading a [u8] |
| Partial copy | `mid(s: str, lo: i64, hi: i64) -> str ! alloc` (`substr`) and `dup(s: str) -> str ! alloc` (`copy`); the driver passes the received String through `black_box` | substr·copy cost (per byte). Includes allocation; for llvm, includes the UTF-8 re-check of the binding's str return |
| ABI UTF-8 check | llvm: the raw C entry `pruv_abi_blen(ptr, len)` (does the UTF-8 check) and the binding `blen(&str)` (`pruv_abi_blen__typed`, no check) | difference = the cost of the raw entry's `pruv_check_utf8`. The rust backend takes `&str`, so there is no check |

Fix (after the first measurement): the first version used `mid_len`·`copy_len` (returning only len), so on the rust backend the copy was optimized away (below 0.0001 ns per byte), and the UTF-8 check, measured as the binding `blen` (typed, no check) versus `blen_u8`, came out as 0. We changed to the table above and measured again.

- Median of R runs (default 7) per call, ns per byte. Check that the result equals the `reference` computation (a failure if not).
- Every function is built in proof mode (verification passes). If a public-entry `requires` check is involved (such as `len(s) <= ...`), its cost is included too, so the measured functions
  carry only O(1) requires.

## 5. Contract-writing volume (`bench/g2/solutions/i64_repr/`, `bench/g2/contract_size.py`)

- The same 6 problems written in the pre-G2 representation: bytes use `[i64]` + an element-range `requires`/`ensures` (`0 <= a[k] && a[k] <= 255`),
  bool uses `[i64]` 0/1, and strings use `[i64]` bytes + the boundary expression written out in full (`k == 0 || k == len(a) || (a[k] < 128 || a[k] >= 192)`).
  The function names are the same; only the types differ. They must pass verification (they are not run through the grader: the signatures differ).
- Counts: per file, the number of `requires`·`ensures`·`invariant`·`assert`·`decreases` lines and the token count of those clauses (identifiers, numbers, operators; comments excluded),
  and the number of code (rest of the body) lines. ref_pruv and i64_repr side by side.

## 6. Existing bench correctness and verification success rate

- Run the existing bench (`bench/harness/run.py`, the canonical solutions folder) at HEAD on both backends and compare the correctness and verification results against the reference results file (the exact command is decided after investigation).
- g1 ref·indep_try2, examples·must_reject are already covered by the `run_all` 833 rows (Q1 baseline, compiler unchanged).

## 7. Independent use (8.4)

- Author: a Claude sonnet write delegation, allowed to read only `SPEC.md` and `bench/g2/PROBLEMS.md` (no other solutions, examples, docs, or compiler), no execution.
- First attempt `bench/g2/solutions/indep_try1/`, fixed version `indep_try2/` (place all 6, not only the problems that need it). The main agent grades with
  `bench/g2/run.py` over `--compiler rs`·`py` × `--backend rust`·`llvm`. Results `bench/g2/results/indep_try{N}_{compiler}_{backend}.json`.
- What is handed over for fixing is only the compiler error JSON (including counterexamples) and the first line of the failing test. No reference solution or hint is given.
- Record: first-attempt success count, number of fixes, final success count. If a failure's cause is a gap in the spec, record it together with the fact that SPEC was fixed.
- What actually happened (RESULTS 43): author 1 `indep_try1..3` (2 fixes, final 5/6) → added `verify_unknown` guidance to SPEC §8 →
  author 2 `indep2_try1` (6/6, but the guidance example contained the correct invariant of q04 — audit must-fix 1) → with the SPEC whose example was changed to generic wording,
  author 3 `indep3_try1` (6/6 on the first attempt, the result used for the gate decision). Each author is a new delegation (does not know earlier attempts); authors 2 and 3 are also forbidden from the earlier solution folders.

## 8. What remains

- Rejection of negative lengths and NULL for the raw entries `[i64]`·`[u8]`·`[bool]` is not added this time, following G2_SPEC 5.4 ("the actual allocation size, lifetime, and accessibility of a raw pointer are
  the contract of the external caller"). `str` was added in B2. It is recorded as a remaining gap.
- i32 (A6) is deferred.
