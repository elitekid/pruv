# G3: Generics — Type Parameters and Parametric Contracts

Status: **Implemented (G3a A0–A5 and Q), 2026-11-12 — RESULTS §45–46**

This document defines the first release of G3, called **G3a**. Its implementation batches are A0–A5 and Q. All test counts below are acceptance requirements, not measured results.

The objective is to introduce parameterized types and functions, with verification once per generic definition, before the performance pass and G6 Rust interoperability. G3a deliberately supports copyable values; it does not introduce Rust collection implementations or ownership-bearing generic payloads.

## 0.0 Confirmed decisions for this design

“Confirmed” means fixed within this proposed implementation contract, not an assertion of prior project approval.

1. **Functions, structs, and enums may declare type parameters.** Parameters are first-order types, scoped to one declaration. Generic type applications may be nested.
2. **An unconstrained parameter ranges over copyable Pruv value types:** `i64`, `bool`, and finite compositions of structs, enums, `Option`, and `Result`. Arrays, `str`, `()`, and storage-only `u8` are not type arguments.
3. **`Option<T>` and `Result<T>` are generalized.** `Result<T>` retains an `i64` error payload. A second built-in error type parameter is deferred; a user-defined generic enum can express two independently typed alternatives.
4. **`[T]` requires `T: Element`.** The only concrete members of this built-in capability are `i64` and `bool`. This permits generic length, indexing, allocation, copying, and mutation without expanding the G2 storage model.
5. **`[u8]` remains a concrete storage-specialized array.** Its read expression remains `i64`. `u8` is not a scalar type or an admissible type argument. `[u8]` cannot instantiate `[T]`.
6. **No user-defined traits or bounds.** `Element` is the sole new bound spelling. Copyability and contract equality are implicit properties of the admitted value universe, not user-implementable interfaces.
7. **Type arguments are explicit.** Generic calls use `f::<T>(x)`. Generic nominal constructors use `Pair::<T> { ... }` and `Choice::<T>::Left(x)`. There is no generic type-argument inference.
8. **Existing unqualified built-in constructors retain their i64 meaning.** `Some(x)`, `None`, `Ok(x)`, and `Err(x)` remain shorthand for the existing i64 constructors. New instantiations use `Some::<T>(x)`, `None::<T>`, `Ok::<T>(x)`, and `Err::<T>(code)`.
9. **Abstract values support copying and contract equality, not arithmetic or runtime equality.** `T == T` is legal in contracts. Runtime equality remains restricted to expressions statically typed `i64` or `bool`, preserving the current distinction between scalar and aggregate equality.
10. **Verification happens before specialization.** Each generic definition is verified with fresh uninterpreted SMT sorts for its type parameters. Its body is not reverified for each concrete instantiation.
11. **Both backends monomorphize.** The Rust source backend emits concrete functions and concrete nominal types, rather than public Rust generic functions. LLVM uses the same specialization plan.
12. **Generic definitions have no direct external ABI.** Existing non-generic Pruv functions remain public entry points and can wrap generic calls. No export-instantiation syntax or CLI flag is added.
13. **Refinements remain annotations on existing types.** `[T; <=N]` is supported for `T: Element`; numeric refinements on `T` and `[T]` are rejected. Refinements cannot appear inside type arguments.
14. **`--infer` remains definition-level.** No new inference templates are required. Candidate generation must exclude abstract values and abstract array elements from scalar-specific templates; final verification remains mandatory.
15. **No recursion or polymorphic recursion.** Function recursion is rejected on declaration identities, independent of type arguments. Nominal type dependencies must remain acyclic.
16. **A6 stays separate.** G3a neither adds `[i32]` nor reinterprets narrow storage types as scalar type arguments.
17. **Python first, Rust port in the same batch, then cross-check.** An incomplete downstream layer must reject explicitly with `unsupported_type`, including under `--no-verify`.
18. **Preserve old behavior deliberately.** Existing accepted programs retain their semantics and external signatures. Legacy SMT snapshots remain unchanged. Rejections intentionally superseded by G3 receive explicit migrations rather than disappearing from the regression inventory.

### 0.0.1 Implementation sequence

| Batch | Deliverable | Minimum exit evidence |
|---|---|---|
| A0 | Structured type representation, substitution API, compatibility baseline | 24 type/substitution unit cases; legacy parse/check dumps and 231-input SMT snapshot unchanged |
| A1 | Generic syntax, checking, bounded arrays, constructor typing | 33 new-code rejection samples; 20 accepted frontend samples; Python/Rust dumps identical |
| A2 | Parametric verification, contracts, refinement and inference integration | 20 positive proof samples; 29 reused-code rejection samples; 8 inference cases; strict trace equality |
| A3 | Shared specialization plan and Rust source backend | 2 specialization-limit rejection samples; 12 plan cases; 16 Rust-backend runtime cases |
| A4 | LLVM lowering, bindings, concrete ABI | The same 16 runtime cases on LLVM; 10 ABI cases; Python/Rust IR and bindings identical |
| A5 | Integrated release gate, audits, compatibility migrations | At least 64 rejection files, 20 examples, 24 runtime cases; full regression and all 12 current cross-check stages |
| Q | Fuzzing, mutation, measurements, independent use | Three seeds × 100 verified generic programs; at least 60 classified incorrect mutants; four independent-use problems |

Section 7 specifies ownership, ordering, and exact gate interpretation.

## 1. Scope and current foundation

### 1.1 Verified repository facts

The following observations come from reading the named files, not from executing the compiler.

| Area | Observed implementation | Evidence |
|---|---|---|
| Roadmap | G3 precedes a performance pass and G6; generic Rust library types motivate this order; A6 remains deferred | `BLUEPRINT.md:159–193` |
| Python types | `Type` currently stores one name; arrays use named internal types | `pruvc/vast.py:9–21`, `pruvc/typeinfo.py:7–35` |
| Rust frontend types | AST types are strings | `pruvc-rs/crates/pruv-core/src/ast.rs:1–6` |
| Rust proof types | `Ty` distinguishes scalars, `Array(Elem)`, strings, fixed Option/Result, and named user types | `pruvc-rs/crates/pruv-proof/src/model.rs:35–113` |
| Built-in payloads | Both parsers restrict `Option` and `Result` to i64 | `pruvc/vparser.py:326–344`, `pruvc-rs/crates/pruv-core/src/parser.rs:390–420` |
| Array typing | G2 recognizes i64/u8/bool storage; byte reads produce i64, bool reads produce bool | `pruvc/typeinfo.py:14–30`, `pruvc/check.py:402–405` |
| Nominal types | Fields reject unit, arrays, and strings; type and function recursion are rejected | `pruvc/check.py:87–143` |
| Equality | Runtime equality is scalar-only; contracts allow value equality; arrays and strings reject whole-value equality | `pruvc/check.py:383–396`, `pruvc-rs/crates/pruv-core/src/check.rs:830–853` |
| SMT | Option/Result currently have integer payloads; user aggregates use SMT datatypes | `pruvc/verify.py:11–13,110–163`, `pruvc-rs/crates/pruv-proof/src/model.rs:1–15` |
| Modular calls | Calls prove requires, create a fresh result, and assume ensures; the callee separately checks contract definedness | `pruvc/verify.py:840–870`, `pruvc-rs/crates/pruv-proof/src/symbolic.rs:1240–1289` |
| Refinements | Expansion precedes ordinary type checking and preserves base types | `pruvc/refine.py:1–24`, `SPEC.md:215–273` |
| Inference | Candidate generation filters bool-element templates and disallows calls other than `len`; inference is followed by full verification | `pruvc/infer.py:395–418`, `pruvc/verify.py:1118–1150` |
| Rust generation | Public value types derive Copy and equality; runtime contracts use recursively widened i128 mirror types | `pruvc/codegen.py:43–49,231–303`, `pruvc-rs/crates/pruv-core/src/emit_common.rs:1–86` |
| LLVM ABI | Nominal aggregates use word serialization; legacy Option/Result have special handling; array/string entry checks are separate | `pruvc/llvmgen.py:45–49,156–179,1348–1429`, `pruvc-rs/crates/pruv-core/src/abi.rs:1–183` |
| Bindings | Existing bindings contain concrete type mapping and v2 allocation helpers | `pruvc-rs/crates/pruv-core/src/bindings.rs:1–135` |
| Regression inventory | `run_all.py` supports row listing and comparison; source counts are not execution-row counts | `tests/run_all.py:1–35` |
| Cross-check stages | The current runner has 12 stages: the original eight plus four ABI stages | `tests/m3_all.py:1–18,52–66` |

The G2 spec contains historical descriptions of pre-G2 code. Those historical descriptions are not used as evidence of the current implementation.

### 1.2 Included in G3a

- Generic functions, structs, and enums.
- Nested finite value types, including `Option<bool>`, `Option<Pair<i64, bool>>`, and `Result<Option<T>>`.
- Generic argument passing, returns, locals, field access, field assignment, construction, and exhaustive matching.
- Generic-to-generic calls with explicit type substitution.
- Contract equality, constructor tests, payload access, and index-bounded quantification involving abstract values.
- `[T]` for `T: Element`, including G2 ownership and effects.
- Both code-generation backends, runtime contract checks, and concrete host wrappers.
- Definition-level compatibility with refinements and `--infer`.

This foundation supplies parameterized signatures and contracts for later interoperability. It does **not** claim that every Rust library type is already representable.

### 1.3 Explicit non-scope

- Rust calls, foreign declarations, trusted external contracts, or implementations of `Vec`, `HashMap`, and `String` operations.
- Arrays or strings as generic arguments or aggregate payloads.
- `Option<str>`, `Result<[i64]>`, nested arrays, and arrays of user-defined values.
- Scalar `u8`, scalar `i32`, `[i32]`, casts, narrow arithmetic, or wraparound.
- Generic aliases, higher-kinded types, const generics, lifetime parameters, references, or borrowing beyond existing array/string parameters.
- User traits, trait implementations, trait objects, associated types, operator overloading, specialization, or runtime type inspection.
- Generic numeric algorithms requiring order or arithmetic on `T`, such as `max<T>`.
- Runtime equality on abstract or aggregate values.
- Function values, generic callbacks, closures, and higher-order contracts.
- Recursive types, recursive functions, and polymorphic recursion.
- Type-argument inference, partial type arguments, defaults, or `_` placeholders.
- Arbitrary Rust instantiation of generated generic functions.
- New invariant inference templates or an automatic proof-specialization fallback.

## 2. Syntax

### 2.1 Declaration and type grammar

The following extends existing grammar; existing contracts, effects, refinements, and statements remain unchanged.

```text
TypeParams   ::= "<" TypeParam ("," TypeParam)* ">"
TypeParam    ::= UpperIdent [ ":" "Element" ]

Function     ::= "fn" Ident [TypeParams] "(" Params ")" "->" Type
                 [Effects] Contracts Block

Struct       ::= "struct" UpperIdent [TypeParams] "{" Fields "}"
Enum         ::= "enum" UpperIdent [TypeParams] "{" Variants "}"

Type         ::= "i64" | "bool" | "()" | "str"
               | UpperIdent
               | UpperIdent "<" TypeArgs ">"
               | "[" ArrayElement [LengthRefinement] "]"
               | ExistingConcreteRefinedType

TypeArgs     ::= Type ("," Type)*

ArrayElement ::= "i64" | "u8" | "bool" | TypeParameter
LengthRefinement ::= ";" "<=" IntegerLiteral
```

Semantic restrictions determine which parsed types are legal type arguments and array elements.

- A type-parameter list is nonempty.
- No trailing comma is added to the new angle-bracket lists.
- Parameters are unique within a declaration and start with an uppercase letter.
- A parameter cannot shadow a declared type, a built-in type constructor, or another parameter.
- `Element` is contextual in a bound position, not a new globally reserved identifier.
- `T<X>` is invalid: a type parameter is not a type constructor.
- Nested closing `>` tokens must parse without requiring spaces.
- Existing reserved-identifier rules continue to apply.

### 2.2 Calls and constructors

```text
GenericCall       ::= Ident "::" "<" TypeArgs ">" "(" Arguments ")"
GenericStructLit  ::= UpperIdent "::" "<" TypeArgs ">" "{" FieldInitializers "}"
GenericEnumCtor   ::= UpperIdent "::" "<" TypeArgs ">" "::" Variant
                      [ "(" Arguments ")" ]

GenericBuiltinCtor ::= "Some" "::" "<" Type ">" "(" Expr ")"
                     | "None" "::" "<" Type ">"
                     | "Ok"   "::" "<" Type ">" "(" Expr ")"
                     | "Err"  "::" "<" Type ">" "(" Expr ")"
```

Examples:

```pruv
struct Pair<A, B> {
  first: A,
  second: B
}

enum Choice<A, B> {
  Left(value: A),
  Right(value: B)
}

fn identity<T>(x: T) -> T
  ensures result == x
{
  return x;
}

fn swap<A, B>(p: Pair<A, B>) -> Pair<B, A>
  ensures result.first == p.second
  ensures result.second == p.first
{
  return Pair::<B, A> {
    first: p.second,
    second: p.first
  };
}

fn use_identity(x: i64) -> i64
  ensures result == x
{
  return identity::<i64>(x);
}
```

Bare `identity(x)` is rejected even if its argument appears sufficient to infer `T`.

Built-in compatibility is explicit:

```pruv
let a: Option<i64> = Some(7);
let b: Option<bool> = Some::<bool>(true);
let c: Option<bool> = None::<bool>;
let d: Result<bool> = Err::<bool>(3);
```

`Some(true)` does not acquire a new inferred interpretation.

### 2.3 Patterns and contract selectors

Patterns obtain type arguments from the checked scrutinee:

```pruv
match value {
  Choice::Left(x) => { ... }
  Choice::Right(y) => { ... }
}
```

Pattern qualifiers do not accept explicit type arguments. The named declaration must match the scrutinee’s nominal declaration.

The same rule applies to:

```pruv
is_variant(value, Choice::Left)
variant_field(value, Choice::Left, value)
```

The checker records the complete instantiated nominal type on these nodes. Matching and field selection never erase type arguments.

## 3. Type rules

### 3.1 Admissible value universe

Define `Value` recursively:

```text
Value ::= i64
        | bool
        | Option<Value>
        | Result<Value>
        | D<Value, ...>
        | NonGenericValueDeclaration
```

Every field of an admitted declaration must itself be a `Value`. Declarations must be acyclic.

`Value` is a specification category, not source syntax.

An unconstrained parameter `T` ranges over `Value`. This gives:

- fixed-size, copyable values;
- no ownership or drop behavior;
- structural equality suitable for contracts;
- no requirement for a default value.

`()` remains usable as an ordinary function return type, but is not a generic argument or aggregate field.

Empty structs and payload-free enum variants remain legal. Unused type parameters are allowed. Monomorphization avoids introducing a Rust `PhantomData` field into the language’s value model.

### 3.2 The `Element` bound

`T: Element` adds one capability: `[T]` is well formed.

The concrete members are exactly:

```text
Element = { i64, bool }
```

A parameter with this bound is still abstract. It does not gain arithmetic, ordering, boolean operators, or runtime equality.

Examples:

```pruv
fn first<T: Element>(a: [T]) -> T
  requires len(a) > 0
  ensures result == a[0]
{
  return a[0];
}

fn repeat<T: Element>(n: i64, value: T) -> [T] ! alloc
  requires 0 <= n && n <= 1000
  ensures len(result) == n
  ensures forall k in 0..n: result[k] == value
{
  let out: [T] = alloc(n, value);
  return out;
}
```

`first::<i64>` and `first::<bool>` are legal. `first::<Point>` and `first::<u8>` are not.

A generic caller may pass its parameter `U` to an `Element`-bounded callee only when `U` also has the bound.

This restriction intentionally leaves user-value array layout outside G3a.

### 3.3 Allowed operations

| Operation on abstract `T` | G3a |
|---|---|
| Bind, copy, assign a mutable local, pass, return | Allowed |
| Store in a generic value field or payload | Allowed |
| Contract `==` / `!=` with the same static type | Allowed |
| Runtime `==` / `!=` | Rejected |
| Arithmetic, ordering, unary minus | Rejected |
| Boolean operators or use as an `if` condition | Rejected |
| Field access directly on `T` | Rejected |
| Match directly on `T` | Rejected |
| `print(T)` | Rejected |
| Construct an arbitrary `T` from a literal | Rejected |
| Index, allocate, copy, or mutate `[T]` | Allowed only with `Element` |

A field such as `Pair<T, i64>.second` is concretely `i64` and retains ordinary integer operations. A field whose substituted type is `T` remains abstract.

The checker must not inspect known call-site specializations to authorize operations inside a generic body.

### 3.4 Instantiation

For each generic application:

1. Resolve the declaration and check type-argument arity.
2. Resolve every type argument in the caller’s type-parameter scope.
3. Check the admissible value universe and each `Element` requirement.
4. Perform capture-avoiding substitution throughout the signature.
5. Check value arguments against the substituted parameter types.
6. Record the resolved declaration identity and complete substitution on the checked expression.

Type equality is structural for applications and nominal for declarations. `Pair<i64, bool>` and `Pair<bool, i64>` are different types.

Substitution must cover:

- field and payload types;
- local annotations;
- constructors and selectors;
- expression types;
- nested call type arguments;
- contracts and refinement-generated expressions.

There are no implicit conversions or subtyping between instantiations.

### 3.5 Option and Result

For `Option<T>`:

- `Some::<T>(x)` requires `x: T`;
- `None::<T>` has no payload;
- `some_val` returns `T` and retains its existing domain obligation;
- `Some(x)` match binders have type `T`.

For `Result<T>`:

- `Ok::<T>(x)` requires `x: T`;
- `Err::<T>(code)` requires `code: i64`;
- `ok_val` returns `T`;
- `err_val` returns `i64`;
- `Ok(x)` and `Err(code)` bind these respective types.

Whole-value equality remains contract-only and compares the constructor and active payload.

`Option<i64>` and `Result<i64>` normalize to the legacy types, including when obtained through substitution. They must not acquire duplicate representations or incompatible ABI identities.

### 3.6 Arrays, ownership, and allocation

The existing G2 rules apply to `[T]`:

- Parameters are read-only borrowed views.
- A local array binding or reassignment requires an owned source: `alloc`, `copy`, or an array-returning call.
- A parameter cannot be returned directly; use `copy`.
- Only mutable local arrays permit element stores.
- Whole-array equality remains forbidden.
- `len` returns i64.
- Indexing returns `T`; a store requires exactly `T`.
- `alloc` and `copy` require `alloc`.
- The length bound remains `0..=2^40`.
- Evaluation remains left-to-right; stores evaluate index, value, then store.

G2’s limited allocation hint rule is retained. An expected `[T]` reaches `alloc` only when it is the direct expression of a typed let, reassignment, or return.

Thus:

```pruv
let out: [T] = alloc(n, value);
```

is legal, while a generic `alloc(n, value)` nested directly in an argument position receives no new contextual inference. Bind it first.

A generic function may independently accept concrete `[u8]` or `str` parameters. Those parameters do not become values of `T`.

### 3.7 Refinements

- Concrete i64 and u8 refinements retain their existing meanings.
- `[T; <=N]` is legal when `T: Element`.
- `T | L..=U` and `[T | L..=U]` are rejected with `refinement_base`, even if all current callers use i64.
- A refinement within a type-argument list is rejected with `refinement_position`.
- Type arguments describe base types, never refined subtypes.
- Refinement expansion occurs once on the definition. Specialization substitutes its output; it does not expand it again.
- A refined concrete argument may be passed to a generic function using its base type. Its refinement facts remain caller facts; they do not silently strengthen the generic definition.

There is no new mechanism for propagating a caller’s numeric refinement through an opaque `T`. Such preservation must follow from the generic function’s explicit equality or structural contract.

### 3.8 Contracts and aggregates

Contracts may use:

- equality between same-typed abstract values;
- known generic constructors and fields;
- Option/Result predicates and guarded payload access;
- `[T]` length and guarded element access;
- bounded integer quantifiers;
- `count` over a boolean condition involving abstract equality.

Examples:

```pruv
ensures result == x
ensures is_some(result) && some_val(result) == x
ensures forall k in 0..len(a): a[k] == value
ensures result == count(k in 0..len(a): a[k] == value)
```

`sum`, `max`, and `min` still require i64 bodies. They cannot consume a `T` or `[T]` element. `count(k in ...: a[k])` is also invalid for abstract `T`; the body must be statically bool.

User function calls remain forbidden in contracts, including generic functions.

## 4. Proof semantics

### 4.1 Definition-level model

For a generic function with parameters `T0, …, Tn`, create fresh uninterpreted sorts:

```text
g3!<function-declaration-index>!T0
...
g3!<function-declaration-index>!Tn
```

These identities are based on declaration and parameter positions, not source spelling alone.

A sort has no cardinality, ordering, numeric-range, representation, or default-value axioms.

`T: Element` uses the same uninterpreted-sort treatment. Its implementation restriction is checked statically; the verifier proves a stronger theorem over arbitrary element domains.

Do not model `T` as an integer with unknown bounds or as a tagged union of all permitted concrete types.

### 4.2 Type interpretation

| Type | SMT interpretation |
|---|---|
| Abstract `T` | Fresh uninterpreted sort |
| `Option<T>` | Datatype with `None` and `Some(T)` |
| `Result<T>` | Datatype with `Ok(T)` and `Err(Int)` |
| `Pair<A, B>` | Datatype whose fields have the substituted sorts |
| Generic enum | Datatype with one constructor per variant and typed payloads |
| `[T]` | Pair of `Array(Int, sort(T))` and integer length |
| Concrete types | Existing interpretation |

SMT datatype caches are keyed by complete structural type identity and the current abstract-sort environment.

An application such as `Pair<T, T>` must reuse the same sort in both fields. `Pair<T, U>` must retain two independently identified sorts.

No axiom says values of distinct type parameters are unequal. They are statically incomparable. A caller may instantiate two distinct parameters with the same concrete type.

For all G3-free inputs, retain legacy sort names and declaration ordering, including `Opt` and `Res`.

### 4.3 Well-formedness and state changes

An abstract scalar has no additional well-formedness predicate.

Concrete i64 leaves retain existing range predicates. Generic datatypes apply well-formedness recursively to known concrete leaves and active payloads. For example, `Result<T>` still bounds its error code.

An abstract array carries:

```text
0 <= length <= 2^40
```

Its operations are:

- allocation: prove length validity, then construct `K(value)`;
- copy: preserve the logical contents and length;
- read: prove index validity, then use `Select`;
- store: prove index validity, then use `Store`;
- call result or loop havoc: create a fresh correctly typed array.

No numeric domain is introduced for abstract elements.

Existing concrete u8 domain restrictions remain at G2’s established introduction points. G3 must not introduce assumptions after an invalid store that make later obligations vacuous.

### 4.4 Contract instantiation at calls

A generic call uses a checked type substitution `θ` and evaluated value arguments.

The verifier:

1. Evaluates arguments once, in source order.
2. Interprets the callee’s typed contract under `θ` in the caller’s SMT environment.
3. Proves each substituted requires clause in declaration order.
4. Creates a fresh result of the substituted return type.
5. Adds the permitted result well-formedness facts.
6. Assumes the substituted ensures clauses.

This is typed contract re-interpretation, not textual replacement inside an SMT string.

The callee’s generic proof establishes contract definedness under parameter well-formedness and preceding requires. The caller retains the existing modular rule rather than reproving the body or assuming an unchecked requires clause.

Calls between generic functions map callee parameters to caller type expressions. For example, `identity::<Option<T>>(x)` uses the caller’s `Option<T>` datatype.

### 4.5 Obligations

No new logical proof-obligation category is required solely for polymorphism.

Existing obligations remain applicable:

- `call_requires`;
- `ensures`;
- assertion obligations;
- `contract_domain` and `variant_domain`;
- `index_oob`;
- allocation-length obligations;
- invariant entry and preservation;
- decreases obligations;
- concrete arithmetic and refinement obligations.

Type-argument validity and bounds are static checks, not solver assumptions.

A generic definition is verified even if no concrete call reaches it. Verification errors remain attached to the definition’s source location and function name.

A false generic specification cannot pass because its currently observed concrete instances happen to satisfy it.

### 4.6 Soundness argument

The proof treats a type parameter as an arbitrary domain whose values can be transported and compared for equality in contracts. The body cannot inspect representation, invent an arbitrary value, or use operations unavailable on that domain.

Every admitted concrete type provides such a domain:

- copying preserves its value;
- constructor and field operations follow the datatype interpretation;
- equality is structural and compares active payloads;
- array indexing and mutation follow the array model.

Therefore, a property proved for the arbitrary domain also holds when the domain is replaced by an admitted concrete type. The `Element` restriction further limits execution to two supported array layouts; the proof does not depend on that finite list.

Distinct type-parameter sorts do not create a hidden “different types imply different values” assumption, because cross-parameter equality and casts are unavailable.

This argument depends on faithful substitution, matching runtime equality, well-formed boundary values, and correct specialization. Those are explicit audit targets.

### 4.7 Counterexamples and traces

Abstract values are not reported as invented i64 values.

Within each counterexample, render abstract values as:

```json
{"type_parameter": "T", "value": "opaque#0"}
```

Assign ordinals independently per abstract sort, in deterministic traversal order through parameters and nested fields. Repeated equal model values reuse an ordinal.

Arrays use the existing bounded counterexample display policy, with abstract elements represented by these tokens. Concrete bool values remain JSON booleans.

The tokens describe equality classes in one model. They are not serializable runtime inputs or global identities.

Trace records identify the generic definition. Adding another concrete instantiation must not add another verification of that definition.

### 4.8 Inference

Run Houdini once per generic definition, then run full verification once with its surviving candidates.

For generic definitions:

- retain applicable integer-counter and length candidates;
- exclude abstract scalars from numeric and boolean templates;
- exclude abstract array element reads and writes from element-specific templates;
- do not add generic equality inference templates in G3a;
- keep the ban on candidate calls other than `len`;
- maintain scope-sensitive type information at each loop position.

Explicit invariants may still use abstract equality.

Filtering must be based on actual typed expressions, not only the present bool-array name filter. A caller instantiating `T` with i64 must not cause additional definition-level arithmetic candidates to appear.

## 5. Specialization, code generation, and ABI

### 5.1 Shared specialization pass

Add a shared, deterministic specialization pass between successful verification and backend generation. Under `--no-verify`, run it after full type checking.

The pass must not mutate the checked generic program.

Roots are all non-generic functions, including those not called from `main`, because they are existing public entry points.

For each root:

1. Collect concrete generic calls.
2. Substitute the body and all type metadata.
3. Recursively collect concrete generic callees and nominal types.
4. Deduplicate by declaration identity and complete type-argument tuple.
5. Emit each specialization once.

Unused generic functions are checked and verified but generate no executable specialization.

The function declaration call graph must be acyclic before specialization. Checking only concrete instance cycles would miss polymorphic recursion.

Resource limits are fixed for G3a:

- at most 4,096 distinct generic function specializations;
- at most 4,096 distinct generic nominal type applications;
- maximum instantiated type nesting depth of 128, counting the root as depth one;
- at most 65,536 type nodes in a single instantiated type.

Exceeding a limit gives `codegen/specialization_limit`, identifying the triggering declaration or application. It must not produce a partial output artifact or an internal recursion error.

### 5.2 Deterministic naming

Use structural type encodings, never randomized hashes or collection iteration order.

```text
E(i64)          = i
E(bool)         = b
E(Option<X>)    = o E(X)
E(Result<X>)    = r E(X)

E(D<X0,...>)    = n <name-byte-length> "_" <name>
                   "_" <arity> ("_" E(Xi))*
```

A non-generic nominal type uses arity zero.

Generated specialization stems are:

```text
pruv_g3_f_<name-byte-length>_<function-name>_<arity>_<encoded-arguments>
pruv_g3_t_<name-byte-length>_<type-name>_<arity>_<encoded-arguments>
```

The argument encodings are separated by underscores and decoded structurally. Name lengths make nominal names containing underscores unambiguous.

Examples:

```text
identity<i64>   → pruv_g3_f_8_identity_1_i
Pair<i64,bool> → pruv_g3_t_4_Pair_2_i_b
```

The existing body/entry suffix conventions apply to function stems.

Non-generic symbols retain their existing names. Generic built-in applications normalize to their canonical type keys; `Option<i64>` and `Result<i64>` retain legacy lowering.

Output ordering is declaration order, then lexicographic structural argument encoding, with type dependencies emitted first.

### 5.3 Rust source backend

Emit concrete Rust functions and concrete nominal declarations from the specialization plan.

- `Option<X>` lowers to `::std::option::Option<R(X)>`.
- `Result<X>` lowers to `::std::result::Result<R(X), i64>`.
- Concrete nominal instances use generated names and existing value-type derives.
- `[i64]` and `[bool]` retain their current borrowed-parameter and owned-result mappings.
- No public unconstrained Rust generic function is emitted.
- Generic implementation functions are private; non-generic wrappers remain public.

Monomorphization avoids accidentally permitting a host Rust caller to choose a type outside Pruv’s admitted universe.

Runtime contract evaluation recursively builds the concrete contract mirror:

```text
C(i64)       = i128
C(bool)      = bool
C(Option<X>) = Option<C(X)>
C(Result<X>) = Result<C(X), i128>
```

Nominal mirrors apply the same transformation to every field and active payload.

Do not compare raw bytes or reuse execution i64 arithmetic inside contract mirrors.

### 5.4 LLVM backend

LLVM consumes the same concrete specialization plan as the Rust source backend.

For generic nominal instances, use the existing G1 shapes:

- struct: fields in declaration order;
- enum: i64 tag followed by all variants’ payload fields;
- contract mirror: recursively widened concrete integer leaves.

For new built-in applications:

```text
Option<X>, X != i64: { i1 present, L(X) payload }
Result<X>, X != i64: { i1 is_ok, L(X) ok_payload, i64 error_payload }
```

Unused payload storage is initialized deterministically and ignored semantically. Equality and selectors inspect only active payloads.

Legacy `Option<i64>` and `Result<i64>` keep their existing shared-payload layout.

No type parameters reach LLVM instruction selection, storage sizing, or ABI generation. Encountering one is an implementation failure caught by internal assertions and specialization tests.

Because `Element` admits only i64 and bool, generic arrays specialize directly to existing G2 layouts and allocation/free paths. No generic heap object representation or new allocation protocol is required.

### 5.5 Host exposure and `--rust-bindings`

A generic definition has no standalone ABI symbol and is not directly callable from generated bindings.

Expose an instantiation with a non-generic Pruv wrapper:

```pruv
fn first_bool(a: [bool]) -> bool
  requires len(a) > 0
  ensures result == a[0]
{
  return first::<bool>(a);
}
```

The wrapper receives ordinary verification and ordinary public-entry checks.

Concrete generic nominal types appearing in public wrapper signatures are emitted in generated Rust source and bindings under their deterministic generated names. They are not claimed to have Rust’s native generic-type ABI.

For newly supported value applications, extend G1 word serialization:

```text
W(i64)       = 1
W(bool)      = 1
W(Option<X>) = 1 + W(X)                 when X != i64
W(Result<X>) = 1 + W(X) + 1             when X != i64
W(struct)    = max(1, sum(field words))
W(enum)      = 1 + sum(all payload words)
```

The legacy i64 Option/Result word count remains two.

New generic aggregate arguments use pointers to these word representations. Returns use an explicit output pointer and return void. They do not depend on platform-specific native aggregate register classification.

New Option/Result words use tag `1` for Some/Ok and `0` for None/Err. Inactive words serialize as zero.

For new word-based applications:

- bool words normalize by the existing nonzero-to-true convention;
- Option/Result tags normalize by the same convention;
- an invalid nominal enum ordinal must be rejected before requires or body execution;
- inactive fields must not affect equality or payload access.

Generated typed bindings supply valid tags. Raw-pointer validity, sufficient storage, and alignment remain caller responsibilities.

Existing G2 bool-array and UTF-8 checks remain before requires and remain active under `--trust-callers`. The existing typed-entry optimization remains limited to its valid typed inputs.

No runtime ABI version bump is planned: G3a adds concrete value layouts and symbols while retaining the G2 allocation protocol. Existing public function signatures must remain unchanged.

### 5.6 Compilation modes

| Mode | Required behavior |
|---|---|
| Default | Verify generic definitions; specialize; retain public requires checks |
| `--trust-callers` | Same proof and specialization; retain existing policy of skipping public requires checks |
| `--no-verify` | Check generic definitions and applications; specialize; use existing safe arithmetic, indexing, and allocation |
| Both flags | Existing combined policy; type restrictions and representation checks still apply |
| `--infer` | Infer and verify at definition level before specialization |

As today, assertions, ensures, local refinements, and loop invariants are not new runtime checks under `--no-verify`.

A backend must not type-check a specialized body more permissively than the generic checker.

## 6. Diagnostics and rejection corpus

### 6.1 New codes

Language and proof failures use exit code 1. Unsupported intermediate layers also use exit code 1, never an internal-error exit.

| Stage | Code | Minimum files | Required cases |
|---|---|---:|---|
| parse | `generic_syntax` | 4 | Empty parameter list; missing type argument; unsupported bound-list syntax; malformed expression type application |
| type | `type_parameter` | 5 | Duplicate parameter; lowercase parameter; global type shadowing; parameter used as a type constructor; undeclared parameter used in a generic declaration |
| type | `type_arity` | 6 | Missing function arguments; too few; too many; arguments on a non-generic function; missing nominal arguments; wrong built-in arity |
| type | `type_argument` | 6 | Array argument; string argument; unit argument; nested owned payload; disallowed explicit constructor argument type; user value as an array element |
| type | `generic_operation` | 6 | Arithmetic on T; ordering on T; runtime equality on T; boolean operation on T; direct field access on T; direct match on T |
| type | `generic_bound` | 5 | `[T]` without Element; concrete non-Element application; unbounded forwarding; unknown bound; invalid bounded nominal application |
| type | `generic_main` | 1 | `main` declares type parameters |
| codegen | `specialization_limit` | 2 | Instance-count overflow; instantiated-depth overflow |
| **Total** | | **35** | |

Existing scalar storage spelling errors remain `element_storage_type`; do not change `u8` into a generic type argument merely to produce a newer code.

An unknown type outside a type-parameter context retains `unknown_type`.

### 6.2 Existing codes exercised by G3

Add at least **29** further rejection files:

| Category | Files | Required coverage |
|---|---:|---|
| Equality restrictions | 2 | Whole `[T]` equality; concrete generic aggregate equality in code |
| Recursion | 4 | Direct generic function recursion; mutual generic recursion; direct generic type cycle; type cycle hidden inside an argument |
| Contract/proof failures | 6 | False identity ensures; false field ensures; unmet substituted requires; unguarded Option payload; unguarded enum payload; unguarded generic array access |
| Ownership/type rules | 5 | Borrowed array return; array alias; parameter store; wrong generic field value; wrong generic constructor payload |
| Refinements | 4 | Scalar T range; element T range; refinement inside type argument; invalid length bound |
| Effects/contracts | 2 | Missing alloc effect; generic user call in a contract |
| Parametricity | 4 | Body valid only for i64; body valid only for bool; unused invalid generic body; rejection unaffected by adding a favorable concrete caller |
| Inference final pass | 2 | Bad generic index survives candidate exploration but fails final verification; bad generic ensures fails with inference enabled |
| **Total** | **29** | |

Combined minimum: **64 distinct rejection source files**, each with expected stage/code metadata.

Tests for a single-code failure should avoid earlier unrelated errors. The deterministic diagnostic order is parse, declaration/type resolution, refinement validation, body checking, verification, then specialization/code generation.

### 6.3 Legacy rejection migration

Some existing rejection tests intentionally become valid, such as admissible non-i64 Option payloads. Others, including storage-only payloads, remain invalid.

A0 records a migration manifest containing:

- source path;
- old expected stage/code;
- new expected acceptance or stage/code;
- the governing G3 rule;
- replacement positive or rejection row.

Do not demand unchanged rejection results for syntax explicitly legalized by G3. Do not silently delete the old row.

## 7. Implementation batches and file ownership

Path abbreviations:

- `P/` = `pruvc/`
- `C/` = `pruvc-rs/crates/pruv-core/src/`
- `V/` = `pruvc-rs/crates/pruv-proof/src/`
- `D/` = `pruvc-rs/crates/pruvc/src/`

New paths below are implementation targets, not claims that files already exist.

### 7.1 Rules for every batch

1. Implement and validate Python behavior first.
2. Port the same behavior to Rust within the batch.
3. Compare both implementations before closing the batch.
4. Run the full regression inventory in both compilers.
5. For proof or generation changes, also re-grade existing benchmarks in default and `--trust-callers` modes and run existing mutation checks, following `BLUEPRINT.md:237–241`.
6. Perform one audit and one confirmation after fixes. No unresolved required findings may remain.
7. Record results in `RESULTS.md` and update the G3 roadmap line.

One worker owns a file at a time. In particular, Python LLVM, ABI, and bindings work all share `P/llvmgen.py` and must have one owner.

### 7.2 A0 — Type foundation and baseline

**Frontend/type owner**

- Python: `P/vast.py`, `P/typeinfo.py`
- Rust: `C/ast.rs`, `C/typeinfo.rs`, `C/dump.rs`
- Proof representation adaptation: `V/model.rs`, `V/samples.rs`

**Harness owner**

- `tests/diff_py_adapter.py`
- `tests/diff_parse.py`
- `tests/run_all.py`
- `tests/smt_snapshot.py`
- New `tests/g3/type_substitution.py`
- New `tests/g3/legacy_migrations.json`

Introduce structured types with explicit constructors for base types, bound parameters, arrays, and nominal applications. A bound parameter carries declaration identity and parameter index.

Provide one shared API per implementation for:

```text
type equality
source formatting
legacy dump formatting
substitution
admissible-value checking
Element checking
dependency traversal
canonical specialization encoding
```

Consumers must not independently parse encoded type names.

**Exit criteria**

- 24 unit cases covering substitution, capture avoidance, repeated parameters, nested applications, canonical legacy types, arity, and name encoding.
- Old parse/check dump bytes unchanged when the input contains no G3 syntax.
- The existing 231-input SMT snapshot unchanged.
- Capture the actual current regression row inventory; do not reuse G2’s historical 444-row count.
- Complete the intentional migration manifest.
- No new source syntax accepted yet.

### 7.3 A1 — Frontend and static rules

**Frontend owner**

- Python: `P/vparser.py`, `P/check.py`, `P/refine.py`
- Rust: `C/lexer.rs`, `C/parser.rs`, `C/check.rs`, `C/refine.rs`, `C/dump.rs`
- Shared type files return to this owner only after A0 closes.

**Test owner**

- `tests/check_edge/g3_*.pruv`
- `tests/must_reject/g3_*.pruv`
- Matching JSON metadata
- `tests/diff_parse.py`, `tests/diff_py_adapter.py`

Implement all syntax, capability checks, constructor substitution, patterns, and array hints.

Dependency analysis traverses nested type applications. A reference to a nominal declaration anywhere inside a field type contributes a dependency edge, including phantom arguments.

**Exit criteria**

- All 33 new parse/type rejection files from §6.1 pass.
- At least 20 accepted frontend samples cover every declaration and expression form.
- Python/Rust parse and checked dumps match byte-for-byte.
- Untyped built-in constructors retain their legacy behavior.
- Later layers detect G3 recursively and return `unsupported_type`, including under `--no-verify`.

### 7.4 A2 — Parametric proof and inference

**Proof owner**

- Python: `P/verify.py`, `P/infer.py`
- Rust: `V/model.rs`, `V/symbolic.rs`, `V/obligation.rs`, `V/infer.rs`, `V/samples.rs`, `V/sys.rs`
- Proof orchestration: `V/lib.rs` as needed for the new type environment

**Test owner**

- `tests/diff_trace.py`, `tests/diff_py_adapter.py`
- `tests/inference/g3_*`
- G3 proof rejection files and positive examples
- New `tests/g3/proof_once.py`

Add uninterpreted-sort support, typed datatype applications, abstract values, contract substitution, and deterministic counterexample rendering.

**Exit criteria**

- 20 positive proof examples.
- All 29 reused-code rejection files from §6.2.
- Eight inference cases: four accepted and four rejected, including generic/scalar sibling functions and scope-sensitive loop typing.
- A proof-count test adds one, two, then ten instantiations and confirms an unchanged generic-definition obligation sequence.
- New deterministic traces classify as `same`; `cex_only` and `same_unknown` do not satisfy this gate.
- Legacy SMT snapshot unchanged.
- Both code generators continue to reject unsupported generic execution explicitly.

### 7.5 A3 — Specialization and Rust generation

**Specialization owner**

- New `P/mono.py`
- New `C/mono.rs`
- `P/pruvc.py`, `D/driver.rs`
- `C/lib.rs` for module integration

**Rust-generation owner**

- `P/codegen.py`
- `C/codegen.rs`, `C/emit_common.rs`

**Test owner**

- New `tests/g3/mono_plan.py`
- `tests/diff_rust.py`
- `tests/runtime/g3_*`
- The two specialization-limit rejection cases

Implement the shared plan, deterministic naming, immutable generic AST handling, recursive concrete contract mirrors, and private specialized functions.

**Exit criteria**

- Twelve specialization-plan cases covering deduplication, nested calls, multiple type parameters, unused definitions, phantom parameters, dependencies, legacy normalization, and deterministic ordering.
- Both specialization-limit cases reject cleanly.
- Sixteen runtime cases pass in both compilers on the Rust source backend.
- Generated Rust is byte-identical between compilers.
- Runtime requires checks exercise abstract equality specialized to bool and nested aggregates.
- The LLVM path remains an explicit `unsupported_type` failure for G3 execution.

### 7.6 A4 — LLVM, ABI, and bindings

**LLVM/ABI owner**

- Python: `P/llvmgen.py`
- Rust: `C/llvmgen.rs`, `C/abi.rs`, `C/bindings.rs`

**Test owner**

- `tests/diff_llvm.py`
- `tests/abi/check_generated.py`
- `tests/abi/check_abi.py`
- `tests/abi/gen/g3_*`
- `tests/abi/winci/prepare.py`
- `tests/abi/winci/run_windows.py`
- Existing G3 runtime samples

No runtime allocator change is scheduled. Any discovered need for one must be justified and separately tested before expanding this batch’s ownership.

**Exit criteria**

- The same sixteen runtime cases pass on LLVM.
- Ten ABI cases cover nested values, empty structs, every new built-in branch, generic nominal enums, bool arrays, concrete wrappers, invalid new enum tags, and legacy i64 Option/Result compatibility.
- IR and bindings are byte-identical between Python and Rust.
- Correct active-payload equality and inactive-payload initialization are tested.
- Allocation/free balance passes for generic array copies, reassignment, and early return.
- Host execution and Windows CI execution are reported separately. Cross-compilation alone is not recorded as Windows execution.

### 7.7 A5 — Integrated completion gate

**Integration owner**

- `tests/m3_all.py`
- `tests/run_all.py`
- G3 test inventories and migration manifest

**Documentation owner**

- `SPEC.md`
- `BLUEPRINT.md`
- `RESULTS.md`
- `docs/G3_SPEC.md`

**Exit criteria**

- At least 64 rejection files, 20 positive examples, and 24 runtime cases.
- The additional eight runtime cases cover evaluation order, failed requires, safe-mode bounds failure, short-circuit payload access, repeated instances, contract-budget behavior, concrete str coexistence, and repeated compilation determinism.
- Applicable runtime cases run across both compilers, both backends, and all four verification/trust mode combinations.
- Both compilers pass the complete current regression inventory, with only reviewed migration changes.
- All 12 current `m3_all.py` stages pass: parse, check, trace, trace_infer, llvm, rust, compilers, standalone, abi, abi_v2, abi_bool, abi_utf8.
- Legacy SMT remains unchanged; G3 deterministic traces meet the stricter `same` gate.
- No G3 `unsupported_type` staging guards remain for features included by this specification.
- Documentation distinguishes G3a completion from support for owned generic containers.

### 7.8 Q — Fuzzing, mutation, and measurement

**Fuzz owner**

- `bench/fuzz/generate.py`
- `bench/fuzz/oracle.py`
- `bench/fuzz/run.py`
- `bench/fuzz/README.md`

**G3 evaluation owner**

- New `bench/g3/PROBLEMS.md`
- New `bench/g3/mutate_ops.py`
- New `bench/g3/run.py`
- New `bench/g3/solutions/`
- New `bench/g3/results/`

Keep existing mutation operation lists unchanged.

**Exit criteria**

- Seeds 41, 56, and 57 each produce at least 100 verified programs that actually exercise G3.
- At least eight concrete inputs per accepted program.
- Compare both compilers, both backends, and verified/safe execution against an independent oracle.
- Per seed, at least 20 deliberately unproved but well-typed programs run only in safe mode.
- At least 60 independently classified incorrect mutants, with zero incorrectly verified mutants.
- Mutations include wrong type substitution, swapped fields, wrong active payload, deleted bounds guards, false ensures, and loss of a bound during generic forwarding.
- Crashes, timeouts, unknowns, and unsupported oracle cases do not count as successful rejection or execution.

Four independent-use problems are required:

1. Generic pair swapping.
2. Generic Option fallback.
3. First element of a nonempty generic array.
4. Generic array copying with a pointwise postcondition.

An independent author receives only the user-facing specification and problem. Record first-attempt outcomes and every diagnostic-driven revision. Final reference and independent solutions must pass all four problems.

## 8. Risks and acceptance measurements

| Risk | Required mitigation or measurement |
|---|---|
| Type-name strings hide nested structure | Structured type API and exhaustive substitution tests |
| Same parameter spelling leaks between functions | Binder identities and per-definition SMT environments |
| SMT datatype caches confuse applications | Full type-expression and sort-environment cache keys |
| Body checking becomes specialization-dependent | Reject invalid unused definitions; compare verdict after adding callers |
| Narrow storage is confused with a scalar type | Keep u8 outside the generic argument universe |
| Contract mirrors lose mathematical semantics | Recursive i128 conversion and nested runtime contract tests |
| Generic array inference creates ill-sorted formulas | Typed filtering before candidate submission; explicit inference rejection cases |
| Generic specialization changes public ABI | Non-generic wrapper boundary and legacy signature snapshots |
| Unused payloads affect equality | Active-variant equality tests and deterministic serialization |
| Specialization causes excessive output | Deduplication, fixed resource limits, output-size measurements |
| Generic proof adds repeated solver work | Obligation-count invariance under added instantiations |
| Copy-only design is mistaken for full Rust interop | Explicit owned-payload and G6 non-scope documentation |

Measure:

- verification time and obligation count for one, ten, and one hundred calls to the same generic definition;
- specialization count, output size, and generation time for one, ten, and one hundred distinct admissible applications;
- existing benchmark correctness and verification success;
- existing compile/proof median and upper-tail latency over at least five repeated runs.

A repeated regression above 10% in existing compile/proof time requires investigation and an explicit gate decision. No performance improvement is claimed in advance.

The expected benefit is reusable specifications and proofs. Reduced solver work relative to handwritten duplicated definitions is a **hypothesis to measure**, not a demonstrated result.

## 9. Evidence limits and follow-up boundary

### 9.1 Confirmed by this investigation

The repository files listed in §1.1 and the relevant sections of `SPEC.md`, `BLUEPRINT.md`, and `docs/G2_SPEC.md` were read. The proposed design is grounded in their current type, proof, generation, ABI, and regression mechanisms.

No file was modified. No compiler, regression suite, benchmark, ABI executable, or generated program was run during this read-only design task.

### 9.2 Not experimentally confirmed

The following are future implementation acceptance work:

- solver behavior and timing for abstract sorts and nested generic datatypes;
- byte-identical Python/Rust implementation of the proposed changes;
- runtime and ABI correctness of new concrete applications;
- specialization resource-limit behavior;
- fuzz, mutation, and independent-use results.

The numerical gates in this document are requirements, not repository results.

### 9.3 Deliberate follow-up boundary

G3a establishes type application, parametric proof, and deterministic specialization. Before G6 exposes ownership-bearing Rust types, a later design must specify their movement, borrowing, destruction, boundary validity, and contract model.

That later work may widen the admissible type-argument universe or add capabilities. It must not silently reinterpret G3a’s copyable parameters.

A6 narrow storage expansion remains independent: supporting `[i32]` does not by itself make i32 a scalar type, and neither `[u8]` nor `[i32]` should become `[T]` through an implicit storage-to-value conversion.

## 10. Implementation notes

Deviations decided during implementation (A0–A5):

- Legacy `Option<i64>` / `Result<i64>` constants count as nesting depth 2.
- The Rust AST carries `tparams`, `targs`, `inst` and `enum_ty` as real fields.
- `is_value` checks each declaration's declared fields once, with type parameters left abstract (linear in the program size).
- Unconstrained generic instances skip the well-formedness walk.
- ABI (de)serialization propagates the active-payload condition and zeroes the inactive words of generic-type outputs.
