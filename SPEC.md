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
| `inout a: [i64]` (also `[u8]`, `[bool]`, `[T]`) | parameter mode, not a type (section 6g) | `&mut [i64]` (`&mut [u8]`, `&mut [bool]`) |
| `str` | read-only UTF-8 text, indexed by byte (section 6b) | param: `&str`, local/return: `String` |
| `Option<i64>` | `Some(v)` or `None` | `Option<i64>` |
| `Result<i64>` | `Ok(v)` or `Err(code)`, code is i64 | `Result<i64, i64>` |
| `Point`, `Event` | user struct / enum (section 6a) | `pub struct` / `pub enum` (Copy) |

Parameters cannot be reassigned. Array parameters are read-only views, except an `inout` array parameter (section 6g),
which is an exclusive mutable view: its elements can be assigned, but the parameter itself never can. Otherwise only
`let mut` locals can be reassigned or have elements assigned.

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
- A parameter may be written `inout name: [T]` for an array the function updates in place; the call must repeat
  the mark (`f(inout a)`). See section 6g.
- Calls are checked modularly: the caller must prove the callee's `requires`, and then may assume its `ensures`.
- Recursion (direct or mutual) is allowed when every function in the cycle has a `decreases` clause (section 6e).

## 4. Statements
```
let x: T = e;            // type annotation required
let mut x: T = e;
x = e;                   // only mut locals
a[i] = e;                // only mut local arrays and inout array parameters
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
f(inout a, args);        // mutating call: only in the statement positions of section 6g
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
- `old(a)` (in ensures, invariant, assert): the entry contents of an `inout` parameter `a` of the enclosing function (section 6g).
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
- Fields: `i64`, `bool`, `Option<i64>`, `Result<i64>`, or another struct/enum. No `()` fields, no `[Point]`, no
  `Option<Point>`. Non-generic structs/enums may also have `[i64]`/`[u8]`/`[bool]`/`str` fields and be recursive (section 6e). Empty structs are allowed; an enum needs at least one variant.
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
- Generic recursion only with a stable type-parameter vector: inside a recursive cycle every function has the same
  type parameters (same order and bounds) and every call in the cycle forwards them unchanged (section 6e).
  Recursive or buffer-field types cannot be type arguments.
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

## 6d. Calling Rust and standard collections (G6)
Full contract: `docs/G6_SPEC.md` (§10–§13 are the implemented decisions). Examples: `examples/g6_*.pruv`.
```
trusted rust fn rust_min(a: i64, b: i64) -> i64
  ensures result <= a && result <= b
  ensures result == a || result == b
  = "::std::cmp::min";

fn push_two(take v: Vec<i64>, x: i64) -> Vec<i64> ! alloc
  requires len(v) < 1000
  ensures len(result) == len(v) + 2 && result[len(v)] == x
{
  let mut w: Vec<i64> = vec_push::<i64>(move v, x);
  w = vec_push::<i64>(move w, x);
  return move w;
}
```
- **Trust.** A `trusted rust fn` has no body; it names a Rust function by absolute path (`::std::...` or a crate given
  with `--rust-extern NAME=PATH`). The prover checks that callers satisfy its `requires` and then **assumes** its
  `ensures`; the Rust code itself is not proved. A wrong contract can make wrong code "verify", so the Rust backend lists the contracts in
  `<out>.foreign.json` (the LLVM backend does not write this file yet). Signatures use `i64`, `bool`, `Option`/`Result` of those, read-only `[i64]`/`[u8]`/`[bool]`/`str`
  parameters, and `i64`/`bool`/`()`/`Option`/`Result` results; at least one `ensures` (`ensures true` is allowed).
- **Collections.** `Vec<T>`, `HashMap<K, V>` (`K` is `i64` or `bool`) and `String` hold values (no nested collections,
  no collections inside structs/Options/arrays). Operations (`vec_*` and `map_*` take explicit type arguments, `string_*` and `len` take none): `vec_new`, `vec_push`,
  `vec_get`, `map_new`, `map_insert`, `map_get` (returns `Option<V>`), `string_new`, `string_push_str`, `string_byte`,
  `string_to_str` (copies into a `str`), and `len`. Allocating operations need `! alloc`. In contracts only: `v[i]`, `s[i]`,
  `map_lookup::<K, V>(m, k)` and `map_updated::<K, V>(after, before, k, v)` (the whole new map: k set, size, others kept).
  A map whose values grow in a loop (counters, histograms) needs either a saturating update (`if c < LIMIT { c + 1 }`)
  (preferred) or an invariant bounding every value (quantifying over all keys is expensive and may time out); an
  invariant about only the queried key cannot bound the others, so `count + 1` is then not provably free of overflow.
- **Ownership.** A collection has one owner. An unmarked collection parameter is borrowed for the call (read only, cannot
  be moved, returned or aliased). `take` parameters and locals own their collection. Pass ownership with `move x`
  (into a `take` argument, a `let`, an assignment or a `return`); after that `x` is dead until reassigned. A binding
  moved on only some paths cannot be used after the join; a loop must leave every outer owner alive at the end of each
  iteration. Collections are freed automatically. `ensures` may mention a consumed parameter: it means the value at entry.
- **Run-time boundary checks** (`--foreign-checks`): `requires` (default) checks foreign and catalog preconditions at
  run time; `all` also checks their postconditions (snapshots; slower, repeated appends become quadratic; on the LLVM backend
  the bytes copied by `string_to_str` are not re-compared); `off` skips
  both (only with verification). Failures exit 101 with `pruv: foreign requires violated:`, `pruv: foreign ensures
  violated:`, `pruv: foreign contract undefined:` or `pruv: foreign panic:`.
- **Build.** The Rust backend supports all of the above. The LLVM backend supports collections of `i64`/`bool` and trusted
  functions over `i64`/`bool`/arrays/`str` returning `i64`/`bool`/`()`, built by compiling the generated bindings
  (which then contain the Rust shim) with rustc together with the object; the Rust compiler's `--emit exe|obj` rejects such
  programs with `codegen/foreign_target`, and a `--no-verify` LLVM build cannot check a `requires` that uses `v[i]`, `s[i]`,
  `map_lookup` or `map_updated` (`codegen/unsupported_type`). Collection-bearing functions are internal: expose them through functions with
  ordinary parameter and result types.
- **New error codes:** `foreign_syntax`, `foreign_path`, `foreign_signature`, `foreign_owned_type`, `foreign_move`,
  `foreign_borrow`, `foreign_loop_move`, `foreign_contract`, `foreign_export`, `foreign_target`.

## 6e. Recursion, recursive types and buffer fields (G9)
Full contract: `docs/G9_SPEC.md` (§10–§14 are the implemented decisions). Examples: `examples/g9_*.pruv`.
```
enum Tree { Empty, Node(value: i64, left: Tree, right: Tree) }
struct Packet { bytes: [u8], label: str }

fn tree_count(t: Tree) -> i64
  requires size(t) <= 1000
  ensures result >= 0 && result <= size(t)
  decreases size(t)
{
  match t {
    Tree::Empty => { return 0; }
    Tree::Node(v, l, r) => { return 1 + tree_count(l) + tree_count(r); }
  }
}
```
- **Recursion and `decreases`.** Functions may call themselves or each other, in any order. Every function in a
  recursive cycle needs exactly one `decreases e` after its `requires`/`ensures`. `e` is a mathematical integer built
  from parameters, constants and contract operations. The verifier proves `e >= 0` at entry and, at every call inside
  the cycle, that the callee's `e` on the actual arguments is `>= 0` and smaller than the caller's entry value
  (`verify` errors `recursive_nonneg`, `recursive_decrease`). Only then is the callee's `ensures` assumed, so it works
  as an induction hypothesis. One scalar measure; for mutual phases use e.g. `2 * n + 1` versus `2 * n`.
- **Recursive types.** Non-generic structs/enums may refer to each other directly through fields, e.g. a list as
  `struct Node { value: i64, next: Link }` with `enum Link { End, More(node: Node) }`. Every type must have a finite
  value (`struct Bad { next: Bad }` is rejected). The compiler adds the boxing; you never write `Box`. Recursion must
  be a direct field, not hidden in `Option`, `Result`, arrays, generic arguments or collections.
- **`size(x)`** (contracts only, non-generic struct/enum values): the number of struct/enum constructors in the value,
  counting only active payloads; scalars, arrays and strings count 0 (use `len` for those). Every direct child is
  smaller than its parent, so `decreases size(t)` works for tree walks. Bound it (`requires size(t) <= 1000`) when
  you add up per-node values.
- **Buffer fields.** `[i64]`, `[u8]`, `[bool]` and `str` may be fields of non-generic structs and payloads. Initialize
  or replace them with a fresh buffer (`alloc`, a literal string) or `copy(view)`; return a field buffer with `copy`.
  `p.bytes[i] = v` is not allowed: copy the field into a mutable local, change it, and assign the field back.
- **Values, not pointers.** Recursive and buffer-bearing values are independent: copying one deep-copies everything,
  and changing a copy never changes the original. Parameters, field reads and `match` bindings are read-only views
  and do not allocate. Putting an existing value into an owning place (`let`, assignment, constructor field,
  `return`) copies it and needs `! alloc`; a fresh constructor or call result moves without a copy. Any constructor
  of a recursive value needs `! alloc`. While a `match` arm views part of a mutable local, that local cannot be
  changed (`type/recursive_borrow`). Whole-value `==`/`!=` on values that contain arrays or strings is rejected
  (`type/eq_type`); compare tags, lengths and elements instead.
- **Limits.** Recursive and buffer-field types cannot be generic arguments, `Option`/`Result` payloads or G6
  collection elements. Functions whose signatures use them are internal (no exported ABI or `--rust-bindings` entry);
  expose them through functions with ordinary parameters. Contracts are not invented: a property such as "x is
  somewhere in the tree" must be stated with the existing contract operations, and not every recursive property is
  expressible. Proofs about deeply nested or very wide types can be slow. Native stack depth is not checked: very
  deep recursion, copying or freeing can overflow the stack (a resource failure, never a successful result).
  `--no-verify` does not check `decreases` and may recurse forever. Run-time `requires` that use `size`, `==` or
  field reads of recursive values count one unit of the 2^30 contract budget per node visited.
- **New error codes:** `decreases_syntax`, `recursive_decreases` (missing measure), `recursive_polymorphism`,
  `recursive_generic_type`, `recursive_borrow`, `size_type`, `recursive_nonneg`, `recursive_decrease`; reused:
  `recursive_type` (type without a finite value), `field_type`, `type_argument`, `eq_type`, `missing_effect`.

## 6f. Modules and visibility (G4)
Full contract: `docs/G4_SPEC.md` (§10–§13 are the implemented decisions). Example: `examples/g4_backend/`.
```
// root.pruv                               // arithmetic.pruv
mod arithmetic;                            pub fn increment(x: i64) -> i64
pub fn bounded(x: i64) -> i64                requires 0 <= x && x <= 10
  requires 0 <= x && x <= 10                 ensures result == x + 1
  ensures result == x + 1                  { return x + 1; }
{ return crate::arithmetic::increment(x); }
```
- **Files.** The command-line file is the root. `mod name;` (top level only) loads `name.pruv` next to the root;
  inside `a.pruv`, `mod b;` loads `a/b.pruv`. Only declared files are loaded, each exactly once. No inline modules,
  `pub mod`, path attributes or `mod.pruv`.
- **Explicit mode.** A root that contains `mod` or a top-level `pub` switches the whole program to explicit
  visibility. Then unmarked `fn`/`struct`/`enum` items are private to their file. A root with neither keeps the old
  single-file rules and output unchanged.
- **Paths.** Other modules' items are reached only by full paths from `crate`: `crate::math::clamp(x)`,
  `crate::model::Event::Hit`, `crate::model::Pair<i64, bool>`, `crate::math::first::<i64>(a)`. Plain names look only
  in the same file, then builtins. There is no `use`, `self`, `super` or relative path.
- **Visibility.** `pub` makes an item usable from every module. Fields and variants of a visible type are always
  visible. A public signature or contract may mention only public types and items (checked through field types too);
  private helpers are fine inside bodies. `pub trusted rust fn` is rejected: wrap it in a public Pruv function.
- **Host entries.** Only root `pub`, non-generic functions are callable from Rust/C (`--rust-bindings`, LLVM
  `pruv_abi_<name>`). Their signatures must be plain values (no collections, recursive or buffer-field types:
  `type/entry_signature`). Child `pub` functions are for Pruv callers only. An optional root `main` must be
  `pub fn main() -> ()`; a child `main` is an ordinary function.
- **Proof.** Every function is verified, including private and unused ones; a caller only sees the callee's
  contract, never its body. Recursion and recursive types may span modules. Host entries check `requires` at run
  time unless `--trust-callers`; `--no-verify` checks `requires` on every call.
- **Diagnostics** in explicit mode carry a `file` field (relative to the root, `/` separators). New codes include
  `parse/module_syntax`, `parse/visibility_syntax`, `parse/module_file`, `type/private_item`, `type/public_interface`,
  `type/entry_signature`, `type/entry_main` (see `docs/G4_SPEC.md` §8 for the full table).

## 6g. In-place array parameters: `inout` (G5)
Full contract: `docs/G5_SPEC.md` (§2–§8 and §15 for deferred limits). Examples: `examples/g5_*.pruv`, `tests/runtime/g5_r*`.
```
fn set_at(inout a: [i64], i: i64, v: i64) -> ()
  requires 0 <= i && i < len(a)
  ensures a[i] == v
  ensures forall k in 0..len(a): k != i ==> a[k] == old(a)[k]
{ a[i] = v; }

let mut w: [i64] = copy(a);
set_at(inout w, 0, 7);
```
- **Syntax and types.** `inout name: T` on a parameter, `T` one of `[i64]`, `[u8]`, `[bool]` or `[T]` with `T: Element`
  (section 6c); any other type is `type/inout_type`. The mode is not part of the type. The caller must write `inout`
  at the call (`type/inout_argument` if missing or extra). The marked argument must be a whole `let mut` array local
  or an `inout` parameter of the caller, with exactly the parameter's element type; immutable locals, ordinary
  parameters, `match` binders, fields, elements and calls are rejected. `inout` is contextual, not a keyword;
  malformed or combined modes (e.g. with `take`) are `parse/inout_syntax`.
- **What the callee may do.** Read, index, `len`, `copy`, and assign elements (`a[i] = e`, with the usual bounds,
  `u8` range and refinement proofs). Never `a = ...` (`type/immutable`), resize, move, store or return the view
  itself (`type/array_alias`; return `copy(a)` instead). It may pass `a` unmarked to a read-only parameter or
  forward it as `inout a`. No `alloc` effect is needed for mutation.
- **Exclusivity.** A marked binding may occur nowhere else in the same call's arguments, not even inside nested calls
  or `len(a)`: `f(inout a, a)`, `f(inout a, len(a))` and `f(inout a, inout a)` are `type/inout_alias`. Compute
  `let n: i64 = len(a);` first. Read-only arguments may alias each other. Holds in every mode, also under
  `--no-verify` and `--trust-callers`. Mutable access while a `match` arm views the same root is `type/recursive_borrow`.
- **`old`.** `old(a)` names the entry contents of an `inout` parameter `a` of the enclosing function; legal only in
  that function's `ensures`, `invariant` and `assert` (`type/old_context`, `type/old_argument` otherwise: locals,
  ordinary parameters, fields, elements and nested `old` are rejected). It always means function entry. In `requires`
  a parameter is its entry value; in `ensures` an `inout` parameter is its final value. `len(a) == len(old(a))` is
  always known. `old` is a proof object: no copy, no run-time check. Arrays still cannot be compared with `==`.
- **Frame.** After `f(inout a, ...)` the caller knows only what `f`'s `ensures` says about `a`: fresh contents, same
  length. An unconstrained element is arbitrary, even if the body never writes it, so state the frame
  (`k != i ==> a[k] == old(a)[k]`). Other variables keep their values. The `requires` are proved on the pre-call
  arrays and `old` refers to them. `ensures` of an `inout` function are always applied at the call.
- **Statement boundaries.** A call with `inout` may only be the whole expression of an expression statement, a `let`
  initializer, the right side of a whole-variable assignment, or a `return` (parentheses do not matter); anywhere
  else (argument, operator, condition, index, field or element assignment) it is `type/inout_context`. Its result may
  have any supported type. Use a temporary: `let changed: bool = update(inout data);`. Arguments are evaluated left
  to right and the mutation completes before the `let`/assignment/return.
- **Generics.** `fn swap<T: Element>(inout a: [T], ...)` works like any G3 function; `swap::<i64>(inout w, i, j)`
  (`examples/g5_generic_swap.pruv`). It is specialized per element type, also across modules.
- **Loops.** A loop that passes an array as `inout` treats it as changed: an `inout` parameter keeps its length, a
  local keeps its length unless the loop can also reassign it. State what the loop preserves in `invariant`s
  (`old` may be used there); `--infer` may miss such invariants but never keeps a false one.
- **Refinements.** An annotation on an `inout` parameter is an entry `requires` only, not an output guarantee; state
  that in `ensures`. A refined local passed `inout` must satisfy its refinement again right after the call
  (`verify/refinement_assign`), proved from `ensures` (a length-only refinement follows from the preserved length).
- **Modes and back ends.** Verified and safe (`--no-verify`) modes both work. Safe mode checks the `requires` of an
  `inout` function on every call to it, including under `--trust-callers`, which only skips checks at host entries;
  other internal calls follow the existing safe-mode rules. Rust emits
  `&mut [T]`; LLVM passes the existing pointer and length with `noalias nocapture` and no `readonly`, and never frees
  it. Neither allocates or copies for the parameter. Programs without `inout` compile exactly as before.
- **Host limits.** An `inout` function is never host-visible: no exported ABI entry, no typed variant, no
  `--rust-bindings` entry. In explicit mode a root `pub` non-generic function with `inout` is `type/entry_signature`
  (private, child-`pub` and generic functions may use it; in legacy mode it is automatically internal); a
  `trusted rust fn` with `inout` is `type/foreign_signature`. Give the host an ordinary function that owns a
  `copy` of its input, calls the `inout` helpers on it and returns it.
- **Not supported.** `inout` calls nested in expressions or conditions, fields or elements as `inout` places, scalar,
  `str`, aggregate or collection `inout` parameters, `old` of anything but an `inout` parameter, mutable host entries.
- **New error codes:** `inout_syntax`, `inout_type`, `inout_argument`, `inout_alias`, `inout_context`, `old_context`,
  `old_argument`; reused: `immutable`, `array_alias`, `recursive_borrow`, `entry_signature`, `foreign_signature`,
  `reserved`, `refinement_assign`.

## 6h. Files (G10)

`fs` is the file-system effect, independent of `io` (stdout) and `alloc`. Direct and transitive calls
must declare their effects. `File` is an owned type: local, borrowed parameter, `take` parameter or
result; never nested in aggregates/collections or exposed in a host-entry signature. Host entries take paths
as `str`; paths are relative to the process working directory.

| Operation | Effects | Meaning / contract |
|---|---|---|
| `file_open_read(path: str) -> File` | fs | readable iff ok; not writable; size 0 |
| `file_create(path: str) -> File` | fs | truncate/create; writable iff ok; not readable; size 0 |
| `file_read_all(take f: File) -> File` | fs, alloc | requires readable; read remaining bytes into the handle; readable iff ok; not writable; failure clears buffer |
| `file_write_str(take f: File, text: str) -> File` | fs | requires writable; write UTF-8 bytes; writable iff ok; not readable; size 0 |
| `file_write_bytes(take f: File, data: [u8]) -> File` | fs | same as write_str, for bytes |
| `file_close(take f: File) -> bool` | fs | consume/close; true only if ok and final flush succeeds |
| `file_ok/readable/writable(f: File) -> bool` | none | status/mode observers, usable in code and contracts |
| `file_size(f: File) -> i64` | none | buffered byte count, >= 0 |
| `file_byte(f: File, i: i64) -> i64` | none | requires 0 <= i < size; returns 0..255 |

Pass ownership with `move f`; a moved/closed binding cannot be read until reassigned. Branch joins and loops
follow §6d. Borrowing never transfers ownership. Every live owner is dropped on scope exit, including early
return; drop closes the handle and ignores errors. Explicit close reports flush success; it does not sync
to disk. OS failures become `file_ok == false`, not panics. Verification models each operation's result only
through its catalog contract: writing and reopening a path does not prove its contents.

```
fn sum_bytes(f: File) -> i64
  requires file_size(f) <= 1000000
  ensures result >= 0
{
  let mut s: i64 = 0;
  let mut i: i64 = 0;
  while i < file_size(f)
    invariant 0 <= i && i <= file_size(f) && 0 <= s && s <= 255 * i
    decreases file_size(f) - i
  {
    s = s + file_byte(f, i);
    i = i + 1;
  }
  return s;
}
pub fn checksum(path: str) -> i64 ! fs, alloc
  ensures result >= -1
{
  let f: File = file_open_read(path);
  if !file_readable(f) { return -1; }
  let g: File = file_read_all(move f);
  if !file_ok(g) || file_size(g) > 1000000 { return -1; }
  return sum_bytes(g);
}
```

Rust uses `pruv_File`; LLVM uses an opaque pointer and the same Rust operations in the §6d shim emitted with
`--rust-bindings`, including observers and drop. Link with Rust; `--emit exe|obj` rejects File programs with
`codegen/foreign_target`. `--foreign-checks` follows §6d: with `--no-verify`, reading a write handle exits 101
with `pruv: foreign requires violated:`. Programs without File retain their generated output.

## 6i. Parallel calls: par (G7)

A `par` statement runs two or more semicolon-terminated unit calls and joins them
before the next statement. `par` remains an ordinary identifier elsewhere.

```pruv
fn set(inout a: [i64], x: i64) -> ()
  requires len(a) > 0
  ensures a[0] == x
{ a[0] = x; }

fn pair(inout a: [i64], inout b: [i64]) -> ()
  requires len(a) > 0 && len(b) > 0
  ensures a[0] == 7 && b[0] == 9
{
  par { set(inout a, 7); set(inout b, 9); }
}
```

Each branch must call an ordinary Pruv function returning `()`. Arguments are
binding names, integer/bool literals, or `inout name`; bind calculations first.
Boundary types are `i64`, `bool`, primitive arrays (`[i64]`, `[u8]`, `[bool]`),
and supported concrete `Element` specializations. Arrays are borrowed, never
moved or copied. Every written array must be disjoint from every other branch's
read or write arrays; immutable inputs may repeat. These rules apply even with
`--no-verify --trust-callers`.

The entire reachable branch call graph may use only the `alloc` effect, with no
trusted Rust functions, catalog operations, or nested `par`. Ordinary pure
builtins and sequential helpers are allowed. The caller may perform I/O outside
the group; branch allocation effects propagate to it. Scheduling adds no source
effect. Arguments are captured once in branch and parameter order before workers
start. All started workers join before normal continuation; successful results
match sequential calls in source order. Execution order and overlap are unspecified.

Verification checks every callee normally and proves all branch preconditions
against the same group-entry state. At join it assumes their postconditions,
including unit calls without inout; written arrays retain their lengths and only
contracted contents. `old` in a branch contract refers to its group-entry values.
Safe mode retains bounds, arithmetic and branch precondition checks even under
`--trust-callers`; postconditions are not checked dynamically.

A caught worker panic joins started workers and exits 101. Spawn failure joins
started workers, prints `pruv: parallel spawn failed`, and exits 101. Failures do
not roll back mutations. Process-fatal failures and LLVM runtime check exits may
terminate immediately; no Rust panic unwinds across the callback ABI.

The Rust backend uses scoped threads. LLVM keeps branch bodies in LLVM and emits
private callbacks with stack contexts; its generated `--rust-bindings` file
contains the synchronous Rust thread bridge. Emit IR and bindings, compile the
IR with the usual Pruv runtime, and link with a Rust host. Native `--emit exe` and
`--emit obj` reject `par` with `codegen/parallel_target`.

## 6j. Cost bounds: cost and spent (Stage 5)

A function may state an upper bound on the work it performs. The verifier proves
that every execution stays within it.

```pruv
fn sum(a: [i64]) -> i64
  requires len(a) <= 1_000_000
  cost len(a)
{
  let mut s: i64 = 0;
  let mut i: i64 = 0;
  while i < len(a)
    invariant 0 <= i && i <= len(a)
    invariant spent == i
    decreases len(a) - i
  { s = s + a[i]; i = i + 1; }
  return s;
}
```

The header clause `cost <i64 expr>` comes last (`requires* ensures* decreases?
cost?`), at most once. It is a contract expression over the parameters, evaluated
in the entry state, and must be defined there; `result`, `old` and `spent` are not
allowed in it. `spent` is the number of units this call has spent so far. It may
appear only in `invariant` and `assert` of a function with `cost`. `cost` and
`spent` are keywords.

Units: each `while` iteration adds 1 before the body; a call `f(args)` adds
`1 + C_f` evaluated on the actual arguments (the callee's stated bound, not its
real spending); `alloc(n, v)` adds `1 + n`; `copy(a)` adds `1 + len(a)`; `par`
adds every branch's call units once at group entry from the captured arguments.
Everything else costs 0. Every return must satisfy `spent <= C`, where `C` is the
bound at entry. A function without `cost` is unchanged.

A function with `cost` may call only functions with `cost`
(`effect/cost_callee`), and may not use foreign, catalog or file operations
(`effect/cost_unsupported`). Loops forget `spent` like any assigned variable, so
a loop needs a `spent` invariant. A failed return check is `verify/cost_bound`
with a counterexample; an undefined bound is `verify/contract_domain`. Generic
functions may have `cost`, and a `pub` function's bound is part of its interface.

Verified mode erases `cost` and `spent`: Rust source, LLVM IR and bindings are
byte-identical to the program without them. Safe mode (`--no-verify`) keeps a
checked counter per cost function on both backends. It evaluates `C` at entry
with the run-time contract evaluator (after the function's own `requires` checks
unless `--trust-callers`; outside its domain `pruv: requires undefined`). A
return with `spent > C` or a negative `C`, a call whose evaluated callee bound
is negative, or counter overflow panics `pruv: cost exceeded` (exit 101). `--trust-callers` does not disable these
checks; `assert` stays erased.

## 6k. The standard module: std (G8)

Full contract: `docs/G8_SPEC.md`. Examples: `examples/g8_std_clamp.pruv`, `examples/g8_std_index.pruv`,
`examples/g8_std_modules/`.

The compiler ships one module of twelve verified functions written in ordinary Pruv. It is source, not a
precompiled library: the bundled file is parsed, checked and proved together with your program.

```pruv
mod std;

pub fn bounded(x: i64) -> i64
  ensures 0 <= result && result <= 100
{
  return crate::std::clamp_i64(x, 0, 100);
}
```

- **One import, at the root.** `mod std;` in the root file loads the bundled module. It is the only way in: no `use`,
  no bare `std::`, no implicit import. `mod std;` in a child is `parse/std_import_location`. Like any `mod`, it
  switches the program to explicit visibility (section 6f), so a root `main` must be `pub`.
- **Qualified calls.** Every module, root or child, calls `crate::std::<name>(...)`. A function of your own named
  `min_i64` stays your own; plain names never fall back to std. Std functions may not appear in contracts: write the
  property itself (`forall k in 1..len(a): a[k - 1] <= a[k]`), not `crate::std::is_sorted_i64(a)`.
- **Contracts.** The twelve functions and their exact contracts are listed in `docs/G8_SPEC.md` section 4:
  `min_i64`, `max_i64`, `clamp_i64` (requires `lo <= hi`), `abs_i64` (requires `x > i64::MIN`), `checked_add_i64`
  and `checked_sub_i64` (return `None` exactly when the mathematical result leaves i64), `sum_i64`, `contains_i64`,
  `index_of_i64` (the first matching index, `None` when absent), `is_sorted_i64` (nondecreasing, empty and singleton
  arrays are sorted), `array_max_i64` (requires `len(a) > 0`) and `reverse_i64 ! alloc` (a fresh array; the input is
  unchanged). A call proves the callee's `requires` on your arguments and then knows only its `ensures`, exactly as
  for your own functions.
- **Sum bounds.** `sum_i64` requires `len(a) <= 1_000_000` and every element in `-1_000_000_000..=1_000_000_000`.
  This keeps every prefix of the left-to-right sum within 10^15. It rejects some inputs whose sum would fit; bounding
  only the final sum would not be sound. For other inputs, write your own loop or use `checked_add_i64`.
- **Proof on every compile.** A verified compilation that imports std proves all twelve bundled functions, used or
  not, before generating anything. There is no cache, certificate or trusted copy. A std proof that fails or returns
  unknown fails the whole compilation with its ordinary code (`verify/ensures`, `verify/overflow`, ...) and the file
  label `@std/std.pruv`. Without `mod std;`, nothing is loaded and output is byte-identical to before.
- **Errors.** Your calls report ordinary diagnostics: `verify/call_requires` for an unproved precondition (with a
  counterexample), unknown-function resolution for a misspelled name, unknown-module resolution when `mod std;` is
  missing. `parse/std_source` means the compiler's own bundled resource is missing or unreadable: reinstall the
  compiler; do not create a `std.pruv` of your own.
- **Safe mode.** `--no-verify` proves nothing (neither your code nor std) but keeps parsing and checking, checks
  index and overflow at run time, and checks every std `requires` on every call (`pruv: requires violated:
  crate::std::<name>`). `--trust-callers` only skips the root entry's `requires`; the checks inside std calls stay.
- **Host wrappers.** Std functions are Pruv-only APIs. They are never exported as `pruv_abi_*` symbols or Rust
  bindings, and both backends give them internal linkage. To call one from Rust or C, write a root `pub` wrapper
  with a plain-value signature:
  ```pruv
  mod std;
  pub fn safe_add(a: i64, b: i64) -> Option<i64> { return crate::std::checked_add_i64(a, b); }
  ```
  A wrapper may return the `reverse_i64` result; ownership passes to the host as for any owned array result.
- **Migrating a module named std.** `std` is now reserved for the bundled module. If your project has a `std.pruv`
  next to the root and declares `mod std;`, compilation fails with `parse/std_module_conflict` (even if the file is
  identical to the bundle, and also for a directory or dangling link of that name). Rename the file and the
  `crate::std::...` paths that used it, e.g. to `mystd.pruv` and `crate::mystd::...`. Other module names and local
  identifiers named `std` are unchanged.
- **Packaging.** The Python compiler reads `stdlib/std.pruv` next to its `pruvc/` package directory, never from the
  working directory or an environment path, so copy or install both directories together. The Rust compiler embeds
  the same file at build time; its binary needs no file next to it.

## 7. What the compiler proves (all must succeed)
1. Every `a[i]` (read or write): `0 <= i < len(a)`.
2. Every `+ - * unary-` in code: result within i64 range.
3. `/ %`: divisor > 0, dividend >= 0. `alloc(n, v)`: 0 <= n <= 2^40.
4. Callee `requires` at each call; `ensures` at each return; `assert`s.
5. Loop invariants hold on entry and are preserved; `decreases` is >= 0 at each iteration start and strictly decreases.
   For a recursive call, the callee's `decreases` (evaluated on the arguments) is >= 0 and strictly below the caller's
   value at entry (section 6e).
6. Array parameters have `0 <= len(a) <= 2^40` and elements in i64 range (assumed; guaranteed for Pruv callers because every alloc is proven <= 2^40).
Variables not assigned in a loop keep their values across it; assigned ones are only known through invariants.
A variable counts as assigned if the loop body assigns it, stores into its elements, or passes it as an `inout`
argument (section 6g); an `inout` array keeps only its length across the loop.

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
| a `while` that assigns a refined local alive at the loop head, or passes it as an `inout` argument | that local's conditions are put first in the loop's `invariant` list |
| an `inout` call on a refined local | an `assert` of the local's condition right after the call (`verify/refinement_assign`), proved from the callee's `ensures`; an `inout` parameter's annotation is only an entry `requires` |
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
