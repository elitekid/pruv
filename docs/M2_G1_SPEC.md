# M2 = G1 Design: Structs and Enums

This document is the implementation spec for M2 (G1). The design was written by Codex gpt-6-astra (2026-11-10) and finalized after review by the main session.
Scope (user decision): fields are only scalars + nested user types, `[Point]` and `Option<Point>` are outside G1, and field assignment on a `let mut` local struct is allowed.

## 1. Syntax and language semantics

| Item | G1 decision |
|---|---|
| Types | Distinguished by name (nominal). Even with the same structure, different names are different types |
| Fields | Only `i64`, `bool`, `Option<i64>`, `Result<i64>`, user structs and enums |
| Excluded | Array and unit fields, direct and indirect recursive types, `[Point]`, `Option<Point>`, `Result<Point>`, generics |
| Value semantics | Construction, assignment, argument passing, return, and pattern binding are value copies. No aliasing or implicit allocation |
| Struct mutation | `p.x = e` and nested `p.a.b = e` on a `let mut` local variable are allowed |
| Enum mutation | Only reassignment of the whole value. No direct assignment to a variant payload |
| match | Statement only. For user enums and Option/Result alike, every variant exactly once |
| Patterns | Bind all fields of a variant to names in declaration order. No nested patterns, wildcards, guards, or `mut` patterns |
| Equality | In code, as before, only `i64` and `bool`. Struct and enum `==`·`!=` only in contracts |
| Contracts | Construction expressions, struct field access, structural equality, `is_variant`·`variant_field` are allowed |
| Output | `print` remains `i64` and `bool` only |

### Declaration and construction
```pruv
struct Point {
  x: i64,
  y: i64,
}

struct Frame {
  origin: Point,
  visible: bool,
  hint: Option<i64>,
}

enum Event {
  Empty,
  Hit(point: Point, accepted: bool),
  Failed(code: i64),
}
```
- A struct with 0 fields is allowed: `struct Marker {}`. An enum has at least 1 variant.
- A variant with 0 fields has no parentheses (`Empty()` is forbidden). Declarations are comma-separated, and a trailing comma is allowed.
- Type and function declarations are only at top level, may be mixed, and can refer to a type declared later.

```pruv
let p: Point = Point { x: 3, y: 4 };
let e: Event = Event::Hit(p, true);
let empty: Event = Event::Empty;
let mut frame: Frame = Frame { origin: p, visible: true, hint: Some(7) };
frame.origin.x = 8;
let x: i64 = frame.origin.x;
```
- A struct literal gives all fields exactly once in declaration order. No shorthand, defaults, or update syntax.
- Initial values and variant arguments are evaluated once each from the left.
- Field access is possible on any struct expression (`make_point().x`). The left side of a field assignment is only a struct field path starting from a local variable
  (`make_point().x = 1` and paths passing through an enum are forbidden). Store after the right side is fully evaluated.

### match
```pruv
fn event_x(e: Event) -> i64 {
  match e {
    Event::Empty => { return 0; }
    Event::Hit(p, accepted) => { return p.x; }
    Event::Failed(code) => { return code; }
  }
}
```
- The scrutinee is evaluated once. Bindings are immutable and valid only inside that arm.
- Shadowing an outer name and duplicate names within the same arm are forbidden (`shadow`). An unused payload is also given a name (no read obligation).
- The existing `Some(v)`·`None`·`Ok(v)`·`Err(c)` syntax is kept. A user variant is always qualified, like `Event::Hit`.
- Arm order is free, and commas are optional as before.

### Contract-only constructs
- `is_variant(e, Event::Hit)` : bool. Defined for every value.
- `variant_field(e, Event::Hit, point)` : the value of that field. Defined only when the actual variant is the specified variant.
- The second argument is a variant name and the third is a field name (not value expressions).
- When a public requires execution check reaches a wrong variant lookup:
  `pruv: requires undefined: variant_field expected Event::Hit.point` (exit code 101)
- `==`·`!=` are between the same types. A struct compares all fields; an enum compares only the variant and the active payload.
- Integer fields of a construction expression inside a contract are mathematical integers (the executed requires is checked i128 as before). The i64 range is not forced on values constructed in contracts.
- There is no direct enum field access (`e.point`).

### Names and parsing
- Type and user variant names: `[A-Z][A-Za-z0-9_]*`. Field names: `[a-z][A-Za-z0-9_]*`. The existing function and variable rules are kept.
- The bans on the `pruv_` prefix, containing `__`, `_`, and Rust reserved words also apply to new names (types, variants, fields).
- `Option`, `Result`, `Some`, `None`, `Ok`, `Err` cannot be used as user type names. The same name for a type and a function is forbidden.
  Fields of different types, and variants of different enums, may share names.
- Added keywords: `struct`, `enum`, `is_variant`, `variant_field`. Added tokens: `::`, `.` (the lexer handles `::` before `:` and `..` before `.`).
- `Parser.primary()` treats only **a name starting with an uppercase letter followed by `{`** as a struct literal (to avoid a conflict with `if flag { ... }`).
  To use an uppercase-named variable as a condition or scrutinee, wrap it in parentheses.
- Places to modify: `KEYWORDS`, `TOKEN_RE`, `Parser.program()`, `type_()`, `stmt()`, `postfix()`, `primary()` of `vparser.py`.

## 2. Type checking (check.py)

- Existing rules are kept: discarding a non-unit call result as a statement is `unused_value`, and a general expression statement is `useless_expr`.
  Whether a bound value is read later is not checked. The same holds for structs with Option/Result fields.
- Check order: ① collect top-level type and function names ② declaration names and duplicates ③ resolve all type references ④ type dependency graph and recursion check
  ⑤ function contracts, body types, effects ⑥ the existing `Checker.no_recursion()`.
- Recursion: if a field (in any variant) has a user type B, then A→B. Find cycles by DFS and report `recursive_type`, with `A -> B -> A` in the message.
  Recursion is rejected even if there is a variant without fields.
- Effects: construction, copy, access, equality, and match themselves have no effect. The effects of inner expressions propagate as before. No `alloc` effect.
- Extend `Checker._expr()`, `stmt()`, `ends_in_return()`. Replace direct `TNAME[...]` lookups with `typeinfo.type_name(t)`.
  Fill `Expr.ty` of every new expression. An unknown type must not cause `KeyError` or `internal_error`.
- If there are multiple errors, the first error in declaration and field order. For struct construction, an unknown field is reported first as `unknown_field`, and then remaining list problems as `struct_fields`.

### New error codes (JSON format and exit code 1 kept)
| stage | code | Condition |
|---|---|---|
| parse | `unsupported_type` | An unsupported type construction such as `[Point]`, `Option<Point>` |
| type | `type_name` | A type name does not start with an uppercase letter |
| type | `variant_name` | A variant name does not start with an uppercase letter |
| type | `field_name` | A field name does not start with a lowercase letter |
| type | `dup_type` | Duplicate type name across structs and enums together |
| type | `name_collision` | Type and function name collision |
| type | `unknown_type` | Reference to an undeclared type |
| type | `dup_field` | Duplicate field in the same struct or the same variant |
| type | `dup_variant` | Duplicate variant in the same enum |
| type | `empty_enum` | An enum with no variants |
| type | `field_type` | Array or unit field |
| type | `recursive_type` | Direct or indirect type cycle |
| type | `not_struct` | Field access or assignment on a non-struct value, wrong struct construction |
| type | `not_enum` | Variant construction, test, or lookup on a non-enum type |
| type | `unknown_field` | A field not present in that struct or variant |
| type | `struct_fields` | Missing, duplicate, or out-of-order fields in struct construction |
| type | `unknown_variant` | A variant not present in that enum |
| type | `match_arity` | Number of pattern binders differs from number of payloads |
| verify | `variant_domain` | Cannot rule out a reachable wrong variant field lookup in a contract |

Reuse of existing codes: reserved names `reserved_name` (redeclaring an existing built-in name is `reserved`), type mismatch `type_mismatch`,
constructor argument count `arity`, field assignment to an immutable target `immutable`, match target type `match_type`,
missing, duplicate, or other-enum arm `match_arms`, duplicate or shadowing binders `shadow`, user-type equality in code `eq_type`,
use of a contract-only construct in code `contract_only`.

## 3. Verifier (verify.py, z3)

### Type model
- Keep the existing `Opt`, `Res` Datatypes and reference them as they are from user fields.
- User types are created in dependency order. Struct: one constructor + an accessor per field. Enum: a constructor, recognizer, and field accessors per variant.
- i64 → `IntSort()`, bool → `BoolSort()`. Internal names are a per-program prefix + declaration number. Constructors and accessors are kept in a table (no recombining strings).
- `verify_program()` builds the per-program model table once and passes it to every `FnVerifier`. Equality is done as z3 expressions (no comparing Python objects).

### Value domain `well_formed(ty, value)`
| Type | Condition |
|---|---|
| i64 | `in_range(value)` |
| bool | True |
| Option | If Some, the payload is in the i64 range |
| Result | The active Ok/Err payload is in the i64 range |
| Struct | All fields `well_formed` |
| Enum | If each recognizer is true, all fields of that variant are `well_formed` (no assumption on inactive accessors) |

Apply recursively to function arguments, call results, and loop havoc results. Match binders take the field type. Extend `fresh()`·`run()`·`call()`·`havoc()`.
It is not applied to values constructed inside contracts (do not assume that `p.x + 1` is in the i64 range from `Point { x: p.x + 1, y: 0 }`).

### Field assignment and loops
`p.a.b = rhs`: ① evaluate rhs in the pre-assignment state ② rebuild the value of `p.a` with only b changed ③ rebuild the value of `p` with a changed ④ store in `env["p"]`.
`FnVerifier.assigned()` puts `FieldAssign.name` into the mutated set and traverses into nested if, while, and match.
**In a loop, the whole changed root struct is havoced** (sibling fields are also unknown without an invariant). Add a sort→Type table so that `havoc()` restores the user-type and Opt/Res domains.

### match and calls
- Evaluate the scrutinee once, add the recognizer to the path condition for each arm, and bind accessor results with the field types.
- At the end of an arm, remove the binders and arm locals from the environment and leave only updates to outer variables. If all arms return, there is no subsequent state.
- A call returning a user type: a fresh Datatype value + `well_formed`, then assume the callee's ensures. Always use `FnVerifier.assume()` so that it does not leak outside the short-circuit path.

### Domain of a contract's variant fields `variant_domain(expr, env)` = D
A z3 accessor has a value even for a wrong constructor, so `variant_field` must not be translated as just the accessor.
- Strict operations: the conjunction of the operands' D. `a && b`, `a ==> b`: `D(a) && (a ==> D(b))`. `a || b`: `D(a) && (!a ==> D(b))`.
- `variant_field(e, E::V, f)`: `D(e) && is_V(e)`. Construction expression: D of all arguments. Field access: D of the base.
- Bodies of sum/count/max/min: D at every element of the interval.
- forall/exists reflect the actual short-circuit order: the condition under which the body is evaluated at k is, respectively, "the bodies of all earlier j are true" / "the bodies of all earlier j are false". Under that condition, `D(body(k))`.
  Do not unconditionally assume "the entire interval is defined" for a forall/exists in requires.

| Position | Handling |
|---|---|
| Function-entry requires | Assume `D(r) && r` in declaration order |
| Call requires | Prove `D(r)` first on the caller path (failure is `variant_domain`), then the existing `call_requires` |
| ensures | Prove the domain on the return path, then prove the existing ensures |
| assert | Assume after proving the domain and the condition |
| invariant | Prove the domain and the condition at entry and preservation; assume both after havoc |
| decreases | Prove the domain first on the path where the loop condition is true |

After assuming the result of the current expression, the domain of that expression is not proved (only earlier requires and the left side of a short circuit are used).
The general contract-domain problems of existing Option/Result selectors, array indices, division, and aggregates are not solved by G1 (a Stage 0 task).

## 4. Rust backend (codegen.py)

```rust
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Point { pub x: i64, pub y: i64 }

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Event { Empty, Hit(Point, bool), Failed(i64) }
```
- All are `Copy`. Types and fields are public. Enum variants use the positional-argument form. The ban on equality in code is the checker's responsibility.
- Remove the "Vec if the type is unknown" fallback of `rty()`. For a user type, the name; any other unsupported type is an internal error.
- Contract types such as `pruv_contract__Point`: same structure with i64 leaves → i128, Option/Result also with i128 payloads, user fields as the corresponding contract types,
  `Clone, Copy, PartialEq, Eq`. The conversion of an execution value to a contract value is recursive (for an enum, only the active variant). `Gen.c()` emits construction, field access, and equality in this representation.
- `Gen.e()`: struct and variant construction, field reads. `Gen.stmt()`: nested field assignment, match with multiple binders. `Gen.entry()`: reuse the existing sequential requires check.
- `show()`: render the new expressions to a common string (`is_variant(e, Event::Hit)`, `variant_field(e, Event::Hit, point)`, `p.x`, `Point { x: 1, y: 2 }`, `Event::Hit(p, true)`).
- Execution code for `variant_field`: store the base once in a temporary and extract it with a Rust match; the other arms call `pruv_ud("variant_field expected Event::Hit.point")`.
- A new `emit_public_types(prog) -> str` is placed in codegen.py and is also used by the LLVM bindings.
- Standard type paths are qualified as `::std::vec::Vec`, `::std::option::Option`, `::std::result::Result` (to prevent a clash with a user type `Vec`). Generated temporary names use `pruv_`·`__`.
- In proof mode, internal calls use the existing `f__pruv_body`, and safe mode uses the public entry. `--trust-callers` skips the requires execution check in both modes, while safe-mode arithmetic checks are kept.

## 5. LLVM backend (llvmgen.py)

### Internal layout (flattening: tag + space for the payloads of all variants)
```llvm
%pruv_t_Point = type { i64, i64 }
%pruv_t_Event = type { i64, %pruv_t_Point, i1, i64 }
```
| Index | Meaning |
|---|---|
| 0 | Tag: Empty=0, Hit=1, Failed=2 (declaration order, i64) |
| 1 | Hit.point |
| 2 | Hit.accepted |
| 3 | Failed.code |
- Struct fields are in declaration order. Enum payloads are concatenated in variant order and field order (storage index = 1 + sum of field counts of earlier variants + field_index).
- Inactive payloads always start from `zeroinitializer`. An empty struct is `{}`. A nested user type is a field with its LLVM aggregate type.
- The contract `%pruv_c_*` has the same structure with only integer leaves as i128. The existing Option/Result `{ i1, i64 }` and the contract i128 representation are kept.
- A nested value inside an inactive field is not regarded as a valid value (no reads, comparisons, or contract conversions).

### Calling convention
| Boundary | User structs and enums |
|---|---|
| Internal arguments of `__pruv_body` / `__pruv_entry` | One LLVM aggregate value |
| Internal return | Return the aggregate value |
| External `pruv_abi_*` arguments | A `ptr` pointing to a fixed-length array of i64 words |
| External return | `void`, with the word array written to the last `ptr out` |
| Rust public wrapper | Takes and returns the original user type by value |

Word count W(T): i64·bool 1, Option/Result 2, struct `max(1, Σ W(field))`, enum `1 + Σ W(all fields of all variants)`.
The one word of an empty struct is 0. bool 0/1, Option Some=1/None=0, Result Ok=1/Err=0. Inactive payloads and the None payload are serialized as 0.
The Rust bindings build `[i64; W(T)]` on the stack and serialize field by field, receive the return as an array too, and restore it with a safe constructor (no `transmute` and no dependence on Rust layout).
The top-level Option/Result argument and 2-word register-return ABI of M1 is not changed.

### IR generation
- Add `ty: Optional[Type]` to `V` and `Slot`, and a new kind `"agg"` (`V.a` aggregate SSA, `Slot.a` aggregate alloca, `b` unused).
- Extend: `lty()`, `vkind()`, `ir_params()`, `new_slot()`, `load()`, `store()`, `agg()`, `bind_params()`, `emit_ret()`, `ev_call()`,
  `ev()`, `cev()`, `bind_contract_params()`, `abi_of()`, `gen_bindings()`, `gen_llvm()`.
- Field assignment: evaluate RHS → load root → nested `insertvalue` → store root. Field read: `extractvalue`. Aggregate values are not in the owned-array list and are not subject to `pruv_free`.
- Enum match: a `switch` on the tag, with payload extraction only in that arm's block. If all arms end, the join block is omitted. default is `unreachable`.
- Contract equality: evaluate both sides once → for structs, recurse field by field → for enums, false if the tags differ, otherwise only the active fields → do not compare the payload of an Option None.
- `variant_field` accesses after a tag branch, and failure uses the existing `pruv_panic_undefined`. Do not merge with `select`.
- No change to `runtime.c`. The comparison target of the two backends is the `pruv:` diagnostic string.

## 6. Tests and examples

### Rejection tests (`tests/must_reject/g1_*.pruv` + a same-named `.json` with `{"stage": ..., "code": ...}`)
`run_must_reject()` also checks, when a `.json` exists, that the actual JSON diagnostic contains that stage and code (if absent, only exit code 1 as before).

| File | Wrong program | Expected stage/code |
|---|---|---|
| `g1_recursive_direct` | `struct Node { next: Node }` | type/`recursive_type` |
| `g1_recursive_indirect` | Cycle struct → enum payload → struct | type/`recursive_type` |
| `g1_array_field` | `struct Boxed { items: [i64] }` | type/`field_type` |
| `g1_unit_field` | `struct Boxed { item: () }` | type/`field_type` |
| `g1_array_of_struct` | `[Point]` local variable | parse/`unsupported_type` |
| `g1_generic_option` | `Option<Point>` | parse/`unsupported_type` |
| `g1_unknown_type` | Field of an undeclared type | type/`unknown_type` |
| `g1_duplicate_type` | A struct and an enum with the same name | type/`dup_type` |
| `g1_duplicate_field` | x twice in the same struct | type/`dup_field` |
| `g1_duplicate_variant` | Hit twice in the same enum | type/`dup_variant` |
| `g1_empty_enum` | `enum Empty {}` | type/`empty_enum` |
| `g1_literal_fields` | y missing in Point construction | type/`struct_fields` |
| `g1_unknown_field` | `p.z` | type/`unknown_field` |
| `g1_param_write` | Parameter `p.x = 1` | type/`immutable` |
| `g1_nested_immutable` | Immutable local `f.origin.x = 1` | type/`immutable` |
| `g1_match_missing` | Event::Failed arm missing | type/`match_arms` |
| `g1_match_duplicate` | Event::Empty arm duplicated | type/`match_arms` |
| `g1_match_arity` | `Event::Hit(p)` | type/`match_arity` |
| `g1_match_shadow` | A payload binder has the same name as a parameter | type/`shadow` |
| `g1_unused_wrapper` | Discard a call returning a struct with an Option field as a statement | type/`unused_value` |
| `g1_code_equal` | `p == q` in the body | type/`eq_type` |
| `g1_reserved_field` | Field name `pruv_x` | parse/`reserved_name` |
| `g1_false_ensures` | Returned field differs from the contract | verify/`ensures` |
| `g1_bad_variant_contract` | Unconditionally returns Empty with an ensures that looks up a Hit field | verify/`variant_domain` |
| `g1_call_requires` | Pass a struct with x=0 to a function requiring x>0 | verify/`call_requires` |
| `g1_loop_havoc` | Claims a sibling field of a changed struct is preserved without an invariant | verify/`assert` |
| `g1_shortcircuit_ensures` | Depends on the struct-returning ensures of a call that was not executed | verify/`assert` |

(The verify-stage code names follow the codes that the existing verify.py actually emits.)

```pruv
struct Point { x: i64, y: i64 }
fn wrong() -> Point
  ensures result.x == 1
{
  return Point { x: 2, y: 0 };
}
```
```pruv
enum Event { Empty, Hit(value: i64) }
fn wrong() -> Event
  ensures variant_field(result, Event::Hit, value) == 0
{
  return Event::Empty;
}
```
```pruv
struct Point { x: i64, y: i64 }
fn lost() -> () {
  let mut p: Point = Point { x: 0, y: 7 };
  let mut i: i64 = 0;
  while i < 1
    invariant 0 <= i && i <= 1
    decreases 1 - i
  {
    p.x = 1;
    i = i + 1;
  }
  assert p.y == 7;
}
```
(The version with `invariant p.y == 7` added must pass — confirm in examples/g1_counter.pruv.)

### Execution tests (`tests/runtime/g1_*`: `.pruv`·`.rs`·`.json`)
stdout is compared exactly with `stdout_lines`. A success test uses four combinations on both backends: default, safe, trust, and safe+trust (optional `flags_matrix`, keeping the existing `flags` format).

| stem | Content | Mode | stdout | exit / stderr |
|---|---|---|---|---|
| `g1_r01_copy` | Copy p=(1,2) to q, then q.x=9; print p.x, q.x | Four combinations | `1`,`9` | 0 |
| `g1_r02_nested` | Frame.origin.x 3→8; print the earlier copy and the new value | Four combinations | `3`,`8` | 0 |
| `g1_r03_variants` | Round trip of Empty, Hit(Point(3,4),true), Failed(7) through arguments, returns, and match | Four combinations | `0`,`3`,`7` | 0 |
| `g1_r04_wrapped` | Extract Some(5), None, Ok(6), Err(7) inside a struct with match | Four combinations | `5`,`0`,`6`,`7` | 0 |
| `g1_r05_requires` | `positive(p)` `requires p.x > 0`, driver passes x=0 | Default, safe | None | 101, `pruv: requires violated: positive: (p.x > 0)` |
| `g1_r06_undefined` | requires immediately looks up Hit.value, driver passes Empty | Default, safe | None | 101, `pruv: requires undefined: variant_field expected Event::Hit.value` |
| `g1_r07_guarded` | `!is_variant(e, Event::Hit) \|\| variant_field(e, Event::Hit, value) > 0`, pass Empty | Default, safe | `7` | 0 |
| `g1_r08_trust` | The r05 function returns 7 in its body, pass x=0 | trust, safe+trust | `7` | 0 |
| `g1_r09_overflow` | Assign `p.x + 1` to struct x, driver passes MAX | Safe, safe+trust | None | 101, `pruv: arithmetic error: overflow in +` |
| `g1_r10_order` | Constructor-argument functions print 1,2, the scrutinee function prints 3, print the Hit sum | Four combinations | `1`,`2`,`3`,`30` | 0 |
| `g1_r11_wide_abi` | Round trip of a struct wider than 2 words, with bool, Option, Result, and a nested enum, through arguments and returns (all variants) | Four combinations | `true`,`5`,`6`,`7` | 0 |
| `g1_r12_contract_int` | In requires, `Point { x: p.x + 1, y: 0 } == Point { x: p.x + 1, y: 0 }`, x=MAX | Default, safe | `true` | 0 |
| `g1_r13_empty` | Round trip of an empty struct and a fieldless variant through arguments and returns | Four combinations | `1` | 0 |
| `g1_r14_internal_entry` | An internal call passes a wrong Point to a requires function | Safe | None | 101, `pruv: requires violated` |
| `g1_r15_quant_domain` | forall/exists short-circuit at the first element and skip a later wrong variant lookup | Default, safe | `true`,`true` | 0 |

Messages and driver shape follow the existing tests/runtime tests and existing message formats (the strings above are the expected meaning).

### Examples
- `examples/g1_point.pruv`: nested struct update, input immutability, field ensures.
- `examples/g1_event.pruv`: variants with 0, 1, and several fields, a full match, contract variant checks.
- `examples/g1_counter.pruv`: a field invariant matched to the whole-struct havoc.

## 7. Finalized AST and file boundaries

The existing `Type` stays as is, and a user type is also `Type("Point")`. The same name means the same type. Add to and replace in `vast.py` (Python 3.9):

```python
@dataclass
class FieldDecl:
    line: int
    col: int
    name: str
    type: Type

@dataclass
class VariantDecl:
    line: int
    col: int
    name: str
    fields: List[FieldDecl]

@dataclass
class TypeDecl:
    line: int
    col: int
    name: str

@dataclass
class StructDecl(TypeDecl):
    fields: List[FieldDecl]

@dataclass
class EnumDecl(TypeDecl):
    variants: List[VariantDecl]

@dataclass
class FieldInit:
    line: int
    col: int
    name: str
    value: Expr

@dataclass
class StructLit(Expr):
    name: str
    fields: List[FieldInit]
    ty: Optional[Type] = None

@dataclass
class EnumCtor(Expr):
    enum_name: str
    variant: str
    args: List[Expr]
    ty: Optional[Type] = None

@dataclass
class FieldAccess(Expr):
    base: Expr
    field: str
    ty: Optional[Type] = None

@dataclass
class IsVariant(Expr):
    value: Expr
    enum_name: str
    variant: str
    ty: Optional[Type] = None

@dataclass
class VariantField(Expr):
    value: Expr
    enum_name: str
    variant: str
    field: str
    ty: Optional[Type] = None

@dataclass
class FieldAssign(Stmt):
    name: str
    fields: List[str]
    value: Expr

@dataclass
class MatchArm:
    line: int
    col: int
    enum_name: Optional[str]
    ctor: str
    binders: List[str]
    body: List[Stmt]

@dataclass
class Program:
    functions: List[Function] = field(default_factory=list)
    types: List[TypeDecl] = field(default_factory=list)
```
- `Program.functions` stays the first field. Remove `MatchArm.binder` and move all consumers to `binders` (no compatibility field).
- Option/Result arms have `enum_name=None`, and a user enum has a string. `ctor` is only the variant name (`"Hit"`). Some/Ok/Err have one binder, and None has an empty list.
- `FieldAssign.fields` is non-empty: `p.a.b` → `name="p"`, `fields=["a","b"]`.
- The existing `Ctor`, `Call`, `Match` are kept. New built-in constructs are not put into `Call.args` as fake `Var`s.
- `line`, `col` are the first token of the construct. (If there is a problem with the ordering of fields with defaults under dataclass inheritance, follow the existing vast.py convention.)

### Shared type information `pruvc/typeinfo.py` (owned by batch A)
```python
def type_name(ty: Type) -> str: ...

class TypeTable:
    def __init__(self, prog: Program): ...
    # decls: Dict[str, TypeDecl]
    # order: List[TypeDecl]  # dependency-first, stable
    def decl(self, ty: Type) -> TypeDecl: ...
    def is_struct(self, ty: Type) -> bool: ...
    def is_enum(self, ty: Type) -> bool: ...
    def fields(self, ty: Type, variant: Optional[str] = None) -> List[FieldDecl]: ...
    def field_index(self, ty: Type, name: str, variant: Optional[str] = None) -> int: ...
    def variant_index(self, ty: Type, variant: str) -> int: ...
```
`fields` returns the struct fields or the fields of the specified variant in declaration order. The Checker guarantees validity first, and B·C·D build the table from the Program after checking (no dynamic attributes on the AST).

### Batches (no two batches modify the same file)
| Batch | Exclusively modified files | Deliverable |
|---|---|---|
| A frontend | `pruvc/vast.py`, `pruvc/vparser.py`, `pruvc/check.py`, new `pruvc/typeinfo.py` | AST, syntax, type and effect checking |
| B proof | `pruvc/verify.py` | Datatypes, domains, rebuilding, havoc, calls and match |
| C Rust | `pruvc/codegen.py` | Public type output, contract types, Rust code, common `show` |
| D LLVM | `pruvc/llvmgen.py` | Aggregate-value IR, ABI serialization, bindings |
| E tests | `tests/run_all.py`, new `tests/must_reject/g1_*`, new `tests/runtime/g1_*`, new `examples/g1_*` | Regression suite, examples |
`runtime.c`, `pruvc.py`, `docs/M1_LLVM_SPEC.md` are not modified. The main session adds the SPEC.md G1 section.
Order: A·E in parallel → B·C in parallel → D (uses C's `emit_public_types`) → the main session runs and integrates → audit and confirmation → independent-solve measurement.

## 8. SPEC.md G1 section draft (English) — the main session puts it into SPEC.md

(The original design document text. The main session polishes it to match the implementation results and puts it in.)

## 9. Audit points
| Risk | Required check |
|---|---|
| parser `{` ambiguity | `if flag {}`, `match value {}`, struct literals and parentheses |
| Nominal types | Cannot assign or compare different types with the same structure |
| Missed recursion | Rejected even if only one enum variant cycles |
| Value copy | A nested field change in q does not change p |
| z3 accessor total-function property | A wrong variant lookup is not proved as an arbitrary value |
| Domain self-justification | Lookups are not justified by first assuming the requires·ensures result |
| Short circuit · quantifiers | Lookup and call conditions are not assumed after an unexecuted branch or an early exit |
| i64 range | Range condition on every active nested leaf of arguments, call results, and havoc |
| Contract value range | No contradiction proved by attaching i64 conditions to contract-constructed values |
| Loops | Field assignments in nested if, match, and while are included in the root havoc set |
| match scope | Binders do not leak outside the arm |
| enum equality | Inactive payloads and padding are not compared |
| LLVM initialization | undef/poison is not observed in returns and serialization |
| ABI | Large types, empty types, nested types |
| Call path | Correct entry/body under proof/safe mode and trust combinations |
| Messages | Both backends have the same `show()` and the same undefined detail |
| Name collisions | A user type `Vec` etc. versus standard types and generated helpers |
| Existing regression | Option/Result ABI, array free, arithmetic checks, short-circuit evaluation |

A flattened enum grows in size when it has many variants (before measurement). A union layout and small-type register returns are decided after measurement.
