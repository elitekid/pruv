# tests/g9/proof

G9 batch A1 proof fixtures (docs/G9_SPEC.md sections 2, 3, 4, 5, 8 and 11.2). Every `pNN_name.pruv` here must verify
completely in default mode (every contract and every termination obligation proven). `tests/run_all.py` group `g9_proof`
picks them up. None has a `main`, like the A0 frontend samples. Each file starts with a `// G9 A1 proof:` header.

The matching rejections are `tests/must_reject/g9p_*.pruv` with `.json` `{"stage": "verify", "code": ...}`. Each is
type-correct and is meant to fail for one reason.

## Positive fixtures (32)

| Files | Covers |
|---|---|
| p01, p02 | two-function SCCs: shared measure (even/odd), phase measures 2n+1 / 2n |
| p03, p04 | three-function SCCs: shared measure with range ensures, phase measures 3n+2 / 3n+1 / 3n |
| p05, p06, p07 | array descent (`decreases len(a) - i`) with `sum`, `count`, `forall`/`exists` postconditions |
| p08, p09, p10 | tree traversal: contains (variant contracts), size total, depth bounded by size |
| p11, p12 | recursive builders with `alloc`, size of the result (`mirror`, `chain`) |
| p13, p14 | size facts across a struct <-> enum type SCC (mutual functions, constructor equations) |
| p15 | mutual functions over a three-type SCC (Json, Items, Members) |
| p16, p17, p18, p19 | buffer fields: wf of params, wf after loop havoc (with invariant), field reassignment, enum payloads |
| p20, p21, p22 | unit-returning recursive functions with contracts: self, mutual, array walk |
| p23, p24, p25, p26 | generic recursion proven once for opaque T: identity, array length, mutual, element result |
| p27, p29, p30 | scalar measures: two parameters, halving (`n / 2`), linear-bounded accumulation |
| p28, p31, p32 | what may justify a decrease: helper ensures, an earlier call's ensures, a nested call's ensures |

Proof style: no nonlinear arithmetic (only constant factors and literal divisors); results that feed `+` carry bounds
in `ensures` (and `size(t) <= 1000` in `requires`) because `size` is mathematical and code arithmetic is checked for
i64 overflow.

## Rejections (32), all `stage: verify`

| Code | Files (`g9p_` prefix) |
|---|---|
| `recursive_decrease` | unchanged_measure, increasing_measure, cyclic_ensures_false, callee_ensures_decrease, mutual_edge_not_decreasing, phase_measures_equal, three_cycle_edge, array_wrong_measure, tree_swapped_args, generic_unchanged_measure, unit_phase_equal, recursive_on_larger_value, rebuilt_same_value |
| `recursive_nonneg` | negative_entry, negative_entry_recursive, array_missing_upper_bound |
| `call_requires` | missing_callee_requires, array_cursor_skips_end, tree_call_size_bound |
| `ensures` | false_base_case, false_inductive_step, tree_false_size, generic_wrong_ensures, struct_enum_false_size, unit_false_ensures, buffer_u8_range_unproven |
| `variant_domain` | measure_variant_selector |
| `contract_domain` | measure_array_index, measure_div_zero |
| `index_oob` | forgotten_buffer_len |
| `assert` | forgotten_length_after_loop |
| `overflow` | unbounded_result_overflow |

Notes:

- A measure that is negative only at a recursive call cannot be written on its own: the callee's `requires` is proven
  first and the entry obligation covers the same parameters, so a call-site `recursive_nonneg` implies an entry failure.
  The `recursive_nonneg` rejections therefore fail at the entry clause (`negative_entry*`, `array_missing_upper_bound`).
- `cyclic_ensures_false` must fail termination, never prove `false`.
- `callee_ensures_decrease`: only the inner call `shrink(n)` is unchanged; the outer call would decrease if the inner call
  could assume its own ensures.
