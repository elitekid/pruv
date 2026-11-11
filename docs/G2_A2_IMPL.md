# G2 A2 구현 명세(u8 증명) — 두 판 공통

이 명세는 Python 판(`pruvc/`)과 Rust 판(`pruvc-rs/`)이 **같은 SMT·같은 의무 순서·같은 문구**를 내도록 고정한 것이다. 근거: `docs/G2_SPEC.md` 0.0절 결정 2·4·8·16, 4.3절.

## 1. 원소 정의역 술어 `u8_dom(arr)`

원소 타입이 U8 인 기호 배열 `arr`(배열 항 `A`, 길이 `n`)에 대해:

```
ForAll([k], Implies(And(k >= 0, k < n), And(Select(A, k) >= 0, Select(A, k) <= 255)))
```

- 묶인 변수 `k` 는 정수 상수 이름 **`elem!k`** (고정 이름). 카운터 `s.k` / `self.k` 를 **건드리지 않는다**.
- And 인자 순서, `>=`/`<=` 방향, 상수 0·255 를 위와 글자 그대로 둔다. patterns 없음.
- I64 배열(그리고 다른 원소 타입)에는 아무것도 만들지 않는다 → 기존 SMT 바이트 불변.

## 2. 정의역을 넣는 세 곳(결정 2) — 길이 가정 **바로 뒤**에 넣는다

1. 함수 진입 매개변수: 배열이면 `pc.append(And(n >= 0, n <= MAX_LEN))` 다음 줄에, U8 이면 `pc.append(u8_dom(v))`.
2. 사용자 함수 호출 결과: `assume(st, g, And(res.n >= 0, res.n <= MAX_LEN))` 다음에, U8 이면 `assume(st, g, u8_dom(res))`. (ensures 가정보다 앞)
3. 루프 havoc 의 배열 분기: `h.pc.append(And(nv.n >= 0, nv.n <= MAX_LEN))` 다음에, U8 이면 `h.pc.append(u8_dom(nv))`.

이 밖(alloc·copy·재바인딩·저장 뒤·코드의 원소 읽기)에는 정의역 가정을 **넣지 않는다**. 코드의 원소 읽기 `a[i]` 의 `in_range(Select)` 가정은 지금 그대로(i64 범위) 둔다.

## 3. `elem_range` 의무

헬퍼 `prove(st, g, ob, node, code, what, key_extra=None, cand=None)` (Rs `prove_core(.., node, code, what, key_extra)`) 를 그대로 쓰고 **cand 없음**(None) — 그래서 `--infer` 탐색에서는 생략되고 최종 전체 검증에서만 판정된다(결정 4).

- 의무식: `And(v >= 0, v <= 255)` (v 는 이미 평가한 값 항).
- key_extra: 없음(None).

### 3.1 alloc(n, v)

결과 원소 타입은 검사기가 Call 노드에 단 타입(`e.ty`; Py `Call.ty`, Rs `Call.ty`)에서 얻는다: 타입 이름이 `"array_u8"` 이면 U8, 그 밖은 지금처럼 I64.

순서: 기존 `alloc_negative` 의무 → (U8 이면) `elem_range` 의무 → 기존 `s.k += 1` → 상수 배열 생성(원소 타입 = 위에서 얻은 것).

- node = alloc Call 식(`alloc_negative` 와 같은 노드).
- what = `u8 element range 0..=255 for the alloc fill value`

### 3.2 원소 저장 `a[i] = v`

순서: 색인 평가 → 값 평가 → 기존 `index_oob` → (배열 원소 타입이 U8 이면) `elem_range` → 기존 정제 `refinement_assign` → Store.

- node = 저장문(`index_oob` 와 같은 노드).
- what = `u8 element range 0..=255 for NAME[...] =` (NAME 은 저장 대상 변수 이름, 기존 index_oob 문구의 `%s` 와 같은 값)

### 3.3 FIX 표

`elem_range` 키를 더한다(Py `FIX` 딕셔너리 `contract_domain` 다음, Rs `fix_for` 같은 자리). 문구 글자 그대로:

```
store or fill only values in 0..=255 into a [u8] array: bound the value with requires, an if, or a loop invariant
```

완성된 진단 message 는 기존 형식 그대로 `cannot prove <what> in <fn>` 이 된다.

## 4. 가드(결정 16)

- verify 가드 제거: Py `verify.py` `verify_program` 첫머리의 `g2_unimplemented_error(prog, "verify")` 블록, Rs `pruv-proof/src/lib.rs` `verify_program_opts` 첫머리의 같은 블록을 지운다. (`[bool]` 은 아직 파서가 거부하므로 증명 층에 오지 않는다.)
- 드라이버 codegen 가드는 **verify 성공 뒤에도** 돈다: Py `pruvc/pruvc.py` 의 `if not verify:` 조건을 없애 무조건 실행, Rs `pruvc-rs/crates/pruvc/src/driver.rs` 의 `if !a.verify { .. }` 조건을 없애 무조건 실행. 위치는 그대로(verify 블록 뒤, 생성기 앞). 주석은 "G2: verify 뒤에도, 아직 코드 생성 층이 없는 배열 타입은 거부(A3·A4 까지)" 뜻으로 고친다.
- 생성기 자체의 가드(`codegen.py`·`llvmgen.py`·`codegen.rs`·`llvmgen.rs`)는 건드리지 않는다.

## 5. `--infer` 후보 필터(결정 4)

- 배열 이름 → 원소 타입 표를 함수에서 만든다: 매개변수 타입과 본문(중첩 블록 포함)의 `Let` 선언 타입 중 배열인 것. 타입 이름 `"array"` → i64, `"array_u8"` → u8, `"array_bool"` → bool.
- 종류 5(`ranges` 를 돌며 대상 배열 `b` 에 `lo <= b[k] <= hi` 를 만드는 곳): `ranges` 의 각 항목은 **그 범위의 출처 배열 원소 타입이 `b` 의 원소 타입과 같을 때만** 쓴다. 출처 배열이나 `b` 의 타입을 표에서 못 찾으면 쓰지 않는다. 지금 i64 만 쓰는 입력에서는 결과가 그대로여야 한다(같은 순서·같은 후보).
- 원소를 읽거나 쓰는 후보(종류 5·6·7·8·9·10·11·12·13·14): 후보 식이 **원소 타입이 bool 인 배열**의 원소(Index)를 읽거나, 대상 배열이 bool 이면 그 후보를 만들지 않는다. (지금은 [bool] 이 파서에서 막혀 실제로 걸리는 일이 없다. i64·u8 입력의 후보는 바뀌면 안 된다.)
- u8 의 암묵 범위 0..=255 를 `ranges` 에 새로 넣지 않는다(새 후보를 더하지 않는다).
- 후보의 함수 호출 금지(len 외)는 그대로.
