# Stage 5: Cost Bound Contracts (first slice)

Status: design. BLUEPRINT Stage 5 lists four items: (1) automatic caching of pure functions, (2) state-read and
`io none` contracts, (3) resource-lifetime types, (4) computation-bound contracts (`cost O(n)`). This slice is item 4
only, in an explicit, modular, checkable form. Items 2 and 3 are already covered for the current language (section 1),
item 1 is deferred (section 9).

## 1. Goal and repository facts

Goal: a function may state an upper bound on the work it performs, as an i64 expression over its parameters, and the
verifier proves that every execution stays within it. Refactors that move a loop or call into a hotter place then
fail to verify at the caller (whose own bound no longer holds) instead of slowing down silently.

Facts this design builds on (read from the repository on 2026-11-13):

- Effects are declared per function (`! io, alloc, fs`); no `!` part means pure (SPEC §3, §6h). This already is the
  `io none` contract of Stage 5 item 2. Pruv has no global or module state, so `reads state.x` has nothing to name.
- `File` (G10) is an owned handle closed on every path or dropped (SPEC §6h); this is Stage 5 item 3 for the only
  resource the language has. Watchers/timers/subscriptions do not exist yet.
- Every `while` has exactly one `decreases` (SPEC §4); recursive functions have a function `decreases` (SPEC §6e,
  `Function.decreases` in `pruvc/vast.py`, checked at calls in `pruvc/verify.py` around the recursive-call check).
- Calls are verified modularly: prove the callee `requires`, assume its `ensures` (SPEC §3). Loop-assigned variables
  are known after the loop only through invariants (SPEC §7).
- `par` groups (G7, SPEC §6i) run branch calls whose argument values are captured at group entry.

## 2. Non-goals

- No asymptotic notation (`O(n)`), no inference of bounds, no amortized or probabilistic cost, no time in seconds.
- No bound on memory; `alloc` sizes are already proven `<= 2^40`.
- No span/critical-path cost for `par` (only total work).
- No cost for foreign (G6) or file (G10) operations in this slice: such calls are rejected inside cost functions.
- Caching (item 1) and finer effect splits stay deferred.

## 3. User surface

```
fn sum(a: [i64]) -> i64
  requires len(a) <= 1_000_000
  cost len(a)
{
  let mut s: i64 = 0;
  let mut i: i64 = 0;
  while i < len(a)
    invariant 0 <= i && i <= len(a)
    invariant spent == i
    decreases len(a) - i
  { s = s + a[i]; i = i + 1; }
  return s;
}
```

- Header clause `cost <i64 expr>`: at most one, after all `requires`/`ensures`, before or after `decreases` is a
  parse error unless it comes last (`requires* ensures* decreases? cost?`). The expression is a contract expression
  over the parameters (no `result`, no `old`, no `spent`), evaluated in the entry state, and must be defined there
  (contract domain, SPEC §6).
- Contract-only expression `spent` (i64): the units this function has spent so far in the current call. Allowed only
  in `invariant` and `assert` of a function that has a `cost` clause.
- A function without `cost` is unchanged and costs nothing to verify.
- `cost` and `spent` become keywords (no program in the repository uses them as names; checked 2026-11-13).

Cost units (the "spent" counter of one call, starting at 0):

| Event | Units added |
|---|---|
| start of each `while` iteration (the body is entered) | 1 |
| call `f(args)` to a Pruv function with `cost C_f` | 1 + C_f evaluated on the actual arguments |
| `alloc(n, v)` | 1 + n |
| `copy(a)` | 1 + len(a) |
| `par { b1; ...; bk; }` | sum of the branch call units (each 1 + C_bi on the captured arguments) |
| every other expression or statement, `len`, built-in contract helpers | 0 |

The function verifies its bound if `spent <= C` holds at every return, where `C` is the `cost` expression evaluated
at entry (frozen like `old`). A negative `C` is allowed but then only a body that spends 0 can meet it.

## 4. Static rules (binding)

1. A function with `cost` may call only functions that also have `cost` (and the built-ins in the table); otherwise
   `effect/cost_callee`: "`f` has no cost clause, so its work is unbounded here".
2. Foreign calls (G6), collection/catalog operations and file operations (G10) inside a cost function:
   `effect/cost_unsupported` (deferred, section 9). The rule is direct (callees are covered by rule 1).
3. `spent` outside `invariant`/`assert` of a cost function: `type/spent_context`. `spent`, `result` or `old` inside a
   `cost` expression: `type/cost_expr`. Non-i64 `cost`: `type/cost_type`.
4. Duplicate or misplaced clause: `parse/cost_syntax`.
5. Generic functions may have `cost`; each specialization is checked like any other function. A `pub` function's
   `cost` is part of its module interface (G4) and is visible to importers.

## 5. Verification (binding)

Per cost function, the verifier keeps a ghost i64 variable `spent`, 0 at entry, unbounded (mathematical) arithmetic.

- Loop: `spent` counts as assigned by every loop (rule of SPEC §7): it is havocked at loop entry and known only through
  the invariants. The iteration step adds 1 before the body; invariants are checked on entry and after the body as
  today. A loop with no `spent` invariant therefore loses all knowledge of `spent` and the return check fails with a
  counterexample.
- Call: after proving the callee's `requires` (and recursive `decreases`), check the callee's `cost` expression is
  defined on the actual arguments (`contract_domain`), then `spent := spent + 1 + C_f(args)`.
- Recursion is sound by the existing termination proof: the recursive call's `C_f` is assumed as the callee's bound,
  justified by induction on the proved `decreases`.
- `par`: the units of all branches are added once at group entry, using the captured argument values.
- Return: prove `spent <= C_entry` (`verify/cost_bound`, counterexample names the function, the bound text and the
  values of `spent` and `C`).
- `alloc`/`copy`: units are added after the existing size checks.
- `spent` in `assert` reads the current ghost value.

Run-time requires checks (SPEC §7, public entries) do not count as spent units.

## 6. Backends (binding)

- Verified mode (default): `cost` and `spent` are erased. Generated Rust source and LLVM IR of a program are
  byte-identical to the same program with the `cost` clauses and `spent` clauses removed.
- Safe mode (`--no-verify`): each cost function keeps a local u128 counter with the same units, adds the callee's
  evaluated bound at each call (modular, not the callee's actual spending), and at each return checks
  `spent <= C_entry`; a violation panics with `pruv: cost exceeded` (exit 101). `C` is evaluated at entry with the
  run-time contract evaluator (i128, panics `pruv: requires undefined` outside its domain). `assert` stays erased.
  `--trust-callers` does not disable these checks.
- Both compilers (Python reference, Rust port) produce byte-identical output; both backends (Rust source, LLVM) behave
  the same.

## 7. Diagnostics (binding)

| Stage/code | When |
|---|---|
| `parse/cost_syntax` | duplicate, empty or misplaced `cost` |
| `type/cost_type`, `type/cost_expr`, `type/spent_context` | section 4 rule 3 |
| `effect/cost_callee`, `effect/cost_unsupported` | section 4 rules 1-2 |
| `verify/cost_bound` | `spent <= C` not proved at a return |
| `verify/contract_domain` | `C` undefined at entry or at a call |

## 8. Batches (binding gates)

- **A0 frontend:** parser, AST, type and effect rules of sections 3-4 and 7 in both compilers; must_reject roots for
  every diagnostic; a program that uses `cost` or `spent` and passes the static checks stops with the staging guard
  `codegen/cost_unavailable` ("Stage 5 cost verification is not implemented yet") in every mode and on both
  backends; programs without them are byte-identical to before.
- **A1 verification:** section 5 in both compilers; at least 12 proof programs (loops, nested loops with
  `spent == i * m + j`, calls, recursion, generic callee, par, alloc/copy) and 12 must_reject cases (missing
  invariant, off-by-one bound, callee bound larger than budget, call in a loop without a multiplied bound, recursion
  with a too small bound, par sum exceeding the bound). Remove the staging guard.
- **A2 Rust backend:** erasure in verified mode (byte comparison against the clause-free program for every A1 proof
  program) and the safe-mode counter; runtime roots including a deliberate `pruv: cost exceeded` under `--no-verify`.
- **A3 LLVM backend:** same as A2 for LLVM; SPEC.md gets one user section (§6j).
- **Q:** fuzzing (verified programs with cost bounds run in safe mode must never panic `cost exceeded`; programs
  with a bound reduced by one must be rejected by the verifier or panic in safe mode for some generated input),
  at least 40 source mutants (wrong unit counting, missing loop, extra call, bound off by one, wrong multiplier) with
  zero wrongly verified, fault injections (omit loop unit, omit call unit, assume instead of prove at return, skip
  havoc of `spent` at loops, erase safe-mode check), an independent author given SPEC and two problems, and a
  measurement showing verified-mode output is unchanged (no run-time cost) and the safe-mode counter overhead.

Each batch: Python first, Rust port in the same commit; `--only` group runs while fixing; full suite once per commit.

## 9. Deferred work

- Costs for foreign, collection and file operations (needs per-operation bounds in the catalogs).
- Span cost for `par`, amortized costs, cost inference, `O()` notation.
- Stage 5 item 1 (caching pure functions) and item 3 for future resources (watchers, timers).
