# G10 Q, part 1

Two file problems, default-verified reference solutions, a four-configuration grader,
42 explicit invalid source mutants plus two controls, eight compiler fault injections,
and a 10 MB read/sum benchmark. `PROBLEMS.md` contains statements and Python oracles,
without Pruv implementation guidance.

## Run

From the repository root (no installation or new dependencies):

```
python3 bench/g10/run.py bench/g10/solutions --compiler py
python3 bench/g10/run.py bench/g10/solutions --compiler rs --backend rust
python3 bench/g10/mutate_ops.py --self-test
python3 bench/g10/mutate_ops.py --list
python3 bench/g10/mutate_ops.py --compiler py --jobs 8
python3 bench/g10/faults/check.py
python3 bench/g10/perf.py --compiler py
python3 bench/g10/perf.py --compiler rs --backend rust
```

`run.py` also supports `--compiler both`, `--backend rust|llvm|both`, an explicit
JSON output path and `--no-verify`. Mutants support either compiler and either/both
backends; default is Python/both. Performance builds always verify and use default
foreign checks; its exit status is 1 when the 1.5x target is missed.

All temporary programs, file fixtures, compiler copies and caches are confined to
`bench/g10/.work/`. Drivers create their own input files. Disposable working-tree
compiler copies are removed after each injection; no worktree, source compiler,
original checkout, dependency installation or elevated permission is used.

This delegated checkout had neither `.venv` nor a Rust compiler binary. Recorded runs
used existing tools through these overrides, without modifying their locations:

```
export PRUV_PYTHON=/Users/spica4345/Projects/pruv/.venv/bin/python
export PRUVC_RS=/Users/spica4345/Projects/pruv/pruvc-rs/target/release/pruvc
export RUSTC=/Users/spica4345/.rustup/toolchains/stable-aarch64-apple-darwin/bin/rustc
```

The outer interpreter was `/opt/homebrew/bin/python3 -B`; Python compilation always
used this checkout's `pruvc/pruvc.py`. Tool paths are included in the JSON results.
The externally supplied Rust binary was not rebuilt or asserted identical to these
uncommitted Python sources. Default tool selection uses the current repository.

## Recorded results

| Command/configuration | q01 | q02 | Exit |
|---|---:|---:|---:|
| grader, py-rust | 40/40 | 18/18 | 0 |
| grader, py-llvm | 40/40 | 18/18 | 0 |
| grader, rs-rust | 40/40 | 18/18 | 0 |
| grader, rs-llvm (after the Rust A3 port) | 40/40 | 18/18 | 0 |
| independent author (`solutions/indep1`), all four configurations | 40/40 | 18/18 | 0 |

`results/solutions_py_both.json` and `results/solutions_rs_rust.json` contain the
default-mode proof/build/runtime results. rs-llvm was run after the Rust A3 port
(`results/solutions_rs_llvm.json`). The independent solutions were written from SPEC.md and
PROBLEMS.md only, without a compiler, and passed on the first attempt
(`results/solutions_indep1_both_both.json`; assumptions in `solutions/indep1/NOTES.md`). No full test suite was run.

Mutant self-test passes; `--list` lists all 44 unique exact edits. The full Python
run exits 0: each backend rejects 36 at verification and 6 at static checking;
the two controls pass runtime tests. **wrong_but_proved = 0**, with no unresolved
invalid mutant. `results/mutants.json` preserves each edit, source hash, diagnostic,
no-verify result and per-backend classification.

The no-verify oracle observes 31 runtime-incorrect programs, 6 statically invalid
programs and 7 programs passing the fixture tests. Five of those seven still have
invalid proof obligations (unchecked reopening or unjustified claims about the
fresh handle); the other two are controls. Passing finite tests does not establish
correctness. Wrong-mode, unchecked-read, renamed-use-after-close, byte bounds,
transformation, unchecked-write, size bounds and missing-close/reopen mutations
are explicit catalogue entries, not random or regex-generated edits.

G10 3.3 allows implicit close, and G10 4.3 gives a fresh, unrelated result at each
open. Therefore removing `file_close` alone cannot be required to fail verification.
The two controls expose this limit; they are not claimed to implement q01's explicit
close-error reporting contract on every OS failure. The six missing-close/reopen
mutants omit close **and** make an invalid read, byte access or assertion about the
reopened handle. Neither a missing close nor filesystem persistence is falsely
reported as a property the compiler proves. End-to-end file contents and status
semantics are checked by runtime oracles; q01 also proves the local byte transform.

All eight injected compiler faults are caught by named rejection tests with clean
baselines. Seven families allow at least one invalid program; disabling owned-field
placement instead causes an internal compiler error. The latter is recorded as a
diagnostic regression, not unsound acceptance. See [faults/README.md](faults/README.md)
for patch hashes, commands and detecting tests, and `results/faults.json` for raw evidence.

| Performance configuration | Pruv median ms | Hand Rust median ms | Ratio | <=1.5x |
|---|---:|---:|---:|---|
| py-rust | 2.612625 | 1.172750 | 2.2278x | fail |
| rs-rust | 2.295813 | 1.097438 | 2.0920x | fail |
| py-llvm | 25.583375 | 1.144105 | 22.3610x | fail |
| rs-llvm | 26.856688 | 1.300001 | 20.6590x | fail |

Final performance runs were serialized after the mutation/fault jobs finished.
Each measurement reads and sums exactly 10,000,000 bytes, checks the checksum,
warms up both implementations and alternates order for ten in-process repetitions.
Both include open/read/sum/drop; fixture creation is excluded. The Rust baseline
uses `File::open` and `read_to_end`, as the Pruv runtime does. LLVM uses the existing
G2 Rust shim/runtime linking path. `rustc -O` and `clang -O2` are used; no unchecked
or no-verify shortcut is enabled. Raw samples and tool versions are in
`results/perf_py_both.json`, `results/perf_rs_rust.json` and `results/perf_rs_llvm.json`.
The 1.5x target is not met; causes and the deferred fast byte path are in G10_SPEC sections 8-9.

**The performance gate is not met; both performance commands exit 1.** No compiler
optimization was attempted outside the authorized `bench/g10/` scope. Actual disk
full/final-flush failure is not injected by the file fixtures; deterministic output
failures use a directory and a missing parent instead. The independent-author
exercise is outside this part-1 assignment.

## Files

- `PROBLEMS.md`, `solutions/q01/root.pruv`, `solutions/q02/root.pruv`
- `run.py`, `mutate_ops.py`
- `faults/check.py`, `faults/README.md`, `faults/f1_*.diff` through `faults/f8_*.diff`
- `perf.py`, `perf/sum.pruv`, `perf/driver.rs`
- `results/.gitkeep`, solution/mutant/fault/performance JSON evidence
- `.gitignore`, this README
