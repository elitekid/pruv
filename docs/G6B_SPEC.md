# G6b: Owned Results from Trusted Rust Adapters

Status: accepted design (2026-11-13), extends [G6_SPEC.md](G6_SPEC.md) §3.3 and §13.

Path abbreviations: `P/ = pruvc/`, `C/ = pruvc-rs/crates/pruv-core/src/`,
`V/ = pruvc-rs/crates/pruv-proof/src/`, `D/ = pruvc-rs/crates/pruvc/src/`.

Why: stage L2 ports Lair code that needs a third-party Rust crate (for example `encoding_rs`
to decode bytes into text). Before G6b a user `trusted rust fn` could return only scalars,
so a crate could answer yes/no questions but could not hand text or a list back to Pruv.

## 1. Surface and diagnostics

The result row of G6 §3.3 becomes:

| Position | Allowed | Rust mapping |
|---|---|---|
| Result | Existing i64, bool, (), Option/Result of i64/bool; additionally catalog `String` and exactly `Vec<i64>` | Existing value mappings; owned `::std::string::String`, `::std::vec::Vec<i64>` |

The two additions require `! alloc` on the declaration, even for adapters that happen to return
an empty value. `io` and the other effects still describe the adapter independently.

```pruv
trusted rust fn numbers(text: str) -> Vec<i64> ! alloc
  ensures len(result) == 2
  ensures result[0] == 7 && result[1] == 9
  = "::adapter::numbers";
```

A safe adapter may call a third-party crate internally. Pruv still does not run Cargo
(`--rust-extern` / `--rust-search` as in G6), and no parameter ABI changes.

Still rejected:

| Case | Code |
|---|---|
| Collection parameters, `take`, `inout`, generic foreign declarations, missing ensures | `type/foreign_signature` |
| Other result types: `Vec<bool>`, `HashMap<i64,i64>`, `File`, arrays, `str`, nominal user types (a user type named `String` included) | `type/foreign_signature` |
| Nested owned types (`Option<String>`, `Result<Vec<i64>>`, `Vec<Vec<i64>>`) | existing `type/foreign_owned_type` where the type pass rejects first |
| Aliasing, use after move, borrowed escape, collection host exports | existing ownership/export diagnostics |
| Missing `alloc` on the declaration or a caller | `effect/missing_effect` |

Catalog types are recognized structurally (resolved catalog type, no nominal owner).

Frontend: `P/foreign.py` / `C/foreign.rs` (`allowed_result`, `check_foreign_decl`);
`P/check.py:Checker.fn` / `C/check.rs:fn_` enforce `alloc` after the foreign contracts are
checked and before the foreign-body early return, keeping ordinary signature/type errors first.
LLVM's existing Option/Result trusted-signature restriction (`codegen/unsupported_type`) stays.

## 2. Proof semantics

Each normal return introduces a fresh logical value, independent of earlier calls. Freshness
means a new model with exclusive ownership; it says nothing about contents or addresses.

- `String`: the existing byte-array model `(n, B)`, `0 <= n <= 2^40`, bytes in `0..255`;
  length counts UTF-8 bytes.
- `Vec<i64>`: the existing array model `(n, A)`, `0 <= n <= 2^40`, and for new foreign results
  `forall i, 0 <= i < n ==> I64_MIN <= A[i] <= I64_MAX`.
- Contents are unconstrained except for this well-formedness and the declared ensures. The empty
  postconditions of `vec_new` / `string_new` are not imported.
- Requires are proved before the result and its ensures are assumed. Input models and all other
  owners are preserved.
- `len(result)`, guarded indexing and quantified relations use the existing observers. Contract
  domains are checked even for unused declarations; earlier ensures may establish later domains.
- Rust bodies stay trusted: accepting a declaration proves neither satisfiability nor correctness.

Existing paths: `P/verify.py:FnVerifier.fresh`, `.call`, `.run_foreign`;
`V/symbolic.rs:try_fresh`, `call`, `run_foreign`. No new sort, catalog operation or UTF-8 theory.

## 3. Runtime result checks

Order: evaluate arguments once; existing input checks; selected requires; call the adapter;
check the returned length; selected ensures; publish ownership.

| Mode | Requires | Ensures | Result length |
|---|---|---|---|
| `requires` | checked | trusted | always checked |
| `all` | checked | checked | always checked |
| `off` | omitted | trusted | always checked |

The length check compares the native `usize` length with `2^40` without a truncating cast and
fails with `pruv: invalid representation:` and exit 101. Only then do observers convert the length
to i64. Safe Rust types already guarantee UTF-8 validity and i64 elements, so contents are not
rescanned. `all` evaluates ensures on the returned object itself with the existing checked i128
arithmetic, domain rules and per-call iteration budget. G6 failure prefixes and panic handling
are unchanged; boxing/publication happens only after the checks pass.

## 4. Code generation and ownership

Rust source: `P/foreign_codegen.py:ForeignGen.trusted_helper` and `C/codegen.rs` emit the length
guard between the adapter call and the ensures, with the result in the contract type environment.
String contract support must be emitted for a String-only program (a nullary adapter whose ensures
index result bytes, with no `str` anywhere).

LLVM: G6 §13 collection constructors return `PruvH`; G6b uses the same convention.
`foreign_shim` emits a `PruvH`-returning adapter that calls the typed helper and boxes the result
with `pruv_g6_new`; `llvmgen.trusted_call` emits a `ptr` call that yields a typed collection value
in the expression's ownership context (temporary registration for borrowed fresh results);
`g6_llvm_error` admits exactly the two new result types. The result is boxed once, even when empty,
and joins the existing owner slots, temporary cleanup, move-nullification, reassignment, branch,
loop, early-return and typed-drop paths. Collection-bearing helpers stay internal; host bindings
expose no new handles.

Deferred: the foreign manifest keeps schema `pruv-foreign-v1` and does not yet record trusted
signature types. Bundle digests are already deferred by G6 §13.6; when they are designed, their
canonical input must include full trusted signatures (owned result types included), contracts and
check mode.

## 5. Tests

- Frontend/proof fixtures under `tests/g6/`: both result types with `alloc`; byte length/content
  ensures with multibyte text; `Vec<i64>` length and quantified contents with i64 bounds; moving a
  result through a helper while another owner is preserved.
- Runtime fixtures under `tests/runtime/` with a local adapter (`rust_externs`): empty/ASCII/
  multibyte String, a nullary String-only declaration, empty/nonempty `Vec<i64>` with extrema and
  spare capacity, ownership (temporary, return, reassignment, branch, loop, early return, two live
  results), lying adapters (wrong length, wrong content: `all` fails with the ensures prefix and
  exit 101, `requires`/`off` accept the trusted lie). `g6_drop_balance` on LLVM rows.
- `tests/must_reject/g6b_*`: missing alloc (declaration, caller), `Vec<bool>`/`HashMap`/nominal
  `String` results, owned result plus collection parameter/`take`/`inout`, `Option<String>`,
  unguarded result index in ensures (`verify/contract_domain`), caller asserting content the
  ensures do not give (`verify/ensures`), alias/use after move (`type/foreign_move`).
  `g6_sig_owned_return` (`[i64]` result) stays rejected.

## 6. Batches

| Batch | Files | Exit evidence |
|---|---|---|
| B0 surface | `P/foreign.py`, `P/check.py`, `C/foreign.rs`, `C/check.rs`, rejection fixtures | exact allowlist, alloc rule, unchanged parameter rules |
| B1 proof | `P/verify.py`, `V/symbolic.rs`, proof fixtures | fresh model, domains, element bounds, matching traces |
| B2 Rust helpers | `P/foreign_codegen.py`, `P/codegen.py`, `C/foreign_codegen.rs`, `C/codegen.rs`, runtime fixtures | length before ensures, String-only programs, mode matrix |
| B3 LLVM | `P/llvmgen.py`, `P/foreign_shim.py`, `C/llvmgen.rs`, `C/foreign_shim.rs` | typed handles, temporary ownership, zero live boxes |
