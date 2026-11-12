# Assumptions

- Inputs satisfy the frozen preconditions and the language's i64 and array-length bounds.
- The bundled std functions expose the mathematical sum, maximum, checked-addition, and reversal guarantees described in SPEC.md section 6k; no external contract files were consulted.
- The verifier can instantiate the quantified prefix invariants and explicit existential witnesses in first_duplicate. Its quadratic scan is acceptable because there is no performance requirement.
- These are first-attempt implementations based only on SPEC.md and PROBLEMS.md. No compiler, verifier, or tests were run.
