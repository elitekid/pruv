# Pruv

AI가 코드를 쓰고, 사람은 약속(계약)만 읽고, 컴파일러가 그 코드가 약속을 지킨다고 증명하는 언어.
증명된 안전장치(범위 검사, 오버플로 검사)는 지워서 빠르게 돌린다.

- 언어 명세: [SPEC.md](SPEC.md)
- 청사진(목표·단계 계획): [BLUEPRINT.md](BLUEPRINT.md)
- 실험 결과: [RESULTS.md](RESULTS.md)

## 지금 상태 (시제품 v0.1)
컴파일러 정본은 Rust 판 `pruvc`(`pruvc-rs/`)다. 단일 실행 파일이고 z3·LLVM을 정적으로 포함하며(macOS 빌드는 아직 Homebrew libzstd 에 동적으로 의존한다. 배포 빌드는 보류),
`--emit rs|ll|obj|exe` 로 Rust 소스·LLVM IR·오브젝트·실행 파일을 낸다.
Python 판 `pruvc/`는 대조 기준으로 유지한다(지우지 않고, 시험 도구의 대조 상대로 쓴다).
기본 시험은 Rust 판이 대상이다(배포 빌드는 보류).

### 빌드와 사용 (Rust 판)
```
cd pruvc-rs
LLVM_SYS_221_PREFIX=/opt/homebrew/opt/llvm@22 cargo build --release --locked
cd ..
pruvc-rs/target/release/pruvc examples/sum.pruv --emit exe -o sum     # 실행 파일
pruvc-rs/target/release/pruvc examples/sum.pruv --emit rs -o sum.rs   # Rust 소스
pruvc-rs/target/release/pruvc examples/sum.pruv --emit ll -o sum.ll --rust-bindings sum_bind.rs   # LLVM IR (+ Rust 바인딩 sum_bind.rs)
```
`--emit ll` 은 `--rust-bindings` 를 생략하면 `-o` 에서 확장자를 뗀 이름에 `.rs` 를 붙여(sum.ll → sum.rs) 바인딩을 쓰므로, 위 rs 예시의 sum.rs 를 덮어쓰지 않게 다른 이름을 준다.
`--emit exe` 는 `-o` 를 생략하면 입력 이름에서 확장자를 뗀 이름으로 쓰며(Windows 대상이면 `.exe` 가 붙는다), 시스템 링커로 링크한다(환경변수 `PRUVC_LINKER`가 있으면 그것, 없으면 macOS `xcrun --find cc`(없으면 `cc`), Linux `cc`). Windows 대상 exe 링크는 아직 지원하지 않는다(`.exe` 이름 규칙만 미리 있음). 그 밖의 옵션:
`--no-verify`, `--trust-callers`, `--contract-budget N`(시험용), `--target TRIPLE`, `-mcpu=CPU`, `--backend rust|llvm`, `--rust-bindings PATH`, `--also-llvm LL RS`(`--emit rs`와 함께, 시험용).
시험 도구(`tests/run_all.py` 등)는 기본으로 이 바이너리를 쓴다(`--compiler py` 로 Python 판, `--compiler-path` 로 다른 위치).

### 대조 기준 (Python 판)
Python 3.9 + z3 시제품이다: 파서 → 타입·효과 검사 → z3 증명 → Rust 코드 생성 → rustc.

```
python3 -m venv .venv && .venv/bin/pip install z3-solver
.venv/bin/python pruvc/pruvc.py examples/sum.pruv -o sum.rs && rustc -O sum.rs
```

### 새 기능 정책
새 언어 기능은 Python 판에 먼저 넣고(빠른 시제품·독립 대조), 같은 묶음에서 Rust 판에 이식해
`tests/m3_all.py` 대조를 통과시킨다. 기본 시험은 Rust 판이다(배포 빌드는 보류).

## 라이선스
MIT 또는 Apache-2.0 중 하나를 골라 쓸 수 있다([LICENSE-MIT](LICENSE-MIT), [LICENSE-APACHE](LICENSE-APACHE)).
특별히 밝히지 않으면 이 저장소에 보낸 기여도 같은 두 라이선스로 낸다.
Rust 판 실행 파일에는 z3(MIT)와 LLVM(Apache-2.0 WITH LLVM-exception)이 정적으로 들어간다. 실행 파일을 나눠 줄 때는 z3 의 MIT 고지문을 함께 둔다.
