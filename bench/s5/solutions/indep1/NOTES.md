# Independent-author notes

- Read only `SPEC.md` and `bench/s5/PROBLEMS.md` (read-only `cat`/`sed` on those two files). No compiler, verifier, grader, or tests were run.
- Cost counting follows SPEC.md section 6j: one unit per loop-body entry, `1 + callee bound` per ordinary call, `1 + length` per alloc/copy, zero for everything else used.
- q01 counts each ordered index pair once. At the outer loop head the count is `i * n` and `spent == i * (n + 1)`; at the inner loop head they are `i * n + j` and `i * (n + 1) + 1 + j`. On exit the count is `n * n` and spent is `n * (n + 1)`.
- q02 allocates once and calls a private `twice` helper per element. The helper has no loops, calls or allocations, so its bound is `cost 0`. After `i` processed elements `spent == 1 + n + 2 * i`, and on exit `3 * n + 1`.
- Both inputs are read-only. Empty input gives 0 for q01 and a new empty array for q02.
- Lengths are at most 32, so q01's result is at most 1024 and q02's products lie in [-2000, 2000]; indices and arithmetic were meant to be justified by the preconditions and loop invariants.
- Actual parsing, proof and runtime results were not confirmed by the author.
