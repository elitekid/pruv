"""Pruv verifier: symbolic execution + z3. Proves bounds, overflow, contracts, loops."""
import z3
from vast import *
from typeinfo import TypeTable

I64_MIN, I64_MAX = -2 ** 63, 2 ** 63 - 1
MAX_LEN = 2 ** 40
TIMEOUT_MS = 8000

_o = z3.Datatype("Opt"); _o.declare("some", ("sval", z3.IntSort())); _o.declare("none")
_r = z3.Datatype("Res"); _r.declare("ok", ("oval", z3.IntSort())); _r.declare("err", ("eval", z3.IntSort()))
Opt, Res = z3.CreateDatatypes(_o, _r)

_MODEL_SEQ = [0]


def query_status(result, reason):
    """map a z3 check result (+ reason_unknown) to the trace status vocabulary"""
    if result == z3.unsat:
        return "proved"
    if result == z3.sat:
        return "not_proved"
    if reason in ("timeout", "canceled"):
        return "timeout"
    return "resource_unknown"


class QueryConfig:
    """how one solver query is configured; rlimit/seed None = option not set (no text line either)"""

    def __init__(s, phase="verification", round=None, timeout_ms=TIMEOUT_MS, rlimit=None, seed=None):
        s.phase, s.round, s.timeout_ms, s.rlimit, s.seed = phase, round, timeout_ms, rlimit, seed


class TraceRecorder:
    """official query-recording boundary: one entry per obligation, one attempt per solver check"""

    def __init__(s):
        s.obligations = []

    def begin(s, fn, node, code, skipped, phase, round_, cand):
        entry = {"seq": len(s.obligations), "fn": fn, "line": node.line, "col": node.col, "code": code,
                 "attempts": [], "phase": phase, "round": round_, "cand": cand}
        if skipped:
            entry["skipped"] = True
        s.obligations.append(entry)
        return len(s.obligations) - 1

    def attempt(s, idx, lemmas, smt2, result, status, timeout_ms, rlimit, seed, reason_unknown):
        s.obligations[idx]["attempts"].append({
            "lemmas": lemmas, "smt2": smt2, "result": result, "status": status, "timeout_ms": timeout_ms,
            "rlimit": rlimit, "seed": seed, "reason_unknown": reason_unknown})


class Model:
    """Per-program z3 model of the user structs/enums (G1). Built once in verify_program.
    struct[name] = (constructor, [accessor per field])
    enum[name][variant] = (constructor, recognizer, [accessor per field])
    Every variant has its own constructor, so a value has no inactive payload."""

    def __init__(s, prog):
        s.tt = TypeTable(prog)
        s.sorts = {}
        s.struct = {}
        s.enum = {}
        s.by_sort = {Opt.name(): OPTION, Res.name(): RESULT}
        _MODEL_SEQ[0] += 1
        pre = "m%d" % _MODEL_SEQ[0]
        for idx, d in enumerate(s.tt.order):
            tag = "%st%d!" % (pre, idx)
            dt = z3.Datatype(tag + d.name)
            if isinstance(d, StructDecl):
                dt.declare(tag + d.name, *[(tag + d.name + "." + fd.name, s.sort_of(fd.type)) for fd in d.fields])
                srt = dt.create()
                s.struct[d.name] = (srt.constructor(0), [srt.accessor(0, j) for j in range(len(d.fields))])
            else:
                for v in d.variants:
                    cn = tag + d.name + "::" + v.name
                    dt.declare(cn, *[(cn + "." + fd.name, s.sort_of(fd.type)) for fd in v.fields])
                srt = dt.create()
                s.enum[d.name] = {}
                for i, v in enumerate(d.variants):
                    s.enum[d.name][v.name] = (srt.constructor(i), srt.recognizer(i),
                                              [srt.accessor(i, j) for j in range(len(v.fields))])
            s.sorts[d.name] = srt
            s.by_sort[srt.name()] = Type(d.name)

    def is_user(s, ty):
        return ty.name in s.sorts

    def sort_of(s, ty):
        if ty == I64:
            return z3.IntSort()
        if ty == BOOL:
            return z3.BoolSort()
        if ty == OPTION:
            return Opt
        if ty == RESULT:
            return Res
        return s.sorts[ty.name]

    def type_of(s, v):
        """Pruv Type of a z3 datatype value (Opt/Res/user), or None"""
        try:
            return s.by_sort.get(v.sort().name())
        except Exception:
            return None


def _conj(xs):
    xs = [x for x in xs if x is not None]
    if not xs:
        return None
    return xs[0] if len(xs) == 1 else z3.And(*xs)


def _imp(c, d):
    return None if d is None else z3.Implies(c, d)


_TAG_FNS = ("some_val", "ok_val", "err_val")


def _partial_here(e, kind):
    """is e itself a partial operation of the requested kind (None=any, "variant", "other")"""
    if isinstance(e, VariantField):
        return kind in (None, "variant")
    if kind == "variant":
        return False
    if isinstance(e, Index):
        return True
    if isinstance(e, Binary):
        return e.op in ("/", "%")
    if isinstance(e, Call):
        return e.name in _TAG_FNS
    if isinstance(e, Quant):
        return e.kind in ("max", "min")
    return False


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


def _has_vf(e, kind=None):
    """does the contract expression contain a partial operation (variant_field lookup, or for kind None/"other":
    index, / %, some_val/ok_val/err_val, max/min), i.e. a source of a nontrivial domain"""
    if _partial_here(e, kind):
        return True
    return any(_has_vf(c, kind) for c in _kids(e))


class Arr:
    __slots__ = ("a", "n", "name")

    def __init__(s, a, n, name):
        s.a, s.n, s.name = a, n, name


class State:
    def __init__(s, env, pc):
        s.env, s.pc = env, pc

    def fork(s, extra=None):
        return State(dict(s.env), s.pc + ([extra] if extra is not None else []))


def _occurs(t, c):
    """does z3 constant c appear in term t"""
    seen, todo = set(), [t]
    while todo:
        n = todo.pop()
        i = n.get_id()
        if i in seen:
            continue
        seen.add(i)
        if z3.is_const(n) and n.eq(c):
            return True
        if z3.is_quantifier(n):
            todo.append(n.body())
        else:
            todo.extend(n.children())
    return False


def in_range(x):
    return z3.And(x >= I64_MIN, x <= I64_MAX)


FIX = {
    "index_oob": "add a requires/invariant/if that bounds the index, e.g. `invariant 0 <= i && i <= len(a)`",
    "overflow": "bound the operands with requires (element ranges, len(a) <= N) and loop invariants on accumulators",
    "div": "prove divisor > 0 and dividend >= 0 (add an if or requires)",
    "alloc_negative": "prove 0 <= length <= 2^40",
    "call_requires": "make the callee's requires hold before the call",
    "ensures": "fix the code, or strengthen loop invariants so the postcondition follows",
    "assert": "strengthen invariants or fix the code",
    "refinement_init": "make the initial value satisfy the declared range/length, or widen the refinement; it is a proof obligation, not a run-time check",
    "refinement_assign": "make the stored value satisfy the declared range, or widen the refinement; a loop that updates it needs invariants that imply the range",
    "invariant_entry": "the invariant must hold before the first iteration; check initial values",
    "invariant_preserved": "the invariant must hold again after one body iteration; add facts it depends on as more invariants",
    "decreases_nonneg": "the decreases expression must be >= 0 whenever the loop condition holds; add an invariant",
    "decreases_decrease": "the decreases expression must strictly decrease each iteration",
    "variant_domain": "guard the lookup so it is only reached for that variant, e.g. `is_variant(e, E::V) && variant_field(e, E::V, f) > 0` or `!is_variant(e, E::V) || ...`",
    "contract_domain": "guard the partial operation earlier in the same contract or in an earlier clause: index range, divisor != 0, is_some/is_ok before some_val/ok_val/err_val, lo < hi before max/min",
}


class FnVerifier:
    def __init__(s, prog, f, errors, model=None, rec=None, qcfg=None):
        s.rec = rec
        s.qcfg = qcfg if qcfg is not None else QueryConfig()
        s.funcs = {g.name: g for g in prog.functions}
        s.model = model if model is not None else Model(prog)
        s.f, s.errors = f, errors
        s.k = 0
        s.seen = set()
        s.qstack = []
        s.aggs = {}
        s.lemmas = []
        s.lemma_keys = set()

    def fresh(s, base, ty):
        s.k += 1
        n = "%s!%d" % (base, s.k)
        if ty == I64:
            return z3.Int(n)
        if ty == BOOL:
            return z3.Bool(n)
        if ty == OPTION:
            return z3.Const(n, Opt)
        if ty == RESULT:
            return z3.Const(n, Res)
        if ty == ARRAY:
            return Arr(z3.Array(n, z3.IntSort(), z3.IntSort()), z3.Int(n + ".len"), base)
        if s.model.is_user(ty):
            return z3.Const(n, s.model.sorts[ty.name])
        raise Exception("fresh: " + ty.name)

    # ---------- value domain ----------
    def wf(s, ty, v):
        """well_formed(ty, v): every active leaf is an i64. None when trivially true."""
        if ty == I64:
            return in_range(v)
        if ty == OPTION:
            return z3.Implies(Opt.is_some(v), in_range(Opt.sval(v)))
        if ty == RESULT:
            return z3.And(z3.Implies(Res.is_ok(v), in_range(Res.oval(v))),
                          z3.Implies(Res.is_err(v), in_range(Res.eval(v))))
        m = s.model
        if m.tt.is_struct(ty) and ty.name in m.struct:
            accs = m.struct[ty.name][1]
            return _conj([s.wf(fd.type, acc(v)) for fd, acc in zip(m.tt.fields(ty), accs)])
        if m.tt.is_enum(ty) and ty.name in m.enum:
            parts = []
            for vd in m.tt.decl(ty).variants:
                _, rec, accs = m.enum[ty.name][vd.name]
                w = _conj([s.wf(fd.type, acc(v)) for fd, acc in zip(vd.fields, accs)])
                if w is not None:
                    parts.append(z3.Implies(rec(v), w))
            return _conj(parts)
        return None

    def rebuild(s, ty, cur, path, new):
        """struct value `cur` of type ty with the field path replaced by `new`"""
        if not path:
            return new
        m = s.model
        i = m.tt.field_index(ty, path[0])
        ctor, accs = m.struct[ty.name]
        vals = [acc(cur) for acc in accs]
        vals[i] = s.rebuild(m.tt.fields(ty)[i].type, vals[i], path[1:], new)
        return ctor(*vals)

    # ---------- obligations ----------
    def prove(s, st, g, ob, node, code, what, key_extra=None, cand=None):
        key = (node.line, node.col, code) if key_extra is None else (node.line, node.col, code, key_extra)
        skipped = key in s.seen
        idx = None
        if s.rec is not None:
            idx = s.rec.begin(s.f.name, node, code, skipped, s.qcfg.phase, s.qcfg.round, cand)
        if skipped:
            return
        def run(with_lemmas):
            cfg = s.qcfg
            sol = z3.Solver()
            sol.set("timeout", cfg.timeout_ms)
            if cfg.rlimit is not None:
                sol.set("rlimit", cfg.rlimit)
            if cfg.seed is not None:
                sol.set("random_seed", cfg.seed)
            for p in st.pc:
                sol.add(p)
            for p in g:
                sol.add(p)
            if with_lemmas:
                for p in s.lemmas:
                    sol.add(p)
            sol.add(z3.Not(ob))
            text = None
            if s.rec is not None:
                text = "(set-option :timeout %d)\n" % cfg.timeout_ms
                if cfg.rlimit is not None:
                    text += "(set-option :rlimit %d)\n" % cfg.rlimit
                if cfg.seed is not None:
                    text += "(set-option :random_seed %d)\n" % cfg.seed
                text += sol.sexpr()
            try:
                r = sol.check()
            except z3.Z3Exception as e:
                if s.rec is not None:
                    s.rec.attempt(idx, with_lemmas, text, "error", "error", cfg.timeout_ms, cfg.rlimit,
                                  cfg.seed, str(e))
                raise
            if s.rec is not None:
                reason = sol.reason_unknown() if r == z3.unknown else None
                s.rec.attempt(idx, with_lemmas, text, str(r), query_status(r, reason), cfg.timeout_ms,
                              cfg.rlimit, cfg.seed, reason)
            return sol, r

        # first without aggregate lemmas: fewer assumptions, so unsat here is still a sound proof,
        # and it keeps quantified lemmas out of the many obligations that never need them
        sol, r = run(False)
        if r == z3.unsat:
            return
        relaxed = None
        if s.lemmas:
            if r == z3.sat:
                relaxed = s.cex(sol.model(), st)
            sol, r = run(True)
            if r == z3.unsat:
                return
        s.seen.add(key)
        cex = None
        if r == z3.sat or relaxed is not None:
            cex = s.cex(sol.model(), st) if r == z3.sat else dict(relaxed, _note="counterexample ignores aggregate (sum/count/max/min) definitions; retry with them: %s" % sol.reason_unknown())
            code2, msg = code, "cannot prove %s in %s" % (what, s.f.name)
        else:
            code2, msg = "verify_unknown", "solver gave up proving %s in %s (%s)" % (what, s.f.name, sol.reason_unknown())
        s.errors.append(PruvError("verify", node.line, node.col, code2, msg, FIX.get(code, ""), cex))

    def cex(s, m, st):
        out = {}
        for name, v in st.env.items():
            try:
                if isinstance(v, Arr):
                    n = m.eval(v.n, model_completion=True).as_long()
                    els = [m.eval(z3.Select(v.a, i), model_completion=True).as_long() for i in range(min(max(n, 0), 8))]
                    out[name] = {"len": n, "first": els}
                elif z3.is_int(v):
                    out[name] = m.eval(v, model_completion=True).as_long()
                elif z3.is_bool(v):
                    out[name] = z3.is_true(m.eval(v, model_completion=True))
                else:
                    out[name] = s.fmt_val(m.eval(v, model_completion=True))
            except Exception:
                pass
        return out

    def fmt_val(s, v):
        """z3 model value -> Pruv syntax on one line (user struct/enum); unknown shapes keep z3's str()"""
        try:
            if z3.is_int_value(v):
                return str(v.as_long())
            if z3.is_bool(v):
                return "true" if z3.is_true(v) else "false"
            ty = s.model.type_of(v)
            if ty is None or not s.model.is_user(ty) or not z3.is_app(v):
                return str(v)
            dn = v.decl().name()
            kids = [s.fmt_val(c) for c in v.children()]
            if ty.name in s.model.struct:
                ctor, _ = s.model.struct[ty.name]
                decl = next((d for d in s.model.tt.order if d.name == ty.name), None)
                if ctor.name() == dn and decl is not None and len(decl.fields) == len(kids):
                    if not kids:
                        return ty.name
                    return "%s { %s }" % (ty.name, ", ".join(
                        "%s: %s" % (fd.name, k) for fd, k in zip(decl.fields, kids)))
            elif ty.name in s.model.enum:
                for vn, (ctor, _, _) in s.model.enum[ty.name].items():
                    if ctor.name() == dn:
                        if not kids:
                            return "%s::%s" % (ty.name, vn)
                        return "%s::%s(%s)" % (ty.name, vn, ", ".join(kids))
            return str(v)
        except Exception:
            return str(v)

    def assume(s, st, g, fact):
        """add a fact that only holds on the short-circuit path g"""
        st.pc.append(z3.Implies(z3.And(*g), fact) if g else fact)

    # ---------- expressions ----------
    def ev(s, e, st, g, code, env=None):
        """code=True: emit proof obligations and i64 semantics. env overrides st.env (contracts)."""
        env = st.env if env is None else env
        if isinstance(e, IntLit):
            return z3.IntVal(e.value)
        if isinstance(e, BoolLit):
            return z3.BoolVal(e.value)
        if isinstance(e, Var):
            return env[e.name]
        if isinstance(e, Unary):
            v = s.ev(e.operand, st, g, code, env)
            if e.op == "!":
                return z3.Not(v)
            if code:
                s.prove(st, g, in_range(-v), e, "overflow", "no overflow in unary -")
            return -v
        if isinstance(e, Binary):
            op = e.op
            if op in ("&&", "||", "==>"):
                l = s.ev(e.left, st, g, code, env)
                g2 = g + [l if op != "||" else z3.Not(l)]
                r = s.ev(e.right, st, g2, code, env)
                return z3.And(l, r) if op == "&&" else z3.Or(l, r) if op == "||" else z3.Implies(l, r)
            l = s.ev(e.left, st, g, code, env)
            r = s.ev(e.right, st, g, code, env)
            if op == "+": res = l + r
            elif op == "-": res = l - r
            elif op == "*": res = l * r
            elif op in ("/", "%"):
                if code:
                    s.prove(st, g, z3.And(r > 0, l >= 0), e, "div", "divisor > 0 and dividend >= 0")
                return l / r if op == "/" else l % r
            elif op == "==": return l == r
            elif op == "!=": return l != r
            elif op == "<": return l < r
            elif op == "<=": return l <= r
            elif op == ">": return l > r
            elif op == ">=": return l >= r
            if code:
                s.prove(st, g, in_range(res), e, "overflow", "no i64 overflow in `%s`" % op)
            return res
        if isinstance(e, Index):
            arr = s.ev(e.array, st, g, code, env)
            i = s.ev(e.index, st, g, code, env)
            if code:
                s.prove(st, g, z3.And(i >= 0, i < arr.n), e, "index_oob",
                        "index in bounds for %s[...]" % arr.name)
            v = z3.Select(arr.a, i)
            if code:
                s.assume(st, g, in_range(v))
            return v
        if isinstance(e, Ctor):
            if e.name == "None":
                return Opt.none
            v = s.ev(e.arg, st, g, code, env)
            return {"Some": Opt.some, "Ok": Res.ok, "Err": Res.err}[e.name](v)
        if isinstance(e, Quant):
            lo = s.ev(e.lo, st, g, False, env)
            hi = s.ev(e.hi, st, g, False, env)
            s.k += 1
            k = z3.Int("%s!q%d" % (e.var, s.k))
            env2 = dict(env); env2[e.var] = k
            s.qstack.append(k)
            try:
                body = s.ev(e.body, st, g, False, env2)
            finally:
                s.qstack.pop()
            if e.kind in ("sum", "count", "max", "min"):
                return s.aggregate(e.kind, k, lo, hi, body)
            rng = z3.And(k >= lo, k < hi)
            if e.kind == "forall":
                return z3.ForAll([k], z3.Implies(rng, body))
            return z3.Exists([k], z3.And(rng, body))
        if isinstance(e, Call):
            return s.call(e, st, g, code, env)
        if isinstance(e, StructLit):
            vals = [s.ev(fi.value, st, g, code, env) for fi in e.fields]
            return s.model.struct[e.name][0](*vals)
        if isinstance(e, EnumCtor):
            vals = [s.ev(a, st, g, code, env) for a in e.args]
            return s.model.enum[e.enum_name][e.variant][0](*vals)
        if isinstance(e, FieldAccess):
            v = s.ev(e.base, st, g, code, env)
            ty = s.model.type_of(v)
            return s.model.struct[ty.name][1][s.model.tt.field_index(ty, e.field)](v)
        if isinstance(e, IsVariant):
            v = s.ev(e.value, st, g, code, env)
            return s.model.enum[e.enum_name][e.variant][1](v)
        if isinstance(e, VariantField):
            v = s.ev(e.value, st, g, code, env)
            ety = Type(e.enum_name)
            return s.model.enum[e.enum_name][e.variant][2][s.model.tt.field_index(ety, e.field, e.variant)](v)
        raise Exception("ev: %r" % e)

    # ---------- contract domain of variant_field lookups ----------
    def dom(s, e, st, g, env, kind=None):
        """D(e): z3 condition under which every partial operation in contract e is defined (index in range,
        divisor != 0, some_val/ok_val/err_val on the right tag, variant_field on the named variant, max/min range
        non-empty), following the short-circuit order. kind: None=all, "variant"=variant_field only,
        "other"=the rest. None means trivially true."""
        if not _has_vf(e, kind):
            return None
        wo = kind in (None, "other")
        wv = kind in (None, "variant")
        if isinstance(e, Unary):
            return s.dom(e.operand, st, g, env, kind)
        if isinstance(e, Binary):
            dl = s.dom(e.left, st, g, env, kind)
            if e.op in ("&&", "||", "==>"):
                l = s.ev(e.left, st, g, False, env)
                dr = s.dom(e.right, st, g, env, kind)
                guard = z3.Not(l) if e.op == "||" else l
                return _conj([dl, _imp(guard, dr)])
            parts = [dl, s.dom(e.right, st, g, env, kind)]
            if wo and e.op in ("/", "%"):
                parts.append(s.ev(e.right, st, g, False, env) != 0)
            return _conj(parts)
        if isinstance(e, Index):
            parts = [s.dom(e.array, st, g, env, kind), s.dom(e.index, st, g, env, kind)]
            if wo:
                arr = s.ev(e.array, st, g, False, env)
                i = s.ev(e.index, st, g, False, env)
                parts.append(z3.And(i >= 0, i < arr.n))
            return _conj(parts)
        if isinstance(e, Ctor):
            return s.dom(e.arg, st, g, env, kind)
        if isinstance(e, Call):
            parts = [s.dom(a, st, g, env, kind) for a in e.args]
            if wo and e.name in _TAG_FNS:
                v = s.ev(e.args[0], st, g, False, env)
                parts.append(Opt.is_some(v) if e.name == "some_val" else
                             Res.is_ok(v) if e.name == "ok_val" else z3.Not(Res.is_ok(v)))
            return _conj(parts)
        if isinstance(e, StructLit):
            return _conj([s.dom(fi.value, st, g, env, kind) for fi in e.fields])
        if isinstance(e, EnumCtor):
            return _conj([s.dom(a, st, g, env, kind) for a in e.args])
        if isinstance(e, FieldAccess):
            return s.dom(e.base, st, g, env, kind)
        if isinstance(e, IsVariant):
            return s.dom(e.value, st, g, env, kind)
        if isinstance(e, VariantField):
            inner = s.dom(e.value, st, g, env, kind)
            if not wv:
                return inner
            v = s.ev(e.value, st, g, False, env)
            return _conj([inner, s.model.enum[e.enum_name][e.variant][1](v)])
        if isinstance(e, Quant):
            lo = s.ev(e.lo, st, g, False, env)
            hi = s.ev(e.hi, st, g, False, env)
            outer = [s.dom(e.lo, st, g, env, kind), s.dom(e.hi, st, g, env, kind)]
            if wo and e.kind in ("max", "min"):
                outer.append(lo < hi)
            outer = _conj(outer)
            s.k += 1
            k = z3.Int("%s!dk%d" % (e.var, s.k))
            envk = dict(env); envk[e.var] = k
            s.qstack.append(k)
            try:
                dbody = s.dom(e.body, st, g, envk, kind)
            finally:
                s.qstack.pop()
            if dbody is None:
                return outer
            rng = z3.And(k >= lo, k < hi)
            if e.kind in ("forall", "exists"):
                # the body at k is evaluated only if every earlier body was true (forall) / false (exists)
                j = z3.Int("%s!dj%d" % (e.var, s.k))
                envj = dict(env); envj[e.var] = j
                s.qstack.append(j)
                try:
                    bj = s.ev(e.body, st, g, False, envj)
                finally:
                    s.qstack.pop()
                prior = z3.ForAll([j], z3.Implies(z3.And(j >= lo, j < k), bj if e.kind == "forall" else z3.Not(bj)))
                rng = z3.And(rng, prior)
            return _conj([outer, z3.ForAll([k], z3.Implies(rng, dbody))])
        return None

    def dom_obligations(s, e, st, g, env):
        """[(D, code)]: variant_field lookups -> variant_domain, other partial operations -> contract_domain.
        Trivial domains (no partial op, or simplify to True) give no entry, hence no query."""
        out = []
        for kind, code in (("variant", "variant_domain"), ("other", "contract_domain")):
            if not _has_vf(e, kind):
                continue
            d = s.dom(e, st, g, env, kind)
            if d is None or z3.is_true(z3.simplify(d)):
                continue
            out.append((d, code))
        return out

    def check_dom(s, st, g, e, node, what, env=None):
        """prove D(e) separately per code (variant_domain / contract_domain); returns the proven domains"""
        obs = s.dom_obligations(e, st, g, st.env if env is None else env)
        for d, code in obs:
            s.prove(st, g, d, node, code, what if code == "variant_domain" else what.replace(
                "variant_field lookups", "partial operations (index, /, %, some_val/ok_val/err_val, max/min)"))
        return [d for d, _ in obs]

    def aggregate(s, kind, k, lo, hi, T):
        """sum/count/max/min over lo<=k<hi as an uninterpreted F(lo, hi, *outer) plus unfolding lemmas."""
        outer = [c for c in s.qstack if _occurs(T, c)]
        K0 = z3.Int("agg!k")
        Ps = [z3.Int("agg!p%d" % i) for i in range(len(outer))]
        Tc = z3.substitute(T, (k, K0), *[(o, p) for o, p in zip(outer, Ps)])
        key = (kind, Tc.sexpr(), len(outer))
        if key not in s.aggs:
            F = z3.Function("agg!%s%d" % (kind, len(s.aggs)), z3.IntSort(), z3.IntSort(),
                            *([z3.IntSort()] * len(outer)), z3.IntSort())
            s.aggs[key] = F
        F = s.aggs[key]

        def body_at(x):
            return z3.substitute(Tc, (K0, x), *[(p, o) for p, o in zip(Ps, outer)])

        def val(x):
            return z3.If(body_at(x), 1, 0) if kind == "count" else body_at(x)

        def comb(smaller, x, empty):
            # aggregate of (smaller range) extended by element x; `empty`: the smaller range is empty
            if kind in ("sum", "count"):
                return z3.If(empty, 0, smaller) + val(x)
            better = (smaller >= val(x)) if kind == "max" else (smaller <= val(x))
            return z3.If(empty, val(x), z3.If(better, smaller, val(x)))

        if (kind, F) not in s.lemma_keys:
            # empty range: sum/count are 0 (no new terms, so no matching loop)
            s.lemma_keys.add((kind, F))
            if kind in ("sum", "count"):
                x, y = z3.Ints("agg!x agg!y")
                os_ = list(z3.Ints(" ".join("agg!o%d" % i for i in range(len(outer))))) if outer else []
                fa = F(x, y, *os_)
                s.lemmas.append(z3.ForAll([x, y] + os_, z3.Implies(y <= x, fa == 0), patterns=[fa]))

        app = F(lo, hi, *outer)
        facts = []
        if kind == "count":
            facts.append(z3.Implies(lo < hi, z3.And(app >= 0, app <= hi - lo)))
        bound_lo = [c for c in s.qstack if _occurs(lo, c)]
        bound_hi = [c for c in s.qstack if _occurs(hi, c)]
        # unfold only by moving an unbound end, so a quantified lemma never re-matches its own output
        if not bound_hi:
            facts.append(z3.Implies(lo < hi, app == comb(F(lo, hi - 1, *outer), hi - 1, hi - 1 <= lo)))
            facts.append(z3.Implies(lo <= hi, F(lo, hi + 1, *outer) == comb(app, hi, hi <= lo)))
        if not bound_lo:
            facts.append(z3.Implies(lo < hi, app == comb(F(lo + 1, hi, *outer), lo, hi <= lo + 1)))
            facts.append(z3.Implies(lo <= hi, F(lo - 1, hi, *outer) == comb(app, lo - 1, hi <= lo)))
        if facts:
            L = z3.And(*facts)
            bs = [c for c in s.qstack if any(c.eq(o) for o in outer) or _occurs(lo, c) or _occurs(hi, c)]
            if bs:
                L = z3.ForAll(bs, L, patterns=[app])
            lk = L.sexpr()
            if lk not in s.lemma_keys:
                s.lemma_keys.add(lk)
                s.lemmas.append(L)
        return app

    def call(s, e, st, g, code, env):
        n = e.name
        args = [s.ev(a, st, g, code, env) for a in e.args]
        if n == "len":
            return args[0].n
        if n == "alloc":
            s.prove(st, g, z3.And(args[0] >= 0, args[0] <= MAX_LEN), e, "alloc_negative",
                    "alloc length in 0..2^40")
            s.k += 1
            return Arr(z3.K(z3.IntSort(), args[1]), args[0], "alloc")
        if n == "copy":
            return Arr(args[0].a, args[0].n, "copy")
        if n == "print":
            return None
        if n == "is_some": return Opt.is_some(args[0])
        if n == "some_val": return Opt.sval(args[0])
        if n == "is_ok": return Res.is_ok(args[0])
        if n == "ok_val": return Res.oval(args[0])
        if n == "err_val": return Res.eval(args[0])
        f = s.funcs[n]
        cenv = {p.name: a for p, a in zip(f.params, args)}
        if code:
            # No domain proof of callee requires here: the callee's own run() already proved
            # D(r) under "param wf + earlier requires (values and variant domains)"; the call site
            # proves each earlier requires value and the args satisfy wf, so it would be redundant.
            for r in f.requires:
                ob = s.ev(r, st, g, False, cenv)
                s.prove(st, g, ob, e, "call_requires", "precondition of %s (line %d)" % (n, r.line))
        if f.ret == UNIT:
            return None
        res = s.fresh("ret_" + n, f.ret)
        if isinstance(res, Arr):
            s.assume(st, g, z3.And(res.n >= 0, res.n <= MAX_LEN))
        else:
            w = s.wf(f.ret, res)
            if w is not None:
                s.assume(st, g, w)
        cenv["result"] = res
        for en in f.ensures:
            s.assume(st, g, s.ev(en, st, g, False, cenv))
        return res

    # ---------- statements ----------
    def ensures_ok(s, st, val, node):
        env = dict(st.env)
        for p in s.f.params:
            env[p.name] = s.params[p.name]
        if val is not None:
            env["result"] = val
        prev = []   # earlier clauses (domain + value) were proven above and may justify later lookups
        for en in s.f.ensures:
            prev.extend(s.check_dom(st, prev, en, node, "variant_field lookups in postcondition (line %d) are defined" % en.line, env))
            ob = s.ev(en, st, [], False, env)
            s.prove(st, [], ob, node, "ensures", "postcondition (line %d)" % en.line)
            prev.append(ob)

    def exec_block(s, stmts, st):
        states = [st]
        for stmt in stmts:
            nxt = []
            for cur in states:
                nxt.extend(s.exec(stmt, cur))
            states = nxt
            if not states:
                break
        return states

    def assigned(s, stmts, out):
        for st in stmts:
            if isinstance(st, (Assign, IndexAssign, FieldAssign)):
                out.add(st.name)
            elif isinstance(st, If):
                s.assigned(st.then, out); s.assigned(st.els, out)
            elif isinstance(st, While):
                s.assigned(st.body, out)
            elif isinstance(st, Match):
                for a in st.arms:
                    s.assigned(a.body, out)
        return out

    def havoc(s, st, names):
        h = st.fork()
        for n in sorted(names):
            if n not in h.env:
                continue
            old = h.env[n]
            if isinstance(old, Arr):
                nv = s.fresh(n, ARRAY)
                h.pc.append(z3.And(nv.n >= 0, nv.n <= MAX_LEN))
                h.env[n] = nv
            elif z3.is_int(old):
                nv = s.fresh(n, I64)
                h.pc.append(in_range(nv))
                h.env[n] = nv
            elif z3.is_bool(old):
                h.env[n] = s.fresh(n, BOOL)
            else:
                nv = z3.Const("%s!h%d" % (n, s.k), old.sort()); s.k += 1
                h.env[n] = nv
                ty = s.model.type_of(old)
                if ty is not None:
                    w = s.wf(ty, nv)
                    if w is not None:
                        h.pc.append(w)
        return h

    def exec(s, stmt, st):
        if isinstance(stmt, Let) or isinstance(stmt, Assign):
            st = st.fork()
            v = s.ev(stmt.value, st, [], True)
            if isinstance(v, Arr):
                v = Arr(v.a, v.n, stmt.name)
            st.env[stmt.name] = v
            return [st]
        if isinstance(stmt, IndexAssign):
            st = st.fork()
            arr = st.env[stmt.name]
            i = s.ev(stmt.index, st, [], True)
            v = s.ev(stmt.value, st, [], True)
            s.prove(st, [], z3.And(i >= 0, i < arr.n), stmt, "index_oob", "index in bounds for %s[...] =" % stmt.name)
            if stmt.elem_refine is not None:
                # refine.py: the stored value (already evaluated) must lie in the element range. One query, no
                # domain check, no re-evaluation, no forall; not assumed afterwards (it is implied by the path).
                lo, hi, what = stmt.elem_refine
                s.prove(st, [], z3.And(v >= lo, v <= hi), stmt, "refinement_assign", what, what)
            st.env[stmt.name] = Arr(z3.Store(arr.a, i, v), arr.n, stmt.name)
            return [st]
        if isinstance(stmt, If):
            st = st.fork()
            c = s.ev(stmt.cond, st, [], True)
            return s.exec_block(stmt.then, st.fork(c)) + s.exec_block(stmt.els, st.fork(z3.Not(c)))
        if isinstance(stmt, Match):
            st = st.fork()
            v = s.ev(stmt.scrutinee, st, [], True)
            outer = set(st.env)
            out = []
            for a in stmt.arms:
                if a.enum_name is not None:
                    ety = Type(a.enum_name)
                    _, rec, accs = s.model.enum[a.enum_name][a.ctor]
                    cond = rec(v)
                    vals = [acc(v) for acc in accs]
                    ftys = [fd.type for fd in s.model.tt.fields(ety, a.ctor)]
                else:
                    if a.ctor == "Some": cond, val = Opt.is_some(v), Opt.sval(v)
                    elif a.ctor == "None": cond, val = Opt.is_none(v), None
                    elif a.ctor == "Ok": cond, val = Res.is_ok(v), Res.oval(v)
                    else: cond, val = Res.is_err(v), Res.eval(v)
                    vals = [] if val is None else [val]
                    ftys = [I64] * len(vals)
                b = st.fork(cond)
                for name, val, fty in zip(a.binders, vals, ftys):
                    b.env[name] = val
                    w = s.wf(fty, val)
                    if w is not None:
                        b.pc.append(w)
                for end in s.exec_block(a.body, b):
                    # binders and arm locals end with the arm; only updates to outer variables remain
                    for k in [k for k in end.env if k not in outer]:
                        del end.env[k]
                    out.append(end)
            return out
        if isinstance(stmt, FieldAssign):
            st = st.fork()
            v = s.ev(stmt.value, st, [], True)          # rhs first, on the state before the store
            root = st.env[stmt.name]
            st.env[stmt.name] = s.rebuild(s.model.type_of(root), root, stmt.fields, v)
            return [st]
        if isinstance(stmt, Return):
            st = st.fork()
            v = s.ev(stmt.value, st, [], True) if stmt.value is not None else None
            s.ensures_ok(st, v, stmt)
            return []
        if isinstance(stmt, Assert):
            s.check_dom(st, [], stmt.cond, stmt, "variant_field lookups in assertion are defined")
            ob = s.ev(stmt.cond, st, [], False)
            if stmt.origin_code is None:
                s.prove(st, [], ob, stmt, "assert", "assertion")
            else:
                # synthesized by refine.py: own code and a source description; the description also keys
                # the duplicate suppression, so different sites of one annotation are all reported
                s.prove(st, [], ob, stmt, stmt.origin_code, stmt.origin_what, stmt.origin_what)
            st = st.fork(ob)
            return [st]
        if isinstance(stmt, ExprStmt):
            st = st.fork()
            s.ev(stmt.expr, st, [], True)
            return [st]
        if isinstance(stmt, While):
            return s.loop(stmt, st)
        raise Exception("exec: %r" % stmt)

    def loop(s, w, st):
        prev = []   # invariants run in order: an earlier one (proven here) may justify a later one's lookups
        for inv in w.invariants:
            prev.extend(s.check_dom(st, prev, inv, inv, "variant_field lookups in loop invariant (entry) are defined"))
            ob = s.ev(inv, st, [], False)
            s.prove(st, [], ob, inv, "invariant_entry", "loop invariant on entry")
            prev.append(ob)
        names = s.assigned(w.body, set())
        # one arbitrary iteration; the invariants held (and were defined) at its start
        b = s.havoc(st, names)
        for inv in w.invariants:
            d = s.dom(inv, b, [], b.env, "variant")
            if d is not None:
                b.pc.append(d)
            b.pc.append(s.ev(inv, b, [], False))
        c = s.ev(w.cond, b, [], True)
        b.pc.append(c)
        s.check_dom(b, [], w.decreases, w.decreases, "variant_field lookups in decreases are defined")
        d0 = s.ev(w.decreases, b, [], False)
        s.prove(b, [], d0 >= 0, w.decreases, "decreases_nonneg", "decreases >= 0")
        for end in s.exec_block(w.body, b):
            prev = []
            for inv in w.invariants:
                prev.extend(s.check_dom(end, prev, inv, inv, "variant_field lookups in loop invariant (preserved) are defined"))
                ob = s.ev(inv, end, [], False)
                s.prove(end, [], ob, inv, "invariant_preserved", "loop invariant preserved")
                prev.append(ob)
            if _has_vf(w.decreases):
                # decreases is read at the end of the body: the invariants just proved may justify its lookups
                extra = []
                for inv in w.invariants:
                    d = s.dom(inv, end, [], end.env)
                    if d is not None:
                        extra.append(d)
                    extra.append(s.ev(inv, end, [], False))
                s.check_dom(end, extra, w.decreases, w.decreases, "variant_field lookups in decreases are defined")
            s.prove(end, [], s.ev(w.decreases, end, [], False) < d0, w.decreases, "decreases_decrease",
                    "decreases strictly decreases")
        # after the loop
        a = s.havoc(st, names)
        for inv in w.invariants:
            d = s.dom(inv, a, [], a.env, "variant")
            if d is not None:
                a.pc.append(d)
            a.pc.append(s.ev(inv, a, [], False))
        c = s.ev(w.cond, a, [], True)
        a.pc.append(z3.Not(c))
        return [a]

    def run(s):
        f = s.f
        env, pc = {}, []
        for p in f.params:
            v = s.fresh(p.name, p.type) if p.type != ARRAY else s.fresh(p.name, ARRAY)
            if isinstance(v, Arr):
                v.name = p.name
                pc.append(z3.And(v.n >= 0, v.n <= MAX_LEN))
            else:
                w = s.wf(p.type, v)
                if w is not None:
                    pc.append(w)
            env[p.name] = v
        s.params = dict(env)
        st = State(env, pc)
        for r in f.requires:
            # D(r) is proven from the earlier requires only, then D(r) && r is assumed, in declaration order
            s.check_dom(st, [], r, r, "variant_field lookups in requires (line %d) are defined" % r.line)
            # assume only the variant_field part of D(r) (as before): the other domains are proven above but not
            # assumed, since nested quantified index ranges in every later query made p06 ~150x slower
            d = s.dom(r, st, [], st.env, "variant")
            if d is not None:
                st.pc.append(d)
            st.pc.append(s.ev(r, st, [], False))
        for end in s.exec_block(f.body, st):
            if f.ret == UNIT:
                s.ensures_ok(end, None, f)


def verify_program(prog, rec=None):
    errors = []
    model = Model(prog)
    for f in prog.functions:
        FnVerifier(prog, f, errors, model, rec=rec).run()
    return errors
