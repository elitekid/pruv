# G2 problems (u8 arrays, bool arrays, UTF-8 strings)

Each solution is one Pruv file `qNN.pruv` (language rules: SPEC.md; a G2 summary will be added there later).
Define the function with exactly the given name and parameter/return types. Helper functions are allowed.
Inputs always satisfy the stated constraints. The function must prove (verify) and must not panic.
Write `requires` that state the input constraints (the compiler needs them to prove no overflow / in-bounds),
and `ensures` that describe what the result means.

Type mapping used by the grader: `[i64]` is passed as `&[i64]`, `[u8]` as `&[u8]` (result `Vec<u8>`),
`[bool]` as `&[bool]`, `str` as `&str` (result `String`). The grader compares the result (Rust `Debug`
output) with a trusted reference.

---

## q01 — byte range conversion

`fn clamp_bytes(a: [i64]) -> [u8] ! alloc`

- Constraints: elements are arbitrary i64; `len(a) <= 1_000_000`.
- Meaning: same length as `a`; `out[k] = min(max(a[k], 0), 255)`.
- Example: `[-5, 7, 300]` -> `[0, 7, 255]`.

## q02 — ASCII filter

`fn ascii_mask(a: [u8]) -> [u8] ! alloc`

- Constraints: `len(a) <= 1_000_000`.
- Meaning: same length as `a`; `out[k] = a[k]` if `a[k] < 128`, otherwise 63 (`'?'`).
- Example: `[65, 200, 127, 128]` -> `[65, 63, 127, 63]`.

## q03 — saturating u8 array update

`fn add_sat(a: [u8], d: i64) -> [u8] ! alloc`

- Constraints: `-255 <= d <= 255`; `len(a) <= 1_000_000`.
- Meaning: same length as `a`; `out[k] = min(max(a[k] + d, 0), 255)`.
- Example: `a = [0, 100, 250]`, `d = 10` -> `[10, 110, 255]`; `d = -10` -> `[0, 90, 240]`.

## q04 — longest run of true

`fn longest_true_run(a: [bool]) -> i64`

- Constraints: `len(a) <= 1_000_000`.
- Meaning: length of the longest block of consecutive `true` elements; 0 if there is none.
- Example: `[true, false, true, true, false]` -> 2; `[]` -> 0.

## q05 — count UTF-8 characters

`fn count_chars(s: str) -> i64`

- Constraints: `len(s) <= 1_000_000`.
- Meaning: number of characters (code points) of `s` = number of bytes that are not continuation bytes,
  i.e. not in 128..=191.
- Example: `"a\u{e9}"` (3 bytes) -> 2; `"\u{1F600}"` (4 bytes) -> 1.

## q06 — prefix by characters

`fn prefix_chars(s: str, k: i64) -> str ! alloc`

- Constraints: `0 <= k <= 1_000_000`; `len(s) <= 1_000_000`.
- Meaning: the first `k` characters of `s` as a new string; if `s` has fewer than `k` characters, a copy of
  all of `s`. The cut must fall on a character boundary.
- Example: `("a\u{e9}b", 2)` -> `"a\u{e9}"`; `("ab", 5)` -> `"ab"`; `(s, 0)` -> `""`.
