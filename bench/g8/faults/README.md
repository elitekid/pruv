# G8 compiler faults

Run `python3 -B bench/g8/faults/check.py` or `--only f1` through `--only f5`. Only named G8 groups run.
Each patch is applied alone with patch -p1; clean baselines must pass. The unchanged test runner is copied too so bundle meta-tests use the faulty compiler.
User write boundaries override /tmp: all disposable copies and TMPDIR live in owned directories and copies are removed. Full commands and output: ../results/faults.json.

| ID | Omission | SHA256 prefix | Replay command | Detecting tests | Gap |
|---|---|---|---|---|---|
| f1_unused | Skip proofs of std functions unreachable from user definitions | 666a37aa7c81b4e8 | `python3 -B bench/g8/faults/check.py --only f1` | g8_proof/bundle | none |
| f2_trusted | Trust every std contract without proving bundle bodies | ba7411dabdfe5da1 | `python3 -B bench/g8/faults/check.py --only f2` | g8_proof/bundle | none |
| f3_local | Load local std.pruv despite the reserved-module conflict | 5e20a4cc1569eb0a | `python3 -B bench/g8/faults/check.py --only f3` | g8_frontend/bundle, must_reject/g8_conflict/root.pruv, must_reject/g8_symlink_conflict/root.pruv | none |
| f4_rust_requires | Drop safe std requires under trust-callers (Rust) | 92465ab232df702d | `python3 -B bench/g8/faults/check.py --only f4` | runtime/g8_r03_clamp_i64 [--no-verify --trust-callers], runtime/g8_r04_abs_i64 [--no-verify --trust-callers], runtime/g8_r07_sum_i64 [--no-verify --trust-callers], runtime/g8_r11_array_max_i64 [--no-verify --trust-callers], runtime/g8_r16_trust_internal [--no-verify --trust-callers] | none |
| f5_llvm_requires | Drop safe std requires under trust-callers (LLVM) | 0052af1b2e44ee41 | `python3 -B bench/g8/faults/check.py --only f5` | runtime/g8_r03_clamp_i64 [--no-verify --trust-callers] [llvm], runtime/g8_r04_abs_i64 [--no-verify --trust-callers] [llvm], runtime/g8_r07_sum_i64 [--no-verify --trust-callers] [llvm], runtime/g8_r11_array_max_i64 [--no-verify --trust-callers] [llvm], runtime/g8_r16_trust_internal [--no-verify --trust-callers] [llvm] | none |
