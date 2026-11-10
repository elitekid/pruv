"""Vow -> Rust.  gen_rust(prog, verified=True, trust_callers=False)

Contracts are erased from function bodies; they are only used (a) by the verifier and
(b) to build the runtime `requires` check of the public entry point.

Modes (two independent axes):
  verified=True   Output of a program the verifier proved: array accesses are
                  `get_unchecked` (unsafe), arithmetic is plain Rust.
  verified=False  (--no-verify, "safe mode") No proof exists, so nothing unsafe is emitted
                  and nothing wraps silently: array reads/writes go through vow_get/vow_set
                  (panic unless 0 <= i < len), + - * / % and unary - go through
                  vow_add/vow_sub/vow_mul/vow_div/vow_rem/vow_neg (+ - * and unary -
                  are checked_*, panic on overflow), alloc(n, v) goes through
                  vow_alloc (panic unless 0 <= n <= 2^40).  / and % use the same domain
                  the verifier proves (verify.py): divisor > 0 and dividend >= 0,
                  otherwise panic "division outside domain: ...".
  trust_callers=False (default)  Functions with `requires` are emitted twice; the public
                  entry checks every requires at run time and panics with
                  "vow: requires violated: <fn>: <expr>" before running the body.
  trust_callers=True  The public entry calls the body without checks (for benchmarking).

Generated names (reserved: the parser rejects any user identifier that starts with `vow_`
or contains `__`, error code reserved_name, so user names never collide with these):
  f                 public function, same name/params/return type as the Vow function
                    (`#[inline]` wrapper when f has requires, otherwise the real body).
  f__vow_body       private unchecked body, only for functions with requires.
                    Verified mode: calls inside Vow code go straight to f__vow_body
                    (the caller proved requires).  Safe mode: inner
                    calls go to the checked entry f.
  vow_*             helper functions emitted once at the top of the file (only the ones
                    needed): vow_idx vow_oob vow_get vow_set vow_ovf vow_add vow_sub
                    vow_mul vow_div vow_rem vow_neg vow_alloc (safe mode) and
                    vow_ud vow_cidx vow_cadd vow_csub vow_cmul vow_cneg vow_cdiv vow_crem
                    (requires evaluation).  Local temporaries vow_* are also reserved.

Run-time requires evaluation uses i128 (contracts are mathematical integers).  Contract
/ and % are Euclidean (div_euclid/rem_euclid, as z3 Int).  Anything undefined there
(division by zero, index out of range, i128 overflow, max/min over an empty range,
some_val of None, ...) panics with "vow: requires undefined: ...".

G1 (structs/enums): user types are `Copy` and emitted by emit_public_types(prog) at the top of
the file.  Contract evaluation uses mirror types `vow_contract__Name` (every i64 leaf is i128,
Option/Result carry i128) and converters `vow_to_c__Name(value)` (recursive; an enum converts
only its active variant), so contract arithmetic never goes through i64.
Standard types are always written `::std::vec::Vec` / `::std::option::Option` /
`::std::result::Result` so user types named Vec etc. cannot collide.
"""
from vast import *
from typeinfo import TypeTable, is_user_type

ALLOW = ("#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, "
         "dead_code, unreachable_code, unreachable_patterns)]")

SAFE_PRELUDE = """\
#[allow(dead_code)]
#[cold]
#[inline(never)]
fn vow_oob(i: i64, len: usize) -> ! { panic!("vow: index out of bounds: {} (len {})", i, len) }
#[allow(dead_code)]
#[cold]
#[inline(never)]
fn vow_ovf(what: &str) -> ! { panic!("vow: arithmetic error: {}", what) }
#[allow(dead_code)]
#[inline]
fn vow_idx(i: i64, len: usize) -> usize { if i >= 0 && (i as u64) < (len as u64) { i as usize } else { vow_oob(i, len) } }
#[allow(dead_code)]
#[inline]
fn vow_get(a: &[i64], i: i64) -> i64 { a[vow_idx(i, a.len())] }
#[allow(dead_code)]
#[inline]
fn vow_set(a: &mut [i64], i: i64, v: i64) { let k = vow_idx(i, a.len()); a[k] = v; }
#[allow(dead_code)]
#[inline]
fn vow_add(a: i64, b: i64) -> i64 { match a.checked_add(b) { Some(v) => v, None => vow_ovf("overflow in +") } }
#[allow(dead_code)]
#[inline]
fn vow_sub(a: i64, b: i64) -> i64 { match a.checked_sub(b) { Some(v) => v, None => vow_ovf("overflow in -") } }
#[allow(dead_code)]
#[inline]
fn vow_mul(a: i64, b: i64) -> i64 { match a.checked_mul(b) { Some(v) => v, None => vow_ovf("overflow in *") } }
#[allow(dead_code)]
#[inline]
fn vow_div(a: i64, b: i64) -> i64 { if b > 0 && a >= 0 { a / b } else { vow_ovf("division outside domain: need divisor > 0 and dividend >= 0") } }
#[allow(dead_code)]
#[inline]
fn vow_rem(a: i64, b: i64) -> i64 { if b > 0 && a >= 0 { a % b } else { vow_ovf("division outside domain: need divisor > 0 and dividend >= 0") } }
#[allow(dead_code)]
#[inline]
fn vow_neg(a: i64) -> i64 { match a.checked_neg() { Some(v) => v, None => vow_ovf("overflow in unary -") } }
#[allow(dead_code)]
#[inline]
fn vow_alloc(n: i64, v: i64) -> ::std::vec::Vec<i64> { if n < 0 || n > (1i64 << 40) { vow_ovf("alloc length outside 0..2^40") } vec![v; n as usize] }
"""

CONTRACT_PRELUDE = """\
#[allow(dead_code)]
#[cold]
#[inline(never)]
fn vow_ud(what: &str) -> ! { panic!("vow: requires undefined: {}", what) }
#[allow(dead_code)]
#[inline]
fn vow_cidx(a: &[i64], i: i128) -> i128 { if i >= 0 && i < (a.len() as i128) { a[i as usize] as i128 } else { vow_ud("array index out of range") } }
#[allow(dead_code)]
#[inline]
fn vow_cadd(a: i128, b: i128) -> i128 { a.checked_add(b).unwrap_or_else(|| vow_ud("i128 overflow in +")) }
#[allow(dead_code)]
#[inline]
fn vow_csub(a: i128, b: i128) -> i128 { a.checked_sub(b).unwrap_or_else(|| vow_ud("i128 overflow in -")) }
#[allow(dead_code)]
#[inline]
fn vow_cmul(a: i128, b: i128) -> i128 { a.checked_mul(b).unwrap_or_else(|| vow_ud("i128 overflow in *")) }
#[allow(dead_code)]
#[inline]
fn vow_cneg(a: i128) -> i128 { a.checked_neg().unwrap_or_else(|| vow_ud("i128 overflow in unary -")) }
#[allow(dead_code)]
#[inline]
fn vow_cdiv(a: i128, b: i128) -> i128 { if b == 0 { vow_ud("division by zero in /") } a.checked_div_euclid(b).unwrap_or_else(|| vow_ud("i128 overflow in /")) }
#[allow(dead_code)]
#[inline]
fn vow_crem(a: i128, b: i128) -> i128 { if b == 0 { vow_ud("division by zero in %") } a.checked_rem_euclid(b).unwrap_or_else(|| vow_ud("i128 overflow in %")) }
"""

SAFE_ARITH = {"+": "vow_add", "-": "vow_sub", "*": "vow_mul", "/": "vow_div", "%": "vow_rem"}
CONTRACT_ARITH = {"+": "vow_cadd", "-": "vow_csub", "*": "vow_cmul", "/": "vow_cdiv", "%": "vow_crem"}


def rty(t, param=False):
    simple = {"i64": "i64", "bool": "bool", "unit": "()", "option": "::std::option::Option<i64>",
              "result": "::std::result::Result<i64, i64>"}
    if t.name in simple:
        return simple[t.name]
    if t.name == "array":
        return "&[i64]" if param else "::std::vec::Vec<i64>"
    if is_user_type(t):
        return t.name
    raise Exception("codegen: unsupported type %r" % (t,))


def cty(t):
    """contract (i128) mirror of a type"""
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
        return "vow_contract__" + n
    raise Exception("codegen: type %r has no contract representation" % (t,))


def conv(t, x):
    """Rust expression turning the executed value `x` (type t) into its contract value"""
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
        return "vow_to_c__%s(%s)" % (n, x)
    raise Exception("codegen: type %r has no contract representation" % (t,))


def emit_public_types(prog):
    """`pub struct` / `pub enum` for every user type, dependency-first (TypeTable.order)."""
    out = []
    for d in TypeTable(prog).order:
        out.append("#[allow(dead_code, non_camel_case_types, non_snake_case)]")
        out.append("#[derive(Clone, Copy, Debug, PartialEq, Eq)]")
        if isinstance(d, StructDecl):
            if d.fields:
                body = ", ".join("pub %s: %s" % (f.name, rty(f.type)) for f in d.fields)
                out.append("pub struct %s { %s }" % (d.name, body))
            else:
                out.append("pub struct %s {}" % d.name)
        else:
            vs = []
            for v in d.variants:
                if v.fields:
                    vs.append("%s(%s)" % (v.name, ", ".join(rty(f.type) for f in v.fields)))
                else:
                    vs.append(v.name)
            out.append("pub enum %s { %s }" % (d.name, ", ".join(vs)))
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
    if isinstance(e, StructLit):
        if not e.fields:
            return "%s {}" % e.name
        return "%s { %s }" % (e.name, ", ".join("%s: %s" % (f.name, show(f.value)) for f in e.fields))
    if isinstance(e, EnumCtor):
        if not e.args:
            return "%s::%s" % (e.enum_name, e.variant)
        return "%s::%s(%s)" % (e.enum_name, e.variant, ", ".join(show(a) for a in e.args))
    if isinstance(e, FieldAccess):
        return "%s.%s" % (show(e.base), e.field)
    if isinstance(e, IsVariant):
        return "is_variant(%s, %s::%s)" % (show(e.value), e.enum_name, e.variant)
    if isinstance(e, VariantField):
        return "variant_field(%s, %s::%s, %s)" % (show(e.value), e.enum_name, e.variant, e.field)
    return "?"


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
    def __init__(s, prog, verified=True, trust_callers=False):
        s.prog = prog
        s.verified = verified
        s.trust = trust_callers
        s.out = []
        s.has_req = {f.name for f in prog.functions if f.requires}
        s.cp = None    # set during requires entry checks: user-type params already converted
        s.bound = []   # quantifier variables in scope (contract evaluation)
        s.tmp = 0
        s.table = TypeTable(prog)

    def emit(s, ind, line):
        s.out.append("    " * ind + line)

    def prelude(s):
        types = emit_public_types(s.prog)
        if types:
            s.out.append(types)
        if not s.verified:
            s.out.append(SAFE_PRELUDE)
        if s.has_req and not s.trust:
            s.out.append(CONTRACT_PRELUDE)
            ctypes = s.contract_types()
            if ctypes:
                s.out.append(ctypes)

    def contract_types(s):
        """vow_contract__Name mirror types and vow_to_c__Name converters (only for requires evaluation)"""
        attrs = "#[allow(dead_code, non_camel_case_types, non_snake_case, unused_variables)]"
        out = []
        for d in s.table.order:
            cn = "vow_contract__" + d.name
            out.append(attrs)
            out.append("#[derive(Clone, Copy, PartialEq, Eq)]")
            if isinstance(d, StructDecl):
                out.append("struct %s { %s }" % (cn, ", ".join("%s: %s" % (f.name, cty(f.type)) for f in d.fields)))
                out.append(attrs)
                out.append("#[inline]")
                init = ", ".join("%s: %s" % (f.name, conv(f.type, "v." + f.name)) for f in d.fields)
                out.append("fn vow_to_c__%s(v: %s) -> %s { %s { %s } }" % (d.name, d.name, cn, cn, init))
            else:
                vs, arms = [], []
                for v in d.variants:
                    if v.fields:
                        vs.append("%s(%s)" % (v.name, ", ".join(cty(f.type) for f in v.fields)))
                        names = ["vow_a%d" % i for i in range(len(v.fields))]
                        args = ", ".join(conv(f.type, n) for f, n in zip(v.fields, names))
                        arms.append("%s::%s(%s) => %s::%s(%s)," % (d.name, v.name, ", ".join(names), cn, v.name, args))
                    else:
                        vs.append(v.name)
                        arms.append("%s::%s => %s::%s," % (d.name, v.name, cn, v.name))
                out.append("enum %s { %s }" % (cn, ", ".join(vs)))
                out.append(attrs)
                out.append("#[inline]")
                out.append("fn vow_to_c__%s(v: %s) -> %s { match v { %s } }" % (d.name, d.name, cn, " ".join(arms)))
        return "\n".join(out) + ("\n" if out else "")

    def fn(s, f):
        s.params = {p.name for p in f.params}
        ps = ", ".join("%s: %s" % (p.name, rty(p.type, True)) for p in f.params)
        ret = "" if f.ret == UNIT else " -> " + rty(f.ret)
        body_name = f.name + "__vow_body" if f.requires else f.name
        s.emit(0, ALLOW)
        s.emit(0, "%sfn %s(%s)%s {" % ("" if f.requires else "pub ", body_name, ps, ret))
        s.block(f.body, 1)
        s.emit(0, "}")
        s.emit(0, "")
        if f.requires:
            s.entry(f, ps, ret, body_name)

    def entry(s, f, ps, ret, body_name):
        s.emit(0, ALLOW)
        s.emit(0, "#[inline]")
        s.emit(0, "pub fn %s(%s)%s {" % (f.name, ps, ret))
        if not s.trust:
            s.cp = {}   # user-type parameter -> its type, converted once below
            checks = []
            try:
                for n, r in enumerate(f.requires, 1):
                    msg = "vow: requires violated: %s: %s" % (f.name, show(r))
                    checks.append("if !(%s) { panic!(\"{}\", %s); }" % (s.c(r), rstr(msg)))
                used = dict(s.cp)
            finally:
                s.cp = None
            for p in f.params:
                if p.name in used:
                    s.emit(1, "let vow_cp_%s: %s = %s;" % (p.name, cty(used[p.name]), conv(used[p.name], p.name)))
            for line in checks:
                s.emit(1, line)
        s.emit(1, "%s(%s)" % (body_name, ", ".join(p.name for p in f.params)))
        s.emit(0, "}")
        s.emit(0, "")

    # ---------- contract evaluation (requires), i128 ----------
    def carr(s, e):
        if isinstance(e, Var):
            return e.name
        raise Exception("codegen: unsupported array expression in contract: %r" % e)

    def c(s, e):
        if isinstance(e, IntLit):
            return "(%di128)" % e.value if e.value < 0 else "%di128" % e.value
        if isinstance(e, BoolLit):
            return "true" if e.value else "false"
        if isinstance(e, Var):
            if e.name in s.bound:
                return e.name
            t = e.ty.name if e.ty is not None else "i64"
            if s.cp is not None and e.ty is not None and is_user_type(e.ty) and e.name in s.params:
                s.cp[e.name] = e.ty
                return "vow_cp_" + e.name
            if t in ("i64", "option", "result") or is_user_type(e.ty):
                return conv(e.ty if e.ty is not None else I64, e.name)
            return e.name
        if isinstance(e, Unary):
            if e.op == "!":
                return "(!%s)" % s.c(e.operand)
            return "vow_cneg(%s)" % s.c(e.operand)
        if isinstance(e, Binary):
            op = e.op
            if op == "==>":
                return "(!%s || %s)" % (s.c(e.left), s.c(e.right))
            if op in CONTRACT_ARITH:
                return "%s(%s, %s)" % (CONTRACT_ARITH[op], s.c(e.left), s.c(e.right))
            return "(%s %s %s)" % (s.c(e.left), op, s.c(e.right))
        if isinstance(e, Index):
            return "vow_cidx(%s, %s)" % (s.carr(e.array), s.c(e.index))
        if isinstance(e, Ctor):
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
            return "(vow_contract__%s { %s })" % (e.name, body) if fs else "(vow_contract__%s {})" % e.name
        if isinstance(e, EnumCtor):
            ctor = "vow_contract__%s::%s" % (e.enum_name, e.variant)
            if not e.args:
                return ctor
            return "%s(%s)" % (ctor, ", ".join(s.c(a) for a in e.args))
        if isinstance(e, FieldAccess):
            return "%s.%s" % (s.c(e.base), e.field)
        if isinstance(e, IsVariant):
            return "matches!(%s, vow_contract__%s::%s { .. })" % (s.c(e.value), e.enum_name, e.variant)
        if isinstance(e, VariantField):
            s.tmp += 1
            tmp = "vow_e%d" % s.tmp
            cn = "vow_contract__%s" % e.enum_name
            vf = s.table.variant(Type(e.enum_name), e.variant)
            idx = s.table.field_index(Type(e.enum_name), e.field, e.variant)
            pats = ", ".join("vow_f" if i == idx else "_" for i in range(len(vf.fields)))
            msg = "variant_field expected %s::%s.%s" % (e.enum_name, e.variant, e.field)
            return "({ let %s: %s = %s; match %s { %s::%s(%s) => vow_f, _ => vow_ud(%s) } })" % (
                tmp, cn, s.c(e.value), tmp, cn, e.variant, pats, rstr(msg))
        if isinstance(e, Call):
            n, a = e.name, e.args
            if n == "len":
                return "(%s.len() as i128)" % s.carr(a[0])
            if n == "is_some":
                return "%s.is_some()" % s.c(a[0])
            if n == "some_val":
                return '%s.unwrap_or_else(|| vow_ud("some_val of None"))' % s.c(a[0])
            if n == "is_ok":
                return "%s.is_ok()" % s.c(a[0])
            if n == "ok_val":
                return '%s.ok().unwrap_or_else(|| vow_ud("ok_val of Err"))' % s.c(a[0])
            if n == "err_val":
                return '%s.err().unwrap_or_else(|| vow_ud("err_val of Ok"))' % s.c(a[0])
        raise Exception("codegen: unsupported expression in requires: %r" % e)

    def cquant(s, e):
        s.tmp += 1
        n = s.tmp
        lo, hi = s.c(e.lo), s.c(e.hi)   # bounds see only the outer scope
        s.bound.append(e.var)
        body = s.c(e.body)
        s.bound.pop()
        k, r, h = "vow_k%d" % n, "vow_r%d" % n, "vow_hi%d" % n
        head = "{ let vow_lo%d: i128 = %s; let %s: i128 = %s; let mut %s: i128 = vow_lo%d; " % (n, lo, h, hi, k, n)
        loop = "while %s < %s { let %s: i128 = %s; " % (k, h, e.var, k)
        tail = "%s += 1; } " % k
        kind = e.kind
        if kind == "forall":
            return head + "let mut %s = true; " % r + loop + "if !(%s) { %s = false; break; } " % (body, r) + tail + r + " }"
        if kind == "exists":
            return head + "let mut %s = false; " % r + loop + "if %s { %s = true; break; } " % (body, r) + tail + r + " }"
        if kind == "sum":
            return head + "let mut %s: i128 = 0; " % r + loop + "%s = vow_cadd(%s, %s); " % (r, r, body) + tail + r + " }"
        if kind == "count":
            return head + "let mut %s: i128 = 0; " % r + loop + "if %s { %s += 1; } " % (body, r) + tail + r + " }"
        # max / min
        cmp = ">" if kind == "max" else "<"
        return (head + "let mut %s: ::std::option::Option<i128> = None; " % r + loop + "let vow_v: i128 = %s; " % body +
                "%s = Some(match %s { None => vow_v, Some(vow_a) => if vow_v %s vow_a { vow_v } else { vow_a } }); " % (r, r, cmp) +
                tail + '%s.unwrap_or_else(|| vow_ud("%s over an empty range")) }' % (r, kind))

    # ---------- statements / code expressions ----------
    def block(s, stmts, ind):
        for st in stmts:
            s.stmt(st, ind)

    def stmt(s, st, ind):
        if isinstance(st, Let):
            s.emit(ind, "let %s%s: %s = %s;" % ("mut " if st.mutable else "", st.name, rty(st.type), s.e(st.value)))
        elif isinstance(st, Assign):
            s.emit(ind, "%s = %s;" % (st.name, s.e(st.value)))
        elif isinstance(st, FieldAssign):
            # rhs is fully evaluated into a temporary before the store
            vty = st.value.ty
            decl = "let vow_v: %s = " % rty(vty) if vty is not None else "let vow_v = "
            s.emit(ind, "{ %s%s; %s.%s = vow_v; }" % (decl, s.e(st.value), st.name, ".".join(st.fields)))
        elif isinstance(st, IndexAssign):
            if s.verified:
                s.emit(ind, "unsafe { *%s.get_unchecked_mut((%s) as usize) = %s; }" % (st.name, s.e(st.index), s.e(st.value)))
            else:
                # temporaries first: `&mut a` must not be live while index/value read `a`
                s.emit(ind, "{ let vow_i: i64 = %s; let vow_x: i64 = %s; vow_set(&mut %s, vow_i, vow_x); }" %
                       (s.e(st.index), s.e(st.value), st.name))
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
            s.emit(ind, "return;" if st.value is None else "return %s;" % s.e(st.value))
        elif isinstance(st, Assert):
            pass
        elif isinstance(st, ExprStmt):
            s.emit(ind, s.e(st.expr) + ";")
        elif isinstance(st, Match):
            s.emit(ind, "match %s {" % s.e(st.scrutinee))
            for a in st.arms:
                name = a.ctor if a.enum_name is None else "%s::%s" % (a.enum_name, a.ctor)
                pat = name if not a.binders else "%s(%s)" % (name, ", ".join(a.binders))
                s.emit(ind + 1, "%s => {" % pat)
                s.block(a.body, ind + 2)
                s.emit(ind + 1, "}")
            s.emit(ind, "}")

    def arr_ref(s, e):
        """an array expression used as a borrowed slice"""
        if isinstance(e, Var) and e.name not in s.params:
            return "&" + e.name
        if isinstance(e, Var):
            return e.name
        return "&" + s.e(e)

    def e(s, e):
        if isinstance(e, IntLit):
            if e.value == -2 ** 63:
                return "i64::MIN"
            return "(%di64)" % e.value if e.value < 0 else "%di64" % e.value
        if isinstance(e, BoolLit):
            return "true" if e.value else "false"
        if isinstance(e, Var):
            return e.name
        if isinstance(e, Unary):
            if not s.verified and e.op == "-":
                return "vow_neg(%s)" % s.e(e.operand)
            return "(%s%s)" % (e.op, s.e(e.operand))
        if isinstance(e, Binary):
            if not s.verified and e.op in SAFE_ARITH:
                return "%s(%s, %s)" % (SAFE_ARITH[e.op], s.e(e.left), s.e(e.right))
            return "(%s %s %s)" % (s.e(e.left), e.op, s.e(e.right))
        if isinstance(e, Index):
            if not s.verified:
                return "vow_get(%s, %s)" % (s.arr_ref(e.array), s.e(e.index))
            return "(unsafe { *%s.get_unchecked((%s) as usize) })" % (s.e(e.array), s.e(e.index))
        if isinstance(e, Ctor):
            return "None" if e.name == "None" else "%s(%s)" % (e.name, s.e(e.arg))
        if isinstance(e, StructLit):
            # declaration order = left-to-right evaluation; parenthesized so `if S { .. }.x` parses
            inits = {f.name: f.value for f in e.fields}
            fs = s.table.fields(Type(e.name))
            if not fs:
                return "(%s {})" % e.name
            return "(%s { %s })" % (e.name, ", ".join("%s: %s" % (f.name, s.e(inits[f.name])) for f in fs))
        if isinstance(e, EnumCtor):
            ctor = "%s::%s" % (e.enum_name, e.variant)
            return "%s(%s)" % (ctor, ", ".join(s.e(a) for a in e.args)) if e.args else ctor
        if isinstance(e, FieldAccess):
            return "%s.%s" % (s.e(e.base), e.field)
        if isinstance(e, Call):
            n, a = e.name, e.args
            if n == "len":
                return "(%s.len() as i64)" % s.e(a[0])
            if n == "alloc":
                if not s.verified:
                    return "vow_alloc(%s, %s)" % (s.e(a[0]), s.e(a[1]))
                return "vec![%s; (%s) as usize]" % (s.e(a[1]), s.e(a[0]))
            if n == "copy":
                return "%s.to_vec()" % s.e(a[0])
            if n == "print":
                return 'println!("{}", %s)' % s.e(a[0])
            args = [s.arr_ref(x) if x.ty == ARRAY else s.e(x) for x in a]
            if s.verified and n in s.has_req:
                n = n + "__vow_body"   # caller proved requires
            return "%s(%s)" % (n, ", ".join(args))
        raise Exception("codegen: contract-only expression in code: %r" % e)


def gen_rust(prog, verified=True, trust_callers=False):
    g = Gen(prog, verified, trust_callers)
    g.prelude()
    for f in prog.functions:
        g.fn(f)
    return "\n".join(g.out) + "\n"
