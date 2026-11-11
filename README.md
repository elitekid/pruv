# Pruv

Korean version: [README.ko.md](README.ko.md)

A language where AI writes the code, humans read only the promises (contracts), and the compiler proves that the code keeps those promises.
Safeguards that have been proven (range checks, overflow checks) are erased so the program runs fast.

- Language specification: [SPEC.md](SPEC.md)
- Blueprint (goals and stage plan): [BLUEPRINT.md](BLUEPRINT.md)
- Experiment results: [RESULTS.md](RESULTS.md)

## Current status (prototype v0.1)
The canonical compiler is the Rust implementation `pruvc` (`pruvc-rs/`). It is a single executable that statically includes z3 and LLVM (the macOS build still depends dynamically on Homebrew libzstd; the release build is on hold),
and `--emit rs|ll|obj|exe` produces Rust source, LLVM IR, an object file, or an executable.
The Python implementation `pruvc/` is kept as the cross-check reference (it is not deleted; it serves as the counterpart for the test tools' cross-checks).
The default tests target the Rust implementation (the release build is on hold).

### Build and usage (Rust implementation)
```
cd pruvc-rs
LLVM_SYS_221_PREFIX=/opt/homebrew/opt/llvm@22 cargo build --release --locked
cd ..
pruvc-rs/target/release/pruvc examples/sum.pruv --emit exe -o sum     # executable
pruvc-rs/target/release/pruvc examples/sum.pruv --emit rs -o sum.rs   # Rust source
pruvc-rs/target/release/pruvc examples/sum.pruv --emit ll -o sum.ll --rust-bindings sum_bind.rs   # LLVM IR (+ Rust bindings sum_bind.rs)
```
If `--rust-bindings` is omitted, `--emit ll` writes the bindings to the `-o` name with its extension stripped and `.rs` appended (sum.ll → sum.rs), so give it a different name to avoid overwriting the sum.rs from the rs example above.
If `-o` is omitted, `--emit exe` uses the input name with its extension stripped (with `.exe` appended for a Windows target) and links with the system linker (the environment variable `PRUVC_LINKER` if set; otherwise macOS `xcrun --find cc` (or `cc` if that is missing), Linux `cc`). Linking an exe for a Windows target is not supported yet (only the `.exe` naming rule is in place). Other options:
`--no-verify`, `--trust-callers`, `--contract-budget N` (for testing), `--target TRIPLE`, `-mcpu=CPU`, `--backend rust|llvm`, `--rust-bindings PATH`, `--also-llvm LL RS` (together with `--emit rs`, for testing).
The test tools (`tests/run_all.py` etc.) use this binary by default (`--compiler py` for the Python implementation, `--compiler-path` for another location).

### Cross-check reference (Python implementation)
A Python 3.9 + z3 prototype: parser → type and effect checking → z3 proof → Rust code generation → rustc.

```
python3 -m venv .venv && .venv/bin/pip install z3-solver
.venv/bin/python pruvc/pruvc.py examples/sum.pruv -o sum.rs && rustc -O sum.rs
```

### Policy for new features
A new language feature goes into the Python implementation first (quick prototype, independent cross-check), and in the same batch it is ported to the Rust implementation
and made to pass the `tests/m3_all.py` cross-check. The default tests target the Rust implementation (the release build is on hold).

## License
You may choose either MIT or Apache-2.0 ([LICENSE-MIT](LICENSE-MIT), [LICENSE-APACHE](LICENSE-APACHE)).
Unless stated otherwise, contributions submitted to this repository are made under the same two licenses.
The Rust implementation's executable statically includes z3 (MIT) and LLVM (Apache-2.0 WITH LLVM-exception). When distributing the executable, include z3's MIT notice with it.
