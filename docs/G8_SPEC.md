# G8: A Verified Standard Module Written in Pruv

Status: **First-slice design, 2026-11-13; implementation and proof gates pending.**

This document fixes batches A0–A3 and Q. Requirements below describe future
implementation, not completed verification. This design task only reads sources
and creates this document; it runs no compiler, build, test, or benchmark.

## 1. Goal

Ship one ordinary Pruv module, `std`, containing twelve precisely contracted
integer and array helpers. The compiler proves their bodies with the same
verifier used for application code. Applications use only their contracts in
proofs. This starts BLUEPRINT.md §4's G8 row and progress item 8: replace selected
borrowed Rust functionality with Pruv implementations, starting with high proof
value. It does not replace the whole G6 catalog.

Humans review the public contracts in §4; implementation authors supply bodies
and loop invariants. The review covers the exact result, failure conditions,
effects, and preconditions, rather than merely a loose range guarantee. Compiler
and solver correctness remain in the trust base.

### 1.1 Verified repository facts

The following implementation facts were checked by reading the named functions.
The historical status lines in G4/G5 design documents do not describe the current
implementation; SPEC.md §§6c–6g and these sources are the relevant foundation.

| Fact | Source actually read |
|---|---|
| Loading currently reads ordinary declared module files relative to the root, in root-first depth-first order; a root without `mod`/`pub` keeps the legacy path. There is no bundled-standard-module branch in this loader. | `pruvc/modules.py`, `load_program` and its nested `visit`; `pruvc-rs/crates/pruv-core/src/modules.rs`, `load_program` and the opening of `load_source` |
| Module resolution gives declarations absolute identities, rejects builtin/catalog function-name collisions, checks visibility, and checks interfaces before entries. | `pruvc/modules.py`, `_Resolver.run`, `_Resolver.ident`, `_Resolver.walk`, `_Resolver.access` |
| The Python driver loads, checks, conditionally verifies, then specializes explicit-mode programs before emission. The Rust driver likewise loads/checks before optional verification. | `pruvc/pruvc.py`, `compile_file`; `pruvc-rs/crates/pruvc/src/driver.rs`, `compile` |
| The normal verifier visits every function, including unused functions; the inference path also visits every definition. | `pruvc/verify.py`, `verify_program` |
| Ordinary calls prove callee requires, introduce a fresh result, and assume instantiated ensures; this path does not inspect the callee body. | `pruvc/verify.py`, `FnVerifier.call` |
| Quantifiers use bounded integer ranges. Aggregates have empty-range and one-step unfolding facts, not a general induction engine. | `pruvc/verify.py`, `FnVerifier.ev`, `FnVerifier.aggregate` |
| Contract definedness guards Option payload access and array indexing and follows short-circuit implication/conjunction. | `pruvc/verify.py`, `FnVerifier.dom` |
| Abstract type parameters cannot use executable equality or arithmetic/order; ordinary functions cannot be called in contracts. | `pruvc/check.py`, `Checker.expect`, `Checker._expr`, `Checker.call` |
| G6 operations are compiler-created pseudo-declarations; the fixed catalog includes Vec, HashMap and String operations. | `pruvc/foreign.py`, `_add` and its adjacent catalog registrations; `pruvc/verify.py`, `FnVerifier.call` catalog dispatch |
| Rust generation treats child functions as internal and emits checked internal calls in safe mode. LLVM host ABI eligibility excludes non-entry children. | `pruvc/codegen.py`, `Gen.fn`; `pruvc/llvmgen.py`, `is_host_abi_fn` |
| Module symbol stems encode complete components with lengths, rather than just leaf names. | `pruvc/modules.py`, `encode_name`, `encode_stem` |
| A repository example delegates scalar min/max to trusted Rust and builds clamp from them; it is a concrete replacement opportunity. | `examples/g6_min_clamp.pruv`, `rust_min`, `rust_max`, `clamp` |
| An existing reversal example states a pointwise reversal contract with explicit quantified invariants, using inout; an aggregate-max example uses `max(k in ...)`. These are source precedents, not test results from this task. | `examples/g5_reverse.pruv`, `reverse`, `reversed`; `tests/inference/inf_max.pruv`, `max_of` |

Language constraints additionally come from the whole SPEC.md: §§2–6 for i64,
Option, mathematical contract arithmetic and aggregates; §6c for generics; §6f
for module boundaries; §7 for array length limits and runtime contract budgets;
§6j for optional cost clauses. G4_SPEC §§2–8, G6_SPEC §§4 and 10–13, and
G5_SPEC's goal/rules/backend/batch structure inform this design. No measured
claim of solver success, runtime behavior, or compiler parity is made here.

### 1.2 Non-goals

- Verified replacements for G6 Vec and HashMap collections are deferred.
- Verified strings and replacement of G6 String operations are deferred.
- Verified I/O and replacement of G10 file operations are deferred.
- A package manager, registry, dependency manifest, and version selection are deferred.
- No new arithmetic types, casts, traits, specification functions, proof axioms,
  trusted helpers, caching, proof certificates, separate compilation, or ABI.
- No new mutation/ownership rules, automatic contract inference, automatic
  prelude, aliases, or alternate import spelling.
- No cost annotations in this slice: a function with a Stage 5 `cost` clause
  cannot call these helpers until they receive proved cost contracts. Do not
  weaken `effect/cost_callee` to accommodate std.

## 2. User surface and loading

There is one import form, at the program root:

```pruv
mod std;

pub fn bounded(x: i64) -> i64
  ensures 0 <= result && result <= 100
{
  return crate::std::clamp_i64(x, 0, 100);
}
```

`mod std;` activates normal G4 explicit visibility for the whole program. A root
main, when present, must therefore be public. Every module calls a standard
function through `crate::std::<name>`; there is no `use`, bare `std::`, implicit
import, or unqualified fallback. A caller's own `min_i64` remains its own local
function. Standard signatures are not installed in the G6 catalog.

The only loading extension is that the root declaration `mod std;` selects the
compiler's bundled UTF-8 source instead of `<root-directory>/std.pruv`. All
parsing, name resolution, visibility, checking, proof, and generation thereafter
use the ordinary G4 module pipeline. Without the declaration, std is not loaded,
proved, or emitted. Repeated root declarations use `type/duplicate_module`.

Reserve `std` as a module name for this purpose: `mod std;` in a child is rejected
with `parse/std_import_location`, directing the author to the root. A local
root-side `std.pruv` present alongside `mod std;` is `parse/std_module_conflict`,
even if identical to the bundle; never silently choose one. Presence includes a
directory or dangling symlink at that pathname. Existing user modules named std
must be renamed. This is an explicit compatibility change; other user module
names and legacy identifiers named std retain their current rules. Ordinary
module/item collisions still use G4 diagnostics.

The implementation adds one canonical repository source, `stdlib/std.pruv`
(new). Python loads that resource relative to its installed compiler package,
never relative to the application's working directory or an environment search
path. The Rust compiler embeds those same source bytes at build time and feeds
them to the same file-local parser as an ordinary child. Packaging must include
the resource for Python and include it in the Rust compiler build inputs. There
is no command-line override or fallback to a user file. This is distribution of
source, not a preverified native library or cached proof.

Assign the logical source identity `@std/std.pruv` in diagnostics and traces;
this is a bundled-resource label, not a path relative to the user's root. Source
line/column and declaration identity `crate::std::name` survive resolution and
specialization. Insert the module in the root declaration's normal traversal
position. Physical installation paths must not leak into deterministic artifacts.

The bundle contains exactly the twelve public functions below, with ordinary
bodies, explicit invariants, no foreign declarations, no submodules, no G6 calls,
and no references to application modules. Keep implementations self-contained;
no private helper API is necessary for this slice. This layout is checked by
implementation fixtures, not by a new user-visible language restriction.

## 3. Review surface

§4 is the contracts-only public listing for this slice. The bodies in
`stdlib/std.pruv` must carry exactly these signatures and ordered clauses. The
implementation fixtures compare their parsed headers with the approved public
surface; body changes cannot silently weaken contracts or add effects.

A new general CLI contracts printer is deferred. Producing a stable source-like
listing from resolved/generic ASTs would add formatting and driver scope that
this first module does not need. Do not use the foreign-dependency manifest as
a substitute: these are verified Pruv functions, not trusted declarations.

## 4. Standard signatures and contracts

These are declaration headers for review, not standalone compilable declarations;
the implementation appends ordinary Pruv bodies. No implicit requires, hidden
postcondition, or runtime intrinsic supplements the text. All functions are
monomorphic i64 functions; only `reverse_i64` has an effect. Empty-array behavior
is fixed by the formulas, including true sortedness and an empty reverse.

```pruv
pub fn min_i64(a: i64, b: i64) -> i64
  ensures result <= a && result <= b
  ensures result == a || result == b

pub fn max_i64(a: i64, b: i64) -> i64
  ensures result >= a && result >= b
  ensures result == a || result == b

pub fn clamp_i64(x: i64, lo: i64, hi: i64) -> i64
  requires lo <= hi
  ensures lo <= result && result <= hi
  ensures x < lo ==> result == lo
  ensures x > hi ==> result == hi
  ensures lo <= x && x <= hi ==> result == x

pub fn abs_i64(x: i64) -> i64
  requires x > -9223372036854775808
  ensures result >= 0
  ensures x >= 0 ==> result == x
  ensures x < 0 ==> result == -x

pub fn checked_add_i64(a: i64, b: i64) -> Option<i64>
  ensures is_some(result) == (-9223372036854775808 <= a + b && a + b <= 9223372036854775807)
  ensures is_some(result) ==> some_val(result) == a + b

pub fn checked_sub_i64(a: i64, b: i64) -> Option<i64>
  ensures is_some(result) == (-9223372036854775808 <= a - b && a - b <= 9223372036854775807)
  ensures is_some(result) ==> some_val(result) == a - b

pub fn sum_i64(a: [i64]) -> i64
  requires len(a) <= 1_000_000
  requires forall k in 0..len(a): -1_000_000_000 <= a[k] && a[k] <= 1_000_000_000
  ensures result == sum(k in 0..len(a): a[k])

pub fn contains_i64(a: [i64], x: i64) -> bool
  ensures result == (exists k in 0..len(a): a[k] == x)

pub fn index_of_i64(a: [i64], x: i64) -> Option<i64>
  ensures is_some(result) == (exists k in 0..len(a): a[k] == x)
  ensures is_some(result) ==> (0 <= some_val(result) && some_val(result) < len(a))
  ensures is_some(result) ==> a[some_val(result)] == x
  ensures is_some(result) ==> (forall k in 0..some_val(result): a[k] != x)

pub fn is_sorted_i64(a: [i64]) -> bool
  ensures result == (forall k in 1..len(a): a[k - 1] <= a[k])

pub fn array_max_i64(a: [i64]) -> i64
  requires len(a) > 0
  ensures result == max(k in 0..len(a): a[k])

pub fn reverse_i64(a: [i64]) -> [i64] ! alloc
  ensures len(result) == len(a)
  ensures forall k in 0..len(a): result[k] == a[len(a) - 1 - k]
```

`sum_i64` deliberately has a simple sufficient overflow-excluding precondition:
every prefix magnitude is at most `1_000_000_000 * len(a)`, hence at most 10^15.
It rejects some mathematically safe inputs. Merely bounding the final sum would
be unsound for a left-to-right accumulation with overflowing intermediate sums.
An exact all-prefix precondition is deferred to avoid nested aggregate cost and
proof complexity in the initial API.

`index_of_i64` returns None exactly when absent, and Some of the first matching
index when present. The ordered range clause guards the later indexing clause.
`is_sorted_i64` means nondecreasing adjacent elements, including duplicates.
Its contract does not automatically furnish a quantified all-pairs theorem.
`array_max_i64` rejects an empty input rather than inventing a sentinel.
`reverse_i64` returns an independently owned array without changing the input.

Generic arithmetic, ordering, and runtime equality are excluded by G3. A generic
reverse would be expressible with `T: Element`, but is deliberately deferred so
this first surface has one monomorphic spelling per operation. No extra bound
or inference rule is introduced. Standard function calls remain illegal in
contracts: write the quantified property, not `requires crate::std::is_sorted_i64(a)`.

## 5. Verification rules and implementation witnesses

1. On every verified compilation importing std, parse/check the bundle with the
   user modules and verify every bundled definition, including unused ones.
   Do this before specialization or emission. There is no once-per-install
   trust, cache, certificate, or body exemption. A failed or unknown std proof
   fails the entire compilation even if all user obligations succeed.
2. A std call uses the ordinary G4 call rule: prove requires on actual arguments,
   then assume ensures about a fresh result. Never add standard-name axioms,
   unfold a body in a caller proof, or recognize a function name as an SMT
   builtin. Array results use existing freshness and ownership semantics.
3. Verify contract domains, arithmetic, indexing, allocation bounds, invariants,
   and termination normally. Guard payloads and indexed results in the clause
   order in §4. Mathematical arithmetic in contracts is not executable wide
   arithmetic. Inference may be enabled, but the shipped bodies must verify
   with inference disabled using explicit invariants.
4. `--no-verify` skips SMT for both the application and std and claims no proof.
   Parsing/checking and all safe arithmetic/index/precondition checks remain.
   A syntactically broken bundle still fails; a false ensures is not dynamically
   checked in safe mode. `--trust-callers` does not skip safe internal std
   precondition checks. `--foreign-checks` does not control these Pruv functions.
5. Broken bundle syntax/type/proof errors retain the ordinary stage/code and
   point to `@std/std.pruv`. Unknown is `verify/verify_unknown`, never success.
   A missing/unreadable/invalid-UTF-8 Python resource uses §8's loading error at
   the root import. An invalid embedded Rust source fails when imported too.

The following witnesses constrain implementation without fixing body formatting:

| Functions | Ordinary implementation and proof facts |
|---|---|
| min, max, clamp | Branch on comparisons; return an input or bound. No arithmetic or foreign call is needed. |
| abs | Branch on `x < 0`; negate only under the precondition excluding i64 minimum. |
| checked add | If `b > 0`, reject `a > 9223372036854775807 - b`; if `b < 0`, reject `a < -9223372036854775808 - b`; otherwise return Some(a + b). Compute the sum only after the guards. |
| checked sub | If `b > 0`, reject `a < -9223372036854775808 + b`; if `b < 0`, reject `a > 9223372036854775807 + b`; otherwise return Some(a - b). Never implement this as addition of `-b`. |
| sum | Forward loop with `0 <= i && i <= len(a)`, `s == sum(k in 0..i: a[k])`, and `-1_000_000_000 * i <= s && s <= 1_000_000_000 * i`; decrease `len(a) - i`. |
| contains, index_of | Forward scan, returning at the first equality; maintain `forall k in 0..i: a[k] != x`, index bounds, and decrease `len(a) - i`. Exit establishes absence. |
| is_sorted | Return true immediately for length below 2, then scan from i = 1; maintain `1 <= i && i <= len(a)` and `forall k in 1..i: a[k - 1] <= a[k]`. An inversion is a witness for false; decrease `len(a) - i`. |
| array_max | Start from a[0], scan from i = 1; maintain `1 <= i && i <= len(a)` and `m == max(k in 0..i: a[k])`; decrease `len(a) - i`. |
| reverse | Allocate `alloc(len(a), 0)`, fill forward from i = 0, maintain result length, `0 <= i && i <= len(a)`, and `forall k in 0..i: out[k] == a[len(a) - 1 - k]`; decrease `len(a) - i`. The source index is evaluated only inside the loop. |

These witnesses use current language constructs. Actual solver acceptance and
trace parity are A1 gates, not established by this design. If a witness needs
additional invariants, supply them without changing the public contract or
adding trusted lemmas. An unresolved proof blocks the batch.

## 6. Rust backend

Emit the bundled functions through ordinary G4 symbol allocation and body
generation in the application's output. No Rust standard-library function
substitutes for a Pruv body. Std functions are child-public Pruv APIs, never
host exports or direct binding entries; users write root public wrappers.

Use existing i64, Option, borrowed array parameters and owned array results.
Reverse allocates one result array; reads do not acquire ownership or copy the
input. All twelve nongeneric definitions may be emitted, including unused ones;
reachability pruning is unnecessary. Verified internal calls use proved bodies;
safe calls retain internal requires checks, including under `--trust-callers`.
Ordinary ensures remain erased. The bounded sum precondition uses the existing
contract iteration budget; budget exhaustion remains a resource failure, not
permission to assume a precondition. No G6 foreign dependency is introduced.

## 7. LLVM backend

Emit the same ordinary function bodies, identities and order through LLVM.
Use existing Option and array representations, allocation, ownership cleanup,
checked arithmetic and contract evaluation. No std-specific C or Rust shim,
runtime symbol, ABI version, or foreign target restriction is introduced.

Std functions and safe internal wrappers have internal linkage; exported ABI
symbols and generated Rust bindings contain only eligible root entries.
Exercise reverse results through such a wrapper, including ownership transfer
and freeing. Check optimized execution as well as IR/binding equality.

## 8. Diagnostics and compatibility

New codes, with exact names:

| Stage/code | Trigger and required repair |
|---|---|
| `parse/std_import_location` | A child declares `mod std;`. Point to that declaration; move the single declaration to the root and call `crate::std::name`. |
| `parse/std_module_conflict` | The root declares std and a local `std.pruv` path exists. Point to the declaration; rename the user module/file and its paths. Never load either candidate silently. |
| `parse/std_source` | Bundled resource cannot be read or decoded. Point to the root declaration; restore/reinstall the matching compiler resource. Do not suggest creating an application std.pruv. |

Use ordinary parse/type errors for malformed bundle content, and ordinary
`call_requires`, `ensures`, `contract_domain`, `overflow`, `index_oob`, invariant,
termination and unknown diagnostics for proof obligations. There is no umbrella
`std_proof_failed` that discards the offending obligation or counterexample.
Wrong function spelling uses existing unknown-function resolution; absent import
uses G4 unknown-module resolution. Catalog-name conflicts retain `type/reserved`.

At an import, reject invalid location first, then a local conflict, then resource
loading/decoding; ordinary duplicate declaration handling remains deterministic.
After loading, retain normal G4 checking and verification order. Include the
stable logical file label for bundle diagnostics and preserve root-relative
labels elsewhere. No physical path, cache identifier, or nondeterministic field.

Preserve G8-free artifacts byte-for-byte except for the explicitly reserved
module-name cases above. Capture compatibility baselines before implementation.
No blanket snapshot regeneration. Staging guards use existing
`codegen/unsupported_type` and disappear by A3. Generate requested artifacts
successfully before writing new output; a failed std proof produces none.

## 9. Shared batch gates

All paths below are proposed implementation work, not edits made by this task.
Each batch implements Python behavior, then Rust parity, before the next batch.
Maintain a new test-only `tests/g8/fixtures.json` inventory of source roots;
reuse G4 project handling for companion files. The bundle is a resource, not a
user companion file. Replay records the compiler/bundle revision used.

Require deterministic parse/check dumps, diagnostics, applicable proof traces,
Rust, LLVM IR and bindings to agree across compilers. Keep the existing exception
for counterexample values explicit; compare all other diagnostic fields and
counterexample presence. Unknown, timeout, crash, unsupported, and missing rows
never count as successful proofs. Agreement alone is not a semantic oracle.

During implementation run relevant targeted groups; at the release/commit gate
run the repository-required broader checks under AGENTS.md. Relevant harnesses
are `tests/run_all.py`, `tests/diff_compilers.py`, `tests/diff_llvm.py`, and
parse/check/trace adapters. This document does not authorize their execution
during the present design-only task. Fuzzing, mutants and performance belong to Q.

Minimum distinct new source-root fixtures (not backend rows or bundled files):

| Batch | Frontend | Positive proof | Rejection | Runtime | Examples |
|---|---:|---:|---:|---:|---:|
| A0 | 6 | 0 | 8 | 0 | 0 |
| A1 | 0 | 14 | 12 | 0 | 0 |
| A2 | 0 | 0 | 0 | 12 | 2 |
| A3 | 0 | 0 | 0 | 4 | 1 |
| Q | 0 | 0 | 4 | 2 | 1 |

## 10. A0 — frontend and loading

1. Add canonical `stdlib/std.pruv`, packaging/embedding of identical source
   bytes, root-only loading, logical file identity and conflict diagnostics.
   Implement through `pruvc/modules.py` and
   `pruvc-rs/crates/pruv-core/src/modules.rs`; adjust their drivers/resource
   packaging as needed. No alternate resolver or new AST expression is needed.
2. Parse and check the twelve public headers and ordinary implementations.
   Check the public-surface fixture against §4. The bundled module contains no
   trusted declarations/catalog calls; frontend fixtures enforce this inventory.
3. Six positive roots cover the import alone, calls from root and child,
   same-spelled local helpers, G6 coexistence, and explicit main/host wrappers.
   Eight negative roots cover nested import, duplicate import, local resource
   conflict, missing and malformed resource, absent import, unknown std item,
   and module/item collision. Include symlink conflict and invalid UTF-8 as
   additional metadata variants. Use disposable test resources, not a developer's
   installed bundle, for corruption cases.
4. Check both compiler distributions from a working directory unrelated to the
   root or compiler location. Verify that their packaged bytes agree.
5. Exit: matching frontend artifacts/errors, no extra user file required,
   compatibility preserved outside the documented std-name migration. Until A1,
   guard std verification/emission after checking; no staged path may emit code.

## 11. A1 — verification

1. Add explicit invariants to the ordinary source bodies and integrate the whole
   bundle into normal verification. No standard-name assumptions or trusted
   implementations. Change the verifier only if a demonstrated general bug
   requires a separately reviewed correction; do not add a G8 proof oracle.
2. Fourteen positive proof roots: one contract-use client per function, a client
   composing several calls, and a cross-module client. Verify with inference
   disabled; additionally check infer-enabled parity on representative scans.
3. Twelve rejection roots include invalid clamp bounds, abs of i64 minimum,
   both sum precondition failures, empty array max, unchecked Option payload,
   an incorrect first-index claim, missing membership, false sortedness,
   wrong reverse element, std function called in a contract, and an unused
   bundled function with a false postcondition. Record exact expected codes.
4. Prove two alternative bodies with identical headers and compare the caller's
   normalized obligations/facts: no extra fact may leak from either body.
   Check std failure on every fresh compile, including after a prior success;
   no persistent success state may bypass verification.
5. Exercise empty/singleton arrays, duplicate matches, all-negative maxima,
   i64 extrema and exact checked-add/sub overflow boundaries. Ensure None is
   proved exactly on overflow, not just allowed as an arbitrary answer.
6. Exit: all twelve bodies and clients proved in both implementations, strict
   deterministic trace agreement, recorded negative obligations rejected.
   Move the staging guard after proof; emission remains guarded until A2.

## 12. A2 — Rust backend

1. Route std through ordinary emission/specialization. Planned touchpoints are
   `pruvc/codegen.py`, `pruvc/mono.py`, the Rust core equivalents, and drivers;
   change them only where loading metadata requires it. Reuse existing symbols,
   internal wrappers, effects and ownership.
2. Twelve runtime roots cover every function with independent expected values.
   Run verified and safe modes; include safe-plus-trust internal-precondition
   failures. Test MIN/MAX arithmetic pairs, invalid abs/clamp/sum/max inputs,
   duplicates, unsorted arrays and empty arrays. Check Option tags and payloads,
   and exact reverse contents plus unchanged input.
3. Add two examples: replace the trusted min/max clamp example with std calls,
   and use first-index plus checked arithmetic in a small array client.
4. Inspect generated Rust for ordinary Pruv bodies, no trusted min/max path,
   no std host exports, one reverse result allocation, and correct safe checks.
5. Exit: matching generated bytes and expected runtime results/failures. LLVM
   remains guarded, including combined-output requests; failures leave no new
   partial Rust output.

## 13. A3 — LLVM and SPEC user page

1. Lower through `pruvc/llvmgen.py` and Rust core LLVM/binding paths using the
   existing ABI and runtime. Run every A2 runtime root on LLVM as well.
2. Four additional runtime roots cover root-wrapper Option ABI, reverse result
   ownership/freeing, calls from multiple user modules with repeated leaf names,
   and optimized safe internal checks under `--trust-callers`.
3. Inspect symbol lists, internal linkage, bounds/overflow checks in safe mode,
   absence of foreign shims, and IR/binding equality. Inspect LLVM execution
   independently of Rust emission agreement.
4. Add one module-client example. Update SPEC.md with a one-page std section:
   the single import, qualification, contracts, sum bounds, error behavior,
   per-compile proof, safe mode, host wrappers, and std-name migration. Update
   BLUEPRINT.md and RESULTS.md only with measured implementation evidence.
5. Exit: both backends and compilers meet all preceding gates; no G8 staging
   guard/pending row remains. Document resource packaging and verify it using
   installed/relocated compiler fixtures. Conduct one independent correctness
   review of loading, proof boundaries, and emitted ownership/check behavior;
   fix findings and check the affected groups.

## 14. Q — fuzz, mutants, independent use, and measurement

1. Add a G8 mode to the fuzz harness and `bench/g8/` (new) for an independent
   value oracle, mutation cases, problems, measurements and saved results.
   Generate 30 successful verified client roots per seed 41, 56 and 57, with
   eight concrete inputs each. Use an arbitrary-precision oracle for arithmetic
   and direct array computations; never derive expected results from SMT or
   emitted code. Deliberately include boundary inputs outside random sampling.
2. Compare two compilers × two backends × verified/safe execution for all cases:
   at least 5,760 completed comparisons. Cover all twelve functions and cross-
   module compositions. Record rejected/unknown/unsupported cases and shortfalls
   separately; save compiler/bundle identity, sources, inputs and replay commands.
3. Classify at least 36 incorrect source mutants retaining the approved
   contracts: flipped comparisons, wrong overflow boundaries, premature sum
   return, skipped match, last instead of first index, wrong sortedness result,
   incorrect maximum and reversal index. Require zero incorrectly verified
   mutants. Weak-contract and equivalent mutants are separate categories.
4. Execute four compiler fault injections in disposable checkouts: skip unused
   std verification, treat std contracts as trusted without proving bodies,
   load a local std file despite the conflict, and drop safe internal requires
   checks under trust-callers. Record each actual patch and detecting test;
   proposed fault names alone are not evidence.
5. Give an independent author only the updated SPEC and two fresh problems:
   an array search service requiring the first duplicate index and checked
   arithmetic, and an array summary/reversal service using the bounded sum and
   non-empty maximum. Record attempts, diagnostics, revisions and assistance;
   final programs must prove and execute correctly on both backends.
6. Measure fresh-process compile/proof time for matched clients with and without
   std, including an import with no calls. This measures the deliberate cost of
   reproving the whole bundle. Separately compare std calls with equivalent
   local Pruv implementations for bounded sum and reverse on deterministic
   million-element inputs. Use identical optimization, consume/check outputs,
   separate host contract checking from body timing, and record at least ten
   repetitions, medians/spread, versions, target and flags. Report code size,
   allocations/copied bytes where measurable, and unexplained regressions.
   There is no invented speedup requirement and no cache claim.
7. Promote four rejection roots, two runtime roots and one example from distinct
   useful findings. Exit: counts met, every injected fault detected, no incorrect
   mutant accepted, independent tasks complete, measurements recorded, and no
   unexplained compiler/backend mismatch or compatibility regression.

## 15. Deferred work and open evidence

- `checked_mul_i64`: the exact Option contract is expressible with mathematical
  multiplication, but a body cannot first multiply and then test overflow.
  Existing executable division requires nonnegative dividend and positive
  divisor; a general signed guard must handle i64 minimum without negating it.
  A sign-aware or iterative implementation may be possible today. It is deferred
  for implementation/proof scope, not declared impossible in the language.
- `binary_search_i64`: sortedness, membership and index contracts are expressible
  today, but a halving search adds quantified excluded-interval invariants and
  all-pairs sortedness reasoning. It is deferred to keep this slice at twelve
  functions. A future API must require explicit sortedness (not a call to the
  ordinary is_sorted function), specify Some/None exactly and decide its duplicate
  index policy. This design makes no claim that current Pruv cannot implement it.
- Sorting with a permutation contract: there is no primitive permutation
  predicate, arbitrary lemma function, or general aggregate induction. Bounded
  count-based multiset properties can be written, so syntax alone is not the
  blocker; proving preservation and usable runtime domains with today's solver
  needs separate evidence. Sortedness alone would be an insufficient contract.
- General prefix-safe sum, checked sum, generic reverse, bool/byte variants,
  cost contracts, verified collections/strings/I/O, contracts-listing CLI,
  package management, pruning and proof caching remain outside this slice.

Open evidence to settle in implementation: acceptance and stable proof times of
the exact quantified contracts in both compilers; packaging behavior on supported
installation layouts; repeatable cost of twelve proofs per importing compile;
and backend runtime/ownership behavior under optimized execution. None was
measured here. Import spelling, function set, contracts, conflict policy and
per-compile proof policy are fixed decisions, not open questions.
