# M1 LLVM Backend Spec (finalized 2026-11-10)

`pruvc --backend llvm` emits textual LLVM IR (`.ll`) and Rust bindings (`.rs`). The canonical reference (the semantic standard) is `pruvc/codegen.py` (the Rust backend), and the LLVM implementation must produce the same output, the same error messages, and the same exit code (101) for the same program. `codegen.py`, `vast.py`, `check.py`, `verify.py`, and `vparser.py` are not modified.

## 1. Files and ownership

| File | Contents |
|---|---|
| `pruvc/llvmgen.py` (new) | `gen_llvm(prog, verified=True, trust_callers=False) -> (ir: str, rust_bindings: str)` |
| `pruvc/runtime.c` (new) | the runtime support functions of §2 |
| `pruvc/pruvc.py` | `--backend rust|llvm`, `--rust-bindings PATH` |
| `tests/run_all.py`, `bench/harness/run.py`, `bench/mutate.py` | `--backend` option, build and link of the LLVM implementation |

## 2. runtime.c (C11, clang -O2 -std=c11 -c)

```c
#include <stdint.h>
int64_t *pruv_alloc(int64_t len, int64_t value);   // len>=0 (guaranteed by the caller). len==0 -> NULL. fills len elements with value
int64_t *pruv_copy(const int64_t *src, int64_t len); // len==0 -> NULL (does not read src)
void pruv_free(int64_t *data, int64_t len);        // NULL or len==0 -> no-op
void pruv_print_i64(int64_t v);                    // "%lld\n" to stdout, fflush(stdout) every time
void pruv_print_bool(int64_t v);                   // "true\n"/"false\n", fflush
_Noreturn void pruv_panic_oob(int64_t i, int64_t len);              // "pruv: index out of bounds: <i> (len <len>)"
_Noreturn void pruv_panic_arith(const char *detail);                // "pruv: arithmetic error: <detail>"
_Noreturn void pruv_panic_requires(const char *fn, const char *expr);// "pruv: requires violated: <fn>: <expr>"
_Noreturn void pruv_panic_undefined(const char *detail);            // "pruv: requires undefined: <detail>"
```
- Panic family: `fflush(stdout)` → message + `\n` to stderr → `exit(101)`.
- Allocation failure (or len*8 overflow): in the default (malloc) mode, `pruv_panic_arith("allocation failed")`. In the Rust allocator mode, the binding's `handle_alloc_error` aborts (the same behavior as the canonical `vec!`).
- Two allocation backends:
  - Default: `malloc`/`free`.
  - `-DPRUV_RUST_ALLOCATOR`: allocation is `int64_t *pruv_host_alloc(int64_t len)` and deallocation is `void pruv_host_free(int64_t *data, int64_t len)` (both defined by the Rust binding, called only when len>0). If `value == 0`, allocation is `int64_t *pruv_host_alloc_zeroed(int64_t len)` (zero-initialized allocation, no fill loop; the default mode uses `calloc`). Panic functions first call `void pruv_host_flush(void)` (Rust stdout flush). Only in this mode, the no-op function `void pruv_runtime_rust_allocator_v1(void)` is defined (the binding references it → linking the wrong runtime fails at link time).
  - `-DPRUV_COUNT_ALLOCS` (for tests, can be combined with either of the two modes): counts successful allocations and non-null `pruv_free` calls, and emits one line `pruv-alloc-balance: <allocs> <frees>` to stderr via `atexit`.

## 3. Value → LLVM type

| Pruv | Internal SSA | Notes |
|---|---|---|
| i64 | `i64` | |
| bool | `i1` (an alloca slot may be `i1` too) | |
| unit | `void` | |
| [i64] | `{ ptr, i64 }` (data, len) | an owned array of length 0 is `{null, 0}` |
| Option<i64> | `{ i1, i64 }` | tag: Some=1, None=0. None payload=0 |
| Result<i64,i64> | `{ i1, i64 }` | tag: Ok=1, Err=0 |
| contract integer | `i128` | inputs, elements, and payloads are `sext` |

Ownership is not put into the IR as a tag; the generator tracks it at compile time (an array argument = borrowed, results of alloc/copy/array-returning calls = owned).

## 4. Function names and calling convention

Three are emitted per function `f`.

| Name | Linkage | What it does |
|---|---|---|
| `@f__pruv_body` | `internal` | the body (proof mode or safe mode) |
| `@f__pruv_entry` | `internal` | if not trust and there is a requires, evaluates the requires in declaration order as i128 and panics on failure, then calls body. Otherwise passes straight to body |
| `@pruv_abi_f` | external (C calling convention) | converts external ABI values to internal values and calls entry |

- Calls inside Pruv: proof mode → `f__pruv_body` (the caller proves the requires), safe mode → `f__pruv_entry`.
- Internal signature: an array argument is expanded into two arguments `ptr, i64`. bool is `i1`. Option/Result arguments and returns are `{i1,i64}` aggregate values. An array return is a `{ptr,i64}` aggregate value.
- External ABI (`pruv_abi_f`):
  - i64 → `i64`, bool argument → `i64` (0/1), array argument → `ptr, i64`, Option/Result argument → `i64 tag, i64 value`.
  - Return: i64 → `i64`, bool → `i64` (0/1), unit → `void`.
  - Array return → `void`, stored into the last argument `ptr out` as `PruvArray { int64_t *data; int64_t len; }`.
  - An Option/Result return is a `{i64,i64}` value return (`{tag zext, payload}`; on the Rust side `#[repr(C)] Pruv__Tagged` is received as `-> Pruv__Tagged`; macOS arm64 and SysV only; Windows x64 returns a 16-byte struct through a hidden pointer, so in M3 it must be turned back into an out-pointer or ABI lowering is needed).
    - Reason: the cost of out-pointer stores and reads was measured in p04's million calls, and value return removes that cost.
  - Only an array return uses an out-pointer. The `sret` attribute is not used (an explicit out-pointer).
- The IR contains no target triple or datalayout (`-Wno-override-module` for clang).

## 5. Body lowering

- Local variables and the return slot are `alloca` in the entry block (clang -O2 promotes them). No alloca inside loops.
- Every basic block ends with exactly one terminator. Dead statements after a return are not emitted (putting them in a new block that ends in `unreachable` is also fine).
- `&&` and `||` are short-circuit evaluated.
- `assert`, `invariant`, `decreases`, and `ensures` have no runtime code.

| Operation | Proof mode | Safe mode |
|---|---|---|
| `+ - *` | `add/sub/mul nsw i64` | `llvm.sadd/ssub/smul.with.overflow.i64`, failure → `pruv_panic_arith("overflow in +")`, etc. |
| unary `-` | `sub nsw i64 0, x` | `ssub.with.overflow(0,x)` → `"overflow in unary -"` |
| `/ %` | `udiv/urem` (the verifier proves dividend>=0, divisor>0) | after the `b > 0 && a >= 0` check, `udiv/urem`; failure → `"division outside domain: need divisor > 0 and dividend >= 0"` |
| Index read/write | `getelementptr inbounds i64, ptr %d, i64 %i` without a check | `0 <= i < len` (possible with a single unsigned comparison), GEP only in the success block; failure → `pruv_panic_oob(i, len)` |
| `alloc(n, v)` | `pruv_alloc(n, v)` | check `0 <= n <= 2^40`; failure → `"alloc length outside 0..2^40"` |
| `copy(a)` | `pruv_copy(d, len)` | same |
| `len(a)` | the array's len | same |
| `print(x)` | `pruv_print_i64` / `pruv_print_bool(zext)` | same |

- A failure path is a separate block with a panic call + `unreachable`. The panic declarations carry `noreturn cold`.
- The evaluation order in every mode is source order (left to right) (a `! io` user function can be called inside an expression, so the order shows up in the output). Index assignment `a[i] = v`: i → v (in safe mode followed by the range check) → store. `alloc(n, v)`: n → v (in safe mode followed by the length check).
- Marking of proved facts: `nsw`, `inbounds`, and `udiv/urem` only in the proof-mode body. No `nsw` is attached to the safe-mode body (the result on the successful check path is the intrinsic value as is).

## 6. Memory (the same semantics as Rust `Vec` drop)

- An owned array local variable is `pruv_free`d at the end of the block where it was declared, in reverse declaration order. Locals of a while body are freed at the end of every iteration.
- Array variable reassignment `a = f(...)`: evaluate the whole right-hand side → free the old value → store the new value.
- `return`: evaluate the return value → (if a local array variable is returned, empty that slot to prevent a double free) → free the locals and temporaries of all currently open scopes → ret.
- Temporary arrays from call results (`len(f(x))`, `g(f(x))`, `f(x)[i]`, `copy(f(x))`, inside a condition expression): freed when the statement that uses that temporary (or the condition evaluation) ends. The top-level call result on the right-hand side of a `let`/assignment/`return` is not a temporary; ownership moves.
- Under short-circuit evaluation, only the temporaries of the path actually executed are freed.
- An array argument is borrowed. The callee does not free it.
- On panic (exit 101), nothing is freed.

## 7. Runtime check of requires (entry function, when not trust)

- The message expression string uses `codegen.show(expr)` as is (`from codegen import show`). The string is an IR global constant (`private unnamed_addr constant [N x i8] c"...\00"`, byte escape `\XX`).
- i128 evaluation: `+ - *` and unary `-` use `llvm.s*.with.overflow.i128`, failure → `pruv_panic_undefined("i128 overflow in +")`, etc.
- `/ %` are Euclidean (the same as z3 Int). The internal functions inside the IR `@pruv_cdiv`, `@pruv_crem` (i128): b==0 → `"division by zero in /"`/`"division by zero in %"`, a==MIN && b==-1 → `"i128 overflow in /"`/`"i128 overflow in %"`, otherwise after sdiv/srem, if the remainder is negative, correct it (if b>0, q-=1, r+=b; if b<0, q+=1, r-=b).
- Contract index `a[i]`: in the i128 state, read after confirming `0 <= i < len`; failure → `"array index out of range"`.
- `some_val`/`ok_val`/`err_val`: check the tag; failure → `"some_val of None"`, `"ok_val of Err"`, `"err_val of Ok"`.
- Option/Result `==`/`!=` (possible only in contracts): different if the tags differ, equal if both are None, otherwise compare the payloads.
- `==>` is `!a || b` (short-circuit).
- Quantifier `kind var in lo..hi: body`: lo and hi are evaluated once outside, the iteration variable is i128, `[lo, hi)`, an empty range if lo>=hi.
  - forall: true, stop when a false is met. exists: false, stop when a true is met.
  - sum: checked add from i128 0 (`"i128 overflow in +"`).
  - count: +1 from i128 0 when true (no check, no nsw, as in the canonical reference).
  - max/min: start from the first value; empty range → `"max over an empty range"`/`"min over an empty range"`.
- Multiple requires are in declaration order, panicking at the first failure.

## 8. Rust bindings (`.rs`, brought in with `#[path] mod sol;`)

- Per function, the same public signature as the Rust canonical reference: `pub fn f(a: &[i64], x: i64) -> Option<i64>` (array argument `&[i64]`, array return `Vec<i64>`, bool, `Option<i64>`, `Result<i64, i64>`, unit has no return type).
- Declare `pruv_abi_*` in an `extern "C"` block (using the same name without `#[link_name]` is fine), and public wrappers are `#[inline]`.
- Array return: if len>0, `Vec::from_raw_parts(data, len, len)` (safe because it was allocated by the Rust allocator); if len==0, `Vec::new()`.
- Option/Result: build the Rust constructor from the tag (transmute forbidden).
- A function with the `io` effect ("io" in `f.effects`) calls `std::io::Write::flush(&mut std::io::stdout())` before the call.
- Allocation wiring: the binding defines `#[no_mangle] pub extern "C" fn pruv_host_alloc(len: i64) -> *mut i64` and `pruv_host_free(data: *mut i64, len: i64)` (`std::alloc::alloc`/`dealloc`, `Layout::array::<i64>(len)`; on failure `std::alloc::handle_alloc_error`), `pruv_host_alloc_zeroed` (`alloc_zeroed`), and `pruv_host_flush` (`std::io::stdout().flush()`, result ignored). If there is even one function that returns an array, reference `extern "C" { fn pruv_runtime_rust_allocator_v1(); }` (for example, `black_box` a function pointer inside a wrapper) to prevent linking the wrong runtime.
- Warning suppression: `#[allow(dead_code, non_snake_case, unused)]` on each item. Rust 2021 edition.

## 9. CLI and build commands

```
python pruvc/pruvc.py in.pruv -o out.ll --backend llvm [--rust-bindings out.rs] [--no-verify] [--trust-callers]
```
- `--backend` defaults to rust. If it is llvm and `--rust-bindings` is omitted, the path of `-o` with its extension changed to `.rs` (rejected if it is the same).
- Giving `--rust-bindings` with the rust backend is a usage error (exit 2). A language error is a JSON line + exit 1 as now, and success is `{"ok": true}`.
- Test-harness build (LLVM implementation):
  1. `clang -O2 <cpu> -Wno-override-module -c gen.ll -o gen.o`
  2. `clang -O2 <cpu> -std=c11 -DPRUV_RUST_ALLOCATOR -c pruvc/runtime.c -o rt.o`
  - `<cpu>`: `-mcpu=native` for arm64 (`platform.machine()` is arm64/aarch64), `-march=native` otherwise.
  3. Add `-C link-arg=gen.o -C link-arg=rt.o` to the current rustc command, and `mod sol` is the bindings `.rs`.

## 10. Test harness

- `tests/run_all.py --backend rust|llvm|both` (default rust). The examples and runtime tests run on the chosen backend. Rejection tests run once regardless of backend.
  - LLVM examples: generate `.ll` in three modes → clang object → pass if linking an empty `fn main(){}` executable that includes the bindings as `mod sol` succeeds.
  - The "no unsafe" check of `--no-verify` is for the Rust implementation only. For the LLVM implementation's safe mode, instead check that the `.ll` has no `nsw`.
  - `gen_contains` in runtime JSON is for the Rust implementation only. The LLVM implementation reads `gen_contains_llvm` (optional).
- `bench/harness/run.py --backend rust|llvm`, `build_and_run(sol_path, pid, workdir, noperf=False, llvm_path=None)` (if llvm_path is given, link the LLVM implementation). If the executable ends with a nonzero code it is `wrong` (+`exit_code`); if not noperf and all tests passed but there is no PERF, it is `wrong`.
- `bench/mutate.py <src> <out> [--backend llvm]`: both the proof build and the `--no-verify` build use the same backend.
