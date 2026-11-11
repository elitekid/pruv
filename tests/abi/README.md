# tests/abi — Windows x64 external wrapper (sret) samples

## Purpose
`docs/M3_C4_SPEC.md` §7: on Windows x64, a 16-byte Option/Result return must be emitted **from the start** not as a `{i64,i64}` value return but as
`void` + a first hidden `ptr sret({i64,i64}) align 8`. This folder holds the expected IR samples for that,
and the checks possible on this Mac (cross COFF object generation, verify, symbols, signature comparison against a C reference).
Names and argument order follow `abi_of` in `pruvc/llvmgen.py` (lines 1214–1285); only the return was changed.

## Running
```
.venv/bin/python tests/abi/check_abi.py [--ir-tool PATH]     # the environment variable PRUV_IR_TOOL also works
```
- With `--ir-tool`, it runs `PATH obj IN.ll -o OUT.o --target x86_64-pc-windows-msvc` (turning the given IR into an object as is);
  without it, `llc -mtriple=x86_64-pc-windows-msvc -filetype=obj -O2`.
- Note: generating a Windows object from the Python implementation's (legacy) IR is not supported (it returns Option/Result as a `{i64,i64}` value, which does not match the MSVC ABI). The `abi_lower` check was removed on 2026-11-11. Windows-target IR is produced with the Rust implementation's `pruvc --target`.
- Tools are taken from `/opt/homebrew/opt/llvm@22/bin` first, otherwise from PATH.
- If any check fails, exit 1. The last line is always `The Windows execution ABI cannot be verified on this Mac: Windows CI is required`.

## Boundaries the samples check
| File | Boundary |
|---|---|
| `win_x64/opt_ret.ll` | Option return: void + first hidden sret align 8, tag zext + payload store, the Some/None two paths |
| `win_x64/res_ret.ll` | Result return (ok/err), same sret shape |
| `win_x64/args_0_1_5.ll` | 0/1/5 arguments + sret. Since sret takes RCX, up to 3 user arguments go in registers, the rest on the stack |
| `win_x64/arr_ret.ll` | Array return: last out pointer + void, no sret |
| `win_x64/struct_opt.ll` | User struct (including an Option field): word-array pointer argument / last out pointer, no sret |
| `win_x64/ref.c` | Reference for how clang lowers a C 2×int64 return (declare and define signatures) |
| `win_x64/rust_extern.rs` | Rust extern call driver to run on the Windows CI |

## Runtime v2 link test
`check_runtime_v2.py [--pruvc PATH]` actually links the 6 cases of G2 A4 (`docs/G2_A4_IMPL.md` §6) on the host target:
new bindings + new runtime (`g2a_u8_ret`, `arr_ret`) must succeed (for the `[u8]` side, `pruv-alloc-balance` is checked); new bindings + old runtime,
old bindings imitated without the v2 helper + new runtime, and new bindings + malloc runtime (no marker) must fail the `rustc` link with the expected symbol name.
`runtime_v1.c` is a frozen copy of `pruvc/runtime.c` at the A3 commit (bec0348) and serves only as the old runtime (do not modify).
Each case prints one line, `ok <name>` / `FAIL <name>: reason`; if any is FAIL, exit 1. It also runs as the `abi_v2` stage of `tests/m3_all.py`.

## To do on the Windows CI (not possible on this Mac)
1. Turn the samples and the actually generated IR into objects, link them with the MSVC linker against `rust_extern.rs` and the C caller, and run them.
2. Native execution: Some/None, Ok/Err, i64 MIN/MAX, 0/1/5 arguments, repeated calls (100,000 or more),
   Option inside a struct, array return.
3. Compare our signatures with the 2×int64 return IR produced by cl/clang-cl (this folder's check_abi.py is also run together on the CI).

## core/abi.rs porting plan (draft)
```rust
pub enum Target { MacArm64, MacX64, LinuxX64, WinX64 }

pub enum RetPlan {
    Void,
    Scalar,            // i64 / bool(zext)
    TaggedRegs,        // { i64, i64 } value return (macOS, Linux x64)
    TaggedSret,        // void + first hidden ptr sret({i64,i64}) align 8 (Windows x64)
    OutPtr,            // last explicit out pointer + void (arrays, user types)
}

pub enum ParamPlan { Scalar, Bool, Array /* ptr,n */, Tagged /* tag,v */, UserWords /* ptr */ }

pub struct AbiPlan { pub name: String, pub params: Vec<ParamPlan>, pub ret: RetPlan }

pub fn plan_abi(f: &FnSig, target: Target) -> AbiPlan;
pub fn emit_wrapper(plan: &AbiPlan, f: &FnSig, tt: &TypeTable, out: &mut String);
```
- `plan_abi` splits only the Option/Result return by target, choosing `TaggedRegs`/`TaggedSret`; everything else is target-independent.
- `emit_wrapper` turns the `{i1,i64}` after the entry call into two i64s with the tag zext'd. `TaggedSret` stores into the two slots of the sret pointer and does `ret void`.
- The sret attributes of the declaration, the definition, and the IR call site are produced from the same plan so that they match.

## Unverified assumptions
These samples were only written and never run (no shell). The LLVM 22 syntax and datalayout string,
the shape of the sret attribute clang emits, and the meaning of Result's tag must be checked on the first run.
