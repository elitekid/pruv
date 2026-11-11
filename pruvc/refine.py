"""STAGE1 A: refinement annotations -> existing contracts (sugar expansion).

`expand(prog)` runs once at the start of Checker.run(), before any type checking, so the synthesized
nodes are typed by the ordinary checker and consumed unchanged by verify/codegen/llvmgen.

1. Validation (stage "type", source order): refinement_base (a `|` annotation on a non-i64 base),
   refinement_bounds (bounds outside i64, L > U, length bound outside 0..=2^40).
2. Expansion (no new type system: `Type` stays the base type):
   * parameter `p: T|R`      -> requires, in parameter order, placed BEFORE the user requires
                                 scalar: `L <= p && p <= U`
                                 array : `len(p) <= N`, then `forall K in 0..len(p): L <= p[K] && p[K] <= U`
   * return `-> T|R`          -> the same conditions on `result`, placed BEFORE the user ensures
   * `let x: T|R = e;`        -> Assert after the binding        (verify code refinement_init)
   * `x = e;` (refined local) -> Assert after the assignment     (refinement_assign)
   * `x[i] = e;` (element range) -> NO assert: the IndexAssign gets `elem_refine = [L, U, origin]`; verify
                                 proves `L <= v && v <= U` for the already evaluated stored value v right after
                                 the index_oob obligation (refinement_assign; no re-evaluation, no forall)
   * a while that assigns a refined local that is alive at the loop head
                              -> the local's conditions are put at the FRONT of its invariants
   Every synthesized node carries the line/col of the original annotation.
3. K, the bound variable of the synthesized forall, is the first of k, k_1, k_2, ... that does not occur
   as any identifier in the function (no capture).
Without a refinement annotation nothing is changed at all."""
import copy
from vast import *

I64_MIN, I64_MAX = -2 ** 63, 2 ** 63 - 1
MAX_LEN = 2 ** 40


def _terr(r, code, msg, fix=""):
    raise PruvError("type", r.line, r.col, code, msg, fix)


def _validate(r):
    if r.shape == "scalar" and r.base != "i64":
        _terr(r, "refinement_base",
              "a refinement `| L..=U` applies only to i64 or [i64], not to %s" % r.base,
              "remove the annotation and state the condition with requires/ensures/assert")
    for what, v in (("lower bound", r.lo), ("upper bound", r.hi)):
        if v is not None and not I64_MIN <= v <= I64_MAX:
            _terr(r, "refinement_bounds", "refinement %s %d is outside the i64 range" % (what, v),
                  "bounds must lie in -9223372036854775808..=9223372036854775807")
    if r.lo is not None and r.lo > r.hi:
        _terr(r, "refinement_bounds", "empty refinement range %d..=%d: the lower bound exceeds the upper bound" % (
            r.lo, r.hi), "write the smaller bound first; both ends are included")
    if r.maxlen is not None and not 0 <= r.maxlen <= MAX_LEN:
        _terr(r, "refinement_bounds", "refinement length bound %d is outside 0..=2^40" % r.maxlen,
              "the length bound `<=N` needs 0 <= N <= 1_099_511_627_776")
    if r.shape == "array" and r.base == "u8" and r.lo is not None and (r.lo < 0 or r.hi > 255):
        _terr(r, "refinement_bounds", "element range %d..=%d is outside the u8 range 0..=255" % (r.lo, r.hi),
              "use bounds within 0..=255")


# ---------- generic AST helpers ----------
def _kids(e):
    if isinstance(e, Unary):
        return [e.operand]
    if isinstance(e, Binary):
        return [e.left, e.right]
    if isinstance(e, Index):
        return [e.array, e.index]
    if isinstance(e, Ctor):
        return [] if e.arg is None else [e.arg]
    if isinstance(e, Quant):
        return [e.lo, e.hi, e.body]
    if isinstance(e, Call):
        return list(e.args)
    if isinstance(e, StructLit):
        return [fi.value for fi in e.fields]
    if isinstance(e, EnumCtor):
        return list(e.args)
    if isinstance(e, FieldAccess):
        return [e.base]
    if isinstance(e, (IsVariant, VariantField)):
        return [e.value]
    return []


def _expr_names(e, out):
    if isinstance(e, Var):
        out.add(e.name)
    elif isinstance(e, Call):
        out.add(e.name)
    elif isinstance(e, Quant):
        out.add(e.var)
    for c in _kids(e):
        _expr_names(c, out)


def _stmt_names(stmts, out):
    for st in stmts:
        if isinstance(st, Let):
            out.add(st.name); _expr_names(st.value, out)
        elif isinstance(st, (Assign, FieldAssign)):
            out.add(st.name); _expr_names(st.value, out)
        elif isinstance(st, IndexAssign):
            out.add(st.name); _expr_names(st.index, out); _expr_names(st.value, out)
        elif isinstance(st, If):
            _expr_names(st.cond, out); _stmt_names(st.then, out); _stmt_names(st.els, out)
        elif isinstance(st, While):
            _expr_names(st.cond, out)
            for i in st.invariants:
                _expr_names(i, out)
            _expr_names(st.decreases, out); _stmt_names(st.body, out)
        elif isinstance(st, Return):
            if st.value is not None:
                _expr_names(st.value, out)
        elif isinstance(st, Assert):
            _expr_names(st.cond, out)
        elif isinstance(st, ExprStmt):
            _expr_names(st.expr, out)
        elif isinstance(st, Match):
            _expr_names(st.scrutinee, out)
            for a in st.arms:
                out.update(a.binders); _stmt_names(a.body, out)


def _fn_names(f):
    out = set(p.name for p in f.params)
    for e in f.requires + f.ensures:
        _expr_names(e, out)
    _stmt_names(f.body, out)
    return out


def pick_bound_name(names):
    """first of k, k_1, k_2, ... not in names (deterministic)"""
    if "k" not in names:
        return "k"
    i = 1
    while "k_%d" % i in names:
        i += 1
    return "k_%d" % i


def _assigned(stmts, out):
    for st in stmts:
        if isinstance(st, (Assign, IndexAssign)):
            out.add(st.name)
        elif isinstance(st, If):
            _assigned(st.then, out); _assigned(st.els, out)
        elif isinstance(st, While):
            _assigned(st.body, out)
        elif isinstance(st, Match):
            for a in st.arms:
                _assigned(a.body, out)
    return out


# ---------- condition builders (all nodes at the annotation position) ----------
class _At:
    def __init__(s, r, kname):
        s.line, s.col, s.k = r.line, r.col, kname

    def lit(s, v): return IntLit(s.line, s.col, v)
    def var(s, n): return Var(s.line, s.col, n)
    def bin(s, op, l, r): return Binary(s.line, s.col, op, l, r)
    def length(s, n): return Call(s.line, s.col, "len", [s.var(n)])

    def within(s, v, r):
        """L <= v && v <= U for an i64 expression builder `v()`"""
        return s.bin("&&", s.bin("<=", s.lit(r.lo), v()), s.bin("<=", v(), s.lit(r.hi)))


def parts(r, name, kname):
    """[(label, expr)] conditions of refinement r on the variable `name` (`result` allowed)"""
    at = _At(r, kname)
    if r.shape == "scalar":
        return [("value range", at.within(lambda: at.var(name), r))]
    out = []
    if r.maxlen is not None:
        out.append(("length bound", at.bin("<=", at.length(name), at.lit(r.maxlen))))
    if r.lo is not None:
        body = at.within(lambda: Index(at.line, at.col, at.var(name), at.var(kname)), r)
        out.append(("element range", Quant(at.line, at.col, "forall", kname, at.lit(0), at.length(name), body)))
    return out


def _synth_assert(r, label, expr, code, what):
    return Assert(r.line, r.col, expr, code, what)


class _Expander:
    def __init__(s, f):
        s.f = f
        s.k = pick_bound_name(_fn_names(f))

    def block(s, stmts, scope):
        out = []
        for st in stmts:
            out.append(st)
            if isinstance(st, Let):
                if st.refine is not None:
                    scope[st.name] = st.refine
                    for label, e in parts(st.refine, st.name, s.k):
                        out.append(_synth_assert(st.refine, label, e, "refinement_init",
                                                 "the %s of local %s at its declaration (line %d)" % (
                                                     label, st.name, st.line)))
            elif isinstance(st, Assign):
                r = scope.get(st.name)
                if r is not None:
                    for label, e in parts(r, st.name, s.k):
                        out.append(_synth_assert(r, label, e, "refinement_assign",
                                                 "the %s of local %s after the assignment on line %d" % (
                                                     label, st.name, st.line)))
            elif isinstance(st, IndexAssign):
                r = scope.get(st.name)
                if r is not None and r.shape == "array" and r.lo is not None:
                    # no synthesized assert: verify proves the stored value's range (code refinement_assign)
                    st.elem_refine = [r.lo, r.hi, "the element range of local %s after the store on line %d" % (
                        st.name, st.line)]
            elif isinstance(st, If):
                st.then = s.block(st.then, dict(scope))
                st.els = s.block(st.els, dict(scope))
            elif isinstance(st, While):
                changed = _assigned(st.body, set())
                pre = []
                for name, r in scope.items():          # declaration order, only what is alive at the loop head
                    if name in changed:
                        pre.extend(e for _, e in parts(r, name, s.k))
                if pre:
                    st.invariants = pre + st.invariants
                st.body = s.block(st.body, dict(scope))
            elif isinstance(st, Match):
                for a in st.arms:
                    a.body = s.block(a.body, dict(scope))
        return out

    def run(s):
        f = s.f
        pre = []
        for p in f.params:
            if p.refine is not None:
                pre.extend(e for _, e in parts(p.refine, p.name, s.k))
        if pre:
            f.requires = pre + f.requires
        if f.ret_refine is not None:
            f.ensures = [e for _, e in parts(f.ret_refine, "result", s.k)] + f.ensures
        f.body = s.block(f.body, {})


def _validate_block(stmts):
    for st in stmts:
        if isinstance(st, Let) and st.refine is not None:
            _validate(st.refine)
        elif isinstance(st, If):
            _validate_block(st.then); _validate_block(st.els)
        elif isinstance(st, While):
            _validate_block(st.body)
        elif isinstance(st, Match):
            for a in st.arms:
                _validate_block(a.body)


def has_refinements(prog):
    for f in prog.functions:
        if f.ret_refine is not None or any(p.refine is not None for p in f.params):
            return True
        if _any_let_refine(f.body):
            return True
    return False


def _any_let_refine(stmts):
    for st in stmts:
        if isinstance(st, Let) and st.refine is not None:
            return True
        if isinstance(st, If) and (_any_let_refine(st.then) or _any_let_refine(st.els)):
            return True
        if isinstance(st, While) and _any_let_refine(st.body):
            return True
        if isinstance(st, Match) and any(_any_let_refine(a.body) for a in st.arms):
            return True
    return False


def expand(prog):
    """validate every annotation, then desugar. Idempotent per Program; no-op without annotations."""
    if getattr(prog, "_refined", False):
        return
    prog._refined = True
    if not has_refinements(prog):
        return
    for f in prog.functions:
        for p in f.params:
            if p.refine is not None:
                _validate(p.refine)
        if f.ret_refine is not None:
            _validate(f.ret_refine)
        _validate_block(f.body)
    for f in prog.functions:
        _Expander(f).run()
