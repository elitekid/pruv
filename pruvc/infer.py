"""STAGE1 B2 (+ B+ kinds 12-14, config version 2): template Houdini loop-invariant inference (--infer).
Normative spec: docs/STAGE1_B_INFER.md (3.7 for the B+ kinds: value ranges, output-array prefix, early-return prefix).

Per function: generate candidate invariants from fixed templates (section 3), then run Houdini rounds
(section 4.1): every round verifies the whole function with all surviving candidates as extra loop
invariants and drops the candidates whose entry / preservation obligation is not proved; stop when a round
drops nothing. verify.py then verifies the function once more with the survivors (section 4.2).
No heuristics beyond the document. Dependency direction: this module imports verify; verify imports this
module only lazily inside verify_program."""
import dataclasses
import time

from vast import *
from refine import pick_bound_name, _fn_names, _kids
from typeinfo import contains_collection
from verify import (FnVerifier, QueryConfig, Probe, BudgetExhausted, InferenceTimeout, walk_loops)

INFER_CONFIG = {
    "version": 2,
    "max_candidates": 64,     # per loop, after sorting and de-duplication (the cut-off count is `capped`)
    "max_queries": 512,       # per function, every solver attempt (also lemma retries) counts 1
    "rlimit": 100000,
    "timeout_ms": 500,
    "seed": 0,
    "max_seconds": 5,         # per function, wall clock (time.monotonic)
}

I64_MAX = 2 ** 63 - 1


class _Skip(Exception):
    """a candidate that cannot be built (constant outside i64, node kind the printer does not know)"""


# ---------------------------------------------------------------------------
# printing (section 3.5)
# ---------------------------------------------------------------------------
_PREC = {"==>": 1, "||": 2, "&&": 3, "==": 4, "!=": 4, "<": 4, "<=": 4, ">": 4, ">=": 4,
         "+": 5, "-": 5, "*": 6, "/": 6, "%": 6}


def _is_quantifier(e):
    return isinstance(e, Quant) and e.kind in ("forall", "exists")


def show(e):
    if isinstance(e, IntLit):
        return str(e.value)
    if isinstance(e, BoolLit):
        return "true" if e.value else "false"
    if isinstance(e, Var):
        return e.name
    if isinstance(e, Unary):
        o = show(e.operand)
        if isinstance(e.operand, Binary) or _is_quantifier(e.operand):
            o = "(" + o + ")"
        return e.op + o
    if isinstance(e, Binary):
        p = _PREC[e.op]
        l, r = show(e.left), show(e.right)
        if _is_quantifier(e.left):
            l = "(" + l + ")"
        elif isinstance(e.left, Binary):
            lp = _PREC[e.left.op]
            if lp < p or (lp == p and e.op == "==>"):
                l = "(" + l + ")"
        if _is_quantifier(e.right):
            r = "(" + r + ")"
        elif isinstance(e.right, Binary):
            rp = _PREC[e.right.op]
            if rp < p or (rp == p and e.op != "==>"):
                r = "(" + r + ")"
        return "%s %s %s" % (l, e.op, r)
    if isinstance(e, Index):
        return "%s[%s]" % (show(e.array), show(e.index))
    if isinstance(e, Call):
        return "%s(%s)" % (e.name, ", ".join(show(a) for a in e.args))
    if isinstance(e, Ctor):
        return e.name if e.arg is None else "%s(%s)" % (e.name, show(e.arg))
    if isinstance(e, Quant):
        rng = "%s in %s..%s: %s" % (e.var, show(e.lo), show(e.hi), show(e.body))
        if _is_quantifier(e):
            return "%s %s" % (e.kind, rng)
        return "%s(%s)" % (e.kind, rng)
    raise _Skip()


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------
def _shape(x):
    """structure of an expression without positions and checker types"""
    if isinstance(x, Expr):
        return (type(x).__name__,) + tuple(
            _shape(getattr(x, f.name)) for f in dataclasses.fields(x) if f.name not in ("line", "col", "ty"))
    if isinstance(x, list):
        return tuple(_shape(i) for i in x)
    if isinstance(x, FieldInit):
        return ("FieldInit", x.name, _shape(x.value))
    return x


def _free(e, bound, out):
    """free variable names of e (quantifier variables are bound inside the quantifier body)"""
    if isinstance(e, Var):
        if e.name not in bound:
            out.add(e.name)
    elif isinstance(e, Quant):
        _free(e.lo, bound, out)
        _free(e.hi, bound, out)
        _free(e.body, bound | {e.var}, out)
    else:
        for c in _kids(e):
            _free(c, bound, out)
    return out


def _has_foreign_call(e):
    """True if e contains a Call node other than `len` (user functions, alloc, copy, print, is_some, ...)"""
    if isinstance(e, Call) and e.name != "len":
        return True
    return any(_has_foreign_call(c) for c in _kids(e))


def _assign_stmts(stmts, out):
    """every Assign / IndexAssign / FieldAssign, nested blocks included"""
    for st in stmts:
        if isinstance(st, (Assign, IndexAssign, FieldAssign)):
            out.append(st)
        elif isinstance(st, If):
            _assign_stmts(st.then, out)
            _assign_stmts(st.els, out)
        elif isinstance(st, While):
            _assign_stmts(st.body, out)
        elif isinstance(st, Match):
            for a in st.arms:
                _assign_stmts(a.body, out)
    return out


def _assigned(stmts):
    return set(st.name for st in _assign_stmts(stmts, []))


def _locals(stmts, out):
    """names declared inside the statements (let, match binders): not visible at the loop head"""
    for st in stmts:
        if isinstance(st, Let):
            out.add(st.name)
        elif isinstance(st, If):
            _locals(st.then, out)
            _locals(st.els, out)
        elif isinstance(st, While):
            _locals(st.body, out)
        elif isinstance(st, Match):
            for a in st.arms:
                out.update(a.binders)
                _locals(a.body, out)
    return out


def _init(block, idx, name, skip_index=False):
    """value of `name` at the loop at block[idx]: the nearest earlier let/assign in the same block; None if an
    earlier if/while/match assigns it first or there is none. skip_index: IndexAssign to it is stepped over."""
    for j in range(idx - 1, -1, -1):
        st = block[j]
        if isinstance(st, (Let, Assign)) and st.name == name:
            return st.value
        if skip_index and isinstance(st, IndexAssign) and st.name == name:
            continue
        if isinstance(st, (If, While, Match)) and name in _assigned([st]):
            return None
    return None


def _lit(e):
    """int value of an integer literal (IntLit, or unary minus of one), else None"""
    if isinstance(e, IntLit):
        return e.value
    if isinstance(e, Unary) and e.op == "-" and isinstance(e.operand, IntLit):
        return -e.operand.value
    return None


def _isvar(e, name):
    return isinstance(e, Var) and e.name == name


def _is_len_var(e, M):
    return isinstance(e, Call) and e.name == "len" and len(e.args) == 1 and isinstance(e.args[0], Var) \
        and e.args[0].name not in M


def _invariant_expr(e, M):
    """an expression that the loop does not change (3.1)"""
    if isinstance(e, IntLit):
        return True
    if isinstance(e, Var):
        return e.name not in M
    if _is_len_var(e, M):
        return True
    if isinstance(e, Unary):
        return e.op == "-" and _invariant_expr(e.operand, M)
    if isinstance(e, Binary):
        return e.op in ("+", "-", "*") and _invariant_expr(e.left, M) and _invariant_expr(e.right, M)
    return False


def _conj_terms(e):
    if isinstance(e, Binary) and e.op == "&&":
        return _conj_terms(e.left) + _conj_terms(e.right)
    return [e]


def _elem_ranges(f):
    """{array name: (L, U)} from `forall K in 0..len(x): A && B` requires (first one found per array)"""
    out = {}
    for r in f.requires:
        if not (isinstance(r, Quant) and r.kind == "forall"):
            continue
        if not (isinstance(r.lo, IntLit) and r.lo.value == 0 and isinstance(r.hi, Call) and r.hi.name == "len"
                and len(r.hi.args) == 1 and isinstance(r.hi.args[0], Var)):
            continue
        x = r.hi.args[0].name
        if x in out or not (isinstance(r.body, Binary) and r.body.op == "&&"):
            continue

        def is_elem(e):
            return isinstance(e, Index) and _isvar(e.array, x) and _isvar(e.index, r.var)

        lo = hi = None
        ok = True
        for t in (r.body.left, r.body.right):
            side = None
            if isinstance(t, Binary) and t.op in (">=", "<="):
                lv, rv = _lit(t.right), _lit(t.left)
                if is_elem(t.left) and lv is not None:
                    side = ("lo" if t.op == ">=" else "hi", lv)
                elif is_elem(t.right) and rv is not None:
                    side = ("hi" if t.op == ">=" else "lo", rv)
            if side is None:
                ok = False
            elif side[0] == "lo" and lo is None:
                lo = side[1]
            elif side[0] == "hi" and hi is None:
                hi = side[1]
            else:
                ok = False
        if ok and lo is not None and hi is not None:
            out[x] = (lo, hi)
    return out


_ELEM_NAME = {"array": "i64", "array_u8": "u8", "array_bool": "bool"}


def _elem_name(ty):
    """element kind of an array type: "i64" | "u8" | "bool", "abs" for a G3 [T] (abstract element), else None"""
    if getattr(ty, "name", None) == "array" and getattr(ty, "args", ()):
        return "abs"
    return _ELEM_NAME.get(getattr(ty, "name", None))


def _has_param(ty):
    """does the type mention a type parameter anywhere (T, [T], Option<T>, Pair<T, i64>, ...)"""
    return isinstance(ty, Type) and (ty.owner is not None or any(_has_param(a) for a in ty.args))


def _abstract_expr(e, tenv):
    """G3 A2 (4.8): does the candidate expression read a value whose static type involves a type parameter?
    Decided on typed expressions: checker types on cloned nodes, and the position-based type table for names.
    `len(x)` only reads the length, so it stays allowed for an abstract array."""
    if isinstance(e, Call) and e.name == "len":
        return False
    if isinstance(e, Var) and _has_param(tenv.get(e.name)):
        return True
    if _has_param(getattr(e, "ty", None)):
        return True
    if isinstance(e, Index) and isinstance(e.array, Var) and _has_param(tenv.get(e.array.name)):
        return True
    return any(_abstract_expr(c, tenv) for c in _kids(e))


def _mentions_collection(e, tenv):
    """G6 A1 (G6_SPEC 11.4): does the candidate mention a variable of collection type (Vec/HashMap/String)? Even
    `len(v)` counts: inference never builds candidates about owned collections."""
    if isinstance(e, Move):
        return True
    if isinstance(e, Var):
        t = tenv.get(e.name)
        return t is not None and contains_collection(t)
    return any(_mentions_collection(c, tenv) for c in _kids(e))


def _scope_types(f, w):
    """G3 A2: {name: Type} of the parameters and locals visible at the head of loop `w` (same node object).
    Position-based, same walk rules as _elem_types: a `let` sets the name, if/while/match bodies get a copy of
    the environment, match binders are removed."""
    def walk(stmts, env):
        for st in stmts:
            if st is w:
                return dict(env)
            if isinstance(st, Let):
                env[st.name] = st.type
            elif isinstance(st, If):
                r = walk(st.then, dict(env))
                if r is None:
                    r = walk(st.els, dict(env))
                if r is not None:
                    return r
            elif isinstance(st, While):
                r = walk(st.body, dict(env))
                if r is not None:
                    return r
            elif isinstance(st, Match):
                for a in st.arms:
                    e2 = dict(env)
                    for bn in a.binders:
                        e2.pop(bn, None)
                    r = walk(a.body, e2)
                    if r is not None:
                        return r
        return None

    env0 = {p.name: p.type for p in f.params}
    r = walk(f.body, dict(env0))
    return r if r is not None else env0


def _elem_types(f, w):
    """G2 A5: {array name: "i64" | "u8" | "bool" | "abs"} visible at the head of loop `w` (same node object).
    Position-based: start from the parameters, walk statements in order; an array `let` sets the name, a
    non-array `let` (shadowing) removes it; if/while/match bodies get a copy of the environment and their
    lets do not leak out; match binders are not arrays and are removed. The environment at `w` is returned."""
    out = {}
    for n, t in _scope_types(f, w).items():
        k = _elem_name(t)
        if k is not None:
            out[n] = k
    return out


def _reads_bool_array(e, et):
    """does e contain an Index whose array is a Var naming a [bool] array (G3: or a [T] array of abstract
    elements, "abs"): no element-specific template may read such an element"""
    if isinstance(e, Index) and isinstance(e.array, Var) and et.get(e.array.name) in ("bool", "abs"):
        return True
    return any(_reads_bool_array(c, et) for c in _kids(e))


def _rng(e, ranges, M):
    """(low, high) of a term, or None (3.1 rng)"""
    if isinstance(e, IntLit):
        return (e.value, e.value)
    if isinstance(e, Unary):
        if e.op != "-":
            return None
        r = _rng(e.operand, ranges, M)
        return None if r is None else (-r[1], -r[0])
    if isinstance(e, Index):
        if isinstance(e.array, Var) and e.array.name not in M and e.array.name in ranges:
            return ranges[e.array.name]
        return None
    if isinstance(e, Binary) and e.op in ("+", "-", "*"):
        a, b = _rng(e.left, ranges, M), _rng(e.right, ranges, M)
        if a is None or b is None:
            return None
        if e.op == "+":
            return (a[0] + b[0], a[1] + b[1])
        if e.op == "-":
            return (a[0] - b[1], a[1] - b[0])
        ps = [a[0] * b[0], a[0] * b[1], a[1] * b[0], a[1] * b[1]]
        return (min(ps), max(ps))
    return None


class _B:
    """builds candidate nodes; every node carries the position of the loop (3.4)"""

    def __init__(s, w, kname):
        s.line, s.col, s.k = w.line, w.col, kname

    def lit(s, n):
        if abs(n) > I64_MAX:
            raise _Skip()
        if n < 0:
            return Unary(s.line, s.col, "-", IntLit(s.line, s.col, -n))
        return IntLit(s.line, s.col, n)

    def var(s, n):
        return Var(s.line, s.col, n)

    def bin(s, op, l, r):
        return Binary(s.line, s.col, op, l, r)

    def length(s, n):
        return Call(s.line, s.col, "len", [s.var(n)])

    def index(s, a, i):
        return Index(s.line, s.col, s.var(a), i)

    def quant(s, kind, var, lo, hi, body):
        return Quant(s.line, s.col, kind, var, lo, hi, body)

    def clone(s, e, sub=None):
        """copy of e at the loop position; sub = (name, factory): free occurrences of Var name become factory()"""
        if isinstance(e, Var):
            if sub is not None and e.name == sub[0]:
                return sub[1]()
            return Var(s.line, s.col, e.name)
        if isinstance(e, Quant):
            inner = None if (sub is not None and e.var == sub[0]) else sub
            return Quant(s.line, s.col, e.kind, e.var, s.clone(e.lo, sub), s.clone(e.hi, sub),
                         s.clone(e.body, inner))
        kw = {}
        for f in dataclasses.fields(e):
            if f.name in ("line", "col"):
                continue
            kw[f.name] = s._val(getattr(e, f.name), sub)
        return type(e)(s.line, s.col, **kw)

    def _val(s, x, sub):
        if isinstance(x, Expr):
            return s.clone(x, sub)
        if isinstance(x, list):
            return [s._val(i, sub) for i in x]
        if isinstance(x, FieldInit):
            return FieldInit(s.line, s.col, x.name, s.clone(x.value, sub))
        return x

    def at_k(s, e, v):
        """T[v:=k]"""
        return s.clone(e, (v, lambda: s.var(s.k)))


# ---------------------------------------------------------------------------
# candidate generation (section 3)
# ---------------------------------------------------------------------------
def _gen(f, w, block, idx, kname, ranges):
    """[(kind, text, expr)] for loop w (unsorted, may contain duplicates)"""
    B = _B(w, kname)
    M = _assigned(w.body)
    loc = _locals(w.body, set())
    NS = M | loc
    asg = _assign_stmts(w.body, [])
    out = []
    et = _elem_types(f, w)   # G2 A5: position-based table at loop w
    tenv = _scope_types(f, w)   # G3 A2: position-based type table at loop w

    def add(kind, build):
        try:
            e = build()
            # G3 A2 (4.8): no template may read an abstract value (decided on typed expressions)
            if _abstract_expr(e, tenv):
                return
            if _mentions_collection(e, tenv):    # G6 A1: no candidate about a collection-typed variable
                return
            # G2 A2: kinds 5..14 never read/write an element of a [bool] array
            if kind >= 5 and _reads_bool_array(e, et):
                return
            # soundness: in contract context a call assumes the callee's ensures without checking its
            # requires, so only `len` calls are allowed (dropped before sorting / de-duplication / cap)
            if _has_foreign_call(e):
                return
            out.append((kind, show(e), e))
        except _Skip:
            pass

    def stable(e, v):
        """e mentions v; every other free name is outside M and not declared in the loop body"""
        names = _free(e, set(), set())
        return v in names and not ((names - {v}) & NS)

    def n_of(v, lo):
        if isinstance(lo, IntLit) and lo.value == 0:
            return B.var(v)
        return B.bin("-", B.var(v), B.clone(lo))

    def with_c0(c0, t):
        return t if c0 == 0 else B.bin("+", B.lit(c0), t)

    def coef(c, N):
        if c == 0:
            return B.lit(0)
        if c == 1:
            return N
        return B.bin("*", B.lit(c), N)

    # ---- counters ----
    for v in sorted(M):
        mine = [st for st in asg if st.name == v]
        if len(mine) != 1 or not isinstance(mine[0], Assign):
            continue
        st = mine[0]
        pos = None
        for j, b in enumerate(w.body):
            if b is st:
                pos = j
        if pos is None:
            continue
        val = st.value
        if not (isinstance(val, Binary) and val.op == "+" and _isvar(val.left, v)
                and isinstance(val.right, IntLit) and val.right.value >= 1):
            continue
        lo = _init(block, idx, v)
        if lo is None or not _invariant_expr(lo, M):
            continue
        lov = _lit(lo)

        # kind 1
        add(1, lambda: B.bin("<=", B.clone(lo), B.var(v)))
        # kinds 2, 3: bound expressions of the loop condition
        for t in _conj_terms(w.cond):
            if not isinstance(t, Binary):
                continue
            E = plus1 = None
            if t.op == "<" and _isvar(t.left, v):
                E, plus1 = t.right, False
            elif t.op == ">" and _isvar(t.right, v):
                E, plus1 = t.left, False
            elif t.op == "<=" and _isvar(t.left, v):
                E, plus1 = t.right, True
            elif t.op == ">=" and _isvar(t.right, v):
                E, plus1 = t.left, True
            if E is None or not _invariant_expr(E, M):
                continue

            def up(E=E, plus1=plus1):
                x = B.clone(E)
                return B.bin("+", x, B.lit(1)) if plus1 else x

            add(2, lambda up=up: B.bin("<=", B.var(v), up()))
            if lov is not None:
                add(3, lambda up=up: B.bin("||", B.bin("<=", B.var(v), up()), B.bin("==", B.var(v), B.clone(lo))))

        # ---- accumulating statements before pos(v) ----
        for st2 in w.body[:pos]:
            # plain sum: s = s + T | s = T + s
            if isinstance(st2, Assign):
                acc = _acc(st2)
                if acc is not None:
                    s_name, T = acc
                    c0 = _lit(_init(block, idx, s_name))
                    if (s_name != v and c0 is not None and sum(1 for a in asg if a.name == s_name) == 1
                            and stable(T, v)):
                        add(6, lambda s_name=s_name, T=T, c0=c0: B.bin(
                            "==", B.var(s_name),
                            with_c0(c0, B.quant("sum", kname, B.clone(lo), B.var(v), B.at_k(T, v)))))
                        r = _rng(T, ranges, M)
                        if r is not None:
                            add(11, lambda s_name=s_name, c0=c0, r=r: B.bin(
                                ">=", B.var(s_name), with_c0(c0, coef(r[0], n_of(v, lo)))))
                            add(11, lambda s_name=s_name, c0=c0, r=r: B.bin(
                                "<=", B.var(s_name), with_c0(c0, coef(r[1], n_of(v, lo)))))
            # conditional accumulation / max / min: if X { ... }
            elif isinstance(st2, If) and not st2.els and len(st2.then) == 1 and isinstance(st2.then[0], Assign):
                inner = st2.then[0]
                acc = _acc(inner)
                if acc is not None:
                    s_name, T = acc
                    c0 = _lit(_init(block, idx, s_name))
                    is_count = isinstance(T, IntLit) and T.value == 1
                    if (s_name != v and c0 is not None and sum(1 for a in asg if a.name == s_name) == 1
                            and stable(st2.cond, v) and (is_count or stable(T, v))):
                        if is_count:
                            add(7, lambda s_name=s_name, c0=c0, C=st2.cond: B.bin(
                                "==", B.var(s_name),
                                with_c0(c0, B.quant("count", kname, B.clone(lo), B.var(v), B.at_k(C, v)))))
                            add(11, lambda s_name=s_name, c0=c0: B.bin(">=", B.var(s_name), B.lit(c0)))
                            add(11, lambda s_name=s_name, c0=c0: B.bin(
                                "<=", B.var(s_name), with_c0(c0, n_of(v, lo))))
                        else:
                            r = _rng(T, ranges, M)
                            if r is not None:
                                r = (min(r[0], 0), max(r[1], 0))
                                add(11, lambda s_name=s_name, c0=c0, r=r: B.bin(
                                    ">=", B.var(s_name), with_c0(c0, coef(r[0], n_of(v, lo)))))
                                add(11, lambda s_name=s_name, c0=c0, r=r: B.bin(
                                    "<=", B.var(s_name), with_c0(c0, coef(r[1], n_of(v, lo)))))
                # max / min: if X { m = T; }
                m, T = inner.name, inner.value
                if (m != v and sum(1 for a in asg if a.name == m) == 1 and v in _free(T, set(), set())
                        and not (_free(T, set(), set()) & loc)):
                    kind = _maxmin(st2.cond, m, T)
                    if kind is not None:
                        bs = [lambda: B.clone(lo)]
                        initm = _init(block, idx, m)
                        if lov is not None and lov >= 1 and initm is not None:
                            n1 = lov - 1
                            sub = (v, lambda n1=n1: IntLit(w.line, w.col, n1))
                            if _shape(initm) == _shape(B.clone(T, sub)):
                                bs.append(lambda n1=n1: B.lit(n1))
                        cmp = "<=" if kind == "max" else ">="
                        for bf in bs:
                            add(8, lambda bf=bf, m=m, T=T, kind=kind: B.bin(
                                "==>", B.bin("<", bf(), B.var(v)),
                                B.bin("==", B.var(m), B.quant(kind, kname, bf(), B.var(v), B.at_k(T, v)))))
                            add(9, lambda bf=bf, m=m, T=T, cmp=cmp: B.quant(
                                "forall", kname, bf(), B.var(v), B.bin(cmp, B.at_k(T, v), B.var(m))))
                            add(10, lambda bf=bf, m=m, T=T: B.bin(
                                "==>", B.bin("<", bf(), B.var(v)),
                                B.quant("exists", kname, bf(), B.var(v), B.bin("==", B.at_k(T, v), B.var(m)))))

    # ---- arrays written only by element stores (kinds 4, 5) ----
    for b in sorted(M):
        mine = [st for st in asg if st.name == b]
        if not all(isinstance(st, IndexAssign) for st in mine):
            continue
        init = _init(block, idx, b, True)
        if not isinstance(init, Call):
            continue
        c = None
        if init.name == "alloc" and len(init.args) == 2 and _invariant_expr(init.args[0], M):
            E = init.args[0]
            c = _lit(init.args[1])
        elif init.name == "copy" and len(init.args) == 1 and isinstance(init.args[0], Var) \
                and init.args[0].name not in M:
            E = Call(w.line, w.col, "len", [Var(w.line, w.col, init.args[0].name)])
        else:
            continue
        add(4, lambda b=b, E=E: B.bin("==", B.length(b), B.clone(E)))
        pairs = []
        for src, (lo_, hi_) in ranges.items():
            # G2 A2: use a range only when its source array has the same element type as b (both known)
            if et.get(src) is None or et.get(src) != et.get(b):
                continue
            p = (min(lo_, c), max(hi_, c)) if c is not None else (lo_, hi_)
            if p not in pairs:
                pairs.append(p)
        if not pairs and c is not None:
            pairs.append((c, c))
        for (lo_, hi_) in pairs:
            add(5, lambda b=b, lo_=lo_, hi_=hi_: B.quant(
                "forall", kname, B.lit(0), B.length(b),
                B.bin("&&", B.bin("<=", B.lit(lo_), B.index(b, B.var(kname))),
                      B.bin("<=", B.index(b, B.var(kname)), B.lit(hi_)))))

    # ---- B+ kinds 12, 13, 14 (3.7) ----
    ctr = {}   # CTR: every variable meeting the counter definition of 3.1 -> (pos, lo, step)
    for v in sorted(M):
        mine = [st for st in asg if st.name == v]
        if len(mine) != 1 or not isinstance(mine[0], Assign):
            continue
        pos = None
        for j, b_ in enumerate(w.body):
            if b_ is mine[0]:
                pos = j
        val = mine[0].value
        if pos is None or not (isinstance(val, Binary) and val.op == "+" and _isvar(val.left, v)
                               and isinstance(val.right, IntLit) and val.right.value >= 1):
            continue
        lo0 = _init(block, idx, v)
        if lo0 is None or not _invariant_expr(lo0, M):
            continue
        ctr[v] = (pos, lo0, val.right.value)

    # kind 12: value range of a non-counter scalar that only receives plain assignments
    for v in sorted(M):
        if v in ctr:
            continue
        mine = [st for st in asg if st.name == v]
        if not mine or not all(isinstance(st, Assign) for st in mine):
            continue
        iv = _init(block, idx, v)
        if iv is None:
            continue
        L = U = None
        n = _lit(iv)
        if n is not None:
            L = U = n
        elif isinstance(iv, Var) and iv.name not in M:
            L, U = _srng(f, iv.name)
        elif isinstance(iv, Index) and isinstance(iv.array, Var) and iv.array.name not in M \
                and iv.array.name in ranges:
            L, U = ranges[iv.array.name]
        if L is not None:
            add(12, lambda v=v, L=L: B.bin(">=", B.var(v), B.lit(L)))
        if U is not None:
            add(12, lambda v=v, U=U: B.bin("<=", B.var(v), B.lit(U)))

    for v in sorted(ctr):
        pos, lo, step = ctr[v]
        if step != 1:
            continue
        for st3 in w.body[:pos]:
            # kind 13: output array prefix  b[v] = E;
            if isinstance(st3, IndexAssign) and _isvar(st3.index, v):
                b = st3.name
                mine = [st for st in asg if st.name == b]
                if len(mine) != 1 or mine[0] is not st3:
                    continue
                init = _init(block, idx, b, True)
                if not isinstance(init, Call):
                    continue
                if init.name == "alloc" and len(init.args) == 2 and _invariant_expr(init.args[0], M):
                    pass
                elif init.name == "copy" and len(init.args) == 1 and isinstance(init.args[0], Var) \
                        and init.args[0].name not in M:
                    pass
                else:
                    continue
                E = st3.value
                if (_free(E, set(), set()) - {v}) & NS:
                    continue
                add(13, lambda b=b, E=E, lo=lo, v=v: B.quant(
                    "forall", kname, B.clone(lo), B.var(v),
                    B.bin("==", B.index(b, B.var(kname)), B.at_k(E, v))))
            # kind 14: early-return prefix  if C { return R; }
            elif isinstance(st3, If) and not st3.els and len(st3.then) == 1 \
                    and isinstance(st3.then[0], Return) and stable(st3.cond, v):
                add(14, lambda C=st3.cond, lo=lo, v=v: B.quant(
                    "forall", kname, B.clone(lo), B.var(v),
                    Unary(w.line, w.col, "!", B.at_k(C, v))))
    return out


def _srng(f, p):
    """(low, high) of scalar parameter p from f.requires (3.7 srng); None for a missing side"""
    lo = hi = None
    for r in f.requires:
        for t in _conj_terms(r):
            if not isinstance(t, Binary) or t.op not in (">=", "<=", ">", "<"):
                continue
            if _isvar(t.left, p) and _lit(t.right) is not None:
                c, op = _lit(t.right), t.op
            elif _isvar(t.right, p) and _lit(t.left) is not None:
                # c op p  ->  p (flipped op) c
                c, op = _lit(t.left), {">=": "<=", "<=": ">=", ">": "<", "<": ">"}[t.op]
            else:
                continue
            if op == ">=" and lo is None:
                lo = c
            elif op == ">" and lo is None:
                lo = c + 1
            elif op == "<=" and hi is None:
                hi = c
            elif op == "<" and hi is None:
                hi = c - 1
    return lo, hi


def _acc(st):
    """Assign `s = s + T` / `s = T + s` -> (s, T), else None"""
    val = st.value
    if isinstance(val, Binary) and val.op == "+":
        if _isvar(val.left, st.name):
            return st.name, val.right
        if _isvar(val.right, st.name):
            return st.name, val.left
    return None


def _maxmin(X, m, T):
    """"max" / "min" when X compares T with Var m in a max / min shape, else None"""
    if not isinstance(X, Binary):
        return None
    if _isvar(X.right, m) and _shape(X.left) == _shape(T):
        if X.op in (">", ">="):
            return "max"
        if X.op in ("<", "<="):
            return "min"
    if _isvar(X.left, m) and _shape(X.right) == _shape(T):
        if X.op in ("<", "<="):
            return "max"
        if X.op in (">", ">="):
            return "min"
    return None


def candidates_for_loop(f, w, block, idx, kname, ranges):
    """(sorted, de-duplicated, capped [(kind, text, expr)], generated, capped)"""
    raw = _gen(f, w, block, idx, kname, ranges)
    raw.sort(key=lambda c: (c[0], c[1]))
    seen, uniq = set(), []
    for c in raw:
        if c[1] not in seen:
            seen.add(c[1])
            uniq.append(c)
    cap = INFER_CONFIG["max_candidates"]
    return uniq[:cap], len(uniq), max(0, len(uniq) - cap)


# ---------------------------------------------------------------------------
# Houdini driver (4.1) and report (5)
# ---------------------------------------------------------------------------
class _Loop:
    def __init__(s, n, w, cands, generated, capped):
        s.n, s.w, s.generated, s.capped = n, w, generated, capped
        s.cands = [("L%d#%d" % (n, i), e, text) for i, (_, text, e) in enumerate(cands)]
        # kind number of every first-list candidate (parallel to s.cands); extra() keeps (id, expr, text)
        s.kinds = [k for (k, _, _) in cands]
        s.alive = list(s.cands)
        s.dropped = []

    def restart_v1(s):
        """4.1 version 1 fall-back: alive = the first list restricted to kinds 1..11 (IDs unchanged)"""
        s.alive = [c for c, k in zip(s.cands, s.kinds) if k <= 11]
        s.dropped = []


class InferResult:
    def __init__(s, f, loops):
        s.f, s.loops = f, loops
        s.status = "ok"          # ok | budget_exhausted | timeout
        s.rounds = 0
        s.queries = 0
        s.fallback = False

    def extra(s):
        """{loop number: [(id, expr, text)]} of the surviving candidates; {} when there are none"""
        return {l.n: list(l.alive) for l in s.loops if l.alive}

    def records(s, new_errors):
        """one report record per loop; new_errors = errors of this function's final verification"""
        out = []
        for l in s.loops:
            if l.generated == 0:
                status = "none"
            elif s.status != "ok":
                status = s.status
            else:
                status = "verified" if new_errors == 0 else "selected"
            rec = {
                "fn": s.f.name, "loop": l.n, "line": l.w.line, "col": l.w.col, "status": status,
                "invariants": ["invariant " + text for (_, _, text) in l.alive],
                "generated": l.generated, "capped": l.capped, "kept": len(l.alive),
                "dropped": l.dropped, "rounds": s.rounds, "queries": s.queries}
            if s.f.file is not None:    # G4 A1: explicit mode only (legacy records keep their exact key set)
                rec["file"] = s.f.file
            if s.fallback:
                rec["fallback"] = "v1"
            out.append(rec)
        return out


def infer_function(prog, f, model, rec=None):
    """candidates + Houdini rounds for one function; returns an InferResult (status ok / budget_exhausted /
    timeout). Does not touch any error list."""
    cfg = INFER_CONFIG
    kname = pick_bound_name(_fn_names(f))
    ranges = _elem_ranges(f)
    loops = []
    for n, (w, block, idx) in enumerate(walk_loops(f.body)):
        cands, generated, capped = candidates_for_loop(f, w, block, idx, kname, ranges)
        loops.append(_Loop(n, w, cands, generated, capped))
    res = InferResult(f, loops)
    deadline = time.monotonic() + cfg["max_seconds"]
    probe = Probe(cfg["max_queries"], deadline)
    status, r = _explore(prog, f, model, rec, res, probe, 0)
    res.status, res.rounds, res.queries = status, r, probe.queries
    # 4.1 version 1 fall-back: budget exhausted and a kind >= 12 candidate was in the first lists
    if status == "budget_exhausted" and any(k >= 12 for l in loops for k in l.kinds):
        for l in loops:
            l.restart_v1()
        probe2 = Probe(cfg["max_queries"], deadline)
        status, r = _explore(prog, f, model, rec, res, probe2, r)
        res.fallback = True
        res.status, res.rounds, res.queries = status, r, probe.queries + probe2.queries
    return res


def _explore(prog, f, model, rec, res, probe, r):
    """Houdini rounds (4.1) from round number r+1 on, over the loops' alive lists. Returns (status, last round
    number); on budget exhaustion / timeout every alive list is emptied."""
    cfg = INFER_CONFIG
    loops = res.loops
    status = "ok"
    try:
        while True:
            extra = res.extra()
            if not extra:
                break      # no candidates (left): no round
            r += 1
            probe.begin_round()
            qcfg = QueryConfig(phase="inference", round=r, timeout_ms=cfg["timeout_ms"], rlimit=cfg["rlimit"],
                               seed=cfg["seed"])
            FnVerifier(prog, f, [], model, rec=rec, qcfg=qcfg, extra=extra, probe=probe).run()
            failed = probe.failed
            if not failed:
                break
            for l in loops:
                keep = []
                for c in l.alive:
                    if c[0] in failed:
                        code, st = failed[c[0]]
                        l.dropped.append({"cand": c[0], "text": c[2], "round": r, "code": code,
                                          "status": st})
                    else:
                        keep.append(c)
                l.alive = keep
    except BudgetExhausted:
        status = "budget_exhausted"
        for l in loops:
            l.alive = []
    except InferenceTimeout:
        status = "timeout"
        for l in loops:
            l.alive = []
    return status, r
