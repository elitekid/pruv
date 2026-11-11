# Related research survey (2026-11-10, survey by Gemini 3.8 Flash + some direct checks)

> Rename (2026-11-10): "Vow" in this document is today's **Pruv**. It is a record from that time, so the body is left as is.

The original is on the Lair delegation card (07a03351). Below is only what is to be used in the Vow blueprint.
Marks: ✔ opened and checked directly · ? not checked (as presented by the surveyor)

## Lessons to reflect in the blueprint right away

| Stage | Lesson | Source |
|---|---|---|
| 1 Invariant inference | LLMs easily write contracts that are "true but useless" (`ensures true`). Houdini-style candidate elimination or cross-checking code, spec, and description is needed | Houdini(2001) ?, Clover(2023) ? arxiv.org/abs/2310.17807 |
| 2 AI writing verified code | Sorting verifier errors by type and turning them into concrete instructions raises the success rate a lot. Verus macros and borrowing rules are a heavy burden for LLMs | DafnyBench best 68% ✔ arxiv.org/abs/2406.08467, AutoVerus ? arxiv.org/abs/2409.13082 |
| 2 Aggregate functions | If sum and count are defined recursively, the SMT solver falls into matching loops. We should go with **built-in aggregates + automatic lemma injection**. Encode count as a multiset | Dafny, Why3 int.Sum, Verus trigger docs ? |
| 3 Automatic testing | Find counterexamples first with PBT before proving, and leave contracts whose proofs fail as runtime checks (graceful degradation) | DSpec2Test ✔ arxiv.org/abs/2609.29713, QuickCheck |
| 4 Separating optimization | Guarantee the equivalence of schedule transformations by effect analysis, as Exo does. Search with a cost model + beam search | Halide, Exo, TVM, AlphaDev ? |
| 6 Multiple outputs | Erase contracts and ghost code without a trace. When lowering unbounded integers to i64, the range proof is the key | Dafny backend, Low*/KaRaMeL, Aeneas ? |
| 5 Structural performance | Timers, watchers, and signals leak in a reactive graph without ownership or scope cleanup. Cost contracts reduce to linear programming, as in RAML | Adapton, Salsa, Incremental, Svelte runes, RAML ? |

## Developer opinion (surveyor's summary, original not checked)
- Martin Kleppmann's post "AI will make formal verification mainstream" got strong support on HN. The surveyor said it was December 2024, but the year was not checked.
- There are concerns about "garbage spec → verified garbage" and AI reward hacking (passing the verifier with trivial contracts).
- z3 instability: a trivial change can jump from milliseconds to a timeout. Many opinions say a hybrid mixing proofs and runtime checks is needed.

## Competitors and how Vow differs
| Competitor | Strength | Where Vow may differ |
|---|---|---|
| Dafny | The most polished contract language, multiple outputs | Designed for humans (triggers, manual lemmas). Vow is for AI: built-in aggregates, automatic lemmas |
| Verus | Rust-level performance | Borrowing rules and macros are hard for LLMs. No output other than Rust |
| Exo | Verified schedule separation | Limited to accelerator kernels |

Candidates for Vow's novelty: ① a syntax for AI that avoids SMT pitfalls (built-in aggregates) ② a continuous grading from proof to testing ③ verified AI schedule search ④ combining incremental computation with cost contracts.

## Proposed blueprint changes
- Stage 2: state **built-in aggregates + automatic lemmas** explicitly, not "recursively defined aggregates".
- Stage 3: make the option of leaving a failed proof as a runtime check the default, instead of treating it as a build failure.
- Add "trivial contract detection" to Stage 0 (warn when an ensures is true even without the code). This prevents reward hacking.
