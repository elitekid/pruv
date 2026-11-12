# G9: Recursion, Recursive Values, and Aggregate Buffer Fields

Status: **Design fixed for implementation, 2026-11-12; not implemented.**

This document defines batches A0–A4 and Q. Requirements and numerical gates below
are acceptance criteria, not measured results. The numbered implementation decisions
in §§10–15 are binding, following the format of G6 §§10–13.

## 1. Goal and foundation

G9 makes finite trees, JSON-like values, and recursive descent over arrays or UTF-8
bytes expressible and verifiable. A program must prove both its ordinary contracts
and termination of every cycle of Pruv function calls. This is the next G9 row in
`BLUEPRINT.md` §4, after G6; it does not implement G4 modules or G5 alias permissions.

The smallest useful release provides binary trees, linked sequences of JSON values
and object members, structs containing primitive arrays and strings, and recursive
functions with explicit measures. JSON numbers in examples are i64; full JSON number
syntax, floating point, Unicode escape decoding, and a complete JSON library are not
release requirements. Parsing examples must state precisely the grammar they accept.

### 1.1 Repository facts

- `SPEC.md` §§3 and 6c prohibit function recursion; §6a prohibits recursive types and
  array fields. §6b also prohibits string fields. These are intentional G9 migrations.
- The Python parser is `pruvc/vparser.py`, not `parser.py`; AST nodes are in `vast.py`.
  Function headers currently collect requires/ensures; only while nodes carry decreases.
- `pruvc/check.py` resolves declarations, checks bodies/effects, then calls
  `no_recursion()`. Its declaration-name call graph rejects self and mutual cycles
  with `type/recursion`. `type_recursion()` rejects nominal cycles with
  `type/recursive_type`; `resolve_types()` rejects buffers with `type/field_type`.
- Rust mirrors these checks in `pruvc-rs/crates/pruv-core/src/check.rs`, including
  `type_recursion` and `no_recursion`; parser/AST/type metadata live alongside it.
- `pruvc/verify.py` evaluates call arguments, proves `call_requires`, creates a fresh
  well-formed result, and assumes ensures. Rust mirrors this in `pruv-proof/src/symbolic.rs`.
  Neither verifier proves a callee by inlining its body at each call.
- Ordinary unit-returning calls currently skip ensures; trusted unit calls do not.
  G9 must address this explicitly when using recursive unit contracts (§11).
- `pruvc/mono.py` and core `mono.rs` specialize after verification using a deduplicated
  work list. Type dependency ordering and well-formedness walks currently assume
  acyclic declarations. Merely removing the checker rejection would be insufficient.
- `pruvc/codegen.py` and core `codegen.rs` emit Rust; `pruvc/llvmgen.py` and core
  `llvmgen.rs` emit IR. Rust `abi.rs`/`bindings.rs` and Python `llvmgen.py` own bindings.
  Existing aggregates are Copy; LLVM uses inline fields and explicit buffer cleanup.
- `docs/G3_SPEC.md` establishes definition-level generic proof and specialization
  limits. `SPEC.md` §6d and G6 §§10–13 establish a separate owned-collection universe.
  G9 does not silently extend either universe to recursively owned payloads.

### 1.2 Non-goals

No cyclic runtime graphs, shared mutable nodes, references as values, garbage
collection, user destructors, higher-order recursion, coinduction, or automatic
induction search. No user functions in contracts, recursive logical predicates,
general lemma language, polymorphic recursion, or recursive generic type declarations.
No arrays of aggregates, nested arrays, nested G6 collections, or new scalar types.
There is no proof of sufficient heap or native stack space.

## 2. Function surface and termination measures

Ordinary `fn` declarations may call themselves or later declarations. Mutual recursion
requires no `rec` keyword or declaration group. All signatures are resolved first.

```pruv
fn even(n: i64) -> bool
  requires n >= 0
  ensures result == (n % 2 == 0)
  decreases n
{
  if n == 0 { return true; }
  return odd(n - 1);
}
fn odd(n: i64) -> bool
  requires n >= 0
  ensures result == (n % 2 == 1)
  decreases n
{
  if n == 0 { return false; }
  return even(n - 1);
}
```

A function header accepts at most one `decreases Expr`, after all requires/ensures
and before `{`. Every member of a recursive call-graph SCC must have one, including
unused definitions and edges in syntactically unreachable branches. A nonrecursive
function may supply one; its entry obligations still apply. Foreign declarations
cannot have decreases: foreign termination remains trusted and outside this theorem.

The expression has static type i64 and is evaluated as a **mathematical integer**,
like other contracts. Prove it defined and >= 0 at entry under requires. There is
no i64 upper-bound obligation on contract intermediates or the resulting measure.
Only parameters, constants, and existing contract operations may occur; no result,
locals, allocation, effects, or user-function calls. Partial operations retain their
short-circuit domain obligations. The clause does not establish additional requires.

One scalar measure is sufficient for this release. Lexicographic tuples, multisets,
ordinal measures, inferred measures, and implicit SCC phase numbers are deferred.
Mutual phases can use an explicit scalar such as `2 * n + 1` versus `2 * n`;
contract arithmetic makes that encoding independent of executable i64 overflow.

Generic function recursion is allowed only with a stable parameter vector. Within
an SCC all members have the same number and ordered bounds of type parameters;
each intra-SCC call forwards the caller's parameters in that exact order, modulo
binder renaming. No constants, permutation, or type constructors on those edges.
Non-generic SCCs have the empty vector. Calls between SCCs retain G3 substitution.
This admits generic recursive array algorithms without polymorphic recursion.

## 3. Recursive types and structural size

Recursive declarations are non-generic nominal structs/enums in arbitrary order.
Recursion edges must be direct nominal fields, not hidden inside generic arguments,
Option/Result, arrays, or collections. Existing acyclic value fields remain legal.

```pruv
enum Tree { Empty, Node(value: i64, left: Tree, right: Tree) }
struct Document { root: Json, source: str, offsets: [i64] }
enum Json {
  Null, Boolean(value: bool), Number(value: i64), Text(value: str),
  Array(items: Items), Object(members: Members)
}
enum Items { End, Next(value: Json, rest: Items) }
enum Members { End, Next(key: str, value: Json, rest: Members) }
```

A recursive struct is useful through a terminating enum, for example
`struct Node { value: i64, next: Link }` with `enum Link { End, More(node: Node) }`.
`struct Bad { next: Bad }` is rejected. Every declared type must have a finite
inhabitant: compute a least fixed point, marking a struct when all fields are
inhabited and an enum when some variant's fields are inhabited. Require every
declaration to be marked, not merely one declaration per SCC. Empty buffers and
ordinary inhabited scalar/value fields are base cases; Box alone is not a base case.

The compiler inserts indirection; source programs never write Box or dereference.
For each field edge between declarations in the same recursive type SCC, store
that field as a boxed child. Box every such edge, not a traversal-dependent minimum
feedback set. Edges between SCCs remain inline. Representation never permits cycles.

Add reserved contract-only builtin `size(x)` for non-generic nominal values.
It counts nominal struct/enum constructor occurrences in the value:

```text
size_D(C(fields)) = 1 + sum(weight(field))
weight(nominal value) = size(value)
weight(Some(v)) = weight(v); weight(None) = 0
weight(Ok(v)) = weight(v); weight(Err(code)) = 0
weight(scalar, primitive array, str) = 0
```

The traversal includes acyclic nominal fields too. It follows only active payloads;
every direct nominal child has strictly smaller size, even across mutually recursive
types. Array length and string byte length do not contribute: use `len` explicitly
for parsing measures. `size` is total, pure, mathematical, and not executable i64
code. It can appear in requires/ensures/invariants/assert/decreases. Calls on a scalar,
buffer, abstract T, or generic nominal application are rejected in G9.

```pruv
fn contains(t: Tree, x: i64) -> bool
  ensures is_variant(t, Tree::Empty) ==> !result
  ensures is_variant(t, Tree::Node) &&
          variant_field(t, Tree::Node, value) == x ==> result
  decreases size(t)
{
  match t {
    Tree::Empty => { return false; }
    Tree::Node(v, l, r) => {
      if v == x { return true; }
      if contains(l, x) { return true; }
      return contains(r, x);
    }
  }
}
```

This contract proves the two stated facts, not full membership equivalence. Stronger
tree properties need explicit expressible contracts; G9 does not invent a recursive
membership predicate. Array recursion can state full content properties using the
existing quantifiers/aggregates, with `decreases len(a) - i` and suitable bounds.

## 4. Fields, value semantics, and matching

Permit `[i64]`, `[u8]`, `[bool]`, and `str` in non-generic struct fields and enum
payloads. Such declarations may nest through other non-generic declarations, with
no new fixed nesting limit beyond existing compiler resource limits. Strings keep
UTF-8 and byte-index semantics; primitive arrays keep the 2^40 length limit.

Call a type **extended** if it is recursive, contains a buffer field, or transitively
contains an extended nominal field. This is compiler metadata, not a source bound.
G3 Value/Element remain unchanged: extended types are not generic arguments or
Option/Result payloads and cannot be G6 Vec/map elements. Generic declarations may
not contain extended types or buffer fields, including `[T]` fields. Use dedicated
non-generic enums instead. Existing generic acyclic declarations remain supported.

Extended aggregates are independent values. Copying an aggregate deep-copies its
owned buffers and boxed descendants; mutating one copy cannot change another.
Function parameters are immutable read views. Reading fields, passing a read argument,
and matching do not allocate. Materializing an existing aggregate in an owning
position (let, assignment, constructor field, return) clones it and requires `alloc`.
A fresh constructor/call result transfers into the owning position without another
clone. Any constructor that allocates a boxed field requires `alloc`, even if empty.
Effects are determined conservatively before optional copy-elision optimizations.

Array/str fields keep G2 explicit ownership: initializing or replacing a buffer field
requires a fresh buffer expression or `copy(view)`; a named buffer is not silently
moved or aliased. Returning a field buffer also requires `copy`. Expected narrow-array
types do not flow into constructor arguments; bind `alloc` to a typed local first,
then use `copy(local)` in the constructor. This keeps the existing hint rule exact.

```pruv
struct Packet { bytes: [u8], label: str }
fn packet_demo() -> i64 ! alloc {
  let bytes: [u8] = alloc(2, 7);
  let p: Packet = Packet { bytes: copy(bytes), label: "ok" };
  let mut q: Packet = p;
  let mut changed: [u8] = copy(q.bytes);
  changed[0] = 9;
  q.bytes = copy(changed);
  assert p.bytes[0] == 7;
  return q.bytes[0];
}
```

Whole-field assignment through struct paths remains allowed only on mutable locals.
Direct `p.bytes[i] = v` is deferred; copy the field to a mutable array, update it,
and replace the field. No enum payload mutation or update through pattern binders.
RHS evaluation completes before the replaced value is dropped. Rebuilding the root
preserves unmodified fields; loops modifying a field still havoc the whole root.

Existing exhaustive statement matches suffice: exactly one arm per variant, no
wildcards, guards, nested patterns, or match expressions. Bindings are immutable
arm-local views; scalars are read directly and extended values clone only in owning
positions. Matching does not consume its scrutinee. Escaping a payload by return or
assignment produces an owned copy, so there are no source-level dangling borrows.
Backend views must not survive mutation of the owning root. G9 rejects root mutation
during that match arm with `type/recursive_borrow`, including replacing an ancestor
of the matched field. Automatic snapshots on mutation are deferred. Matching a fresh
temporary keeps that temporary alive until the selected arm exits.

Contract equality on buffer-free recursive aggregates is structural, including only
active payloads. Aggregates transitively containing arrays/str cannot use whole-value
`==`/`!=` (`type/eq_type`); compare tags, lengths, and indexed contents. This prevents
accidentally exposing SMT array tails or changing G2's whole-buffer equality rule.

## 5. Verification and inductive reasoning

Build deterministic SCCs over resolved Pruv declaration identities before proof.
A singleton with a self-edge is recursive. Include all checked call expressions;
trusted/catalog calls are leaves and cannot create Pruv backedges. Validate effects
on every edge as today; declaring recursive effects is not an inference fixed point.

For a function f, freeze entry parameters and evaluate its measure M_f once logically.
At a call f -> g inside the same SCC, evaluate actual arguments once left-to-right,
then prove in this order:

1. Ordinary callee requires, in source order (`call_requires`).
2. Definedness of the instantiated callee measure (existing domain codes).
3. M_g(actuals) >= 0 (`recursive_nonneg`).
4. M_g(actuals) < M_f(entry) (`recursive_decrease`).
5. Only then introduce a fresh result and assume the instantiated callee ensures.

At each function entry, prove measure definedness and nonnegativity too. The caller
measure is the frozen entry value, not a mutable local, previous sibling call, or
loop iteration value. Negative values on terminal invocations are also rejected.
Calls outside the SCC need no relative decrease; each recursive SCC proves its own
well-founded descent. Existing while termination obligations remain independent.

Assuming a recursive callee's postcondition is an induction hypothesis for smaller
measures, not an unverified axiom about its body. Verify all bodies in the SCC under
this rule and reject the entire compilation if any obligation fails or is unknown.
No failed termination check may authorize code generation. In particular,
`ensures false` plus an unchanged self-call must fail termination, not prove false.
Earlier successfully justified recursive calls can supply facts for later calls.
Never use the current call's ensures to establish its own decrease or precondition.

### 5.1 Recursive SMT values

Create each recursive nominal SCC with one simultaneous SMT datatype declaration
(`z3.CreateDatatypes` / corresponding Z3 C API). Constructor and selector identities
follow declaration/variant/field order; dependencies between SCCs are created first.
These are inductive finite datatypes, not uninterpreted pointers or bounded unrollings.
No user-visible Box appears in logic. SMT datatype occurs checks exclude cycles.

Represent a buffer field by a datatype containing integer length and an SMT array
of the existing element sort. Field projection adapts it to the existing Arr model.
Only indices below length matter. Never use raw datatype equality for a buffer-bearing
aggregate. String proofs retain G2's byte abstraction rather than assuming UTF-8 facts.

Define mutually recursive `wf_D` and `size_D` functions structurally over active
constructors. Well-formedness checks scalar ranges, buffer lengths/element domains,
and child well-formedness. A1 decision: `size_D` and `wf_D` are uninterpreted function
symbols constrained only by the one-step equations of observed terms below, which are
instances of the structural definition; Z3 recursive-function definitions are not used
(their automatic unfolding timed out on the tree fixtures), and no cyclic axioms are added.
The weight of an admitted acyclic G3 field application is a constant when its size is
value-independent, otherwise a per-instance uninterpreted size constrained by positivity
only; this does not expose `size` on generic applications or abstract parameters in source.
Field access observes the parent term first, and `observe` caches observed terms by id.
At constructors, matches, and guarded selectors expose the corresponding one-step
equations, child wf facts, and nonnegative size facts. The size positivity/child-smaller
lemmas are valid by structural induction on finite datatypes and need an audited
justification in `tests/g9/model_notes.md`; they are not user-assumed contracts.

Build declarations once per model and unfold only observed terms, never recursively
expand an arbitrary parameter's entire type in the host language. Fresh parameters,
call results, and havoc values get wf; constructor results obtain wf from checked
fields. Partial selectors still require `variant_domain`/`contract_domain` guards.
No numeric range may be assumed for an unchecked stored value to discharge its own proof.

Proof arithmetic is mathematical even in aggregate contract literals: do not force
their intermediate i64-looking fields into runtime ranges. Distinguish those terms
from well-formed executable values, as the existing contract semantics requires.

## 6. Rust backend and runtime contracts

Emit extended types with Clone, never Copy. Internal recursive edges are
`::std::boxed::Box<R(Child)>`; buffers are Vec<i64/u8/bool> or owned String.
Nonextended types keep their existing derives and output bytes. Read parameters and
pattern payload views use Rust references; owning contexts clone explicitly and
fresh temporaries move. Do not require `alloc` just to traverse a tree by reference.

RAII drops owned locals, fields, and temporaries on normal exits. No Rc/Arc, interning,
shared tails, or pointer-identity equality. Generate recursive helpers deterministically
and reserve their `pruv_` names. Tail-call optimization is not required.

Functions whose signatures contain extended types are internal in both backends,
including non-generic functions. No raw ABI or `--rust-bindings` entry is generated
for them. Ordinary exported scalar/buffer wrappers can build and consume these values.
Foreign signatures stay G6-only; host construction/deserialization of trees is deferred.

Runtime requires retain short-circuit evaluation, i128 checked arithmetic, and the
existing shared 2^30 iteration budget. Size/equality/contract conversion visits of
nominal nodes cost one budget unit each; charge buffer elements when visited.
A runtime `requires` operand that would copy a named value whose type can hold an
array or str field (directly or through field types) is rejected with
`codegen/unsupported_type`; scalar-only nominal copies are charged one unit per node.
Compute size with checked i128 addition; budget/overflow fails with
`pruv: requires undefined: ...`, exit 101. Checks must not eagerly inspect an
inactive variant or skipped operand. Ordinary ensures and decreases are erased.

`--no-verify` still checks syntax, SCC annotations, types, effects, and ownership,
but does not prove or dynamically enforce decreases. It preserves safe arithmetic,
bounds, allocation, and entry-contract checks. It can recurse forever.
Both modes can exhaust native stack in calls, cloning, contract traversal, or drop.
G9 adds no depth check, no portable stack-overflow exit code, and no stack-space theorem.
OOM and stack exhaustion are resource failures, never successful verified results.

## 7. LLVM backend

Keep ordinary acyclic aggregates inline. A recursive SCC field is an opaque `ptr`
to an independently allocated object of the child's named LLVM type. Buffers remain
`{ptr, i64}`. Enum storage retains the existing tag plus all variant payload slots;
inactive pointers are null and inactive scalar storage is zero. Only active payloads
are loaded, cloned, compared, or dropped. Type layout follows declaration field order.

Generate per-type clone/drop helpers. Clones recursively allocate and copy active
children and buffers. Drop visits active children before freeing the node allocation;
inline root aggregates are not themselves freed. Internal read arguments are pointers
to valid caller-owned storage, and aggregate results use explicit output storage.
The backend must distinguish owned storage from borrowed views; every normal path,
including loop exits, replacement, and early return, releases each owner exactly once.

Add a separate runtime node allocator/free pair with byte size and alignment,
`pruv_node_alloc_v1(size, align)` / `pruv_node_free_v1(ptr, size, align)`, and a link
marker `pruv_runtime_nodes_v1`. These are new internal symbols, not changes to the
G2 v2 buffer ABI (whose element-size/alignment assumptions do not describe nodes).
Check layout multiplication/addition and allocation failure; allocate at least one
byte for zero-sized nodes. Support the existing C and Rust-host allocator modes,
using matching allocation/free layouts and generated host helpers in the latter.
Node helpers never call Rust Box deallocation on C-allocated memory or vice versa.

Native call, clone, and drop recursion has the same resource policy as Rust (§6).
Runtime contracts implement the same i128/domain/budget semantics on LLVM. G9-only
programs require no G6 Rust shim. Existing G6 target/bridge restrictions still apply
when the program separately uses G6 features outside that backend's supported subset.

During A0–A2, unsupported G9 execution fails with `codegen/unsupported_type`:
`G9 recursive values and aggregate buffer fields are not implemented by the llvm codegen layer yet`.
Use `tests/llvm_pending.txt` for the affected runtime paths, never skip them silently.
A3 must support the entire admitted G9 core and remove all G9-only pending rows.
No permanent G9 LLVM subset is planned; existing unrelated G6 pending rows remain.

## 8. Compatibility and diagnostics

Preserve G9-free dumps, SMT snapshots, Rust, IR, bindings, and diagnostic order except
explicitly reviewed migrations. Inventory old recursion and field rejections in
`tests/g9/legacy_migrations.json`: old path/stage/code, new result, rule, replacement
row. In particular, uninhabited G1 recursive structs remain rejected; productive
cycles become positive tests. Missing function measures remain rejection tests with
the new code. Generic recursive type tests remain rejected by the scope restriction.

Codes use existing lowercase underscore names and ordinary JSON locations/fixes.
New static codes: `parse/decreases_syntax`, `type/recursive_decreases`,
`type/recursive_polymorphism`, `type/recursive_generic_type`, `type/recursive_borrow`,
and `type/size_type`. Reuse `recursive_type` for uninhabited types, `field_type` for
forbidden fields, `type_argument` for extended generic arguments, `eq_type` for
forbidden equality, `foreign_owned_type` for G6 nesting, and `effect/missing_effect`.
New proof codes are `verify/recursive_nonneg` and `verify/recursive_decrease`.
Existing loop `decreases_nonneg`/`decreases_decrease` remain unchanged.

## 9. Shared batch gates and paths

Abbreviations: P = `pruvc/`, C = `pruvc-rs/crates/pruv-core/src/`,
V = `pruvc-rs/crates/pruv-proof/src/`, D = `pruvc-rs/crates/pruvc/src/`.
Paths below are future implementation targets; this design task creates only this file.

Every batch implements Python and Rust together and requires byte-identical applicable
artifacts: parse/check dumps, normalized proof traces, Rust source, LLVM IR, bindings,
and diagnostics. Add group `g9` to `tests/diff_parse.py`, `diff_trace.py`, `diff_rust.py`,
and `diff_llvm.py`, selecting `tests/g9/{frontend,proof}`, `tests/must_reject/g9_*`,
`tests/runtime/g9_*`, and `examples/g9_*` as appropriate. Deduplicate overlapping paths.

Wire `g9_frontend` and `g9_proof` into `tests/run_all.py`, following G6's backend-null
rows. Frontend rows check acceptance before the downstream guard; proof rows require
successful proof before any expected guard. After guards lift, use the real successful
compiler outcome. Execution fixtures remain `tests/runtime/g9_*.pruv` with matching
JSON mode/output metadata; rejection fixtures remain in `tests/must_reject/`.
Update `tests/run_all_rows.txt` deliberately; source counts are not mode/backend rows.

Run the full regression inventory for both compilers and backends and applicable
`tests/m3_all.py` stages at each exit. Proof/codegen changes also require existing
bench re-grading in default/`--trust-callers` modes and mutation checks per BLUEPRINT.
New deterministic proof comparisons must be `same`, not `cex_only` or `same_unknown`.
One audit and confirmation after fixes precede release; record actual evidence and
unresolved findings in RESULTS during implementation, never infer success from parity.

## 10. A0 implementation decisions — frontend (binding)

### 10.1 Representation and ordering

Add optional `Function.decreases` to P/vast.py and C/ast.rs, omitted from legacy dumps
when absent. Extend P/vparser.py and C/parser.rs header parsing; loop syntax is unchanged.
P/check.py and C/check.rs replace cycle bans with SCC validation. Shared metadata in
P/typeinfo.py and C/typeinfo.rs records SCC IDs, boxed edges, extended status, and
inhabitance. Number SCCs by smallest declaration index; members/fields use source order.
Run type resolution, type SCC/inhabitance, body checking, then function SCC validation.
Do not traverse recursive metadata as an infinitely expanded type expression.

### 10.2 Static decisions and diagnostics

Duplicate, empty, tuple, or misplaced function clauses give `decreases_syntax` at the
offending token. Missing recursive measures and foreign decreases give
`recursive_decreases` at the function name/clause. Wrong expression type reuses the
ordinary type mismatch; prohibited contract operations retain existing codes.
Intra-SCC type substitution outside §2 gives `recursive_polymorphism` at the call.
A generic declaration in a recursive type SCC gives `recursive_generic_type` before
inhabitance checking. Uninhabited SCCs give `recursive_type` at the first unmarked
declaration, with a deterministic cycle witness and a fix requesting a base variant.
Reserve `size` through the existing `type/reserved` rule; illegal operands give
`size_type`, use in executable code gives `contract_only`.

Track owning/view expression contexts to charge clone/box effects. Reject assignment
to a match scrutinee's root while any payload view is live (`recursive_borrow` at
the assignment); callers cannot mutate borrowed parameters. Keep `move`/`take`
restricted to G6 collections. Install explicit downstream guards in both drivers.

### 10.3 Tests and exit criteria

Add at least 24 `tests/g9/frontend/*.pruv` fixtures and 24 static rejection sources
with JSON metadata: forward/self/mutual calls, stable generic recursion, hidden SCC
edges, productive/unproductive types, buffers, cloning effects, views, nesting, and
new-name collisions. Record every old rejection migration before changing it.
Exit: `g9_frontend` rows pass; parse/check `g9` dumps and guard diagnostics are
byte-identical; full shared gates pass. Proof/generation cannot accept unchecked G9.

## 11. A1 implementation decisions — verification (binding)

### 11.1 Pipeline and model

Implement §§3/5 in P/verify.py and V/model.rs, symbolic.rs, obligation.rs, sys.rs,
and lib.rs. Add recursive-function Z3 bindings only as needed for wf/size definitions.
Preserve declaration-based model cache keys and stable fresh-symbol numbering.
P/infer.py and V/infer.rs gain no recursion templates; they may not infer a missing
decreases clause or treat a candidate proof as final termination evidence.
Move guards after verification in both drivers and trace adapters.

For SCC members, ordinary unit-returning recursive calls also assume ensures after
the termination obligations. Give the same unit-call behavior to calls targeting
those members from outside the SCC. Leave unrelated legacy unit traces unchanged.
Check contract domains for every function independently of recursive result facts;
in particular a measure cannot depend on a postcondition from its own invocation.
Entry nonnegative failures point to the clause; call failures point to the call and
name both measures. SAT shows counterexample parameters; unknown remains
`verify_unknown`, never a fabricated counterexample or termination certificate.

Serialize recursive counterexamples in constructor/field order with a display limit
of 64 nominal nodes and depth 16, using an explicit truncated marker beyond either.
Display bounds never constrain SMT values or turn incomplete models into proof facts.

### 11.2 Tests and exit criteria

Add at least 24 positive `tests/g9/proof/*.pruv` fixtures and 24 proof rejection
sources. Include two- and three-function SCCs, differing phase measures, array
descent with aggregate postconditions, tree traversal, size facts across type SCCs,
buffer wf after havoc, unit contracts, and generic proof-once checks.
Reject unchanged/increasing/negative measures, cyclic false ensures, callee ensures
used to justify decrease, undefined measure selectors, false base cases, false
inductive steps, forgotten buffer facts, and missing callee preconditions.
Exit: `g9_proof` rows pass, `diff_trace.py` group `g9` is strictly `same`, old snapshots
are unchanged except reviewed migrations, and all shared regression/bench gates pass.

## 12. A2 implementation decisions — Rust backend (binding)

### 12.1 Specialization and lowering

Update P/mono.py and C/mono.rs to register instances before following recursive calls.
Stable generic SCCs deduplicate by existing keys; keep all G3 specialization limits.
Dependency ordering operates on SCC condensation, not a recursive topological walk.
P/codegen.py and C/codegen.rs/emit_common.rs implement §6 and view/clone contexts.
Generate only needed helpers, in declaration order; no addresses or randomized hashes
enter output. `size` is lowered only in runtime contracts; decreases stays erased.
Fresh temporaries used as read arguments live through the call and then drop.
Extended signatures are private, including their checked entry wrappers.

No new diagnostic family: clone allocation omissions are `missing_effect` from A0;
remaining LLVM work uses `codegen/unsupported_type`. Add runtime contract budget
failures to existing undefined-contract behavior, not a new language error.

### 12.2 Tests and exit criteria

Add at least 20 runtime sources with JSON metadata: scalar/mutual recursion, tree
construction and pure traversal, independent clones, nested buffers, early returns,
field replacement, recursive pattern views, string byte reads, and contract budgets.
Use scalar public wrappers so host tests do not depend on a new recursive ABI.
Test default, safe, and trust modes; do not run deliberately divergent safe programs
without an external timeout. Register only affected LLVM rows as pending.
Exit: Rust execution agrees across compilers, Rust source is byte-identical for `g9`,
specialization terminates, guard diagnostics match on LLVM, and shared gates pass.

## 13. A3 implementation decisions — LLVM backend (binding)

### 13.1 Allocation, cleanup, and checks

Implement §7 in P/llvmgen.py, P/runtime.c, C/llvmgen.rs, abi.rs, bindings.rs, and
driver/link integration only where the new runtime marker requires it. Use target
layout size/alignment, not Python-host pointer sizes. Emit node allocation/drop
helpers with null-initialized inactive slots; never drop a borrowed view.
Evaluate RHS and acquire its owned result before destroying an assignment target.
Recursive helpers must not annotate borrowed child storage as mutually `noalias`:
the same subtree may be passed as two read arguments.
Emit checks in safe mode before any inbounds access or arithmetic assumption.

No new static code is needed; stale runtime failures use existing link diagnostics.
Unsupported existing G6 combinations retain their G6 diagnostics and pending rows.
Remove the G9 staging guard only after IR, contract checks, and cleanup are implemented.

### 13.2 Tests and exit criteria

Run every A2 G9-only runtime fixture on LLVM, adding at least eight cleanup/layout
cases for mutually recursive types, inactive variants, nested buffers, replacement,
branch/loop/early-return cleanup, and borrowed aliases. Instrument node and buffer
allocation balance on normal termination using the existing runtime counting pattern.
Test both allocator modes and missing/wrong runtime-marker link failures.
Exit: zero G9-only pending rows; IR and bindings are byte-identical under `diff_llvm.py`
group `g9`; all executions and balance checks pass for both compilers. Report actual
host platforms; cross-emission is not execution evidence. Shared gates pass.

## 14. A4 implementation decisions — user documentation and examples (binding)

### 14.1 User-facing contract

Add a concise SPEC §6e covering recursion, decreases, size, finite recursive types,
owned fields, allocation effects, matching, and resource limits. Update contradictory
statements in §§3, 6a, 6b, 6c, and §7; preserve §6d's collection restrictions.
Clarify the unchanged G3 Value universe and stable generic function recursion.
Add at least eight `examples/g9_*.pruv`: even/odd, phase measures, array suffix scan,
tree traversal, recursive struct/link, JSON-like construction, a documented restricted
recursive-descent parser, and independent buffer-field copying. Contracts must state
useful results, not merely `ensures true` or termination.

No new diagnostic codes. Document existing/new G9 codes and fixes without claiming
that any arbitrary recursive predicate is expressible or automatically inductive.
The parser example must prove cursor progress and access bounds for every recursion
edge; its restricted grammar is part of its example documentation.

### 14.2 Tests and exit criteria

Examples run through `run_all` example rows and every applicable `g9` differential
group; documentation snippets are backed by frontend/proof/runtime fixtures.
Exit: all A0–A3 criteria still pass, both compilers remain byte-identical, row inventory
and migration manifest reconcile, no admitted G9 core uses a staging guard, and the
audit plus fix-confirmation has no unresolved required findings. Record scope and
measured results in BLUEPRINT/RESULTS during implementation; this file makes no claim
that those future edits or checks have already occurred.

## 15. Q implementation decisions — soundness stress and independent use (binding)

### 15.1 Fuzzing and mutants

Add `--g9` mode to `bench/fuzz/generate.py`, oracle.py, run.py, and README.md.
Generate bounded finite trees/JSON lists, direct/mutual recursion, array cursors,
clones, and field replacement. The independent oracle uses its own value interpreter,
not compiler SMT terms or generated backend helpers. Compare both compilers, both
backends, and verified/safe outputs on identical inputs.
Seeds 41, 56, and 57 each require at least 100 verified G9 programs and eight concrete
inputs per program, plus 20 deliberately unproved well-typed safe-only programs.
Bound generator depth/work externally; resource timeout is not proof of correctness.

Add `bench/g9/mutate_ops.py`, run.py, PROBLEMS.md, solutions/, and results/.
Require at least 80 independently classified incorrect mutants: deleted progress,
wrong phase, missing base case, wrong return, swapped recursive children, bad bounds,
false ensures, lost clone isolation, wrong active-payload drop, or stale field facts.
Separate source-contract mutants (must be rejected) from compiler fault injections
(must be caught by differential/runtime/model tests). A timeout, unknown, crash,
unsupported feature, or unexecuted mutant is not a successful semantic rejection.
No new diagnostic codes; use existing G9 and soundness-failure classifications.
Ground truth is graded against the problem's stated contracts: a mutant that fails
the full functional tests but satisfies every stated requires/ensures on every test
input (checked by executing those clauses as Rust assertions), changes no signature or
contract line, and keeps every helper contract on those inputs (checked by the reference
interpreter `bench/fuzz/oracle.py`) is classified `contract_weak`. It is not an incorrect mutant and does not count toward the 80; it
measures a weakness of the problem statement, not of the verifier.

### 15.2 Independent use and exit criteria

Four fresh problems: array recursive search with a quantified postcondition; tree
traversal with size termination; bounded JSON-like descent returning a cursor/result;
and nested buffer copying with independence assertions. An independent author gets
only SPEC and problem statements, no implementation hints or reference solutions.
Record first attempts and every diagnostic-driven revision. Require final 4/4
solutions to verify and execute across both compilers/backends; report first-attempt
success separately. Validate answers with independent graders and incorrect variants.

Exit: zero incorrect source mutants verified, all injected faults detected, zero
unexplained fuzz mismatches, all four final independent solutions pass, and existing
bench/mutation numbers do not regress. Run all shared gates, including byte-identical
`g9` groups and complete `run_all` rows. Measure proof latency, generated size, clone
allocation counts, and traversal time; investigate repeated legacy latency regression
above 10%. Small-case agreement cannot establish stack safety or solver completeness.

## 16. Deferred list and remaining risks

- Lexicographic/ordinal/multiset measures, automatic termination inference, and
  automatic induction, recursive specification functions, and user lemma procedures.
- Recursive generic types, changing type arguments on recursive edges, widening
  Value/Element, Option/Result of extended types, and owned generic field capabilities.
- Arrays of structs/trees, nested arrays, nested collections, direct array-field
  element stores, enum payload mutation, match guards/expressions/nested patterns.
- Shared DAG storage, cycles, references, mutation permissions, copy-on-write, move
  syntax for aggregates, custom drops, and guaranteed linear-time persistent updates.
- Public recursive-value ABI, host tree imports, foreign recursive values, and
  serialization/deserialization libraries. Existing public ABIs stay unchanged.
- Full JSON parsing, floating-point numbers, Unicode escape decoding, modules, I/O,
  stack-overflow detection/recovery, tail-call guarantees, and bounded-memory proofs.

The design choices are fixed; their implementation feasibility is not measured here.
Recursive wf/size definitions plus buffer quantifiers may need solver engineering;
unknown must fail closed. Implicit deep cloning can be expensive, especially repeated
list construction; measure it without weakening independence. Native recursive drop
and clone can exhaust stack even when user recursion terminates. Those resource
limits are explicit, not unresolved choices. No compiler, benchmark, or runtime test
was executed to validate this proposed feature during this document-only task.
