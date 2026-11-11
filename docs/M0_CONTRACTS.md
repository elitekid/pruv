# Remaining Stage 0 tasks: contract domain, run-time iteration budget, O(n) check of the sortedness precondition (2026-11-10)

Design draft: Codex gpt-6-astra (design delegation). Below are the final decisions as revised by the main.

## A. Contract domain as a verifier proof obligation
Widen `dom()` (verify.py) from variant_field only to a general domain. V(e)=mathematical value, D(e)=domain.

| Expression | Conditions other than the children's domains |
|---|---|
| `a[i]` | `0 <= i < len(a)` |
| `x / y`, `x % y` | `y != 0` (z3 Int div/mod = SMT-LIB Euclidean = run-time `checked_div_euclid`, so the backend is not changed) |
| `some_val(o)` / `ok_val(r)` / `err_val(r)` | `is_some(o)` / `is_ok(r)` / `!is_ok(r)` |
| `variant_field(e, E::V, f)` | `is_variant(e, E::V)` (existing) |
| `max/min(k in lo..hi: b)` | `lo < hi` |
| Everything else (arithmetic, sum/count, fields, constructors) | children only |

- Short-circuit: `D(a&&b)=D(a)∧(V(a)⇒D(b))`, `D(a||b)=D(a)∧(¬V(a)⇒D(b))`, `D(a==>b)=D(a)∧(V(a)⇒D(b))`.
- Quantifiers: the end domain first. As now, forall/exists check the body domain (Reach) only for the k whose result was not decided in earlier iterations. Aggregates check the body domain for every k in the range.
- Where to prove: requires (assume only the earlier requires and prove D(r)), ensures, assert, invariant entry and preservation, decreases. For ensures and invariant, the earlier clauses of the same kind (domain + value) are used to prove the domain of later clauses.
- At a call site the callee's requires domain is not proven again (audit R2): the callee's run() has already proven it with "parameter wf + earlier requires", and the call site proves the earlier requires values while the arguments satisfy wf, so it is always redundant.
- Assumption: of the proven domains, only the variant_field part is put into the path condition (same as before). Assuming the other domains as well put the nested-quantifier index ranges into every query and made the p06 proof go from 0.44 s to 69 s. Dropping the assumption is sound.
- Error codes: the variant_field obligation keeps the existing `variant_domain`, the rest use the new `contract_domain`. If one expression has both, each is proven separately (2 queries) to keep the codes.
- Fast path: an expression with no partial operation has no query (`_has_vf` extended). If `z3.simplify(D)` is True there is no query.
- Relation to the run-time check: once the domain is proven, `requires undefined` in a public function's run-time check can no longer occur because of the domain, only from i128 overflow or exceeding the iteration budget (B) (resource limits, written in the spec).

Migration of existing tests (an intended change of meaning): r20 and g1_r06 (unguarded max and variant_field requires) are now rejected in the default mode → run the execution tests only with `--no-verify` and add new rejection tests. r21 gets `requires len(a) >= 1` in front. r18, r19, and g1_r15 stay as they are.

## B. Iteration budget of the run-time requires check
- No static upper-bound obligation is added (an unneeded burden for proof-only contracts, and it would not prevent the cost of nested products).
- All requires checks of one public function entry share an iteration budget of 2^30 (1,073,741,824). It decreases by 1 each time a forall/exists/aggregate body is run once, and when used up it gives `pruv: requires undefined: contract iteration budget exceeded`, exit code 101. A new budget at each entry (a local variable, no global state).
- The range length is not computed separately (the i128 iteration variable is below hi, so it does not overflow). Empty ranges and expressions skipped by short-circuit do not use the budget.
- ensures, invariant, assert, and decreases have no run-time code, so they do not apply.

## C. O(n) run-time check of the sortedness precondition
- The verifier keeps using the original double forall. Only the run-time check (both backends, in both proof and safe modes) changes.
- Recognized form (by AST structure, bound variable names free): `forall i in 0..len(a): forall j in i..len(a): a[i] <= a[j]` and the one whose inner start is `i + 1`. Same array variable, outer start integer 0, both ends `len(a)`, and the body is the single `a[i] <= a[j]`. Anything else gets the original check.
- Execution: `forall k in 1..len(a): a[k-1] <= a[k]`. Equivalent: for length 0 or 1 both are true, otherwise by transitivity and reflexivity. All indices are in range, so there is no difference in undefined order. The budget is charged for the actual iterations of the changed check.
- The common recognizer `codegen.match_sorted_requires(e) -> Optional[str]` (the array variable name) is used by llvmgen.
- Note: the bench p04 performance section calls the public function n times, so even if the check is O(n) the whole is O(n^2). Algorithm speed comparisons keep using `--trust-callers`.

## D. Fuzzing
Done (2026-11-11, RESULTS §§10–12 and §25). `bench/fuzz/{generate,oracle,run}.py`, an independent oracle (an arbitrary-precision interpreter), cross-check of Rust·LLVM × proof·safe, 4 modes. It follows the plan in §D of the design draft.
