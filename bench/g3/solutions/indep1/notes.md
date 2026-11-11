# Notes (no compiler was available; none of this was run)

- q01: High confidence. Plain struct construction and field reads; the contract is spelled out in full.
- q02: High confidence. The only open point is whether `match` with `return` in both arms counts as "every path ends with return". The wrappers use `let mut o` plus an `if` to build the Option, because the spec has no conditional expression.
- q03: High confidence. The wrappers repeat the generic `requires`, so the empty-array probe should panic with `pruv: requires violated`.
- q04: Medium confidence. I use `copy(a)` on `[T]` and rely on the verifier knowing `len(copy(a)) == len(a)` and the elementwise equality. SPEC §5 only says "new array equal to a". I avoided `alloc(n, v)` because an abstract `T` has no fill value. If the verifier does not know the equality, a loop with invariants would be needed instead, and that would need a fill value, e.g. `copy(a)` first and then rewriting each element.
- Unclear in SPEC.md: (1) whether `copy` works on `[T]` for abstract `T`, and what the verifier knows about it; (2) whether `Some::<T>(v)` may appear in an assignment to a `let mut` Option local (assumed yes); (3) whether a struct field name like `first` clashes with a function named `first` (assumed no, since they are in different namespaces).
