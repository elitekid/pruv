# indep1 notes

## q01
- Assumed `file_read_all` on a failed handle gives `file_ok == false` (-1), and `file_size` is the byte count read, so I check `> 10_000_000` after the ok test.
- The spec never says whether `alloc(n, 0)` is known to give `len == n`; I assumed so and also put `len(out) == n` in the invariant. I assumed `file_size(g)` stays equal to `n` while `g` is only borrowed (added as an invariant).
- Unclear: is `file_close` allowed on a handle with `file_ok == false`, and is its bool result allowed to go unused? I assumed both are fine and bound the bool to a named local. I closed the input explicitly before `file_create` to make equal paths safe, although the spec says drop would do it.
- Opening output: `file_writable` is the check (spec: "writable iff ok"). After `file_write_bytes` I rely only on `file_close` returning false for a failed write ("true only if ok and final flush succeeds").
- Confusing: whether names starting with `_` (e.g. `_unused`) are legal; I avoided them. The spec doesn't say whether `ensures` literal returns like `return -3;` accept unary minus on a literal in code (assumed yes).

## q02
- Assumed code `&&` is short-circuit for proof purposes, but used nested `if`s for `file_byte(g, n - 1)` to avoid depending on it.
- Bounds proof: `lines <= lf + 1`, `fields <= lf + commas + 1 <= 4097`, so the result is at most `4097 * 10000 + 4097`, which equals the `ensures` bound exactly. No tighter invariant was needed.
- The spec doesn't say whether a long `ensures` constant expression like `4097 * 10001` is evaluated mathematically (assumed yes).
- Unclear if `else if` with only a single inner `if` needs the nested form I used; I used nested to be safe.
