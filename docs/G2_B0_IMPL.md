# G2 B0 implementation spec: the `str` frontend

Status: B0 batch implementation contract (written by the main worker). Both implementations (Python `pruvc/`, Rust `pruvc-rs/crates/`) emit the text below **byte for byte**. Basis: `docs/G2_SPEC.md` §0.0 decisions 7, 13, 14, 16 and §2.2, §3.5, §6.1, §6.3, §7.5. Anything not written below is done the same way as the existing array path.

## 0. Scope and decisions

1. B0 opens the `str` type and string literals only as far as the **lexer, parser, type/effect check, refinement, and dump**. Proof (B1) and Rust source/LLVM/ABI (B2) do not exist yet, so a program that uses `str` or a string literal is rejected in the proof layer with `verify`/`unsupported_type`, and with `--no-verify` in the generation layer with `codegen`/`unsupported_type` (decision 16).
2. The internal type name is `"str"`, the same as the source spelling (Py `vast.STR = Type("str")`, Rs type string `"str"`). Because the internal name and the source name are the same, the internal-name leak of decision 7 does not occur (no new rejection list).
3. `str` is **not an array.** Do not add it to `typeinfo.is_array`/`is_array_name`. Only the places that read it as a byte sequence (`len`, `copy`, index read) and the ownership places are allowed separately.
4. A literal's value is a UTF-8 **byte string** (Py `bytes`, Rs `Vec<u8>`). NUL is not a terminator and counts toward the length.
5. **The output for existing inputs does not change by a single byte** (parse/check dump, SMT, Rust source, IR, diagnostics). Only inputs that used `"` change (previously `bad_char`).

## 1. Lexer (Py `vparser.py` lex / Rs `lexer.rs` lex)

- On meeting `"` (before comments and other tokens, that is, at a token start position), read a string token. Inside the string, `//`, brackets, `|` and so on are ordinary characters.
- Look at one character (code point) at a time, left to right. The column number is, as before, **per character** (`pos - lstart + 1`).
  1. `"` → end of token.
  2. `\` → look at the next character.
     - If at end of input → `string_unterminated` (below; the position is the opening quote).
     - `"`→0x22, `\`→0x5C, `n`→0x0A, `r`→0x0D, `t`→0x09, `0`→0x00.
     - Any other character (including an actual line break) → `string_escape`, at the position of **that `\`**.
  3. An actual line break (`\n`) → `string_character` (line-break message), at the position of that line-break character (a column on the same line).
  4. A code point in 0x00~0x1F (excluding line break) or 0x7F → `string_character` (control-character message), at the position of that character.
  5. Any other character appends its UTF-8 bytes to the value (non-ASCII control characters U+0080 and above are allowed).
  6. End of input without a closing quote → `string_unterminated`, at the position of the opening quote.
- Checks are made in the order characters are met and **stop at the first error**.
- Token: kind `"str"` (Rs `Kind::Str`), `val` is **the original text as is** (including the opening and closing quotes and backslashes, e.g. `"a\n"` is 4+2 characters), `line`/`col` are those of the opening quote, `end` is the column after the closing quote (`col + number of characters in the original text`). The decoded bytes are obtained by the parser unescaping `val` again (the text has already been checked, so it cannot fail). When a string token appears in a wrong place, the existing `expected ..., found %r` message uses the repr of the original text in `val` unchanged (Py `%r` = Rs `repr_str`).
- `\r`: in Py, `open()` uses universal newlines, and in Rs the normalization in `parse_source` means there is no actual CR in file input. If a CR comes directly into `parse()`, it is rejected by item 4 (control character).
- The set of allowed `|` lexings (`_bar_after_type` / its counterpart in `lexer.rs`) is **not changed**. So `x: str | 0..=1` is `bad_char` as it is now (there is no refinement syntax for `str`).

### 1.1 Diagnostic text (all stage `parse`)

| code | message | fix |
|---|---|---|
| `string_unterminated` | `unterminated string literal` | `close it with "` |
| `string_escape` | `unsupported escape %r in a string literal` (`%r` = the Python repr of the two-character string consisting of the backslash and the character after it) | `use one of \" \\ \n \r \t \0` |
| `string_character` (line break) | `a string literal cannot span lines` | `close the string before the line break, or write \n` |
| `string_character` (control character) | `a string literal cannot contain the control character %r` (`%r` = the Python repr of that one character) | `write it as an escape (\n, \r, \t, \0) or remove it` |

The `\"`, `\\`, `\n` and so on inside the fix text are **literal backslash characters** (e.g. `use one of \" \\ \n \r \t \0` is `use one of ` + backslash + quote + space + two backslashes + …). Example: `"\x41"` → message `unsupported escape '\\x' in a string literal` (Python repr emits a backslash as `\\`).

## 2. Parser

- primary: for a `str` token, `StrLit(line, col, value=decoded bytes, ty=None)`. The position (just before or after the IntLit branch) is free, but it must not change the result of any other branch. `"ab"[0]` becomes `Index(StrLit, ..)` through the existing postfix.
- Type name `str` → `STR` (Rs `"str".to_string()`). The position is next to the `i64` and `bool` branches.
- `Option<str>` and `Result<str>`: send them to the same `unsupported_type` line as the existing `u8` and `i32` (the existing `unsupported` wording of the `Option<str> is not supported` family). That is, add `"str"` to the condition `e.val[0].isupper() or e.val in ("u8", "i32")`.
- `[str]` is `syntax` (`only [i64], [u8] and [bool] arrays exist`) as it is now. Do not change it.
- Do not change the internal-name rejection list (`unit`, `array`, …, `array_i32`).
- Py source reading: change `open(path)` in `pruvc.py` to `open(path, encoding="utf-8")` (Rs `read_source` is already strict UTF-8). Other newline handling stays the same.

## 3. AST

- Py `vast.py`: `STR = Type("str")`. Expression node:
  ```python
  @dataclass
  class StrLit(Expr):
      value: bytes
      ty: Optional[Type] = None
  ```
  (Place it after BoolLit.)
- Rs `ast.rs`: `pub struct StrLit { pub line: i64, pub col: i64, pub value: Vec<u8>, pub ty: Ty }`, `Expr::StrLit(StrLit)` (after BoolLit). Add an arm to `line()`/`col()`. Change the header comment "14 expressions" to "15 expressions" and "33 nodes" to "34 nodes".

## 4. Type and effect check (Py `check.py` / Rs `check.rs`)

Add `STR`/`"str"` to `typeinfo` as a built-in name: Py `"str"` in `BUILTIN_TYPE_NAMES`, `_BUILTIN_PRINT["str"] = "str"`; Rs `BUILTIN_TYPE_NAMES: [&str; 9]` (+ the length 8→9 in the test), `"str" => "str"` in `type_name`.

| Place | Rule |
|---|---|
| `StrLit` expression | Type `str`. If not in a contract (`c == False`), add `"alloc"` to `used_effects`. No effect inside a contract. |
| `len(x)` | `x` is an array **or `str`**. Otherwise the existing `type_mismatch` `expected [i64], found %s` as before. Result `i64`. |
| `copy(x)` | Forbidden in contracts (existing `copy not allowed in contracts`). `x` is an array or `str`, and the result is the input type. `alloc` effect (existing). |
| `x[i]` read | `x` is an array or `str` (error text as before). If `str`, the result is `i64`. |
| `is_char_boundary(s, i)` | Allowed in both code and contracts. `arity(2)` (the existing arity wording), `expect(s, STR)`, `expect(i, I64)`, result `bool`, no effect. |
| `substr(s, lo, hi)` | In a contract, `effect_in_contract` `substr not allowed in contracts` (before arity, the same order as copy). `arity(3)`, `expect(s, STR)`, `expect(lo, I64)`, `expect(hi, I64)`, `alloc` effect, result `str`. |
| Position of the new builtin branches | After the `copy` branch, before the `print` branch (`substr` after `is_char_boundary`). |
| Reserved function names | Add `"is_char_boundary"` and `"substr"` to `("len", "alloc", "copy", "print")` (the wording `%s is a builtin name` unchanged). |
| `NAME[i] = x` | Right after `lookup`, **before** the `not_array` check: if the target type is `str`, type/`immutable_string`, message `%s is a str; its bytes cannot be changed`, fix `build a new str with substr() or copy() instead`. The position is the assignment statement. |
| Ownership (`let`, reassignment, `return`) | Change the existing condition `if is_array(T): array_source(...)` to `is_array(T) or T == STR`. `array_source` passes if the value is a `Call` or a **`StrLit`**; the local-variable rule for return is unchanged (returning a parameter needs `copy`). Failure wording: for arrays, the existing text; for `str`, message `a str value here must come from a string literal, copy(), substr() or a function call`, and the fix is the same as for arrays: `write copy(x) to make an explicit copy (needs \`! alloc\`)`. (Because `expect` comes before `array_source`, assigning between `str` and `[u8]` yields `type_mismatch` first.) |
| `==`, `!=` | Right after the existing `is_array(lt)` check: if `lt == STR` (in both code and contracts), type/`eq_type`, message `str values cannot be compared with ==`, fix `compare lengths and bytes: len(a) == len(b) && forall k in 0..len(a): a[k] == b[k]`. |
| Struct and enum fields | Add `or ty == STR` to the `field_type` condition (wording unchanged). |
| `print(s)` | The existing `print_type`, unchanged. |
| `alloc` hint | Not changed (`str` is not an array, so there is no hint). |

The \` in the fix text is a literal backtick. The corresponding functions in Rs (the inline places of `expect_array`/`is_array_name`) use the same decision and the same text.

## 5. Refinement (Py `refine.py` / Rs `refine.rs`)

- There is no refinement syntax for `str`. Only add `Expr::StrLit(_) => Vec::new()` to Rs `kids` (Py `_kids` is automatic).

## 6. Guard for unimplemented layers (Py `typeinfo.py` / Rs `typeinfo.rs`)

- `_g2_hit(ty, skip)` (the Rs counterpart) = `((is_array(ty) and ty != ARRAY) or ty == STR) and ty.name not in skip`.
- Order of `first_g2_unimplemented(prog, skip)` (in function declaration order, decided at the first function that is hit):
  1. If any parameter is hit, `(fn.line, fn.col, that type)` (in parameter order, first one).
  2. If the return type is hit, `(fn.line, fn.col, ret)`.
  3. Otherwise, the one with the smallest `(line, col)` among **all candidate positions** of that function: (a) the position and type of any `Let` whose type is hit anywhere in the body (including nested blocks), and (b) when `"str"` is not in skip, the position of every `StrLit` in **all expressions** of `requires`, `ensures` and every body statement (conditions, invariants, decreases, assert, return values, assignment indexes and values, expression statements, match targets, and all nested expressions), with type `STR`.
  4. If there is no candidate, go to the next function.
- Py may find StrLit by an ordinary traversal of dataclass fields. Rs traverses every variant of `Stmt` and `Expr` **without a wildcard** (so that compilation breaks when nodes are added later).
- (The result when only arrays are present is the same as now: the existing depth-first source order = the smallest position.)
- `g2_unimplemented_error`: if the hit type is `str`, message `str is not supported yet: the %s layer is not implemented` (`%s` = layer or stage), fix default `do not use str yet`. For arrays, the existing text unchanged.
- **Proof-layer guard (new):** at the very start of Py `verify.verify_program` (before building the model and z3), and at the very start of Rs `pruv-proof` `lib.rs` `verify_program_opts` (and also at the very start of any other public verification entry in Rs that does not go through this one):
  ```python
  g2err = g2_unimplemented_error(prog, "verify", skip=("array_u8", "array_bool"))  # G2 B0
  if g2err is not None:
      return [g2err]
  ```
  `--infer` and `--show-inferred` also end before this point (no record).
- The 6 generation-layer guards (Py `pruvc.py`, `codegen.py`, `llvmgen.py`; Rs `driver.rs`, `codegen.rs`, `llvmgen.rs`) are not modified. Since `str` is not in skip, the `_g2_hit` change alone blocks `str` (stage `codegen`).

## 7. Gaps in the later layers (for Rs to compile; not executed)

They cannot be reached in B0 because of the guards. Still, return an `Err` so that an internal error does not become a panic.

- `expr_ty` in `codegen.rs` and `llvmgen.rs`: `Expr::StrLit(x) => x.ty.clone()` (the same shape as other literals, adapted to the actual function shape).
- `emit_common.rs` `show`: `Expr::StrLit(_) => "<str>".to_string()` (to be decided in B2).
- `pruv-proof` `symbolic.rs` `ev`: `Expr::StrLit(_) => Err("ev: string literal is not supported yet".to_string())` (adapted to the actual error type).
- `pruv-proof` `infer.rs` `kids` → an empty list, `clone_e` → clone as is.
- Py `verify.ev`, `codegen` and `llvmgen` are not modified (unreachable because of the guards).

## 8. dump (Rs `dump.rs` / test `tests/diff_py_adapter.py`)

- `StrLit` node: kind `"StrLit"`, fields `value`, `ty`. `value` is the **lowercase hexadecimal string** of the bytes (2 characters per byte, `""` for the empty string). Examples: `"안"` → `"ec9588"`, `"\0a"` → `"0061"`.
  - Rs: `node("StrLit", Some((x.line, x.col)), vec![("value", Json::Str(hex)), ("ty", ty(&x.ty))])` (adapted to the actual Json constructor).
  - Py: `NODE_FIELDS["StrLit"] = ("value", "ty")`, and in `ser` a `bytes` → `v.hex()` branch (before the current RuntimeError).
- In check mode, `ty` is `"str"`.

## 9. Samples (test worker)

### 9.1 `tests/must_reject/` (`.pruv` + `.json` `{"stage":..,"code":..[,"flags":[..]]}`)

Write each sample so that it passes every other check before the target error (including declaring the `! alloc` effect).

| Name | Content | stage/code |
|---|---|---|
| `g2b_escape` | the literal `"\xFF"` | parse/`string_escape` |
| `g2b_escape_newline` | an actual line break right after `\` | parse/`string_escape` |
| `g2b_unterminated` | a literal not closed until EOF | parse/`string_unterminated` |
| `g2b_unterminated_escape` | the file ends with `"ab\` | parse/`string_unterminated` |
| `g2b_newline` | an actual line break inside a literal | parse/`string_character` |
| `g2b_control` | an actual TAB character inside a literal | parse/`string_character` |
| `g2b_option_str` | `Option<str>` | parse/`unsupported_type` |
| `g2b_store` | `let mut s: str = "ab"; s[0] = 1;` | type/`immutable_string` |
| `g2b_param_store` | `s[0] = 1;` on a parameter `s: str` | type/`immutable_string` |
| `g2b_alias` | `let s: str = t;` (t is a str parameter) | type/`array_alias` |
| `g2b_param_return` | `return s;` (s is a str parameter) | type/`array_alias` |
| `g2b_field` | a struct str field | type/`field_type` |
| `g2b_to_bytes` | assign a str to a `[u8]` local | type/`type_mismatch` |
| `g2b_from_bytes` | assign a `[u8]` to a str local | type/`type_mismatch` |
| `g2b_eq` | whole-string `==` in code | type/`eq_type` |
| `g2b_eq_contract` | whole-string `==` in requires | type/`eq_type` |
| `g2b_contract_copy` | `copy(s)` inside requires | type/`effect_in_contract` |
| `g2b_contract_substr` | `substr(s, 0, 0)` inside requires | type/`effect_in_contract` |
| `g2b_boundary_type` | `is_char_boundary(b, 0)` (b is `[u8]`) | type/`type_mismatch` |
| `g2b_substr_type` | `substr(s, true, 1)` | type/`type_mismatch` |
| `g2b_reserved` | a function named `substr` | type/`reserved` |
| `g2b_print` | `print("hi");` (`! alloc, io`) | type/`print_type` |
| `g2b_missing_alloc` | `len("ab")` in code without an effect declaration | effect/`missing_effect` |
| `g2b_b0_verify_layer` | a valid str program that passes the frontend (literal, len, index, copy, substr, is_char_boundary, str return) | verify/`unsupported_type` |
| `g2b_b0_literal_verify` | only a literal, without a str type: `fn f() -> i64 ! alloc { return len("abc"); }` | verify/`unsupported_type` |
| `g2b_b0_infer_layer` | a valid str program with a while loop, flags `["--infer"]` | verify/`unsupported_type` |
| `g2b_b0_codegen_layer` | the same kind as `g2b_b0_verify_layer`, flags `["--no-verify"]` | codegen/`unsupported_type` |
| `g2b_b0_contract_literal_nv` | a literal only in requires (`requires len(s) >= len("a")`, s is `[u8]`, no effect), flags `["--no-verify"]` | codegen/`unsupported_type` |
| `g2b_b0_guard_order` | no str parameter; a str Let inside a nested if (5:5) + a later literal, `cex_contains` `"line": 5, "col": 5` | verify/`unsupported_type` |
| `g2b_b0_guard_order_nv` | an ensures literal (4:25) comes before the body literal, flags `["--no-verify"]`, `cex_contains` `"line": 4, "col": 25` | codegen/`unsupported_type` |
| `g2b_b0_guard_lit_first` | a literal (4:20) comes before a later str Let (5:3), `cex_contains` `"line": 4, "col": 20` | verify/`unsupported_type` |

Pinned wording (`cex_contains`, audit recommendation): `g2b_eq` → `str values cannot be compared with ==`, `g2b_alias` and `g2b_param_return` → `a str value here must come from a string literal`.

### 9.2 `tests/parse_edge/` (cross-check of the parse dump between the two implementations)

- `str_ok_literals.pruv`: ASCII, Korean, 2/3/4-byte characters (`é`, `한`, `😀`), the empty string, one containing `\0`, all 6 escapes, `//`, `(`, `]`, `|` and `'` inside a string, a literal index `"ab"[1]`, several literals on one line (column numbers), a comment on the same line after a literal.
- Error samples (one per file): `str_err_escape_x.pruv`, `str_err_escape_quote_at_eof.pruv` (`"\` EOF), `str_err_unterminated.pruv`, `str_err_newline.pruv`, `str_err_tab.pruv`, `str_err_del.pruv` (0x7F), `str_err_ctrl_after_multibyte.pruv` (a control character after Korean text: checks that the column is per character), `str_err_misplaced.pruv` (`let "a" = 1;` → the existing syntax wording with the repr of the original text), `str_err_quote_in_repr.pruv` (`let "it's" = 1;`).
- The existing `badchar_dquote.pruv` is now a string: fix only the first-line comment to "now parses successfully as a string literal (print_type in check)" and leave the content.

### 9.3 `tests/check_edge/` (cross-check of the check dump between the two implementations)

- `ok_str_ops.pruv`: str parameter and return, literal, `len`, index, `copy`, `substr`, `is_char_boundary` (in code and contracts), a literal inside a contract, whole reassignment of `let mut s: str`, returning a local str, calling a user function with a literal argument, a byte read inside a loop.
- Error samples: `str_immutable.pruv`, `str_eq_contract.pruv`, `str_option_result.pruv` (`Result<str>`), `str_field_enum.pruv` (an enum payload str → field_type), `str_alias_reassign.pruv` (the reassignment RHS is another str variable).

### 9.4 Harness

- `tests/diff_parse.py`: add `string_escape`, `string_unterminated` and `string_character` to the required parse code set (`REQUIRED_CODES`), and `immutable_string` to the required check code set (`CHECK_CODES`). Update the node-count comment.
- `tests/diff_py_adapter.py`: §8. If the Python source reading is `open()`, use `encoding="utf-8"`.
