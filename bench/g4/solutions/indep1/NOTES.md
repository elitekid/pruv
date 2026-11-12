# indep1 notes (blind attempt, never compiled)

## q01
Split: `root` (3 host entries) -> `crate::store` (pub `find`, `sum`, `insert_at`; private `scan`, `build`) ->
`crate::store::check` (pub `in_range(lo,hi,n)`, `valid_pos(i,n)`, bool results with ensures in both directions).
Key contracts/invariants:
- `scan(a,q,start)`: requires prefix `a[0..start]` has no `q`; loop invariant `forall k in 0..i: a[k] != q`, early `return i`.
- `sum`: requires valid range + element bounds; invariants `s == sum(k in lo..i: a[k])` and `|s| <= 1e6*(i-lo)` (overflow).
- `build` (private, alloc): ensures `len(result)==len(a)+1`, `result[i]==v`, prefix equal, suffix shifted by one;
  three-phase fill (prefix loop, set `b[i]`, suffix loop with `b[m+1]==a[m]`), `len(b)` carried in invariants.
- `insert_at` reads `build(...)[j]`; root only calls it after `valid_pos` checks.

## q02
Split: `root` -> `crate::tree` (pub `enum Tree`, `build`, `count_nodes`, `count_leaves`, `height`) -> `crate::tree::shape` (pub `mid`).
Key contracts: all measured by `size(t)`, assuming `size(Empty) == 1` (every constructor counts), so a tree with
c nodes has size `2c+1`: `build` ensures `size(result) == 2*(hi-lo)+1` (decreases `hi-lo`); `count_nodes`: `size(t)==2*result+1`;
`count_leaves`: `size(t)==2*result-1`; `height`: `0<=result<=size(t)`. All have `requires size(t) <= 2001` and
`decreases size(t)`. `mid` ensures `lo <= result < hi` and the exact formula.

## Unclear
- Whether `size(Empty)` is 1 or 0 is not stated outright ("number of constructors... counting only active payloads");
  the whole q02 proof depends on 1. The `result <= 2*n+1` bound in the problem hints that it is 1.
- SPEC does not say whether user functions may appear in contracts (I assumed not), nor whether `pub enum` syntax is
  `pub enum Tree {...}` (assumed), nor whether returning from inside a `while` is fine (assumed yes).
- Whether `return` of a local array (`b`) needs `copy` (assumed no, only parameters do).
- Unused match bindings (`v`) assumed not an error.
