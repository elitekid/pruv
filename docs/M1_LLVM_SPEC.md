# M1 LLVM 뒷단 명세 (2026-11-10 확정)

`vowc --backend llvm`이 텍스트 LLVM IR(`.ll`)과 Rust 바인딩(`.rs`)을 낸다. 정본(의미 기준)은 `vowc/codegen.py`(Rust 뒷단)이고, LLVM판은 같은 프로그램에서 같은 출력·같은 오류 메시지·같은 종료 코드(101)를 내야 한다. `codegen.py`·`vast.py`·`check.py`·`verify.py`·`vparser.py`는 고치지 않는다.

## 1. 파일과 담당

| 파일 | 내용 |
|---|---|
| `vowc/llvmgen.py` (새) | `gen_llvm(prog, verified=True, trust_callers=False) -> (ir: str, rust_bindings: str)` |
| `vowc/runtime.c` (새) | 2절 실행 지원 함수 |
| `vowc/vowc.py` | `--backend rust|llvm`, `--rust-bindings PATH` |
| `tests/run_all.py`, `bench/harness/run.py`, `bench/mutate.py` | `--backend` 옵션, LLVM판 빌드·링크 |

## 2. runtime.c (C11, clang -O2 -std=c11 -c)

```c
#include <stdint.h>
int64_t *vow_alloc(int64_t len, int64_t value);   // len>=0 (호출자가 보장). len==0 -> NULL. len개를 value로 채움
int64_t *vow_copy(const int64_t *src, int64_t len); // len==0 -> NULL (src 안 읽음)
void vow_free(int64_t *data, int64_t len);        // NULL 또는 len==0 -> 무동작
void vow_print_i64(int64_t v);                    // "%lld\n" 를 stdout에, 매번 fflush(stdout)
void vow_print_bool(int64_t v);                   // "true\n"/"false\n", fflush
_Noreturn void vow_panic_oob(int64_t i, int64_t len);              // "vow: index out of bounds: <i> (len <len>)"
_Noreturn void vow_panic_arith(const char *detail);                // "vow: arithmetic error: <detail>"
_Noreturn void vow_panic_requires(const char *fn, const char *expr);// "vow: requires violated: <fn>: <expr>"
_Noreturn void vow_panic_undefined(const char *detail);            // "vow: requires undefined: <detail>"
```
- panic 계열: `fflush(stdout)` → 메시지+`\n`을 stderr에 → `exit(101)`.
- 할당 실패(또는 len*8 넘침): 기본(malloc) 모드는 `vow_panic_arith("allocation failed")`. Rust 할당기 모드는 바인딩의 `handle_alloc_error`가 abort한다(정본 `vec!`과 같은 동작).
- 할당 백엔드 두 가지:
  - 기본: `malloc`/`free`.
  - `-DVOW_RUST_ALLOCATOR`: 할당은 `int64_t *vow_host_alloc(int64_t len)`, 해제는 `void vow_host_free(int64_t *data, int64_t len)`(둘 다 Rust 바인딩이 정의, len>0일 때만 부름). `value == 0`이면 할당은 `int64_t *vow_host_alloc_zeroed(int64_t len)`(0 초기화 할당, 채우기 루프 없음; 기본 모드는 `calloc`). panic 함수는 맨 먼저 `void vow_host_flush(void)`(Rust stdout flush)를 부른다. 이 모드에서만 무동작 함수 `void vow_runtime_rust_allocator_v1(void)`를 정의한다(바인딩이 참조 → 잘못된 런타임을 링크하면 링크 실패).
  - `-DVOW_COUNT_ALLOCS`(시험용, 두 모드와 같이 쓸 수 있음): 성공한 할당 수와 null 아닌 `vow_free` 수를 세고, `atexit`로 stderr에 `vow-alloc-balance: <allocs> <frees>` 한 줄을 낸다.

## 3. 값 → LLVM 타입

| Vow | 내부 SSA | 비고 |
|---|---|---|
| i64 | `i64` | |
| bool | `i1` (alloca 슬롯은 `i1`이어도 됨) | |
| unit | `void` | |
| [i64] | `{ ptr, i64 }` (data, len) | 길이 0 소유 배열은 `{null, 0}` |
| Option<i64> | `{ i1, i64 }` | tag: Some=1, None=0. None payload=0 |
| Result<i64,i64> | `{ i1, i64 }` | tag: Ok=1, Err=0 |
| 계약 정수 | `i128` | 입력·원소·payload는 `sext` |

소유 여부는 IR에 태그로 넣지 않고 생성기가 컴파일 시간에 추적한다(배열 인자 = 빌림, alloc/copy/배열 반환 호출 = 소유).

## 4. 함수 이름과 호출 규약

함수 `f`마다 세 개를 낸다.

| 이름 | 연결 | 하는 일 |
|---|---|---|
| `@f__vow_body` | `internal` | 본문(증명 모드 또는 안전 모드) |
| `@f__vow_entry` | `internal` | trust가 아니고 requires가 있으면 선언 순서대로 requires를 i128로 평가해 실패 시 panic, 그다음 body 호출. 그 밖에는 body로 바로 넘김 |
| `@vow_abi_f` | 외부(C 호출 규약) | 외부 ABI 값을 내부 값으로 바꿔 entry 호출 |

- Vow 안쪽 호출: 증명 모드 → `f__vow_body`(호출자가 requires를 증명함), 안전 모드 → `f__vow_entry`.
- 내부 시그니처: 배열 인자는 `ptr, i64` 두 인자로 펼침. bool은 `i1`. Option/Result 인자·반환은 `{i1,i64}` 집합값. 배열 반환은 `{ptr,i64}` 집합값.
- 외부 ABI(`vow_abi_f`):
  - i64 → `i64`, bool 인자 → `i64`(0/1), 배열 인자 → `ptr, i64`, Option/Result 인자 → `i64 tag, i64 value`.
  - 반환: i64 → `i64`, bool → `i64`(0/1), unit → `void`.
  - 배열 반환 → `void`, 마지막 인자 `ptr out`에 `VowArray { int64_t *data; int64_t len; }` 저장.
  - Option/Result 반환은 `{i64,i64}` 값 반환(`{tag zext, payload}`, Rust 쪽은 `#[repr(C)] Vow__Tagged`를 `-> Vow__Tagged`로 받음; macOS arm64·SysV 전용; Windows x64는 16바이트 구조체를 숨은 포인터로 돌려주므로 M3에서 out-pointer로 되돌리거나 ABI 하강 필요).
    - 이유: p04 백만 회 호출에서 out-pointer 저장·읽기 비용을 측정했고, 값 반환이 그 비용을 없앤다.
  - 배열 반환만 out-pointer를 쓴다. `sret` 속성은 쓰지 않는다(명시적 out-pointer).
- IR에 target triple·datalayout은 넣지 않는다(clang에 `-Wno-override-module`).

## 5. 본문 하강

- 지역 변수·반환 슬롯은 entry 블록의 `alloca`(clang -O2가 승격). 루프 안에서 alloca 금지.
- 모든 기본 블록은 terminator 하나로 끝난다. return 뒤 죽은 문장은 내지 않는다(새 블록에 넣고 `unreachable`이어도 됨).
- `&&`, `||`는 단락 평가.
- `assert`, `invariant`, `decreases`, `ensures`는 실행 코드 없음.

| 연산 | 증명 모드 | 안전 모드 |
|---|---|---|
| `+ - *` | `add/sub/mul nsw i64` | `llvm.sadd/ssub/smul.with.overflow.i64`, 실패 → `vow_panic_arith("overflow in +")` 등 |
| 단항 `-` | `sub nsw i64 0, x` | `ssub.with.overflow(0,x)` → `"overflow in unary -"` |
| `/ %` | `udiv/urem` (검증기가 피제수>=0, 제수>0 증명) | `b > 0 && a >= 0` 검사 뒤 `udiv/urem`, 실패 → `"division outside domain: need divisor > 0 and dividend >= 0"` |
| 인덱스 읽기·쓰기 | 검사 없이 `getelementptr inbounds i64, ptr %d, i64 %i` | `0 <= i < len`(무부호 비교 하나로 가능) 성공 블록에서만 GEP, 실패 → `vow_panic_oob(i, len)` |
| `alloc(n, v)` | `vow_alloc(n, v)` | `0 <= n <= 2^40` 검사, 실패 → `"alloc length outside 0..2^40"` |
| `copy(a)` | `vow_copy(d, len)` | 같음 |
| `len(a)` | 배열의 len | 같음 |
| `print(x)` | `vow_print_i64` / `vow_print_bool(zext)` | 같음 |

- 실패 경로는 별도 블록에서 panic 호출 + `unreachable`. panic 선언에 `noreturn cold`.
- 평가 순서는 정본과 같다(`! io` 사용자 함수를 식 안에서 부를 수 있어 순서가 출력으로 드러난다). 인덱스 대입 `a[i] = v`: 안전 모드는 i → v → 범위 검사 → store(정본 `vow_set` 임시 순서), 증명 모드는 v → i → store(정본 `*a.get_unchecked_mut(i) = v`, Rust는 대입 오른쪽을 먼저 평가). `alloc(n, v)`: 증명 모드 v → n(`vec![v; n]`), 안전 모드 n → v.
- 증명 사실 표시: 증명 모드 본체에만 `nsw`, `inbounds`, `udiv/urem`. 안전 모드 본체에는 `nsw`를 붙이지 않는다(검사 성공 경로의 결과는 intrinsic 값 그대로).

## 6. 메모리 (Rust `Vec` drop과 같은 의미)

- 소유 배열 지역 변수는 선언된 블록이 끝날 때 선언 역순으로 `vow_free`. while 본문 지역은 매 회차 끝에 해제.
- 배열 변수 재대입 `a = f(...)`: 오른쪽 전체 평가 → 옛 값 해제 → 새 값 저장.
- `return`: 반환값 평가 → (지역 배열 변수를 반환하면 그 슬롯을 비워 이중 해제 방지) → 지금 열린 모든 스코프의 지역·임시 해제 → ret.
- 호출 결과 임시 배열(`len(f(x))`, `g(f(x))`, `f(x)[i]`, `copy(f(x))`, 조건식 안): 그 임시를 쓰는 문장(또는 조건 평가)이 끝나면 해제. `let`/대입/`return`의 오른쪽 최상위 호출 결과는 임시가 아니라 소유가 이동한다.
- 단락 평가에서는 실제 실행된 경로의 임시만 해제한다.
- 배열 인자는 빌림. 피호출자가 해제하지 않는다.
- panic(exit 101) 시 해제하지 않는다.

## 7. requires 실행 검사 (entry 함수, trust가 아닐 때)

- 메시지 식 문자열은 `codegen.show(expr)`를 그대로 쓴다(`from codegen import show`). 문자열은 IR 전역 상수(`private unnamed_addr constant [N x i8] c"...\00"`, 바이트 이스케이프 `\XX`).
- i128 평가: `+ - *`와 단항 `-`는 `llvm.s*.with.overflow.i128`, 실패 → `vow_panic_undefined("i128 overflow in +")` 등.
- `/ %`는 유클리드(z3 Int와 같음). IR 안의 내부 함수 `@vow_cdiv`, `@vow_crem`(i128): b==0 → `"division by zero in /"`/`"division by zero in %"`, a==MIN && b==-1 → `"i128 overflow in /"`/`"i128 overflow in %"`, 그 밖에 sdiv/srem 뒤 나머지가 음수면 보정(b>0이면 q-=1, r+=b; b<0이면 q+=1, r-=b).
- 계약 인덱스 `a[i]`: i128 상태에서 `0 <= i < len` 확인 뒤 읽음, 실패 → `"array index out of range"`.
- `some_val`/`ok_val`/`err_val`: 태그 확인, 실패 → `"some_val of None"`, `"ok_val of Err"`, `"err_val of Ok"`.
- Option/Result `==`/`!=`(계약에서만 가능): 태그가 다르면 다름, 둘 다 None이면 같음, 아니면 payload 비교.
- `==>`는 `!a || b`(단락).
- 한정자 `kind var in lo..hi: body`: lo, hi를 바깥에서 한 번 평가, 반복 변수 i128, `[lo, hi)`, lo>=hi면 빈 구간.
  - forall: true, 거짓 만나면 중단. exists: false, 참 만나면 중단.
  - sum: i128 0에서 checked add(`"i128 overflow in +"`).
  - count: i128 0에서 참일 때 +1 (정본처럼 검사 없음, nsw 없음).
  - max/min: 첫 값으로 시작, 빈 구간 → `"max over an empty range"`/`"min over an empty range"`.
- requires 여러 개는 선언 순서대로, 첫 실패에서 panic.

## 8. Rust 바인딩 (`.rs`, `#[path] mod sol;`로 들어감)

- 함수마다 Rust 정본과 같은 공개 시그니처: `pub fn f(a: &[i64], x: i64) -> Option<i64>` (배열 인자 `&[i64]`, 배열 반환 `Vec<i64>`, bool, `Option<i64>`, `Result<i64, i64>`, unit은 반환형 없음).
- `extern "C"` 블록에 `vow_abi_*` 선언(`#[link_name]` 없이 같은 이름 써도 됨), 공개 래퍼는 `#[inline]`.
- 배열 반환: len>0이면 `Vec::from_raw_parts(data, len, len)`(Rust allocator로 할당됐으므로 안전), len==0이면 `Vec::new()`.
- Option/Result: 태그로 Rust 생성자 생성(transmute 금지).
- `io` 효과(`f.effects`에 "io")가 있는 함수는 호출 전에 `std::io::Write::flush(&mut std::io::stdout())`.
- 할당 연결: 바인딩이 `#[no_mangle] pub extern "C" fn vow_host_alloc(len: i64) -> *mut i64`와 `vow_host_free(data: *mut i64, len: i64)`를 정의(`std::alloc::alloc`/`dealloc`, `Layout::array::<i64>(len)`; 실패 시 `std::alloc::handle_alloc_error`), `vow_host_alloc_zeroed`(`alloc_zeroed`), `vow_host_flush`(`std::io::stdout().flush()`, 결과 무시). 배열을 반환하는 함수가 하나라도 있으면 `extern "C" { fn vow_runtime_rust_allocator_v1(); }`를 참조해(예: 래퍼 안에서 함수 포인터를 `black_box`) 잘못된 런타임 링크를 막는다.
- 경고 억제: 각 항목에 `#[allow(dead_code, non_snake_case, unused)]`. Rust 2021 판.

## 9. CLI와 빌드 명령

```
python vowc/vowc.py in.vow -o out.ll --backend llvm [--rust-bindings out.rs] [--no-verify] [--trust-callers]
```
- `--backend` 기본 rust. llvm이고 `--rust-bindings`를 생략하면 `-o` 경로의 확장자를 `.rs`로 바꾼 곳(같으면 거부).
- rust 뒷단에 `--rust-bindings`를 주면 사용법 오류(exit 2). 언어 오류는 지금처럼 JSON 줄 + exit 1, 성공은 `{"ok": true}`.
- 시험 장치 빌드(LLVM판):
  1. `clang -O2 <cpu> -Wno-override-module -c gen.ll -o gen.o`
  2. `clang -O2 <cpu> -std=c11 -DVOW_RUST_ALLOCATOR -c vowc/runtime.c -o rt.o`
  - `<cpu>`: arm64(`platform.machine()`이 arm64/aarch64)는 `-mcpu=native`, 그 밖에는 `-march=native`.
  3. 지금 rustc 명령에 `-C link-arg=gen.o -C link-arg=rt.o` 추가, `mod sol`은 바인딩 `.rs`.

## 10. 시험 장치

- `tests/run_all.py --backend rust|llvm|both` (기본 rust). examples·runtime 시험을 고른 뒷단으로 돈다. 거부 시험은 뒷단과 무관하게 한 번.
  - LLVM판 examples: 세 모드로 `.ll` 생성 → clang 오브젝트 → 바인딩을 `mod sol`로 넣은 빈 `fn main(){}` 실행 파일 링크 성공이면 통과.
  - `--no-verify`의 "unsafe 없음" 검사는 Rust판에만. LLVM판 안전 모드에서는 대신 `.ll`에 `nsw`가 없음을 검사.
  - runtime JSON의 `gen_contains`는 Rust판 전용. LLVM판용 `gen_contains_llvm`(선택)을 읽는다.
- `bench/harness/run.py --backend rust|llvm`, `build_and_run(sol_path, pid, workdir, noperf=False, llvm_path=None)` (llvm_path가 있으면 LLVM판 링크). 실행 파일이 0이 아닌 코드로 끝나면 `wrong`(+`exit_code`), noperf가 아니고 모든 시험이 통과했는데 PERF가 없으면 `wrong`.
- `bench/mutate.py <src> <out> [--backend llvm]`: 증명 빌드와 `--no-verify` 빌드 모두 같은 뒷단.
