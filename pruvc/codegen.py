"""Pruv -> Rust.  gen_rust(prog, verified=True, trust_callers=False, budget=1 << 30)

Contracts are erased from function bodies; they are only used (a) by the verifier and
(b) to build the runtime `requires` check of the public entry point.

Modes (two independent axes):
  verified=True   Output of a program the verifier proved: array accesses are
                  `get_unchecked` (unsafe), arithmetic is plain Rust.
  verified=False  (--no-verify, "safe mode") No proof exists, so nothing unsafe is emitted
                  and nothing wraps silently: array reads/writes go through pruv_get/pruv_set
                  (panic unless 0 <= i < len), + - * / % and unary - go through
                  pruv_add/pruv_sub/pruv_mul/pruv_div/pruv_rem/pruv_neg (+ - * and unary -
                  are checked_*, panic on overflow), alloc(n, v) goes through
                  pruv_alloc (panic unless 0 <= n <= 2^40).  / and % use the same domain
                  the verifier proves (verify.py): divisor > 0 and dividend >= 0,
                  otherwise panic "division outside domain: ...".
  trust_callers=False (default)  Functions with `requires` are emitted twice; the public
                  entry checks every requires at run time and panics with
                  "pruv: requires violated: <fn>: <expr>" before running the body.
  trust_callers=True  The public entry calls the body without checks (for benchmarking).

Generated names (reserved: the parser rejects any user identifier that starts with `pruv_`
or contains `__`, error code reserved_name, so user names never collide with these):
  f                 public function, same name/params/return type as the Pruv function
                    (`#[inline]` wrapper when f has requires, otherwise the real body).
  f__pruv_body       private unchecked body, only for functions with requires.
                    Verified mode: calls inside Pruv code go straight to f__pruv_body
                    (the caller proved requires).  Safe mode: inner
                    calls go to the checked entry f.
  pruv_*             helper functions emitted once at the top of the file (only the ones
                    needed): pruv_idx pruv_oob pruv_get pruv_set pruv_ovf pruv_add pruv_sub
                    pruv_mul pruv_div pruv_rem pruv_neg pruv_alloc (safe mode) and
                    pruv_ud pruv_cidx pruv_cadd pruv_csub pruv_cmul pruv_cneg pruv_cdiv pruv_crem
                    (requires evaluation).  Local temporaries pruv_* are also reserved.
                    [u8] programs also get pruv_elem_oor pruv_get_u8 pruv_set_u8 pruv_alloc_u8
                    (safe mode) and pruv_cidx_u8 (requires evaluation).

Run-time requires evaluation uses i128 (contracts are mathematical integers).  Contract
/ and % are Euclidean (div_euclid/rem_euclid, as z3 Int).  Anything undefined there
(division by zero, index out of range, i128 overflow, max/min over an empty range,
some_val of None, ...) panics with "pruv: requires undefined: ...".

G1 (structs/enums): user types are `Copy` and emitted by emit_public_types(prog) at the top of
the file.  Contract evaluation uses mirror types `pruv_contract__Name` (every i64 leaf is i128,
Option/Result carry i128) and converters `pruv_to_c__Name(value)` (recursive; an enum converts
only its active variant), so contract arithmetic never goes through i64.
Standard types are always written `::std::vec::Vec` / `::std::option::Option` /
`::std::result::Result` so user types named Vec etc. cannot collide.

G3 (generics): gen_rust first builds the shared specialization plan (mono.py) and generates from the CONCRETE program
it contains, so there is no generic Rust. Generic function specializations are private fns named `pruv_g3_f_...`
(with `__pruv_body` + a private checked entry when they have `requires`); generic nominal applications are ordinary
`pub struct/enum pruv_g3_t_...` with the usual derives. Option<X> / Result<X> (X != i64) are
`::std::option::Option<R(X)>` / `::std::result::Result<R(X), i64>`; their constructors are written with explicit
turbofish (`None::<R(X)>`, `Ok::<R(X), i64>(..)`). Contract mirrors are recursive: C(Option<X>) = Option<C(X)>,
C(Result<X>) = Result<C(X), i128>. A program without generics is generated directly, byte for byte as before G3.

G9 (recursion, recursive types, aggregate buffer fields; docs/G9_SPEC.md 3, 4, 6, 12): recursion is an ordinary Rust call.
An EXTENDED type (prog.g9["extended"]) derives `Clone, Debug` and never Copy; a recursive edge (prog.g9["boxed"]) is
`::std::boxed::Box<Child>`; buffer fields are Vec<i64>/Vec<u8>/Vec<bool>/String. Value contexts:
  read parameter / payload view  `&T`     (a call argument borrows: `f(&local)`, `f(param)`, `f(&(fresh()))`)
  owning position                 let / assignment / constructor field / return: a named value or a field path is
                                  cloned (`::std::clone::Clone::clone(&x)`), a constructor / call result moves; a
                                  constructor stores a recursive edge as `Box::new(..)`
  match on an extended enum       `match <view> { E::V(a, b) => { let a: i64 = *a; let b: &T = b; .. } }`
A function with an extended type in its signature is private (and so is its checked entry wrapper). Runtime requires use
`size` and `==` on extended values through generated helpers `pruv_csize__Name` / `pruv_ceq__Name` (declaration order,
only the needed ones) over the REAL values: nothing is converted eagerly, only active variants are visited, one budget
unit per node, i128 checked additions; exhaustion -> `pruv: requires undefined: ...`. Types are emitted in the order of
the SCC condensation of the field graph (the same as before for acyclic programs).

G4 A2 (explicit visibility mode, docs/G4_SPEC.md 4, 6; Program.explicit): the program always comes from mono.specialize, which
renames every function and type to its Rust stem (modules.encode_stem; root host entries and root `pub` types keep their
source spelling) and records `pub` / `host_entry` / `disp` (the source-qualified identity used in panic text and manifests).
Only host entries are `pub fn`; source-`pub` types are `pub` Rust types, private ones are private items. Wrappers: verified
mode emits a checked wrapper only for host entries with a requires (none under trust_callers) and Pruv calls invoke
`<stem>__pruv_body`; safe mode emits a private checked wrapper `<stem>` for EVERY function with a requires (and Pruv calls
go through it), under trust_callers the pub entry is unchecked and `<entry>__pruv_chk` is the checked one Pruv callers use.
"""
from vast import *
from typeinfo import TypeTable, is_user_type, is_array, uses_array_type, uses_str, is_collection, dependencies
from foreign import CATALOG

ALLOW = ("#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, "
         "dead_code, unreachable_code, unreachable_patterns, "
         "unconditional_panic, arithmetic_overflow)]")

SAFE_PRELUDE = """\
#[allow(dead_code)]
#[cold]
#[inline(never)]
fn pruv_oob(i: i64, len: usize) -> ! { panic!("pruv: index out of bounds: {} (len {})", i, len) }
#[allow(dead_code)]
#[cold]
#[inline(never)]
fn pruv_ovf(what: &str) -> ! { panic!("pruv: arithmetic error: {}", what) }
#[allow(dead_code)]
#[inline]
fn pruv_idx(i: i64, len: usize) -> usize { if i >= 0 && (i as u64) < (len as u64) { i as usize } else { pruv_oob(i, len) } }
#[allow(dead_code)]
#[inline]
fn pruv_get(a: &[i64], i: i64) -> i64 { a[pruv_idx(i, a.len())] }
#[allow(dead_code)]
#[inline]
fn pruv_set(a: &mut [i64], i: i64, v: i64) { let k = pruv_idx(i, a.len()); a[k] = v; }
#[allow(dead_code)]
#[inline]
fn pruv_add(a: i64, b: i64) -> i64 { match a.checked_add(b) { Some(v) => v, None => pruv_ovf("overflow in +") } }
#[allow(dead_code)]
#[inline]
fn pruv_sub(a: i64, b: i64) -> i64 { match a.checked_sub(b) { Some(v) => v, None => pruv_ovf("overflow in -") } }
#[allow(dead_code)]
#[inline]
fn pruv_mul(a: i64, b: i64) -> i64 { match a.checked_mul(b) { Some(v) => v, None => pruv_ovf("overflow in *") } }
#[allow(dead_code)]
#[inline]
fn pruv_div(a: i64, b: i64) -> i64 { if b > 0 && a >= 0 { a / b } else { pruv_ovf("division outside domain: need divisor > 0 and dividend >= 0") } }
#[allow(dead_code)]
#[inline]
fn pruv_rem(a: i64, b: i64) -> i64 { if b > 0 && a >= 0 { a % b } else { pruv_ovf("division outside domain: need divisor > 0 and dividend >= 0") } }
#[allow(dead_code)]
#[inline]
fn pruv_neg(a: i64) -> i64 { match a.checked_neg() { Some(v) => v, None => pruv_ovf("overflow in unary -") } }
#[allow(dead_code)]
#[inline]
fn pruv_alloc(n: i64, v: i64) -> ::std::vec::Vec<i64> { if n < 0 || n > (1i64 << 40) { pruv_ovf("alloc length outside 0..2^40") } vec![v; n as usize] }
"""

CONTRACT_PRELUDE = """\
#[allow(dead_code)]
#[cold]
#[inline(never)]
fn pruv_ud(what: &str) -> ! { panic!("pruv: requires undefined: {}", what) }
#[allow(dead_code)]
#[inline]
fn pruv_cidx(a: &[i64], i: i128) -> i128 { if i >= 0 && i < (a.len() as i128) { a[i as usize] as i128 } else { pruv_ud("array index out of range") } }
#[allow(dead_code)]
#[inline]
fn pruv_cadd(a: i128, b: i128) -> i128 { a.checked_add(b).unwrap_or_else(|| pruv_ud("i128 overflow in +")) }
#[allow(dead_code)]
#[inline]
fn pruv_csub(a: i128, b: i128) -> i128 { a.checked_sub(b).unwrap_or_else(|| pruv_ud("i128 overflow in -")) }
#[allow(dead_code)]
#[inline]
fn pruv_cmul(a: i128, b: i128) -> i128 { a.checked_mul(b).unwrap_or_else(|| pruv_ud("i128 overflow in *")) }
#[allow(dead_code)]
#[inline]
fn pruv_cneg(a: i128) -> i128 { a.checked_neg().unwrap_or_else(|| pruv_ud("i128 overflow in unary -")) }
#[allow(dead_code)]
#[inline]
fn pruv_cdiv(a: i128, b: i128) -> i128 { if b == 0 { pruv_ud("division by zero in /") } a.checked_div_euclid(b).unwrap_or_else(|| pruv_ud("i128 overflow in /")) }
#[allow(dead_code)]
#[inline]
fn pruv_crem(a: i128, b: i128) -> i128 { if b == 0 { pruv_ud("division by zero in %") } a.checked_rem_euclid(b).unwrap_or_else(|| pruv_ud("i128 overflow in %")) }
"""

SAFE_PRELUDE_U8 = """\
#[allow(dead_code)]
#[cold]
#[inline(never)]
fn pruv_elem_oor(v: i64) -> ! { panic!("pruv: element out of range: {} (u8 0..=255)", v) }
#[allow(dead_code)]
#[inline]
fn pruv_get_u8(a: &[u8], i: i64) -> i64 { a[pruv_idx(i, a.len())] as i64 }
#[allow(dead_code)]
#[inline]
fn pruv_set_u8(a: &mut [u8], i: i64, v: i64) { let k = pruv_idx(i, a.len()); if v < 0 || v > 255 { pruv_elem_oor(v) } a[k] = v as u8; }
#[allow(dead_code)]
#[inline]
fn pruv_alloc_u8(n: i64, v: i64) -> ::std::vec::Vec<u8> { if n < 0 || n > (1i64 << 40) { pruv_ovf("alloc length outside 0..2^40") } if v < 0 || v > 255 { pruv_elem_oor(v) } vec![v as u8; n as usize] }
"""

CONTRACT_PRELUDE_U8 = """\
#[allow(dead_code)]
#[inline]
fn pruv_cidx_u8(a: &[u8], i: i128) -> i128 { if i >= 0 && i < (a.len() as i128) { a[i as usize] as i128 } else { pruv_ud("array index out of range") } }
"""


def is_u8_array(t):
    return t is not None and t.name == "array_u8"


# G2 A5: [bool] preludes (emitted only for programs that use [bool])
SAFE_PRELUDE_BOOL = """\
#[allow(dead_code)]
#[inline]
fn pruv_get_bool(a: &[bool], i: i64) -> bool { a[pruv_idx(i, a.len())] }
#[allow(dead_code)]
#[inline]
fn pruv_set_bool(a: &mut [bool], i: i64, v: bool) { let k = pruv_idx(i, a.len()); a[k] = v; }
#[allow(dead_code)]
#[inline]
fn pruv_alloc_bool(n: i64, v: bool) -> ::std::vec::Vec<bool> { if n < 0 || n > (1i64 << 40) { pruv_ovf("alloc length outside 0..2^40") } vec![v; n as usize] }
"""

CONTRACT_PRELUDE_BOOL = """\
#[allow(dead_code)]
#[inline]
fn pruv_cidx_bool(a: &[bool], i: i128) -> bool { if i >= 0 && i < (a.len() as i128) { a[i as usize] } else { pruv_ud("array index out of range") } }
"""


def is_bool_array(t):
    return t is not None and t.name == "array_bool"


# G2 B2: str preludes (emitted only for programs that use str)
STR_PRELUDE = """\
#[allow(dead_code)]
#[inline]
fn pruv_str_boundary(a: &str, i: i64) -> bool { i >= 0 && (i as u64) <= (a.len() as u64) && a.is_char_boundary(i as usize) }
"""

SAFE_PRELUDE_STR = """\
#[allow(dead_code)]
#[cold]
#[inline(never)]
fn pruv_slice_oob(lo: i64, hi: i64, len: usize) -> ! { panic!("pruv: string slice out of bounds: {}..{} (len {})", lo, hi, len) }
#[allow(dead_code)]
#[cold]
#[inline(never)]
fn pruv_slice_cut(lo: i64, hi: i64, len: usize) -> ! { panic!("pruv: UTF-8 boundary error: {}..{} (len {})", lo, hi, len) }
#[allow(dead_code)]
#[inline]
fn pruv_get_str(a: &str, i: i64) -> i64 { a.as_bytes()[pruv_idx(i, a.len())] as i64 }
#[allow(dead_code)]
#[inline]
fn pruv_substr(a: &str, lo: i64, hi: i64) -> ::std::string::String { if !(lo >= 0 && lo <= hi && (hi as u64) <= (a.len() as u64)) { pruv_slice_oob(lo, hi, a.len()) } if !(a.is_char_boundary(lo as usize) && a.is_char_boundary(hi as usize)) { pruv_slice_cut(lo, hi, a.len()) } ::std::string::String::from(&a[(lo as usize)..(hi as usize)]) }
"""

CONTRACT_PRELUDE_STR = """\
#[allow(dead_code)]
#[inline]
fn pruv_cidx_str(a: &str, i: i128) -> i128 { if i >= 0 && i < (a.len() as i128) { a.as_bytes()[i as usize] as i128 } else { pruv_ud("array index out of range") } }
#[allow(dead_code)]
#[inline]
fn pruv_cboundary(a: &str, i: i128) -> bool { i >= 0 && i <= (a.len() as i128) && a.is_char_boundary(i as usize) }
"""


def is_str(t):
    return t is not None and t.name == "str"


def str_lit(bs):
    """Rust literal of UTF-8 bytes: printable ASCII except " and \\ as is, everything else \\u{hex}."""
    out = []
    for ch in bs.decode("utf-8"):
        o = ord(ch)
        if 0x20 <= o <= 0x7E and ch != '"' and ch != "\\":
            out.append(ch)
        else:
            out.append("\\u{%x}" % o)
    return '"' + "".join(out) + '"'


SAFE_ARITH = {"+": "pruv_add", "-": "pruv_sub", "*": "pruv_mul", "/": "pruv_div", "%": "pruv_rem"}
CONTRACT_ARITH = {"+": "pruv_cadd", "-": "pruv_csub", "*": "pruv_cmul", "/": "pruv_cdiv", "%": "pruv_crem"}


# ---------------------------------------------------------------------------
# G6 (docs/G6_SPEC.md section 12): extra attributes and preludes, emitted only for programs that use G6.
# ---------------------------------------------------------------------------
ALLOW_G6 = ALLOW[:-2] + ", unused_assignments, unused_comparisons)]"

_UD_OLD = """\
#[allow(dead_code)]
#[cold]
#[inline(never)]
fn pruv_ud(what: &str) -> ! { panic!("pruv: requires undefined: {}", what) }
"""

# pruv_ud with a boundary context: a foreign helper sets the context (RAII guard), so that an undefined contract
# inside it reports `pruv: foreign contract undefined: NAME: what`; elsewhere the message is unchanged.
_UD_G6 = """\
::std::thread_local! { static PRUV_CTX: ::std::cell::Cell<&'static str> = ::std::cell::Cell::new(""); }
#[allow(dead_code)]
struct PruvCtx;
impl ::std::ops::Drop for PruvCtx { fn drop(&mut self) { PRUV_CTX.with(|c| c.set("")); } }
#[allow(dead_code)]
fn pruv_ctx(name: &'static str) -> PruvCtx { PRUV_CTX.with(|c| c.set(name)); PruvCtx }
#[allow(dead_code)]
#[cold]
#[inline(never)]
fn pruv_ud(what: &str) -> ! {
    let c: &'static str = PRUV_CTX.with(|c| c.get());
    if c.is_empty() { panic!("pruv: requires undefined: {}", what) } else { panic!("pruv: foreign contract undefined: {}: {}", c, what) }
}
"""
assert _UD_OLD in CONTRACT_PRELUDE
CONTRACT_PRELUDE_G6 = CONTRACT_PRELUDE.replace(_UD_OLD, _UD_G6)

FILE_PRELUDE = ("struct pruv_File { file: ::std::option::Option<::std::fs::File>, "
                "ok: bool, readable: bool, writable: bool, buf: ::std::vec::Vec<u8> }\n")

G6_PRELUDE = """\
#[allow(dead_code)]
#[cold]
#[inline(never)]
fn pruv_g6_req(name: &str, what: &str) -> ! { panic!("pruv: foreign requires violated: {}: {}", name, what) }
#[allow(dead_code)]
#[cold]
#[inline(never)]
fn pruv_g6_ens(name: &str, what: &str) -> ! { panic!("pruv: foreign ensures violated: {}: {}", name, what) }
#[allow(dead_code)]
#[cold]
#[inline(never)]
fn pruv_g6_repr(what: &str) -> ! { panic!("pruv: invalid representation: {}", what) }
#[allow(dead_code)]
#[inline]
fn pruv_g6_charge(budget: &mut i64, n: usize) { let n: i64 = if n > (i64::MAX as usize) { i64::MAX } else { n as i64 }; *budget = budget.saturating_sub(n); if *budget < 0 { pruv_ud("budget") } }
"""


# ---------------------------------------------------------------------------
# G9 A2: runtime contract helpers for `size` and for equality of extended (buffer-free recursive) values. They are emitted
# only when a runtime requires needs them (see Gen.g9_helper_texts) and share the entry's iteration budget.
# ---------------------------------------------------------------------------
G9_TICK = """\
#[allow(dead_code)]
#[inline]
fn pruv_g9_tick(pruv_budget: &mut i64) { *pruv_budget -= 1; if *pruv_budget < 0 { pruv_ud("contract iteration budget exceeded") } }
"""
G9_HELPER_ALLOW = "#[allow(dead_code, non_camel_case_types, non_snake_case, unused_variables, unreachable_patterns)]"


def nominals_in(t):
    """names of the user types a field of type t can contribute to `size` / structural equality: the type itself, or
    the payload type of Option / Result (arrays, str and scalars contribute nothing), in first-occurrence order"""
    if t.owner is None and t.args and t.name in ("option", "result"):
        return nominals_in(t.args[0])
    if is_user_type(t):
        return [t.name]
    return []


def rty(t, param=False):
    if t.owner is None and t.args and t.name in ("option", "result"):  # G3: Option<X> / Result<X>, X != i64
        x = rty(t.args[0])
        if t.name == "option":
            return "::std::option::Option<%s>" % x
        return "::std::result::Result<%s, i64>" % x
    if t.owner is None and t.name in ("vec", "hashmap", "string", "file"):   # G6: owned; a borrowed parameter is a reference
        if t.name == "vec":
            r = "::std::vec::Vec<%s>" % rty(t.args[0])
        elif t.name == "hashmap":
            r = "::std::collections::HashMap<%s, %s>" % (rty(t.args[0]), rty(t.args[1]))
        elif t.name == "file":
            r = "pruv_File"
        else:
            r = "::std::string::String"
        return "&" + r if param else r
    simple = {"i64": "i64", "bool": "bool", "unit": "()", "option": "::std::option::Option<i64>",
              "result": "::std::result::Result<i64, i64>"}
    if t.name in simple:
        return simple[t.name]
    if t.name == "array":
        return "&[i64]" if param else "::std::vec::Vec<i64>"
    if t.name == "array_u8":
        return "&[u8]" if param else "::std::vec::Vec<u8>"
    if t.name == "array_bool":  # G2 A5
        return "&[bool]" if param else "::std::vec::Vec<bool>"
    if t.name == "str":  # G2 B2
        return "&str" if param else "::std::string::String"
    if is_user_type(t):
        return t.name
    raise Exception("codegen: unsupported type %r" % (t,))


def cty(t):
    """contract (i128) mirror of a type"""
    if t.owner is None and t.args and t.name in ("option", "result"):  # G3: C(Option<X>) = Option<C(X)>
        x = cty(t.args[0])
        if t.name == "option":
            return "::std::option::Option<%s>" % x
        return "::std::result::Result<%s, i128>" % x
    n = t.name
    if n == "i64":
        return "i128"
    if n == "bool":
        return "bool"
    if n == "option":
        return "::std::option::Option<i128>"
    if n == "result":
        return "::std::result::Result<i128, i128>"
    if is_user_type(t):
        return "pruv_contract__" + n
    raise Exception("codegen: type %r has no contract representation" % (t,))


def conv(t, x):
    """Rust expression turning the executed value `x` (type t) into its contract value"""
    if t.owner is None and t.args and t.name in ("option", "result"):  # G3: recursive, payload first
        inner = conv(t.args[0], "v")
        if t.name == "option":
            return x if inner == "v" else "%s.map(|v| %s)" % (x, inner)
        ok = x if inner == "v" else "%s.map(|v| %s)" % (x, inner)
        return "%s.map_err(|v| v as i128)" % ok
    n = t.name
    if n == "i64":
        return "(%s as i128)" % x
    if n == "bool":
        return x
    if n == "option":
        return "%s.map(|v| v as i128)" % x
    if n == "result":
        return "%s.map(|v| v as i128).map_err(|v| v as i128)" % x
    if is_user_type(t):
        return "pruv_to_c__%s(%s)" % (n, x)
    raise Exception("codegen: type %r has no contract representation" % (t,))


def condensed_type_order(decls):
    """G9 A2: declarations (dict name -> decl, first declaration wins) in dependency-first order over the SCC
    condensation of the field-dependency graph. Iterative Tarjan (no recursion over the type graph): roots are visited in
    declaration order, successors in field order (first occurrence), a component is emitted when its root finishes, and
    the members of one component are listed in declaration order. For an acyclic graph this is exactly the old
    depth-first post-order of TypeTable._build_order, so the order of non-recursive programs does not change."""
    names = list(decls)
    index = dict((n, i) for i, n in enumerate(names))
    adj = []
    for n in names:
        d = decls[n]
        fields = d.fields if isinstance(d, StructDecl) else [f for v in d.variants for f in v.fields]
        out = []
        for f in fields:
            for m in dependencies(f.type):
                j = index.get(m)
                if j is not None and j not in out:
                    out.append(j)
        adj.append(out)
    count = len(names)
    num = [-1] * count
    low = [0] * count
    onstack = [False] * count
    stack = []
    comps = []
    counter = 0
    for root in range(count):
        if num[root] != -1:
            continue
        num[root] = low[root] = counter
        counter += 1
        stack.append(root)
        onstack[root] = True
        work = [(root, 0)]
        while work:
            v, pos = work.pop()
            if pos < len(adj[v]):
                work.append((v, pos + 1))
                w = adj[v][pos]
                if num[w] == -1:
                    num[w] = low[w] = counter
                    counter += 1
                    stack.append(w)
                    onstack[w] = True
                    work.append((w, 0))
                elif onstack[w]:
                    low[v] = min(low[v], num[w])
            else:
                if low[v] == num[v]:
                    comp = []
                    while True:
                        w = stack.pop()
                        onstack[w] = False
                        comp.append(w)
                        if w == v:
                            break
                    comps.append(comp)
                if work:
                    parent = work[-1][0]
                    low[parent] = min(low[parent], low[v])
    return [decls[names[i]] for comp in comps for i in sorted(comp)]


class CondensedTypeTable(TypeTable):
    """TypeTable whose dependency order is computed on the SCC condensation (G9 programs only)."""
    def _build_order(self):
        self.order = condensed_type_order(self.decls)


def make_type_table(prog):
    return CondensedTypeTable(prog) if getattr(prog, "g9", None) is not None else TypeTable(prog)


def g9_sets(prog):
    """(extended declaration names, boxed field labels) of a G9 program; two empty sets otherwise.
    A boxed label is "Struct.field" or "Enum::Variant.field" (check.py field_label)."""
    meta = getattr(prog, "g9", None)
    if meta is None:
        return set(), set()
    return set(meta["extended"]), set(meta["boxed"])


def emit_public_types(prog, order=None):
    """`pub struct` / `pub enum` for every user type, dependency-first (TypeTable.order).
    G9: an extended type (recursive, or holding a buffer or an extended type) derives Clone, never Copy; a boxed field
    (recursive edge inside a recursive type SCC) is `::std::boxed::Box<Child>`; buffer fields are Vec / String.
    Every other type keeps its exact old text."""
    ext, boxed = g9_sets(prog)
    explicit = bool(getattr(prog, "explicit", False))   # G4 A2: only a source-`pub` type is a `pub` Rust item
    out = []
    for d in (order if order is not None else make_type_table(prog).order):
        pv = "pub " if (not explicit or d.pub) else ""
        out.append("#[allow(dead_code, non_camel_case_types, non_snake_case%s)]" % (", private_interfaces" if explicit else ""))
        if d.name in ext:
            out.append("#[derive(Clone, Debug)]")
        else:
            out.append("#[derive(Clone, Copy, Debug, PartialEq, Eq)]")

        def fty(f, label):
            r = rty(f.type)
            return "::std::boxed::Box<%s>" % r if label in boxed else r
        if isinstance(d, StructDecl):
            if d.fields:
                body = ", ".join("%s%s: %s" % (pv, f.name, fty(f, "%s.%s" % (d.name, f.name))) for f in d.fields)
                out.append("%sstruct %s { %s }" % (pv, d.name, body))
            else:
                out.append("%sstruct %s {}" % (pv, d.name))
        else:
            vs = []
            for v in d.variants:
                if v.fields:
                    vs.append("%s(%s)" % (v.name, ", ".join(
                        fty(f, "%s::%s.%s" % (d.name, v.name, f.name)) for f in v.fields)))
                else:
                    vs.append(v.name)
            out.append("%senum %s { %s }" % (pv, d.name, ", ".join(vs)))
        out.append("")
    return "\n".join(out) + ("\n" if out else "")


def show(e):
    """readable source-like text of a contract expression (for panic messages)"""
    if isinstance(e, (IntLit, BoolLit)):
        return str(e.value).lower() if isinstance(e, BoolLit) else str(e.value)
    if isinstance(e, Var):
        return e.name
    if isinstance(e, Unary):
        return "%s%s" % (e.op, show(e.operand))
    if isinstance(e, Binary):
        return "(%s %s %s)" % (show(e.left), e.op, show(e.right))
    if isinstance(e, Index):
        return "%s[%s]" % (show(e.array), show(e.index))
    if isinstance(e, Call):
        return "%s(%s)" % (e.name, ", ".join(show(a) for a in e.args))
    if isinstance(e, Ctor):
        return e.name if e.arg is None else "%s(%s)" % (e.name, show(e.arg))
    if isinstance(e, Quant):
        return "%s %s in %s..%s: %s" % (e.kind, e.var, show(e.lo), show(e.hi), show(e.body))
    # G3: a specialized node carries the declaration name as written in `src_name` (its name is the generated stem)
    if isinstance(e, StructLit):
        sn = getattr(e, "src_name", e.name)
        if not e.fields:
            return "%s {}" % sn
        return "%s { %s }" % (sn, ", ".join("%s: %s" % (f.name, show(f.value)) for f in e.fields))
    if isinstance(e, EnumCtor):
        sn = getattr(e, "src_name", e.enum_name)
        if not e.args:
            return "%s::%s" % (sn, e.variant)
        return "%s::%s(%s)" % (sn, e.variant, ", ".join(show(a) for a in e.args))
    if isinstance(e, FieldAccess):
        return "%s.%s" % (show(e.base), e.field)
    if isinstance(e, IsVariant):
        return "is_variant(%s, %s::%s)" % (show(e.value), getattr(e, "src_name", e.enum_name), e.variant)
    if isinstance(e, VariantField):
        return "variant_field(%s, %s::%s, %s)" % (show(e.value), getattr(e, "src_name", e.enum_name), e.variant, e.field)
    if isinstance(e, StrLit):  # G2 B2
        return "<str>"
    return "?"


def match_sorted_requires(e):
    """Name of the array `a` if e is structurally
    `forall i in 0..len(a): forall j in i..len(a): a[i] <= a[j]` (inner start `i` or `i + 1`), else None."""
    def is_len(x, name=None):
        if isinstance(x, Call) and x.name == "len" and len(x.args) == 1 and isinstance(x.args[0], Var):
            return x.args[0].name if name is None else (x.args[0].name == name)
        return None
    if not (isinstance(e, Quant) and e.kind == "forall" and isinstance(e.lo, IntLit) and e.lo.value == 0):
        return None
    a = is_len(e.hi)
    if not a:
        return None
    q = e.body
    if not (isinstance(q, Quant) and q.kind == "forall") or q.var == e.var or a in (e.var, q.var):
        return None
    lo = q.lo
    if isinstance(lo, Binary) and lo.op == "+" and isinstance(lo.right, IntLit) and lo.right.value == 1:
        lo = lo.left
    if not (isinstance(lo, Var) and lo.name == e.var and is_len(q.hi, a)):
        return None
    b = q.body
    if not (isinstance(b, Binary) and b.op == "<=" and isinstance(b.left, Index) and isinstance(b.right, Index)):
        return None
    for ix, v in ((b.left, e.var), (b.right, q.var)):
        if not (isinstance(ix.array, Var) and ix.array.name == a and isinstance(ix.index, Var) and ix.index.name == v):
            return None
    return a


def rstr(text):
    """Rust string literal (ASCII-safe)"""
    out = []
    for ch in text:
        if ch in '\\"':
            out.append("\\" + ch)
        elif 32 <= ord(ch) < 127:
            out.append(ch)
        else:
            out.append("\\u{%x}" % ord(ch))
    return '"' + "".join(out) + '"'


class Gen:
    def __init__(s, prog, verified=True, trust_callers=False, budget=1 << 30, foreign_checks="requires"):
        s.budget = budget
        s.prog = prog
        s.verified = verified
        s.trust = trust_callers
        s.out = []
        s.has_req = {f.name for f in prog.functions if f.requires and f.foreign is None}
        # G4 A2 (explicit visibility mode, docs/G4_SPEC.md 4): only host entries are `pub`. Verified: just the entries
        # that have a requires get a checked wrapper (host boundary; none under trust_callers), every Pruv call goes to
        # the body. Safe mode (--no-verify): EVERY function with a requires has a checked wrapper and every Pruv call goes
        # through it; under trust_callers the entry's pub wrapper skips the checks and an extra private checked wrapper
        # `<entry>__pruv_chk` serves the Pruv callers.
        s.explicit = bool(getattr(prog, "explicit", False))
        s.entries = {f.name for f in prog.functions if f.host_entry}
        s.checks_needed = s.explicit and any(
            f.requires and f.foreign is None and (not verified or (f.host_entry and not trust_callers))
            for f in prog.functions)
        s.cp = None    # set during requires entry checks: user-type params already converted
        s.bound = []   # quantifier variables in scope (contract evaluation)
        s.tmp = 0
        s.table = make_type_table(prog)
        s.params = set()
        s.inouts = set()     # G5 A2: inout parameters of the function being generated (`&mut [T]` bindings)
        # G5 A2: the inout code paths only run for a program that uses inout (unchecked program: assume it may)
        s.g5 = getattr(prog, "uses_inout", None) is not False
        # G5 A2 (legacy mode): a function with an inout parameter has an always-checked private wrapper, also under
        # trust_callers, so its contract prelude is needed there too
        s.inout_req = s.g5 and (not s.explicit) and any(
            f.requires and f.foreign is None and any(p.mode == "inout" for p in f.params) for f in prog.functions)
        s.vt = {}
        s.borrowed = set()
        # G9 A2 (docs/G9_SPEC.md 6, 12): `ext` = extended declarations (Clone, never Copy), `boxed` = field labels that
        # are Box edges, `refs` = names bound to a Rust reference (extended parameters, match payload views, buffer
        # payload views), `need_size` / `need_eq` = types whose runtime contract helpers are needed (filled while the
        # requires checks are generated, closed over field types by g9_helper_texts). All empty for a non-G9 program.
        s.g9 = getattr(prog, "g9", None) is not None
        s.ext, s.boxed = g9_sets(prog)
        s.refs = set()
        s.need_size = set()
        s.need_eq = set()
        # G6 (section 12): only a program that uses G6 gets any of the following
        from foreign import first_g6_use, uses_files
        s.g10 = uses_files(prog)
        s.g6 = first_g6_use(prog) is not None
        s.fmode = foreign_checks
        s.allow = ALLOW_G6 if s.g6 else ALLOW
        s.fmap = {}
        for f in prog.functions:
            s.fmap.setdefault(f.name, f)
        s.fg = None
        if s.g6:
            from foreign_codegen import ForeignGen
            s.fg = ForeignGen(s)

    def emit(s, ind, line):
        s.out.append("    " * ind + line)

    def field_uses(s, name):
        """G9: some struct field / enum payload has the internal type `name` (array_u8, array_bool, str). The G2
        helpers are emitted by usage; uses_array_type / uses_str look at parameters, results and lets only."""
        for d in s.prog.types:
            fields = d.fields if isinstance(d, StructDecl) else [f for v in d.variants for f in v.fields]
            if any(f.type.name == name for f in fields):
                return True
        return False

    def prelude(s):
        if s.g10:
            s.out.append(FILE_PRELUDE)
        types = emit_public_types(s.prog, s.table.order if s.g9 else None)
        if types:
            s.out.append(types)
        u8_used = uses_array_type(s.prog, "array_u8") or s.g10
        bool_used = uses_array_type(s.prog, "array_bool")  # G2 A5
        str_used = uses_str(s.prog)  # G2 B2
        if s.g9:
            u8_used = u8_used or s.field_uses("array_u8")
            bool_used = bool_used or s.field_uses("array_bool")
            str_used = str_used or s.field_uses("str")
        if s.g6 and not str_used:   # G6: a String parameter can be indexed in a runtime requires (pruv_cidx_str)
            str_used = uses_array_type(s.prog, "string")
        if str_used:
            s.out.append(STR_PRELUDE)
        if not s.verified:
            s.out.append(SAFE_PRELUDE)
            if u8_used:
                s.out.append(SAFE_PRELUDE_U8)
            if bool_used:
                s.out.append(SAFE_PRELUDE_BOOL)
            if str_used:
                s.out.append(SAFE_PRELUDE_STR)
        if (s.checks_needed if s.explicit else (s.has_req and (not s.trust or s.inout_req))) or s.g6:
            s.out.append(CONTRACT_PRELUDE_G6 if s.g6 else CONTRACT_PRELUDE)
            if u8_used:
                s.out.append(CONTRACT_PRELUDE_U8)
            if bool_used:
                s.out.append(CONTRACT_PRELUDE_BOOL)
            if str_used:
                s.out.append(CONTRACT_PRELUDE_STR)
            ctypes = s.contract_types()
            if ctypes:
                s.out.append(ctypes)
            if s.g6:
                s.out.append(G6_PRELUDE)

    def contract_types(s):
        """pruv_contract__Name mirror types and pruv_to_c__Name converters (only for requires evaluation)"""
        attrs = "#[allow(dead_code, non_camel_case_types, non_snake_case, unused_variables)]"
        out = []
        for d in s.table.order:
            if d.name in s.ext:
                continue    # G9: extended values have no i128 mirror; contracts read them through references (cx)
            cn = "pruv_contract__" + d.name
            out.append(attrs)
            out.append("#[derive(Clone, Copy, PartialEq, Eq)]")
            if isinstance(d, StructDecl):
                out.append("struct %s { %s }" % (cn, ", ".join("%s: %s" % (f.name, cty(f.type)) for f in d.fields)))
                out.append(attrs)
                out.append("#[inline]")
                init = ", ".join("%s: %s" % (f.name, conv(f.type, "v." + f.name)) for f in d.fields)
                out.append("fn pruv_to_c__%s(v: %s) -> %s { %s { %s } }" % (d.name, d.name, cn, cn, init))
            else:
                vs, arms = [], []
                for v in d.variants:
                    if v.fields:
                        vs.append("%s(%s)" % (v.name, ", ".join(cty(f.type) for f in v.fields)))
                        names = ["pruv_a%d" % i for i in range(len(v.fields))]
                        args = ", ".join(conv(f.type, n) for f, n in zip(v.fields, names))
                        arms.append("%s::%s(%s) => %s::%s(%s)," % (d.name, v.name, ", ".join(names), cn, v.name, args))
                    else:
                        vs.append(v.name)
                        arms.append("%s::%s => %s::%s," % (d.name, v.name, cn, v.name))
                out.append("enum %s { %s }" % (cn, ", ".join(vs)))
                out.append(attrs)
                out.append("#[inline]")
                out.append("fn pruv_to_c__%s(v: %s) -> %s { match v { %s } }" % (d.name, d.name, cn, " ".join(arms)))
        return "\n".join(out) + ("\n" if out else "")

    def is_ext(s, t):
        """t is an extended user type (G9): recursive, or holding a buffer or an extended type"""
        return bool(s.ext) and t is not None and t.owner is None and not t.args and t.name in s.ext

    def rt(s, t, param=False):
        """rty, except that an extended parameter is a shared reference `&Name` (read view)"""
        if param and s.is_ext(t):
            return "&" + t.name
        return rty(t, param)

    def private(s, f):
        """G3 specializations, G6 collection-bearing functions and (G9) functions with an extended type in their
        signature are private Rust items (no raw ABI); this includes their checked entry wrappers"""
        return (getattr(f, "private", False) or any(is_collection(p.type) for p in f.params) or is_collection(f.ret)
                or any(s.is_ext(p.type) for p in f.params) or s.is_ext(f.ret)
                or (s.g5 and any(p.mode == "inout" for p in f.params)))   # G5: no public API for a mutable borrow

    def fn(s, f):
        if f.foreign is not None:
            return   # G6: a trusted rust fn has no body; its boundary helper is emitted on first use
        s.params = {p.name for p in f.params}
        if s.g5:
            s.inouts = {p.name for p in f.params if p.mode == "inout"}
        s.vt = {p.name: p.type for p in f.params}
        s.borrowed = {p.name for p in f.params if is_collection(p.type) and not p.take}
        s.refs = {p.name for p in f.params if s.is_ext(p.type)}
        if s.inouts:
            ps = ", ".join("%s: %s" % (p.name, "&mut " + rty(p.type, True)[1:] if p.mode == "inout"
                                       else s.rt(p.type, not p.take)) for p in f.params)
        else:
            ps = ", ".join("%s: %s" % (p.name, s.rt(p.type, not p.take)) for p in f.params)
        ret = "" if f.ret == UNIT else " -> " + rty(f.ret)
        body_name = f.name + "__pruv_body" if f.requires else f.name
        if s.explicit:
            vis = "pub " if (f.host_entry and not f.requires) else ""
        else:
            vis = "" if (f.requires or s.private(f)) else "pub "   # G3: specializations are private
        s.emit(0, s.allow)
        s.emit(0, "%sfn %s(%s)%s {" % (vis, body_name, ps, ret))
        s.block(f.body, 1)
        s.emit(0, "}")
        s.emit(0, "")
        if f.requires:
            if not s.explicit:
                # G5: a wrapper of an inout function always checks (trust_callers does not waive it)
                s.entry(f, ps, ret, body_name, checked=True if s.inouts else None)
            elif s.verified:
                if f.host_entry:     # the checked host wrapper; no other function has a wrapper in verified mode
                    s.entry(f, ps, ret, body_name, f.name, True, not s.trust)
            elif f.host_entry:
                s.entry(f, ps, ret, body_name, f.name, True, not s.trust)
                if s.trust:          # Pruv callers of the entry keep the safe-mode check
                    s.entry(f, ps, ret, body_name, f.name + "__pruv_chk", False, True)
            else:
                s.entry(f, ps, ret, body_name, f.name, False, True)

    def callee(s, n):
        """explicit mode: the Rust name a Pruv call of the function n invokes (see Gen.__init__)"""
        if n not in s.has_req:
            return n
        if s.verified:
            return n + "__pruv_body"     # the caller proved requires
        return n + "__pruv_chk" if (s.trust and n in s.entries) else n

    def entry(s, f, ps, ret, body_name, name=None, pub=None, checked=None):
        """the checked wrapper of f. Legacy: `pub` unless private, checks unless trust_callers. Explicit mode passes the
        wrapper name, its visibility and whether it checks."""
        name = f.name if name is None else name
        pub = (not s.private(f)) if pub is None else pub
        checked = (not s.trust) if checked is None else checked
        s.emit(0, s.allow)
        s.emit(0, "#[inline]")
        s.emit(0, "%sfn %s(%s)%s {" % ("pub " if pub else "", name, ps, ret))
        if checked:
            s.cp = {}   # user-type parameter -> its type, converted once below
            checks = []
            try:
                for n, r in enumerate(f.requires, 1):
                    msg = "pruv: requires violated: %s: %s" % (getattr(f, "disp", f.name), show(r))
                    code = s.c(r)
                    checks.append("if !(%s) { panic!(\"{}\", %s); }" % (code, rstr(msg)))
                used = dict(s.cp)
            finally:
                s.cp = None
            for p in f.params:
                if p.name in used:
                    s.emit(1, "let pruv_cp_%s: %s = %s;" % (p.name, cty(used[p.name]), conv(used[p.name], p.name)))
            if checks:
                s.emit(1, "let mut pruv_budget: i64 = %s;" % format(s.budget, "_"))
            for line in checks:
                s.emit(1, line)
        if s.inouts:
            s.emit(1, "%s(%s)" % (body_name, ", ".join(("&mut *" + p.name) if p.mode == "inout" else p.name
                                                        for p in f.params)))
        else:
            s.emit(1, "%s(%s)" % (body_name, ", ".join(p.name for p in f.params)))
        s.emit(0, "}")
        s.emit(0, "")

    # ---------- contract evaluation (requires), i128 ----------
    def carr(s, e):
        if isinstance(e, Var):
            return e.name
        if isinstance(e, StrLit):  # G2 B2: &'static str
            return str_lit(e.value)
        if s.g9 and isinstance(e, (FieldAccess, VariantField)):   # G9: a buffer field of a real (extended) value
            return s.cx(e)
        raise Exception("codegen: unsupported array expression in contract: %r" % e)

    # ---------- G9: contract operands over REAL values ----------
    def g9_unsupported(s, e, what):
        return PruvError("codegen", e.line, e.col, "unsupported_type",
                         "%s is not supported in a runtime requires by the Rust backend yet" % what,
                         "compare tags with is_variant and fields with variant_field, or move the check into the body")

    def cx(s, e):
        """Rust expression of type `&R(T)` for a contract operand of nominal or buffer type, evaluated on the REAL
        parameter values (extended values have no i128 mirror, so nothing is converted eagerly and an inactive variant
        or a skipped operand is never inspected). Supported: a parameter, a field path, variant_field (a partial
        selector: `pruv_ud` when the variant is not active) and nullary constructors of a unit variant / empty struct."""
        if isinstance(e, Var):
            if e.name in s.bound or e.name not in s.params:
                raise s.g9_unsupported(e, "the variable %s as an aggregate operand" % e.name)
            return e.name if s.is_ext(e.ty) else "(&%s)" % e.name
        if isinstance(e, FieldAccess):
            deref = "*" if s.field_boxed(e.base.ty, e.field) else ""
            return "(&%s(%s).%s)" % (deref, s.cx(e.base), e.field)
        if isinstance(e, VariantField):
            if s.g9_owned(e.value):
                # the selected value is a fresh constructor (or a part of one): select from the OWNED temporary and
                # borrow the moved-out field, so no reference into a block-local temporary escapes its block
                return "(&%s)" % s.g9_owned_expr(e)
            s.tmp += 1
            tmp = "pruv_e%d" % s.tmp
            ety = Type(e.enum_name)
            vf = s.table.variant(ety, e.variant)
            idx = s.table.field_index(ety, e.field, e.variant)
            pats = ", ".join("pruv_f" if i == idx else "_" for i in range(len(vf.fields)))
            msg = "variant_field expected %s::%s.%s" % (getattr(e, "src_name", e.enum_name), e.variant, e.field)
            return ("({ let %s: &%s = %s; match %s { %s::%s(%s) => { let pruv_r: &%s = pruv_f; pruv_r } _ => pruv_ud(%s) } })" % (
                tmp, e.enum_name, s.cx(e.value), tmp, e.enum_name, e.variant, pats, rty(vf.fields[idx].type), rstr(msg)))
        if isinstance(e, (EnumCtor, StructLit)):
            # a constructor (with or without payload) is a REAL temporary value of the type; a reference to it lives
            # through the enclosing statement. Contract integers are i128: every i64 field is converted with a checked
            # conversion (pruv_ud when out of range).
            return "(&%s)" % s.g9_real(e)
        raise s.g9_unsupported(e, "this expression as an aggregate operand")

    @staticmethod
    def g9_owned(e):
        """e denotes a fresh constructor value, or a field / variant_field part of one"""
        if isinstance(e, (EnumCtor, StructLit)):
            return True
        if isinstance(e, VariantField):
            return Gen.g9_owned(e.value)
        if isinstance(e, FieldAccess):
            return Gen.g9_owned(e.base)
        return False

    def g9_owned_expr(s, e):
        """OWNED Rust value of e (g9_owned(e)): a constructor is built (g9_real); a part is moved out of the owned
        value of its base (a Box edge is unboxed)"""
        if isinstance(e, (EnumCtor, StructLit)):
            return s.g9_real(e)
        if isinstance(e, FieldAccess):
            deref = "*" if s.field_boxed(e.base.ty, e.field) else ""
            return "(%s(%s).%s)" % (deref, s.g9_owned_expr(e.base), e.field)
        ety = Type(e.enum_name)
        vf = s.table.variant(ety, e.variant)
        idx = s.table.field_index(ety, e.field, e.variant)
        pats = ", ".join("pruv_f" if i == idx else "_" for i in range(len(vf.fields)))
        boxed = ("%s::%s.%s" % (e.enum_name, e.variant, e.field)) in s.boxed
        msg = "variant_field expected %s::%s.%s" % (getattr(e, "src_name", e.enum_name), e.variant, e.field)
        return "(match %s { %s::%s(%s) => %s, _ => pruv_ud(%s) })" % (
            s.g9_owned_expr(e.value), e.enum_name, e.variant, pats, "*pruv_f" if boxed else "pruv_f", rstr(msg))

    @staticmethod
    def g9_charge(n):
        """charge the shared contract budget n units (n: a Rust usize expression) before a buffer copy"""
        return ("{ let pruv_n: usize = %s; pruv_budget = pruv_budget.saturating_sub(i64::try_from(pruv_n).unwrap_or(i64::MAX)); "
                "if pruv_budget < 0 { pruv_ud(\"contract iteration budget exceeded\") } }" % n)

    def g9_field_real(s, x, ty, label):
        """a constructor field of declared type ty: the real value, boxed on a recursive edge"""
        v = s.g9_real(x, ty)
        return "::std::boxed::Box::new(%s)" % v if label in s.boxed else v

    def g9_real(s, e, ty=None):
        """Rust expression of the REAL (executed representation) OWNED value of the contract expression e (declared type
        ty, default e.ty). Constructors are built field by field in declaration order; i64 values come from the i128
        contract value through a checked conversion; named values and field paths are cloned from their reference."""
        if isinstance(e, StructLit):
            inits = {f.name: f.value for f in e.fields}
            fs = s.table.fields(Type(e.name))
            if not fs:
                return "%s {}" % e.name
            return "%s { %s }" % (e.name, ", ".join(
                "%s: %s" % (f.name, s.g9_field_real(inits[f.name], f.type, "%s.%s" % (e.name, f.name))) for f in fs))
        if isinstance(e, EnumCtor):
            ctor = "%s::%s" % (e.enum_name, e.variant)
            if not e.args:
                return ctor
            vf = s.table.variant(Type(e.enum_name), e.variant).fields
            return "%s(%s)" % (ctor, ", ".join(
                s.g9_field_real(a, fd.type, "%s::%s.%s" % (e.enum_name, e.variant, fd.name)) for a, fd in zip(e.args, vf)))
        t = ty if ty is not None else e.ty
        if isinstance(e, Ctor):
            px = t.args[0] if t is not None and t.args else I64
            rx = rty(px)
            if e.name == "None":
                return "None::<%s>" % rx
            if e.name == "Some":
                return "Some::<%s>(%s)" % (rx, s.g9_real(e.arg, px))
            return "%s::<%s, i64>(%s)" % (e.name, rx, s.g9_real(e.arg, px if e.name == "Ok" else I64))
        if t is None or (t.owner is None and t.name == "i64"):
            return "i64::try_from(%s).unwrap_or_else(|_| pruv_ud(\"constructor field out of i64 range\"))" % s.c(e)
        if t.owner is None and t.name == "bool":
            return s.c(e)
        if isinstance(e, (Var, FieldAccess, VariantField)) and (is_user_type(t) or t.name in ("option", "result")):
            if is_user_type(t) and not t.args and s.table.holds_buffer(t.name):
                raise s.g9_unsupported(e, "a copy of a value holding an array or str")
            # a copy of a named value / part is charged first: its weight (one unit per nominal node)
            w = s.g9_weight(t, "pruv_c", "&mut pruv_budget")
            if w == "0i128":
                return "::std::clone::Clone::clone(%s)" % s.cx(e)
            if nominals_in(t):
                s.need_size.update(nominals_in(t))
            return "({ let pruv_c: &%s = %s; let _ = %s; ::std::clone::Clone::clone(pruv_c) })" % (rty(t), s.cx(e), w)
        if is_array(t):
            # the buffer expression is evaluated once: bound, charged by its length, then copied
            return "({ let pruv_b: &[_] = %s; %s pruv_b.to_vec() })" % (s.carr(e), s.g9_charge("pruv_b.len()"))
        if t == STR:
            return "({ let pruv_b: &str = %s; %s pruv_b.to_owned() })" % (s.carr(e), s.g9_charge("pruv_b.len()"))
        raise s.g9_unsupported(e, "this expression as a constructor field of an aggregate operand")

    def g9_real_path(s, e):
        """e reads a part of a REAL (extended) value through references (cx): a variant_field of an extended value, or
        a field path below one"""
        if isinstance(e, VariantField):
            return s.is_ext(e.value.ty) or s.g9_real_path(e.value)
        if isinstance(e, FieldAccess):
            return s.is_ext(e.base.ty) or s.g9_real_path(e.base)
        return False

    def g9_metered(s, ty, ref):
        """contract value of type ty from `ref` (a Rust expression of type `&R(ty)`). A value holding nominal parts is
        converted whole, so the conversion is charged to the shared budget first: one unit per nominal node visited
        (the size helper ticks once per node)."""
        if not nominals_in(ty):
            return conv(ty, "(*%s)" % ref)
        s.need_size.update(nominals_in(ty))
        return "({ let pruv_m: &%s = %s; let _ = %s; %s })" % (
            rty(ty), ref, s.g9_weight(ty, "pruv_m", "&mut pruv_budget"), conv(ty, "(*pruv_m)"))

    def path_boxed(s, root, fields):
        """the LAST field of the assignment path root.f1.f2... is a Box edge (follows the declared field types)"""
        cur = s.vt.get(root)
        boxed = False
        for fname in fields:
            if cur is None or cur.owner is not None or cur.name not in s.table.decls:
                return False
            decl = s.table.decls[cur.name]
            if not isinstance(decl, StructDecl):
                return False
            boxed = ("%s.%s" % (cur.name, fname)) in s.boxed
            nxt = None
            for fd in decl.fields:
                if fd.name == fname:
                    nxt = fd.type
            cur = nxt
        return boxed

    def field_boxed(s, base_ty, field):
        """the field `field` of the struct type base_ty is a Box edge"""
        return bool(s.boxed) and base_ty is not None and ("%s.%s" % (base_ty.name, field)) in s.boxed

    def c(s, e):
        if isinstance(e, StrLit):  # G2 B2
            return str_lit(e.value)
        if isinstance(e, IntLit):
            return "(%di128)" % e.value if e.value < 0 else "%di128" % e.value
        if isinstance(e, BoolLit):
            return "true" if e.value else "false"
        if isinstance(e, Var):
            if e.name in s.bound:
                return e.name
            t = e.ty.name if e.ty is not None else "i64"
            if s.is_ext(e.ty):    # G9: an extended value is only an operand of size / == / is_variant / field access
                raise s.g9_unsupported(e, "the extended value %s as a plain operand" % e.name)
            if s.cp is not None and e.ty is not None and is_user_type(e.ty) and e.name in s.params:
                s.cp[e.name] = e.ty
                return "pruv_cp_" + e.name
            if t in ("i64", "option", "result") or is_user_type(e.ty):
                return conv(e.ty if e.ty is not None else I64, e.name)
            return e.name
        if isinstance(e, Unary):
            if e.op == "!":
                return "(!%s)" % s.c(e.operand)
            return "pruv_cneg(%s)" % s.c(e.operand)
        if isinstance(e, Binary):
            op = e.op
            if op in ("==", "!=") and s.is_ext(e.left.ty):
                # G9: structural equality of buffer-free extended aggregates, visited lazily on the real values; every
                # visited node pair costs one budget unit; only the active variant's fields are compared
                s.need_eq.add(e.left.ty.name)
                code = "pruv_ceq__%s(%s, %s, &mut pruv_budget)" % (e.left.ty.name, s.cx(e.left), s.cx(e.right))
                return code if op == "==" else "(!%s)" % code
            if op == "==>":
                return "(!%s || %s)" % (s.c(e.left), s.c(e.right))
            if op in CONTRACT_ARITH:
                return "%s(%s, %s)" % (CONTRACT_ARITH[op], s.c(e.left), s.c(e.right))
            return "(%s %s %s)" % (s.c(e.left), op, s.c(e.right))
        if isinstance(e, Index):
            if e.array.ty is not None and e.array.ty.owner is None and e.array.ty.name == "vec":   # G6: checked read
                a = s.carr(e.array)
                return ("({ let pruv_i: i128 = %s; if pruv_i >= 0 && pruv_i < (%s.len() as i128) { "
                        "let pruv_x: %s = %s[pruv_i as usize]; %s } else { pruv_ud(\"vector index out of range\") } })") % (
                            s.c(e.index), a, rty(e.ty), a, conv(e.ty, "pruv_x"))
            if e.array.ty is not None and e.array.ty.owner is None and e.array.ty.name == "string":   # G6
                return "pruv_cidx_str(&%s, %s)" % (s.carr(e.array), s.c(e.index))
            if is_str(e.array.ty):  # G2 B2
                return "pruv_cidx_str(%s, %s)" % (s.carr(e.array), s.c(e.index))
            if is_bool_array(e.array.ty):  # G2 A5
                return "pruv_cidx_bool(%s, %s)" % (s.carr(e.array), s.c(e.index))
            if is_u8_array(e.array.ty):
                return "pruv_cidx_u8(%s, %s)" % (s.carr(e.array), s.c(e.index))
            return "pruv_cidx(%s, %s)" % (s.carr(e.array), s.c(e.index))
        if isinstance(e, Ctor):
            if e.ty is not None and e.ty.args:   # G3: Option<X> / Result<X>, X != i64
                cx = cty(e.ty.args[0])
                if e.name == "None":
                    return "None::<%s>" % cx
                if e.name == "Some":
                    return "Some::<%s>(%s)" % (cx, s.c(e.arg))
                return "%s::<%s, i128>(%s)" % (e.name, cx, s.c(e.arg))
            if e.name == "None":
                return "None::<i128>"
            ctor = {"Some": "Some", "Ok": "Ok::<i128, i128>", "Err": "Err::<i128, i128>"}[e.name]
            return "%s(%s)" % (ctor, s.c(e.arg))
        if isinstance(e, Quant):
            return s.cquant(e)
        if isinstance(e, StructLit):
            # evaluated in declaration order (Rust evaluates literal fields in written order)
            inits = {f.name: f.value for f in e.fields}
            fs = s.table.fields(Type(e.name))
            body = ", ".join("%s: %s" % (f.name, s.c(inits[f.name])) for f in fs)
            return "(pruv_contract__%s { %s })" % (e.name, body) if fs else "(pruv_contract__%s {})" % e.name
        if isinstance(e, EnumCtor):
            ctor = "pruv_contract__%s::%s" % (e.enum_name, e.variant)
            if not e.args:
                return ctor
            return "%s(%s)" % (ctor, ", ".join(s.c(a) for a in e.args))
        if isinstance(e, FieldAccess):
            if s.is_ext(e.base.ty) or s.g9_real_path(e.base):
                # G9: a field of a real value (extended struct, or a part of one) is read from the original reference;
                # only the field itself is converted (a nominal field is converted whole and charged to the budget)
                if s.is_ext(e.ty) or is_array(e.ty) or e.ty == STR:
                    raise s.g9_unsupported(e, "the aggregate field %s as a plain operand" % e.field)
                if nominals_in(e.ty):
                    return s.g9_metered(e.ty, s.cx(e))
                return conv(e.ty, "(%s).%s" % (s.cx(e.base), e.field))
            return "%s.%s" % (s.c(e.base), e.field)
        if isinstance(e, IsVariant):
            if s.is_ext(e.value.ty) or s.g9_real_path(e.value):
                return "matches!(%s, %s::%s { .. })" % (s.cx(e.value), e.enum_name, e.variant)
            return "matches!(%s, pruv_contract__%s::%s { .. })" % (s.c(e.value), e.enum_name, e.variant)
        if isinstance(e, VariantField) and (s.is_ext(e.value.ty) or s.g9_real_path(e.value)):
            if s.is_ext(e.ty) or is_array(e.ty) or e.ty == STR:
                raise s.g9_unsupported(e, "the aggregate field %s as a plain operand" % e.field)
            s.tmp += 1
            tmp = "pruv_e%d" % s.tmp
            ety = Type(e.enum_name)
            vf = s.table.variant(ety, e.variant)
            idx = s.table.field_index(ety, e.field, e.variant)
            pats = ", ".join("pruv_f" if i == idx else "_" for i in range(len(vf.fields)))
            msg = "variant_field expected %s::%s.%s" % (getattr(e, "src_name", e.enum_name), e.variant, e.field)
            return "({ let %s: &%s = %s; match %s { %s::%s(%s) => %s, _ => pruv_ud(%s) } })" % (
                tmp, e.enum_name, s.cx(e.value), tmp, e.enum_name, e.variant, pats, s.g9_metered(e.ty, "pruv_f"), rstr(msg))
        if isinstance(e, VariantField):
            s.tmp += 1
            tmp = "pruv_e%d" % s.tmp
            cn = "pruv_contract__%s" % e.enum_name
            vf = s.table.variant(Type(e.enum_name), e.variant)
            idx = s.table.field_index(Type(e.enum_name), e.field, e.variant)
            pats = ", ".join("pruv_f" if i == idx else "_" for i in range(len(vf.fields)))
            msg = "variant_field expected %s::%s.%s" % (
                getattr(e, "src_name", e.enum_name) if s.explicit else e.enum_name, e.variant, e.field)   # G4: source-qualified
            return "({ let %s: %s = %s; match %s { %s::%s(%s) => pruv_f, _ => pruv_ud(%s) } })" % (
                tmp, cn, s.c(e.value), tmp, cn, e.variant, pats, rstr(msg))
        if isinstance(e, Call):
            n, a = e.name, e.args
            if n == "len":
                return "(%s.len() as i128)" % s.carr(a[0])
            if n == "size":   # also for a program without other G9 features (size of a plain acyclic struct / enum)
                # G9: structural size on the real value, checked i128 additions, one budget unit per node visited
                s.need_size.add(a[0].ty.name)
                return "pruv_csize__%s(%s, &mut pruv_budget)" % (a[0].ty.name, s.cx(a[0]))
            if n in ("file_ok", "file_readable", "file_writable"):
                return "(%s).%s" % (s.c(a[0]), n[5:])
            if n == "file_size":
                return "((%s).buf.len() as i128)" % s.c(a[0])
            if n == "file_byte":
                return "pruv_cidx_u8(&(%s).buf, %s)" % (s.c(a[0]), s.c(a[1]))
            if n == "map_lookup":   # G6: finite-map lookup, Option mirror of the stored value
                kt, vt = a[0].ty.args[0], a[0].ty.args[1]
                key = s.c(a[1])
                if kt == I64:
                    look = "i64::try_from(%s).ok().and_then(|pruv_k| %s.get(&pruv_k).copied())" % (key, s.carr(a[0]))
                else:
                    look = "%s.get(&%s).copied()" % (s.carr(a[0]), key)
                return "(%s)" % conv(mk_option(vt), "(%s)" % look)
            if n == "map_updated":   # G6: generated scan helper; shares the entry's iteration budget
                kt, vt = a[0].ty.args[0], a[0].ty.args[1]
                helper = s.fg.map_updated_helper(kt, vt, e.inst["src_args"] if e.inst else (kt, vt))
                return "%s(&%s, &%s, %s, %s, &mut pruv_budget)" % (helper, s.carr(a[0]), s.carr(a[1]),
                                                                  s.c(a[2]), s.c(a[3]))
            if n == "is_char_boundary":  # G2 B2
                return "pruv_cboundary(%s, %s)" % (s.carr(a[0]), s.c(a[1]))
            if n == "is_some":
                return "%s.is_some()" % s.c(a[0])
            if n == "some_val":
                return '%s.unwrap_or_else(|| pruv_ud("some_val of None"))' % s.c(a[0])
            if n == "is_ok":
                return "%s.is_ok()" % s.c(a[0])
            if n == "ok_val":
                return '%s.ok().unwrap_or_else(|| pruv_ud("ok_val of Err"))' % s.c(a[0])
            if n == "err_val":
                return '%s.err().unwrap_or_else(|| pruv_ud("err_val of Ok"))' % s.c(a[0])
        raise Exception("codegen: unsupported expression in requires: %r" % e)

    def cquant(s, e):
        arr = match_sorted_requires(e)
        if arr is not None and is_str(e.hi.args[0].ty):  # G2 B2: no sorted fast path for str
            arr = None
        if arr is not None:
            # O(n) equivalent (docs/M0_CONTRACTS.md C): forall pruv_sk in 1..len(a): a[pruv_sk-1] <= a[pruv_sk]
            L = dict(line=e.line, col=e.col)
            kv = Var(name="pruv_sk", **L)
            aty = e.hi.args[0].ty            # type of the original array variable
            ity = e.body.body.left.ty        # type of the original a[i] node
            e = Quant(kind="forall", var="pruv_sk", lo=IntLit(value=1, **L), hi=e.hi,
                      body=Binary(op="<=", left=Index(array=Var(name=arr, ty=aty, **L),
                                                       index=Binary(op="-", left=kv, right=IntLit(value=1, **L), **L),
                                                       ty=ity, **L),
                                  right=Index(array=Var(name=arr, ty=aty, **L), index=kv, ty=ity, **L), **L), **L)
        s.tmp += 1
        n = s.tmp
        lo, hi = s.c(e.lo), s.c(e.hi)   # bounds see only the outer scope
        s.bound.append(e.var)
        body = s.c(e.body)
        s.bound.pop()
        k, r, h = "pruv_k%d" % n, "pruv_r%d" % n, "pruv_hi%d" % n
        head = "{ let pruv_lo%d: i128 = %s; let %s: i128 = %s; let mut %s: i128 = pruv_lo%d; " % (n, lo, h, hi, k, n)
        loop = ("while %s < %s { pruv_budget -= 1; if pruv_budget < 0 { pruv_ud(\"contract iteration budget exceeded\"); } "
                "let %s: i128 = %s; ") % (k, h, e.var, k)
        tail = "%s += 1; } " % k
        kind = e.kind
        if kind == "forall":
            return head + "let mut %s = true; " % r + loop + "if !(%s) { %s = false; break; } " % (body, r) + tail + r + " }"
        if kind == "exists":
            return head + "let mut %s = false; " % r + loop + "if %s { %s = true; break; } " % (body, r) + tail + r + " }"
        if kind == "sum":
            return head + "let mut %s: i128 = 0; " % r + loop + "%s = pruv_cadd(%s, %s); " % (r, r, body) + tail + r + " }"
        if kind == "count":
            return head + "let mut %s: i128 = 0; " % r + loop + "if %s { %s += 1; } " % (body, r) + tail + r + " }"
        # max / min
        cmp = ">" if kind == "max" else "<"
        return (head + "let mut %s: ::std::option::Option<i128> = None; " % r + loop + "let pruv_v: i128 = %s; " % body +
                "%s = Some(match %s { None => pruv_v, Some(pruv_a) => if pruv_v %s pruv_a { pruv_v } else { pruv_a } }); " % (r, r, cmp) +
                tail + '%s.unwrap_or_else(|| pruv_ud("%s over an empty range")) }' % (r, kind))

    # ---------- G9: generated contract helpers (size, structural equality) ----------
    @staticmethod
    def decl_fields(d):
        return d.fields if isinstance(d, StructDecl) else [f for v in d.variants for f in v.fields]

    def g9_weight(s, t, x, bud="pruv_budget"):
        """Rust i128 expression for weight(value) (G9_SPEC 3); x names a variable of type `&R(t)`; bud is the budget
        argument expression (`pruv_budget` inside a helper, where it is a `&mut i64`).
        Scalars, arrays and str weigh 0; a nominal value weighs its size; Some / Ok weigh their payload; None / Err 0."""
        if t.owner is None and t.args and t.name in ("option", "result"):
            inner = s.g9_weight(t.args[0], "pruv_w", bud)
            if inner == "0i128":
                return "0i128"
            if t.name == "option":
                return ("match %s { ::std::option::Option::Some(pruv_w) => %s, ::std::option::Option::None => 0i128 }"
                        % (x, inner))
            return ("match %s { ::std::result::Result::Ok(pruv_w) => %s, ::std::result::Result::Err(_) => 0i128 }"
                    % (x, inner))
        if is_user_type(t):
            return "pruv_csize__%s(%s, %s)" % (t.name, x, bud)
        return "0i128"

    def g9_walks(s, t):
        """equality has to walk into t (a nominal value, or Option / Result of one)"""
        if t.owner is None and t.args and t.name in ("option", "result"):
            return s.g9_walks(t.args[0])
        return is_user_type(t)

    def g9_eq(s, t, x, y):
        """Rust bool expression: structural equality of the values behind the references x and y (type `&R(t)`)"""
        if t.owner is None and t.args and t.name in ("option", "result") and s.g9_walks(t.args[0]):
            inner = s.g9_eq(t.args[0], "pruv_p", "pruv_q")
            if t.name == "option":
                return ("(match (%s, %s) { (::std::option::Option::Some(pruv_p), ::std::option::Option::Some(pruv_q)) => %s, "
                        "(::std::option::Option::None, ::std::option::Option::None) => true, _ => false })" % (x, y, inner))
            return ("(match (%s, %s) { (::std::result::Result::Ok(pruv_p), ::std::result::Result::Ok(pruv_q)) => %s, "
                    "(::std::result::Result::Err(pruv_p), ::std::result::Result::Err(pruv_q)) => (*pruv_p == *pruv_q), "
                    "_ => false })" % (x, y, inner))
        if is_user_type(t):
            return "pruv_ceq__%s(%s, %s, pruv_budget)" % (t.name, x, y)
        return "(*%s == *%s)" % (x, y)

    def g9_size_text(s, d):
        """pruv_csize__Name: 1 + sum of the weights of the ACTIVE fields, one budget unit per call (= per node)"""
        n = d.name
        lines = [G9_HELPER_ALLOW, "fn pruv_csize__%s(v: &%s, pruv_budget: &mut i64) -> i128 {" % (n, n),
                 "    pruv_g9_tick(pruv_budget);"]

        def unit(fields):
            binds, ws = [], []
            for i, f in enumerate(fields):
                w = s.g9_weight(f.type, "pruv_a%d" % i)
                if w == "0i128":
                    binds.append("_")
                else:
                    binds.append("pruv_a%d" % i)
                    ws.append(w)
            return binds, ws

        def stmts(ws):
            """sequential accumulator statements (linear text, no nested pruv_cadd(pruv_cadd(..)..) chain)"""
            return ["let mut pruv_s: i128 = 1i128;"] + ["pruv_s = pruv_cadd(pruv_s, %s);" % w for w in ws]

        def fold(ws):
            if len(ws) == 0:
                return "1i128"
            if len(ws) == 1:
                return "pruv_cadd(1i128, %s)" % ws[0]
            return "{ %s pruv_s }" % " ".join(stmts(ws))
        if isinstance(d, StructDecl):
            binds, ws = unit(d.fields)
            if d.fields:
                lines.append("    let %s { %s } = v;" % (n, ", ".join("%s: %s" % (f.name, b) for f, b in zip(d.fields, binds))))
            if len(ws) >= 2:
                lines.extend("    " + x for x in stmts(ws))
                lines.append("    pruv_s")
            else:
                lines.append("    " + fold(ws))
        else:
            lines.append("    match v {")
            for v in d.variants:
                if not v.fields:
                    lines.append("        %s::%s => 1i128," % (n, v.name))
                    continue
                binds, ws = unit(v.fields)
                lines.append("        %s::%s(%s) => %s," % (n, v.name, ", ".join(binds), fold(ws)))
            lines.append("    }")
        lines.append("}")
        return "\n".join(lines) + "\n"

    def g9_eq_text(s, d):
        """pruv_ceq__Name: structural equality; fields are compared left to right and only for the same active variant"""
        n = d.name
        lines = [G9_HELPER_ALLOW, "fn pruv_ceq__%s(a: &%s, b: &%s, pruv_budget: &mut i64) -> bool {" % (n, n, n),
                 "    pruv_g9_tick(pruv_budget);"]

        def conj(fields):
            if not fields:
                return "true"
            return " && ".join(s.g9_eq(f.type, "pruv_a%d" % i, "pruv_b%d" % i) for i, f in enumerate(fields))
        if isinstance(d, StructDecl):
            if d.fields:
                for side, var in (("a", "pruv_a"), ("b", "pruv_b")):
                    lines.append("    let %s { %s } = %s;" % (n, ", ".join(
                        "%s: %s%d" % (f.name, var, i) for i, f in enumerate(d.fields)), side))
            lines.append("    " + conj(d.fields))
        else:
            lines.append("    match (a, b) {")
            for v in d.variants:
                if not v.fields:
                    lines.append("        (%s::%s, %s::%s) => true," % (n, v.name, n, v.name))
                    continue
                pa = ", ".join("pruv_a%d" % i for i in range(len(v.fields)))
                pb = ", ".join("pruv_b%d" % i for i in range(len(v.fields)))
                lines.append("        (%s::%s(%s), %s::%s(%s)) => %s," % (n, v.name, pa, n, v.name, pb, conj(v.fields)))
            lines.append("        _ => false,")
            lines.append("    }")
        lines.append("}")
        return "\n".join(lines) + "\n"

    def g9_helper_texts(s):
        """the helpers the runtime requires of this program need, in declaration order (size, then equality, per type).
        need_size / need_eq hold the operand types seen; both are closed over the nominal types of the fields."""
        if not (s.need_size or s.need_eq):
            return []
        decls = s.table.decls

        def close(seed):
            out = set()
            work = sorted(seed)
            while work:
                n = work.pop()
                if n in out or n not in decls:
                    continue
                out.add(n)
                for f in s.decl_fields(decls[n]):
                    work.extend(nominals_in(f.type))
            return out
        sizes, eqs = close(s.need_size), close(s.need_eq)
        texts = [G9_TICK]
        for d in decls.values():
            if d.name in sizes:
                texts.append(s.g9_size_text(d))
            if d.name in eqs:
                texts.append(s.g9_eq_text(d))
        return texts

    # ---------- G9: owning and viewing extended values (executable code) ----------
    def view(s, e):
        """Rust `&T` for an extended expression in a READ position (argument, match scrutinee): no clone, no alloc.
        A parameter / payload view is already a reference; an owned local or a field path is borrowed; a fresh temporary
        (call result, constructor) is borrowed as a temporary, which lives through the whole enclosing statement."""
        if isinstance(e, Var):
            return e.name if e.name in s.refs else "&" + e.name
        if isinstance(e, FieldAccess):
            return "&" + ("*" if s.field_boxed(e.base.ty, e.field) else "") + s.e(e)
        return "&(%s)" % s.e(e)

    def own_e(s, e):
        """an expression in an OWNING position (let, assignment, constructor field, return). A named value or a field
        path is cloned explicitly; a fresh temporary (constructor, literal, call) moves. Other types: plain s.e."""
        if s.ext and s.is_ext(e.ty) and isinstance(e, (Var, FieldAccess)):
            return "::std::clone::Clone::clone(%s)" % s.view(e)
        return s.e(e)

    def field_value(s, x, label):
        """the value stored into the field `label` of a constructor / literal: owned, boxed on a recursive edge"""
        v = s.own_e(x)
        return "::std::boxed::Box::new(%s)" % v if label in s.boxed else v

    # ---------- statements / code expressions ----------
    def block(s, stmts, ind):
        saved = dict(s.vt)
        saved_refs = set(s.refs)
        for st in stmts:
            s.stmt(st, ind)
        s.vt = saved
        s.refs = saved_refs

    def stmt(s, st, ind):
        if isinstance(st, Let):
            s.emit(ind, "let %s%s: %s = %s;" % ("mut " if st.mutable else "", st.name, rty(st.type), s.own_e(st.value)))
            s.vt[st.name] = st.type
            s.refs.discard(st.name)    # G9: a local is an owned value, never a reference
        elif isinstance(st, Assign):
            s.emit(ind, "%s = %s;" % (st.name, s.own_e(st.value)))
        elif isinstance(st, FieldAssign):
            # rhs is fully evaluated into a temporary before the store (the replaced value drops at the store)
            vty = st.value.ty
            decl = "let pruv_v: %s = " % rty(vty) if vty is not None else "let pruv_v = "
            stored = "pruv_v"
            if s.boxed and s.path_boxed(st.name, st.fields):
                stored = "::std::boxed::Box::new(pruv_v)"    # the assigned field is a recursive (Box) edge
            s.emit(ind, "{ %s%s; %s.%s = %s; }" % (decl, s.own_e(st.value), st.name, ".".join(st.fields), stored))
        elif isinstance(st, IndexAssign):
            if is_bool_array(s.vt.get(st.name)):  # G2 A5
                if s.verified:
                    s.emit(ind, "{ let pruv_i: i64 = %s; let pruv_x: bool = %s; unsafe { *%s.get_unchecked_mut(pruv_i as usize) = pruv_x; } }" %
                           (s.e(st.index), s.e(st.value), st.name))
                else:
                    s.emit(ind, "{ let pruv_i: i64 = %s; let pruv_x: bool = %s; pruv_set_bool(%s, pruv_i, pruv_x); }" %
                           (s.e(st.index), s.e(st.value), s.mut_ref(st.name)))
            elif is_u8_array(s.vt.get(st.name)):
                if s.verified:
                    s.emit(ind, "{ let pruv_i: i64 = %s; let pruv_x: i64 = %s; unsafe { *%s.get_unchecked_mut(pruv_i as usize) = pruv_x as u8; } }" %
                           (s.e(st.index), s.e(st.value), st.name))
                else:
                    s.emit(ind, "{ let pruv_i: i64 = %s; let pruv_x: i64 = %s; pruv_set_u8(%s, pruv_i, pruv_x); }" %
                           (s.e(st.index), s.e(st.value), s.mut_ref(st.name)))
            elif s.verified:
                s.emit(ind, "{ let pruv_i: i64 = %s; let pruv_x: i64 = %s; unsafe { *%s.get_unchecked_mut(pruv_i as usize) = pruv_x; } }" %
                       (s.e(st.index), s.e(st.value), st.name))
            else:
                # temporaries first: `&mut a` must not be live while index/value read `a`
                s.emit(ind, "{ let pruv_i: i64 = %s; let pruv_x: i64 = %s; pruv_set(%s, pruv_i, pruv_x); }" %
                       (s.e(st.index), s.e(st.value), s.mut_ref(st.name)))
        elif isinstance(st, If):
            s.emit(ind, "if %s {" % s.e(st.cond))
            s.block(st.then, ind + 1)
            if st.els:
                s.emit(ind, "} else {")
                s.block(st.els, ind + 1)
            s.emit(ind, "}")
        elif isinstance(st, While):
            s.emit(ind, "while %s {" % s.e(st.cond))
            s.block(st.body, ind + 1)
            s.emit(ind, "}")
        elif isinstance(st, Return):
            s.emit(ind, "return;" if st.value is None else "return %s;" % s.own_e(st.value))
        elif isinstance(st, Assert):
            pass
        elif isinstance(st, ExprStmt):
            s.emit(ind, s.e(st.expr) + ";")
        elif isinstance(st, Match) and s.is_ext(st.scrutinee.ty):
            s.match_ext(st, ind)
        elif isinstance(st, Match):
            s.emit(ind, "match %s {" % s.e(st.scrutinee))
            for a in st.arms:
                name = a.ctor if a.enum_name is None else "%s::%s" % (a.enum_name, a.ctor)
                pat = name if not a.binders else "%s(%s)" % (name, ", ".join(a.binders))
                s.emit(ind + 1, "%s => {" % pat)
                s.block(a.body, ind + 2)
                s.emit(ind + 1, "}")
            s.emit(ind, "}")

    def match_ext(s, st, ind):
        """match on an extended enum: the scrutinee is borrowed (a view, never cloned, never consumed) and every payload
        binder is an arm-local view. Scalars and non-extended values are copied out (`let v: i64 = *v;`), extended
        payloads become `&T` (a Box edge derefs by coercion), buffers become `&[T]` / `&str`."""
        sty = st.scrutinee.ty
        s.emit(ind, "match %s {" % s.view(st.scrutinee))
        for a in st.arms:
            name = a.ctor if a.enum_name is None else "%s::%s" % (a.enum_name, a.ctor)
            pat = name if not a.binders else "%s(%s)" % (name, ", ".join(a.binders))
            s.emit(ind + 1, "%s => {" % pat)
            saved_vt, saved_refs = dict(s.vt), set(s.refs)
            fields = s.table.variant(sty, a.ctor).fields
            for b, fd in zip(a.binders, fields):
                ft = fd.type
                if s.is_ext(ft):
                    s.emit(ind + 2, "let %s: &%s = %s;" % (b, ft.name, b))
                    s.refs.add(b)
                elif is_array(ft) or ft == STR:
                    s.emit(ind + 2, "let %s: %s = %s;" % (b, rty(ft, True), b))
                    s.refs.add(b)
                else:
                    s.emit(ind + 2, "let %s: %s = *%s;" % (b, rty(ft), b))
                    s.refs.discard(b)
                s.vt[b] = ft
            s.block(a.body, ind + 2)
            s.vt, s.refs = saved_vt, saved_refs
            s.emit(ind + 1, "}")
        s.emit(ind, "}")

    def mut_ref(s, name):
        """G5: a mutable borrow of the array `name`: a reborrow for an inout parameter (already `&mut [T]`)"""
        return "&mut *" + name if name in s.inouts else "&mut " + name

    def arr_ref(s, e):
        """an array expression used as a borrowed slice"""
        if isinstance(e, Var) and e.name in s.refs:
            return e.name          # G9: a buffer payload view is already a reference
        if isinstance(e, Var) and e.name in s.inouts:
            return "&*" + e.name   # G5: a shared reborrow of an inout parameter
        if isinstance(e, Var) and e.name not in s.params:
            return "&" + e.name
        if isinstance(e, Var):
            return e.name
        return "&" + s.e(e)

    def cref(s, x):
        """a collection expression in a borrow position (G6 section 12.1)"""
        if isinstance(x, Var):
            return x.name if x.name in s.borrowed else "&" + x.name
        return "&(%s)" % s.e(x)

    def catalog_call(s, e):
        """executable catalog operation -> call of its private boundary helper"""
        from foreign import CATALOG
        cat = CATALOG[e.name]
        low = tuple(e.inst["args"]) if e.inst else ()
        src = tuple(e.inst.get("src_args", low)) if e.inst else ()
        name = s.fg.catalog_helper(e.name, low, src)
        args = []
        for p, x in zip(cat.params, e.args):
            if is_collection(p.type):
                args.append(s.e(x) if p.take else s.cref(x))
            elif p.type == STR or (e.name == "file_write_bytes" and p.type == ARRAY_U8):
                args.append(s.arr_ref(x))
            else:
                args.append(s.e(x))
        return "%s(%s)" % (name, ", ".join(args))

    def e(s, e):
        if isinstance(e, IntLit):
            if e.value == -2 ** 63:
                return "i64::MIN"
            return "(%di64)" % e.value if e.value < 0 else "%di64" % e.value
        if isinstance(e, BoolLit):
            return "true" if e.value else "false"
        if isinstance(e, Var):
            return e.name
        if isinstance(e, Move):   # G6: Rust moves
            return e.name
        if isinstance(e, Unary):
            if not s.verified and e.op == "-":
                return "pruv_neg(%s)" % s.e(e.operand)
            return "(%s%s)" % (e.op, s.e(e.operand))
        if isinstance(e, Binary):
            if not s.verified and e.op in SAFE_ARITH:
                return "%s(%s, %s)" % (SAFE_ARITH[e.op], s.e(e.left), s.e(e.right))
            return "(%s %s %s)" % (s.e(e.left), e.op, s.e(e.right))
        if isinstance(e, StrLit):  # G2 B2
            return "::std::string::String::from(%s)" % str_lit(e.value)
        if isinstance(e, Index):
            if is_str(e.array.ty):  # G2 B2
                if not s.verified:
                    return "pruv_get_str(%s, %s)" % (s.arr_ref(e.array), s.e(e.index))
                return "((unsafe { *%s.as_bytes().get_unchecked((%s) as usize) }) as i64)" % (s.e(e.array), s.e(e.index))
            if is_bool_array(e.array.ty):  # G2 A5
                if not s.verified:
                    return "pruv_get_bool(%s, %s)" % (s.arr_ref(e.array), s.e(e.index))
                return "(unsafe { *%s.get_unchecked((%s) as usize) })" % (s.e(e.array), s.e(e.index))
            if is_u8_array(e.array.ty):
                if not s.verified:
                    return "pruv_get_u8(%s, %s)" % (s.arr_ref(e.array), s.e(e.index))
                return "((unsafe { *%s.get_unchecked((%s) as usize) }) as i64)" % (s.e(e.array), s.e(e.index))
            if not s.verified:
                return "pruv_get(%s, %s)" % (s.arr_ref(e.array), s.e(e.index))
            return "(unsafe { *%s.get_unchecked((%s) as usize) })" % (s.e(e.array), s.e(e.index))
        if isinstance(e, Ctor):
            if e.ty is not None and e.ty.args:   # G3: explicit payload type, never left to Rust inference
                rx = rty(e.ty.args[0])
                if e.name == "None":
                    return "None::<%s>" % rx
                if e.name == "Some":
                    return "Some::<%s>(%s)" % (rx, s.e(e.arg))
                return "%s::<%s, i64>(%s)" % (e.name, rx, s.e(e.arg))
            return "None" if e.name == "None" else "%s(%s)" % (e.name, s.e(e.arg))
        if isinstance(e, StructLit):
            # declaration order = left-to-right evaluation; parenthesized so `if S { .. }.x` parses
            inits = {f.name: f.value for f in e.fields}
            fs = s.table.fields(Type(e.name))
            if not fs:
                return "(%s {})" % e.name
            if s.ext:   # G9: constructor fields are owning positions; a recursive edge is boxed
                return "(%s { %s })" % (e.name, ", ".join(
                    "%s: %s" % (f.name, s.field_value(inits[f.name], "%s.%s" % (e.name, f.name))) for f in fs))
            return "(%s { %s })" % (e.name, ", ".join("%s: %s" % (f.name, s.e(inits[f.name])) for f in fs))
        if isinstance(e, EnumCtor):
            ctor = "%s::%s" % (e.enum_name, e.variant)
            if e.args and s.ext:   # G9
                vf = s.table.variant(Type(e.enum_name), e.variant).fields
                return "%s(%s)" % (ctor, ", ".join(
                    s.field_value(a, "%s::%s.%s" % (e.enum_name, e.variant, fd.name)) for a, fd in zip(e.args, vf)))
            return "%s(%s)" % (ctor, ", ".join(s.e(a) for a in e.args)) if e.args else ctor
        if isinstance(e, FieldAccess):
            return "%s.%s" % (s.e(e.base), e.field)
        if isinstance(e, Call):
            n, a = e.name, e.args
            if n == "len":
                return "(%s.len() as i64)" % s.e(a[0])
            if n == "alloc":
                if is_bool_array(e.ty):  # G2 A5
                    if not s.verified:
                        return "pruv_alloc_bool(%s, %s)" % (s.e(a[0]), s.e(a[1]))
                    return "{ let pruv_n: i64 = %s; let pruv_v: bool = %s; vec![pruv_v; pruv_n as usize] }" % (s.e(a[0]), s.e(a[1]))
                if is_u8_array(e.ty):
                    if not s.verified:
                        return "pruv_alloc_u8(%s, %s)" % (s.e(a[0]), s.e(a[1]))
                    return "{ let pruv_n: i64 = %s; let pruv_v: i64 = %s; vec![pruv_v as u8; pruv_n as usize] }" % (s.e(a[0]), s.e(a[1]))
                if not s.verified:
                    return "pruv_alloc(%s, %s)" % (s.e(a[0]), s.e(a[1]))
                # source order: n before v (vec![v; n] would evaluate v first)
                return "{ let pruv_n: i64 = %s; let pruv_v: i64 = %s; vec![pruv_v; pruv_n as usize] }" % (s.e(a[0]), s.e(a[1]))
            if n == "copy":
                if is_str(a[0].ty):  # G2 B2
                    return "%s.to_owned()" % s.e(a[0])
                return "%s.to_vec()" % s.e(a[0])
            if n == "print":
                return 'println!("{}", %s)' % s.e(a[0])
            if n == "is_char_boundary":  # G2 B2
                return "pruv_str_boundary(%s, %s)" % (s.arr_ref(a[0]), s.e(a[1]))
            if n == "substr":  # G2 B2
                if not s.verified:
                    return "pruv_substr(%s, %s, %s)" % (s.arr_ref(a[0]), s.e(a[1]), s.e(a[2]))
                return ("{ let pruv_s: &str = %s; let pruv_lo: i64 = %s; let pruv_hi: i64 = %s; "
                        "::std::string::String::from(unsafe { pruv_s.get_unchecked((pruv_lo as usize)..(pruv_hi as usize)) }) }") % (
                            s.arr_ref(a[0]), s.e(a[1]), s.e(a[2]))
            if s.g6 and n in CATALOG:
                return s.catalog_call(e)
            callee = s.fmap.get(n) if s.g6 else None
            if callee is not None and callee.foreign is not None:
                s.fg.called.add(n)
                s.fg.trusted_helper(callee)   # emitted on first use; the helper checks the selected requires itself
            args = []
            for i, x in enumerate(a):
                if isinstance(x, InoutArg):   # G5: `inout name` -> a mutable borrow / reborrow, in source order
                    args.append(s.mut_ref(x.expr.name))
                elif s.g6 and (isinstance(x, Move) or (x.ty is not None and is_collection(x.ty))):
                    take = isinstance(x, Move) or (callee is not None and callee.params[i].take)
                    args.append(s.e(x) if take else s.cref(x))
                elif s.ext and s.is_ext(x.ty):
                    args.append(s.view(x))   # G9: an extended argument is a read view; a fresh temporary lives through the call
                elif x.ty is not None and (is_array(x.ty) or is_str(x.ty)):
                    args.append(s.arr_ref(x))
                else:
                    args.append(s.e(x))
            if s.explicit:
                n = s.callee(n)
            elif s.verified and n in s.has_req:
                n = n + "__pruv_body"   # caller proved requires
            return "%s(%s)" % (n, ", ".join(args))
        raise Exception("codegen: contract-only expression in code: %r" % e)


def gen_rust(prog, verified=True, trust_callers=False, budget=1 << 30, plan=None, foreign_checks="requires",
             externs=()):
    """plan: a mono.SpecPlan for a generic program (computed here when omitted; PruvError specialization_limit
    propagates). A program without generics is generated directly from prog, exactly as before G3.
    foreign_checks: G6 boundary checks requires|all|off (docs/G6_SPEC.md section 12.3)."""
    return gen_rust_ex(prog, verified, trust_callers, budget, plan, foreign_checks, externs)[0]


def gen_rust_ex(prog, verified=True, trust_callers=False, budget=1 << 30, plan=None, foreign_checks="requires",
                externs=()):
    """(rust text, manifest text or None). The manifest (G6_SPEC 12.4) exists only for programs that use G6;
    externs: [(name, path)] as given with --rust-extern."""
    from typeinfo import g2_unimplemented_error, first_g3_use
    if foreign_checks not in ("requires", "all", "off"):
        raise ValueError("foreign_checks must be requires, all or off")
    if plan is None and (first_g3_use(prog) is not None or prog.explicit):   # G4 A2: explicit mode always names via mono
        from mono import specialize
        plan = specialize(prog)
    if plan is not None:
        prog = plan.program   # concrete: stems for specializations, no type parameters
    g2err = g2_unimplemented_error(prog, "codegen", skip=("array_u8", "array_bool", "str"))  # G2 B2
    if g2err is not None:  # same as the Rust generator's Err(String); drivers reject earlier with the diagnostic
        raise RuntimeError("unsupported_type: %s" % g2err.message)
    g = Gen(prog, verified, trust_callers, budget, foreign_checks)
    g.prelude()
    mark = len(g.out)
    for f in prog.functions:
        g.fn(f)
    # G9: size / equality helpers discovered while the requires checks were generated go in front of the functions
    # (declaration order, no addresses or hashes); nothing at all is added when no runtime requires needs them
    g.out[mark:mark] = g.g9_helper_texts()
    manifest = None
    if g.g6:
        # helpers are discovered while the functions are generated; they go in front of them, in first-use order
        g.out[mark:mark] = g.fg.helper_texts()
        manifest = g.fg.manifest(externs)
    return "\n".join(g.out) + "\n", manifest
