# Pruv(옛 이름 Vow) v0.1 실험 결과 (2026-11-10)

> 이름 변경(2026-11-10): 언어 이름이 Vow → **Pruv**로 바뀌었다(14절). 13절까지는 당시 기록이라 옛 이름·경로를 그대로 둔다. 옛 경로 대응: `vowc/vowc.py` → `pruvc/pruvc.py`, `*.vow` → `*.pruv`, `solutions/vow_try1`·`vow_agg` → `pruv_try1`·`pruv_agg`, `g1/solutions/ref_vow` → `ref_pruv`, `solve/vow` → `solve/pruv`, 실행 오류 접두사 `vow:` → `pruv:`. bench 결과 JSON(`mutants*.json`, `results_*vow*.json`, `g1/results_*.json`)과 `solve/` 입력 사본(SPEC·PROBLEMS)은 옛 이름 그대로 보존.

## 1. 독립 AI 작업자(Claude sonnet, 실행 없이 한 번에 작성)
| | 첫 시도 | 고치기 1회 뒤 |
|---|---|---|
| Rust | 10/10 통과 | - |
| Vow (명세 6쪽만 보고) | 9/10 (p03 오버플로 증명 실패, 실제 버그 아님) | 10/10 |

- p03: 컴파일러 JSON 반례(`len=0, i=i64::MAX`) 하나로 작업자가 불변식을 고쳐 통과.
- 작업자는 p04(최소 인덱스)·p06·p10에 핵심 동작 계약을 쓰지 않음 → 그 부분 논리 버그는 Vow도 못 잡는다.

## 2. 변이 시험 (solutions/vow_try1에 작은 버그 83개 주입, bench/mutants.json)
| 결과 | 개수 |
|---|---|
| 테스트에서 틀린 변이체 (무한 루프 20개 포함) | 79 |
| └ Vow가 컴파일 때 거부 | **73 (92%)** |
| └ Vow가 통과시킴 | 6 |
| 테스트 통과(동작 같음) 변이체 | 4 (그중 1개는 Vow가 거부 = 오탐) |

- rustc 단독은 79개 모두 컴파일을 통과시킨다(타입이 맞으니까). 범위 밖 접근은 Rust에서도 실행 중 panic으로 드러나지만, 나머지 논리 버그는 조용히 틀린 값을 낸다.
- 놓친 6개는 모두 동작 계약이 없는 함수(합, 최대 부분합, 개수, 내적)의 `+`↔`-`, `<`↔`<=` 같은 값 버그다.
- 거부 사유: 불변식 유지 실패 30, 범위 밖 14+6=20, 불변식 시작 14, 사후조건 4, 종료 3, 기타 2.
- 오탐 1개: p02 `i = 1`→`0`은 동작은 맞지만 불변식 `1 <= i`와 어긋나 거부.

## 3. 속도 (1,000,000개 입력, 21회 중앙값)
Vow가 만든 Rust, 작업자 Rust, 참조 Rust가 대부분 측정 흔들림(같은 코드끼리도 최대 ±40%) 안에서 비슷했다. p04는 한 번 Vow가 느리게(93ms 대 67ms) 나왔지만 반복 측정 전에는 결론 못 냄.

## 4. 결론과 한계
- 가설 "오류는 적고 속도는 같다": **속도는 같다는 쪽, 오류는 계약을 쓴 만큼 크게 준다는 쪽**으로 나왔다.
- 이 언어의 효과는 결국 AI가 계약을 얼마나 세게 쓰냐에 달렸다. 다음 단계는 합·최대값 같은 집계를 계약에서 쓸 수 있게 하는 것(명세 함수).
- 한계: 문제 10개가 쉽다. 작업자는 모델 하나뿐이다. 변이 시험은 내가 쓴 풀이에만 돌렸다. 컴파일러(내가 작성)는 아직 감사를 받지 않았다. 검증기에 건전성 버그가 있으면 숫자가 달라진다.

## 5. 2단계: 계약용 집계 (2026-11-10)
문법 `sum/count/max/min(k in lo..hi: e)` (SPEC 6절). 집계를 z3의 정의되지 않은 함수 F(lo, hi, 바깥 묶인 변수)로 두고,
쓰인 자리마다 "한 칸 펼치기" 사실(위·아래 끝 줄이기/늘리기, sum·count 빈 구간 = 0)을 보조정리로 넣는다.
묶인 변수가 든 끝은 움직이지 않게 해서 매칭 루프를 막는다. 증명은 보조정리 없이 먼저 풀고, 안 되면 넣고 다시 푼다.

| | 1차(계약 없음, mutants.json) | 집계 계약판(mutants3.json) |
|---|---|---|
| 테스트에서 틀린 변이체 | 79 | 79 |
| └ Vow가 컴파일 때 거부 | 73 (92%) | **79 (100%)** |
| └ 그중 시간 초과(verify_unknown)로 거부 | 0 | 0 |
| 동작이 같은 변이체 중 거부(오탐) | 1 / 4 | 1 / 4 (같은 p02 `i = 1`→`0`) |

- 풀이: `bench/solutions/vow_agg/` (vow_try1에서 p01·p06·p07·p09에만 집계 ensures·불변식 추가). 4개 모두 0.1~0.3초에 증명, 재채점 10/10.
- 놓쳤던 6개(p01 `+`→`-`, p06 `cur + v`→`cur - v`, p07 `<`→`<=`·`c + 1`→`c`, p09 `+`→`-`·`*`→`+`)를 모두 잡는다.
- p06(최대 부분합)은 `max`로 쓰면 증명이 안 된다("max(e + c) = max(e) + c" 같은 귀납 사실이 필요). 대신
  "모든 부분합 이상이고(forall) 그중 하나와 같다(exists)"로 쓰면 증명된다.
- 중간 판(보조정리를 모든 증명에 넣던 판, mutants2.json)도 79/79를 잡았지만 p06 변이 4개가 시간 초과로 거부돼
  반례가 없었다. 증명을 두 번에 나눈 뒤 0개가 됐다.
- 회귀: tests/must_reject 20/20 거부 유지, examples 그대로. 일부러 틀린 집계 계약 5개(바깥 변수 본문, 중첩 집계, 빈 max 등) 모두 거부.
- 감사(Claude sonnet) 건전성 필수 0, 고친 뒤 확인 감사 필수 0. 두 감사 모두 셸이 막혀 코드 읽기로만 판단했고, 재현은 내가 위 시험으로 했다.
- 한계: 펼치기가 자리마다 한 칸이라 `sum(k in 0..3: j) == 3*j`처럼 고정 구간을 여러 칸 계산하는 맞는 계약은 증명 못 한다(시간 초과).
  구간 중간 원소 <= max, sum 임의 지점 분할 같은 사실도 자동으로 모른다. 집계 계약은 내가 썼다. 독립 AI가 집계 계약을 스스로 쓰는지는 아직 안 쟀다.

## 6. 0단계: 안전 모드와 공개 함수 경계 검사 (2026-11-10)
고친 구멍 두 개:
1. `--no-verify`(증명 안 함)인데도 `get_unchecked`와 조용히 wrap 되는 산술을 내던 문제 → 안전 모드: 인덱싱·산술·alloc 크기를 검사하고 어기면 panic(`vow: index out of bounds`, `vow: arithmetic error`). `/` `%`는 검증기와 같은 정의역(제수 > 0, 피제수 >= 0).
2. 생성된 `pub fn`을 Rust 쪽에서 requires를 어겨 부르면 막을 게 없던 문제 → requires가 있는 함수는 `pub fn f`(실행 중 requires 검사, `vow: requires violated`) + 비공개 `f__vow_body`. 증명 모드의 안쪽 호출은 본체로 바로 간다. 계약은 i128·유클리드 나눗셈으로 평가. `--trust-callers`로 검사를 끈다.

- 시험: `tests/run_all.py` 57/57(거부 24, examples 세 모드 10, 런타임 23).
- 감사(Claude) 필수 2건: 생성 임시 이름(`vow_k1`, `vow_i`)이 같은 이름의 사용자 변수를 가려 requires 검사를 우회하고 증명 모드에서 범위 밖 `get_unchecked`(비정상 종료 재현), 안전 모드 배열 쓰기가 틀린 값을 씀. → `vow_` 접두어·`__` 포함 이름을 파서에서 거부(`reserved_name`).
- 고친 뒤 확인(Claude) 필수 0. 권고였던 Rust 키워드·`_` 이름(rustc 컴파일 실패)도 예약어로 거부했고, 계약 도우미가 Rust 2015판(`rustc -O x.rs` 기본)에서 컴파일 안 되던 것(`usize::try_from`)을 직접 재현해 고쳤다.
- 변이 시험(`bench/mutants4.json`, vow_agg): 79/79 거부, 오탐 1/4 그대로. 기준 빌드(`--no-verify`)가 안전 모드가 되면서 시간 초과(미정의 동작 무한 루프 등)였던 변이 9개가 `wrong`(panic)으로 바뀌었다.
- 속도(vow_agg, ms, 21회 중앙값): `--trust-callers`면 예전과 같다(Rust 참조와 오차 안). 검사를 켜면 원소 범위 forall이 붙은 문제가 느려진다(p01 0.20→1.13, p05 0.30→0.76, p09 0.43→1.20). p04는 정렬 전제를 이중 forall로 써서 n=10^6에서 O(n^2) 검사가 돼 성능 단계가 시간 초과. 속도 비교는 `--trust-callers`로 잰다.
- 남은 것: 무거운 requires(정렬 등)를 같은 뜻의 O(n) 검사로 바꾸기(증명된 동치 변환), 수 범위 한정자 길이 상한, 계약 정의역(범위 밖 인덱스 등)을 검증기 의무로도 넣어 실행 검사와 의미 맞추기.

## 7. M1 = C2: LLVM IR 뒷단 (2026-11-10)
`vowc --backend llvm`은 텍스트 LLVM IR(`.ll`)과 Rust 바인딩(`.rs`)을 함께 낸다. 실행 지원 코드는 `vowc/runtime.c`이고 clang이 컴파일한다. 명세는 `docs/M1_LLVM_SPEC.md`에 있다. 정본은 Rust 뒷단(`codegen.py`)이며 고치지 않았다.
- 시험 장치는 Rust 드라이버를 그대로 두고 `mod sol`에 바인딩을 넣는다. 두 오브젝트(gen.o, rt.o)는 rustc에 link-arg로 붙인다. 반환 배열은 Rust 할당기로 할당해 복사 없이 `Vec`로 넘긴다.
- 회귀(`tests/run_all.py --backend both`) 102/102 (마무리 뒤 110/110, 런타임 33개)
  - 거부 24, 그리고 뒷단마다 examples 10, 런타임 29.
  - 새 시험 r24·r25: 평가 순서. r26~r29: 배열 해제 경로. 해제 경로 시험은 runtime.c `-DVOW_COUNT_ALLOCS`로 할당 수와 해제 수가 같은지 본다.
- IR의 증명 사실
  - 증명 모드 본체: 산술은 `add/sub/mul nsw`, 배열 접근은 `getelementptr inbounds`, 나눗셈은 `udiv/urem`(검증기가 정의역을 증명함).
  - 배열 인자: `noalias nocapture readonly`. 근거는 check.py 소유 규칙이다(인자 수정·저장·반환 금지).
  - 안전 모드 본체에는 `nsw`가 없다(시험으로 확인).
- bench vow_agg `--trust-callers`: 두 뒷단 모두 10/10.
  - 속도는 같은 실행 파일 안의 Rust 참조와 비교했다. 실행마다 참조 시간이 흔들려서다.
  - 같음: p01·p02·p05·p06·p07·p10, p08(0초기화 할당으로 고친 뒤 0.20ms 대 0.20ms).
  - LLVM이 더 빠름: p03(참조 대비 1.17배, Rust판 1.48배), p09(0.79배, Rust판 1.0배).
  - **LLVM이 더 느림: p04 4~5%.** 두 번 쟀다. Rust판 33.4~33.5ms, LLVM판 34.9~35.3ms. 백만 번 호출하는 문제다. Rust 드라이버가 FFI 경계 너머의 함수를 인라인하지 못해서라고 추정하고, 확인하지 않았다. M1 속도 기준(오차 안 또는 더 빠름)을 이 문제 하나가 못 채운다.
- 변이 시험(`bench/mutants5_llvm.json`, 감사 고침 전 빌드)
  - 검증기 판정 81개가 모두 Rust판(mutants4)과 같다. 79/79 거부, 오탐 1/4.
  - 시험 결과가 다른 것은 4개이고, Rust판의 시간 초과가 LLVM판에서 `wrong`이 됐다. p01·p05·p09의 `i = i + 1`→`i = i`, p04의 `lo < hi`→`lo <= hi`다.
  - p01 하나를 재현했다. 끝나지 않는 루프에서 누적값이 넘쳐 `overflow in +`(101)로 멈춘다. LLVM판이 120초 제한 안에 그 지점에 닿는 것으로 본다. Rust판을 끝까지 돌려 같은 오류가 나는지는 확인하지 않았다.
  - 차이가 나는 까닭이 하나 더 있다. LLVM판 panic은 C `exit(101)`이라 프로세스 전체가 끝나지만, Rust판은 `catch_unwind`로 다음 입력을 계속 돌린다. 둘 다 "통과 아님"이라 판정은 같다.
- 감사(Claude Opus) 필수 1건
  - 증명 모드 `a[i] = v`에서 정본은 v를 먼저 평가하는데, LLVM판은 i를 먼저 평가했다. `! io` 함수를 식 안에서 부르면 출력 순서가 달라진다(정본 2,1,2, LLVM 1,2,2). 직접 재현하고 고쳤다.
  - 같이 고친 권고: panic 전에 Rust stdout 비우기, 0초기화 할당, 해제 경로 실행 시험, IR 검사를 본체 함수로 좁히기, 내부 오류는 exit 3·변이 시험에서 crash로 분류, CPU 옵션을 아키텍처별로.
- 고친 뒤 확인(Claude Opus): 필수 0.
  - noalias·readonly 속성은 건전하다고 판정했다.
  - 남은 권고:
    - 증명 모드 nsw 검사를 명령어 단위로 엄격하게.
    - 해제 시험 보강: 증명 모드판, while 조건·return 식·인덱스 대입 안의 임시, 길이 0 배열.
    - 누수와 이중 해제가 같이 생기면 수가 상쇄돼 놓친다.
- 마무리(같은 날, 커밋 d6aa190 뒤)
  - 감사 고침 뒤 변이 시험 재실행(`bench/mutants6_llvm.json`): mutants5와 똑같다. 검증기 판정은 Rust판과 같고, 시간 초과→wrong 4개도 그대로다.
  - 해제 시험 r30~r33을 더해 런타임 33개가 됐다. 두 뒷단 모두 통과했고, Rust판 출력이 손으로 계산한 기대값과 같았다.
    - r30: 증명 모드에서 while 지역 배열·재대입·임시
    - r31: while 조건·return 식·인덱스 대입 안의 임시
    - r32: 길이 0 배열
    - r33: if/else 양쪽 return
  - p04 원인은 판정하지 못했다. 다른 작업 때문에 load average가 12~34여서 측정이 흔들렸다.
    - 같은 실행 파일 안 참조 대비 비율을 네 번 재 중앙값을 냈다. Rust판 1.08, Rust판의 공개 함수 인라인을 막은 것 1.22, LLVM판 1.32.
    - 호출 경계(인라인 불가)가 차이의 일부를 설명하지만 전부는 아닌 것으로 보인다. 남는 후보는 Option을 out-pointer로 돌려주는 비용과 본체 코드 차이다.
    - 조용한 기계에서 다시 재야 한다.
- p04 후속(외부 ABI에서 Option·Result를 `{i64,i64}` 레지스터로 반환)
  - out-pointer를 없앴다. macOS arm64·SysV 전용이다(명세 4절).
  - 회귀 110/110.
  - 네 판을 다섯 번씩 재서 같은 실행 파일 안 참조 대비 비율의 중앙값을 냈다. 이번에도 load average가 15~21이었다.

    | 판 | 참조 대비 |
    |---|---|
    | Rust판 | 1.14 |
    | Rust판, 인라인 막음 | 1.13 |
    | LLVM판, out-pointer | 1.21 |
    | LLVM판, 레지스터 반환 | 1.16 |

  - 레지스터 반환으로 Rust판과의 차이가 약 6%에서 약 1.5%로 줄었다. 반복 사이 흔들림(±10%) 안이다.
  - 판정: 남은 차이는 측정 오차 안이다. 이것으로 M1 속도 기준을 채운 것으로 본다. 다만 조용한 기계에서 확인하지는 못했다.
- 남은 것
  - p04를 조용한 기계에서 한 번 더 재기.
  - Windows x64 ABI: 16바이트 구조체 반환을 하강해야 한다(M3).
  - Windows·Linux 연결 시험. M1 산출물은 macOS arm64 개발용이다.

## 8. M2 = G1: 구조체·열거형 (2026-11-10)
설계 `docs/M2_G1_SPEC.md`, 언어 `SPEC.md` 6a절. 필드는 i64·bool·Option/Result<i64>·다른 사용자 타입만(배열 필드, 재귀 타입, `[Point]`, `Option<Point>`는 G2·G3로 미룸). `let mut` 지역의 중첩 필드 대입, 문장 `match`, 계약 전용 `is_variant`·`variant_field`.
- 검증기: z3 Datatype. `variant_field`는 실제 평가 순서(단락, forall/exists 조기 종료)를 따라 정의역을 증명한다(`variant_domain`). 루프에서 필드 하나를 바꾸면 그 변수 전체를 잊는다.
- 두 뒷단: Rust는 `Copy` 타입과 i128 계약 대응 타입, LLVM은 태그+모든 변형 payload를 평탄화한 집합값. 외부 경계는 i64 word 배열 포인터. M1의 Option/Result ABI는 그대로.

건전성 관문 5개:
| 관문 | 결과 |
|---|---|
| 1. SPEC 한 쪽 이내 | SPEC.md 6a절 |
| 2. 틀린 프로그램·틀린 계약 거부 | `tests/must_reject/g1_*` 36개 모두 기대 단계·코드로 거부(실행기가 `.json`의 stage·code까지 확인) |
| 3. 기존 숫자 유지 | `run_all --backend both` 250/250. 변이(LLVM, vow_agg) 81개 판정이 M1(`mutants6_llvm.json`)과 모두 같음, 시험에서 틀린 71개 전부 거부(`bench/mutants7_g1_llvm.json`). bench 10문제 정답(두 뒷단) |
| 4. 감사 1회 + 확인 1회(Claude opus) | 필수 결함 0. 권고 중 시험 공백(재현 8개 추가), `E::V()` 허용, 진단 키, Rust 실행 requires 변환 반복을 고침. 기존 프로그램 47개 검증 시간 HEAD 1.27~1.30s → 1.22~1.25s |
| 5. 독립 AI 측정 | 아래 |

독립 AI(Claude sonnet, SPEC.md와 `bench/g1/PROBLEMS.md`만, 실행 없이 한 번에 작성), 문제 5개 `bench/g1/`:
| | 첫 시도 | 고치기 1회 뒤 |
|---|---|---|
| Vow G1 | 4/5 (g01 거부) | 5/5 (두 뒷단, 각 시험 307~310개 통과) |
- g01: 코드는 맞고 계약이 틀렸다. "두 사각형이 엄격히 겹치면 넓이 > 0"이라 썼는데 폭 0인 사각형이면 거짓이다. 검증기가 그 반례로 거부했고, 작업자가 반례를 보고 전제를 고쳐 통과했다. 틀린 약속을 잡은 경우라 바라던 동작이다.
- 이때 반례의 구조체 값이 z3 내부 이름(`m1t1!Rect(...)`)으로 나와 Vow 문법(`Rect { lo: Point { x: .., y: .. }, .. }`)으로 바꿨다. 재시도에 넘긴 오류는 메인이 같은 형태로 손질한 것이다.
- 작업자는 동작 계약을 스스로 썼다(g02·g04 변형별 결과, g05 첫 음수 조건, g03은 집계 대신 forall/exists로 min/max).

남은 것
- p04 속도: 이 날 기계(녹화 ffmpeg가 CPU 1.5개)에서 이전 커밋도 120초 제한에 걸린다. 정답(307/307, 두 뒷단)은 확인했고 속도는 조용한 기계에서 다시 잰다.
- LLVM 진입이 requires에 안 쓰는 사용자 타입 매개변수까지 계약 값으로 바꾼다(-O2에서 사라질 것으로 보고 미룸).
- 열거형 평탄화 배치는 변형이 많으면 값이 커진다. 측정 뒤 union 배치·작은 타입 레지스터 반환을 판단한다.

## 9. 0단계 남은 과제: 계약 정의역·실행 반복 예산·정렬 전제 O(n) (2026-11-10)
결정 `docs/M0_CONTRACTS.md`(설계 초안 Codex gpt-6-astra, 메인이 고침), 명세 `SPEC.md` 6·6a·7절.
1. **계약 정의역을 검증기 의무로.** 계약 안 `a[i]`(범위), `/` `%`(제수 != 0, 계약 나눗셈은 유클리드), `some_val`·`ok_val`·`err_val`(태그), 빈 `max`/`min`(lo < hi)을 단락·한정자 도달 순서대로 증명한다(새 오류 코드 `contract_domain`, variant_field는 기존 `variant_domain`). requires는 앞 requires만으로, ensures·invariant는 같은 종류 앞 절까지 써서 증명한다. 이제 증명된 프로그램의 공개 함수 실행 검사는 정의역 때문에 `requires undefined`가 나지 않는다.
   - 가정에는 variant_field 정의역만 넣는다. 다른 정의역까지 가정하면 중첩 한정자 인덱스 범위가 모든 질의에 실려 p06 증명이 0.44초→69초가 됐다(되돌린 뒤 0.61초).
   - 호출 지점에서 callee requires 정의역을 다시 증명하지 않는다(callee가 증명, 감사 권고).
   - 의도한 의미 변경: 보호 없는 `max`·`variant_field` requires(r20, g1_r06)는 기본 모드에서 거부. 두 실행 시험은 `--no-verify`로만, r21은 앞에 `len(a) >= 1`.
2. **실행 반복 예산.** 정적 상한 대신, 공개 함수 진입 한 번의 requires 검사 전체가 한정자·집계 반복 2^30회를 나눠 쓴다. 넘으면 `vow: requires undefined: contract iteration budget exceeded`(101, 두 뒷단). 빈 범위·단락으로 건너뛴 식은 안 쓴다.
3. **정렬 전제 O(n).** `forall i in 0..len(a): forall j in i(+1)..len(a): a[i] <= a[j]`를 AST로 알아보고(`codegen.match_sorted_requires`) 실행 검사만 `a[k-1] <= a[k]`로 돈다. 식 어디에 있든(단락 오른쪽, 바깥 한정자 안) 두 뒷단이 같게 바꾼다. 검증기는 원래 식을 쓴다. 20만 원소에서 이중 형식이면 예산 초과, 바뀐 형식은 통과(`sort_nested_big`).

| 확인 | 결과 |
|---|---|
| 회귀 `run_all --backend both` | 341/341(이전 250에 거부·런타임 시험 추가). 새 거부 시험 cd01~cd19가 의도 코드로 거부 |
| 기존 풀이 | vow_agg 10·examples·g1 ref_vow·indep_try2 모두 그대로 증명(indep_try1/g01은 예전과 같은 `ensures` 거부) |
| bench vow_agg | 두 뒷단 9/10 성능까지 정상, p04는 성능 단계 120초 초과(기계 부하, 이전 커밋도 같음), 정답은 두 뒷단 307/307(noperf) |
| 변이(LLVM, `bench/mutants8_m0_llvm.json`) | 81개 판정·오류 코드가 `mutants7_g1_llvm.json`과 모두 같음 |
| g1 | ref_vow(LLVM)·indep_try2(Rust) 5/5 |
| 감사(Claude opus) | 필수 0, 권고 6: 호출 지점 정의역 중복 제거, 시험 공백 11개 추가, SPEC 갱신을 반영. 정의역 계산 중복·집계 보조정리 누적(성능)은 측정상 영향이 없어 남김. 고친 뒤 확인(Claude opus) 필수 0, 권고 3(시험 다듬기: cd15 진입만 실패하게, cd19 짝 시험, `%` 유클리드 실행 시험)을 반영 |

- p04 성능 구간은 공개 함수를 n번 부르므로 검사가 O(n)이 돼도 전체는 O(n^2)다. 알고리즘 속도 비교는 계속 `--trust-callers`.
- 한계: 루프 변경 후·루프 뒤에는 불변식의 비-variant 정의역을 가정하지 않는다(예전과 같음, 건전하나 덜 증명). 실행 검사는 i128이라 수학적으로 참인 계약도 중간값이 넘치면 `requires undefined`다(거짓 requires를 통과시키지는 않음). 정렬 변환은 이 두 형식만. 반복 예산 값(2^30)은 정책값이다.
- 다음: 무작위 프로그램 퍼징(`bench/fuzz/`, 독립 판정기 + Rust·LLVM × 증명·안전 4모드 대조, 계획은 M0_CONTRACTS D절).

## 10. 시험 장치 속도와 차분 퍼징 (2026-11-10)
1. **시험 장치.** `tests/run_all.py`가 시험마다 작업 하나로 스레드 풀(CPU 수)에서 돌고, 결과는 원래 순서대로 찍는다(형식·`--only`·`--backend`·종료 코드 그대로). runtime.c는 변형마다 한 번만 컴파일한다. 숨은 내부 옵션 `vowc --contract-budget N`(시험 전용, SPEC 밖)과 runtime json 칸 `contract_budget`·`ll_contains`를 더했다. 10억 번 돌던 예산 시험은 예산 1000으로 줄이고(`qb_budget_edge`가 1000번 통과·1001번 실패 경계), 실제 기본값 2^30은 `qb_across_requires`가 두 뒷단 생성 코드 글자로 고정한다(기본값을 2^21로 바꾸면 두 뒷단 모두 실패함을 확인). 두 뒷단 전체 회귀 214초(바꾸기 전, 부하 있음) → 47~51초.
2. **퍼저** `bench/fuzz/`(generate·oracle·run·README). oracle은 vowc를 쓰지 않는 독립 파서·임의 정밀도 해석기, 검증 통과 프로그램을 Rust·LLVM × 증명·안전 4모드로 돌려 대조한다. 프로그램 25개를 한 바이너리에 묶어 macOS 첫 실행 검사(바이너리마다 0.33초, 직렬)를 줄였다(100개 188초→34초). 600개 약 2.5분.
3. **찾은 결함과 고침.**
   - fz01: `a[i] = v`를 증명 모드는 값 먼저, 안전 모드는 인덱스 먼저 평가(출력이 모드마다 다름). 같은 종류로 `alloc(n, v)`도 증명 모드가 v 먼저였다(fz04). 결정: 코드는 모든 모드에서 소스 순서(SPEC 5절, M1_LLVM_SPEC 5절). 예전 순서를 고정하던 r24 기대값을 바꿨고, 구성 9가지 순서를 고정하는 r34_eval_order를 더했다.
   - fz02·fz03: requires가 모순인 검증 통과 함수의 도달 불가 `x % 0`·상수 오버플로를 rustc 기본 거부 lint가 막음. Rust 뒷단 allow에 `unconditional_panic`, `arithmetic_overflow` 추가.

| 확인 | 결과 |
|---|---|
| 회귀 `run_all --backend both` | 363/363, 약 50초 |
| bench vow_agg | 두 뒷단 9/10 성능까지 정상, p04는 성능 단계 120초 초과(이전과 같음), 정답 두 뒷단 307/307(noperf) |
| 변이(LLVM) | 81개 판정·오류 코드가 `mutants8_m0_llvm.json`과 모두 같음 |
| 퍼징 재실행(시드 41) | 후보 400 → 통과 183, 입력 1,698·실행 6,312번, 68초, 실패 0 |
| 감사(Claude opus) | 1묶음: 필수 1(기본 예산 고정 약해짐)·권고 5 → 고정·Ctrl-C 취소·범위 assert 반영, 확인 감사 필수 0. 2묶음: 필수 0, 권고 4 중 순서 시험 보강만 반영. 퍼저는 하위 대화에서 감사 2회 |

- 남김: 퍼저가 뒷단마다 vowc를 따로 불러 LLVM 증명 빌드가 검증을 한 번 더 돈다(퍼저 속도 문제, 컴파일러 옵션이 필요해 미룸). 생성기는 아직 배열 여러 개·배열 반환·구조체·열거형·Option/Result를 만들지 않는다. 다음 퍼징은 생성기 범위를 넓히는 쪽.

## 11. 퍼징 생성기 범위 넓히기 (2026-11-10)
1. **오라클** (`bench/fuzz/oracle.py`, vowc 미사용 유지): 구조체·열거형 선언·리터럴·필드 읽기/대입(중첩), `match`(Option·Result·열거형), `Some/None/Ok/Err`, 배열 반환·배열 지역 재대입, 계약 전용 `is_some/some_val/is_ok/ok_val/err_val/is_variant/variant_field`와 구조체·열거형·Option `==`. 정의역 밖(`some_val(None)`, 다른 변이의 `variant_field` 등)은 기존 정의역 위반과 같은 경로(requires는 `requires undefined`). 값은 복사 의미. `format_value`는 Rust `{:?}` 모양(구조체 `Point { x: 1, y: -2 }`, 열거형 `Hit(Point { .. }, true)`).
2. **하네스** (`run.py`): 드라이버가 Option·Result·구조체·열거형 인자를 Rust 식으로 만들고 반환은 모두 `{:?}`로 찍는다. requires 검사에서 예외가 난 입력 후보를 세어(`input_errors`) 전부 예외거나 입력 0개면 `harness_error`.
3. **생성기** (`generate.py`) 새 틀: `twoarr`(배열 2개), `arrret`(`-> [i64]`, `copy`·`alloc`·보조 함수 결과로 재대입), `option`(Option/Result 반환, 보조 함수 결과 `match`), `optparam`(Option/Result 매개변수, 가드 있는/없는 `some_val`), `struct`(f 경계에서 구조체·열거형을 받고 돌려주는 시나리오 70%, requires 안 구조체 리터럴·열거형·Option 비교, `tap(v) ! io`로 필드·인자 평가 순서·match 대상 단일 평가·두 필드 오버플로 순서 관측, 빈 구조체·Result 필드·열거형 필드).
4. **결과**: 컴파일러 결함은 찾지 못했다. 오라클의 구조체 출력을 일부러 틀리게 하면 `oracle_mismatch` 84건이 잡혀 비교는 살아 있다.

| 확인 | 결과 |
|---|---|
| 퍼징 시드 51 (새 틀 1차) | 통과 109, 입력 1,028, 18초, 실패 0 |
| 퍼징 시드 52 | 통과 809, 입력 6,586, 132초, 실패 0 |
| 퍼징 시드 54 (f 경계 구조체 후보 128) | 통과 808, 입력 6,610, 145초, 실패 0 |
| 퍼징 시드 56 (감사 반영 뒤) | 통과 805, 입력 6,550, 154초, 실패 0, `input_errors` 0 |
| 회귀 `run_all --backend both` | 363/363, 108초(다른 작업 부하) |
| 감사(Claude opus) | 오라클·하네스 거짓 음성 경로 없음. 필수 2(requires에 사용자 타입 비교 없음, 새 틀에 io 없음 — 생성기 범위 구멍)·권고 6 중 5 반영(오라클 인자 잎 검사는 rustc 빌드 오류로 드러나 남김). 고친 뒤 확인(Claude opus): 필수 0, 권고 7 중 늘 거절되던 두 변형(option_tap arg, tmatch Hit 전용)만 고침 → 표본 14/14 검증 통과, 시드 57 통과 212 실패 0(38초) |

- 컴파일러는 바꾸지 않아 bench 성능·변이 전체·g1은 돌리지 않았다.
- 남김: ~~퍼저가 뒷단마다 vowc를 따로 불러 LLVM 증명 빌드가 검증을 한 번 더 돈다~~(12절에서 없앰). requires 비교의 i128 초과 입력은 경계 requires 때문에 드물다. 일부 비교 requires(e2·qval·항상 참인 구조체 `==`·`Some(x)`)는 입력 힌트가 위반 값을 잘 못 만든다(확인 감사 권고, 남김).

## 12. 퍼저의 LLVM 증명 빌드 재검증 없애기 (2026-11-10)
1. **문제**: 퍼저(`bench/fuzz/run.py`)가 뒷단마다 vowc를 따로 불러, 검증 통과 프로그램의 LLVM 빌드(`prep_llvm`의 `--backend llvm --rust-bindings`)가 phase_a에서 이미 한 z3 검증을 한 번 더 돌았다.
2. **고침**: vowc에 숨은 시험 옵션 `--also-llvm LL RS`(`vowc/vowc.py`, `--contract-budget`처럼 SPEC 밖·도움말에 없음). Rust 뒷단에서만 받고, 같은 파싱·검사·검증 한 번으로 Rust 출력과 LLVM IR·bindings를 함께 쓴다. "이미 검증됨"을 믿어 주는 옵션은 검증 안 된 프로그램을 증명 모드로 내보내는 길이 되므로 고르지 않았다. 검증이 실패하면 파일을 하나도 쓰지 않고, 모든 출력 텍스트를 만든 뒤에 파일을 쓴다(생성기 내부 오류면 이번 호출의 출력이 남지 않음). OUT·LL·RS가 겹치거나 `--backend llvm`과 함께 주면 사용법 오류(exit 2). 하네스는 phase_a의 두 호출(`--no-verify`, 기본)에 이 옵션을 붙이고, 호출 전에 출력 경로를 지우며, `prep_llvm`은 vowc를 부르지 않고 그 파일만 clang에 넘긴다. `llvm-proof` 파일은 status가 `verified`일 때만 쓴다(아니면 `harness_error`).
3. **검증기·코드 생성은 바꾸지 않았다**(옵션과 출력 경로만). 두 생성기가 `prog`를 바꾸지 않음은 감사가 코드로 확인했고, 출력이 따로 부른 것과 바이트까지 같음은 새 시험이 확인한다. 그래서 bench 성능·변이 전체·g1은 돌리지 않았다.
4. **새 시험** `tests/cli_also_llvm.py`(따로 실행, run_all 밖): 예제×3모드 바이트 동일, must-reject는 exit 1·파일 없음·진단 같음, 사용법 오류 5가지(exit 2·파일 없음), 퍼저 생성 프로그램 40개×2모드. 진단은 (stage, code, line, col)만 비교한다. 같은 vowc 호출을 되풀이해도 z3 반례 값이 달라지는 일이 있어서다(4번 중 1번, 기존 동작).

| 확인 | 결과 |
|---|---|
| `tests/cli_also_llvm.py` | 185/185, 3번 연속, 약 7초 |
| 회귀 `run_all --backend both` | 363/363, 106초 |
| 퍼징 시드 56 전·후(1쌍째, 후 측정 중 감사가 같이 돎) | 실패 0, 통과 808·입력 6,550·실행 25,720 같음. 벽 232→200초, CPU(user+sys) 805→645초 |
| 퍼징 시드 56 전·후(2쌍째, 연달아 혼자) | 같은 결과. 벽 291→264초(생성+검증 65→75, 빌드 98→50), CPU 876→671초 |
| 감사(Claude opus) | 필수 0. 검증 실패·시간 초과·옛 파일·replay·거부 표본 경로 모두 안전. 권고 6 중 4 반영(LLVM 생성기 오류 상세에 `rust+llvm`·출력 끝, 라이브러리 호출에서 llvm 뒷단+also_llvm 거부, 문서 표현, 시험 보강). 대소문자만 다른 경로 비교는 기존 `--rust-bindings`와 같은 한계라 남기고, 빌드 안 할 후보까지 LLVM을 만드는 비용은 호출 하나를 없앤 이득보다 작아 남김. 고친 뒤 확인(Claude opus): 필수 0. 진단 비교는 (stage, code, line, col)의 순서 있는 목록이라 키 집합보다 엄격하고, 뺀 message·fix는 `verify_unknown` 말고는 code에 따라 정해져 잃는 정보가 거의 없다. 권고(message·fix도 비교, 거부 경로 stderr 비교)는 남기고 안 쓰는 변수만 지움 |

- 시간: CPU 시간이 두 쌍 모두 20% 넘게 줄었다. 벽시계는 같은 맥의 다른 작업 부하로 흔들려(같은 코드의 실행 단계가 81~138초) 줄어든 폭이 9~14%로만 보인다. LLVM 생성은 생성+검증 단계로 옮겨 가 그 칸은 늘고 빌드 칸은 준다.
- 후보 수 1,519/1,520 차이는 스트리밍 제출이 멈추는 시점의 꼬리(거절 1개)이고 빌드 대상은 같다.
- 바뀐 실패 분류: LLVM 생성기 내부 오류는 이제 phase_a에서 `internal_error`로 잡혀 그 프로그램 전체가 빠진다(예전엔 llvm 모드만 `build_error`). 실패로 저장되는 것은 같다.

## 13. M3 = C4 첫 묶음: 설계 확정 (2026-11-10)
1. **산출물**: `docs/M3_C4_SPEC.md`(396줄, 확정·설계 논쟁 반영). 코드는 바꾸지 않았다(전체 회귀 생략).
2. **조사**(웹·커뮤니티, 코드): 언어 Rust(Go는 z3·LLVM 모두 cgo라 정적 링크·크로스 빌드가 더 나쁨). z3 크레이트 `=0.22.0` `vendored` + `z3-src =503.3.0`(z3 `gh-release`는 5.3.0 뒤 `libz3.a` 누락 신고 Z3Prover/z3#11266). LLVM은 `llvm-sys 221`(LLVM 22) `force-static`(`prefer-static`은 동적으로 조용히 넘어감), 첫 이식은 텍스트 IR 생성기를 그대로 옮기고 LLVM 라이브러리로 읽어 O2·객체 생성. 시스템 링커는 빌린다(Windows는 MSVC Build Tools 필요). Python판에 이미 비결정 순회 2곳(`check.py` 호출 그래프, `verify.py` havoc 집합) → 0A에서 정렬.
3. **시제품**(`Lair Outputs/.../spike`, 이 맥 arm64): z3 질의 + 텍스트 IR → `default<O2>` → 객체 → `cc` 링크 → 실행 성공.

| 확인 | 결과 |
|---|---|
| 정적 z3 실행 버전 | `5.3.3.0` = Python판 z3-solver 5.3.3.0 |
| 빌드 | cold 393초(대부분 z3 C++, LLVM은 Homebrew 설치본), 다시 빌드 6초 |
| 크기 | strip 105MB(모든 LLVM 대상 초기화) |
| 동적 의존 | macOS 기본 라이브러리 + Homebrew `libzstd`(배포 불가) → 배포 LLVM은 zstd·libxml2·zlib 끄고 직접 빌드 |

4. **설계 논쟁**(Codex): 지적 13개 모두 채택 또는 수정 반영. 큰 변경: 첫 구현 묶음을 위험 먼저로(0A 결정성 + 0B z3 실의무 시제품·SMT-LIB 대조 + 0C Python .ll을 LLVM 라이브러리로 객체화해 시험 장치의 clang 의존 먼저 떼기 + 0D Windows ABI 표본), CLI 기본값은 M3에서 유지(`--emit exe` 추가), Windows sret는 생성기가 대상별로 직접 출력, 비용 상한(150MB·CI cold 120분), 공개 순서 macOS arm64 → Linux → Windows → macOS x64. 반대 의견 중 "Rust 소스 뒷단 이식 폐기"는 받지 않고 M3 맨 뒤로 미뤘다(6단계 여러 언어 출력 계획과 기존 Rust 출력 시험 집계 때문).
- 검증 시간: 시제품 빌드 393초 한 번. 회귀·bench는 코드 변경이 없어 돌리지 않았다.

## 14. 이름 바꾸기 Vow → Pruv (2026-11-10)
같은 성격의 언어(vow-lang)가 있어 이름을 Pruv로 바꿨다(근거는 BLUEPRINT 머리·6절). 도메인 `pruvlang.org` 확보.

| 대상 | 처리 |
|---|---|
| 컴파일러 | `vowc/` → `pruvc/`, `vowc.py` → `pruvc.py`(git mv, 이력 유지), 사용법 문구 `pruvc.py` |
| 소스 파일 | `*.vow` 205개 → `*.pruv`, 풀이 폴더 `pruv_try1`·`pruv_agg`·`ref_pruv`·`solve/pruv` |
| 생성 코드·실행 지원 | 실행 오류 접두사 `pruv:`, 기호 `__pruv_body`·`pruv_abi_*`·`Pruv__Tagged`·`pruv_runtime_rust_allocator_v1`, 매크로 `PRUV_*`, `PruvError` |
| 언어 규칙 | 예약 이름 접두사 `vow_` → `pruv_`(생성 기호와 겹치지 않게 하는 규칙이라 함께 바꿈, must_reject 시험도 바꿈) |
| 시험·bench 장치 | 경로 상수·명령·임시 폴더 접두사·결과 키(`pruv_error`·`pruv_errors`, mutate 판정 `pruv`·`pruv_stage`·`pruv_code`) |
| 문서 | README·SPEC·BLUEPRINT·docs/M0~M3·bench/fuzz/README·PROBLEMS 본문 |
| 그대로 둔 것 | RESULTS 1~13절(머리에 대응표), `docs/research-2026-11.md`(당시 조사 기록, 머리에 메모), bench 결과 JSON(`mutants*.json`·`results_*vow*.json`·`g1/results_*.json`, 옛 키 `vow_stage` 등), `solve/` 입력 사본 SPEC·PROBLEMS(당시 작업자가 본 글, 머리에 메모), BLUEPRINT의 경쟁 언어 Vow(vow-lang) 언급 |

- 방법: git mv 뒤 살아 있는 파일 50개(BLUEPRINT 포함)에 대소문자를 지킨 단순 치환(`Vow`/`VOW`/`vow` → `Pruv`/`PRUV`/`pruv`). 'vow'가 영어 단어나 다른 뜻으로 쓰인 곳은 없었다(토큰 전수 확인).
- 검증: `run_all --backend both` 363/363(82초), `cli_also_llvm` 185/185(8초), 퍼저 seed 1110 30개 실패 0(8초). 생성 코드는 기호 이름과 오류 문구만 바뀌고 의미는 같아 bench 성능·변이 전체·g1은 돌리지 않았다.
- 감사(Claude opus): 필수 1건 — `bench/mutate.py`가 확장자를 앞 4글자로 떼어 `.pruv`에서 문제 번호가 `p01.`이 되어 변이 시험이 멈춤(시험이 안 덮는 경로) → `os.path.splitext`로 고치고 p02 하나로 실행해 확인(변이 7개 정상, 122초). 권고 반영: `solve/` 입력 사본 본문 되돌림, BLUEPRINT 43행 "당시 이름" 표기, 코드 블록 정렬, 이 절의 키·보존 목록 보완.
- 주의: 새 결과 JSON의 키가 `pruv_*`라 옛 결과 JSON(`vow`·`vow_*`)과 직접 비교하는 스크립트를 쓰면 키를 맞춰야 한다.

## 15. M3 = C4 첫 구현 묶음 0A~0D+T (2026-11-11)
설계 `docs/M3_C4_SPEC.md` 4·5·6·7절의 첫 묶음. Python 정본은 0A의 두 줄만 바꿨다. 이 맥(arm64 10코어, Homebrew llvm@22 22.1.8, rustc 1.99.1)에서만 확인했다.

| 묶음 | 산출물 | 확인 결과 |
|---|---|---|
| 0A 결정성·기준 | `check.py:134` 호출 그래프·`verify.py:686` havoc 순회만 이름순 정렬(선언 순서 그대로), `tests/diff_py_adapter.py`(parse AST v1·check·trace·snapshot·seeds), 기준 스냅샷 `tests/baseline/py_0a/`(입력 220, manifest `cfbeae2f…`, z3 5.3.3.0) | hash seed 0·1·2·random: 고치기 전 220 중 24 다름(모두 SMT 순서), 고친 뒤 0. 고치기 전후 seed 0: 진단·판정 220 모두 같고 SMT 질의 순서만 16개 바뀜. 증명 시간·반례·재귀 첫 경로 변화 없음 |
| 0B 잠금·z3 시제품 | `pruvc-rs/` workspace(pruv-core·pruv-proof·pruvc), `Cargo.lock`, `rust-toolchain.toml` 1.99.1, `ci/m3/`(README·check_deps.sh·compare_spike.py), 표본 6개 | 의무 58개(집계 보조정리·재시도, Opt/Res, 사용자 struct/enum, havoc, 배열, 중첩 양화+patterns) 첫 시도·재시도 SMT-LIB 텍스트와 판정이 Python과 글자 단위로 모두 같음. `cargo build --release --locked` 성공, `cargo tree -d` 중복 없음 |
| 0C 객체·링크 도구 | `pruvc-ir-tool`(obj·runtime·link·undef), runtime.c 4변형 build.rs 내장 | `run_all --backend llvm --ir-tool` 222/222(clang 없이 객체화). i128 표본 출력 일치, 미해결 보조 기호 `__divti3`·`__modti3`는 macOS libSystem이 공급. 한글·공백 경로 링크 됨. 객체 최소 OS 11.0 고정 |
| 0D Windows sret 표본 | `tests/abi/`(대상별 wrapper .ll 5개, C 기준 ref.c, Rust extern 드라이버, check_abi.py) | 5/5: COFF x86-64 객체(llc·ir-tool 두 경로), verify, clang C 기준 서명(sret 첫 인자·align 8·void) 일치. **Windows 실행 ABI는 미확인(Windows CI 몫)** |
| T 차분 장치 | `tests/compiler_driver.py`, `tests/diff_compilers.py`(`--replay`), 기존 장치 5개에 `--compiler py\|rs`·`--compiler-path`, run_all `--ir-tool` | py 대 py 468 same. 미구현 응답은 통과로 세지 않고 종료 코드 3(`--allow-unimplemented`면 0). 실패 사례 저장·`--replay` 재현 확인 |

| 의존(정확 잠금) | 값 |
|---|---|
| z3 / z3-src / z3-sys | `=0.22.0` vendored / `=503.3.0` / `=0.14.1` (실행 버전 5.3.3.0) |
| llvm-sys / cc / tempfile / serde_json | `=221.1.2` force-static / `=1.11.1` / `=3.27.0` / `=1.0.154` |
| 빌드 | z3 cold 약 280초(첫 빌드가 컴파일 오류로 끝난 시점 기준, 오류 없는 cold 재측정 안 함), 코드만 바꾼 다시 빌드 수 초 |
| 크기(strip) | pruv-proof-spike 21MB, pruvc-ir-tool 37MB |
| 동적 의존 | spike: libc++·libSystem만(check_deps 통과). ir-tool: Homebrew `libzstd` → check_deps 실패(개발 LLVM 탓, 배포 LLVM 직접 빌드에서 뗄 일) |

- 0B에서 찾은 이식 함정(실제 검증기 이식에서 지킬 것): (1) z3py는 파이썬 반사 비교 규칙 때문에 `x >= IntVal(0)`을 `(<= 0 x)`로 낸다(오른쪽이 수 리터럴이면 반사 메서드). 파이썬 정수와의 비교(`in_range`, `nv.n >= 0` 등)는 뒤집지 않는다 → Rust `Ast::ge`는 반사 규칙, `*_i`는 그대로. (2) 출력 모드는 `Z3_PRINT_SMTLIB2_COMPLIANT`=2(작업자가 넣은 3은 범위 밖 enum transmute라 UB였고 식 출력이 빈 문자열이 되어 보조정리 중복 키가 모두 같아졌음). (3) z3py는 양화 qid/skid에 null 기호를 넘기는데 z3-sys 0.14.1은 이 인자를 NonNull로 묶어 같은 C 함수를 null 허용 서명으로 따로 선언. (4) z3 기본 오류 처리기는 stdout에 쓰고 exit(1) → 언어 거부와 구별되지 않아 abort 처리기로 바꿈.
- 0C에서 고친 것: LLVM 함수 이름 오타, macOS에서 SDK를 안 넘겨 `-lSystem` 링크 실패(`PRUVC_SYSROOT` 또는 `xcrun --show-sdk-path`).
- 검증(고친 뒤 마지막 실행): `run_all --backend both` 363/363, `cli_also_llvm` 186/186(`--backend` 생략 사례 1건 추가), 퍼저 seed 1111 30개 실패 0(13초), 변이 LLVM 81개(목록 83, 같은 줄 중복 2) `mutants8_m0_llvm.json`과 판정·단계·코드·시험 결과 모두 같음(287초, 결과 `bench/mutants9_0a_llvm.json`). 퍼저·변이는 감사 고침 전 실행이며 고침은 mutate의 시간 제한 되돌림·주석뿐이라 다시 돌리지 않았다.
- 감사(Claude): 필수 5건 — mutate에 생긴 300초 제한(되돌림), mutate crash 정의 확대(유지·기록), diff_compilers가 미구현만 있을 때 종료 코드 0(→3), ir-tool 호스트 triple이 LLVM 기본값이라 최소 OS가 빌드 머신을 따름(→대상 표 triple), check_deps가 Intel Homebrew 경로를 놓침(→추가). 권고 반영: z3 오류 처리기, Datatype 출력 배열 null 검사, Rust havoc 내부 정렬, 반례 값 차이는 diff로 세지 않음, Linux `--sysroot=`, xcrun 결과 캐시, 임시 폴더 정리.
- 고친 뒤 확인(Claude): 필수 5건 모두 해결, 새 필수 없음. 권고 4건 중 mutate crash 정의 문구를 실제 정의에 맞추고, diff_compilers 미구현 판별에서 경로에도 걸리는 `todo`를 뺌(`--allow-unimplemented` 때 거짓 통과 가능성). 나머지(실행 파일 이름 치환이 한쪽에만 적용돼 거짓 실패 가능, check_deps 모서리 사례)는 남김.
- 남은 일: Linux·Windows·macOS x64에서 빌드·i128 보조 기호·정적 의존 확인, Windows 실행 ABI(CI), 배포 LLVM 정적 직접 빌드, ir-tool을 bench 하니스·퍼저 객체화에도 연결, 오류 없는 z3 cold 빌드 시간 재측정. 다음 단계는 1 파서 이식.

## 16. M3 = C4 1단계: 파서 이식 (2026-11-11)
설계 `docs/M3_C4_SPEC.md` 4절 1단계. `vast.py`·`vparser.py`를 `pruvc-rs/crates/pruv-core/src/{ast,diagnostic,lexer,parser}.rs`로 옮기고, 시험 스키마 출력 `dump.rs`·Python 호환 JSON `pyjson.rs`·Python `repr()` 흉내 `pyrepr.rs`(+생성 표 `pyrepr_table.rs`, 생성기 `pruvc-rs/tools/gen_pyrepr_table.py`)와 시험 바이너리 `pruv-parse-dump`를 더했다. 외부 크레이트 없음. Python 정본은 바꾸지 않았다. 이 맥에서만 확인했다.

| 확인 | 결과 |
|---|---|
| `tests/diff_parse.py`(새 도구) 기본 입력 | 2263건 중 2261 바이트 동일, 다름 0. must_reject 81·examples 7·runtime 72·bench 10·경계 `tests/parse_edge/` 50·바이트 경계 123·퍼저 seed 41·56·57×200·변형 1320 |
| 넓힌 입력(seed 1~8×500, 변형 30) | 10943건 중 10941 동일, 다름 0 |
| 제외 2건 | 괄호 2000겹·단항 `-` 3000개: Python이 RecursionError로 죽어 비교 대상 없음(Rust는 1GB 스택 스레드로 처리). 알려진 허용 차이 |
| 대응 범위 | 노드 33/33, parse 오류 code 5/5(bad_char·bad_int·reserved_name·syntax·unsupported_type), 오류 문장 형태 28종. `9223372036854775807`·`-9223372036854775808`·20자리 넘는 수·음수 큰 수·`--5` 접기 모두 경계 묶음에 있음 |
| 회귀 | `run_all --backend both` 363/363, `cli_also_llvm` 186/186, `cargo test -p pruv-core` 단위 13 |

- 이식에서 맞춘 Python 동작: `open().read()`의 universal newline(`\r\n`·단독 `\r` → `\n`)을 lexer 전에 적용, line/col은 코드 포인트 단위, BOM은 `bad_char '﻿'`, 정수는 부호+정규화 십진 문자열(자릿수 제한 없음, 음수 접기는 `-` 토큰 위치), bad_char 문장의 `%r`은 Python 3.9.6(Unicode 13.0) `str.isprintable` 표로 `\x`/`\u`/`\U` 선택, 오류 JSON의 line/col은 수·AST의 정수와 위치는 문자열.
- 차분에서 찾은 것 1건: 어댑터 `ser()`는 Quant의 `kind` 필드("forall"·"sum" 등)가 노드 이름 "Quant"를 덮어쓴다(파이썬 dict 덮어쓰기). 기준 스냅샷 pruv-ast-v1에 이미 들어 있는 동작이라 Rust `dump.rs`가 같게 따랐다. 스키마를 고치려면 v2로 올려야 한다.
- 잘못된 UTF-8·읽기 실패: Python 어댑터는 예외로 죽고 Rust는 `{"adapter_error": "decode"|"io"}` 줄을 낸다. 비교 도구가 이 대응을 정한다. Python 기준은 시스템 기본 인코딩(이 맥 UTF-8)으로 읽으므로 Windows 기준 출력은 확인하지 않았다.
- 감사(Claude Opus): 바이트 차이 결함 없음(작업자가 경계 241·변형 3000·생성 1500·큰 CRLF/CR 18·repr 표 전 코드 포인트 대조). 필수 1건 — `peek`/`next`가 토큰을 매번 복제(선형이지만 상수배 낭비; 감사 실측 문 200만 개 0.92초, 같은 입력 Python 27.6초) → `peek`는 참조, `expect`는 소비만(토큰이 필요한 4곳만 복제), 버리는 소비는 `bump`. 권고 반영: 연산자 매칭의 임시 문자열 제거, 안 쓰는 함수·낡은 주석 정리, `pruv-parse-dump`가 줄마다 바로 써서 한 파일의 스택 넘침으로 앞 줄까지 잃지 않게 함. 남긴 권고: 공개 `parse`에 깊이 상한 없음(호출자가 큰 스택을 잡아야 함, I 단계 CLI에서 정함), 개행 정규화·`Vec<char>`의 메모리 약 6배, 오류 형식 크기(`Box` 미적용), 덤프의 JSON 나무 생성.
- 고친 뒤 확인(Claude Opus): 통과. `expect_tok` 4곳이 Python에서 `expect` 반환값을 쓰는 4곳과 같고, 소비 순서·오류 위치·연산자 우선순위·새 panic 없음을 원본과 줄 단위로 대조. 고친 뒤 `cargo test` 13 통과, `diff_parse` 2263·10943건 다름 0(메인 실행).

## 17. M3 = C4 2단계: 검사기 이식 (2026-11-11)
설계 4절 2단계. `typeinfo.py`·`check.py`를 `pruvc-rs/crates/pruv-core/src/{typeinfo,check}.rs`로 옮기고(외부 크레이트 없음), 시험 바이너리 `pruv-check-dump`(어댑터 `check`와 같은 typed AST + type_table JSON)를 더했다. `tests/diff_parse.py`에 `--mode check`, 경계 입력 `tests/check_edge/`(오류 77·성공 12)를 더했다. Python 정본은 바꾸지 않았다. 이 맥에서만 확인했다.

| 확인 | 결과 |
|---|---|
| `diff_parse.py --mode check` 기본 입력 | 2836건 중 2834 바이트 동일, 다름 0(제외 2건은 1단계와 같은 깊은 중첩의 Python RecursionError). 성공 964건 모두 type_table 같음(타입 2개 이상 68건) |
| 넓힌 입력(seed 1~8×500, 변형 30) | 13652건 중 13650 동일, 다름 0, 성공 5168건 |
| 대응 범위 | 검사 오류 code 45/45(도달 불가 `internal` 제외), stage type·effect 둘 다, ty 내장 6종+사용자 타입 24종 |
| 회귀 | `run_all --backend both` 363/363, `cli_also_llvm` 186/186, `diff_parse` parse 모드 2263 다름 0, `cargo test -p pruv-core` 20 |

- 감사(Claude Opus): 바이트 차이 결함 없음(미대조였던 code 경로 전부를 포함해 약 110개 입력을 두 쪽에 넣어 대조). 필수 2건 — enum 변형·필드 이름 중복 검사가 `Vec::contains`라 O(n²)(필드 10만 개에서 Python 0.92초, Rust 9.2초) → `HashSet`으로 바꿔 필드 10만+변형 10만 입력 0.16초. 남긴 권고: 블록마다 scope 복제(Python `dict(scope)`와 같은 차수지만 항목마다 String 할당), 항 100만 개 덧셈 사슬에서 1GB 스택도 넘침(Python은 항 400개에서 RecursionError라 대조 범위 밖), 식마다 타입 문자열 할당, TypeDecl 이중 복사.
- 고친 뒤 확인(Claude Opus): 고친 2건은 Python과 같은 동작(이름 검사 → 중복 검사 → 넣기, 오류 위치·문장 같음)으로 통과. 같은 꼴의 목록 포함 검사가 match 팔(`need`·`seen`), 구조체 리터럴(`declared`·`given`), 타입 의존(`deps`)에 남았으나 Python도 같은 자리에서 list를 써 차수가 같으므로 권고로 남긴다(구조체 리터럴 중복 이름은 "두 번 이상 나온 이름 중 맨 앞"이라 고칠 때 개수 사전을 써야 결과가 같다).

## 18. M3 = C4 3단계: 검증기 이식 (2026-11-11)
설계 4절 3단계. `verify.py` 전체(Model, 상태·배열, fresh·wf·rebuild, prove·재시도·seen, cex·fmt_val, ev·dom·집계 보조정리·call·ensures, exec·havoc·loop·run, verify_program)를 0B 시제품 위에 `pruvc-rs/crates/pruv-proof/src/{lib,model,obligation,symbolic,sys}.rs`로 옮겼다. `pruv-proof`가 `pruv-core`를 path 의존으로 쓴다(외부 의존 추가 없음). 시험 바이너리 `pruv-trace-dump`(어댑터 `trace`와 같은 JSON), 차분 도구 `tests/diff_trace.py`(입력마다 두 판을 새 프로세스로). 공개 CLI는 아직 없다(I 단계). Python 정본은 바꾸지 않았다. 이 맥에서만 확인했다.

| 확인 | 결과 |
|---|---|
| `diff_trace.py` (seed 41·56·57·1·2 × 150 포함) | 932건: SMT-LIB 텍스트·판정·오류(code·line·col·message·fix) 모두 같음. 849건은 바이트 동일, 83건은 반례 값만 다름 |
| 의무 규모(정본 기준) | 의무 9649(skipped 371), 시도 9578, 보조정리 재시도 300, sat 1466·unsat 8112·unknown 0 |
| 반례 | 다른 반례 148개(83건 안) 모두 키·모양(스칼라/배열/구조체 이름) 같음. 값만 다름 |
| 시제품 대조 `ci/m3/compare_spike.py` | 의무 58/58 SMT·판정 같음, z3 5.3.3.0 두 판 같음 |
| 회귀 | `run_all --backend both` 363/363, `cli_also_llvm` 186/186, `cargo build --release --locked`(workspace), `cargo tree -d` 중복 없음, `cargo test -p pruv-proof` 통과 |

- 차분에서 찾아 고친 것: z3py 반사 비교 규칙을 수 리터럴(ArithRef⊃IntNumRef)만 보던 것을 클래스 계층으로 넓혔다. `BoolVal(False) == ForAll(..)`은 오른쪽이 BoolRef의 하위 클래스 QuantifierRef라 반사 메서드가 먼저 불려 `(= forall false)`가 된다(bench p03). 작업자 코드의 컴파일 오류 1건(`Sat` 열거 참조)도 고쳤다.
- 반례 값 차이: 같은 SMT 텍스트인데 z3가 고르는 모델이 다르다. 프로그램 전체를 컨텍스트 하나로 바꿔도 그대로여서 되돌렸다(함수마다 비-rc 컨텍스트, 함수가 끝나면 통째로 버림). 원인은 z3py의 rc 컨텍스트(AST 번호 재사용)와의 차이로 추정하며 확인하지 않았다. 설계 5절대로 반례는 바이트 동일을 요구하지 않는다. 같은 질의의 모델이라 질의 기준으로는 유효하다고 보지만, 독립 oracle로 위반을 다시 평가하는 장치는 아직 없다(이정표 관문 몫).
- 감사(Claude Opus): 반례(Opt/Res/사용자 타입/배열 앞 8개/havoc 지역)·`verify_unknown`·relaxed `_note`·반사 비교(ne·Datatype·Option·Result·양화식)·FIX 표 13쌍을 모델이 하나로 정해지는 작은 입력 9묶음으로 대조해 반례 문자열까지 바이트 동일. 필수 1건 — `pruv-trace-dump`가 읽기·UTF-8 해독 실패에서 `adapter_error`를 내 Python 어댑터(internal_error)와 달랐다 → `pruv-core/src/pyio.rs`(Python `UnicodeDecodeError`·`OSError` 문장 재현, 표본 7개 대조)로 같은 internal_error를 내게 고침. 권고 반영: 덤프 바이너리의 패닉은 exit 3, `diff_trace`에 Python 재귀 한도 범주(py_recursion). 남긴 권고: z3 오류 처리기 abort(검사 통과 입력에서 닿는 경로 없음), 닿지 않는 내부 실패 문구, `Env` 선형 탐색과 문장마다 env 복제(경로 폭발 함수에서 상수배), `MODEL_SEQ` thread_local, 비-rc 컨텍스트 메모리.

## 19. M3 = C4 4단계: LLVM 출력·공통 함수 이식 (2026-11-11)
설계 4절 4단계. `llvmgen.py`(Mod·FnGen·entry_of·cdivrem·gen_llvm)를 `pruv-core/src/llvmgen.rs`, C-ABI wrapper(Words·abi_of)를 `abi.rs`, Rust 바인딩(gen_bindings)을 `bindings.rs`, `codegen.py`의 공통 함수(rty·cty·conv·emit_public_types·show·match_sorted_requires·rstr)를 `emit_common.rs`로 옮겼다(합계 2875줄, 외부 크레이트 없음). 시험 바이너리 `pruv-llvm-dump`, 차분 도구 `tests/diff_llvm.py`. 대상별 Windows wrapper 직접 출력은 6단계 몫이라 아직 없다(지금은 Python과 같은 기존 IR). 이 맥에서만 확인했다.

| 확인 | 결과 |
|---|---|
| `diff_llvm.py` 기본(입력 1636 × 모드 4 + budget 4) | 6548 사례 모두 IR·바인딩 바이트 동일(성공 3320, 언어 오류 3228, internal 0) |
| 넓힌 입력(seed 1~8×500, 변형 10) | 6849 입력, 27400 사례 모두 동일(성공 17532) |
| 실제 CLI 대조 | `pruvc.py --backend llvm` 이 쓴 .ll·.rs 와 bench p03 바이트 동일 |
| 대응 범위 | LLVM 명령 28종, wrapper 4244, nsw(증명 모드) 1190 사례, with.overflow(안전 모드) 1658, 사용자 타입 488, i128 cdiv 1248, requires 검사 3320 |
| 회귀 | `run_all --backend both` 363/363, `cli_also_llvm` 186/186, `cargo test -p pruv-core` 32, workspace `--locked` 빌드 |

- 작업자 코드는 셋으로 나눠 동시에 썼고(본체 / 바인딩·공통 함수 / 차분 도구) 처음 빌드부터 컴파일 오류 없이 첫 대조에서 모두 같았다.
- 감사(Claude Opus): 검사를 통과한 입력에서 Python과 다른 출력 없음(빈 struct, 필드 없는 변형만 있는 enum, 중첩 사용자 타입 안 Option/Result, sorted 패턴 변형, i64·i128 경계 × budget 7개, 입력 해독 경로를 직접 대조). 필수 2건 — 구조체 리터럴 값 모음(`mk_struct`)과 사용자 enum match 바인더(`user_match`의 retain)가 Python 선형 대비 제곱(필드 32000개 2.14초) → 해시맵·retain 삭제로 고쳐 같은 입력 0.72초(대부분 검사기 시간), 고친 뒤 `diff_llvm` 6548 사례 다름 0. 남긴 권고: 검사기가 막아 닿지 않는 경로의 내부 오류 문구(KeyError·`%r` 흉내), `cty`/`conv` unwrap(호출자는 시험뿐), `words` 중복 구현, 변수 조회·문자열 상수의 복제, 계약 문구 `show`의 깊은 사슬 문자열 복사(Python과 같은 차수), 시험 바이너리 `--budget` 범위 검사 없음(CLI는 검사).
- 고친 뒤 확인(Claude Opus): 통과. 구조체 리터럴은 소스 순서로 평가하고 같은 이름은 나중 값, 출력은 선언 필드 순서(해시맵 순회가 출력에 안 들어감), match 바인더는 `run_block`이 차례로 넣어 나중 값이 이겨 Python `dict.update`와 같다.

## 20. M3 = C4 5단계: Rust 판 `pruvc` 명령과 단독 실행 파일 (2026-11-11)
설계 4절 5단계(객체·링크 통합)에 I 단계의 CLI 부분(`pruvc/src/{main,cli,driver}.rs`)을 앞당겨 붙였다. 실행 파일을 시험하려면 명령이 먼저 있어야 해서다. Python `pruvc.py`와 같은 옵션·출력·종료 코드에 설계 3절의 `--emit exe|obj|ll|rs`·`--target`·`-mcpu=`를 더했다. `--emit exe`는 진입점(`fn main() -> ()`, 매개변수 없음)을 검사하고 같은 모듈에 C `main` shim을 붙여 LLVM 라이브러리로 객체를 만든 뒤 내장 malloc 런타임과 시스템 링커로 묶는다(IR 컴파일용 clang 없음). `--backend rust`(Rust 소스 출력)는 7단계라 아직 exit 2(미구현). 4개 플랫폼 CI·배포 LLVM 정적 빌드는 아직(I 단계). 이 맥에서만 확인했다.

| 확인 | 결과 |
|---|---|
| `diff_compilers.py --backend llvm`(두 CLI를 입력마다 새 프로세스로) | 234 사례 모두 same(종료 코드·stdout JSON·.ll·바인딩 바이트) |
| `run_all.py --compiler rs --backend llvm` | 222/222(Rust 판이 쓴 .ll을 객체화해 Rust 드라이버로 실행) |
| `tests/standalone/run.py`(새: 시험 29개, 50 사례) | 모두 same. Rust 판 단독 실행 파일과 기준(Python 판 → Rust 소스 → rustc)의 종료 코드·stdout·`pruv:` 줄 비교. 증명·안전·trust·budget 모드, 넘침·0 나누기·범위 밖·alloc 음수·requires 위반(exit 101), 30만 번 할당 반복, 공백·한글 경로, 진입점 오류 2, 거부 2 |
| 컴파일 시간(bench 10 + examples 7, `--backend llvm`, z3 포함) | Python 1.63초, Rust 0.88초 |
| 실행 파일 | `pruvc` 58MB(strip), 동적 의존에 Homebrew `libzstd`(개발 LLVM 탓, 배포 LLVM 직접 빌드에서 뗄 일 — 0B 기록과 같음) |

- 시험 프로그램 29개 중 3개(s03·s09·s11)는 작업자가 증명할 수 없는 계산을 써서 Python 판에서도 검증이 실패했다. 범위 조건·출력식을 고쳐 의도대로 만들었다.
- `pruv-core/src/pyio.rs`를 CLI 입력 읽기에도 써서 읽기·해독 실패 문장이 Python 판과 같다.
- 감사(Claude Opus): 필수 3건 — (1) 출력 파일 쓰기·복사 실패의 internal 문장이 Python과 달랐다 → `pyio::io_error_message`로 `[Errno 2] No such file or directory: '…'`(두 판 같음 확인). (2) 괄호 30만 겹 같은 깊은 입력에서 1GB 스택을 넘어 JSON 없이 abort(134) → 파서에 AST 깊이 한도 50,000(재귀와 왼쪽으로 쌓이는 이항·접미 사슬을 함께 셈)을 두고 넘으면 Python RecursionError처럼 internal_error `maximum recursion depth exceeded`, exit 3. 괄호 4만 겹·덧셈 4만 5천 항은 통과, 30만·300만 겹과 100만 항은 exit 3 확인. Python은 약 1000 단계에서 멈추므로 대조 범위 밖이고 `diff_parse` 2263·2836건은 그대로 다름 0. (3) 사용법 오류의 stdout usage 줄이 새 옵션 때문에 Python과 달랐다 → stdout은 Python과 같은 줄(실행 파일 이름만 다름), 새 옵션 줄은 stderr로. 권고 반영: `link_failed` 진단에 링커의 `error`/`ld:` 줄을 요약. 고친 뒤 확인(Claude Opus): 한도 아래 결과·오류 위치 불변, 괄호 49,990겹은 검증 포함 LLVM 경로 통과. 문제 1건 — `else if` 사슬 재귀가 깊이 셈 밖이라 100만 개에서 스택 넘침(exit 134) → 그 재귀도 세게 고쳐 exit 3 확인. 남긴 권고: argparse의 공백 든 토큰·유니코드 숫자·`--t` 약어 모호(새 `--target` 때문), `-mcpu` 대상별 검증 없음(LLVM 경고 뒤 계속), obj/exe 출력의 원자적 쓰기, 닫힌 stdout에서 println 패닉, 런타임 객체의 macOS 최소 OS 경고, 비UTF-8 argv 거부, 확장자 없는 입력의 `-o` 생략 문장.

## 21. M3 = C4 6단계: Windows x64 대상별 wrapper 직접 출력 (2026-11-11)
설계 7절 "Windows x64 대상별 wrapper". `pruv-core/src/abi.rs`에 `AbiTarget{SysV, WinX64}`, `llvmgen.rs`에 `gen_llvm_for`를 더했다. Windows x64 대상이면 Option/Result를 돌려주는 외부 `pruv_abi_*`만 처음부터 `void` + 첫 숨은 `ptr sret({ i64, i64 }) align 8`로 출력하고(entry 결과의 tag를 zext해 두 슬롯에 저장), IR 맨 앞에 datalayout·triple을 붙인다. 배열 반환·사용자 타입 out 포인터, Option/Result 인자 펼침, 내부 body/entry는 그대로. Rust 바인딩은 대상과 무관(`-> Pruv__Tagged` 값 반환 extern, MSVC C ABI가 숨은 인자를 만든다). 기본(macOS·Linux) 출력은 바뀌지 않는다. `pruvc --target x86_64-pc-windows-msvc`가 이 경로를 쓴다.

| 확인 | 결과 |
|---|---|
| `tests/abi/check_generated.py`(새, 소스 8개) | 모두 통과: 헤더 두 줄, `opt -passes=verify`, wrapper 모양(Option/Result만 sret 하나, 나머지 sret 없음, 바인딩 `Pruv__Tagged` 판정과 일치), `--emit obj` COFF x86-64·`pruv_abi_*` 정의 기호, 같은 소스의 호스트 출력에 triple·sret 없음, clang이 `ref.c`에서 만든 C 2×int64 반환 서명과 같음(인자 0·1·5개) |
| 0D 표본 `check_abi.py` | 5/5 통과 |
| 기본 출력 불변 | `diff_llvm` 6548, `diff_compilers --backend llvm` 234 모두 Python과 바이트 동일, `cargo test -p pruv-core` 36 |

- 감사(Claude Opus): 설계 표의 함수 경계 모두 맞음(섞인 인자 `g(c: C, a: [i64], o: Option<i64>, b: bool) -> Option<i64>`도 sret 맨 앞 하나), datalayout이 clang 22의 x86_64-pc-windows-msvc 값과 같음. 필수 1건 — Windows 호스트에서 `--target` 없이 `--emit ll`이면 SysV 모양이 나올 코드 경로(대상 None → SysV) → `--target`이 없으면 호스트 대상으로 ABI를 고르게 고침(비Windows 호스트의 Python 바이트 대조는 그대로). 남긴 권고: 개발 도구 `abi_lower`의 `--input-abi target` 서명 미검사(Python 대조 뒤 제거 예정), datalayout 상수를 TargetMachine 값과 비교하는 시험, 표본 확대(enum 반환·2인자 C 기준), rustc MSVC extern IR 실측(이 맥에 Windows rust-std 없음 — Win64 C ABI 규칙으로 판단).
- **Windows에서 실제로 실행해 맞물리는지는 이 맥에서 확인할 수 없다.** Rust extern 호출·C 호출자와 링크해 Some/None·MIN/MAX·인자 0·1·5개·반복 호출·구조체 안 Option·배열 반환을 실행하는 것은 Windows CI(I 단계) 몫이다.

## 22. M3 = C4 7단계: Rust 소스 출력 이식 — 두 판이 기존 시험 전부를 같게 통과 (2026-11-11)
설계 4절 7단계. `codegen.py`(Gen·gen_rust·SAFE/CONTRACT prelude)를 `pruv-core/src/codegen.rs`로 옮기고(공통 함수는 4단계 `emit_common.rs` 재사용), 시험 바이너리 `pruv-rust-dump`·차분 도구 `tests/diff_rust.py`를 더했다. `pruvc`의 기본 출력(`.rs`)과 `--also-llvm`이 이제 Rust 판에서도 돈다(모든 텍스트를 만든 뒤에 파일을 쓰는 Python 원칙 그대로). 이로써 Rust 판 `pruvc`가 Python 판의 모든 출력 종류를 낸다. 이 맥에서만 확인했다.

| 확인 | 결과 |
|---|---|
| `diff_rust.py`(입력 1636 × 모드 4 + budget) | 6548 사례 모두 .rs 바이트 동일(첫 대조부터) |
| `run_all.py --compiler rs --backend both` | **363/363**(Rust 판 컴파일러로 기존 회귀 전부) |
| `cli_also_llvm.py --compiler rs` | **186/186** |
| `diff_compilers.py --backend both` | 468 사례(rust 234·llvm 234) 모두 same, 미구현 0 |
| 퍼저 `bench/fuzz/run.py --compiler rs` | seed 41·56·57 각 40 프로그램 실패 0 |
| 변이 `bench/mutate.py --backend llvm --compiler rs` | 83개(81 고유) 판정·단계·코드·시험 결과가 `mutants9_0a_llvm.json`(Python 판)과 모두 같음(299초) |
| 기존 차분 재확인 | `diff_parse` parse 2263·check 2836, `diff_llvm` 6548 모두 다름 0, `cargo test -p pruv-core` 39 |

- 감사(Claude Opus): 드문 조합 5묶음(계약 미러의 중첩 struct·enum·Option·Result 필드, 빈 struct, sorted i·i+1 변형과 비변형 7종, i64 최솟값·`-0`·`007`, unit·배열 반환+io, budget 1·999·1000·2^62)이 모든 모드에서 바이트 동일, panic 지점 없음, `--also-llvm` 쓰기 순서·실패 시 부분 출력이 Python과 같음. 필수 1건 — 구조체 리터럴 필드 값 조회가 필드마다 뒤에서 훑어 제곱(Python은 dict) → 리터럴마다 해시맵을 한 번 만들게 고침(필드 8만 개 전체 5.1초, 대부분 Python과 같은 차수인 검사기 몫). 남긴 권고: 계약 쪽 필드 선언 복제, 닿지 않는 Err 문장의 `{:?}` 표기, Python `codegen.py` docstring의 "필요한 prelude만" 문구가 실제(통째로 냄)와 다름, `--also-llvm`도 Windows 대상이면 sret 형태.
- 남은 M3 일(I 단계): 4개 플랫폼 CI(Windows 실행 ABI 포함), 배포 LLVM 정적 직접 빌드(Homebrew `libzstd` 의존 떼기), 독립 exe 관문, 개발 도구 `abi_lower`·`--input-abi` 제거, 넓힌 퍼저 seed·bench 성능 측정.

## 23. M3 = C4 I 단계 일부: Windows x64 실행 ABI CI (2026-11-11)
사용자 결정(비공개 저장소 비용): 4개 플랫폼 배포 빌드 없이 **Windows 실행 확인만 CI**. `.github/workflows/windows-abi.yml`(windows-latest 1대, 20분 제한, 관련 경로가 바뀐 main push와 수동 실행만). 컴파일러는 Windows에서 빌드하지 않는다: 맥에서 Rust 판 `pruvc --target x86_64-pc-windows-msvc`로 만든 IR·바인딩·Rust 드라이버와, 같은 소스를 맥 호스트 대상으로 실행한 기대 stdout을 `tests/abi/winci/out/`에 커밋하고(`prepare.py`, `--check`로 재생성 결과 동일 확인), 러너가 clang으로 객체화·rustc(MSVC)로 링크·실행해 비교한다(`run_windows.py`).

| 확인 | 결과 |
|---|---|
| 첫 실행(run 42918981038) | 실패: 러너 콘솔 cp1252에서 한글 표 출력 UnicodeEncodeError → 워크플로에 `PYTHONUTF8=1`·`PYTHONIOENCODING=utf-8` |
| 둘째 실행(run 42919117779, 약 40초) | **12/12 통과**: 소스 11개 stdout이 맥 기대 출력과 한 글자도 다르지 않음 + C 호출자(clang, sret 하강)가 `pruv_abi_f0/f1/f5` 반환값 6개와 10만 번 반복 확인 |
| 덮은 경계 | Some/None·Ok/Err, i64 MIN/MAX payload, 인자 0·1·5개와 sret+6워드(스택 전달), 함수마다 10만 번 반복 호출, 구조체 안 Option 인자·반환, 배열 반환, Option/Result 인자·반환 왕복 |
| 러너 도구 | clang 20.1.8(우리 IR은 LLVM 22 출력이지만 객체화됨), rustc 1.99.1(LLVM 23) |

- 이로써 설계 7절의 "Windows 실행 ABI는 Windows CI 성공 필수" 관문을 통과했다. 범위는 외부 wrapper·바인딩의 실행 ABI이고, Windows에서 Rust 판 `pruvc` 자체를 빌드·실행한 것은 아니다(배포 빌드는 하지 않기로 함).
- M3에서 남은 일(사용자 결정 필요 또는 미룸): 4개 플랫폼 배포 실행 파일(LLVM 정적 직접 빌드, Homebrew `libzstd` 의존 떼기), 개발 도구 `abi_lower`·`--input-abi` 제거, 넓힌 퍼저 seed·bench 성능 측정.

## 24. M3 뒷정리: 대조 묶음 명령·개발 도구 정리·Rust 판 정본 (2026-11-11)
1. **대조 묶음 명령** `tests/m3_all.py`: Python↔Rust 대조 도구 8단계(parse·check·trace·llvm·rust·compilers·standalone·abi)를 차례로 돌려 표로 요약, 하나라도 실패·바이너리 없음이면 exit 1. `--only/--skip/--quick/--rs-dir/--log-dir`.
2. **개발 전용 ABI 검사 제거**(설계 5·7절): `pruvc-rs/crates/pruvc/src/abi_lower.rs`와 `pruvc-ir-tool obj --input-abi`를 지웠다. ir-tool은 받은 IR을 그대로 객체화한다(Windows wrapper는 Rust 판 `pruvc`가 처음부터 sret로 출력, 23절 CI로 확인). `tests/abi/check_abi.py`·README 정리.
3. **Rust 판을 정본으로**(결정): 근거 — 모든 출력(parse·check·SMT trace·LLVM IR·바인딩·Rust 소스·CLI·단독 exe)이 Python 판과 바이트 동일, 퍼저·변이 판정 동일, Windows 실행 ABI CI 통과, Python·rustc 없이 실행 파일 하나, 컴파일이 더 빠름(아래). 시험 도구 공통 드라이버 `tests/compiler_driver.py`의 기본을 `rs`(기본 경로 `pruvc-rs/target/release/pruvc`, 없으면 빌드 안내와 함께 실패, Python 판으로 몰래 대체하지 않음)로 바꿨다. Python 판은 지우지 않고 대조 기준으로 둔다(`--compiler py`). **새 기능은 Python 판에 먼저 넣고 같은 묶음에서 Rust 판에 이식해 `m3_all` 대조를 통과시킨다**(빠른 시제품·독립 대조 유지). README '지금 상태' 갱신.

| 확인 | 결과 |
|---|---|
| `tests/m3_all.py` 전체 | 8단계 모두 ok, 82초(parse 1.4·check 2.2·trace 12.8·llvm 6.5·rust 5.4·compilers 468 same 9.0·standalone 50 same 44.2·abi 0.9) |
| `run_all --backend both` Rust 판 / Rust 판 + `--ir-tool` 객체화 | 363/363 / 363/363 |
| `cli_also_llvm` Rust 판 | 186/186 |
| `check_abi.py --ir-tool`(`--input-abi` 없이) | 통과 |
| 기본값 확인 | 옵션 없이 `run_all` → `compiler: rs`, `--compiler py` → Python 판 |
| 퍼저 Rust 판 새 seed 201~205 × 400 | 후보 3,672 → 증명 통과 2,051·거절 1,621, 입력 17,050·실행 65,800번, **실패 0**, oracle limit 0, seed당 49~64초 |

**bench 성능**(`bench/harness/run.py bench/solutions/pruv_agg --pruv --backend llvm --trust-callers`, 같은 객체화 경로, 두 판 번갈아 4번씩). 조용한 상태는 만들지 못했다: 다른 작업이 함께 돌아 load average 4~8. 그래서 같은 실행 파일 안 참조 대비 비율(sol/ref)의 중앙값으로 비교한다.

| 문제 | Python 판 생성물 | Rust 판 생성물 |
|---|---|---|
| p01 | 1.008 | 1.001 |
| p02 | 1.003 | 0.997 |
| p03 | 1.127 | 1.145 |
| p04 | 1.490 | 1.486 |
| p05 | 0.377 | 0.557 |
| p06 | 0.985 | 0.989 |
| p07 | 1.010 | 1.011 |
| p08 | 1.376 | 1.373 |
| p09 | 0.912 | 0.907 |
| p10 | 1.012 | 1.013 |

- 두 판이 만든 `.ll`이 10개 모두 바이트 동일함을 따로 확인했다(`cmp`). 따라서 실행 코드는 같고 위 차이는 측정 잡음이다(p05가 가장 흔들림). 정답 시험은 두 판 모두 10/10.
- **컴파일 시간**(검증+LLVM IR 출력, bench 10개+examples 7개, 3번 중앙값): Python 판 1.82초 → Rust 판 0.99초(약 1.8배). 이 값도 부하 아래 측정이다.
- 감사(Claude Opus): 필수 0, 권고 9. 반영 — ir-tool로 Python 판 IR을 Windows 대상 객체화하면 sret 없이 조용히 성공하는 위험(저장소 안 호출 경로는 없음)을 ir-tool 사용법·`tests/abi/README.md`·설계 5·7절에 명시, `m3_all`에 단계당 `--timeout`(넘으면 `timeout`·실패)과 로그 파일 바로 쓰기·`--log-dir` 루트 기준, README에 macOS 빌드의 Homebrew `libzstd` 동적 의존·`--emit exe` 링크 조건(Windows 대상 exe 미지원)·`--contract-budget` 시험용·바인딩 파일 이름 충돌 예시 고침, 퍼저 README 기본값, Windows 기본 경로 `.exe`. 남김 — Rust 판 `pruvc`에 `--version` 없음(대조 기록에 sha256이 남아 판 식별은 됨).
- 고친 뒤: `cargo build` 성공, `m3_all` 8단계 다시 모두 ok, `--timeout 2`로 standalone이 `timeout`·exit 1·남은 자식 프로세스 없음.
- 확인 감사(Claude Opus): 필수 0, 권고 5 반영 — 시간 초과·Ctrl-C 때 직접 자식만 죽어 손자(pruvc·rustc·실행 파일)가 남을 수 있음 → 단계를 새 프로세스 묶음으로 띄우고 묶음째 종료(POSIX `killpg`, Windows `taskkill /T`), 설계 문서 `--input-abi`·`abi_lower.rs` 표 항목에 제거 표시, README 링커 순서(`PRUVC_LINKER` 먼저)·`--also-llvm`, `diff_compilers` 사용법 `.exe`. 다시 `--timeout 3`에서 timeout·exit 1·남은 손자 없음, `m3_all --only abi,parse` ok.
- 남긴 것: 조용한 기계에서의 재측정, 4개 플랫폼 배포 빌드(사용자 결정으로 보류).

## 25. 0단계 마무리: 대규모 무작위 프로그램 퍼징 (2026-11-11)
질문: **증명을 통과한 프로그램이 실행에서 약속을 깨는가?** `bench/fuzz/run.py`(독립 오라클 = 임의 정밀도 해석기, Rust·LLVM × 증명·안전 4모드)를 정본 Rust 판 `pruvc`로 seed 301~320, seed마다 증명 통과 600개·프로그램당 입력 12개로 돌렸다(`--programs 600 --max-candidates 3000 --inputs 12`).

| 항목 | 값 |
|---|---|
| 생성한 후보 프로그램 | 22,283 (생성기 오류 0, 오라클 미지원 0) |
| 검증기 판정 | 통과 12,185(그중 12,000 빌드·실행) / 거절 10,098 |
| 실행한 입력 / 프로세스 실행 | 150,030 / 585,720 |
| **증명 통과 + requires 만족 입력** | **114,204건 모두 오라클과 같은 정상 결과(약속 위반 0)** |
| 증명 통과 + requires 위반·미정의 입력 | 28,626건(공개 경계 검사가 잡아 exit 101, 오라클과 같음) |
| 거절된 프로그램(표본 600, 안전 모드) + requires 만족 입력 | 실제로 터지는 입력: 0으로 나눔 1,003·범위 밖 389·넘침 105·내부 requires 94 / 정상 4,039 |
| 실패(unsound·mode_mismatch·oracle_mismatch·build·timeout 등) | **20 seed 모두 0** |
| oracle limit로 비교 못 함 | 0 |
| requires 만족 입력이 없는 프로그램 | 68개(대부분 강한 requires 조합, 위반 입력으로만 시험됨) |
| 걸린 시간 | 2,037초(seed당 92~113초) |

- 앞서 같은 날 seed 201~205×400(24절, 증명 통과 2,051·실패 0)과 M0~M3 동안의 seed 1·10·41·51~57·1110·1111 기록(10~12·15절)을 합치면, 이 퍼저로 증명 통과 프로그램 1만 6천 개 이상(오늘 두 묶음만 14,051개)에서 약속 위반이 한 번도 나오지 않았다.
- 거절된 프로그램 쪽 결과는 검증기가 아무거나 거절하는 것이 아님을 보여 준다: 거절 사유 그대로의 런타임 오류가 실제 입력에서 1,591번 났다. 정상으로 끝난 4,039건은 검증기의 보수성(맞는데 증명 실패)이며 1단계(정제 타입·불변식 추론)의 대상이다.
- 한계: 생성기 재료(`bench/fuzz/README.md` 생성기 절) 밖의 구문 — 중첩 반복문 깊이 2 초과, 재귀, 큰 배열 — 은 이 퍼징이 덮지 않는다. 입력은 경계 근처 위주 12개다. 실행 검사 i128 넘침은 자원 한계로 남긴 그대로다(M0_CONTRACTS).
- 컴파일러 코드는 바꾸지 않아 이 묶음의 코드 감사는 하지 않았다(측정만).
- 결론: **0단계(검증기 신뢰)를 닫는다.** 독립 감사·확인 감사·거부 회귀(must_reject)·안전 모드·계약 정의역·실행 예산·대규모 퍼징이 모두 끝났다.

## 26. 1단계 A: 정제 타입 (2026-11-11)
설계 `docs/STAGE1_SPEC.md`(설계 위임 → 설계 논쟁 15건 반영 → 확정 0절). 1단계를 A 정제 타입 → B 템플릿 Houdini 불변식 추론(`--infer`) → C 구간 분석(B 측정 뒤 결정)으로 나누고, 묶음마다 Python 판 → Rust 판 → 대조를 한 번에 끝낸다.

1. **문법**(SPEC 7a): 매개변수·반환·`let` 타입 자리에만 `x: i64 | 0..=100`, `a: [i64 | -1_000_000_000..=1_000_000_000; <=1_000_000]`(값 범위는 닫힌 `..=`, 길이는 `<=N` — 반열린 `forall k in 0..n`과 표기로 구별). 경계는 십진 정수 리터럴만(`1e9`·`0x10`·식은 `parse/refinement_syntax`), 필드·payload·Option 안은 `parse/refinement_position`, `bool` 등은 `type/refinement_base`, 역전·i64 밖·`N>2^40`은 `type/refinement_bounds`.
2. **의미 = 기존 계약으로 펼치기**(`pruvc/refine.py`, `pruv-core/src/refine.rs`): 매개변수 → 합성 `requires`(길이 → 원소 `forall` → 사용자 requires 순, 실행 검사·예산 2^30 공유는 기존 경로 그대로), 반환 → 합성 `ensures`, 지역 → 선언·재대입 뒤 합성 `assert`(`verify/refinement_init`·`refinement_assign`), 정제 지역을 바꾸는 `while` → 필수 불변식(진입·보존 모두 증명). 원소 저장은 저장 값 하나만 범위 의무. 합성 묶인 변수 이름은 함수 안 식별자와 겹치지 않게(`k`, `k_1`, …). 타입·ABI·생성기는 바꾸지 않음. 안전 모드는 지역·반환 정제를 실행 검사하지 않음(문서에 명시).
3. **Rust 판 이식**: 첫 빌드에 컴파일 오류 없음. 덤프 필드 이름 충돌(`kind`가 노드 이름을 덮음) 하나를 `shape`로 바꿔 두 판을 맞춤.

| 확인 | 결과 |
|---|---|
| `run_all --backend both` Rust 판 / Python 판 | **444/444 / 444/444**(기존 363 + 정제 거부 시험 27·실행 시험 12 × 뒷단·모드) |
| `cli_also_llvm` | 213/213 |
| `tests/m3_all.py` | 8단계 모두 같음(parse 2445 입력·check·trace·llvm·rust·compilers 572·standalone 50) |
| 퍼저 seed 41 × 200(Rust 판) | 증명 통과 209, 실패 0 |
| bench 사용성: `pruv_agg`의 입력 조건을 정제 타입으로 옮긴 `bench/solutions/pruv_refine` | 10개 중 5개 변환, 서명+requires 글자 1,043 → 714(−32%), 10/10 증명·정답 시험 통과, `--trust-callers` LLVM IR이 원본과 바이트 동일(검사를 켜면 검사 내용 같고 순서·메시지 글자만 다름) |

- 감사(Claude Opus): 두 판에 직접 넣어 본 사례 20여 개(재대입·원소 저장·`copy`/`alloc` 재대입·if·match·루프 안 대입 뒤 return·중첩 while·형제 블록·havoc 뒤 옛 길이·이름 포획·정수 경계·실행 모드)에서 **건전성 구멍 0**, 두 판 판정 같음. 필수 1 — 원소 저장마다 배열 전체 `forall` 합성 assert가 경로에 쌓여 저장 200개에 18.1초(정제 없이 0.13초) → 저장 노드에 원소 범위를 달고 이미 평가한 저장 값만 한 번 증명하게 바꿈: **0.18초**(Python 판 0.30초). 같이 고침: 범위 밖 저장 뒤 엉뚱한 연쇄 오류 없어짐(오류 정확히 1개), Rust 이중 펼침 표식, 경계 뒤 식·`[i64; 3]`·`0x10` 진단, 감사 수동 사례를 회귀 시험 11개 + 성능 표본(`refine_many_stores`, 직선 저장 62개)으로. 남긴 권고: 합성 requires/ensures/invariant 메시지에 출처 문구 없음(B에서), 실행 검사에서 원소를 두 번 읽음, 항상 참인 i64 전체 범위 검사도 생성, 정제 오류 위치가 주석 위치(원소 저장만 저장문 위치).
- 확인 감사(Claude Opus): 필수 0. 저장 값을 증명만 하고 경로에 가정하지 않아도 같은 경로 조건이 범위를 함의해 건전함을 루프·분기·호출·비선형 저장 사례로 두 판에서 확인(trace sha1 같음), 새 거부 시험이 의도한 code·줄로 거부됨. 권고 2 반영: 루프·분기 안 저장 뒤 정제 불변식·합계가 증명되는 실행 시험 `refine_loop_store` 추가, `diff_trace` 대조에 `bench/solutions/pruv_refine` 그룹 추가(trace·llvm·rust·compilers 다시 모두 같음, compilers 576).

## 27. 1단계 B1: solver 질의 기록 경계·대조기 고침 (2026-11-11)
B 묶음(템플릿 Houdini 불변식 추론)의 첫 작업(STAGE1_SPEC 0절 11·13). 추론 자체는 아직 없다.

1. **질의 기록 경계**: 두 판 검증기의 모든 z3 질의가 한 곳(`verify.py` `prove` 안 `run`, `obligation.rs` `run_attempt`)을 지나며, 설정은 `QueryConfig`(단계·회차·timeout·rlimit·seed)로 받는다. 시도마다 판정과 상태(`proved / not_proved / resource_unknown / timeout / error`), 실제 timeout·rlimit·seed, `reason_unknown`을 기록한다. 시험 어댑터는 이제 `z3.Solver`를 몽키패치하지 않고 이 공식 경계(`verify.TraceRecorder`)로 기록한다. trace 스키마 `pruv-trace-v2`(의무에 `phase/round/cand`, 시도에 위 값, 최상위 `options`).
2. **대조기**(`tests/diff_trace.py`): "두 판 같음"과 "검증 완료"를 따로 센다(`verified` 칸). 바이트 같아도 unknown·`verify_unknown`·`inference_timeout`이 끼면 `same_unknown`(성공으로 안 셈, `inference_timeout`이면 실패). 재시도로 풀린 차이는 첫 결과를 남겨 보고한다. `--flags=--infer`처럼 넘긴 옵션이 두 판 출력의 `options`에 실제로 반영됐는지 검사(`option_mismatch`는 실패). 어댑터·`pruv-trace-dump`는 모르는 옵션에 종료 코드 2(전에는 어댑터가 무시했다).

| 확인 | 결과 |
|---|---|
| `--infer` 없는 경로 SMT 불변: 코퍼스 231개 파일의 의무별 SMT 텍스트·판정·오류를 HEAD(aec7d1d)와 비교 | **바이트 동일** |
| `tests/m3_all.py` | 8단계 모두 ok, trace 351입력 same 333·cex_only 18·same_unknown 0, verified 164 |
| `run_all --backend both` Rust 판 / Python 판 | 444/444 / 444/444 |
| `cli_also_llvm` | 213/213 |
| `--flags=--infer`(아직 미구현) | 두 판 모두 모르는 옵션으로 거부 → 대조 실패로 잡힘(의도대로) |

- 감사는 B 묶음 전체(B2 추론까지)에 한 번 + 확인 한 번으로 한다.

## 28. 1단계 B2: Python 판 템플릿 Houdini 불변식 추론 `--infer` (2026-11-11)
구현 명세 `docs/STAGE1_B_INFER.md`(메인 확정, 두 판이 같은 후보·순서·SMT를 내도록 고정). 새 `pruvc/infer.py`, `verify.py` 연결(`extra`·`probe`), `pruvc.py`의 `--infer`·`--show-inferred`, 시험 어댑터 `--infer`(trace에 탐색 질의와 `inference` 기록). Rust 판 이식은 B3.

- 후보: 루프마다 11가지 틀(카운터 하한·상한, 배열 길이 유지, 원소 범위, 접두 sum/count/max/min, max/min의 forall·exists, 누적값 범위)을 코드 모양에서 만든다. 변수 이름에 기대지 않는다.
- Houdini: 회차마다 새 검증 상태로 함수 전체를 다시 돌려 후보 의무만 묻고(500ms·rlimit 100,000·seed 0), 실패한 후보를 회차 끝에 한꺼번에 뺀다. 남은 후보를 붙여 새 상태에서 전체를 최종 검증한다(8,000ms). 추론 결과는 믿지 않고 최종 검증이 증명한다.

| 측정(Python 판) | 결과 |
|---|---|
| `bench/solutions/pruv_agg` 불변식 절을 모두 지운 사본, `--infer` | **p01·p07·p09 증명(최소 목표 달성)**, p02(max의 forall/exists 특성화)도 증명. p03·p05·p06·p08 실패(후보 일부 남음), p04·p10 후보 없음 |
| 같은 사본, 추론 없음 | 10개 모두 실패 |
| p01/p02/p07/p09 후보·회차·질의 | 6·1·15 / 9·2·83 / 6·1·23 / 6·1·15 (생성·회차·탐색 질의) |
| `tests/inference` 표본 18개(통과 8, 필수 거부 9종 + max 거부 1) | 18/18 |
| `--regress`: 기존 거부 시험 전부가 `--infer`로도 거부, 증명 모드 실행 시험·bench가 `--infer`로도 통과 | 197/197(건전성 회귀 0) |
| `--infer` 없는 경로 SMT·판정·오류(231개 파일, B1 이전 HEAD 기준) | 바이트 동일 |
| `run_all --backend both --compiler py` / `cli_also_llvm --compiler py` | 444/444 / 213/213 |

- 거부 표본 중 셋은 손으로 다시 짰다: `inf_rej_once`(1회차에 남았다가 2회차에 빠짐), `inf_rej_dependent`(두 후보에 기대던 후보가 2회차에 빠짐), `inf_rej_nested_outer`(안쪽 루프가 배열 길이를 새로 만들어 바깥 길이 후보가 빠지고 증명 실패). 실행기는 탈락 회차까지 검사한다.
- 시간: 위 표본은 함수당 1초 안쪽(정밀 측정은 B3에서 두 판을 함께).
- 감사는 B 묶음 끝(B3 뒤)에 한 번 + 확인 한 번.

## 29. 1단계 B3: Rust 판 이식·두 판 대조·측정, 감사, C 결정 (2026-11-11)
Python 판 `--infer`(28절)를 Rust 판에 옮겼다: `pruv-proof/src/infer.rs`(후보 생성·출력·Houdini·보고), `symbolic.rs`/`obligation.rs`(후보 불변식·탐색 모드), `lib.rs` `verify_program_opts`, `pruv-trace-dump --infer`, `pruvc` CLI `--infer`·`--show-inferred`. 첫 빌드에 컴파일 오류 없음. 회차·최종 검증마다 새 z3 컨텍스트를 쓴다.

| 확인 | 결과 |
|---|---|
| `diff_trace --flags=--infer`(코퍼스+fuzz+추론 표본+불변식 지운 bench) | 276입력, 탐색·최종 질의의 SMT 텍스트·판정·후보 보고 **두 판 바이트 동일**(반례 값만 다름 8) |
| `diff_trace --flags="--infer --no-verify"` | 같음 |
| `tests/m3_all.py`(새 단계 `trace_infer` 포함 9단계) | 모두 ok |
| `tests/inference/run.py --regress` Rust 판 / Python 판 | 200/200 / 200/200(표본 21: 통과 8, 거부 12, 예산 소진 1 + 기존 거부 시험·실행 시험·bench 회귀) |
| `--infer` 없는 경로 SMT·판정·오류(231개 파일, B1 이전 기준) | 바이트 동일 |
| `run_all --backend both` 두 판 / `cli_also_llvm` / 퍼저 seed 41×200 | 444/444 두 판 / 213/213 / 실패 0 |

**측정**(`bench/inference/run.py`, 불변식 절을 모두 지운 `bench/inference/agg_noinv`, 5회 중앙값, 부하 있는 기계라 시간은 잡음 포함):

| 입력 | 추론 없음 | `--infer` | 후보 생성/남김/탈락 · 회차 · 탐색 질의 | Rust ms 끔→켬 | Python ms 끔→켬 | trace 바이트 끔→켬 |
|---|---|---|---|---|---|---|
| p01 합 | 실패 | **증명** | 6/6/0 · 1 · 15 | 22→46 | 92→171 | 10,947→46,805 |
| p02 max(forall/exists) | 실패 | **증명** | 9/7/2 · 2 · 83 | 20→166 | 108→356 | 14,632→280,276 |
| p03 정렬 판정 | 실패 | 실패 | 3/2/1 · 2 · 9 | 22→28 | 81→91 | |
| p04 이분 탐색 | 실패 | 실패 | 후보 없음 | 34→33 | 93→90 | |
| p05 접두합 배열 | 실패 | 실패 | 8/7/1 · 2 · 39 | 24→78 | 81→169 | |
| p06 최대 부분합 | 실패 | 실패 | 3/3/0 · 1 · 15 | 30→53 | 85→120 | |
| p07 개수 | 실패 | **증명** | 6/6/0 · 1 · 23 | 20→54 | 69→119 | |
| p08 뒤집기 | 실패 | 실패 | 5/4/1 · 2 · 20 | 28→50 | 73→92 | |
| p09 내적 | 실패 | **증명** | 6/6/0 · 1 · 15 | 39→57 | 105→134 | |
| p10 gcd | 실패 | 실패 | 후보 없음 | 16→16 | 66→67 | |

- **목표 달성**: 불변식 9절을 모두 지운 p01·p07·p09가 두 판 모두 `--infer`로 증명된다(0절 14 최소 목표). 덤으로 p02. 추론 없음은 0/10, 템플릿만 4/10. 예산 폐기(잘림) 0, 예산 소진 0(이 입력들), 시간 초과 0.
- 측정 못 한 것: 생성·기호 실행·최종 검증 시간을 따로 나누지 못했다(컴파일 전체 시간의 끔/켬 차이만). 조용한 기계에서의 시간.
- **실패 원인 진단**: p10은 `x >= 0 && y >= 0` 같은 단순 값 범위가 없어서(구간 분석이 줄 수 있는 종류), p03(정렬 접두 `forall`), p04(lo/hi 구간 관계), p05·p08(출력 배열 접두 관계), p06(부분합 forall/exists)은 관계형·양화 불변식이 필요하다.
- **감사(Claude Opus)**: 필수 2·권고 7. 필수 1은 **건전성 구멍** — 누적 항·max 비교에 사용자 함수 호출이 있으면 그 호출이 후보에 들어가고, 계약 문맥의 호출은 callee `requires`를 검사하지 않고 `ensures`를 가정하므로 거짓 후조건이 `--infer`로 통과했다(재현 2개, 두 판 모두). → `len` 이외 호출이 든 후보는 정렬 전에 버림(두 판 같은 규칙, 명세에 기록), 재현을 거부 표본 `inf_rej_call_in_term`·`inf_rej_call_in_max`로. 필수 2 — 대조기가 반례만 다른 입력의 unknown·추론 시간 초과를 성공으로 셈 → `same_unknown`으로. 권고 반영: Rust CLI 내부 오류 때 기록 안 찍음, `pruv-trace-dump`가 어댑터와 같은 옵션 집합(`options.no_verify`), 루프 후보 목록 복사 제거·중단 뒤 즉시 복귀, 안 쓰는 함수 삭제, 0절 7 문구. 남긴 권고: 후보 질의 하나의 500ms 시간 초과가 함수 전체를 `inference_timeout`으로 만드는 설계(측정 대상, 이 측정에선 0건).
- **확인 감사(Claude Opus)**: 필수 0. 호출 거르기가 모든 후보 경로(단일 지점)에 걸리고, 계약 문맥에서 `requires` 없이 가정을 더하는 노드는 호출뿐임을 코드로 확인, 조건 속 호출 사례·예산 소진 사례(질의 정확히 512)에서 두 판 출력 동일. 권고 3 반영: 어댑터 옵션 약어 끔(두 판 같게), 예산 소진 시험 `inf_budget`, 표 머리 간격.

**C(구간 분석) 결정: 지금은 착수하지 않는다(보류).** 근거: 템플릿만으로 남은 실패 6개 중 비관계형 구간 분석이 직접 풀 수 있는 것은 p10(값 범위) 하나뿐으로 보이고, 나머지 5개는 관계형·양화 불변식이 필요하다(STAGE1_SPEC 6절 열린 문제 "비관계형 구간 분석의 한계가 실제 실패의 주원인인지 측정한 뒤"의 측정 결과). 다음 후보는 구간 분석보다 (1) 값 범위 템플릿(초기값·갱신에서 `x >= 0`류) 추가, (2) 정렬·출력 배열 접두 같은 관계 템플릿이다. STAGE1_SPEC 0절에 기록.


## 30. 1단계 B+: 추론 템플릿 확장(값 범위·출력 배열 접두·조기 반환 접두) (2026-11-11)
`--infer` 후보 템플릿에 세 종류를 더했다(명세 `docs/STAGE1_B_INFER.md` 3.7, 추론 설정 버전 2). 모두 코드 구조에서만 만들고 이름에 기대지 않으며, `len` 외 호출 거르기(한 지점)를 똑같이 지난다. Python 판(`pruvc/infer.py`) → Rust 판(`pruv-proof/src/infer.rs`) 순으로 넣었다.

| 종류 | 후보 | 노린 입력 |
|---|---|---|
| 12 값 범위 | 루프에서 대입만 받는 비카운터 스칼라 v의 시작값 범위: 리터럴, `requires`의 매개변수 하한·상한(`>`·`<`는 ±1), 원소 범위 있는 배열 원소 → `v >= L`, `v <= U` | p10 gcd |
| 13 출력 배열 접두 | 증가폭 1 카운터 앞의 `b[v] = E`(b는 `alloc`/`copy`로 시작해 이 저장으로만 쓰임) → `forall k in lo..v: b[k] == E[v:=k]` | p08 뒤집기 |
| 14 조기 반환 접두 | 증가폭 1 카운터 앞의 `if C { return R; }`(else 없음) → `forall k in lo..v: !C[v:=k]` | p03 정렬 판정 |

**측정**(`bench/inference/run.py --repeat 5`, 불변식 절을 모두 지운 `bench/inference/agg_noinv`, 중앙값, 부하 있는 기계라 시간은 잡음 포함):

| 입력 | `--infer` | 후보 생성/남김/탈락 · 회차 · 탐색 질의 | Rust ms 끔→켬 | Python ms 끔→켬 | trace 바이트 끔→켬 |
|---|---|---|---|---|---|
| p01 합 | 증명 | 8/6/2 · 2 · 36 | 20→65 | 72→133 | 10,947→76,372 |
| p02 max | 증명 | 9/7/2 · 2 · 83 | 20→161 | 69→256 | 14,632→280,276 |
| p03 정렬 판정 | **증명(새로)** | 4/3/1 · 2 · 15 | 20→37 | 68→90 | 10,314→33,527 |
| p04 이분 탐색 | 실패 | 2/1/1 · 2 · 8 | 32→41 | 82→103 | 27,080→41,689 |
| p05 접두합 배열 | 실패 | 10/7/3 · 3 · 66 | 23→97 | 74→181 | 16,227→149,011 |
| p06 최대 부분합 | 실패 | 7/5/2 · 2 · 54 | 28→87 | 80→163 | 30,011→156,339 |
| p07 개수 | 증명 | 7/6/1 · 2 · 49 | 18→67 | 65→140 | 9,639→108,082 |
| p08 뒤집기 | **증명(새로)** | 6/5/1 · 2 · 26 | 20→48 | 71→111 | 9,819→55,796 |
| p09 내적 | 증명 | 8/6/2 · 2 · 36 | 37→85 | 91→164 | 35,374→121,909 |
| p10 gcd | **증명(새로)** | 4/4/0 · 1 · 8 | 17→23 | 61→69 | 4,733→18,113 |

- **결과: 4/10 → 7/10**(두 판 같음, 목표 p10·p08·p03 모두). 추론 없음은 0/10 그대로. 잘림·예산 소진·시간 초과 0.
- p01·p02·p07·p09도 후보가 늘어(예: p01 6→8) 질의 수가 늘었다(p01 15→36). 결과는 같다.
- **남은 실패 진단**: p04는 `lo`/`hi`가 카운터 꼴(`v = v + c`)이 아니라 경계 관계(`lo <= hi`, `forall k in 0..lo: a[k] < x`) 후보가 없다. p05는 저장이 `out[i + 1] = s`(색인이 `v`가 아님)이고 `s == out[i]`·`out[0] == 0` 같은 누적값-배열 관계가 필요하다. p06은 부분합 `forall/exists p ... sum` 꼴이 필요하다. 셋 다 이번 템플릿 범위 밖이다.
- 측정 못 한 것: 생성·기호 실행·최종 검증 시간 분리, 조용한 기계의 시간, 실사용 크기 입력.

| 확인 | 결과 |
|---|---|
| `diff_trace --flags=--infer`(코퍼스+fuzz+추론 표본+불변식 지운 bench) | 392입력 성공: same 364, 반례 값만 다름 26, **same_unknown 2** |
| 그 2개(pruv_agg p06·pruv_refine p06 원본) | SMT·결과·상태는 같고 탐색 질의 하나의 z3 `reason_unknown` 글귀만 다름("max. resource limit exceeded" / "push canceled", 둘 다 rlimit 소진). **끝 기준 "trace 바이트 동일"은 이 2개에서 못 지킴.** 대조기는 이 두 글귀 차이만 `same_unknown`(성공으로 세지 않음, 실패도 아님)으로 분류하게 고침(`strip_reason`, 다른 글귀·상태·결과 차이는 그대로 diff) |
| `tests/inference/run.py --regress` 두 판 | 210/210 / 210/210(표본 31: 새 10 — 통과 5·탈락 2·거부 1·생성 안 됨 1·되돌림 1) |
| `--infer` 없는 경로 SMT·판정·오류(231개 파일, B1 이전 기준) | 바이트 동일 |
| `run_all --backend both` 두 판 / `cli_also_llvm` / `m3_all` 9단계 / 퍼저 seed 41×200 / `cargo test -p pruv-core` | 444/444 두 판 / 213/213 / 모두 ok / 실패 0 / 41 |

- **시험 도구**: `tests/inference/run.py`에 `absent`(보고에 나오지 않아야 할 후보)·`fallback` 기대 키.
- **감사(Claude Opus)**: 필수 1·권고 4. 필수 — 종류 12 후보끼리 서로 받치는 사슬(`a0 = a1; …; a19 = i + 1`)은 Houdini가 회차마다 하나씩만 버려 질의 예산 512를 소진하고, 소진하면 후보를 모두 버리므로 버전 1에서 남던 `0 <= i`·`i <= n`까지 잃어 ensures 거부(두 판 재현). → **버전 1 되돌림**(명세 4.1): 예산 소진이고 처음 목록에 종류 12 이상이 있었으면 종류 1~11만으로 새 예산·같은 마감·이어지는 회차 번호로 다시 탐색, 보고에 `"fallback": "v1"`. 재현은 표본 `inf_budget_fallback`(두 판 질의 512+6, verified). 권고 반영: 명세 비용 설명(질의 수는 회차 × 남은 후보로 는다), `strip_reason`을 rlimit 두 글귀로 한정, 시험 보강(엄격 부등호·`-리터럴`·중첩 `&&`, `copy` 시작, 생성 안 됨 꼴). 남긴 권고: 3.1 카운터 판정이 판마다 두 벌(기존 1~11용·새 12~14용, 지금 같음) — 기존 생성 경로를 건드리지 않으려고 합치지 않음.
- **확인 감사(Claude Opus)**: 필수 1·권고 2. 되돌림은 두 판 동치·명세 일치·첫 탐색 바이트 불변·마감 유지(코드 대조와 직접 실행). 필수 — `absent` 검사가 보고의 `invariant ` 접두와 비교하지 않아 살아남은 후보를 못 잡음 → 고침, 일부러 살아남는 후보를 넣어 검사가 실패함을 확인. 권고 반영: `inf_budget_fallback`의 absent 뜻(되돌림 결과 기준)·`absent`의 한계를 README에, 되돌림의 "나빠지지 않음"은 질의 예산 면만이고 시간 면은 보장하지 않는다고 명세에 적음.

**`--infer` 기본 켜기: 계속 끈다**(STAGE1_SPEC 0절 17). 켜면 컴파일 시간 1.3~8배, trace 1.5~19배이고, 3/10은 켜도 실패한다. 실사용 크기 입력에서 시간 초과·되돌림 시간 한계를 아직 재지 않았다.

## 31. 1단계 마무리(건전성 회귀 측정)와 G2 설계 (2026-11-11)
### 31.1 `--infer` 건전성 회귀: 잘못된 변이의 새 통과 0
STAGE1_SPEC 5.5의 마지막 지표 "건전성 회귀(잘못된 변이의 새 통과 수)"를 쟀다. 새 도구 `bench/inference/mutate_infer.py`는 `bench/mutate.py`의 변이 규칙(OPS·SKIP·`mutants`)을 소스에서 그대로 가져와 같은 변이를 만들고, 컴파일(검증+코드 생성)을 네 번(Python 판·Rust 판 × `--infer` 없음·켬) 돌려 판정을 비교한다. 판정: 통과 = 종료 0, 거부 = 종료 1 + 오류 JSON(stage≠internal), **미결** = 종료 1 + `inference_timeout`·`verify_unknown`, crash = 그 밖(종료 2·3, JSON 없는 종료 1, 시간 초과). 새 통과 = 없음에서 통과가 아닌데 켬에서 통과. 미결은 `--retry`로 병렬 1개로 다시 돌린다. 뒷단은 검증 뒤 단계라 판정에 영향이 없어 rust 뒷단만 쓴다(처음 llvm으로도 돌려 같은 판정을 봤지만 독립 증거는 아니다).

명령: `mutate_infer.py OUT bench/solutions/pruv_try1 bench/solutions/pruv_agg bench/inference/agg_noinv bench/g1/solutions/ref_pruv --jobs 8 --retry`(HEAD 0350eeb, 2분 6초). 요약은 `bench/inference/mutate_infer_31.json`.

| 판 | 없음: 통과/거부/미결/crash | 켬: 통과/거부/미결/crash | 새 통과 | 잃은 통과 |
|---|---|---|---|---|
| Python | 20 / 278 / 0 / 0 | 21 / 269 / **8** / 0 | 1 | 0 |
| Rust | 20 / 278 / 0 / 0 | 21 / 272 / **5** / 0 | 1 | 0 |

- **새 통과 1건은 원래 참인 변이다.** `agg_noinv` p02(max)의 `if a[i] > m` → `if a[i] >= m`. 같은 값을 다시 고를 뿐 결과가 같다. 사람이 쓴 불변식이 있는 `pruv_agg` p02의 같은 변이는 추론 없이도 통과하고, 예전 기록 `bench/mutants9_0a_llvm.json`에서도 통과·시험 통과다. 따라서 **잘못된 변이의 새 통과는 0**(두 판). 참/거짓 변이 판정은 사람이 했다.
- **미결 13건(Python 8·Rust 5)은 통과가 아니다**(종료 1, 컴파일 실패). 병렬 1개 재시도에서도 그대로였다. 그래서 "새 통과 0"은 이 13건을 통과가 아닌 것으로 센 결과다.
- **새로 찾은 두 판 차이(고칠 일):** 미결은 모두 0.1초 안팎에 나는 `inference_timeout`이고 결정적으로 재현된다. 두 판에서 걸리는 변이가 달라 `--infer` 판정이 7건에서 어긋난다(한쪽 미결·다른 쪽 거부, 둘 다 통과 아님). 한 사례(`pruv_try1` p09 줄 8)에서 Python trace의 탐색 질의 하나가 `unknown`(reason `canceled`, 500ms보다 훨씬 짧음 → rlimit 쪽으로 보임)이었고, `query_status`가 `canceled`를 `timeout`으로 분류해 Houdini 전체를 멈췄다. Rust는 같은 자리에서 답을 냈다. 이는 명세(`docs/STAGE1_B_INFER.md` 질의 timeout → 함수 전체 `inference_timeout`)대로의 동작이고, 두 판 차이는 같은 rlimit 소진이 z3 글귀에 따라 `canceled`(→timeout, 추론 중단)와 `push canceled`·`max. resource limit exceeded`(→resource_unknown, 후보 탈락)로 갈리는 데서 온다(30절의 same_unknown 2건과 같은 뿌리). 질의 하나의 `unknown`은 그 후보만 버리면 되는데(건전) 함수 전체 추론을 멈추는 것이 문제다. 근거 자료: 미결·판정 차이 변이의 항목별 기록(초·코드·첫 시도)을 `bench/inference/mutate_infer_31.json`에 두었다. trace 확인은 p09 줄 8 한 사례만 했다. **다음 묶음 첫 일로 고친다**(→ 32절에서 고침: rlimit 소진은 후보 탈락, 벽시계 `timeout`만 함수 중단)(탐색 질의의 unknown은 후보 탈락으로, 함수 중단은 벽시계 5초 기한만으로 — 명세 STAGE1_B_INFER 갱신, 두 판, `--infer` 회귀·대조 다시).
- 기준선 확인: `pruv_agg` 83개 변이의 추론 없음 통과/거부는 예전 기록 `mutants9_0a_llvm.json`(83개)과 모두 같다.
- 한계: 변이는 `mutate.py`의 15가지 연산자 꼴뿐이고 불변식·계약 줄은 바꾸지 않는다. 변이 프로그램 실행 시험은 이 도구에서 하지 않았다.
- 확인 감사(Claude Opus): 앞 필수 7건 중 6건 해결, G2 표본 수 계산 오류(24 → 28, runtime 10 → 11) 필수 1건을 고침. 권고 반영: 미결 판정은 오류가 모두 미결 코드일 때만, z3 판(Python·`z3-src` 크레이트)·Cargo.lock 수정 여부 기록, 미결 항목 자료 저장, 원인 설명 정밀화, G2 결정 4 열거·결정 16 진단 이름·A6 끝 기준 보완.
- 감사(Claude Opus) 필수 2건을 고쳤다: 종료 2·JSON 없는 종료 1을 거부로 세던 것(→ crash, crash가 있으면 도구 실패), `inference_timeout`을 거부로 세던 것(→ 미결, 재시도·따로 집계). 권고 반영: 컴파일러 판 기록(git HEAD·소스 수정 여부·Rust 바이너리 sha256), 임시 폴더 정리, 작업 예외를 crash로 기록, 입력 폴더 이름 겹침 거부, "검증만"·"두 뒷단" 문구 정정, 명령·요약을 저장소에.

**1단계 완료.** 정제 타입(A), 템플릿 Houdini `--infer`(B·B+, 불변식 지운 pruv_agg 7/10)까지 하고 5.5 지표를 모두 쟀다. 구간 분석(C)은 보류, `--infer` 기본 켜기는 계속 끔.

### 31.2 G2 설계 확정(`docs/G2_SPEC.md`)
조사 → 초안 → 설계 논쟁 1회 → 메인 확정 → 감사 순으로 만들었다(구현은 다음 묶음부터, 측정값 없음).

- **조사(Codex):** 지금 정수는 `i64` 하나, 배열은 `[i64]`만(파서가 `[` 뒤 `i64`만 받음), 문자열·문자 토큰 없음(따옴표는 `bad_char`). 증명은 `Array(Int,Int)`+길이, Rust 출력 `&[i64]`/`Vec<i64>`, LLVM `{ptr,i64}`·C 런타임 원소 8바이트 고정, `--rust-bindings`도 `*const i64`.
- **초안(Codex):** 스칼라 정수 타입은 늘리지 않고 배열 원소 저장 타입만 연다. 좁은 원소를 읽으면 `i64`, 쓸 때 `elem_range` 증명. `str` = 유효 UTF-8이 보장된 읽기 전용 바이트열, 경계 증명된 `substr`(복사). `[u8]→str` 변환은 `Option<str>`이 없어 뒤로.
- **설계 논쟁(Codex, 필수 9·권고 6) → 0.0절 확정 결정 14개:** 첫 판 `[u8]`·`[bool]`만(i32 뒤로), 범위 가정은 값이 바깥에서 들어오는 지점(진입·호출 결과·havoc)에서만, `--infer` 탐색이 건너뛰는 `elem_range`는 최종 검증에서 필수 관문, bool 배열 `Array(Int,Bool)`과 반례 JSON, `alloc` 원소 타입은 타입 적은 `let`·재대입·`return` 바로 오른쪽에서만, 내부 타입 이름 소스 사용 거부, 감사는 묶음마다, 444는 실행 행 목록으로 고정, 새 표본 대조는 `same`만 인정. 첫 구현 묶음은 **A0 기반**(새 문법 없이 기존 `[i64]` 기호 배열에 원소 타입 보존).
- **감사(Claude Opus, 문서 몫 필수 5·권고 6):** A0 경계에 `samples.rs`(시제품 경로가 `Arr {..}`를 직접 만듦)·`run_all.py`(행 목록 내보내기) 누락, 결정 4가 후보 종류를 잘못 짚음(원소 범위는 종류 12가 아니라 **종류 5**, 그대로면 bool 배열에 `lo <= b[k]`가 생겨 z3 sort 오류), 코드 읽기 때의 `in_range(Select)` 가정 지점 미규정(좁히면 잘못 저장 뒤 읽기에서 공허한 증명), i32 미루기와 끝 기준(표본 26개·examples·변이·독립 사용) 모순 → 모두 0.0절에 반영(결정 2·4 보강, 15~17 추가, 묶음 표 경계 보강). 권고 반영: 다음 층 미구현 동안 G2 타입 명시 거부, G2 전용 변이 OPS, SMT 기준 입력 목록 고정, 줄 번호 인용 정정.

## 32. B++: 추론 탐색 질의의 rlimit 소진은 후보만 탈락 (2026-11-11)
31.1에서 찾은 두 판 차이를 고쳤다. `--infer` 탐색에서 후보 질의가 `unknown`이면, z3 이유(`reason_unknown`)가 **정확히 `timeout`**(질의의 500ms 벽시계 기한)일 때만 지금처럼 함수 전체 `inference_timeout`이고, 그 밖의 이유(rlimit 소진의 `canceled`·`push canceled`·`max. resource limit exceeded` 등)는 **그 후보만 이번 회차에서 탈락**시킨다(후보를 버리는 것은 항상 건전하다 — 살아남은 후보는 최종 검증이 기본 설정으로 다시 증명한다). 명세 `docs/STAGE1_B_INFER.md` 4.1 "B++ 개정"·5절 `dropped[].status` 값 목록. 코드: `pruvc/verify.py` `_probe_attempts`, `pruv-proof/src/obligation.rs` `probe_attempts`(두 판 같은 흐름). `query_status`와 `--infer` 없는 경로는 그대로. 추론 설정 값은 그대로라 설정 버전은 2 유지.

- **근거 실측:** Python z3 5.3.3에서 같은 어려운 식을 rlimit 100000으로 풀면 `unknown`·이유 `canceled`(통계 `rlimit count` 100039 ≥ 한도), rlimit을 크게 두고 timeout 500ms·50ms로 풀면 이유 `timeout`. 즉 `canceled`는 rlimit 소진(실행마다 같은 결정적 결과)이고 `timeout`은 벽시계다.
- **처음 고침(이유 무관 탈락)은 감사 필수 1로 좁혔다:** 벽시계 `timeout`까지 탈락으로 바꾸면 부하에 따라 살아남는 후보 집합이 달라질 수 있어 STAGE1_SPEC 0절 6("시간 초과는 후보 제거로 바꾸지 않는다")·283행("시간에 따라 서로 다른 후보 집합을 골라 성공시키지 않는다")에 어긋난다. 그래서 벽시계 `timeout`은 옛 동작으로 남겼다. Rust z3 판에서 벽시계 초과의 이유 글귀는 직접 재현하지 못했다(Rust는 rlimit 소진을 원래 `resource_unknown`으로 분류해 왔다).
- **변이 298개(31.1과 같은 명령, `bench/inference/mutate_infer_32.json`):**

| 판 | 없음: 통과/거부/미결/crash | 켬: 통과/거부/미결/crash | 새 통과 | 잃은 통과 |
|---|---|---|---|---|
| Python | 20 / 278 / 0 / 0 | 21 / 277 / **0** / 0 | 1 | 0 |
| Rust | 20 / 278 / 0 / 0 | 21 / 277 / **0** / 0 | 1 | 0 |

  미결 13 → **0**, 두 판 `--infer` 판정 차이 7 → **0**. 새 통과 1건은 31.1과 같은 참인 변이(`agg_noinv` p02 `>`→`>=`)라 잘못된 변이의 새 통과는 계속 0. 좁힌 규칙에서도 미결이 0이므로 13건은 모두 rlimit 소진(`canceled`)이었다.
- **회귀:** `tests/inference --regress` 두 판 210/210, `--infer` 없는 SMT 스냅샷 231파일 바이트 동일, `diff_trace --flags=--infer` 392 성공(same 363·cex_only 27·same_unknown 2, 30절은 364·26·2), run_all 444/444(두 판), cli_also_llvm 213, m3_all 9단계 ok, 퍼저 seed 41×200 실패 0, cargo test pruv-core 41, 불변식 지운 pruv_agg `--infer` 7/10(두 판, 그대로).
- **시험 도구의 시간 흔들림:** `tests/inference/inf_budget.pruv`(예산 소진 표본)는 혼자 돌리면 Python 판 약 2초인데, `diff_trace` 전체(`--jobs 5`)·`m3_all`의 병렬 부하에서는 Python 쪽만 함수당 5초 벽시계에 걸려 `inference_timeout`이 되고 Rust는 `budget_exhausted`로 끝나 diff가 났다. 고치기 전 코드로도 같은 실패가 재현됐고(두 번 중 한 번), 이 표본의 trace는 고치기 전·후 바이트 동일했다. 그래서 `tests/diff_trace.py`가 한쪽 errors에 `inference_timeout`이 있어 다르면 `flaky_unknown`으로 분류해 그 입력만 직렬로 다시 판정하게 했다(재시도 뒤에도 다르면 diff, 성공 칸에 더하지 않음). 위 392 성공 실행에서 재시도는 0건이었다.
- **감사(Claude Opus):** 건전성 결함 없음, 두 판 흐름 같음, 필수 1(위 STAGE1_SPEC 위반) → 고침. 권고: 성능 최악 — 기한 직전에 시작한 질의가 500ms를 더 써 함수당 약 5.5초까지(재현 없음, 측정 안 함), 함수 단위 `timeout` 상태를 직접 보는 시험 없음(결정적으로 만들기 어려워 남김), 31.1·BLUEPRINT의 "남은 고침" 문구에 고쳤다는 표시(반영).
- **확인 감사(Claude Opus):** 필수 0. 필수 1 해소(두 판 같은 판정 순서, STAGE1_SPEC 0절 6·282·283행과 맞음 — 옛 동작은 오히려 282행 "결정론적 자원 한계의 unknown은 후보 제거"에 어긋났다), `diff_trace` 새 분류는 재시도 뒤 다르면 diff로 남아 진짜 차이를 숨기지 않음. 권고 반영: 개정 전후 trace 구분 문구(명세). 남긴 권고: rlimit 소진으로 후보만 탈락하는 회귀 표본 없음(결정적 재현 입력을 아직 못 만듦), `dropped[].status`의 `timeout`이 rlimit 소진도 뜻하는 어휘 문제(다음 어휘 개정 때 `resource_unknown`으로 모으기 검토), 재판정으로 칸이 바뀐 수를 요약 줄에 따로 세기. z3 소스로 벽시계 초과가 `canceled`로 나올 수 없는지는 확인 못 함(짐작: 타이머는 이유를 `timeout`으로 덮어씀).
- 측정 못 한 것: 실사용 크기 입력에서의 탐색 시간, 함수별 탐색 시간 최댓값.

## 33. G2 A0: 원소 타입 배열의 구현 기반 (2026-11-11)
G2 기능이 아니라 **G2 구현 기반**이다. 새 문법은 없고, 지금 소스로 쓸 수 있는 배열은 여전히 `[i64]` 하나다(`docs/G2_SPEC.md` 0.0.1 A0 행).

- **기호 배열에 원소 타입:** Python `pruvc/verify.py` `Arr`에 `elem`, 생성은 `mk_arr` 하나. Rust `pruv-proof/src/symbolic.rs` `Arr`에 `elem`, 생성은 `Arr::new` 하나(`samples.rs` 시제품 포함). fresh(진입 매개변수·호출 결과)·alloc(지금은 i64 고정)·copy·재바인딩·원소 저장·루프 havoc에서 원소 타입을 넘겨받는다. 두 판 대응은 감사가 경로마다 대조했다. fresh 번호 순서는 그대로다. bool 원소면 SMT `Array(Int, Bool)`을 만드는 갈래까지 들어 있지만 아직 도달할 수 없다.
- **배열 질의 API와 내부 이름:** Python `typeinfo.py` `is_array`·`array_elem`·`array_of`(없으면 None), 내부 이름 `array`↔i64·`array_u8`↔u8·`array_bool`↔bool. Rust는 `pruv-core/src/typeinfo.rs` 이름 함수가 대응 표 한 벌이고, `model.rs` `Elem`·`Ty::Array(Elem)`가 그 표를 쓴다(왕복 단위 시험 1). 내부 이름은 소스에서 계속 거부한다: `[u8]`는 parse `syntax`, `array_u8`·`array_bool`은 type `unknown_type`(두 판 같음). 사용자 타입은 대문자로 시작해야 해서 소문자 내부 이름과 겹칠 수 없다.
- **기준선 고정:** `tests/run_all.py --list-rows [FILE]`·`--compare-rows FILE`(행 = 표본·뒷단·플래그·모드·묶음·컴파일러, 비교는 이번 실행 범위 안의 저장 행만), 저장한 행 목록 `tests/run_all_rows.txt` 444행. SMT 기준 입력 231개 목록 `tests/smt_snapshot_inputs.txt`와 `tests/smt_snapshot.py run|compare`(`--abs-keys`면 옛 저장소 밖 스크립트와 바이트 같은 형식, crash가 있으면 실패).
- **회귀(고친 뒤 마지막 실행):**
  - run_all `--backend both` 두 판 444/444, 행 비교 결과 빠진 행·새 행·실패 모두 0
  - `--infer` 없는 SMT 231파일: 옛 스크립트·새 스크립트 모두 기준과 바이트 동일
  - `diff_trace --flags=--infer` 392 성공(same 364·cex_only 26·same_unknown 2. 첫 실행은 363·27·2였고, 반례 값만 실행마다 흔들리는 기존 현상), 플래그 없이 392 성공(363·29)
  - `tests/inference --regress` 두 판 210/210(Python 판 첫 실행 하나는 알려진 `inf_budget` 시간 흔들림으로 209, 다시 돌리니 210)
  - cli_also_llvm 213, m3_all 9단계 ok, 퍼저 seed 41×200 실패 0, cargo test pruv-core 41
- **감사(Claude Opus):** 필수 0·권고 9. 반영: 행 비교 범위, runtime 행 키에서 flags_matrix 순번 제거, must_reject 행 뒷단 칸 비움, 행에 묶음 이름, 두 옵션을 함께 주면 거부, 스냅샷 crash를 실패로, Python API를 None 반환으로, Rust 대응 표 한 벌·왕복 시험, 중복 줄 정리. 남김: 내부 이름이 진단·`is_user_type`에 새는 것(A1에서 소스로 열 때 함께), Rust `Arr` 필드 비공개화(읽는 곳이 많아 grep 확인으로 대신).
- **확인 감사(Claude Opus):** 필수 0, 반영 항목 모두 맞음. 남긴 권고 4:
  - 비교 범위를 실행된 행에서 만들어, 한 묶음의 작업이 0개가 되면 그 묶음의 빠진 행을 못 잡는다(재현 없음).
  - `group` 없는 옛 형식 행을 따로 알리지 않는다.
  - compiler 일치 판정이 범위 밖 행까지 본다.
  - Rust 왕복 시험이 `Elem` 변형 전체를 돌지 않는다(`unwrap`→`expect`).
  - 다음 시험 도구를 손볼 때 고친다.
- 측정 못 한 것: 없음(이번 묶음은 동작 불변이 기준이고, 성능 변화는 재지 않았다).

## 34. G2 A1: `[u8]` 앞단(문법·타입 검사) (2026-11-11)
`[u8]`를 소스로 쓸 수 있게 됐지만 **앞단(파싱·타입 검사·정제 검증)만**이다. 증명·코드 생성 층은 아직 `[u8]`를 모르므로, 검사를 통과한 `[u8]` 프로그램은 명시 진단으로 거부한다(`docs/G2_SPEC.md` 0.0 결정 16). 아직 G2a 사용 가능 기능으로 치지 않는다.

- **문법:** `[u8]`, 정제 `[u8 | L..=U; <=N]`(정제 `base`는 쓴 원소 이름 `u8`). 스칼라 `u8`·`i32`는 parse `element_storage_type`, `Option<u8>`·`Result<i32>`는 parse `unsupported_type`, `[bool]`·`[i32]`는 아직 parse `syntax`("only [i64] and [u8] arrays exist"). 내부 이름 `array_u8`·`array_bool`·`array_i32`는 소스에서 parse `syntax`(결정 7). 예전엔 type `unknown_type`이었다. `u8`은 변수 이름으로 계속 쓸 수 있다. 렉서의 정제 막대 `|` 판정에 `u8`을 더했다.
- **타입 검사:** 배열 규칙(별칭 금지·원소 대입·`==` 금지·필드 금지·`len`·색인·`copy`)을 `[i64]` 비교에서 모든 배열 타입으로 넓혔다. 읽기 결과는 i64, 저장 값도 i64 식이다. `copy`는 입력 타입을 보존한다. `alloc`은 결정 6대로, 타입을 적은 let의 오른쪽 식 자체·배열 변수 재대입의 오른쪽 식 자체·return 바로 뒤에서만 기대 배열 타입을 받는다. 그 밖(`copy(alloc(..))`·함수 인자·`len(alloc(..))`)은 `[i64]`라서 `[u8]` 자리에 쓰면 type `type_mismatch`다. 내장 타입 표와 출력 표에 `array_u8`(`[u8]`)·`array_bool`(`[bool]`)을 넣어 내부 이름이 진단과 `is_user_type`으로 새지 않는다(A0 감사 권고). `[i64]` 입력의 진단·문구·순서는 그대로다.
- **정제:** `[u8 | L..=U]`는 범위 전체가 0..=255 안이어야 하고, 밖이면 type `refinement_bounds`(교집합으로 해석하지 않음). 펼침은 바꾸지 않았다. u8의 암묵 범위 0..255는 A2에서 정의역 도입 지점에만 넣는다.
- **미구현 층 가드(결정 16):** 두 판 `first_g2_unimplemented`가 함수 순서대로 매개변수 → 반환 타입 → 본문 Let(블록 깊이 우선)에서 `[i64]`가 아닌 첫 배열 타입을 찾는다. 검증을 켜면 verify 진입(Python `verify_program`, Rust `verify_program_opts`)에서 verify `unsupported_type`으로, `--no-verify`면 드라이버에서 codegen `unsupported_type`으로 거부한다(종료 1, 메시지에 미구현 층 이름). 생성기 함수(`gen_rust`·`gen_llvm`)도 첫머리에서 같은 문구의 내부 오류 문자열을 낸다. 드라이버를 거치지 않는 대조 도구용이고, 두 판 모두 `internal`로 같게 분류된다. 선언 없이 `[u8]` 값을 만드는 길은 지금 없어서 우회로는 없다고 감사가 판정했다. 뒤 묶음에서 기대 타입 전달을 넓히면 가드도 넓혀야 한다.
- **표본:** `tests/must_reject/g2a_*` 21쌍. G2_SPEC 6.2 중 앞단 해당분 13(scalar_u8·scalar_i32·nested_array·user_element·option_u8·array_field·mixed_argument(`[u8]`→`[i64]`)·param_store·alias·array_eq·refine_wide·return_mismatch·missing_alloc), 내부 이름 2(internal_name·internal_name_bool), alloc 위치 2(alloc_copy_nested·alloc_argument), 가드 4(a1_verify_layer·a1_codegen_layer·a1_guard_nested·a1_guard_nested_nv). 정상 위치의 alloc·`len(alloc(..))`·지역 변수 이름 `u8`·정제 매개변수는 a1_verify_layer가 검사를 통과하는지로 확인한다. bool 표본(bool_fill 등)은 A5, verify 표본(u8_negative 등)은 A2 몫이다. must_reject json에 선택 키 `flags`를 두어 `--no-verify` 표본을 돌린다(`run_all`·`tests/inference/run.py`).
- **시험 도구(A0 확인 감사 권고):** `--compare-rows` 비교 범위를 실행된 행이 아니라 `--only`·`--backend` 인자로 만든다. `group` 없는 옛 형식 행이 있으면 종료 2다. compiler 판정은 범위 안 행으로 한다. Rust 왕복 시험은 `Elem` 전체를 돌고 `unwrap`을 `expect`로 바꿨다. 행 목록 `tests/run_all_rows.txt`는 465행(444 + must_reject 21)으로 다시 저장했다.
- **회귀(고친 뒤 마지막 실행):**
  - run_all `--backend both` 두 판 465/465, 행 비교 결과 빠진 행·새 행·실패 모두 0
  - m3_all 9단계 ok(parse/check dump 두 판 모두 same, compilers 618)
  - `--infer` 없는 SMT 231파일: 기준과 바이트 동일
  - `diff_trace --flags=--infer` 413 성공(same 384·cex_only 27·same_unknown 2), 플래그 없이 413 성공(same 384·cex_only 29). 새 21건은 모두 same이다.
  - `tests/inference --regress` 두 판 231/231, cli_also_llvm 234
  - 퍼저 seed 41×200 실패 0, cargo test pruv-core 41·`model::tests` 1
- **감사(Claude Opus):** 필수 0·권고 6.
  - 반영(2): 가드가 블록 안 Let으로 내려가는 표본(guard_nested 둘), 범위 안 저장 행이 0일 때 쓸데없는 안내 줄.
  - 기록만(4):
    - `u8 | ..` 처럼 홑 `|`를 잘못 쓴 입력은 예전 렉서 `bad_char` 대신 parse `syntax`가 나온다. 두 판 같음을 실행해 확인했다.
    - 가드는 선언 타입만 본다(뒤 묶음에서 넓힘).
    - 매개변수·반환에서 걸리면 진단 위치가 함수 위치다.
    - `len`·`copy`·색인 오류 문구가 모든 배열을 받는데도 "expected [i64]"다. 기존 바이트를 지키려고 그대로 뒀다.
- **메인이 직접 고친 것:** Rust 가드 진단의 stage가 "type"으로 고정돼 있던 것을 층 이름으로 바꿨다. Python 생성기 가드를 Rust `Err(String)`과 같은 내부 오류로 맞췄다(diff_rust·diff_llvm 8건 불일치 해소). 추론 회귀 도구가 표본 `flags`를 읽게 했다.
- **확인 감사(Claude Opus):** 필수 0, 반영 항목 모두 맞음. 권고 1: 표본 json은 stage/code만 봐서 진단 위치 회귀는 시험이 못 잡는다(하네스 확장은 범위 밖).
- 측정 못 한 것: 성능 변화(앞단에 배열 판정 몇 곳과 컴파일당 1~3회 문장 훑기만 더했다), Windows·Linux 실행.

## 35. G2 A2: `[u8]` 증명 (2026-11-11)
`[u8]` 프로그램을 이제 증명한다. 코드 생성 층은 아직 없으므로, 검증을 통과한 `[u8]` 프로그램은 드라이버에서 codegen `unsupported_type`으로 거부한다(결정 16, A3·A4에서 풂). 두 판이 같은 SMT·의무 순서·문구를 내도록 구현 명세를 `docs/G2_A2_IMPL.md`에 고정했다.

- **정의역(결정 2):** u8 기호 배열에는 `forall k: 0 <= k < n ==> 0 <= A[k] <= 255`(묶인 변수 고정 이름 `elem!k`, 순번 카운터를 쓰지 않음)를 **세 곳에서만** 가정한다: 함수 진입 매개변수, 사용자 함수 호출 결과, 루프 havoc(모두 길이 가정 바로 뒤). alloc·copy·재바인딩·저장 뒤에는 넣지 않고, 코드의 원소 읽기는 지금처럼 i64 범위만 가정한다.
- **`elem_range` 의무(verify, 새 코드):** `alloc(n, v)`는 `alloc_negative` → `elem_range`(v가 0..=255) 순서, 원소 저장은 `index_oob` → `elem_range` → 정제의 `refinement_assign` 순서. 위치는 alloc 호출식·저장문. 후보 의무가 아니므로 `--infer` 탐색에서는 빠지고 최종 전체 검증에서만 판정된다(결정 4). 원소 타입은 검사기가 alloc 호출 노드에 단 타입에서 얻는다.
- **`--infer` 필터(결정 4):** 함수의 배열 이름 → 원소 타입 표(매개변수·Let)를 만들어, 종류 5는 같은 원소 타입 배열에서 온 범위만 쓰고, 종류 5 이상 후보 중 bool 배열 원소를 읽는 것은 버린다(지금은 `[bool]`이 파서에서 막혀 실제로 걸리지 않음). u8 암묵 범위를 새 후보로 넣지 않았다.
- **가드:** verify 단계 가드를 지웠다. 드라이버 codegen 가드는 verify를 켰을 때도 돈다(두 판). A1 표본 `g2a_a1_verify_layer`·`g2a_a1_guard_nested`의 기대는 verify → codegen `unsupported_type`으로 바꿨다(이름은 A1 때 것 그대로).
- **표본 23쌍(must_reject 152):**
  - verify 거부 10: u8_negative·u8_high·alloc_value(+ alloc_value_reassign·alloc_value_return, 감사 반영)는 `elem_range`, store_index `index_oob`, refined_store `refinement_assign`, contract_oob `contract_domain`, alloc_length `alloc_negative`, store_then_read(300 저장 뒤 읽어 `10 / (x - 300)`) `div` — 읽기에서 0..255를 가정하면 경로가 모순돼 div가 공허하게 증명되므로 이를 잡는다.
  - 잘못된 저장 뒤 루프 탈출·반환·호출 3종 × `--infer` 끔/켬 = 6, 그리고 불변식 없는 루프 본문 안 잘못된 저장 + `--infer` 1(bad_store_in_loop_inf, 확인 감사 반영), 모두 `elem_range`.
  - 증명 통과(기대 codegen `unsupported_type`) 6: ok_param·ok_call_result·ok_loop_havoc·ok_branch·ok_copy_store·ok_loop_havoc_inf. param·call_result·copy_store·loop_havoc(둘)는 각 정의역 없이는 실패한다(ok_loop_havoc_inf는 `[i64]`로 바꾸면 assert 실패를 확인).
  - G2_SPEC 6.2 u8 거부 표본은 이것으로 다 찼다. bool(bool_fill 등)·infer_bool·sum_bool은 A5, i32는 A6.
- **회귀(마지막 실행):**
  - run_all `--backend both` 두 판 488/488(행 목록 488 = 465 + 23, 빠진 행·실패 0)
  - `--infer` 없는 SMT 231파일: 기준과 바이트 동일
  - diff_trace 플래그 없이 435 성공(same 406·cex_only 29), `--infer` 435 성공(same 407·cex_only 26·same_unknown 2). 새 22건은 두 모드 모두 same(결정 11). 확인 감사 뒤 더한 1건도 단독 대조에서 두 모드 same(전체 대조는 그 전 435건으로 실행). 나머지 분류는 A1 때와 같은 수준이고 반례 값만 흔들린다.
  - `tests/inference --regress` 두 판 251/251(Python 판은 병렬 부하에서 inf_budget이 한 번 시간 초과, 다시 돌려 통과)
  - m3_all 9단계 ok(compilers 664)·cli_also_llvm 257(표본을 다 더한 뒤), 퍼저 seed 41×200 실패 0(감사 반영 표본을 더하기 전), cargo test pruv-core 41·`model::tests` 1
- **처음 대조에서 고친 것:** 불변식 없는 `_inf` 표본 2개가 플래그 없는 대조에서 cex_only(반례의 i 값만 두 판이 다름)였다. 끔 표본과 같은 내용(불변식 포함)에 `--infer` 플래그만 두도록 바꿨고, 불변식 없는 추론 경로는 bad_store_return_inf·ok_loop_havoc_inf가 맡는다.
- **감사(Claude Opus):** 필수 0·권고 5.
  - 반영(2): alloc 재대입·return 지점 거부 표본 추가, ok_loop_havoc_inf가 추론된 접두 불변식(`forall k in 0..i: b[k] == k * 30`)으로 정의역 없이도 통과하던 것을 접두 밖 원소 검사로 바꿈.
  - 기록만(3): 추론의 원소 타입 표가 이름 기반이라 형제 블록에서 같은 이름을 다른 배열 타입으로 선언하면 섞일 수 있다(후보는 최종 검증을 거쳐 건전성 영향 없음, bool이 열리는 A5에서 처리). `g2a_a1_verify_layer` 이름이 지금 내용(codegen 층 거부)과 다르다. u8 함수의 pc에 전칭 가정이 들어가 의무가 많은 함수에서 느려질 수 있다(측정 안 함).
- **확인 감사(Claude Opus):** 필수 0·권고 1(불변식 없는 루프 안 잘못된 저장 + `--infer` 표본이 빠짐) → 반영. 미룬 권고 3건이 건전성에 영향 없음(후보는 최종 검증을 거치고, 느려지면 `verify_unknown`으로 거부될 뿐)도 확인했다.
- 측정 못 한 것: u8 함수의 증명 시간(R5), Windows·Linux 실행.

## 36. G2 A3: `[u8]` Rust 소스 실행 (2026-11-11)
`[u8]` 프로그램을 이제 Rust 소스 뒷단(`--backend rust`)에서 실행 코드로 만든다. LLVM 뒷단은 A4까지 codegen `unsupported_type`("the llvm codegen layer is not implemented")으로 거부한다(결정 16). 두 판이 같은 바이트를 내도록 생성 글자를 `docs/G2_A3_IMPL.md`에 고정했다.

- **생성:** 매개변수 `&[u8]`, 지역·반환 `Vec<u8>`, 읽기는 i64로 넓힘. 증명 모드는 `get_unchecked` + 증명된 값만 `as u8`(저장·alloc 두 곳). 안전 모드(`--no-verify`)는 `pruv_get_u8`·`pruv_set_u8`·`pruv_alloc_u8`이 검사한 뒤 줄인다: 저장은 색인 → 값, alloc은 길이 → 값(길이 0이어도 값 검사). 새 실패 문구 `pruv: element out of range: <v> (u8 0..=255)`(종료 101). requires 실행 검사의 원소 읽기는 `pruv_cidx_u8`(정렬 requires의 O(n) 다시 쓰기도 원소 타입을 이어받음).
- **기존 출력 불변:** u8 helper는 프로그램이 `[u8]`를 쓸 때만 덧붙인다. `[i64]`만 쓰는 프로그램의 생성 소스는 바이트 그대로다.
- **가드:** 드라이버는 순수 Rust 뒷단에서만 `[u8]`를 통과시키고, llvmgen을 쓰는 모든 길(`--backend llvm`, `--also-llvm`, Rust 판 `--emit ll/obj/exe`)은 거부한다. 생성기 자체 가드도 같은 기준(llvmgen 가드는 그대로).
- **범위 조정:** `runtime.c` 크기·정렬 일반화는 A4로 옮겼다. 런타임은 LLVM 뒷단만 쓰고, Rust allocator 판에 v2 host helper extern을 넣으면 아직 그 helper가 없는 기존 바인딩 링크가 깨지기 때문이다(v2 런타임과 v2 바인딩은 함께 들어가야 함).
- **표본:** 증명 통과 must_reject 10쌍을 지우고(이제 rust 뒷단에서 통과) 양성 표본으로 옮겼다. examples `g2a_u8_*` 11개(옮긴 8 + ASCII 정제 대문자화·루프 원소 변경·타입 alloc 3), runtime `g2a_rt_*` 15개(양 끝값, 읽기 확대, 256/-1 저장 거부, 길이 0 alloc 값 검사, alloc 길이 우선, 저장 평가·검사 순서, 복사 독립, 반환, 재대입·조기 반환, 정제 진입 검사, trust, 정렬 requires, `--infer` havoc, match 팔·호출 결과 색인). 이들의 llvm 행은 `tests/llvm_pending.txt`로 "llvm 층 거부"를 기대한다(A4에서 지움). G2_SPEC 8.2의 u8 항목을 덮고, bool 배치·raw bool은 A5·A4, i32는 A6.
- **회귀(마지막 실행):**
  - run_all `--backend both` 두 판 590/590(행 목록 590 = 488 − 10 + 112, 빠진 행·실패 0)
  - `--infer` 없는 SMT 231파일: 기준과 바이트 동일
  - diff_rust·diff_llvm 모두 same, cli_also_llvm 두 판 280/280
  - diff_trace 451(감사 반영 표본 1개 더하기 전): 플래그 없이 same 422·cex_only 29, `--infer` same 423·cex_only 26·same_unknown 2. 새 표본은 두 모드 모두 same(결정 11, 더한 1개도 단독 대조 same). 나머지 분류 수는 A2와 같다.
  - m3_all 9단계 ok(compilers 752), `tests/inference --regress` 두 판 252/252, 퍼저 seed 41×200 실패 0, cargo test pruv-core 42·`model::tests` 1
- **감사(Claude Opus):** 필수 0·권고 5, 모두 반영: Rust 정렬 다시 쓰기의 Index ty 고정을 명세 문구에 맞춤, Python prelude의 u8 사용 판정 한 번만, run_all pending 검사가 "llvm codegen" 층 문구와 목록 파일 존재까지 확인, cli_also_llvm pending이 rust 실행의 출력·파일까지 확인, match 팔·호출 결과 직접 색인 표본 추가.
- **확인 감사(Claude Opus):** 필수 0, 반영 5건 모두 맞음. 권고 1(cli_also_llvm pending도 층 문구 확인) → 반영.
- 측정 못 한 것: u8 함수의 증명 시간, 생성 코드 성능, Windows·Linux 실행.

## 37. G2 A4: `[u8]` LLVM 뒷단·`--rust-bindings`·런타임 v2 (2026-11-11)
`[u8]` 프로그램을 이제 LLVM 뒷단(`--backend llvm`, `--also-llvm`, Rust 판 `--emit ll/obj/exe`)과 `--rust-bindings`로도 만든다. 이로써 `[u8]`는 앞단·증명·두 실행 뒷단·ABI 전 층이 열렸다(`[bool]`은 A5까지 `unsupported_type`). 두 판이 같은 바이트를 내도록 IR·바인딩·런타임 글자를 `docs/G2_A4_IMPL.md`에 먼저 고정했고, 두 판은 첫 비교에서 바로 IR·바인딩 바이트가 같았다.

- **IR:** 집합체는 `{ ptr, i64 }` 그대로(길이 = 원소 수), u8 원소는 `i8`(크기·정렬 1·1), 읽기는 `zext` → i64, 저장은 `trunc` → `i8`. 배열 값·슬롯에 원소 타입을 싣고(매개변수·슬롯 load·alloc·copy·호출 결과에서 채움) GEP·load·store·복사·해제가 그것을 따른다. 안전 모드는 Rust 뒷단과 같은 순서·문구로 검사한다: 저장 색인 → 값(`icmp ule 255`), alloc 길이 → 값(길이 0이어도), `pruv: element out of range: <v> (u8 0..=255)`(종료 101). 증명 모드는 검사 없이 줄인다(`elem_range`가 증명). requires의 원소 읽기와 정렬 requires O(n) 검사도 `i8`로 읽는다. u8 선언 4줄은 u8 프로그램에만 붙여 **`[i64]`만 쓰는 프로그램의 IR은 바이트 그대로**다.
- **런타임 v2(`pruvc/runtime.c`):** 기존 `pruv_alloc/copy/free`·v1 host helper·v1 marker는 그대로 두고 `pruv_alloc_u8`·`pruv_copy_v2`·`pruv_free_v2`(원소 수·크기·정렬)·`pruv_panic_elem`을 더했다. 크기 계산은 곱하기 전에 배치(1·1/4·4/8·8)·`len <= 2^40`·`len*size <= SIZE_MAX`를 검사한다. Rust allocator 판은 v2 host helper(`pruv_host_alloc_v2`·`_zeroed_v2`·`pruv_host_free_v2`, `Layout(len*size, align)`)를 부르고 marker `pruv_runtime_rust_allocator_v2`를 정의한다.
- **바인딩:** `[u8]` 인자 `*const u8, len`, 반환 `Pruv__ArrayU8 { data: *mut u8, len }` out 포인터(기존 `Pruv__Array` 유지), 공개 함수는 `&[u8]`/`Vec<u8>`. v2 host helper 셋은 **모든 프로그램의 바인딩에 늘 들어가고**, 배열을 돌려주는 함수는 v2 marker를 참조한다. 그래서 바인딩 글자는 모든 프로그램에서 바뀌었다(G2_SPEC 5.4 호환성 3·4항: 재생성·재링크 필요). Windows CI 고정 결과물 `tests/abi/winci/out`을 다시 만들고 u8 표본 호출 목록을 더했다(48파일, `--check` 동일).
- **링크 시험(`tests/abi/check_runtime_v2.py`, m3_all `abi_v2` 단계):** 6경우 모두 기대대로 — 새 바인딩+새 런타임 성공(u8은 런타임 안 해제 ≥1·할당 = 해제 + 1), 새 바인딩+옛 런타임(`tests/abi/runtime_v1.c` = A3 런타임 사본) 실패(u8·i64 둘 다, v2 marker 없음), v2 helper를 뺀 옛 바인딩 흉내+새 런타임 실패, 새 바인딩+malloc 런타임 실패.
- **가드:** 드라이버·두 생성기 모두 모든 길에서 `array_u8`만 건너뛰는 하나의 가드로 합쳤다. `tests/llvm_pending.txt`를 지워 examples `g2a_u8_*` 11·runtime `g2a_rt_*` 15의 llvm 행이 "거부 기대"에서 실제 링크·실행 검사로 바뀌었다(행 목록은 그대로).
- **할당/해제 균형:** 종료 0인 u8 runtime 표본 6개에 `alloc_balance`를 붙였다(돌려준 배열을 Rust가 놓는 `g2a_rt_return`, 할당 0인 `g2a_rt_refine_trust`, panic으로 끝나는 7개는 제외). 새 표본 `g2a_rt_free_paths`: 루프 재대입, 분기 조기 반환(살아 있는 copy와 함께), 호출 결과 임시값, 지역 배열을 pruv 호출자에게 옮기는 반환, `[u8]` 인자 전달을 두 모드에서 돌리고 균형 + 함수 본문 IR 글자(`call void @pruv_free_v2(`·`call ptr @pruv_copy_v2(` 있음, i64 helper 없음)를 본다.
- **회귀(마지막 실행):**
  - run_all `--backend both` 두 판 594/594(행 목록 594 = 590 + 새 표본 4, 빠진 행·실패 0). 감사 반영 뒤 `--only runtime` 두 판 348행 실패 0
  - `--infer` 없는 SMT 231파일: 기준과 바이트 동일
  - diff_llvm 모두 same(두 판 u8 IR·바인딩 바이트 동일), m3_all 10단계 ok(compilers 760, rust·llvm·trace·trace_infer·standalone·abi·abi_v2 포함), cli_also_llvm 두 판 280/280, check_generated 통과(u8 반환 = out 포인터 + void)
  - 새 표본 diff_trace 두 모드 same(결정 11), `tests/inference --regress` 두 판 254/254, 퍼저 seed 41×200 실패 0, cargo test pruv-core 42
- **감사(Claude Opus):** 필수 0·권고 6, 모두 반영: u8 표본에 해제 helper IR 글자 검사(횟수만으로는 i64 크기 해제 퇴행을 못 잡음), requires u8 읽기에 통과 경우 더함(정렬·정제 진입), 링크 시험 판정 조임(런타임 안 해제 ≥1, 옛 런타임 u8은 marker 필수), 명세의 링크 실패 문구를 실제 보장 범위로 좁힘, `alloc_balance` 예외 기록, 옮기는 반환·인자 전달 경로 표본.
- **확인 감사(Claude Opus):** 필수 0, 반영 6건 중 5건 맞음. 권고 3: 해제·복사 helper 전체 .ll 검사가 u8 선언 줄 때문에 늘 참 → 함수 본문 `llvm_fn_contains`로 바꿈, 명세 링크 시험 표의 옛 균형 기준·기대 심볼 갱신, 명세 표본 설명에 새 경로 기록 → 모두 반영.
- **Windows CI(푸시 뒤, run 42986134593):** 통과 — 새 바인딩 12표본(u8 반환 `g2a_u8_ret` 포함)을 Windows에서 clang으로 객체화한 `runtime.c`(Rust allocator 판, v2 helper 포함)와 rustc(MSVC)로 링크·실행해 맥 기대 출력과 같음.
- 측정 못 한 것: u8 함수의 증명 시간과 생성 코드 성능, MSVC(`cl /std:c11`)로 런타임을 직접 컴파일하는 길(pruvc-rs 를 Windows에서 빌드할 때), Linux 실행.
