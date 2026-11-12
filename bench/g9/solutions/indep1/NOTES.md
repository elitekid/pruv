# Notes

## q01
Helpers `find_from` / `below_from` take a start index `i` and recurse with `decreases len(a) - i`; the wrappers call
them with 0. The helper's `ensures` guard `result < len(a)` inside the `a[result]` implication so the contract
domain does not depend on an earlier `ensures`. Unsure: whether earlier `ensures` clauses guard later ones (SPEC
only says so for `requires`/`invariant`).

## q02
`build` splits the index range at the middle and ensures `size(result) == 2*(hi-lo)+1`, because `size` counts
`Empty` leaves too. `count_nodes` ensures `2*result+1 == size(t)`, `count_empties` ensures `2*result == size(t)+1`;
both have `decreases size(t)` and a `match`. Unsure: that the verifier knows `size(Node(..)) == 1 + size(l) + size(r)`
and `size >= 0` (SPEC says only "children are smaller"); also that passing a local `Tree` to a parameter does not copy.

## q03
Mutual recursion `value_end` (measure `2*(len-i)`) and `list_end` (measure `2*(len-j)+1`). `list_end` calls
`value_end` at the same position, so it needs the larger measure; it relies on `value_end`'s `ensures` (`i < result`)
for the decrease on its self-call. Unsure: that `decreases` on a public wrapper is allowed (I added it; no `requires`
were added).

## q04
Straight-line code. Unsure: whether `let mut q: Pair = p;` and `let saved: Buf = q.left;` (copies) and
`q.left.data = copy(tmp)` are accepted as written, and whether the verifier tracks `p.left.data[0] == a[0]` through
struct fields without an extra assert.

Nothing was compiled or run (no shell available).
