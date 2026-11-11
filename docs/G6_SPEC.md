# G6: Calling Rust Functions — Trusted Contracts and Standard Collections

Status: **Design proposal, 2026-11-12. Not implemented or execution-tested by this document.**

G6 supplies a small, explicit trust boundary to the Rust ecosystem. It depends on completion of **G3a exactly as specified in `docs/G3_SPEC.md`**, not on an expanded interpretation of its type parameters. Numerical gates below are acceptance requirements, not measurements.

## 0.0 Confirmed decisions for this design

“Confirmed” means fixed within this proposed implementation contract, not prior project approval.

1. A bodyless `trusted rust fn` associates a Pruv signature and contracts with a Rust path. The compiler proves callers satisfy `requires`, then assumes `ensures` on normal return. It does not prove the Rust implementation.
2. User declarations initially have **concrete signatures**: scalar/value results and read-only scalar, array, or `str` inputs as specified in §3.3. Rust adapters can hide larger libraries behind this surface. Arbitrary foreign opaque types and user-defined foreign generics are deferred.
3. The first owned foreign types are the fixed catalog `Vec<T>`, `HashMap<K,V>`, and `String`. They are separate from G3a's copyable `Value` universe. `T` and `V` remain G3a values; `K: Element` means exactly `i64` or `bool`.
4. Ownership is affine: explicit `move`, call-scoped read-only borrowing, automatic drop. Updates consume a collection and return its replacement. No mutable references, escaped views, or general lifetime system are introduced.
5. Collection payloads cannot own resources. `Vec<Vec<i64>>`, `Option<String>`, owned fields, and instantiating an ordinary `T` with a collection remain invalid. `[T]` still requires `T: Element`; `u8` is still storage-only.
6. Collection observations describe contents, not addresses or capacity. Vec is a sequence, String a UTF-8 byte sequence, and HashMap a finite map with extensional key equality.
7. `--foreign-checks=requires|all|off` controls boundary contract checks. The default is `requires`; `all` also checks postconditions; `off` is permitted only with verification. `--trust-callers` does not change this setting or representation checks.
8. A trusted contract includes effect honesty, memory safety, borrowing/frame behavior, and normal-return results. Runtime checks detect some violations; they do not prove a foreign library safe, terminating, or correctly specified.
9. Both backends ship in G6. Rust source uses typed direct `::std::...` or external-crate path calls. LLVM uses generated Rust `extern "C"` shims, compiled and linked by rustc; it never calls Rust's native ABI directly.
10. LLVM collections are opaque pointers to Rust-owned boxes. Only Rust shims construct, inspect, update, and destroy them. G2 buffers retain runtime ABI v2; a separate G6 bridge marker prevents mismatched shim links.
11. Collection-bearing Pruv function signatures are internal-only in this release. Host entry points use existing Pruv value/array/`str` signatures and may use collections internally. `--rust-bindings` remains the Rust-to-Pruv direction.
12. Python first, Rust port in the same batch, then cross-check. Unsupported intermediate layers reject explicitly, including under `--no-verify`. No G6 completion claim before both backends and all release gates pass.

### 0.0.1 Implementation sequence

| Batch | Deliverable | Minimum exit evidence |
|---|---|---|
| A0 | Boundary manifest, G3a baseline, syntax/types/ownership | 24 accepted frontend cases, 40 frontend rejection files, identical checked dumps |
| A1 | Trust-aware proof and collection models | 24 positive proof cases, 20 reused-code rejection files, identical obligation traces |
| A2 | Rust backend and executable boundary checks | 24 runtime fixtures, mode matrix, false-contract and cleanup probes |
| A3 | LLVM shim, build integration, bindings compatibility | Same 24 fixtures on LLVM, 16 ABI/build probes, identical generated artifacts |
| A4 | Integrated release and audits | At least 60 rejection files, full regression/cross-check, no required audit findings |
| Q | Mutation, fuzzing, measurements, independent use | Three seeds × 100 programs, 60 classified mutants, four independent-use problems |

## 1. Scope and current foundation

### 1.1 Repository facts read for this proposal

These are source observations, not results of running the compiler. Some G3 groundwork is already present; this document does not infer G3a completion from that groundwork.

| Area | Observation and implication | Evidence |
|---|---|---|
| Roadmap | The new order is G3, performance check, G6, then G9/G4/G5. G6 opens L2; L2's table also names G9 for richer data. G6 alone does not deliver all L2 data structures. | `BLUEPRINT.md` §4, general-feature and Lair tracks |
| Ecosystem | Rust libraries are to be reused; guarantees depend on attached trusted contracts. | `BLUEPRINT.md` §5 |
| G3 foundation | Explicit type arguments, verification before specialization, copyable parameters, and `Element = {i64,bool}` are required. §9.3 explicitly leaves movement, borrowing, destruction, boundary validity, and contract models to the next design. | `docs/G3_SPEC.md` §§0.0, 3, 5, 9.3 |
| Current type work | Python has structured type formatting/substitution and `is_value`; the checked-in Rust AST still exposes string-based type fields. These are observations of this checkout, not a replacement for the G3a contract. | `pruvc/typeinfo.py`, `pruvc-rs/crates/pruv-core/src/ast.rs` |
| Ownership today | Arrays/`str` have borrowed parameters, independent owned allocation/copy results, and no owned aggregate fields. | `SPEC.md` §§4–7, `docs/G2_SPEC.md` §§3.3–3.6, `pruvc/check.py` |
| Modular calls | Both verifiers prove callee preconditions and assume postconditions; they rely on separate checking of the callee's contract domain. Foreign declarations need that domain pass even without a body. | `pruvc/verify.py` call handling, `pruvc-rs/crates/pruv-proof/src/symbolic.rs` call handling |
| Runtime contracts | Rust generation uses i128 contract arithmetic and checked partial operations. LLVM tracks owned temporaries and emits unchecked arithmetic/indexing only in proof mode. | `pruvc/codegen.py`, `pruvc/llvmgen.py` |
| Buffer ABI | Runtime v2 allocation/copy/free receives element size/alignment; generated Rust bindings use matching allocation helpers and typed bool/string entries. This does not expose a native growable Vec's capacity. | `pruvc/runtime.c`, `pruvc-rs/crates/pruv-core/src/bindings.rs`, `docs/G2_SPEC.md` §5 |
| Link driver | The current standalone link path uses a system C driver, accepts host targets only, and rejects Windows linking. A Rust-dependent link path is new work. | `pruvc-rs/crates/pruvc/src/link.rs` |
| Existing CLI | Backend/output choices and `--rust-bindings` are already distinct. Python produces source; the canonical Rust driver also handles object/executable emission. | `pruvc/pruvc.py`, `pruvc-rs/crates/pruvc/src/cli.rs`, `pruvc-rs/crates/pruvc/src/driver.rs` |
| Regression | The cross-check runner currently lists 12 stages, including four ABI stages; regression rows and source-file counts are different quantities. | `tests/m3_all.py`, `tests/run_all.py` |
| Prior measurements | G2 measured copy/UTF-8 costs; the later performance check attributes p04 to algorithm, p08 to zero initialization, and p03 to Rust-source loop shape. These are not G6 overhead measurements. | `RESULTS.md` §§43–44 |

`docs/M1_LLVM_SPEC.md` supplies the original body/entry/ABI split and ownership cleanup model. Its original v1 allocation signatures and platform caveats are historical; G2's v2 specification and current code take precedence. No claim here treats the historical proposed `[i32]` portions of G2 as implemented.

### 1.2 Included

- Pure Rust scalar computation with explicit trusted contracts, and concrete adapter calls with `alloc`/`io` effects.
- Growable Vec accumulation, scalar-key map insertion/lookup, and incremental String construction.
- Passing collections through generic Pruv helper functions without changing what an ordinary type parameter admits.
- Content proofs, ownership checking, cleanup, boundary diagnostics, both execution backends, and auditable build inputs.
- G2 arrays and immutable `str` at adapters and public Pruv entry points.

### 1.3 Non-scope

- Cargo/package resolution, automatic downloads, modules/visibility syntax, generated contracts from Rust source, or verification of Rust bodies.
- General foreign object declarations, Rust traits, arbitrary `Hash`/`Eq`, custom allocators/hashers, callbacks, closures, references as values, async, threads, and dynamic libraries.
- Collection iteration APIs, capacity/reserve APIs, removal/pop, nested owned payloads, resource-owning Result/Option, or borrowing collection storage as a returned slice.
- General mutation permissions (G5), recursive/owned fields (G9), refined I/O/resource protocols (G10), and A6 narrow scalar/storage extensions.
- A guaranteed no-panic/no-OOM/termination theorem for foreign calls, or an assertion that checking ensures eliminates trust.

## 2. Syntax

### 2.1 Concrete foreign declarations

```text
ForeignDecl ::= "trusted" "rust" "fn" Ident "(" Params ")" "->" Type
                [Effects] Contracts "=" RustPathString ";"
RustPath    ::= "::" Ident ("::" Ident)*
```

The path string contains only the grammar above: no Rust source, generic arguments, whitespace, macros, or arbitrary expressions. The first segment is `std` or an explicitly supplied external crate name. No `crate`, `self`, or `super` roots. Signatures are concrete and checked against §3.3; the generated typed Rust call lets rustc resolve ordinary Rust generic inference, such as `std::cmp::min` at i64. A Rust method or unsupported signature needs a small free-function adapter in a supplied crate.

```pruv
trusted rust fn rust_min(a: i64, b: i64) -> i64
  ensures result <= a && result <= b
  ensures result == a || result == b
  = "::std::cmp::min";

fn smaller_positive(a: i64, b: i64) -> i64
  requires a > 0 && b > 0
  ensures result > 0
{
  return rust_min(a, b);
}
```

The declaration must have at least one `ensures`; `ensures true` explicitly documents an unconstrained result. Missing `requires` means true. No body is permitted. Names share the ordinary function namespace. Ordinary `fn` cannot acquire a Rust path or an implicit trust exemption. Foreign functions cannot be called in contract expressions.

### 2.2 Collection and ownership syntax

```text
OwnedType ::= "Vec" "<" ValueType ">"
            | "HashMap" "<" ElementType "," ValueType ">"
            | "String"
Param     ::= ["take"] Ident ":" Type
MoveExpr  ::= "move" Ident
```

`ValueType` and `ElementType` are specification categories from G3a, not new bounds. `take` is legal only on collection parameters. An unmarked collection parameter borrows read-only. `move` applies only to a live owned collection binding, never G2 arrays/`str` or a copyable value. Collection-producing calls are already owned and need no `move` wrapper.

The compiler supplies the fixed trusted catalog in §4.4; it is available without modules or imports. Catalog calls use G3a's explicit arguments. `len` is extended to collections and remains unparameterized.

```pruv
fn append_one<T>(take v: Vec<T>, x: T) -> Vec<T> ! alloc
  requires len(v) < 1099511627776
  ensures len(result) == len(v) + 1
  ensures result[len(v)] == x
  ensures forall i in 0..len(v): result[i] == v[i]
{
  return vec_push::<T>(move v, x);
}

fn collection_demo() -> i64 ! alloc
  ensures result == 7
{
  let mut v: Vec<i64> = vec_new::<i64>();
  v = append_one::<i64>(move v, 7);
  let mut m: HashMap<i64, i64> = map_new::<i64, i64>();
  m = map_insert::<i64, i64>(move m, 3, vec_get::<i64>(v, 0));
  let found: Option<i64> = map_get::<i64, i64>(m, 3);
  match found {
    Some(x) => { return x; }
    None => { return 0; }
  }
}

fn greeting() -> str ! alloc
  ensures len(result) == 5
{
  let mut s: String = string_new();
  s = string_push_str(move s, "hello");
  return string_to_str(s);
}
```

`v[i]`/`s[i]` for owned collections are contract-only observations. Executable reads use `vec_get::<T>` and `string_byte`. Whole-collection equality and executable element assignment are rejected. No general `old` operator is needed: parameters in a function's postcondition always denote their entry values, including consumed parameters. Only selected foreign/catalog runtime postcondition checks capture owned snapshots before consumption; ordinary Pruv helper ensures remain erased and need no runtime clones.

### 2.3 Naming and compatibility

`trusted`, `rust`, `take`, and `move` are contextual syntax. Catalog function names become reserved. The type names `Vec`, `HashMap`, and `String` denote catalog types only when no user declaration of the same name exists; an existing user type keeps its meaning. A source file declaring such a type cannot also use the homonymous catalog type and receives the ordinary type/arity error if it tries. This preserves existing programs that use these names, which current Rust generation deliberately permits through absolute `::std` paths.

Before implementation, A0 inventories any collisions with newly reserved catalog functions and records explicit diagnostic migrations. No unrelated rejection or legacy SMT snapshot is silently removed.

## 3. Type, ownership, and effect rules

### 3.1 Keep G3a's value universe intact

`Vec<T>` accepts any G3a `Value`, including a finite generic struct or `Option<T>`. `HashMap<K,V>` accepts `K: Element` and any `Value` for V. Using `Element` for keys is only a convenient existing restriction to i64/bool; it does not add hashing operations on abstract parameters. `String` has no arguments. An abstract K must carry `Element` before a `HashMap<K,V>` can be formed.

All collection types are outside `Value` and outside `Element`. No collection fields/payloads, arrays of collections, refinements on collection types, `copy(collection)`, or specialization of `identity<T>` at `String`. G3a's explicit type arguments, definition-level parametric proofs, runtime-equality restrictions, deterministic monomorphization, recursion prohibition, and specialization limits all remain in force. Extend structural type encodings with distinct collection constructors, without changing existing encodings.

### 3.2 Movement, borrowing, and destruction

- Owned bindings arise from catalog/Pruv collection-returning calls, `take` parameters, or `move` of another owned binding. `let b: Vec<i64> = a` is an alias error; `let b: Vec<i64> = move a` transfers ownership.
- A read parameter borrows for the entire call only. It cannot be moved, reassigned, returned, or saved as another collection binding. Multiple read borrows are allowed. There is no mutation during a read borrow.
- A consuming argument requires `move name` or a fresh collection call result. Moving invalidates the binding immediately. No double consumption or use after move, including later arguments evaluated left-to-right. Borrow/move overlap anywhere within the same call is rejected, including `f(v, move v)` and `f(move v, v)`.
- `take` permits consumption, not implicit reassignment; reassignable parameter syntax is not added. A helper can return its taken parameter with `return move v;` or move it into a `let mut` local.
- Reassignment evaluates the RHS first and then destroys the old live LHS. For `v = vec_push(move v, x)`, the old slot is already dead and must not be destroyed again. Only mutable locals permit reassignment. A dead mutable local can be reinitialized.
- At control-flow joins, a binding is usable only if live on every incoming path; cleanup flags retain whether it is actually live on each path. A loop backedge must restore the entry liveness of all outer bindings. Loop-local handles drop each iteration. This rejects conditional consumption followed by use and consumption without restoration in a loop.
- Returning a collection requires an owned call result or `move` of a live owned binding. No implicit clone. Unused owned locals drop at block exit in reverse declaration order, including early returns. Read parameters never drop. Unused non-unit call statements remain rejected; an owned temporary borrowed within an expression drops at its statement/condition boundary.
- Drop has no language effect because payloads have no destructors and only approved std collections are owned. Allocator activity in drop is not observable Pruv `io`. Generated code must drop every live owner exactly once on normal control flow. Process termination paths need not unwind Pruv scopes, consistent with G2.

Collection-bearing ordinary functions have internal linkage in both backends and are omitted from host bindings; they are still checked and verified even if unused. A collection signature cannot be the program's `main`. Non-generic functions with existing public types retain their public entry points and may call these helpers. No host-supplied raw collection pointers are accepted in G6.

### 3.3 User foreign signature surface

| Position | Allowed in user `trusted rust fn` | Rust mapping |
|---|---|---|
| Copyable parameter | i64, bool, Option<i64/bool>, Result<i64/bool> | Same Rust type; Result error is i64 |
| Read parameter | `[i64]`, `[u8]`, `[bool]`, `str` | `&[i64]`, `&[u8]`, `&[bool]`, `&str` |
| Result | i64, bool, (), Option<i64/bool>, Result<i64/bool> | Same Rust value type |

No owned returns, nominal struct/enum parameters, collection arguments, `take`, unsafe Rust functions, variadics, or generic declarations on this user surface. A safe free-function adapter can convert external enums/errors to these forms. Catalog entries alone have privileged collection signatures; they are not evidence that an arbitrary Rust function may receive a handle. Rust type checking checks the adapter signature, not its semantic contract.

Borrowed inputs must remain unchanged and must not escape. Rust code may not call back into the active Pruv invocation, stash raw pointers, or access Pruv-owned memory through hidden aliases. These are trusted obligations even if unsafe code is hidden behind a safe Rust signature.

### 3.4 Effects and failure

The existing effect set remains `alloc` and `io`. A declared foreign effect propagates to callers just like a Pruv effect. No effect means no observable I/O or hidden mutable-state dependence; a pure function's result must be determined by its inputs. `alloc` permits allocation, not arbitrary hidden state. Reads of clocks/randomness/global mutable state require `io`; hashing's randomized internal layout is unobservable in the catalog and needs no `io`.

Constructors, grow operations, and `string_to_str` require `alloc`, conservatively even for an empty allocation or a push that fits existing capacity. Read operations and drop require no effect. Foreign declarations must list internal Rust allocations as `alloc`; the compiler trusts this annotation. Runtime checker snapshots are implementation instrumentation and do not change source-level effects.

Contracts concern normal return. A Rust panic is caught inside the generated Rust boundary, reported, and terminates with exit 101; it never unwinds through C/LLVM frames. The supported shim build uses `panic=unwind`. Process aborts, OOM, external termination, and nontermination cannot be converted into successful contract results. Consumed owners belong to the shim once called; if a Rust operation unwinds, its Rust locals clean up before the shim terminates. No caller resumes with a dead handle.

## 4. Proof semantics and trusted catalog

### 4.1 What is trusted

The trust base includes the declared pre/postconditions, effects, memory/representation validity, frame behavior, Rust adapter/library/toolchain, catalog implementations, and ABI conversion. Pruv proves its own code only **conditional on these contracts and normal foreign return**. A false trusted `ensures false` can make a reachable continuation appear unreachable. It must never be reported as a proved Rust function.

Every compilation that contains foreign declarations or catalog calls emits a deterministic `<output>.foreign.json` manifest. It records declaration location, target path or catalog operation/version, concrete reachable instances, effects, contracts, check mode, target, and supplied crate identities. Verification-only records explicitly state that Rust signatures have not yet been checked by rustc. Build completion adds rustc version and hashes of explicit crate artifacts; hashes identify inputs, not correctness. Verification success reports trusted dependencies separately from verified functions, including dependencies propagated through Pruv helpers. Unused foreign declarations are listed as declared but not reachable from emitted roots.

### 4.2 Call and declaration rules

1. Type-check every declaration and contract, including unused declarations. In proof mode, check each requires' definedness under parameter well-formedness and preceding requires. Check each ensures' definedness under requires, result well-formedness, and preceding ensures. There is no body-postcondition proof. An inconsistent contract is still a trust risk, not something domain checking proves consistent.
2. Evaluate call arguments once in source order and retain their logical entry values. Prove all `requires` in clause order using `call_requires`. No postcondition may justify its own precondition.
3. Create a fresh result with type well-formedness. Assume instantiated ensures on normal return; foreign calls are never inlined or evaluated by the solver. Apply this even for unit results, unlike a shortcut that could otherwise skip unit postconditions.
4. Preserve every unconsumed object's state. A consumed collection's snapshot may occur in the callee contract substitution, but its source binding is no longer usable. Returned ownership carries the fresh result model.
5. For Pruv helpers, prove their ensures against parameter entry snapshots even after those parameters have moved. These ghost snapshots are immutable logical terms, not aliases to live runtime memory.

Under `--no-verify`, parsing, type/effect checking, liveness, specialization, and representation checks remain mandatory, but no SMT proof is claimed. Selected runtime checks enforce contract values/domains. `--infer` runs at generic definition level as G3a specifies; it adds no collection templates and must exclude owned values from inappropriate existing candidates. Final verification is never skipped after inference.

### 4.3 Logical collection models and observations

Let `MAX_LEN = 2^40`. All live collection lengths lie in `0..=MAX_LEN`.

- `Vec<T>` has `(n, A)` with `A: Array(Int, Sort(T))`. Only indices `0 <= i < n` denote contents. Elements satisfy G3a well-formedness. `v[i]` is contract-only, has type T, and needs `contract_domain`; runtime reads use `vec_get`.
- `String` has the G2 byte model `(n, B)`, bytes in `0..=255`. UTF-8 validity is maintained by the runtime boundary and std operations; the SMT model does not silently gain a full UTF-8 theory. `s[i]` in contracts and `string_byte(s,i)` in code return i64 bytes. `len` counts bytes.
- `HashMap<K,V>` has membership array `D: Array(Sort(K), Bool)`, payload array `A: Array(Sort(K), Sort(V))`, and size n. Values outside D are unobservable. Models denote finite maps; size is maintained by constructors and insert transitions, not asserted as an unsupported SMT cardinality primitive. There are no external arbitrary map entries. A borrowed helper parameter gets an abstract well-formed map, without axioms equating two maps by length alone.

Contract-only `map_lookup::<K,V>(m,k)` returns `Option<V>` and is total: Some(A[k]) if D[k], otherwise None. `map_updated::<K,V>(after,before,k,v)` is a contract-only Boolean: the after-domain is exactly the before-domain plus k, k maps to v, all other present values are unchanged, and size grows by one iff k was absent. It expands to SMT `Store`/`Select` relations, with payload equality required only on present keys. There is no quantification over all i64 keys at runtime. The executable check scans the finite stored entries in both maps, compares keys and structural values, and checks size/membership; iteration order is irrelevant. This named predicate is fixed compiler functionality, not user-defined logic or a general foreign observer hook.

`map_lookup`/`map_updated` require explicit type arguments; `len` and indexing use the operand's type. A contract's observer does not invoke a user trusted function. Runtime catalog observers use checked, read-only std operations. No equality on pointers or spare capacity enters proofs. Mutating/replacing a loop variable forgets its collection model; invariants recover length/content facts just as for current arrays.

### 4.4 Initial standard catalog

In this table `v`, `m`, and `s` on the right denote entry snapshots, `r` the result, and `n = len(input)`. Unlisted requires are true. All methods route through Rust-owned adapter code with explicit trusted contracts; they are not new Pruv container implementations.

| Pruv signature | Effect | Requires and complete logical result guarantee | Rust operation |
|---|---|---|---|
| `vec_new<T>() -> Vec<T>` | alloc | `len(r) == 0` | `::std::vec::Vec::<R(T)>::new()` |
| `vec_push<T>(take v: Vec<T>, x: T) -> Vec<T>` | alloc | `n < MAX_LEN`; length n+1, prefix equal to v, `r[n] == x` | `Vec::push(&mut v,x)` then return v |
| `vec_get<T>(v: Vec<T>, i: i64) -> T` | none | `0 <= i < n`; `r == v[i]` | Checked index, copy the value |
| `map_new<K: Element,V>() -> HashMap<K,V>` | alloc | Empty domain and `len(r) == 0` | `::std::collections::HashMap::new()` |
| `map_get<K: Element,V>(m: HashMap<K,V>, k: K) -> Option<V>` | none | `r == map_lookup::<K,V>(m,k)` | `HashMap::get(&m,&k).copied()` |
| `map_insert<K: Element,V>(take m: HashMap<K,V>, k: K, v: V) -> HashMap<K,V>` | alloc | Key already present or `n < MAX_LEN`; `map_updated::<K,V>(r,m,k,v)` | `HashMap::insert`, discard old copied value, return m |
| `string_new() -> String` | alloc | `len(r) == 0` | `::std::string::String::new()` |
| `string_push_str(take s: String, text: str) -> String` | alloc | `len(s)+len(text) <= MAX_LEN`; result bytes are s followed by text | `String::push_str(&mut s,text)` then return s |
| `string_byte(s: String, i: i64) -> i64` | none | `0 <= i < n`; `r == s[i]` | Checked index on `as_bytes()` |
| `string_to_str(s: String) -> str` | alloc | Same byte length and every byte equal; independent owned result | Clone bytes/text into a G2-owned result |
| `len(collection) -> i64` | none | Exact logical length; no mutation | Std `len`, checked conversion |

Vec payload copies preserve G3a structural values, including active enum/Option/Result payloads. HashMap uses Rust's standard i64/bool equality/hash; no user equality, hashing, or destructor code executes. No arithmetic capability is added to K or T.

The exact Vec append contract is expressible as the three ensures in `append_one` above. String append expands to `len(r)==len(s)+len(text)`, preservation over `0..len(s)`, and `r[len(s)+j]==text[j]` over `0..len(text)`. `string_to_str` uses equal lengths and `forall` byte equality. Map insertion includes the frame relation: a contract that states only the inserted key and size is insufficient.

## 5. Runtime checks, code generation, and ABI

### 5.1 Check modes and failure behavior

| Mode | SMT proof | Foreign requires | Foreign ensures | Representation/ownership checks |
|---|---|---|---|---|
| Default / `--foreign-checks=requires` | Yes | Runtime | Trusted only | Always |
| `--foreign-checks=all` | Yes | Runtime | Runtime | Always |
| `--foreign-checks=off` | Yes | Proven at call sites | Trusted only | Always |
| `--no-verify` (requires default) | No | Runtime | Trusted only | Always |
| `--no-verify --foreign-checks=all` | No | Runtime | Runtime | Always |
| `--no-verify --foreign-checks=off` | Rejected CLI combination | — | — | — |

These apply to the fixed catalog too. `--trust-callers` affects only existing public Pruv entry preconditions; it never disables foreign checks. Existing assertions, ordinary Pruv ensures, refinements, and invariants keep their existing runtime policy. `all` is not a global runtime-assertions switch.

Boundary order is: evaluate arguments once; validate representation; check requires if selected; capture any postcondition snapshots; invoke Rust; validate returned representation/length; check ensures if selected; publish result. No result reaches proof-optimized continuation before its selected checks. Consumed input snapshots used by `all` are independent Rust clones, created before the call. Read-only inputs remain borrowed. The catalog's `all` mode compares actual pre/post contents; it must not “check” its own postcondition using the predicted logical update.

Reuse checked i128 mathematical contract evaluation, short-circuit/domain rules, structural contract mirrors, and the configurable existing iteration budget (default `2^30`). One foreign call shares a fresh budget across requires, snapshots' element visits, and ensures. Each visited quantifier/aggregate/map-comparison/snapshot element costs one; empty traversals cost zero. Overflow, exhausted budget, or undefined partial expressions fail closed. These limits can reject a mathematically valid execution. Snapshot allocation can fail like ordinary Rust allocation. Diagnostic context identifies requires versus ensures and the trusted declaration.

| Boundary failure | stderr prefix | Exit |
|---|---|---:|
| False precondition | `pruv: foreign requires violated:` | 101 |
| False postcondition | `pruv: foreign ensures violated:` | 101 |
| Domain/budget/i128 failure | `pruv: foreign contract undefined:` | 101 |
| Representation/length conversion | `pruv: invalid representation:` | 101 |
| Caught Rust panic | `pruv: foreign panic:` | 101 |

Caught panic hooks may add Rust diagnostics; tests require the Pruv prefix and exit code, not a platform backtrace. Flush stdout before reporting termination. All shims protect Rust unwinding with `catch_unwind` inside the ABI boundary. Approved std operations still use safe access and checked growth guards even in `off`: an incorrect trusted result must not turn a catalog index into Rust UB. Checks do not protect against arbitrary UB inside an external crate.

### 5.2 Rust source backend

After G3a specialization, generate one typed boundary helper per concrete foreign/catalog instance. Calls target absolute paths, e.g. `::std::cmp::min(a,b)` or `::adapter::parse_code(text)`. Scalar bool/value types remain native Rust types. Borrow arrays/`str` without copies; no foreign function may retain them. Catalog collections are native `Vec<R(T)>`, `HashMap<R(K),R(V)>`, and `String` behind compiler-owned names. Collection read parameters lower to `&...`, take parameters/results to owned Rust values.

Use normal Rust moves and RAII for normal cleanup, but enforce the Pruv ownership checker first so both backends accept the same language. A consuming update can reuse its allocation; it is not a semantic clone. Only selected contract snapshots and `string_to_str` require copies. Contract mirrors recursively widen integer leaves to i128 as G3a requires. Monomorphized value types remain Copy; collections never derive Copy.

### 5.3 LLVM bridge ABI

Generate `<output-stem>.foreign.rs`, using Rust 2021, with symbols named by declaration identity and G3a structural instance encoding under `pruv_g6_v1_`. No native Rust aggregate ABI crosses the boundary.

| Bridge value | C-compatible representation |
|---|---|
| i64 / bool | i64; bool must be exactly 0 or 1 |
| G3a value aggregate | Pointer to canonical i64 words, using G3a serialization; explicit output pointer for result |
| Borrowed arrays / str | Data pointer plus i64 element/byte count |
| G2 owned str result (`string_to_str` only) | Output record `{data: ptr, len: i64}` in the caller's final output storage; fresh v2 buffer |
| Owned collection | Opaque pointer to `Box<ConcreteRustCollection>`; borrowed or consuming convention known statically |
| Unit result | void |

All non-unit shim results use a final explicit output pointer, including scalars and handles. This new internal bridge convention avoids platform aggregate-return classification and does not change existing `pruv_abi_*` exports. Output storage is initialized only after success; failure does not return. Each collection instance has typed length/read/update/drop shims. Read shims borrow the boxed object. A consuming update takes ownership of the box, mutates its contents, and returns ownership (normally the same box pointer); the caller's old slot is cleared before invocation. Drop reconstructs that exact Box once. The pointer never encodes a G2 buffer and is never passed to `pruv_free_v2`.

The LLVM backend tracks collection ownership separately from G2 buffers, using liveness/drop flags across branches and early returns. It calls the typed drop shim for every live owner in reverse scope order. No LLVM access to Vec/HashMap/String fields, capacity, allocator layout, or interior pointers is allowed. Contract observation/snapshot/drop operations use the same typed bridge.

Before constructing Rust references, check lengths (`0..=MAX_LEN`), arithmetic/layout conversions, non-null for nonempty slices, alignment, bool bytes, UTF-8, and aggregate tags. Empty slices use valid Rust dangling empty references, never `from_raw_parts(null,0)`. Raw pointer accessibility/provenance cannot be validated by byte checks: bridge pointers come from generated Pruv code, and existing external raw callers retain their documented responsibility. Opaque handles must be non-null live objects of the exact concrete type; static ownership and compiler-only construction guarantee provenance. A null check is not a forged-pointer defense. No public API accepts arbitrary handles.

Keep all G2 input representation checks active, including under `--trust-callers`. Rust source inputs already have typed Rust representations but lengths still need checked conversion. `string_to_str` on LLVM allocates a fresh v2 byte buffer and copies from the Rust string; it never hands arbitrary Rust capacity to a `{ptr,len}` return. Its output record has fields in that order, a mutable byte pointer followed by i64, using the existing G2 record alignment. Empty output is `{null,0}`; a nonempty allocation has size len and alignment 1. Ownership transfers to the LLVM caller only when the shim successfully publishes the output record after selected checks, and subsequent cleanup uses v2 free. It uses the selected existing runtime allocator so the G2 host/free convention stays correct. Ordinary Vec growth never uses v2 buffer allocation.

LLVM references `pruv_g6_bridge_v1` in addition to any required G2 v2 marker. It also references `pruv_g6_bundle_<sha256>`, defined only by its matching shim. Compute that digest over the canonical declaration/contracts, concrete instance list, target, bridge schema version, check mode, and shim source template before substituting the digest into symbol names. No timestamps or local paths enter that digest. Missing/wrong or stale same-version shims therefore fail to link. The driver verifies the actual shim source hash against the manifest before invoking rustc; explicit crate artifact hashes are also checked at that step. G6 adds no native-layout promise to `--rust-bindings` and does not bump the G2 buffer protocol.

### 5.4 Build integration and target policy

Add repeatable `--rust-extern NAME=PATH` and `--rust-search PATH` options in both compilers. They correspond to rustc `--extern` and `-L dependency`, passed as argument arrays, never shell text. NAME must be a Rust identifier; duplicate names and reserved `std` are errors. Paths identify prebuilt rlibs for the selected target/toolchain. Pruv does not run Cargo, download crates, or guess features. Only explicitly supplied crate roots may occur in foreign paths.

Source emission records required options in `.foreign.json`; it does not claim a successful Rust build. For Rust-source output, the consumer compiles the generated module with those options. For LLVM output:

1. Emit LLVM IR/object, the Rust shim source, bindings if requested, and the manifest as one coherent artifact set. On failure, publish no partial set.
2. Generated Rust host bindings include the shim module exactly once. A Rust host executable links the Pruv LLVM object and the existing runtime object through rustc, with external rlibs/search paths supplied.
3. For canonical `--emit exe`, add a Rust link-root source that includes the shim and calls the generated Pruv main wrapper; use rustc as final link driver with the LLVM/runtime objects. Do not retain a second C `main`. Reuse the existing default runtime allocation variant; a host-binding build keeps its existing Rust-allocator v2 variant. Supply exactly one set of host allocator helpers.
4. `--emit obj` is a bundle contract: the object is not self-contained without its shim/manifest and Rust link step. Python parity is checked through the same source/object harness; it need not acquire the canonical driver's native object emitter.

Foreign-free output keeps its existing toolchain requirements. G6 LLVM **does require rustc and std at link time**; no claim of rustc-free execution builds applies when Rust libraries are used. Final linking uses one compatible target triple, pointer width, rustc toolchain, and crate set. No cross-toolchain Rust ABI compatibility is promised.

The initial executable gate is host macOS arm64 and Linux x86-64, each with installed compatible toolchains. Other target emission must either have ABI probes recorded or return `foreign_target`; unsupported cross/Windows linking remains explicit. This is a release requirement, not a claim those platforms were tested here. A C-only consumer/link driver and standalone Rust staticlib packaging are deferred.

## 6. Diagnostics and must_reject inventory

Language/proof/build failures use JSON diagnostics and exit 1; invalid CLI combinations use exit 2. Runtime failures follow §5.1. New diagnostics must carry declaration/call location and an actionable fix. Type/liveness checks run under every mode.

### 6.1 New-code rejection files

| Stage/code | Minimum distinct files | Required coverage |
|---|---:|---|
| `parse/foreign_syntax` | 4 | Missing path, body on declaration, missing trusted marker on foreign form, malformed take/move |
| `type/foreign_path` | 4 | Injected expression, relative root, unsupplied crate, generic text in path |
| `type/foreign_signature` | 6 | User foreign generic, owned return, nominal argument, take argument, collection argument, missing ensures |
| `type/foreign_owned_type` | 8 | Nested Vec, Option<String>, owned field, owned ordinary type argument, non-Element key, invalid collection refinement, Vec<str>, HashMap<i64,str> |
| `type/foreign_move` | 8 | Use after move, duplicate consumption, moving borrowed parameter, missing move in a consuming argument, move of scalar, conditional move then use, returning owned local without move, owned local alias without move |
| `type/foreign_borrow` | 4 | Read then move in one call, move then read, borrowed return, borrowed alias binding |
| `type/foreign_loop_move` | 2 | Missing backedge restoration, one branch fails restoration |
| `type/foreign_contract` | 3 | User foreign call in contract, map observer wrong key type, executable map_updated |
| `type/foreign_export` | 1 | Collection-bearing main signature |
| **Total** | **40** | |

Require four additional build rejection fixtures: two `codegen/foreign_target` cases (unsupported target policy and G6 executable cross link), and two `codegen/foreign_bridge` cases (conflicting artifact paths and incompatible bridge manifest). Build-only failures such as missing rlib/rustc, unsafe-function signature rejection by rustc, or missing bridge symbols are additional fixtures (`rustc/foreign_build` or the existing linker diagnostic); none count as rejected Pruv source files. Invalid flags have separate CLI fixtures. New-code errors are not substituted for an earlier existing parse/type error when that earlier error is the actual cause.

### 6.2 Reused-code rejection files

Add at least **20** further files: four unprovable `call_requires` (Rust scalar precondition, Vec index, growth limit, String growth); four false Pruv `ensures` after calls (wrong scalar claim, lost Vec prefix, changed unrelated map key, wrong String bytes); four domain errors (unguarded Vec byte/value read, unguarded Option payload, undefined contract division, bad bound ordering); three effect omissions (constructor, grow, foreign io); three G3 restrictions (u8 argument, unbounded map key parameter, runtime aggregate equality); two inference cases that must still fail final proof. Preserve the governing existing stage/code.

Combined minimum: **60 distinct must_reject sources**, not 60 backend/mode rows. Every source has expected stage/code metadata. False foreign implementations with satisfiable declarations are **runtime trust-violation fixtures**, not expected compile-time rejections. In `requires`/`off` they can pass a proof; this limitation is an explicit test expectation.

## 7. Implementation batches and file ownership

Abbreviations: `P/ = pruvc/`, `C/ = pruvc-rs/crates/pruv-core/src/`, `V/ = pruvc-rs/crates/pruv-proof/src/`, `D/ = pruvc-rs/crates/pruvc/src/`. New files below are implementation targets, not files created by this design-document task.

### 7.1 Rules for every batch

Implement Python first, port to Rust within the batch, then compare before closing it. One worker owns each file at a time; notably Python LLVM emission and bindings share `P/llvmgen.py`. Core AST/type changes hand off before proof or generation edits begin. Preserve foreign-free behavior and legacy SMT snapshots. Use explicit `unsupported_type` in unfinished downstream layers, including safe mode; remove all such guards for admitted G6 cases before A4.

Run `tests/run_all.py` for both compilers/backends and all applicable `tests/m3_all.py` stages. New proof trace comparisons must be `same`; `cex_only` and `same_unknown` are not passing evidence. Proof/codegen changes also re-grade existing benchmarks in default and `--trust-callers` modes and run existing mutation checks, per `BLUEPRINT.md` §7. Each batch needs one audit and a confirmation after fixes with zero unresolved required findings. Future implementation batches record actual results in `RESULTS.md`; this task changes only this specification.

### 7.2 A0 — Baseline, declarations, and ownership

**Frontend owner:** `P/vast.py`, `P/vparser.py`, `P/typeinfo.py`, `P/check.py`, `P/refine.py`; `C/ast.rs`, `C/parser.rs`, `C/typeinfo.rs`, `C/check.rs`, `C/refine.rs`. Add `P/foreign.py` and `C/foreign.rs` for the fixed catalog, normalized declarations, and type/ownership rules. Driver owner subsequently adds option parsing in `P/pruvc.py`, `D/cli.rs`.

Require G3a exit gates as entry evidence. Freeze regression row inventory, G3 specialization/SMT baseline, and a name-collision migration manifest. Exit: 24 accepted frontend samples, the 40 parse/type rejection sources in §6.1, cross-implementation AST/type/liveness dumps identical; exhaustive ownership unit cases for joins, loops, temporaries, and return cleanup plans. The four additional codegen/build rejection fixtures are due in A3. Backend guards reject accepted-but-not-yet-lowered types.

### 7.3 A1 — Models and modular trust

**Proof owner:** `P/verify.py`, `P/infer.py`, catalog schema in `P/foreign.py`; `V/model.rs`, `V/symbolic.rs`, corresponding inference files, and the proof-side adapter for `C/foreign.rs`. Only the frontend owner changes checked-node representation.

Exit: 24 positive proof programs covering all catalog transitions, abstract Vec values, bool/i64 keys, helper entry snapshots, and untouched-state frames; all 20 §6.2 rejections; declaration-domain tests on unused foreign declarations; unit-return ensures honored. Python/Rust query traces and dependency manifests match. Deliberately false but well-defined foreign ensures are marked trusted, never counted as verified bodies.

### 7.4 A2 — Rust execution and boundary checks

**Rust generation owner:** `P/codegen.py`, new `P/foreign_codegen.py`; `C/codegen.rs`, `C/emit_common.rs`, new `C/foreign_codegen.rs`. Driver owner integrates coherent output/manifest generation in `P/pruvc.py`, `D/driver.rs`.

Exit: at least 24 runtime fixtures: four scalar/Option/Result adapter cases, six Vec cases, six map cases, four String cases, and four ownership/effect/evaluation-order cases. Each runs in verified requires/all/off and safe requires/all modes, with and without `--trust-callers`. Both compilers emit identical Rust source. Dedicated injected-wrong-Rust fixtures exercise false ensures, panic, unchanged read inputs, i128/domain/budget failures, and no duplicate argument evaluation. Normal-path owner/drop counts balance after branches, loops, reassignment, and early returns.

### 7.5 A3 — LLVM shims, build, and ABI

**LLVM/ABI owner:** `P/llvmgen.py`, LLVM portions of `P/foreign_codegen.py`; `C/llvmgen.rs`, `C/abi.rs`, `C/bindings.rs`, shim portions of `C/foreign_codegen.rs`. **Runtime/build owner after ABI handoff:** `P/runtime.c` only for needed bridge support, `D/driver.rs`, `D/link.rs`, `D/runtime.rs`, `D/cli.rs`, plus test build adapters. Do not change v2 allocation signatures.

Exit: the same 24 runtime fixtures and modes on LLVM, identical Python/Rust IR/shims/bindings/manifests after normalizing recorded local tool paths. At least 16 ABI/build probes: four value serialization cases, four array/bool/UTF-8/empty-input cases, four live-owner/drop/capacity cases, and four missing-or-stale shim/crate/target cases. Exercise Vec capacity greater than len, String Unicode append, empty handles, aggregate elements, and G2-owned string return under both allocator variants. Run platform probes for each released target; do not infer Linux/Windows success from macOS output inspection.

### 7.6 A4 — Release integration

**Harness owner:** `tests/run_all.py`, `tests/m3_all.py`, existing differential runners, new `tests/foreign/` fixtures and `tests/abi/check_foreign.py`. **Documentation owner after implementation freeze:** `SPEC.md`, `RESULTS.md`, roadmap G6 entry, examples.

Exit: 60 must_reject files, 24 runtime fixtures, 24 positive proof cases, 16 ABI/build probes, all 12 current cross-check stages plus a new foreign stage. Full regression and existing benchmark/mutation baselines cannot lose unexplained results. The user-facing SPEC summary is at most one page and explains trust, modes, move/borrow/drop, and the catalog. Complete one boundary audit and one confirmation; unresolved required findings block release.

### 7.7 Q — Soundness stress and independent use

Generate three fixed seeds × 100 small programs, with an independent sequence/map/byte-string oracle. Test both compilers and backends; include repeated growth, duplicate keys, branch/loop ownership, Unicode, and all boundary modes. Classify at least 60 mutants: 30 incorrect Pruv computations, 20 incorrect foreign results/contracts, and 10 ownership/ABI implementation faults. Require zero unexplained accepted wrong Pruv results under correct trusted contracts; foreign lies must be caught by `all` when the violated property is expressible/checkable. Log undetectable lies as trust limitations rather than inflating a proof-rejection count.

Four independent-use problems, from the final spec alone: Vec filter/accumulate, scalar-key histogram, UTF-8 String assembly, and a small external Rust parser adapter returning a scalar Result. Supply the adapter contract, not a solution or invariant. Require correct reference results in all four compiler/backend combinations, record first-attempt and repaired scores separately, and retain failures/timeouts. Larger parsed trees remain G9 work.

## 8. Risks and acceptance measurements

| Risk | Required mitigation/evidence |
|---|---|
| False/overstrong trusted contract makes proof vacuous | Trust manifest and dependency reporting; deliberately false-contract tests; human review of contracts; no “verified Rust” label |
| Use-after-move/double drop or borrow escape | Checked liveness model; branch/backedge tests; exact normal-path drop counts; ABI instrumentation |
| Rust capacity/layout or allocator mismatch | Opaque boxed collections; no native field access; v2 copy for G2 conversion; capacity-greater-than-len and allocator probes |
| Map contracts lose other keys or mix equality semantics | Exact map_updated frame; i64/bool keys only; collision/replacement tests and finite-map oracle |
| Runtime checks too costly | Separate requires/all/off timing; report snapshot bytes and scan work; never omit expensive ensures silently |
| Proof timeouts on abstract contents | Definition-level G3a proof; store/select models; deterministic traces; report unknown separately from disproved |
| Foreign panic crosses LLVM | catch inside Rust extern shim; panic fixture on both backends; supported panic strategy recorded |
| Toolchain/crate/target mismatch | Explicit build inputs and artifact hashes; coherent manifests; rustc diagnostics and per-target ABI probes |

Measure on a recorded machine/toolchain with load reported, using identical workloads against handwritten Rust. Record median and spread over at least 21 executions, with startup separated where meaningful:

1. Pure scalar foreign call overhead, Rust direct path versus LLVM shim, each check mode.
2. Vec push throughput, allocations/reallocations and peak memory at 0, 1, 1,000, and 1,000,000 elements, including aggregate values.
3. HashMap insert/get for new and repeated keys, both key types, with output consumed to prevent dead-code elimination.
4. String append and `string_to_str` cost per appended/copied byte, ASCII and multibyte UTF-8; separate UTF-8 validation cost.
5. `all` snapshot/contract work, bytes cloned, iteration-budget exhaustion, and slowdown relative to requires/off. Quadratic cumulative checking during repeated append must be reported explicitly.
6. Compiler/checker/prover time, obligation counts, solver unknowns, shim compile/link time, output size, and foreign-free regression ratios against the post-G3a baseline.

Correctness/cleanup/ABI gates are hard gates. There is no invented universal speedup threshold. Report regressions and their causes before release; `RESULTS.md` §44 already shows why algorithm, initialization, and generated loop shape must be distinguished from boundary cost. No benchmark result from that section establishes the performance of this bridge.

## 9. Evidence limits and follow-up boundary

This document was grounded in the repository paths listed in §1.1 and the G2/G3/M1 specifications. Only `docs/G6_SPEC.md` is created by this task. No compiler implementation, tests, generated ABI executable, benchmark, crate build, or target runtime was run to validate the proposed features.

The language/ownership/check-mode decisions above are resolved for this proposal. Open empirical questions are solver scalability, clone/check overhead, panic-hook consistency, and target/toolchain link behavior; batches A1–Q provide their acceptance evidence. They are not permissions to leave the semantics unspecified.

Further library coverage requires reviewed adapter contracts. Arbitrary owned foreign types, owned generic payloads, String keys, iterator/reference lifetimes, host exposure of collection handles, Cargo integration, and recovery from allocation/panic failures require later designs. G6 opens the first L2 components with scalar/array/string adapter boundaries; it does not claim to replace G9 data structures or the G10/G7 prerequisites for L3.

## 10. A0 implementation decisions (fixed 2026-11-12, before implementation)

These choices make §§2–3 and §6.1 precise enough for two independent implementations (Python first, Rust port byte-identical). Where this section and an earlier section differ, this section governs A0.

### 10.1 Representation

- Internal type names: `vec` (args `(T,)`), `hashmap` (args `(K, V)`), `string` (no args). They join `BUILTIN_TYPE_NAMES`; `type_name`/`format_type` print `Vec<T>`, `HashMap<K, V>`, `String`. The parser still produces nominal `Vec`/`HashMap`/`String`; the checker's type resolution maps a nominal of that name to the collection type **only when no user type of that name is declared**. Wrong arity (`Vec`, `Vec<i64, i64>`, `String<i64>`) is the existing `type/type_arity`.
- AST additions are plain class attributes (as G3 did), so every dump of a G6-free program is byte-identical to today: `Param.take = False`; `Function.foreign = None` (for a foreign declaration a dict `{"path": "::std::cmp::min", "line": L, "col": C}` where line/col are those of the path string token; `body` is `[]`); new expression node `Move(line, col, name)` with `ty`. The test adapter (`tests/diff_py_adapter.py`) and `pruv-parse-dump`/`pruv-check-dump` emit `take`, `foreign` and `Move` only when present/non-default.
- A collection value is never a G3 `Value`/`Element`; `is_value`/`is_element` return false for it.

### 10.2 Syntax and parse errors (`parse/foreign_syntax`)

- Top level: identifier `trusted` followed by `rust` `fn` starts a foreign declaration: `trusted rust fn NAME [<...>] ( params ) -> TYPE [! effects] (requires|ensures)* = "PATH" ;`. Type parameters are parsed (and rejected later by the checker, §10.4). After the contracts: `{` → `foreign_syntax` "a trusted rust fn has no body"; anything other than `=` → `foreign_syntax` "missing Rust path"; after `=` a non-string token → `foreign_syntax` "missing Rust path"; then `;` is required (ordinary `expect`).
- Top level `rust` followed by `fn` → `foreign_syntax` "missing `trusted`". Top level `trusted` not followed by `rust fn` → `foreign_syntax`.
- Parameters: `take` followed by an identifier then `:` is a take parameter. `take` followed by an identifier and then not `:` → `foreign_syntax` "malformed take". `take :` is still an ordinary parameter named `take`. The existing function name `take` (used in tests) is unaffected.
- Expressions: `move` followed by an identifier token is `Move(name)`. `move` followed by an integer, string, `true`/`false`, `(`, `[`, or `move` → `foreign_syntax` "move takes a binding name". Otherwise `move` is an ordinary identifier.
- The path string is kept verbatim; its shape is validated by the checker (§10.4).

### 10.3 Catalog (fixed, reserved names)

`vec_new<T>`, `vec_push<T>`, `vec_get<T>`, `map_new<K: Element, V>`, `map_get<K: Element, V>`, `map_insert<K: Element, V>`, `string_new`, `string_push_str`, `string_byte`, `string_to_str` with the signatures and effects of §4.4 (take parameters: `vec_push.v`, `map_insert.m`, `string_push_str.s`). `vec_*`/`map_*` require explicit type arguments (missing → the existing G3 code for a missing/wrong type application, `type/type_arity`); `string_*` take none. Contract-only: `map_lookup<K: Element, V>(m: HashMap<K,V>, k: K) -> Option<V>` and `map_updated<K: Element, V>(after: HashMap<K,V>, before: HashMap<K,V>, k: K, v: V) -> bool`. `len` accepts a collection (code and contracts). `x[i]` on `Vec<T>` (type T) and `String` (type i64) is contract-only (existing `type/contract_only` in code). All twelve names are reserved for user functions (existing `type/reserved`). Defining a user function with a catalog name is `reserved`.

### 10.4 Checker rules and codes

Foreign declarations (`type/foreign_signature` unless noted): type parameters; return type other than i64, bool, unit, Option<i64|bool>, Result<i64|bool> ("owned return" covers str, arrays, collections); a parameter of nominal type; a `take` parameter; a collection parameter; no `ensures`. Allowed parameter types: i64, bool, Option<i64|bool>, Result<i64|bool>, `[i64]`, `[u8]`, `[bool]`, `str`. Contracts are type-checked like ordinary contracts. Foreign declarations have no call-graph edges (recursion check skips them). `take` on an ordinary function parameter whose type is not a collection → `type/foreign_move` "take is only for collection parameters".

Path (`type/foreign_path`): must match `^::[A-Za-z_][A-Za-z0-9_]*(::[A-Za-z_][A-Za-z0-9_]*)*$` (covers injected expressions, whitespace and generic text); first segment `crate`, `self`, `super` → relative root; first segment neither `std` nor a name given with `--rust-extern NAME=PATH` → unsupplied crate. The checker receives the extern name set from the driver (empty by default; must_reject `.json` may give `"flags": ["--rust-extern", "adapter=/none.rlib"]`; A0 does not open the file).

Owned types (`type/foreign_owned_type`): a refinement written on a catalog collection type (checked in refinement validation, before the existing `refinement_base`), a collection inside Option/Result/array/another collection/struct field/enum payload, as an ordinary (user function or user type) type argument, with a refinement, `Vec<X>`/`HashMap<_, X>` where X is not a G3 Value (str, arrays, unit), `HashMap<K, _>` where K is not Element (a concrete type other than i64/bool, or a type parameter without the `Element` bound). Collection type arguments may be type parameters (`Vec<T>`).

Contracts (`type/foreign_contract`): a call to a foreign declaration or to an executable catalog function inside `requires`/`ensures`/`assert`/invariant; `map_lookup`/`map_updated` used in code; `map_lookup`/`map_updated` whose key argument type differs from the map's K. Contracts are not subject to ownership liveness: parameters in `ensures` denote entry values even if consumed.

Export (`type/foreign_export`): `main` with a collection parameter or result.

Ownership (only in executable code; checked per function after typing, in statement order):

- Binding states: `owned-live`, `owned-dead`, `owned-maybe` (live on some incoming path), `borrowed` (unmarked collection parameter; never changes). Owned bindings: `take` parameters and `let`/`let mut` locals of collection type.
- Positions that may hold a collection expression: (a) argument to a borrow (unmarked collection) parameter or to `len`/`vec_get`/`map_get`/`string_byte`/`string_to_str` — a live binding (owned or borrowed) or a fresh call result; (b) argument to a take parameter, `let` initializer, assignment right-hand side, `return` value — consuming positions: `move x` or a fresh call result. A `Move` anywhere else → `type/foreign_move` "move only where ownership is consumed".
- Codes, checked in this order: `move x` where x is not of collection type → `foreign_move` "move of a non-collection value"; use (any position) of an `owned-dead` binding → `foreign_move` "use after move"; use of an `owned-maybe` binding → `foreign_move` "binding may have been moved"; consuming position given a plain `Var` of an owned binding → `foreign_move` (let initializer: "alias of an owned binding without move"; return: "returning an owned binding without move"; take argument: "missing move in a consuming argument"); consuming position given a plain `Var` or `move` of a borrowed parameter → `foreign_borrow` for plain `Var` in `let`/`return` ("borrowed alias"/"borrowed return") and `foreign_move` "moving a borrowed parameter" for `move p` or a plain borrowed `Var` in a take argument; the same owned binding consumed twice in one call → `foreign_move` "consumed twice"; consumed and borrowed in the same call (either order) → `foreign_borrow` "borrowed and moved in one call".
- Before processing a call's arguments, the call is scanned for the same owned binding appearing both consumed (`move x`) and borrowed (plain `x`) → `foreign_borrow`, or consumed twice → `foreign_move` "consumed twice" (this scan comes first, so `f(move v, v)` is `foreign_borrow`, not use after move). Arguments are then processed left to right; a consumption marks the binding dead immediately. Assignment `v = e`: `e` first, then v becomes live (v must be a `let mut` local; existing `immutable` otherwise). Joins (if/else, match arms; an `if` without else joins with the fall-through path): live on all non-returning incoming paths → live; dead on all → dead; otherwise maybe. Paths that end in `return` do not join. Loop: process the body once from the entry state; every outer owned binding live at loop entry must be live at the end of the body → else `type/foreign_loop_move` ("moved in the loop body and not restored"); bindings declared inside the body are local to it. A maybe/dead binding may be reinitialized by assignment.
- Dropping is implicit; no error for owned bindings live at scope end. Cleanup plans are produced by the backends (A2/A3), not dumped in A0.

### 10.5 Driver and guard

Both drivers accept `--rust-extern NAME=PATH` (repeatable; NAME a Rust identifier, not `std`, no duplicates; otherwise CLI usage error exit 2), `--rust-search PATH` (repeatable) and `--foreign-checks requires|all|off` (default requires; `--no-verify` with `off` → exit 2). After a successful check, a program that contains a foreign declaration, a collection type, a `take`, or a `Move` is rejected in A0 with `codegen/unsupported_type` "G6 foreign calls and collections are not implemented by the llvm codegen layer yet" at the first such construct (source order: functions in order, signature before body), also under `--no-verify`. The accepted frontend samples (`tests/g6/frontend/*.pruv`) therefore expect exactly that diagnostic; `tests/diff_parse.py --mode check` compares their checked dumps.

## 11. A1 implementation decisions (fixed 2026-11-12, before implementation)

These make §4 precise for two byte-identical verifier implementations (Python `pruvc/verify.py`, Rust `pruv-proof`). Where this section differs from §4/§7.3, it governs A1.

### 11.1 Pipeline

- Verification now runs on G6 programs. The A0 guard (`codegen/unsupported_type`) moves to **after** verification in both drivers; with `--no-verify` it still fires right after the check. Verification errors therefore win over the guard. The trace adapters (`tests/diff_py_adapter.py trace`, `pruv-trace-dump`) produce real traces for G6 programs (no guard).
- `tests/g6/frontend/*` keep only their `--no-verify` row (they were written as frontend samples, not proof samples). New `tests/g6/proof/*.pruv` must verify completely: their rows expect exactly `codegen/unsupported_type` in default mode (proof done, no code generator yet).
- The `.foreign.json` manifest and trusted-dependency reporting (§4.1) are emitted with build outputs in A2, not in A1.

### 11.2 Models (MAX_LEN = 2^40)

- `Vec<T>`: an `Arr` exactly like a G3 `[T]` array (array `Int -> Sort(T)`, length n, elem T). Well-formedness, havoc in loops and fresh results follow the existing `[T]` rules (`0 <= n <= MAX_LEN`, nothing more for non-u8 elements).
- `String`: an `Arr` with elem `u8` exactly like `str` (`0 <= n <= MAX_LEN`, `u8_dom`).
- `HashMap<K, V>`: a new map value `(d: Array(Sort(K), Bool), a: Array(Sort(K), Sort(V)), n: Int)`; well-formedness `0 <= n <= MAX_LEN`. Fresh/havoc maps get fresh d, a, n with that fact.
- `move x` evaluates to the current value of x. Parameters in `ensures` keep denoting entry values (existing `params` snapshot), also when consumed.

### 11.3 Catalog semantics at a call (arguments evaluated once, left to right)

Each catalog precondition is proved (in code only) with obligation code `call_requires` and description `precondition of NAME (catalog)`; `vec_new`/`string_new`/`map_new` take a fresh symbol (one counter step) and replace its length by the literal 0; fresh names follow the existing `base!k` scheme (`.len`, `.d`, `.a`); the `map_updated` quantifier variable is `map!j`; then the result below is used directly (no fresh symbol where an exact term exists):

| Call | Requires | Result |
|---|---|---|
| `vec_new` | — | fresh array, n = 0 |
| `vec_push(v, x)` | `v.n < MAX_LEN` | `(Store(v.a, v.n, x), v.n + 1)` |
| `vec_get(v, i)` | `0 <= i && i < v.n` | `Select(v.a, i)`; for an i64 element the i64 range is assumed (as an array read) |
| `map_new` | — | `(K(Sort(K), false), fresh array, 0)` |
| `map_get(m, k)` | — | `If(m.d[k], Some(m.a[k]), None)` |
| `map_insert(m, k, x)` | `Or(m.d[k], m.n < MAX_LEN)` | `(Store(m.d, k, true), Store(m.a, k, x), m.n + If(m.d[k], 0, 1))` |
| `string_new` | — | fresh array, n = 0, u8 |
| `string_push_str(s, t)` | `s.n + t.n <= MAX_LEN` | fresh u8 array r, `r.n == s.n + t.n`, `forall j in 0..s.n: r[j] == s[j]`, `forall j in 0..t.n: r[s.n + j] == t[j]` (quantified like `substr`) |
| `string_byte(s, i)` | `0 <= i && i < s.n` | `Select(s.a, i)`, i64 range assumed (as an array read) |
| `string_to_str(s)` | — | a `str` value with the same array and length |
| `len(c)` | — | `c.n` |

Contract-only: `v[i]` / `s[i]` use the existing contract index-domain rule of arrays. `map_lookup(m, k)` = `If(m.d[k], Some(m.a[k]), None)`. `map_updated(after, before, k, x)` = `after.d == Store(before.d, k, true) && after.n == before.n + If(before.d[k], 0, 1) && forall j: after.d[j] ==> after.a[j] == Store(before.a, k, x)[j]` (j of Sort(K)).

### 11.4 Trusted declarations

- A `trusted rust fn` is verified like a function without a body: parameters fresh with well-formedness; each `requires` domain-checked under the earlier requires (existing rule); then a fresh result with well-formedness is introduced and each `ensures` is domain-checked under all requires, result well-formedness and the earlier ensures. No `ensures` proof, no body. Unused declarations are checked the same way.
- A call to a trusted declaration is the existing call rule (prove each requires as `call_requires`, fresh result with wf, assume each ensures) with one difference: a **unit** result still assumes its ensures (ordinary unit functions keep the legacy behaviour so legacy traces do not change).
- `--infer` never builds candidates mentioning collection-typed variables.

## 12. A2 implementation decisions (fixed 2026-11-12, before implementation)

Rust source backend only; the LLVM backend keeps rejecting G6 with `codegen/unsupported_type` until A3 (runtime fixtures list themselves in `tests/llvm_pending.txt`). Both compilers must emit byte-identical Rust source.

### 12.1 Types, ownership and expressions

- `Vec<T>` → `::std::vec::Vec<R(T)>`, `HashMap<K,V>` → `::std::collections::HashMap<R(K), R(V)>`, `String` → `::std::string::String` (owned: locals, take parameters, results); a borrowed (unmarked) collection parameter has type `&R(C)`. Monomorphized value types stay `Copy`; collections are never `Copy`.
- `move x` → `x`. A collection argument in a borrow position: an owned binding `x` → `&x`; a borrowed parameter `x` → `x`; a fresh call result → `&(call)`. Consuming positions pass by value. Rust moves/RAII perform the drops (the Pruv ownership checker already accepts only programs whose moves Rust also accepts).
- `len(c)` → `(c.len() as i64)` (a collection length never exceeds 2^40, so the cast is exact). Contract-only forms are never emitted in code.
- `string_to_str(s)` → an independent `::std::string::String` clone (the Rust-source `str` representation).
- Collection-bearing functions are private (no `pub`), never get host bindings and cannot be `main` (A0). They keep the existing entry/body scheme: with `requires`, a private checked entry `f` and a private body `f__pruv_body`; verified callers call the body, safe-mode callers the entry.
- Runtime `requires` evaluation (i128 mirror) gains collection observers: `len(c)` → `(c.len() as i128)`; `v[i]` → checked index (out of range → `pruv: requires undefined: ...`) then the element's contract conversion; `s[i]` → byte as i128; `map_lookup::<K,V>(m, k)` → `m.get(&k).copied()` converted to the Option mirror; `map_updated` in a requires → a generated scan helper (`pruv_g6_map_updated__K__V`). Contract-only observers never allocate.
- Generic helpers: after G3 specialization, catalog calls keep their name with substituted type arguments (no specialization of the catalog itself).

### 12.2 Boundary helpers

One private helper per concrete instance, emitted once, in first-use order:

- Catalog: `pruv_g6_<op>__<enc>` where `<enc>` is the G3 structural encoding of each type argument joined by `__` (none for `string_*`). Body: selected requires checks, selected snapshot, the std operation, selected ensures checks, result. Requires per §4.4/§11.3 (`vec_push`: `len < 2^40`; `vec_get`/`string_byte`: `0 <= i < len`; `map_insert`: key present or `len < 2^40`; `string_push_str`: `len(s) + len(t) <= 2^40`). Even with `off`, `vec_get`/`string_byte` use checked indexing (a failure there is `pruv: invalid representation: index`), never `get_unchecked`.
- User `trusted rust fn NAME`: a private helper `NAME` with the declared signature (`str`/array parameters borrowed as `&str`/`&[T]`) that checks the selected requires (existing i128 mirror and messages with the new prefix), calls `::path(args)` inside `::std::panic::catch_unwind(::std::panic::AssertUnwindSafe(|| ...))`, turns `Err` into `panic!("pruv: foreign panic: NAME")`, checks the selected ensures with `result` bound, and returns.
- Messages (all via `panic!`, so exit 101): `pruv: foreign requires violated: NAME: <expr>`, `pruv: foreign ensures violated: NAME: <expr>`, `pruv: foreign contract undefined: NAME: <what>`. Catalog `<expr>` texts are fixed strings written in the helper (e.g. `len(v) < 2^40`).

### 12.3 Check modes (`--foreign-checks`, default `requires`)

- `requires`: requires checks in every helper (also in verified mode). `all`: also ensures checks; catalog updates snapshot consumed inputs with `.clone()` before the operation and compare actual contents afterwards (Vec/String: length and every element/byte of the prefix and the appended part; HashMap: size, every entry of the snapshot except the inserted key unchanged, inserted key present with the value; `string_to_str`: equal bytes; `vec_get`/`string_byte`/`map_get`: the result equals a second checked read). `off`: no contract checks (CLI already rejects `off` with `--no-verify`). `--trust-callers` does not change foreign checks.
- `all` work counts against the existing contract budget (`--contract-budget`, default 2^30): one unit per visited element/entry, fresh per helper call; exhaustion → `pruv: foreign contract undefined: NAME: budget`.

### 12.4 Manifest

When the program uses any G6 construct, both drivers also write `<out>.foreign.json` (sorted keys, 2-space indent, UTF-8, trailing newline): `{"schema": "pruv-foreign-v1", "backend": "rust", "check_mode": M, "rustc_checked": false, "trusted": [{"name", "path", "line", "col", "effects", "requires": [text], "ensures": [text], "reachable": bool}], "catalog": [{"op", "type_args": [spelling]}], "externs": [{"name", "path"}]}` with lists in source order (catalog: first-use order of the emitted helpers). `reachable` is whether any emitted function calls it. Texts use the existing contract `show` spelling. No timestamps or absolute paths beyond what the user passed.

### 12.5 Tests

`tests/runtime/g6_*.pruv` + `.json` + driver `.rs` (24: 4 scalar/Option/Result adapter, 6 Vec, 6 map, 4 String, 4 ownership/effect/evaluation order), each with a flags matrix over `[]`, `["--foreign-checks","all"]`, `["--foreign-checks","off"]`, `["--no-verify"]`, `["--no-verify","--foreign-checks","all"]` and the same with `--trust-callers` where meaningful. A runtime `.json` may name extern crates: `"rust_externs": {"NAME": "tests/runtime/FILE.rs"}`; the harness builds each as an rlib, passes `--rust-extern NAME=RLIB` to pruvc and `--extern NAME=RLIB` to rustc. Injected-wrong-Rust fixtures use such an adapter crate to exercise false ensures (caught only with `all`), panic, i128/budget failures and single evaluation of arguments.

## 13. A3 implementation decisions (fixed 2026-11-12, before implementation)

These narrow §5.3–§5.4 to a first LLVM bridge that both compilers emit byte-identically. Deviations from §5.3/§5.4/§7.5 are listed in 13.6.

### 13.1 Supported on LLVM in A3

- Collections whose element, key and value types are `i64` or `bool`: `Vec<i64|bool>`, `HashMap<i64|bool, i64|bool>`, `String`; `map_get` results `Option<i64|bool>`.
- `trusted rust fn` with parameters `i64`, `bool`, `[i64]`, `[u8]`, `[bool]`, `str` and results `i64`, `bool`, `()`.
- Run-time `requires` evaluation (generated only for `--no-verify` builds of collection-bearing functions on LLVM) supports `len(c)` but not `v[i]`, `s[i]`, `map_lookup` or `map_updated`; such a requires is outside the subset on LLVM (fixed after the A3 audit; the Rust backend supports them).
- Anything else G6 on LLVM (other element types, Option/Result in trusted signatures) keeps `codegen/unsupported_type` with the message "G6 foreign calls and collections are not implemented by the llvm codegen layer yet" at the first such construct (those runtime fixtures stay in `tests/llvm_pending.txt`).
- The supported build is the **Rust host build**: the generated bindings file (`--rust-bindings`), compiled by rustc together with the LLVM object and the runtime object (exactly how `tests/run_all.py` links LLVM rows). The canonical driver's `--emit exe|obj` for a G6 program reports `codegen/foreign_target` "a G6 program on the LLVM backend needs the Rust host build (generated bindings compiled by rustc)".

### 13.2 Shim (in the generated bindings file)

- The bindings file gains, only for G6 programs, a module `pruv_g6_shim` containing exactly the A2 Rust helpers the program uses (same text, same check mode, same budget, same preludes they need) and, for each, one `#[no_mangle] pub extern "C"` adapter named `pruv_g6_v1_<helper name>`, plus `#[no_mangle] pub static pruv_g6_bridge_v1: u8 = 1;`. The LLVM module declares `@pruv_g6_bridge_v1 = external global i8` and references it from every G6 function, so linking without the shim fails.
- Representations: `i64` as i64; `bool` as i64 0/1 (anything else → `pruv: invalid representation: bool`); a collection handle as `ptr` to a `Box` of the concrete Rust collection; a borrowed array/str as `(ptr, i64 len)` (the adapter checks `0 <= len <= 2^40`, uses an empty slice for len 0, checks bool bytes 0/1 and UTF-8 for str → `pruv: invalid representation: ...`); `Option<i64|bool>` results through two out-pointers `(ptr tag_out, ptr val_out)` (tag 0/1; val 0 for None).
- Consuming updates (`vec_push`, `map_insert`, `string_push_str`) take the handle, replace the boxed value in place (`std::mem::take` + helper + store back) and return the **same** pointer (no allocation per update). Constructors return a fresh `Box::into_raw`. Reads borrow (`&*p`). `pruv_g6_v1_drop__<C>(ptr)` frees once (`<C>` = `vec__i`, `vec__b`, `hashmap__i__i`, …, `string`; the G3 encoding of the full collection type). `string_to_str` becomes `pruv_g6_v1_string_bytes(h, ptr data_out, ptr len_out)` (borrowed view) followed on the LLVM side by the existing `pruv_copy` into a fresh G2 `str`.
- Every adapter runs its body under `catch_unwind`; on a panic (the panic hook has already printed the `pruv: ...` message) it calls C `fflush(NULL)` and `std::process::exit(101)`. No unwinding crosses into LLVM frames.

### 13.3 LLVM code generation

- A collection value is an SSA `ptr`. Each owned collection binding (`let` local, `take` parameter) has an `alloca ptr` slot initialized to null. Reading a binding in a borrow position loads the slot. `move x` loads the slot and stores null. Assignment evaluates the right side, then drops the old slot value if non-null, then stores. At every scope exit (end of block, each loop iteration's body end for loop-local bindings, and before `ret` for all enclosing scopes, innermost first, reverse declaration order) each owned slot is loaded and dropped if non-null. A fresh collection result used only in a borrow position is a temporary dropped at the end of its statement (existing temporary machinery). Borrowed parameters are never dropped. Returning a collection moves it out (slot nulled) before the drops.
- Collection-bearing functions are internal and get no `pruv_abi_*` wrapper and no binding.
- `len(c)` calls `pruv_g6_v1_len__<C>`.

### 13.4 Tests

The A2 runtime fixtures run on LLVM unless they use something outside 13.1 (those stay pending and are listed). The shim always keeps a count of live boxes in a static atomic (incremented on every `Box::into_raw` of a new collection, decremented on drop). When the environment variable `PRUV_G6_COUNT=1` is set, the first constructor registers a C `atexit` handler that prints `pruv-g6-live: N` to stderr. A runtime `.json` may set `"g6_drop_balance": true`; the harness then sets the variable on LLVM rows and requires `N == 0`.

### 13.5 Python/Rust parity

Both compilers emit identical `.ll` and bindings text for G6 programs (`tests/diff_llvm.py`).

### 13.6 Deferred from §5.3–§5.4/§7.5

Collection observers in LLVM run-time `requires` (13.1); the `all`-mode byte comparison of `string_to_str` on LLVM (the copy is made by the existing `pruv_copy` from the borrowed bytes, so the shim has no separate snapshot to compare); bundle digest symbol `pruv_g6_bundle_<sha256>`, aggregate (G3 value) payloads across the bridge, `--emit exe/obj` link driver via rustc, `--rust-search`, the 16-probe ABI suite and other targets than the host. They are follow-ups after A4 and do not block the Rust-source path.
