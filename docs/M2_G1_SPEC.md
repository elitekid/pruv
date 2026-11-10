# M2 = G1 설계: 구조체·열거형

이 문서는 M2(G1) 구현 명세다. 설계는 Codex gpt-6-astra(2026-11-10)가 쓰고 메인이 검토해 확정했다.
범위(사용자 결정): 필드는 스칼라+중첩 사용자 타입만, `[Point]`·`Option<Point>`는 G1 밖, `let mut` 지역 구조체의 필드 대입 허용.

## 1. 문법과 언어 의미

| 항목 | G1 결정 |
|---|---|
| 타입 | 이름으로 구별(명목). 구조가 같아도 이름이 다르면 다른 타입 |
| 필드 | `i64`, `bool`, `Option<i64>`, `Result<i64>`, 사용자 구조체·열거형만 |
| 제외 | 배열·unit 필드, 직접·간접 재귀 타입, `[Point]`, `Option<Point>`, `Result<Point>`, 제네릭 |
| 값 의미 | 생성·대입·인자 전달·반환·패턴 바인딩은 값 복사. 별칭·암시적 할당 없음 |
| 구조체 변경 | `let mut` 지역변수의 `p.x = e`, 중첩 `p.a.b = e` 허용 |
| 열거형 변경 | 값 전체 재대입만. 변형 payload에 직접 대입 없음 |
| match | 문장만. 사용자 열거형·Option/Result 모두 모든 변형을 정확히 한 번 |
| 패턴 | 변형 필드를 선언 순서대로 모두 이름에 바인딩. 중첩 패턴·와일드카드·가드·`mut` 패턴 없음 |
| 동등성 | 코드에서는 기존처럼 `i64`·`bool`만. 구조체·열거형 `==`·`!=`는 계약에서만 |
| 계약 | 생성 식, 구조체 필드 접근, 구조적 동등성, `is_variant`·`variant_field` 허용 |
| 출력 | `print`는 계속 `i64`·`bool`만 |

### 선언과 생성
```vow
struct Point {
  x: i64,
  y: i64,
}

struct Frame {
  origin: Point,
  visible: bool,
  hint: Option<i64>,
}

enum Event {
  Empty,
  Hit(point: Point, accepted: bool),
  Failed(code: i64),
}
```
- 필드 0개 구조체 허용: `struct Marker {}`. 열거형은 변형 최소 1개.
- 필드 0개 변형은 괄호 없음(`Empty()` 금지). 선언은 쉼표 구분, 마지막 쉼표 허용.
- 타입·함수 선언은 최상위에만, 섞어 둘 수 있고 뒤에 선언된 타입을 참조할 수 있다.

```vow
let p: Point = Point { x: 3, y: 4 };
let e: Event = Event::Hit(p, true);
let empty: Event = Event::Empty;
let mut frame: Frame = Frame { origin: p, visible: true, hint: Some(7) };
frame.origin.x = 8;
let x: i64 = frame.origin.x;
```
- 구조체 리터럴은 모든 필드를 선언 순서대로 정확히 한 번. 축약·기본값·갱신 구문 없음.
- 초기값·변형 인자는 왼쪽부터 한 번씩 평가.
- 필드 접근은 임의 구조체 식에 가능(`make_point().x`). 필드 대입 왼쪽은 지역변수에서 시작하는 구조체 필드 경로만
  (`make_point().x = 1`, 열거형을 통과하는 경로 금지). 오른쪽을 완전히 평가한 뒤 저장.

### match
```vow
fn event_x(e: Event) -> i64 {
  match e {
    Event::Empty => { return 0; }
    Event::Hit(p, accepted) => { return p.x; }
    Event::Failed(code) => { return code; }
  }
}
```
- scrutinee는 한 번 평가. 바인딩은 불변, 그 arm 안에서만 유효.
- 바깥 이름 가림·같은 arm 안 이름 중복 금지(`shadow`). 안 쓰는 payload도 이름을 붙인다(읽기 의무 없음).
- 기존 `Some(v)`·`None`·`Ok(v)`·`Err(c)` 문법 유지. 사용자 변형은 항상 `Event::Hit`처럼 한정.
- arm 순서 자유, 쉼표는 기존처럼 선택.

### 계약 전용 구문
- `is_variant(e, Event::Hit)` : bool. 모든 값에서 정의.
- `variant_field(e, Event::Hit, point)` : 그 필드 값. 실제 변형이 지정 변형일 때만 정의.
- 두 번째 인자는 변형 이름, 세 번째는 필드 이름(값 식 아님).
- 공개 requires 실행 검사에서 잘못된 변형 조회에 닿으면:
  `vow: requires undefined: variant_field expected Event::Hit.point` (종료 코드 101)
- `==`·`!=`는 같은 타입끼리. 구조체는 모든 필드, 열거형은 변형과 활성 payload만 비교.
- 계약 안 생성 식의 정수 필드는 수학적 정수(실행 requires는 기존처럼 checked i128). 계약 생성 값에 i64 범위를 강제하지 않는다.
- 열거형 직접 필드 접근(`e.point`)은 없다.

### 이름·구문 분석
- 타입·사용자 변형 이름: `[A-Z][A-Za-z0-9_]*`. 필드 이름: `[a-z][A-Za-z0-9_]*`. 기존 함수·변수 규칙 유지.
- `vow_` 접두사, `__` 포함, `_`, Rust 예약어 금지는 새 이름(타입·변형·필드)에도 적용.
- `Option`, `Result`, `Some`, `None`, `Ok`, `Err`는 사용자 타입 이름으로 못 씀. 타입·함수 동일 이름 금지.
  다른 타입의 필드끼리, 다른 열거형의 변형끼리는 이름 중복 가능.
- 추가 키워드: `struct`, `enum`, `is_variant`, `variant_field`. 추가 토큰: `::`, `.`(lexer는 `::`를 `:`보다, `..`를 `.`보다 먼저).
- `Parser.primary()`는 **대문자로 시작하는 이름 다음 `{`만** 구조체 리터럴로 본다(`if flag { ... }`와 충돌 방지).
  대문자 이름 변수를 조건·scrutinee로 쓰려면 괄호로 감싼다.
- 고칠 곳: `vparser.py`의 `KEYWORDS`, `TOKEN_RE`, `Parser.program()`, `type_()`, `stmt()`, `postfix()`, `primary()`.

## 2. 타입 검사(check.py)

- 기존 규칙 유지: non-unit 호출 결과를 문장으로 버리면 `unused_value`, 일반 식문이면 `useless_expr`.
  바인딩한 값을 나중에 읽는지는 검사하지 않는다. Option/Result 필드를 가진 구조체도 같다.
- 검사 순서: ① 최상위 타입·함수 이름 수집 ② 선언 이름·중복 ③ 모든 타입 참조 해결 ④ 타입 의존 그래프와 재귀 검사
  ⑤ 함수 계약·본문 타입·효과 ⑥ 기존 `Checker.no_recursion()`.
- 재귀: 필드(모든 변형 포함)에 사용자 타입 B가 있으면 A→B. DFS로 순환을 찾아 `recursive_type`, 메시지에 `A -> B -> A`.
  필드 없는 변형이 있어도 재귀는 거부.
- 효과: 생성·복사·접근·동등성·match 자체는 효과 없음. 내부 식의 효과는 기존처럼 전파. `alloc` 효과 없음.
- `Checker._expr()`, `stmt()`, `ends_in_return()` 확장. `TNAME[...]` 직접 조회는 `typeinfo.type_name(t)`로 바꾼다.
  모든 새 식의 `Expr.ty`를 채운다. 모르는 타입 때문에 `KeyError`·`internal_error`가 나면 안 된다.
- 여러 오류가 있으면 선언·필드 순서로 첫 오류. 구조체 생성은 모르는 필드를 먼저 `unknown_field`, 나머지 목록 문제를 `struct_fields`.

### 새 오류 코드(JSON 형식·종료 코드 1 유지)
| stage | code | 조건 |
|---|---|---|
| parse | `unsupported_type` | `[Point]`, `Option<Point>` 등 지원 안 하는 타입 구성 |
| type | `type_name` | 타입 이름이 대문자로 시작하지 않음 |
| type | `variant_name` | 변형 이름이 대문자로 시작하지 않음 |
| type | `field_name` | 필드 이름이 소문자로 시작하지 않음 |
| type | `dup_type` | 구조체·열거형 통틀어 같은 타입 이름 중복 |
| type | `name_collision` | 타입·함수 이름 충돌 |
| type | `unknown_type` | 선언 안 된 타입 참조 |
| type | `dup_field` | 같은 구조체·같은 변형 안 필드 중복 |
| type | `dup_variant` | 같은 열거형 안 변형 중복 |
| type | `empty_enum` | 변형 없는 열거형 |
| type | `field_type` | 배열·unit 필드 |
| type | `recursive_type` | 직접·간접 타입 순환 |
| type | `not_struct` | 구조체 아닌 값의 필드 접근·대입, 잘못된 구조체 생성 |
| type | `not_enum` | 열거형 아닌 타입의 변형 생성·검사·조회 |
| type | `unknown_field` | 그 구조체·변형에 없는 필드 |
| type | `struct_fields` | 구조체 생성의 필드 누락·중복·순서 위반 |
| type | `unknown_variant` | 그 열거형에 없는 변형 |
| type | `match_arity` | 패턴 바인더 수와 payload 수 불일치 |
| verify | `variant_domain` | 계약에서 도달 가능한 잘못된 변형 필드 조회를 배제 못 함 |

기존 코드 재사용: 예약 이름 `reserved_name`(기존 내장 이름 재선언은 `reserved`), 타입 불일치 `type_mismatch`,
생성자 인자 수 `arity`, 불변 대상 필드 대입 `immutable`, match 대상 타입 `match_type`,
누락·중복·다른 열거형 arm `match_arms`, 바인더 중복·가림 `shadow`, 코드의 사용자 타입 동등성 `eq_type`,
계약 전용 구문을 코드에서 사용 `contract_only`.

## 3. 검증기(verify.py, z3)

### 타입 모델
- 기존 `Opt`, `Res` Datatype 유지, 사용자 필드에서 그대로 참조.
- 사용자 타입은 의존 순서대로 생성. 구조체: 생성자 하나+필드별 accessor. 열거형: 변형마다 생성자·recognizer·필드 accessor.
- i64 → `IntSort()`, bool → `BoolSort()`. 내부 이름은 프로그램별 접두사+선언 번호. 생성자·accessor는 테이블에 보관(문자열 재조합 금지).
- `verify_program()`에서 프로그램별 모델 테이블을 한 번 만들어 모든 `FnVerifier`에 넘긴다. 동등성은 z3 식으로(Python 객체 비교 금지).

### 값 정의역 `well_formed(ty, value)`
| 타입 | 조건 |
|---|---|
| i64 | `in_range(value)` |
| bool | True |
| Option | Some이면 payload가 i64 범위 |
| Result | 활성 Ok/Err payload가 i64 범위 |
| 구조체 | 모든 필드 `well_formed` |
| 열거형 | 각 recognizer가 참이면 그 변형 모든 필드 `well_formed` (비활성 accessor엔 가정 없음) |

함수 인자, 호출 결과, 루프 havoc 결과에 재귀 적용. match 바인더는 필드 타입으로. `fresh()`·`run()`·`call()`·`havoc()` 확장.
계약 안에서 만든 값에는 적용하지 않는다(`Point { x: p.x + 1, y: 0 }`로 `p.x + 1`이 i64 범위라고 가정 금지).

### 필드 대입과 루프
`p.a.b = rhs`: ① 대입 전 상태에서 rhs 평가 ② `p.a`에서 b만 바꾼 값 재구성 ③ `p`에서 a를 바꾼 값 재구성 ④ `env["p"]`에 저장.
`FnVerifier.assigned()`는 `FieldAssign.name`을 변경 집합에 넣고 중첩 if·while·match 안까지 순회.
**루프에서는 바뀐 루트 구조체 전체를 havoc**(형제 필드도 invariant 없으면 모름). `havoc()`가 사용자 타입·Opt/Res 정의역을 복원하도록 sort→Type 테이블 추가.

### match와 호출
- scrutinee 한 번 평가, arm마다 recognizer를 경로 조건에 추가, accessor 결과를 필드 타입으로 바인딩.
- arm 끝에서 바인더·arm 지역변수를 환경에서 제거하고 바깥 변수 갱신만 남긴다. 모든 arm이 return하면 후속 상태 없음.
- 사용자 타입 반환 호출: fresh Datatype 값 + `well_formed` 뒤 callee ensures 가정. 반드시 `FnVerifier.assume()`를 써서 단락 경로 밖으로 새지 않게.

### 계약의 변형 필드 정의역 `variant_domain(expr, env)` = D
z3 accessor는 잘못된 생성자에도 값이 있으므로 `variant_field`를 accessor로만 번역하면 안 된다.
- 엄격 연산: 피연산자 D의 논리곱. `a && b`, `a ==> b`: `D(a) && (a ==> D(b))`. `a || b`: `D(a) && (!a ==> D(b))`.
- `variant_field(e, E::V, f)`: `D(e) && is_V(e)`. 생성 식: 모든 인자 D. 필드 접근: base의 D.
- sum/count/max/min 본문: 구간 모든 원소에서 D.
- forall/exists는 실제 단락 순서 반영: k에서 본문을 평가하는 조건은 각각 "앞선 모든 j의 본문이 참" / "앞선 모든 j의 본문이 거짓". 그 조건 아래 `D(body(k))`.
  requires의 forall/exists에 "전체 구간 정의됨"을 무조건 가정하지 않는다.

| 위치 | 처리 |
|---|---|
| 함수 진입 requires | 선언 순서로 `D(r) && r` 가정 |
| 호출 requires | caller 경로에서 `D(r)`를 먼저 증명(실패 `variant_domain`), 그다음 기존 `call_requires` |
| ensures | 반환 경로에서 정의역 증명 뒤 기존 ensures 증명 |
| assert | 정의역과 조건 증명 뒤 가정 |
| invariant | 진입·보존에서 정의역과 조건 증명, havoc 뒤엔 둘 다 가정 |
| decreases | 루프 조건이 참인 경로에서 정의역 먼저 증명 |

현재 식의 결과를 가정한 뒤 그 식의 정의역을 증명하지 않는다(앞선 requires와 단락 왼쪽만 사용).
기존 Option/Result selector·배열 인덱스·나눗셈·집계의 일반 계약 정의역 문제는 G1이 해결하지 않는다(0단계 과제).

## 4. Rust 뒷단(codegen.py)

```rust
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Point { pub x: i64, pub y: i64 }

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Event { Empty, Hit(Point, bool), Failed(i64) }
```
- 모두 `Copy`. 타입·필드 공개. 열거형 변형은 위치 인자 형식. 코드의 동등성 금지는 checker 책임.
- `rty()`의 "모르는 타입이면 Vec" 대체를 없앤다. 사용자 타입이면 이름, 그 밖 미지원은 내부 오류.
- 계약용 타입 `vow_contract__Point` 등: 구조 같고 i64 leaf → i128, Option/Result도 i128 payload, 사용자 필드는 대응 계약 타입,
  `Clone, Copy, PartialEq, Eq`. 실행 값→계약 값 변환은 재귀(열거형은 활성 변형만). `Gen.c()`는 이 표현으로 생성·필드 접근·동등성 출력.
- `Gen.e()`: 구조체·변형 생성, 필드 읽기. `Gen.stmt()`: 중첩 필드 대입, 여러 바인더 match. `Gen.entry()`: 기존 순차 requires 검사 재사용.
- `show()`: 새 식을 공통 문자열로(`is_variant(e, Event::Hit)`, `variant_field(e, Event::Hit, point)`, `p.x`, `Point { x: 1, y: 2 }`, `Event::Hit(p, true)`).
- `variant_field` 실행 코드: base를 임시값에 한 번 저장 후 Rust match로 추출, 나머지 arm은 `vow_ud("variant_field expected Event::Hit.point")`.
- 새 `emit_public_types(prog) -> str`를 codegen.py에 두고 LLVM 바인딩에서도 쓴다.
- 표준 타입 경로를 `::std::vec::Vec`, `::std::option::Option`, `::std::result::Result`로 한정(사용자 타입 `Vec` 충돌 방지). 생성 임시 이름은 `vow_`·`__` 사용.
- 증명 모드 내부 호출은 기존 `f__vow_body`, 안전 모드는 공개 진입. `--trust-callers`는 두 모드에서 requires 실행 검사 생략, 안전 모드 산술 검사는 유지.

## 5. LLVM 뒷단(llvmgen.py)

### 내부 배치(평탄화: 태그 + 모든 변형 payload 공간)
```llvm
%vow_t_Point = type { i64, i64 }
%vow_t_Event = type { i64, %vow_t_Point, i1, i64 }
```
| 인덱스 | 의미 |
|---|---|
| 0 | 태그: Empty=0, Hit=1, Failed=2 (선언 순서, i64) |
| 1 | Hit.point |
| 2 | Hit.accepted |
| 3 | Failed.code |
- 구조체 필드는 선언 순서. 열거형 payload는 변형 순서·필드 순서로 이어 붙임(저장 인덱스 = 1 + 앞선 변형 필드 수 합 + field_index).
- 비활성 payload는 항상 `zeroinitializer`에서 시작. 빈 구조체는 `{}`. 중첩 사용자 타입은 그 LLVM 집합 타입을 필드로.
- 계약용 `%vow_c_*`는 같은 구조에서 정수 leaf만 i128. 기존 Option/Result `{ i1, i64 }`와 계약 i128 표현 유지.
- 비활성 필드 안 중첩 값은 유효 값으로 보지 않는다(읽기·비교·계약 변환 금지).

### 호출 규약
| 경계 | 사용자 구조체·열거형 |
|---|---|
| `__vow_body` / `__vow_entry` 내부 인자 | LLVM 집합값 하나 |
| 내부 반환 | 집합값 반환 |
| 외부 `vow_abi_*` 인자 | 고정 길이 i64 word 배열을 가리키는 `ptr` |
| 외부 반환 | `void`, 마지막 `ptr out`에 word 배열 기록 |
| Rust 공개 래퍼 | 원래 사용자 타입을 값으로 받고 반환 |

word 수 W(T): i64·bool 1, Option/Result 2, 구조체 `max(1, Σ W(field))`, 열거형 `1 + Σ W(모든 변형의 모든 필드)`.
빈 구조체의 word 하나는 0. bool 0/1, Option Some=1/None=0, Result Ok=1/Err=0. 비활성 payload와 None payload는 0으로 직렬화.
Rust 바인딩은 `[i64; W(T)]`를 스택에 만들어 필드별 직렬화, 반환도 배열로 받아 안전한 생성자로 복원(`transmute`·Rust 레이아웃 의존 금지).
M1의 최상위 Option/Result 인자·2-word 레지스터 반환 ABI는 바꾸지 않는다.

### IR 생성
- `V`와 `Slot`에 `ty: Optional[Type]` 추가, 새 kind `"agg"`(`V.a` 집합 SSA, `Slot.a` 집합 alloca, `b` 미사용).
- 확장: `lty()`, `vkind()`, `ir_params()`, `new_slot()`, `load()`, `store()`, `agg()`, `bind_params()`, `emit_ret()`, `ev_call()`,
  `ev()`, `cev()`, `bind_contract_params()`, `abi_of()`, `gen_bindings()`, `gen_llvm()`.
- 필드 대입: RHS 평가 → 루트 load → 중첩 `insertvalue` → 루트 store. 필드 읽기: `extractvalue`. 집합값은 배열 소유 목록·`vow_free` 대상 아님.
- 열거형 match: 태그 `switch`, payload 추출은 그 arm 블록에서만. 모든 arm이 끝나면 join 블록 생략. default는 `unreachable`.
- 계약 동등성: 양쪽 한 번 평가 → 구조체는 필드별 재귀 → 열거형은 태그 다르면 false, 같으면 활성 필드만 → Option None payload 비교 안 함.
- `variant_field`는 태그 분기 뒤 접근, 실패는 기존 `vow_panic_undefined`. `select`로 합치지 않는다.
- `runtime.c` 변경 없음. 두 뒷단의 비교 대상은 `vow:` 진단 문자열.

## 6. 시험과 예제

### 거부 시험(`tests/must_reject/g1_*.vow` + 같은 이름 `.json`에 `{"stage": ..., "code": ...}`)
`run_must_reject()`는 `.json`이 있으면 실제 JSON 진단에 그 stage·code가 있는지도 확인한다(없으면 기존처럼 종료 코드 1만).

| 파일 | 틀린 프로그램 | 기대 stage/code |
|---|---|---|
| `g1_recursive_direct` | `struct Node { next: Node }` | type/`recursive_type` |
| `g1_recursive_indirect` | 구조체→열거형 payload→구조체 순환 | type/`recursive_type` |
| `g1_array_field` | `struct Boxed { items: [i64] }` | type/`field_type` |
| `g1_unit_field` | `struct Boxed { item: () }` | type/`field_type` |
| `g1_array_of_struct` | `[Point]` 지역변수 | parse/`unsupported_type` |
| `g1_generic_option` | `Option<Point>` | parse/`unsupported_type` |
| `g1_unknown_type` | 미선언 타입 필드 | type/`unknown_type` |
| `g1_duplicate_type` | 같은 이름 struct·enum | type/`dup_type` |
| `g1_duplicate_field` | 같은 구조체에 x 두 번 | type/`dup_field` |
| `g1_duplicate_variant` | 같은 enum에 Hit 두 번 | type/`dup_variant` |
| `g1_empty_enum` | `enum Empty {}` | type/`empty_enum` |
| `g1_literal_fields` | Point 생성에서 y 누락 | type/`struct_fields` |
| `g1_unknown_field` | `p.z` | type/`unknown_field` |
| `g1_param_write` | 매개변수 `p.x = 1` | type/`immutable` |
| `g1_nested_immutable` | 불변 지역 `f.origin.x = 1` | type/`immutable` |
| `g1_match_missing` | Event::Failed arm 누락 | type/`match_arms` |
| `g1_match_duplicate` | Event::Empty arm 중복 | type/`match_arms` |
| `g1_match_arity` | `Event::Hit(p)` | type/`match_arity` |
| `g1_match_shadow` | payload 바인더가 매개변수 이름과 같음 | type/`shadow` |
| `g1_unused_wrapper` | Option 필드 구조체 반환 호출을 문장으로 버림 | type/`unused_value` |
| `g1_code_equal` | 본문에서 `p == q` | type/`eq_type` |
| `g1_reserved_field` | 필드 이름 `vow_x` | parse/`reserved_name` |
| `g1_false_ensures` | 반환 필드가 계약과 다름 | verify/`ensures` |
| `g1_bad_variant_contract` | 무조건 Empty 반환하며 Hit 필드 조회 ensures | verify/`variant_domain` |
| `g1_call_requires` | x>0 요구 함수에 x=0 구조체 전달 | verify/`call_requires` |
| `g1_loop_havoc` | 바뀐 구조체 형제 필드를 invariant 없이 보존 주장 | verify/`assert` |
| `g1_shortcircuit_ensures` | 실행 안 된 호출의 구조체 반환 ensures에 의존 | verify/`assert` |

(verify 단계 code 이름은 기존 verify.py가 실제로 내는 코드에 맞춘다.)

```vow
struct Point { x: i64, y: i64 }
fn wrong() -> Point
  ensures result.x == 1
{
  return Point { x: 2, y: 0 };
}
```
```vow
enum Event { Empty, Hit(value: i64) }
fn wrong() -> Event
  ensures variant_field(result, Event::Hit, value) == 0
{
  return Event::Empty;
}
```
```vow
struct Point { x: i64, y: i64 }
fn lost() -> () {
  let mut p: Point = Point { x: 0, y: 7 };
  let mut i: i64 = 0;
  while i < 1
    invariant 0 <= i && i <= 1
    decreases 1 - i
  {
    p.x = 1;
    i = i + 1;
  }
  assert p.y == 7;
}
```
(`invariant p.y == 7`을 넣은 판은 통과해야 한다 — examples/g1_counter.vow에서 확인.)

### 실행 시험(`tests/runtime/g1_*`: `.vow`·`.rs`·`.json`)
stdout은 `stdout_lines`로 정확히 비교. 성공 시험은 두 뒷단에서 기본·안전·trust·안전+trust 네 조합(선택적 `flags_matrix`, 기존 `flags` 형식 유지).

| stem | 내용 | 모드 | stdout | exit / stderr |
|---|---|---|---|---|
| `g1_r01_copy` | p=(1,2)를 q에 복사 후 q.x=9; p.x, q.x 출력 | 네 조합 | `1`,`9` | 0 |
| `g1_r02_nested` | Frame.origin.x 3→8; 이전 복사본과 새 값 출력 | 네 조합 | `3`,`8` | 0 |
| `g1_r03_variants` | Empty, Hit(Point(3,4),true), Failed(7) 인자·반환·match 왕복 | 네 조합 | `0`,`3`,`7` | 0 |
| `g1_r04_wrapped` | 구조체 안 Some(5), None, Ok(6), Err(7)를 match로 추출 | 네 조합 | `5`,`0`,`6`,`7` | 0 |
| `g1_r05_requires` | `positive(p)` `requires p.x > 0`, driver가 x=0 | 기본·안전 | 없음 | 101, `vow: requires violated: positive: (p.x > 0)` |
| `g1_r06_undefined` | requires가 곧바로 Hit.value 조회, driver가 Empty | 기본·안전 | 없음 | 101, `vow: requires undefined: variant_field expected Event::Hit.value` |
| `g1_r07_guarded` | `!is_variant(e, Event::Hit) \|\| variant_field(e, Event::Hit, value) > 0`, Empty 전달 | 기본·안전 | `7` | 0 |
| `g1_r08_trust` | r05 함수가 본문에서 7 반환, x=0 전달 | trust·안전+trust | `7` | 0 |
| `g1_r09_overflow` | 구조체 x에 `p.x + 1` 대입, driver가 MAX | 안전·안전+trust | 없음 | 101, `vow: arithmetic error: overflow in +` |
| `g1_r10_order` | 생성자 인자 함수가 1,2 출력, scrutinee 함수가 3 출력, Hit 합 출력 | 네 조합 | `1`,`2`,`3`,`30` | 0 |
| `g1_r11_wide_abi` | bool·Option·Result·중첩 enum 포함 2-word 초과 구조체 인자·반환 왕복(모든 변형) | 네 조합 | `true`,`5`,`6`,`7` | 0 |
| `g1_r12_contract_int` | requires에서 `Point { x: p.x + 1, y: 0 } == Point { x: p.x + 1, y: 0 }`, x=MAX | 기본·안전 | `true` | 0 |
| `g1_r13_empty` | 빈 구조체·무필드 변형 인자·반환 왕복 | 네 조합 | `1` | 0 |
| `g1_r14_internal_entry` | 내부 호출이 잘못된 Point를 requires 함수에 전달 | 안전 | 없음 | 101, `vow: requires violated` |
| `g1_r15_quant_domain` | forall/exists가 첫 원소에서 단락해 뒤의 잘못된 변형 조회를 건너뜀 | 기본·안전 | `true`,`true` | 0 |

메시지·driver 모양은 기존 tests/runtime 시험과 기존 메시지 형식에 맞춘다(위 문자열은 기대 의미).

### 예제
- `examples/g1_point.vow`: 중첩 구조체 갱신, 입력 불변성, 필드 ensures.
- `examples/g1_event.vow`: 0·1·여러 필드 변형, 전체 match, 계약 변형 검사.
- `examples/g1_counter.vow`: 구조체 전체 havoc에 맞춘 필드 invariant.

## 7. 확정 AST와 파일 경계

기존 `Type`은 그대로, 사용자 타입도 `Type("Point")`. 이름이 같으면 같은 타입. `vast.py`에 추가·교체(Python 3.9):

```python
@dataclass
class FieldDecl:
    line: int
    col: int
    name: str
    type: Type

@dataclass
class VariantDecl:
    line: int
    col: int
    name: str
    fields: List[FieldDecl]

@dataclass
class TypeDecl:
    line: int
    col: int
    name: str

@dataclass
class StructDecl(TypeDecl):
    fields: List[FieldDecl]

@dataclass
class EnumDecl(TypeDecl):
    variants: List[VariantDecl]

@dataclass
class FieldInit:
    line: int
    col: int
    name: str
    value: Expr

@dataclass
class StructLit(Expr):
    name: str
    fields: List[FieldInit]
    ty: Optional[Type] = None

@dataclass
class EnumCtor(Expr):
    enum_name: str
    variant: str
    args: List[Expr]
    ty: Optional[Type] = None

@dataclass
class FieldAccess(Expr):
    base: Expr
    field: str
    ty: Optional[Type] = None

@dataclass
class IsVariant(Expr):
    value: Expr
    enum_name: str
    variant: str
    ty: Optional[Type] = None

@dataclass
class VariantField(Expr):
    value: Expr
    enum_name: str
    variant: str
    field: str
    ty: Optional[Type] = None

@dataclass
class FieldAssign(Stmt):
    name: str
    fields: List[str]
    value: Expr

@dataclass
class MatchArm:
    line: int
    col: int
    enum_name: Optional[str]
    ctor: str
    binders: List[str]
    body: List[Stmt]

@dataclass
class Program:
    functions: List[Function] = field(default_factory=list)
    types: List[TypeDecl] = field(default_factory=list)
```
- `Program.functions`는 첫 필드 유지. `MatchArm.binder`는 없애고 모든 소비자를 `binders`로(호환 필드 없음).
- Option/Result arm은 `enum_name=None`, 사용자 enum은 문자열. `ctor`는 변형 이름만(`"Hit"`). Some/Ok/Err는 바인더 하나, None은 빈 목록.
- `FieldAssign.fields`는 비지 않음: `p.a.b` → `name="p"`, `fields=["a","b"]`.
- 기존 `Ctor`, `Call`, `Match` 유지. 새 내장 구문을 `Call.args`에 가짜 `Var`로 넣지 않는다.
- `line`, `col`은 구문 첫 토큰. (dataclass 상속에서 기본값 필드 순서 문제가 있으면 기존 vast.py 관례대로 맞춘다.)

### 공유 타입 정보 `vowc/typeinfo.py`(묶음 A 소유)
```python
def type_name(ty: Type) -> str: ...

class TypeTable:
    def __init__(self, prog: Program): ...
    # decls: Dict[str, TypeDecl]
    # order: List[TypeDecl]  # dependency-first, stable
    def decl(self, ty: Type) -> TypeDecl: ...
    def is_struct(self, ty: Type) -> bool: ...
    def is_enum(self, ty: Type) -> bool: ...
    def fields(self, ty: Type, variant: Optional[str] = None) -> List[FieldDecl]: ...
    def field_index(self, ty: Type, name: str, variant: Optional[str] = None) -> int: ...
    def variant_index(self, ty: Type, variant: str) -> int: ...
```
`fields`는 구조체 필드 또는 지정 변형 필드를 선언 순서로. Checker가 유효성을 먼저 보장하고, B·C·D는 검사가 끝난 Program에서 테이블을 만든다(AST에 동적 속성 금지).

### 묶음(같은 파일을 두 묶음이 고치지 않는다)
| 묶음 | 독점 수정 파일 | 산출물 |
|---|---|---|
| A 앞단 | `vowc/vast.py`, `vowc/vparser.py`, `vowc/check.py`, 새 `vowc/typeinfo.py` | AST, 문법, 타입·효과 검사 |
| B 증명 | `vowc/verify.py` | Datatype, 정의역, 재구성, havoc, 호출·match |
| C Rust | `vowc/codegen.py` | 공개 타입 출력, 계약 타입, Rust 코드, 공통 `show` |
| D LLVM | `vowc/llvmgen.py` | 집합값 IR, ABI 직렬화, 바인딩 |
| E 시험 | `tests/run_all.py`, 새 `tests/must_reject/g1_*`, 새 `tests/runtime/g1_*`, 새 `examples/g1_*` | 회귀·예제 |
`runtime.c`, `vowc.py`, `docs/M1_LLVM_SPEC.md`는 고치지 않는다. SPEC.md G1 절은 메인이 넣는다.
순서: A·E 병렬 → B·C 병렬 → D(C의 `emit_public_types` 사용) → 메인이 실행·통합 → 감사·확인 → 독립 풀이 측정.

## 8. SPEC.md G1 절 초안(영어) — 메인이 SPEC.md에 넣는다

(설계 문서 원문. 구현 결과에 맞춰 메인이 다듬어 넣는다.)

## 9. 감사 지점
| 위험 | 필수 확인 |
|---|---|
| parser `{` 모호성 | `if flag {}`, `match value {}`, 구조체 리터럴·괄호 |
| 명목 타입 | 구조가 같은 다른 타입을 대입·비교하지 못함 |
| 재귀 누락 | enum 한 변형만 순환해도 거부 |
| 값 복사 | q의 중첩 필드 변경이 p를 안 바꿈 |
| z3 accessor 전체 함수 성질 | 잘못된 변형 조회를 임의 값으로 증명하지 않음 |
| 정의역 자기 정당화 | requires·ensures 결과를 먼저 가정해 조회를 정당화하지 않음 |
| 단락·한정자 | 미실행 분기·조기 종료 뒤 조회·호출 조건을 가정하지 않음 |
| i64 범위 | 인자·호출 결과·havoc의 모든 활성 중첩 leaf에 범위 조건 |
| 계약 값 범위 | 계약 생성 값에 i64 조건을 붙여 모순 증명하지 않음 |
| 루프 | 중첩 if·match·while의 필드 대입이 루트 havoc 집합에 포함 |
| match 스코프 | 바인더가 arm 밖으로 새지 않음 |
| enum 동등성 | 비활성 payload·padding 비교 안 함 |
| LLVM 초기화 | 반환·직렬화에서 undef/poison 관찰 안 함 |
| ABI | 큰 타입·빈 타입·중첩 타입 |
| 호출 경로 | 증명/안전 모드와 trust 조합에서 올바른 entry/body |
| 메시지 | 두 뒷단이 같은 `show()`와 같은 undefined detail |
| 이름 충돌 | 사용자 타입 `Vec` 등과 표준 타입·생성 도우미 |
| 기존 회귀 | Option/Result ABI, 배열 해제, 산술 검사, 단락 평가 |

평탄화 enum은 변형이 많으면 크기가 커진다(측정 전). union 배치·작은 타입 레지스터 반환은 측정 뒤 판단.
