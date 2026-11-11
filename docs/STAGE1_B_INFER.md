# 1단계 B: 템플릿 Houdini 불변식 추론 — 구현 명세

> 상태: 확정(2026-11-11, 메인). `docs/STAGE1_SPEC.md` 0절 5·6·7·9·11·12·14·15와 본문 2절을 구현 수준으로 고정한 문서다. 두 판(Python `pruvc/infer.py`, Rust `pruv-proof/src/infer.rs`)은 이 문서대로 **같은 후보·같은 순서·같은 SMT**를 만든다. 구간 분석(C)은 없다.

## 1. 설정(추론 설정 버전 1)

| 이름 | 값 |
|---|---|
| `version` | 1 |
| 루프당 후보 상한 | 64(정렬·중복 제거 뒤 앞에서 자름, 잘린 수는 `capped`) |
| 함수당 탐색 질의 상한 | 512(보조정리 재시도 포함, 시도 1번 = 1) |
| 탐색 질의 `rlimit` | 100000 |
| 탐색 질의 `timeout` | 500ms |
| 탐색 질의 `random_seed` | 0 |
| 함수당 추론 시간 안전장치 | 5초(벽시계) |

최종 검증은 기존 그대로(timeout 8000, rlimit·seed 없음).

## 2. 루프 번호

함수 본문을 전위 순회한다: 문장을 순서대로, `While`이면 번호를 매긴 뒤 그 본문, `If`는 then → els, `Match`는 arm 순서. 번호는 0부터.

## 3. 후보 생성

### 3.1 기본 정의(루프 `w`)

- `M` = `w.body` 안에서 대입되는 이름(기존 `assigned`: `Assign`·`IndexAssign`·`FieldAssign`, 중첩 블록 포함).
- **불변식**(이 루프에서 안 바뀌는 식): `IntLit`, `Var x`(x∉M), `len(Var x)`(x∉M), 단항 `-`, 이항 `+ - *` 로만 된 식.
- **초기값** `init(v)`: `w`와 같은 블록에서 `w` 앞 문장을 뒤에서부터 본다. `Let v`/`Assign v`를 만나면 그 값. 그 전에 `If/While/Match` 중 `v`를 대입하는 문장을 만나면 없음. 블록 처음까지 없으면 없음. 배열 길이용 `init_len(b)`는 `IndexAssign b`를 건너뛰고 같은 규칙.
- **카운터** `v`: `w.body` 안 `v` 대입이 정확히 하나이고 그것이 본문 최상위 `v = v + c`(c는 `IntLit`, c≥1)이며 `init(v)`가 불변식인 변수. 그 문장의 최상위 위치를 `pos(v)`, 시작값을 `lo = init(v)`.
- **경계식**: `w.cond`를 최상위 `&&`로 나눈 각 항이 `v < E`/`E > v`이면 `up = E`, `v <= E`/`E >= v`이면 `up = E + 1`. v는 카운터, E는 불변식.
- **원소 범위**: `f.requires`(정제 합성 requires 포함)의 `forall K in 0..len(x): A && B` 꼴에서 A·B가 `x[K] >= L`·`L <= x[K]`·`x[K] <= U`·`U >= x[K]`(L·U는 정수 리터럴 또는 `-리터럴`)이면 `x`의 범위 (L, U). 배열마다 처음 찾은 것 하나.
- **항 범위** `rng(T)`: `IntLit n`→(n,n), `-e`→(−U,−L), `x[e]`(x∉M, 원소 범위 있음)→(L,U), `+`→끝점 합, `-`→(L1−U2, U1−L2), `*`→네 끝점 곱의 최소·최대. 그 밖은 없음.
- `N(v)` = `lo`가 `IntLit 0`이면 `v`, 아니면 `v - lo`.
- `T[v:=k]`: 식의 `Var v`를 `Var k`로 바꾼 식. `k`는 `refine.pick_bound_name(함수 안 모든 이름)`(함수당 하나).
- 정수 상수는 i64 안이어야 한다(음수는 `-` + 양수 리터럴, 크기 ≤ 2^63−1). 벗어나는 후보는 만들지 않는다.

### 3.2 누적문(카운터 `v`마다, `pos(v)`보다 앞의 최상위 문장)

- **합**: `s = s + T` 또는 `s = T + s`. s≠v, `w.body` 안 s 대입은 이것 하나, T에 `v`가 나오고 그 밖의 이름은 M 밖, `T` 안 배열은 M 밖. `init(s)`는 정수 리터럴(`c0`, 음수 허용).
- **조건부 누적**: `if C { s = s + T; }`(else 없음, then이 그 문장 하나). 위 조건 + C에 `v`가 나오고 그 밖 이름은 M 밖. `T`가 `IntLit 1`이면 **개수**, 아니면 조건부 합.
- **최대/최소**: `if X { m = T; }`(else 없음, then이 그 문장 하나), m 대입은 이것 하나, T에 `v`, X가 `T > m`·`m < T`·`T >= m`·`m <= T`이면 max, `T < m`·`m > T`·`T <= m`·`m >= T`이면 min(T는 위치 무시 구조 비교). 시작 후보 `b`: `lo`, 그리고 `lo`가 정수 리터럴 n≥1이고 `init(m)`이 `T[v:=IntLit(n−1)]`과 구조가 같으면 `n−1`도.

### 3.3 후보 종류(고정 번호)

| 번호 | 후보 | 조건 |
|---|---|---|
| 1 | `lo <= v` | 카운터 |
| 2 | `v <= up` | 경계식 |
| 3 | `v <= up \|\| v == lo` | 경계식, lo가 정수 리터럴 |
| 4 | `len(b) == E` | b∈M, b에 대한 대입이 모두 `IndexAssign`, `init_len(b)`가 `alloc(E, _)`(E 불변식) 또는 `copy(x)`(x∉M → `len(x)`) |
| 5 | `forall k in 0..len(b): L <= b[k] && b[k] <= U` | 4와 같은 b. (L,U)는 requires 원소 범위마다 하나, `alloc(_, c)`(c 리터럴)이면 c를 포함하도록 넓힘; requires 범위가 없고 alloc 리터럴만 있으면 (c,c) |
| 6 | `s == sum(k in lo..v: T[v:=k])` (c0≠0이면 `s == c0 + sum(...)`) | 합 |
| 7 | `c == count(k in lo..v: C[v:=k])` (c0≠0이면 `c0 + ...`) | 개수 |
| 8 | `b < v ==> m == max(k in b..v: T[v:=k])` (min) | 최대/최소, b마다 |
| 9 | `forall k in b..v: T[v:=k] <= m` (min은 `>=`) | 최대/최소, b마다 |
| 10 | `b < v ==> (exists k in b..v: T[v:=k] == m)` | 최대/최소, b마다 |
| 11 | `s >= c0 + L * N(v)`, `s <= c0 + U * N(v)` | 합(rng(T)=(L,U)) / 조건부 합(L→min(L,0), U→max(U,0)) / 개수(`c >= c0`, `c <= c0 + N(v)`) |

식 꼴 규칙: c0=0이면 `c0 +`를 뺀다. 계수 L=0이면 `L * N` 대신 `0`, L=1이면 `N`. 항은 위 표의 모양 그대로(왼쪽에 누적 변수).

### 3.4 정렬·번호·위치

루프마다 후보를 (종류 번호, 출력 문자열) 순으로 정렬하고 같은 문자열은 첫 것만 남긴 뒤 64개로 자른다. 후보 ID는 `L<루프번호>#<순위>`(순위 0부터). 후보 식의 모든 노드 위치는 `w`의 위치(`w.line, w.col`)다.

### 3.5 출력 문자열(두 판 동일)

- 우선순위: `==>` 1(오른쪽 결합), `||` 2, `&&` 3, 비교 4, `+ -` 5, `* / %` 6, 단항 7.
- 이항은 `l op r`(공백 하나). 자식이 이항이고 우선순위가 더 낮으면 괄호, 오른쪽 자식은 같아도 괄호(단 `==>`는 왼쪽이 같으면 괄호).
- 단항 `-e`, `!e`: 피연산자가 이항이나 양화면 괄호.
- `forall/exists k in lo..hi: body`는 이항의 피연산자이면 괄호. 집계는 `sum(k in lo..hi: body)`.
- 정수는 십진(밑줄 없음), `len(a)`, `a[i]`.

### 3.6 구현에서 정한 해석(Python 판 B2, Rust 판도 따른다)

1. 개수(`T`가 `IntLit 1`)는 "T에 `v`가 나온다" 조건을 면제하고 `C`에만 `v`를 요구한다. 조건부 합은 `T`에도 `v`가 있어야 한다.
2. 루프 본문 안에서 선언된 이름(`let`, match 바인더)은 루프 머리에 없으므로, 합·개수의 "M 밖" 검사는 `M ∪ 본문 지역 이름`으로 한다. 최대/최소의 `T`는 본문 지역 이름만 막는다(M 검사 없음, 틀리면 Houdini가 버린다).
3. 원소 범위 `A && B`는 하한·상한 순서와 무관하게 받는다. 종류 5의 (L,U) 쌍은 requires에 범위가 있는 모든 배열에서 모아 같은 쌍은 한 번만.
4. 계수 L=0이면 `L * N`만 `0`으로 바꾼다(c0≠0이면 `s >= c0 + 0`).
5. 단항 `-`/`!`의 피연산자 괄호는 이항·forall/exists에만(집계는 괄호 없음).
6. 출력 함수가 모르는 노드(구조체 리터럴·필드 접근 등)가 든 후보는 만들지 않는다.
7. 보고: `queries`는 탐색 시도 수(최종 검증 제외). 예산 소진·시간 초과면 `rounds`는 시작한 회차 수, `dropped`는 그 전 회차까지, `invariants`는 `[]`. 후보가 0개인 루프는 `none`. `--no-verify --infer` 어댑터는 `inference: []`.
8. 묶인 변수 이름은 함수 안 모든 이름을 피하므로 requires가 `k`를 쓰면 후보는 `k_1`이 된다.

## 4. 검증기 연결

- `FnVerifier`에 `extra`(루프 번호 → [(후보 ID, 식, 문자열)])와 `probe`(탐색 상태)를 준다. `extra`가 비면 기존 경로와 **바이트 동일**(fresh 번호·SMT·오류).
- `loop(w)`의 불변식 목록 = `w.invariants`(필수 정제 → 사용자, 기존 순서) + 그 루프의 후보(3.4 순서). 진입·보존·정의역·havoc 뒤 가정을 모두 이 목록으로 한다(기존 규칙: 한 절의 정의역은 앞 절만 가정, 보존 쪽 머리 가정은 전부).
- 후보 의무는 `prove(..., key_extra=ID, cand=ID)`, 정의역도 같은 ID. `what`은 `inferred loop invariant \`TEXT\` on entry` / `... preserved` / 정의역은 `partial operations in inferred loop invariant \`TEXT\` (entry|preserved) are defined`.

### 4.1 탐색 회차(probe)

- 회차마다 새 `FnVerifier`(새 fresh·seen·집계·보조정리), `QueryConfig(phase="inference", round=r(1부터), timeout_ms=500, rlimit=100000, seed=0)`.
- `cand`가 없는 의무는 질의·기록 없이 건너뛴다(최종 검증이 본다). 이번 회차에 이미 실패한 후보의 의무도 질의·기록 없이 건너뛴다.
- 후보 의무: 기존 `prove`와 같은 두 단계(보조정리 없이 → unsat 아니고 보조정리가 있으면 보조정리와 함께). 시도마다 먼저 질의 수가 상한이면 **예산 소진**, 벽시계가 함수 시작 + 5초를 넘었으면 **시간 초과**; 아니면 질의 수 +1, 질의. 시도 상태가 `timeout`이면 시간 초과. z3 예외는 상태 `error`로 기록하고 그 후보 실패. 마지막 시도가 `proved`가 아니면(`not_proved`·`resource_unknown`·`error`) 그 후보는 이번 회차 실패: (ID, 의무 code, 상태)를 남긴다. 오류 목록·`seen`은 건드리지 않는다.
- 회차 끝에 실패 후보를 한꺼번에 뺀다. 빠진 것이 없으면 끝. 후보가 하나도 없으면 회차를 돌지 않는다.
- **예산 소진**: 그 함수의 자동 후보를 모두 버리고(상태 `budget_exhausted`) 최종 검증으로 간다.
- **시간 초과**: 그 함수는 최종 검증 없이 오류 `verify/inference_timeout` 하나(위치 함수, 메시지 `invariant inference for <fn> hit the time safety limit (5 s per function, 500 ms per query)`, 안내 `write the loop invariants explicitly, or compile without --infer`). 다른 함수는 계속.

### 4.2 최종 검증

살아남은 후보를 `extra`로 준 새 `FnVerifier`(기본 `QueryConfig`)로 함수 전체를 검증한다. 오류는 기존대로 보고한다.

## 5. 옵션·출력

- `--infer`(기본 꺼짐): 위 추론. `--show-inferred`: `--infer` 없이 쓰면 사용법 오류(종료 2). `--no-verify --infer`면 추론하지 않고, `--show-inferred`면 stderr에 `{"status": "skipped_no_verify"}` 한 줄.
- `--show-inferred` 출력: 루프 하나당 stderr JSON 한 줄(`sort_keys`, `ensure_ascii=False`). 키: `fn`, `loop`(번호), `line`, `col`, `status`(`verified` 최종 검증에서 이 함수 오류 0 / `selected` 오류 있음 / `budget_exhausted` / `timeout` / `none` 후보 없음), `invariants`(살아남은 후보의 `invariant TEXT` 목록, 순서대로), `generated`(중복 제거 뒤·자르기 전 수), `capped`, `kept`, `dropped`([{`cand`, `text`, `round`, `code`, `status`}], 회차·ID 순), `rounds`, `queries`(함수 전체). 함수 순서 → 루프 번호 순.
- 시험 어댑터·`pruv-trace-dump`: `--infer`면 `options.infer=true`, 탐색·최종 질의가 모두 trace에 남고, 최상위 `inference`에 위 줄 목록(같은 객체)을 넣는다. 꺼져 있으면 `inference` 키 없음.
- 생성 코드는 바뀌지 않는다(추론 불변식은 증명용이라 실행 코드에서 지워지는 기존 불변식과 같다).
