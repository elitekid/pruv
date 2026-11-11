# G2 A5 구현 명세: `[bool]` 배열 전 층

상태: A5 묶음 구현 계약(메인 작성). 두 판(Python `pruvc/`, Rust `pruvc-rs/crates/`)은 아래 글자를 **바이트 그대로** 낸다. 근거: `docs/G2_SPEC.md` 0.0절 결정 4·5·6·7·15·16, 2.1·3.1·4.2·5.1·5.2·5.3·5.4절. A2~A4 명세(`docs/G2_A2_IMPL.md`·`G2_A3_IMPL.md`·`G2_A4_IMPL.md`)의 u8 구현을 본뜨고, 아래에 적지 않은 것은 u8 길과 같게 한다.

## 0. 범위와 결정

1. A5는 `[bool]`(내부 이름 `array_bool`, Py `vast.ARRAY_BOOL`)을 앞단·증명·Rust 소스 뒷단·LLVM 뒷단·`--rust-bindings`·런타임에서 모두 연다. 묶음 끝에는 `g2_unimplemented_error`의 skip이 `("array_u8", "array_bool")`(Rs `&["array_u8", "array_bool"]`)이 된다. 여섯 호출 자리(Py `pruvc.py`·`codegen.py`·`llvmgen.py`, Rs `driver.rs`·`codegen.rs`·`llvmgen.rs`) 모두 같게 바꾼다. 가드 함수 자체는 B 묶음(str)을 위해 남긴다.
2. **기존 `[i64]`·`[u8]`만 쓰는 프로그램의 SMT·Rust 소스·IR·바인딩은 한 바이트도 바뀌지 않는다.** bool용 prelude·선언·구조체는 프로그램이 `[bool]`를 쓸 때만(`uses_array_type(prog, "array_bool")`) 붙인다.
3. bool 배열에는 `elem_range` 의무도 원소 정의역 가정도 없다(값 범위는 SMT sort가 보장).
4. 메모리 표현: 원소 1바이트(`i8`, Rust `bool`), 값 0/1. 비트 압축 없음. 크기·정렬 (1,1).
5. raw ABI(`pruv_abi_<f>`) 진입에서 `[bool]` 인자의 모든 바이트가 0/1인지 런타임 함수로 검사한다. 이 검사는 `__pruv_entry`(requires 검사 포함) 호출보다 먼저 하므로 `--trust-callers`와 무관하게 늘 돈다. typed Rust 바인딩의 `&[bool]`은 타입이 0/1을 보장하므로(G2_SPEC 5.4) 바인딩은 검사 줄만 뺀 `pruv_abi_<f>__typed`를 부른다(감사 필수 2: 매 호출 O(n) 중복 검사 제거, 4.2·4.4).

## 1. 앞단(Py `vparser.py`·`check.py`·`refine.py` / Rs `parser.rs`·`check.rs`·`refine.rs`)

- 배열 원소 이름 허용: `i64`·`u8`·`bool`. `bool`이면 타입은 `ARRAY_BOOL` / `"array_bool"`.
- 그 밖 원소 이름의 오류(지금 `only [i64] and [u8] arrays exist` / fix `use [i64] or [u8]`)를 다음 글자로 바꾼다. 대문자 시작은 지금처럼 `unsupported_type`.
  - msg: `only [i64], [u8] and [bool] arrays exist`
  - fix: `use [i64], [u8] or [bool]`
- `[bool | L..=U ...]`은 파싱은 지금 문법대로 되고, refine 검증(`_validate` / `validate`)에서 거부한다. 위치는 **스칼라 `refinement_base` 검사 바로 다음**(다른 범위 검사보다 먼저):
  - 조건: `shape == "array"` 이고 `base == "bool"` 이고 `lo`가 있음.
  - stage/code: `type` / `refinement_base`
  - msg: `a refinement \`| L..=U\` does not apply to [bool]; only its length can be bounded`
  - fix: `remove \`| L..=U\`; keep \`; <=N\` if a length bound is needed`
  - (글자 안의 \` 는 백틱 그대로. 스칼라용 기존 문구는 바꾸지 않는다.)
- `[bool; <=N]`은 허용(길이 정제만, 기존 길이 정제 펼침 그대로).
- 타입 검사:
  - `a[i]`의 식 타입: 배열 원소가 bool이면 `bool`, 아니면 지금처럼 `i64`.
  - `NAME[i] = x`의 `x` 기대 타입: 대상 배열 원소가 bool이면 `bool`, 아니면 `i64`.
  - `alloc(n, v)`: 결정 6의 힌트 타입이 `array_bool`이면 `v` 기대 타입 `bool`, 그 밖은 `i64`. 힌트가 없으면 지금처럼 `[i64]`(그래서 `len(alloc(4, false))`는 `type_mismatch`).
  - 오류 글자는 기존 `expect`의 `type_mismatch` 문구를 그대로 쓴다(새 문구 없음).
  - `sum` 본문은 지금처럼 `i64` 기대(bool 본문 → `type_mismatch`), `count(k in ..: a[k])`는 허용. 배열 전체 `==`/`!=` 금지는 지금 그대로, 원소끼리 비교는 허용.
- `tests/parse_edge/array_only_i64.pruv`는 메인이 `[i32]`로 고친다(작업자는 건드리지 않는다).

## 2. 증명(Py `verify.py`·`infer.py` / Rs `pruv-proof`의 `symbolic.rs`·`obligation.rs`·`infer.rs`)

### 2.1 기호 실행

- 매개변수·호출 결과·havoc의 bool 배열은 이미 `fresh`가 `Array(Int, Bool)`로 만든다(변경 없음). U8 전용 정의역 가정(`u8_dom`)은 bool에 넣지 않는다(지금 코드가 U8만 보므로 변경 없음).
- 코드·계약 읽기 `a[i]`(Py Index, Rs `symbolic.rs` Index): 색인 의무·`contract_domain` 처리는 지금 그대로. 그 뒤
  - bool 배열이면 `in_range(v)` 가정을 **넣지 않고**, 결과는 bool 값(Py: z3 Bool 식 그대로, Rs: `Val::Bool(select 결과 as_bool)`).
  - 그 밖은 지금 그대로(`in_range` 가정 후 Int, Rs `Val::Int`).
- `alloc(n, v)`: Call 노드 타입이 `array_bool`이면 원소 `BOOL`/`Elem::Bool`, 상수 배열 `K(Int, v)`(v는 Bool). 의무는 지금처럼 `alloc_negative`만(elem_range 없음). 순서·fresh 번호는 u8/i64 길과 같다.
- `NAME[i] = x`: `index_oob` 뒤 `Store(a, i, x)`(x는 Bool). `elem_range`·`refinement_assign`은 bool에 없음(bool 원소 정제가 없으므로 `elem_refine`도 생기지 않는다).
- `copy`·재바인딩·호출 결과는 원소 정보를 그대로 보존(이미 됨).
- SMT 이름·의무 순서는 u8 길과 같은 규칙. 기존 입력 SMT 231개 바이트 불변.

### 2.2 반례 JSON

- 배열 반례 항목은 지금 `{"len": n, "first": [..]}`(앞 최대 8개)이다. 원소가 bool이면 `first`의 각 항목을 JSON `true`/`false`로 낸다.
  - Py: `z3.is_true(m.eval(z3.Select(v.a, i), model_completion=True))` → Python `True/False` → JSON `true/false`.
  - Rs: `Json::Bool(..)`(z3 `model_completion=true` 평가 결과가 참이면 true).
- 정수 배열은 지금 그대로.
- 길이가 양수인 bool 배열 반례에서 `first`가 실제로 나오는지는 표본으로 시험한다(5절 `cex_contains`).

### 2.3 `--infer`

- 원소 타입 표를 **이름 기반 평평한 표에서 루프 위치 기준 표로** 바꾼다(감사 권고). Py `_elem_types(f)` → `_elem_types(f, w)`, Rs `elem_types` 대응.
  - 시작 환경: 매개변수(배열이면 원소 이름 `"i64"|"u8"|"bool"`).
  - 문장 목록을 앞에서부터 걸으며 환경을 갱신한다: `Let name: T`가 배열 타입이면 `env[name] = 원소 이름`, **배열이 아니면 `env`에서 name을 지운다**(가림). 대상 루프 `w`(같은 노드 객체, Rs는 같은 위치 식별 방법)에 닿으면 그때의 환경이 그 루프의 표다.
  - `If`의 then/else, `While` 본문, `Match` 각 팔은 **복사한 환경**으로 들어가고, 나와서는 바깥 환경을 그대로 쓴다(안쪽 let은 밖으로 새지 않는다). Match 팔 바인더는 배열이 아니므로 그 이름을 env에서 지운다.
  - 루프 본문 안의 let은 루프 머리에서 보이지 않으므로 표에 넣지 않는다.
- 이 표를 지금 쓰는 두 곳(bool 원소 읽기 필터 `kind >= 5`, 종류 5의 같은 원소 타입 검사)이 그대로 쓴다. 필터 위치·순서(정렬·중복 제거·자르기 전)는 지금 그대로.
- 기존 입력의 후보·결과는 바뀌지 않아야 한다(`tests/inference/run.py --regress` 두 판 통과 유지; A5 뒤 기준 271/271).

## 3. Rust 소스 뒷단(Py `codegen.py` / Rs `codegen.rs`·`emit_common.rs`)

- `rty`: `array_bool` → 매개변수 `&[bool]`, 지역·반환 `::std::vec::Vec<bool>`. (Rs `emit_common.rs`의 `other => other.to_string()` 폴백에 기대지 말고 명시 분기를 둔다.)
- 원소 판별은 u8과 같은 자리(Py `s.vt`/`e.array.ty`/`e.ty`, Rs `self.vars`/`elem_of`)에서 `array_bool`을 본다.
- prelude: 안전 모드면 `SAFE_PRELUDE`, (u8 쓰면) `SAFE_PRELUDE_U8`, (bool 쓰면) `SAFE_PRELUDE_BOOL` 순. requires가 있고 trust가 아니면 `CONTRACT_PRELUDE`, (u8) `CONTRACT_PRELUDE_U8`, (bool) `CONTRACT_PRELUDE_BOOL`, 그 뒤 contract types 순.

`SAFE_PRELUDE_BOOL`(마지막 줄 뒤 줄바꿈 하나, u8 것과 같은 모양):
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

식·문장 글자(`I`·`X`·`N`·`V`는 하위 식, `A`는 배열 식, `R`는 지금 `arr_ref`, `C`는 지금 `carr`, `CI`는 계약 색인):
- 저장, 증명 모드: `{ let pruv_i: i64 = I; let pruv_x: bool = X; unsafe { *NAME.get_unchecked_mut(pruv_i as usize) = pruv_x; } }`
- 저장, 안전 모드: `{ let pruv_i: i64 = I; let pruv_x: bool = X; pruv_set_bool(&mut NAME, pruv_i, pruv_x); }`
- 읽기, 증명 모드: `(unsafe { *A.get_unchecked((I) as usize) })` (i64 길과 같은 글자)
- 읽기, 안전 모드: `pruv_get_bool(R, I)`
- alloc, 증명 모드: `{ let pruv_n: i64 = N; let pruv_v: bool = V; vec![pruv_v; pruv_n as usize] }`
- alloc, 안전 모드: `pruv_alloc_bool(N, V)`
- 계약 읽기: `pruv_cidx_bool(C, CI)`
- copy·len·호출 인자: 지금 그대로.

## 4. LLVM·바인딩·런타임

### 4.1 원소 정보(Py `llvmgen.py` / Rs `llvmgen.rs`)

- `lty("array_bool") = ARR`, `vkind("array_bool") = arr` (u8과 같게; 폴백에 기대지 않는다).
- `elem_ty(t)`: `array_u8` → `ARRAY_U8`, `array_bool` → `ARRAY_BOOL`, 그 밖 `None`. Rs도 `Slot.ty`/`V.ty`에 `Some("array_bool")`을 싣는다(u8을 싣는 모든 자리: new_slot/load, bind_params, bind_contract_params, alloc, copy, 호출 결과).
- 새 질의 "바이트 배열"(Py `is_bytes(v)`, Rs 대응) = ty 이름이 `array_u8` 또는 `array_bool`. **GEP 원소 타입 `i8`, copy `pruv_copy_v2(.., 1, 1)`, free `pruv_free_v2(.., 1, 1)`은 바이트 배열 전체에 적용**한다. `is_u8`은 u8만(값 범위 검사·zext 확대).

### 4.2 IR 글자(번호는 `s.op` 순서대로, 아래 순서로 부른다)

- 코드 읽기 `a[i]`(bool): `index_ptr` 뒤
  ```
  %x = load i8, ptr %g
  %b = icmp ne i8 %x, 0
  ```
  결과 `V("i1", %b)`.
- 저장 `NAME[i] = x`(bool 슬롯): 색인 → 값 평가 → load 슬롯 → `index_ptr` 뒤
  ```
  %z = zext i1 X to i8
  store i8 %z, ptr %g
  ```
  값 범위 검사 없음.
- `alloc(n, v)`(Call 타입 `array_bool`): 지금처럼 cnt·v 평가, 안전 모드 길이 검사 뒤
  ```
  %z = zext i1 V to i64
  %p = call ptr @pruv_alloc_u8(i64 CNT, i64 %z)
  ```
  결과 `V("arr", %p, CNT, ARRAY_BOOL)`.
- `copy`·free: 4.1대로 v2 (1,1), 결과 V의 ty는 인자 ty.
- 계약 읽기(`cev` Index, bool): 지금 가드(`zext`·`icmp ult i128`·undefined)와 `trunc i128 .. to i64` 뒤
  ```
  %g = getelementptr inbounds i8, ptr A, i64 II
  %x = load i8, ptr %g
  %b = icmp ne i8 %x, 0
  ```
  결과 `V("i1", %b)`.
- `csorted`는 bool에 생기지 않는다(`<=` 불가) — 변경 없음.
- raw 진입 `abi_of`: 매개변수가 `[bool]`이면 그 매개변수 차례에 `pre`에 다음 한 줄을 넣는다(인자 글자 `ptr %a.Q.a, i64 %a.Q.n`은 지금 그대로):
  ```
  call void @pruv_check_bool(ptr %a.Q.a, i64 %a.Q.n)
  ```
  `[bool]` 매개변수가 하나라도 있으면 그 `define` 바로 뒤에 빈 줄 하나와, 이름이 `@pruv_abi_<f>__typed`이고 서명·본문이 같되 `  call void @pruv_check_bool(` 로 시작하는 줄만 뺀 `define`을 하나 더 낸다.
- 선언: `DECLS` 뒤에 `DECLS_U8`(u8 **또는 bool**을 쓰면), 그 뒤 `DECLS_BOOL`(bool을 쓰면).
  ```
  DECLS_BOOL = "declare void @pruv_check_bool(ptr nocapture readonly, i64) nounwind\n"
  ```

### 4.3 런타임 `pruvc/runtime.c`

- 머리 주석에 두 함수 설명 한 줄씩 더한다. `pruv_panic_elem` 원형 아래에 원형 `_Noreturn void pruv_panic_repr(int64_t v, const char *what);`.
- `pruv_panic_elem` 정의 바로 뒤:
  ```c
  _Noreturn void pruv_panic_repr(int64_t v, const char *what) {
      PRUV_HOST_FLUSH();
      fflush(stdout);
      fprintf(stderr, "pruv: invalid representation: %" PRId64 " (%s)\n", v, what);
      exit(101);
  }
  ```
- v2 함수들 뒤(#ifdef 바깥, 모든 변형 공통):
  ```c
  void pruv_check_bool(const uint8_t *data, int64_t len) {
      if (data == NULL || len <= 0)
          return;
      for (int64_t k = 0; k < len; k++)
          if (data[k] > 1)
              pruv_panic_repr((int64_t)data[k], "bool 0..=1");
  }
  ```
- `tests/abi/runtime_v1.c`는 고치지 않는다.

### 4.4 바인딩(두 판 `gen_bindings`, Py `llvmgen.py` / Rs `bindings.rs`)

- `rust_ty`: `array_bool` → `&[bool]` / `::std::vec::Vec<bool>`.
- 구조체: `Pruv__ArrayU8` 줄 뒤에, bool을 쓰면 `ALLOW` 줄과 `#[repr(C)]\npub struct Pruv__ArrayBool { pub data: *mut u8, pub len: i64 }`.
- extern 인자: `[bool]` → `*const u8`, `i64`. 반환 out: `*mut Pruv__ArrayBool`.
- extern 블록: 모든 `pruv_abi_*` 줄 뒤, marker 줄 앞에, `[bool]`을 돌려주는 함수가 하나라도 있으면 `    fn pruv_check_bool(p0: *const u8, p1: i64);`.
- `[bool]` 매개변수가 있는 함수는 extern 선언·호출 이름을 `pruv_abi_<f>__typed`로 쓴다(`[bool]` 반환만 있는 함수는 그대로 `pruv_abi_<f>`).
- 공개 함수 인자 전달: `[bool]` → `NAME.as_ptr() as *const u8`, `NAME.len() as i64`.
- `[bool]` 반환 본문(지금 배열 반환 3줄 자리):
  ```
  let mut pruv__out = Pruv__ArrayBool { data: ::std::ptr::null_mut(), len: 0 };
  pruv_abi_F(.., &mut pruv__out);
  pruv_check_bool(pruv__out.data, pruv__out.len);
  if pruv__out.len > 0 { ::std::vec::Vec::from_raw_parts(pruv__out.data as *mut bool, pruv__out.len as usize, pruv__out.len as usize) } else { ::std::vec::Vec::new() }
  ```
  (검사 뒤에 Rust bool로 인수한다. marker 참조 줄은 지금처럼 배열 반환 함수에 붙는다.)

## 5. 표본·시험(시험 담당)

- must_reject(쌍 `.pruv`+`.json`): `g2a_bool_fill`(type/type_mismatch), `g2a_bool_store`(type/type_mismatch), `g2a_bool_read_int`(type/type_mismatch), `g2a_bool_refine`(type/refinement_base), `g2a_sum_bool`(type/type_mismatch), `g2a_mixed_bool`(`[u8]`를 `[bool]` 매개변수에 전달, type/type_mismatch), `g2a_bool_alloc_nohint`(`len(alloc(4, false))`, type/type_mismatch), `g2a_infer_bool`(flags `--infer`, bool 배열·정수 배열을 함께 도는 루프 뒤 거짓 assert → verify 단계의 기대 코드; 내부 오류가 아님), `g2a_bool_cex`(길이 양수 bool 배열 매개변수로 거짓 ensures/assert → verify, 반례 JSON에 bool 원소가 나오는지 `cex_contains`로 확인).
- `tests/run_all.py` must_reject json에 선택 키 `cex_contains`(문자열 목록: 컴파일러가 낸 진단 JSON 출력에 모두 들어 있어야 함)를 더한다. 두 컴파일러 모두 같은 키로 검사한다.
- examples(`examples/g2a_bool_*.pruv`, 검증 통과): bool 생성(alloc·저장·읽기·반환), bool count(`count(k in 0..len(a): a[k])`를 ensures에 쓰는 루프), 매개변수·호출 결과·copy 뒤 저장, `[bool; <=N]` 길이 정제, `--infer`에서 형제 블록이 같은 이름을 다른 배열 타입으로 쓰는 루프(2.3의 위치 기준 표가 필요한 경우; 이 표본은 `--infer`로도 돌게).
- runtime(`tests/runtime/g2a_rt_bool_*`, `.pruv`+`.json`+`.rs`): 생성·저장·읽기·반환 값, 복사 독립성, 안전 모드 색인 범위 panic, requires 안의 bool 원소 읽기(`flags_matrix`로 `--trust-callers` 포함), 할당/해제 균형(`alloc_balance`, 배열을 Rust로 돌려주지 않는 표본), IR 글자 확인(`llvm_fn_contains`: `zext i1`·`store i8`·`icmp ne i8`·`@pruv_free_v2(`·`@pruv_copy_v2(`).
- raw 표현 검사 `tests/abi/check_bool_repr.py`(새 파일, `check_runtime_v2.py` 방식): 두 컴파일러(Py·Rs)가 낸 IR + 일반 런타임 + C 호출자로 `pruv_abi_<f>`를 직접 부른다. 경우: 바이트 0/1 → 정상 출력, 바이트 2 → 종료 101·stderr `pruv: invalid representation: 2 (bool 0..=1)`, `--trust-callers` 빌드에서 같은 결과, requires가 거짓인 입력에 바이트 2를 같이 주면 표현 오류가 먼저 나온다. `tests/m3_all.py`에 단계 `abi_bool`을 더한다.
- `tests/abi/gen/g2a_bool_ret.pruv`(한 줄 서명, `[bool]` 인자·반환, 중간 copy) + `tests/abi/winci/calls.json` 항목.
