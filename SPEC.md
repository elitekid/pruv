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

## 8. Errors
Compiler prints JSON lines: `{"stage": "parse|type|effect|verify|rustc", "line": n, "col": n,
"code": "...", "message": "...", "fix": "...", "counterexample": {...}}`. Exit code 1 on any error.

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
