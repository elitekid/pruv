# tests/abi/winci — Windows x64 execution ABI CI

## Purpose
Confirm by **native execution** the Windows x64 wrapper of `docs/M3_C4_SPEC.md` §7 (Option/Result return = void + first hidden sret).
On the Mac only the IR, object files, and signatures can be checked (`tests/abi/check_generated.py`), so only the execution check is done on a Windows runner. No release build for the 4 platforms is made.

## Producing the inputs on the Mac (commit the results)
```
python3 tests/abi/winci/prepare.py            # creates out/: *.win.ll *.rs *_main.rs *.expected
python3 tests/abi/winci/prepare.py --check    # only checks that out/ matches the committed copy (exit 1 if it differs)
```
- Requires: the Rust implementation of pruvc (`pruvc-rs/target/release/pruvc`, changeable with `--pruvc`), clang, rustc.
- Sources: `tests/abi/gen/*.pruv` (not modified) + `src/*.pruv`. Calls are in `calls.json` (file name → list).
  `"f(args)"` is a Rust expression (called as `sol::f(args)`, with the type `sol::Cell {..}`), and `{"repeat","args","n"}` is a one-line sum of repeated calls.
- `.expected` is the stdout from building the same source for the **host target** and running it on the Mac with the same driver.
  If the Windows result differs from it by even one character, it is an ABI mismatch.

## What the CI does (`.github/workflows/windows-abi.yml`)
`run_windows.py`: `.win.ll` → clang `--target=x86_64-pc-windows-msvc -O2 -c`, `pruvc/runtime.c` → clang (`-DPRUV_RUST_ALLOCATOR`,
dynamic CRT), then rustc (MSVC) links `<name>_main.rs` with the two objects and runs it, comparing stdout with `.expected` (prints a table, exit 1 on mismatch).
In addition, `c_caller.c` (a C caller) is linked with `args_0_1_5.win.obj` and run (can be skipped with `--skip-c`).

## Design for staying within the free quota
One runner (windows-latest), no matrix, cache, or install steps (it uses the runner's default LLVM and Rust), the compiler is not built (the artifacts made on the Mac are committed),
`timeout-minutes: 20`, and the triggers are only `workflow_dispatch` and main pushes that change relevant paths. Expected 10–20 minutes per run.

## Unverified assumptions
This folder was written without a shell and has never been run. Things to check on the first run: compilation of the 3 sources (`src/`), whether runtime.c
builds with the MSVC-target clang, clang's `-fuse-ld=lld` C linking (detection of the MSVC library path), and rustc link warnings.
