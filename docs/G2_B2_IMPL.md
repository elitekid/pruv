# G2 B2 implementation spec: `str` execution and raw ABI — common to both implementations

Status: B2 batch implementation contract (written by the main worker). Both implementations (Python `pruvc/`, Rust `pruvc-rs/crates/`) emit the text below **byte for byte**. Basis: `docs/G2_SPEC.md` §0.0 decisions 13, 16, §5.1~§5.4, §6.3, §7.6, §8.2. It follows the earlier batch specs `docs/G2_A3_IMPL.md`, `G2_A4_IMPL.md`, `G2_A5_IMPL.md` (u8 and bool execution) and `G2_B0_IMPL.md`, `G2_B1_IMPL.md` (str frontend and proof); anything not written here is done the same way as the `[u8]` path.

## 0. Scope and decisions

1. The generation layer (Rust source, LLVM, `--rust-bindings`) accepts `str`. Change the skip of the 6 generation-layer guards (Py `pruvc.py`, `codegen.py`, `llvmgen.py`; Rs `driver.rs`, `codegen.rs`, `llvmgen.rs`) to `("array_u8", "array_bool", "str")` (Rs `&["array_u8", "array_bool", "str"]`) and make the comment `G2 B2`. The guard function is not deleted.
2. **For programs that do not use str, the Rust source, IR, bindings and SMT do not change by a single byte.** The str prelude, declarations and structs are attached only when `uses_str(prog)` is true.
3. `uses_str(prog)` (a new function, Py `typeinfo.py`, Rs `typeinfo.rs` `pub fn uses_str(prog: &Program) -> bool`): true if the parameter or return type of any function, or the type of a `let` (including inside nested blocks), is `str`, or if **any expression** in requires, ensures or the body contains a string literal (`StrLit`). (`uses_array_type(prog, "str")` cannot see a literal inside a `let` value expression, so the literal walk is done separately. The expression walk has the same scope as the literal-candidate collection of `first_g2_unimplemented`.)
4. Memory representation: a str value is `{ ptr, i64 }`, the same as a byte array (length = number of bytes), 1-byte elements (`i8`), size and alignment (1,1). In Rust source, parameters are `&str`, and locals and returns are `::std::string::String`.
5. A str during execution is always valid UTF-8: only literals (guaranteed by the parser), `copy`, and `substr` (boundary check or proof) create a str. The only way in from outside is the raw ABI (`pruv_abi_<f>`), where it is checked with `pruv_check_utf8` **before the body and requires** (regardless of `--trust-callers`). The `&str` of the typed Rust bindings is guaranteed by the language, so it calls the `__typed` entry (no check line) (the same approach as A5 bool).
6. The boundary decision has the same meaning as SMT `str_boundary` (B1): true if `i == 0` or `i == len`, false if `i < 0` or `i > len`, and otherwise true when the byte `b` satisfies `b < 128 || b >= 192` (= `(b & 0xC0) != 0x80`). For valid UTF-8 this equals Rust `str::is_char_boundary`.
7. New failures in safe mode (the same text in both backends, exit 101):
   - `pruv: string slice out of bounds: LO..HI (len N)` — violation of `0 <= lo <= hi <= len`
   - `pruv: UTF-8 boundary error: LO..HI (len N)` — the range is right but lo or hi is not a boundary
   - `pruv: invalid representation: K (str UTF-8, byte offset)` — invalid UTF-8 in raw input (K = the byte position where the invalid sequence starts)
   Check order: argument evaluation (s → lo → hi) → range → boundary → copy.
8. `print` does not accept a str (the checker as is). The ban on whole-array `==` also stays.
9. `show` (the expression text in the requires-violation message): `StrLit` is `<str>` in both implementations (Py currently gives `?`, to be changed to `<str>`).
10. The sorted-requires fast path (LLVM `csorted`, or the same thing in the Rust source if there is one) is not used for str: if the match is a str array, treat it as not matching and take the general path.

## 1. Rust source backend (Py `codegen.py` / Rs `codegen.rs`, `emit_common.rs`)

### 1.1 Types
- `rty`: `str` → `&str` for parameters, `::std::string::String` for locals and returns (an explicit branch in Rs `emit_common.rs`; do not rely on the fallback).
- Element discrimination: the query that checks whether the expression type is `str` (Py `is_str(t)` = `t is not None and t.name == "str"`, Rs `expr_ty(e) == Some("str")` or `self.vars`) is checked **before the u8/bool discrimination**. Since Rs `elem_of` gives str "i64", a str Index must be split off before it reaches `elem_of`.
- User-function call arguments: where `arr_ref` is currently used when `is_array(x.ty)`, **str also uses `arr_ref`** (local `&s`, parameter `s`, temporary `&<expression>`).

### 1.2 Literal text `LIT(bytes)`
Decode the bytes as UTF-8 and, for each character: if the code point is 0x20..=0x7E and is not `"` (0x22) or `\` (0x5C), the character as is; everything else (control characters, NUL, `"`, `\`, 0x7F, all non-ASCII) is `\u{X}` (X is lowercase hexadecimal with no leading zeros). Wrap with `"` at both ends.
- Examples: `"a\"b"` → `"a\u{22}b"`, `"é"` → `"\u{e9}"`, `"a\0b"` → `"a\u{0}b"`, `"\n"` → `"\u{a}"`, `""` → `""`, `"😀"` → `"\u{1f600}"`.
- Both implementations build it directly by this rule, without relying on the host language's repr.

### 1.3 Code expression text (`S` is a str sub-expression `s.e(..)`, `R` is `arr_ref(..)`, `I`, `LO`, `HI` are integer sub-expressions)
| Expression | Proof mode | Safe mode (`--no-verify`) |
|---|---|---|
| literal | `::std::string::String::from(LIT)` | same |
| `len(s)` | the current text as is, `(S.len() as i64)` | same |
| `s[i]` | `((unsafe { *S.as_bytes().get_unchecked((I) as usize) }) as i64)` | `pruv_get_str(R, I)` |
| `copy(s)` | `S.to_owned()` | same |
| `is_char_boundary(s, i)` | `pruv_str_boundary(R, I)` | same |
| `substr(s, lo, hi)` | `{ let pruv_s: &str = R; let pruv_lo: i64 = LO; let pruv_hi: i64 = HI; ::std::string::String::from(unsafe { pruv_s.get_unchecked((pruv_lo as usize)..(pruv_hi as usize)) }) }` | `pruv_substr(R, LO, HI)` |
- `let`, reassignment, `return` and call results follow the current array path as is (String move). Returning a parameter requires `copy` from the checker.
- Safe-mode output must contain no `unsafe` or `get_unchecked` (checked by run_all).

### 1.4 Contract (requires) text (`C` is a contract array expression, `CI` is an i128 index)
- `carr`: `Var` is the name as now; **if `StrLit`, `LIT(bytes)`** (not a String; a `&'static str`). Anything else is the current error as is.
- `StrLit` in the contract expression `c()`: `LIT(bytes)`.
- `len(s)`: the current text `(C.len() as i128)`.
- `s[i]`: `pruv_cidx_str(C, CI)`.
- `is_char_boundary(s, i)`: `pruv_cboundary(C, CI)`.

### 1.5 prelude
Order of attachment (each piece is joined with `"\n"` as now): user types → **(uses_str) `STR_PRELUDE`** → (safe mode) `SAFE_PRELUDE`, (u8) `SAFE_PRELUDE_U8`, (bool) `SAFE_PRELUDE_BOOL`, **(uses_str) `SAFE_PRELUDE_STR`** → (has requires and not trust) `CONTRACT_PRELUDE`, (u8) `CONTRACT_PRELUDE_U8`, (bool) `CONTRACT_PRELUDE_BOOL`, **(uses_str) `CONTRACT_PRELUDE_STR`**, contract types.

Each constant has one newline after the last line (the same shape as the u8 ones).

`STR_PRELUDE` (independent of mode):
```
#[allow(dead_code)]
#[inline]
fn pruv_str_boundary(a: &str, i: i64) -> bool { i >= 0 && (i as u64) <= (a.len() as u64) && a.is_char_boundary(i as usize) }
```

`SAFE_PRELUDE_STR`:
```
#[allow(dead_code)]
#[cold]
#[inline(never)]
fn pruv_slice_oob(lo: i64, hi: i64, len: usize) -> ! { panic!("pruv: string slice out of bounds: {}..{} (len {})", lo, hi, len) }
#[allow(dead_code)]
#[cold]
#[inline(never)]
fn pruv_slice_cut(lo: i64, hi: i64, len: usize) -> ! { panic!("pruv: UTF-8 boundary error: {}..{} (len {})", lo, hi, len) }
#[allow(dead_code)]
#[inline]
fn pruv_get_str(a: &str, i: i64) -> i64 { a.as_bytes()[pruv_idx(i, a.len())] as i64 }
#[allow(dead_code)]
#[inline]
fn pruv_substr(a: &str, lo: i64, hi: i64) -> ::std::string::String { if !(lo >= 0 && lo <= hi && (hi as u64) <= (a.len() as u64)) { pruv_slice_oob(lo, hi, a.len()) } if !(a.is_char_boundary(lo as usize) && a.is_char_boundary(hi as usize)) { pruv_slice_cut(lo, hi, a.len()) } ::std::string::String::from(&a[(lo as usize)..(hi as usize)]) }
```

`CONTRACT_PRELUDE_STR`:
```
#[allow(dead_code)]
#[inline]
fn pruv_cidx_str(a: &str, i: i128) -> i128 { if i >= 0 && i < (a.len() as i128) { a.as_bytes()[i as usize] as i128 } else { pruv_ud("array index out of range") } }
#[allow(dead_code)]
#[inline]
fn pruv_cboundary(a: &str, i: i128) -> bool { i >= 0 && i <= (a.len() as i128) && a.is_char_boundary(i as usize) }
```

### 1.6 Cleaning up the B0 gaps
- Add a StrLit branch to Py `c()` and `e()` (the text above); change the `Expr::StrLit` arm (currently Err) in Rs `c()` and `e()` to the text above.
- `is_char_boundary` and `substr` are handled in the builtin branch (the same place as `len`, `alloc`, `copy` and `print`: after `print`, before the user call). Make sure they do not fall into the user-function call path.
- Add `StrLit` → `"<str>"` to Py `show`.

## 2. LLVM backend (Py `llvmgen.py` / Rs `llvmgen.rs`)

### 2.1 Type and element information
- `lty("str") = ARR`, `vkind("str") = arr` (explicit branch). `elem_ty("str") = STR` (Py `vast.STR`, Rs `Some("str")`).
- Add `"str"` to the byte queries (Py `is_bytes`, Rs `is_bytes_ty`/`elem_ir`): GEP element `i8`, `pruv_copy_v2(.., 1, 1)` and `pruv_free_v2(.., 1, 1)` apply to str.
- A new query Py `is_strv(v)` / its Rs counterpart (`v.ty == Some("str")`). **In code reads and contract reads, str emits the same text as u8** (`load i8` → `zext i8 .. to i64` / `to i128`). The value-range check (store, alloc) does not apply to str (the checker blocks stores, and alloc does not create a str).
- At every place that handles arrays (`ir_params`, `bind_params`, `bind_contract_params`, slot creation, `load`, the scope ownership list, the temporary list, call-argument expansion, call-result `extractvalue`, `emit_ret`, entry, abi signature), handle str exactly like an array and carry `STR` in the `ty` of V/Slot (where `is_array(t)` is now used to branch, read it as `is_array(t) or t.name == "str"`).

### 2.2 Literal (code)
Decode the literal bytes into a UTF-8 string and register a global with `Mod.string(text)` (the same function, the same numbering and the same rendering used by the panic messages now; the trailing `\00` is an unused extra). The registration time is when that literal is evaluated (inside `ev`).
```
%p = call ptr @pruv_copy_v2(ptr @.str.N, i64 L, i64 1, i64 1)
```
Result `temp_arr(V("arr", %p, "L", STR), owned)` (L is the decimal text of the number of bytes, `0` for `""` — `pruv_copy_v2` returns NULL at len 0 and does not read the source).

### 2.3 Literal (contract `cev`)
`V("arr", "@.str.N", "L", STR)` with no copy. After that, `len`, Index and `is_char_boundary` are the same as for an ordinary str value.

### 2.4 Code expression IR (`S` = the str value `{a, b}`, numbering in `s.op` order as now)
- `s[i]`: after `index_ptr` (safe-mode `pruv_panic_oob` check + `getelementptr inbounds i8`)
  ```
  %x = load i8, ptr %g
  %y = zext i8 %x to i64
  ```
- `copy(s)`: the byte-array path as is (`pruv_copy_v2(.., 1, 1)`), result ty `STR`.
- `len(s)`: as now (`S.b`).
- `is_char_boundary(s, i)` (arguments evaluated in the order s → i, the same in both modes):
  ```
  %r = call i32 @pruv_str_boundary(ptr S.a, i64 S.b, i64 I)
  %c = icmp ne i32 %r, 0
  ```
  Result `V("i1", %c)`.
- `substr(s, lo, hi)` (arguments evaluated in the order s → lo → hi; if s is a temporary, it is freed at the end of the statement per the current temporary list):
  - Proof mode:
    ```
    %d = sub i64 HI, LO
    %g = getelementptr inbounds i8, ptr S.a, i64 LO
    %p = call ptr @pruv_copy_v2(ptr %g, i64 %d, i64 1, i64 1)
    ```
  - Safe mode:
    ```
    %p = call ptr @pruv_substr(ptr S.a, i64 S.b, i64 LO, i64 HI)
    %d = sub i64 HI, LO
    ```
  Result `temp_arr(V("arr", %p, %d, STR), owned)`. It is a new buffer, so it is independent of the lifetime of the source.

### 2.5 Contract IR
- Index (str): the current guard (`zext`, `icmp ult i128`, undefined `array index out of range`) and, after `trunc`, the same `getelementptr inbounds i8` → `load i8` → `zext i8 .. to i128` as u8.
- `is_char_boundary(s, i)`:
  ```
  %ln = zext i64 S.b to i128
  %ok = icmp ule i128 I, %ln
  %t = trunc i128 I to i64
  %u = select i1 %ok, i64 %t, i64 -1
  %r = call i32 @pruv_str_boundary(ptr S.a, i64 S.b, i64 %u)
  %c = icmp ne i32 %r, 0
  ```
  Result `V("i1", %c)`. (A negative i128 is larger than len in an unsigned comparison, so `-1` → false.)

### 2.6 Raw entry `abi_of` (Py `llvmgen.py` / Rs `abi.rs`)
- str parameter: the argument text is the same as for arrays, `ptr %a.Q.a, i64 %a.Q.n`, and in `pre` at that parameter's turn
  ```
  call void @pruv_check_utf8(ptr %a.Q.a, i64 %a.Q.n)
  ```
- `__typed` definition: made if any parameter is `[bool]` **or `str`**. The body is a copy with the lines that start with `  call void @pruv_check_bool(` **or** `  call void @pruv_check_utf8(` removed (the remaining text and blank-line rules are as in A5).
- str return: the same `ptr %out` path as an array return.

### 2.7 Declarations
`DECLS` → `DECLS_U8` (u8 **or bool or uses_str**) → `DECLS_BOOL` (bool) → `DECLS_STR` (uses_str):
```
DECLS_STR = "declare i32 @pruv_str_boundary(ptr nocapture readonly, i64, i64) nounwind willreturn memory(argmem: read)\n"
            "declare noalias ptr @pruv_substr(ptr nocapture readonly, i64, i64, i64) nounwind\n"
            "declare void @pruv_check_utf8(ptr nocapture readonly, i64) nounwind\n"
```

## 3. Bindings (`gen_bindings` in both implementations, Py `llvmgen.py` / Rs `bindings.rs`)
- `rust_ty`: `str` → `&str` / `::std::string::String`.
- Structs: after the `Pruv__ArrayBool` place, if `uses_str(prog)`, an `ALLOW` line and `#[repr(C)]\npub struct Pruv__Str { pub data: *mut u8, pub len: i64 }`.
- extern arguments: str → `*const u8`, `i64`. Return out: `*mut Pruv__Str`.
- extern block order: all `pruv_abi_*` lines → (if there is a `[bool]`-returning function) the `pruv_check_bool` line → (if there is a str-returning function) `    fn pruv_check_utf8(p0: *const u8, p1: i64);` → the marker line. The marker counts a str-returning function as an "array return" too.
- `typed_abi_name`: `__typed` if there is a `[bool]` **or `str`** parameter.
- Passing public-function arguments: str → `NAME.as_ptr()`, `NAME.len() as i64`.
- str-return body (4 lines, at the array-return place):
  ```
  let mut pruv__out = Pruv__Str { data: ::std::ptr::null_mut(), len: 0 };
  pruv_abi_F(.., &mut pruv__out);
  pruv_check_utf8(pruv__out.data, pruv__out.len);
  if pruv__out.len > 0 { ::std::string::String::from_utf8_unchecked(::std::vec::Vec::from_raw_parts(pruv__out.data, pruv__out.len as usize, pruv__out.len as usize)) } else { ::std::string::String::new() }
  ```
  (The marker reference line is attached to array-returning functions as now.)

## 4. Runtime `pruvc/runtime.c`
- Add one paragraph at the end of the header comment: `str (G2 B2): pruv_str_boundary(data, len, i) is the UTF-8 character boundary test (i == 0 or i == len, else 0 < i < len and data[i] is not a continuation byte); pruv_substr(data, len, lo, hi) checks the range then both boundaries ("pruv: string slice out of bounds: lo..hi (len n)" / "pruv: UTF-8 boundary error: lo..hi (len n)", exit 101) and returns a fresh copy (v2 layout 1,1); pruv_check_utf8(data, len) rejects a negative len (pruv_panic_repr(len, "str length")), NULL data with len > 0 (pruv_panic_repr(len, "str NULL data")) and ill-formed UTF-8 (Unicode Table 3-7) with pruv_panic_repr(offset, "str UTF-8, byte offset").`
- Four lines in the public prototype list (and also the missing `void pruv_check_bool(const uint8_t *data, int64_t len);`):
  ```c
  _Noreturn void pruv_panic_slice(const char *what, int64_t lo, int64_t hi, int64_t len);
  int32_t pruv_str_boundary(const uint8_t *data, int64_t len, int64_t i);
  void *pruv_substr(const uint8_t *data, int64_t len, int64_t lo, int64_t hi);
  void pruv_check_utf8(const uint8_t *data, int64_t len);
  ```
- Right after the `pruv_panic_repr` definition:
  ```c
  _Noreturn void pruv_panic_slice(const char *what, int64_t lo, int64_t hi, int64_t len) {
      PRUV_HOST_FLUSH();
      fflush(stdout);
      fprintf(stderr, "pruv: %s: %" PRId64 "..%" PRId64 " (len %" PRId64 ")\n", what, lo, hi, len);
      exit(101);
  }
  ```
- After the `pruv_check_bool` definition (outside `#ifdef`):
  ```c
  int32_t pruv_str_boundary(const uint8_t *data, int64_t len, int64_t i) {
      if (i == 0 || i == len)
          return 1;
      if (i < 0 || i > len)
          return 0;
      return (data[i] & 0xC0) != 0x80;
  }

  void *pruv_substr(const uint8_t *data, int64_t len, int64_t lo, int64_t hi) {
      if (!(lo >= 0 && lo <= hi && hi <= len))
          pruv_panic_slice("string slice out of bounds", lo, hi, len);
      if (!(pruv_str_boundary(data, len, lo) && pruv_str_boundary(data, len, hi)))
          pruv_panic_slice("UTF-8 boundary error", lo, hi, len);
      if (hi == lo)
          return NULL;
      return pruv_copy_v2(data + lo, hi - lo, 1, 1);
  }

  void pruv_check_utf8(const uint8_t *data, int64_t len) {
      if (len < 0)
          pruv_panic_repr(len, "str length");
      if (len == 0)
          return;
      if (data == NULL)
          pruv_panic_repr(len, "str NULL data");
      int64_t k = 0;
      while (k < len) {
          uint8_t b = data[k];
          int64_t need = 0;
          uint8_t lo = 0x80, hi = 0xBF;
          if (b < 0x80) {
              k++;
              continue;
          } else if (b >= 0xC2 && b <= 0xDF) {
              need = 1;
          } else if (b == 0xE0) {
              need = 2;
              lo = 0xA0;
          } else if ((b >= 0xE1 && b <= 0xEC) || b == 0xEE || b == 0xEF) {
              need = 2;
          } else if (b == 0xED) {
              need = 2;
              hi = 0x9F;
          } else if (b == 0xF0) {
              need = 3;
              lo = 0x90;
          } else if (b >= 0xF1 && b <= 0xF3) {
              need = 3;
          } else if (b == 0xF4) {
              need = 3;
              hi = 0x8F;
          } else {
              pruv_panic_repr(k, "str UTF-8, byte offset");
          }
          if (len - k <= need)
              pruv_panic_repr(k, "str UTF-8, byte offset");
          if (data[k + 1] < lo || data[k + 1] > hi)
              pruv_panic_repr(k, "str UTF-8, byte offset");
          for (int64_t j = 2; j <= need; j++)
              if ((data[k + j] & 0xC0) != 0x80)
                  pruv_panic_repr(k, "str UTF-8, byte offset");
          k += need + 1;
      }
  }
  ```
  (`pruv_copy_v2` must be defined before these functions; otherwise resolve it with a prototype.)
- `tests/abi/runtime_v1.c` is not modified.

## 5. Samples and tests (test owner)

### 5.1 Cleaning up must_reject (the main worker runs `git rm`)
Once the generation layer opens, the str samples that expected stage codegen are no longer rejected.
- To delete (main worker): 8 pairs `g2b_b0_{verify_layer,literal_verify,infer_layer,guard_order,guard_lit_first,codegen_layer,contract_literal_nv,guard_order_nv}`, 8 pairs `g2b_b1_ok_{len,boundary,boundary2,flow,param,loop,contract,infer}`.
- To move (the test owner copies the same body into a new file, changing only the first-line comment to mean "B2: passes through generation and execution"):
  - `examples/g2b_lit_len.pruv` ← `g2b_b1_ok_len` (literal byte length, byte reads)
  - `examples/g2b_boundary.pruv` ← `g2b_b1_ok_boundary`
  - `examples/g2b_boundary2.pruv` ← `g2b_b1_ok_boundary2` (multi-byte boundary substrings)
  - `examples/g2b_flow.pruv` ← `g2b_b1_ok_flow` (copy and return)
  - `examples/g2b_param.pruv` ← `g2b_b1_ok_param`
  - `examples/g2b_loop.pruv` ← `g2b_b1_ok_loop`
  - `examples/g2b_contract.pruv` ← `g2b_b1_ok_contract`
  - `tests/runtime/g2b_rt_infer.{pruv,json,rs}` ← `g2b_b1_ok_infer` (examples has no `--infer` mode, so it goes to runtime, with `flags_matrix: [["--infer"]]`)
  - New: `examples/g2b_ascii_substr.pruv` (an ASCII substring, with ensures on the result len and bytes), `examples/g2b_boundary_branch.pruv` (a boundary branch of the form `if is_char_boundary(s, i) { return substr(s, 0, i); } else { return copy(s); }`).
  - examples run in three modes (default, no-verify, trust-callers) × two backends: every path must return, and using a literal, copy or substr requires `! alloc`.
- `g2b_b0_infer_layer` is only deleted (`g2b_rt_infer` covers the same meaning).

### 5.2 runtime samples `tests/runtime/g2b_rt_*` (`.pruv`+`.json`+`.rs`, at least 12)
The driver `.rs` calls `sol::f("..")` (parameter `&str`) and prints the returned `String` with `println!("{}", ..)` or `.len()` and `.as_bytes()`. Include the following:
1. `escape`: the length and bytes of `"\"\\\n\r\t\0"`, and output of the returned string's bytes.
2. `nul`: `"a\0b"` has length 3, the middle byte is 0, and the returned String has len 3 (not truncated).
3. `empty`: `""` has length 0, `substr("",0,0)`, `copy("")`, `is_char_boundary("",0)`.
4. `multibyte`: compare the bytes, boundaries and substrings of Korean text and 😀 against the Rust-side expectation.
5. `big_bound`: `is_char_boundary(s, -1)`, `(s, len+1)`, `(s, 9223372036854775807)` and `(s, -9223372036854775807)` are false both in code and in requires (i128) (include `--trust-callers` in flags_matrix).
6. `ends`: boundaries 0 and len are true, `substr(s, 0, len(s))`, `substr(s, len(s), len(s))`.
7. `bad_slice_range` (flags `[["--no-verify"]]`, exit 101, stderr_contains `pruv: string slice out of bounds: 2..1 (len 3)`) — its must_reject twin with the same body is `g2b_b2_bad_slice_range` (verify/`string_slice_range`).
8. `bad_slice_cut` (`--no-verify`, of the form `substr("é", 0, 1)`, stderr_contains `pruv: UTF-8 boundary error: 0..1 (len 2)`) — its must_reject twin is `g2b_b2_bad_slice_cut` (verify/`utf8_boundary`). Also one negative-lo case (`-1..1`) (range wording).
9. `eval_order`: in the form `substr(f(), g(), h())`, the `! io` functions print the order with `print` (checked with stdout_lines); then check that the safe-mode failure also occurs after argument evaluation.
10. `reassign`: reassign a `let mut t: str` in a loop (the old value is freed), `alloc_balance: true`.
11. `nested_temp`: nested temporaries such as `len(substr(copy("..."), a, b))`, `is_char_boundary(substr(..), k)` and `substr(f(), ..)`, `alloc_balance: true`.
12. `return_owned`: `substr` from a local string and return it (the original is freed at the end of the function) — the caller reads the result's bytes; on the Rust side the returned String is printed. Check `@pruv_copy_v2(` with `llvm_fn_contains`.
- Put `gen_contains` (Rust: `pruv_substr`, `pruv_str_boundary`, `pruv_cidx_str`) and `ll_contains` (`@pruv_substr(`, `@pruv_str_boundary(`) in at least two samples.

### 5.3 Raw UTF-8 check `tests/abi/check_utf8_repr.py` (new file, in the style of `check_bool_repr.py`)
- Source: `fn tlen(s: str) -> i64 requires len(s) >= 1 && s[0] != 120 { return len(s); }` (120 = `x`). IR from both compilers + the ordinary runtime + a C caller (fills a buffer with the hexadecimal bytes in argv, calls `pruv_abi_tlen(buf, n)`, and prints the result).
- Cases (each in the default build and the `--trust-callers` build): valid `61`, `61 00 62` (output 3: NUL does not truncate), `C3 A9`, `F0 9F 98 80`; rejected (exit 101, stderr `pruv: invalid representation: K (str UTF-8, byte offset)`): an isolated continuation `61 80` (K=1), a truncated multi-byte sequence `E3 81` (K=0), overlong `C0 AF` (K=0) and `E0 80 AF` (K=0), a surrogate `ED A0 80` (K=0), beyond U+10FFFF `F4 90 80 80` (K=0) and `F5 80 80 80` (K=0), and the first byte `x` with invalid UTF-8 `78 FF` (the representation error comes before the requires violation: K=1).
- Add a stage `abi_utf8` to `tests/m3_all.py`.

### 5.4 ABI generated outputs
- `tests/abi/gen/g2b_str_ret.pruv` (a one-line signature, `str` argument and return, intermediate `substr`/`copy`) + an entry in `tests/abi/winci/calls.json` (of the form `sol::f("héllo", ..)`).
- `tests/abi/gen/g2a_bool_opt.pruv`: a `[bool]` argument + an `Option<i64>` return (the A5 confirmation audit recommendation: the sret combination) + a calls.json entry.
- `tests/abi/check_generated.py`: if a `__typed` define exists, add checks that its **signature is the same** as the original define, and that the `pruv_abi_*__typed` called by the bindings is defined in the IR (the A5 confirmation audit recommendation). The COFF symbol check is Windows-side work, so if it is left out, write the reason in the README.
- The winci output (`tests/abi/winci/out/*`) is regenerated by the main worker with `prepare.py`.

## 5.5 Decided after the audit
- `pruv_check_utf8` also rejects a negative length (`pruv: invalid representation: <len> (str length)`) and a NULL with positive length (`... (str NULL data)`) (because SMT assumes the parameter length is 0..MAX_LEN). The same gap has existed in the `[i64]`, `[u8]` and `[bool]` raw entries since before B2 — widening this to all arrays is deferred.
- `pruv_abi_<f>__typed` is a public symbol with no check (the same design as A5 bool). A C caller must call `pruv_abi_<f>`, and `__typed` is only for generated Rust bindings.
- The re-check (`pruv_check_utf8`) of the str return in the bindings is kept: it is the last defense to preserve the UTF-8 invariant of Rust `String` even in a call that violates requires under `--trust-callers` (O(n), proportional to the returned length).
- `willreturn memory(argmem: read)` is attached to the `pruv_str_boundary` declaration so that optimization can hoist calls inside a loop (it is not inlined because the runtime is a different object).

## 6. Verification (main worker)
Build → `run_all --backend both` (update the row list with `--list-rows`) → SMT 231 cmp → new samples with diff_trace (same only) → diff_parse → diff_compilers (must_reject + byte cross-check of the examples and runtime generated outputs between the two implementations) → m3_all (the new `abi_utf8`) → cli_also_llvm → inference --regress → fuzzer → cargo test → winci prepare/--check.
