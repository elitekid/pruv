# G9 A1: proof model notes (audited justification)

Scope: `pruvc/verify.py` (`Model.size_fn`, `Model.wf_fn`, `Model.facts`, `FnVerifier.observe`). G9_SPEC 5.1 requires
that the size positivity and child-smaller lemmas, and the places where well-formedness (wf) facts appear, are
justified here. None of them is a user-assumed contract.

## 1. Definitions

For a non-generic nominal declaration D with constructors C_1..C_k (a struct has one), the verifier declares

    size_D(x) = 1 + sum over the fields f of the active constructor of weight(f)

as the structural definition (a nested `If` over the recognizers; the last constructor is the else branch, the
constructors are exhaustive). Weights: nominal non-generic value -> `size_E(value)`; `Some(v)`/`Ok(v)` -> weight of the
payload (guarded by the recognizer), `None`/`Err` -> 0; scalar, `[i64]`/`[u8]`/`[bool]`, `str` -> 0; an admitted acyclic
G3 application (e.g. `Pair<i64>`) -> a constant when its size is value-independent (`fixed_size`: a struct whose
fields are all scalars, buffers, collections or such structs has size 1 + the sum of the nested sizes; anything with
an Option/Result/enum field has no fixed size), otherwise the per-instance uninterpreted function `size!<instance
sort>` (`size_inst`). The instance function gets positivity only (`size_inst(c) >= 1`, added by `facts` for every
such direct child); it has no one-step equation, so it is never expanded (a function over a deep finite datatype
sort is very slow in z3, hence the constant). All `size_E` of one nominal type SCC are declared first and
defined together (mutual recursion); dependency SCCs are built first, so every definition refers only to functions
already declared. A1 decision: the Z3 symbols are plain uninterpreted functions; the definition is
asserted only as ground one-step instances on observed terms (`Model.facts`), never as a `RecFunction` or a
quantified axiom (RecFunction unfolding timed out on the tree fixtures). Fewer facts can only lose proofs, not soundness.

`wf_D(x)` (recursive types only) is defined in the same way: the conjunction over the constructors `C_i(x) ==> wf of
its fields`, where i64 fields are in range, buffer fields (projected to an array model by `field_get`) satisfy
`0 <= len <= 2^40` and the byte domain for `u8`/`str`, a nested non-recursive nominal field is expanded one level by
Python (finite, as before G9), and a recursive nominal field is `wf_E(field)`. wf of a non-recursive type that
contains a recursive type is the usual Python expansion that ends in `wf_E(...)` applications.

## 2. Lemmas (valid in every model of the definitions)

Every fact `observe` adds to a path condition is valid; none relies on the path, on wf, or on the active variant.

* **L1 positivity.** `size_D(t) >= 1` for every term t of type D.
  Proof by structural induction on the finite datatype value. In the one-step equation
  `size_D(t) = 1 + sum(weights)`, each weight is `0`, or the size of a child value (>= 1 by the induction hypothesis,
  the children being structurally smaller), or the payload weight of an Option/Result (>= 0, or 0 when the tag is
  None/Err). A sum of nonnegative terms plus 1 is >= 1. The base case is a constructor without nominal fields:
  the sum is empty and `size = 1`. Z3 datatypes are inductive (finite, no cycles, occurs check), and the recursive
  function is total because every call is on a strict subterm, so the induction is valid.
* **L2 one-step equation.** `size_D(t) = size_value(D, t)` and, for recursive D, `wf_D(t) = wf_step(D, t)`. These are the
  defining equations instantiated at t (a ground instance of the definition body), added only so that proofs do not
  depend on the solver's recursive-function unfolding depth.
* **L3 child smaller.** For a nominal child c = field_i(t) of the active constructor of t: `size_E(c) < size_D(t)`.
  From L2, `size_D(t) = 1 + w_1 + ... + w_n` where `size_E(c)` is one summand w_j (weight of a nominal child is its
  size); the other summands are >= 0 by L1 for nominal siblings (`facts` adds `size_E(sibling) >= 1` for every
  direct nominal child of every constructor) and by definition for Option/Result payload weights; hence
  `size_D(t) >= 1 + size_E(c) > size_E(c)`. The solver derives L3 from L1+L2 and is not given it separately. A
  selector on a variant that is not active gives an arbitrary value of the field type, so L3 is only used under the
  guard (`is_variant`, a match arm); L1 and L2 hold unconditionally.
* **L4 size of a constructor result.** For `C(a_1..a_n)` the equation L2 instantiates to
  `1 + sum(weights(a_i))`, again a ground instance of the definition.

Consequences used by `recursive_decrease`: for `match t { Node(v, l, r) => f(l) }` with `decreases size(t)`, the
obligation `size(l) < size(t)` follows from L2 (equation at t, which is observed at the match) and L1 for the
siblings (observed children).

## 3. Where wf facts are introduced (and where they are not)

* Fresh parameters, call results, havoc values (loop-modified variables): `wf(type)`; for a recursive type this is the
  application `wf_D(value)`, for a buffer-bearing aggregate the projected buffer conditions. This is the existing
  rule; every executable value is well formed (parameters by contract, call results by the callee's checked
  result, havoc values because loops only produce well-formed values).
* Constructor results: no wf is assumed. `wf_D(C(args))` follows from L2 and the wf of the (checked) arguments;
  an argument that is a proven in-range i64 satisfies its own wf, so nothing unchecked is used to prove itself.
* Match arms: the binders are assumed well formed, exactly as before G9 (the scrutinee is an executable value).
  For a recursive child the assumption is `wf_E(binder)`; it is also derivable from `wf_D(scrutinee)` and L2.
* Guarded selectors (`variant_field`, field access): the parent term is observed first (its one-step wf/size
  equations give the field's own facts), then the field value; only L1/L2 facts are added; the `variant_domain` /
  `contract_domain` obligation of the partial selector is unchanged and still required.
* `observe` caches observed terms by z3 AST id (`State.obs` holds the ids of observed terms and of added facts): a
  term already observed on the path is skipped without recomputing its facts.
* Contract literals (`code=False`): constructors build the datatype value from the mathematical field values
  without range obligations or assumptions; wf is never assumed for them. Only the valid facts L1/L2 are added.
* Buffer fields: stored as a datatype `Buf(len, arr)`. `field_get` projects to the existing array model and
  `field_put` injects it back. Only indices below `len` matter. No raw datatype equality is used for a
  buffer-bearing aggregate (the checker rejects `==` there, `type/eq_type`), so array tails never become visible.

## 4. Termination (reminder of the proof structure)

Entry: measure defined and `>= 0` under requires (`recursive_nonneg`, error at the clause). Call inside the SCC: callee
requires, measure definedness, `M_g(actuals) >= 0`, `M_g(actuals) < M_f(entry)` (frozen entry value), and only then a
fresh result with the callee ensures (the induction hypothesis for strictly smaller measures). The measure is a
nonnegative mathematical integer that strictly decreases along every call chain inside an SCC, hence there is
no infinite chain and every ensures assumed for a callee is a statement about an already terminating call.

## 5. Display (counterexamples)

Recursive values print in constructor/field order. A value shows at most 64 nominal nodes (preorder, left to right) and
depth 16 (the value itself is depth 1); anything beyond is the marker `<truncated>`. Buffer fields print as
`[e0, e1, ...]` (first 8 elements, `...` if longer) or `"bytes"` for `str`. The bounds only affect printing.
