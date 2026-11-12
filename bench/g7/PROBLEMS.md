# G7 parallel-call problems

Implement each problem in its own directory, `q01/root.pruv` and
`q02/root.pruv`. Both must use an actual `par { ... }` group containing
the two computations. The grader checks the group and freezes the public
signatures and contracts below (whitespace and comments may differ).
Private helper names and implementation techniques are unrestricted.
Do not add public host entries.

## q01: independent bounded byte transforms

Given two immutable byte arrays, independently transform owned copies in one
parallel group. On the half-open range [lo, hi), add c to the first array with
saturation at 255 and add c to the second array modulo 256. Preserve every
position outside the range exactly. Return the first result when pick is 0,
or the second when pick is 1; compute both before selecting. The arrays may
have different lengths. Both input arrays must remain unchanged.

The domain is 0 <= lo <= hi <= min(len(a), len(b)), 0 <= c <= 255,
and pick in {0, 1}. Empty inputs/ranges are valid.

Required host entry and exact contract:

```pruv
pub fn transform(a: [u8], b: [u8], lo: i64, hi: i64, c: i64, pick: i64) -> [u8] ! alloc
  requires 0 <= lo && lo <= hi && hi <= len(a) && hi <= len(b) && 0 <= c && c <= 255
  requires pick == 0 || pick == 1
  ensures pick == 0 ==> len(result) == len(a)
  ensures pick == 1 ==> len(result) == len(b)
  ensures forall k in 0..len(result): (pick == 0 && lo <= k && k < hi && a[k] + c <= 255) ==> result[k] == a[k] + c
  ensures forall k in 0..len(result): (pick == 0 && lo <= k && k < hi && a[k] + c > 255) ==> result[k] == 255
  ensures forall k in 0..len(result): (pick == 1 && lo <= k && k < hi) ==> result[k] == (b[k] + c) % 256
  ensures forall k in 0..len(result): (pick == 0 && (k < lo || k >= hi)) ==> result[k] == a[k]
  ensures forall k in 0..len(result): (pick == 1 && (k < lo || k >= hi)) ==> result[k] == b[k]

```

## q02: two views of one immutable signal

From one immutable bounded integer array, compute two arrays in one parallel
group. Both branches must receive the same input as a read-only argument.
The first output contains twice each input value. The second output contains
each input value minus the first input value. Return the first output for
pick 0, the second for pick 1; compute both before selecting. Preserve the
input exactly. An empty input produces an empty output without reading src[0].

The domain is len(src) <= 4096, every element in [-1000, 1000], pick in {0, 1}.

Required host entry and exact contract:

```pruv
pub fn compute(src: [i64], pick: i64) -> [i64] ! alloc
  requires len(src) <= 4096 && (pick == 0 || pick == 1)
  requires forall k in 0..len(src): -1000 <= src[k] && src[k] <= 1000
  ensures len(result) == len(src)
  ensures forall k in 0..len(src): pick == 0 ==> result[k] == src[k] * 2
  ensures forall k in 0..len(src): pick == 1 ==> result[k] == src[k] - src[0]

```

## Exact Python reference

```python
def ref_transform(a, b, lo, hi, c, pick):
    left = [min(255, x + c) if lo <= k < hi else x for k, x in enumerate(a)]
    right = [(x + c) % 256 if lo <= k < hi else x for k, x in enumerate(b)]
    return (left, right)[pick]


def ref_compute(src, pick):
    return [2 * x if pick == 0 else x - src[0] for x in src]

```

## Grading tests

Deterministic seed 7007. q01 tests empty and singleton arrays, 0/255 endpoints,
all 256 byte values, random lengths 2/7/31/64, unequal array lengths, empty,
full, suffix-empty and interior ranges; c is 0, 1, 127 or 255. Both selectors
are exercised for every case (248 calls, 744 assertions including unchanged
inputs). q02 tests empty/singleton arrays, +/-1000, zeros, constant and mixed
sign arrays, random lengths 2/7/31/64/4096, both selectors (26 calls, 52
assertions including unchanged input). Expected arrays are calculated by the
Python reference and embedded as literal Rust test data. Returned lengths and
all elements are compared exactly. The grader rejects changed public contracts
or a missing par group before compilation.

Passing runtime tests alone does not establish correctness for every input;
default compilation must also prove all contracts and safety obligations.
