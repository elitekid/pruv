# G2 B0 구현 명세: `str` 앞단

상태: B0 묶음 구현 계약(메인 작성). 두 판(Python `pruvc/`, Rust `pruvc-rs/crates/`)은 아래 글자를 **바이트 그대로** 낸다. 근거: `docs/G2_SPEC.md` 0.0절 결정 7·13·14·16, 2.2·3.5·6.1·6.3·7.5절. 아래에 적지 않은 것은 기존 배열 길과 같게 한다.

## 0. 범위와 결정

1. B0은 `str` 타입과 문자열 리터럴을 **렉서·파서·타입/효과 검사·정제·dump**까지만 연다. 증명(B1)·Rust 소스/LLVM/ABI(B2)는 아직 없으므로 `str`이나 문자열 리터럴을 쓰는 프로그램은 증명 층에서 `verify`/`unsupported_type`, `--no-verify`면 생성 층에서 `codegen`/`unsupported_type`으로 거부한다(결정 16).
2. 내부 타입 이름은 소스 철자와 같은 `"str"`이다(Py `vast.STR = Type("str")`, Rs 타입 문자열 `"str"`). 내부 이름과 소스 이름이 같으므로 결정 7의 내부 이름 누출은 생기지 않는다(새 거부 목록 없음).
3. `str`은 **배열이 아니다.** `typeinfo.is_array`/`is_array_name`에 넣지 않는다. 바이트 열로 읽는 자리(`len`·`copy`·색인 읽기)와 소유권 자리만 따로 허용한다.
4. 리터럴 값은 UTF-8 **바이트열**이다(Py `bytes`, Rs `Vec<u8>`). NUL은 종결자가 아니며 길이에 들어간다.
5. **기존 입력의 출력은 한 바이트도 바뀌지 않는다**(parse/check dump, SMT, Rust 소스, IR, 진단). 바뀌는 것은 `"`를 쓰던 입력뿐이다(전에는 `bad_char`).

## 1. 렉서(Py `vparser.py` lex / Rs `lexer.rs` lex)

- `"`를 만나면(주석·다른 토큰보다 먼저, 즉 토큰 시작 위치에서) 문자열 토큰을 읽는다. 문자열 안의 `//`·괄호·`|` 등은 일반 문자다.
- 왼쪽에서 오른쪽으로 한 문자(코드 포인트)씩 본다. 열 번호는 기존처럼 **문자 단위**(`pos - lstart + 1`)다.
  1. `"` → 토큰 끝.
  2. `\` → 다음 문자를 본다.
     - 입력 끝이면 → `string_unterminated`(아래, 위치는 여는 따옴표).
     - `"`→0x22, `\`→0x5C, `n`→0x0A, `r`→0x0D, `t`→0x09, `0`→0x00.
     - 그 밖의 문자(실제 줄바꿈 포함) → `string_escape`, 위치는 **그 `\`**.
  3. 실제 줄바꿈(`\n`) → `string_character`(줄바꿈 문구), 위치는 그 줄바꿈 문자(같은 줄의 열).
  4. 코드 포인트가 0x00~0x1F(줄바꿈 제외) 또는 0x7F → `string_character`(제어 문자 문구), 위치는 그 문자.
  5. 그 밖의 문자는 그 문자의 UTF-8 바이트를 값에 붙인다(비ASCII 제어 문자 U+0080 이상은 허용).
  6. 닫는 따옴표 없이 입력 끝 → `string_unterminated`, 위치는 여는 따옴표.
- 검사는 문자를 만나는 순서대로 하고 **첫 오류**에서 멈춘다.
- 토큰: kind `"str"`(Rs `Kind::Str`), `val`은 **원문 그대로**(여는·닫는 따옴표와 역슬래시 포함, 예 `"a\n"` 4+2글자), `line`/`col`은 여는 따옴표, `end`는 닫는 따옴표 다음 열(`col + 원문 문자 수`). 디코드한 바이트는 파서가 `val`을 다시 풀어 얻는다(이미 검사된 원문이므로 실패 없음). 잘못된 자리에 문자열 토큰이 오면 기존 `expected ..., found %r` 문구가 `val` 원문의 repr을 그대로 쓴다(Py `%r` = Rs `repr_str`).
- `\r`: Py는 `open()` universal newline, Rs는 `parse_source`의 정규화로 파일 입력에는 실제 CR이 없다. 직접 `parse()`에 CR이 들어오면 4번(제어 문자)으로 거부한다.
- `|` 렉싱 허용 집합(`_bar_after_type` / `lexer.rs` 대응)은 **바꾸지 않는다**. 그래서 `x: str | 0..=1`은 지금처럼 `bad_char`다(`str` 정제 문법 없음).

### 1.1 진단 글자(stage 모두 `parse`)

| code | message | fix |
|---|---|---|
| `string_unterminated` | `unterminated string literal` | `close it with "` |
| `string_escape` | `unsupported escape %r in a string literal` (`%r` = 역슬래시와 그 다음 문자 두 글자 문자열의 Python repr) | `use one of \" \\ \n \r \t \0` |
| `string_character`(줄바꿈) | `a string literal cannot span lines` | `close the string before the line break, or write \n` |
| `string_character`(제어 문자) | `a string literal cannot contain the control character %r` (`%r` = 그 한 문자의 Python repr) | `write it as an escape (\n, \r, \t, \0) or remove it` |

fix 글자 안의 `\"`·`\\`·`\n` 등은 **역슬래시 문자 그대로**다(예: `use one of \" \\ \n \r \t \0`는 `use one of ` + 백슬래시 + 따옴표 + 공백 + 백슬래시 두 개 + …). 예: `"\x41"` → message `unsupported escape '\\x' in a string literal` (Python repr이 역슬래시를 `\\`로 낸다).

## 2. 파서

- primary: `str` 토큰이면 `StrLit(line, col, value=디코드한 바이트, ty=None)`. 위치(IntLit 분기 바로 앞 또는 뒤)는 자유이나 다른 분기 결과를 바꾸지 않는다. `"ab"[0]`은 기존 postfix로 `Index(StrLit, ..)`가 된다.
- 타입 이름 `str` → `STR`(Rs `"str".to_string()`). 위치는 `i64`·`bool` 분기 옆.
- `Option<str>`·`Result<str>`: 기존 `u8`·`i32`와 같은 `unsupported_type` 줄(`Option<str> is not supported` 계열의 기존 `unsupported` 문구)로 보낸다. 즉 조건 `e.val[0].isupper() or e.val in ("u8", "i32")`에 `"str"`을 더한다.
- `[str]`은 지금처럼 `syntax`(`only [i64], [u8] and [bool] arrays exist`). 바꾸지 않는다.
- 내부 이름 거부 목록(`unit`·`array`·…·`array_i32`)은 바꾸지 않는다.
- Py 소스 읽기: `pruvc.py`의 `open(path)`를 `open(path, encoding="utf-8")`로(Rs `read_source`는 이미 엄격 UTF-8). 그 밖의 줄바꿈 처리는 그대로.

## 3. AST

- Py `vast.py`: `STR = Type("str")`. 식 노드
  ```python
  @dataclass
  class StrLit(Expr):
      value: bytes
      ty: Optional[Type] = None
  ```
  (BoolLit 다음에 둔다.)
- Rs `ast.rs`: `pub struct StrLit { pub line: i64, pub col: i64, pub value: Vec<u8>, pub ty: Ty }`, `Expr::StrLit(StrLit)`(BoolLit 다음). `line()`/`col()`에 팔 추가. 머리 주석 "식 14"→"식 15", "33 노드"→"34 노드".

## 4. 타입·효과 검사(Py `check.py` / Rs `check.rs`)

`typeinfo`에 `STR`/`"str"`을 내장 이름으로 더한다: Py `BUILTIN_TYPE_NAMES`에 `"str"`, `_BUILTIN_PRINT["str"] = "str"`; Rs `BUILTIN_TYPE_NAMES: [&str; 9]`(+ 시험의 길이 8→9), `type_name`에 `"str" => "str"`.

| 자리 | 규칙 |
|---|---|
| `StrLit` 식 | 타입 `str`. 계약이 아니면(`c == False`) `used_effects`에 `"alloc"`. 계약 안에서는 효과 없음. |
| `len(x)` | `x`가 배열 **또는 `str`**. 아니면 기존 그대로 `type_mismatch` `expected [i64], found %s`. 결과 `i64`. |
| `copy(x)` | 계약 금지(기존 `copy not allowed in contracts`). `x`가 배열 또는 `str`, 결과는 입력 타입. `alloc` 효과(기존). |
| `x[i]` 읽기 | `x`가 배열 또는 `str`(오류 글자 기존 그대로). `str`이면 결과 `i64`. |
| `is_char_boundary(s, i)` | 코드·계약 모두 허용. `arity(2)`(기존 arity 문구), `expect(s, STR)`, `expect(i, I64)`, 결과 `bool`, 효과 없음. |
| `substr(s, lo, hi)` | 계약이면 `effect_in_contract` `substr not allowed in contracts`(arity보다 먼저, copy와 같은 순서). `arity(3)`, `expect(s, STR)`, `expect(lo, I64)`, `expect(hi, I64)`, `alloc` 효과, 결과 `str`. |
| 새 builtin 분기 위치 | `copy` 분기 다음, `print` 분기 앞(`is_char_boundary` 다음 `substr`). |
| 예약 함수 이름 | `("len", "alloc", "copy", "print")`에 `"is_char_boundary"`, `"substr"`을 더한다(문구 `%s is a builtin name` 그대로). |
| `NAME[i] = x` | `lookup` 바로 뒤, `not_array` 검사 **앞**: 대상 타입이 `str`이면 type/`immutable_string`, message `%s is a str; its bytes cannot be changed`, fix `build a new str with substr() or copy() instead`. 위치는 대입 문장. |
| 소유권(`let`·재대입·`return`) | 기존 `if is_array(T): array_source(...)` 조건을 `is_array(T) or T == STR`로. `array_source`는 값이 `Call`이거나 **`StrLit`**이면 통과, return의 지역 변수 규칙은 그대로(매개변수 반환은 `copy` 필요). 실패 문구: 배열은 기존 그대로, `str`이면 message `a str value here must come from a string literal, copy(), substr() or a function call`, fix는 배열과 같은 `write copy(x) to make an explicit copy (needs \`! alloc\`)`. (`expect`가 `array_source`보다 먼저라서 `str`↔`[u8]` 대입은 `type_mismatch`가 먼저 난다.) |
| `==`·`!=` | 기존 `is_array(lt)` 검사 바로 다음: `lt == STR`이면 (코드·계약 모두) type/`eq_type`, message `str values cannot be compared with ==`, fix `compare lengths and bytes: len(a) == len(b) && forall k in 0..len(a): a[k] == b[k]`. |
| 구조체·열거형 필드 | `field_type` 조건에 `or ty == STR`(문구 그대로). |
| `print(s)` | 기존 `print_type` 그대로. |
| `alloc` 힌트 | 바꾸지 않는다(`str`은 배열이 아니므로 힌트 없음). |

fix 글자의 \` 는 백틱 그대로다. Rs의 대응 함수(`expect_array`/`is_array_name` 인라인 자리)도 같은 판정·같은 글자로.

## 5. 정제(Py `refine.py` / Rs `refine.rs`)

- 정제 문법은 `str`에 없다. Rs `kids`에 `Expr::StrLit(_) => Vec::new()`만 더한다(Py `_kids`는 자동).

## 6. 미구현 층 가드(Py `typeinfo.py` / Rs `typeinfo.rs`)

- `_g2_hit(ty, skip)`(Rs 대응) = `((is_array(ty) and ty != ARRAY) or ty == STR) and ty.name not in skip`.
- `first_g2_unimplemented(prog, skip)` 순서(함수 선언 순서로, 첫 번째로 걸린 함수에서 결정):
  1. 매개변수 중 하나라도 걸리면 `(fn.line, fn.col, 그 타입)`(첫 매개변수 순).
  2. 반환 타입이 걸리면 `(fn.line, fn.col, ret)`.
  3. 그렇지 않으면 그 함수의 **후보 위치 전체** 중 `(line, col)`이 가장 작은 것: (a) 본문 어디든(중첩 블록 포함) 타입이 걸리는 `Let`의 위치와 타입, (b) `"str"`이 skip에 없을 때 `requires`·`ensures`·본문 모든 문장의 **모든 식**(조건·불변식·decreases·assert·return 값·대입의 색인·값·식 문장·match 대상·중첩 식 전부)에 있는 `StrLit`의 위치와 타입 `STR`.
  4. 후보가 없으면 다음 함수.
- Py는 dataclass 필드를 일반 순회해 StrLit을 찾아도 된다. Rs는 `Stmt`·`Expr` 모든 변형을 **와일드카드 없이** 순회한다(앞으로 노드가 늘면 컴파일이 깨지도록).
- (배열만 있을 때의 결과는 지금과 같다: 기존 깊이 우선 소스 순서 = 가장 작은 위치.)
- `g2_unimplemented_error`: 걸린 타입이 `str`이면 message `str is not supported yet: the %s layer is not implemented`(`%s` = layer 또는 stage), fix 기본값 `do not use str yet`. 배열이면 기존 글자 그대로.
- **증명 층 가드(새로):** Py `verify.verify_program` 맨 앞(모델·z3를 만들기 전), Rs `pruv-proof` `lib.rs` `verify_program_opts` 맨 앞(Rs의 다른 공개 검증 진입이 이것을 거치지 않으면 그 진입 맨 앞에도):
  ```python
  g2err = g2_unimplemented_error(prog, "verify", skip=("array_u8", "array_bool"))  # G2 B0
  if g2err is not None:
      return [g2err]
  ```
  `--infer`·`--show-inferred`도 이 앞에서 끝난다(기록 없음).
- 생성 층 가드 6곳(Py `pruvc.py`·`codegen.py`·`llvmgen.py`, Rs `driver.rs`·`codegen.rs`·`llvmgen.rs`)은 고치지 않는다. skip에 `str`이 없으므로 `_g2_hit` 변경만으로 `str`을 막는다(stage `codegen`).

## 7. 뒤 층의 빈틈(Rs 컴파일용, 실행되지 않음)

가드 때문에 B0에서는 닿지 않는다. 그래도 내부 오류가 패닉이 되지 않게 `Err`를 돌린다.

- `codegen.rs`·`llvmgen.rs`의 `expr_ty`: `Expr::StrLit(x) => x.ty.clone()`(다른 리터럴과 같은 모양, 실제 함수 모양에 맞춤).
- `emit_common.rs` `show`: `Expr::StrLit(_) => "<str>".to_string()`(B2에서 정함).
- `pruv-proof` `symbolic.rs` `ev`: `Expr::StrLit(_) => Err("ev: string literal is not supported yet".to_string())`(실제 오류 타입에 맞춤).
- `pruv-proof` `infer.rs` `kids` → 빈 목록, `clone_e` → 그대로 복제.
- Py `verify.ev`·`codegen`·`llvmgen`은 고치지 않는다(가드로 닿지 않음).

## 8. dump(Rs `dump.rs` / 시험 `tests/diff_py_adapter.py`)

- `StrLit` 노드: kind `"StrLit"`, 필드 `value`, `ty`. `value`는 바이트의 **소문자 16진 문자열**(바이트마다 2글자, 빈 문자열은 `""`). 예: `"안"` → `"ec9588"`, `"\0a"` → `"0061"`.
  - Rs: `node("StrLit", Some((x.line, x.col)), vec![("value", Json::Str(hex)), ("ty", ty(&x.ty))])`(실제 Json 생성자에 맞춤).
  - Py: `NODE_FIELDS["StrLit"] = ("value", "ty")`, `ser`에 `bytes` → `v.hex()` 분기(지금 RuntimeError 앞).
- check 모드의 `ty`는 `"str"`.

## 9. 표본(시험 작업자)

### 9.1 `tests/must_reject/`(`.pruv` + `.json` `{"stage":..,"code":..[,"flags":[..]]}`)

각 표본은 목표 오류 전의 다른 검사를 모두 통과하게 쓴다(효과 `! alloc` 선언 포함).

| 이름 | 내용 | stage/code |
|---|---|---|
| `g2b_escape` | 리터럴 `"\xFF"` | parse/`string_escape` |
| `g2b_escape_newline` | `\` 바로 뒤 실제 줄바꿈 | parse/`string_escape` |
| `g2b_unterminated` | EOF까지 닫히지 않은 리터럴 | parse/`string_unterminated` |
| `g2b_unterminated_escape` | `"ab\` 로 파일 끝 | parse/`string_unterminated` |
| `g2b_newline` | 리터럴 안 실제 줄바꿈 | parse/`string_character` |
| `g2b_control` | 리터럴 안 실제 TAB 문자 | parse/`string_character` |
| `g2b_option_str` | `Option<str>` | parse/`unsupported_type` |
| `g2b_store` | `let mut s: str = "ab"; s[0] = 1;` | type/`immutable_string` |
| `g2b_param_store` | 매개변수 `s: str`에 `s[0] = 1;` | type/`immutable_string` |
| `g2b_alias` | `let s: str = t;`(t는 str 매개변수) | type/`array_alias` |
| `g2b_param_return` | `return s;`(s는 str 매개변수) | type/`array_alias` |
| `g2b_field` | 구조체 str 필드 | type/`field_type` |
| `g2b_to_bytes` | str을 `[u8]` 지역에 대입 | type/`type_mismatch` |
| `g2b_from_bytes` | `[u8]`를 str 지역에 대입 | type/`type_mismatch` |
| `g2b_eq` | 코드에서 문자열 전체 `==` | type/`eq_type` |
| `g2b_eq_contract` | requires에서 문자열 전체 `==` | type/`eq_type` |
| `g2b_contract_copy` | requires 안 `copy(s)` | type/`effect_in_contract` |
| `g2b_contract_substr` | requires 안 `substr(s, 0, 0)` | type/`effect_in_contract` |
| `g2b_boundary_type` | `is_char_boundary(b, 0)`(b는 `[u8]`) | type/`type_mismatch` |
| `g2b_substr_type` | `substr(s, true, 1)` | type/`type_mismatch` |
| `g2b_reserved` | 함수 이름 `substr` | type/`reserved` |
| `g2b_print` | `print("hi");`(`! alloc, io`) | type/`print_type` |
| `g2b_missing_alloc` | 효과 선언 없이 코드에서 `len("ab")` | effect/`missing_effect` |
| `g2b_b0_verify_layer` | 앞단을 통과하는 정상 str 프로그램(리터럴·len·색인·copy·substr·is_char_boundary·str 반환) | verify/`unsupported_type` |
| `g2b_b0_literal_verify` | str 타입 없이 리터럴만: `fn f() -> i64 ! alloc { return len("abc"); }` | verify/`unsupported_type` |
| `g2b_b0_infer_layer` | while 루프가 있는 정상 str 프로그램, flags `["--infer"]` | verify/`unsupported_type` |
| `g2b_b0_codegen_layer` | `g2b_b0_verify_layer`와 같은 종류, flags `["--no-verify"]` | codegen/`unsupported_type` |
| `g2b_b0_contract_literal_nv` | 리터럴이 requires에만(`requires len(s) >= len("a")`, s는 `[u8]`·효과 없음), flags `["--no-verify"]` | codegen/`unsupported_type` |
| `g2b_b0_guard_order` | str 매개변수 없이 중첩 if 안 str Let(5:5) + 뒤 리터럴, `cex_contains` `"line": 5, "col": 5` | verify/`unsupported_type` |
| `g2b_b0_guard_order_nv` | ensures 리터럴(4:25)이 본문 리터럴보다 앞, flags `["--no-verify"]`, `cex_contains` `"line": 4, "col": 25` | codegen/`unsupported_type` |
| `g2b_b0_guard_lit_first` | 리터럴(4:20)이 뒤 str Let(5:3)보다 앞, `cex_contains` `"line": 4, "col": 20` | verify/`unsupported_type` |

문구 고정(`cex_contains`, 감사 권고): `g2b_eq` → `str values cannot be compared with ==`, `g2b_alias`·`g2b_param_return` → `a str value here must come from a string literal`.

### 9.2 `tests/parse_edge/`(parse dump 두 판 대조)

- `str_ok_literals.pruv`: ASCII, 한글, 2/3/4바이트 문자(`é`, `한`, `😀`), 빈 문자열, `\0` 포함, 이스케이프 6종 전부, 문자열 안 `//`·`(`·`]`·`|`·`'`, 리터럴 색인 `"ab"[1]`, 한 줄에 리터럴 여럿(열 번호), 리터럴 뒤 같은 줄 주석.
- 오류 표본(파일마다 하나): `str_err_escape_x.pruv`, `str_err_escape_quote_at_eof.pruv`(`"\` EOF), `str_err_unterminated.pruv`, `str_err_newline.pruv`, `str_err_tab.pruv`, `str_err_del.pruv`(0x7F), `str_err_ctrl_after_multibyte.pruv`(한글 뒤 제어 문자: 열이 문자 단위인지), `str_err_misplaced.pruv`(`let "a" = 1;` → 기존 syntax 문구에 원문 repr), `str_err_quote_in_repr.pruv`(`let "it's" = 1;`).
- 기존 `badchar_dquote.pruv`는 이제 문자열이다: 첫 줄 주석만 "이제 문자열 리터럴로 parse 성공(check에서는 print_type)"으로 고치고 내용은 둔다.

### 9.3 `tests/check_edge/`(check dump 두 판 대조)

- `ok_str_ops.pruv`: str 매개변수·반환, 리터럴, `len`, 색인, `copy`, `substr`, `is_char_boundary`(코드·계약), 계약 안 리터럴, `let mut s: str` 전체 재대입, 지역 str 반환, 리터럴 인자로 사용자 함수 호출, 루프 안 바이트 읽기.
- 오류 표본: `str_immutable.pruv`, `str_eq_contract.pruv`, `str_option_result.pruv`(`Result<str>`), `str_field_enum.pruv`(열거형 payload str → field_type), `str_alias_reassign.pruv`(재대입 RHS가 다른 str 변수).

### 9.4 하네스

- `tests/diff_parse.py`: parse 필수 코드 집합(`REQUIRED_CODES`)에 `string_escape`·`string_unterminated`·`string_character`, check 필수 코드 집합(`CHECK_CODES`)에 `immutable_string`. 노드 수 주석 갱신.
- `tests/diff_py_adapter.py`: 8절. Python 소스 읽기가 `open()`이면 `encoding="utf-8"`.
