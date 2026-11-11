# Pruv language spec v0.1

Pruv is a tiny language designed to be written by AI. Humans read only the contracts
(`requires` / `ensures`). The compiler proves every function correct against its contracts
with an SMT solver (z3), proves every array access in bounds and every arithmetic
operation free of i64 overflow, then emits Rust with all those runtime checks removed.
If anything cannot be proven, compilation fails with a JSON error containing a counterexample.

Design rules: one way to do each thing; everything a function does is visible in its
signature; no null, no exceptions, no implicit conversions, no globals, no overloading.

## 1. Lexical
- Comments: `// ...` to end of line.
- Identifiers: `[a-zA-Z_][a-zA-Z0-9_]*`. Integer literals: decimal digits, optional `_` separators (`1_000_000`).
- Keywords: `fn let mut if else while return match true false invariant decreases requires ensures assert forall exists in result Some None Ok Err struct enum is_variant variant_field`.
- Names starting with `pruv_` or containing `__`, the name `_`, and Rust keywords (`type`, `loop`, `self`, `for`, ...) are reserved; the parser rejects them (`reserved_name`).

## 2. Types
| Pruv | meaning | Rust |
|---|---|---|
| `i64` | 64-bit signed int | `i64` |
| `bool` | boolean | `bool` |
| `()` | unit | `()` |
| `[i64]` | array of i64 | param: `&[i64]`, local/return: `Vec<i64>` |
| `[u8]`, `[bool]` | array of bytes 0..=255 / of bools (section 6b) | `&[u8]`/`Vec<u8>`, `&[bool]`/`Vec<bool>` |
| `str` | read-only UTF-8 text, indexed by byte (section 6b) | param: `&str`, local/return: `String` |
| `Option<i64>` | `Some(v)` or `None` | `Option<i64>` |
| `Result<i64>` | `Ok(v)` or `Err(code)`, code is i64 | `Result<i64, i64>` |
| `Point`, `Event` | user struct / enum (section 6a) | `pub struct` / `pub enum` (Copy) |

Parameters are immutable. Array parameters are read-only views. Only `let mut` locals can be reassigned
or have elements assigned.

## 3. Functions
```
fn name(p1: T1, p2: T2) -> R ! effect1, effect2
  requires <bool expr>
  ensures <bool expr>      // may use `result`
{
  ...
}
```
- Effects: `io` (may call `print`), `alloc` (may call `alloc`/`copy` or a function with `alloc`).
  A function must list every effect it uses, directly or through calls. No `!` part means pure.
- Any number of `requires` and `ensures` lines, combined with `&&`.
- Every path must end with `return e;` (for `()` functions `return;` may be omitted at the end).
- Program entry, if present, is `fn main() -> () ! io ...`.
- Calls are checked modularly: the caller must prove the callee's `requires`, and then may assume its `ensures`.
- No recursion (v0.1).

## 4. Statements
```
let x: T = e;            // type annotation required
let mut x: T = e;
x = e;                   // only mut locals
a[i] = e;                // only mut local arrays
if c { ... } else { ... }        // else optional; `else if` allowed
while c
  invariant <bool expr>          // zero or more
  decreases <i64 expr>           // exactly one, required
{ ... }
return e;  /  return;
assert <bool expr>;              // proven at compile time, erased
print(e);                        // e: i64 or bool; needs `io`
match e {                        // e: Option<i64>, Result<i64> or a user enum (6a); all arms required
  Some(v) => { ... }
  None => { ... }
}
match r { Ok(v) => { ... } Err(c) => { ... } }
f(args);                 // call as statement only if f returns ()
```
`while` is the only loop. A value of type `Result<i64>` or `Option<i64>` must be used (let-bound, returned, matched);
it can never be silently dropped.

## 5. Expressions
- Literals `123`, `true`, `false`; variables; `f(a, b)`; `a[i]`; `len(a)` (i64).
- Arithmetic `+ - * / %` on i64. `/` and `%` require proving divisor `> 0` and dividend `>= 0`.
- Comparison `== != < <= > >=` (i64, and `== !=` on bool). In contracts `== !=` also work on Option/Result.
  Arrays can never be compared with `==`; compare `len` and elements with `forall`.
- Logic `&& || !` (short-circuit). Unary `-`.
- Constructors `Some(e)`, `None`, `Ok(e)`, `Err(e)`.
- `alloc(n, v)`: new array of length n (0 <= n <= 2^40 must be proven) filled with v. Needs `alloc`.
  To grow an array, bound the input: `requires len(a) <= 1_000_000` before `alloc(len(a) + 1, 0)`.
- `copy(a)`: new array equal to a. Needs `alloc`.
- Evaluation order: code evaluates left to right in source order, the same in every compile mode; call arguments left to right, and in `a[i] = v` the index is evaluated before the value.
- Precedence (high to low): unary `- !`; `* / %`; `+ -`; comparisons (non-associative); `&&`; `||`; `==>`.

## 6. Contract-only expressions
Allowed only in `requires`, `ensures`, `invariant`, `assert`:
- `result` (in ensures): the return value.
- `forall i in lo..hi: e` / `exists i in lo..hi: e` (i ranges over lo <= i < hi).
- `a ==> b` (implication).
- `is_some(o)`, `some_val(o)`, `is_ok(r)`, `ok_val(r)`, `err_val(r)`.
- In contracts arithmetic is mathematical (unbounded); overflow is only checked in code. Contract `/` `%` are
  Euclidean (`-7 / 2 == -4`, `-7 % 2 == 1`, the remainder is never negative) and need only a divisor `!= 0`.
- Contract domain: every partial operation in a contract must be defined where it is evaluated, and the verifier
  proves it (`verify` error `contract_domain`): `a[i]` needs `0 <= i < len(a)`, `x / y` and `x % y` need `y != 0`,
  `some_val(o)` needs `is_some(o)`, `ok_val(r)` needs `is_ok(r)`, `err_val(r)` needs `!is_ok(r)`, `max`/`min` need
  `lo < hi`. Evaluation is left to right with short-circuit `&&` `||` `==>`; `forall`/`exists` go up from `lo` and stop
  at the first false/true k, so only the k they reach need a defined body; aggregates need it for every k in range.
  This holds in `requires` (each clause from the earlier ones only: write `requires 0 <= i && i < len(a)` before
  `requires a[i] > 0`), `ensures`, `invariant` (earlier clauses of the same kind may guard later ones), `assert` and
  `decreases`.
- Aggregates (k ranges over lo <= k < hi, like `forall`):
  - `sum(k in lo..hi: e)` — sum of i64 `e`; 0 if the range is empty.
  - `count(k in lo..hi: c)` — number of k where bool `c` holds; 0 if empty.
  - `max(k in lo..hi: e)`, `min(k in lo..hi: e)` — largest / smallest `e`; undefined if empty (`contract_domain`),
    so guard with `len(a) >= 1` or `lo < hi`.
  - There is one form only: write `sum(k in 0..len(a): a[k])`, not `sum(a)`. Ranges are half-open so loop
    invariants can name the part done so far: `invariant s == sum(k in 0..i: a[k])`.
  - The verifier knows one step of each aggregate (e.g. `sum(lo..hi) == sum(lo..hi-1) + e[hi-1]`, and from the
    front `sum(lo..hi) == e[lo] + sum(lo+1..hi)`) at every place the aggregate appears. Loops that grow `i` by one
    and keep `acc == agg(k in 0..i: ...)` therefore verify without extra lemmas. Facts that need induction
    (e.g. `sum` splitting at an arbitrary point, `max` of `e + c`) are not known automatically.
  - Example: `ensures result == count(k in 0..len(a): a[k] < x)` with
    `invariant c == count(k in 0..i: a[k] < x)`.

## 6a. Structs and enums
```
struct Point { x: i64, y: i64 }
enum Event { Empty, Hit(point: Point, accepted: bool), Failed(code: i64) }

let p: Point = Point { x: 3, y: 4 };      // every field, in declaration order
let e: Event = Event::Hit(p, true);       // arguments in field order; `Event::Empty` has no parentheses
let mut q: Point = p;                      // values are copied, never shared
q.x = 8;                                   // field assignment: `let mut` locals only, nested `f.origin.x = e` ok
match e {                                  // statement; every variant exactly once
  Event::Empty => { ... }
  Event::Hit(pt, ok) => { ... }            // one name per field, in order; names are immutable, arm-local
  Event::Failed(code) => { ... }
}
```
- Declared at top level, in any order. Type and variant names start upper-case, field names lower-case.
- Fields: `i64`, `bool`, `Option<i64>`, `Result<i64>`, or another struct/enum. No array or `()` fields, no recursive
  types, no `[Point]`, no `Option<Point>`. Empty structs are allowed; an enum needs at least one variant.
- Read struct fields with `v.field`. Enum payloads are read only with `match` in code.
- `==` / `!=` on structs and enums: contracts only, same type. Enums compare the variant and its fields.
- Contract-only: `is_variant(e, Event::Hit)` (bool) and `variant_field(e, Event::Hit, point)` (that field).
  `variant_field` is defined only when `e` is that variant; the verifier proves this wherever the contract is
  evaluated, following short-circuit order (`verify` error `variant_domain`; other partial operations give `contract_domain`, section 6). Guard it:
  `requires !is_variant(e, Event::Hit) || variant_field(e, Event::Hit, point).x > 0`.
- A loop that assigns any field of `p` forgets all of `p`; keep the other fields with invariants (`invariant p.y == 7`).
- Contract arithmetic inside struct literals is mathematical, like all contract arithmetic.

## 6b. Byte arrays, bool arrays and strings (G2)
Full contract: `docs/G2_SPEC.md`. There are no scalar `u8` types, no casts and no narrow arithmetic: reading `[u8]` or
`str` gives an `i64`, reading `[bool]` gives a `bool`, and all arithmetic stays i64.

**Arrays `[u8]` and `[bool]`.** Same positions and rules as `[i64]` (parameters read-only, `let mut` locals mutable,
return a parameter with `copy`). Refinements: `[u8 | L..=U; <=N]` with `0 <= L <= U <= 255`; `[bool; <=N]` (length only).
- Storing into `[u8]` (`b[i] = v`, and the fill value of `alloc(n, v)`, even when `n == 0`) must prove
  `0 <= v <= 255` (`verify` error `elem_range`; the check order of a store is index, then value range, then refinement).
  `b[i] + 1` is fine as an i64; storing a 256 is not.
- `alloc(n, v)` gets the narrow type **only** when it is directly the right side of a typed `let`
  (`let mut b: [u8] = alloc(n, 0);`), of a reassignment of such a variable, or directly after `return` in a function
  returning `[u8]`/`[bool]`. Anywhere else (a call argument, inside `copy(...)` or `len(...)`) it is `[i64]`; bind it to a
  typed local first. `copy(a)` keeps the type of `a`.
- `[bool]` stores and the fill value of `alloc` for `[bool]` must be `bool` (no 0/1 integers).
- Array types must match exactly: no passing `[u8]` where `[i64]` is expected, no `[u8]`↔`str` conversion.
- Elements of `[u8]` parameters, call results and loop-changed arrays are known to be in `0..=255`. Count true elements
  with `count(k in 0..len(b): b[k])`; `sum` needs an i64 body (`sum(k in ..: b[k])` on `[bool]` is a type error).

**Strings `str`.** A `str` is always valid UTF-8 and its bytes never change (`let mut s: str` may only be reassigned).
- Literals `"..."` hold any Unicode text; escapes are only `\" \\ \n \r \t \0` (a real newline or other control
  character inside is an error). In code a literal creates a new string and needs `alloc`; in contracts it is free.
- `len(s)` is the number of **bytes**; `s[i]` is byte `i` as an i64 in `0..=255` (index must be proven in range).
- `copy(s)` (needs `alloc`) returns an independent copy. A `str` follows the array ownership rules: a `let` or
  assignment from another `str` variable, and returning a parameter, need `copy(s)`.
- `is_char_boundary(s, i)` (code and contracts) is exactly: `i == 0 || i == len(s) || (0 < i && i < len(s) && (s[i] < 128
  || s[i] >= 192))`; it is false outside `0..=len(s)` and never needs a domain proof for `i`.
- `substr(s, lo, hi)` (needs `alloc`, code only) copies bytes `lo..hi`. The verifier proves `0 <= lo <= hi <= len(s)`
  (`string_slice_range`) and then `is_char_boundary(s, lo) && is_char_boundary(s, hi)` (`utf8_boundary`; also when
  `lo == hi`). It knows `len(result) == hi - lo` and `result[k] == s[lo + k]`.
- Not available: `==`/`!=` on whole strings (compare `len` and bytes with `forall`), `print` of a string, `str` in
  `Option`/`Result`/struct fields, char/code-point indexing. Character counts are written with boundaries, e.g.
  `count(t in 0..len(s): is_char_boundary(s, t))` counts the characters of `s`.
- The verifier models a `str` as bytes `0..=255`; it does **not** know UTF-8 rules (e.g. that byte 0 is not a
  continuation byte unless you check it), and a counterexample string may be invalid UTF-8.

**Run time.** Proof mode removes the element-range and substring checks. `--no-verify` (safe mode) checks them and panics with exit 101:
`pruv: element out of range: v (u8 0..=255)`, `pruv: string slice out of bounds: lo..hi (len n)`,
`pruv: UTF-8 boundary error: lo..hi (len n)` (range is checked before boundaries). Raw `--rust-bindings` entries check
`str` UTF-8 and `[bool]` 0/1 bytes before the body (`pruv: invalid representation`) in both modes, also with
`--trust-callers`. Raw `[i64]`/`[u8]`/`[bool]` entries do not check for a negative length or a null pointer (the caller's
duty); raw `str` entries do.

## 6c. Generics (G3)
Full contract: `docs/G3_SPEC.md`. Examples: `examples/g3_*.pruv`.
```
struct Pair<A, B> { first: A, second: B }
enum Choice<A, B> { Left(value: A), Right(value: B) }

fn swap<A, B>(p: Pair<A, B>) -> Pair<B, A>
  ensures result.first == p.second
{ return Pair::<B, A> { first: p.second, second: p.first }; }

fn first<T: Element>(a: [T]) -> T
  requires len(a) > 0
  ensures result == a[0]
{ return a[0]; }

let q: Pair<bool, i64> = swap::<i64, bool>(p);
let c: Choice<bool, i64> = Choice::<bool, i64>::Left(true);
let o: Option<bool> = Some::<bool>(true);   // also None::<bool>, Ok::<bool>(x), Err::<bool>(code)
```
- **Type parameters** go on `fn`, `struct` and `enum`: `fn f<T, U: Element>(...)`. The only bound is `Element`; it is
  required wherever `[T]` is written. `Element` means `i64` or `bool`.
- **Type arguments** may be `i64`, `bool`, `Option<V>`, `Result<V>`, and structs/enums of values (also generic
  applications such as `Pair<i64, bool>`). Not allowed: arrays, `str`, `()`, `u8`. A `T: Element` argument must be `i64` or `bool`.
- **Explicit type arguments** are written at every generic call and constructor: `f::<T>(x)`, `Pair::<A, B> { .. }`,
  `Choice::<A, B>::Left(x)`, `Some::<T>(x)`, `None::<T>`, `Ok::<T>(x)`, `Err::<T>(code)`. There is no inference of
  type arguments. Unqualified `Some`, `None`, `Ok`, `Err` keep their old meaning (`Option<i64>`, `Result<i64>`).
- **On an abstract `T` you can** copy it, pass it, store it (locals, fields, payloads, `[T]` elements) and compare it
  with `==`/`!=` **in contracts only**. You cannot do arithmetic, ordering, run-time equality, field access, `match` or `print`
  on a `T`. (`match` on an `Option<T>` or `Choice<A, B>` is fine; the payload variable is a `T`.)
- `Result<T>` keeps an `i64` error code: `Err::<T>(code)`.
- `alloc`, `copy`, indexing and stores work on `[T]` (`T: Element`) as on `[i64]`; the verifier knows that
  `copy(a)` has `len(a)` elements equal to `a`'s. Explicitly typed constructors may appear anywhere an expression may
  (`o = Some::<T>(v);`).
- **Contracts** may use abstract equality, guarded payload access (`is_some(o) ==> result == some_val(o)`) and
  `count` over abstract equality. `sum`/`max`/`min` need an `i64` body.
- **No recursion**, direct or mutual, in generic code (a generic function's call graph is acyclic).
- **Proof:** a generic definition is proved once, for an abstract `T`. A counterexample prints abstract values as `opaque#N`.
- **Code generation** specializes per concrete instance (`first::<i64>`, `first::<bool>` are separate functions).
  Generic functions are **not exported** (no `--rust-bindings` entry, no raw ABI symbol): expose instances through
  non-generic wrappers (`fn head_int(a: [i64]) -> i64 { return first::<i64>(a); }`, `examples/g3_wrapper_instances.pruv`).
- **Specialization limits:** at most 4096 function instances, 4096 type applications, type nesting depth 128 and 65536
  type nodes; beyond that `codegen/specialization_limit` (no partial output).
- **New error codes:** `generic_syntax` (malformed `<..>`/`::<..>`), `type_parameter` (unknown, duplicate or misused
  parameter), `type_arity` (wrong number of type arguments), `type_argument` (inadmissible type argument),
  `generic_operation` (operation not allowed on an abstract `T`), `generic_bound` (`[T]` without `T: Element`, or a
  non-`Element` argument for an `Element` parameter), `generic_main` (`main` may not be generic), and
  `specialization_limit` (above).

## 7. What the compiler proves (all must succeed)
1. Every `a[i]` (read or write): `0 <= i < len(a)`.
2. Every `+ - * unary-` in code: result within i64 range.
3. `/ %`: divisor > 0, dividend >= 0. `alloc(n, v)`: 0 <= n <= 2^40.
4. Callee `requires` at each call; `ensures` at each return; `assert`s.
5. Loop invariants hold on entry and are preserved; `decreases` is >= 0 at each iteration start and strictly decreases.
6. Array parameters have `0 <= len(a) <= 2^40` and elements in i64 range (assumed; guaranteed for Pruv callers because every alloc is proven <= 2^40).
Variables not assigned in a loop keep their values across it; assigned ones are only known through invariants.

### Run-time `requires` and modes
A public function's `requires` are checked at run time, left to right with short-circuit evaluation; a violation
panics with `pruv: requires violated`. If evaluation reaches something outside the contract domain (index out of
range, division by zero, `max`/`min` over an empty range, `some_val(None)`, `variant_field` of another variant, ...), it panics with
`pruv: requires undefined`. So write domain conditions first, e.g. `0 <= i && i < len(a) && a[i] > 0`.
A verified program never reaches these (the verifier proves the contract domain), except two run-time resource limits
that also panic with `pruv: requires undefined`: contract arithmetic is evaluated in i128 (an intermediate value or
running sum beyond i128 stops the check), and one public call's `requires` checks share a budget of 2^30 quantifier and
aggregate iterations (`pruv: requires undefined: contract iteration budget exceeded`). Skipped short-circuit operands
and empty ranges cost nothing. These limits never make a false `requires` pass.
Number-range quantifiers and aggregates iterate once per element of the range, so their cost is the range length,
with one exception: the sortedness precondition `forall i in 0..len(a): forall j in i..len(a): a[i] <= a[j]` (or with
inner start `i + 1`; any bound names, same array `a`, exactly this shape) is checked as the equivalent
`forall k in 1..len(a): a[k-1] <= a[k]`, in O(len(a)). The verifier still uses the written form.

`--no-verify` emits safe mode: no proof exists, so indexing and arithmetic are checked (panic on out-of-range index
or i64 overflow), and `/` `%` use the verifier's domain (divisor > 0 and dividend >= 0, otherwise panic).
`--trust-callers` makes the public entry skip the `requires` checks (for benchmarking; callers must be trusted).

## 7a. Refinement types (STAGE 1, bundle A)
A refinement is an annotation on a type that the compiler expands into the contracts of section 6; it adds no new
type. `Type` and ABI stay `i64` / `[i64]`, and a program without annotations is compiled byte for byte as before.
```
x: i64 | 0..=100                                   scalar value range
a: [i64 | -1_000_000_000..=1_000_000_000; <=1_000_000]   element range and length bound
a: [i64 | -10..=10]      a: [i64; <=100]           either part alone
```
**Closed value range vs half-open loop range.** In an annotation `L..=U` includes both ends. The `lo..hi` of
`forall/exists/sum/count/max/min` still excludes `hi`. `; <=N` means `len(a) <= N`. Writing `L..U` in an annotation is
`parse/refinement_syntax`.

**Where.** Only the type of a parameter, a return type, and the type of `let` / `let mut`. Struct fields, enum payloads,
`Option<..>` / `Result<..>` contents and any other place give `parse/refinement_position`. A lone `|` anywhere else is the
old `parse/bad_char`.

**Bounds** are signed decimal integer literals (`_` allowed, sign applied first; `-9223372036854775808` is fine). Exponent
notation (`1e9`), other spellings (`0x10`), expressions (a binary operator `* + - / %` after a bound, e.g. `0..=2*3`)
and variables are `parse/refinement_syntax`; so is an array length written without `<=` (`[i64; 3]`, fix: `<=N`). After parsing:
`L > U`, a bound outside i64, or `N` outside `0..=2^40` is `type/refinement_bounds`; `|` on `bool` or a user type is
`type/refinement_base` (reported after the whole file parsed). These checks run before the type checker.

**Expansion** (done by `pruvc/refine.py` at the start of the checker; the synthesized nodes sit at the line/col of the
annotation and are type-checked like user code):
| written | becomes |
|---|---|
| parameter `p: i64\|L..=U` | `requires L <= p && p <= U`, before the user's `requires`, in parameter order |
| parameter `a: [i64\|L..=U; <=N]` | `requires len(a) <= N`, then `requires forall K in 0..len(a): L <= a[K] && a[K] <= U` |
| return `-> T\|R` | the same conditions on `result` as `ensures`, before the user's `ensures` |
| `let x: T\|R = e;` | an `assert` of the condition right after the binding (`verify/refinement_init`) |
| `x = e;` on a refined local | an `assert` right after (`verify/refinement_assign`) |
| `x[i] = e;` on an element-refined array | no assert: the store node carries `elem_refine = [L, U, origin]`, and the verifier proves `L <= v && v <= U` for the already evaluated stored value `v` right after the `index_oob` obligation (`verify/refinement_assign`; one query, no re-evaluation of `i`, no `forall`) |
| a `while` that assigns a refined local alive at the loop head | that local's conditions are put first in the loop's `invariant` list |
`K` is the first of `k`, `k_1`, `k_2`, ... that occurs nowhere in the function, so a user variable named `k` is never
captured. Obligations are also checked on the path where the function returns right after the statement.

**Current behaviour worth knowing.**
* The line/col of an error from a synthesized `requires` / `ensures` / `invariant` / `assert` is the annotation's position
  (the comment position), not the statement that broke it; the one exception is an element store, whose
  `refinement_assign` error sits at the store statement. A store into a refined array checks only the stored value: the
  rest of the array is covered by the elements' own earlier obligations, so an out-of-range index gives just `index_oob`
  and no follow-up error.
* Synthesized `requires` / `ensures` / `invariant` conditions do not yet carry a source phrase in their messages (they read
  like ordinary contract failures); only the synthesized `assert`s and element stores name their origin. A phrase for them
  is planned for stage 1 B.
* The proven store-value fact is not added to the path afterwards (it is already implied by the path).
* Expansion runs once per parsed program (a done-marker on the program); calling the checker twice does not expand twice.
  The marker and `elem_refine` are not part of the source language; `elem_refine` appears in the checked-AST dump only on
  a store into an element-refined array.

**Meaning and run-time policy.** A refinement is a proof obligation, not an enforced type. Proof mode checks every
obligation statically (callers prove parameter refinements as `call_requires`; a return refinement fails as
`ensures`; invariants as `invariant_entry` / `invariant_preserved`). An unrefined `i64` can be passed where a refinement
is expected when the path facts (an `if`, a `requires`) prove it. The parameter conditions are ordinary `requires`: they
are checked at a public entry before the user's `requires`, share its 2^30 iteration budget (length bound first, so a too
long array fails before any element is visited; each visited element costs 1), and are skipped by `--trust-callers`.
Return and local refinements, like `assert`, `ensures` and `invariant`, are erased from the generated code; `--no-verify`
therefore does not check them (it still keeps the entry `requires` checks and the safe indexing/arithmetic).
Do not read an annotation as a run-time guarantee of local variables or results under `--no-verify`.

## 8. Errors
Compiler prints JSON lines: `{"stage": "parse|type|effect|verify|rustc", "line": n, "col": n,
"code": "...", "message": "...", "fix": "...", "counterexample": {...}}`. Exit code 1 on any error.

G3 added the error codes `generic_syntax`, `type_parameter`, `type_arity`, `type_argument`, `generic_operation`,
`generic_bound`, `generic_main` and `specialization_limit` (section 6c).

`verify_unknown` is not a counterexample: the solver gave up on that one obligation (the message usually ends in
`(timeout)`). Each attempt gets 8 seconds of wall time (a second attempt with aggregate lemmas when aggregates are
used), so a loaded machine can also cause it. The program may be correct; make the proof easier. What helps, in order:
- Keep each loop invariant to one simple fact, and state a fact about one position without a quantifier when you can:
  "`last` is the last negative index before `i`" is `-1 <= last && last < i`, `last == -1 || a[last] < 0` and
  `forall k in last + 1..i: a[k] >= 0`, not `forall s in 0..i: (exists k in s..i: a[k] < 0) ==> s <= last`.
- A quantifier on the left of `==>` (or under `!`) inside another quantifier is the most expensive shape; write such a
  fact once (in `ensures` and the one invariant that carries it) and support it with the simple facts above.
- Add the small facts the step needs as extra invariants (simple bounds between your variables), rather than `assert`s.
- Which shapes time out can differ slightly between the Python and Rust compilers; a proof meant to be kept should
  pass both.

## 9. Example
```
fn sum(a: [i64]) -> i64
  requires len(a) <= 1_000_000
  requires forall k in 0..len(a): a[k] >= -1_000_000_000 && a[k] <= 1_000_000_000
{
  let mut s: i64 = 0;
  let mut i: i64 = 0;
  while i < len(a)
    invariant 0 <= i && i <= len(a)
    invariant s >= -1_000_000_000 * i && s <= 1_000_000_000 * i
    decreases len(a) - i
  {
    s = s + a[i];
    i = i + 1;
  }
  return s;
}
```
