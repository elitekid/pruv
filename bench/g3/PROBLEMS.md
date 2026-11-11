# G3 problems (generics)

Each solution is one Pruv file `qNN.pruv`. The language rules are in SPEC.md (section 6c, Generics). Nothing else
is needed.

Rules common to all four problems:

- Define the generic function with exactly the given name, type parameters and signature. Helper definitions are allowed.
- Generic functions are not exported (SPEC 6c), so the grader calls **concrete wrappers**: non-generic functions with
  exactly the given names and types, each calling one instance of your generic function (`f::<i64>`, `f::<bool>`, ...).
  Every wrapper is tested with both `T = i64` and `T = bool` instances where listed.
- The file must verify (no `--no-verify`), on both compilers and both backends, and must not panic on the test inputs.
- State the **full meaning** in `ensures`: the contract of the generic function and of every wrapper must determine the
  result completely (for the given inputs there is exactly one result that satisfies the `ensures`). A weaker contract
  such as `ensures true` or only `len(result) == len(a)` is a failed attempt, even if the tests pass.
  Write `requires` for every input condition you rely on.
- The grader compares the wrapper's result (Rust `Debug` text) with a trusted reference. A wrapper whose `requires`
  fails must panic with `pruv: requires violated` (checked on the Rust backend only).

Type mapping at the wrapper boundary: `i64` is `i64`, `bool` is `bool`, `[i64]` is `&[i64]` (result `Vec<i64>`),
`[bool]` is `&[bool]` (result `Vec<bool>`).

Test inputs: `I = {i64::MIN, -1, 0, 1, 2, 7, i64::MAX}`, `B = {false, true}`. Array inputs are all arrays of length 0..=3
over `{0, 1}` (`i64`) or `{false, true}` (`bool`), plus 12 seeded random arrays of length 4..=9 and one array of
length 40. The exact generator is `tests()` in `run.py`.

---

## q01 — generic pair swapping

Declare

```
struct Pair<A, B> { first: A, second: B }
fn swap<A, B>(p: Pair<A, B>) -> Pair<B, A>
```

- Meaning: `result.first == p.second` and `result.second == p.first`.
- Wrappers (each builds a `Pair`, calls `swap::<..>`, returns the named field of the swapped pair; each states
  `ensures result == <the input it must return>`):

| wrapper | instance | returns |
|---|---|---|
| `fn swap_ib_first(a: i64, b: bool) -> bool` | `swap::<i64, bool>` | `b` |
| `fn swap_ib_second(a: i64, b: bool) -> i64` | `swap::<i64, bool>` | `a` |
| `fn swap_bi_first(a: bool, b: i64) -> i64` | `swap::<bool, i64>` | `b` |
| `fn swap_bi_second(a: bool, b: i64) -> bool` | `swap::<bool, i64>` | `a` |
| `fn swap_ii_first(a: i64, b: i64) -> i64` | `swap::<i64, i64>` | `b` |
| `fn swap_bb_first(a: bool, b: bool) -> bool` | `swap::<bool, bool>` | `b` |

- Tests: `I x B` for the first four, `I x I` for `swap_ii_first`, `B x B` for `swap_bb_first`.

## q02 — generic Option fallback

`fn get_or<T>(o: Option<T>, d: T) -> T`

- Meaning: if `o` holds a value, the result is that value; otherwise the result is `d`
  (contract: `is_some(o) ==> result == some_val(o)` and `!is_some(o) ==> result == d`).
- Wrappers (build `Some::<..>(v)` when `has` is true and `None::<..>` otherwise; state
  `has ==> result == v` and `!has ==> result == d`):
  - `fn get_or_int(has: bool, v: i64, d: i64) -> i64`  (`get_or::<i64>`)
  - `fn get_or_bool(has: bool, v: bool, d: bool) -> bool`  (`get_or::<bool>`)
- Tests: `B x I x I` for `get_or_int`, `B x B x B` for `get_or_bool`.
  Example: `get_or_int(true, 5, 9) == 5`, `get_or_int(false, 5, 9) == 9`.

## q03 — first element of a nonempty generic array

`fn first<T: Element>(a: [T]) -> T`

- Constraint: `len(a) > 0` (state it as `requires`).
- Meaning: the result is `a[0]` (`ensures result == a[0]`).
- Wrappers (same `requires` and `ensures` as the generic function):
  - `fn head_int(a: [i64]) -> i64`  (`first::<i64>`)
  - `fn head_bool(a: [bool]) -> bool`  (`first::<bool>`)
- Tests: every nonempty array of the input set, for both wrappers. Probe (Rust backend only): the empty array must
  panic with `pruv: requires violated`.
  Example: `head_int([4, 5, 6]) == 4`.

## q04 — generic array copy with a pointwise postcondition

`fn copy_all<T: Element>(a: [T]) -> [T] ! alloc`

- Meaning: the result has the same length as `a` and every element equals the element of `a` at the same index
  (`ensures len(result) == len(a)` and `ensures forall k in 0..len(a): result[k] == a[k]`).
- Wrappers (same `ensures`):
  - `fn copy_int(a: [i64]) -> [i64] ! alloc`  (`copy_all::<i64>`)
  - `fn copy_bool(a: [bool]) -> [bool] ! alloc`  (`copy_all::<bool>`)
- Tests: every array of the input set (including the empty array), for both wrappers.
  Example: `copy_int([3, -1]) == [3, -1]`.

---

Reference solutions: `solutions/ref/q01.pruv` .. `q04.pruv`. Grader: `python3 bench/g3/run.py <solutions_dir>`.
