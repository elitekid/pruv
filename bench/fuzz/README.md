# Vow 컴파일러 차분 퍼징

무작위로 만든 Vow 프로그램을 컴파일러(`vowc/vowc.py`)와 독립 오라클(`oracle.py`)에 모두 돌려서 결과를 비교한다.

## 검사하는 약속

검증기가 받아들인 프로그램(vowc 기본 모드, exit 0)은 다음을 만족해야 한다.

- `requires`를 만족하는 모든 입력에서 범위 밖 인덱스, 오버플로, 나눗셈 정의역 위반이 없다.
- `ensures`(그리고 invariant/assert/decreases)가 성립한다.
- 출력이 오라클과 같다.

모드마다 **자기 오라클**과 비교한다. 증명 모드(`rust-proof`/`llvm-proof`)는 `oracle.run(..., mode="proof")`
(안쪽 호출의 실행 requires 검사를 건너뛰고 `call_requires ...` 계약 실패를 기록), 안전 모드는 `mode="safe"` 결과다.
검증된 프로그램은 입력마다 두 결과(`oracle_proof`, `oracle_safe`)를 계산하고, 거절된 프로그램은 안전 결과만 쓴다.
(`results.json`의 `oracle`은 호환용으로 안전 결과.)

- 오라클 결과(kind, 값, 출력, detail 접두어)가 같은 모드끼리는 (종료 코드, stdout, `vow: ...` 줄)이 정확히 같아야 한다.
  `rust-X == llvm-X`(X = proof, safe)는 항상 요구하고, proof == safe는 두 오라클 결과가 같을 때만 요구한다.
  안쪽 호출의 실행 requires가 i128 한계에 닿는 경우처럼 두 오라클 결과가 다르면 증명·안전 모드가 정당하게 달라질 수 있다.
- 오라클이 ok면 exit 0, 기대 stdout, **빈** `vow:` 줄. 오라클이 오류면 exit 101, `vow:` 줄이 기대 접두어로 시작,
  stdout은 오류 직전까지 오라클이 찍은 줄들(각 줄 + 개행, 없으면 빈 문자열)과 같아야 한다.
- 오라클이 `limit`(단계 한도 초과)이면 비교하지 못한 것으로 `incomplete`에 센다 (실패도 통과도 아님).

| 모드 | backend | 증명 여부 |
|---|---|---|
| `rust-proof` | rust | 기본 (검증기 통과 프로그램만) |
| `rust-safe` | rust | `--no-verify` |
| `llvm-proof` | llvm | 기본 (검증기 통과 프로그램만) |
| `llvm-safe` | llvm | `--no-verify` |

검증기가 거절한 프로그램 중 `--rejected-sample`개는 안전 모드 2개만 만들어 오라클과 비교한다.

## 실행

```
python bench/fuzz/run.py [--seed 1] [--programs 100] [--inputs 8] [--max-candidates 400] \
                         [--rejected-sample 30] [--jobs N] [--out bench/fuzz/out/<seed>] [--keep-work]
python bench/fuzz/run.py --seed 32 --programs 600 --max-candidates 3000 --avoid-known fz01   # 보고한 결함 형태는 피함
python bench/fuzz/run.py --replay bench/fuzz/out/1/failures/unsound_c1_17     # 저장된 사례 다시 실행
python bench/fuzz/run.py --replay path/to/case.vow                             # 옆의 inputs.json 사용
python bench/fuzz/generate.py --seed 1 --count 20 --out /tmp/vowgen            # 생성된 .vow만 확인
```

- 필요 도구: `rustc`, `clang`, 파이썬 3.9 (`.venv/bin/python`이 있으면 그것으로 vowc를 돌린다). 표준 라이브러리만 쓴다.
- `runtime.c` 객체는 한 번만 만들어 재사용한다.
- 종료 코드: 실패가 하나라도 있으면 1.

### 단계

1. 후보 생성(index 0,1,2,...) 후 `oracle.parse_program`으로 파싱. 오라클이 지원하지 않으면 건너뛰고 센다.
2. `vowc --no-verify`(타입 검사)와 기본 모드(검증)를 돌린다. `--no-verify`가 exit 1이고 진단 JSON의 stage가
   parse/type/effect뿐이면 `generator_invalid`. 그 밖의 종료 코드(음수=신호/크래시, 2=사용법, 3=내부 오류 등)나
   다른 stage의 exit 1은 `internal_error` 실패, 시간 초과(120초)는 `timeout` 실패.
   후보는 스트리밍으로 낸다: 최대 `jobs*2`개를 진행 중으로 두고 하나 끝날 때마다 다음 후보를 제출한다.
   `--programs`개가 검증을 통과하거나 `--max-candidates`에 닿으면 제출만 멈추고, 이미 낸 후보의 결과는 모두 거둔다
   (실패도 기록). `--programs`를 넘는 통과 프로그램은 빌드하지 않는다. 통과가 모자라면 경고를 찍고 `programs_short`.
3. 프로그램마다 입력 300개를 뽑아 `check_requires`로 나누고, `--inputs`의 3/4를 만족 입력, 나머지를 위반/미정의 입력으로 고른다 (모자라면 있는 것으로 채움).
4. (프로그램, 모드)마다 바이너리 1개를 만든다. 생성된 `main`이 `argv[1]`로 입력 번호를 받는다.
5. 바이너리를 입력마다 1번 실행한다 (제한 10초). (종료 코드, stdout, 첫 `vow: ` 줄)을 기록한다.
6. 검사하고 실패를 저장한다.
7. `summary.json`과 짧은 요약을 쓴다. 작업 폴더는 `--keep-work`가 없으면 지운다.

## 출력 구조

```
OUT/summary.json                  후보 수, 생성기 오류, 검증 통과, 거절(오류 코드별), 실행한 입력 수, 실패 종류별 수, 단계별 시간(초),
                                  incomplete(oracle limit으로 비교 못 한 (입력, 모드) 수),
                                  no_sat_inputs({count, names 처음 20개}: requires 만족 입력이 하나도 없는 프로그램),
                                  programs_short(검증 통과가 --programs보다 적으면 true)
OUT/failures/<kind>_<case>/       실패한 사례마다
    case.vow                      프로그램
    inputs.json                   인자 목록들
    results.json                  모드·입력별 (exit, stdout, vow 줄)과 오라클 결과, 실패 상세
    vowc_output.txt               vowc 출력 (--no-verify, 검증)
OUT/generator_invalid/            타입 검사를 못 넘은 생성물 처음 10개
```

## 실패 종류

| kind | 뜻 |
|---|---|
| `mode_mismatch` | 기대 오라클 결과가 같은 모드들(또는 rust-X/llvm-X)이 (종료 코드, stdout, `vow:` 줄)에서 서로 다르다 |
| `oracle_mismatch` | 모드별 오라클과 다르다: ok면 exit 0 + 기대 stdout + 빈 `vow:` 줄, 오류면 exit 101 + `expected_stderr_prefix`로 시작하는 줄 + 오류 직전 출력과 같은 stdout (`limit`은 `incomplete`로 셈) |
| `unsound` | 검증됨 + 입력이 requires 만족인데 `oracle_proof`가 오류(oob/overflow/div_domain/내부 requires)를 내거나 `contract_failures`(ensures·invariant·assert·decreases, `call_requires ...` 포함)가 있다. `limit` 결과도 먼저 검사한다 |
| `internal_error` | vowc 종료 코드가 0/1이 아님(3, 음수=신호, 2=사용법 등), `--no-verify` exit 1인데 진단 stage가 parse/type/effect가 아님, 또는 검증기 오류 JSON의 stage가 `internal` |
| `build_error` | 검증기(또는 `--no-verify`)가 받아들였는데 vowc(llvm)/clang/rustc가 실패 |
| `timeout` | vowc가 120초 안에 끝나지 않음 |
| `run_timeout` | 바이너리가 10초 안에 끝나지 않음 (오라클이 `limit`이면 `incomplete`로 셈) |
| `oracle_error` | 오라클이 예외를 던짐 (오라클 버그 의심) |
| `harness_error` | 이 도구 자체의 예외 |

## 오라클 독립성

`oracle.py`는 자체 파서와 해석기를 가지며 `vowc`에서 아무것도 import하지 않는다.
그래서 컴파일러와 같은 버그를 공유하지 않는다. 오라클은 Rust `println!("{}")` 형식으로 값을 찍고,
`vow: ...` 메시지의 접두어를 알려 준다. 오라클 자체가 틀렸을 수 있으므로 `oracle_mismatch`는 먼저 오라클을 의심해 본다.

## 생성기 재료 (`generate.py`)

- 본문: `let mut` 지역 직선 코드(+ - * / % 단항 -), `a[e]` 인덱싱(가드 있음/없음), if/else, 정수·배열 매개변수 1~3개, 반환 i64 또는 bool.
- requires: 정수 범위(10, 1000, 10^6, 2^31), `len(a) <= N`, `len(a) >= k`, 원소 범위 `forall`, `x < y`, 가드 있는/없는 `a[x] > 0`, `(y != 0) && ((x / y) > 2)`와 무방비 `/`, `(x % 3) == 1`(유클리드), `sum`, `count`, 가드 있는/없는 `max`/`min`, `exists`, 정렬성(`j in i..len(a)`, `j in (i + 1)..len(a)`), `==>`.
- 반복문 틀(올바른 invariant 포함): 합(SPEC §9), 개수 세기, 최댓값 스캔, 선형 탐색(`return i` / `-1`), 카운트다운(`while m > 0 decreases m`), 정렬 배열의 끝값 - 첫값.
- 변이(약 35%): invariant 하나 빼기, 마지막 `<=`를 `<`로, 조건 `i < len(a)` → `i <= len(a)`, 걸음 `+1` → `+2`, 잘못된 decreases, 비교 뒤집기, 반환값 어긋남.
- 보조 함수 `fn g(p, q)` (약 30%, 자체 requires/ensures, f가 호출).
- ensures(약 60%): 참이 보장된 것(`result == <반환식>`, 틀별 ensures)과 거짓일 수 있는 무작위 경계.
- 입력: requires 경계 근처, 0, ±1, 작은 값, 가끔 i64 극값. 배열 길이 0..8. 반복 횟수를 정하는 매개변수는 상한(3000)을 둔다.

## 알려진 한계

- 부분집합만 다룬다: 구조체, 열거형, Option/Result, 계약 안의 함수 호출은 생성기·오라클 모두 쓰지 않는다.
  효과(print/io, alloc/copy), 지역 배열, assert, 중첩 반복, bool 매개변수는 3판 생성기부터 만든다(약 20%).
- 배열 길이는 최대 8, 값 범위는 경계 근처로 치우쳐 있어 큰 배열이나 `2^30` 반복 예산 같은 자원 한계는 건드리지 못한다.
- 둘 이상의 배열 매개변수, 배열을 반환하는 함수는 없다.
- 오라클의 `limit`(단계 한도 초과)은 비교하지 않고 `incomplete`로만 센다 (단, `limit` 결과의 `contract_failures`는 `unsound` 검사에 쓴다).
  `limit` 모드끼리는 기대 결과가 같다고 보지 않으므로 proof == safe 도 요구하지 않는다(rust-X == llvm-X 는 요구).
- `vow: ` 줄은 stderr의 첫 번째 `vow: `로 시작하는 줄만 본다.

## 찾은 실패

- **fz01 — 인덱스 대입 평가 순서** (`tests/runtime/fz01_index_assign_order.{vow,rs,json}`).
  `b[i] = v`에서 증명 모드는 값(`v`)을 먼저, 안전 모드는 인덱스(`i`)를 먼저 평가해 부수 효과·실패 순서가 다르다.
  상태: **현재 실패 중**. 고칠 곳은 vowc다: `codegen.py`의 `IndexAssign` 검증된 가지가
  `*a.get_unchecked_mut(i) = v`를 내는데 Rust는 이때 오른쪽을 먼저 평가한다. `llvmgen.py`의 `IndexAssign`이 이를 그대로 따른다.
  생성기 3판(effects 재료)은 100개 중 5개에서 이것을 스스로 찾는다. 이미 보고했으므로 `--avoid-known fz01`로 피할 수 있다
  (값을 지역에 먼저 묶어 대입).
- **fz02 / fz03 — 증명 모드 Rust 뒷단의 rustc 거부 lint** (`tests/runtime/fz02_const_div_zero`, `fz03_const_overflow`).
  requires가 모순이라 검증이 공허하게 통과한 함수의 본문에 `x % 0` 또는 `i64::MAX + 1`처럼 상수로 접히는 연산이 있으면,
  증명 모드 Rust 출력(검사 없는 `%`·`+`)을 rustc가 기본 거부 lint `unconditional_panic`·`arithmetic_overflow`로 컴파일하지 않는다.
  LLVM 뒷단과 안전 모드는 정상(진입 requires 위반으로 101). 상태: **현재 실패 중**(Rust 증명 모드만).
  고칠 곳 추정: `codegen.py`의 `ALLOW` 속성에 `unconditional_panic, arithmetic_overflow`를 더한다(검증된 코드에서 그 연산은
  도달 불가). 퍼징에서는 생성기 2판 재료(나눗셈 재료가 상수 0을 고름 + 모순 requires)로 600개 중 1개에서 나왔다.

## 실패를 회귀 테스트로 만들기

1. `--replay OUT/failures/<kind>_<case>`로 재현하고, 가능하면 프로그램을 줄인다.
2. 검증기가 받아들이면 안 되는 프로그램(`unsound` 중 검증이 틀린 경우): `tests/must_reject/<이름>.vow`와
   `tests/must_reject/<이름>.json`(`{"stage": "verify", "code": "<기대 오류 코드>"}`)을 만든다. 기존 파일 형식을 따른다.
3. 실행 시간 동작(모드 불일치, 메시지, 종료 코드): `tests/runtime/<이름>.vow`, 입력 하나를 부르는 `tests/runtime/<이름>.rs`
   (`fn main() { ... println!("{}", sol::f(...)); }`), 기대를 적은 `tests/runtime/<이름>.json`
   (예: `{"flags": [], "exit": 101, "stdout_contains": null, "stderr_contains": "requires violated"}`)을 만든다.
   `--no-verify` 동작이면 `"flags": ["--no-verify"]`, 여러 입력은 여러 테스트로 나눈다.
4. `python tests/run_all.py`로 확인한다 (`--backend both`로 두 backend 모두).

## 실행 기록

2026-11-10, 맥미니(10코어), `--jobs 10`. 시간은 벽시계 기준.

| 시드 | 생성기 | 통과 프로그램 | 후보 | 입력 | 프로세스 실행 | 시간(생성+검증 / 빌드 / 실행) | 실패 |
|---|---|---|---|---|---|---|---|
| 1 | 1판, 바이너리 프로그램×모드마다 | 100 | 277 | 1,040 | 3,680 | 188초 (13 / 25 / 150) | 0 |
| 1 | 1판, `--batch 25` | 100 | 277 | 1,040 | 3,680 | 34초 (14 / 10 / 9) | 0 |
| 3 | 1판 | 500 | 1,320 | 5,200 | 18,400 | 326초 (210 / 51 / 65) | 0 |
| 11 | 2판(재료 확장) | 100 | 259 | 1,280 | 4,160 | 42초 (21 / 9 / 12) | 0 |
| 12 | 2판 | 600 | 1,594 | 6,400 | 22,400 | 177초 (78 / 44 / 54) | 0 |
| 21 | 2판, 감사 반영 하네스(모드별 오라클, 스트리밍) | 66 | 193 | 640 | 2,240 | 21초 (9 / 5 / 6) | 0 |
| 31 | 3판(지역 배열·효과·assert·중첩 반복·bool·보조 함수) | 114 | 231 | 1,120 | 3,840 | 23초 (8 / 7 / 9) | fz01 5개 프로그램 |
| 32 | 3판, `--avoid-known fz01` | 606 | 1,325 | 6,370 | 22,264 | 151초 (53 / 36 / 63) | fz02 1개 프로그램 |

- 시드 3의 생성+검증 210초는 z3가 오래 걸린 후보 몇 개 탓이다(`verify_unknown` 2건). 2판은 같은 규모에 78초.
- 2판 입력 결과(시드 12): 검증 통과 프로그램에서 requires 만족 3,839 / 위반 900 / 미정의 61(모두 i128 한계,
  명세가 허용하는 자원 한계), 거절 프로그램 안전 모드에서 div_domain 294·oob 43·overflow 25·호출 requires 위반 25·
  requires 미정의 36.
- 검출 확인: 오라클의 출력 형식을 일부러 틀리게 바꾸면 `oracle_mismatch` 8건이 잡히고 `--replay`로 재현된다.
- rustc가 PATH에 없으면 `PATH=$HOME/.cargo/bin:$PATH`로 돌린다(run.py는 `~/.cargo/bin/rustc`도 찾는다).
