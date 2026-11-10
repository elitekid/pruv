# M3 = C4 설계: 독립 실행 컴파일러

**확정(2026-11-10), 설계 논쟁 반영. 기준 Python 커밋: `c4b352a`.** Python판은 정본으로 남기고 Rust판을 나란히 만든다.
근거는 `BLUEPRINT.md` 56~83·155~163줄, 언어 의미는 `SPEC.md`, 뒷단 경계는 M1·M2 명세다.
현재 동작은 `RESULTS.md` 7~12절과 코드가 기준이다. 특히 M0 계약 정의역·반복 예산·평가 순서 고침을 함께 옮긴다.
이 묶음은 설계 문서만 개정한다. 아래 구현 파일·명령·CI는 다음 묶음의 작업 지시이며 구현·실측 완료를 뜻하지 않는다.

## 1. 목표·범위·안 하는 것

`pruvc` 한 파일로 `.pruv`를 검증하고 실행 파일까지 만든다. 사용자에게 Python·rustc·IR 컴파일용 clang을 요구하지 않는다.
z3·LLVM은 컴파일러에 정적 링크한다. 생성 프로그램에는 필요한 실행 지원 객체만 링크하며 z3·LLVM은 넣지 않는다.
시스템 링커와 대상 C 런타임·SDK는 빌린다(BLUEPRINT 58줄). 따라서 개발 도구가 전혀 없는 OS에서의 링크까지 보장하지 않는다.

| 항목 | M3 결정 / 끝 기준 |
|---|---|
| 공개 대상 | macOS arm64 → Linux x64 GNU → Windows x64 MSVC → macOS x64 순으로 공개; 네 대상 모두 통과해야 M3 완료 |
| 언어 | Rust. Go는 z3·LLVM 모두 cgo 경계를 거쳐 정적 링크·크로스 빌드가 더 복잡하고, 기존 시험은 이미 rustc 사용 |
| 의미 보존 | 언어 기능 추가 없음. AST·검사·증명·Rust/LLVM 출력·실행 결과를 Python판과 대조 |
| 회귀 | 최종 기존 `--backend both` 363건을 두 컴파일러 각각 통과. Rust 소스 뒷단 완료 전에는 'LLVM 뒷단 행만' 별도 집계 |
| 독립 실행 | Pruv main에서 직접 만든 실행 파일의 출력·panic 101 확인; Python/rustc 없는 환경에서도 컴파일 |
| 범위 밖 | LLD 내장, Cranelift, inkwell, 셀프 호스팅, 새 최적화·증명 전략, 언어 확장, enum union 배치 |
| 배포 약속 | 단일 컴파일러 파일이지 완전 정적 OS 실행 환경이 아님. OS 라이브러리·링커·SDK 의존 공개 |

## 2. 크레이트 구성·의존·빌드 환경

`pruvc-rs/`를 별도 Cargo workspace로 둔다. 이름 충돌을 피하고 Python `pruvc/`는 계속 실행 가능하게 남긴다.
처음에는 세 크레이트로 나눈다. `pruv-core`(앞단·출력), `pruv-proof`(z3), `pruvc`(CLI·LLVM·링크).
라이브러리 API는 `parse → check → verify → gen`이고, 검사 뒤 AST는 읽기 전용이다. 코드 생성 중 AST를 수정하지 않는다.

| Python / 기존 파일 | Rust 위치(`pruvc-rs/crates/` 아래) | 담당 |
|---|---|---|
| `vast.py` | `pruv-core/src/ast.rs`, `diagnostic.rs` | 식 14·문 10·선언/보조 노드 9, 합계 33 구체 노드; Type은 이름 하나 |
| `vparser.py` | `pruv-core/src/lexer.rs`, `parser.rs` | 토큰·위치·재귀 하강·음수 리터럴 접기 |
| `typeinfo.py` | `pruv-core/src/typeinfo.rs` | 명목 타입·선언 순서·안정적인 의존 순서 |
| `check.py` | `pruv-core/src/check.rs` | 타입·효과·소유·재귀 금지·첫 오류 순서 |
| `codegen.py` | `pruv-core/src/codegen.rs`, `emit_common.rs` | Rust 출력은 마지막; 공통 `show`, `emit_public_types`, `match_sorted_requires`는 LLVM 단계에서 먼저 이식 |
| `verify.py` | `pruv-proof/src/{lib,model,symbolic,obligation}.rs` | z3 모델·상태·정의역·의무·반례 |
| `llvmgen.py` | `pruv-core/src/{llvmgen,abi,bindings}.rs` | 본체 텍스트 IR / 대상 wrapper / Rust 바인딩을 분리, 공통 출력 모듈 사용 |
| `pruvc.py` | `pruvc/src/{main,cli,driver}.rs` | 인자·출력 조정·JSON·종료 코드 |
| 새 객체/링크 층 | `pruvc/src/{lib,llvm,target,link,runtime}.rs`, 개발 도구의 `abi_lower.rs`(2026-11-11 제거) | LLVM C API·링크·내장 객체는 공유; IR ABI 후처리는 pruvc-ir-tool 전용 |
| `runtime.c` | `pruvc/build.rs`에서 원본을 읽음 | 별도 사본 없이 대상별로 컴파일해 `OUT_DIR`에 생성 |

AST는 enum+struct로 표현하고 재귀 식은 Box/Vec로 소유한다. `IndexMap`과 Vec로 선언·필드·함수·가정 순서를 보존한다.
HashMap/HashSet은 조회·포함 검사에만 쓴다. 순회 결과가 진단·이름·출력에 들어가면 반드시 순서를 정의한다.
정수 토큰은 부호+정규화 십진 문자열로 보관한다. i128도 넘는 입력을 lexer에서 거부하지 않고 checker의 `int_range`로 보낸다.
`-9223372036854775808`, 연속 단항 `-`, 밑줄을 Python처럼 처리한다(`vparser.py:47,396`, `check.py:335`).
line/col은 1부터, Python 문자열처럼 유니코드 문자 단위다. UTF-8 바이트 오프셋을 col로 쓰지 않는다.

### 의존 고정

| 의존 | 선택·고정 방법 | 근거 / 확인 관문 |
|---|---|---|
| `z3` | `=0.22.0`, `vendored` | 메인 결정. 시스템 libz3에 의존하지 않음 |
| `z3-src` | `=503.3.0`, Cargo.lock에서 z3-sys의 전이 의존까지 단일 버전 고정 | 시제품에서 실행 버전 `5.3.3.0` 확인(8절) |
| Python `z3-solver` | `==5.3.3.0` 개발 환경 고정 | 메인이 조사한 .venv 기준. 두 판의 실제 z3 전체 버전도 기록 |
| `llvm-sys` | 221.x, `force-static`; 시제품은 221.1.2로 빌드, 확정 잠금은 0B | LLVM 22 대응. `prefer-static`은 동적 링크로 조용히 넘어가므로 금지 |
| LLVM | 소스 `22.1.8`+소스 해시 / 설정 해시 고정 | 개발 Homebrew llvm@22와 배포 CI를 맞춤 |
| `indexmap`, `serde`, `serde_json` | 각각 2.x, 1.x, 1.x에서 선택 후 정확 버전과 Cargo.lock 커밋 | 순서·AST 덤프·JSON; 자동 의존 갱신 금지 |
| `cc`, `tempfile`, `find-msvc-tools` | 각각 1.x, 3.x, 0.1.x에서 선택 후 정확 버전과 Cargo.lock 커밋 | 빌드 때 C 컴파일, 임시 파일, Windows 링커·SDK 탐색 |
| Rust 도구 체인 | 첫 빌드에서 MSRV 확인 후 `rust-toolchain.toml`에 patch까지 고정 | LLVM/z3 크레이트의 요구 버전을 추측해 확정하지 않음 |

기준 코드 `c4b352a`와 0A 최소 정렬 변경의 차분·스냅샷, 시험 manifest SHA-256, 0B 확정 의존 잠금, 8절 시제품 환경 기록은 별개다.
manifest 해시는 0A에서 입력·플래그·기대값을 고정한 뒤 산출하며 이 문서에서 추정하지 않는다. 0B 산출물은 위 범위를 정확 버전으로 치환한
workspace Cargo.toml·Cargo.lock·도구 체인 파일·의존 소스 해시다. CI는 `cargo build --release --locked`로만 빌드한다.
`z3-src` 직접 지정이 전이 의존 제약과 맞는지 `cargo tree -e features`로 확인하고, z3가 두 벌이면 실패시킨다.
`gh-release`는 [z3#11266](https://github.com/Z3Prover/z3/issues/11266)의 5.3.0 이후 libz3.a 누락 신고 때문에 쓰지 않는다.
버전 고정은 버전 차이라는 변수를 없애는 조치다. 같은 버전이어도 빌드 옵션·플랫폼·질의 모양·시간 때문에 판정은 달라질 수 있다.

| 빌드 환경 | 사용 규칙 |
|---|---|
| `LLVM_SYS_221_PREFIX` | 정확한 LLVM 22 설치 prefix; 개발은 메인이 확인한 Homebrew llvm@22(22.1.8, .a 694개) |
| `CC`, `CXX`, `AR`, `CMAKE_GENERATOR`, `CMAKE_BUILD_PARALLEL_LEVEL` | z3/LLVM/런타임 빌드 도구·병렬 수 고정; 메모리 부족 시 병렬 수 제한 |
| `CC_<target>`, `AR_<target>` | cc 크레이트의 대상별 설정; host 도구를 cross 대상에 잘못 쓰지 않음 |
| `SDKROOT`, `MACOSX_DEPLOYMENT_TARGET` | macOS SDK·최소 OS 고정; 컴파일러·런타임·객체의 값 일치 |
| `RUSTFLAGS`, Windows CMake CRT 설정 | Windows는 `-C target-feature=+crt-static`, `/MT` 계열로 Rust·z3·LLVM·런타임 통일 |
| `OUT_DIR`, `HOST`, `TARGET` | Cargo 제공. 런타임 대상은 TARGET이며 빌드 스크립트 실행 호스트와 혼동 금지 |
| `PRUVC_LINKER`, `PRUVC_SYSROOT` (새 런타임 설정) | 사용자가 지정한 링커/대상 SDK; 자동 탐색보다 우선, 셸 문자열이 아닌 실행 경로로 취급 |

LLVM 개발 설치를 배포물로 복사하지 않는다. CI에서 `BUILD_SHARED_LIBS=OFF`, `LLVM_BUILD_LLVM_DYLIB=OFF`,
`LLVM_LINK_LLVM_DYLIB=OFF`, `LLVM_TARGETS_TO_BUILD=X86;AArch64`로 정적 묶음을 만들고 캐시한다.
불필요한 LLVM 도구·시험·예제·선택 압축/XML 의존은 끄거나 정적으로 공급한다. C++ 표준 라이브러리까지 실제 의존을 검사한다.
Windows 공식 배포 정적 lib은 [llvm-project#172890](https://github.com/llvm/llvm-project/issues/172890)의 libxml2s.lib 누락 신고가 있어 공급원으로 믿지 않는다.
위 로컬 설치·외부 신고·z3 버전은 메인이 제공한 조사 결과이며 이 문서 작업에서 외부 다운로드로 재검증하지 않았다.

## 3. CLI·출력 형식·대상 정책

```text
pruvc app.pruv -o app.rs               # M3 기본: 기존 Rust 소스 출력 유지
pruvc app.pruv -o app --emit exe
pruvc lib.pruv -o lib.ll --backend llvm # 기존 명령: .ll + 기본 lib.rs 바인딩
pruvc lib.pruv -o lib.rs --backend rust
pruvc lib.pruv -o lib.o --emit obj --rust-bindings lib.rs
pruvc app.pruv --emit exe --target x86_64-pc-windows-msvc -mcpu=generic
```

| 옵션 | 결정 |
|---|---|
| 입력, `-o` | 입력 하나. 텍스트·obj는 -o 필수; exe만 생략 시 입력 stem으로 출력. 입력과 출력 경로 중복 거부 |
| `--backend rust\|llvm`, 새 `--emit exe\|obj\|ll\|rs` | 아래 결정표로 내부 출력 종류 하나(rs/ll/obj/exe)에 합침. backend는 호환 별칭; 확장자 추론 없음 |
| `--rust-bindings PATH` | LLVM 전용. ll은 생략 시 기존처럼 확장자를 .rs로 바꿈; obj는 명시할 때만 생성, exe는 거부 |
| `--no-verify`, `--trust-callers` | 기존 그대로. 안전 모드 산술 검사·실행 requires·trust 의미 유지 |
| `--contract-budget N` | 숨은 시험 옵션 유지. 기본 2^30, 범위 1..2^62, 공개 진입 한 번의 공유 예산 |
| `--also-llvm LL RS` | 숨김 유지. 결정표 결과가 rs일 때만 허용; parse/check/verify 한 번 공유 |
| `--target TRIPLE` | 기본 호스트. 네 공개 triple만 허용; LLVM triple로 명시 변환. 지원하지 않는 대상은 exit 2 |
| `-mcpu=generic\|native\|NAME` | 기본 generic, 시험·bench는 native를 명시. native는 호스트 대상에서만, CPU 이름은 대상별 검증 |

| backend / emit | 생략 | rs | ll | obj | exe |
|---|---|---|---|---|---|
| 생략 | rs | rs | ll | obj | exe |
| rust | rs | rs | 사용법 오류 | 사용법 오류 | 사용법 오류 |
| llvm | ll | 사용법 오류 | ll | obj | exe |

M3에서는 두 판 모두 기본 Rust 소스와 기본 rs의 `-o` 필수를 유지한다. exe 기본 전환은 M3 뒤 별도 릴리스 결정(10절)이다.
`--also-llvm`은 parse/check/verify 한 번을 공유하고 검증 실패 시 아무 출력도 쓰지 않는다. 모든 텍스트 생성 성공 뒤 쓰는 원칙도 유지한다.
여러 출력 경로는 정규화해 중복을 막고 Windows 대소문자·기존 파일 별칭도 검사한다. 실패 시 기존 성공 파일을 새 산출물로 오인하지 않게 한다.

| 결과 | stdout / 종료 |
|---|---|
| 성공 | `{"ok": true}` 한 줄 / 0 |
| 언어·증명 오류 | PruvError JSON 줄 / 1. stage,line,col,code,message,fix[,counterexample], UTF-8 비ASCII 보존 |
| 사용법 오류 | 기존처럼 usage + stderr 상세 / 2; 오류 문장의 실행 파일 이름 차이만 대조 시 정규화 |
| 내부 결함 | stage=internal, code=internal_error, line=col=0 / 3 |
| 새 빌드 실패 | stage=link 또는 codegen의 JSON / 1; `linker_missing`, `link_failed`, `target_runtime_missing` 등 별도 목록 |

기존 오류 코드 66개(parse 5·check 46·verify 14·internal 1)는 별도 manifest로 고정한다. 새 빌드 진단은 이 목록을 재사용해 덮지 않는다.
성공·언어 진단은 stdout, 링커 상세는 진단에 요약하고 stderr에 원문을 남긴다. 파일 I/O 등 기존 내부 오류 경로도 차분 시험으로 고정한다.

## 4. 이식 순서·파일 경계·단계별 끝 기준

같은 파일을 두 작업자가 동시에 소유하지 않는다. 각 묶음이 인터페이스를 먼저 고정하고 다음 묶음이 소비한다.
workspace manifest·CLI 연결은 통합 담당만 고친다. 아래 `core`, `proof`, `bin`은 각각 2절 크레이트의 src다.

| 단계 / 묶음 | 독점 파일 경계 | 끝 기준·차분 지점 |
|---|---|---|
| 0A 최소 결정성·기준 | `pruvc/check.py`, `pruvc/verify.py`, `tests/diff_py_adapter.py` | 두 set 소비 순회만 정렬; 기준 스냅샷·manifest 해시·여러 hash seed의 진단/질의 순서 고정 |
| 0B 잠금·실의무 시제품 | workspace manifests/lock/toolchain, `ci/m3/`, z3 시제품 | Rust z3로 집계 보조정리·Opt/Res/사용자 Datatype·havoc·중첩 양화+patterns·재시도 재현; Python SMT-LIB·판정 대조, 정확 잠금·플랫폼별 정적 의존/비용 기록 |
| 0C 객체·링크 도구 선행 | `bin/{lib,llvm,target,link,runtime}.rs`, `bin/bin/pruvc-ir-tool.rs`, 도구 전용 `abi_lower.rs`(2026-11-11 제거), `pruvc/build.rs` | Python .ll→LLVM 객체→내장 runtime·시스템 링크; 시험 장치 IR용 clang 제거, i128 보조 기호 확인 |
| 0D Windows ABI 표본 | `tests/abi/`, `core/abi.rs` 계획 | 대상별 wrapper를 직접 출력한 작은 .ll→cross 객체·서명 검사, Windows 실행은 CI; 0A~0D 검토 후 파서 착수 |
| 1 파서 | `core/{ast,diagnostic,lexer,parser}.rs` | parse AST JSON·parse 오류 비교; 극대 정수·유니코드 위치·33 노드 모두 대응 |
| 2 검사 | `core/{typeinfo,check}.rs` | typed AST·타입 순서·type/effect 오류 JSON 동일, 재귀·소유 규칙 동일 |
| 3 검증기 | `proof/{lib,model,symbolic,obligation}.rs` | 의무별 첫 시도/재시도 SMT-LIB·판정·진단 비교, 승인 전 proof 모드 CLI 공개 금지 |
| 4 LLVM 출력·공통 함수 | `core/{llvmgen,abi,bindings,emit_common}.rs` | show·emit_public_types·match_sorted_requires·Rust 바인딩 선행, 원본 .ll·바인딩 이식 관문과 대상별 wrapper 기대값·M0/G1 회귀 |
| 5 객체·링크 통합 | 0C 파일 소유권 인계, `pruvc/runtime.c` | 직접 O2 객체·시스템 링크·main shim, 내장 런타임·MSVC count 초기화·링커 진단 |
| 6 Windows ABI 통합 | `core/abi.rs`, `tests/abi/` | Rust 생성기가 대상 ABI wrapper 직접 출력; sret C/Rust 호출·배열/집합 왕복을 Windows CI에서 통과 |
| 7 Rust 소스 출력(마지막) | `core/codegen.rs` | .rs 바이트 이식 관문, BLUEPRINT 6단계 여러 언어 출력 계획·기존 Rust 출력 시험 집계 유지 |
| T 차분 장치 | `tests/{compiler_driver,diff_compilers}.py`, 기존 호출 장치 5개 | 5절 선택 옵션·결과 분류·재현 산출물. 1~7과 인터페이스 단위 병렬 |
| I 통합·배포 | `bin/{main,cli,driver}.rs`, workspace 연결, `.github/workflows/m3.yml` | 기존 363·CLI 185·bench·변이·퍼징 및 독립 exe 관문 전부 통과 |

| 공유 상태·함수 경계 | 단독 소유·인계 조건 |
|---|---|
| verify.rs에 해당하는 proof 본체와 llvmgen.rs 본체 | 한 작업자가 전담; Model/fresh/가정/캐시 및 FnGen 임시 이름·스코프·해제·계약 환경을 함수별로 쪼개 병렬 수정하지 않음 |
| FnGen 근거 | `llvmgen.py:192–203·314–336·552–588·973–1023`; 식/문 평가·해제·계약 함수는 같은 가변 상태를 소비 |
| 병렬 담당 | 다른 작업자가 `abi.rs`의 ABI 계획·wrapper 출력, `bindings.rs`의 바인딩·`emit_common.rs` 공통 함수, 차분 도구·표본 담당; 본체 파일은 수정하지 않음 |
| 인계 | 읽기 전용 typed AST·TypeTable·ABI 계획→wrapper/바인딩 텍스트, typed AST→verify/gen, 의무 trace→차분의 함수 서명·형식·순서를 고정; FnGen 상태를 넘기지 않고 표본/영역 차분 통과·단독 소유권 명시 후 통합 |

0A를 M3에 포함한다. `check.py:134`는 호출 set 순회(`:143`에서 생성), `verify.py:671`은 assigned 시작,
`:686`의 havoc가 `:793`에서 만든 set을 순회한다. Python에서 두 소비 지점을 이름 사전순으로 정렬하고 Rust도 같은 순서를 쓴다.
선언 순서를 사전순으로 바꾸지는 않는다. 변경 전후 기존 363건·변이 판정을 재확인한 뒤 기준 커밋+최소 차분으로 정본 스냅샷을 갱신한다.
증명 시간·반례·복수 재귀의 첫 경로가 바뀌면 기록한다. hash seed를 하나 고정하는 것만으로 결정성을 해결했다고 보지 않는다.

## 5. 차분 대조 장치·시험 장치 연결

### 현재 호출 지점(이 문서 작성 시 코드 줄)

| 파일:줄 | 실제 호출 / 연결 | M3에서 바꿀 경계 |
|---|---|---|
| `tests/run_all.py:30,33,42` | PY/PRUVC 선택, `[PY,PRUVC,src,-o,out]` 실행 | 공통 compiler_driver 사용 |
| `tests/run_all.py:57,71` | runtime.c 변형별 캐시, .ll을 clang -O2로 객체화 | 새 비교 경로는 두 판 모두 내장 런타임·LLVM 객체 API |
| `tests/run_all.py:168,180,228` | LLVM 예제 링크, Rust 예제 lib, runtime Rust main 빌드 | rustc 시험 드라이버 유지 |
| `bench/harness/run.py:8,9,195,197,198` | PY/PRUVC, backend별 명령 구성·subprocess | 컴파일러 선택 인자를 build 경로까지 전달 |
| `bench/harness/run.py:107,111,138` | clang으로 IR·runtime, rustc -C target-cpu=native 링크 | 새 객체 경로, 같은 CPU·최적화 조건 |
| `bench/fuzz/run.py:42,45,236,263` | 안전·증명 호출 각각 --also-llvm, run_cmd(:60) | 검증 1회 유지, 컴파일러별 작업 폴더 |
| `bench/fuzz/run.py:87,383,448` | runtime 빌드, 심볼 고유화한 .ll 객체화, 배치 rustc 링크 | 재작성 후 LLVM API 객체화; prep_llvm은 pruvc 재검증 안 함 |
| `bench/mutate.py:45,49,55` | H.PY/H.PRUVC로 증명·안전 호출, H.build_and_run | 선택 정보를 H까지 전달, crash와 reject 구별 |
| `tests/cli_also_llvm.py:25,31` | sys.executable로 PRUVC 실행 | 선택 옵션 추가, 성공 출력·바이트·실패 무출력 검사 유지 |

`bench/fuzz/generate.py`는 seed:index로 입력을 만들고 `oracle.py`는 독립 파서·해석기다. 둘은 컴파일러를 호출하지 않으며 독립성을 유지한다.
시험 도구에 `--compiler py|rs`(초기 기본 py), `--compiler-path PATH`를 더한다. `--backend`는 계속 출력 뒷단 선택이다.
`tests/compiler_driver.py`가 argv 목록을 만든다(py=[고정 Python,PRUVC], rs=[바이너리]). 모든 호출은 backend를 명시한다.
Python 실행 경로는 Windows `.venv/Scripts/python.exe`도 지원하고 PATH의 도구 유무를 선검사한다. 셸 문자열 결합은 하지 않는다.
기존 시험의 Rust main은 그대로 유지한다. 개발·시험의 rustc 의존과 사용자 `--emit exe`의 무-rustc 경로는 별개다.
LLVM API 공통 함수를 쓰는 개발 전용 `pruvc-ir-tool`을 0C에서 `pruvc/src/bin/`에 둔다: 이미 생성된 ll→obj, 내장 runtime 추출·시스템 링크를 연결한다.
퍼저의 심볼 재작성 뒤 파일도 이 도구로 처리한다. 배포에 포함하지 않으며, 입력 IR을 검증된 Pruv라고 선언하는 기능은 없다.
Windows에서는 Python판도 이 도구로 대상 ABI 하강 후 객체화한다. 기존 clang 경로만으로는 Python판의 16바이트 반환 결함이 남는다. → 제거됨(2026-11-11, RESULTS 24절). Python 판 IR의 Windows 객체화는 지원하지 않는다.
`--input-abi legacy|target`은 이 도구 전용이다. Python 원본/대상별 직접 생성 IR을 구별하고 서명을 검사해 sret 이중 적용을 막는다. → 제거됨(2026-11-11, RESULTS 24절).
제한적 `abi_lower`와 `--input-abi`는 Python판 대조가 끝나면 제거한다. 배포 CLI·Rust 생성기 경로에는 넣지 않는다. → **제거함(2026-11-11, RESULTS 24절)**: ir-tool은 받은 IR을 그대로 객체화한다.
같은 객체화 층을 쓰는 비교는 앞단 이식의 차분 시험이다. 공유 층 자체의 ABI 정확성은 7절 C/Rust 독립 표본으로 따로 검증한다.

### `tests/diff_compilers.py` (새 도구)

같은 입력·플래그·대상·CPU·작업 부하에서 두 CLI를 별도 프로세스로 실행한다. 입력마다 새 프로세스를 써 model sequence를 맞춘다.
`tests/diff_py_adapter.py`와 Rust 시험 API가 parse/typed AST·검증 trace를 낸다(공개 CLI 규약 밖).
AST 시험 스키마 v1은 명시한 노드·필드·위치·타입·목록 순서만 직렬화한다. 역직렬화·범용 IR은 만들지 않고 변경 시 버전을 올린다.
입력 manifest에는 must_reject, examples(거부 예제 포함), runtime의 flags_matrix·contract_budget,
bench `solutions/pruv_agg` 10문제, 변이, 퍼저 생성 소스·입력·seed:index를 저장한다. 퍼저는 후보 목록을 먼저 고정해 병렬 제출 꼬리 차이를 없앤다.

| 비교 대상 | 통과 규칙 |
|---|---|
| parse/typed AST | 스키마에 명시한 kind·필드·위치·ty만 JSON 비교. 정수는 십진 문자열, null 보존, 객체 키만 정렬; 목록 순서 보존. TypeTable 의존 순서는 별도 비교 |
| 오류 JSON | 종료 코드·진단 수·순서·stage/code/line/col 필수 동일. message/fix도 비교, unknown 사유·도구 경로만 명시적 정규화 |
| .rs, .ll, bindings | 원본 생성기를 그대로 옮기는 동안 바이트 동일이 이식 관문(공백·이름·개행 포함). Windows Python text-mode CRLF만 별도 LF 정규화 보고 |
| 승인된 출력 변경 | 이후 개별 기대값 변경으로 관리. 대상별 Windows wrapper·exe main·triple/datalayout은 별도 기대 IR; ABI·안전 검사·평가 순서·실행 결과 관문은 계속 필수 |
| 증명 | 의무 ID·순서·첫 시도/재시도 각각 SMT-LIB 텍스트·sat/unsat/unknown 비교(6절); unknown은 성공 아님 |
| 반례 | 숫자 바이트 동일 요구 안 함. 아래 반례 판정으로 유효성·부분 정보·보조정리 생략을 구별 |
| 객체·exe | 바이트 동일 요구 안 함(LLVM/링커 차이). 같은 대상에서 exit·stdout·`pruv:` 진단 비교 |
| 실행 | 같은 backend·모드는 정확 비교. Rust panic 장식은 제외하고 pruv 줄 비교; proof/safe 교차는 oracle 기대가 같을 때만 |

반례는 공개 JSON만으로 완전 재실행할 수 없다: 배열은 앞 8개만, 상태에는 havoc 지역도 있고 `_note`는 집계 정의를 생략한 모델이다.
유한 스칼라·배열의 완전 입력은 독립 oracle로 위반을 재평가한다. 양화·havoc·relaxed는 원 질의(pc·guard·의무·보조정리)와 전체 모델/해석을 보존해 '미결'로 분류한다.
재평가할 정보가 부족한 경우도 `incomplete_cex`/`relaxed_cex`로 별도 집계한다. 미결 반례는 출시를 막지 않지만 수를 공개하고 유효 반례로 세지 않는다.
별도 모델 검증기 개발은 M3 범위 밖이다. 미결 반례와 기존 회귀의 증명 판정 불일치는 구별한다.
무효 반례·sat/unsat 충돌·검증 통과인데 oracle 계약 실패는 즉시 실패다. 모델 차이 자체는 실패가 아니다.
실패 폴더에 입력·argv·버전/해시·원출력·AST·IR·의무 SMT·모델·시간을 저장하고 `--replay`로 같은 사례를 재현한다.

### 세 시험 관문

| 관문 | 실행 범위·집계 |
|---|---|
| 작업 중 | 바뀐 영역만 차분·표본 실행; 매 수정마다 전체 회귀·bench·퍼징을 반복하지 않음 |
| 묶음 끝 전체 차분 | 두 컴파일러 × 기존 회귀 각 1번, 관련 CLI 시험. Rust 소스 뒷단 완료 전 'LLVM 뒷단 행만' 따로 세고, 최종 363건·CLI 185건 및 새 시험 별도 집계 |
| 이정표 | bench 10·변이 81 판정/코드, 퍼저 seed 41·56·57+새 seed(두 컴파일러×Rust/LLVM×proof/safe, 거부는 safe만, oracle limit은 incomplete), 네 플랫폼 정적 의존·직접 exe |

컴파일러 프로세스마다 timeout(예: 300초), 두 컴파일러를 합한 z3 동시 실행 상한은 CPU 수; 프로세스 시간 초과는 solver unknown과 별도 분류한다.
RESULTS 10·12절 회귀 약 50~106초를 기준으로, 같은 부하에서 두 컴파일러 전체 대조가 기준의 2배를 넘지 않는 것을 목표로 측정한다.
bench 성능은 조용한 머신에서 별도 측정하고 p04 기존 timeout은 정상 측정에서 뺀다. `tests/standalone/`은 main·IO·할당/해제·panic 101·예산·진입점/경로 오류를 검사한다.

## 6. z3 버전·결정성·시간 제한

| 지점 | Rust 재현 규칙 |
|---|---|
| 논리 | Int·Bool·Array(Int→Int)·Datatype·미해석 Function·ForAll/Exists(patterns 포함), substitute/simplify 유지 |
| 비사용 API | BitVec 전환·push/pop·rlimit 도입 안 함. 증명 전략 개선은 이식 뒤 별도 측정 |
| Datatype | 먼저 Opt/Res를 같은 이름·생성자 순서로 함께 생성. 사용자 타입은 TypeTable 의존 순서 |
| `_MODEL_SEQ` | 프로세스 시작 0, Model 생성마다 증가; `m1t0!Type` 등 그대로. 라이브러리 연속 호출도 Python과 같은 횟수로 증가 |
| fresh | 함수마다 k=0; fresh는 선증가해 `base!1`, 배열 길이는 `.len`. havoc 집합값은 기존 `name!h{k}` 후증가까지 재현 |
| 순서 | 소스 함수·매개변수·필드·변형·경로·가정·보조정리 순서 보존. 0A에서 정한 havoc/호출 집합 정렬만 적용 |
| sexpr 내부 키 | 집계 캐시 키(kind,Tc.sexpr(),outer 수)·보조정리 중복 키 그대로; Rust Display와 Python sexpr golden 검사, 단순 정규화로 차이를 덮지 않음 |
| solver | 의무마다 새 Solver(timeout=8000ms), pc→guard→Not(ob). unsat 아니고 lemmas가 있으면 새 Solver에 보조정리 추가해 재시도 |
| 모델 | `model_completion=true`; 환경 삽입 순서·사용자 타입 Pruv 표현 유지. relaxed sat 뒤 unknown의 `_note`도 유지 |

의무마다 첫 시도·재시도 각각 선언·assert 순서·patterns·solver 설정(timeout 포함)을 담은 SMT-LIB와 판정을 기록한다.
Python `Solver.sexpr()`/`to_smt2` 상당과 Rust의 같은 출력을 쓰되, 누락되는 solver 설정은 `set-option`(예: `:timeout 8000`)으로 함께 기록해 재생 시 적용한다.
텍스트 동일이 1차 기준이다. 다르면 양쪽 원문을 각각 같은 z3로 재생해 판정을 비교하고 차이 원인을 기록한다. 같은 SMT라도 시간 판정은 보장되지 않는다.
0B는 Int smoke를 넘어 실제 Pruv 의무 모양(집계 보조정리·Opt/Res/사용자 Datatype·havoc·중첩 양화+patterns·재시도)을 재현해 이 기준으로 검토한다.
z3 크레이트의 자동 평탄화·quantifier weight/pattern 변경도 이 trace로 확인한다.
필요한 저수준 API는 작은 z3-sys 래퍼로 한정하고 수명·context 소유를 감사한다. 의무 생성 중 병렬화하지 않는다.
timeout은 호출당 8초이므로 보조정리 재시도가 있으면 의무 하나가 약 16초를 쓸 수 있다. 전체 프로세스 제한과 혼동하지 않는다.
8초 부근 불일치는 원본 SMT·reason_unknown·경과 시간을 저장하고, 부하 없는 같은 환경에서 양쪽 각각 3회 재실행한다.
추가 긴 제한 실행은 원인 분석용이며 8초 관문의 통과를 대체하지 않는다. 시간만 다른 사례는 `inconclusive_timeout`으로 격리한다.
기존 고정 회귀의 판정 불일치가 남으면 M3 완료가 아니다. 퍼징의 미결 사례도 수·원인을 공개하고 통과 표본 수에서 뺀다.

## 7. LLVM 객체·링크·런타임·Windows x64 ABI

Rust 텍스트 생성기가 대상 ABI 계획으로 wrapper를 직접 출력한다. `LLVMParseIRInContext2` → 대상 triple/datalayout 설정·exe main 삽입 → `LLVMVerifyModule`
→ `LLVMRunPasses("default<O2>")`(TargetMachine 전달) → 재검사 → `LLVMTargetMachineEmitToFile` 객체 생성 순서다.
LLVM C API를 llvm-sys로 직접 부르고 메모리·오류 메시지 소유를 RAII로 감싼다. inkwell은 이식 표면을 늘리므로 나중 검토한다.
`--emit ll`은 최적화 전 직접 생성 텍스트다. 기존 macOS/SysV는 triple/datalayout 없는 출력을 유지하고, Windows는 대상 정보를 붙인다.
원본 이식 관문은 기존 ABI 출력에 적용한다. Windows 직접 출력은 별도 기대값이며 Python 원본과 바이트 동일 대상이 아니다.
`core/abi.rs`는 LLVM 의존 없는 대상 ABI 계획·wrapper 출력 함수다. `llvmgen.rs`가 이를 사용해 외부 `pruv_abi_*`를 처음부터 대상별로 출력한다.
IR 후처리 `abi_lower`는 Python 원본 IR을 Windows에서 객체화하는 개발 도구에만 제한한다(5절 종료 조건). Rust CLI 경로에는 없다. → 제거됨(2026-11-11, RESULTS 24절). Python 판 IR의 Windows 객체화는 지원하지 않는다.
ir-tool은 라이브러리 IR에 main을 삽입하지 않는다. 0C 링크 표본은 진입점이 있는 IR/독립 드라이버를 쓴다.
배포 CPU는 generic, host bench만 native; PIC/PIE·최소 OS·코드 모델을 대상 설정으로 고정하고 링크 설정과 맞춘다.

### 실행 파일과 런타임

exe는 `SPEC.md:45`의 인자 없는 unit main을 요구하고, 기존 효과 검사에 따라 IO/alloc을 처리한다. 잘못된 진입점은 exe 빌드 진단으로 거부한다.
같은 LLVM 모듈 안에 IR 진입 shim `define i32 @main()`을 삽입해 internal `main__pruv_entry`를 호출하고 0을 반환한다. trust 설정은 entry 생성에 그대로 반영한다.
Pruv 함수 본체·ABI 이름은 기존 mangling을 쓰므로 C main과 충돌하지 않는다. ll/obj 라이브러리 출력에는 C main을 만들지 않는다.
OS CRT가 main을 부르게 하며 `_start`/`mainCRTStartup`을 직접 구현하지 않는다.
`build.rs`는 cc로 대상 런타임 객체를 만들고 `include_bytes!`로 넣는다. exe 링크 때 전용 임시 디렉터리에 꺼내고 종료 시 정리한다.
기본 malloc/free와 `PRUV_RUST_ALLOCATOR` 두 변형, 각각 `PRUV_COUNT_ALLOCS` 시험 변형을 구별한다. exe는 malloc, Rust 드라이버는 Rust allocator다.
Rust allocator 객체의 `pruv_runtime_rust_allocator_v1` 연결 검사를 유지해 malloc 배열을 Vec가 해제하는 조합을 막는다.
Windows의 count 변형은 현재 GCC식 `__attribute__((constructor))`를 MSVC에서도 작동하는 초기화 경로로 옮기는 작업이 필요하다.
계약 i128 연산이 내는 `__divti3`·`__modti3`·`__multi3` 등 미해결 보조 기호를 대상별 조사한다. 시스템이 공급하지 않으면
동일 LLVM 버전의 compiler-rt builtins 중 필요한 정적 객체를 함께 내장한다(특히 MSVC). rustc가 우연히 보충한 경로에 기대지 않는다.
배포 기본은 해당 호스트 런타임만 내장한다. 다른 공개 대상의 ll/obj는 만들 수 있지만 exe는 해당 런타임·SDK·링커가 갖춰졌을 때만 허용한다.
다른 대상 런타임을 추가한 개발 빌드는 가능하되 보유 목록을 명시하고, 없으면 `target_runtime_missing`으로 실패한다.

| 플랫폼 | 링크·남는 사용자 의존 |
|---|---|
| macOS | xcrun으로 SDK/cc 탐색, cc를 링크 드라이버로 사용(내부 ld). Command Line Tools·SDK 필요 |
| Linux | cc 드라이버로 객체·CRT·libc 링크; 배포 기준 glibc 및 개발용 CRT/startup 객체·링커 필요 |
| Windows | find-msvc-tools로 link.exe·MSVC/UCRT/Windows SDK lib 경로 탐색, x64·CRT 일치; MSVC Build Tools 필요 |

macOS cc가 clang이어도 **IR 컴파일용 clang 호출은 없다**. 여기서는 시스템 링크 드라이버 역할만 빌린다.
컴파일러 개발에는 C/C++ 컴파일러·CMake·정적 라이브러리 빌드가 필요하지만 사용자는 runtime.c를 컴파일하지 않는다.
링크 인자는 argv/응답 파일로 전달하고 공백·한글 경로를 시험한다. LLD 내장은 미룬다(lld-rs LLVM 14 정체, 최신 연동은 C++ shim 필요).

### Windows x64 대상별 wrapper

M1 명세 4절(65줄 근처), RESULTS 124줄의 미완료 항목을 여기서 해결한다. triple만 붙인다고 C 구조체 반환 ABI가 자동 변환되지는 않는다.

| 함수 경계 | Windows x64 적용 |
|---|---|
| 외부 `pruv_abi_f`, 반환 Option/Result | `{i64,i64}`(16바이트) 반환 대신 처음부터 `void`+첫 숨은 `ptr sret({i64,i64}) align 8`로 출력 |
| 같은 함수의 Rust extern | `#[repr(C)] Pruv__Tagged` 값 반환 선언 유지; rustc의 MSVC C ABI가 숨은 첫 인자를 만든다 |
| 내부 body/entry | 자체 LLVM 집합 인자·반환 유지. 모두 같은 모듈/규칙으로 호출하므로 외부 C ABI 하강 대상 아님 |
| 배열 반환 | 기존 마지막 명시 out 포인터 + void 유지; 숨은 sret 추가 금지 |
| 사용자 구조체·열거형 | 기존 word 배열 포인터 인자/마지막 out 포인터 유지(크기 16바이트여도 예외 없음) |
| 스칼라·unit·Option/Result 인자 | i64/void 및 tag,payload 펼침 유지 |

`llvmgen.py:1214–1285` wrapper 부분을 옮기며 entry의 내부 `{i1,i64}` 결과를 tag zext한 두 i64로 만들어 sret 포인터에 저장한다.
직접 생성한 선언·정의·IR call site의 속성을 일치시킨다. 실제 숨은 포인터 반환 레지스터 처리는 LLVM 대상 하강에 맡긴다.
macOS arm64/x64·Linux x64의 기존 레지스터 반환은 유지한다. Python 원본의 Windows 후처리는 대조용 도구에만 남긴다.
Windows 전용 기대 IR은 C의 2×int64 구조체 반환을 cl/clang-cl로 만든 ABI 표본과 Rust extern 호출로 대조한다(개발 시험 도구).
Some/None·Ok/Err, MIN/MAX, 인자 0·1·5개(레지스터/스택 경계), 반복 호출, 구조체 내부 Option, 배열 반환을 네이티브 실행한다.
이 맥에서는 cross COFF 생성·LLVMVerifyModule·기호/서명 검사는 가능해도 Windows 실행 ABI를 검증할 수 없다. Windows CI 성공이 필수다.

## 8. 배포·CI·예상 비용

| GitHub Actions 실행기 | 산출물 / 필수 확인 |
|---|---|
| macOS ARM64 runner(`macos-14-xlarge` 등 ARM64 larger runner) | aarch64-apple-darwin; SDK·최소 OS·직접 실행 |
| macOS Intel runner(`macos-15-intel` 등 제공되는 고정 이미지) | x86_64-apple-darwin; 네이티브 회귀·직접 실행 |
| `windows-2022` x64 | x86_64-pc-windows-msvc; /MT 일치·sret 왕복·Build Tools 탐색 |
| `ubuntu-22.04` x64 | x86_64-unknown-linux-gnu; 기준 glibc·cc 링크·실행 |

runner 라벨 제공 여부는 CI 착수 때 확인하고 architecture assert를 넣는다. Intel hosted가 없으면 해당 self-hosted runner가 필요하다.
캐시 키는 OS/arch·Rust·LLVM/z3 소스 해시·CMake 설정·CRT·SDK·Cargo.lock을 포함한다. 라이브러리 캐시와 완성 바이너리를 구별한다.
출시 산출물은 대상별 pruvc 하나, SHA-256, 라이선스/NOTICE·빌드 정보다. universal macOS 합본은 필수 아님.
비용 상한은 대상별 strip 실행 파일 **150MB**, CI cold(LLVM 정적 묶음 포함) **120분**, 캐시 적중 **15분**이다.
플랫폼별 LLVM 정적 묶음 빌드 / 컴파일러 링크 / 회귀 시간을 따로 재고 전체 CI 시간·최대 메모리도 기록한다.
초과 시 LLVM 대상 X86·AArch64만 남기기·불필요 구성 끄기로 대상을 줄이거나 목표 개정을 결정한다. 동적 LLVM 배포는 BLUEPRINT 약속 변경이므로 대안으로 쓰지 않는다.
공개 순서는 macOS arm64 → Linux x64 → Windows x64 → macOS x64; 일부 공개 후에도 네 대상 모두 통과해야 M3 완료다.

**시제품 실측(2026-11-10, 이 맥 arm64 10코어, Homebrew llvm@22 22.1.8, ninja 없음)** — z3 =0.22.0 vendored + z3-src =503.3.0 ·
llvm-sys 221.1.2 force-static, release·thin LTO·strip. 하는 일: z3 Int 질의 하나, 텍스트 IR → `default<O2>` → 객체 → 시스템 `cc` 링크 → 실행.
아래는 **배포 잠금이 아닌 시제품 환경 기록**이다. 393초는 사전 설치 LLVM을 사용한 시제품 빌드이며 LLVM 정적 묶음 자체의 빌드 시간은 포함하지 않는다.

| 항목 | 값 |
|---|---|
| z3 실행 버전 | `5.3.3.0`(Python판 z3-solver 5.3.3.0과 같음) → 2절 버전 추정은 확인됨 |
| cold 빌드 | 393초(대부분 z3 C++), 코드만 바꾼 다시 빌드 6초 |
| 실행 파일 | 105MB(모든 대상 초기화 `LLVM_InitializeAll*`; 대상을 X86·AArch64로 줄이면 감소 예상, 미측정) |
| 동적 의존 | libc++·libz·libxml2·libiconv·libSystem(macOS 기본, 허용) + **`/opt/homebrew/opt/zstd/lib/libzstd.1.dylib`(배포 불가)** |
| API | `LLVMParseIRInContext`는 LLVM 22에서 사용 중단 경고 → 본 구현은 `LLVMParseIRInContext2` |

결론: Homebrew LLVM은 개발용으로만 쓴다. 배포 LLVM은 `LLVM_ENABLE_ZSTD=OFF`·`LLVM_ENABLE_LIBXML2=OFF`·`LLVM_ENABLE_ZLIB=OFF`(또는 정적 공급)로 직접 빌드하고
0B에서 위 의존 검사로 Homebrew 경로가 없음을 확인한다. Linux에서는 libc++/libstdc++·zlib도 정적이거나 기준 glibc 시스템 것만 남게 한다.
macOS `otool -L`, Linux `ldd/readelf`, Windows `dumpbin /dependents`로 libz3/LLVM DLL·dylib/so 의존이 없음을 확인한다.
Windows VC 런타임의 비시스템 DLL 의존도 검사한다. OS 기본 라이브러리는 허용하지만 Homebrew·빌드 디렉터리 경로 의존은 실패다.
서명·공증·설치 프로그램·자동 업데이트는 M3 범위 밖이다. 미서명 실행 경고가 남음을 릴리스에 밝히며 필요하면 배포 직전 별도 작업으로 한다.

## 9. 위험과 대응

| 위험 | 대응·확인 |
|---|---|
| z3 정적 빌드 시간/메모리 | vendored 캐시, 병렬 수 제한, cold/warm 분리 측정 |
| z3-src 버전 추정 오류 | 소스 해시·헤더·런타임 버전 교차 확인; 불일치면 구현 전에 잠금 재결정 |
| Windows CRT 불일치 | Rust/LLVM/z3/runtime /MT 통일, Rust 드라이버도 +crt-static, 의존 DLL 검사 |
| LLVM 정적 lib 공급 누락 | CI 직접 빌드·최소 의존 설정·모든 대상 링크 smoke; 공식 Windows 패키지에 의존 안 함 |
| 증명 시간 차이 | 같은 질의·8초·부하 통제, timeout 미결 분리; 긴 제한 성공으로 덮지 않음 |
| 반례 차이/부분 모델 | 유한 입력은 oracle 재평가, 양화·havoc·relaxed는 질의/모델 보존·미결 수 공개; 별도 모델 검증기 제외 |
| 비결정 순회 | 0A 정렬·IndexMap·seed 반복, Datatype/fresh/보조정리 순서 고정 |
| 사용자 링커/SDK 부재 | 탐색 실패를 설치 안내 JSON으로, Python·rustc 불필요와 SDK 필요를 분리 설명 |
| .ll 바이트 대조 깨짐 | 원본 생성기 이식 중 golden, 승인된 변경은 개별 기대값; ABI·안전·평가 순서·실행 관문 유지 |
| 런타임 할당기 혼합 | 내장 객체 변형 식별·marker 링크·배열 반환/해제·count 시험 |
| i128 보조 기호·MSVC C 구문 | 직접 exe 링크의 undefined symbol 검사·builtins 내장·count 초기화 이식 |
| CLI 호환 회귀 | M3 기본 Rust 소스 유지, backend/emit 단일 결정표·옛 옵션 조합 회귀 |
| cross 객체 성공을 배포 성공으로 오인 | 네 플랫폼 네이티브 실행 필수, 미실행 대상은 미완료 |
| 두 구현이 같은 결함 공유 | 독립 oracle 유지, 기존 회귀·변이·새 seed 병행; Python 일치만으로 건전성 주장 안 함 |

## 10. 열린 문제·다음 첫 구현 묶음

| 열린 문제 | 결정할 시점·판단 기준 |
|---|---|
| llvm-sys 221 patch·나머지 크레이트·Rust 최소 버전 | 0B 최소 빌드로 검증 후 정확 잠금. 이 문서의 버전 계열을 배포 lock으로 쓰지 않음 |
| 기본 exe 전환 | M3 뒤 별도 릴리스에서 호환 비용·이행 안내를 검토해 결정; M3는 기존 기본 유지 |
| llvm-mingw 후속 평가 | 초기 Windows 지원은 MSVC만. 같은 ABI·CRT·할당기·실행 표본으로 후속 평가하며 호환을 주장하지 않음 |
| cross exe 범위 | 타깃 런타임·SDK 재배포 권리와 공급 방식 확정 전에는 네이티브 exe만 공개 지원 |
| Linux 최소 glibc·macOS 최소 OS | 공개 지원 버전 확정 후 CI sysroot/SDK에 고정; 현재 runner에서 됨만으로 구형 OS 지원 주장 금지 |
| 서명·공증 | 필요하면 별도 배포 묶음; 비용 초과 대응은 8절 확정 규칙 적용 |

**첫 구현 묶음은 0A~0D+T**다. (a) 호출 그래프·havoc set 소비 정렬과 기준 스냅샷/manifest 해시를 만들고 기존 363·CLI 185·변이 판정 및 hash seed 0·1·2·random을 기록한다.
(b) 0B에서 Rust z3 실의무 시제품(집계 보조정리·Opt/Res/사용자 Datatype·havoc·중첩 양화+patterns·재시도)의 SMT-LIB·판정을 Python과 대조하고 의존을 잠근다.
(c) pruvc-ir-tool을 앞당겨 Python .ll을 LLVM 라이브러리로 객체화하고 내장 runtime·시스템 링커로 링크한다. i128 보조 기호를 확인하고 시험 장치의 IR 컴파일용 clang 의존을 M3 초기에 뗀다.
(d) 대상별 직접 출력 형태의 작은 .ll로 Windows ABI cross 객체·서명을 검사하고 실행은 Windows CI에서 확인한다. T는 argv 어댑터·비교·재현 저장부터 만들며 rs 미구현을 통과로 세지 않는다.
이 네 결과와 잠금·비용 기록을 검토한 뒤 본 앞단 이식(1 파서)에 착수한다. 이번 문서 개정에서는 구현·회귀 실행·네 플랫폼 빌드를 하지 않았다.

### 설계 논쟁 반영 기록

| 지적 13개 | 채택/수정 |
|---|---|
| 1. 결정성 기준 부재 | 채택: 0A 두 set 순회 최소 수정·기준 스냅샷(4·10절) |
| 2. z3 smoke 부족 | 수정: 실제 Pruv 의무·재시도 SMT-LIB/판정 시제품(4·6·10절) |
| 3. 객체화·ABI 위험 확인이 늦음 | 채택: ir-tool·내장 runtime 링크·i128·Windows cross 표본 선행(4·7·10절) |
| 4. 바이트 동일의 영구 제약 | 수정: 이식 관문으로 한정, 승인 기대값 변경·의미 관문 유지(5절) |
| 5. AST 시험 IR 과대화 | 수정: 버전 있는 명시 스키마 직렬화만, TypeTable 별도(5절) |
| 6. Rust 소스 뒷단 우선순위 | 수정: 유지하되 마지막, 공통 함수/바인딩 선행·LLVM 행 별도 집계(1·4·5절) |
| 7. 증명 대조 정보 부족 | 채택: 시도별 SMT-LIB·설정·판정과 동일 z3 재생, sexpr 키 보존(6절) |
| 8. CLI 기본값 호환 파괴 | 수정: 기본 rs 유지, 단일 결정표·exe 전환 후속 릴리스(3·10절) |
| 9. Windows 도구 체인 혼동 | 수정: MSVC 초기 한정, llvm-mingw는 같은 표본으로 후속 평가(1·10절) |
| 10. 배포 IR 후처리 복잡도 | 수정: 대상 ABI wrapper 직접 출력, abi_lower/input-abi는 개발 도구에서 대조 후 제거(5·7절) |
| 11. 비용·공개 범위 모호 | 채택: 150MB/120분/15분·분리 측정, 단계 공개·네 대상 완료(8절) |
| 12. 시험 비용·반례 검증 과대화 | 수정: 세 관문·프로세스 제한·z3 상한·미결 공개, 모델 검증기 제외(5·6절) |
| 13. 공유 상태·기준/잠금 혼동 | 채택: 본체 단독 소유·함수 인계, 커밋/manifest/0B 잠금/시제품 분리·2절 참조 수정(2·4·8절) |
