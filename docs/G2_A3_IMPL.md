# G2 A3 구현 명세: `[u8]` Rust 소스 뒷단

상태: A3 묶음 구현 계약(메인 작성). 두 판(Python `pruvc/`, Rust `pruvc-rs`)은 아래 글자를 **바이트 그대로** 낸다. `tests/diff_rust.py`가 두 판의 생성 Rust 소스를 바이트로 비교한다.

## 0. 범위와 결정

1. A3는 **Rust 소스 뒷단**(`--backend rust`)에서 `[u8]`를 연다. LLVM 뒷단(`--backend llvm`, `--also-llvm`, Rust 판의 `--emit ll|obj|exe` 등 llvmgen을 쓰는 모든 길)은 A4까지 `codegen/unsupported_type`으로 거부한다(결정 16).
2. **`runtime.c`·`pruvc/src/runtime.rs`는 A3에서 고치지 않고 A4로 옮긴다.** 까닭: `runtime.c`는 LLVM 뒷단만 쓰며, `-DPRUV_RUST_ALLOCATOR` 판에 v2 host helper(`pruv_host_alloc_v2` 등) extern을 넣으면 그 helper를 아직 정의하지 않는 기존 바인딩과 링크가 깨진다. v2 런타임과 v2 바인딩은 같은 묶음(A4)에서 함께 들어가야 한다. A3에서 런타임에 넣을 수 있는 것은 아무 소비자 없는 죽은 코드뿐이라 넣지 않는다.
3. 기존 `[i64]`만 쓰는 프로그램의 생성 Rust 소스는 **한 바이트도 바뀌지 않는다**. u8 helper는 프로그램이 `[u8]`를 쓸 때만 따로 덧붙인다.
4. 안전 모드(`--no-verify`)의 새 실패 문구(5.3절 표의 접두어):
   `pruv: element out of range: <v> (u8 0..=255)` — panic, 종료 101(Rust panic). A4의 `runtime.c`도 이 문구를 쓴다.
5. 검사 순서(검증 의무 순서와 같다): 저장은 **색인 → 값 범위**, alloc은 **길이 → 값 범위**. alloc 값 범위는 길이가 0이어도 검사한다.

## 1. 공유 타입 질의(typeinfo)

Python `pruvc/typeinfo.py` / Rust `pruv-core/src/typeinfo.rs`.

- 지금의 `first_g2_unimplemented(prog)` 걷기(함수마다: 매개변수 → 반환 타입 → 본문 let, 깊이 우선·소스 순서)는 그대로 두고, **건너뛸 내부 이름 목록** `skip`을 받게 한다.
  - Py: `first_g2_unimplemented(prog, skip=())` — `is_array(ty) and ty != ARRAY and ty.name not in skip`인 첫 자리.
  - Rs: `first_g2_unimplemented(prog: &Program, skip: &[&str])`.
- `g2_unimplemented_error(prog, stage, layer=None, skip=(), fix=None)` (Rs: `g2_unimplemented_error(prog, stage, layer: Option<&str>, skip: &[&str], fix: Option<&str>)`):
  - 메시지: `"%s arrays are not supported yet: the %s layer is not implemented" % (type_name(ty), layer or stage)`
  - fix: `fix or "use [i64] for now"`
  - code `unsupported_type`, stage `stage`, 위치는 지금과 같음.
- 새 함수 `uses_array_type(prog, name)` (Rs: `uses_array_type(prog: &Program, name: &str) -> bool`): 같은 걷기에서 `ty.name == name`인 자리가 하나라도 있으면 참.
  - `[u8]` 값은 반드시 어떤 함수의 매개변수·반환·let 타입에서 나오므로(결정 6: alloc의 u8은 타입 적은 let·재대입·return 자리뿐) 이 걷기로 충분하다.
- 기존 호출부는 모두 새 인자를 기본값으로 넘겨 지금 동작을 유지한다(Rs는 `None, &[], None`).

## 2. 드라이버 가드

Py `pruvc/pruvc.py` `compile_file`, Rs `pruvc-rs/crates/pruvc/src/driver.rs` `compile`. 위치는 지금 가드 자리(verify 뒤, 생성 전) 그대로.

```
llvm 을 쓰는 길(Py: backend == "llvm" 또는 also_llvm; Rs: a.kind 가 Rs 가 아니거나 a.also_llvm 이 Some):
    g2_unimplemented_error(prog, "codegen", layer="llvm codegen", fix="use --backend rust or [i64] for now")
그 밖(순수 Rust 소스 뒷단):
    g2_unimplemented_error(prog, "codegen", skip=("array_u8",))
```

결과 진단(예):
`{"stage": "codegen", ..., "code": "unsupported_type", "message": "[u8] arrays are not supported yet: the llvm codegen layer is not implemented", "fix": "use --backend rust or [i64] for now"}`

생성기 자체 가드:
- `codegen.py` `gen_rust` / `codegen.rs` `gen_rust`: `g2_unimplemented_error(prog, "codegen", skip=("array_u8",))` — 메시지 형식은 지금과 같음(`unsupported_type: ...`).
- `llvmgen.py`·`llvmgen.rs`의 가드는 **고치지 않는다**(A4에서 푼다).

## 3. 타입 철자

`rty`(Py `codegen.py`, Rs `emit_common.rs`):

| 내부 이름 | param=True | param=False |
|---|---|---|
| `array` | `&[i64]` | `::std::vec::Vec<i64>` |
| `array_u8` | `&[u8]` | `::std::vec::Vec<u8>` |

`array_bool`은 여기서 다루지 않는다(파서가 아직 거부; 만나면 지금처럼 Py는 예외, Rs는 지금 동작 유지 — 단, Rs `rty`는 `other => other.to_string()`라 그대로 두면 됨).

## 4. 원소 타입 알아내기

- **읽기 `a[i]`(코드·계약 모두)**: `array_elem(e.array.ty)`(Rs: `array_elem_name(expr_ty(array))`). 검사기는 refine이 만든 노드까지 모든 식에 ty를 단다.
- **저장 `NAME[i] = v`**: IndexAssign에는 ty가 없으므로 생성기가 **변수 타입 표**를 가진다.
  - 함수 시작에 매개변수 이름→타입을 넣는다.
  - `Let`을 내보낼 때 그 이름→`st.type`을 넣는다.
  - `block`(문장 목록)마다 들어갈 때 표를 복사해 두고 나올 때 되돌린다(형제 블록의 같은 이름이 섞이지 않게).
  - 저장 대상 이름의 타입이 `array_u8`이면 u8 저장, 아니면 지금 그대로.
- **alloc**: Call 노드의 ty가 `array_u8`이면 u8 alloc(검사기가 결정 6의 세 자리에서만 그렇게 단다).
- **`match_sorted_requires` 다시 쓰기**(Py `cquant`, Rs 같은 곳): 새로 만드는 `Var(name=arr)` 두 개(`Index`의 array)에 **원래 배열 변수의 ty**(`e.hi`의 `len(a)` 인자 Var의 ty)를 넣고, 새 `Index` 노드의 ty는 원래 본문 `a[i]` Index의 ty를 넣는다(정수 배열 읽기의 ty는 늘 `i64`라 Rust 판은 `Some("i64")`로 둔다. 이 ty는 출력 글자에 쓰이지 않는다). 그래야 u8 배열의 정렬 requires가 `pruv_cidx_u8`을 고른다. `[i64]`의 출력 바이트는 바뀌지 않는다.

## 5. 생성 글자(정확한 문자열)

아래 `I`, `X`, `N`, `V`는 지금과 같은 식 생성 결과, `NAME`은 변수 이름, `AREF`는 지금 `arr_ref` 결과, `A`는 지금 읽기에서 쓰는 배열 식 결과다. `[i64]` 경로의 글자는 하나도 바꾸지 않는다.

### 5.1 증명 모드(verified=True)

| 자리 | `[u8]` 출력 |
|---|---|
| 읽기 `a[i]` | `((unsafe { *A.get_unchecked((I) as usize) }) as i64)` |
| 저장 `NAME[i] = x` | `{ let pruv_i: i64 = I; let pruv_x: i64 = X; unsafe { *NAME.get_unchecked_mut(pruv_i as usize) = pruv_x as u8; } }` |
| `alloc(n, v)` | `{ let pruv_n: i64 = N; let pruv_v: i64 = V; vec![pruv_v as u8; pruv_n as usize] }` |

(증명 모드의 `as u8`은 `elem_range`가 증명된 값만 받으므로 자르지 않는다.)

### 5.2 안전 모드(verified=False)

| 자리 | `[u8]` 출력 |
|---|---|
| 읽기 `a[i]` | `pruv_get_u8(AREF, I)` |
| 저장 `NAME[i] = x` | `{ let pruv_i: i64 = I; let pruv_x: i64 = X; pruv_set_u8(&mut NAME, pruv_i, pruv_x); }` |
| `alloc(n, v)` | `pruv_alloc_u8(N, V)` |

### 5.3 계약(requires 실행 검사, i128)

| 자리 | `[u8]` 출력 |
|---|---|
| 읽기 `a[i]` | `pruv_cidx_u8(ARR, I)` (`ARR`은 지금 `carr` 결과) |

`len`, `copy`(`X.to_vec()`), 함수 호출 인자, `return`, 재대입은 글자가 같다. 단 **호출 인자에서 배열을 빌려 넘기는 조건**을 `x.ty == ARRAY`에서 `is_array(x.ty)`로 넓힌다(Rs: `expr_ty(x) == Some("array")` → `is_array_name`).

### 5.4 덧붙이는 prelude

`uses_array_type(prog, "array_u8")`이 참일 때만 덧붙인다.

- 안전 모드: 출력 목록에 `SAFE_PRELUDE`를 넣은 **바로 다음 원소**로 `SAFE_PRELUDE_U8`을 넣는다.
- requires 실행 검사가 있을 때(`has_req and not trust`): `CONTRACT_PRELUDE`를 넣은 **바로 다음 원소**로 `CONTRACT_PRELUDE_U8`을 넣는다(계약 거울 타입 `ctypes`보다 앞).

Python 출력은 원소들을 `"\n"`으로 잇고 끝에 `"\n"`을 붙인다. 각 상수는 줄마다 `\n`으로 끝나므로 상수 사이에 빈 줄이 하나 생긴다. Rust 판은 같은 바이트를 내야 한다.

`SAFE_PRELUDE_U8`(정확한 글자, 마지막 줄도 `\n`으로 끝남):

```
#[allow(dead_code)]
#[cold]
#[inline(never)]
fn pruv_elem_oor(v: i64) -> ! { panic!("pruv: element out of range: {} (u8 0..=255)", v) }
#[allow(dead_code)]
#[inline]
fn pruv_get_u8(a: &[u8], i: i64) -> i64 { a[pruv_idx(i, a.len())] as i64 }
#[allow(dead_code)]
#[inline]
fn pruv_set_u8(a: &mut [u8], i: i64, v: i64) { let k = pruv_idx(i, a.len()); if v < 0 || v > 255 { pruv_elem_oor(v) } a[k] = v as u8; }
#[allow(dead_code)]
#[inline]
fn pruv_alloc_u8(n: i64, v: i64) -> ::std::vec::Vec<u8> { if n < 0 || n > (1i64 << 40) { pruv_ovf("alloc length outside 0..2^40") } if v < 0 || v > 255 { pruv_elem_oor(v) } vec![v as u8; n as usize] }
```

`CONTRACT_PRELUDE_U8`(정확한 글자):

```
#[allow(dead_code)]
#[inline]
fn pruv_cidx_u8(a: &[u8], i: i128) -> i128 { if i >= 0 && i < (a.len() as i128) { a[i as usize] as i128 } else { pruv_ud("array index out of range") } }
```

## 6. 시험(표본 담당)

- 증명 통과 `must_reject` 10개(`g2a_ok_param`·`g2a_ok_call_result`·`g2a_ok_loop_havoc`·`g2a_ok_loop_havoc_inf`·`g2a_ok_branch`·`g2a_ok_copy_store`·`g2a_a1_verify_layer`·`g2a_a1_guard_nested`·`g2a_a1_guard_nested_nv`·`g2a_a1_codegen_layer`)는 rust 뒷단에서 이제 통과하므로 `must_reject`에서 빼고 `examples/g2a_*`·`tests/runtime/g2a_*` 양성 표본으로 옮긴다.
- `tests/llvm_pending.txt`: 줄마다 저장소 기준 상대 경로 하나(`#` 줄·빈 줄 무시). 여기 적힌 표본의 **llvm 행**은 "pruvc 종료 1 + 진단 `codegen/unsupported_type`"을 기대한다(결정 16의 다음 층 거부 표본). A4에서 이 파일을 비우거나 지운다. 행 목록(row key)은 바뀌지 않는다.
- `tests/run_all.py`: examples·runtime의 llvm 작업이 위 목록을 따른다. `tests/cli_also_llvm.py`: 목록의 examples는 `--also-llvm` 실행이 종료 1·`unsupported_type` 진단·출력 파일 없음을 기대하고, 같은 표본의 순수 rust 실행은 종료 0이어야 한다.
