# Stage 1 B2 `--infer` tests

Spec: `docs/STAGE1_B_INFER.md`. Next to each `inf_*.pruv` there is a `.json` of the same name (the expected values).

## Running

    .venv/bin/python tests/inference/run.py --compiler py|rs [--regress] [--jobs N] [name ...]

- `--compiler`/`--compiler-path`: the same as in `tests/compiler_driver.py` (default rs).
- Each `.pruv` is compiled with `--backend rust` plus the json's `flags` (default `["--infer", "--show-inferred"]`).
  JSON lines on stdout are read as errors, and JSON lines on stderr as `--show-inferred` records.
- `--regress`: additionally checks that `tests/must_reject/*.pruv` are still rejected under `--infer` (including the stage/code in the json next to each),
  and that the `examples/` and `tests/runtime/` tests that have an `exit` key and `bench/solutions/pruv_agg/*.pruv`
  still compile successfully with `--infer`.
- At the end it prints `TOTAL passed/total` and the list of failures; exit 0 if all pass, otherwise 1.

## json format

    {"expect": "ok" | {"stage": "verify", "code": "..."},
     "noinfer": "ok" | "reject",          (optional)
     "kept": ["..."], "dropped": ["..."],  (optional)
     "dropped_round": {"TEXT": round},      (optional: whether that candidate was dropped in that round)
     "status": {"<fn>": "verified|selected|budget_exhausted|timeout|none"},  (optional)
     "absent": ["..."],                    (optional: candidates that must not be generated)
     "fallback": {"<fn>": true | false},   (optional: whether it fell back to version 1)
     "flags": ["--infer", "--show-inferred"],  (optional)
     "note": "what this test looks at"}

- `expect ok`: exit 0. An object: exit 1 with at least one error of that stage/code.
- `kept`: each string is exactly equal to an `invariant TEXT` inside the `invariants` of some record.
- `dropped`: each string is equal to the `dropped[].text` of some record.
- `status`: the `status` of all records of that function is that one value.
- `absent`: each string appears neither in an `invariant TEXT` inside the `invariants` of any record nor in any `dropped[].text` (= it does not appear in the report; candidates cut off by `capped` and the first search records erased by the fallback are not visible to begin with, so this is not a complete proof of "not generated").
- `fallback`: function name → true/false. Whether the records of that function have the key `"fallback": "v1"` (true: all records have it, false: no record has it).
- `noinfer`: compile again without `--infer` and expect `ok` (exit 0) or `reject` (exit 1).

## B+ samples (kinds 12, 13, 14, spec 3.7)

- `inf_range_gcd`: kind 12. The lower bounds `x >= 0` and `y >= 0` from `x = a; y = b` remain, proving `result >= 0` (noinfer reject).
- `inf_prefix_store`: kind 13. The reversal's `forall k in 0..i: out[k] == a[n - 1 - k]` and `len(out) == n` remain, ok (noinfer reject).
- `inf_early_return`: kind 14. The sortedness check's `forall k in 1..i: !(a[k - 1] > a[k])` remains, ok (noinfer reject).
- `inf_rej_range_wrong`: the false kind 12 candidate `x >= 0` is dropped at preservation and only the true `x <= 100` remains, ok.
- `inf_rej_early_domain`: a kind 14 candidate is dropped at the domain check (for the division `10 / a[k]`, `a[k] > 0` is known only for the current i through the loop condition). The function is ok without candidates.
- `inf_rej_prefix_wrong_post`: the kind 13 candidate remains but the ensures (`result[j] == a[j]`) is wrong, giving an `ensures` error.
- `inf_budget_fallback`: fallback to version 1 (spec 4.1). The kind 12 candidate chain `a0 = a1; … a19 = i + 1` (20 of them) exhausts the first search's 512 queries → searching again with kinds 1–11 only leaves `0 <= i` and `i <= n`, ok (noinfer reject). `fallback {"chain": true}`. The `a0 >= 0` etc. in absent are generated in the first search but the fallback erases that record, so here it means "kind 12 is not in the fallback result (the remaining invariants and dropped records)".
- `inf_range_strict`: kind 12's `srng`. It looks at strict inequalities (`a > -5` → lower bound -4, `a < 100` → upper bound 99), `-literal`, and nested `&&` in parentheses (`_conj_terms` recursion). `x >= -4` and `x <= 99` remain, ok (noinfer reject).
- `inf_prefix_copy`: kind 13 where the start value is `copy(a)`. `forall k in 0..i: out[k] == a[k] * 2` and `len(out) == len(a)` remain, ok (noinfer reject).
- `inf_absent_shapes`: three shapes that must not be generated (absent): an early-return `if` with an else, `out[i] = 7` before a counter with step 2, and an `if` whose then has two statements. The function is ok with kind 1's `0 <= i` (noinfer reject).
- The bound name in the ensures is written as `j` so that the candidate's bound name becomes `k` (or `k_1` if there is a `k` in the function).

The expected values were written by following the document's candidate rules by hand, so if they differ from an actual run, first check whether the expected value is wrong rather than the inference.
