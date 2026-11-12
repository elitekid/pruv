# G5 compiler fault injections (G5_SPEC 14.5)

Each patch was applied alone to a disposable copy of the working tree (Python compiler `pruvc/`), the detecting
command was run, and the patch was reverted (the copy was checked identical to `pruvc/` afterwards).
Apply with `patch -p1 < bench/g5/faults/NAME.diff` from the repository root of a disposable copy.

| Fault | Patch (sha256, first 16) | Command | Detecting tests |
|---|---|---|---|
| f1 disabled exclusivity (`check.py` inout_alias) | `f1_exclusivity.diff` eeec29091e0c8b90 | `tests/run_all.py --compiler py --backend rust --only g5_reject` | 60/68: g5_alias_two_marked, g5_alias_marked_and_plain, g5_alias_len, g5_alias_nested_call (no-verify and trust-callers rows) accepted |
| f2 old(a) bound to current contents (`verify.py` call) | `f2_old_current.diff` 15baf4b5d029ade2 | `tests/run_all.py --compiler py --backend rust --only g5_proof` | 19/25: p04_generic_exchange, p07_old_across_calls, p13_loop_calls_old (default and infer) no longer verify |
| f3 omitted call havoc (`verify.py` inout_finals keeps the pre-call array) | `f3_call_havoc.diff` 18b28bf3f981e85d | same as f2 | 22/25: g5p_loop_forgotten_write, g5p_refine_not_preserved, g5p_return_call_refine wrongly verify |
| f4 omitted loop call-write collection (`verify.py` loop `calls = set()`) | `f4_loop_callwrites.diff` adeb7d03cfa47e63 | same as f2 | 24/25: g5p_loop_forgotten_post wrongly verifies |
| f5 stale return-parameter overlay (inout parameters overlaid with entry values) | `f5_stale_overlay.diff` 9115d1b8cd7749a7 | same as f2 | 5/25: p01_i64_store_frame, p02_u8_store_domain, p03_bool_store_frame, p04_generic_exchange, ... no longer verify |
| f6 readonly retained on the inout LLVM pointer (`llvmgen.py` sig_text) | `f6_readonly.diff` 28c22a7ad35753df | `sh bench/g5/faults/check_attr.sh` (direct attribute check) | clean: PASS (`ptr noalias nocapture %p.a.a`); with the fault: `FAIL readonly on inout pointer`, exit 1 |

The g5_proof group carries the --infer rows of the proof-reject roots; their default-mode rows are must_reject rows.
`check_attr.sh` compiles `examples/g5_reverse.pruv` with the llvm backend and inspects the definition of `swap_at`.
