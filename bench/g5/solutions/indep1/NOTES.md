# indep1 notes (blind attempt, G5_SPEC 14 item 6)

Author: a delegated worker that saw only `SPEC.md` and `bench/g5/PROBLEMS.md`, with no shell and no compiler.
The files here are its output, unchanged.

Result (2026-11-12): every compile was accepted on the first try (py and rs compilers, rust and llvm backends,
default verify mode, py/rs outputs byte-identical). `python3 bench/g5/run.py bench/g5/solutions/indep1`: 8/8
problem runs ok (q01 1056/1056 tests, q02 151/151 tests in each configuration). Compiler feedback rounds: 0.
Revisions: 0. Manual help: none.

## q01
Three private single-element inout helpers on `[u8]` (`sat_at`, `wrap_at`, `set_at`) with exact contracts against
`old(b)` and a `forall` frame, three loop helpers (`sat_range`, `wrap_range`, `fill_range`) with invariants over
`old(b)`, and three host entries that `copy(a)` and call the loop helpers.

## q02
`root` -> `crate::xform` (pub `swap_at`, recursive `rev_rec` with `decreases hi - lo + 1`, recursive `shift_from`
with `decreases len(a) - i`). The root entries copy the input and call `crate::xform::...(inout w, ...)`.

## What the author was unsure about (none of it caused a problem)
- Whether an inout `[u8]` keeps the 0..255 element domain (it does).
- Whether `len(b) == len(old(b))` is implicit (it is; the author did not need to state it).
- Whether `return w` of a local array needs `copy` (it does not).
- Whether `rev_rec` would need two quantifier layers (it did not).
- `shift_from` requires only `forall k in i..len(a)` bounds (enough).
- Whether a module path works with `inout` (it does).
- Bound `n = len(w)` before `rev_rec(inout w, 0, n - 1)` to avoid an `inout_alias` with `len(w)` (that is the rule).
