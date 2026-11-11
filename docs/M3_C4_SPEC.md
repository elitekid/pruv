# M3 = C4 Design: A Standalone Compiler

**Finalized (2026-11-10), reflecting the design debate. Reference Python commit: `c4b352a`.** The Python implementation stays as the canonical one, and the Rust implementation is built alongside it.
The basis is `BLUEPRINT.md` lines 56–83 and 155–163, the language semantics are in `SPEC.md`, and the backend boundary is in the M1·M2 specs.
Current behavior is defined by `RESULTS.md` §7–§12 and the code. In particular, the M0 contract domain, the iteration budget, and the evaluation-order fix are carried over together.
This batch revises only the design document. The implementation files, commands, and CI below are work instructions for the next batch and do not mean that implementation or measurement is complete.

## 1. Goals, scope, and non-goals

A single `pruvc` file verifies `.pruv` and even produces an executable. It does not require the user to have Python, rustc, or a clang for compiling IR.
z3 and LLVM are statically linked into the compiler. The generated program links only the runtime support objects it needs, and does not include z3 or LLVM.
The system linker and the target C runtime/SDK are borrowed (BLUEPRINT line 58). So linking on an OS with no development tools at all is not guaranteed.

| Item | M3 decision / completion criterion |
|---|---|
| Public targets | Released in the order macOS arm64 → Linux x64 GNU → Windows x64 MSVC → macOS x64; all four targets must pass for M3 to be complete |
| Language | Rust. In Go, both z3 and LLVM go through the cgo boundary, making static linking and cross builds more complex, and the existing tests already use rustc |
| Semantics preservation | No language features added. AST, checking, proof, Rust/LLVM output, and execution results are cross-checked against the Python implementation |
| Regression suite | Finally, the existing `--backend both` 363 cases must pass on each of the two compilers. Until the Rust source backend is complete, count 'the LLVM backend rows only' separately |
| Standalone | Output and panic 101 are verified for an executable built directly from Pruv main; compiling works in an environment without Python/rustc |
| Out of scope | Embedding LLD, Cranelift, inkwell, self-hosting, new optimizations or proof strategies, language extensions, enum union layout |
| Distribution promise | A single compiler file, not a fully static OS execution environment. Dependencies on OS libraries, the linker, and the SDK are disclosed |

## 2. Crate layout, dependencies, and build environment

`pruvc-rs/` is placed as a separate Cargo workspace. This avoids name collisions and keeps the Python `pruvc/` runnable.
Initially it is split into three crates: `pruv-core` (frontend and output), `pruv-proof` (z3), and `pruvc` (CLI, LLVM, linking).
The library API is `parse → check → verify → gen`, and after checking the AST is read-only. The AST is not modified during code generation.

| Python / existing file | Rust location (under `pruvc-rs/crates/`) | Responsibility |
|---|---|---|
| `vast.py` | `pruv-core/src/ast.rs`, `diagnostic.rs` | 14 expressions, 10 statements, 9 declaration/auxiliary nodes, 33 concrete nodes in total; Type is just a name |
| `vparser.py` | `pruv-core/src/lexer.rs`, `parser.rs` | Tokens, positions, recursive descent, negative-literal folding |
| `typeinfo.py` | `pruv-core/src/typeinfo.rs` | Nominal types, declaration order, stable dependency order |
| `check.py` | `pruv-core/src/check.rs` | Types, effects, ownership, recursion ban, first-error order |
| `codegen.py` | `pruv-core/src/codegen.rs`, `emit_common.rs` | Rust output comes last; the common `show`, `emit_public_types`, `match_sorted_requires` are ported earlier, in the LLVM stage |
| `verify.py` | `pruv-proof/src/{lib,model,symbolic,obligation}.rs` | z3 model, state, domain, proof obligations, counterexamples |
| `llvmgen.py` | `pruv-core/src/{llvmgen,abi,bindings}.rs` | Body text IR / target wrapper / Rust bindings are separated, using the common output module |
| `pruvc.py` | `pruvc/src/{main,cli,driver}.rs` | Arguments, output coordination, JSON, exit codes |
| New object/link layer | `pruvc/src/{lib,llvm,target,link,runtime}.rs`, the development tool's `abi_lower.rs` (removed 2026-11-11) | LLVM C API, linking, and embedded objects are shared; the IR ABI post-processing is exclusive to pruvc-ir-tool |
| `runtime.c` | read from the original by `pruvc/build.rs` | No separate copy; compiled per target and generated into `OUT_DIR` |

The AST is expressed with enum+struct, and recursive expressions are owned via Box/Vec. `IndexMap` and Vec preserve the order of declarations, fields, functions, and assumptions.
HashMap/HashSet is used only for lookup and containment checks. If iteration results enter diagnostics, names, or output, the order must be defined.
Integer tokens are stored as a sign plus a normalized decimal string. The lexer does not reject inputs even beyond i128; it sends them to the checker's `int_range`.
`-9223372036854775808`, consecutive unary `-`, and underscores are handled as in Python (`vparser.py:47,396`, `check.py:335`).
line/col start at 1 and count in Unicode characters, like Python strings. UTF-8 byte offsets are not used as col.

### Pinned dependencies

| Dependency | Choice / how it is pinned | Basis / confirmation gate |
|---|---|---|
| `z3` | `=0.22.0`, `vendored` | Main-agent decision. Does not depend on the system libz3 |
| `z3-src` | `=503.3.0`, pinned in Cargo.lock to a single version including z3-sys's transitive dependency | Runtime version `5.3.3.0` confirmed in the prototype (§8) |
| Python `z3-solver` | `==5.3.3.0` pinned in the dev environment | Based on the .venv the main agent investigated. Also record the actual full z3 version of both implementations |
| `llvm-sys` | 221.x, `force-static`; the prototype built with 221.1.2, the final lock is 0B | Targets LLVM 22. `prefer-static` silently falls back to dynamic linking, so it is forbidden |
| LLVM | Source `22.1.8` + source hash / configuration hash pinned | Aligns dev Homebrew llvm@22 with the distribution CI |
| `indexmap`, `serde`, `serde_json` | Choose from 2.x, 1.x, 1.x respectively, then commit the exact version and Cargo.lock | Order, AST dump, JSON; automatic dependency updates forbidden |
| `cc`, `tempfile`, `find-msvc-tools` | Choose from 1.x, 3.x, 0.1.x respectively, then commit the exact version and Cargo.lock | C compilation at build time, temporary files, Windows linker/SDK discovery |
| Rust toolchain | Confirm the MSRV on the first build, then pin down to the patch in `rust-toolchain.toml` | Do not finalize by guessing the versions the LLVM/z3 crates require |

The diff and snapshot of the reference code `c4b352a` plus the 0A minimal alignment change, the test manifest SHA-256, the 0B final dependency lock, and the §8 prototype environment record are all separate things.
The manifest hash is produced after 0A fixes the inputs, flags, and expected values, and is not estimated in this document. The 0B deliverable is the workspace Cargo.toml, Cargo.lock, toolchain file, and dependency source hashes
in which the ranges above are replaced with exact versions. CI builds only with `cargo build --release --locked`.
Check with `cargo tree -e features` that specifying `z3-src` directly is consistent with the transitive dependency constraints, and fail if there are two copies of z3.
`gh-release` is not used because of the report in [z3#11266](https://github.com/Z3Prover/z3/issues/11266) that libz3.a is missing after 5.3.0.
Version pinning is a measure that removes version difference as a variable. Even with the same version, verdicts can differ because of build options, platform, query shape, and time.

| Build environment | Usage rule |
|---|---|
| `LLVM_SYS_221_PREFIX` | The exact LLVM 22 install prefix; for development, the Homebrew llvm@22 the main agent confirmed (22.1.8, 694 .a files) |
| `CC`, `CXX`, `AR`, `CMAKE_GENERATOR`, `CMAKE_BUILD_PARALLEL_LEVEL` | Pin the z3/LLVM/runtime build tools and parallelism; limit parallelism when memory is short |
| `CC_<target>`, `AR_<target>` | Per-target settings of the cc crate; do not mistakenly use host tools for the cross target |
| `SDKROOT`, `MACOSX_DEPLOYMENT_TARGET` | Pin the macOS SDK and minimum OS; the values of the compiler, runtime, and objects must agree |
| `RUSTFLAGS`, Windows CMake CRT settings | On Windows, unify Rust, z3, LLVM, and the runtime with `-C target-feature=+crt-static` and the `/MT` family |
| `OUT_DIR`, `HOST`, `TARGET` | Provided by Cargo. The runtime target is TARGET; do not confuse it with the host running the build script |
| `PRUVC_LINKER`, `PRUVC_SYSROOT` (new runtime settings) | User-specified linker / target SDK; take precedence over auto-discovery, and are treated as an execution path, not a shell string |

The LLVM development install is not copied into the distribution. In CI, a static bundle is built and cached with `BUILD_SHARED_LIBS=OFF`, `LLVM_BUILD_LLVM_DYLIB=OFF`,
`LLVM_LINK_LLVM_DYLIB=OFF`, and `LLVM_TARGETS_TO_BUILD=X86;AArch64`.
Unneeded LLVM tools, tests, examples, and optional compression/XML dependencies are turned off or supplied statically. Check the actual dependencies, including the C++ standard library.
The official Windows distribution's static libs are not trusted as a source, because of the report in [llvm-project#172890](https://github.com/llvm/llvm-project/issues/172890) that libxml2s.lib is missing.
The local install, external reports, and z3 version above are investigation results provided by the main agent and were not re-verified by external downloads in this document's work.

## 3. CLI, output formats, and target policy

```text
pruvc app.pruv -o app.rs               # M3 default: keep the existing Rust source output
pruvc app.pruv -o app --emit exe
pruvc lib.pruv -o lib.ll --backend llvm # existing command: .ll + default lib.rs bindings
pruvc lib.pruv -o lib.rs --backend rust
pruvc lib.pruv -o lib.o --emit obj --rust-bindings lib.rs
pruvc app.pruv --emit exe --target x86_64-pc-windows-msvc -mcpu=generic
```

| Option | Decision |
|---|---|
| input, `-o` | One input. `-o` is required for text and obj; only exe falls back to the input stem when omitted. Input and output paths that coincide are rejected |
| `--backend rust\|llvm`, new `--emit exe\|obj\|ll\|rs` | Merged into one internal output kind (rs/ll/obj/exe) by the decision table below. backend is a compatibility alias; no extension inference |
| `--rust-bindings PATH` | LLVM only. For ll, when omitted, the extension is changed to .rs as before; for obj, generated only when given explicitly; rejected for exe |
| `--no-verify`, `--trust-callers` | Unchanged. Safe-mode arithmetic checks, runtime requires, and trust semantics are kept |
| `--contract-budget N` | The hidden test option is kept. Default 2^30, range 1..2^62, a budget shared across one public entry |
| `--also-llvm LL RS` | Stays hidden. Allowed only when the decision-table result is rs; parse/check/verify are shared once |
| `--target TRIPLE` | Defaults to the host. Only the four public triples are allowed; explicitly converted to the LLVM triple. Unsupported targets exit 2 |
| `-mcpu=generic\|native\|NAME` | Default generic; tests and bench state native explicitly. native only on the host target; CPU names are validated per target |

| backend / emit | omitted | rs | ll | obj | exe |
|---|---|---|---|---|---|
| omitted | rs | rs | ll | obj | exe |
| rust | rs | rs | usage error | usage error | usage error |
| llvm | ll | usage error | ll | obj | exe |

In M3, both implementations keep the default Rust source and the requirement of `-o` for the default rs. Switching the exe default is a separate release decision after M3 (§10).
`--also-llvm` shares one parse/check/verify and writes no output at all if verification fails. The principle of writing only after all text generation succeeds is also kept.
Multiple output paths are normalized to prevent duplicates, and Windows case-insensitivity and existing-file aliases are also checked. On failure, an existing successful file must not be mistaken for the new output.

| Result | stdout / exit |
|---|---|
| Success | one line `{"ok": true}` / 0 |
| Language/proof error | PruvError JSON line / 1. stage,line,col,code,message,fix[,counterexample], UTF-8 non-ASCII preserved |
| Usage error | usage + stderr details as before / 2; when cross-checking, only the difference in the executable name in the error sentence is normalized |
| Internal defect | stage=internal, code=internal_error, line=col=0 / 3 |
| New build failure | JSON with stage=link or codegen / 1; a separate list such as `linker_missing`, `link_failed`, `target_runtime_missing` |

The existing 66 error codes (parse 5, check 46, verify 14, internal 1) are pinned in a separate manifest. New build diagnostics do not reuse or overwrite this list.
Success and language diagnostics go to stdout; linker details are summarized in the diagnostic and the raw text is left on stderr. Existing internal-error paths such as file I/O are also pinned by differential tests.

## 4. Porting order, file boundaries, and per-stage completion criteria

No two workers own the same file at the same time. Each batch fixes its interface first and the next batch consumes it.
Only the integration owner edits the workspace manifest and the CLI wiring. `core`, `proof`, and `bin` below are each the src of the crates in §2.

| Stage / batch | Exclusive file boundary | Completion criterion / cross-check point |
|---|---|---|
| 0A Minimal determinism and reference | `pruvc/check.py`, `pruvc/verify.py`, `tests/diff_py_adapter.py` | Sort only the two set-consuming iterations; fix the reference snapshot, manifest hash, and the diagnostic/query order under several hash seeds |
| 0B Lock and real-obligation prototype | workspace manifests/lock/toolchain, `ci/m3/`, z3 prototype | With Rust z3, reproduce aggregate lemmas, Opt/Res/user Datatype, havoc, nested quantifiers + patterns, and retries; cross-check against Python SMT-LIB and verdicts; record the exact lock and per-platform static dependencies/cost |
| 0C Object and link tools first | `bin/{lib,llvm,target,link,runtime}.rs`, `bin/bin/pruvc-ir-tool.rs`, the tool-only `abi_lower.rs` (removed 2026-11-11), `pruvc/build.rs` | Python .ll → LLVM object → embedded runtime and system link; remove clang for the test harness's IR; check the i128 helper symbols |
| 0D Windows ABI sample | `tests/abi/`, `core/abi.rs` plan | A small .ll with the per-target wrapper emitted directly → cross object and signature check; Windows execution in CI; start the parser after reviewing 0A~0D |
| 1 Parser | `core/{ast,diagnostic,lexer,parser}.rs` | Compare parse AST JSON and parse errors; maximal integers, Unicode positions, and all 33 nodes are covered |
| 2 Checker | `core/{typeinfo,check}.rs` | Identical typed AST, type order, and type/effect error JSON; identical recursion and ownership rules |
| 3 Verifier | `proof/{lib,model,symbolic,obligation}.rs` | Compare first-attempt/retry SMT-LIB, verdicts, and diagnostics per obligation; no public proof-mode CLI before approval |
| 4 LLVM output and common functions | `core/{llvmgen,abi,bindings,emit_common}.rs` | show, emit_public_types, match_sorted_requires, and Rust bindings first; the original .ll/bindings porting gate, the per-target wrapper expected values, and the M0/G1 regression suite |
| 5 Object and link integration | handover of 0C file ownership, `pruvc/runtime.c` | Direct O2 objects, system link, main shim, embedded runtime, MSVC count initialization, linker diagnostics |
| 6 Windows ABI integration | `core/abi.rs`, `tests/abi/` | The Rust generator emits the target ABI wrapper directly; sret C/Rust calls and array/set round trips pass in Windows CI |
| 7 Rust source output (last) | `core/codegen.rs` | The .rs byte porting gate, the BLUEPRINT stage-6 multi-language output plan, and the existing Rust output test tally maintained |
| T Differential harness | `tests/{compiler_driver,diff_compilers}.py`, the 5 existing invocation harnesses | The §5 selection option, result classification, and reproduction artifacts. In parallel with 1~7 at interface granularity |
| I Integration and distribution | `bin/{main,cli,driver}.rs`, workspace wiring, `.github/workflows/m3.yml` | All of the existing 363, CLI 185, bench, mutation testing, fuzzing, and the standalone-exe gates pass |

| Shared state / function boundary | Sole ownership / handover conditions |
|---|---|
| The proof body corresponding to verify.rs and the llvmgen.rs body | Handled by a single worker; Model/fresh/assumptions/cache and FnGen temporary names, scopes, release, and contract environment are not split per function for parallel edits |
| FnGen basis | `llvmgen.py:192–203·314–336·552–588·973–1023`; the expression/statement evaluation, release, and contract functions consume the same mutable state |
| Parallel owners | Other workers handle the ABI plan and wrapper output in `abi.rs`, the bindings in `bindings.rs`, the common functions in `emit_common.rs`, and the differential tools and samples; they do not edit the body files |
| Handover | Fix the function signatures, formats, and order for: read-only typed AST and TypeTable and ABI plan → wrapper/bindings text; typed AST → verify/gen; obligation trace → differential. FnGen state is not passed; integrate after the sample/region differential passes and sole ownership is stated |

0A is included in M3. `check.py:134` iterates the call set (created at `:143`), `verify.py:671` starts from assigned,
and the havoc at `:686` iterates the set created at `:793`. In Python, sort the two consuming points in lexicographic name order, and Rust uses the same order.
Declaration order is not changed to lexicographic. After re-confirming the existing 363 cases and the mutation-testing verdicts before and after the change, update the canonical snapshot with the reference commit plus the minimal diff.
Record it if the proof time, counterexamples, or the first path of multiple recursion changes. Fixing a single hash seed alone is not considered to have solved determinism.

## 5. Differential cross-check harness and test-harness wiring

### Current call sites (code lines at the time of writing this document)

| File:line | Actual call / wiring | Boundary to change in M3 |
|---|---|---|
| `tests/run_all.py:30,33,42` | PY/PRUVC selection, runs `[PY,PRUVC,src,-o,out]` | Use the common compiler_driver |
| `tests/run_all.py:57,71` | Per-variant cache of runtime.c, turns .ll into objects with clang -O2 | The new comparison path uses the embedded runtime and the LLVM object API for both implementations |
| `tests/run_all.py:168,180,228` | LLVM example link, Rust example lib, runtime Rust main build | Keep the rustc test driver |
| `bench/harness/run.py:8,9,195,197,198` | PY/PRUVC, per-backend command construction and subprocess | Pass the compiler-selection argument through to the build path |
| `bench/harness/run.py:107,111,138` | IR and runtime via clang, link with rustc -C target-cpu=native | New object path, same CPU and optimization conditions |
| `bench/fuzz/run.py:42,45,236,263` | --also-llvm for each of the safe and proof invocations, run_cmd (:60) | Keep verification to once; per-compiler working folders |
| `bench/fuzz/run.py:87,383,448` | Runtime build, objectifying the symbol-uniquified .ll, batch rustc link | After the rewrite, objectify through the LLVM API; prep_llvm does not re-verify with pruvc |
| `bench/mutate.py:45,49,55` | Proof and safe invocations via H.PY/H.PRUVC, H.build_and_run | Pass the selection info through to H, distinguish crash from reject |
| `tests/cli_also_llvm.py:25,31` | Runs PRUVC via sys.executable | Add the selection option; keep the success output, bytes, and no-output-on-failure checks |

`bench/fuzz/generate.py` builds inputs from seed:index and `oracle.py` is an independent parser/interpreter. Neither calls a compiler, and their independence is maintained.
Add `--compiler py|rs` (initial default py) and `--compiler-path PATH` to the test tools. `--backend` remains the output backend selection.
`tests/compiler_driver.py` builds the argv list (py=[pinned Python, PRUVC], rs=[binary]). Every invocation states the backend explicitly.
The Python executable path also supports Windows `.venv/Scripts/python.exe` and pre-checks for the presence of tools on PATH. No shell string concatenation.
The Rust main of the existing tests is kept as is. The rustc dependency of development and testing is separate from the no-rustc path of the user's `--emit exe`.
A development-only `pruvc-ir-tool` that uses the common LLVM API functions is placed in `pruvc/src/bin/` in 0C: it connects already-generated ll→obj, embedded runtime extraction, and system linking.
Files after the fuzzer's symbol rewrite are also processed with this tool. It is not included in the distribution, and it has no feature to declare the input IR as verified Pruv.
On Windows, the Python implementation was also to lower to the target ABI with this tool before objectifying. The existing clang path alone leaves the Python implementation's 16-byte return defect. → Removed (2026-11-11, RESULTS §24). Objectifying Python-implementation IR on Windows is not supported.
`--input-abi legacy|target` is exclusive to this tool. It distinguishes Python-original from per-target directly generated IR and checks signatures to prevent double application of sret. → Removed (2026-11-11, RESULTS §24).
The limited `abi_lower` and `--input-abi` are removed once the Python-implementation cross-check is finished. They are not put into the distributed CLI or the Rust generator path. → **Removed (2026-11-11, RESULTS §24)**: ir-tool objectifies the IR it receives as is.
A comparison using the same objectification layer is a differential test of the frontend port. The ABI correctness of the shared layer itself is verified separately by the independent C/Rust samples of §7.

### `tests/diff_compilers.py` (new tool)

Runs the two CLIs as separate processes with the same input, flags, target, CPU, and workload. A new process is used per input to align the model sequence.
`tests/diff_py_adapter.py` and the Rust test API emit the parse/typed AST and verification trace (outside the public CLI contract).
AST test schema v1 serializes only the explicitly specified nodes, fields, positions, types, and list order. No deserialization or general-purpose IR is built; the version is bumped when it changes.
The input manifest stores must_reject, examples (including rejection examples), the runtime's flags_matrix and contract_budget,
the 10 problems of bench `solutions/pruv_agg`, mutants, and fuzzer-generated sources, inputs, and seed:index. The fuzzer fixes its candidate list first to eliminate tail differences from parallel submission.

| Comparison subject | Pass rule |
|---|---|
| parse/typed AST | Compare as JSON only the kinds, fields, positions, and ty specified in the schema. Integers as decimal strings, null preserved, only object keys sorted; list order preserved. The TypeTable dependency order is compared separately |
| Error JSON | Exit code, diagnostic count, order, and stage/code/line/col must be identical. message/fix are also compared, with only unknown reasons and tool paths explicitly normalized |
| .rs, .ll, bindings | While the original generator is ported as is, byte equality is the porting gate (including whitespace, names, newlines). Only Windows Python text-mode CRLF is reported separately with LF normalization |
| Approved output changes | Afterwards managed as individual expected-value changes. Per-target Windows wrapper, exe main, and triple/datalayout have separate expected IR; the ABI, safety check, evaluation order, and execution-result gates remain mandatory |
| Proof | Compare per obligation ID, order, and first attempt/retry the SMT-LIB text and sat/unsat/unknown (§6); unknown is not success |
| Counterexample | Byte-identical numbers are not required. The counterexample verdict below distinguishes validity, partial information, and lemma omission |
| Object, exe | Byte equality is not required (LLVM/linker differences). On the same target, compare exit, stdout, and `pruv:` diagnostics |
| Execution | Exact comparison for the same backend and mode. Exclude Rust panic decoration and compare the pruv line; proof/safe crossing only when the oracle expectations are the same |

A counterexample cannot be fully re-run from the public JSON alone: arrays show only the first 8 elements, the state also contains havoc locals, and `_note` is a model that omits the aggregate definitions.
For complete inputs of finite scalars and arrays, the violation is re-evaluated by the independent oracle. For quantified, havoc, and relaxed cases, the original query (pc, guard, obligation, lemmas) and the full model/interpretation are preserved and classified as 'undecided'.
Cases with too little information to re-evaluate are also tallied separately as `incomplete_cex`/`relaxed_cex`. Undecided counterexamples do not block release, but their count is published and they are not counted as valid counterexamples.
Developing a separate model verifier is out of M3 scope. Undecided counterexamples are distinguished from proof-verdict mismatches in the existing regression suite.
An invalid counterexample, a sat/unsat conflict, or a verification pass with an oracle contract failure is an immediate failure. A model difference by itself is not a failure.
The failure folder stores the input, argv, versions/hashes, raw output, AST, IR, obligation SMT, model, and time, and `--replay` reproduces the same case.

### The three test gates

| Gate | Execution scope / tally |
|---|---|
| During work | Run the differential and samples only for the changed area; do not repeat the full regression suite, bench, and fuzzing on every edit |
| Full differential at the end of a batch | Two compilers × the existing regression suite once each, plus the relevant CLI tests. Before the Rust source backend is complete, count 'the LLVM backend rows only' separately, and tally the final 363 cases, the 185 CLI cases, and the new tests separately |
| Milestone | bench 10, mutation testing 81 verdicts/codes, fuzzer seeds 41·56·57 + new seeds (two compilers × Rust/LLVM × proof/safe, rejections only in safe, oracle limit is incomplete), static dependencies and direct exe on four platforms |

Each compiler process has a timeout (e.g., 300 seconds), the upper bound on concurrent z3 runs across both compilers combined is the CPU count; a process timeout is classified separately from a solver unknown.
Taking the roughly 50~106 seconds of the RESULTS §10·§12 regression suite as the baseline, we measure with the goal that the full two-compiler cross-check under the same load does not exceed 2× the baseline.
bench performance is measured separately on a quiet machine, and the existing p04 timeout is excluded from normal measurement. `tests/standalone/` checks main, IO, allocation/free, panic 101, budget, and entry-point/path errors.

## 6. z3 version, determinism, and time limits

| Point | Rust reproduction rule |
|---|---|
| Logic | Int, Bool, Array(Int→Int), Datatype, uninterpreted Function, ForAll/Exists (including patterns); substitute/simplify kept |
| Unused APIs | No switch to BitVec, no push/pop, no rlimit introduced. Proof-strategy improvements are measured separately after the port |
| Datatype | First create Opt/Res together with the same names and constructor order. User types follow the TypeTable dependency order |
| `_MODEL_SEQ` | Starts at 0 at process start, increments with each Model creation; `m1t0!Type` etc. as is. Consecutive library calls also increment by the same count as in Python |
| fresh | k=0 per function; fresh pre-increments to give `base!1`, and the array length is `.len`. Havoc set values reproduce even the existing `name!h{k}` post-increment |
| Order | Preserve the source order of functions, parameters, fields, variants, paths, assumptions, and lemmas. Only the havoc/call-set sorting decided in 0A is applied |
| sexpr internal keys | The aggregate cache key (kind, Tc.sexpr(), outer count) and the lemma deduplication key as is; check Rust Display against Python sexpr goldens, and do not cover differences with simple normalization |
| solver | A new Solver per obligation (timeout=8000ms), pc→guard→Not(ob). If the result is not unsat and there are lemmas, add the lemmas to a new Solver and retry |
| Model | `model_completion=true`; keep the environment insertion order and the Pruv representation of user types. Also keep the `_note` of an unknown after a relaxed sat |

For each obligation, record the SMT-LIB containing the declarations, assert order, patterns, and solver settings (including timeout) of the first attempt and the retry separately, along with the verdict.
Use the equivalent of Python `Solver.sexpr()`/`to_smt2` and the same output from Rust, but record any missing solver settings together as `set-option` (e.g., `:timeout 8000`) so they are applied on replay.
Textual identity is the primary criterion. If they differ, replay both raw texts with the same z3, compare the verdicts, and record the cause of the difference. Even with the same SMT, the time-based verdict is not guaranteed.
0B goes beyond an Int smoke test and reproduces the real Pruv obligation shapes (aggregate lemmas, Opt/Res/user Datatype, havoc, nested quantifiers + patterns, retries) and is reviewed against this criterion.
Automatic flattening and quantifier weight/pattern changes by the z3 crate are also checked with this trace.
Required low-level APIs are limited to a small z3-sys wrapper, and lifetimes and context ownership are audited. No parallelization during obligation generation.
The timeout is 8 seconds per call, so if there is a lemma retry, one obligation can use about 16 seconds. Do not confuse this with the whole-process limit.
For mismatches near 8 seconds, store the raw SMT, reason_unknown, and elapsed time, and rerun each side 3 times in the same unloaded environment.
Additional long-limit runs are for cause analysis and do not substitute for passing the 8-second gate. Cases that differ only in time are isolated as `inconclusive_timeout`.
If a verdict mismatch in the existing fixed regression suite remains, M3 is not complete. Undecided fuzzing cases are also published with their count and cause, and subtracted from the passing sample count.

## 7. LLVM object, linking, runtime, and Windows x64 ABI

The Rust text generator emits the wrapper directly from the target ABI plan. The order is `LLVMParseIRInContext2` → set the target triple/datalayout and insert the exe main → `LLVMVerifyModule`
→ `LLVMRunPasses("default<O2>")` (passing the TargetMachine) → re-verify → generate the object with `LLVMTargetMachineEmitToFile`.
Call the LLVM C API directly through llvm-sys and wrap memory and error-message ownership in RAII. inkwell widens the porting surface, so it is considered later.
`--emit ll` is the directly generated text before optimization. The existing macOS/SysV keep output without a triple/datalayout, and Windows attaches the target information.
The original porting gate applies to the existing ABI output. Windows direct output has separate expected values and is not subject to byte equality with the Python original.
`core/abi.rs` is the LLVM-independent target ABI plan and wrapper output function. `llvmgen.rs` uses it to emit the external `pruv_abi_*` per target from the start.
The IR post-processing `abi_lower` is limited to the development tool that objectifies Python-original IR on Windows (the end condition in §5). It is not in the Rust CLI path. → Removed (2026-11-11, RESULTS §24). Objectifying Python-implementation IR on Windows is not supported.
ir-tool does not insert main into library IR. The 0C link sample uses IR with an entry point or an independent driver.
The distribution CPU is generic, and only host bench is native; PIC/PIE, minimum OS, and code model are fixed as target settings and aligned with the link settings.

### Executable and runtime

exe requires the argument-less unit main of `SPEC.md:45` and handles IO/alloc according to the existing effect checks. An invalid entry point is rejected with an exe build diagnostic.
Insert the IR entry shim `define i32 @main()` into the same LLVM module, calling the internal `main__pruv_entry` and returning 0. The trust setting is reflected as is in entry generation.
Pruv function bodies and ABI names use the existing mangling, so they do not collide with C main. No C main is created for ll/obj library output.
The OS CRT calls main, and `_start`/`mainCRTStartup` are not implemented directly.
`build.rs` creates the target runtime object with cc and embeds it with `include_bytes!`. When linking the exe, it is extracted into a dedicated temporary directory and cleaned up on exit.
Distinguish the two variants, default malloc/free and `PRUV_RUST_ALLOCATOR`, and for each the `PRUV_COUNT_ALLOCS` test variant. exe uses malloc, and the Rust driver uses the Rust allocator.
Keep the `pruv_runtime_rust_allocator_v1` link check on the Rust allocator object to prevent the combination where a Vec frees a malloc array.
For the count variant on Windows, the current GCC-style `__attribute__((constructor))` needs to be moved to an initialization path that also works on MSVC.
Investigate per target the unresolved helper symbols emitted by contract i128 operations, such as `__divti3`, `__modti3`, and `__multi3`. If the system does not supply them,
embed together the needed static objects from the compiler-rt builtins of the same LLVM version (especially MSVC). Do not rely on paths that rustc happened to supply.
By default the distribution embeds only the host runtime. ll/obj for other public targets can be produced, but exe is allowed only when the runtime, SDK, and linker for that target are available.
A development build that adds other target runtimes is possible but must state the list it holds, and if missing, fails with `target_runtime_missing`.

| Platform | Linking / remaining user dependencies |
|---|---|
| macOS | Discover SDK/cc with xcrun, use cc as the link driver (internal ld). Command Line Tools and the SDK are required |
| Linux | Link objects, CRT, and libc with the cc driver; the reference glibc for distribution and the CRT/startup objects and linker for development are required |
| Windows | Discover link.exe and the MSVC/UCRT/Windows SDK lib paths with find-msvc-tools, matching x64 and the CRT; MSVC Build Tools are required |

Even if the macOS cc is clang, **there is no clang call for compiling IR**. Only the role of a system link driver is borrowed here.
Compiler development requires a C/C++ compiler, CMake, and static-library builds, but users do not compile runtime.c.
Link arguments are passed via argv/response files, and paths with spaces and Korean characters are tested. Embedding LLD is deferred (lld-rs is stuck at LLVM 14, and the latest integration needs a C++ shim).

### Windows x64 per-target wrapper

The incomplete item at M1 spec §4 (near line 65) and RESULTS line 124 is resolved here. Merely attaching the triple does not automatically convert the C struct return ABI.

| Function boundary | Applied on Windows x64 |
|---|---|
| External `pruv_abi_f`, returning Option/Result | Instead of returning `{i64,i64}` (16 bytes), emit from the start as `void` + a first hidden `ptr sret({i64,i64}) align 8` |
| The Rust extern of the same function | Keep the `#[repr(C)] Pruv__Tagged` by-value return declaration; rustc's MSVC C ABI creates the hidden first argument |
| Internal body/entry | Keep the own LLVM set arguments and returns. All are called with the same module/rules, so they are not targets of external C ABI lowering |
| Array return | Keep the existing last explicit out pointer + void; adding a hidden sret is forbidden |
| User struct/enum | Keep the existing word-array pointer argument / last out pointer (no exception even when the size is 16 bytes) |
| Scalar, unit, Option/Result arguments | Keep i64/void and the tag,payload spreading |

While porting the wrapper section of `llvmgen.py:1214–1285`, turn the entry's internal `{i1,i64}` result into two i64 with the tag zext'd and store them to the sret pointer.
Match the attributes of directly generated declarations, definitions, and IR call sites. The actual hidden-pointer return-register handling is left to LLVM's target lowering.
The existing register returns of macOS arm64/x64 and Linux x64 are kept. The Windows post-processing of the Python original remains only in the cross-check tool.
The Windows-specific expected IR is cross-checked against an ABI sample that builds the C 2×int64 struct return with cl/clang-cl, and against Rust extern calls (a development test tool).
Natively execute Some/None and Ok/Err, MIN/MAX, 0, 1, and 5 arguments (register/stack boundary), repeated calls, Option inside a struct, and array returns.
On this Mac, cross COFF generation, LLVMVerifyModule, and symbol/signature checks are possible, but the Windows execution ABI cannot be verified. A Windows CI success is mandatory.

## 8. Distribution, CI, and estimated cost

| GitHub Actions runner | Artifact / required checks |
|---|---|
| macOS ARM64 runner (an ARM64 larger runner such as `macos-14-xlarge`) | aarch64-apple-darwin; SDK, minimum OS, direct execution |
| macOS Intel runner (a provided pinned image such as `macos-15-intel`) | x86_64-apple-darwin; native regression suite, direct execution |
| `windows-2022` x64 | x86_64-pc-windows-msvc; /MT match, sret round trip, Build Tools discovery |
| `ubuntu-22.04` x64 | x86_64-unknown-linux-gnu; reference glibc, cc link, execution |

Whether the runner label is available is checked when CI work starts, and an architecture assert is added. If no Intel hosted runner exists, a self-hosted runner for it is required.
The cache key includes OS/arch, Rust, LLVM/z3 source hashes, CMake settings, CRT, SDK, and Cargo.lock. Library caches and finished binaries are distinguished.
Release artifacts are one pruvc per target, SHA-256, the license/NOTICE, and build information. A universal macOS bundle is not required.
The cost ceilings are **150MB** per target for the stripped executable, **120 minutes** for CI cold (including the LLVM static bundle), and **15 minutes** with a cache hit.
Measure the per-platform LLVM static-bundle build / compiler link / regression-suite times separately, and also record the total CI time and peak memory.
If exceeded, reduce the targets by keeping only the LLVM targets X86 and AArch64 and turning off unneeded configuration, or decide to revise the goal. A dynamic LLVM distribution changes the BLUEPRINT promise, so it is not used as an alternative.
The release order is macOS arm64 → Linux x64 → Windows x64 → macOS x64; even after a partial release, all four targets must pass for M3 to be complete.

**Prototype measurements (2026-11-10, this Mac arm64 10 cores, Homebrew llvm@22 22.1.8, no ninja)** — z3 =0.22.0 vendored + z3-src =503.3.0 ·
llvm-sys 221.1.2 force-static, release, thin LTO, strip. What it does: one z3 Int query, text IR → `default<O2>` → object → system `cc` link → run.
Below is **a prototype environment record, not a distribution lock**. The 393 seconds is a prototype build using a pre-installed LLVM and does not include the build time of the LLVM static bundle itself.

| Item | Value |
|---|---|
| z3 runtime version | `5.3.3.0` (same as the Python implementation's z3-solver 5.3.3.0) → the version estimate in §2 is confirmed |
| Cold build | 393 seconds (mostly z3 C++), 6 seconds for a rebuild with only code changed |
| Executable | 105MB (initializes all targets with `LLVM_InitializeAll*`; expected to shrink if targets are reduced to X86·AArch64, not measured) |
| Dynamic dependencies | libc++·libz·libxml2·libiconv·libSystem (macOS default, allowed) + **`/opt/homebrew/opt/zstd/lib/libzstd.1.dylib` (not distributable)** |
| API | `LLVMParseIRInContext` gives a deprecation warning in LLVM 22 → this implementation uses `LLVMParseIRInContext2` |

Conclusion: Homebrew LLVM is used only for development. The distribution LLVM is built directly with `LLVM_ENABLE_ZSTD=OFF`, `LLVM_ENABLE_LIBXML2=OFF`, `LLVM_ENABLE_ZLIB=OFF` (or supplied statically), and
0B confirms with the dependency check above that there is no Homebrew path. On Linux, libc++/libstdc++ and zlib must also be static or only those of the reference glibc system.
Confirm the absence of libz3/LLVM DLL, dylib, or so dependencies with macOS `otool -L`, Linux `ldd/readelf`, and Windows `dumpbin /dependents`.
Also check for non-system DLL dependencies of the Windows VC runtime. OS default libraries are allowed, but dependencies on Homebrew or build-directory paths are a failure.
Signing, notarization, installers, and auto-update are out of M3 scope. The release states that an unsigned-executable warning remains; if needed, it is handled as separate work right before distribution.

## 9. Risks and responses

| Risk | Response / confirmation |
|---|---|
| z3 static build time/memory | vendored cache, limited parallelism, separate cold/warm measurement |
| z3-src version estimate error | Cross-check the source hash, headers, and runtime version; if inconsistent, re-decide the lock before implementation |
| Windows CRT mismatch | Unify /MT for Rust/LLVM/z3/runtime, +crt-static for the Rust driver too, dependent-DLL check |
| Missing LLVM static lib supply | Direct CI build, minimal-dependency settings, link smoke on all targets; do not depend on the official Windows package |
| Differences in proof time | Same query, 8 seconds, controlled load, separate timeout-undecided; do not cover with a long-limit success |
| Counterexample differences / partial models | Finite inputs are re-evaluated by the oracle; for quantified, havoc, and relaxed cases, preserve the query/model and publish the undecided count; separate model verifier excluded |
| Nondeterministic iteration | 0A sorting, IndexMap, seed repetition, fixed Datatype/fresh/lemma order |
| Missing user linker/SDK | Report discovery failure as an install-guidance JSON, and explain separately that Python·rustc are unnecessary and the SDK is necessary |
| .ll byte cross-check breaks | Goldens while porting the original generator, approved changes as individual expected values; keep the ABI, safety, evaluation-order, and execution gates |
| Runtime allocator mixing | Embedded-object variant identification, marker link, array return/free, count tests |
| i128 helper symbols, MSVC C syntax | Undefined-symbol check on the direct exe link, embedding builtins, porting the count initialization |
| CLI compatibility regression | Keep the M3 default Rust source, a single backend/emit decision table, regression tests for old option combinations |
| Mistaking a cross-object success for a distribution success | Native execution on four platforms is mandatory; an unexecuted target is incomplete |
| Both implementations share the same defect | Keep the independent oracle, run the existing regression suite, mutation testing, and new seeds in parallel; do not claim soundness from Python agreement alone |

## 10. Open issues and the next first implementation batch

| Open issue | When to decide / criterion |
|---|---|
| llvm-sys 221 patch, other crates, minimum Rust version | Pin exactly after verifying with the 0B minimal build. The version series in this document is not used as the distribution lock |
| Switching the default to exe | Decide in a separate release after M3 by reviewing compatibility cost and migration guidance; M3 keeps the existing default |
| llvm-mingw follow-up evaluation | Initial Windows support is MSVC only. Evaluate later with the same ABI, CRT, allocator, and execution samples; compatibility is not claimed |
| Scope of cross exe | Until the rights to redistribute the target runtime/SDK and the supply method are settled, only native exe is publicly supported |
| Minimum Linux glibc / minimum macOS | After settling the publicly supported versions, pin them in the CI sysroot/SDK; do not claim support for older OSes merely because it works on the current runner |
| Signing, notarization | If needed, a separate distribution batch; for cost overruns, apply the finalized rule of §8 |

**The first implementation batch is 0A~0D+T.** (a) Create the sorted consumption of the call graph and havoc set and the reference snapshot/manifest hash, and record the existing 363, CLI 185, mutation-testing verdicts, and hash seeds 0, 1, 2, and random.
(b) In 0B, cross-check the SMT-LIB and verdicts of the Rust z3 real-obligation prototype (aggregate lemmas, Opt/Res/user Datatype, havoc, nested quantifiers + patterns, retries) against Python and lock the dependencies.
(c) Bring forward pruvc-ir-tool, objectify the Python .ll with the LLVM library, and link with the embedded runtime and the system linker. Check the i128 helper symbols and remove the test harness's clang dependency for compiling IR early in M3.
(d) Check the Windows ABI cross object and signatures with a small .ll in the per-target direct-output form, and confirm execution in Windows CI. T starts with the argv adapter, comparison, and reproduction storage; an unimplemented rs is not counted as a pass.
After reviewing these four results and the lock/cost records, start the real frontend port (1 Parser). In this document revision, implementation, regression runs, and four-platform builds were not performed.

### Design-debate reflection record

| 13 objections | Adopted/revised |
|---|---|
| 1. No determinism criterion | Adopted: minimal fix of the two set iterations in 0A, reference snapshot (§4·§10) |
| 2. z3 smoke test insufficient | Revised: prototype of real Pruv obligations, retry SMT-LIB/verdicts (§4·§6·§10) |
| 3. Object and ABI risk confirmed too late | Adopted: ir-tool, embedded-runtime link, i128, and Windows cross samples first (§4·§7·§10) |
| 4. Permanent constraint of byte equality | Revised: limited to a porting gate, approved expected-value changes and semantic gates kept (§5) |
| 5. AST test IR oversized | Revised: only versioned explicit-schema serialization, TypeTable separate (§5) |
| 6. Priority of the Rust source backend | Revised: kept but last, common functions/bindings first, LLVM rows counted separately (§1·§4·§5) |
| 7. Insufficient proof cross-check information | Adopted: per-attempt SMT-LIB, settings, verdicts, replay with the same z3, sexpr key preserved (§6) |
| 8. CLI default compatibility break | Revised: default rs kept, single decision table, exe switch in a later release (§3·§10) |
| 9. Windows toolchain confusion | Revised: MSVC only initially, llvm-mingw evaluated later with the same samples (§1·§10) |
| 10. Complexity of distribution IR post-processing | Revised: target ABI wrapper emitted directly, abi_lower/input-abi removed after cross-check in the development tool (§5·§7) |
| 11. Cost and release scope ambiguous | Adopted: 150MB/120 min/15 min, separate measurement, staged release, four-target completion (§8) |
| 12. Test cost and counterexample verification oversized | Revised: three gates, process limits, z3 ceiling, undecided disclosed, model verifier excluded (§5·§6) |
| 13. Confusion between shared state and reference/lock | Adopted: sole ownership of bodies, function handover, separation of commit/manifest/0B lock/prototype, §2 references fixed (§2·§4·§8) |
