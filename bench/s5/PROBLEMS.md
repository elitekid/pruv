# Stage 5 cost-bound problems

Implement each task in its own directory, q01/root.pruv and q02/root.pruv.
Use exactly the public entry signature and contract below, including the cost
clause. Whitespace and line comments may differ. No additional public entries.
The grader compares the complete normalized public header, so an absent or
textually different bound is rejected. Private helpers are unrestricted.

## q01: bounded square-grid traversal

Given an immutable integer array a of length at most 32, count all ordered
index pairs (i, j) with 0 <= i < len(a) and 0 <= j < len(a). Elements do not
affect the result and may be any i64. The empty array has zero pairs.
Implement a bounded nested-loop computation. Preserve the input.

The required bound is `cost len(a) * (len(a) + 1)`: each outer iteration and
each inner iteration costs one unit.

```pruv
pub fn grid(a: [i64]) -> i64
  requires len(a) <= 32
  ensures result == len(a) * len(a)
  cost len(a) * (len(a) + 1)
```

## q02: elementwise doubling with a costed helper

Given an immutable array src of length at most 32 with elements in
[-1000, 1000], return a new array containing twice each element. Preserve src.
Use one alloc or copy, and call a costed helper for each element in a loop.
The empty input produces an empty output.

The required bound is `cost 3 * len(src) + 1`. The allocation/copy costs
1 + len(src), loop entries cost len(src), and helper calls with a zero-unit
helper bound cost len(src).

```pruv
pub fn compute(src: [i64]) -> [i64] ! alloc
  requires len(src) <= 32
  requires forall k in 0..len(src): -1000 <= src[k] && src[k] <= 1000
  ensures len(result) == len(src)
  ensures forall k in 0..len(src): result[k] == src[k] * 2
  cost 3 * len(src) + 1
```

## Exact Python reference

```python
def ref_grid(a):
    return sum(1 for i in range(len(a)) for j in range(len(a)))


def ref_compute(src):
    return [x * 2 for x in src]
```

## Tests

Both tasks use 38 cases: [], [-1000], [1000], [0], [-1000, 0, 1000],
one random array for every length 2 through 32 (random.Random(5005),
randrange(-1000, 1001)), and length-32 arrays filled with each endpoint.
Thus all valid lengths occur, including the maximum-cost length 32.
Each case checks the exact result and unchanged input: 76 assertions.
q01's functional result depends only on length; q02 includes mixed signs,
zeros and endpoints. The same independent oracle and maximum-cost inputs
are used for safe-mode mutant truth runs. Finite tests do not replace proof
over all valid inputs. Implementation structure is reviewed from source;
the automated submission gate checks the public contract and cost text.
