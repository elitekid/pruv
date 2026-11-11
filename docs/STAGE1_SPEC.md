# Stage 1 Design: Automatic Inference of Refinement Types and Invariants

> Status: **final** (2026-11-11). The draft came from a design delegation (Codex gpt-6-astra); after one design debate (same model, opposing position) the main session finalized it. What was adopted is recorded in "Design debate adoption record" at the end of the document. §0 below takes precedence over the body.

## 0. Summary of final decisions (takes precedence over the body)

1. **Split into three batches.** A refinement types → B template-based Houdini inference (no interval analysis) → C interval analysis (decide whether to start it after measuring the effect of B's templates against a baseline). The first completion scope of Stage 1 is A.
2. **Each batch finishes Python implementation → corresponding Rust implementation → AST/error/SMT/output cross-check (extending `tests/m3_all.py`) within a single batch.** P/R is the implementation order inside a batch, not separate batches to integrate separately (same as the README new-feature policy).
3. **Syntax:** value ranges are closed `L..=U`, length upper bounds are `; <=N`. This distinguishes them from the existing `forall/exists` and aggregate `lo..hi` (upper bound exclusive). Example: `a: [i64 | -1_000_000_000..=1_000_000_000; <=1_000_000]`, `x: i64 | 0..=100`. Bounds are signed decimal integer literals only (checked against i64 after applying the sign; `-9223372036854775808` is allowed); `1e9` is rejected with `parse/refinement_syntax` and the decimal notation is suggested.
4. **Unsupported positions** (fields, payloads, inside Option/Result) are rejected with `parse/refinement_position`. No type representation that preserves an unsupported refinement is created.
5. **Inference (B) ships in the first implementation behind the explicit opt-in option `--infer`** (off by default). The budget figures (64, 512, rlimit 100,000, 500ms, 5 s) are starting values for measurement. Whether to turn it on by default will be decided again after measurement. `--show-inferred` is part of B.
6. **Per-round state isolation:** each Houdini round runs the whole function from a fresh symbolic state with a fixed candidate map, and uses no path conditions, `seen`, errors, verdicts, aggregate caches, or lemmas from earlier rounds. A candidate survives only if its domain and value obligations succeed on every entry and back-edge path that reaches it. Exploration queries explicitly return `proved / not_proved / resource_unknown / timeout / error`, and the verdict is not derived from the error recording or return value of the existing `prove()`. A candidate is not removed on the basis of a `sat` from the first attempt without lemmas alone; the permitted retry is also considered. A timeout is not turned into candidate removal (`verify/inference_timeout`).
7. **Placement and domain:** invariant order is mandatory refinements → the user's original order → automatic fixed order. When checking the domain of a clause, no current-state values of that clause or later clauses are assumed (the induction hypothesis of the previous iteration's head in the preservation check is used). An automatic candidate must prove its domain by its own guard or by candidates earlier in the fixed order (`max/min` blocks an empty range with its own guard, and the array range of a sum/count prefix interval relies on earlier bound candidates).
8. **Name and declaration binding:** a refinement annotation carries a declaration ID and original position. Synthesized quantifier names do not collide with user names (capture-free substitution), and synthesized contracts also go through the basic type and scope checks. A mandatory invariant is created only for declarations alive at that loop head. Obligations for local declarations, reassignment, and element stores are checked at that operation's point and are not omitted even if a `return` follows immediately.
9. **havoc:** the first implementation keeps the existing havoc (recreates both the contents and the length of a modified array). A length alias (`n = len(a)`) and the old element range are not assumed directly after havoc; relations to be kept are proved by mandatory-invariant obligations or candidates. A whole reassignment invalidates the old summary.
10. **Mode axes:** proof mode and `--trust-callers` are two independent axes. Proof mode checks all static obligations of refinements. Safe mode does not guarantee local or return refinements. The runtime check of parameter refinements (public boundary, internal calls in safe mode) is performed only when `--trust-callers` is absent. The iteration budget is one per function entry (shared by synthesized + user requires). No runtime checks are added for return or local refinements. Documentation and error messages do not describe refinements as runtime-enforced types.
11. **Query recording boundary:** every solver call in exploration and in final verification passes through a common execution/recording boundary. The actual timeout, rlimit, and seed, whether it was a retry, `reason_unknown`, and the stage, round, candidate, and obligation IDs are recorded, and solvers in separate modules are recorded without omission. On the `--no-infer` (default) path, the existing model-generation counts and SMT names do not change.
12. **Scope of reproducibility:** candidate generation order and query construction are deterministic. Agreement of solver verdicts and adopted candidates is tested only under a designated solver profile (z3 version, build, platform, options, inference-configuration version); the same verdicts across different versions are not guaranteed.
13. **Cross-checker:** "the two implementations give the same result" and "verification complete" are counted separately. The same inference timeout or undecided result is not a success sample. A difference resolved by retry still keeps the first result. Check that the new proof options were actually passed to the adapter and the Rust dump, and do not ignore unknown options. This fix is the first task of batch B.
14. **Measurement goal (B):** the minimum goal is to delete all of the invariant §9 (3 each) in p01, p07, and p09 and succeed in proving them. This is not an effect metric for refinements or interval analysis. Compare no inference / templates only / (after C) templates + intervals on the same inputs. p03 (return inside a loop), p05 and p08 (modified arrays), and p10 (remainder operation, nested loops) are diagnostic samples; p02 and p06 do not substitute for `max/min` aggregate tests, so separate `max/min` pass and reject samples are provided. Report the numbers of candidates, rounds, and solver calls, the generation, symbolic-execution, and final-verification times, trace size, and the number of budget-discarded items. The reduction in writing effort from refinements (A) and the cost of runtime boundary checks are measured separately.
15. **Required rejection samples (B):** one each of: first entry of a false candidate, a candidate that holds only once, failure after removing a dependent candidate, a nested loop where removing an outer candidate breaks the inner proof, return right after a wrong store, use of the old length/element summary after whole-array replacement, wrong loop-condition indexing, an unguarded empty `max/min`, and a wrong user invariant.
16. **C decision (2026-11-11, after B measurement, RESULTS §29):** interval analysis (C) is not started now. On pruv_agg with the invariants deleted, templates alone prove 4/10 (p01, p02, p07, p09); of the remaining 6, only p10 appears solvable with non-relational intervals, and the rest (p03, p04, p05, p06, p08) need relational or quantified invariants. The next candidates are value-range templates (`x >= 0` style, based on initial values and updates) and relation templates (sortedness, output-array prefix); when work starts, it will be recorded in this document as a new decision. Turning `--infer` on by default is also not done yet (the measurement inputs are small, and the real-world impact of a design in which the timeout of a single candidate query fails the whole function is unmeasured).
17. **B+ decision (2026-11-11, RESULTS §30):** added template kinds 12 (value range), 13 (output-array prefix), and 14 (early-return prefix), plus a revert to version 1 when the budget is exhausted (`docs/STAGE1_B_INFER.md` 3.7 and 4.1, inference configuration version 2). pruv_agg with invariants deleted went from 4/10 → 7/10. **Turning `--infer` on by default is still not done.** Measurement basis: turning it on makes compile time 1.3–8× per input for the Rust implementation (17–37ms → 23–161ms) and trace 1.5–19×; 3/10 (p04, p05, p06) still fail, so there remain cases where users must write invariants even with it on; the time-side limits of timeout and revert are not measured on realistic-size inputs. Condition for reconsideration: measuring zero timeouts and under 2× time increase on a larger batch of inputs.

Body §§1–6 keep the draft sentences, but where they conflict with §0, follow §0 (in particular the `..` notation, `type/refinement_position`, inference on by default, the batch tables in 5.2–5.3, and the inclusion of interval analysis in the first implementation).

This document is the design for implementing `BLUEPRINT.md` Stage 1. Refinement types are introduced as annotations that expand into existing contracts, and invariant candidates produced by interval analysis and syntax-based templates are filtered Houdini-style and passed to the existing verifier. **Responsibility for proof stays with the z3 verifier, and the inference result itself is not trusted.**

Below, "confirmed" is current behavior read from the repository, and "decision" is a decision of this design.

## 1. Refinement type syntax and semantics

### 1.1 Supported scope

**Decision:** the first implementation supports the value range of `i64`, and the element range and length upper bound of `[i64]`. The usable positions are function parameters, return types, `let`, and `let mut`.

| Position | First implementation |
|---|---|
| Function parameter | scalar and array refinements allowed |
| Function return type | scalar and array refinements allowed |
| `let`, `let mut` | scalar and array refinements allowed |
| Struct field, enum payload | refinement annotations forbidden |
| Inside `Option<i64>`, `Result<i64>` | refinement annotations forbidden |
| Condition on a whole user type | use existing `requires`/`ensures` |

Field refinements are deferred. Currently structs and enums need consistent handling of construction, nested field assignment, pattern binding, the external boundary, and whole-root havoc in loops. Including this in the first implementation would make the implementation scope larger than the goal of reducing the writing effort of array inputs and accumulation loops. Array fields are already forbidden today (`SPEC.md:132`, `pruvc/check.py:84`).

### 1.2 Syntax and bounds

```pruv
fn sum_array(
  a: [i64 | -1_000_000_000..1_000_000_000; ..1_000_000]
) -> i64 {
  // ...
}

fn clamp_input(x: i64 | 0..100) -> i64 | 0..100 {
  return x;
}

let mut count: i64 | 0..100 = 0;
let values: [i64; ..100] = alloc(100, 0);
let bounded: [i64 | -10..10] = copy(values);
```

```text
scalar-refinement := i64 "|" signed-int ".." signed-int
array-refinement  := "[" i64 ["|" signed-int ".." signed-int]
                            [";" ".." unsigned-int] "]"
```

- `L..U` in a refinement annotation is a **value range that includes both endpoints**.
- The length annotation `..N` means `0 <= len(a) && len(a) <= N`.
- The element range and the length upper bound can each be omitted.
- Scalar and element bounds are integers in the `i64` range and must satisfy `L <= U`.
- The length upper bound satisfies `0 <= N <= 2^40`. `N = 0` allows only the empty array.
- Only integer literals are allowed as bounds. Ranges that reference variables, `len`, arithmetic expressions, or depend on other arguments are written with existing contracts.
- `|` cannot be attached to `bool`, `()`, or user types.
- The existing `[i64]` and `i64` syntax is unchanged.

**Rationale:** this maps the blueprint example's "element range and length upper bound" directly onto the existing examples' `<=` contracts. However, the existing `forall k in lo..hi` and the iteration range of aggregates remain **upper-bound exclusive** (`SPEC.md:89`, `SPEC.md:107`). The difference between value-range annotations and iteration ranges is stated explicitly in the spec and the boundary tests. The alternative of unifying every `..` as a half-open range keeps the notation simple but cannot carry the blueprint's upper bound over as written, so it is not adopted.

**Literal decision:** `1e9` and `1e6` are not allowed in this stage either. The blueprint example is specified as follows.

```pruv
a: [i64 | -1_000_000_000..1_000_000_000; ..1_000_000]
```

The current spec and lexer support only decimal digits and the `_` separator (`SPEC.md:14`, `pruvc/vparser.py:13`). The general literal syntax is not extended just for exponent notation. Exponent notation in a refinement bound is rejected with `parse/refinement_syntax` and the decimal notation is suggested.

### 1.3 Type system and expansion

**Decision:** the identity, ABI, and value representation of the base types do not change. A refinement is a verification annotation attached to a declaration, and its logical meaning expands into existing contracts.

Currently Python's `Type` is a single name and Rust's `Type` is a string. The checker checks exact matches of base types (`pruvc/vast.py:9`, `pruvc/check.py:322`, `pruvc-rs/crates/pruv-core/src/ast.rs:5`). Keeping this structure, rather than adding a new dependent-type system, makes it easier to keep the two implementations and the two output backends consistent.

Define `R(T, v)` as the condition that refinement type `T` requires of value `v`.

```text
R(i64 | L..U, x)
  = L <= x && x <= U

R([i64 | L..U; ..N], a)
  = 0 <= len(a) && len(a) <= N
    && (forall k in 0..len(a): L <= a[k] && a[k] <= U)
```

Without an element range, no `forall` is created. Without a length upper bound, the existing array length condition `0..2^40` applies.

| Position | Meaning after expansion |
|---|---|
| Parameter `p: T` | synthesized `requires R(T, p)` on the function |
| Return type `T` | synthesized `ensures R(T, result)` |
| Local variable declaration | an obligation equivalent to `assert R(T, x)` after evaluating and binding the initial value |
| Reassignment of a refined local variable | an obligation of the same refinement condition after storing the new value |
| Assignment to a refined array element | the element-range obligation of the stored value added to the existing index and arithmetic obligations |
| Loop that modifies a refined local variable | the corresponding refinement condition added as a mandatory invariant |

Synthesized parameter contracts go in parameter declaration order, ahead of the user's `requires`. For arrays, the order is the length condition, then the element condition. The return refinement goes ahead of the user's `ensures`. The order among the user's own contracts is not changed.

A local refinement is not an annotation checked only once at initialization. It must also be maintained at reassignment of a `let mut` and at element stores. Therefore the following is rejected in proof mode.

```pruv
let mut x: i64 | 0..100 = 0;
x = 101;
```

A mandatory invariant derived from a local refinement is distinguished from automatic inference candidates. Houdini cannot delete it, and it remains even under `--no-infer`. The refinement fact must not be put into `havoc()` unconditionally without proving loop entry and preservation.

Expansion does not increase the number of evaluations. Obligations are built on the value obtained by evaluating the initialization, assignment, or return expression once. In particular, `a[i] = f()` keeps the current index → value evaluation order (`SPEC.md:83`, `pruvc/verify.py:718`).

### 1.4 Subtyping and assignment rules

The inclusion relation among refinements holds only between the same base type.

```text
i64 | L1..U1 <: i64 | L2..U2
  iff L2 <= L1 && U1 <= U2
```

Arrays require both element-range inclusion and length-upper-bound inclusion. A base type without a refinement is the case with no such refinement condition.

The actual assignment and argument-passing rule is unified into the following single rule.

> The base types must be the same, and the target refinement condition must be provable from the facts of the current path.

Therefore a plain `i64` without a refinement can also enter a refined position if its range is confirmed by an `if` or a `requires`. The inclusion relation of declared ranges can be used for fast decisions, but an unclear inclusion relation alone is not a reason to reject at the type stage.

- The result type of arithmetic is the base `i64`. Refinement types are not arbitrarily composed in arithmetic.
- A base-type mismatch is the existing `type_mismatch`.
- The array alias and ownership rules are kept. `array_alias` cannot be bypassed through refinement inclusion.
- Array parameters remain read-only. Covariance for mutable aliases is not introduced.
- Whole reassignment of a refined array proves both the element and the length conditions.
- An element store does not change the length, so preservation of the whole refinement is proved from the existing array refinement and the new element range.

The current restrictions on array creation, copy, and return are at `pruvc/check.py:307`.

### 1.5 Error codes

| stage | code | Condition |
|---|---|---|
| parse | `refinement_syntax` | malformed refinement syntax such as a missing bound, or a non-literal or exponent-notation bound |
| type | `refinement_position` | unsupported position such as a field, payload, or inside Option/Result |
| type | `refinement_base` | refinement of an unsupported base type |
| type | `refinement_bounds` | reversed range, bound outside i64, invalid length upper bound |
| verify | `refinement_init` | failed to prove the refinement of a local's initial value |
| verify | `refinement_assign` | failed to prove the refinement of a reassignment or element store |

Synthesized parameter and return contracts use the existing `call_requires` and `ensures`. Failures of mandatory invariants are the existing `invariant_entry` and `invariant_preserved`, and domain failures are `contract_domain` and `variant_domain`. When the solver cannot reach a conclusion, the existing `verify_unknown` is kept.

Every synthesized obligation preserves the position and kind of the original annotation. Messages state the origin, such as "return refinement" or "element range of parameter a", and do not present internal variable names that the user did not write as things to fix.

### 1.6 Runtime checks and safe mode

**Decision:** in line with the principle of expanding refinements into existing contracts, the runtime policy of `docs/M0_CONTRACTS.md` is followed as is.

- A synthesized parameter `requires` is checked at runtime at public function entry.
- The synthesized and user `requires` of one entry share **the same 2^30 iteration budget**. No per-refinement budget is created.
- An element `forall` consumes 1 for each element actually checked. Empty arrays and expressions skipped by short-circuiting consume nothing.
- The length upper bound is checked first, so if the length exceeds the bound the check fails before iterating over elements.
- Budget overflow is the existing `pruv: requires undefined: contract iteration budget exceeded`, exit code 101.
- Refinements do not introduce a new static limit on the iteration count of existing contracts. The combined cost of multiple array contracts is limited by the runtime budget.
- Return refinements, local refinement obligations, and mandatory and inferred invariants are erased from the runtime code.
- `--no-verify` does not prove the logical validity of refinements. As before, the runtime safety checks for indexing, arithmetic, and allocation and the public-boundary `requires` check remain.
- Internal calls in safe mode go through the checked entry point. Internal calls in proof mode go to the body on the basis of the proved `requires`.
- `--trust-callers` also skips the public-boundary check including synthesized refinements. It does not remove the static proof obligations.

Therefore it must not be explained that local or return refinements are guaranteed at runtime under `--no-verify`. This is the same as the current policy in which `assert`, `ensures`, and `invariant` are erased even in safe mode (`docs/M0_CONTRACTS.md:28`, `pruvc/codegen.py:494`).

## 2. Houdini-style automatic invariant inference

### 2.1 Candidate generation

**Decision:** a finite set of candidates is built from the checked AST and the refinement expansion result. It uses the structure of initializations, conditions, updates, and contracts, without depending on whether a variable is named `i`, `s`, or `count`.

| Source | Example candidate | Restriction |
|---|---|---|
| Interval analysis | `0 <= i`, `i <= 100`, `x == 0` | only finite bounds are passed |
| Loop condition and initialization | `0 <= i && i <= len(a)` | initial value, increment, and condition are checked together |
| Refinement or explicit element precondition | `forall k in 0..len(a): L <= a[k] && a[k] <= U` | preservation proof needed if the array is modified |
| Sum accumulation | `s == sum(k in 0..i: a[k])` | check initial value, one-step update, and unmodified input |
| Count accumulation | `c == count(k in 0..i: a[k] < x)` | conditional `+1` pattern |
| Max/min accumulation | `0 < i ==> m == max(k in 0..i: a[k])` | guard for the empty prefix is mandatory |
| Range of accumulated value | `L*i <= s && s <= U*i` | generated from the term's range and the number processed |
| Count range | `0 <= c && c <= i` | count accumulation pattern |

It is not claimed that interval analysis alone yields relations such as `s <= U*i`. That is a separate accumulation template.

The candidate generator supports the following.

1. Forward loops with a start value such as `i = 0` or `i = 1` and `i = i + 1`.
2. Length aliases that are not modified, such as `n = len(a)`.
3. `s = s + e(i)` and conditional count increments.
4. `if e(i) > m { m = e(i); }` and its symmetric form for the minimum.
5. Prefix candidates obtained by replacing the upper bound of an explicit aggregate postcondition with the progress variable.
6. Cases such as `return Ok(s)` where the link between the result payload and the accumulation variable is syntactically confirmed.
7. Inner-product term ranges obtained from products of element ranges.

If the initial accumulated value is not 0, either a candidate that includes that value is created or the pattern is abandoned. The empty-prefix initialization of a sum is not applied to a maximum loop whose start index is 1.

The existing one-step unfolding lemma of aggregates is used as is. No new global induction axiom is added per candidate. The aggregate model at `verify.py:545` provides neither arbitrary interval splitting nor the distributivity of maximum. `RESULTS.md:49` also records the limitation that the maximum subarray sum cannot be proved with a plain `max` contract.

### 2.2 Removal algorithm and soundness

For each loop `ℓ`, define the following.

- `Uℓ`: the user invariants and the mandatory invariants of local refinements. Cannot be deleted.
- `Cℓ`: automatic candidates. Can be deleted.
- `Iℓ = Uℓ ∧ ∧Cℓ`.

A fixed-point computation is done that handles even the nested loops of one function together.

```text
Generate and normalize the candidates of all loops.
Repeat:
    Fix the candidate set for this round.
    Symbolically execute the function and loops in the determined order.
    Check the entry, preservation, and domain obligations of each candidate.
    Collect the IDs of candidates that fail or for which no conclusion is reached.
    At the end of the round, remove the failed candidates in one batch.
    If nothing was removed, stop.
Re-verify the whole program with the confirmed candidates attached, from a new verification state.
```

The obligations to check are as follows.

- **Entry:** on every path that reaches the loop, the candidate is defined and true. The loop's own candidates are not used as entry assumptions.
- **Preservation:** after havocking the modified variables, assume the current `Iℓ` and the loop condition and execute the body once. On every path that returns to the next iteration, the candidate must be defined and true.
- **Exit paths:** paths that `return` from the body are not required to satisfy back-edge preservation. The return contract is checked in the final verification.
- **Domain:** a candidate's own domain is not justified by the candidate's value. `max/min` guards the empty range with a short-circuit guard inside the candidate.

One candidate may need another, so when a candidate is removed, the remaining candidates are checked again. A candidate that succeeded once is not confirmed permanently. Nested loops are also checked using the candidate set of the same round, which prevents the situation in which an outer candidate is gone but only the inner proof result remains.

During exploration `Uℓ` can be used as an induction hypothesis, but failures of entry or preservation of user invariants are not hidden or deleted. The final full verification must succeed on all of the following.

- Entry, preservation, and domain of user, mandatory, and inferred invariants
- All indexing, arithmetic, and assignment obligations
- Call preconditions and return postconditions
- `assert`
- The domain, non-negativity, and strict decrease of `decreases`

**Inference neither creates nor omits `decreases`.** The exactly one `decreases` that the current parser requires is kept (`pruvc/vparser.py:247`).

Exploration errors, `seen`, fresh numbers, aggregate caches, and lemmas are not reused in the final verification state. The current `prove()` does both error recording and duplicate suppression, so it must not be used directly as a boolean function for candidate verdicts (`pruvc/verify.py:254`).

### 2.3 Budget and determinism

**Decision:** candidate selection is controlled by a fixed order and logical resource budgets, not by elapsed time.

The initial defaults are as follows. The figures are proposed values before performance measurement.

| Item | Initial value |
|---|---|
| Candidate limit per loop | 64 |
| Exploration solver-call limit per function | 512, including lemma retries |
| z3 `rlimit` per exploration query | 100,000 |
| Time safeguard per exploration query | 500ms |
| Inference time safeguard per function | 5 s |

- The 64 limit is applied after sorting, and the number discarded is recorded in diagnostics.
- If the fixed point is not completed before the query-count limit, **all automatic candidates of that function are discarded** and the existing verification proceeds. A partially checked set is not treated as completed invariants.
- An ordinary `sat` or an `unknown` from a deterministic resource limit removes the candidate.
- If the wall-clock time safeguard fires, compilation is aborted with `verify/inference_timeout`. Different candidate sets are not chosen depending on time so as to make it succeed. The suggested fix is `--no-infer` or explicit invariants.
- The existing 8,000ms query limit of final verification is separate (`pruvc/verify.py:8`).
- The candidate cap, rounds, query count, and resource settings are shared by the two implementations as a versioned inference configuration.

It is not possible to guarantee the same result for runs that hit the time safeguard. This is distinguished from the determinism contract for normally completed runs, and it is not hidden as a success in cross-check tests.

Candidate IDs and order are fixed by the following.

```text
function declaration order
→ loop AST pre-order index
→ fixed number of the candidate kind
→ structural key of the alpha-normalized expression
```

Bound variables are normalized to internal reserved names, and integers use decimal normal form. Hash-map order, object addresses, and the enumeration order of counterexample models are not used in candidate selection. Normalization that indiscriminately swaps the child order of quantifiers or logical expressions is also not done, because that can change the short-circuit domain.

The relative order of user invariants is kept, and the placement rule for mandatory refinement invariants and automatic candidates is fixed. An automatic candidate must be able to prove its domain with its own guard or with conditions earlier in the fixed order. Later inference candidates are not used to retroactively justify the domain of an earlier user contract.

### 2.4 Python and Rust SMT-LIB cross-check

The current cross-check does not look only at the final success or failure. The Python adapter records the SMT text just before each solver call, and `tests/diff_trace.py` compares those strings (`tests/diff_py_adapter.py:199`, `tests/diff_trace.py:302`).

Therefore the new inference trace adds the following.

- Stage: `inference` or `verification`
- Function, loop, round, and candidate ID
- Obligation kind: entry, preservation, domain
- Actual solver options: timeout, rlimit, fixed seed
- Whether a lemma was used, the SMT-LIB source text, and the verdict
- Candidate removal and budget termination reasons

The current Python adapter records the timeout as a constant, so a fix is mandatory. Inference queries must not be omitted, and a 500ms query must not be shown as 8,000ms.

The two implementations are aligned in fresh names, path traversal, havoc order, aggregate registration order, assertion insertion order, and the attempt without lemmas → attempt with lemmas. Differences in counterexample values keep the existing tolerance, but candidates are not selected by counterexample content.

A separate gate is that, with `--no-infer` on existing inputs, the existing final-verification SMT and errors are preserved.

### 2.5 User diagnostics and turning it off

- Inference is on in default proof mode.
- `--no-infer`: turns off automatic candidate generation and Houdini. The mandatory obligations of refinements are kept.
- `--show-inferred`: shows the inference result on stderr as JSON Lines with a fixed key order.
- `--no-verify`: inference is also not run. If the display option is used together, a `skipped_no_verify` status is emitted.

The display carries the function and loop position, a pasteable `invariant ...` statement, the origin, the generated, adopted, and dropped counts, and the budget status. Only results that succeed through final verification are shown as `verified`. If full verification fails, candidates that survived exploration are distinguished as `selected`.

The existing stdout error JSON and `{"ok": true}` format are kept. Automatic annotations are not inserted into the generated source, and the user's files are not modified.

## 3. Interval analysis

### 3.1 Abstract domain and targets

**Decision:** the first implementation is a non-relational integer interval analysis.

```text
Interval = ⊥ | [lower, upper]
lower/upper = integer or -∞/+∞
```

The tracked targets are `i64` local variables and parameters, array lengths, and separately summarized array element ranges. Arithmetic is computed with arbitrary-precision integers. An overflow in the analyzer must not create a wrongly narrow interval.

- A plain `i64` input starts from the full i64 range.
- The bounds of refinements and simple explicit `requires` are read as input facts.
- Simple comparisons combined with `&&` are narrowed in order.
- General quantified expressions and complex logical expressions are not arbitrarily turned into numeric bounds.
- An explicit `forall k in 0..len(a): L <= a[k] && a[k] <= U` is recognized as the same summary as the refined element range.

This form of existing preconditions is supported so that `bench/solutions/pruv_agg`, which has not been converted to the new syntax, can also be measured.

### 3.2 Transfer functions

| Construct | Handling |
|---|---|
| Literal, variable, unary sign | exact interval propagation |
| `+`, `-`, `*` | interval operations; products use endpoint combinations |
| `/`, `%` | narrow only when the domain of the current code can be confirmed |
| Assignment | replace the previous target interval with the new interval |
| `if` | narrow each of the true and false branches, then merge as the smallest enclosing interval |
| Short-circuit logic | reflect the actual reaching condition |
| `alloc`, `copy` | propagate length and element range |
| Array store | merge the existing element range and the stored value's range |
| Function call | use the return refinement and supported simple postconditions; the rest gets the default range |
| `match` | analyze each arm and merge, removing the arm's local variables |
| Unsupported expression | conservatively the full range |

When arithmetic safety is not proved, the result is not clipped to the i64 range to circularly prove "no overflow". If the computed result can go outside i64, that possibility is retained and left to the existing verifier.

An unmodified `n = len(a)` is kept as alias information. A relation such as `x <= y` cannot be expressed exactly with independent intervals alone, so supported loop-bound relations are handed to separate candidate templates.

### 3.3 While fixed point and widening

The loop-head state is computed by combining the initial entry state and the back-edge state. The true loop condition is applied for the body analysis.

- The first two times, an ordinary join is done.
- After that, increasing endpoints are widened with fixed thresholds.
- The thresholds are made by sorting and deduplicating 0, 1, both i64 ends, relevant constants in the source, refinement bounds, and length upper bounds.
- If it keeps expanding past the thresholds, it is widened to infinity.
- When the implementation's iteration limit is reached, the changing components are widened to the full range.
- After stabilization, one conservative narrowing is allowed, and it is rechecked that the result is a post-fixed point of the abstract transfer.
- Nested loops are handled with the same rules and a fixed order.

In particular, distinguish the **loop-head interval before the condition is applied** from the interval inside the body. If the body fact `i < n` of `while i < n` is submitted as an invariant as is, it fails after the last iteration. `i <= n` is generated as a separate bound candidate and checked for inductiveness.

### 3.4 Results passed on as candidates

The analysis result is passed to the candidate generator together with the following information.

```text
loop ID, variable/array ID, finite lower and upper bounds,
length alias, element range, origin, loop head/body/exit distinction
```

A finite lower bound becomes the candidate `L <= x`, a finite upper bound `x <= U`, and equal endpoints `x == C`. Infinity, the full range, and unreachable states do not create unnecessary candidates.

The interval result does not directly become an SMT assumption or an LLVM optimization attribute. Even a wrong analysis result is used only if it passes both Houdini and the final verification.

## 4. Out of scope for this work

**The `BLUEPRINT.md` feature of passing counterexamples to an AI and receiving invariant proposals is not implemented in this stage.** Model calls, prompts, external services, counterexample transmission, and the caching and retry policies of AI proposals are also out of scope. The inference in this work uses only finite candidates generated deterministically from repository code and contracts.

Refinement fields, general dependent types, arbitrary-predicate refinements, refinement type aliases, termination-measure inference, and arbitrary splitting of aggregates and additional induction lemmas are likewise not included in this first implementation.

## 5. Implementation batches and completion criteria

### 5.1 Data boundaries

The current Python pipeline is `parse → check → verify → gen` (`pruvc/pruvc.py:53`). The actual parser file is `pruvc/vparser.py`.

The following boundaries are added.

```text
Original AST
→ base type check + refinement validation and expansion
→ checked AST with contracts expanded
→ interval analysis, candidate generation, Houdini
→ full verification using the confirmed invariant map
→ existing Rust/LLVM code generation
```

- `Type` and `Expr.ty` represent only base types.
- Refinement metadata is placed explicitly on `Param`, the return annotation of `Function`, and `Let`.
- `Refinement` holds the bounds and the original position.
- Synthesized obligations carry an origin and a unique ID. Multiple obligations arising from the same annotation position must not collide in the existing `seen` key.
- The inference result is passed as separate immutable data of `LoopId → candidate list`. The checked AST is not modified for each exploration round.
- Refinement conditions are not mixed into `wf()` for base types. A refinement is a contract that must be proved.

The batches below are units of sequential integration. When several batches modify the same file, proceed after the earlier batch is complete.

### 5.2 Python implementation (new features first)

| Batch | Files modified/added | Deliverable and completion criterion |
|---|---|---|
| P1 Syntax and expansion | modify `pruvc/vast.py`, `pruvc/vparser.py`, `pruvc/check.py`, `pruvc/typeinfo.py`; new `pruvc/refine.py`; modify `tests/diff_py_adapter.py`, `SPEC.md` | Supported positions, bounds, and error order fixed. The origins of synthesized requires/ensures and local obligations remain in the dump. New parse/type pass and reject tests pass. |
| P2 Refinement proof and output wiring | modify `pruvc/verify.py`, `pruvc/pruvc.py`, `pruvc/codegen.py`, `pruvc/llvmgen.py`; modify `docs/M0_CONTRACTS.md` | Verification of initialization, reassignment, array stores, returns, calls, and mandatory loop invariants. The manual-contract version and the refinement version agree in meaning. The two outputs agree in boundary checks, budget sharing, and safe-mode behavior. ABI unchanged. |
| P3 Interval and candidates | new `pruvc/interval.py`, `pruvc/infer.py`; new `tests/inference/` test data | Confirm widening termination and conservativeness for branches, nested loops, and array modification. Actually generate the bound, accumulation, and prefix candidates needed for p01, p07, and p09. Confirm that generation order is independent of the hash seed. Candidates are not yet used as proof facts. |
| P4 Houdini and diagnostics | modify `pruvc/infer.py`, `pruvc/verify.py`, `pruvc/pruvc.py`, `pruvc/codegen.py`, `tests/diff_py_adapter.py`; new `tests/inference/run.py` | Iterative removal, re-checking of nested loops, and final fresh-state verification complete. Budget, timeout, option, and diagnostic tests pass. Wrong candidates and user-invariant errors are distinguished. Exploration does not pollute the final fresh names and caches. |
| P5 Python integration | modify `tests/run_all.py`, `tests/compiler_driver.py`, `tests/cli_also_llvm.py`; new `tests/must_reject/refine_*`, `tests/runtime/refine_*`; new `bench/inference/run.py`; modify `RESULTS.md` | The regression, soundness, and usability gates below are first achieved on the Python implementation, and the results, settings, and input list are fixed. |

The backend changes in P2 are for consuming the expanded contracts identically and showing origins. No new runtime refinement types or local-refinement runtime checks are introduced.

### 5.3 Rust port

Port after the Python semantics and snapshots are stable.

| Batch | Files modified/added | Completion criterion |
|---|---|---|
| R1 Frontend | `pruvc-rs/crates/pruv-core/src/ast.rs`, `lexer.rs`, `parser.rs`, `check.rs`, `typeinfo.rs`, `dump.rs`, `lib.rs`; new `refine.rs` in the same directory | The original, checked, and expanded ASTs, error JSON, and origin order are byte-identical to Python. The new cases of `tests/diff_parse.py` and the Python adapter pass. |
| R2 Analysis and proof | `pruvc-rs/crates/pruv-proof/src/symbolic.rs`, `obligation.rs`, `sys.rs`, `lib.rs`; new `interval.rs`, `infer.rs` in the same directory; modify `src/bin/pruv-trace-dump.rs` | Interval results, candidates, per-round removal sets, final invariants, and SMT-LIB are identical to Python. The actual rlimit and timeout settings are applied identically in `sys.rs`. |
| R3 CLI and output | `pruvc-rs/crates/pruvc/src/cli.rs`, `driver.rs`; `pruvc-rs/crates/pruv-core/src/codegen.rs`, `llvmgen.rs`, `emit_common.rs`; the corresponding parse/check/Rust/LLVM dump entry points | Inference options and diagnostics and the synthesized-contract output agree. Zero differences between the two implementations in Rust source, LLVM IR, and bindings. The existing ABI and call paths are kept. |
| D Final cross-check | `tests/diff_trace.py`, `tests/diff_compilers.py`, `tests/diff_rust.py`, `tests/diff_llvm.py`, `tests/diff_py_adapter.py`, `tests/run_all.py`, `bench/inference/run.py`, `RESULTS.md` | Cross-check of the new feature on/off and the proof, safe, and trust combinations (`tests/m3_all.py`). Zero SMT text differences including the candidate trace. Timeouts and crashes are not counted as passes; results are recorded after independent review. |

New fields are needed in the AST and trace, so the dump schema change is versioned explicitly. The serialization rules of the existing formats are not changed by accident.

### 5.4 Regression and new test gates

On completion, the following are required for each of Python and Rust.

1. The existing 363 regression rows are not deleted and are kept on both backends.
2. The existing expected results are confirmed in default inference mode and under `--no-infer`.
3. If inference changes an existing rejection verdict, investigate individually whether it is a real bug or a proof-incompleteness test. Expected values are not updated in bulk.
4. New tests are reported as a separate count, and the total is recorded alongside.
5. The existing 186 CLI tests are also kept, and tests for the new options are added.

The new tests must include the following.

- Both ends of a scalar, one step outside the range, the i64 minimum and maximum.
- Array lengths 0, N, and N+1, both ends of elements, reversed ranges, invalid upper bounds, and unsupported positions.
- Cases where an unrefined value is narrowed by path conditions and passes, and cases rejected because it is not proved.
- `let mut` reassignment, whole-array replacement, element stores, and loop-preservation violations.
- Boundary checks where a synthesized refinement is evaluated before user contracts.
- Budget sharing among multiple synthesized and explicit `requires`. Boundaries are confirmed with the small `--contract-budget` used for existing tests.
- Candidates that fail at initial entry, candidates that hold only once, and candidates that fail after a dependent candidate is removed.
- A wrong `max/min` empty prefix, and an element range broken by modifying the array.
- Nested loops, early returns, zero iterations, and safety obligations of condition expressions.
- Cases where a wrong user invariant does not disappear because of inference.
- Candidate and query limits, rlimit, the time safeguard, `--no-infer`, `--no-verify`.
- Repeated cross-checks with different Python hash seeds, and cross-checks of candidate and SMT order between the two implementations.

### 5.5 Measuring the reduction in writing effort

The baseline inputs are `bench/solutions/pruv_agg/p01.pruv` through `p10.pruv`. The originals are preserved and copies are made for measurement.

- **Full removal:** delete all user `invariant`s while keeping contracts, bodies, and `decreases`.
- **Partial removal:** delete them one at a time or in fixed groups to measure which invariants are replaced.

| Metric | Definition |
|---|---|
| Proof success after full removal | number of the 10 functions whose obligations are all proved |
| Number of replacement invariants | number of explicit invariant clauses deleted and number kept |
| Inference effect | difference in success with inference on vs. off on the same variant input |
| Cost | per-function numbers of candidates, rounds, and queries; median and tail latency of time |
| Stability | repeated runs on the same input, hash seeds, Python/Rust verdict and SMT agreement |
| Soundness regression | number of new passes by wrong mutants |

**The first-implementation completion goal is set as proof success of the three functions p01 (sum), p07 (count), and p09 (inner product) with all invariants removed**, because the required prefix aggregates and accumulation bounds correspond clearly to the code. Separate `max/min`-only pass and reject samples are also provided so that all four aggregates are verified.

The `forall/exists` maximum characterization of p02, the binary-search interval of p04, the output-array prefix of p05 and p08, and the maximum subarray sum of p06 have their measurement results published but are not counted in the required number of successes for this first implementation. The success count above is a **goal, not a current measured value.**

## 6. Risks and open problems

| Risk | Decision in this work and review point |
|---|---|
| Unconditional assumption of refinements | Separate from `wf()` and check the obligations for initialization, stores, and loop preservation. |
| Circular justification among candidates | Entry checks, re-checking after removal, and full verification in a new state are mandatory. |
| Self-justification of the domain | Check the domain before the candidate's value. Test short-circuiting and empty aggregates. |
| Reuse of old ranges of modified arrays | Re-prove preservation after stores, whole reassignment, and havoc. |
| Leakage of inference state | Isolate the exploration's `seen`, fresh numbers, and aggregate caches from the final verification. |
| Cost blow-up from quantified expressions | Keep the candidate cap and two-stage aggregate proofs. Take into account the record that the existing domain assumption slowed p06 considerably (`docs/M0_CONTRACTS.md:21`). |
| Subtle differences in SMT text | Names, ordering, registration, options, and serialization are all cross-check targets. |
| Nondeterminism of time limits | Adopting partial candidates depending on time is forbidden. Runs that time out are reported as a separate failure. |
| Misunderstanding of safe mode | Distinguish runtime safety from a full contract guarantee. Local and return refinements are not proved in safe mode. |
| Closed refinement range vs. half-open iteration range | Distinguish them through documentation, error messages, and boundary tests. A point to reconsider before the public syntax is finalized. |
| Overfitting to the benchmark | Put variable renames, variants of condition direction, initial values, and return wrapping, as well as negative elements and empty input, into the new tests. |

Open problems:

- It must be measured whether the proposed 64 candidates, 512 queries, rlimit, and time safeguard suit real programs.
- If the cost of re-checking the whole of outer and inner loops is large, a proof-dependency cache will be considered later. The first implementation chooses a simple, reviewable full re-check.
- Whether the limits of non-relational interval analysis are the main cause of real failures will be measured, and then relational analysis considered.
- Field refinements will be introduced after separately designing the semantics of construction, assignment, match, and the external boundary.
- The lemma linking `max/min` equalities to the existing `forall/exists` characterization needs a separate soundness review.

## Design debate adoption record

Design debate (2026-11-11, Codex gpt-6-astra, opposing position): 15 findings (9 required, 6 recommended).

| Finding | Decision |
|---|---|
| 1 First-implementation scope too large; interval analysis cannot directly produce the core goal (prefix aggregates) | Adopted: A/B/C split, C after measurement (§0 item 1) |
| 2 All P then R conflicts with the "port within the same batch" policy (required) | Adopted: Python, Rust, and cross-check per batch (§0 item 2) |
| 3 Unclear state isolation between rounds; `prove()` has no verdict value (required) | Adopted (§0 item 6) |
| 4 Invariant placement and the set of domain assumptions undecided (required) | Adopted (§0 item 7) |
| 5 Name capture of synthesized `forall k` and declaration binding (required) | Adopted (§0 item 8) |
| 6 havoc recreates even the array length → risk of assuming a length alias (required) | Adopted (§0 item 9) |
| 7 The safe-mode description could be read as a refinement guarantee | Adopted (§0 item 10) |
| 8 Conflicting budget figures; risk that default-on makes existing proofs hit the new limits | Adopted: explicit `--infer` opt-in (§0 item 5) |
| 9 Reproducibility depending on rlimit unknown and the z3 version (required) | Adopted: solver-profile scope (§0 item 12) |
| 10 Risk that exploration queries bypass the recording boundary (required) | Adopted (§0 item 11) |
| 11 The cross-checker counts the same timeout or flaky result as a success (required) | Adopted: first task of B (§0 item 13) |
| 12 `..` has two meanings, closed and half-open | Adopted: `..=`, `<=N` (§0 item 3) |
| 13 Cost of sending unsupported positions to the type stage | Adopted: `parse/refinement_position` (§0 item 4) |
| 14 p01, p07, and p09 are weak evidence for interval analysis | Adopted: separated into a comparison experiment (§0 item 14) |
| 15 The required goal does not look at modified arrays, nested loops, or returns inside loops (required) | Adopted: diagnostic samples and rejection samples (§0 items 14 and 15) |
