# G7: Scoped Parallel Calls (first slice)

Status: **Design for implementation, 2026-11-12; no implementation or measurements performed for this document.**

## 1. Goal and verified repository facts

Goal: run a fixed group of independent array-transforming calls concurrently, exclude data races statically,
and resume the caller only after every call finishes. This is the first slice of BLUEPRINT's G7 row
("Concurrency (reference permissions, Pony)"), order item 7, and the L3 prerequisite, not completion of L3.
The design follows the A0–A3 + Q organization of `docs/G10_SPEC.md` and the whole-array scope of
`docs/G5_SPEC.md`. The normative language pages consulted were all of `SPEC.md`, including §6g and §6h.

### 1.1 Verified repository facts

These are source-reading findings in this working copy, not results inferred from historical design status lines.
Each code fact below names the file and function read. References F1–F9 elsewhere refer to these exact anchors.

- **F1 — Parsing and effects.** `pruvc/vparser.py`, `Parser.function`, accepts `io`, `alloc`, and `fs`, and
  records contextual `inout` parameter metadata. `Parser.stmt` dispatches statement forms and calls
  `Parser.block` for bodies. `pruvc/check.py`, `Checker.call`, unions a callee's declared effects into
  `used_effects`; `Checker.fn` reports missing declarations as `effect/missing_effect`.
- **F2 — Exclusive places.** `pruvc/check.py`, `Checker.inout_args`, accepts whole mutable array locals or
  enclosing inout parameters, checks exact substituted types and active match roots, rejects any other
  occurrence of a marked binding in that call's arguments, and restricts mutation to statement boundaries.
  `Checker.array_source` rejects array aliases from ordinary variable initializers and borrowed-array returns.
  `pruvc-rs/crates/pruv-core/src/check.rs`, `Checker::inout_args`, implements the same marker/place/type path
  in the portion inspected. Distinct owning locals and exclusive incoming parameters are the foundation;
  this is not an existing range-disjointness prover.
- **F3 — Call proof.** `pruvc/verify.py`, `FnVerifier.call`, evaluates arguments, freezes callee old bindings,
  proves requires and recursive termination, creates inout finals, assumes ensures, and checks local refinements.
  Legacy nonrecursive unit calls without inout can skip ensures; inout unit calls do not. `FnVerifier.inout_finals`
  creates fresh contents with the original length; `FnVerifier.post_refine` checks attached assertions.
  `pruvc-rs/crates/pruv-proof/src/symbolic.rs`, `FnVerifier::inout_finals`, likewise preserves length and the u8
  domain. These transitions already exist; the older G5 design's preimplementation observations are not current facts.
- **F4 — Snapshots and loops.** `pruvc/verify.py`, `FnVerifier.ensures_ok`, restores entry values only for
  ordinary parameters. `FnVerifier.call` resolves old through a call environment or the enclosing snapshot map.
  `FnVerifier.call_writes` visits ordinary statement-contained calls recursively through control-flow blocks;
  `FnVerifier.havoc` preserves array lengths only for names in its keep set. A new statement needs traversal support.
- **F5 — Rust lowering.** `pruvc/codegen.py`, `Gen.fn`, emits mutable slice parameters and checked wrappers;
  `Gen.mut_ref` and `Gen.arr_ref` emit mutable/shared reborrows; `Gen.e` lowers inout call arguments and selects
  body versus checked call routing. `Gen.private` excludes inout signatures from public Rust APIs.
- **F6 — LLVM arrays.** `pruvc/llvmgen.py`, `ir_params`, uses pointer-plus-i64-length array parameters;
  `sig_text` omits readonly for inout pointers while retaining noalias/nocapture. `FnGen.ev_call` passes those
  pointers without copying and chooses body/entry call targets. `is_internal_fn` excludes inout functions from
  host eligibility. `pruvc-rs/crates/pruv-core/src/llvmgen.rs`, `sig_text`, has the corresponding mutable-pointer rule.
- **F7 — Rust bridge.** `pruvc/foreign_shim.py`, `build_shim`, emits generated Rust helpers and bridge runtime
  into `mod pruv_g6_shim`; `pruvc/llvmgen.py`, `gen_bindings`, accepts this shim text. The generated function
  `pruv_g6_guard` in `foreign_shim.py`'s `BRIDGE_RUNTIME` catches Rust unwinds, flushes, and exits 101.
  This is a packaging precedent, not a scoped-task implementation or proof that arbitrary callbacks are safe.
- **F8 — Native build limit.** `pruvc-rs/crates/pruvc/src/driver.rs`, `foreign_target_error`, rejects programs
  requiring the G6/File bridge with `codegen/foreign_target` and directs users to LLVM IR plus generated Rust
  bindings compiled by rustc. The G7 native-target restriction below is a proposed extension of this check.
- **F9 — Foreign trust and call graph.** `pruvc/check.py`, `Checker.fn`, skips body checking for foreign
  declarations; `Checker.call` records user calls in `calls` but excludes foreign leaves from `call_log`.
  `Checker.check_fn_sccs` builds recursive components from `call_log`. Thus an effect declaration alone is
  insufficient evidence that a foreign implementation has no hidden shared state; G7 needs a separate
  transitive eligibility summary that retains foreign leaves.

Only the named portions of the Rust port were inspected; full cross-compiler equivalence is an implementation gate.

## 2. Non-goals

- Async/await: deferred; this slice blocks at join.
- Channels: deferred; no communication between branches.
- Actors: deferred; no mailbox or persistent actor state.
- Atomics: deferred as a language facility.
- Locks: deferred as a language facility.
- Detached tasks, cancellation, task handles, task pools, dynamic fan-out, parallel loops, and nested parallelism.
- Shared mutable state, mutable host entries, subarray/field permissions, arbitrary closures, and returning branch values.
- Pony-style `iso`/`val`/`ref`, lifetime syntax, Send/Sync traits, new effect names, or scheduling guarantees.

Runtime implementation may use synchronization internally. The source language exposes none of it.

## 3. User surface

The only new syntax is a statement containing two or more semicolon-terminated calls:

```pruv
fn set_first(inout a: [i64], value: i64) -> ()
  requires len(a) > 0
  ensures a[0] == value
  ensures forall k in 1..len(a): a[k] == old(a)[k]
{ a[0] = value; }

fn set_pair(inout left: [i64], inout right: [i64]) -> ()
  requires len(left) > 0 && len(right) > 0
  ensures left[0] == 7 && right[0] == 9
{
  par {
    set_first(inout left, 7);
    set_first(inout right, 9);
  }
  assert left[0] == 7 && right[0] == 9;
}
```

Recognize `par` contextually only when followed by `{` in statement position. Ordinary identifiers and calls
named `par` remain legal. No trailing semicolon after the closing brace; no expression form. Each branch is
exactly one ordinary Pruv call returning `()`. Paths and explicit generic arguments use their ordinary syntax.
No let, assignment, return, control flow, print, builtin, or catalog operation directly inside the group.
Factor work into a named function and communicate results through whole inout arrays.

Arguments are deliberately restricted to binding names, integer/bool literals (including negative integer
literals), or `inout name`. Supported instantiated parameter types are `i64`, `bool`, `[i64]`, `[u8]`, `[bool]`,
and `[T]` for `T: Element`; scalar `T: Element` is also admissible. No take/move, str, aggregate, File, or
collection crosses a branch boundary. Bind calculations such as `len(a)` before the group. This narrower rule
than ordinary G5 calls (F2) avoids argument temporaries, hidden calls, and evaluation-order dependencies.

The group may occur in a function, loop, if, or match body. It joins before the next enclosing statement,
including before a following return. A group with zero or one branch is rejected; write a single ordinary call.

## 4. Static rules and execution semantics (binding)

### 4.1 Whole-group exclusivity

Apply the ordinary per-call G5 checks (F2), then compare resolved binding identities across the whole group.
For branch i, let W_i be all its inout actuals and R_i all its unmarked array actuals. Require:

```text
W_i intersect W_j = empty and W_i intersect R_j = empty, for every i != j.
```

Shared read-only arrays may repeat within or across branches. Different names count as disjoint only because
they are distinct owners or exclusive incoming views under F2; do not treat arbitrary renamed views as owners.
A branch can read/write its own inout arrays, allocate private arrays, and call sequential helpers. It cannot
capture anything implicitly. Parent storage and all argument views live through join; the parent cannot access
them meanwhile. Exclusivity is enforced in verified, safe, infer, and trust-callers configurations alike.
No SMT query, runtime overlap test, implicit array copy, or user permission annotation is introduced.

### 4.2 Eligible branch call graph and effects

Every function reachable from a branch must have declared effects contained in `{alloc}`. Reject `io` and `fs`,
even when a caller thinks an effectful path unreachable. The enclosing function may use io/fs before or after
the group; a branch's alloc requirement propagates to that enclosing function. Scheduling overhead itself adds
no alloc effect: this effect describes source operations, not a promise that the runtime allocates nothing.

Reject any reachable trusted Rust declaration or catalog operation, even a pure observer. This intentionally
defers G6/File use inside workers; no claim about their thread safety follows from F9. Pure language builtins
and ordinary Pruv helpers are permitted. Functions elsewhere in the program remain unrestricted.
Reject any branch whose transitive callees contain a par statement, including indirect recursion back to a
function containing par. Sequential recursion inside a worker remains permitted with its ordinary proof obligations.

Compute eligibility to a fixed point over resolved calls after ordinary typing, including calls in all executable
expressions and branches. Do not reuse F9's foreign-excluding SCC edges as the sole input. Retain a deterministic
source-order witness path for rejection. No additional user annotation or new solver theory is needed.

### 4.3 Ordering, failure, and determinism

Capture arguments once in branch order and parameter order before spawning any worker. Scalars are values;
arrays are views. Run all branches in a scope and join all started workers before any normal continuation.
Completion order and actual simultaneous execution are unspecified. On successful termination, final array
values and subsequent source-level output equal the source-order sequential calls; scheduling is unobservable.
There is no branch stdout ordering rule because stdout is prohibited in workers.

Failure does not roll back arrays and never returns a partially successful group to Pruv. Safe checks retain
their failure categories. A caught worker panic joins started workers and then terminates with exit 101;
thread creation failure does likewise with `pruv: parallel spawn failed`. A process-fatal abort, OOM, or LLVM
runtime exit may stop the process immediately; join is a guarantee on normal continuation, not on process death.
Multiple simultaneous failures need not choose a deterministic diagnostic. No panic may unwind across a C ABI.

## 5. Verification (binding)

1. Verify all callee bodies normally. A group is not a trusted contract boundary. Static eligibility and
   exclusivity must succeed before either proof or safe emission.
2. Freeze group-entry actuals and the enclosing path condition. Prove every branch requires and applicable
   recursive decreases against this same entry state, in source order, before assuming any branch ensures.
   A sibling's postcondition may never justify another sibling's precondition.
3. For each branch, instantiate generic contracts with its frozen actuals. Use the G5 transition (F3): fresh
   contents for every inout actual, unchanged length and element type, and u8 domain. Create all finals before
   assuming relational ensures. Callee old is that branch's group-entry actual, not the caller's function-entry old.
4. Merge the distinct written bindings and conjoin every branch's ensures at join, including unit branches
   without inout in legacy mode. Do not inherit F3's legacy unit-ensures omission for this new construct.
   Unwritten bindings retain their values; unspecified written contents remain arbitrary. Then prove each
   modified local's refinement using its branch contract and framed entry facts, without relying on sibling
   ensures to establish that local's preservation. No ordinary ensures is checked dynamically.
5. Keep enclosing function-entry old snapshots unchanged (F4). Extend changed-variable, refinement, inference,
   module-resolution, specialization, and diagnostic/source-location visitors for the new statement. In loops,
   include every branch inout argument in call writes; preserve local length only if no whole assignment can
   replace it. Inference may omit candidates but must never retain stale initializer/content facts.
6. Preserve normal domain, bounds, overflow, element-range, requires, ensures, invariant, and termination
   obligations. Unknown/timeout is never a proof. Safe mode skips proof but never bypasses the static rules.

Soundness argument: admitted branches access only their explicit immutable inputs, private allocations, and
pairwise exclusive mutable arrays. No branch writes another branch's inputs; no foreign or observable external
effect can mediate communication. Therefore their successful state transitions commute and have the same result
as the source-order sequential execution. The combined postconditions describe that joined state. Allocation
failure and thread resource exhaustion are outside this successful-execution equivalence, not proof successes.

## 6. Backends (binding)

### 6.1 Rust source

Lower a group to one `std::thread::scope`. Prepare typed scalar values and explicit shared/mutable reborrows
using F5's conventions, then move those views into worker closures, never the owner's Vec. Use
`std::thread::Builder::spawn_scoped` so creation failure is handled as a value. Spawn one worker per branch,
retain handles in source order, join every started worker even after a join failure, and apply §4.3.
No worker may capture the entire parent environment. Neither input buffers nor old snapshots are cloned.
Safe calls route through checked internal wrappers even under trust-callers; ensure this also holds for legacy
unit branches without inout, rather than relying on host-entry routing. No language-level Send/Sync bound is added;
the concrete permitted scalar/slice types must compile under Rust's actual thread bounds.

### 6.2 LLVM and Rust bindings

Use the generated Rust bindings packaging path (F7), adding a small independent synchronous G7 bridge. Do not
rewrite the compiler's algorithms in Rust callbacks: each branch body remains LLVM code.

Proposed internal ABI: `void pruv_g7_v1_run(ptr jobs, i64 count)`; each C-layout job has exactly two pointers,
an `extern "C" fn(*mut c_void)` callback and its context. Emit a target-layout-compatible descriptor and context
per branch in the caller's stack frame. Contexts contain scalars and borrowed pointer/length pairs, never owners.
Represent bool scalar context fields as i8, normalize to i1 in the LLVM trampoline; use existing element layouts.
Generate a deterministic private LLVM trampoline for each group branch which decodes its context and calls the
ordinary body or safe checked wrapper according to §6.1. It returns void and does not retain any context pointer.

The Rust bridge reads descriptors, transfers each once to a scoped worker, invokes its callback once, and joins
before returning. A private audited Send wrapper for the raw descriptor is permitted only here: its justification
is the compiler's disjointness rule, immutable shared inputs, synchronous join, and stack-context lifetime. Do not
cast pointers through integers to evade Send or add blanket Send implementations to Pruv runtime values.
No descriptor array/context is mutated while workers can read it. Protect Rust panic paths inside the bridge;
LLVM runtime failures must terminate without unwinding through the callback ABI. Retain F6's array attributes
on callee parameters, but add no readonly/nocapture/noalias to the scheduling call or context pointers merely by analogy.

Emit the G7 runtime only for programs containing par; handle programs needing both G6 and G7 without duplicate
symbols or runtime definitions. Extend native `--emit exe|obj` rejection with `codegen/parallel_target`, directing
users to LLVM IR plus `--rust-bindings` and a Rust host build. Plain LLVM IR emission is allowed; linking without
the generated G7 bridge is unsupported. No new mutable host entry or externally callable trampoline is introduced.

### 6.3 Compatibility

Programs without par must retain byte-identical AST/check dumps, proof traces, diagnostics, Rust, LLVM, bindings,
and manifests in both compilers. New metadata is absent by default; no unconditional runtime prelude or symbol
renumbering. Compatibility fixtures must include ordinary functions/locals named par. Full cross-compiler byte
agreement for new artifacts is a gate; solver counterexample values may differ, with shape and all other fields checked.

## 7. Diagnostics (binding)

New codes are fixed below. Use the offending node's location and resolved module file; hints give a concrete repair.

| Stage/code | Trigger | Repair |
|---|---|---|
| `parse/parallel_syntax` | Malformed par block, missing semicolon, non-call member | Write semicolon-terminated calls |
| `type/parallel_arity` | Fewer than two branches | Use one ordinary call |
| `type/parallel_call` | Non-unit, builtin, catalog, or foreign direct branch target | Call a unit Pruv helper |
| `type/parallel_argument` | Unsupported boundary type or argument expression | Bind a scalar first or use whole primitive arrays |
| `type/parallel_alias` | Cross-branch write/write or write/read overlap | Use separate owners or sequential calls |
| `effect/parallel_effect` | Reachable declaration has io or fs | Move I/O outside par |
| `type/parallel_foreign` | Reachable foreign/catalog call below a Pruv branch | Use Pruv computation outside the foreign boundary |
| `type/parallel_nested` | Reachable function contains par | Keep only the outer group |
| `codegen/parallel_unavailable` | Temporary A0–A2 staging guard | Use a supported completed backend/batch |
| `codegen/parallel_target` | Native LLVM obj/exe requested for par | Emit IR/bindings and link using Rust |

Ordinary call resolution, arity, type, and G5 place/alias errors remain their ordinary diagnostics (F1–F3);
same-call overlap is `type/inout_alias`, cross-call overlap is `type/parallel_alias`. Proof failures retain F3's
`verify/call_requires` and `verify/refinement_assign`; no new proof code is necessary. For G7-specific validation,
check group arity, direct target, ordinary argument typing/G5 validity, restricted argument form/types, and
cross-branch overlap in source order; then run transitive eligibility. At one offending branch prioritize effect,
foreign, then nested witnesses. Report the later conflicting branch and identify the earlier branch and binding.

## 8. Batches A0..A3 + Q (binding gates)

Each implementation batch completes Python then its Rust port in the same batch. Capture par-free artifacts
before implementation and compare at each gate. Run focused new/affected checks while editing; run the required
precommit regression once under repository policy, without duplicate whole-suite runs after unchanged results.
Require matching parse/check diagnostics, proof verdicts and deterministic traces, generated source/IR/bindings,
and all applicable runtime modes. Do not count unsupported, crash, unknown, or timeout as a positive case.
The following counts are distinct source roots, not backend/mode expansion. All are future implementation work.

### A0 — Frontend

Add a Par statement and preserve it through every AST consumer, module resolution and specialization. Implement
§§3–4, including a transitive eligibility summary separate from effects/SCCs. Add at least 10 positive frontend
roots and 18 rejection roots covering contextual names, modules, generics, repeated reads, multi-inout calls,
both overlap directions, unsupported arguments/types, hidden foreign calls, indirect nesting, and effect propagation.
Exercise all new static codes and existing G5 conflicts in safe/trust modes too. Stop before verification/emission
with `codegen/parallel_unavailable`: "G7 verification is not implemented yet" in every mode. No partial output.
Exit: differential frontend/diagnostics and unchanged-program artifacts pass; no visitor silently drops a group.

### A1 — Verification

Implement §5 and update refinement/inference/loop-write consumers. Add at least 12 positive and 12 negative proof
roots: both branch postconditions, old/current separation, forgotten frame, same-length havoc, caller refinement,
u8/bool/generic types, callee rejection, independent preconditions, repeated loop groups, whole replacement inside
loops, legacy unit ensures, and inference on/off. In particular a later branch must not use an earlier branch's
ensures to prove its requires; use a read-only unit helper with a nontrivial valid ensures to test this ordering.
Move the staging guard after proof (or after static checks in safe mode): "G7 code generation is not implemented yet".
Exit: positive proofs and expected failures agree; no stale content survives havoc; par-free proof bytes unchanged.

### A2 — Rust backend

Implement §6.1. Add at least 10 runtime roots and two examples: disjoint transformations, shared reads, three branches,
forwarded inout views, generic/bool/u8 arrays, repeated loop groups, empty arrays, join-before-return, and safe
requires/bounds/overflow failures. Check exact contents against sequential oracles, including safe plus trust-callers.
Use test-only worker instrumentation to establish overlapping worker lifetimes without timing-sensitive language tests.
Inject spawn failure and worker panic through test-only hooks; prove started workers join before recoverable cleanup.
Inspect emitted code for captures and absence of buffer clones. LLVM remains guarded with
"G7 LLVM code generation is not implemented yet". Exit: compiled Rust execution and source-byte differential pass.

### A3 — LLVM + SPEC user page

Implement §6.2, run every A2 case through the LLVM/Rust bridge, and add at least six roots for descriptor layouts,
optimized pointer use, repeated readonly aliases, generic trampolines, bridge coexistence, and native-target rejection.
Test descriptor size/alignment/offsets on supported target ABIs and actually run each claimed execution platform;
cross-compilation alone does not establish runtime correctness. Inspect symbols, attributes, safe-wrapper routing,
pointer lifetime, and the no-unwind boundary. Add at most one page to SPEC (§6i proposed), documenting syntax,
eligibility, effects, join, failures, contracts, and LLVM host-build requirements. Remove all staging guards/pending rows.
Exit: runtime/backend agreement, IR/binding byte parity and compatibility pass; record untested platforms explicitly.

### Q — Stress, mutants, fault injections, independent use, measurement

1. Generate at least 30 verified programs for each of three recorded seeds and eight inputs each: 720 program/input
   pairs, run with two compilers × two backends × verified/safe = 5,760 completed comparisons. Include repeated
   runs under scheduling perturbation, loop groups, multi-array branches, shared reads, generics, and exact frames.
   An independent sequential owner-based interpreter checks actual final arrays, not only exit codes. Save/replay
   every failure; report shortfalls and oracle gaps separately.
2. Grade at least 40 behaviorally incorrect source mutants with adequate contracts: wrong target/index/value,
   missing branch/store, false frame, old/current confusion, duplicate writable input, and effect/foreign leakage.
   Require zero incorrect acceptances. Classify weak-contract or equivalent mutants separately; no denominator padding.
3. Execute at least eight compiler fault injections: omit cross-branch write/read check; omit write/write check;
   omit transitive foreign rejection; admit nested par; assume sibling ensures before requires; omit branch havoc;
   omit loop call writes; return the bridge before join. Also check mutable LLVM readonly and safe-wrapper routing
   with direct artifact assertions. Record each patch, command and named detecting test; a proposed injection is not evidence.
4. Give an independent author only the updated SPEC and two fresh problems: independent bounded byte transforms
   with exact frames, and two output-array computations sharing one immutable input. Record first attempts,
   diagnostics, revisions and help; both final solutions must verify and execute on both backends.
5. Measure a compute-heavy transformation of two independent arrays against (a) the same Pruv calls sequentially,
   (b) hand-written sequential Rust, and (c) hand-written scoped parallel Rust with identical work and worker counts.
   Include small inputs to expose spawn overhead and large inputs to expose memory bandwidth. Use at least ten
   repetitions after warmup, identical optimization/contract-check settings, observable checksums, and identical
   setup/copy costs. Report medians/spread, CPU/core count, OS/toolchain/flags, bytes/allocations, setup-inclusive and
   kernel-only times. Target: within 1.5x of hand-written parallel Rust at the large size; seek speedup over sequential
   Pruv on a machine with two available cores, but do not invent a mandatory speedup. Explain missed targets with
   evidence (spawn/join, checks, bridge, optimizer/vectorization, bandwidth, load); record failure and follow-up
   rather than silently changing the baseline. No performance result is claimed by this design.

Q exits only with completed counts, no unexplained mismatch, all injected faults detected, independent solutions
passing, and an honest measurement report. A missed performance target may be explicitly deferred; soundness or
lifetime failures may not. Promote useful discoveries into permanent regression fixtures.

## 9. Deferred work and open evidence

- Subarray splitting and parallel loops need range-based permissions and a separate alias/ABI design.
- Branch return values, arbitrary expressions, aggregate/str captures and collection transfer need richer capture lifetimes.
- Pony permissions become relevant when references escape scopes or ownership crosses tasks; they are unnecessary here.
- Async, channels, actors, atomics and locks each require a separate semantic and verification proposal.
- Nested scheduling, bounded pools, cancellation and resource budgets follow measured demand, not this syntax release.
- Foreign thread-safety contracts and G6/File worker access need an explicit trusted boundary policy.
- Standalone LLVM native task-runtime linkage is deferred; the first release requires generated Rust bindings.

Open evidence, to be settled by the named gates: actual spawn/bridge overhead and crossover sizes (Q), target ABI
layout and failure behavior (A3), supported toolchain availability for scoped spawning (A2), and solver robustness
for the positive contract/inference fixtures (A1). These cannot be settled by source inspection. No test suite,
compiler execution, benchmark, or fault injection was run for this document; only `docs/G7_SPEC.md` is to be created.
