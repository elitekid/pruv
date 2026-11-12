# G7 compiler fault injections

Run `PRUV_PYTHON=/path/to/python python -B bench/g7/faults/check.py`.
Each patch is applied alone to a disposable working-tree compiler snapshot under faults/.
Fixtures are read from this working tree; no git reset/checkout, /tmp writes, or compiler edits.
This follows G10 snapshot isolation instead of copying the entire repository, to honor the delegated write boundary.
Named must_reject oracles compare checked-in stage/code and flags on both backends.
Runtime f8 builds/runs the existing g7_r10_join_return source/driver and compares its spec stdout.
f9/f10 are direct LLVM artifact assertions; these are benchmark assertions, not additions to tests/.
Clean baseline success is required; compile failures, timeouts, internal errors and unknown proofs never count.

| ID / omitted rule | SHA256 prefix | Rerun command | Detecting tests | Result / gap |
|---|---|---|---|---|
| f1_write_read | 6f7858ae1c81ed99 | `python -B bench/g7/faults/check.py --only f1` | g7_alias_write_read:rust (diagnostic_regression), g7_alias_write_read:llvm (diagnostic_regression), g7_alias_read_write:rust (diagnostic_regression), g7_alias_read_write:llvm (diagnostic_regression) | detected |
| f2_write_write | 66214bfad50ca720 | `python -B bench/g7/faults/check.py --only f2` | g7_alias_write_write:rust (diagnostic_regression), g7_alias_write_write:llvm (diagnostic_regression), g7_alias_write_write_noverify:rust (accepted), g7_alias_write_write_noverify:llvm (accepted) | detected |
| f3_transitive_foreign | a2ec7eda2c0e22af | `python -B bench/g7/faults/check.py --only f3` | g7_foreign_deep:rust (diagnostic_regression), g7_foreign_deep:llvm (diagnostic_regression) | detected |
| f4_nested | 5c716c180a80dbe5 | `python -B bench/g7/faults/check.py --only f4` | g7_nested_indirect:rust (diagnostic_regression), g7_nested_indirect:llvm (diagnostic_regression) | detected |
| f5_early_ensures | 9d3dd86e8811ed4c | `python -B bench/g7/faults/check.py --only f5` | g7_v_sibling_ensures_order:rust (accepted), g7_v_sibling_ensures_order:llvm (accepted) | detected |
| f6_no_havoc | 21e247c855c932a5 | `python -B bench/g7/faults/check.py --only f6` | g7_v_stale_contents:rust (accepted), g7_v_stale_contents:llvm (accepted), g7_v_partial_frame:rust (accepted), g7_v_partial_frame:llvm (accepted) | detected |
| f7_loop_writes | 1cbc0b86d76b30d4 | `python -B bench/g7/faults/check.py --only f7` | g7_v_loop_stale:rust (accepted), g7_v_loop_stale:llvm (accepted), g7_v_loop_stale_infer:rust (accepted), g7_v_loop_stale_infer:llvm (accepted) | detected |
| f8_detached_bridge | dd131029a26e3497 | `python -B bench/g7/faults/check.py --only f8` | runtime:g7_r10_join_return:llvm (runtime_signal_or_wrong_output) | detected |
| f9_mutable_readonly | 6256d0a6f4c79e86 | `python -B bench/g7/faults/check.py --only f9` | artifact:mutable_attributes:llvm (artifact_assertion) | detected |
| f10_safe_body | daf474b93220ad06 | `python -B bench/g7/faults/check.py --only f10` | artifact:safe_routing:llvm (artifact_assertion) | detected |

Full baseline/fault commands, outputs, artifact evidence, patch hashes and exit codes: `../results/faults.json`.
Diagnostic regressions detect a missing static rule even if a later proof still rejects the program; they are not claimed as wrong acceptance.
f8 detaches native workers: only the disposable subprocess executes the faulty bridge; no faulty code is loaded into this runner.
A runtime signal is evidence of this lifetime fault, not a successful semantic result. Its scheduling is nondeterministic; a deterministic gated lifetime regression remains desirable.
