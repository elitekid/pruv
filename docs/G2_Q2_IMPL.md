# G2 Q2 구현 명세: 측정·독립 사용·SPEC 요약

G2_SPEC 7.7·8.4의 마지막 관문. 컴파일러(`pruvc/`·`pruvc-rs/`)는 바꾸지 않는다. 측정 도구와 풀이만 더한다.

## 0. 기준

- **G2 이전 기준 커밋:** `5c65fe3`(G2 A0 `ea4efb5` 바로 앞, 컴파일러 코드가 G2 전). 워크트리 `/tmp/q2/base`, Rust 판은
  `CARGO_TARGET_DIR=/tmp/q2/base-target` 로 빌드해 `/tmp/q2/base-target/release/pruvc`.
- **지금:** `HEAD`(Q1 `337ac05` 뒤), `pruvc-rs/target/release/pruvc`.
- 정본은 Rust 판. Python 판은 대조용이라 시간 측정의 주 대상이 아니다(재면 따로 적는다).
- 측정은 다른 무거운 작업과 동시에 돌리지 않는다(직렬, jobs 1). 기계 부하는 결과에 적는다.

## 1. 기존 compile/proof 시간 (`bench/g2/measure_compile.py`)

- 입력: `tests/smt_snapshot_inputs.txt` 231개(G2 이전 프로그램, A0에서 고정, 거부 표본 포함).
- 명령: 각 판의 `pruvc <file> -o <tmp>.rs`(검증 + Rust 소스 생성, rustc 없음). 벽시계 시간(`time.perf_counter`), 종료 코드.
- 반복 R회(기본 5). 한 반복 안에서 파일마다 base → head 를 번갈아 돌려 시간 흐름에 따른 부하 차이를 양쪽에 고르게 나눈다.
- 기록: 파일마다 각 판의 시간 목록·중앙값·종료 코드. 요약: 파일 중앙값의 합, 파일 중앙값들의 중앙값·p90·최댓값, 판 비(head/base),
  head 가 base 보다 10% 넘게 느리고 차이가 0.05초 넘는 파일 목록, 두 판 종료 코드가 다른 파일 목록(있으면 실패).
- 관문: 합계 비 ≤ 1.10. 넘으면 원인을 찾은 뒤 판단(8.4).

## 2. solver 통계 (`bench/g2/solver_stats.py`)

- 수단: `tests/diff_py_adapter.py trace <file> [--infer]` 의 JSON(`obligations[].attempts[].{smt2,result,lemmas}`, `skipped`).
  기존 231개는 SMT 스냅숏이 G2 전과 바이트 동일하므로(Q1 기준값) 통계도 같다는 것을 기록하고, 새로 재는 대상은 G2 프로그램이다.
- 대상: `bench/g2/solutions/ref_pruv/*.pruv`, 독립 풀이 최종판, `examples/` 의 G2 양성(`g2*`).
- 파일마다: 의무 수, 시도 수, 결과 종류별 수(`unsat`/`sat`/`unknown`/그 밖 그대로), 건너뛴 수, smt2 안 `forall`·`exists` 출현 수(양화 수),
  timeout 표시(결과 문자열 그대로). 합계 행.

## 3. 배열 실행 시간·메모리 (`bench/g2/perf/arr_*.pruv`, `bench/g2/measure_run.py arrays`)

- 같은 일을 `[i64]`·`[u8]`·`[bool]` 로 한 `main` 프로그램 셋: 길이 N = 20_000_000 배열을 `alloc` 하고 루프로 채운 뒤
  (i64·u8: `i % 200`, bool: `i % 2 == 0`) 다시 훑어 센 값(정수: `>= 100` 인 수, bool: 참인 수)을 `print`.
  증명 모드로 검증 통과해야 한다.
- 두 뒷단(rust, llvm) 단독 실행 파일로 빌드(`pruvc file -o exe`; 링크 경로는 기존 시험과 같음), R회(기본 5) 실행해 벽시계 중앙값과
  `/usr/bin/time -l` 의 최대 상주 메모리(maximum resident set size) 중앙값, 출력 값이 세 타입에서 같은지(정답 확인).
- 주의: 채우기·훑기가 한 프로그램이므로 "할당+채우기+훑기" 시간이다. 프로세스 시작 비용이 같이 들어간다(N 이 커서 작다고 보지만 숫자로 적는다: N=0 짝 프로그램 시간도 잰다).

## 4. 문자열 처리 비용 (`bench/g2/perf/str_ops.pruv`, `bench/g2/measure_run.py strings`)

Rust 드라이버(`bench/g2/run.py` 의 TEMPLATE 처럼 생성 Rust 를 `mod` 로 포함)에서 `std::time::Instant` 로 함수 호출만 잰다.
입력 String 은 길이 B 바이트(1_000_000 과 8_000_000), ASCII 반·다중 바이트 반(결정적 생성).

| 항목 | Pruv 함수 | 뜻 |
|---|---|---|
| 바이트 스캔 | `scan_str(s: str) -> i64`(128 이상 바이트 수) 와 같은 일의 `scan_u8(a: [u8]) -> i64` | str 읽기가 [u8] 읽기와 같은 비용인지 |
| 부분 복사 | `mid(s: str, lo: i64, hi: i64) -> str ! alloc`(`substr`) 와 `dup(s: str) -> str ! alloc`(`copy`), 드라이버가 받은 String 을 `black_box` | substr·copy 비용(바이트당). 할당 포함, llvm 은 바인딩의 str 반환 UTF-8 재검사 포함 |
| ABI UTF-8 검사 | llvm: raw C 진입 `pruv_abi_blen(ptr, len)`(UTF-8 검사함) 와 바인딩 `blen(&str)`(`pruv_abi_blen__typed`, 검사 안 함) | 차이 = raw 진입 `pruv_check_utf8` 비용. rust 뒷단은 `&str` 라 검사 없음 |

고침(첫 측정 뒤): 처음 판은 `mid_len`·`copy_len`(len 만 반환)이라 rust 뒷단에서 복사가 최적화로 사라졌고(바이트당 0.0001ns 미만), UTF-8 검사를 바인딩 `blen`(typed, 검사 없음) 대 `blen_u8` 로 재서 0으로 나왔다. 위 표대로 바꿔 다시 쟀다.

- 호출마다 R회(기본 7) 중앙값, 바이트당 ns. 결과가 `reference` 계산과 같은지 확인(같지 않으면 실패).
- 모든 함수는 증명 모드(검증 통과)로 빌드한다. 공개 진입 `requires` 검사가 끼면(`len(s) <= ...` 같은) 그 비용도 들어가므로 측정 함수에는
  O(1) requires 만 둔다.

## 5. 계약 작성량 (`bench/g2/solutions/i64_repr/`, `bench/g2/contract_size.py`)

- 같은 6문제를 G2 이전 표현으로 쓴 판: 바이트는 `[i64]` + 원소 범위 `requires`/`ensures`(`0 <= a[k] && a[k] <= 255`),
  bool 은 `[i64]` 0/1, 문자열은 `[i64]` 바이트 + 경계 식을 그대로 펼침(`k == 0 || k == len(a) || (a[k] < 128 || a[k] >= 192)`).
  함수 이름은 같고 타입만 다르다. 검증 통과해야 한다(채점기로는 돌리지 않는다: 서명이 달라서).
- 셈: 파일마다 `requires`·`ensures`·`invariant`·`assert`·`decreases` 줄 수와 그 절들의 토큰 수(식별자·숫자·연산자, 주석 제외),
  코드(나머지 본문) 줄 수. ref_pruv 와 i64_repr 를 나란히.

## 6. 기존 bench 정답·검증 성공률

- 기존 bench(`bench/harness/run.py`, 정본 풀이 폴더)를 HEAD 로 두 뒷단 돌려 기준 결과 파일과 정답·검증 결과를 비교한다(조사 결과로 정확한 명령을 정함).
- g1 ref·indep_try2, examples·must_reject 는 `run_all` 833행(Q1 기준, 컴파일러 불변)으로 이미 덮인다.

## 7. 독립 사용 (8.4)

- 작성자: Claude sonnet 쓰기 위임, `SPEC.md`·`bench/g2/PROBLEMS.md` 만 읽게 함(다른 풀이·examples·docs·컴파일러 금지), 실행 없음.
- 첫 시도 `bench/g2/solutions/indep_try1/`, 고친 판 `indep_try2/`(필요한 문제만이 아니라 6개 모두 둔다). 채점은 메인이
  `bench/g2/run.py` 로 `--compiler rs`·`py` × `--backend rust`·`llvm`. 결과 `bench/g2/results/indep_try{N}_{compiler}_{backend}.json`.
- 고치기에 넘기는 것은 컴파일러 오류 JSON(반례 포함)과 실패 시험 첫 줄뿐. 정답 풀이·힌트는 주지 않는다.
- 기록: 첫 시도 성공 수, 고치기 횟수, 최종 성공 수. 실패 원인이 명세 부족이면 SPEC 를 고친 사실과 함께 적는다.
- 실제 진행(RESULTS 43): 작성자 1 `indep_try1..3`(고치기 2회, 최종 5/6) → SPEC 8절에 `verify_unknown` 안내 추가 →
  작성자 2 `indep2_try1`(6/6, 단 안내 예시에 q04 정답 불변식이 들어가 있었음 — 감사 필수 1) → 예시를 일반 문구로 고친 SPEC 로
  작성자 3 `indep3_try1`(첫 시도 6/6, 관문 판정에 쓰는 결과). 작성자마다 새 위임(이전 시도를 모름), 2·3 은 이전 풀이 폴더도 금지.

## 8. 남기는 것

- raw 진입 `[i64]`·`[u8]`·`[bool]` 의 음수 길이·NULL 거부는 G2_SPEC 5.4("raw 포인터의 실제 할당 크기·수명·접근 가능성은 외부 호출자의
  계약")에 따라 이번에 넣지 않는다. `str` 은 B2 에서 넣었다. 남은 공백으로 기록한다.
- i32(A6)는 미룬다.
