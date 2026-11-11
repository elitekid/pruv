# G2 A4 구현 명세: `[u8]` LLVM 뒷단·`--rust-bindings`·런타임 v2

상태: A4 묶음 구현 계약(메인 작성). 두 판(Python `pruvc/llvmgen.py`, Rust `pruv-core/src/llvmgen.rs`·`abi.rs`·`bindings.rs`)은 아래 글자를 **바이트 그대로** 낸다. `tests/diff_llvm.py`가 두 판의 IR과 바인딩을 바이트로 비교한다. 근거: `docs/G2_SPEC.md` 0.0절, 5.2·5.3·5.4절. A3 명세 `docs/G2_A3_IMPL.md`의 안전 모드 문구·검사 순서를 그대로 따른다.

## 0. 범위와 결정

1. A4는 llvmgen을 쓰는 모든 길(`--backend llvm`, `--also-llvm`, Rust 판 `--emit ll|obj|exe`)에서 `[u8]`를 연다. `[bool]`(`array_bool`)은 계속 `unsupported_type`으로 거부한다(A5).
2. **기존 `[i64]`만 쓰는 프로그램의 IR은 한 바이트도 바뀌지 않는다.** u8용 선언(`DECLS_U8`)은 프로그램이 `[u8]`를 쓸 때만(`uses_array_type(prog, "array_u8")`) 덧붙인다.
3. **바인딩은 모든 프로그램에서 바뀐다**(G2_SPEC 5.4 호환성 3·4항): v2 host helper 세 개를 늘 정의하고, 배열을 돌려주는 함수가 있으면 marker를 `pruv_runtime_rust_allocator_v2`로 참조한다. 까닭: `-DPRUV_RUST_ALLOCATOR` 런타임이 v2 host helper를 extern으로 부르므로, 그 런타임과 링크하는 모든 바인딩이 helper를 정의해야 한다. 새 바인딩 + 옛 런타임은 배열을 돌려주는 함수가 있거나(v2 marker) v2 런타임 함수를 쓰면 링크가 실패하고, 옛 바인딩 + 새 런타임은 v2 host helper를 부르는 런타임 코드가 링크에 남으면 실패한다. 둘 다 아닌 조합은 링크될 수 있으나 그때는 v1 경로만 쓰이므로 안전하다(보장 범위는 G2_SPEC 5.4 호환성 4항: 재생성·재링크 필요). 시험(6절)은 `-C link-dead-code`로 쓰이지 않는 함수가 링커 gc로 지워져 실패가 가려지는 일을 막는다.
4. 런타임의 기존 `pruv_alloc`·`pruv_copy`·`pruv_free`·`pruv_raw_alloc`과 v1 host helper·v1 marker는 **고치지 않는다**. v2 함수는 새로 더한다.
5. 안전 모드 저장 범위 문구는 Rust 소스 뒷단과 같다: `pruv: element out of range: <v> (u8 0..=255)`, 종료 101. 검사 순서: 저장은 색인 → 값, alloc은 길이 → 값(길이가 0이어도 값 검사).
6. 증명 모드는 검사를 넣지 않는다(값 범위는 `elem_range`가 증명). GEP의 `inbounds`는 지금처럼 두 모드 모두 붙는다(안전 모드는 색인 검사 뒤라 참).

## 1. 원소 타입 정보 싣기(두 판 공통 규칙)

- `lty("array_u8") = "{ ptr, i64 }"`(ARR), `vkind("array_u8") = arr`(Rs `Kind::Arr`). `array_bool`은 지금 그대로(가드가 막음).
- 배열 값 `V(k=arr)`과 배열 슬롯 `Slot(k=arr)`은 `ty` 칸에 원소 정보를 싣는다:
  - `[u8]`이면 `ty` = `ARRAY_U8`(Py `Type("array_u8")`) / Rs `Some("array_u8".to_string())`.
  - `[i64]`이면 지금처럼 `ty` = `None`(Py `None`, Rs `None`). **i64 길의 코드·출력은 그대로.**
  - 아래에서 "u8 배열"은 `ty`의 이름이 `array_u8`인 배열 값/슬롯이다. 원소 IR 타입 `E` = u8이면 `i8`, 아니면 `i64`.
- 배열 값이 생기는 모든 자리에서 `ty`를 채운다:
  - 매개변수: `bind_params`·`bind_contract_params`(타입 `p.type`).
  - 슬롯: `new_slot(name, ty)`가 배열 슬롯에 `ty`(u8일 때만)를 넣고, `load(sl)`가 돌려주는 배열 V에 `sl.ty`를 복사한다.
  - `alloc(n, v)`: Call 노드의 ty(Py `e.ty`, Rs `expr_ty(e)`)가 `array_u8`이면 u8.
  - `copy(x)`: 결과 V의 `ty` = 인자 V의 `ty`.
  - 사용자 함수 호출 결과: `f.ret`이 `array_u8`이면 u8.
- 매개변수·호출·반환에서 배열인지 판정하던 `p.type == ARRAY` / `p.ty == "array"` / `f.ret == ARRAY`는 **배열이면(`array`·`array_u8`)** 으로 넓힌다(Py `is_array(t)`, Rs `is_array_name(..)` 등 typeinfo에 있는 질의). 대상: `ir_params`, `bind_params`, `bind_contract_params`, `ev_call`의 호출 결과, `abi_of`(인자 `ptr %a.x.a, i64 %a.x.n`과 반환 out 포인터 글자는 원소와 무관하게 지금과 같다), 바인딩 생성.
- 소유 배열 목록(`scope["arrays"]`)과 임시값 목록(`temps`)은 슬롯·V를 그대로 담으므로 `ty`가 따라온다. 해제(`free_val`)는 V의 `ty`로 고른다.
- 조기 `return x`의 슬롯 비우기(`store ptr null` / `store i64 0`)는 그대로.

## 2. 생성 IR 글자(정확한 문자열)

`%t`·`%g` 등은 지금 생성기의 `s.op` 번호 붙이기를 따른다. **아래 적은 순서대로 `op`/`ins`를 부른다**(번호가 두 판에서 같아야 한다). `[i64]` 경로의 글자·순서는 바꾸지 않는다.

### 2.1 색인 주소 `index_ptr(a, i)`

```
(안전 모드만, 지금과 같음)  %ok = icmp ult i64 I, N ; guard → call void @pruv_panic_oob(i64 I, i64 N)
%g = getelementptr inbounds E, ptr A, i64 I
```

### 2.2 코드 읽기 `a[i]`

u8: `index_ptr` 뒤
```
%x = load i8, ptr %g
%r = zext i8 %x to i64          ; 결과 V("i64", %r)
```
i64: 지금 그대로(`load i64`).

### 2.3 원소 저장 `NAME[i] = x` (u8 배열 슬롯)

순서: 색인 식 → 값 식 → 슬롯 load → `index_ptr`(안전 모드 색인 검사) → (안전 모드만) 값 범위 검사 → trunc → store.
```
(안전 모드만)
%ok = icmp ule i64 X, 255
guard(ok, fail_when=False):  call void @pruv_panic_elem(i64 X, ptr @.str.K)     ; 문자열 "u8 0..=255"
(두 모드)
%b = trunc i64 X to i8
store i8 %b, ptr %g
```
- `guard`는 지금 `index_ptr`의 색인 검사와 같은 방식(`ok`/`fail` 라벨, fail 블록 끝 `unreachable`)이다. 문자열 `"u8 0..=255"`는 `panic1`처럼 fail 블록을 내보낼 때 `m.string`으로 등록한다(`call void @pruv_panic_elem(i64 X, ptr S)` 한 줄을 `ins`).
- `icmp ule`(부호 없는 비교)라 음수도 실패로 간다.

### 2.4 `alloc(n, v)` (u8)

순서: n 식 → v 식 → (안전 모드만) 길이 검사(지금과 같은 `icmp ult i64 CNT, 1099511627777` + `pruv_panic_arith("alloc length outside 0..2^40")`) → (안전 모드만) 값 범위 검사(2.3과 같은 `icmp ule i64 V, 255` + `pruv_panic_elem(i64 V, "u8 0..=255")`) → 호출.
```
%p = call ptr @pruv_alloc_u8(i64 CNT, i64 V)
```
결과 `V("arr", %p, CNT, ty=u8)`, 지금처럼 `temp_arr(.., owned)`.

### 2.5 `copy(x)` (u8)

```
%p = call ptr @pruv_copy_v2(ptr A, i64 N, i64 1, i64 1)
```
결과 `V("arr", %p, N, ty=u8)`, `temp_arr`.

### 2.6 해제 `free_val(v)` (u8)

```
call void @pruv_free_v2(ptr P, i64 N, i64 1, i64 1)
```
i64는 지금 그대로 `call void @pruv_free(ptr P, i64 N)`.

### 2.7 계약 읽기(requires, `cev`의 Index) (u8)

지금 순서 그대로(`zext` 길이 → `icmp ult i128` → guard `pruv_panic_undefined("array index out of range")` → `trunc i128 .. to i64`) 뒤:
```
%g = getelementptr inbounds i8, ptr A, i64 %ii
%x = load i8, ptr %g
%r = zext i8 %x to i128          ; 결과 V("i128", %r)
```

### 2.8 정렬 requires `csorted` (u8)

루프 몸체의 비교 부분만 바뀐다. 순서:
```
%pk = sub i64 %kv, 1
%g0 = getelementptr inbounds i8, ptr A, i64 %pk
%g1 = getelementptr inbounds i8, ptr A, i64 %kv
%x0 = load i8, ptr %g0
%x1 = load i8, ptr %g1
%z0 = zext i8 %x0 to i64
%z1 = zext i8 %x1 to i64
%le = icmp sle i64 %z0, %z1
```
i64는 지금 그대로.

### 2.9 선언

`DECLS`는 그대로 두고, u8 프로그램이면 그 바로 뒤에 `DECLS_U8`을 붙인다.
```
declare noalias ptr @pruv_alloc_u8(i64, i64) nounwind
declare noalias ptr @pruv_copy_v2(ptr nocapture readonly, i64, i64, i64) nounwind
declare void @pruv_free_v2(ptr nocapture, i64, i64, i64) nounwind
declare void @pruv_panic_elem(i64, ptr) noreturn cold nounwind
```
조립: `문자열 상수 + "\n" + 타입 정의 + (타입 있으면 "\n") + DECLS + (u8이면 DECLS_U8) + "\n" + 함수 청크들`(Rs는 Windows 머리 그대로 앞에).

### 2.10 가드

- 생성기 자체 가드: Py `gen_llvm`의 `g2_unimplemented_error(prog, "codegen", skip=("array_u8",))`, Rs `gen_llvm_for`의 `g2_unimplemented_error(prog, "codegen", None, &["array_u8"], None)`.
- 드라이버(Py `pruvc/pruvc.py` `compile_file`, Rs `pruvc-rs/crates/pruvc/src/driver.rs` `compile`): llvm 길과 rust 길을 가르던 분기를 없애고 모든 길에서 `g2_unimplemented_error(prog, "codegen", skip=("array_u8",))`(Rs `None, &["array_u8"], None`).

## 3. 런타임 `pruvc/runtime.c` v2

기존 코드는 그대로 두고 다음을 더한다(C11, MSVC `/std:c11`에서도 컴파일돼야 하므로 `__attribute__`는 기존 COUNT 블록 밖에 쓰지 않는다).

선언부(기존 선언 뒤):
```c
void *pruv_alloc_u8(int64_t len, int64_t value);
void *pruv_copy_v2(const void *src, int64_t len, int64_t size, int64_t align);
void pruv_free_v2(void *data, int64_t len, int64_t size, int64_t align);
_Noreturn void pruv_panic_elem(int64_t v, const char *range);
```
`#ifdef PRUV_RUST_ALLOCATOR` 블록 안(기존 v1 marker 뒤):
```c
extern void *pruv_host_alloc_v2(int64_t len, int64_t size, int64_t align);
extern void *pruv_host_alloc_zeroed_v2(int64_t len, int64_t size, int64_t align);
extern void pruv_host_free_v2(void *data, int64_t len, int64_t size, int64_t align);
void pruv_runtime_rust_allocator_v2(void) {}
```
panic(기존 panic 4개 뒤):
```c
_Noreturn void pruv_panic_elem(int64_t v, const char *range) {
    PRUV_HOST_FLUSH();
    fflush(stdout);
    fprintf(stderr, "pruv: element out of range: %" PRId64 " (%s)\n", v, range);
    exit(101);
}
```
할당(기존 `pruv_free` 뒤):
```c
#define PRUV_MAX_LEN ((uint64_t)1 << 40)

static int pruv_layout_ok(int64_t size, int64_t align) {
    return (size == 1 && align == 1) || (size == 4 && align == 4) || (size == 8 && align == 8);
}

static void *pruv_raw_alloc_v2(int64_t len, int64_t size, int64_t align, int zeroed) {
    /* len > 0 here; every check comes before the multiplication */
    if (!pruv_layout_ok(size, align)) pruv_panic_arith("invalid element layout");
    if ((uint64_t)len > PRUV_MAX_LEN) pruv_panic_arith("allocation failed");
    if ((uint64_t)len > (uint64_t)SIZE_MAX / (uint64_t)size) pruv_panic_arith("allocation failed");
#ifdef PRUV_RUST_ALLOCATOR
    void *p = zeroed ? pruv_host_alloc_zeroed_v2(len, size, align) : pruv_host_alloc_v2(len, size, align);
#else
    void *p = zeroed ? calloc((size_t)len, (size_t)size) : malloc((size_t)len * (size_t)size);
#endif
    if (!p) pruv_panic_arith("allocation failed");
#ifdef PRUV_COUNT_ALLOCS
    pruv_n_allocs++;
#endif
    return p;
}

void *pruv_alloc_u8(int64_t len, int64_t value) {
    /* value is already in 0..=255: proved (proof mode) or checked by the caller (safe mode) */
    if (len <= 0) return NULL;
    if (value == 0) return pruv_raw_alloc_v2(len, 1, 1, 1);
    uint8_t *p = (uint8_t *)pruv_raw_alloc_v2(len, 1, 1, 0);
    memset(p, (int)(uint8_t)value, (size_t)len);
    return p;
}

void *pruv_copy_v2(const void *src, int64_t len, int64_t size, int64_t align) {
    if (len <= 0) return NULL;
    void *p = pruv_raw_alloc_v2(len, size, align, 0);
    memcpy(p, src, (size_t)len * (size_t)size);
    return p;
}

void pruv_free_v2(void *data, int64_t len, int64_t size, int64_t align) {
#ifdef PRUV_COUNT_ALLOCS
    if (data) pruv_n_frees++;
#endif
    if (!data || len <= 0) return;
#ifdef PRUV_RUST_ALLOCATOR
    pruv_host_free_v2(data, len, size, align);
#else
    (void)len;
    (void)size;
    (void)align;
    free(data);
#endif
}
```
머리 주석에 v2 helper·v2 marker·새 panic 문구(`pruv: element out of range: <v> (<range>)`)를 한 단락으로 더한다. `build.rs`·`runtime.rs`는 고치지 않는다(4변형이 `runtime.c`를 그대로 다시 굽는다).

## 4. 바인딩 글자(두 판 `gen_bindings`)

`ALLOW` = `#[allow(dead_code, non_snake_case, unused)]`. 순서는 지금 그대로이고 아래만 바뀐다.

1. `Pruv__Array` 구조체 뒤, `Pruv__Tagged` 앞에 — u8 프로그램이면:
   ```
   ALLOW
   #[repr(C)]
   pub struct Pruv__ArrayU8 { pub data: *mut u8, pub len: i64 }
   ```
2. `pruv_host_free` 블록 뒤에 **늘**(모든 프로그램) 세 블록(각각 앞에 `ALLOW` 한 줄):
   ```rust
   #[no_mangle]
   pub extern "C" fn pruv_host_alloc_v2(len: i64, size: i64, align: i64) -> *mut u8 {
       let layout = match (len as usize).checked_mul(size as usize).and_then(|b| ::std::alloc::Layout::from_size_align(b, align as usize).ok()) {
           Some(l) => l,
           None => ::std::alloc::handle_alloc_error(::std::alloc::Layout::new::<u8>()),
       };
       let p = unsafe { ::std::alloc::alloc(layout) };
       if p.is_null() { ::std::alloc::handle_alloc_error(layout); }
       p
   }
   ```
   ```rust
   #[no_mangle]
   pub extern "C" fn pruv_host_alloc_zeroed_v2(len: i64, size: i64, align: i64) -> *mut u8 {
       let layout = match (len as usize).checked_mul(size as usize).and_then(|b| ::std::alloc::Layout::from_size_align(b, align as usize).ok()) {
           Some(l) => l,
           None => ::std::alloc::handle_alloc_error(::std::alloc::Layout::new::<u8>()),
       };
       let p = unsafe { ::std::alloc::alloc_zeroed(layout) };
       if p.is_null() { ::std::alloc::handle_alloc_error(layout); }
       p
   }
   ```
   ```rust
   #[no_mangle]
   pub extern "C" fn pruv_host_free_v2(data: *mut u8, len: i64, size: i64, align: i64) {
       if data.is_null() || len <= 0 { return; }
       if let Some(layout) = (len as usize).checked_mul(size as usize).and_then(|b| ::std::alloc::Layout::from_size_align(b, align as usize).ok()) {
           unsafe { ::std::alloc::dealloc(data, layout) };
       }
   }
   ```
   (`Vec<u8>::from_raw_parts(p, len, len)`이 놓을 때 쓰는 `Layout::array::<u8>(len)` = 크기 len·정렬 1과 같다.)
3. `extern "C"` 블록:
   - `array_u8` 매개변수 → `*const u8`, `i64`. (`array`는 지금처럼 `*const i64`, `i64`.)
   - `array_u8` 반환 → 마지막 `*mut Pruv__ArrayU8`, 반환 없음. (`array`는 지금처럼 `*mut Pruv__Array`.)
   - 배열(원소 무관)을 돌려주는 함수가 하나라도 있으면 마지막 줄 `    fn pruv_runtime_rust_allocator_v2();` (지금의 `_v1` 줄을 바꾼다).
4. 공개 래퍼:
   - 타입 철자: `array_u8` 매개변수 `&[u8]`, 반환 `::std::vec::Vec<u8>`(`rust_ty`).
   - 인자: 배열이면 원소 무관 `x.as_ptr()`, `x.len() as i64`.
   - 배열 반환: `let _ = ::std::hint::black_box(pruv_runtime_rust_allocator_v2 as unsafe extern "C" fn());`(지금의 `_v1`을 바꾼다), `let mut pruv__out = Pruv__ArrayU8 { data: ::std::ptr::null_mut(), len: 0 };`(i64는 `Pruv__Array`), 나머지 호출·`from_raw_parts` 줄은 지금과 같다.

## 5. 표본·시험(시험 담당)

- `tests/llvm_pending.txt`는 메인이 지운다(`git rm`). 그러면 run_all·cli_also_llvm의 같은 llvm 행이 실제 링크·실행 검사로 바뀐다. pending 장치 코드는 남긴다(A5에서 다시 쓸 수 있음).
- `tests/runtime/g2a_rt_*.json` 15개에 `"alloc_balance": true`를 더한다(llvm 행만 읽는 키). 단, 종료 코드가 0이 아닌(panic으로 끝나는) 표본은 `exit(101)`로 끝나도 atexit가 돌아 줄이 나오지만 해제가 덜 된 채 끝나므로 넣지 않는다. 구현에서 정한 예외 둘: `g2a_rt_return`(돌려준 배열을 Rust `Vec`이 놓아 런타임 해제 횟수에 안 잡힘)과 `g2a_rt_refine_trust`(할당 0번이라 `a > 0` 조건에 걸림)도 넣지 않는다. 대신 `g2a_rt_free_paths`에 함수별 `llvm_fn_contains`(`call void @pruv_free_v2(`·`call ptr @pruv_copy_v2(` 있음; 선언 줄 때문에 늘 참인 `ll_contains`는 쓰지 않음)와 `llvm_fn_absent`(`@pruv_free(` 등 i64 helper 없음)를 둬서, 해제 횟수만으로는 못 잡는 i64 크기 해제 퇴행을 IR 글자로 막는다.
- 새 runtime 표본 `tests/runtime/g2a_rt_free_paths.{pruv,rs,json}`: u8 배열의 반복 재대입(루프 안 `a = alloc(..)`), 분기 안 조기 반환, 호출 결과 임시값(`len(make())`, `make()[0]`), `copy`, 지역 `[u8]`를 pruv 호출자에게 옮기는 반환(`mk2`), `[u8]` 인자 전달(`sum2`), 길이만 쓰는 호출(`pass_on`)을 섞고 `alloc_balance: true`. 두 모드(증명·`--no-verify`) 모두 돌도록 기존 표본 json 형식을 따른다.
- ABI 표본 `tests/abi/gen/g2a_u8_ret.pruv`(`[u8]` 인자를 받아 `[u8]`를 돌려주는 함수)와 `tests/abi/check_generated.py`가 `[u8]` 반환을 "마지막 out 포인터 + void"로 인정하게.
- 런타임 v2 링크 시험 `tests/abi/check_runtime_v2.py`: 6절.

## 6. 링크 실패 시험(`tests/abi/check_runtime_v2.py`)

호스트 대상에서 Rust 판 pruvc로 `.ll`+바인딩을 만들고 clang으로 `.ll`·런타임을 객체화한 뒤 rustc로 Rust 주 프로그램과 링크한다. `tests/abi/runtime_v1.c`는 A3 커밋(1b884b7)의 `runtime.c`를 그대로 얼린 사본이다.

| 경우 | 바인딩 | 런타임 | 기대 |
|---|---|---|---|
| ok_u8 | `g2a_u8_ret` 새 바인딩 | 새 `runtime.c` `-DPRUV_RUST_ALLOCATOR -DPRUV_COUNT_ALLOCS` | 링크·실행 성공, 기대 출력, `pruv-alloc-balance: A F`에서 F >= 1·A = F + 1(돌려준 배열은 Rust `Vec`이 놓음; 표본은 중간 copy 하나를 런타임 안에서 놓음) |
| ok_i64 | `arr_ret` 새 바인딩 | 새 runtime, rust allocator | 성공 |
| old_rt_u8 | `g2a_u8_ret` 새 바인딩 | `runtime_v1.c` rust allocator | 링크 실패(`pruv_runtime_rust_allocator_v2` 없음) |
| old_rt_i64 | `arr_ret` 새 바인딩 | `runtime_v1.c` rust allocator | 링크 실패(`pruv_runtime_rust_allocator_v2` 없음) |
| old_bind | `arr_ret` 새 바인딩에서 v2 helper 세 블록을 지운 것(옛 바인딩 흉내) | 새 runtime rust allocator | 링크 실패(`pruv_host_alloc_v2` 등 없음) |
| malloc_rt | `g2a_u8_ret` 새 바인딩 | 새 runtime, malloc(정의 없음) | 링크 실패(marker 없음) |

링크 실패 경우는 rustc 종료 코드가 0이 아니고, 오류 글에 기대 심볼 이름이 있어야 통과다. 결과를 경우마다 한 줄로 찍고 하나라도 어긋나면 종료 1.
