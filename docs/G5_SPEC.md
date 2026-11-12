# G5: Mutable Array Value Semantics and Exclusivity

Status: **Design fixed for implementation, 2026-11-12; not implemented.**

This document defines four implementation batches A0–A3 and a bounded Q batch.
Numbered decisions in §§10–14 are binding acceptance criteria, not measured results.
Each batch finishes the Python compiler first, then its byte-identical Rust port,
and passes the differential gates before the next batch starts.

## 1. Goal and foundation

G5 lets a function update a caller-owned array without allocating and returning a
replacement array. Exclusive access makes the affected storage non-overlapping
with every other argument through which the call could access it. The verifier
uses this rule to frame other values; the LLVM backend uses it to retain useful
alias information while allowing stores.

This implements the G5 row in `BLUEPRINT.md` §4 and item 6 of its current order.
It is a small mutable-value-semantics feature, not a general implementation of
Hylo's ownership system. Existing copies remain independent values.

### 1.1 Verified repository facts

- `BLUEPRINT.md:167` names mutable value semantics and array non-overlap as G5;
  `BLUEPRINT.md:190` identifies avoiding copies of large mutable data as its purpose.
- `SPEC.md:31` makes parameters immutable; `SPEC.md:85` fixes left-to-right
  evaluation. `SPEC.md:267` separates G6 borrowed and consumed collections.
  `SPEC.md:320` defines independent G9 values and temporary match views.
  `SPEC.md:361` restricts G4 host entries.
- `pruvc/vparser.py:600` parses functions. Lines 610–624 recognize contextual
  `take` and attach parameter metadata. `pruvc/vparser.py:1027` parses `move name`.
  Rust implements the corresponding parameter path in
  `pruvc-rs/crates/pruv-core/src/parser.rs:906`.
- `pruvc/vast.py:351` uses absent-by-default extension metadata to preserve old
  dumps. Rust parameters currently contain a `take` flag at
  `pruvc-rs/crates/pruv-core/src/ast.rs:185`.
- `pruvc/check.py:665` installs immutable parameter bindings.
  `pruvc/check.py:741` checks element assignment separately from whole assignment.
  Rust mirrors these rules at `pruvc-rs/crates/pruv-core/src/check.rs:1582`
  and `pruvc-rs/crates/pruv-core/src/check.rs:1703`.
- `pruvc/check.py:865` restricts array ownership sources to fresh expressions,
  with a local-variable exception for permitted returns. Lines 898–912 track
  extended match roots and reject mutation during active views.
- `pruvc/check.py:1286` instantiates generic call signatures and then checks
  arguments. `pruvc/check.py:589` rejects unsupported explicit host signatures.
- `pruvc/verify.py:1493` evaluates call arguments before proving requires.
  Lines 1542–1580 instantiate contracts, check recursive termination, create
  results, and assume ensures. Ordinary legacy nonrecursive unit calls still
  skip ensures; explicit-mode unit calls do not.
  Rust mirrors this distinction in
  `pruvc-rs/crates/pruv-proof/src/symbolic.rs:1847`.
- `pruvc/verify.py:1666` currently replaces every parameter in an ensures
  environment with its entry value. Rust does the same in
  `pruvc-rs/crates/pruv-proof/src/symbolic.rs:1091`.
  This must change specifically for inout parameters.
- `pruvc/verify.py:1745` models element assignment with SMT Store, preserving
  length and checking bounds, u8 range, and local refinement. It captures the
  target array before evaluating the index and value. The Rust counterpart at
  `pruvc-rs/crates/pruv-proof/src/symbolic.rs:2360` does likewise.
- `pruvc/verify.py:1690` and
  `pruvc-rs/crates/pruv-proof/src/symbolic.rs:300` collect explicit assignments
  for loop havoc, but not mutations through calls. Python havoc at line 1703
  introduces a fresh array length. Loop entry/body/exit handling is at line 1837.
- `pruvc/infer.py:125` collects assignment statements; line 162 searches for
  initial values. Rust inference collects the corresponding assigned set at
  `pruvc-rs/crates/pruv-proof/src/infer.rs:343`.
- `pruvc/refine.py:213` instruments local refinements and loop invariants.
  Lines 254–264 expand parameter refinements into requires only.
  `SPEC.md:424` documents this distinction between parameter preconditions and
  local preservation obligations.
- `pruvc/mono.py:403` reconstructs parameters and explicitly preserves `take`.
  Rust reconstructs them in `pruvc-rs/crates/pruv-core/src/mono.rs:825`.
  An added mode must survive both paths.
- `pruvc/codegen.py:756` emits signatures and checked wrappers; line 1602
  lowers call arguments. The safe store helpers at lines 105, 167, and 191
  already accept mutable slices. Rust call lowering is at
  `pruvc-rs/crates/pruv-core/src/codegen.rs:2300`.
- `pruvc/llvmgen.py:357` lowers arrays to pointer and length; line 384 already
  emits `ptr noalias nocapture readonly` for their internal pointer parameters.
  Rust mirrors this at
  `pruvc-rs/crates/pruv-core/src/llvmgen.rs:588` and line 620.
  Parameter binding at `pruvc/llvmgen.py:937` keeps array parameters borrowed;
  call lowering at line 1383 passes their pointer and length.
- `pruvc/llvmgen.py:3014` filters binding entries. Rust filters them in
  `pruvc-rs/crates/pruv-core/src/bindings.rs:357`, and its current array
  declarations use const pointers at line 380.
- `tests/run_all.py:726` inventories runtime metadata and flag matrices.
  `tests/diff_compilers.py:183` compares diagnostics with an explicit
  counterexample-value exception. `tests/diff_llvm.py:276` compares generated
  IR/bindings after checking, without proving the input.
- `bench/fuzz/run.py:1596` implements G4 success accounting, including shortfalls
  and oracle gaps. `bench/g4/mutate_ops.py:601` grades source mutants across
  configurations. Its `fault_injections` function at line 674 explicitly records
  descriptions rather than executing compiler fault injections.

These facts were checked by reading the repository. No compiler, test suite,
benchmark, or fault injection was run for this design. G4 and G9 are present in
the implementation and current SPEC; the design-status lines in their historical
design documents are not evidence that those features are absent.

### 1.2 Non-goals

No references as values, arbitrary borrowed locals, slices, subarray permissions,
field mutation through borrowed buffers, shared mutation, pointer arithmetic,
lifetimes, concurrency, or runtime alias checks. No mutable str, scalar, aggregate,
recursive-value, Vec, HashMap, or String parameters. G6 ownership remains separate.

No new allocator, ABI version, solver theory, mutation effect keyword, automatic
copy insertion, or automatic postcondition inference. Allocation failure remains
a resource failure. General nested expressions containing mutating calls are
deferred as specified in §2.

## 2. Parameter modes and call surface

Add contextual parameter syntax:

```pruv
fn set_at(inout a: [i64], i: i64, value: i64) -> ()
  requires 0 <= i && i < len(a)
  ensures a[i] == value
  ensures forall k in 0..len(a): k != i ==> a[k] == old(a)[k]
{
  a[i] = value;
}
```

Supported types are `[i64]`, `[u8]`, `[bool]`, and `[T]` where T has the existing
Element bound. G3 already supports abstract element stores, array snapshots,
and specialization; G5 needs mode propagation, not another generic capability.
Element still means i64 or bool; this does not introduce scalar u8 or new bounds.

The mode is not part of the array value type. An inout parameter permits reads
and element assignment, but never whole-parameter reassignment, resizing,
ownership transfer, storage of its view, or return of its view. `take` and
`inout` are mutually exclusive.

Callers must write the mode:

```pruv
set_at(inout data, 0, 7);
```

The marked argument must be a whole mutable local array binding or an inout
parameter of the caller, with exactly the instantiated element type. Immutable
locals, ordinary parameters, match binders, fields, elements, calls, and other
expressions are not places admissible for inout.

Reading, indexing, `len`, and `copy` remain legal. `copy(a)` creates an independent
owner and requires alloc; returning or storing that copy is legal. Passing `a`
unmarked to a read-only array parameter is legal. Forwarding mutable access
requires `inout a`. There is no implicit copy-in/copy-out operation.

### 2.1 Statement-boundary calls

For the smallest sufficient release, a call whose signature contains inout may
occur only as:

- A complete expression statement, subject to the existing unit-result rule.
- The complete initializer of a let.
- The complete RHS of whole-variable assignment.
- The complete expression of return.

Parentheses do not change these positions. The function's result may have any
otherwise supported type; it is not restricted to unit.

Such a call may not be nested in another call argument, operator, constructor,
index, condition, field assignment, or element assignment. Its ordinary
arguments may contain existing non-inout calls and retain source-order evaluation.

This is an explicit G5 restriction, not an assertion that general expression
mutation is inherently unsound. Adding only call havoc to the current evaluator
would be unsound: an element assignment captures its old target before evaluating
its RHS, and short-circuit evaluation guards facts without merging mutable
environments. Statement boundaries avoid a new expression-effect IR and guarded
state-merging algorithm.

Write a temporary when needed:

```pruv
let changed: bool = update(inout data);
if changed { /* ... */ }
```

The mutation completes before initializing, assigning, or returning the result.
Checks on the modified arguments also occur before that enclosing operation.
A whole-local assignment may subsequently replace a local array; this does not
permit replacing an inout parameter.

## 3. Exclusive access and value ownership

For each marked argument, its binding may occur nowhere else in the entire
argument list of that call. Inspect complete argument syntax, including nested
ordinary calls and unreachable short-circuit operands.

Reject all of these:

```pruv
f(inout a, inout a);
g(inout a, a);
h(inout a, len(a));
k(inout a, read_first(a));
```

The rule intentionally rejects scalar observations and explicit copies appearing
inside another argument. Evaluate those before the call:

```pruv
let n: i64 = len(a);
h(inout a, n);
```

Different local owners are disjoint under the existing fresh-array rules.
Different inout parameters are disjoint by the caller's same obligation.
Read-only arguments may alias each other, including repeated arguments.

An inout parameter may be temporarily read-borrowed by a nested callee, and may
be exclusively reborrowed by a nested inout callee. No view escapes either call.
After the call, the caller resumes access to its own binding.

Check active G9 match roots before granting mutable access. Reuse
`type/recursive_borrow` when an eligible owning root is actively viewed.
Under today's types, primitive arrays are not matchable and buffer payload
binders are already ineligible; do not invent mutable field access to make this
case reachable. Existing G9 active-root tests must remain effective.

Exclusivity is a static language rule in both verified and safe modes.
`--no-verify` and `--trust-callers` never disable it.

Mutation through the mode does not require alloc or a new effect declaration.
The mode exposes the mutation in the signature and at the call. Existing io and
alloc requirements still propagate normally.

## 4. Entry snapshots and contracts

In requires, each parameter denotes its entry value. In ensures, an inout
parameter denotes its final value; every other parameter keeps its existing
entry-value meaning, including consumed G6 parameters.

Add `old(a)` as a contract-only array expression. Its operand must be exactly
the name of an inout parameter of the enclosing function. It is legal only in
that function's ensures, loop invariants, and asserts.

Reject old in requires, executable expressions, function decreases, and loop
decreases. Reject old of a local, ordinary parameter, field, element, expression,
or another old expression. Wrong arity is also rejected.

`old(a)` means function entry, never the latest call or loop entry. It has a
frozen array-content term and the entry length. It can be indexed or passed to
existing contract operations such as len and aggregates; ordinary function
calls in contracts remain forbidden.

At every reachable point:

```text
len(a) == len(old(a))
```

is a built-in fact for an inout parameter. Equality of whole arrays remains
forbidden; compare lengths and indexed contents.

Old snapshots are proof objects. They do not copy storage at runtime, introduce
alloc effects, or appear in emitted runtime contracts. Ordinary ensures,
invariants, and asserts remain erased.

Parameter refinement annotations retain their existing meaning: they generate
entry requires, including on inout parameters. They do not silently become
persistent invariants or output guarantees. State an output guarantee in ensures.

A refined local passed inout must satisfy its declared refinement immediately
after the call. Prove this from the callee's ensures and the remaining caller
facts using `verify/refinement_assign`. Do not assume preservation. Length-only
refinements follow from the preserved length. Insert the corresponding local
conditions into enclosing loop invariants when the local is changed by a call.

These local proof obligations retain the existing safe-mode erasure policy for
refinement assertions; G5 adds no dynamic refinement protocol.

## 5. Modular verification and loops

### 5.1 Callee rule

Create the ordinary well-formed entry array and retain it in a separate immutable
snapshot environment. Bind the executable name to the current array value.

Element assignment uses the existing Store model and the existing bounds,
u8-range, and applicable local-refinement obligations. A Store preserves length.
At returns, overlay entry values for ordinary parameters only; preserve current
values for inout parameters. Resolve old through the immutable snapshot map.

The same postcondition proof runs at explicit return and implicit unit return.
No successful caller proof excuses an unproved callee.

### 5.2 Caller rule

For an admitted statement-boundary call:

1. Evaluate arguments once, left to right. A marked argument identifies a place;
   it neither moves nor copies its array.
2. Freeze the actual pre-call arrays for the callee's old bindings.
3. Prove requires on those pre-call values.
4. Discharge applicable G9 recursive measure domain, nonnegative, and strict
   decrease obligations on the pre-call actuals.
5. Create fresh contents for each inout argument, in parameter order, retaining
   exactly its pre-call length and element type. Establish ordinary element
   well-formedness, including the u8 domain.
6. Create the ordinary well-formed result, if any.
7. Instantiate ensures with final arrays, pre-call old snapshots, entry values
   of ordinary arguments, and result. Assume the clauses in their existing order.
8. Prove applicable caller-local refinement preservation, then complete the
   enclosing let, assignment, return, or expression statement.

All modified arguments obtain fresh values before any ensures clause is assumed.
Relational ensures may connect several modified arrays.

An unspecified post-state is arbitrary contents of the same length. Never
retain old element facts merely because the callee body happens not to write.
Other bindings retain their values by the exclusive-access frame rule.

Apply ensures for every inout call, including nonrecursive unit calls in legacy
single-file mode. Preserve the old unit-call behavior for signatures without
inout. This closes the relevant omission without changing G5-free SMT.

Old maps are scoped to contract evaluation, not implemented by temporarily
overwriting the caller's entry snapshot. Restore generic substitution and
snapshot contexts after each call, including failure paths.

Module resolution and recursive SCC handling remain those of G4/G9. A recursive
call compares its pre-call measure with the caller's frozen entry measure.
Neither final array contents nor the call's ensures may justify its own requires
or termination obligation.

### 5.3 Loop havoc and inference

The changed-variable analysis must include every inout argument of calls in
let initializers, assignments, returns, and expression statements, recursively
through statement blocks. The assignment's own target remains changed too.
Local bindings created inside the loop are not new loop-head owners.

Havoc inout parameters' contents while retaining their entry length. For local
arrays changed by inout calls, retaining the loop-head length is sound only when
the loop cannot also replace that binding. If whole assignment is possible,
retain the existing arbitrary-length havoc and require the relevant invariant.
Unchanged G5-free loops keep their exact old havoc behavior and SMT.

Update all three consumers: verification, refinement expansion, and Houdini.
Inference must treat inout writes as assignments and invalidate earlier
initializer/content facts at an intervening call. Templates requiring exclusively
element stores must not mistake a call write for such a store.

No new inference templates are required. Existing candidates may be conservatively
omitted for arrays changed through calls. Ordinary candidate checking and final
re-verification remain mandatory, and explicit old-containing invariants are
always checked. `--infer` may fail to discover a needed invariant; it may not
preserve an invalid one.

## 6. Rust backend and host entries

Emit an inout parameter as `&mut [i64]`, `&mut [u8]`, or `&mut [bool]` after
specialization. Preserve source parameter order.

Pass a mutable local with `&mut local`; forward an inout parameter with
`&mut *parameter`. Read-only forwarding uses a shared reborrow such as
`&*parameter`. Safe store helpers must use the same reborrow, not attempt to
mutably borrow an immutable reference binding.

The parameter owns neither the slice allocation nor its elements' storage.
No clone, Vec conversion, allocation, move, resize, or drop is introduced for
the borrowed array. Returning `copy(parameter)` remains an ordinary owned return.

### 6.1 Entry policy

G5 does not expose inout signatures to the host.

- In explicit G4 mode, a root public nongeneric function with any inout
  parameter is rejected with `type/entry_signature`.
- Private functions, child-public functions, and public generic Pruv APIs may
  use inout.
- In legacy mode, a function with inout is automatically internal, like existing
  collection-bearing or extended signatures. It receives no public Rust API,
  raw ABI entry, typed ABI variant, or Rust binding.
- Existing main-signature restrictions continue to apply.
- Trusted Rust declarations with inout are rejected with
  `type/foreign_signature`, regardless of whether they are called.

A host wrapper can copy an input into its own mutable local, call several
in-place helpers, and return the local or a scalar result. This preserves existing
host capabilities while eliminating repeated internal copy-and-return operations.

Supporting mutable host entries would require another boundary contract for
writable storage and overlap, including raw callers. Rejecting them is the
cheaper sound G5 scope.

### 6.2 Runtime checks

Verified Pruv calls use the body after proof. Safe calls to an inout function
with requires use a checked internal wrapper, including in legacy mode with
`--trust-callers`. Trust-callers does not waive checks on the new internal
mutable calls.

The wrapper checks the pre-call array and then reborrows it into the body.
Existing short-circuit domain checks, i128 arithmetic, shared iteration budget,
panic messages, and safe index/u8 checks remain unchanged.

Existing public wrappers retain their boundary-check policy. G5 emits no runtime
old snapshot or ordinary ensures check. G6 foreign-checks remain independent.

## 7. LLVM backend and optimization information

Keep the existing pointer-plus-i64-length internal calling convention. An inout
parameter points directly to caller-owned storage; stores update that storage.
Never register it as an owned buffer, free it, replace its descriptor, or return
its pointer as an owned result.

Use parameter-mode metadata when printing definition signatures:

```text
inout array pointer:    ptr noalias nocapture
read-only array pointer: existing ptr noalias nocapture readonly
length:                i64
```

Apply the mutable signature to both the internal body and any checked internal
wrapper. Remove readonly only for the inout pointer. Preserve existing call
operand syntax and attributes unless a G5-specific change is necessary.

The current backend already gives read-only array pointers noalias. G5 retains
that spelling; it does not newly infer that read-only arguments have different
addresses. Repeated read-only arguments remain legal. The relevant guarantee is
that storage modified through an inout pointer is not accessed through another
independent argument during the invocation.

Derived element pointers and nested reborrows belong to the same access path.
Do not add noalias to arbitrary G9 aggregate pointers, result-storage pointers,
collection handles, or individual loads/stores.

Use existing element layout and checks: i64 storage for `[i64]`, byte storage for
`[u8]` and `[bool]`, existing bool normalization, and existing verified/safe
bounds and range behavior. No runtime or allocator ABI change is needed.

Binding and ABI enumeration must exclude inout signatures independently of
whether a requires wrapper exists. Test symbol inventories as well as runtime
results. No `pruv_abi_*`, `__typed`, or host Rust wrapper may expose an inout helper.

Programs without inout preserve their prior IR and bindings byte-for-byte.
Do not rewrite existing read-only signatures or regenerate their baselines.

## 8. Diagnostics and compatibility

Keep existing JSON stages, exit statuses, field order, source maps, and G4
relative-file locations. New codes are fixed below.

| Stage/code | Meaning |
|---|---|
| `parse/inout_syntax` | Malformed marker, missing operand/name, or combined/repeated parameter modes |
| `type/inout_type` | Inout declared on a type outside the supported primitive/generic arrays |
| `type/inout_argument` | Missing/extra call marker, inadmissible place, or nonmutable binding |
| `type/inout_alias` | A marked binding also occurs elsewhere in the call arguments |
| `type/inout_context` | Mutating call outside the statement-boundary positions in §2.1 |
| `type/old_context` | Builtin old used outside ensures, invariants, or asserts |
| `type/old_argument` | Wrong arity or operand other than this function's inout parameter name |

Reuse these existing codes:

| Stage/code | G5 use |
|---|---|
| `type/immutable` | Whole reassignment of an inout parameter |
| `type/array_alias` | Attempt to store or return the borrowed array without copying |
| `type/foreign_move` | Attempt to move an array through G6 ownership syntax |
| `type/recursive_borrow` | Mutable access while an applicable G9 root view is active |
| `type/foreign_signature` | Inout on a trusted Rust declaration |
| `type/entry_signature` | Inout on an explicit host entry |
| `type/reserved` | Callable old declaration conflicting with the G5 builtin |
| `verify/refinement_assign` | Modified local's refinement not established after a call |
| `codegen/unsupported_type` | Temporary batch guard only |

Reuse existing type-mismatch, effect, bounds, elem_range, contract_domain,
call_requires, ensures, assert, loop, and recursive proof diagnostics.
G5 needs no new proof obligation code.

Recognize inout contextually, preserving existing identifiers named inout where
they are ordinary names. Recognize the old builtin for programs using inout;
reserve its callable declaration name in that feature context. G5-free programs
with an existing function named old retain their old resolution and bytes.
Do not globally add either spelling to the lexer keyword table.

Check declaration modes and entry eligibility before bodies. At a resolved call,
check arity and generic substitution, marker/place validity, argument types,
exclusive use, and statement context in deterministic source order.
Old context is checked before its operand validity.

Every new diagnostic points to the offending marker, call, or old expression and
gives a specific repair. Unsupported marker expressions such as `inout p.field`
are diagnosed as inadmissible arguments rather than silently truncated names.

Preserve G5-free parse/check dumps, SMT, diagnostics, Rust, IR, bindings, and
foreign manifests. New optional fields are omitted when absent. Add a small
compatibility fixture for ordinary uses of each new spelling.
No blanket snapshot regeneration is acceptable.

## 9. Shared batch gates and paths

Abbreviations: P = `pruvc/`; C = `pruvc-rs/crates/pruv-core/src/`;
V = `pruvc-rs/crates/pruv-proof/src/`; D = `pruvc-rs/crates/pruvc/src/`.
Paths below are planned edits, not changes made by this design task.

Every batch implements Python first, ports behavior to Rust second, and runs:

- `tests/run_all.py` for both compilers and all applicable backend/mode rows.
- `tests/diff_compilers.py --backend both`, including the new G5 fixtures.
- `tests/diff_llvm.py`, including G5 IR/bindings or the expected staging guard.
- Applicable parse/check, trace, Rust-source, and `tests/m3_all.py` checks.

Require byte-identical applicable artifacts and strict `same` on deterministic
positive proof traces. Counterexample values retain the existing explicit
exception; compare all other diagnostic fields and counterexample presence.
Timeout, unknown, crash, and unsupported paths are not successful proofs.

Capture G5-free artifacts before implementation and compare them at each exit.
Proof/emission batches also run existing benchmark and mutation regression gates.
Differential generation alone is insufficient: diff_llvm does not prove its
inputs, and agreement can reproduce the same mistake.

Add `tests/g5/fixtures.json` (new) as a test-only inventory. Reuse
`tests/g4/projects.py` for multi-file copying/replay; do not introduce a language
manifest. Extend inventory/discovery to G5 roots without treating companion
modules as standalone inputs.

Use flat fixtures where possible:
`tests/g5/{frontend,proof}/*.pruv`,
`tests/must_reject/g5_*.pruv`,
`tests/runtime/g5_*.pruv` with existing JSON/harness companions, and
`examples/g5_*.pruv`.
Multi-file fixtures use corresponding `g5_*/root.pruv` project directories;
runtime projects use the existing `spec.json` and `main.rs` convention.

Counts below count distinct source roots, not backend/mode rows, companion files,
or generated mutants:

| Batch | Frontend | Proof | Must-reject | Runtime | Examples |
|---|---:|---:|---:|---:|---:|
| A0 | 16 | 0 | 24 | 0 | 0 |
| A1 | 0 | 16 | 18 | 0 | 0 |
| A2 | 0 | 0 | 0 | 12 | 3 |
| A3 | 0 | 0 | 0 | 6 | 2 |
| Q | 0 | 0 | 4 | 2 | 1 |
| Total | 16 | 16 | 46 | 20 | 6 |

These are minimum new fixtures; the listed coverage is mandatory even if more
fixtures are needed. Expected stage/code and mode are recorded for every reject.

A0 guards verification and emission. A1 moves the guard after proof.
A2 supports Rust and leaves LLVM guarded. A3 removes every G5 staging guard and
pending row. All guards use `codegen/unsupported_type`, and requested outputs are
generated before any new artifact is written.

## 10. A0 — frontend and exclusive places (binding)

1. Add absent-by-default parameter mode metadata, an explicit inout argument
   node, and resolved old-expression metadata. Preserve locations and source
   identity. Do not represent inout as an ordinary value-producing function.
2. Extend contextual parsing without changing old identifier behavior.
   Keep take and inout mutually exclusive. Update all AST visitors and dump
   adapters that encounter the new node, including module traversal.
3. Separate permission to store an element from permission to replace a binding.
   Implement §3, statement-boundary checking, old context/operand checking,
   foreign rejection, and host eligibility.
4. Include `[T: Element]`. Existing type substitution performs the element-type
   match; modes do not introduce new generic bounds or specialization keys.
5. Files: P/`vast.py`, `vparser.py`, `check.py`, `foreign.py`, `modules.py`,
   `pruvc.py`; C/`ast.rs`, `parser.rs`, `check.rs`, `foreign.rs`, `modules.rs`,
   `dump.rs`, `pyrepr.rs`, `pyjson.rs`, `diagnostic.rs`,
   `bin/pruv-parse-dump.rs`, `bin/pruv-check-dump.rs`; D/`driver.rs`;
   `tests/diff_py_adapter.py`, `tests/diff_parse.py`, `tests/diff_compilers.py`,
   `tests/run_all.py`, `tests/run_all_rows.txt`, and the new §9 inventory/fixtures.
   Extend lexer handling only if contextual lookahead cannot remain in parsing.
6. Add 16 frontend roots covering three concrete element types, generic
   forwarding, mutable locals, reborrows, read forwarding, two disjoint arrays,
   copying an inout parameter, return values, module calls, old scopes, and
   ordinary identifier compatibility.
7. Add 24 rejection roots: unsupported types (six), mode/place/type misuse
   (six), duplicate or hidden argument uses (four), invalid old uses (four),
   prohibited nested mutation contexts (two), foreign signature (one), and
   explicit host entry (one). Include named-array escape and whole-parameter
   replacement among mode/place misuse.
8. Exit: frontend dumps and deterministic diagnostics match; static rejections
   hold with and without verification; downstream guards cannot be bypassed;
   complete G5-free gates pass. Existing G9 match-borrow and G6 ownership tests
   remain passing.

## 11. A1 — snapshots, call transitions, and loop proof (binding)

1. Implement separate current and entry-snapshot environments and the caller
   transition of §5. Apply unit ensures to inout calls in both source modes.
   Prove every definition before specialization.
2. Update changed-variable analysis, loop length treatment, local-refinement
   instrumentation, and inference invalidation. An inout call must not be
   classified as an ordinary array initializer or element-store template.
3. Preserve modes and call markers through specialization; resolve old operands
   to their defining parameter, including G4 names and G3 substitutions.
   No old snapshot may become executable storage.
4. Files: P/`verify.py`, `infer.py`, `refine.py`, `mono.py`, `pruvc.py`;
   C/`refine.rs`, `mono.rs`; V/`symbolic.rs`, `infer.rs`, `lib.rs`,
   `bin/pruv-trace-dump.rs`; D/`driver.rs`;
   `tests/diff_py_adapter.py`, `tests/diff_trace.py`, `tests/smt_snapshot.py`,
   `tests/diff_compilers.py`, `tests/run_all.py`, `tests/run_all_rows.txt`,
   and §9 inventory/proof/rejection fixtures.
5. Add 16 positive proof roots: exact store/frame contracts for all concrete
   types, generic exchange, multiple outputs, forwarding, immutable old across
   two calls, untouched locals, legacy unit ensures, explicit unit ensures,
   direct recursion, cross-module mutual recursion, loop call havoc,
   refined-local preservation, explicit old loop invariants, and infer-enabled
   control cases. A fixture may cover several of these categories.
6. Add 18 negative proof roots covering false final ensures, entry/final
   confusion, stale caller contents, missing call requires, wrong multi-output
   relation, forgotten loop writes, incorrect frame claim, u8 range, missing
   local-refinement preservation, and recursive decrease failures.
   Include failures with `--infer` both off and on.
7. Include a loop that both calls inout and replaces the same local with a
   different-length array; no fixed-length assumption may leak across that loop.
   Include a return directly containing an inout call so post-call refinement
   obligations cannot be skipped by return.
8. Exit: all positive roots verify with strict trace agreement, each negative
   root fails at its recorded obligation, and no unknown is counted as success.
   Two proved callees with identical signatures/contracts but different bodies
   give the same caller obligations. G5-free SMT and shared gates pass.
   Code generation remains explicitly guarded.

## 12. A2 — Rust generation and runtime checks (binding)

1. Emit mutable slice parameters and explicit mutable/shared reborrows.
   Use signature lookup independently of whether a program uses G6.
   Preserve existing source-order argument evaluation and store temporaries.
2. Implement internal visibility and safe wrapper routing from §6, including
   legacy safe-plus-trust calls. Existing host wrappers still check their own
   requires under the existing policy.
3. Files: P/`codegen.py`, `mono.py`, `pruvc.py`;
   C/`codegen.rs`, `mono.rs`, `emit_common.rs`, `bin/pruv-rust-dump.rs`;
   D/`driver.rs`; `tests/diff_rust.py`, `tests/diff_compilers.py`,
   `tests/run_all.py`, `tests/run_all_rows.txt`, `tests/llvm_pending.txt`,
   and §9 inventory/runtime/example fixtures.
4. Add 12 runtime roots covering i64/u8/bool updates, generic i64/bool instances,
   repeated reborrows, read forwarding, two disjoint outputs, recursive/module
   calls, a copied independent owner, early return, and safe precondition,
   bounds, and u8-range failures. Use multiple metadata rows where appropriate.
5. Add three examples: set/exchange with exact frame contracts, an iterative
   reversal, and a generic in-place exchange. Host harnesses enter through
   ordinary wrappers, never directly through an inout helper.
6. Inspect emitted code for borrowed signatures, absence of borrowed-buffer
   clones, and safe checks. Runtime assertions must inspect actual resulting
   contents, not merely successful exit.
7. Exit: Rust source is byte-identical between compilers, all new Rust runtime
   cases pass in verified and applicable safe/trust modes, expected safe failures
   exit with the existing diagnostics, and shared gates pass. LLVM guard
   diagnostics match until A3.

## 13. A3 — LLVM, bindings, and SPEC user page (binding)

1. Implement §7 with a mode-aware internal signature printer. Both body and
   checked wrapper must omit readonly on mutable parameters.
   Keep ownership cleanup independent of mutable access.
2. Use one consistent host-eligibility rule in Rust emission, LLVM wrappers,
   raw/typed ABI enumeration, and Rust bindings. Add defensive eligibility
   checks to ABI construction paths rather than relying on one caller's filter.
3. Files: P/`llvmgen.py`, `pruvc.py`;
   C/`llvmgen.rs`, `abi.rs`, `bindings.rs`, `emit_common.rs`,
   `bin/pruv-llvm-dump.rs`; D/`driver.rs`;
   `tests/diff_llvm.py`, `tests/diff_compilers.py`, `tests/run_all.py`,
   `tests/run_all_rows.txt`, `tests/llvm_pending.txt`, `tests/g4/projects.py`,
   §9 inventory/runtime/example fixtures, `SPEC.md`, `BLUEPRINT.md`, `RESULTS.md`.
4. Run all 12 A2 runtime roots on LLVM. Add six runtime roots for optimized
   multi-array calls, repeated aliased read-only arguments, safe private-call
   failure, typed/raw host-wrapper regression, borrowed-buffer lifetime through
   repeated calls, and cross-module generic specialization.
   Use explicit symbol/attribute expectations alongside those executions.
5. Add two examples: a module containing a public Pruv-only inout helper and
   root wrapper, and a mutable-array service with several internal operations
   after one initial copy.
6. The SPEC update adds a one-page §6g covering syntax, exclusivity, old, frame,
   statement boundaries, generic support, refinements, modes, and host limits.
   Amend §§2–4, §6's expression list, §7's loop-write statement, and §7a's
   refinement expansion table so they no longer claim all parameters are
   immutable or that only assignment syntax changes a loop variable.
7. Exit: complete IR/binding bytes match across compilers; optimized execution
   matches both backends; no inout host symbol exists; mutable pointer
   definitions have no readonly; G5-free IR remains unchanged.
   Remove all G5 guards/pending rows and pass the full shared gates.
   Complete an independent correctness audit and confirmation after fixes.

## 14. Q — bounded stress, independent use, and performance (binding)

1. Files: `bench/fuzz/generate.py`, `oracle.py`, `run.py`, `README.md`;
   `bench/g5/run.py`, `mutate_ops.py`, `PROBLEMS.md`, `README.md`,
   `perf.py`, `solutions/`, `results/` (all new);
   §9 inventory and new regression fixtures; `RESULTS.md`.
   Add a separate `--g5` fuzz mode following G4's saved-project/replay convention.

2. Generate at least 30 verified programs for each seed 41, 56, and 57, with
   eight concrete inputs each. Cover all concrete types, generic instances,
   repeated/nested-function reborrows, multiple owners, loops, recursion,
   module calls, old-based contracts, and contract-preserving body replacements.
   Nested-function calls here remain at the statement boundaries of §2.1.

3. The independent interpreter maintains mutable owners and frozen old values.
   It checks final mutated arrays as well as result and output. It must not
   derive expected values from compiler SMT or generated code.
   Require agreement across two compilers, two backends, and verified/safe
   execution: at least 5,760 completed comparisons.
   Record seeds, feature counts, shortfalls, saved failures, and replay commands.
   Oracle gaps, unexpected rejections, unknowns, and timeouts cannot satisfy
   the count. Exercise infer on at least ten generated programs per seed.

4. Classify at least 40 behaviorally incorrect source mutants with contracts
   strong enough to expose their error. Include wrong indices, missing stores,
   wrong frame clauses, old/current confusion, omitted calls, and reordered
   operations. Record correct and weak-contract mutants separately.
   Require zero incorrectly verified mutants across compilers and backends.

5. Execute at least six compiler fault injections in disposable implementation
   checkouts: disabled exclusivity, old bound to current contents, omitted call
   havoc, omitted loop call-write collection, stale return-parameter overlay,
   and readonly retained on a mutable LLVM parameter.
   Include a direct expected-attribute check for the last fault; a runtime
   optimizer need not exploit every invalid attribute.
   Save patch identity, command, and detecting test for every injection.
   A list of fault names or proposed commands is not execution evidence.

6. Give an independent author only the updated SPEC and two new problems:
   a bounded byte-range transformation preserving untouched elements, and a
   module-based recursive array transformation with an ordinary host wrapper.
   Require exact content/frame contracts, not merely length or range properties.
   Record original attempts, compiler feedback, revisions, and manual assistance.
   Both final solutions must verify and run on both backends.

7. Measure reversal of 1,000,000 i64 elements using two equivalent implementations:
   in-place inout, and the prior read-parameter/copy-and-return style.
   Prove equivalent pointwise reversal contracts. Run both generated backends
   with identical optimization settings and deterministic inputs.
   Use an ordinary host entry that owns its working local so the host restriction
   is respected. Report setup-inclusive time and repeated-operation time
   separately; retain the copy-and-return version's intrinsic copies.
   Consume/check output to prevent dead-code elimination.
   Report allocation counts or copied bytes, peak memory where available, at
   least ten repetitions, medians and spread, compiler/runtime versions, target,
   and flags. Inspect generated code for actual remaining copies.
   Require zero algorithm-level buffer allocations in the inout reversal body;
   do not invent a mandatory speedup percentage. Investigate a repeatable
   slowdown and explain measurement noise or optimization effects.

8. Add four permanent rejection roots, two runtime roots, and one example
   from independently useful stress/audit cases. These are new roots, not
   duplicate counting of A0–A3 or random saved mutants.
   Exit: all minimum counts are met, no incorrect mutant verifies, every
   injected fault is detected, both independent solutions pass, the performance
   comparison is recorded, no unexplained differential mismatch remains, and
   all shared and existing mutation/benchmark gates pass.

## 15. Deferred work and evidence limits

Deferred:

- Inout calls nested in arbitrary expressions, conditions, or store operands.
  These need defined guarded-state transitions and backend evaluation-order
  lowering, not just a relaxed checker.
- Mutable host entries, safe Rust slice bindings for them, raw writable-buffer
  ABI contracts, and trusted foreign inout declarations.
- Disjoint slices, field places, element places, splitting a single array into
  permissions, and range-based exclusivity proofs.
- Mutable scalar, str, aggregate, recursive-value, and G6 collection parameters.
- References as values, explicit lifetimes, concurrency permissions, and
  persistent/shared mutation.
- Old of arbitrary expressions or locals, loop-entry snapshots, executable old,
  and dynamic ordinary postcondition checking.
- New inference templates, automatic frame inference, general heap separation
  logic, and additional alias metadata or scheduling transformations.

The lead's core exclusive-array and snapshot model is sound under the stated
place and ownership rules. The current implementation conflicts with a direct
minimal patch in four places: ensures restores all entry parameters, legacy
unit calls can omit ensures, loop analyses do not see call writes, and LLVM
array pointers are unconditionally readonly. Each is an explicit implementation
requirement above.

The statement-boundary restriction additionally prevents applying the proposed
havoc rule unsoundly inside the current expression evaluator. It is a deliberate
scope decision, not a measured implementation limitation of all possible designs.

Generic support and the cost of retaining existing array representations are
design judgments based on the inspected paths. Compilation, proof feasibility,
optimization quality, runtime behavior, and performance remain unmeasured until
the implementation gates run. No source outside this repository was inspected.
