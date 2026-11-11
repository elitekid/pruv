# G2 A4 Implementation Spec: `[u8]` LLVM Backend, `--rust-bindings`, Runtime v2

Status: A4 batch implementation contract (written by main). Both implementations (Python `pruvc/llvmgen.py`, Rust `pruv-core/src/llvmgen.rs`, `abi.rs`, `bindings.rs`) emit the text below **byte for byte**. `tests/diff_llvm.py` compares the IR and bindings of the two implementations byte for byte. Basis: `docs/G2_SPEC.md` §0.0, §5.2, §5.3, §5.4. It follows the safe-mode messages and check order of the A3 spec `docs/G2_A3_IMPL.md` as is.

## 0. Scope and decisions

1. A4 opens `[u8]` in every path that uses llvmgen (`--backend llvm`, `--also-llvm`, the Rust implementation's `--emit ll|obj|exe`). `[bool]` (`array_bool`) continues to be rejected as `unsupported_type` (A5).
2. **The IR of existing programs that use only `[i64]` does not change by a single byte.** The u8 declarations (`DECLS_U8`) are appended only when the program uses `[u8]` (`uses_array_type(prog, "array_u8")`).
3. **Bindings change for all programs** (G2_SPEC 5.4 compatibility items 3 and 4): three v2 host helpers are always defined, and if there is a function that returns an array, the marker is referenced as `pruv_runtime_rust_allocator_v2`. Reason: the `-DPRUV_RUST_ALLOCATOR` runtime calls the v2 host helpers as extern, so every binding linked with that runtime must define the helpers. A new binding + old runtime fails to link if there is a function returning an array (v2 marker) or if a v2 runtime function is used, and an old binding + new runtime fails if runtime code that calls the v2 host helpers remains in the link. Combinations that are neither may link, but then only the v1 path is used, so it is safe (the guaranteed range is G2_SPEC 5.4 compatibility item 4: regeneration and relinking required). The tests (§6) use `-C link-dead-code` to prevent unused functions from being removed by linker gc and hiding a failure.
4. The runtime's existing `pruv_alloc`, `pruv_copy`, `pruv_free`, `pruv_raw_alloc`, and the v1 host helpers and v1 marker are **not modified**. v2 functions are added new.
5. The safe-mode store-range message is the same as the Rust source backend: `pruv: element out of range: <v> (u8 0..=255)`, exit 101. Check order: for a store, index → value; for alloc, length → value (the value is checked even when the length is 0).
6. Proof mode inserts no checks (the value range is proved by `elem_range`). The `inbounds` of GEP is attached in both modes as now (in safe mode it is true because it follows the index check).

## 1. Carrying element type information (rules common to both implementations)

- `lty("array_u8") = "{ ptr, i64 }"` (ARR), `vkind("array_u8") = arr` (Rs `Kind::Arr`). `array_bool` stays as is (the guard blocks it).
- The array value `V(k=arr)` and array slot `Slot(k=arr)` carry element information in the `ty` field:
  - For `[u8]`, `ty` = `ARRAY_U8` (Py `Type("array_u8")`) / Rs `Some("array_u8".to_string())`.
  - For `[i64]`, `ty` = `None` as now (Py `None`, Rs `None`). **The code and output of the i64 path are unchanged.**
  - Below, a "u8 array" is an array value/slot whose `ty` name is `array_u8`. The element IR type `E` is `i8` if u8, otherwise `i64`.
- `ty` is filled in at every place an array value arises:
  - Parameters: `bind_params`, `bind_contract_params` (type `p.type`).
  - Slots: `new_slot(name, ty)` puts `ty` (only when u8) in an array slot, and `load(sl)` copies `sl.ty` to the array V it returns.
  - `alloc(n, v)`: if the ty of the Call node (Py `e.ty`, Rs `expr_ty(e)`) is `array_u8`, it is u8.
  - `copy(x)`: the `ty` of the resulting V = the `ty` of the argument V.
  - User function call result: if `f.ret` is `array_u8`, it is u8.
- The `p.type == ARRAY` / `p.ty == "array"` / `f.ret == ARRAY` that decided whether something is an array in parameters, calls, and returns is widened to **if it is an array (`array` or `array_u8`)** (Py `is_array(t)`, Rs `is_array_name(..)`, and other queries in typeinfo). Targets: `ir_params`, `bind_params`, `bind_contract_params`, the call result in `ev_call`, `abi_of` (the arguments `ptr %a.x.a, i64 %a.x.n` and the return out-pointer text are the same as now regardless of element), and binding generation.
- The owned array list (`scope["arrays"]`) and the temporaries list (`temps`) hold slots and Vs as is, so `ty` follows. Freeing (`free_val`) is chosen by the V's `ty`.
- Clearing the slot at an early `return x` (`store ptr null` / `store i64 0`) is unchanged.

## 2. Generated IR text (exact strings)

`%t`, `%g`, etc. follow the `s.op` numbering of the current generator. **Call `op`/`ins` in the order written below** (the numbers must be the same in both implementations). The text and order of the `[i64]` path are not changed.

### 2.1 Index address `index_ptr(a, i)`

```
(safe mode only, same as now)  %ok = icmp ult i64 I, N ; guard → call void @pruv_panic_oob(i64 I, i64 N)
%g = getelementptr inbounds E, ptr A, i64 I
```

### 2.2 Code read `a[i]`

u8: after `index_ptr`
```
%x = load i8, ptr %g
%r = zext i8 %x to i64          ; result V("i64", %r)
```
i64: as now (`load i64`).

### 2.3 Element store `NAME[i] = x` (u8 array slot)

Order: index expression → value expression → slot load → `index_ptr` (safe-mode index check) → (safe mode only) value range check → trunc → store.
```
(safe mode only)
%ok = icmp ule i64 X, 255
guard(ok, fail_when=False):  call void @pruv_panic_elem(i64 X, ptr @.str.K)     ; string "u8 0..=255"
(both modes)
%b = trunc i64 X to i8
store i8 %b, ptr %g
```
- `guard` works the same way as the index check of the current `index_ptr` (`ok`/`fail` labels, `unreachable` at the end of the fail block). The string `"u8 0..=255"` is registered with `m.string` when the fail block is emitted, as with `panic1` (`ins` the one line `call void @pruv_panic_elem(i64 X, ptr S)`).
- Since it is `icmp ule` (unsigned comparison), negatives also go to failure.

### 2.4 `alloc(n, v)` (u8)

Order: n expression → v expression → (safe mode only) length check (same as now: `icmp ult i64 CNT, 1099511627777` + `pruv_panic_arith("alloc length outside 0..2^40")`) → (safe mode only) value range check (same as 2.3: `icmp ule i64 V, 255` + `pruv_panic_elem(i64 V, "u8 0..=255")`) → call.
```
%p = call ptr @pruv_alloc_u8(i64 CNT, i64 V)
```
The result is `V("arr", %p, CNT, ty=u8)`, `temp_arr(.., owned)` as now.

### 2.5 `copy(x)` (u8)

```
%p = call ptr @pruv_copy_v2(ptr A, i64 N, i64 1, i64 1)
```
The result is `V("arr", %p, N, ty=u8)`, `temp_arr`.

### 2.6 Free `free_val(v)` (u8)

```
call void @pruv_free_v2(ptr P, i64 N, i64 1, i64 1)
```
For i64, as now: `call void @pruv_free(ptr P, i64 N)`.

### 2.7 Contract read (requires, Index of `cev`) (u8)

After the current order (`zext` length → `icmp ult i128` → guard `pruv_panic_undefined("array index out of range")` → `trunc i128 .. to i64`) as is:
```
%g = getelementptr inbounds i8, ptr A, i64 %ii
%x = load i8, ptr %g
%r = zext i8 %x to i128          ; result V("i128", %r)
```

### 2.8 Sorted requires `csorted` (u8)

Only the comparison part of the loop body changes. Order:
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
i64 is as now.

### 2.9 Declarations

`DECLS` is left as is, and if the program is a u8 program, `DECLS_U8` is attached right after it.
```
declare noalias ptr @pruv_alloc_u8(i64, i64) nounwind
declare noalias ptr @pruv_copy_v2(ptr nocapture readonly, i64, i64, i64) nounwind
declare void @pruv_free_v2(ptr nocapture, i64, i64, i64) nounwind
declare void @pruv_panic_elem(i64, ptr) noreturn cold nounwind
```
Assembly: `string constants + "\n" + type definitions + ("\n" if there are types) + DECLS + (DECLS_U8 if u8) + "\n" + function chunks` (Rs puts the Windows header in front as is).

### 2.10 Guards

- The generator's own guard: Py `gen_llvm`'s `g2_unimplemented_error(prog, "codegen", skip=("array_u8",))`, Rs `gen_llvm_for`'s `g2_unimplemented_error(prog, "codegen", None, &["array_u8"], None)`.
- Driver (Py `pruvc/pruvc.py` `compile_file`, Rs `pruvc-rs/crates/pruvc/src/driver.rs` `compile`): remove the branch that separated the llvm path from the rust path, and in every path use `g2_unimplemented_error(prog, "codegen", skip=("array_u8",))` (Rs `None, &["array_u8"], None`).

## 3. Runtime `pruvc/runtime.c` v2

Leave the existing code as is and add the following (C11; it must also compile under MSVC `/std:c11`, so `__attribute__` is not used outside the existing COUNT block).

Declaration part (after the existing declarations):
```c
void *pruv_alloc_u8(int64_t len, int64_t value);
void *pruv_copy_v2(const void *src, int64_t len, int64_t size, int64_t align);
void pruv_free_v2(void *data, int64_t len, int64_t size, int64_t align);
_Noreturn void pruv_panic_elem(int64_t v, const char *range);
```
Inside the `#ifdef PRUV_RUST_ALLOCATOR` block (after the existing v1 marker):
```c
extern void *pruv_host_alloc_v2(int64_t len, int64_t size, int64_t align);
extern void *pruv_host_alloc_zeroed_v2(int64_t len, int64_t size, int64_t align);
extern void pruv_host_free_v2(void *data, int64_t len, int64_t size, int64_t align);
void pruv_runtime_rust_allocator_v2(void) {}
```
Panic (after the existing 4 panics):
```c
_Noreturn void pruv_panic_elem(int64_t v, const char *range) {
    PRUV_HOST_FLUSH();
    fflush(stdout);
    fprintf(stderr, "pruv: element out of range: %" PRId64 " (%s)\n", v, range);
    exit(101);
}
```
Allocation (after the existing `pruv_free`):
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
Add the v2 helpers, the v2 marker, and the new panic message (`pruv: element out of range: <v> (<range>)`) to the header comment as one paragraph. `build.rs` and `runtime.rs` are not modified (the 4 variants re-bake `runtime.c` as is).

## 4. Binding text (`gen_bindings` of both implementations)

`ALLOW` = `#[allow(dead_code, non_snake_case, unused)]`. The order is as now, and only the following changes.

1. After the `Pruv__Array` struct and before `Pruv__Tagged` — if it is a u8 program:
   ```
   ALLOW
   #[repr(C)]
   pub struct Pruv__ArrayU8 { pub data: *mut u8, pub len: i64 }
   ```
2. After the `pruv_host_free` block, **always** (all programs), three blocks (each preceded by one `ALLOW` line):
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
   (The `Layout::array::<u8>(len)` that `Vec<u8>::from_raw_parts(p, len, len)` uses when releasing equals size len and alignment 1.)
3. `extern "C"` block:
   - `array_u8` parameter → `*const u8`, `i64`. (`array` is `*const i64`, `i64` as now.)
   - `array_u8` return → a final `*mut Pruv__ArrayU8`, no return value. (`array` is `*mut Pruv__Array` as now.)
   - If there is at least one function that returns an array (any element type), the last line is `    fn pruv_runtime_rust_allocator_v2();` (replacing the current `_v1` line).
4. Public wrappers:
   - Type spelling: `array_u8` parameter `&[u8]`, return `::std::vec::Vec<u8>` (`rust_ty`).
   - Arguments: if an array, regardless of element, `x.as_ptr()`, `x.len() as i64`.
   - Array return: `let _ = ::std::hint::black_box(pruv_runtime_rust_allocator_v2 as unsafe extern "C" fn());` (replacing the current `_v1`), `let mut pruv__out = Pruv__ArrayU8 { data: ::std::ptr::null_mut(), len: 0 };` (for i64, `Pruv__Array`), and the remaining call and `from_raw_parts` lines are the same as now.

## 5. Samples and tests (test owner)

- `tests/llvm_pending.txt` is deleted by main (`git rm`). Then the same llvm rows in run_all and cli_also_llvm turn into real link-and-run checks. The pending mechanism code stays (it can be reused in A5).
- Add `"alloc_balance": true` to the 15 `tests/runtime/g2a_rt_*.json` (a key read only by llvm rows). However, samples whose exit code is nonzero (ending in panic) are not included: even though they end with `exit(101)`, atexit runs and the line is printed, but they end with deallocation incomplete. Two exceptions decided in implementation: `g2a_rt_return` (the returned array is released by the Rust `Vec`, so it is not counted in the runtime free count) and `g2a_rt_refine_trust` (zero allocations, so it hits the condition `a > 0`) are also not included. Instead, `g2a_rt_free_paths` gets per-function `llvm_fn_contains` (`call void @pruv_free_v2(` and `call ptr @pruv_copy_v2(` present; `ll_contains`, which is always true because of declaration lines, is not used) and `llvm_fn_absent` (no i64 helpers such as `@pruv_free(`), so that an i64-sized free regression, which the free count alone cannot catch, is blocked by IR text.
- New runtime sample `tests/runtime/g2a_rt_free_paths.{pruv,rs,json}`: mixes repeated reassignment of a u8 array (`a = alloc(..)` inside a loop), early return inside a branch, call-result temporaries (`len(make())`, `make()[0]`), `copy`, a return that moves a local `[u8]` to a pruv caller (`mk2`), passing a `[u8]` argument (`sum2`), and a call that uses only the length (`pass_on`), with `alloc_balance: true`. It follows the existing sample json format so that it runs in both modes (proof and `--no-verify`).
- ABI sample `tests/abi/gen/g2a_u8_ret.pruv` (a function that takes a `[u8]` argument and returns a `[u8]`), and make `tests/abi/check_generated.py` accept a `[u8]` return as "final out pointer + void".
- Runtime v2 link test `tests/abi/check_runtime_v2.py`: §6.

## 6. Link failure test (`tests/abi/check_runtime_v2.py`)

On the host target, create `.ll` + bindings with the Rust implementation's pruvc, turn the `.ll` and runtime into objects with clang, and link with a Rust main program using rustc. `tests/abi/runtime_v1.c` is a frozen copy of the `runtime.c` of the A3 commit (bec0348).

| Case | Binding | Runtime | Expected |
|---|---|---|---|
| ok_u8 | new binding of `g2a_u8_ret` | new `runtime.c` `-DPRUV_RUST_ALLOCATOR -DPRUV_COUNT_ALLOCS` | link and run succeed, expected output, and in `pruv-alloc-balance: A F` F >= 1 and A = F + 1 (the returned array is released by the Rust `Vec`; the sample releases one intermediate copy inside the runtime) |
| ok_i64 | new binding of `arr_ret` | new runtime, rust allocator | success |
| old_rt_u8 | new binding of `g2a_u8_ret` | `runtime_v1.c` rust allocator | link failure (`pruv_runtime_rust_allocator_v2` missing) |
| old_rt_i64 | new binding of `arr_ret` | `runtime_v1.c` rust allocator | link failure (`pruv_runtime_rust_allocator_v2` missing) |
| old_bind | the new binding of `arr_ret` with the three v2 helper blocks removed (imitating an old binding) | new runtime rust allocator | link failure (`pruv_host_alloc_v2` etc. missing) |
| malloc_rt | new binding of `g2a_u8_ret` | new runtime, malloc (no definition) | link failure (marker missing) |

For the link-failure cases, the rustc exit code must be nonzero and the error text must contain the expected symbol name to pass. Print the results one line per case, and exit 1 if even one deviates.
