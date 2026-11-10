# tests/abi/winci — Windows x64 실행 ABI CI

## 목적
`docs/M3_C4_SPEC.md` 7절의 Windows x64 wrapper(Option/Result 반환 = void + 첫 숨은 sret)를 **네이티브로 실행**해 확인한다.
맥에서는 IR·객체·서명까지만 확인되므로(`tests/abi/check_generated.py`), 실행 확인만 Windows 러너에서 한다. 4개 플랫폼 배포 빌드는 하지 않는다.

## 맥에서 입력물 만들기 (결과물을 커밋)
```
python3 tests/abi/winci/prepare.py            # out/ 생성: *.win.ll *.rs *_main.rs *.expected
python3 tests/abi/winci/prepare.py --check    # out/ 이 커밋본과 같은지만 확인 (다르면 exit 1)
```
- 필요: Rust 판 pruvc(`pruvc-rs/target/release/pruvc`, `--pruvc` 로 변경), clang, rustc.
- 소스: `tests/abi/gen/*.pruv`(수정 안 함) + `src/*.pruv`. 호출은 `calls.json`(파일 이름 → 목록).
  `"f(인자)"` 는 Rust 식(`sol::f(인자)` 로 호출, 타입은 `sol::Cell {..}`), `{"repeat","args","n"}` 는 반복 호출 합계 한 줄.
- `.expected` 는 같은 소스를 **호스트 대상**으로 만들어 같은 드라이버로 맥에서 실행한 stdout 이다.
  Windows 결과가 이것과 한 글자라도 다르면 ABI 불일치.

## CI 가 하는 일 (`.github/workflows/windows-abi.yml`)
`run_windows.py`: `.win.ll` → clang `--target=x86_64-pc-windows-msvc -O2 -c`, `pruvc/runtime.c` → clang(`-DPRUV_RUST_ALLOCATOR`,
동적 CRT), rustc(MSVC)로 `<이름>_main.rs` 를 두 객체와 링크·실행, stdout 을 `.expected` 와 비교(표 출력, 불일치 시 exit 1).
추가로 `c_caller.c`(C 호출자)를 `args_0_1_5.win.obj` 와 링크해 실행(`--skip-c` 로 생략 가능).

## 무료 한도 안에서 쓰려는 설계
러너 1개(windows-latest), 매트릭스·캐시·설치 단계 없음(러너 기본 LLVM·Rust 사용), 컴파일러는 빌드하지 않고 맥에서 만든 산출물을 커밋,
`timeout-minutes: 20`, 트리거는 `workflow_dispatch` 와 관련 경로가 바뀐 main push 뿐. 예상 회당 10~20분.

## 확인 안 된 가정
이 폴더는 셸 없이 작성돼 한 번도 실행되지 않았다. 첫 실행에서 확인할 것: 소스 3개(`src/`)의 컴파일, runtime.c 가
MSVC 대상 clang 에서 빌드되는지, clang 의 `-fuse-ld=lld` C 링크(MSVC 라이브러리 경로 탐지), rustc 링크 경고.
