# G8 independent problems

Implement each service as a root Pruv module using `mod std;`. Supply
q01/root.pruv and q02/root.pruv. All inputs satisfy the stated preconditions,
i64 scalar bounds and the language array-length bound. Do not mutate inputs.
There are no performance or cost-clause requirements. The host contracts below
are frozen; additional private helpers are allowed.

## q01: array search service

`first_duplicate(a)` returns the smallest index i whose value occurs again at
some j > i, or None if no such i exists. This is the first original occurrence,
not the index where a repeated value is encountered during a forward scan.
For [3,2,2,3] the answer is Some(0), not Some(1) or Some(2).
`checked_total(a,b)` returns Some of the mathematical sum exactly when it fits
i64, and None otherwise. The scalar inputs are independent values.

```pruv
pub fn first_duplicate(a: [i64]) -> Option<i64>
 ensures is_some(result) == (exists i in 0..len(a): exists j in i + 1..len(a): a[i] == a[j])
 ensures is_some(result) ==> (0 <= some_val(result) && some_val(result) < len(a))
 ensures is_some(result) ==> (exists j in some_val(result) + 1..len(a): a[some_val(result)] == a[j])
 ensures is_some(result) ==> (forall k in 0..some_val(result): forall j in k + 1..len(a): a[k] != a[j])

pub fn checked_total(a: i64, b: i64) -> Option<i64>
 ensures is_some(result) == (-9223372036854775808 <= a + b && a + b <= 9223372036854775807)
 ensures is_some(result) ==> some_val(result) == a + b
```

## q02: array summary and reversal service

`bounded_sum(a)` returns the exact sum, including zero for an empty array.
Its inputs have at most 1,000,000 elements, each between -1,000,000,000 and
1,000,000,000 inclusive. These are the std sum preconditions.
`maximum(a)` returns the greatest element and requires a nonempty array;
all i64 element values are valid for this entry.
`reversed(a)` returns a fresh owned array in reverse order, including an empty
result for an empty input. The input remains unchanged.

```pruv
pub fn bounded_sum(a: [i64]) -> i64
 requires len(a) <= 1000000
 requires forall k in 0..len(a): -1000000000 <= a[k] && a[k] <= 1000000000
 ensures result == sum(k in 0..len(a): a[k])

pub fn maximum(a: [i64]) -> i64
 requires len(a) > 0
 ensures result == max(k in 0..len(a): a[k])

pub fn reversed(a: [i64]) -> [i64] ! alloc
 ensures len(result) == len(a)
 ensures forall k in 0..len(a): result[k] == a[len(a) - 1 - k]
```

## Exact Python reference

Python integers provide mathematical arithmetic independently of the compiler.

```python
MIN, MAX = -(2**63), 2**63 - 1

def first_duplicate(a):
    return next((i for i, x in enumerate(a) if x in a[i + 1:]), None)

def checked_total(a, b):
    value = a + b
    return value if MIN <= value <= MAX else None

def bounded_sum(a):
    assert len(a) <= 1_000_000
    assert all(-1_000_000_000 <= x <= 1_000_000_000 for x in a)
    return sum(a)

def maximum(a):
    assert len(a) > 0
    return max(a)

def reversed(a):
    return a[::-1]
```

## Deterministic tests

Executable definitions are `cases`, `ref_duplicate`, `ref_checked` and `driver`
in run.py. Array edges are [], [0], [1], [-1], [1,2,1], [3,2,2,3], [1,1,1],
[-9,-2,-7], [3,2,1], [1,2,3], [0,0], [-10**9,10**9], and 32 copies of
each signed 10**9 bound. Also test each length 2 through 32 with Python
Random(8008), drawing each element with randrange(-5,6).
q01 adds [MIN,MAX,MIN], [MAX,MIN], [MIN]. Every array group checks unchanged
input. Checked arithmetic uses the Cartesian product
[MIN,MIN+1,-2,-1,0,1,2,MAX-1,MAX] by [MIN,-1,0,1,MAX].
q01 has 141 assertions and q02 has 179 per configuration. Empty arrays never
go to maximum. Tests sample inputs; verification proves the complete domains.
