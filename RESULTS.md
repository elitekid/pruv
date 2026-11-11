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
