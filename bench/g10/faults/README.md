# G10 compiler fault injections

Each patch is applied alone with `patch -p1` to a disposable copy of the current `pruvc/`.
The copy, generated output and compiler caches stay under `bench/g10/.work` and are removed.
The original compiler is never patched. Run `python3 bench/g10/faults/check.py`.
Direct named must_reject rows use their checked-in stage/code JSON oracle; clean baselines must pass.
Timeouts and startup failures do not count. An internal error counts only as a detected
diagnostic regression, never as acceptance or a successful source-mutant rejection.

| Rule family | Patch SHA256 prefix | Named test(s) | Command in disposable copy | Result |
|---|---|---|---|---|
| f1_use_after_close.diff | bb1d3b9a9f2f111f | g10_use_after_close | `$PRUV_PYTHON pruvc/pruvc.py <test>.pruv --backend rust -o <work>/out.rs` | detected (accepted) |
| f2_double_close.diff | 7a323254eccbfde5 | g10_double_close | `$PRUV_PYTHON pruvc/pruvc.py <test>.pruv --backend rust -o <work>/out.rs` | detected (accepted) |
| f3_branch_move.diff | 2b7c1aacf351992e | g10_branch_move | `$PRUV_PYTHON pruvc/pruvc.py <test>.pruv --backend rust -o <work>/out.rs` | detected (accepted) |
| f4_loop_move.diff | 6f0efb1a0fd1580f | g10_loop_move | `$PRUV_PYTHON pruvc/pruvc.py <test>.pruv --backend rust -o <work>/out.rs` | detected (accepted) |
| f5_borrow_consume.diff | 526e44e78b00145b | g10_borrow_close | `$PRUV_PYTHON pruvc/pruvc.py <test>.pruv --backend rust -o <work>/out.rs` | detected (accepted) |
| f6_owned_placement.diff | f64221df84189d6a | g10_owned_field | `$PRUV_PYTHON pruvc/pruvc.py <test>.pruv --backend rust -o <work>/out.rs` | detected (internal_error) |
| f7_host_entry.diff | c4aa3aabd3fe4bc4 | g10_host_entry, g10_main_signature | `$PRUV_PYTHON pruvc/pruvc.py <test>.pruv --backend rust -o <work>/out.rs` | detected (accepted) |
| f8_catalog_requires.diff | b716f81d1f328fd4 | g10_v_read_created, g10_v_write_opened, g10_v_byte_at_size, g10_v_read_unchecked | `$PRUV_PYTHON pruvc/pruvc.py <test>.pruv --backend rust -o <work>/out.rs` | detected (accepted) |

Full commands, exit codes, baseline diagnostics and faulty diagnostics are in `../results/faults.json`.
The host-entry family includes both explicit public entries (`entry_signature`) and implicit main
(`foreign_export`), reflecting the actual diagnostic names rather than treating them as identical.
The proof fault covers both byte bounds and read/write mode catalog preconditions.
