# G2 Q1 구현 명세: G2 문제 6개·채점기·G2 변이·퍼저 G2

상태: 구현 계약(메인 고정). 근거는 `docs/G2_SPEC.md` 0.0절 결정 11·12·15·17, 7.7절, 8.3절. Q2(측정·독립 작성자·`SPEC.md` 요약)는 이 문서 범위 밖이다.

## 0. 범위

Q1 은 G2_SPEC 8.3절(퍼저·변이) 관문을 닫는다. 변이의 참/거짓 자동 판정(결정 17)에 참조 시험이 필요하므로, Q2 독립 사용에 쓸 **문제 6개·참조 구현·채점기·참조 Pruv 풀이**를 Q1 에서 먼저 만든다(Q2 는 이 위에 독립 작성자 풀이와 측정만 더한다).

| 부분 | 파일(경계) |
|---|---|
| A. G2 문제·채점기 | `bench/g2/PROBLEMS.md`, `bench/g2/reference.rs`, `bench/g2/run.py`, `bench/g2/solutions/ref_pruv/q01..q06.pruv` |
| B. G2 변이 | `bench/g2/mutate_ops.py` (결과 `bench/g2/results/`) |
| C. 퍼저 G2 | `bench/fuzz/{generate,oracle,run}.py`, `bench/fuzz/README.md` (5절, 조사 뒤 고정) |

기존 `bench/mutate.py`·`bench/inference/mutate_infer.py`·`bench/g1/**`는 고치지 않는다(결정 17).

## 1. 문제 6개 (G2_SPEC 8.4 + 결정 15: i32 갱신 → u8 갱신)

모든 함수 이름·서명은 아래 그대로다. 채점기는 결과를 Rust `Debug` 문자열로 참조 구현과 비교한다. 입력은 항상 제약을 지킨다. 풀이는 검증을 통과해야 하고 panic 하면 안 된다.

| id | 서명 | 제약 | 뜻 |
|---|---|---|---|
| q01 바이트 범위 변환 | `fn clamp_bytes(a: [i64]) -> [u8] ! alloc` | 원소 아무 i64, `len(a) <= 1_000_000` | 같은 길이, `out[k] = min(max(a[k], 0), 255)` |
| q02 ASCII 필터 | `fn ascii_mask(a: [u8]) -> [u8] ! alloc` | `len(a) <= 1_000_000` | 같은 길이, `a[k] < 128` 이면 그대로, 아니면 63(`'?'`) |
| q03 u8 배열 갱신 | `fn add_sat(a: [u8], d: i64) -> [u8] ! alloc` | `-255 <= d <= 255`, `len(a) <= 1_000_000` | 같은 길이, `out[k] = min(max(a[k] + d, 0), 255)` |
| q04 bool 집계 | `fn longest_true_run(a: [bool]) -> i64` | `len(a) <= 1_000_000` | 연속한 `true` 의 가장 긴 길이(없으면 0) |
| q05 UTF-8 바이트 탐색 | `fn count_chars(s: str) -> i64` | `len(s) <= 1_000_000` | 문자(코드 포인트) 수 = 이어지는 바이트(128..=191)가 아닌 바이트 수 |
| q06 경계 기반 부분 문자열 | `fn prefix_chars(s: str, k: i64) -> str ! alloc` | `0 <= k <= 1_000_000`, `len(s) <= 1_000_000` | 앞에서 k 문자. 문자가 k 개보다 적으면 전체 복사 |

채점기 Rust 쪽 타입 대응: `[i64]`→`&[i64]`(입력 `Vec<i64>`), `[u8]`→`&[u8]`/`Vec<u8>`, `[bool]`→`&[bool]`/`Vec<bool>`, `str`→`&str`/`String`. rust 뒷단 생성물과 llvm `--rust-bindings` 생성물은 둘 다 이 서명의 `pub fn` 을 낸다.

## 2. A. `bench/g2/` 파일

### 2.1 `PROBLEMS.md`
`bench/g1/PROBLEMS.md` 와 같은 꼴(영어). 머리에 규칙: 풀이는 `qNN.pruv` 하나, 1절의 이름·서명 그대로, 보조 함수 허용, `requires` 로 제약을, `ensures` 로 뜻을 적을 것. 채점기 타입 대응 문단. 문제마다 서명·제약·뜻·작은 예 1~2개. 언어 규칙은 `SPEC.md` 를 보라고 적는다(Q2 에서 G2 요약이 들어간다).

### 2.2 `reference.rs`
신뢰하는 Rust 참조 구현. `pub fn clamp_bytes(a: &[i64]) -> Vec<u8>`, `pub fn ascii_mask(a: &[u8]) -> Vec<u8>`, `pub fn add_sat(a: &[u8], d: i64) -> Vec<u8>`, `pub fn longest_true_run(a: &[bool]) -> i64`, `pub fn count_chars(s: &str) -> i64`(= `s.chars().count()`), `pub fn prefix_chars(s: &str, k: i64) -> String`(= `s.chars().take(k as usize).collect()`). 외부 크레이트 없음.

### 2.3 `run.py` (채점기)
`bench/g1/run.py` 를 본뜬다. 다른 점:

- 사용: `run.py <solutions_dir> <out.json> [--backend rust|llvm] [--compiler py|rs] [--no-verify] [--trust-callers] [qNN ...]`. `--compiler` 기본 `py`. `py` = `[ROOT/.venv/bin/python, ROOT/pruvc/pruvc.py]`, `rs` = `[ROOT/pruvc-rs/target/release/pruvc]`. 두 컴파일러 모두 `IN -o OUT [--backend llvm --rust-bindings RS] [flags]` 를 받는다.
- 모듈로 import 해 쓸 공개 함수(B 가 쓴다, 이름·인자 고정):
  - `P`: dict, 키 `"q01".."q06"`.
  - `compile_pruv(compiler, src, workdir, backend="rust", flags=()) -> dict`: 컴파일만 한다. 반환 `{"rc": int, "errors": [JSON 오류 dict...], "rs": 경로, "ll": 경로 또는 None, "stderr": 끝 500자}`. timeout 600초면 `rc = -1`.
  - `build_and_run(sol_rs_path, pid, workdir, llvm_path=None) -> dict`: g1 과 같은 반환(`status` ok|wrong|compile_error|timeout, `tests_passed`, `tests_total`, `first_failure`, 실패 시 `exit_code`·`stderr`). 실행 timeout 120초.
- 입력: 문제마다 손으로 적은 EDGE 입력 + 무작위 300개(LCG seed 12345, `n = r.range(0, 50)`). Lcg 에 도우미 `bytes(n)`(0..=255), `bools(n)`, `utf8(n)`(문자 n 개, 아래 분포) 를 더한다.
  - `utf8` 문자 분포: 1/2 ASCII(0x00..=0x7F 전부, NUL 포함), 1/6 2바이트(U+0080..=U+07FF), 1/6 3바이트(U+0800..=U+FFFF 중 서로게이트 U+D800..=U+DFFF 제외), 1/6 4바이트(U+10000..=U+10FFFF). `char::from_u32(..).unwrap()`.
  - EDGE 최소: 빈 입력, 길이 1, 문제의 경계값(q01: `i64::MIN`, `i64::MAX`, -1, 0, 255, 256; q02: 127, 128, 255, 0; q03: d = ±255, 0, a 에 0·255; q04: 전부 true·전부 false·마지막이 가장 긴 run; q05: `""`, `"é"`, `"😀"`, `"a\u{0}b"`, `"한글"`; q06: k = 0, k = 문자 수, k > 문자 수, 4바이트 문자 사이 경계, `""`).
  - 입력 수는 문제마다 300 + EDGE.
- llvm 뒷단 빌드는 g1 의 `build_llvm_objects` 그대로(runtime.c 를 `-DPRUV_RUST_ALLOCATOR` 로).
- 출력·표 형식은 g1 과 같다.

### 2.4 `solutions/ref_pruv/q01..q06.pruv`
참조 Pruv 풀이. 두 컴파일러 모두에서 검증 통과(`--infer` 없이)·rust/llvm 두 뒷단 채점 300+EDGE 전부 통과가 끝 기준(메인이 실행해 확인). 반드시 `requires` 로 제약, `ensures` 로 뜻의 핵심(길이·범위·원소 관계 중 증명 가능한 것)을 적는다. 변이 시험의 원본이므로 **줄마다 한 가지 일**을 하게 쓴다(조건·경계·상수가 각각 다른 줄에 오면 변이가 잘 갈린다).

## 3. B. G2 변이 `bench/g2/mutate_ops.py`

### 3.1 사용
`mutate_ops.py OUT.json [SRC_DIR] [--jobs N] [--retry] [--only qNN ...]`. `SRC_DIR` 기본 `bench/g2/solutions/ref_pruv`. 결과는 `bench/g2/results/` 에 둔다(메인이 실행).

### 3.2 변이 연산(G2 전용 목록 `G2_OPS`)
각 항목은 `(이름, 함수)`이고 함수는 한 줄 문자열을 받아 바뀐 줄 목록을 돌려준다(바뀌지 않은 것은 버림). 계약 줄(`SKIP` 정규식: `^\s*(requires|ensures|invariant|decreases|fn |//)`)은 건드리지 않는다.

| 이름 | 바꾸기 | 근거 |
|---|---|---|
| `byte_const_pm1` | 정수 토큰 `127`·`128`·`191`·`192`·`255`·`256` 을 각각 +1·−1 | 저장 상한 ±1 |
| `guard_true` / `guard_false` | `if 조건 {` 의 조건을 `true` / `false` 로 (`else if` 포함) | 범위 가드 삭제 |
| `len_pm1` | `len(X)` 를 `(len(X) + 1)` / `(len(X) - 1)` (X 는 괄호 균형 맞춘 인자) | 색인 끝값 변경 |
| `substr_pm1` | `substr(s, lo, hi)` 의 lo·hi 를 각각 `(lo + 1)`·`(lo - 1)`·`(hi + 1)`·`(hi - 1)` (최상위 쉼표로 인자 분리) | 부분 문자열 경계 ±1 |
| `boundary_drop` | `is_char_boundary(..)` 호출을 `true` 로, `!is_char_boundary(..)` 는 `false` 로 | 경계 조건 삭제 |
| `conj_drop` | `while`·`if` 조건이 `A && B` 이면 `A` 만·`B` 만 (최상위 `&&` 하나씩) | 경계 조건 삭제 |

여기에 기존 `bench/mutate.py` 의 `OPS` 를 **mutate_infer.py 처럼 소스에서 읽어**(사본 없음) 이름 `base` 로 함께 돌린다. 같은 결과 텍스트가 둘 이상이면 하나로 합치고 이름을 모두 남긴다.

### 3.3 판정
변이마다:
1. 검증: 컴파일러 `py`·`rs` × `--infer` 없음·켬 = 4번, 뒷단 rust. 분류는 `mutate_infer.py` `classify` 와 같다(accepted / rejected / undecided(`inference_timeout`·`verify_unknown` 만) / crash(종료 0·1 밖, JSON 없는 1, `stage` internal, timeout 600초, 실행 실패)). `--retry` 면 undecided 를 직렬로 한 번 더.
2. 참/거짓(진실): `rs` 컴파일러 `--no-verify` rust 뒷단으로 컴파일 → `run.build_and_run`. `ok` → `true_mutant`(관측상 원본과 같음), `wrong`·`timeout` → `false_mutant`, 컴파일 거부 → `not_compilable`, 컴파일러 crash → `crash`. 모든 변이에 대해 한다.
3. 요약(`summary`): 연산별·문제별로 진실×판정 표, `false_accepted`(거짓 변이인데 4번 중 하나라도 accepted, 목록), `true_accepted`(수), `crash`(목록), `py_rs_verdict_diff`(목록), `undecided`(목록), `versions`(mutate_infer 와 같은 함수). 
4. 종료 코드: `false_accepted` 나 crash 가 있으면 1, 아니면 0.

관문(G2_SPEC 8.3): `false_accepted` = 0, crash = 0, 두 판 판정 차이 0(있으면 원인 기록). 참 변이의 통과는 오류로 세지 않고 수만 기록한다.

## 4. 기존 변이 corpus 저하 없음
메인이 31.1 과 같은 명령 `bench/inference/mutate_infer.py OUT bench/solutions/pruv_try1 bench/solutions/pruv_agg bench/inference/agg_noinv bench/g1/solutions/ref_pruv --jobs 8 --retry` 를 돌려 `mutate_infer_32.json`(298개, 두 판 없음 20/278, 켬 21/277) 과 판정이 같은지 본다.

## 5. C. 퍼저 G2

지금 퍼저는 G2 를 하나도 만들지 않는다(생성 타입 i64·bool·`[i64]`·Option/Result·사용자 타입, 오라클 렉서·`type_` 가 G2 를 `OracleParseError`·`OracleUnsupported` 로 거름). 세 파일은 `case` dict·입력 JSON·오라클 결과로만 이어지므로 아래 표현을 고정하고 파일마다 한 작업자가 고친다.

### 5.0 고정 규칙(세 파일 공통)
1. **기존 출력 불변.** `--g2` 없이 돌리면 `generate_case(seed, index)` 의 결과(`case` dict 전체)·`run.py` 의 동작·`summary.json` 키는 지금과 바이트 단위로 같다. G2 템플릿은 기존 `FAMILY`·재료 목록에 넣지 않는다(가중 선택이 바뀌어 옛 seed 프로그램이 달라진다).
2. **G2 모드.** `generate_case(seed, index, g2=False)`. `g2=True` 면 rng 를 `random.Random("g2:%s:%s" % (seed, index))` 로 따로 만들고 G2 템플릿 목록 `G2_TEMPLATES` 에서만 고른다.
3. **타입 문자열**(`case["params"]` 의 타입, `case["ret"]`): 새로 `"array_u8"`(`[u8]`), `"array_bool"`(`[bool]`), `"str"`. 정제 `[u8 | ..]` 는 퍼저에서 만들지 않는다(표본이 이미 덮음).
4. **입력 JSON 값**: `array_u8` = 0..255 정수 list, `array_bool` = bool list, `str` = JSON 문자열(Python `str`, 서로게이트 없음, 실행에 넘길 때 UTF-8 바이트).
5. **`case` 에 더하는 키**(g2 모드에서만): `"g2": True`, `"g2_features"`: 정렬된 태그 list. 태그: `u8`, `bool_arr`, `str`, `lit`(코드 안 문자열 리터럴), `substr`, `boundary`(is_char_boundary), `store_u8`, `alloc_u8`, `alloc_bool`, `ret_u8`, `ret_bool`, `ret_str`.
6. **반환값 비교 표현**: Rust 드라이버는 반환 타입이 `str` 이면 `println!("{:?}", R.as_bytes())`(바이트 정수 list), 그 밖은 지금처럼 `{:?}`. 오라클 `format_value` 는 str(내부 `bytes`)을 `[104, 105]` 꼴로, `[u8]` 은 정수 list, `[bool]` 은 `[true, false]` 로 찍는다. 빈 것은 `[]`.
7. **안전 모드 실패 문구**(종료 101, stderr 첫 `pruv: ` 줄의 앞부분 비교):

| 오라클 kind | detail | 기대 접두어 |
|---|---|---|
| `elem_range` | 값 v | `pruv: element out of range: v (u8 0..=255)` |
| `slice_range` | `"lo hi n"` | `pruv: string slice out of bounds: lo..hi (len n)` |
| `slice_cut` | `"lo hi n"` | `pruv: UTF-8 boundary error: lo..hi (len n)` |
| `oob` (str 색인 포함) | 지금과 같음 | `pruv: index out of bounds:` |

### 5.1 오라클 `bench/fuzz/oracle.py`(컴파일러 import 금지, 독립 해석)
- 렉서: 문자열 리터럴 `"…"`, 이스케이프는 `\" \\ \n \r \t \0` 만(그 밖은 `OracleParseError`). 값은 소스 문자의 UTF-8 바이트(`bytes`).
- `type_`: `[u8]`, `[bool]`, `str`. `[u8 | …]` 정제는 `OracleUnsupported`.
- 값: `[u8]` 은 int list, `[bool]` 은 bool list, `str` 은 불변 `bytes`. 함수 환경에 변수별 선언 타입을 둔다(매개변수·`let` 타입·함수 반환 타입).
- `alloc(n, v)` 좁은 타입(G2_SPEC 0.0 결정 6): 타입 적은 `let` 바로 오른쪽·그 변수 재대입 바로 오른쪽·`return` 바로 뒤에서만 그 배열 타입, 그 밖은 `[i64]`. `[u8]` 이면 **길이 검사 → 값 범위 검사**(길이 0 이어도 값 검사) 순서. 범위 밖은 `elem_range`.
- `[u8]` 원소 저장 `a[i] = v`: 지금의 평가 순서 그대로 두고 **색인 검사 → 값 범위 검사**.
- `copy`: 배열은 list 복사, str 은 같은 bytes.
- str: `len` = 바이트 수, `s[i]` = 바이트 정수(범위 밖 `oob`), `is_char_boundary(s, i)` = G2_SPEC 4.4 식(i==0 또는 i==n 또는 0<i<n 이고 바이트 <128 또는 >=192, 음수·n 초과는 false; 코드·계약 모두), `substr(s, lo, hi)`: `0<=lo<=hi<=n` 아니면 `slice_range`, 두 끝 중 하나라도 경계 아니면 `slice_cut`, 아니면 `s[lo:hi]`.
- 증명 모드에서도 위 실패는 같은 kind 로 나고, `run.py` 가 지금처럼 "검증 통과 + requires 만족 입력에서 실패 = unsound" 로 판정한다.
- 계약(`cev`): `len`·색인·`is_char_boundary` 를 str·`[u8]`·`[bool]` 에서. 계약 안 리터럴도 bytes.
- `expected_stderr_prefix`: 5.0 표.
- `_check_arg`: 새 타입의 입력 값 형식 검사(u8 범위, bool, str).
- `_selftest` 에 새 경우를 더한다(경계 식, substr 두 실패 순서, alloc 길이→값 순서, 리터럴 이스케이프, 다중 바이트 문자).

### 5.2 생성기 `bench/fuzz/generate.py`
- `G2_TEMPLATES` 최소 10개. 각 템플릿은 맞는 판(검증 통과 목표)을 기본으로, 확률 약 0.3 으로 G2 특유 오류 판(아래 "거부 판")을 만든다. 기존 `mutate`·`maybe_bad_ensures` 를 써도 된다.
  1. `[i64]`→`[u8]` 자르기 루프 저장(q01 꼴) / 거부 판: 상한 가드 없이 저장
  2. `[u8]` 매개변수 스캔(합·최대·개수, 원소 0..255 사실로 오버플로 증명) / 거부 판: 범위 밖 상수 비교 뒤 저장 등
  3. `[u8]` copy 뒤 원소 갱신(+d 포화) 반환 / 거부 판: 포화 한쪽 삭제
  4. `alloc` 으로 `[u8]` 만들어 반환(`ret_u8`, 값은 상수 또는 계산) / 거부 판: 초기값 256 등
  5. `[bool]` 매개변수 집계(개수·최장 run) 
  6. `[bool]` 만들어 반환(`alloc(n, false)` 뒤 조건 저장, `ret_bool`)
  7. str 매개변수 바이트 스캔(특정 바이트 개수·문자 수·첫 위치) / 거부 판: 색인 끝 +1
  8. str 경계 부분 문자열(`is_char_boundary` 로 가드 뒤 `substr`, 또는 다음 경계까지 전진 루프) 반환(`ret_str`) / 거부 판: 경계 가드 삭제, 끝 ±1
  9. 코드 안 문자열 리터럴(이스케이프·다중 바이트 포함)의 `len`·바이트·`substr`(리터럴 안 알려진 경계) / 거부 판: 다중 바이트 중간 자르기
  10. str → `[u8]` 바이트 복사(`alloc(len(s), 0)` 뒤 `out[i] = s[i]`, `ret_u8`)
  11. (선택) `requires is_char_boundary(s, i)` 를 둔 함수와 그 호출
- 리터럴 내용은 ASCII 인쇄 문자·`"`·`\`·개행·탭·NUL·2/3/4바이트 문자를 섞는다(오라클·Rust 소스 이스케이프 모두 시험).
- 입력 후보(`candidate_inputs`): `array_u8` 길이 0..8, 원소는 1/2 확률로 {0,1,127,128,191,192,254,255} 중, 아니면 0..255 균등. `array_bool` 길이 0..8. `str` 문자 0..8 개: ASCII 1/2(인쇄 문자 외 `\0`·`\n`·`\t`·`"`·`\\` 포함), 2·3·4바이트 각 1/6(서로게이트 제외). 정수 매개변수가 색인·경계로 쓰이면 0..len+1 근처 값과 -1 을 섞는다(`input_hints` 로).
- 식별자 규칙: `__` 금지, Rust 키워드 금지, `pruv_` 접두 금지, 같은 스코프 가림 금지. 코드 안 리터럴·copy·substr·alloc 이 있으면 서명에 `! alloc`. while 에는 invariant·decreases.
- `main`(`generate.py --seed S --count N --out DIR`)에 `--g2` 를 더한다.

### 5.3 실행기 `bench/fuzz/run.py`·`README.md`
- `--g2` 플래그: `generate_case(..., g2=True)`, 출력 폴더 이름 끝에 `_g2`. 입력 rng 이름도 `"g2:"` 접두.
- `batch_driver_source`: `array_u8` → `let aJ: Vec<u8> = vec![..];` + `&aJ`, `array_bool` → `Vec<bool>`, `str` → `let aJ: &str = "<이스케이프>";` + `aJ`(0x20..=0x7E 중 `"`·`\` 가 아니면 그대로, 나머지는 `\u{소문자hex}`). 반환이 `str` 이면 5.0 6번처럼 `.as_bytes()`. specs 에 반환 타입을 넘긴다.
- `signature_from_src`: `[u8]`·`[bool]`·`str` 반환과 매개변수를 잡는다.
- `prep_llvm` 등 llvm 경로가 str/u8/bool 바인딩(`Pruv__Str`, `pruv_check_utf8`, `pruv_check_bool`, `__typed`)과 함께 링크되는지 확인(필요하면 기호 재작성 목록에 더함).
- `deep_copy_arg`·`_check_arg` 연동: str 은 불변이라 그대로.
- 집계(`summary.json`, g2 모드에서만 키 추가): `g2_verified`(검증 통과이면서 `case["g2"]`), `g2_rejected_built_safe_modes`, `g2_features_verified`(태그별 검증 통과 수), `g2_inputs_per_program_min`. 관문: `--g2` 면 `g2_verified < --programs` 또는 `g2_rejected_built_safe_modes < --rejected-sample` 이면 `failures_by_kind["g2_shortfall"]` 에 숫자를 남기고 종료 1(결정 11). 오라클 unsupported·parse error·incomplete·timeout 은 통과 수에 넣지 않고 지금처럼 따로 센다.
- 입력 수: 프로그램당 `--inputs`(기본 8) 그대로. 입력이 8개에 못 미친 프로그램 수를 `g2_short_inputs` 로 센다.
- README: G2 모드 사용법·표현(5.0)·측정 기록 자리(메인이 채움).

### 5.3a 감사 반영(메인)
- `run.py` `FAULT_KINDS` 에 `elem_range`·`slice_range`·`slice_cut` 를 더했다(빠져 있으면 G2 안전 모드 실패와 증명 모드 건전성이 비교되지 않는다 — 감사 필수 1). 기존 경로는 이 kind 를 만들지 않으므로 동작이 같다.
- `g2_verified`·`g2_rejected_built_safe_modes` 는 **센 프로그램**만 센다: g2 case, 입력 `--inputs` 개 이상, 그 프로그램의 모든 모드(거절은 안전 모드) 실행 결과가 다 있음, 검증 통과분은 requires 만족이면서 오라클이 `limit` 아닌 입력이 하나 이상(감사 필수 2·권고).
- 그 몫으로 g2 모드에서만 검증 통과를 `--programs` 의 110%, 거절 표본을 `--rejected-sample + 5` 까지 모은다.
- 오라클 `narrow` 는 `(alloc(..))` 도 좁힌다(컴파일러와 같게, 권고). 생성기 정수 위반 입력을 `-1·-2·-7`, `L+1·L+2·L+5` 로 넓혀 입력 8개 미달을 줄였다.
- `mutate_ops.py` 진실 판정에서 rustc `compile_error` 는 `crash`(코드 생성 결함 후보)로 센다(권고).

### 2.4a 참조 풀이의 ensures(메인)
처음 판(ensures 가 길이뿐)으로 G2 변이를 재니 거짓 변이 39개가 검증을 통과했다. 컴파일러 결함이 아니라 계약이 뜻을 담지 않아서다. 그래서 q01~q06 의 ensures 를 PROBLEMS.md 의 뜻 전체로 바꿨다(원소별 값, q04 는 모든 true run ≤ 결과 + 결과 길이 run 존재(시작 위치 `start` 변수로 증인), q05 는 `count`, q06 은 앞부분 바이트 같음·끝 경계·경계 수 ≤ k·전체이거나 경계 수 = k).

### 5.4 끝 기준(메인 실행)
- `run.py --g2 --seed S --programs 200 --rejected-sample 30` (S = 41·56·57), 컴파일러 py·rs 각각: 실패 0, `g2_shortfall` 없음, 프로그램당 입력 8.
- `--g2` 없는 `run.py --seed 41 --programs 200` 실패 0, `generate.py --seed 41 --count 300` 출력이 고치기 전과 바이트 동일.
- `oracle.py` 자체 시험 통과.
