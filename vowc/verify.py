"""Vow verifier: symbolic execution + z3. Proves bounds, overflow, contracts, loops."""
import z3
from vast import *

I64_MIN, I64_MAX = -2 ** 63, 2 ** 63 - 1
MAX_LEN = 2 ** 40
TIMEOUT_MS = 8000

_o = z3.Datatype("Opt"); _o.declare("some", ("sval", z3.IntSort())); _o.declare("none")
_r = z3.Datatype("Res"); _r.declare("ok", ("oval", z3.IntSort())); _r.declare("err", ("eval", z3.IntSort()))
Opt, Res = z3.CreateDatatypes(_o, _r)


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
    "invariant_entry": "the invariant must hold before the first iteration; check initial values",
    "invariant_preserved": "the invariant must hold again after one body iteration; add facts it depends on as more invariants",
    "decreases_nonneg": "the decreases expression must be >= 0 whenever the loop condition holds; add an invariant",
    "decreases_decrease": "the decreases expression must strictly decrease each iteration",
}


class FnVerifier:
    def __init__(s, prog, f, errors):
        s.funcs = {g.name: g for g in prog.functions}
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
        raise Exception("fresh: " + ty.name)

    # ---------- obligations ----------
    def prove(s, st, g, ob, node, code, what):
        key = (node.line, node.col, code)
        if key in s.seen:
            return
        def run(with_lemmas):
            sol = z3.Solver()
            sol.set("timeout", TIMEOUT_MS)
            for p in st.pc:
                sol.add(p)
            for p in g:
                sol.add(p)
            if with_lemmas:
                for p in s.lemmas:
                    sol.add(p)
            sol.add(z3.Not(ob))
            return sol, sol.check()

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
        s.errors.append(VowError("verify", node.line, node.col, code2, msg, FIX.get(code, ""), cex))

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
                    out[name] = str(m.eval(v, model_completion=True))
            except Exception:
                pass
        return out

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
        raise Exception("ev: %r" % e)

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
            for r in f.requires:
                ob = s.ev(r, st, g, False, cenv)
                s.prove(st, g, ob, e, "call_requires", "precondition of %s (line %d)" % (n, r.line))
        if f.ret == UNIT:
            return None
        res = s.fresh("ret_" + n, f.ret)
        if isinstance(res, Arr):
            s.assume(st, g, z3.And(res.n >= 0, res.n <= MAX_LEN))
        elif f.ret == I64:
            s.assume(st, g, in_range(res))
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
        for en in s.f.ensures:
            ob = s.ev(en, st, [], False, env)
            s.prove(st, [], ob, node, "ensures", "postcondition (line %d)" % en.line)

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
            if isinstance(st, (Assign, IndexAssign)):
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
        for n in names:
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
                h.env[n] = z3.Const("%s!h%d" % (n, s.k), old.sort()); s.k += 1
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
            st.env[stmt.name] = Arr(z3.Store(arr.a, i, v), arr.n, stmt.name)
            return [st]
        if isinstance(stmt, If):
            st = st.fork()
            c = s.ev(stmt.cond, st, [], True)
            return s.exec_block(stmt.then, st.fork(c)) + s.exec_block(stmt.els, st.fork(z3.Not(c)))
        if isinstance(stmt, Match):
            st = st.fork()
            v = s.ev(stmt.scrutinee, st, [], True)
            out = []
            for a in stmt.arms:
                if a.ctor == "Some": cond, val = Opt.is_some(v), Opt.sval(v)
                elif a.ctor == "None": cond, val = Opt.is_none(v), None
                elif a.ctor == "Ok": cond, val = Res.is_ok(v), Res.oval(v)
                else: cond, val = Res.is_err(v), Res.eval(v)
                b = st.fork(cond)
                if a.binder is not None:
                    b.env[a.binder] = val
                    b.pc.append(in_range(val))
                out.extend(s.exec_block(a.body, b))
            return out
        if isinstance(stmt, Return):
            st = st.fork()
            v = s.ev(stmt.value, st, [], True) if stmt.value is not None else None
            s.ensures_ok(st, v, stmt)
            return []
        if isinstance(stmt, Assert):
            ob = s.ev(stmt.cond, st, [], False)
            s.prove(st, [], ob, stmt, "assert", "assertion")
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
        for inv in w.invariants:
            s.prove(st, [], s.ev(inv, st, [], False), inv, "invariant_entry", "loop invariant on entry")
        names = s.assigned(w.body, set())
        # one arbitrary iteration
        b = s.havoc(st, names)
        for inv in w.invariants:
            b.pc.append(s.ev(inv, b, [], False))
        c = s.ev(w.cond, b, [], True)
        b.pc.append(c)
        d0 = s.ev(w.decreases, b, [], False)
        s.prove(b, [], d0 >= 0, w.decreases, "decreases_nonneg", "decreases >= 0")
        for end in s.exec_block(w.body, b):
            for inv in w.invariants:
                s.prove(end, [], s.ev(inv, end, [], False), inv, "invariant_preserved",
                        "loop invariant preserved")
            s.prove(end, [], s.ev(w.decreases, end, [], False) < d0, w.decreases, "decreases_decrease",
                    "decreases strictly decreases")
        # after the loop
        a = s.havoc(st, names)
        for inv in w.invariants:
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
            elif p.type == I64:
                pc.append(in_range(v))
            env[p.name] = v
        s.params = dict(env)
        st = State(env, pc)
        for r in f.requires:
            st.pc.append(s.ev(r, st, [], False))
        for end in s.exec_block(f.body, st):
            if f.ret == UNIT:
                s.ensures_ok(end, None, f)


def verify_program(prog):
    errors = []
    for f in prog.functions:
        FnVerifier(prog, f, errors).run()
    return errors
