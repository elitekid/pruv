# Independent-author notes

- Read only `SPEC.md` and `bench/g7/PROBLEMS.md`. No compiler, verifier, grader, or tests were run.
- Assumed an owned local primitive array can be returned directly, without `move` or another `copy`. The spec explicitly requires copying borrowed array parameters but is less explicit about the syntax for returning owned array locals.
- Interpreted q01 as allowing copies before the parallel group; both actual transforms occur inside it. Helper contracts use `old(dst)` for the original copy and preserve every element outside the requested range.
- Interpreted q02 as allowing output allocation before the parallel group. Both branches receive the same read-only `src`, with separate mutable outputs.
- Relied on section 6's empty-range contract semantics: the quantified q02 postcondition does not evaluate `src[0]` when the input is empty. The implementation also returns from the relative-value helper before reading that element.
- Contracts and loop invariants were written to support modular default verification, including byte bounds, overflow safety, and frame preservation. Actual verifier acceptance and solver timing remain unconfirmed because execution was prohibited.
