# Stage 1 B: Template Houdini Invariant Inference — Implementation Spec

> Status: final (2026-11-11, main session; 3.7 version 2 added the same day). A document that fixes `docs/STAGE1_SPEC.md` §0 items 5, 6, 7, 9, 11, 12, 14, 15 and body §2 at the implementation level. The two implementations (Python `pruvc/infer.py`, Rust `pruv-proof/src/infer.rs`) produce **the same candidates, the same order, and the same SMT** as this document specifies. There is no interval analysis (C).

## 1. Configuration (inference configuration version 2, 3.7)

| Name | Value |
|---|---|
| `version` | 2 |
| Candidate limit per loop | 64 (truncated from the front after sorting and deduplication; the number cut is `capped`) |
| Exploration query limit per function | 512 (including lemma retries; one attempt = 1) |
| Exploration query `rlimit` | 100000 |
| Exploration query `timeout` | 500ms |
| Exploration query `random_seed` | 0 |
| Inference time safeguard per function | 5 s (wall clock) |

Final verification is as before (timeout 8000, no rlimit or seed).

## 2. Loop numbering

Traverse the function body in pre-order: statements in order; for a `While`, assign the number and then visit its body; `If` is then → els; `Match` is in arm order. Numbers start from 0.

## 3. Candidate generation

### 3.1 Basic definitions (loop `w`)

- `M` = names assigned inside `w.body` (the existing `assigned`: `Assign`, `IndexAssign`, `FieldAssign`, including nested blocks).
- **Invariant expression** (an expression that does not change in this loop): an expression made only of `IntLit`, `Var x` (x∉M), `len(Var x)` (x∉M), unary `-`, and binary `+ - *`.
- **Initial value** `init(v)`: look at the statements before `w` in the same block as `w`, from the back. When `Let v`/`Assign v` is found, that value. If, before that, a statement among `If/While/Match` that assigns `v` is found, none. If none is found up to the start of the block, none. `init_len(b)`, for array length, skips `IndexAssign b` and follows the same rule.
- **Counter** `v`: a variable such that there is exactly one assignment to `v` inside `w.body`, that assignment is a top-level `v = v + c` of the body (c is an `IntLit`, c≥1), and `init(v)` is an invariant expression. The top-level position of that statement is `pos(v)`, and the start value is `lo = init(v)`.
- **Bound expression**: for each term of `w.cond` split at top-level `&&`, if it is `v < E`/`E > v` then `up = E`, and if it is `v <= E`/`E >= v` then `up = E + 1`. v is a counter and E is an invariant expression.
- **Element range**: in the form `forall K in 0..len(x): A && B` in `f.requires` (including the synthesized requires of refinements), if A and B are `x[K] >= L`/`L <= x[K]` and `x[K] <= U`/`U >= x[K]` (L and U are integer literals or `-literal`), the range (L, U) of `x`. One, the first found, per array.
- **Term range** `rng(T)`: `IntLit n` → (n,n), `-e` → (−U,−L), `x[e]` (x∉M, with an element range) → (L,U), `+` → sum of endpoints, `-` → (L1−U2, U1−L2), `*` → min and max of the four endpoint products. Otherwise none.
- `N(v)` = `v` if `lo` is `IntLit 0`, otherwise `v - lo`.
- `T[v:=k]`: the expression with `Var v` replaced by `Var k`. `k` is `refine.pick_bound_name(all names in the function)` (one per function).
- Integer constants must be within i64 (a negative is `-` + a positive literal, magnitude ≤ 2^63−1). A candidate that goes outside is not created.

### 3.2 Accumulation statements (per counter `v`, top-level statements before `pos(v)`)

- **Sum**: `s = s + T` or `s = T + s`. s≠v, the only assignment to s inside `w.body` is this one, `v` appears in T and its other names are outside M, and arrays inside `T` are outside M. `init(s)` is an integer literal (`c0`, negatives allowed).
- **Conditional accumulation**: `if C { s = s + T; }` (no else, and the then is that one statement). The conditions above + `v` appears in C and its other names are outside M. If `T` is `IntLit 1` it is a **count**, otherwise a conditional sum.
- **Max/min**: `if X { m = T; }` (no else, and the then is that one statement), the only assignment to m is this one, `v` is in T, and if X is `T > m`, `m < T`, `T >= m`, or `m <= T` it is max, and if `T < m`, `m > T`, `T <= m`, or `m >= T` it is min (T is compared structurally, ignoring positions). Start candidates `b`: `lo`, and also `n−1` if `lo` is an integer literal n≥1 and `init(m)` is structurally the same as `T[v:=IntLit(n−1)]`.

### 3.3 Candidate kinds (fixed numbers)

| No. | Candidate | Condition |
|---|---|---|
| 1 | `lo <= v` | counter |
| 2 | `v <= up` | bound expression |
| 3 | `v <= up \|\| v == lo` | bound expression, lo is an integer literal |
| 4 | `len(b) == E` | b∈M, all assignments to b are `IndexAssign`, and `init_len(b)` is `alloc(E, _)` (E an invariant expression) or `copy(x)` (x∉M → `len(x)`) |
| 5 | `forall k in 0..len(b): L <= b[k] && b[k] <= U` | the same b as 4. One (L,U) per requires element range; if `alloc(_, c)` (c a literal), widened to include c; if there is no requires range and only an alloc literal, (c,c) |
| 6 | `s == sum(k in lo..v: T[v:=k])` (`s == c0 + sum(...)` if c0≠0) | sum |
| 7 | `c == count(k in lo..v: C[v:=k])` (`c0 + ...` if c0≠0) | count |
| 8 | `b < v ==> m == max(k in b..v: T[v:=k])` (min) | max/min, per b |
| 9 | `forall k in b..v: T[v:=k] <= m` (`>=` for min) | max/min, per b |
| 10 | `b < v ==> (exists k in b..v: T[v:=k] == m)` | max/min, per b |
| 11 | `s >= c0 + L * N(v)`, `s <= c0 + U * N(v)` | sum (rng(T)=(L,U)) / conditional sum (L→min(L,0), U→max(U,0)) / count (`c >= c0`, `c <= c0 + N(v)`) |

Expression-form rules: if c0=0, drop the `c0 +`. If the coefficient L=0, use `0` instead of `L * N`, and if L=1, use `N`. Terms have exactly the shape in the table above (the accumulation variable on the left).

**No calls (soundness):** if a completed candidate expression contains even one `Call` node other than `len` (user function, `alloc`, `copy`, `print`, `is_some`, `some_val`, etc.), that candidate is not created (this filtering happens **before** sorting, deduplication, and the 64 truncation, so `generated` and the IDs are the same in the two implementations). Reason: a call in a contract context (`code=False`) does not check the callee's `requires` and assumes its `ensures`, so if a call enters a candidate the path condition is polluted and a false `ensures` could pass.

### 3.4 Sorting, numbering, position

For each loop, sort the candidates by (kind number, output string), keep only the first of identical strings, and then truncate to 64. The candidate ID is `L<loop number>#<rank>` (rank from 0). The position of every node of a candidate expression is the position of `w` (`w.line, w.col`).

### 3.5 Output strings (identical in the two implementations)

- Precedence: `==>` 1 (right-associative), `||` 2, `&&` 3, comparison 4, `+ -` 5, `* / %` 6, unary 7.
- A binary is `l op r` (one space). If a child is binary and has lower precedence, parenthesize; a right child is parenthesized even at equal precedence (but for `==>`, parenthesize if the left is equal).
- Unary `-e`, `!e`: parenthesize if the operand is binary or quantified.
- `forall/exists k in lo..hi: body` is parenthesized if it is an operand of a binary. An aggregate is `sum(k in lo..hi: body)`.
- Integers are decimal (no underscores), `len(a)`, `a[i]`.

### 3.6 Interpretations fixed in the implementation (Python implementation B2; the Rust implementation follows too)

1. A count (`T` is `IntLit 1`) is exempt from the condition "`v` appears in T" and requires `v` only in `C`. A conditional sum must have `v` in `T` as well.
2. Names declared inside the loop body (`let`, match binders) do not exist at the loop head, so the "outside M" check for sums and counts uses `M ∪ body-local names`. For max/min, `T` only forbids body-local names (no M check; if wrong, Houdini discards it).
3. The element range `A && B` is accepted regardless of lower/upper order. The (L,U) pairs of kind 5 are collected from all arrays that have a range in requires, with the same pair appearing once.
4. If the coefficient L=0, only `L * N` is replaced with `0` (if c0≠0, `s >= c0 + 0`).
5. Parenthesizing the operand of unary `-`/`!` applies only to binaries and forall/exists (no parentheses for aggregates).
6. A candidate that contains a node the output function does not know (struct literal, field access, etc.) is not created.
7. Reporting: `queries` is the number of exploration attempts (excluding final verification). If the budget is exhausted or it times out, `rounds` is the number of rounds started, `dropped` is up to the previous rounds, and `invariants` is `[]`. A loop with 0 candidates is `none`. The `--no-verify --infer` adapter gives `inference: []`.
8. Bound-variable names avoid all names in the function, so if requires uses `k`, the candidate becomes `k_1`.

### 3.7 B+ additional kinds (inference configuration version 2, finalized by the main session 2026-11-11)

Version 2 adds kinds 12, 13, and 14 to the table in 3.3. The conditions, shapes, and order of 1–11 do not change (if a new candidate is the same string, only the earlier kind's remains by the deduplication in 3.4). All new candidates also pass the 3.3 no-calls filter (a single point, `add`/`push`). Candidates are made only from code structure and do not rely on names.

Additional definitions (loop `w`, 3.1 terminology):

- **Counter set** `CTR` = all variables that satisfy the 3.1 counter definition (including the start-value condition).
- **Scalar range** `srng(p)`: look at `f.requires` (including synthesized refinements) in order, and at the terms obtained by splitting each clause at top-level `&&`, in order. If a term is `p >= c`/`c <= p`, lower bound c; if `p > c`/`c < p`, lower bound c+1; if `p <= c`/`c >= p`, upper bound c; if `p < c`/`c > p`, upper bound c−1 (p is a `Var`, c is an integer literal or `-literal`). Take the first found for each of lower and upper (if none, that side is absent). The result is, for each of lower and upper, present or absent.
- **Start range** `irng(e)` (e = `init(v)`): `IntLit n`/`-n` → (n, n); `Var p` (p∉M) → `srng(p)`; `x[e']` (x∉M, x has an element range) → the element range (L, U). Otherwise none.

| No. | Candidate | Condition |
|---|---|---|
| 12 | `v >= L`, `v <= U` (separately, only the side that exists) | v∈M, v∉CTR, all assignments to v inside `w.body` are `Assign`, `init(v)` exists, lower bound L/upper bound U of `irng(init(v))` |
| 13 | `forall k in lo..v: b[k] == E[v:=k]` | v∈CTR with increment c=1, in a top-level statement `b[I] = E` (`IndexAssign`) before `pos(v)` where I is `Var v`; b satisfies the condition of kind 4 (all assignments are `IndexAssign`, and `init_len(b)` is `alloc(E',_)` (E' an invariant expression) or `copy(x)` (x∉M)) and the only assignment to b inside `w.body` is this one; every free name of `E` other than v is outside `M ∪ body-local names` (v need not appear) |
| 14 | `forall k in lo..v: !C[v:=k]` | v∈CTR with increment c=1, in a top-level statement `if C { return R; }` before `pos(v)` (no else, the then is a single `Return` statement, R is anything or absent); v appears in C and its other free names are outside `M ∪ body-local names` |

- The order of v for kind 12 is by name sorting as in 3.2; for 13 and 14 it is counter-name sorting → body statement order. In any case 3.4 sorts by (kind, string).
- Output: for `!C`, as in 3.5, `!(…)` if C is binary. The constants of kind 12 follow the 3.1 i64 rule (no candidate if out of range).
- Reasons: 12 is for the sign of values that start from parameters and are passed back and forth as in `x = a; y = b` (gcd p10); 13 is for the output-array prefix relation (reversal p08; the length candidate 4 supports the index domain after havoc); 14 is for the prefix property of decision loops that "return immediately if the condition is true" (sortedness check p03). If any is false, Houdini discards it and the final verification proves again.
- Cost: the number of candidates is at most (number of non-counter scalars × 2) per loop for 12, 1 per output array for 13, and 1 per early-return `if` for 14. However, the number of queries is roughly Σ over rounds (the entry and preservation obligations of the remaining candidates + the basic obligations), so a chain of kind-12 candidates that support each other (`a0 = a1; a1 = a2; …`) increases the rounds and can exhaust the 512 budget (audit reproduction: exhausted with a chain of 20). Hence the 4.1 **version 1 revert**.

## 4. Verifier connection

- Give `FnVerifier` `extra` (loop number → [(candidate ID, expression, string)]) and `probe` (exploration state). When `extra` is empty it is **byte-identical** to the existing path (fresh numbers, SMT, errors).
- The invariant list of `loop(w)` = `w.invariants` (mandatory refinements → user, existing order) + that loop's candidates (3.4 order). Entry, preservation, domain, and the post-havoc assumptions all use this list (existing rule: the domain of a clause assumes only the earlier clauses, and the head assumption on the preservation side is all of them).
- Candidate obligations are `prove(..., key_extra=ID, cand=ID)`, and the domain also uses the same ID. `what` is `inferred loop invariant \`TEXT\` on entry` / `... preserved`, and for the domain `partial operations in inferred loop invariant \`TEXT\` (entry|preserved) are defined`.

### 4.1 Exploration round (probe)

- Each round has a new `FnVerifier` (new fresh, seen, aggregates, lemmas) and `QueryConfig(phase="inference", round=r (from 1), timeout_ms=500, rlimit=100000, seed=0)`.
- Obligations without `cand` are skipped without a query or record (the final verification looks at them). Obligations of candidates that have already failed in this round are also skipped without a query or record.
- Candidate obligations: the same two stages as the existing `prove` (without lemmas → if not unsat and there are lemmas, with lemmas). Before each attempt, if the query count is already at the limit it is **budget exhausted**, and if the wall clock has passed function start + 5 s it is **timed out**; otherwise the query count +1 and the query is made. A z3 exception is recorded with status `error` and that candidate fails. If an attempt result is unknown and the z3 reason is exactly `timeout` (the query's 500ms wall-clock deadline), it is **timed out**. If the last attempt is not `proved` (`not_proved`, `resource_unknown`, `timeout` (other than the exception above), `error`), that candidate fails in this round: (ID, obligation code, status) is recorded. The error list and `seen` are not touched.
- At the end of the round, the failed candidates are removed all at once. If none was removed, stop. If there are no candidates at all, no round is run.
- **Budget exhausted**: discard all automatic candidates of that function (status `budget_exhausted`) and go to the final verification.
- **Version 1 revert (version 2, 3.7):** if the budget is exhausted and the function's initial candidate list (after the 3.4 truncation) had even one kind 12 or higher, redo the exploration from the beginning once, with, for each loop, the list that keeps only kinds 1–11 of the initial list (IDs the same as the initial ones). New query budget 512, wall-clock deadline the same as the initial one (function start + 5 s), round numbers continue to be counted (from r+1), and a new `FnVerifier` every round. The records of candidates removed in the first exploration (`dropped`) are discarded. When the revert ends, go to 4.2 with its result. If the revert also exhausts the budget, `budget_exhausted`; if it times out, timed out (below). There is no revert for a timeout. Reporting: if a revert was done, every record of that function gets the key `"fallback": "v1"` (no key if not done), `rounds` is the last round number (sum of the two explorations), `queries` is the sum of the queries of the two explorations, `dropped` is that of the revert exploration, and `generated` and `capped` are the initial ones. If the revert list is empty, `ok` with no rounds (`verified`/`selected` by the final verification result, `kept` 0). Reason: so that, **in terms of query budget**, version 2 is no worse than version 1 (the revert list is the same as the version 1 list under the 3.4 sort). The time side is not guaranteed: the revert uses only the time left after the first exploration, so if the first exploration uses nearly 5 s, a function that would have passed under version 1 can become `inference_timeout` (not reproduced, a measurement target).
- **Timed out**: that function gets exactly one error `verify/inference_timeout` without final verification (position is the function, message `invariant inference for <fn> hit the time safety limit (5 s per function, 500 ms per query)`, hint `write the loop invariants explicitly, or compile without --infer`). Other functions continue.
- **B++ revision (2026-11-11):** if a candidate query is unknown, it is a whole-function timeout only when the z3 reason is exactly `timeout` (the query's 500ms wall-clock deadline); for any other reason (`canceled`, `push canceled`, `max. resource limit exceeded`, etc. from rlimit exhaustion), only that candidate is dropped. Reason: rlimit exhaustion is a deterministic result that is the same every run, but depending on the z3 version the wording split into `canceled` (old classification → timeout) and `resource_unknown`, so the verdicts of the two implementations diverged (RESULTS §31.1, §32). The wall-clock case is not turned into candidate removal, per STAGE1_SPEC §0 item 6 and line 283. The configuration values are unchanged, so the configuration version is not raised. The verdict meaning changed, so when comparing traces, distinguish before and after commit a07f0f1 (before: rlimit `canceled` also aborted the function). The report keys are unchanged, and `timeout` (rlimit exhaustion whose z3 reason is `canceled`) may appear in `dropped[].status`.

### 4.2 Final verification

Verify the whole function with a new `FnVerifier` (default `QueryConfig`) given the surviving candidates as `extra`. Errors are reported as before.

## 5. Options and output

- `--infer` (off by default): the inference above. `--show-inferred`: used without `--infer` it is a usage error (exit 2). With `--no-verify --infer`, inference is not run, and with `--show-inferred` a single line `{"status": "skipped_no_verify"}` goes to stderr.
- `--show-inferred` output: one stderr JSON line per loop (`sort_keys`, `ensure_ascii=False`). Keys: `fn`, `loop` (number), `line`, `col`, `status` (`verified`: zero errors for this function in the final verification / `selected`: has errors / `budget_exhausted` / `timeout` / `none`: no candidates), `invariants` (list of `invariant TEXT` of the surviving candidates, in order), `generated` (count after deduplication, before truncation), `capped`, `kept`, `dropped` ([{`cand`, `text`, `round`, `code`, `status`}] (status values: `not_proved`, `resource_unknown`, `timeout`, `error`), in round and ID order), `rounds`, `queries` (whole function). Function order → loop number order.
- Test adapter and `pruv-trace-dump`: with `--infer`, `options.infer=true`, both exploration and final queries are all in the trace, and the list of the above lines (the same objects) is put in the top-level `inference`. When off, there is no `inference` key.
- Generated code does not change (inferred invariants are for proof, so they are erased from the runtime code like the existing invariants).
