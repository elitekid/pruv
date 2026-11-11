# M3 (C4) 0B: dependency locking procedure and record items

Design basis: `docs/M3_C4_SPEC.md` §2 (dependency pinning) and §6 (z3 reproduction rules). The workspace is `pruvc-rs/`.

The first deliverable of 0B is `Cargo.lock`. The procedure below is run in `pruvc-rs/`.
If `crates/pruvc` does not exist yet, the workspace will not load, so create it first.

## 1. Dependency locking procedure

```sh
cd pruvc-rs

# 1) generate the lock file
cargo generate-lockfile

# 2) check that there is a single set of the z3 family (two sets count as failure)
cargo tree -e features -p pruv-proof -i z3-sys
cargo tree -e features -p pruv-proof -i z3-src
cargo tree -d            # list of duplicate versions. Stop if z3-sys or z3-src appear
#   - z3-src must be the single 503.3.0, and z3-sys the single one that z3 0.22.0 requires.
#   - Change the directly specified z3-sys (`z3-sys = "0"` in Cargo.toml) to the exact version "=x.y.z" shown in the lock.

# 3) check the static dependency (is libz3 inside the executable thanks to vendored?)
cargo build --release --locked -p pruv-proof --bin pruv-proof-spike
otool -L target/release/pruv-proof-spike        # Linux: ldd
sh ../ci/m3/check_deps.sh target/release/pruv-proof-spike

# 4) the same build as CI (no automatic dependency updates)
cargo build --release --locked
```

- Only `cargo build --release --locked` is the CI build method. Do not run `cargo update` without `--locked`.
- Do not use the `gh-release` feature (SPEC §2: z3#11266).
- `check_deps.sh` fails if `/opt/homebrew`, `/usr/local/Cellar`, the build folder path (`CHECK_DEPS_BUILD_DIR`, default the current folder),
  `libz3`, or `libLLVM` is in the dependency list. System libraries (`libSystem`, `libc++`, etc.) pass.
- If the script has no execute permission, call it as `sh ci/m3/check_deps.sh ...`.

## 2. Running the spike and cross-checking against Python

```sh
cargo run --release --locked -p pruv-proof --bin pruv-proof-spike -- --list
cargo run --release --locked -p pruv-proof --bin pruv-proof-spike -- s1_sum_loop     # one JSON object
cargo run --release --locked -p pruv-proof --bin pruv-proof-spike -- --all           # one line per sample (JSON Lines)

python3 tests/diff_py_adapter.py trace pruvc-rs/crates/pruv-proof/samples/s1_sum_loop.pruv   # same format
```

Output format:

```json
{"sample": "...", "obligations": [
  {"seq": 1, "fn": "...", "line": 8, "col": 22, "code": "invariant_entry",
   "attempts": [{"lemmas": false, "smt2": "(set-option :timeout 8000)\n...", "result": "sat|unsat|unknown"}]}
 ], "z3_version": "..."}
```

Assumptions that must match in the cross-check (if they diverge, the difference comes from these assumptions and not from SMT):

1. `seq` counts from 1 over the whole sample, in the order in which `prove` recorded attempts. Obligations skipped through `seen` are not recorded.
2. `smt2` is `Solver.sexpr()` **before check**. `(set-option :timeout 8000)\n` is prepended.
3. The havoc variable order is by name (0A sorting in SPEC §6). The Python side must also iterate after sorting.
4. A new process per sample: `_MODEL_SEQ` starts at 0, giving the `m1t0!Point` form.
5. The Python side's z3 is `z3-solver==5.3.3.0`, and the context is `Z3_mk_context_rc` + the SMT-LIB2 output mode (z3py default). Rust uses a non-rc context
   + the same output mode, and this is assumed to have no effect on the text.

## 3. 0B record items

The measured-value cells are left empty (`not measured`). The main fills them in after the first build.

| Item | Value | Notes |
|---|---|---|
| Full rustc / cargo version | not measured | `rustc -Vv`, `cargo -V`. The toolchain file says 1.99.1 |
| Confirmed z3 crate version | not measured | spec `=0.22.0` |
| Confirmed z3-sys version | not measured | A single version per Cargo.lock, pinned as `=x.y.z` in Cargo.toml |
| Confirmed z3-src version | not measured | spec `=503.3.0` |
| Full z3 runtime version (Rust) | not measured | `z3_version` of the spike JSON |
| Full z3 runtime version (Python) | not measured | `z3.get_full_version()`, spec 5.3.3.0 |
| z3-family duplicates in `cargo tree -d` | not measured | must be 0 to pass |
| Cargo.lock SHA-256 | not measured | |
| z3-src / z3-sys source hashes | not measured | hash of the `.crate` files in `~/.cargo/registry` |
| `otool -L` / `ldd` result | not measured | pruv-proof-spike |
| `check_deps.sh` result | not measured | pass/fail and the items found |
| First spike build time (release, clean target) | not measured | including the vendored z3 build |
| Spike executable size | not measured | after strip |
| Verdict comparison of 6 samples × (Rust, Python) | not measured | number of verdict mismatches, number of text mismatches |
| Number of obligations with identical SMT text / total | not measured | primary criterion (SPEC §6). If different, replay both originals with the same z3 |
| Mismatches near 8 seconds (inconclusive_timeout) | not measured | save the original, reason_unknown, and elapsed time; rerun 3 times each |
| Text difference from the z3 crate's high-level API | not measured | This prototype uses sys directly. The high-level `forall_const` may differ in weight/qid |
| Places the main fixed in sys.rs | not measured | list of signature differences |

## 4. Known unverified items

- This document and the source were written without compiling. Differences in z3-sys signatures are fixed in one place, `crates/pruv-proof/src/sys.rs`.
- The agreement between the Rust verdicts and the Python verdicts is not measured. The samples mix the proof success (unsat), counterexample (sat), and first-attempt sat → lemmas unsat paths, but
  which obligation gets which verdict is decided by z3.
