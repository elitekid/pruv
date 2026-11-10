# Problems
Each solution is one file `pNN.rs` (Rust) or `pNN.pruv` (Pruv) defining the function below (helpers allowed).
Unless stated: 0 <= len(a) <= 1_000_000, every element and x in [-1_000_000_000, 1_000_000_000].
Inputs always satisfy the constraints. Solutions must not panic.

- p01 `sum_array(a: &[i64]) -> i64` — sum of elements.
- p02 `max_element(a: &[i64]) -> Option<i64>` — maximum, None if empty.
- p03 `is_sorted(a: &[i64]) -> bool` — true iff non-decreasing.
- p04 `binary_search(a: &[i64], x: i64) -> Option<i64>` — a is sorted non-decreasing; smallest index i with a[i] == x, else None. O(log n).
- p05 `prefix_sums(a: &[i64]) -> Vec<i64>` — length len(a)+1, out[0] = 0, out[i+1] = out[i] + a[i].
- p06 `max_subarray(a: &[i64]) -> i64` — len(a) >= 1; max sum of a non-empty contiguous subarray.
- p07 `count_less(a: &[i64], x: i64) -> i64` — number of elements < x.
- p08 `reverse(a: &[i64]) -> Vec<i64>` — reversed copy.
- p09 `dot(a: &[i64], b: &[i64]) -> Result<i64, i64>` — Err(1) if lengths differ, else Ok(sum a[i]*b[i]). Here elements are in [-1_000_000, 1_000_000].
- p10 `gcd(a: i64, b: i64) -> i64` — 0 <= a, b <= 1_000_000_000_000; gcd(0, 0) = 0.

Pruv type mapping: `&[i64]`/`Vec<i64>` -> `[i64]`, `Result<i64, i64>` -> `Result<i64>`.
