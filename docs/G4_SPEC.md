# G4: Modules, Visibility, and Packages

Status: **Design fixed for implementation, 2026-11-12; not implemented.**

This document defines four implementation batches A0–A3 and a small Q batch.
Numbered decisions in §§10–14 are binding acceptance criteria, not measured results.
Each batch implements Python first, then the Rust port, with differential checks
before the next batch starts.

## 1. Goal and foundation

G4 lets one Pruv program occupy several files, gives declarations explicit visibility,
and distinguishes Pruv-callable functions from host-callable entry points.
It supports growing an application backend without adding a build system.
`BLUEPRINT.md` §4 places G4 after completed G3, G6, and G9 work.
Packages and independently compiled dependencies are deferred to G4b.

### 1.1 Verified repository facts

- `pruvc/pruvc.py:68` defines `compile_file`; it reads one UTF-8 file, parses,
  checks, verifies, specializes when needed, and generates output.
- `pruvc/vparser.py:6` defines Pruv keywords. `mod`, `pub`, `use`, and `crate`
  currently belong to reserved Rust names, not supported module syntax.
  `::` already serves enum references and explicit generic applications.
- `pruvc/vparser.py:192` accepts functions, trusted Rust functions, structs,
  and enums at top level. It does not load module files.
- `pruvc/check.py:101` builds flat function/type maps. It rejects duplicate
  functions, duplicate types, and type/function name collisions.
  Its pipeline includes refinement expansion, type resolution, and G9 SCC checks.
- `pruvc/check.py:1286` rejects ordinary function calls inside contracts.
  G4 therefore need not introduce visibility rules for callable specification helpers.
- `pruvc/verify.py:1535` proves callee requires, checks recursive termination,
  creates a fresh result, and assumes ensures without inlining the callee body.
  `verify_program` at line 1957 visits all definitions, including unused ones.
- Ordinary nonrecursive unit calls currently skip ensures; trusted and recursive
  unit calls assume them. The Rust counterpart is
  `pruvc-rs/crates/pruv-proof/src/symbolic.rs:1809`.
- `pruvc/codegen.py:483` emits public Rust types and public struct fields.
  At line 732 it makes generic instances, collection signatures, and extended
  G9 signatures private. Existing functions are therefore not universally exported.
- `pruvc/codegen.py:737` emits checked wrappers for functions with requires;
  verified internal calls bypass them, while safe-mode calls use checked entries.
- `pruvc/llvmgen.py:2961` filters bindings by existing export eligibility.
  At line 3141 its generator emits internal bodies, checked entries, and ABI wrappers.
- `pruvc/mono.py` retains every nongeneric function as a specialization root.
  `pruvc-rs/crates/pruv-core/src/mono.rs:757` implements the corresponding worklist.
- Rust frontend and emission code reside in `pruvc-rs/crates/pruv-core/src/`;
  proof code resides in `pruvc-rs/crates/pruv-proof/src/`.
  `pruvc-rs/crates/pruvc/src/driver.rs:200` implements the single-file pipeline
  and additionally supports native object/executable emission.
- `tests/run_all.py` inventories backend/mode rows and runtime JSON expectations.
  `tests/diff_compilers.py` compares diagnostics and generated artifact bytes,
  excluding counterexample values from exact comparison. Its saved-case mechanism
  currently copies only the root input, which is insufficient for module replay.

These facts were checked by reading repository files. No compiler, runtime test,
benchmark, or proposed G4 implementation was executed during this design task.
Historical statements in `docs/G9_SPEC.md` §1.1 describe its earlier foundation;
current `SPEC.md` §6e and implementation already include G9.

### 1.2 Non-goals

No package manifest, dependency resolver, registry, versions, separate compilation,
incremental cache, automatic file discovery, conditional modules, or module initialization.
No imports, aliases, re-exports, wildcard lookup, private fields, opaque types,
representation invariants, specification functions, or new proof axioms.
No new foreign ABI, collection capability, recursive-value ABI, or ownership model.

## 2. Program files and compatibility mode

The existing CLI input denotes the root file. Outputs still represent one program.
A declaration `mod math;` in the root loads `<root-directory>/math.pruv`.
A declaration `mod detail;` in that file loads `<root-directory>/math/detail.pruv`.
In general, module path `a::b` maps only to `<root-directory>/a/b.pruv`.
The root filename does not participate in this rule; there is no `mod.pruv` fallback.

Only declared files are loaded. Declarations must be top-level and end in `;`.
Inline modules, path attributes, `pub mod`, and string-valued module paths are rejected.
Module names follow `[a-z][A-Za-z0-9_]*` and existing reserved-name restrictions.
Sibling module declarations must be unique and cannot collide with local item names.

The loader parses each file completely, then visits its children in declaration order.
Module order is root-first depth-first traversal; each file retains source item order.
Function and type lists are separately projected from that ordered item sequence.
All signatures are collected before resolving bodies, so forward references work.

Canonical file identity is checked while loading. Loading the root again, an ancestor,
or a previously loaded file through an alias is rejected; files are never merged.
Cross-module calls and type references may form cycles even though file loading is a tree.
I/O and UTF-8 failures in declared children are language diagnostics at `mod`.

A root containing `mod` or a valid top-level `pub` activates explicit visibility mode
for the whole program. Children never receive independent compatibility modes.
A root containing neither follows the existing legacy pipeline and export policy.
Adding the first `mod` deliberately changes unmarked declarations to private.
A single file may opt in with `pub`; this previously rejected syntax has no old output
to preserve. No CLI edition flag or automatic migration is introduced.

## 3. Paths and visibility

There is one cross-module reference mechanism: absolute qualified paths.
Write `crate::math::clamp(x)`; `crate` denotes the root and is not a user identifier.
Unqualified item references search only the defining module, then existing builtins.
They never search parents, siblings, or the entire program.
There is no `use`, `self::`, `super::`, relative module path, or leading `::`.

```pruv
// root.pruv
mod arithmetic;
pub fn bounded(x: i64) -> i64
  requires 0 <= x && x <= 10
  ensures result == x + 1
{ return crate::arithmetic::increment(x); }

// arithmetic.pruv
pub fn increment(x: i64) -> i64
  requires 0 <= x && x <= 10
  ensures result == x + 1
{ return x + 1; }
```

`pub` applies to ordinary `fn`, `struct`, and `enum` declarations.
An unmarked item is visible only within its defining module, including when qualified.
Parents and children receive no implicit access to one another's private items.
Module namespaces themselves are navigable throughout the program; they have no visibility.
Consequently every `pub` item has a usable absolute path from every module.

Existing local enum syntax remains `Event::Hit`.
Qualified types, constructors, patterns, and contract selectors use complete paths:
`crate::model::Event`, `crate::model::Event::Hit`, and
`is_variant(e, crate::model::Event::Hit)`.
Generic forms are `crate::math::first::<i64>(a)`,
`crate::model::Pair<i64, bool>` in types, and
`crate::model::Choice::<i64, bool>::Left(3)` in expressions.
Type arguments attach to the item, never a module segment.

All fields, variants, and payloads are transparent wherever their enclosing type is visible.
A public type's field types must themselves be public, recursively through type arguments.
Private fields and opaque types are deferred: useful abstraction would require a defined
invariant or abstract-contract mechanism, which the current language does not provide.
Hiding fields alone would remove useful caller proof facts without supplying a replacement.

Trusted Rust declarations remain module-private; `pub trusted rust fn` is rejected.
Expose them through ordinary public Pruv wrappers with explicit contracts.
Existing Rust extern configuration remains program-wide and is not a Pruv dependency system.
Builtin/catalog recognition follows local resolution: a local nominal `Vec` keeps its
existing meaning, while a qualified nominal reference never becomes a catalog type.

## 4. Entries and runtime checks

In explicit visibility mode, host entries are root `pub`, nongeneric ordinary functions.
Their signatures must satisfy existing shared Rust/LLVM export restrictions.
A root public nongeneric function with collections or extended G9 types in its
signature is rejected with `type/entry_signature`; use a scalar/value wrapper.
Child `pub` functions may use those types and remain callable from Pruv only.
Public generic functions are Pruv APIs, not host entries; expose concrete wrappers.

An optional root `main` must be `pub fn main() -> ()` with no parameters or type parameters.
Its effects follow existing rules. A child function named `main` is an ordinary item.
A library needs no `main`; native executable emission still requires the root entry.
`--rust-bindings` exposes exactly host entries, never child functions or specializations.

Verified host entries check requires unless `--trust-callers` is set.
All verified Pruv calls invoke internal bodies after static precondition proof.
Private and child-public functions need no checked wrapper in verified mode.
In `--no-verify`, every ordinary call with requires uses an internal checked wrapper,
including calls to private, child-public, and specialized functions.
`--trust-callers` skips host-boundary checks only in the new mode; it does not remove
safe-mode internal checks. Existing legacy combinations retain their old behavior.

Contract order, short-circuiting, i128 arithmetic, shared iteration budgets, panic
messages, refinement checks, and unconditional raw representation validation persist.
Foreign boundary checks remain governed by `--foreign-checks`, independently of visibility.
Runtime ensures and decreases remain erased.

## 5. Verification at module boundaries

Visibility is checked before verification and cannot be bypassed by specialization.
Every ordinary definition is verified, including private, unused, and generic definitions.
Foreign declarations retain their existing trusted status and domain checks.
No successful caller proof can compensate for a failing or unknown callee proof.

Resolve contracts in the defining module once, then instantiate resolved identities.
Caller-local names must never capture types, constructors, or selectors in callee contracts.
Public signatures, requires, ensures, and decreases may mention only public nominal
items, builtin operations, literals, bound type parameters, parameters, and permitted
logical binders/result. Check the full syntax, including unreachable short-circuit operands.
Follow nominal field/payload dependencies transitively, using a visited set for cycles.
This rule also applies to public generic declarations and unused public items.
A public function may freely use private items inside its executable body.

The call rule remains: prove requires, discharge G9 intra-SCC measure obligations,
then introduce a well-formed fresh result and assume ensures.
Function and type SCCs span all modules; module boundaries do not break recursion cycles.
Effects, ownership, refinement expansion, and generic proof-once rules are unchanged.
In explicit visibility mode, ordinary nonrecursive unit calls also assume ensures
after the same applicable obligations. This closes the existing unit-call omission;
legacy unit calls retain their exact previous behavior and SMT.

Public transparent types expose their existing datatype facts, not implementation bodies.
There is no independent module proof certificate or cached imported axiom.
Changing a body while preserving a proved contract must not supply extra facts to callers.

## 6. Rust backend and naming

Emit one flat Rust source file. Pruv modules do not become Rust compilation units.
Use a shared deterministic symbol allocator in both compiler implementations.
For a component sequence, encode its count followed by each ASCII byte length and
component, separated by `_`; lengths make underscores inside components unambiguous.
The sequence contains module components followed by the item name.
Prefix internal function stems with `pruv_m_f_` and nominal type stems with `pruv_m_t_`.
Kinds and length-delimited components prevent path and type/function collisions.

Root host entry names and root public nominal names retain their source spelling.
Other ordinary declarations use encoded stems, including root-private declarations.
Existing helper suffixes such as `__pruv_body` attach only after allocating the stem.
G3 specialization keys include full resolved declaration identity and argument identities;
their existing injective encoding and distinct `pruv_g3_` prefix remain in use.
All user components still reject `pruv_` prefixes and `__`.

Emit source-public types as public Rust types, with transparent fields and variants.
Private nominal types are private Rust items. Concrete generic types inherit their
declaration's visibility; public API closure prevents private arguments leaking.
Public Rust type emission does not grant an extended type a new host-callable ABI.
Module public types use their encoded Rust names; no alias/re-export layer is added.

Keep all nongeneric definitions as specialization roots in this release.
Roots control materialization, not export eligibility; no reachability optimization is needed.
Propagate visibility, host-entry status, source identity, and display names through mono.
Generate checked wrappers only where §4 requires them.
Diagnostics and contract panic text use source-qualified names rather than encoded stems.
Foreign manifests retain all used trusted dependencies, including private ones.

## 7. LLVM backend

Use the same declaration stems, specialization identities, ordering, and entry set.
Bodies and safe-only checked wrappers have internal linkage.
Emit `pruv_abi_<root-entry>` and existing typed ABI variants only for host entries.
Do not export a child-public function merely because Pruv callers can name it.
Bindings expose entry signatures and their transitive nominal type dependencies only.

Named LLVM types and generated clone/drop/contract helpers use resolved type identities.
Same-spelled types in different modules remain distinct throughout layout and proof.
No runtime layout, allocator marker, representation check, or foreign bridge ABI changes.
The native executable shim targets only the designated root `main` checked entry.
Existing G6 backend restrictions still apply; G4 adds no permanent LLVM subset.

## 8. Diagnostics and compatibility

Keep JSON stage/code conventions and exit statuses.
For explicit-mode programs add `file`, relative to the root directory with `/` separators,
to source diagnostics, trace locations, and inference reports.
Preserve local line/column positions; missing child diagnostics point to the declaring file.
Synthetic refinement nodes inherit their annotation's source identity.
Legacy records omit `file` and retain existing field order and output bytes.

| Stage/code | Meaning |
|---|---|
| `parse/module_syntax` | Invalid module declaration or module name shape |
| `parse/visibility_syntax` | Misplaced/unsupported visibility, including public foreign declarations |
| `parse/path_syntax` | Malformed qualified path |
| `parse/module_file` | Declared child absent, unreadable, or invalid UTF-8 |
| `parse/module_alias` | Canonical file loaded more than once |
| `type/duplicate_module` | Repeated sibling module declaration |
| `type/unknown_module` | Missing module segment in a qualified reference |
| `type/private_item` | Reference to another module's private item |
| `type/public_interface` | Private nominal dependency in a public interface |
| `type/entry_signature` | Unsupported signature of a requested host entry |
| `type/entry_main` | Invalid explicit-mode root main |

Reuse `reserved_name`, `dup_fn`, `dup_type`, `name_collision`, `unknown_fn`,
`unknown_type`, generic errors, and existing effect/proof codes where applicable.
After loading: check declaration collisions, resolve references/access, validate public
interfaces and entry eligibility, then run remaining existing checks and verification.
Within each phase use deterministic declaration and expression traversal order.
Errors name source paths and suggest the relevant declaration/path correction.

Legacy successful programs must preserve AST/check dumps, SMT, Rust, IR, bindings,
foreign manifests, diagnostics, and ordering byte-for-byte.
Existing invalid identifier uses of `mod`, `pub`, and `crate` keep `reserved_name`;
recognize new syntax contextually rather than changing all keyword diagnostics.
No blanket snapshot regeneration is an acceptable compatibility explanation.

## 9. Shared batch gates and paths

Abbreviations: P = `pruvc/`; C = `pruvc-rs/crates/pruv-core/src/`;
V = `pruvc-rs/crates/pruv-proof/src/`; D = `pruvc-rs/crates/pruvc/src/`.
Implementation paths below are planned edits.
New files are explicitly marked “new”; fixture directory patterns specify new test files.

Every batch finishes Python implementation, Rust port, and applicable byte comparisons:
parse/check dumps, normalized SMT traces, diagnostics, Rust, IR, and bindings.
Require strict `same` for deterministic G4 proof fixtures; unknown is not a passing proof.
The existing counterexample-value exception remains; it is not full diagnostic-byte equality.
Capture the pre-G4 legacy artifacts before implementation and compare at every exit.
Run complete `run_all` rows for both compilers/backends and applicable `tests/m3_all.py`
checks; proof/emission changes also require existing benchmark and mutation regression gates.

Add a test-only `tests/g4/fixtures.json` root inventory and `tests/g4/projects.py` helper.
Use project directories with `root.pruv`; companion modules are not standalone test roots.
Runtime projects include `root.json` and `root.rs`; rejection projects include expected JSON.
Extend discovery and replay to preserve each project's relative tree and root basename.
Do not make the test inventory a language/package manifest.
All staged guards are `codegen/unsupported_type` and must disappear by A3.
Generate all requested artifacts before writing any; failures produce no partial new output.

## 10. A0 — loading, resolution, and visibility (binding)

1. Add the fixed-rule loader, ordered module tree, source identities, and mode selection.
   Preserve `parse(src)` as a file-local API; file-taking drivers/adapters use the loader.
   Every node retains its originating file through a stable source-map association.
2. Add contextual syntax, absolute paths in every item-reference position, local name
   tables, access checks, public-interface closure, and explicit entry classification.
   Keep source spelling separate from resolved identity and eventual backend symbols.
3. Resolve complete declaration identities before G3 owner binding and G9 graph creation.
   Validate source naming rules before internal identities replace lookup keys.
   Guard explicit-mode verification/emission until A1; frontend dump adapters remain usable.
4. Files: P/`modules.py` (new), `vast.py`, `vparser.py`, `check.py`, `typeinfo.py`,
   `refine.py`, `pruvc.py`; C/`modules.rs` (new), `ast.rs`, `lexer.rs`, `parser.rs`,
   `check.rs`, `gtype.rs`, `typeinfo.rs`, `refine.rs`, `diagnostic.rs`, `dump.rs`,
   `lib.rs`; D/`driver.rs`; `tests/diff_py_adapter.py`, `tests/diff_parse.py`,
   `tests/diff_compilers.py`, `tests/run_all.py`, `tests/run_all_rows.txt`,
   C/`bin/pruv-parse-dump.rs`, `bin/pruv-check-dump.rs`, and the new §9 helpers.
5. Add 12 frontend projects under `tests/g4/frontend/` and 12 rejection projects under
   `tests/must_reject/g4_*/`: nested files, missing child, duplicate modules, aliases,
   sibling privacy, private root access, public type leakage, generic paths, qualified
   patterns/selectors, local catalog shadowing, and legacy reserved-name preservation.
   Exit: frontend dumps and guard diagnostics match; source locations and saved replay
   work after relocation; legacy artifact gates pass.

## 11. A1 — proof and specialization identity (binding)

1. Implement §5 over the resolved whole program, including unit ensures in explicit mode.
   Prove every definition before specialization; private helpers remain proof obligations.
   Preserve defining-module bindings during contract substitution and inference.
2. Make specialization keys, abstract parameter owners, SCCs, and SMT datatype identities
   module-aware. Retain all nongeneric roots, existing resource limits, and stable ordering.
   Move the staging guard after proof; do not enable code generation yet.
3. Files: P/`modules.py`, `verify.py`, `infer.py`, `mono.py`, `typeinfo.py`, `pruvc.py`;
   C/`modules.rs`, `mono.rs`, `gtype.rs`, `typeinfo.rs`; V/`lib.rs`, `model.rs`,
   `symbolic.rs`, `obligation.rs`, `infer.rs`, `bin/pruv-trace-dump.rs`;
   D/`driver.rs`; `tests/diff_py_adapter.py`, `tests/diff_trace.py`,
   `tests/smt_snapshot.py`, `tests/run_all.py`, `tests/run_all_rows.txt`,
   and `tests/g4/fixtures.json`.
4. Add ten `tests/g4/proof/` projects and ten `tests/must_reject/g4_*` projects:
   same-spelled nominal types, cross-file generic calls, recursive function/type SCCs,
   public unit postconditions, false private ensures, missing call preconditions,
   unchanged recursive measures, hidden interface dependencies, and caller-name capture.
   Include two proved callee bodies with identical contracts; caller obligations must agree.
   Exit: G4 traces are strictly `same`, legacy SMT is unchanged, all proof/regression gates pass.

## 12. A2 — Rust generation and runtime boundaries (binding)

1. Implement shared encoding, concrete visibility propagation, flat Rust generation,
   and §4 wrapper routing. Do not derive host eligibility from specialization roots.
   Generate no private checked wrappers in verified mode; retain safe-mode wrappers.
2. Preserve source-qualified names in runtime failures and trusted-dependency manifests.
   Keep LLVM explicitly guarded after successful proof.
3. Files: P/`modules.py`, `mono.py`, `codegen.py`, `foreign_codegen.py`,
   `foreign_shim.py`, `pruvc.py`; C/`modules.rs`, `mono.rs`, `codegen.rs`,
   `emit_common.rs`, `foreign_codegen.rs`, `foreign_shim.rs`;
   D/`driver.rs`; C/`bin/pruv-rust-dump.rs`; `tests/diff_rust.py`,
   `tests/run_all.py`, `tests/run_all_rows.txt`, `tests/llvm_pending.txt`,
   `tests/g4/fixtures.json`.
4. Add ten `tests/runtime/g4_*/` projects and two `examples/g4_*/` projects.
   Cover rejected host inputs, safe private-call failures, trust/safe combinations,
   module type construction, generic wrappers, repeated leaf names, nested underscore
   names, foreign wrappers, and cross-file recursion with scalar entry signatures.
   Inspect emitted visibility and wrapper absence as well as runtime outcomes.
   Exit: Rust sources match byte-for-byte; both compilers execute all new Rust cases;
   LLVM guards match, and shared compatibility/benchmark gates pass.

## 13. A3 — LLVM, bindings, native entry, and documentation (binding)

1. Implement §7 with exactly the Rust entry set and wrapper policy.
   Compare symbol inventories against explicit expectations, not only compiler parity.
   Preserve ABI representation validation under both verification and trust modes.
2. Update native main selection, finish project-aware differential discovery, and remove
   every G4-only staging/pending row. Document one-page user rules in SPEC.
3. Files: P/`llvmgen.py`, `pruvc.py`; C/`llvmgen.rs`, `abi.rs`, `bindings.rs`,
   `emit_common.rs`, `bin/pruv-llvm-dump.rs`; D/`driver.rs`;
   `tests/diff_llvm.py`, `tests/diff_compilers.py`, `tests/run_all.py`,
   `tests/run_all_rows.txt`, `tests/llvm_pending.txt`, `tests/g4/projects.py`,
   `tests/g4/fixtures.json`, `SPEC.md`, `BLUEPRINT.md`, `RESULTS.md`.
4. Run all A2 runtime projects on LLVM; add four projects for entry type closure,
   raw bool/string validation, same-spelled type layouts, and root/child main distinction.
   Add a nested backend-component example with public contracts and private helpers.
   Test Rust native executable emission separately where supported.
   Exit: IR/bindings are byte-identical, exported symbols contain only entries,
   runtime cases pass in both backends, no G4 guard remains, and full shared gates pass.
   Record actual host execution separately from cross-target emission.
   Complete one independent audit and confirmation after fixes before release.

## 14. Q — bounded stress and independent use (binding)

1. Files: `bench/fuzz/generate.py`, `oracle.py`, `run.py`, `README.md`;
   `bench/g4/run.py`, `mutate_ops.py`, `PROBLEMS.md`, `README.md` (all new),
   `bench/g4/solutions/`, `bench/g4/results/` (new), and `RESULTS.md`.
2. Generate 30 bounded programs per seed 41, 56, and 57, each with 2–5 modules and
   eight concrete inputs. Use an independent value oracle and vary private/public
   helpers, repeated names, generic paths, and contract-preserving body replacements.
   Require agreement across both compilers, both backends, and verified/safe execution.
3. Classify at least 20 incorrect source mutants and four compiler fault injections:
   privacy bypass, leaf-name identity collision, dropped entry checks, and missing
   cross-module recursive obligations. Tests must catch every injected fault.
   Timeouts, unknowns, crashes, unsupported paths, and weak contracts are separate
   outcomes, not successful semantic rejections.
4. Give an independent author SPEC and two fresh problems: a bounded array service split
   into modules, and a recursive tree service exposing scalar host wrappers.
   Record first attempts and revisions; require both final solutions to verify and run.
   Exit: no incorrect mutant verifies, no unexplained mismatch remains, all shared gates
   pass, and existing mutation/benchmark results do not regress.
   Measure a deterministic 100-module fixture's compile/proof time without claiming
   incremental behavior; investigate repeatable legacy latency increases above 10%.

## 15. Deferred work and evidence limits

G4b owns packages, external Pruv dependencies, package identities, and separate compilation.
Imports/re-exports, private module namespaces, opaque values, representation invariants,
private fields, specification helpers, and richer host type naming remain deferred.
Reachability pruning, incremental proof reuse, and build orchestration are unnecessary
for this first whole-program release.

The design fixes behavior and implementation gates; feasibility and performance are
unmeasured until implementation. In particular, cross-module recursive proofs retain
existing solver and resource limitations.
