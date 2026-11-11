# Notes

**q01.** I could not run the compiler. I assumed `vec_get::<i64>(v, i)` borrows `v` and requires `0 <= i < len(v)`. I also assumed `vec_push` keeps the earlier elements, so the `v[i - 1] == s` invariant holds. The `len(v) <= i` invariant is there so `vec_push` can be proved to have room.

**q02.** This is the least certain file. The histogram invariant quantifies over every i64 key, using the range `MIN..MAX+1` written with contract arithmetic. I assumed `map_lookup::<i64, i64>(m, x)` returns an Option, so I used `is_some`/`some_val` on it. I also assumed `map_insert` returns the new map and that `len(m)` works on a map. The verifier may time out on the nested quantifiers and counts, or fail to instantiate them. A weaker fallback would be a smaller invariant, but it cannot prove the full `ensures`. Repair: the verifier timed out on the all-keys invariant, so the loop invariants now talk only about the queried key `q` (count > 0 means the entry equals the count, count == 0 means it is absent).

**q03.** I wrote `string_new()` and `string_push_str(move s, x)` without type arguments, because the spec only requires them for generic operations. I assumed `string_to_str(s)` borrows `s` and gives a `str` with the same length and bytes. The three `forall` clauses rely on `string_push_str` keeping the prefix and appending the new bytes. I used a separate name for each intermediate String so the facts about earlier versions stay available.

**q04.** The declaration is copied from PROBLEMS.md. The wrappers branch on `parse_digit(..) >= 0`. This follows from its ensures: the result is >= 0 exactly when D holds. I did not check `-1` as a literal in `return -1;`; it should parse as unary minus.
