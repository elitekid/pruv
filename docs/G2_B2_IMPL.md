# G2 B2 구현 명세: `str` 실행·raw ABI — 두 판 공통

상태: B2 묶음 구현 계약(메인 작성). 두 판(Python `pruvc/`, Rust `pruvc-rs/crates/`)은 아래 글자를 **바이트 그대로** 낸다. 근거: `docs/G2_SPEC.md` 0.0절 결정 13·16, 5.1~5.4절, 6.3절, 7.6절, 8.2절. 앞 묶음 명세 `docs/G2_A3_IMPL.md`·`G2_A4_IMPL.md`·`G2_A5_IMPL.md`(u8·bool 실행)와 `G2_B0_IMPL.md`·`G2_B1_IMPL.md`(str 앞단·증명)를 본뜨고, 여기 적지 않은 것은 `[u8]` 길과 같게 한다.

## 0. 범위와 결정

1. 생성 층(Rust 소스·LLVM·`--rust-bindings`)이 `str` 을 받는다. 생성 층 가드 6곳(Py `pruvc.py`·`codegen.py`·`llvmgen.py`, Rs `driver.rs`·`codegen.rs`·`llvmgen.rs`)의 skip 을 `("array_u8", "array_bool", "str")`(Rs `&["array_u8", "array_bool", "str"]`)로 바꾸고 주석을 `G2 B2` 로 한다. 가드 함수는 지우지 않는다.
2. **str 을 쓰지 않는 프로그램의 Rust 소스·IR·바인딩·SMT 는 한 바이트도 바뀌지 않는다.** str 용 prelude·선언·구조체는 `uses_str(prog)` 가 참일 때만 붙인다.
3. `uses_str(prog)`(새 함수, Py `typeinfo.py`, Rs `typeinfo.rs` `pub fn uses_str(prog: &Program) -> bool`): 어떤 함수의 매개변수·반환 타입이나 (중첩 블록 안까지) `let` 타입이 `str` 이거나, requires·ensures·본문 **어느 식이든** 문자열 리터럴(`StrLit`)이 있으면 참. (`uses_array_type(prog, "str")` 는 `let` 값 식 안의 리터럴을 못 보므로 리터럴 걷기를 따로 한다. 식 걷기는 `first_g2_unimplemented` 의 리터럴 후보 수집과 같은 범위.)
4. 메모리 표현: str 값은 바이트 배열과 같은 `{ ptr, i64 }`(길이 = 바이트 수), 원소 1바이트(`i8`), 크기·정렬 (1,1). Rust 소스는 매개변수 `&str`, 지역·반환 `::std::string::String`.
5. 실행 안의 str 은 언제나 유효 UTF-8 이다: 리터럴(파서가 보장)·`copy`·`substr`(경계 검사 또는 증명) 만이 str 을 만든다. 바깥에서 들어오는 길은 raw ABI(`pruv_abi_<f>`) 뿐이고, 거기서 **본문·requires 보다 먼저** `pruv_check_utf8` 로 검사한다(`--trust-callers` 와 무관). typed Rust 바인딩의 `&str` 은 언어가 보장하므로 `__typed` 진입(검사 줄 없음)을 부른다(A5 bool 과 같은 방식).
6. 경계 판정은 SMT `str_boundary`(B1)와 같은 뜻이다: `i == 0` 또는 `i == len` 이면 참, `i < 0` 또는 `i > len` 이면 거짓, 그 밖은 바이트 `b` 가 `b < 128 || b >= 192`(= `(b & 0xC0) != 0x80`). 유효 UTF-8 에서 Rust `str::is_char_boundary` 와 같다.
7. 안전 모드 새 실패(두 뒷단 같은 글자, 종료 101):
   - `pruv: string slice out of bounds: LO..HI (len N)` — `0 <= lo <= hi <= len` 위반
   - `pruv: UTF-8 boundary error: LO..HI (len N)` — 범위는 맞으나 lo 또는 hi 가 경계 아님
   - `pruv: invalid representation: K (str UTF-8, byte offset)` — raw 입력의 잘못된 UTF-8(K = 잘못된 순서가 시작하는 바이트 위치)
   검사 순서: 인자 평가(s → lo → hi) → 범위 → 경계 → 복사.
8. `print` 는 str 을 받지 않는다(검사기 그대로). 배열 전체 `==` 금지도 그대로.
9. `show`(requires 위반 문구의 식 글자): `StrLit` 은 두 판 모두 `<str>`(Py 는 지금 `?` → `<str>` 로 고침).
10. 정렬 requires 빠른 길(LLVM `csorted`, Rust 소스에 같은 것이 있으면 그것)은 str 에 쓰지 않는다: 매칭이 str 배열이면 맞지 않은 것으로 보고 일반 길로 간다.

## 1. Rust 소스 뒷단(Py `codegen.py` / Rs `codegen.rs`·`emit_common.rs`)

### 1.1 타입
- `rty`: `str` → 매개변수 `&str`, 지역·반환 `::std::string::String`(Rs `emit_common.rs` 에 명시 분기; 폴백에 기대지 않는다).
- 원소 판별: 식 타입이 `str` 인지 보는 질의(Py `is_str(t)` = `t is not None and t.name == "str"`, Rs `expr_ty(e) == Some("str")` 또는 `self.vars`)를 **u8/bool 판별보다 먼저** 본다. Rs `elem_of` 가 str 에 "i64" 를 주므로 str Index 는 `elem_of` 에 닿기 전에 갈라야 한다.
- 사용자 함수 호출 인자: 지금 `is_array(x.ty)` 이면 `arr_ref` 를 쓰는 자리에서 **str 도 `arr_ref`** 를 쓴다(지역 `&s`, 매개변수 `s`, 임시 `&<식>`).

### 1.2 리터럴 글자 `LIT(bytes)`
바이트를 UTF-8 로 풀어 문자마다: 코드 포인트가 0x20..=0x7E 이고 `"`(0x22)·`\`(0x5C)가 아니면 그 문자 그대로, 그 밖(제어 문자·NUL·`"`·`\`·0x7F·비 ASCII 전부)은 `\u{X}`(X 는 소문자 16진, 앞 0 없음). 앞뒤에 `"`.
- 예: `"a\"b"` → `"a\u{22}b"`, `"é"` → `"\u{e9}"`, `"a\0b"` → `"a\u{0}b"`, `"\n"` → `"\u{a}"`, `""` → `""`, `"😀"` → `"\u{1f600}"`.
- 두 판 모두 호스트 언어 repr 에 기대지 않고 이 규칙으로 직접 만든다.

### 1.3 코드 식 글자(`S` 는 str 하위 식 `s.e(..)`, `R` 는 `arr_ref(..)`, `I`·`LO`·`HI` 는 정수 하위 식)
| 식 | 증명 모드 | 안전 모드(`--no-verify`) |
|---|---|---|
| 리터럴 | `::std::string::String::from(LIT)` | 같음 |
| `len(s)` | 지금 글자 그대로 `(S.len() as i64)` | 같음 |
| `s[i]` | `((unsafe { *S.as_bytes().get_unchecked((I) as usize) }) as i64)` | `pruv_get_str(R, I)` |
| `copy(s)` | `S.to_owned()` | 같음 |
| `is_char_boundary(s, i)` | `pruv_str_boundary(R, I)` | 같음 |
| `substr(s, lo, hi)` | `{ let pruv_s: &str = R; let pruv_lo: i64 = LO; let pruv_hi: i64 = HI; ::std::string::String::from(unsafe { pruv_s.get_unchecked((pruv_lo as usize)..(pruv_hi as usize)) }) }` | `pruv_substr(R, LO, HI)` |
- `let`·재대입·`return`·호출 결과는 지금 배열 길 그대로(String 이동). 매개변수 반환은 검사기가 `copy` 를 요구한다.
- 안전 모드 생성물에는 `unsafe`·`get_unchecked` 가 없어야 한다(run_all 검사).

### 1.4 계약(requires) 글자(`C` 는 계약 배열 식, `CI` 는 i128 색인)
- `carr`: `Var` 는 지금처럼 이름, **`StrLit` 이면 `LIT(bytes)`**(String 아님, `&'static str`). 그 밖은 지금 오류 그대로.
- 계약 식 `c()` 의 `StrLit`: `LIT(bytes)`.
- `len(s)`: 지금 글자 `(C.len() as i128)`.
- `s[i]`: `pruv_cidx_str(C, CI)`.
- `is_char_boundary(s, i)`: `pruv_cboundary(C, CI)`.

### 1.5 prelude
붙이는 순서(각 조각은 지금처럼 `"\n"` 로 이음): 사용자 타입 → **(uses_str) `STR_PRELUDE`** → (안전 모드) `SAFE_PRELUDE`, (u8) `SAFE_PRELUDE_U8`, (bool) `SAFE_PRELUDE_BOOL`, **(uses_str) `SAFE_PRELUDE_STR`** → (requires 있고 trust 아님) `CONTRACT_PRELUDE`, (u8) `CONTRACT_PRELUDE_U8`, (bool) `CONTRACT_PRELUDE_BOOL`, **(uses_str) `CONTRACT_PRELUDE_STR`**, 계약 타입.

각 상수는 마지막 줄 뒤 줄바꿈 하나(u8 것과 같은 모양).

`STR_PRELUDE`(모드 무관):
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

### 1.6 B0 빈틈 정리
- Py `c()`·`e()` 의 StrLit 분기 추가(위 글자), Rs `c()`·`e()` 의 `Expr::StrLit` 팔(지금 Err)을 위 글자로.
- `is_char_boundary`·`substr` 은 builtin 분기(`len`·`alloc`·`copy`·`print` 와 같은 자리, `print` 다음·사용자 호출 앞)에서 처리한다. 사용자 함수 호출 길로 떨어지지 않게 한다.
- Py `show` 에 `StrLit` → `"<str>"`.

## 2. LLVM 뒷단(Py `llvmgen.py` / Rs `llvmgen.rs`)

### 2.1 타입·원소 정보
- `lty("str") = ARR`, `vkind("str") = arr`(명시 분기). `elem_ty("str") = STR`(Py `vast.STR`, Rs `Some("str")`).
- 바이트 질의(Py `is_bytes`, Rs `is_bytes_ty`/`elem_ir`)에 `"str"` 을 더한다: GEP 원소 `i8`, `pruv_copy_v2(.., 1, 1)`, `pruv_free_v2(.., 1, 1)` 이 str 에 적용된다.
- 새 질의 Py `is_strv(v)` / Rs 대응(`v.ty == Some("str")`). **코드 읽기·계약 읽기에서 str 은 u8 과 같은 글자**(`load i8` → `zext i8 .. to i64` / `to i128`)를 낸다. 값 범위 검사(저장·alloc)는 str 에 닿지 않는다(검사기가 저장을 막고 alloc 은 str 을 만들지 않음).
- 배열을 다루는 모든 자리(`ir_params`·`bind_params`·`bind_contract_params`·슬롯 생성·`load`·스코프 소유 목록·임시 목록·호출 인자 펼침·호출 결과 `extractvalue`·`emit_ret`·entry·abi 서명)에서 str 을 배열과 똑같이 다루고 V/Slot `ty` 에 `STR` 을 싣는다(지금 `is_array(t)` 로 가르는 곳은 `is_array(t) or t.name == "str"` 뜻으로).

### 2.2 리터럴(코드)
리터럴 바이트를 UTF-8 문자열로 풀어 `Mod.string(text)` 로 전역을 등록한다(지금 패닉 문구가 쓰는 같은 함수·같은 번호·같은 렌더; 끝의 `\00` 은 쓰지 않는 덧붙임). 등록 시점은 그 리터럴을 평가하는 때(`ev` 안).
```
%p = call ptr @pruv_copy_v2(ptr @.str.N, i64 L, i64 1, i64 1)
```
결과 `temp_arr(V("arr", %p, "L", STR), owned)`(L 은 바이트 수 10진 글자, `""` 이면 `0` — `pruv_copy_v2` 가 len 0 에서 NULL 을 돌려주고 원본을 읽지 않는다).

### 2.3 리터럴(계약 `cev`)
복사 없이 `V("arr", "@.str.N", "L", STR)`. 그 뒤 `len`·Index·`is_char_boundary` 는 일반 str 값과 같다.

### 2.4 코드 식 IR(`S` = str 값 `{a, b}`, 번호는 지금처럼 `s.op` 순서)
- `s[i]`: `index_ptr`(안전 모드 `pruv_panic_oob` 검사 + `getelementptr inbounds i8`) 뒤
  ```
  %x = load i8, ptr %g
  %y = zext i8 %x to i64
  ```
- `copy(s)`: 바이트 배열 길 그대로(`pruv_copy_v2(.., 1, 1)`), 결과 ty `STR`.
- `len(s)`: 지금 그대로(`S.b`).
- `is_char_boundary(s, i)`(인자 s → i 차례 평가, 두 모드 같음):
  ```
  %r = call i32 @pruv_str_boundary(ptr S.a, i64 S.b, i64 I)
  %c = icmp ne i32 %r, 0
  ```
  결과 `V("i1", %c)`.
- `substr(s, lo, hi)`(인자 s → lo → hi 차례 평가, s 가 임시값이면 지금 임시 목록대로 문 끝에 해제):
  - 증명 모드:
    ```
    %d = sub i64 HI, LO
    %g = getelementptr inbounds i8, ptr S.a, i64 LO
    %p = call ptr @pruv_copy_v2(ptr %g, i64 %d, i64 1, i64 1)
    ```
  - 안전 모드:
    ```
    %p = call ptr @pruv_substr(ptr S.a, i64 S.b, i64 LO, i64 HI)
    %d = sub i64 HI, LO
    ```
  결과 `temp_arr(V("arr", %p, %d, STR), owned)`. 새 버퍼라 원본 수명과 무관하다.

### 2.5 계약 IR
- Index(str): 지금 가드(`zext`·`icmp ult i128`·undefined `array index out of range`)와 `trunc` 뒤 u8 과 같은 `getelementptr inbounds i8` → `load i8` → `zext i8 .. to i128`.
- `is_char_boundary(s, i)`:
  ```
  %ln = zext i64 S.b to i128
  %ok = icmp ule i128 I, %ln
  %t = trunc i128 I to i64
  %u = select i1 %ok, i64 %t, i64 -1
  %r = call i32 @pruv_str_boundary(ptr S.a, i64 S.b, i64 %u)
  %c = icmp ne i32 %r, 0
  ```
  결과 `V("i1", %c)`. (음수 i128 은 부호 없는 비교에서 len 보다 커서 `-1` → 거짓.)

### 2.6 raw 진입 `abi_of`(Py `llvmgen.py` / Rs `abi.rs`)
- str 매개변수: 인자 글자는 배열과 같은 `ptr %a.Q.a, i64 %a.Q.n`, 그 매개변수 차례에 `pre` 에
  ```
  call void @pruv_check_utf8(ptr %a.Q.a, i64 %a.Q.n)
  ```
- `__typed` 정의: 매개변수에 `[bool]` **또는 `str`** 이 하나라도 있으면 만든다. 본문은 `  call void @pruv_check_bool(` **또는** `  call void @pruv_check_utf8(` 로 시작하는 줄을 뺀 사본(나머지 글자·빈 줄 규칙은 A5 그대로).
- str 반환: 배열 반환과 같은 `ptr %out` 길.

### 2.7 선언
`DECLS` → `DECLS_U8`(u8 **또는 bool 또는 uses_str**) → `DECLS_BOOL`(bool) → `DECLS_STR`(uses_str):
```
DECLS_STR = "declare i32 @pruv_str_boundary(ptr nocapture readonly, i64, i64) nounwind willreturn memory(argmem: read)\n"
            "declare noalias ptr @pruv_substr(ptr nocapture readonly, i64, i64, i64) nounwind\n"
            "declare void @pruv_check_utf8(ptr nocapture readonly, i64) nounwind\n"
```

## 3. 바인딩(두 판 `gen_bindings`, Py `llvmgen.py` / Rs `bindings.rs`)
- `rust_ty`: `str` → `&str` / `::std::string::String`.
- 구조체: `Pruv__ArrayBool` 자리 뒤에, `uses_str(prog)` 이면 `ALLOW` 줄과 `#[repr(C)]\npub struct Pruv__Str { pub data: *mut u8, pub len: i64 }`.
- extern 인자: str → `*const u8`, `i64`. 반환 out: `*mut Pruv__Str`.
- extern 블록 순서: 모든 `pruv_abi_*` 줄 → (`[bool]` 반환 함수가 있으면) `pruv_check_bool` 줄 → (str 반환 함수가 있으면) `    fn pruv_check_utf8(p0: *const u8, p1: i64);` → marker 줄. marker 는 str 반환 함수도 "배열 반환"으로 센다.
- `typed_abi_name`: `[bool]` **또는 `str`** 매개변수가 있으면 `__typed`.
- 공개 함수 인자 전달: str → `NAME.as_ptr()`, `NAME.len() as i64`.
- str 반환 본문(4줄, 배열 반환 자리):
  ```
  let mut pruv__out = Pruv__Str { data: ::std::ptr::null_mut(), len: 0 };
  pruv_abi_F(.., &mut pruv__out);
  pruv_check_utf8(pruv__out.data, pruv__out.len);
  if pruv__out.len > 0 { ::std::string::String::from_utf8_unchecked(::std::vec::Vec::from_raw_parts(pruv__out.data, pruv__out.len as usize, pruv__out.len as usize)) } else { ::std::string::String::new() }
  ```
  (marker 참조 줄은 지금처럼 배열 반환 함수에 붙는다.)

## 4. 런타임 `pruvc/runtime.c`
- 머리 주석 끝에 문단 하나: `str (G2 B2): pruv_str_boundary(data, len, i) is the UTF-8 character boundary test (i == 0 or i == len, else 0 < i < len and data[i] is not a continuation byte); pruv_substr(data, len, lo, hi) checks the range then both boundaries ("pruv: string slice out of bounds: lo..hi (len n)" / "pruv: UTF-8 boundary error: lo..hi (len n)", exit 101) and returns a fresh copy (v2 layout 1,1); pruv_check_utf8(data, len) rejects a negative len (pruv_panic_repr(len, "str length")), NULL data with len > 0 (pruv_panic_repr(len, "str NULL data")) and ill-formed UTF-8 (Unicode Table 3-7) with pruv_panic_repr(offset, "str UTF-8, byte offset").`
- 공개 프로토타입 목록에 네 줄(그리고 빠져 있던 `void pruv_check_bool(const uint8_t *data, int64_t len);`도 같이):
  ```c
  _Noreturn void pruv_panic_slice(const char *what, int64_t lo, int64_t hi, int64_t len);
  int32_t pruv_str_boundary(const uint8_t *data, int64_t len, int64_t i);
  void *pruv_substr(const uint8_t *data, int64_t len, int64_t lo, int64_t hi);
  void pruv_check_utf8(const uint8_t *data, int64_t len);
  ```
- `pruv_panic_repr` 정의 바로 뒤:
  ```c
  _Noreturn void pruv_panic_slice(const char *what, int64_t lo, int64_t hi, int64_t len) {
      PRUV_HOST_FLUSH();
      fflush(stdout);
      fprintf(stderr, "pruv: %s: %" PRId64 "..%" PRId64 " (len %" PRId64 ")\n", what, lo, hi, len);
      exit(101);
  }
  ```
- `pruv_check_bool` 정의 뒤(#ifdef 바깥):
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
  (`pruv_copy_v2` 가 이 함수들보다 앞에 정의돼 있어야 한다; 아니면 프로토타입으로 해결.)
- `tests/abi/runtime_v1.c` 는 고치지 않는다.

## 5. 표본·시험(시험 담당)

### 5.1 must_reject 정리(메인이 `git rm`)
생성 층이 열리면 stage codegen 을 기대하던 str 표본은 거부되지 않는다.
- 지울 것(메인): `g2b_b0_{verify_layer,literal_verify,infer_layer,guard_order,guard_lit_first,codegen_layer,contract_literal_nv,guard_order_nv}` 8쌍, `g2b_b1_ok_{len,boundary,boundary2,flow,param,loop,contract,infer}` 8쌍.
- 옮길 것(시험 담당이 새 파일로 같은 본문 복사, 첫 줄 주석만 "B2: 생성·실행까지 통과" 뜻으로):
  - `examples/g2b_lit_len.pruv` ← `g2b_b1_ok_len`(리터럴 바이트 길이·바이트 읽기)
  - `examples/g2b_boundary.pruv` ← `g2b_b1_ok_boundary`
  - `examples/g2b_boundary2.pruv` ← `g2b_b1_ok_boundary2`(다중 바이트 경계 부분 문자열)
  - `examples/g2b_flow.pruv` ← `g2b_b1_ok_flow`(복사 반환)
  - `examples/g2b_param.pruv` ← `g2b_b1_ok_param`
  - `examples/g2b_loop.pruv` ← `g2b_b1_ok_loop`
  - `examples/g2b_contract.pruv` ← `g2b_b1_ok_contract`
  - `tests/runtime/g2b_rt_infer.{pruv,json,rs}` ← `g2b_b1_ok_infer`(examples 에 `--infer` 모드가 없으므로 runtime 으로, `flags_matrix: [["--infer"]]`)
  - 새로 `examples/g2b_ascii_substr.pruv`(ASCII 부분 문자열, 결과 len·바이트 ensures), `examples/g2b_boundary_branch.pruv`(`if is_char_boundary(s, i) { return substr(s, 0, i); } else { return copy(s); }` 꼴 경계 분기).
  - examples 는 세 모드(default·no-verify·trust-callers)×두 뒷단으로 돈다: 모든 경로 return, 리터럴·copy·substr 쓰면 `! alloc`.
- `g2b_b0_infer_layer` 는 지우기만 한다(같은 뜻을 `g2b_rt_infer` 가 덮음).

### 5.2 runtime 표본 `tests/runtime/g2b_rt_*`(`.pruv`+`.json`+`.rs`, 12개 이상)
구동 `.rs` 는 `sol::f("..")`(매개변수 `&str`)로 부르고 반환 `String` 은 `println!("{}", ..)` 나 `.len()`·`.as_bytes()` 로 찍는다. 다음을 포함:
1. `escape`: `"\"\\\n\r\t\0"` 의 길이·바이트, 반환 문자열 바이트 출력.
2. `nul`: `"a\0b"` 길이 3, 가운데 바이트 0, 반환 String 의 len 3(잘리지 않음).
3. `empty`: `""` 길이 0, `substr("",0,0)`, `copy("")`, `is_char_boundary("",0)`.
4. `multibyte`: 한글·😀 바이트·경계·부분 문자열을 Rust 쪽 기대와 비교.
5. `big_bound`: `is_char_boundary(s, -1)`·`(s, len+1)`·`(s, 9223372036854775807)`·`(s, -9223372036854775807)` 코드와 requires(i128) 양쪽에서 거짓(flags_matrix 에 `--trust-callers` 포함).
6. `ends`: 경계 0·len 이 참, `substr(s, 0, len(s))`·`substr(s, len(s), len(s))`.
7. `bad_slice_range`(flags `[["--no-verify"]]`, exit 101, stderr_contains `pruv: string slice out of bounds: 2..1 (len 3)`) — 같은 본문의 must_reject 짝 `g2b_b2_bad_slice_range`(verify/`string_slice_range`).
8. `bad_slice_cut`(`--no-verify`, `substr("é", 0, 1)` 꼴, stderr_contains `pruv: UTF-8 boundary error: 0..1 (len 2)`) — must_reject 짝 `g2b_b2_bad_slice_cut`(verify/`utf8_boundary`). 음수 lo 경우(`-1..1`)도 하나(range 문구).
9. `eval_order`: `substr(f(), g(), h())` 꼴에서 `! io` 함수들이 `print` 로 순서를 찍음(stdout_lines 로 확인), 그다음 안전 모드 실패도 인자 평가 뒤에 나는지.
10. `reassign`: `let mut t: str` 를 루프에서 다시 대입(옛 값 해제), `alloc_balance: true`.
11. `nested_temp`: `len(substr(copy("..."), a, b))`·`is_char_boundary(substr(..), k)`·`substr(f(), ..)` 같은 중첩 임시값, `alloc_balance: true`.
12. `return_owned`: 지역 문자열에서 `substr` 해 반환(원본은 함수 끝에 해제) — 호출자가 결과 바이트를 읽음; Rust 쪽은 반환 String 을 찍음. `llvm_fn_contains` 로 `@pruv_copy_v2(` 확인.
- 적어도 두 표본에 `gen_contains`(Rust: `pruv_substr`·`pruv_str_boundary`·`pruv_cidx_str`)와 `ll_contains`(`@pruv_substr(`·`@pruv_str_boundary(`)를 둔다.

### 5.3 raw UTF-8 검사 `tests/abi/check_utf8_repr.py`(새 파일, `check_bool_repr.py` 방식)
- 소스: `fn tlen(s: str) -> i64 requires len(s) >= 1 && s[0] != 120 { return len(s); }`(120 = `x`). 두 컴파일러 IR + 일반 런타임 + C 호출자(argv 의 16진 바이트를 버퍼에 채워 `pruv_abi_tlen(buf, n)` 호출, 결과 출력).
- 경우(각각 기본 빌드·`--trust-callers` 빌드): 유효 `61`·`61 00 62`(출력 3: NUL 안 잘림)·`C3 A9`·`F0 9F 98 80`; 거부(종료 101, stderr `pruv: invalid representation: K (str UTF-8, byte offset)`): 고립 continuation `61 80`(K=1), 잘린 다중 바이트 `E3 81`(K=0), overlong `C0 AF`(K=0)·`E0 80 AF`(K=0), surrogate `ED A0 80`(K=0), U+10FFFF 초과 `F4 90 80 80`(K=0)·`F5 80 80 80`(K=0), 첫 바이트 `x` 이면서 잘못된 UTF-8 `78 FF`(표현 오류가 requires 위반보다 먼저: K=1).
- `tests/m3_all.py` 에 단계 `abi_utf8` 을 더한다.

### 5.4 ABI 생성물
- `tests/abi/gen/g2b_str_ret.pruv`(한 줄 서명, `str` 인자·반환, 중간 `substr`/`copy`) + `tests/abi/winci/calls.json` 항목(`sol::f("héllo", ..)` 꼴).
- `tests/abi/gen/g2a_bool_opt.pruv`: `[bool]` 인자 + `Option<i64>` 반환(A5 확인 감사 권고: sret 조합) + calls.json 항목.
- `tests/abi/check_generated.py`: `__typed` define 이 있으면 원래 define 과 **서명이 같은지**, 바인딩이 부르는 `pruv_abi_*__typed` 가 IR 에 정의돼 있는지 검사를 더한다(A5 확인 감사 권고). COFF 기호 검사는 Windows 쪽 일이라 남긴다면 README 에 이유를 적는다.
- winci 출력(`tests/abi/winci/out/*`)은 메인이 `prepare.py` 로 다시 만든다.

## 5.5 감사 뒤 정한 것
- `pruv_check_utf8` 은 음수 길이(`pruv: invalid representation: <len> (str length)`)와 길이가 양수인 NULL(`... (str NULL data)`)도 거부한다(SMT 가 매개변수 길이 0..MAX_LEN 을 가정하므로). 같은 공백이 `[i64]`·`[u8]`·`[bool]` raw 진입에도 B2 전부터 있다 — 배열 전체로 넓히는 일은 뒤로 미룬다.
- `pruv_abi_<f>__typed` 는 검사 없는 공개 기호다(A5 bool 과 같은 설계). C 호출자는 `pruv_abi_<f>` 를 불러야 하며 `__typed` 는 생성 Rust 바인딩 전용이다.
- 바인딩의 str 반환 재검사(`pruv_check_utf8`)는 남긴다: `--trust-callers` 로 requires 를 어긴 호출에서도 Rust `String` 의 UTF-8 불변식을 지키기 위한 마지막 방어다(O(n), 반환 길이만큼).
- `pruv_str_boundary` 선언에 `willreturn memory(argmem: read)` 를 붙여 루프 안 호출을 최적화가 옮길 수 있게 한다(인라인은 런타임이 다른 객체라 하지 않는다).

## 6. 확인(메인)
빌드 → `run_all --backend both`(행 목록 `--list-rows` 갱신) → SMT 231 cmp → 새 표본 diff_trace(same 만) → diff_parse → diff_compilers(must_reject + examples·runtime 생성물 두 판 바이트 대조) → m3_all(새 `abi_utf8`) → cli_also_llvm → inference --regress → 퍼저 → cargo test → winci prepare/--check.
