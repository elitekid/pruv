# G2 Design: Element-Storage-Typed Arrays and UTF-8 Strings

Status: **Finalized (2026-11-11)**; draft → one design debate → finalized by the main session. Implementation starts with the next batch. This document is the implementation contract. The test counts and performance criteria are goals still to be met, not measurement results.

**§0.0 (finalized decisions) takes precedence over the body from §0 onward.** The body is left as the original draft; wherever it differs from §0.0, follow §0.0.

## 0.0 Finalized decisions (reflecting the design debate)

Of the 15 findings raised in the debate (9 required, 6 recommended), we checked the code evidence and decided as follows.

1. **The first implementation covers only `[u8]` and `[bool]` as element types.** `[i32]` adds only the execution burden of sign extension and 4-byte layout, while the new proof-side risks (narrow ranges, a separate sort) are already fully exposed by u8 and bool. i32 is deferred to a separate batch (A6) after G2a. The G2a completion record is written as "u8·bool".
2. **Fix where the domain is introduced (soundness).** The element range of a narrow array, `forall k in 0..n: 0 <= A[k] <= 255`, is assumed **only where values come in from outside**: function entry parameters, results of user function calls, and loop havoc. `alloc` becomes a constant array after proving `elem_range` of the initial value; `copy` and rebinding keep the original term as is; an element store becomes a `Store` after proving `elem_range`. **The range assumption is not re-introduced after a store or rebinding** (this blocks the path where a wrongly stored value contradicts the assumption and makes later obligations vacuously true). For the same reason, **the assumption made when code reads a narrow-array element stays at the i64 range as it is now and is not narrowed to 0..255** (`in_range(Select)` in the array read of `pruvc/verify.py`, and the same spot in Rust `symbolic.rs`). Add a rejection sample that reads after a wrong store. The byte range 0..255 of `str` is likewise placed only at the same three points (entry, call result, havoc) and in the results of literals, `copy`, and `substr`.
3. **Keep the contract-domain order as it is now.** Even when the range is known, `a[0]` of an empty array is undefined. Do not change the current order of checking requires and then assuming (near line 1034 of `pruvc/verify.py`); add samples for an empty-array read, a read after a length guard, and a short-circuited read.
4. **Relationship with `--infer` (required gate).** Since the Houdini search skips obligations other than the candidates, `elem_range` and `utf8_boundary` are decided **only in the final full verification**. Samples in which a loop exit, return, or call follows a wrong store must be rejected with `--infer` both on and off. The ban on function calls in candidates (other than `len`) is not widened. Put an element-type filter on **every candidate generator that reads array elements** (kinds 5·6·7·8~10·12 (array initial value)·13·14, which read elements through `at_k`·`ranges` — re-check all uses of `at_k`·`ranges` in `pruvc/infer.py` at implementation time). The `ranges` of kind 5 uses only those coming from arrays of the same element type. In G2a, no candidates that read or write bool array elements are generated (left as is, `lo <= b[k]` would arise on a bool array and cause a z3 sort error = internal error; see the kind-5 generator in `pruvc/infer.py`).
5. **A bool array is the SMT `Array(Int, Bool)`.** Change together the value tag of the read result (the Python range assumption; Rust fixes `Val::Int`) and the counterexample JSON (`true/false`). Test that array entries actually appear in the counterexample for a bool array of positive length. `count(k in ..: a[k])` keeps its current meaning, a bool body in `sum` is rejected, and the ban on whole-array `==`/`!=` applies to every array type (comparing elements with each other is allowed).
6. **Decide the element type of `alloc` narrowly.** Do not push expected-type propagation through the whole checker. Only when `alloc(n, v)` appears **immediately to the right of a type-annotated `let`, immediately to the right of a reassignment of that variable, or immediately after `return`** does it use that array type; elsewhere (nested `copy`, function arguments, inside `len(...)`) it stays `[i64]` as before. The `copy(alloc(..))` propagation of §3.2 is not done.
7. **Keep internal type names from leaking into source.** Using the internal names `array_u8` and `array_bool` (and the later `array_i32` and the internal name of `str`) as a source type is rejected (add to must_reject). `u8` can still be used as an ordinary variable name.
8. **Diagnostic names follow the existing ones.** A refinement element-store failure is `refinement_assign` (`elem_refine` in §3.4 is merely an AST metadata name). The "no duplicate diagnostics for derived obligations" of §4.3 is not added as a new rule; existing failure handling is left as is (so that existing traces do not change).
9. **Audit once per implementation batch + one confirmation after the fixes** (replacing "each of G2a/G2b" in §8.5).
10. **Fix the 444 baseline as a list of executed rows.** Not the number of sources: save the list of `run_all` rows (sample · backend · flags · compiler) at A0, and in each batch check that all the same rows ran and passed.
11. **The cross-check gate accepts only `same`.** In the trace cross-check of new G2 samples, `cex_only` and `same_unknown` do not count as passes. The fuzzer reports failure if the number of generated programs that actually use G2 falls short of the goal.
12. **The fuzzing and independent-use numbers (§8.3·§8.4) are the last gate of G2 as a whole.** In each feature batch, only small samples and mutations (store bound ±1, range-guard deletion, boundary ±1) are added first.
13. **The UTF-8 abstraction stays as drafted.** The SMT `str` is an over-approximation that may be any byte sequence, and every `str` entering actual execution is valid UTF-8, so this alone does not produce false proofs. Instead, the G2b audit focuses on (a) a UTF-8 pre-check at every raw entry, (b) agreement between the SMT `boundary` and the runtime boundary decision on valid strings, and (c) the `substr` byte relation. State in the documentation and diagnostics that an SMT counterexample is not guaranteed to be valid UTF-8.
14. **G2b (`str`) starts separately after G2a is closed.** Do not record `[u8]` + an ASCII-range contract as completed string support.
15. **End-criteria adjustment following decision 1.** In the §6.2 rejection samples, move the i32 items (`g2a_i32_low`·`g2a_i32_high`) to A6 and change `g2a_mixed_argument` to `[u8]`↔`[bool]`/`[i64]`. Add the internal-name rejection (`g2a_internal_name`), read after a wrong store (`g2a_store_then_read`), no bool candidates generated (`g2a_infer_bool`), and bool body in `sum` (`g2a_sum_bool`), so the G2a minimum is **28 samples** (26 − 2 i32 + 4 new). `g2a_scalar_i32` stays as is even though i32 is deferred, and its expected code is still `element_storage_type` (scalar i32 is not opened anywhere in G2). The i32 items in the §8.2 examples (negative read, boundary store) and in runtime (read sign extension) move to the A6 end criteria; G2a has examples **6** and runtime **11**. The i32 sign-extension mutation in §8.3 and the "i32 array update" of independent use in §8.4 move to A6, and that slot is replaced by "u8 array update (range proof)". The end criteria of A6 are the items moved there.
16. **Layers not yet implemented reject G2 types with an explicit diagnostic.** After A1, even if `[u8]` passes checking, it must not flow into an internal error (exit 3) or wrong generation under `--no-verify` before the proof and generation layers are ready. The diagnostic is the existing `unsupported_type` (stage is that layer), and the message names the layer not yet implemented. Put a sample in each batch's end criteria in which "the next layer rejects with `unsupported_type`", and turn that sample positive in the batch that implements that layer.
17. **G2 mutations are measured with a dedicated OPS list.** The existing `bench/mutate.py` OPS is not changed (so that it stays comparable with existing baselines such as `mutants9`; this decision replaces the `bench/mutate.py` boundary of draft 7.7). The G2-specific list goes in `bench/g2/mutate_ops.py` (proposed path). Store bound ±1, range-guard deletion, and boundary ±1 go in the G2-specific list, and for each new pass, true/false mutants are judged automatically by a `--no-verify` build + reference tests.

### 0.0.1 Implementation batches (replaces §7)

| Batch | Content | Files to modify (boundary) | End criteria |
|---|---|---|---|
| **A0 Foundation** | With no new syntax, put an element-type field in the symbolic arrays of the existing `[i64]` and preserve it through fresh, alloc, copy, rebinding, Store, call results, and havoc (gather `Arr` construction into one constructor function). A common array query API (`is_array`·`array_elem`, etc.). Also define here the mapping between the internal names of later batches (`array_u8`·`array_bool`) and `Ty`. Export and compare the executed-row list in `run_all`. Fix in the repository the path list of the 231 SMT reference inputs and the comparison command | Py: `pruvc/vast.py`·`typeinfo.py`·`verify.py` / Rs: `pruv-core/src/typeinfo.rs`, `pruv-proof/src/model.rs`·`symbolic.rs`·`samples.rs` (the prototype path builds `Arr {..}` directly) / tests: `tests/run_all.py` | 444 executed-row list saved and kept in both implementations, SMT of the 231 files byte-identical without `--infer`, `--infer` cross-check has the same classification as before, new syntax still rejected |
| **A1 u8 frontend** | `[u8]` (+ refined `[u8 \| L..=U; <=N]`) syntax, type checking, narrow `alloc` type decision (decision 6), internal-name rejection | Py: `vparser.py`·`check.py`·`refine.py` / Rs: `parser.rs`·`check.rs`·`refine.rs` (+`lexer.rs`·`dump.rs` if needed) | u8 parse/type rejection samples match, parse/check dumps identical in both implementations |
| **A2 u8 proof** | Domain introduction (decision 2), `elem_range`, counterexamples, `--infer` gate (decision 4) | Py: `verify.py`·`infer.py` / Rs: `symbolic.rs`·`obligation.rs`·`infer.rs`·`model.rs`·`samples.rs` | verify rejection samples and `--infer` on/off rejection, new traces `same`, existing SMT unchanged |
| **A3 u8 execution** | Generalize runtime size and alignment, and Rust source generation (safe-mode range checks) | Py: `runtime.c`·`codegen.py` / Rs: `codegen.rs`·`emit_common.rs`·`pruvc/src/runtime.rs` | u8 examples and runtime samples pass in both implementations and the rust backend |
| **A4 u8 LLVM·ABI** | LLVM generation, `--rust-bindings` (v2 host helper) | Py: `llvmgen.py` / Rs: `llvmgen.rs`·`abi.rs`·`bindings.rs` | llvm backend passes, IR and bindings byte-identical in both implementations, allocation/free balanced |
| **A5 bool** | All layers of decision 5 (syntax → proof → execution → ABI) | Same files as A1~A4, one worker per layer within the batch | All bool samples, counterexamples `true/false` |
| A6 i32 | (Deferred) sign extension, 4 bytes | Same as above | Items moved by decision 15 (rejection samples `g2a_i32_low/high`, i32 examples 2 · runtime 1, sign-extension mutation, independent-use i32 problem) |
| **B0~B2 str** | String frontend → proof → execution · raw ABI (draft 7.5·7.6 split in two + execution) | Draft 7.5·7.6 | Draft end criteria + decision 13 |
| **Q1·Q2** | Oracle and fuzzing (seeds 41·56·57) → measurement and 6 independent-use problems | Draft 7.7 | §8.3·§8.4 |

For each batch: Python implementation → port to the Rust implementation → cross-check of the two implementations, audit 1 + confirmation 1, RESULTS section · BLUEPRINT line. The result of A0 is recorded as "G2 implementation foundation", not as a "G2 feature".

## 0. Summary of draft decisions (§0.0 takes precedence)

1. **G2a extends the element storage type of arrays.** Add `[u8]`, `[i32]`, and `[bool]` to the existing `[i64]`. Scalar `u8` and `i32` are not added.
2. The read result of `[u8]`·`[i32]` is `i64`, and that of `[bool]` is `bool`. Arithmetic remains i64; there is no narrow-width arithmetic, wrap, or implicit array conversion.
3. Creating and storing into a narrow integer array imposes an **`elem_range` proof obligation**. Under `--no-verify`, the same range is checked at run time before storing.
4. `alloc(n, v)` takes an expected array type. Without an expected type it is `[i64]` as before. `copy` preserves the input type, and `len` returns the number of elements.
5. The existing refinement syntax is allowed for integer arrays. For `[bool]`, only length refinement is allowed. The allowed types of Option/Result and of struct and enum fields are not extended.
6. The SMT representation uses `Array(Int, Int)` for integer arrays and **`Array(Int, Bool)`** for bool arrays. The storage type of an array is also preserved in the symbolic execution state.
7. **G2b adds `str`.** It is a valid UTF-8 byte sequence whose contents are read-only. `len(s)` is the byte count, and `s[i]` is the i64 value of that byte.
8. G2b includes string literals, `copy(s)`, `is_char_boundary(s, i)`, and `substr(s, lo, hi)` with a proven boundary. A substring is copied and owned.
9. The `[u8] → str` conversion and the `utf8(b, lo, hi)` predicate are left to a later stage. They are not introduced by working around `Option<str>`·`Result<str>`.
10. The Rust representation uses `&[T]` for array arguments, `Vec<T>` for locals and returns, `&str` for string arguments, and `String` for locals and returns. The LLVM representation keeps `{ ptr, i64 }` while preserving element type and ownership information separately.
11. The argument order and array-return structure of the existing function ABI are kept. A runtime allocation interface taking size and alignment is added as v2. Unconditional mixing of existing generated bindings with the new runtime is not guaranteed.
12. Every implementation batch is closed in the order **Python implementation → Rust port → cross-check of the two implementations**. Do not record G2 as complete when only G2a is done.

## 1. Scope and non-scope

### 1.1 Scope by stage

| Stage | Included |
|---|---|
| G2a | `[u8]`, `[i32]`, `[bool]`, creation, read, write, copy, return, refinement, proof, both backends, ABI |
| G2b | `str`, literals, byte reads, boundary decisions, copied substrings, UTF-8 input boundary checks |
| Later | Fallible conversion of byte sequences to strings, a general UTF-8 predicate, a string-processing library |

Both G2a and G2b support the function parameter, return, `let`, and `let mut` positions. Array parameters are read-only. Strings cannot have elements modified in any position.

### 1.2 Non-scope

- Scalar `u8`·`i32`, cast syntax, per-width arithmetic, wrap operations.
- Nested arrays, arrays of user types, array literals.
- Struct fields and enum payloads that hold arrays or strings.
- Constructor-type extensions such as `Option<bool>`, `Option<str>`, `Result<str>`.
- `char`, code-point indexing, character counts and grapheme counts, normalization, string concatenation, formatting, and output extensions.
- Returning borrowed substrings, lifetime parameters, array views and slice syntax.
- New templates for automatic invariant inference. Only safe coexistence with the existing `--infer` is in scope this time.

## 2. Syntax

### 2.1 Arrays

```text
ArrayType :=
    "[" IntegerStorage [ "|" L "..=" U ] [ ";" "<=" N ] "]"
  | "[" "bool" [ ";" "<=" N ] "]"

IntegerStorage := "i64" | "u8" | "i32"
```

`L`, `U`, and `N` are signed decimal integer literals of the existing refinement syntax. The length bound remains `0..=2^40`.

```pruv
fn make_bytes(n: i64) -> [u8] ! alloc
  requires 0 <= n && n <= 100
  ensures len(result) == n
{
  let mut b: [u8] = alloc(n, 0);
  if n > 0 {
    b[0] = 255;
  }
  return b;
}
```

```pruv
fn ascii_copy(a: [u8 | 0..=127; <=4096])
  -> [u8 | 0..=127; <=4096] ! alloc
{
  return copy(a);
}
```

`[bool | 0..=1]` is not allowed. `[bool; <=100]` is allowed.

`u8` and `i32` have special meaning only at the array element position in the type syntax. They are not made global keywords, so existing variable names are not needlessly banned.

### 2.2 Strings

```text
StringType := "str"
StringLiteral := '"' StringCharacter* '"'
```

Literals allow Unicode scalar values of the UTF-8 source as they are. The minimum escape set is as follows.

| Notation | Value |
|---|---|
| `\"` | Quotation mark |
| `\\` | Backslash |
| `\n` | LF |
| `\r` | CR |
| `\t` | TAB |
| `\0` | NUL |

`\xNN`, `\u{...}`, raw strings, and multi-line strings are excluded. An actual line break and an unescaped ASCII control character are rejected. NUL is not a string terminator and is counted in the length.

`//`, parentheses, and refinement symbols inside a string are ordinary characters. The lexer reads the whole string and then continues processing the surrounding tokens. Column numbers in diagnostics keep the existing per-character rule and are not changed to UTF-8 byte offsets.

```pruv
fn greeting() -> str ! alloc {
  return "안녕";
}

fn prefix(s: str, end: i64) -> str ! alloc
  requires 0 <= end && end <= len(s)
  requires is_char_boundary(s, end)
  ensures len(result) == end
  ensures forall k in 0..end: result[k] == s[k]
{
  return substr(s, 0, end);
}
```

No shorthand refinement syntax is added for `str`. Length and byte conditions are written as ordinary contracts.

## 3. Typing rules

### 3.1 Storage type and expression type

| Array | Range of stored values | Expression type of `a[i]` | Expression type of the assigned value |
|---|---:|---|---|
| `[i64]` | `-2^63..=2^63-1` | `i64` | `i64` |
| `[u8]` | `0..=255` | `i64` | `i64` |
| `[i32]` | `-2^31..=2^31-1` | `i64` | `i64` |
| `[bool]` | `false`, `true` | `bool` | `bool` |

`a[i] + 1` is an i64 addition even for a narrow integer array. When the result is stored back into an array, the storage range is proved. For example, reading a byte equal to 255 and adding 1 is possible, but that 256 cannot be stored into a `[u8]`.

Array types must match exactly. Passing a `[u8]` to a `[i64]` argument, or turning it into a different element type with `copy`, is forbidden.

There is also no 0/1 conversion between bool and integers. The body of `sum` needs an integer, and the number of true elements of a bool array is obtained with `count(k in 0..len(a): a[k])`.

### 3.2 Type decision of `alloc`

The checker passes the expected type of `expect(expr, expected_type, ...)` at the following positions.

- `let` initialization: the declared type.
- Reassignment: the type of the target variable.
- `return`: the function's return type.
- Function argument: the type of the corresponding parameter.
- `copy(expr)`: the outer expected array type is also passed to the inner `expr`.

When `alloc(n, v)` receives an expected array type, it uses that element storage type. Without an expected array type, it is decided as `[i64]`. The width is not guessed from the constant size or value of `v`.

```pruv
let a: [u8] = alloc(4, 0);          // [u8]
let b: [bool] = alloc(4, false);    // [bool]
let c: [i32] = copy(alloc(4, -1));  // [i32]
let n: i64 = len(alloc(4, 0));      // the inner alloc is [i64]
```

`len(alloc(4, false))` has no expected array type, so under the existing default `[i64]` it is a type error. If necessary, bind it first to a `[bool]` local variable.

If the input of `copy(a)` is already an expression with a type, that type is preserved as is. The expected type does not convert an existing array value.

### 3.3 Mutation, aliasing, effects

- As before, the RHS of an array `let` or reassignment must be an owned value coming from `alloc`, `copy`, or a call to an array-returning function.
- Returning an array local variable permits transfer of ownership. Returning a parameter requires `copy`.
- An array argument of a function call is passed by borrowing and can still be used after the call.
- Element mutation is allowed only on `let mut` local arrays.
- `alloc`, `copy`, and `substr` require the `alloc` effect.
- Whole-array `==`·`!=` remain forbidden.
- Evaluation order is kept. Call arguments are evaluated from the left, and an element assignment goes index → RHS → store.

### 3.4 Refinement

`[u8 | L..=U]` and `[i32 | L..=U]` are allowed, but the whole refinement range must lie within the range of the storage type. For example, `[u8 | -1..=127]` is not interpreted as an intersection and is rejected with `refinement_bounds`.

Length refinement is allowed for all four arrays. The existing refinement expansion order and position rules are kept.

- Parameters: add the length condition and then the element condition, in that order, before `requires`.
- Returns: add the corresponding `ensures`.
- Local initialization and reassignment: the existing refinement obligations.
- Element store: the existing `elem_refine` obligation after the storage-type obligation.
- Loops: keep the existing way of inserting refinement invariants.

The range of the storage type and the refinement condition written by the user are separate. The former is always maintained even in safe mode, and the latter keeps the existing refinement execution policy.

### 3.5 Strings

| Expression | Result | Effect · constraint |
|---|---|---|
| `"..."` | `str` | In executable code it creates an owned string; `alloc` required |
| `len(s)` | `i64` | Byte length |
| `s[i]` | `i64` | Byte value, index range obligation |
| `copy(s)` | `str` | Independent owned copy, `alloc` required |
| `is_char_boundary(s, i)` | `bool` | Usable in code and contracts; false if out of range |
| `substr(s, lo, hi)` | `str` | Copy of `[lo, hi)`, range and boundary proofs, `alloc` required |

The contents of a string are immutable. `let mut s: str` allows only reassignment of the whole string. The ownership rules are the same as for arrays, except that a literal is also accepted as a source of a new owned value. To return a parameter, use `copy(s)`.

Using a string literal in a contract is a pure constant use. It then has no allocation effect, and the executable requires check refers to a static byte sequence. `copy` and `substr` are forbidden inside contracts.

There is no implicit conversion between `str` and `[u8]`. Whole-string equality is also not included this time.

### 3.6 Existing composite types

The payload of Option/Result still allows only i64. Struct and enum fields keep the existing `i64`, `bool`, `Option<i64>`, `Result<i64>`, and nested user types. Arrays and strings are not added to them.

## 4. Proof semantics

### 4.1 Type representation and preserving existing SMT

Gather the distinction of array types inside the implementation in one place.

- The serialization name `"array"` of the existing `[i64]` is kept.
- The new names are fixed as `"array_u8"`, `"array_i32"`, `"array_bool"`, `"str"`.
- The Python `Type` and the type strings of Rust C use these names.
- Rust V distinguishes them as `Ty::Array(ElemTy)` and `Ty::Str`.
- Provide common queries such as `is_array`, `array_elem`, `element_value_type`, and `storage_bounds`, and do not scatter string comparisons across many stages.

A symbolic array value keeps its storage type with it. It must not be lost in `fresh`, `copy`, rebinding, call results, or loop havoc.

An input that does not use G2 keeps the existing fresh numbering, obligation order, assumption order, and SMT names. No new universally quantified range assumption is added wholesale to existing `[i64]` paths.

### 4.2 Array model

| Type | Contents | Length |
|---|---|---|
| `[i64]`, `[u8]`, `[i32]` | `Array(Int, Int)` | Separate Int |
| `[bool]` | `Array(Int, Bool)` | Separate Int |
| `str` | Byte sequence as `Array(Int, Int)` | Separate Int |

A bool array selects an SMT Bool element. Compared with a 0/1 encoding, it needs less separate normalization and range assumption, and connects directly to bool expressions, short-circuit evaluation, and `count`. The 0/1 representation in memory is the responsibility of the code-generation layer.

For the parameters, call results, and havoc results of a new integer array, the following domain is placed.

```text
0 <= n <= 2^40
forall k: 0 <= k < n ==> lower(E) <= Select(A, k) <= upper(E)
```

For a bool array, the element domain is guaranteed by the sort. No additional meaning is given to elements outside the length.

`alloc` is modeled as a constant array, `copy` as a separate execution storage with the same contents and length, and assignment as `Store`. A value whose range obligation has not been proved must not be narrowed first in the model, nor may its range be assumed.

### 4.3 Obligations and order

| Operation | Obligation |
|---|---|
| Array/string read in code | Existing `index_oob` |
| Array/string read in a contract | Existing `contract_domain` |
| Arithmetic in code | Existing `overflow`, division-domain obligations |
| `alloc(n, v)` | Existing `alloc_negative`, then the new `elem_range` |
| Element assignment to a narrow integer array | `index_oob` → `elem_range` → existing `refinement_assign` |
| `substr(s, lo, hi)` | New `string_slice_range` → new `utf8_boundary` |

Detailed rules:

- Arguments, indices, and the RHS are each evaluated only once. Expressions are not re-executed to create obligations.
- `elem_range` applies to the creation of and stores into `[u8]`·`[i32]`. `[bool]` uses type checking, and `[i64]` uses the existing i64 expression range check.
- `alloc(0, v)` also evaluates `v` and requires the storage-type range. The range check is not skipped on the grounds that the array is empty.
- A later store or return that depends on a range failure is not treated as verification success.
- After a domain or index failure, the same operation is not diagnosed again with duplicate derived obligations.
- `unknown` and timeout are not proof success.
- `elem_range` points to the call site at creation and to the assignment site at a store.

### 4.4 UTF-8 and boundaries

The language semantics of `str` is valid UTF-8. In G2b this is not provided as an SMT predicate attached to an arbitrary byte array.

Validity is guaranteed by the following creation paths.

1. A valid source string literal.
2. A valid Rust `&str`, or a byte sequence checked at raw ABI entry.
3. A copy of an existing `str`.
4. A substring of an existing `str` whose two end boundaries are proved.
5. The return of a function that obeys the rules above.

SMT abstracts conservatively as a byte-array model that contains valid strings. A byte range and a length are assumed for a new `str` value, but incomplete UTF-8 axioms are not added arbitrarily. Therefore automatically proving every property that is true of valid UTF-8 is not a goal.

The boundary decision is fixed by the following formula.

```text
boundary(A, n, i) =
    (i == 0)
    or (i == n)
    or (0 < i and i < n
        and (Select(A, i) < 128 or Select(A, i) >= 192))
```

In valid UTF-8, an interior position is a character boundary if its byte is not a continuation byte. Negative positions and positions beyond `n` are false. The boundary decision itself is a total operation and adds no `contract_domain`. However, the domain of the argument expressions themselves is checked.

The obligations of `substr` are as follows.

```text
string_slice_range: 0 <= lo <= hi <= len(s)
utf8_boundary:      boundary(s, lo) and boundary(s, hi)
```

The result model satisfies the following.

```text
len(result) = hi - lo
forall k:
    0 <= k < len(result) ==> result[k] = s[lo + k]
```

The two boundaries are bundled into one `utf8_boundary` obligation so that it does not collide with the existing diagnostic de-duplication key. Even when `lo == hi`, that position must be a character boundary.

The rule "cutting between boundaries of valid UTF-8 yields valid UTF-8" is a string-creation rule trusted by the compiler. The agreement between this rule and the execution implementation is explicitly an audit target.

### 4.5 Contracts and inference

The existing contract domain, short-circuit, and quantification order apply to the new types as well. After assuming its own condition, the domain of that condition is not proved.

No candidates dedicated to new arrays or strings are added to `--infer`. When an existing template meets a new type, it generates or skips only the candidates whose types match. In particular, bool elements are not put into integer-range candidates. Regardless of whether `--infer` is on, the storage-range and string-boundary obligations are never dropped.

## 5. Code generation

### 5.1 Rust

| Pruv | Parameter | Local · return | Read |
|---|---|---|---|
| `[i64]` | `&[i64]` | `Vec<i64>` | i64 |
| `[u8]` | `&[u8]` | `Vec<u8>` | Widened to i64 |
| `[i32]` | `&[i32]` | `Vec<i32>` | Widened to i64 preserving the sign |
| `[bool]` | `&[bool]` | `Vec<bool>` | bool |
| `str` | `&str` | `String` | Elements of `as_bytes()` widened to i64 |

In proof mode, only integers whose range has been proved are narrowed to the storage type. In safe mode, the range is checked before narrowing. One must not first truncate with a plain `as u8`·`as i32` and then check.

The existing `[i64]` helpers are preserved and the helpers needed for the new types are added. A contract's integer array read is widened to i128, and a bool read stays bool.

`substr` uses the proved boundary in proof mode, and in safe mode checks the range and boundary and then copies. `is_char_boundary` first handles negative and large i128 contract indices, and converts to `usize` only within the valid range.

String literals are emitted escaped in a way that makes the byte contents unambiguous. The Python and Rust generators do not depend on the differing default string reprs of the host languages.

### 5.2 LLVM

The aggregate shape stays `{ ptr, i64 }`. The length is the **number of elements**, not the byte size. Only `str` has bytes as elements, so its length equals its byte size.

| Element | Memory type | Size · alignment | Read as a code expression |
|---|---|---|---|
| i64 | `i64` | 8·8 | As is |
| u8 | `i8` | 1·1 | `zext` → i64 |
| i32 | `i32` | 4·4 | `sext` → i64 |
| bool | `i8`, 0/1 | 1·1 | Convert to a bool value |
| str bytes | `i8` | 1·1 | `zext` → i64 |

The sizes and alignments above are a contract to be confirmed on the currently supported target ABIs. A target is released only if its checks satisfy them.

- A bool array is not bit-packed. On store, an i1 value is written as a 0/1 i8.
- GEP, load, store, copy, and free follow the storage type.
- The element type is also preserved in the internal `V`, `Slot`, temporaries, and the owned-array list. The size is not decided by `Kind::Arr` alone.
- Proof-based `inbounds` and arithmetic attributes are used only in proof mode.
- Safe mode checks the index, store range, and substring boundary before accessing.
- The exact element size and alignment are passed when freeing on reassignment, branches, early returns, and temporary call values.
- `substr` does not return a pointer into the middle of the original. It allocates a new buffer and copies, so it does not depend on the lifetime of the original.
- Empty strings and empty arrays are neither dereferenced nor freed, and null is never passed to `Vec::from_raw_parts`.

### 5.3 Runtime

The signatures of the existing `pruv_alloc`, `pruv_copy`, `pruv_free` are not changed. The new implementation separates the following responsibilities.

- Per-type filling: i64, u8, i32, bool.
- General allocation, copy, and free: element count, size, alignment.
- Rust allocator integration: the same Layout as used for the actual allocation and free.
- UTF-8 checking and partial string copy.
- Existing allocation/free counting.

The v2 size computation is validated before multiplication.

```text
0 <= len <= 2^40
elem_size, elem_align are an allowed type layout
len * elem_size is within SIZE_MAX and the target allocation limit
```

A general value fill of i32 is not substituted with `memset`. A zero fill is possible for all supported types.

The Rust host helpers are given size and alignment under v2 names. The allocation/free Layout of `pruv_host_alloc_v2`·`pruv_host_alloc_zeroed_v2`·`pruv_host_free_v2` must match. The capacity of a returned buffer is fixed to len.

The new failure messages and exit codes of safe mode are made to agree across both backends.

| Situation | stderr prefix | Exit |
|---|---|---:|
| Storage range violation | `pruv: element out of range:` | 101 |
| Substring range violation | `pruv: string slice out of bounds:` | 101 |
| UTF-8 boundary violation | `pruv: UTF-8 boundary error:` | 101 |
| Invalid representation of raw input | `pruv: invalid representation:` | 101 |

`--trust-callers` skips user requires checks. It is not widened into an option that skips the safe-mode storage-range check or the bool·UTF-8 representation checks of raw input.

### 5.4 `--rust-bindings` ABI and compatibility

| Pruv input | raw ABI |
|---|---|
| `[i64]` | Existing `*const i64`, len |
| `[u8]` | `*const u8`, len |
| `[i32]` | `*const i32`, len |
| `[bool]` | `*const u8`, len, each byte 0/1 |
| `str` | `*const u8`, byte len, valid UTF-8 |

Array and string returns use the last out pointer as before, and the function returns void.

- The existing `Pruv__Array { data: *mut i64, len: i64 }` is kept.
- The new types get `Pruv__ArrayU8`, `Pruv__ArrayI32`, `Pruv__ArrayBool`, and `Pruv__Str` respectively.
- A bool raw pointer is represented as u8. No Rust bool reference is created before validity is checked.
- A returned bool buffer is filled with only 0/1. After checking, it is taken over as a `Vec<bool>` with the same Layout.
- A string return takes over the u8 buffer, then checks validity and makes it a `String`.
- The bool·UTF-8 checks at raw entry are done before the body and the user requires. On the typed Rust paths `&[bool]`·`&str`, the language type guarantees representation validity.
- The actual allocation size, lifetime, and accessibility of a raw pointer are the contract of the external caller. We do not claim that byte checks guarantee the safety of an arbitrary pointer.

Compatibility is distinguished as follows.

1. Existing Pruv programs and public Rust function signatures are kept.
2. The i64 array argument and return layout of the existing `pruv_abi_*` is kept. If the type of a user function is changed, the ABI of that function also changes.
3. The runtime/host helper protocol is raised to v2 and the new bindings reference the v2 marker. A wrong link with the old runtime must fail.
4. Attaching existing generated binding sources as they are to the new runtime is not guaranteed. Regeneration and relinking are needed. Already completed executables are unaffected.
5. Byte-identity of existing output **relative to the past** is required of SMT. Changes to the helpers of generated sources are allowed, but the output bytes **between the Python/Rust implementations** must be the same.

## 6. Error codes and must_reject

### 6.1 New codes

| stage | code | Condition |
|---|---|---|
| parse | `element_storage_type` | `u8`·`i32` used at a scalar type position |
| verify | `elem_range` | The value range of a narrow-array creation or store cannot be proved |
| parse | `string_escape` | Unsupported or incomplete escape |
| parse | `string_unterminated` | EOF without a closing quotation mark |
| parse | `string_character` | An actual line break or a disallowed control character in a literal |
| type | `immutable_string` | Assignment to a string element |
| verify | `string_slice_range` | `0 <= lo <= hi <= len(s)` cannot be proved |
| verify | `utf8_boundary` | The two end boundaries of a substring cannot be proved |

The existing `syntax`, `unsupported_type`, `type_mismatch`, `immutable`, `array_alias`, `eq_type`, `field_type`, `refinement_base`, `refinement_bounds`, `refinement_assign`, `index_oob`, `contract_domain`, `alloc_negative`, `missing_effect` are reused.

The verification-failure JSON and the exit-code-1 convention are kept. Unproved and solver unknown are distinguished. The diagnostic order of existing inputs is not changed as a general cleanup task.

### 6.2 G2a rejection samples: at least 26

Each name is a pair of a `.pruv` and a `.json` containing the expected stage/code under `tests/must_reject/`.

| Name | Wrong condition | Expected stage/code |
|---|---|---|
| `g2a_scalar_u8` | `x: u8` | parse / `element_storage_type` |
| `g2a_scalar_i32` | `-> i32` | parse / `element_storage_type` |
| `g2a_nested_array` | `[[i64]]` | parse / `syntax` |
| `g2a_user_element` | `[Point]` | parse / `unsupported_type` |
| `g2a_option_u8` | `Option<u8>` | parse / `unsupported_type` |
| `g2a_array_field` | `[u8]` field of a struct | type / `field_type` |
| `g2a_mixed_argument` | Pass a `[u8]` to a `[i32]` argument | type / `type_mismatch` |
| `g2a_bool_fill` | `[bool] = alloc(1, 0)` | type / `type_mismatch` |
| `g2a_bool_store` | Store 1 into a bool array | type / `type_mismatch` |
| `g2a_bool_read_int` | Bind a bool element to an i64 | type / `type_mismatch` |
| `g2a_param_store` | Mutate an array parameter | type / `immutable` |
| `g2a_alias` | Bind a local array directly to another local | type / `array_alias` |
| `g2a_array_eq` | Whole-array `==` | type / `eq_type` |
| `g2a_u8_negative` | Store -1 at a valid index | verify / `elem_range` |
| `g2a_u8_high` | Store 256 at a valid index | verify / `elem_range` |
| `g2a_i32_low` | Store -2147483649 | verify / `elem_range` |
| `g2a_i32_high` | Store 2147483648 | verify / `elem_range` |
| `g2a_alloc_value` | `[u8] = alloc(0, 256)` | verify / `elem_range` |
| `g2a_store_index` | Store a valid value at an index equal to the length | verify / `index_oob` |
| `g2a_refine_wide` | `[u8 \| -1..=127]` | type / `refinement_bounds` |
| `g2a_bool_refine` | `[bool \| 0..=1]` | type / `refinement_base` |
| `g2a_refined_store` | Store 128 into `[u8 \| 0..=127]` | verify / `refinement_assign` |
| `g2a_return_mismatch` | Return `[i64]` from a `[u8]` function | type / `type_mismatch` |
| `g2a_contract_oob` | Read an element of an empty array in a contract | verify / `contract_domain` |
| `g2a_alloc_length` | Create with a negative length | verify / `alloc_negative` |
| `g2a_missing_alloc` | Create a new array without an effect declaration | effect / `missing_effect` |

### 6.3 G2b rejection samples: at least 16

| Name | Wrong condition | Expected stage/code |
|---|---|---|
| `g2b_escape` | `"\xFF"` | parse / `string_escape` |
| `g2b_unterminated` | A literal not closed until EOF | parse / `string_unterminated` |
| `g2b_newline` | An actual line break inside a literal | parse / `string_character` |
| `g2b_store` | Element assignment to a `let mut s: str` | type / `immutable_string` |
| `g2b_alias` | Bind an existing string directly to a new owned local | type / `array_alias` |
| `g2b_field` | A str field of a struct | type / `field_type` |
| `g2b_to_bytes` | Assign a str to a `[u8]` | type / `type_mismatch` |
| `g2b_from_bytes` | Assign a `[u8]` to a str | type / `type_mismatch` |
| `g2b_eq` | Whole-string `==` | type / `eq_type` |
| `g2b_slice_range` | `lo > hi` | verify / `string_slice_range` |
| `g2b_slice_start` | Cut the start of `"é"` at byte 1 | verify / `utf8_boundary` |
| `g2b_slice_end` | Cut the end of `"é"` at byte 1 | verify / `utf8_boundary` |
| `g2b_index` | `s[len(s)]` | verify / `index_oob` |
| `g2b_contract_index` | Out-of-range string read in a contract | verify / `contract_domain` |
| `g2b_missing_alloc` | Create an executable literal without an effect declaration | effect / `missing_effect` |
| `g2b_option_str` | `Option<str>` | parse / `unsupported_type` |

Write each sample so that all other obligations before the target error hold. Raw input with invalid UTF-8 goes into the ABI execution tests, not into the Pruv source rejection tests.

## 7. Implementation batches and file boundaries

Path abbreviations: `P/` = `pruvc/`, `C/` = `pruvc-rs/crates/pruv-core/src/`, `V/` = `pruvc-rs/crates/pruv-proof/src/`. New files are proposed paths to be added at implementation time.

### 7.1 Work ownership rules

A file is modified by only one worker at a time. In particular, the Python `llvmgen.py` contains LLVM, ABI, and bindings together, so these three are not assigned to different workers at the same time.

Consumer work proceeds after the shared AST and type API are finalized. The same file may be modified again between batches, but only after the earlier batch is closed and ownership is handed over. The test owner can write dedicated new samples in parallel, and changes to the shared harness are integrated serially by a separate owner.

### 7.2 Batch A1: array frontend

- Files — Python: `P/vast.py`, `P/typeinfo.py`, `P/vparser.py`, `P/check.py`, `P/refine.py` / Rust: `C/ast.rs`, `C/typeinfo.rs`, `C/lexer.rs`, `C/parser.rs`, `C/check.rs`, `C/refine.rs`, `C/dump.rs` / cross-check: `tests/diff_py_adapter.py`, `tests/diff_parse.py`, `tests/diff_compilers.py` / samples: `tests/must_reject/g2a_*.{pruv,json}`, `tests/check_edge/g2a_*.pruv`
- Content: Element-type identification, expected-type propagation, refinement, and errors are first settled in Python and then ported to Rust. The set of type names allowed in `|` lexing is also modified.
- End criteria: All G2a parse/type/effect rejection samples match their expected codes. Checks for `alloc` in direct, nested `copy`, argument, return, and no-expected-type positions. parse/check dumps byte-identical in both implementations. Zero new differences in the existing frontend cross-check. Not released as a usable G2a release before the proof and backends are complete.

### 7.3 Batch A2: array proof

- Files — Python: `P/verify.py`, `P/infer.py` / Rust: `V/model.rs`, `V/symbolic.rs`, `V/obligation.rs`, `V/infer.rs`, `V/samples.rs` / cross-check: `tests/diff_trace.py`, `tests/diff_py_adapter.py` / samples: G2a verify rejection samples, `examples/g2a_*.pruv`
- Content: Implement type-preserving symbolic arrays, the bool sort, the narrow element domain, creation and store obligations, bool output in counterexamples, and type filters for inference.
- End criteria: The 26 G2a rejection samples complete. Samples pass for narrow-array arguments, call results, loop havoc, branches, and store after copy. The SMT and obligation order of the G2a traces are identical in both implementations. SMT of existing inputs without `--infer` is byte-unchanged. Zero cases where `--infer` lets a wrong store pass.

### 7.4 Batch A3: array execution · ABI

- Files — Rust source generation: `P/codegen.py`, `C/codegen.rs`, `C/emit_common.rs` / LLVM·ABI: `P/llvmgen.py`, `C/llvmgen.rs`, `C/abi.rs`, `C/bindings.rs` / runtime: `P/runtime.c`, `pruvc-rs/crates/pruvc/build.rs`, `pruvc-rs/crates/pruvc/src/runtime.rs` / tests: `tests/run_all.py`, `tests/diff_rust.py`, `tests/diff_llvm.py`, `tests/abi/check_generated.py`, `tests/abi/check_abi.py`, `tests/abi/gen/g2a_*.pruv`, `tests/runtime/g2a_*`
- Content: Implement per-element store, widening and narrowing, safe-mode checks, exact allocation Layout and free, the v2 host protocol, and typed/raw ABI. Rust source generation and LLVM generation do not overlap in files, so they can proceed in parallel.
- End criteria: G2a examples at least 8, runtime at least 12. Order and messages of normal values and errors agree across the two backends and two compilers. Confirm element size, alignment, sign extension, bool 0/1, empty arrays, and the Layout of returned buffers. Confirm allocation/free balance for reassignment, temporaries, branches, and early returns. A test that linking a wrong runtime version fails. The existing 444 regression rows are kept, and the new samples are tallied separately.

### 7.5 Batch B1: string frontend · proof

- Files — Python: `P/vast.py`, `P/typeinfo.py`, `P/vparser.py`, `P/check.py`, `P/refine.py`, `P/verify.py`, `P/infer.py` / Rust: `C/ast.rs`, `C/typeinfo.rs`, `C/lexer.rs`, `C/parser.rs`, `C/check.rs`, `C/refine.rs`, `C/dump.rs`, `V/model.rs`, `V/symbolic.rs`, `V/obligation.rs`, `V/infer.rs` / cross-check: `tests/diff_py_adapter.py`, `tests/diff_parse.py`, `tests/diff_trace.py` / samples: `tests/must_reject/g2b_*`, `examples/g2b_*.pruv`
- Content: Implement string tokens, AST, types, and effects, literal byte constants, boundary decisions, and the copied-substring relation. Refinement and inference are also updated so that AST traversals do not miss string literals.
- End criteria: The 16 G2b rejection samples complete. Parsing and byte length agree for ASCII, Hangul, 2/3/4-byte characters, the empty string, and NUL. Confirm boundary decisions for `0`, the end, interior boundaries, continuation positions, and negative and past-the-end positions. The string type is preserved through literal → copy → substring → function return. Existing SMT unchanged and the new trace cross-check passes.

### 7.6 Batch B2: string execution · ABI

- Files — Python: `P/codegen.py`, `P/llvmgen.py`, `P/runtime.c` / Rust: `C/codegen.rs`, `C/emit_common.rs`, `C/llvmgen.rs`, `C/abi.rs`, `C/bindings.rs` / tests: `tests/runtime/g2b_*`, `tests/abi/gen/g2b_*.pruv`, `tests/abi/check_generated.py`, `tests/abi/winci/prepare.py`, `tests/abi/winci/run_windows.py` / shared harness: `tests/run_all.py`, `tests/diff_rust.py`, `tests/diff_llvm.py`
- End criteria: G2b examples at least 6, runtime at least 12. A substring is an independently owned buffer and remains valid after the original is freed. Safe-mode range and boundary errors are identical across the two backends. Invalid UTF-8 is rejected at the raw ABI (isolated continuation, truncated multi-byte, overlong, surrogate, beyond U+10FFFF). Input containing NUL is not truncated. The representation-validity checks are kept even under `--trust-callers`. G2a and all existing regressions are kept.

### 7.7 Batch Q: fuzzing · mutation · independent use · documentation

- Files — fuzzer: `bench/fuzz/{generate,oracle,run}.py`, `bench/fuzz/README.md` / mutation: `bench/mutate.py`, `bench/inference/mutate_infer.py` / new G2 measurement: `bench/g2/{PROBLEMS.md,reference.rs,run.py,solutions/,results/}` / documentation: `SPEC.md`, `BLUEPRINT.md`, `RESULTS.md`, `docs/G2_SPEC.md`
- The oracle does not import the compiler implementation and independently interprets element ranges, UTF-8, and substrings.
- End criteria: Satisfy all of the cross-check, regression, fuzzing, mutation, bench, audit, and independent-use gates of §8. `SPEC.md` summarizes the G2 user rules within one page, and the detailed implementation contract is kept in this document.

## 8. End criteria and measurement

### 8.1 Cross-check and regression

- Fix the **444-row baseline** of the existing `run_all --backend both` as the input list. It must be kept in both Python and Rust.
- New samples are tallied separately as G2a/G2b.
- Cross-check parse/check dumps, verification traces, Rust output, and LLVM IR and bindings between the two implementations.
- `diff_trace.py` distinguishes `cex_only` and `same_unknown`. Do not record "byte-identical" on the basis of exit code 0 alone.
- The new deterministic gate corpus must be identical even down to the raw trace.
- The SMT of existing inputs without `--infer` must be byte-identical to the pre-G2 baseline. The solver version and options are fixed.
- Check with `--infer` both on and off, but completing G2 does not mean enabling inference by default.

### 8.2 Minimum positive and execution samples

| Stage | examples files | runtime batches |
|---|---:|---:|
| G2a | 8 | 12 |
| G2b | 6 | 12 |

The G2a examples include u8 copy, ASCII refinement, i32 negative read, i32 boundary store, bool creation, bool count, expected-type propagation, and loop element mutation. The G2a runtime includes both end values of elements, wrong narrowing, value check at zero-length creation, read sign extension, bool layout, evaluation order, copy independence, function return, free on reassignment and early return, refinement entry, and raw bool check.

The G2b examples include literal byte length, byte read, copy return, ASCII substring, multi-byte boundary substring, and boundary branch. The G2b runtime includes escapes, NUL, empty string, multi-byte, negative/large boundaries, both-end boundaries, invalid substrings, evaluation order, reassignment, nested temporaries, return ownership, and invalid UTF-8 ABI input.

For a rejected program that can run only in safe mode, first confirm the verification rejection and then check the safe-mode panic. Unproved code that may have UB is not run in proof mode.

### 8.3 Fuzzer · mutation

- With each of the fixed seeds 41·56·57, the goal is at least 200 verified-passing programs that actually use G2, and at least 8 inputs per program.
- Compare against an independent oracle across two compilers, two backends, and proof/safe modes.
- In each seed, run at least 30 unproved programs in safe mode.
- Insufficient generation counts, unsupported oracle syntax, timeouts, and incomplete runs are excluded from the pass count and reported.
- The G2 mutations include at least store bound ±1, inputs exposing i32 sign-extension errors, range-guard deletion, index end-value change, substring boundary ±1, and boundary-condition deletion.
- There must be no degradation of the judgments of the existing mutation corpus. The number of new wrong mutants that pass verification must be 0.
- A true mutant passing is distinguished from an error. A compiler crash or timeout is not counted as a correct rejection.

### 8.4 bench and independent use

| Measurement | Requirement |
|---|---|
| Correct answers and verification success rate of existing bench | No decrease |
| Existing compile/proof time | Record median and top latencies; a worsening of more than 10% in repeated measurement is judged at the gate after its cause is resolved |
| Array execution time and memory | Measure u8/i32/bool each against the i64 baseline |
| String processing | Separate the costs of byte scan, partial copy, and ABI UTF-8 check |
| Contract writing effort | Compare the i64 array representation and the new representation for the same problem |
| solver | Record number of obligations, number of quantifiers, unknown, timeout |

**Conjecture:** Narrow arrays can reduce memory usage and some scan costs. The new universal range assumption may increase verification time. No numerical gain is claimed until it is measured after implementation.

The independent-use problems are six: byte-range conversion, ASCII filter, i32 array update, bool aggregation, UTF-8 byte search, and boundary-based substring. The independent author is given only the user specification and the problem. Record the number of first-attempt successes, the number of fixes made using diagnostics, and the final number of successes. Both the reference solution and the independent solution after fixes must pass 6/6. The first-attempt results are not hidden.

### 8.5 Audit

Perform one audit and one fix confirmation for each of G2a and G2b. Zero unresolved required findings are required. Audit focus: generation and store ranges that must be proved before being assumed, whether a contract unjustly assumes the range of an out-of-range element, agreement between the bool sort and the memory representation, whether types are lost in call results, havoc, and alias handling, both ends of a substring and the empty substring, UTF-8 validity of literals, raw ABI, and returns, the exact allocator Layout and return ownership, and preservation of the SMT and obligation order of existing programs.

## 9. What is left and dissenting opinions

### 9.1 Confirmed facts (code at design time)

- The Python AST type is name-based, and Rust C also uses type-name strings. `Ty::Array` of Rust V has no element-type argument (`pruvc/vast.py:10`, `pruv-core/src/ast.rs:5`, `pruv-proof/src/model.rs:38`).
- The array parser allows only `[i64]`, and read and assigned values are fixed to i64 (`pruvc/vparser.py` `type_r`, `pruvc/check.py:209` (write)·372 (read), `pruv-core/src/parser.rs:309`, `pruv-core/src/check.rs:517`).
- Sources of new owned array values and returns have alias restrictions. `alloc`·`copy` require the alloc effect (`pruvc/check.py` `array_source` (309), the alloc effect of `call` (496~502)).
- Refinement is expanded into existing contracts, and the element-store obligation applies to the already evaluated value (`pruvc/refine.py`, `pruvc/verify.py:881`, `pruv-proof/src/symbolic.rs:1436`).
- The runtime uses the i64 size 8 and the i64 Layout of the Rust host, and the bindings take over a returned array with `Vec::from_raw_parts` (`pruvc/runtime.c:108`, `pruv-core/src/bindings.rs` host allocation (11~), return takeover (313)).
- The lexer has no quotation-mark token (`pruvc/vparser.py:13,42`, `pruv-core/src/lexer.rs:83-148`).

### 9.2 What was not confirmed

- The proposed new errors, element types, and string features are not implemented, so whether they actually pass was not confirmed.
- The new per-target element layout, allocator integration, Windows execution ABI, and UTF-8 check performance must be verified after implementation.

### 9.3 Features left for later

`[u8] → str` needs failure to be expressed as a language value. In a later stage, first design a type extension that holds owned payloads such as `Result<str>`, and then decide the conversion API.

If `utf8(b, lo, hi)` is added, it must not be passed through as a plain uninterpreted predicate. The exact UTF-8 semantics, the execution check, invalidation of facts after array mutation, the interpretation of both ends of a partial interval, and the solver cost must be specified together.

Character counts, normalization, string equality, concatenation, output, and borrowed substrings are separate features. The byte semantics of G2b are not changed implicitly.

### 9.4 Dissenting opinions of the draft author

1. The storage-type range must not be treated as exactly the same as an existing refinement annotation. A refinement may keep the existing execution policy, but a narrow storage type must check the range even in safe mode so that values are not truncated.
2. We oppose the proposal to lower every position of `str` to Rust `&str`. The proposal with `&str` for arguments, `String` for locals and returns, and copying for substrings fits the first implementation.
3. We defer the proposal to put the `utf8` predicate and fallible conversion into G2b together. Currently Option/Result have only i64 payloads.
4. The premise that struct fields are only i64 does not match the current code. The existing bool, Option/Result, and nested user-type fields are kept, and only new array and string fields are excluded.
5. Full link compatibility with old generated artifacts is incompatible with the v2 runtime decision. If it is mandatory, an additional batch that separates v1/v2 runtime objects is needed.
