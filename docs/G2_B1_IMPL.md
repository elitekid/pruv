# G2 B1 implementation spec: `str` proof — common to both implementations

This spec fixes things so that the Python implementation (`pruvc/`) and the Rust implementation (`pruvc-rs/`) emit **the same SMT, the same proof obligation order, and the same wording**. Basis: `docs/G2_SPEC.md` §0.0 decisions 2, 4, 11, 13, 16, §4.3~§4.5, §6.1, §6.3, §7.5. Earlier batches: `docs/G2_A2_IMPL.md` (u8 proof), `docs/G2_A5_IMPL.md` §2 (bool proof), `docs/G2_B0_IMPL.md` (str frontend).

## 0. Scope and decisions

- The proof layer accepts `str`. The generation layer (Rust, LLVM) keeps blocking it with `unsupported_type` (stage `codegen`) (opened in B2).
- **Representation:** a symbolic `str` value creates no new form; it is a **symbolic array whose element type is U8** (Py `Arr`, Rs `Val::Arr(Arr)`, `elem = U8`). In SMT it is `Array(Int, Int)` + a length Int. So:
  - The byte-range assumption (decision 2) at the three places — function entry, user-function call result, loop havoc — attaches with the existing `u8_dom` length as is (no new code).
  - `len`, code read `s[i]` (index_oob, `in_range` assumption as is), contract read (contract_domain), `copy`, rebinding, `result` in `ensures`, and the counterexample JSON (`{"len": n, "first": [..]}`, integers) are the same as for array length.
- A literal is a constant term, and a `substr` result is a new symbolic value + assumptions on length and byte relation. In both cases **no range assumption is added separately**: literal bytes are constants (0..255), and `substr` bytes equal those of the original `s`, so the range already holds (this satisfies "results of literal, copy and substr" in decision 2).
- No UTF-8 validity axiom is added (decision 13: over-approximation). **The bytes of a str in an SMT counterexample may not be valid UTF-8.** This meaning is written into the FIX text of the two `substr` obligations (§3).
- `--infer`: no new candidates. `string_slice_range` and `utf8_boundary` are proved without `cand` (None), so they are skipped in the search and decided only in the final full verification (decision 4). `infer.py`/`infer.rs` are not modified (investigation showed the StrLit traversal is already safe: Py `show` is `_Skip`, Rs `show` is None).
- The SMT, fresh numbering, and obligation order for inputs that do not use G2 must not change (the existing 231 bytes of SMT are unchanged).

## 1. Types and fresh

### Py `pruvc/verify.py`
- Check that `STR` comes in through the import (if it already comes in through `from vast import *`, leave it).
- `fresh(base, ty)`: **right before** the `is_array(ty)` branch,
  ```python
  if ty == STR:   # G2 B1: str = U8 byte array
      return mk_arr(z3.Array(n, z3.IntSort(), z3.IntSort()), z3.Int(n + ".len"), base, U8)
  ```
  (The counter `s.k += 1` and the name `n` are as at the start of the function — the same naming rule as arrays, `base!k`, `base!k.len`.)
- `wf(STR, ..)` is never reached (every call site checks `isinstance(v, Arr)` first).

### Rs `pruvc-rs/crates/pruv-proof/src/model.rs`
- Add a `Str` variant to `enum Ty` (after `Array(Elem)`). `from_name("str") => Ty::Str` (before the array-name check), `name(): Ty::Str => "str"`. **Do not change** `is_array()` and `array_elem()` (str is not an array; false/None).
- Where `Ty::Array(_)` is matched (near model.rs 413 `Ty::Unit | Ty::Array(_) => Err(..)`, near symbolic.rs 349 and 581), add `Ty::Str` **in the same arm as Array**. State it explicitly; do not absorb it with a wildcard.
- Add `assert_eq!(Ty::from_name("str"), Ty::Str); assert_eq!(Ty::Str.name(), "str");` to the tests in model.rs (`mod tests`).

### Rs `symbolic.rs` `try_fresh`
- The `Ty::Str` arm: build it exactly like `Ty::Array(Elem::U8)` (the same naming rule, int-sort elements, `elem = Elem::U8`, one counter increment).

## 2. Expression evaluation

### 2.1 String literal `StrLit` (code and contracts, the same term)
In Py `ev`, after the `IntLit`/`BoolLit` branches:
```python
if isinstance(e, StrLit):   # G2 B1: constant byte array, no counter, no assumption
    a = z3.K(z3.IntSort(), z3.IntVal(0))
    for i, b in enumerate(e.value):
        a = z3.Store(a, z3.IntVal(i), z3.IntVal(b))
    return mk_arr(a, z3.IntVal(len(e.value)), "literal", U8)
```
- Constant array default `0`, `Store` in order from index 0 (the outermost is the last byte). The length is `IntVal(number of bytes)`. The name is `"literal"`.
- It does not touch the counter, and there are no obligations or assumptions. Replace the `Expr::StrLit` arm of Rs `symbolic.rs` `ev` (currently `Err(..)`) with the same term (`K` is the constant-array constructor that alloc uses; use the Store that IndexAssign uses).

### 2.2 Boundary decision `boundary(arr, i)`
A Py module function (next to `u8_dom`):
```python
def str_boundary(arr, i):
    """G2 B1 (G2_SPEC 4.4): i is a UTF-8 character boundary of byte array arr (total, no domain)."""
    b = z3.Select(arr.a, i)
    return z3.Or(i == 0, i == arr.n, z3.And(i > 0, i < arr.n, z3.Or(b < 128, b >= 192)))
```
- Literally: the order of the three `Or` arguments, `i > 0` (not Py `0 < i`), `i < arr.n`, `b < 128`, `b >= 192`. The constants are the integers 0, 128, 192.
- In Rs `symbolic.rs`, a `fn str_boundary(&self, arr: &Arr, i: &Ast) -> Ast` that builds the same expression (next to u8_dom): `or([eq(i,0), eq(i,n), and([gt(i,0), lt(i,n), or([lt(b,128), ge(b,192)])])])` — so that the z3 AST is the same as Py (`i > 0` is `(> i 0)`).

### 2.3 builtin `is_char_boundary(s, i)` (code and contracts)
In Py `call`, after the `copy` branch and before the `print` branch:
```python
if n == "is_char_boundary":
    return str_boundary(args[0], args[1])
```
- The arguments were already evaluated in order earlier (`args = [...]`). No obligations or assumptions. The contract domain `dom` is not changed (for a Call it only collects the argument domains — the current code as is matches §4.4 "check only the domain of the argument expressions themselves").
- In Rs `call`, in the builtin-name match, at the same place with the same behavior (`Val::Bool(..)`).

### 2.4 builtin `substr(s, lo, hi)` (code only; contracts are rejected by the checker)
Py, after the `is_char_boundary` branch:
```python
if n == "substr":   # G2 B1 (G2_SPEC 4.4): range -> boundary -> fresh result
    sv, lo, hi = args
    s.prove(st, g, z3.And(lo >= 0, lo <= hi, hi <= sv.n), e, "string_slice_range",
            "substr range 0 <= lo <= hi <= len(%s)" % sv.name)
    s.prove(st, g, z3.And(str_boundary(sv, lo), str_boundary(sv, hi)), e, "utf8_boundary",
            "substr cuts of %s at UTF-8 character boundaries" % sv.name)
    res = s.fresh("substr", STR)
    s.assume(st, g, res.n == hi - lo)
    k = z3.Int("str!k")
    s.assume(st, g, z3.ForAll([k], z3.Implies(z3.And(k >= 0, k < res.n),
                                               z3.Select(res.a, k) == z3.Select(sv.a, lo + k))))
    return res
```
- Fixed order: argument evaluation (existing) → `string_slice_range` → `utf8_boundary` → fresh (counter 1) → length assumption → byte-relation assumption.
- node = the substr Call expression (both obligations have the same node; the codes differ, so the deduplication keys differ). No key_extra, no cand.
- The bound variable is the fixed-name integer constant **`str!k`** (it does not use the counter). No patterns. `lo + k` is in the order `lo + k`.
- The length assumption is the single term `res.n == hi - lo` (do not add `res.n >= 0`, a MAX_LEN assumption, or `u8_dom` separately).
- `s.assume(st, g, ..)` is the same helper as for call-result assumptions (an implication if g exists). Rs uses the same `assume`.
- Failure handling is the existing `prove` as is (no new derived-deduplication rule is created, decision 8).
- In the Rs `call` builtin match, at the same place and in the same order.

### 2.5 Other
- `len`, `copy`, Index, rebinding, return, ensures, havoc, counterexamples: not changed (they are handled through the array path as is). However, if Rs has a match that rejects `Ty::Str`/`Val::Arr`, fix it to be the same as for arrays.
- The exception at the very end of Py `ev` and the other `Err` wording in Rs stay as they are.

## 3. FIX table

Two lines (literal text) in the Py `FIX` dictionary after `elem_range`, and at the same place in Rs `obligation.rs` `fix_for`:

```
string_slice_range: keep 0 <= lo <= hi <= len(s) for substr(s, lo, hi): bound lo and hi with requires, an if, or a loop invariant (a counterexample str may not be valid UTF-8)
utf8_boundary: cut a str only at character boundaries: require or check is_char_boundary(s, lo) and is_char_boundary(s, hi) (a counterexample str may not be valid UTF-8)
```

The diagnostic message uses the existing format `cannot prove <what> in <fn>`. Examples: `cannot prove substr range 0 <= lo <= hi <= len(literal) in f`, `cannot prove substr cuts of s at UTF-8 character boundaries in f`.

## 4. Guard

- Add `"str"` to the skip of the proof-layer guard: at the very start of Py `verify.verify_program`, `g2_unimplemented_error(prog, "verify", skip=("array_u8", "array_bool", "str"))`, and at the very start of Rs `lib.rs` `verify_program_opts`, `&["array_u8", "array_bool", "str"]`. The comment is `G2 B1`.
  - Now that skip covers every G2 type, this guard is always None. It is still not deleted (it is used again when A6 i32 arrives).
- The 6 generation-layer guards are not changed (str is blocked with stage `codegen`; the driver guard runs even after verify succeeds).

## 5. Samples (test worker, `tests/must_reject/`)

`.json` keys: `stage`, `code`, optional `flags`, optional `cex_contains` (a substring of stdout+stderr). Write each sample so that every other obligation before the target error holds. Grammar: `while` requires `decreases`, an expression statement must be a call, every path must `return`, no `__` in identifiers, no shadowing in the same scope, and if a literal is used in code the function needs `! alloc`.

### 5.1 Moving the B0 guard samples (proof passes → generation layer rejects)
`g2b_b0_verify_layer`, `g2b_b0_literal_verify`, `g2b_b0_infer_layer` (keep flags `--infer`), `g2b_b0_guard_order` (keep cex `"line": 5, "col": 5`), `g2b_b0_guard_lit_first` (keep cex `"line": 4, "col": 20`): change `stage` in `.json` from `"verify"` to `"codegen"`. Fix the first-line comment of `.pruv` to mean "from B1 the proof passes and the generation layer rejects" (the program body is unchanged). Exception: in `g2b_b0_guard_lit_first`, `return k + len(s) + n;` was changed to `return k + len(s);` because, now that the proof runs, overflow occurs first due to `n` whose range is unknown (the position 4:20 is unchanged).

### 5.2 G2_SPEC §6.3 verify samples (new)
| Name | Content | stage/code |
|---|---|---|
| `g2b_slice_range` | `substr("abc", 2, 1)` (lo > hi, both boundaries hold) | verify / `string_slice_range` |
| `g2b_slice_start` | `substr("é", 1, 2)` | verify / `utf8_boundary` |
| `g2b_slice_end` | `substr("é", 0, 1)` | verify / `utf8_boundary` |
| `g2b_index` | `let s: str = "ab"; return s[len(s)];` | verify / `index_oob` |
| `g2b_contract_index` | `fn f(s: str) -> i64 requires s[len(s)] >= 0` | verify / `contract_domain` |

### 5.3 B1 positive proof samples (proof passes → stage `codegen` / `unsupported_type`)
Named `g2b_b1_ok_*`. The proof must pass for it to reach the codegen stage.
- `g2b_b1_ok_len`: byte lengths by assert: `len("")==0`, `len("a")==1`, `len("é")==2`, `len("안")==3`, `len("😀")==4`, `len("\0")==1`, `len("a\0b")==3`, `len("안녕")==6`, and byte values `"é"[0]==195`, `"é"[1]==169`, `"\0"[0]==0`, `"안"[0]==236`.
- `g2b_b1_ok_boundary`: by assert, `is_char_boundary("é",0)`, `!is_char_boundary("é",1)`, `is_char_boundary("é",2)`, `!is_char_boundary("é",-1)`, `!is_char_boundary("é",3)`, `is_char_boundary("",0)`, `is_char_boundary("abc",1)`, `!is_char_boundary("😀",1)`, `2` and `3`, `is_char_boundary("😀",4)`, `is_char_boundary("안a",3)`.
- `g2b_b1_ok_flow`: literal → copy → substr → function return → caller. For example `fn head(s: str, i: i64) -> str ! alloc requires 0 <= i && i <= len(s) requires is_char_boundary(s, i) ensures len(result) == i ensures forall k in 0..i: result[k] == s[k]` with body `let c: str = copy(s); let d: str = substr(c, 0, i); return d;`, and in `fn use(..) -> i64 ! alloc`, `let a: str = "안녕"; let b: str = head(a, 3); assert len(b) == 3; assert b[0] == 236;` and `let t: str = substr("héllo", 1, 3); assert len(t) == 2 && t[0] == 195 && t[1] == 169;`.
- `g2b_b1_ok_param`: the byte-range assumption for a str parameter (entry and call result): under `requires len(s) > 0`, `let b: i64 = s[0]; assert b >= 0 && b <= 255;`, and the same assert on the first byte of the result of calling a function that returns a str.
- `g2b_b1_ok_loop`: a byte-range assert after a `let mut t: str` reassigned inside a loop (havoc), and a valid `while` loop that counts the bytes of `s` (with invariant and decreases).
- `g2b_b1_ok_contract`: `is_char_boundary`, `len`, `s[i]` and literals in contracts: e.g. `fn g(s: str, i: i64) -> bool ensures result == is_char_boundary(s, i) { return is_char_boundary(s, i); }`, `requires len(s) >= len("ab")` and `requires len(s) > 0 ==> s[0] >= 0`.
- `g2b_b1_ok_infer` (flags `["--infer"]`): a str loop that cannot be proved without an invariant and is proved by an existing template (e.g. `0 <= i && i <= len(s)`) that `--infer` finds. If inference cannot find it, use a loop with a written invariant instead of this sample, and note that fact in the first-line comment.

### 5.4 B1 rejection samples (does the proof actually decide, and is it not vacuous)
| Name | Content | stage/code |
|---|---|---|
| `g2b_b1_bad_len` | `assert len("안") == 2;` | verify / `assert` |
| `g2b_b1_bad_boundary` | `assert is_char_boundary("é", 1);` | verify / `assert` |
| `g2b_b1_bad_byte` | `assert "é"[1] == 168;` | verify / `assert` |
| `g2b_b1_param_boundary` | `fn f(s: str, i: i64) -> str ! alloc requires 0 <= i && i <= len(s) { return substr(s, 0, i); }` — cex_contains `"first"` (the str counterexample has an array shape) | verify / `utf8_boundary` |
| `g2b_b1_param_range` | only `requires 0 <= i`, then `substr(s, i, len(s))` (i > len(s) is possible) — the first diagnostic is `string_slice_range` | verify / `string_slice_range` |
| `g2b_b1_infer_boundary` (flags `["--infer"]`) | after a valid `while` loop (with a written invariant), return `substr(s, 0, i)` with unknown boundary — rejected with `utf8_boundary` also under `--infer` | verify / `utf8_boundary` |
| `g2b_b1_substr_bytes` | `let t: str = substr("héllo", 1, 3); assert t[0] == 104;` (actually 195) | verify / `assert` |
| `g2b_b1_ensures_len` | `fn h(s: str) -> str ! alloc requires len(s) >= 2 && is_char_boundary(s, 1) ensures len(result) == 2 { return substr(s, 0, 1); }` | verify / `ensures` |

### 5.5 Samples added after the audit
- `g2b_b1_ok_boundary2` (positive): the interior lead bytes 194, 195, 236 are boundaries, the continuation 191 is not, `substr("é",0,0)`, the 3-byte `substr("안녕",3,6)`, the 4-byte `substr("😀a",0,4)`, and the interior ASCII `"a~"` (126) — it catches the mutant that lowers the 192 threshold to 191, the mutant that raises the 128 threshold (item 3 of 😀 in `ok_boundary` = 128), and the mutant that lowers it below 127 (126). 127 (DEL) cannot be written in a literal, so there is no sample for the `b<127` mutant.
- `g2b_b1_bad_cont` (assert), `g2b_b1_slice_mid_empty` (`substr("é",1,1)` → utf8_boundary), `g2b_b1_slice_neg` (negative lo → string_slice_range), `g2b_b1_slice_over` (hi > len → string_slice_range, and utf8_boundary also remains afterward).

- run_all and diff_compilers only check that the expected code is **present** among the diagnostics. The obligation order (range → boundary) was confirmed by the main worker by running both implementations directly (not an automatic check).

### 5.6 Known limitations
- `--infer` candidates do not build expressions that contain a literal (Py `show` `_Skip`, Rs `show` None). So when a loop condition has a literal, as in `while i < len("abcd")`, there is no boundary candidate and inference cannot succeed (a completeness limitation, the same in both implementations). Write an invariant, or put the length in a variable.
- Even when the SMT is the same, the str (array) counterexample values may differ between the two implementations (z3 model choice; diff_trace `cex_only`). Per decision 11 the new samples must be `same`, so the `cex_contains` of a sample does not rely on counterexample values.

## 6. Verification (main worker)

- Build, `run_all --backend both` (update the row list with `--list-rows`), SMT 231 cmp, `diff_trace` on the new samples (no flags, `--flags=--infer`, same only), `diff_parse` and `diff_compilers --only must_reject --backend both`, `m3_all`, `cli_also_llvm`, `inference --regress`, fuzzer, cargo tests.
