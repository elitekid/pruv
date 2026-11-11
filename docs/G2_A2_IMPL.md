# G2 A2 Implementation Spec (u8 proof) — shared by both implementations

This spec pins down how the Python implementation (`pruvc/`) and the Rust implementation (`pruvc-rs/`) emit **the same SMT, the same proof-obligation order, and the same wording**. Basis: `docs/G2_SPEC.md` §0.0 decisions 2, 4, 8, 16, and §4.3.

## 1. Element domain predicate `u8_dom(arr)`

For a symbolic array `arr` whose element type is U8 (array term `A`, length `n`):

```
ForAll([k], Implies(And(k >= 0, k < n), And(Select(A, k) >= 0, Select(A, k) <= 255)))
```

- The bound variable `k` is an integer constant with the fixed name **`elem!k`**. It **does not touch** the counter `s.k` / `self.k`.
- Keep the And argument order, the `>=`/`<=` directions, and the constants 0 and 255 exactly as written above. No patterns.
- For I64 arrays (and any other element type), nothing is created → existing SMT bytes are unchanged.

## 2. The three places that insert the domain (decision 2) — insert **right after** the length assumption

1. Function-entry parameters: for an array, on the line after `pc.append(And(n >= 0, n <= MAX_LEN))`; if it is U8, add `pc.append(u8_dom(v))`.
2. User-function call results: after `assume(st, g, And(res.n >= 0, res.n <= MAX_LEN))`; if it is U8, add `assume(st, g, u8_dom(res))`. (Before the ensures assumptions.)
3. The array branch of loop havoc: after `h.pc.append(And(nv.n >= 0, nv.n <= MAX_LEN))`; if it is U8, add `h.pc.append(u8_dom(nv))`.

Anywhere else (alloc, copy, rebinding, after a store, element reads in code) the domain assumption is **not inserted**. The `in_range(Select)` assumption for an element read `a[i]` in code stays as it is now (i64 range).

## 3. The `elem_range` proof obligation

Use the helper `prove(st, g, ob, node, code, what, key_extra=None, cand=None)` (Rs `prove_core(.., node, code, what, key_extra)`) as is, with **no cand** (None) — so it is skipped during the `--infer` search and is decided only in the final full verification (decision 4).

- Obligation expression: `And(v >= 0, v <= 255)` (v is the already-evaluated value term).
- key_extra: none (None).

### 3.1 alloc(n, v)

The result element type is taken from the type the checker attached to the Call node (`e.ty`; Py `Call.ty`, Rs `Call.ty`): if the type name is `"array_u8"` it is U8; anything else is I64 as now.

Order: existing `alloc_negative` obligation → (if U8) `elem_range` obligation → existing `s.k += 1` → constant-array creation (element type = the one obtained above).

- node = the alloc Call expression (the same node as for `alloc_negative`).
- what = `u8 element range 0..=255 for the alloc fill value`

### 3.2 Element store `a[i] = v`

Order: evaluate index → evaluate value → existing `index_oob` → (if the array element type is U8) `elem_range` → existing refinement `refinement_assign` → Store.

- node = the store statement (the same node as for `index_oob`).
- what = `u8 element range 0..=255 for NAME[...] =` (NAME is the name of the variable being stored into, the same value as `%s` in the existing index_oob wording)

### 3.3 FIX table

Add an `elem_range` key (in Py, the `FIX` dictionary right after `contract_domain`; in Rs, the same spot in `fix_for`). Wording exactly as follows:

```
store or fill only values in 0..=255 into a [u8] array: bound the value with requires, an if, or a loop invariant
```

The completed diagnostic message keeps the existing form, `cannot prove <what> in <fn>`.

## 4. Guards (decision 16)

- Remove the verify guard: delete the `g2_unimplemented_error(prog, "verify")` block at the start of `verify_program` in Py `verify.py`, and the same block at the start of `verify_program_opts` in Rs `pruv-proof/src/lib.rs`. (`[bool]` is still rejected by the parser, so it never reaches the proof layer.)
- The driver codegen guard runs **even after verify succeeds**: in Py `pruvc/pruvc.py`, remove the `if not verify:` condition so it runs unconditionally; in Rs `pruvc-rs/crates/pruvc/src/driver.rs`, remove the `if !a.verify { .. }` condition so it runs unconditionally. The position stays the same (after the verify block, before the generator). Change the comment to mean "G2: even after verify, reject array types for which there is no code-generation layer yet (until A3·A4)".
- Do not touch the generators' own guards (`codegen.py`, `llvmgen.py`, `codegen.rs`, `llvmgen.rs`).

## 5. `--infer` candidate filter (decision 4)

- Build an array-name → element-type table from the function: among the parameter types and the `Let` declaration types in the body (including nested blocks), those that are arrays. Type name `"array"` → i64, `"array_u8"` → u8, `"array_bool"` → bool.
- Kind 5 (where it loops over `ranges` and builds `lo <= b[k] <= hi` for the target array `b`): use each item of `ranges` **only when the element type of that range's source array equals the element type of `b`**. If the type of the source array or of `b` cannot be found in the table, do not use it. For inputs that use only i64 today, the result must stay the same (same order, same candidates).
- Candidates that read or write elements (kinds 5·6·7·8·9·10·11·12·13·14): do not generate the candidate if the candidate expression reads an element (Index) of an **array whose element type is bool**, or if the target array is bool. (Today `[bool]` is blocked in the parser, so this never actually triggers. Candidates for i64 and u8 inputs must not change.)
- Do not newly add the implicit u8 range 0..=255 to `ranges` (do not add new candidates).
- The ban on function calls in candidates (other than len) stays as is.
