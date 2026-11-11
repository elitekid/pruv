# G2 설계: 원소 저장 타입 배열과 UTF-8 문자열

상태: **확정(2026-11-11)**, 초안 → 설계 논쟁 1회 → 메인 확정. 구현은 다음 묶음부터. 이 문서는 구현 계약이다. 시험 수·성능 기준은 앞으로 충족할 목표이며 측정 결과가 아니다.

**0.0절(확정 결정)이 0절 이하 본문보다 우선한다.** 본문은 초안 그대로 두고, 0.0절과 다른 곳은 0.0절을 따른다.

## 0.0 확정 결정(설계 논쟁 반영)

논쟁에서 받은 지적 15건(필수 9·권고 6) 중 코드 근거를 확인해 다음과 같이 정했다.

1. **첫 판 원소 타입은 `[u8]`·`[bool]`만.** `[i32]`는 부호 확장·4바이트 배치라는 실행 부담만 더하고, 증명 쪽 새 위험(좁은 범위·별도 sort)은 u8·bool이 이미 다 드러낸다. i32는 G2a 뒤 별도 묶음(A6)으로 미룬다. G2a 완료 기록은 "u8·bool"로 적는다.
2. **정의역 도입 지점을 고정한다(건전성).** 좁은 배열의 원소 범위 `forall k in 0..n: 0 <= A[k] <= 255`는 **값이 바깥에서 들어오는 곳에서만** 가정한다: 함수 진입 매개변수, 사용자 함수 호출 결과, 루프 havoc. `alloc`은 초기값의 `elem_range`를 증명한 뒤 상수 배열로, `copy`·재바인딩은 원래 항을 그대로, 원소 저장은 `elem_range`를 증명한 뒤 `Store`로 만든다. **저장·재바인딩 뒤에 범위 가정을 다시 넣지 않는다**(잘못 저장한 값과 모순돼 뒤 의무가 공허하게 참이 되는 길을 막는다). 같은 까닭으로 **코드에서 좁은 배열 원소를 읽을 때의 가정은 지금처럼 i64 범위 그대로 두고 0..255로 좁히지 않는다**(`pruvc/verify.py` 배열 읽기의 `in_range(Select)`, Rust `symbolic.rs`의 같은 지점). 잘못 저장한 뒤 읽는 거부 표본을 둔다. `str`의 바이트 범위 0..255도 같은 세 지점(진입·호출 결과·havoc)과 리터럴·`copy`·`substr` 결과에서만 둔다.
3. **계약 정의역 순서는 지금 그대로.** 범위를 알아도 빈 배열의 `a[0]`은 정의되지 않는다. requires를 검사한 뒤 가정하는 지금 순서(`pruvc/verify.py` 1034 근처)를 바꾸지 않고, 빈 배열 읽기·길이 가드 뒤 읽기·단락된 읽기 표본을 둔다.
4. **`--infer`와의 관계(필수 관문).** Houdini 탐색은 후보 외 의무를 생략하므로, `elem_range`·`utf8_boundary`는 **최종 전체 검증에서만** 판정한다. 잘못된 저장 뒤 루프 탈출·반환·호출이 오는 표본을 `--infer` 켬/끔 모두에서 거부시킨다. 후보의 함수 호출 금지(`len` 외)는 넓히지 않는다. **배열 원소를 읽는 모든 후보 생성기**(`at_k`·`ranges`로 원소를 읽는 종류 5·6·7·8~10·12(배열 초기값)·13·14 — 구현 때 `pruvc/infer.py`에서 `at_k`·`ranges` 사용처를 다시 전수 확인)에 원소 타입 필터를 둔다. 종류 5의 `ranges`는 같은 원소 타입의 배열에서 온 것만 쓴다. bool 배열 원소를 읽거나 쓰는 후보는 G2a에서 만들지 않는다(그대로 두면 bool 배열에 `lo <= b[k]`가 생겨 z3 sort 오류 = 내부 오류가 난다, `pruvc/infer.py` 종류 5 생성부).
5. **bool 배열은 SMT `Array(Int, Bool)`.** 읽기 결과 값 태그(Python 범위 가정, Rust `Val::Int` 고정)와 반례 JSON(`true/false`)을 함께 바꾼다. 길이가 양수인 bool 배열 반례에서 배열 항목이 실제로 나오는지 시험한다. `count(k in ..: a[k])`는 지금 의미 그대로, `sum`에 bool 본문은 거부, 배열 전체 `==`/`!=` 금지는 모든 배열 타입에 적용한다(원소끼리 비교는 허용).
6. **`alloc`의 원소 타입은 좁게 정한다.** 기대 타입 전달을 검사기 전체에 넣지 않는다. `alloc(n, v)`가 **타입을 적은 `let`의 바로 오른쪽, 그 변수의 재대입 바로 오른쪽, `return` 바로 뒤**에 올 때만 그 배열 타입을 쓰고, 그 밖(중첩 `copy`·함수 인자·`len(...)` 안)은 기존대로 `[i64]`다. 3.2절의 `copy(alloc(..))` 전달은 하지 않는다.
7. **내부 타입 이름이 소스로 새지 않게 한다.** 내부 이름 `array_u8`·`array_bool`(그리고 뒤에 올 `array_i32`·`str` 내부 이름)은 소스 타입으로 쓰면 거부한다(must_reject 추가). `u8`은 일반 변수 이름으로 계속 쓸 수 있다.
8. **진단 이름은 기존 것을 따른다.** 정제 원소 저장 실패는 `refinement_assign`(3.4절의 `elem_refine`은 AST 메타데이터 이름일 뿐). 4.3절의 "파생 의무 중복 진단 금지"는 새 규칙으로 넣지 않고 기존 실패 처리 그대로 둔다(기존 trace를 바꾸지 않기 위해).
9. **감사는 구현 묶음마다 1회 + 고친 뒤 확인 1회**(8.5절의 "G2a/G2b 각각"을 대체).
10. **444 기준선은 실행 행 목록으로 고정한다.** 소스 수가 아니라 `run_all`의 (표본·뒷단·플래그·컴파일러) 행 목록을 A0에서 저장하고, 묶음마다 같은 행이 모두 실행·통과했는지 본다.
11. **대조 관문은 `same`만 인정한다.** G2 새 표본의 trace 대조에서 `cex_only`·`same_unknown`은 통과로 세지 않는다. 퍼저는 G2를 실제로 쓰는 생성 수가 목표에 못 미치면 실패로 보고한다.
12. **퍼징·독립 사용 숫자(8.3·8.4)는 G2 전체의 마지막 관문.** 기능 묶음마다는 작은 표본과 변이(저장 상한 ±1, 범위 가드 삭제, 경계 ±1)만 먼저 넣는다.
13. **UTF-8 추상화는 초안대로.** SMT의 `str`은 아무 바이트열이나 될 수 있는 과대 근사이고, 실제 실행에 들어오는 `str`은 모두 유효 UTF-8이므로 이것만으로 거짓 증명이 생기지는 않는다. 대신 (a) 모든 raw 진입의 UTF-8 선검사, (b) 유효 문자열에서 SMT `boundary`와 실행 경계 판정 일치, (c) `substr` 바이트 관계를 G2b 감사 초점으로 둔다. SMT 반례가 유효 UTF-8이라는 보장은 없다고 문서·진단에 적는다.
14. **G2b(`str`)는 G2a를 닫은 뒤 따로 착수한다.** `[u8]` + ASCII 범위 계약을 문자열 지원 완료로 기록하지 않는다.
15. **결정 1에 따른 끝 기준 조정.** 6.2절 거부 표본에서 i32 항목(`g2a_i32_low`·`g2a_i32_high`)은 A6으로 옮기고 `g2a_mixed_argument`는 `[u8]`↔`[bool]`/`[i64]`로 바꾼다. 내부 이름 거부(`g2a_internal_name`)·잘못 저장 뒤 읽기(`g2a_store_then_read`)·bool 후보 미생성(`g2a_infer_bool`)·`sum` bool 본문(`g2a_sum_bool`)을 더해 G2a 최소 표본은 **28개**(26 − i32 2 + 새 4). `g2a_scalar_i32`는 i32를 미뤄도 그대로 두고 기대 코드도 `element_storage_type` 그대로다(스칼라 i32는 G2 어디에서도 열지 않음). 8.2절 examples의 i32 항목(음수 읽기·경계 저장)과 runtime의 i32 항목(읽기 부호 확장)은 A6 끝 기준으로, G2a는 examples **6**·runtime **11**. 8.3절 변이의 i32 부호 확장, 8.4절 독립 사용의 "i32 배열 갱신"은 A6로 옮기고 그 자리는 "u8 배열 갱신(범위 증명)"으로 바꾼다. A6의 끝 기준은 옮겨 간 항목들이다.
16. **아직 구현하지 않은 층은 G2 타입을 명시 진단으로 거부한다.** A1 이후 `[u8]`가 검사를 통과해도 증명·생성 층이 준비되기 전에는 내부 오류(종료 3)나 `--no-verify`의 잘못된 생성으로 흘러가면 안 된다. 진단은 기존 `unsupported_type`(stage는 그 층)으로 하고 메시지에 아직 구현하지 않은 층을 적는다. 각 묶음 끝 기준에 "다음 층이 `unsupported_type`으로 거부"하는 표본을 넣고, 그 층을 구현하는 묶음에서 표본을 양성으로 바꾼다.
17. **G2 변이는 전용 OPS 목록으로 잰다.** 기존 `bench/mutate.py` OPS는 바꾸지 않는다(기존 기준선 `mutants9` 등과 비교 가능하게, 초안 7.7의 `bench/mutate.py` 경계는 이 결정이 대체). G2 전용 목록은 `bench/g2/mutate_ops.py`(제안 경로)에 둔다. 저장 상한 ±1·범위 가드 삭제·경계 ±1은 G2 전용 목록에 두고, 새 통과마다 `--no-verify` 빌드 + 참조 시험으로 참/거짓 변이를 자동 판정한다.

### 0.0.1 구현 묶음(7절을 대체)

| 묶음 | 내용 | 고칠 파일(경계) | 끝 기준 |
|---|---|---|---|
| **A0 기반** | 새 문법 없이, 기존 `[i64]`의 기호 배열에 원소 타입 필드를 넣고 fresh·alloc·copy·재바인딩·Store·호출 결과·havoc에서 보존(`Arr` 생성은 생성자 함수 하나로 모음). 배열 공통 질의 API(`is_array`·`array_elem` 등). 뒤 묶음의 내부 이름(`array_u8`·`array_bool`)↔`Ty` 대응도 여기서 정의. `run_all`에 실행 행 목록 내보내기·비교. SMT 기준 입력 231개 경로 목록과 비교 명령을 저장소에 고정 | Py: `pruvc/vast.py`·`typeinfo.py`·`verify.py` / Rs: `pruv-core/src/typeinfo.rs`, `pruv-proof/src/model.rs`·`symbolic.rs`·`samples.rs`(시제품 경로가 `Arr {..}`를 직접 만듦) / 시험: `tests/run_all.py` | 444 실행 행 목록 저장·두 판 유지, `--infer` 없는 SMT 231파일 바이트 동일, `--infer` 대조 기존과 같은 분류, 새 문법은 아직 거부 |
| **A1 u8 앞단** | `[u8]`(+정제 `[u8 \| L..=U; <=N]`) 문법·타입 검사·`alloc` 좁은 타입 결정(결정 6)·내부 이름 거부 | Py: `vparser.py`·`check.py`·`refine.py` / Rs: `parser.rs`·`check.rs`·`refine.rs`(+`lexer.rs`·`dump.rs` 필요 시) | u8 parse/type 거부 표본 일치, parse/check dump 두 판 동일 |
| **A2 u8 증명** | 정의역 도입(결정 2), `elem_range`, 반례, `--infer` 관문(결정 4) | Py: `verify.py`·`infer.py` / Rs: `symbolic.rs`·`obligation.rs`·`infer.rs`·`model.rs`·`samples.rs` | verify 거부 표본·`--infer` 켬/끔 거부, 새 trace `same`, 기존 SMT 불변 |
| **A3 u8 실행** | 런타임 크기·정렬 일반화와 Rust 소스 생성(안전 모드 범위 검사) | Py: `runtime.c`·`codegen.py` / Rs: `codegen.rs`·`emit_common.rs`·`pruvc/src/runtime.rs` | u8 examples·runtime 표본 두 판·rust 뒷단 통과 |
| **A4 u8 LLVM·ABI** | LLVM 생성·`--rust-bindings`(v2 host helper) | Py: `llvmgen.py` / Rs: `llvmgen.rs`·`abi.rs`·`bindings.rs` | llvm 뒷단 통과, 두 판 IR·바인딩 바이트 동일, 할당/해제 균형 |
| **A5 bool** | 결정 5 전 층(문법→증명→실행→ABI) | A1~A4와 같은 파일, 묶음 안에서 층마다 한 작업자 | bool 표본 전부, 반례 `true/false` |
| A6 i32 | (뒤로 미룸) 부호 확장·4바이트 | 위와 같음 | 결정 15로 옮긴 항목(거부 표본 `g2a_i32_low/high`, i32 examples 2·runtime 1, 부호 확장 변이, 독립 사용 i32 문제) |
| **B0~B2 str** | 문자열 앞단 → 증명 → 실행·raw ABI(초안 7.5·7.6을 둘로 나눈 것 + 실행) | 초안 7.5·7.6 | 초안 끝 기준 + 결정 13 |
| **Q1·Q2** | 오라클·퍼징(seed 41·56·57) → 측정·독립 사용 6문제 | 초안 7.7 | 8.3·8.4 |

묶음마다 Python 판 → Rust 판 이식 → 두 판 대조, 감사 1+확인 1, RESULTS 절·BLUEPRINT 줄. A0의 결과는 "G2 기능"이 아니라 "G2 구현 기반"으로 기록한다.

## 0. 초안 결정 요약(0.0절이 우선)

1. **G2a는 배열 원소 저장 타입을 확장한다.** 기존 `[i64]`에 `[u8]`, `[i32]`, `[bool]`을 추가한다. 스칼라 `u8`, `i32`는 추가하지 않는다.
2. `[u8]`·`[i32]`의 읽기 결과는 `i64`, `[bool]`의 읽기 결과는 `bool`이다. 산술은 계속 i64이며, 좁은 폭의 산술·wrap·암시적 배열 변환은 없다.
3. 좁은 정수 배열의 생성·저장에는 **`elem_range` 증명 의무**를 부과한다. `--no-verify`에서는 같은 범위를 실행 중 검사한 뒤 저장한다.
4. `alloc(n, v)`는 기대 배열 타입을 받는다. 기대 타입이 없으면 기존처럼 `[i64]`다. `copy`는 입력 타입을 보존하고, `len`은 원소 수를 반환한다.
5. 정수 배열에는 기존 정제 문법을 허용한다. `[bool]`에는 길이 정제만 허용한다. Option/Result와 구조체·열거형 필드의 허용 타입은 확장하지 않는다.
6. SMT 표현은 정수 배열에 `Array(Int, Int)`, bool 배열에 **`Array(Int, Bool)`**을 사용한다. 배열의 저장 타입은 기호 실행 상태에서도 보존한다.
7. **G2b는 `str`을 추가한다.** 유효한 UTF-8 바이트열이며 내용은 읽기 전용이다. `len(s)`는 바이트 수, `s[i]`는 해당 바이트의 i64 값이다.
8. G2b에는 문자열 리터럴, `copy(s)`, `is_char_boundary(s, i)`, 경계가 증명된 `substr(s, lo, hi)`를 포함한다. 부분 문자열은 복사하여 소유한다.
9. `[u8] → str` 변환과 `utf8(b, lo, hi)` 술어는 후속 단계로 남긴다. `Option<str>`·`Result<str>`를 우회하여 도입하지 않는다.
10. Rust 표현은 배열 인자에 `&[T]`, 지역·반환에 `Vec<T>`, 문자열 인자에 `&str`, 지역·반환에 `String`을 사용한다. LLVM 표현은 `{ ptr, i64 }`를 유지하되 원소 타입·소유권 정보를 별도로 보존한다.
11. 기존 함수 ABI의 인자 순서·배열 반환 구조는 유지한다. 크기·정렬을 받는 런타임 할당 인터페이스는 v2로 추가한다. 기존 생성 바인딩과 새 런타임의 무조건적인 혼용은 보장하지 않는다.
12. 모든 구현 묶음은 **Python 구현 → Rust 이식 → 두 판 대조** 순서로 닫는다. G2a만 끝났을 때 G2 전체 완료로 기록하지 않는다.

## 1. 범위·비범위

### 1.1 단계별 범위

| 단계 | 포함 |
|---|---|
| G2a | `[u8]`, `[i32]`, `[bool]`, 생성·읽기·쓰기·복사·반환, 정제, 증명, 두 뒷단, ABI |
| G2b | `str`, 리터럴, 바이트 읽기, 경계 판정, 복사 부분 문자열, UTF-8 입력 경계 검사 |
| 후속 | 바이트열의 실패 가능한 문자열 변환, 범용 UTF-8 술어, 문자열 처리 라이브러리 |

G2a와 G2b 모두 함수 매개변수·반환·`let`·`let mut` 위치를 지원한다. 배열 매개변수는 읽기 전용이다. 문자열은 어느 위치에서도 원소를 변경할 수 없다.

### 1.2 비범위

- 스칼라 `u8`·`i32`, 캐스트 문법, 폭별 산술, wrap 연산.
- 중첩 배열, 사용자 타입 배열, 배열 리터럴.
- 배열·문자열을 담는 구조체 필드와 열거형 payload.
- `Option<bool>`, `Option<str>`, `Result<str>` 등 생성자 타입 확장.
- `char`, 코드 포인트 색인, 문자 수·글자소 수, 정규화, 문자열 연결·서식화·출력 확장.
- 빌린 부분 문자열 반환, 수명 매개변수, 배열 뷰·슬라이스 문법.
- 자동 불변식 추론의 새 템플릿. 기존 `--infer`와의 안전한 공존만 이번 범위다.

## 2. 문법

### 2.1 배열

```text
ArrayType :=
    "[" IntegerStorage [ "|" L "..=" U ] [ ";" "<=" N ] "]"
  | "[" "bool" [ ";" "<=" N ] "]"

IntegerStorage := "i64" | "u8" | "i32"
```

`L`, `U`, `N`은 기존 정제 문법의 부호 있는 십진 정수 리터럴이다. 길이 한계는 계속 `0..=2^40`이다.

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

`[bool | 0..=1]`은 허용하지 않는다. `[bool; <=100]`은 허용한다.

`u8`, `i32`는 타입 문법의 배열 원소 위치에서만 특별한 의미가 있다. 이를 전역 키워드로 만들어 기존 변수 이름을 불필요하게 금지하지 않는다.

### 2.2 문자열

```text
StringType := "str"
StringLiteral := '"' StringCharacter* '"'
```

리터럴은 UTF-8 소스의 유니코드 스칼라 값을 그대로 허용한다. 최소 이스케이프 집합은 다음과 같다.

| 표기 | 값 |
|---|---|
| `\"` | 따옴표 |
| `\\` | 역슬래시 |
| `\n` | LF |
| `\r` | CR |
| `\t` | TAB |
| `\0` | NUL |

`\xNN`, `\u{...}`, raw string, 여러 줄 문자열은 제외한다. 실제 줄바꿈과 이스케이프되지 않은 ASCII 제어 문자는 거부한다. NUL은 문자열 종결자가 아니며 길이에 포함된다.

문자열 안의 `//`, 괄호, 정제 기호는 일반 문자다. 렉서는 문자열 전체를 읽은 뒤 주변 토큰 처리를 계속한다. 진단의 열 번호는 기존 문자 단위 규칙을 유지하며 UTF-8 바이트 오프셋으로 바꾸지 않는다.

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

`str`의 정제 약식 문법은 넣지 않는다. 길이·바이트 조건은 일반 계약으로 쓴다.

## 3. 타입 규칙

### 3.1 저장 타입과 식 타입

| 배열 | 저장 값의 범위 | `a[i]`의 식 타입 | 대입 값의 식 타입 |
|---|---:|---|---|
| `[i64]` | `-2^63..=2^63-1` | `i64` | `i64` |
| `[u8]` | `0..=255` | `i64` | `i64` |
| `[i32]` | `-2^31..=2^31-1` | `i64` | `i64` |
| `[bool]` | `false`, `true` | `bool` | `bool` |

`a[i] + 1`은 좁은 정수 배열에서도 i64 덧셈이다. 계산 결과를 다시 배열에 저장할 때 저장 범위를 증명한다. 예를 들어 255인 바이트를 읽어 1을 더하는 것은 가능하지만, 그 256을 `[u8]`에 저장할 수는 없다.

배열 타입은 정확히 일치해야 한다. `[u8]`를 `[i64]` 인자에 전달하거나 `copy`로 다른 원소 타입으로 바꾸는 것은 금지한다.

bool과 정수 사이에는 0/1 변환도 없다. `sum`의 본문에는 정수가 필요하고, bool 배열의 참 개수는 `count(k in 0..len(a): a[k])`로 구한다.

### 3.2 `alloc`의 타입 결정

검사기는 `expect(expr, expected_type, ...)`의 기대 타입을 다음 위치에서 전달한다.

- `let` 초기화: 선언 타입.
- 재대입: 대상 변수 타입.
- `return`: 함수 반환 타입.
- 함수 인자: 해당 매개변수 타입.
- `copy(expr)`: 바깥 기대 배열 타입을 내부 `expr`에도 전달.

`alloc(n, v)`가 기대 배열 타입을 받으면 그 원소 저장 타입을 사용한다. 기대 배열 타입이 없으면 `[i64]`로 결정한다. `v`의 상수 크기나 값에 따라 폭을 추측하지 않는다.

```pruv
let a: [u8] = alloc(4, 0);          // [u8]
let b: [bool] = alloc(4, false);    // [bool]
let c: [i32] = copy(alloc(4, -1));  // [i32]
let n: i64 = len(alloc(4, 0));      // 내부 alloc은 [i64]
```

`len(alloc(4, false))`는 기대 배열 타입이 없으므로 기존 기본 `[i64]`에 따라 타입 오류다. 필요하면 `[bool]` 지역변수에 먼저 바인딩한다.

`copy(a)`의 입력이 이미 타입을 가진 식이면 그 타입을 그대로 보존한다. 기대 타입은 기존 배열 값을 변환하지 않는다.

### 3.3 변경·별칭·효과

- 배열의 `let`·재대입 RHS는 기존처럼 `alloc`, `copy`, 배열 반환 함수 호출에서 온 소유 값이어야 한다.
- 배열 지역변수의 반환은 소유권 이전을 허용한다. 매개변수 반환에는 `copy`가 필요하다.
- 함수 호출의 배열 인자는 빌려 전달하며 호출 뒤에도 사용 가능하다.
- 원소 변경은 `let mut` 지역 배열에만 허용한다.
- `alloc`, `copy`, `substr`는 `alloc` 효과를 요구한다.
- 배열 전체 `==`·`!=`는 계속 금지한다.
- 평가 순서는 그대로 유지한다. 호출 인자는 왼쪽부터, 원소 대입은 색인 → RHS → 저장 순이다.

### 3.4 정제

`[u8 | L..=U]`, `[i32 | L..=U]`는 허용하되 정제 범위 전체가 저장 타입의 범위 안에 있어야 한다. 예를 들어 `[u8 | -1..=127]`은 교집합으로 해석하지 않고 `refinement_bounds`로 거부한다.

길이 정제는 네 배열 모두 허용한다. 기존 정제 펼침 순서와 위치 규칙을 유지한다.

- 매개변수: 길이 조건, 원소 조건 순으로 `requires` 앞에 추가.
- 반환: 대응 `ensures` 추가.
- 지역 초기화·재대입: 기존 정제 의무.
- 원소 저장: 저장 타입 의무 뒤에 기존 `elem_refine` 의무.
- 루프: 기존 정제 불변식 삽입 방식 유지.

저장 타입의 범위와 사용자가 쓴 정제 조건은 별개다. 전자는 안전 모드에서도 반드시 유지하며, 후자는 기존 정제 실행 정책을 유지한다.

### 3.5 문자열

| 식 | 결과 | 효과·제약 |
|---|---|---|
| `"..."` | `str` | 실행 코드에서는 소유 문자열 생성, `alloc` 필요 |
| `len(s)` | `i64` | 바이트 길이 |
| `s[i]` | `i64` | 바이트 값, 색인 범위 의무 |
| `copy(s)` | `str` | 독립 소유 복사, `alloc` 필요 |
| `is_char_boundary(s, i)` | `bool` | 코드·계약 모두 가능, 범위 밖이면 false |
| `substr(s, lo, hi)` | `str` | `[lo, hi)` 복사, 범위·경계 증명, `alloc` 필요 |

문자열의 내용은 불변이다. `let mut s: str`은 문자열 전체의 재대입만 허용한다. 소유권 규칙은 배열과 같되 리터럴도 새 소유 값의 출처로 인정한다. 매개변수를 반환하려면 `copy(s)`를 쓴다.

문자열 리터럴을 계약에서 사용하는 것은 순수한 상수 사용이다. 이때 할당 효과가 없으며, 실행 requires 검사에서는 정적 바이트열을 참조한다. `copy`·`substr`는 계약 안에서 금지한다.

`str`과 `[u8]` 사이에는 암시적 변환이 없다. 문자열 전체 동등성도 이번에는 넣지 않는다.

### 3.6 기존 복합 타입

Option/Result의 payload는 계속 i64만 허용한다. 구조체·열거형 필드는 기존의 `i64`, `bool`, `Option<i64>`, `Result<i64>`, 중첩 사용자 타입을 유지한다. 여기에 배열이나 문자열을 추가하지 않는다.

## 4. 증명 의미론

### 4.1 타입 표현과 기존 SMT 보존

구현 내부의 배열 타입 구별을 한곳에 모은다.

- 기존 `[i64]`의 직렬화 이름 `"array"`는 유지한다.
- 새 이름은 `"array_u8"`, `"array_i32"`, `"array_bool"`, `"str"`로 고정한다.
- Python `Type`과 Rust C의 타입 문자열은 이 이름을 사용한다.
- Rust V는 `Ty::Array(ElemTy)`와 `Ty::Str`로 구별한다.
- `is_array`, `array_elem`, `element_value_type`, `storage_bounds` 같은 공통 질의를 두고 문자열 비교를 여러 단계에 흩뿌리지 않는다.

기호 배열 값은 저장 타입을 함께 보관한다. `fresh`, `copy`, 재바인딩, 호출 결과, 루프 havoc에서 이를 잃으면 안 된다.

G2를 사용하지 않는 입력은 기존 fresh 번호·의무 순서·가정 순서·SMT 이름을 유지한다. 기존 `[i64]` 경로에 새 전칭 범위 가정을 일괄 추가하지 않는다.

### 4.2 배열 모델

| 타입 | 내용 | 길이 |
|---|---|---|
| `[i64]`, `[u8]`, `[i32]` | `Array(Int, Int)` | 별도 Int |
| `[bool]` | `Array(Int, Bool)` | 별도 Int |
| `str` | `Array(Int, Int)`인 바이트열 | 별도 Int |

bool 배열은 SMT Bool 원소를 선택한다. 0/1 인코딩보다 별도 정규화·범위 가정이 적고, bool 식·단락 평가·`count`와 직접 연결된다. 메모리의 0/1 표현은 코드 생성 계층의 책임이다.

새 정수 배열의 매개변수·호출 결과·havoc 결과에는 다음 정의역을 둔다.

```text
0 <= n <= 2^40
forall k: 0 <= k < n ==> lower(E) <= Select(A, k) <= upper(E)
```

bool 배열은 원소 정의역이 sort로 보장된다. 길이 밖 원소에는 추가 의미를 주지 않는다.

`alloc`은 상수 배열, `copy`는 내용·길이가 같은 별도 실행 저장소, 대입은 `Store`로 모델링한다. 범위 의무를 증명하지 않은 값을 먼저 좁혀서 모델링하거나 그 범위를 가정해서는 안 된다.

### 4.3 의무와 순서

| 연산 | 의무 |
|---|---|
| 코드의 배열·문자열 읽기 | 기존 `index_oob` |
| 계약의 배열·문자열 읽기 | 기존 `contract_domain` |
| 코드의 산술 | 기존 `overflow`, 나눗셈 정의역 의무 |
| `alloc(n, v)` | 기존 `alloc_negative`, 이후 새 `elem_range` |
| 좁은 정수 배열 원소 대입 | `index_oob` → `elem_range` → 기존 `refinement_assign` |
| `substr(s, lo, hi)` | 새 `string_slice_range` → 새 `utf8_boundary` |

세부 규칙:

- 인자·색인·RHS는 각각 한 번만 평가한다. 의무를 만들기 위해 식을 다시 실행하지 않는다.
- `elem_range`는 `[u8]`·`[i32]` 생성과 저장에 적용한다. `[bool]`은 타입 검사, `[i64]`는 기존 i64 식 범위 검사를 사용한다.
- `alloc(0, v)`도 `v`를 평가하고 저장 타입 범위를 요구한다. 빈 배열이라는 이유로 범위 검사를 생략하지 않는다.
- 범위 실패에 의존하는 후속 저장·반환은 검증 성공으로 취급하지 않는다.
- 정의역·색인 실패 뒤 같은 연산의 파생 의무로 중복 진단하지 않는다.
- `unknown`·timeout은 증명 성공이 아니다.
- `elem_range`는 생성 시 호출 위치, 저장 시 대입 위치를 가리킨다.

### 4.4 UTF-8와 경계

`str`의 언어 의미는 유효한 UTF-8이다. G2b에서는 이를 임의의 바이트 배열에 붙이는 SMT 술어로 제공하지 않는다.

유효성은 다음 생성 경로로 보장한다.

1. 유효한 소스 문자열 리터럴.
2. Rust의 유효한 `&str` 또는 raw ABI 진입에서 검사한 바이트열.
3. 기존 `str`의 복사.
4. 기존 `str`에서 양 끝 경계를 증명한 부분 문자열.
5. 위 규칙을 지키는 함수의 반환.

SMT는 유효한 문자열을 포함하는 바이트 배열 모델로 보수적으로 추상화한다. 새 `str` 값에는 바이트 범위와 길이를 가정하지만, 불완전한 UTF-8 공리를 임의로 추가하지 않는다. 따라서 유효 UTF-8에서 참인 모든 성질을 자동 증명하는 것은 목표가 아니다.

경계 판정은 다음 식으로 고정한다.

```text
boundary(A, n, i) =
    (i == 0)
    or (i == n)
    or (0 < i and i < n
        and (Select(A, i) < 128 or Select(A, i) >= 192))
```

유효한 UTF-8에서는 내부 위치의 바이트가 continuation byte가 아니면 문자 경계다. 음수와 `n` 초과 위치는 false다. 경계 판정 자체는 전체 정의된 연산이며 `contract_domain`을 추가하지 않는다. 단, 인자 식 자체의 정의역은 검사한다.

`substr`의 의무는 다음과 같다.

```text
string_slice_range: 0 <= lo <= hi <= len(s)
utf8_boundary:      boundary(s, lo) and boundary(s, hi)
```

결과 모델은 다음을 만족한다.

```text
len(result) = hi - lo
forall k:
    0 <= k < len(result) ==> result[k] = s[lo + k]
```

두 경계는 하나의 `utf8_boundary` 의무로 묶어 기존 진단 중복 제거 키와 충돌하지 않게 한다. `lo == hi`라도 그 위치는 문자 경계여야 한다.

"유효 UTF-8의 경계 사이를 자르면 유효 UTF-8"이라는 규칙은 컴파일러가 신뢰하는 문자열 생성 규칙이다. 이 규칙과 실행 구현의 일치를 감사 대상으로 명시한다.

### 4.5 계약과 추론

새 타입에도 기존 계약 정의역·단락·양화 순서를 적용한다. 자신의 조건을 가정한 뒤 그 조건의 정의역을 증명하지 않는다.

`--infer`의 새 배열·문자열 전용 후보는 추가하지 않는다. 기존 템플릿이 새 타입을 만나면 타입이 맞는 후보만 생성하거나 건너뛴다. 특히 bool 원소를 정수 범위 후보에 넣지 않는다. `--infer` 유무와 무관하게 저장 범위·문자열 경계 의무는 빠지지 않는다.

## 5. 코드 생성

### 5.1 Rust

| Pruv | 매개변수 | 지역·반환 | 읽기 |
|---|---|---|---|
| `[i64]` | `&[i64]` | `Vec<i64>` | i64 |
| `[u8]` | `&[u8]` | `Vec<u8>` | i64로 확대 |
| `[i32]` | `&[i32]` | `Vec<i32>` | 부호를 보존하여 i64로 확대 |
| `[bool]` | `&[bool]` | `Vec<bool>` | bool |
| `str` | `&str` | `String` | `as_bytes()`의 원소를 i64로 확대 |

증명 모드에서는 범위가 증명된 정수만 저장 타입으로 좁힌다. 안전 모드에서는 축소 전에 범위를 검사한다. 단순 `as u8`·`as i32`로 먼저 잘라낸 뒤 검사해서는 안 된다.

기존 `[i64]` helper는 보존하고 새 타입에 필요한 helper를 추가한다. 계약의 정수 배열 읽기는 i128로 확대하며 bool 읽기는 bool을 유지한다.

`substr`는 증명 모드에서 증명된 경계를 사용하고, 안전 모드에서는 범위와 경계를 검사한 뒤 복사한다. `is_char_boundary`는 음수·큰 i128 계약 인덱스를 먼저 처리하고, 유효한 범위에서만 `usize`로 변환한다.

문자열 리터럴은 바이트 내용이 명확한 방식으로 이스케이프하여 출력한다. Python과 Rust 생성기가 호스트 언어의 서로 다른 기본 문자열 repr에 의존하지 않는다.

### 5.2 LLVM

집합체 모양은 `{ ptr, i64 }`를 유지한다. 길이는 바이트 크기가 아니라 **원소 수**다. `str`만 원소가 바이트이므로 길이와 바이트 크기가 같다.

| 원소 | 메모리 타입 | 크기·정렬 | 코드 식으로 읽기 |
|---|---|---|---|
| i64 | `i64` | 8·8 | 그대로 |
| u8 | `i8` | 1·1 | `zext` → i64 |
| i32 | `i32` | 4·4 | `sext` → i64 |
| bool | `i8`, 0/1 | 1·1 | bool 값으로 변환 |
| str 바이트 | `i8` | 1·1 | `zext` → i64 |

위 크기·정렬은 현재 지원하는 대상 ABI에서 확인할 계약이다. 대상별 검사가 이를 충족해야 출시한다.

- bool 배열은 비트 압축하지 않는다. 저장 시 i1 값을 0/1 i8로 쓴다.
- GEP·load·store·copy·free는 저장 타입을 따른다.
- 내부 `V`, `Slot`, 임시값·소유 배열 목록에도 원소 타입을 보존한다. `Kind::Arr`만으로 크기를 결정하지 않는다.
- 증명 모드에서만 증명에 근거한 `inbounds`·산술 속성을 사용한다.
- 안전 모드는 색인·저장 범위·부분 문자열 경계를 검사한 뒤 접근한다.
- 재대입·분기·조기 반환·임시 호출 값의 해제에 정확한 원소 크기·정렬을 전달한다.
- `substr`는 원본 중간 포인터를 반환하지 않는다. 새 버퍼를 할당하여 복사하므로 원본 수명에 종속되지 않는다.
- 빈 문자열·빈 배열은 역참조·해제를 하지 않으며, null을 `Vec::from_raw_parts`에 넘기지 않는다.

### 5.3 런타임

기존 `pruv_alloc`, `pruv_copy`, `pruv_free`의 서명을 바꾸지 않는다. 새 구현에서는 다음 책임을 분리한다.

- 타입별 채우기: i64, u8, i32, bool.
- 일반 할당·복사·해제: 원소 수, 크기, 정렬.
- Rust allocator 연동: 실제 할당·해제에 사용한 동일한 Layout.
- UTF-8 검사와 문자열 부분 복사.
- 기존 할당·해제 계수.

v2 크기 계산은 곱셈 전에 검증한다.

```text
0 <= len <= 2^40
elem_size, elem_align은 허용된 타입 배치
len * elem_size는 SIZE_MAX와 대상 할당 한계 이내
```

i32의 일반 값 채우기를 `memset`으로 대신하지 않는다. 0 채우기는 모든 지원 타입에서 가능하다.

Rust host helper에는 v2 이름으로 크기·정렬을 전달한다. `pruv_host_alloc_v2`·`pruv_host_alloc_zeroed_v2`·`pruv_host_free_v2`의 할당/해제 Layout이 일치해야 한다. 반환 버퍼의 capacity는 len으로 고정한다.

안전 모드의 새 실패 메시지와 종료 코드는 두 뒷단에서 일치시킨다.

| 상황 | stderr 접두어 | 종료 |
|---|---|---:|
| 저장 범위 위반 | `pruv: element out of range:` | 101 |
| 부분 문자열 범위 위반 | `pruv: string slice out of bounds:` | 101 |
| UTF-8 경계 위반 | `pruv: UTF-8 boundary error:` | 101 |
| raw 입력의 잘못된 표현 | `pruv: invalid representation:` | 101 |

`--trust-callers`는 사용자 requires 검사를 생략한다. 안전 모드의 저장 범위 검사와 raw 입력의 bool·UTF-8 표현 검사를 생략하는 옵션으로 확대하지 않는다.

### 5.4 `--rust-bindings` ABI와 호환성

| Pruv 입력 | raw ABI |
|---|---|
| `[i64]` | 기존 `*const i64`, len |
| `[u8]` | `*const u8`, len |
| `[i32]` | `*const i32`, len |
| `[bool]` | `*const u8`, len, 각 바이트 0/1 |
| `str` | `*const u8`, 바이트 len, 유효 UTF-8 |

배열·문자열 반환은 기존처럼 마지막 out 포인터를 사용하고 함수는 void를 반환한다.

- 기존 `Pruv__Array { data: *mut i64, len: i64 }`를 유지한다.
- 새 타입에는 각각 `Pruv__ArrayU8`, `Pruv__ArrayI32`, `Pruv__ArrayBool`, `Pruv__Str`를 둔다.
- bool raw 포인터는 u8로 표현한다. 유효성을 확인하기 전에 Rust bool 참조를 만들지 않는다.
- 반환 bool 버퍼는 0/1로만 채워진다. 검사 후 동일 Layout의 `Vec<bool>`로 인수한다.
- 문자열 반환은 u8 버퍼를 인수한 뒤 유효성을 확인하여 `String`으로 만든다.
- raw 진입의 bool·UTF-8 검사는 본문과 사용자 requires보다 먼저 한다. typed Rust의 `&[bool]`·`&str` 경로는 언어 타입이 표현 유효성을 보장한다.
- raw 포인터의 실제 할당 크기·수명·접근 가능성은 외부 호출자의 계약이다. 바이트 검사로 임의 포인터의 안전성을 보장한다고 주장하지 않는다.

호환성은 다음처럼 구분한다.

1. 기존 Pruv 프로그램과 공개 Rust 함수 서명은 유지한다.
2. 기존 `pruv_abi_*`의 i64 배열 인자·반환 배치를 유지한다. 사용자 함수의 타입을 바꾸면 그 함수 ABI도 바뀐다.
3. 런타임/host helper 프로토콜은 v2로 올리고 새 바인딩이 v2 marker를 참조한다. 구 런타임과의 잘못된 링크는 실패해야 한다.
4. 기존 생성 바인딩 소스를 새 런타임에 그대로 붙이는 조합은 보장하지 않는다. 재생성·재링크가 필요하다. 기존에 완성된 실행 파일은 영향을 받지 않는다.
5. 기존 출력의 **과거 대비** 바이트 동일성은 SMT에 요구한다. 생성 소스의 helper 변경은 허용하되 **Python/Rust 두 판 사이**의 출력 바이트는 같아야 한다.

## 6. 오류 코드와 must_reject

### 6.1 새 코드

| stage | code | 조건 |
|---|---|---|
| parse | `element_storage_type` | 스칼라 타입 위치에 `u8`·`i32` 사용 |
| verify | `elem_range` | 좁은 배열의 생성·저장 값 범위를 증명하지 못함 |
| parse | `string_escape` | 지원하지 않거나 불완전한 이스케이프 |
| parse | `string_unterminated` | 닫는 따옴표 없이 EOF |
| parse | `string_character` | 리터럴의 실제 줄바꿈·허용하지 않는 제어 문자 |
| type | `immutable_string` | 문자열 원소 대입 |
| verify | `string_slice_range` | `0 <= lo <= hi <= len(s)`를 증명하지 못함 |
| verify | `utf8_boundary` | 부분 문자열의 양 끝 경계를 증명하지 못함 |

기존 `syntax`, `unsupported_type`, `type_mismatch`, `immutable`, `array_alias`, `eq_type`, `field_type`, `refinement_base`, `refinement_bounds`, `refinement_assign`, `index_oob`, `contract_domain`, `alloc_negative`, `missing_effect`는 재사용한다.

검증 실패 JSON과 종료 코드 1 규약은 유지한다. 미증명과 solver unknown은 구분한다. 기존 입력의 진단 순서를 일반 정리 작업으로 바꾸지 않는다.

### 6.2 G2a 거부 표본: 최소 26개

각 이름은 `tests/must_reject/` 아래 `.pruv`와 기대 stage/code를 담은 `.json` 쌍이다.

| 이름 | 틀린 조건 | 기대 stage/code |
|---|---|---|
| `g2a_scalar_u8` | `x: u8` | parse / `element_storage_type` |
| `g2a_scalar_i32` | `-> i32` | parse / `element_storage_type` |
| `g2a_nested_array` | `[[i64]]` | parse / `syntax` |
| `g2a_user_element` | `[Point]` | parse / `unsupported_type` |
| `g2a_option_u8` | `Option<u8>` | parse / `unsupported_type` |
| `g2a_array_field` | 구조체의 `[u8]` 필드 | type / `field_type` |
| `g2a_mixed_argument` | `[u8]`를 `[i32]` 인자에 전달 | type / `type_mismatch` |
| `g2a_bool_fill` | `[bool] = alloc(1, 0)` | type / `type_mismatch` |
| `g2a_bool_store` | bool 배열에 1 저장 | type / `type_mismatch` |
| `g2a_bool_read_int` | bool 원소를 i64에 바인딩 | type / `type_mismatch` |
| `g2a_param_store` | 배열 매개변수 변경 | type / `immutable` |
| `g2a_alias` | 지역 배열을 직접 다른 지역에 바인딩 | type / `array_alias` |
| `g2a_array_eq` | 배열 전체 `==` | type / `eq_type` |
| `g2a_u8_negative` | 정상 색인에 -1 저장 | verify / `elem_range` |
| `g2a_u8_high` | 정상 색인에 256 저장 | verify / `elem_range` |
| `g2a_i32_low` | -2147483649 저장 | verify / `elem_range` |
| `g2a_i32_high` | 2147483648 저장 | verify / `elem_range` |
| `g2a_alloc_value` | `[u8] = alloc(0, 256)` | verify / `elem_range` |
| `g2a_store_index` | 길이와 같은 색인에 정상 값 저장 | verify / `index_oob` |
| `g2a_refine_wide` | `[u8 \| -1..=127]` | type / `refinement_bounds` |
| `g2a_bool_refine` | `[bool \| 0..=1]` | type / `refinement_base` |
| `g2a_refined_store` | `[u8 \| 0..=127]`에 128 저장 | verify / `refinement_assign` |
| `g2a_return_mismatch` | `[u8]` 함수에서 `[i64]` 반환 | type / `type_mismatch` |
| `g2a_contract_oob` | 빈 배열의 원소를 계약에서 읽음 | verify / `contract_domain` |
| `g2a_alloc_length` | 음수 길이 생성 | verify / `alloc_negative` |
| `g2a_missing_alloc` | 효과 선언 없이 새 배열 생성 | effect / `missing_effect` |

### 6.3 G2b 거부 표본: 최소 16개

| 이름 | 틀린 조건 | 기대 stage/code |
|---|---|---|
| `g2b_escape` | `"\xFF"` | parse / `string_escape` |
| `g2b_unterminated` | EOF까지 닫히지 않은 리터럴 | parse / `string_unterminated` |
| `g2b_newline` | 리터럴 안 실제 줄바꿈 | parse / `string_character` |
| `g2b_store` | `let mut s: str`의 원소 대입 | type / `immutable_string` |
| `g2b_alias` | 기존 문자열을 새 소유 지역에 직접 바인딩 | type / `array_alias` |
| `g2b_field` | 구조체의 str 필드 | type / `field_type` |
| `g2b_to_bytes` | str을 `[u8]`에 대입 | type / `type_mismatch` |
| `g2b_from_bytes` | `[u8]`를 str에 대입 | type / `type_mismatch` |
| `g2b_eq` | 문자열 전체 `==` | type / `eq_type` |
| `g2b_slice_range` | `lo > hi` | verify / `string_slice_range` |
| `g2b_slice_start` | `"é"`의 시작을 바이트 1로 자름 | verify / `utf8_boundary` |
| `g2b_slice_end` | `"é"`의 끝을 바이트 1로 자름 | verify / `utf8_boundary` |
| `g2b_index` | `s[len(s)]` | verify / `index_oob` |
| `g2b_contract_index` | 계약의 범위 밖 문자열 읽기 | verify / `contract_domain` |
| `g2b_missing_alloc` | 효과 선언 없이 실행 리터럴 생성 | effect / `missing_effect` |
| `g2b_option_str` | `Option<str>` | parse / `unsupported_type` |

각 표본은 목표 오류 이전의 다른 의무가 모두 성립하도록 작성한다. 잘못된 UTF-8 raw 입력은 Pruv 소스 거부 시험이 아니라 ABI 실행 시험에 넣는다.

## 7. 구현 묶음과 파일 경계

경로 약칭: `P/` = `pruvc/`, `C/` = `pruvc-rs/crates/pruv-core/src/`, `V/` = `pruvc-rs/crates/pruv-proof/src/`. 신규 파일은 구현 시 추가할 제안 경로다.

### 7.1 작업 소유권 규칙

하나의 파일은 동시에 한 작업자만 수정한다. 특히 Python의 `llvmgen.py`에는 LLVM·ABI·바인딩이 함께 있으므로 이 셋을 서로 다른 작업자에게 동시에 맡기지 않는다.

공유 AST·타입 API를 먼저 확정한 뒤 소비자 작업을 진행한다. 묶음 사이에서 같은 파일을 다시 고칠 수는 있지만, 앞 묶음이 닫히고 소유권을 넘긴 뒤에 한다. 시험 담당자는 전용 새 표본을 병렬 작성할 수 있고 공용 하네스 수정은 별도 소유자가 직렬로 통합한다.

### 7.2 묶음 A1: 배열 프런트엔드

- 파일 — Python: `P/vast.py`, `P/typeinfo.py`, `P/vparser.py`, `P/check.py`, `P/refine.py` / Rust: `C/ast.rs`, `C/typeinfo.rs`, `C/lexer.rs`, `C/parser.rs`, `C/check.rs`, `C/refine.rs`, `C/dump.rs` / 대조: `tests/diff_py_adapter.py`, `tests/diff_parse.py`, `tests/diff_compilers.py` / 표본: `tests/must_reject/g2a_*.{pruv,json}`, `tests/check_edge/g2a_*.pruv`
- 내용: 원소 타입 식별·기대 타입 전달·정제·오류를 Python에서 먼저 확정하고 Rust에 이식한다. `|` 렉싱의 타입 이름 허용 집합도 수정한다.
- 끝 기준: G2a의 parse/type/effect 거부 표본 모두 기대 코드 일치. `alloc`의 직접·중첩 `copy`·인자·반환·기대 타입 없는 위치 검사. parse/check dump 두 판 바이트 동일. 기존 프런트엔드 대조에서 새 차이 0. 증명·뒷단이 완성되기 전에는 G2a 사용 가능 릴리스로 배포하지 않음.

### 7.3 묶음 A2: 배열 증명

- 파일 — Python: `P/verify.py`, `P/infer.py` / Rust: `V/model.rs`, `V/symbolic.rs`, `V/obligation.rs`, `V/infer.rs`, `V/samples.rs` / 대조: `tests/diff_trace.py`, `tests/diff_py_adapter.py` / 표본: G2a verify 거부 표본, `examples/g2a_*.pruv`
- 내용: 타입을 보존하는 기호 배열, bool sort, 좁은 원소 정의역, 생성·저장 의무, 반례의 bool 출력, 추론의 타입 필터를 구현한다.
- 끝 기준: G2a 26개 거부 표본 완성. 좁은 배열의 인자·호출 결과·루프 havoc·분기·복사 후 저장 표본 통과. G2a trace의 SMT·의무 순서 두 판 동일. 기존 입력의 `--infer` 없는 SMT 바이트 불변. 잘못된 저장을 `--infer`가 통과시키는 사례 0.

### 7.4 묶음 A3: 배열 실행·ABI

- 파일 — Rust 소스 생성: `P/codegen.py`, `C/codegen.rs`, `C/emit_common.rs` / LLVM·ABI: `P/llvmgen.py`, `C/llvmgen.rs`, `C/abi.rs`, `C/bindings.rs` / 런타임: `P/runtime.c`, `pruvc-rs/crates/pruvc/build.rs`, `pruvc-rs/crates/pruvc/src/runtime.rs` / 시험: `tests/run_all.py`, `tests/diff_rust.py`, `tests/diff_llvm.py`, `tests/abi/check_generated.py`, `tests/abi/check_abi.py`, `tests/abi/gen/g2a_*.pruv`, `tests/runtime/g2a_*`
- 내용: 원소별 저장·확대·축소, 안전 모드 검사, 정확한 할당 Layout과 해제, v2 host 프로토콜, typed/raw ABI를 구현한다. Rust 소스 생성과 LLVM 생성은 파일이 겹치지 않으므로 병렬 진행할 수 있다.
- 끝 기준: G2a examples 최소 8개, runtime 최소 12개. 두 뒷단·두 컴파일러에서 정상 값과 오류의 순서·메시지 일치. 원소 크기·정렬·부호 확장·bool 0/1·빈 배열·반환 버퍼 Layout 확인. 재대입·임시값·분기·조기 반환의 할당/해제 균형 확인. 잘못된 런타임 버전 링크 실패 시험. 기존 회귀 444개 유지, 새 표본 별도 집계.

### 7.5 묶음 B1: 문자열 프런트엔드·증명

- 파일 — Python: `P/vast.py`, `P/typeinfo.py`, `P/vparser.py`, `P/check.py`, `P/refine.py`, `P/verify.py`, `P/infer.py` / Rust: `C/ast.rs`, `C/typeinfo.rs`, `C/lexer.rs`, `C/parser.rs`, `C/check.rs`, `C/refine.rs`, `C/dump.rs`, `V/model.rs`, `V/symbolic.rs`, `V/obligation.rs`, `V/infer.rs` / 대조: `tests/diff_py_adapter.py`, `tests/diff_parse.py`, `tests/diff_trace.py` / 표본: `tests/must_reject/g2b_*`, `examples/g2b_*.pruv`
- 내용: 문자열 토큰·AST·타입·효과, 리터럴 바이트 상수, 경계 판정, 복사 부분 문자열 관계를 구현한다. AST 순회에서 문자열 리터럴을 빠뜨리지 않게 정제·추론도 갱신한다.
- 끝 기준: G2b 거부 표본 16개 완성. ASCII, 한글, 2/3/4바이트 문자, 빈 문자열, NUL의 파싱·바이트 길이 일치. `0`, 끝, 내부 경계, continuation 위치, 음수·끝 초과 경계 판정 확인. 리터럴→복사→부분 문자열→함수 반환에서 문자열 타입 보존. 기존 SMT 불변과 새 trace 대조 통과.

### 7.6 묶음 B2: 문자열 실행·ABI

- 파일 — Python: `P/codegen.py`, `P/llvmgen.py`, `P/runtime.c` / Rust: `C/codegen.rs`, `C/emit_common.rs`, `C/llvmgen.rs`, `C/abi.rs`, `C/bindings.rs` / 시험: `tests/runtime/g2b_*`, `tests/abi/gen/g2b_*.pruv`, `tests/abi/check_generated.py`, `tests/abi/winci/prepare.py`, `tests/abi/winci/run_windows.py` / 공용 하네스: `tests/run_all.py`, `tests/diff_rust.py`, `tests/diff_llvm.py`
- 끝 기준: G2b examples 최소 6개, runtime 최소 12개. 부분 문자열이 독립 소유 버퍼이며 원본 해제 뒤에도 유효함. 안전 모드의 범위·경계 오류가 두 뒷단에서 동일함. raw ABI에서 잘못된 UTF-8 거부(고립 continuation, 잘린 다중 바이트, overlong, surrogate, U+10FFFF 초과). NUL 포함 입력이 잘리지 않음. `--trust-callers`에서도 표현 유효성 검사 유지. G2a와 기존 회귀 모두 유지.

### 7.7 묶음 Q: 퍼징·변이·독립 사용·문서

- 파일 — 퍼저: `bench/fuzz/{generate,oracle,run}.py`, `bench/fuzz/README.md` / 변이: `bench/mutate.py`, `bench/inference/mutate_infer.py` / 신규 G2 측정: `bench/g2/{PROBLEMS.md,reference.rs,run.py,solutions/,results/}` / 문서: `SPEC.md`, `BLUEPRINT.md`, `RESULTS.md`, `docs/G2_SPEC.md`
- 오라클은 컴파일러 구현을 import하지 않고 원소 범위·UTF-8·부분 문자열을 독립 해석한다.
- 끝 기준: 8절의 대조·회귀·퍼징·변이·bench·감사·독립 사용 관문을 모두 충족한다. `SPEC.md`에는 G2 사용자 규칙을 한 쪽 이내로 요약하고 자세한 구현 계약은 이 문서에 둔다.

## 8. 끝 기준·측정

### 8.1 대조와 회귀

- 기존 `run_all --backend both`의 **444개 기준선**을 입력 목록으로 고정한다. Python·Rust 양쪽에서 유지해야 한다.
- 새 표본은 G2a/G2b로 별도 집계한다.
- parse/check dump, 검증 trace, Rust 출력, LLVM IR·바인딩을 두 판에서 대조한다.
- `diff_trace.py`는 `cex_only`·`same_unknown`을 구분한다. 종료 코드 0만으로 "바이트 동일"이라고 기록하지 않는다.
- 새 결정적 관문 corpus는 raw trace까지 동일해야 한다.
- 기존 입력의 `--infer` 없는 SMT는 G2 이전 baseline과 바이트 동일해야 한다. solver 버전·옵션을 고정한다.
- `--infer` 켬/끔을 모두 검사하되 G2 완료가 추론 기본 활성화를 의미하지 않는다.

### 8.2 최소 양성·실행 표본

| 단계 | examples 파일 | runtime 묶음 |
|---|---:|---:|
| G2a | 8 | 12 |
| G2b | 6 | 12 |

G2a examples는 u8 복사·ASCII 정제·i32 음수 읽기·i32 경계 저장·bool 생성·bool count·기대 타입 전달·루프 원소 변경을 포함한다. G2a runtime은 원소 양 끝값, 잘못된 축소, 0길이 생성 값 검사, 읽기 부호 확장, bool 배치, 평가 순서, 복사 독립성, 함수 반환, 재대입·조기 반환 해제, 정제 진입, raw bool 검사를 포함한다.

G2b examples는 리터럴 바이트 길이·바이트 읽기·복사 반환·ASCII 부분 문자열·다중 바이트 경계 부분 문자열·경계 분기를 포함한다. G2b runtime은 이스케이프·NUL·빈 문자열·다중 바이트·음수/큰 경계·양 끝 경계·잘못된 부분 문자열·평가 순서·재대입·중첩 임시값·반환 소유권·잘못된 UTF-8 ABI 입력을 포함한다.

안전 모드에서만 실행 가능한 거부 프로그램은 검증 거부를 먼저 확인한 뒤 안전 모드의 panic을 검사한다. UB 가능성이 있는 증명 없는 코드를 증명 모드로 실행하지 않는다.

### 8.3 퍼저·변이

- 고정 seed 41·56·57 각각에서 G2를 실제 사용하는 검증 통과 프로그램 최소 200개와 프로그램당 입력 최소 8개를 목표로 한다.
- 두 컴파일러·두 뒷단·증명/안전 모드를 독립 오라클과 비교한다.
- 각 seed에서 미증명 프로그램 최소 30개를 안전 모드로 실행한다.
- 부족한 생성 수, 지원하지 않는 오라클 구문, timeout, incomplete는 통과 수에서 제외하여 보고한다.
- G2 변이에 최소한 저장 상한 ±1, i32 부호 확장 오류를 드러내는 입력, 범위 가드 삭제, 색인 끝값 변경, 부분 문자열 경계 ±1, 경계 조건 삭제를 포함한다.
- 기존 변이 corpus의 판정 저하가 없어야 한다. 새 잘못된 변이가 검증을 통과한 수는 0이어야 한다.
- 참인 변이의 통과는 오류와 구분한다. 컴파일러 crash·timeout을 올바른 거부로 세지 않는다.

### 8.4 bench와 독립 사용

| 측정 | 요구 |
|---|---|
| 기존 bench 정답·검증 성공률 | 감소 없음 |
| 기존 compile/proof 시간 | 중앙값·상위 지연 기록, 반복 측정 10% 초과 악화는 원인 해결 후 관문 판단 |
| 배열 실행 시간·메모리 | i64 기준 대비 u8/i32/bool을 각각 측정 |
| 문자열 처리 | 바이트 스캔·부분 복사·ABI UTF-8 검사 비용 분리 |
| 계약 작성량 | 같은 문제의 i64 배열 표현과 새 표현 비교 |
| solver | 의무 수·양화 수·unknown·timeout 기록 |

**추측:** 좁은 배열은 메모리 사용량과 일부 스캔 비용을 줄일 수 있다. 새 전칭 범위 가정은 검증 시간을 늘릴 수 있다. 수치 이득은 구현 후 측정 전까지 주장하지 않는다.

독립 사용 문제는 바이트 범위 변환, ASCII 필터, i32 배열 갱신, bool 집계, UTF-8 바이트 탐색, 경계 기반 부분 문자열의 6개로 한다. 독립 작성자에게는 사용자 명세와 문제만 제공한다. 첫 시도 성공 수·진단으로 수정한 횟수·최종 성공 수를 기록한다. 참조 풀이와 수정 후 독립 풀이가 모두 6/6 통과해야 한다. 첫 시도 결과는 숨기지 않는다.

### 8.5 감사

G2a와 G2b 각각 감사 1회와 수정 확인 1회를 수행한다. 필수 지적 미해결 0을 요구한다. 감사 초점: 가정 전에 증명해야 하는 생성·저장 범위, 계약에서 범위 밖 원소의 범위를 부당하게 가정하는지, bool sort와 메모리 표현의 일치, 호출 결과·havoc·별칭 처리에서 타입을 잃는지, 부분 문자열의 양 끝과 빈 부분 문자열, 리터럴·raw ABI·반환의 UTF-8 유효성, 정확한 allocator Layout과 반환 소유권, 기존 프로그램의 SMT·의무 순서 보존.

## 9. 남긴 것·반대 의견

### 9.1 확인한 사실(설계 시점 코드)

- Python AST 타입은 이름 기반이고 Rust C도 타입 이름 문자열을 사용한다. Rust V의 `Ty::Array`에는 원소 타입 인자가 없다(`pruvc/vast.py:10`, `pruv-core/src/ast.rs:5`, `pruv-proof/src/model.rs:38`).
- 배열 파서는 `[i64]`만 허용하며 읽기·대입 값은 i64로 고정되어 있다(`pruvc/vparser.py` `type_r`, `pruvc/check.py:209`(쓰기)·372(읽기), `pruv-core/src/parser.rs:309`, `pruv-core/src/check.rs:517`).
- 배열의 새 소유 값 출처와 반환에 별칭 제한이 있다. `alloc`·`copy`는 alloc 효과를 요구한다(`pruvc/check.py` `array_source`(309), `call`의 alloc 효과(496~502)).
- 정제는 기존 계약으로 펼쳐지고 원소 저장 의무는 이미 평가된 값에 적용된다(`pruvc/refine.py`, `pruvc/verify.py:881`, `pruv-proof/src/symbolic.rs:1436`).
- 런타임은 i64 크기 8과 Rust host의 i64 Layout을 사용하고, 바인딩은 반환 배열을 `Vec::from_raw_parts`로 인수한다(`pruvc/runtime.c:108`, `pruv-core/src/bindings.rs` host 할당(11~), 반환 인수(313)).
- 렉서에 따옴표 토큰이 없다(`pruvc/vparser.py:13,42`, `pruv-core/src/lexer.rs:83-148`).

### 9.2 확인하지 못한 것

- 제안한 새 오류·원소 타입·문자열 기능은 구현되지 않았으므로 실제 통과 여부를 확인하지 않았다.
- 대상별 새 원소 배치, allocator 결합, Windows 실행 ABI, UTF-8 검사 성능은 구현 뒤 검증해야 한다.

### 9.3 후속으로 남기는 기능

`[u8] → str`은 실패가 언어 값으로 표현되어야 한다. 후속 단계에서 `Result<str>` 등 소유 payload를 담는 타입 확장을 먼저 설계한 뒤 변환 API를 정한다.

`utf8(b, lo, hi)`를 추가한다면 단순 미해석 술어로 통과시키지 않는다. 정확한 UTF-8 의미, 실행 검사, 배열 변경 뒤 사실의 무효화, 부분 구간의 양 끝 해석, solver 비용을 함께 명세해야 한다.

문자 수·정규화·문자열 동등성·연결·출력·빌린 부분 문자열은 별도 기능이다. G2b의 바이트 의미를 암묵적으로 변경하지 않는다.

### 9.4 초안 작성자의 반대 의견

1. 저장 타입 범위를 기존 정제 주석과 완전히 같은 것으로 취급해서는 안 된다. 정제는 기존 실행 정책을 유지할 수 있지만, 좁은 저장 타입은 안전 모드에서도 범위를 검사해야 값이 잘리지 않는다.
2. `str`의 모든 위치를 Rust `&str`로 내리는 안에는 반대한다. 인자는 `&str`, 지역·반환은 `String`, 부분 문자열은 복사하는 안이 첫 판에 맞다.
3. `utf8` 술어와 실패 가능한 변환을 G2b에 함께 넣는 안은 보류한다. 현재 Option/Result는 i64 payload뿐이다.
4. 구조체 필드가 i64만이라는 전제는 현재 코드와 맞지 않는다. 기존 bool·Option/Result·중첩 사용자 타입 필드는 유지하고, 새 배열·문자열 필드만 제외한다.
5. 완전한 구 생성물 링크 호환성은 v2 런타임 결정과 양립하지 않는다. 필수라면 v1/v2 런타임 객체를 분리하는 추가 묶음이 필요하다.
