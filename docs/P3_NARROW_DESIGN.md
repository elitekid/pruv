# P3-N1 design: storage width narrowing of refined i64 arrays

Motivation: sudoku peak RSS is 1.08-1.10 of matched Rust (RESULTS.md 118) because its `[i64 | 0..=728]` tables are
stored as 8-byte elements while the matched Rust uses `u16`. This batch stores refined i64 arrays in the narrowest
integer that holds the refinement range. Language semantics, type compatibility and the verifier do not change.
Paths: `core/` means `pruvc-rs/crates/pruv-core/src/`. Line numbers are from the design read (2026-11-15).

## Decisions

1. **Narrow verified storage only; logical values stay i64.** Pick the smallest of u8/i8/u16/i16/u32/i32 covering
   the component's whole range (unsigned when the lower bound is >= 0), else i64. Arithmetic, scalars, indices and
   lengths stay i64; stores cast to the storage type, every load widens to i64 at once.
   - Rust source: `Vec<i64>`/`&[i64]` is hardcoded in `pruvc/codegen.py:rty:379` and `core/emit_common.rs:rty_name:103`;
     alloc/index/store in `codegen.py:Gen.e:1834`, `Gen.stmt:1586` and `core/codegen.rs:Gen::e:2645`, `Gen::stmt:2256`.
     `.to_vec()`/`.truncate()` already follow the element type.
   - LLVM: `pruvc/llvmgen.py:elem_ty:117`, `FnGen.index_ptr:1302`, `ev:1409`, `stmt:1030`, `ev_call:1508`;
     `core/llvmgen.rs:elem_ty:167`, `index_ptr:2116`, `ev:2315` (Index), `stmt:1881` (IndexAssign),
     `ev_call_inner:2457` (alloc). Storage-width GEP/load/store, `trunc` on store, `sext`/`zext` on load.
   - `len` stays an element count; copy and (movable) `return truncate` keep storage and layout.
   - Runtime (`pruvc/runtime.c`): keep the i64 helpers `pruv_alloc`/`pruv_copy`/`pruv_free`; use
     `pruv_copy_v2`/`pruv_free_v2`/`pruv_shrink_v2` with the real element size and alignment; add `(2,2)` to
     `pruv_layout_ok` and one narrow allocate-and-fill helper on `pruv_raw_alloc_v2` (keep the zero-fill path).
   - `load_be`/`store_be` stay `[u8]` operations, untouched.
2. **One representation per connected array flow; type compatibility unchanged.** Refinements are not part of type
   identity (`pruvc/vast.py:Type._key:23`, `core/gtype.rs:GType::eq:35`), so `[i64 | 0..=8]`, `[i64 | 0..=728]` and
   `[i64]` can flow into each other. After monomorphization build a deterministic storage side table keyed by
   bindings, parameter/result positions and array expressions. Connect argument/formal, return/call result,
   init/reassignment and copy/truncate source/result (recursion and all callers of a specialization included). A
   component's range is the union of its declared ranges; an allocation takes its consumer's storage. An unrefined
   declaration, unresolved flow, aggregate field/payload, external boundary or i64-array `inout` pins the component to
   i64. No conversion buffers, no new errors.
3. **Boundaries stay i64.** Host-exported parameters/results (`codegen.py:Gen.private:825`, `Gen.fn:832`,
   `Gen.entry:932`; `core/codegen.rs:private:718`, `func:885`, `entry:1052`; LLVM `is_host_abi_fn`, `llvmgen.py:3176`,
   `core/llvmgen.rs:4326`), bindings and ABI (`llvmgen.py:abi_of`, `gen_bindings`; `core/abi.rs`, `core/bindings.rs`),
   foreign adapters (`foreign_shim.py:_trusted_adapter`, `core/foreign_shim.rs:trusted_adapter`), and array fields of
   structs/enums. Private helpers such as sudoku `solve` are not pinned by having a signature.
4. **No verifier change.** Refined init/reassignment, element stores (`elem_refine`) and loops already get range
   obligations (`refine.py:_Expander.block:257`, `core/refine.rs:Expander::block:437`; proved in
   `verify.py:Verifier.exec:2075`, `pruv-proof/src/symbolic.rs:Verifier::exec:3000`). Exception: an `inout` body
   starts with an empty local-refinement scope (`refine.py:315`, `refine.rs:546`) and the caller checks only the
   state after the call (`post_refine`), so a callee may store an out-of-range value temporarily; hence decision 2
   pins inout. Under `--no-verify` the optimization is off. Runtime contract readers must widen narrowed loads
   (`codegen.py:Gen.c:1134`, `Gen.cquant:1294`; `core/codegen.rs:c:1329`, `cquant:1652`; LLVM `cev`, `csorted` in
   both compilers: widen to i128 for contracts, i64 for sorted checks).
5. **Python and Rust together, deterministic emission.** Both compilers run the same storage analysis after
   specialization and emit helpers in a fixed order. Generated-source parity is checked by
   `tests/diff_compilers.py` (`compare_files`, `run_pair`); `tests/run_all.py --compare-rows` compares row sets only.
   bench/perf is not in the default differential cases, so affected programs are compared explicitly.
6. **Tests.** New `tests/runtime/p3_n1_storage.{pruv,rs,json}` (verified narrowing) and
   `tests/runtime/p3_n1_noverify.{pruv,rs,json}` (unchanged i64 under `--no-verify`), with generated-code and
   binding substring checks, not only outputs. Existing rejections (`refine_elem_store`, `refine_copy_reassign`,
   `g5p_refine_not_preserved`) cover the proof side; no new rejection rule.
7. **Expected effect (declaration estimates, to be measured).** sudoku: rows/cols -> u16, nr/grid -> u8, cr -> i8,
   cc -> u16, 51,192 -> 12,312 bytes. brainfuck: tape and grow -> i32. nqueen: `a` -> i8. bedcov: bs/be/sx -> u32,
   sk/sw -> u8 (about 7.6 MiB less); `a` stays i64 (inout). fannkuch, binarytrees, revcomp, primes, base64 unchanged.
   Extension on load can cost time in hot loops (brainfuck most at risk); measure under PERF_SPEC (time and RSS
   <= 1.05). The heap-vs-stack part of the sudoku gap may remain for a later stack-array batch.

## Files to change

- Python: new `pruvc/storage.py` (`plan_storage`, range-to-layout); `pruvc/codegen.py` (`rty`/`Gen.rt`, `fn`,
  `entry`, `stmt`, `e`, `c`, helpers, `gen_rust_ex`); `pruvc/llvmgen.py` (`gen_llvm`, `V`/`Slot`, slot load/store,
  param/result propagation, `index_ptr`, `stmt`, `ev`, `ev_call`, `free_val`, contract envs, `cev`, `csorted`,
  runtime declarations).
- Rust: new `core/storage.rs` (registered in `core/lib.rs`); storage-aware spelling in `core/emit_common.rs`;
  `core/codegen.rs` and `core/llvmgen.rs` counterparts of the Python changes.
- Runtime: `pruvc/runtime.c` (`pruv_layout_ok`, narrow alloc/fill helper).
- Unchanged: checker, refinement expansion, verifier, monomorphizer, foreign shims, ABI layouts.

## Tests

- Verified kernel: all six widths at their signed/unsigned bounds, i64 fallback, nonzero fills, sign extension of
  negatives, u32 values above 2^31-1, arithmetic after loads, mixed-range private calls, copy, truncate, empty
  results, allocation balance; wide fallback for unrefined flows, struct fields, generic `[T]`, exported
  inputs/results and inout.
- Contract readers (including sorted checks) widen correctly.
- No-verify kernel: store 128 into an annotated -128..=127 array, observe 128, i64 storage asserted.
- Python/Rust differential comparison of the fixtures and the four affected bench programs.

## Risks

- A missed flow or lost storage metadata gives wrong strides, sign extension or allocator layout; anything unknown
  must fall back to i64.
- Conservative pinning misses some cases (bedcov's inout array); no specialization by width.
