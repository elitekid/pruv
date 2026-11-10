# 0단계 남은 과제: 계약 정의역·실행 반복 예산·정렬 전제 O(n) 검사 (2026-11-10)

설계 초안: Codex gpt-6-astra(설계 위임). 아래는 메인이 고친 최종 결정이다.

## A. 계약 정의역을 검증기 의무로
`dom()`(verify.py)을 variant_field 전용에서 일반 정의역으로 넓힌다. V(e)=수학적 값, D(e)=정의역.

| 식 | 자식 정의역 외 조건 |
|---|---|
| `a[i]` | `0 <= i < len(a)` |
| `x / y`, `x % y` | `y != 0` (z3 Int div/mod = SMT-LIB 유클리드 = 실행 `checked_div_euclid`, 그래서 뒷단은 안 바꾼다) |
| `some_val(o)` / `ok_val(r)` / `err_val(r)` | `is_some(o)` / `is_ok(r)` / `!is_ok(r)` |
| `variant_field(e, E::V, f)` | `is_variant(e, E::V)` (기존) |
| `max/min(k in lo..hi: b)` | `lo < hi` |
| 그 밖(산술·sum/count·필드·생성자) | 자식만 |

- 단락: `D(a&&b)=D(a)∧(V(a)⇒D(b))`, `D(a||b)=D(a)∧(¬V(a)⇒D(b))`, `D(a==>b)=D(a)∧(V(a)⇒D(b))`.
- 한정자: 끝 정의역 먼저. forall/exists는 지금처럼 "앞 반복에서 결과가 정해지지 않은 k"에 대해서만 본문 정의역(Reach). 집계는 범위 안 모든 k에 대해 본문 정의역.
- 증명 자리: requires(앞 requires만 가정하고 D(r) 증명), ensures, assert, invariant 진입·보존, decreases. ensures·invariant는 같은 종류의 앞 절(정의역+값)을 뒤 절 정의역 증명에 쓴다.
- 호출 지점에서는 callee requires 정의역을 다시 증명하지 않는다(감사 R2): callee의 run()이 "매개변수 wf + 앞 requires"로 이미 증명했고, 호출 지점은 앞 requires 값을 증명하며 인자는 wf를 만족하므로 늘 중복이다.
- 가정: 증명한 정의역 중 variant_field 부분만 경로 조건에 넣는다(예전과 같음). 나머지 정의역까지 가정하면 중첩 한정자 인덱스 범위가 모든 질의에 실려 p06 증명이 0.44초→69초가 됐다. 가정을 빼는 것은 건전하다.
- 오류 코드: variant_field 의무는 기존 `variant_domain` 그대로, 나머지는 새 `contract_domain`. 한 식에 둘 다 있으면 각각 따로 증명(질의 2회)해 코드를 지킨다.
- 빠른 길: 부분 연산이 없는 식은 질의 없음(`_has_vf` 확장). `z3.simplify(D)`가 True면 질의 없음.
- 실행 검사와의 관계: 정의역이 증명되면 공개 함수 실행 검사에서 `requires undefined`는 정의역 때문에는 안 나고, i128 넘침·반복 예산 초과(B)로만 날 수 있다(자원 한계, 명세에 적음).

기존 시험 이관(의도한 의미 변경): r20·g1_r06(보호 없는 max·variant_field requires)은 기본 모드에서 이제 거부 → 실행 시험은 `--no-verify`로만 돌리고 거부 시험을 새로 둔다. r21은 앞에 `requires len(a) >= 1`. r18·r19·g1_r15는 그대로.

## B. 실행 requires 검사의 반복 예산
- 정적 상한 의무는 넣지 않는다(증명 전용 계약에 불필요한 부담, 중첩 곱 비용은 막지 못함).
- 공개 함수 진입 한 번의 모든 requires 검사가 반복 예산 2^30(1,073,741,824)회를 공유한다. forall/exists/집계 본문을 한 번 돌 때마다 1 줄이고, 다 쓰면 `vow: requires undefined: contract iteration budget exceeded`, 종료 코드 101. 진입마다 새 예산(지역 변수, 전역 상태 없음).
- 범위 길이를 따로 계산하지 않는다(i128 반복 변수는 hi 미만이라 넘치지 않음). 빈 범위·단락으로 건너뛴 식은 예산을 안 쓴다.
- ensures·invariant·assert·decreases는 실행 코드가 없어 해당 없음.

## C. 정렬 전제 O(n) 실행 검사
- 검증기는 원래 이중 forall을 그대로 쓴다. 실행 검사(두 뒷단, 증명·안전 모드 모두)만 바꾼다.
- 인식 형식(AST 구조로, 묶인 변수 이름 자유): `forall i in 0..len(a): forall j in i..len(a): a[i] <= a[j]` 와 내부 시작이 `i + 1`인 것. 같은 배열 변수, 외부 시작 정수 0, 두 끝 모두 `len(a)`, 본문은 `a[i] <= a[j]` 하나. 그 밖은 원래 검사.
- 실행: `forall k in 1..len(a): a[k-1] <= a[k]`. 동치: 길이 0·1이면 둘 다 참, 그 외 추이성·반사성. 인덱스는 모두 범위 안이라 undefined 순서 차이 없음. 예산은 바뀐 검사의 실제 반복에 부과.
- 공통 인식기 `codegen.match_sorted_requires(e) -> Optional[str]`(배열 변수 이름), llvmgen이 가져다 쓴다.
- 주의: bench p04 성능 구간은 공개 함수를 n번 부르므로 검사가 O(n)이어도 전체는 O(n^2)다. 알고리즘 속도 비교는 계속 `--trust-callers`.

## D. 퍼징
다음 묶음. `bench/fuzz/{generate,oracle,run}.py`, 독립 oracle(임의 정밀도 해석기), Rust·LLVM × 증명·안전 4모드 대조. 설계 초안의 D절 계획을 따른다.
