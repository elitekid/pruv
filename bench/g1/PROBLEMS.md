# G1 problems (structs and enums)

Each solution is one Vow file `gNN.vow` (spec: SPEC.md, especially section 6a). Copy the **type declarations**
of the problem into the file verbatim (names, field names, field order, variant order must match exactly), then
define the function with exactly the given name and parameter/return types. Helper functions are allowed.
Inputs always satisfy the stated constraints. The function must prove (verify) and must not panic.
Write `requires` that state the input constraints (the compiler needs them to prove no overflow / in-bounds),
and `ensures` that describe what the result means.

Type mapping used by the grader: `[i64]` is passed as `&[i64]`; structs/enums are passed by value
(`sol::Rect`, `sol::Op::Add(5)`, ...). The grader compares the result (Debug output) with a trusted reference.

---

## g01 — overlap area of two rectangles

```
struct Point { x: i64, y: i64 }
struct Rect { lo: Point, hi: Point }
```
`fn overlap_area(a: Rect, b: Rect) -> i64`

- Constraints: every coordinate in [-1_000_000_000, 1_000_000_000]; for each rectangle `lo.x <= hi.x` and `lo.y <= hi.y`.
- Meaning: area of the intersection of the two axis-aligned rectangles (the region with `lo.x <= x <= hi.x`
  style extents, area = width * height). If the intersection has zero width or zero height, or they do not
  overlap, the result is 0. Touching edges give 0.

## g02 — calculator step

```
struct Acc { value: i64, steps: i64 }
enum Op { Add(v: i64), Mul(v: i64), Neg, Clear }
```
`fn apply(acc: Acc, op: Op) -> Acc`

- Constraints: `-1_000_000_000 <= acc.value <= 1_000_000_000`, `0 <= acc.steps <= 1_000_000_000`;
  `Add(v)`: v in [-1_000_000_000, 1_000_000_000]; `Mul(v)`: v in [-1_000, 1_000].
- Meaning: apply one operation. `Add(v)`: value += v. `Mul(v)`: value *= v. `Neg`: value = -value.
  `Clear`: value = 0. In every case `steps` increases by exactly 1.

## g03 — statistics in one pass

```
struct Stats { count: i64, sum: i64, min: Option<i64>, max: Option<i64> }
```
`fn stats(a: [i64]) -> Stats`

- Constraints: `0 <= len(a) <= 1_000_000`, every element in [-1_000_000_000, 1_000_000_000].
- Meaning: `count` = number of elements, `sum` = their sum, `min` / `max` = smallest / largest element,
  `None` for both when the array is empty.

## g04 — shape measures

```
struct Measure { area: i64, perimeter: i64 }
enum Shape { Circle(r: i64), Rect(w: i64, h: i64), Tri(a: i64, b: i64, c: i64, h: i64) }
```
`fn measure(s: Shape) -> Measure`

- Constraints: every payload value in [0, 1_000_000].
- Meaning (integer approximation):
  - `Circle(r)`: area = 3*r*r, perimeter = 6*r.
  - `Rect(w, h)`: area = w*h, perimeter = 2*(w+h).
  - `Tri(a, b, c, h)`: sides a, b, c; h is the height onto side c. area = c*h/2 (integer division, rounds down),
    perimeter = a+b+c. (No triangle inequality is required.)

## g05 — first negative element

```
enum Found { Nothing, At(index: i64, value: i64) }
```
`fn first_negative(a: [i64]) -> Found`

- Constraints: `0 <= len(a) <= 1_000_000`, every element in [-1_000_000_000, 1_000_000_000].
- Meaning: if some element is negative, return `At(index, value)` for the smallest such index (`value == a[index]`);
  otherwise `Nothing`.
