# M3 (C4) 0B: 의존 잠금 절차와 기록 항목

설계 근거: `docs/M3_C4_SPEC.md` 2절(의존 고정), 6절(z3 재현 규칙). workspace 는 `pruvc-rs/`.

0B 의 첫 산출물은 `Cargo.lock` 이다. 아래 절차는 `pruvc-rs/` 에서 실행한다.
`crates/pruvc` 가 아직 없으면 workspace 가 로드되지 않으므로 먼저 만들어 둔다.

## 1. 의존 잠금 절차

```sh
cd pruvc-rs

# 1) 잠금 파일 생성
cargo generate-lockfile

# 2) z3 계열이 한 벌인지 확인 (두 벌이면 실패로 본다)
cargo tree -e features -p pruv-proof -i z3-sys
cargo tree -e features -p pruv-proof -i z3-src
cargo tree -d            # 중복 버전 목록. z3-sys, z3-src 가 나오면 중단
#   - z3-src 는 503.3.0 하나, z3-sys 는 z3 0.22.0 이 요구하는 하나여야 한다.
#   - 직접 지정한 z3-sys(Cargo.toml 의 `z3-sys = "0"`)를 lock 에 나온 정확 버전 "=x.y.z" 로 바꾼다.

# 3) 정적 의존 확인 (vendored 로 libz3 가 실행 파일 안에 들어갔는가)
cargo build --release --locked -p pruv-proof --bin pruv-proof-spike
otool -L target/release/pruv-proof-spike        # Linux: ldd
sh ../ci/m3/check_deps.sh target/release/pruv-proof-spike

# 4) CI 와 같은 빌드 (자동 의존 갱신 금지)
cargo build --release --locked
```

- `cargo build --release --locked` 만 CI 빌드 방식이다. `--locked` 없이 `cargo update` 를 하지 않는다.
- `gh-release` 기능은 쓰지 않는다(SPEC 2절: z3#11266).
- `check_deps.sh` 는 `/opt/homebrew`, `/usr/local/Cellar`, 빌드 폴더 경로(`CHECK_DEPS_BUILD_DIR`, 기본 현재 폴더),
  `libz3`, `libLLVM` 이 의존 목록에 있으면 실패한다. 시스템 라이브러리(`libSystem`, `libc++` 등)는 통과한다.
- 스크립트에 실행 권한이 없으면 `sh ci/m3/check_deps.sh ...` 로 부른다.

## 2. spike 실행과 Python 대조

```sh
cargo run --release --locked -p pruv-proof --bin pruv-proof-spike -- --list
cargo run --release --locked -p pruv-proof --bin pruv-proof-spike -- s1_sum_loop     # JSON 한 객체
cargo run --release --locked -p pruv-proof --bin pruv-proof-spike -- --all           # 표본마다 한 줄(JSON Lines)

python3 tests/diff_py_adapter.py trace pruvc-rs/crates/pruv-proof/samples/s1_sum_loop.pruv   # 같은 형식
```

출력 형식:

```json
{"sample": "...", "obligations": [
  {"seq": 1, "fn": "...", "line": 8, "col": 22, "code": "invariant_entry",
   "attempts": [{"lemmas": false, "smt2": "(set-option :timeout 8000)\n...", "result": "sat|unsat|unknown"}]}
 ], "z3_version": "..."}
```

대조 시 맞춰야 할 가정(어긋나면 차이가 SMT 가 아니라 이 가정에서 온 것이다):

1. `seq` 는 표본 전체에서 1부터, `prove` 가 시도를 기록한 순서. `seen` 으로 건너뛴 의무는 기록하지 않는다.
2. `smt2` 는 **check 전에** `Solver.sexpr()`. 앞에 `(set-option :timeout 8000)\n` 을 붙인다.
3. havoc 변수 순서는 이름순(SPEC 6절의 0A 정렬). Python 쪽도 정렬 후 순회여야 한다.
4. 표본마다 새 프로세스: `_MODEL_SEQ` 가 0 에서 시작해 `m1t0!Point` 형식이 나온다.
5. Python 쪽 z3 는 `z3-solver==5.3.3.0`, 컨텍스트는 `Z3_mk_context_rc` + SMT-LIB2 출력 모드(z3py 기본). Rust 는 논-rc 컨텍스트
   + 같은 출력 모드이며 이는 텍스트에 영향이 없다고 가정한다.

## 3. 0B 기록 항목

측정 값 칸은 비워 둔다(`미측정`). 메인이 첫 빌드 뒤에 채운다.

| 항목 | 값 | 비고 |
|---|---|---|
| rustc / cargo 전체 버전 | 미측정 | `rustc -Vv`, `cargo -V`. 툴체인 파일은 1.99.1 |
| z3 crate 확정 버전 | 미측정 | 사양 `=0.22.0` |
| z3-sys 확정 버전 | 미측정 | Cargo.lock 기준 단일 버전, Cargo.toml 에 `=x.y.z` 로 고정 |
| z3-src 확정 버전 | 미측정 | 사양 `=503.3.0` |
| z3 실행 전체 버전(Rust) | 미측정 | spike JSON 의 `z3_version` |
| z3 실행 전체 버전(Python) | 미측정 | `z3.get_full_version()`, 사양 5.3.3.0 |
| `cargo tree -d` 의 z3 계열 중복 | 미측정 | 0건이어야 통과 |
| Cargo.lock SHA-256 | 미측정 | |
| z3-src / z3-sys 소스 해시 | 미측정 | `~/.cargo/registry` 의 `.crate` 파일 해시 |
| `otool -L` / `ldd` 결과 | 미측정 | pruv-proof-spike |
| `check_deps.sh` 결과 | 미측정 | 통과/실패와 발견 항목 |
| spike 첫 빌드 시간(release, 깨끗한 target) | 미측정 | z3 vendored 빌드 포함 |
| spike 실행 파일 크기 | 미측정 | strip 후 |
| 표본 6개 × (Rust, Python) 판정 비교 | 미측정 | 판정 불일치 수, 텍스트 불일치 수 |
| SMT 텍스트 동일 의무 수 / 전체 | 미측정 | 1차 기준(SPEC 6절). 다르면 양쪽 원문을 같은 z3 로 재생 |
| 8초 부근 불일치(inconclusive_timeout) | 미측정 | 원문·reason_unknown·경과 시간 저장, 각 3회 재실행 |
| z3 크레이트 고수준 API 와의 텍스트 차이 | 미측정 | 이 시제품은 sys 직접. 고수준 `forall_const` 는 weight/qid 가 다를 수 있음 |
| 메인이 sys.rs 에서 고친 곳 | 미측정 | 시그니처 차이 목록 |

## 4. 알려진 미확인 사항

- 이 문서와 소스는 컴파일 없이 작성되었다. z3-sys 시그니처 차이는 `crates/pruv-proof/src/sys.rs` 한 곳에서 고친다.
- Rust 판정과 Python 판정의 일치는 미측정이다. 표본은 증명 성공(unsat), 반례(sat), 첫 시도 sat → lemmas unsat 경로를 섞었으나
  어느 의무가 어느 판정이 될지는 z3 가 정한다.
