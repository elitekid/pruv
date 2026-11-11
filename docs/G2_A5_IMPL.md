# G2 A5 Implementation Spec: `[bool]` Arrays, All Layers

Status: A5 batch implementation contract (written by main). Both implementations (Python `pruvc/`, Rust `pruvc-rs/crates/`) emit the text below **byte for byte**. Basis: `docs/G2_SPEC.md` §0.0 decisions 4, 5, 6, 7, 15, 16, and §2.1, §3.1, §4.2, §5.1, §5.2, §5.3, §5.4. It models the u8 implementation of the A2–A4 specs (`docs/G2_A2_IMPL.md`, `G2_A3_IMPL.md`, `G2_A4_IMPL.md`), and whatever is not written below is the same as the u8 path.

## 0. Scope and decisions

1. A5 opens `[bool]` (internal name `array_bool`, Py `vast.ARRAY_BOOL`) in the frontend, proof, Rust source backend, LLVM backend, `--rust-bindings`, and runtime, all of them. At the end of the batch, the skip of `g2_unimplemented_error` becomes `("array_u8", "array_bool")` (Rs `&["array_u8", "array_bool"]`). All six call sites (Py `pruvc.py`, `codegen.py`, `llvmgen.py`; Rs `driver.rs`, `codegen.rs`, `llvmgen.rs`) are changed the same way. The guard function itself is left for batch B (str).
2. **The SMT, Rust source, IR, and bindings of existing programs that use only `[i64]` and `[u8]` do not change by a single byte.** The bool prelude, declarations, and struct are attached only when the program uses `[bool]` (`uses_array_type(prog, "array_bool")`).
3. A bool array has neither an `elem_range` proof obligation nor an element domain assumption (the value range is guaranteed by the SMT sort).
4. Memory representation: 1 byte per element (`i8`, Rust `bool`), value 0/1. No bit packing. Size and alignment (1,1).
5. At raw ABI (`pruv_abi_<f>`) entry, a runtime function checks that every byte of a `[bool]` argument is 0/1. This check runs before the call to `__pruv_entry` (including the requires check), so it always runs regardless of `--trust-callers`. Since the type of `&[bool]` in the typed Rust binding guarantees 0/1 (G2_SPEC 5.4), the binding calls `pruv_abi_<f>__typed`, which only omits the check line (audit must-fix 2: removes a redundant O(n) check on every call; §4.2, §4.4).

## 1. Frontend (Py `vparser.py`, `check.py`, `refine.py` / Rs `parser.rs`, `check.rs`, `refine.rs`)

- Allowed array element names: `i64`, `u8`, `bool`. If `bool`, the type is `ARRAY_BOOL` / `"array_bool"`.
- The error for other element names (currently `only [i64] and [u8] arrays exist` / fix `use [i64] or [u8]`) is changed to the following text. A name starting with an uppercase letter is `unsupported_type` as now.
  - msg: `only [i64], [u8] and [bool] arrays exist`
  - fix: `use [i64], [u8] or [bool]`
- `[bool | L..=U ...]` parses under the current grammar and is rejected in refine validation (`_validate` / `validate`). The position is **immediately after the scalar `refinement_base` check** (before other range checks):
  - condition: `shape == "array"` and `base == "bool"` and `lo` is present.
  - stage/code: `type` / `refinement_base`
  - msg: `a refinement \`| L..=U\` does not apply to [bool]; only its length can be bounded`
  - fix: `remove \`| L..=U\`; keep \`; <=N\` if a length bound is needed`
  - (The \` inside the text is a literal backtick. The existing wording for scalars is not changed.)
- `[bool; <=N]` is allowed (length refinement only, the existing length-refinement expansion as is).
- Type checking:
  - Expression type of `a[i]`: `bool` if the array element is bool, otherwise `i64` as now.
  - Expected type of `x` in `NAME[i] = x`: `bool` if the target array element is bool, otherwise `i64`.
  - `alloc(n, v)`: if the hint type of decision 6 is `array_bool`, the expected type of `v` is `bool`, otherwise `i64`. With no hint, `[i64]` as now (so `len(alloc(4, false))` is `type_mismatch`).
  - Error text uses the existing `type_mismatch` wording of `expect` as is (no new wording).
  - The `sum` body expects `i64` as now (a bool body → `type_mismatch`), while `count(k in ..: a[k])` is allowed. Whole-array `==`/`!=` is forbidden as now, while comparing elements with each other is allowed.
- `tests/parse_edge/array_only_i64.pruv` is changed by main to `[i32]` (the worker does not touch it).

## 2. Proof (Py `verify.py`, `infer.py` / Rs `pruv-proof`'s `symbolic.rs`, `obligation.rs`, `infer.rs`)

### 2.1 Symbolic execution

- Bool arrays from parameters, call results, and havoc are already built by `fresh` as `Array(Int, Bool)` (no change). The U8-specific domain assumption (`u8_dom`) is not put on bool (the current code looks only at U8, so no change).
- Code and contract read `a[i]` (Py Index, Rs `symbolic.rs` Index): the index obligation and `contract_domain` handling are as now. After that,
  - if it is a bool array, **do not add** the `in_range(v)` assumption, and the result is a bool value (Py: the z3 Bool expression as is, Rs: `Val::Bool(select result as_bool)`).
  - otherwise as now (`in_range` assumption then Int, Rs `Val::Int`).
- `alloc(n, v)`: if the Call node type is `array_bool`, the element is `BOOL`/`Elem::Bool`, and the constant array is `K(Int, v)` (v is Bool). The obligation is only `alloc_negative` as now (no elem_range). The order and fresh numbering are the same as the u8/i64 path.
- `NAME[i] = x`: after `index_oob`, `Store(a, i, x)` (x is Bool). `elem_range` and `refinement_assign` do not exist for bool (there is no bool element refinement, so `elem_refine` does not arise either).
- `copy`, rebinding, and call results preserve element information as is (already done).
- SMT names and obligation order follow the same rules as the u8 path. The 231 existing input SMTs are byte-unchanged.

### 2.2 Counterexample JSON

- An array counterexample entry is currently `{"len": n, "first": [..]}` (at most the first 8). If the element is bool, each item of `first` is emitted as JSON `true`/`false`.
  - Py: `z3.is_true(m.eval(z3.Select(v.a, i), model_completion=True))` → Python `True/False` → JSON `true/false`.
  - Rs: `Json::Bool(..)` (true if the z3 `model_completion=true` evaluation result is true).
- Integer arrays are as now.
- Whether `first` actually appears in a counterexample for a bool array of positive length is tested by a sample (§5 `cex_contains`).

### 2.3 `--infer`

- Change the element-type table **from a flat name-based table to a table keyed by loop position** (audit recommendation). Py `_elem_types(f)` → `_elem_types(f, w)`, Rs corresponding to `elem_types`.
  - Starting environment: parameters (if an array, the element name `"i64"|"u8"|"bool"`).
  - Walk the statement list from the front, updating the environment: if `Let name: T` has an array type, `env[name] = element name`; **if it is not an array, remove name from `env`** (shadowing). When the target loop `w` (the same node object; in Rs the same way of identifying position) is reached, the environment at that moment is that loop's table.
  - The then/else of `If`, the `While` body, and each arm of `Match` are entered with a **copied environment**, and on leaving, the outer environment is used as is (an inner let does not leak out). A Match arm binder is not an array, so remove that name from env.
  - A let inside a loop body is not visible at the loop head, so it is not put in the table.
- The two places that currently use this table (the bool element read filter `kind >= 5`, and the same-element-type check of kind 5) use it as is. The filter position and order (sort, deduplication, before truncation) are as now.
- Candidates and results for existing inputs must not change (keep `tests/inference/run.py --regress` passing for both implementations; baseline after A5 is 271/271).

## 3. Rust source backend (Py `codegen.py` / Rs `codegen.rs`, `emit_common.rs`)

- `rty`: `array_bool` → parameter `&[bool]`, local/return `::std::vec::Vec<bool>`. (Do not rely on the `other => other.to_string()` fallback in Rs `emit_common.rs`; put an explicit branch.)
- Element discrimination looks at `array_bool` in the same places as u8 (Py `s.vt`/`e.array.ty`/`e.ty`, Rs `self.vars`/`elem_of`).
- Prelude: in safe mode `SAFE_PRELUDE`, (if u8 is used) `SAFE_PRELUDE_U8`, (if bool is used) `SAFE_PRELUDE_BOOL`, in that order. If there is requires and it is not trust, `CONTRACT_PRELUDE`, (u8) `CONTRACT_PRELUDE_U8`, (bool) `CONTRACT_PRELUDE_BOOL`, then the contract types.

`SAFE_PRELUDE_BOOL` (one newline after the last line, same shape as the u8 one):
```
#[allow(dead_code)]
#[inline]
fn pruv_get_bool(a: &[bool], i: i64) -> bool { a[pruv_idx(i, a.len())] }
#[allow(dead_code)]
#[inline]
fn pruv_set_bool(a: &mut [bool], i: i64, v: bool) { let k = pruv_idx(i, a.len()); a[k] = v; }
#[allow(dead_code)]
#[inline]
fn pruv_alloc_bool(n: i64, v: bool) -> ::std::vec::Vec<bool> { if n < 0 || n > (1i64 << 40) { pruv_ovf("alloc length outside 0..2^40") } vec![v; n as usize] }
```

`CONTRACT_PRELUDE_BOOL`:
```
#[allow(dead_code)]
#[inline]
fn pruv_cidx_bool(a: &[bool], i: i128) -> bool { if i >= 0 && i < (a.len() as i128) { a[i as usize] } else { pruv_ud("array index out of range") } }
```

Expression and statement text (`I`, `X`, `N`, `V` are sub-expressions, `A` is an array expression, `R` is the current `arr_ref`, `C` is the current `carr`, `CI` is a contract index):
- Store, proof mode: `{ let pruv_i: i64 = I; let pruv_x: bool = X; unsafe { *NAME.get_unchecked_mut(pruv_i as usize) = pruv_x; } }`
- Store, safe mode: `{ let pruv_i: i64 = I; let pruv_x: bool = X; pruv_set_bool(&mut NAME, pruv_i, pruv_x); }`
- Read, proof mode: `(unsafe { *A.get_unchecked((I) as usize) })` (same text as the i64 path)
- Read, safe mode: `pruv_get_bool(R, I)`
- alloc, proof mode: `{ let pruv_n: i64 = N; let pruv_v: bool = V; vec![pruv_v; pruv_n as usize] }`
- alloc, safe mode: `pruv_alloc_bool(N, V)`
- Contract read: `pruv_cidx_bool(C, CI)`
- copy, len, call arguments: as now.

## 4. LLVM, bindings, runtime

### 4.1 Element information (Py `llvmgen.py` / Rs `llvmgen.rs`)

- `lty("array_bool") = ARR`, `vkind("array_bool") = arr` (same as u8; do not rely on the fallback).
- `elem_ty(t)`: `array_u8` → `ARRAY_U8`, `array_bool` → `ARRAY_BOOL`, otherwise `None`. Rs also carries `Some("array_bool")` in `Slot.ty`/`V.ty` (at every place that carries u8: new_slot/load, bind_params, bind_contract_params, alloc, copy, call result).
- New query "byte array" (Py `is_bytes(v)`, Rs equivalent) = the ty name is `array_u8` or `array_bool`. **The GEP element type `i8`, copy `pruv_copy_v2(.., 1, 1)`, and free `pruv_free_v2(.., 1, 1)` apply to all byte arrays.** `is_u8` is u8 only (value range check, zext widening).

### 4.2 IR text (numbers follow `s.op` order; call in the order below)

- Code read `a[i]` (bool): after `index_ptr`
  ```
  %x = load i8, ptr %g
  %b = icmp ne i8 %x, 0
  ```
  The result is `V("i1", %b)`.
- Store `NAME[i] = x` (bool slot): evaluate index → value → load slot → after `index_ptr`
  ```
  %z = zext i1 X to i8
  store i8 %z, ptr %g
  ```
  No value range check.
- `alloc(n, v)` (Call type `array_bool`): evaluate cnt and v as now, after the safe-mode length check
  ```
  %z = zext i1 V to i64
  %p = call ptr @pruv_alloc_u8(i64 CNT, i64 %z)
  ```
  The result is `V("arr", %p, CNT, ARRAY_BOOL)`.
- `copy` and free: v2 (1,1) as in §4.1, and the ty of the resulting V is the argument's ty.
- Contract read (`cev` Index, bool): after the current guard (`zext`, `icmp ult i128`, undefined) and `trunc i128 .. to i64`
  ```
  %g = getelementptr inbounds i8, ptr A, i64 II
  %x = load i8, ptr %g
  %b = icmp ne i8 %x, 0
  ```
  The result is `V("i1", %b)`.
- `csorted` does not arise for bool (`<=` is not possible) — no change.
- Raw entry `abi_of`: if a parameter is `[bool]`, put the following one line in `pre` at that parameter's turn (the argument text `ptr %a.Q.a, i64 %a.Q.n` is as now):
  ```
  call void @pruv_check_bool(ptr %a.Q.a, i64 %a.Q.n)
  ```
  If there is at least one `[bool]` parameter, emit right after that `define` one blank line and one more `define` whose name is `@pruv_abi_<f>__typed` and whose signature and body are the same except that the lines starting with `  call void @pruv_check_bool(` are omitted.
- Declarations: after `DECLS`, `DECLS_U8` (if u8 **or bool** is used), then `DECLS_BOOL` (if bool is used).
  ```
  DECLS_BOOL = "declare void @pruv_check_bool(ptr nocapture readonly, i64) nounwind\n"
  ```

### 4.3 Runtime `pruvc/runtime.c`

- Add one line of description for each of the two functions to the header comment. Below the `pruv_panic_elem` prototype, the prototype `_Noreturn void pruv_panic_repr(int64_t v, const char *what);`.
- Immediately after the `pruv_panic_elem` definition:
  ```c
  _Noreturn void pruv_panic_repr(int64_t v, const char *what) {
      PRUV_HOST_FLUSH();
      fflush(stdout);
      fprintf(stderr, "pruv: invalid representation: %" PRId64 " (%s)\n", v, what);
      exit(101);
  }
  ```
- After the v2 functions (outside `#ifdef`, common to all variants):
  ```c
  void pruv_check_bool(const uint8_t *data, int64_t len) {
      if (data == NULL || len <= 0)
          return;
      for (int64_t k = 0; k < len; k++)
          if (data[k] > 1)
              pruv_panic_repr((int64_t)data[k], "bool 0..=1");
  }
  ```
- `tests/abi/runtime_v1.c` is not modified.

### 4.4 Bindings (`gen_bindings` of both implementations, Py `llvmgen.py` / Rs `bindings.rs`)

- `rust_ty`: `array_bool` → `&[bool]` / `::std::vec::Vec<bool>`.
- Struct: after the `Pruv__ArrayU8` line, if bool is used, an `ALLOW` line and `#[repr(C)]\npub struct Pruv__ArrayBool { pub data: *mut u8, pub len: i64 }`.
- extern arguments: `[bool]` → `*const u8`, `i64`. Return out: `*mut Pruv__ArrayBool`.
- extern block: after all `pruv_abi_*` lines and before the marker line, if there is at least one function that returns `[bool]`, `    fn pruv_check_bool(p0: *const u8, p1: i64);`.
- A function that has a `[bool]` parameter uses `pruv_abi_<f>__typed` as its extern declaration and call name (a function with only a `[bool]` return stays `pruv_abi_<f>`).
- Public function argument passing: `[bool]` → `NAME.as_ptr() as *const u8`, `NAME.len() as i64`.
- `[bool]` return body (in the place of the current 3 lines of array return):
  ```
  let mut pruv__out = Pruv__ArrayBool { data: ::std::ptr::null_mut(), len: 0 };
  pruv_abi_F(.., &mut pruv__out);
  pruv_check_bool(pruv__out.data, pruv__out.len);
  if pruv__out.len > 0 { ::std::vec::Vec::from_raw_parts(pruv__out.data as *mut bool, pruv__out.len as usize, pruv__out.len as usize) } else { ::std::vec::Vec::new() }
  ```
  (It is taken over as a Rust bool after the check. The marker reference line is attached to array-returning functions as now.)

## 5. Samples and tests (test owner)

- must_reject (pairs of `.pruv`+`.json`): `g2a_bool_fill` (type/type_mismatch), `g2a_bool_store` (type/type_mismatch), `g2a_bool_read_int` (type/type_mismatch), `g2a_bool_refine` (type/refinement_base), `g2a_sum_bool` (type/type_mismatch), `g2a_mixed_bool` (passing a `[u8]` to a `[bool]` parameter, type/type_mismatch), `g2a_bool_alloc_nohint` (`len(alloc(4, false))`, type/type_mismatch), `g2a_infer_bool` (flags `--infer`, a false assert after a loop that runs over a bool array and an integer array together → the expected code at the verify stage; not an internal error), `g2a_bool_cex` (a false ensures/assert with a positive-length bool array parameter → verify, and check with `cex_contains` that bool elements appear in the counterexample JSON).
- Add an optional key `cex_contains` (a list of strings: all must appear in the diagnostic JSON output emitted by the compiler) to the must_reject json of `tests/run_all.py`. Both compilers are checked with the same key.
- examples (`examples/g2a_bool_*.pruv`, passing verification): bool construction (alloc, store, read, return), bool count (a loop using `count(k in 0..len(a): a[k])` in ensures), store after a parameter, call result, or copy, `[bool; <=N]` length refinement, and under `--infer` a loop in which sibling blocks use the same name with different array types (the case that needs the position-based table of §2.3; this sample should also run with `--infer`).
- runtime (`tests/runtime/g2a_rt_bool_*`, `.pruv`+`.json`+`.rs`): construction, store, read, and returned values; copy independence; safe-mode index range panic; reading a bool element inside requires (including `--trust-callers` via `flags_matrix`); allocation/free balance (`alloc_balance`, a sample that does not return the array to Rust); IR text checks (`llvm_fn_contains`: `zext i1`, `store i8`, `icmp ne i8`, `@pruv_free_v2(`, `@pruv_copy_v2(`).
- Raw representation check `tests/abi/check_bool_repr.py` (new file, in the manner of `check_runtime_v2.py`): with the IR emitted by both compilers (Py and Rs) + the ordinary runtime + a C caller, call `pruv_abi_<f>` directly. Cases: bytes 0/1 → normal output; byte 2 → exit 101 and stderr `pruv: invalid representation: 2 (bool 0..=1)`; the same result in a `--trust-callers` build; given an input where requires is false together with byte 2, the representation error comes first. Add a stage `abi_bool` to `tests/m3_all.py`.
- `tests/abi/gen/g2a_bool_ret.pruv` (one-line signature, `[bool]` argument and return, intermediate copy) + an entry in `tests/abi/winci/calls.json`.
