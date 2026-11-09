"""Vow type / effect / structure checker. Fills Expr.ty."""
from vast import *

CONTRACT_ONLY = {"is_some": (OPTION, BOOL), "some_val": (OPTION, I64), "is_ok": (RESULT, BOOL),
                 "ok_val": (RESULT, I64), "err_val": (RESULT, I64)}
TNAME = {"i64": "i64", "bool": "bool", "unit": "()", "array": "[i64]", "option": "Option<i64>",
         "result": "Result<i64>"}


def terr(node, code, msg, fix="", stage="type"):
    raise VowError(stage, node.line, node.col, code, msg, fix)


class Checker:
    def __init__(s, prog):
        s.prog = prog
        s.funcs = {}
        for f in prog.functions:
            if f.name in s.funcs:
                terr(f, "dup_fn", "function %s defined twice" % f.name)
            if f.name in ("len", "alloc", "copy", "print") or f.name in CONTRACT_ONLY:
                terr(f, "reserved", "%s is a builtin name" % f.name, "rename the function")
            s.funcs[f.name] = f
        s.calls = {}

    def run(s):
        for f in s.prog.functions:
            s.fn(f)
        s.no_recursion()

    def no_recursion(s):
        state = {}

        def visit(n, path):
            if state.get(n) == 1:
                f = s.funcs[n]
                terr(f, "recursion", "recursion is not allowed: %s" % " -> ".join(path + [n]),
                     "rewrite with a while loop")
            if state.get(n) == 2:
                return
            state[n] = 1
            for c in s.calls.get(n, ()):
                visit(c, path + [n])
            state[n] = 2
        for n in s.funcs:
            visit(n, [])

    # ---- function ----
    def fn(s, f):
        s.f = f
        s.calls[f.name] = set()
        scope = {}
        for p in f.params:
            if p.name in scope:
                terr(f, "dup_param", "duplicate parameter %s" % p.name)
            if p.type == UNIT:
                terr(f, "unit_param", "parameter %s cannot have type ()" % p.name)
            scope[p.name] = (p.type, False, "param")
        s.used_effects = set()
        for r in f.requires:
            s.expect(r, BOOL, scope, contract=True)
        escope = dict(scope)
        if f.ret != UNIT:
            escope["result"] = (f.ret, False, "result")
        for e in f.ensures:
            s.expect(e, BOOL, escope, contract=True)
        s.block(f.body, dict(scope))
        if f.ret != UNIT and not s.ends_in_return(f.body):
            terr(f, "missing_return", "function %s may reach its end without returning" % f.name,
                 "end every path with `return ...;`")
        for e in sorted(s.used_effects):
            if e not in f.effects:
                terr(f, "missing_effect", "function %s uses effect `%s` but does not declare it" % (f.name, e),
                     "add `! %s` after the return type" % ", ".join(sorted(set(f.effects) | s.used_effects)),
                     stage="effect")

    def ends_in_return(s, stmts):
        if not stmts:
            return False
        last = stmts[-1]
        if isinstance(last, Return):
            return True
        if isinstance(last, If):
            return s.ends_in_return(last.then) and s.ends_in_return(last.els)
        if isinstance(last, Match):
            return all(s.ends_in_return(a.body) for a in last.arms)
        return False

    # ---- statements ----
    def block(s, stmts, scope):
        for st in stmts:
            s.stmt(st, scope)

    def stmt(s, st, scope):
        f = s.f
        if isinstance(st, Let):
            if st.name in scope:
                terr(st, "shadow", "%s is already defined; shadowing is not allowed" % st.name,
                     "use a new name")
            if st.type == UNIT:
                terr(st, "unit_let", "cannot bind a () value")
            s.expect(st.value, st.type, scope)
            if st.type == ARRAY:
                s.array_source(st, st.value, scope)
            scope[st.name] = (st.type, st.mutable, "local")
        elif isinstance(st, Assign):
            v = s.lookup(st, st.name, scope)
            if not v[1]:
                terr(st, "immutable", "%s is not mutable" % st.name,
                     "declare it with `let mut`" if v[2] == "local" else "parameters are immutable; copy into a `let mut` local")
            s.expect(st.value, v[0], scope)
            if v[0] == ARRAY:
                s.array_source(st, st.value, scope)
        elif isinstance(st, IndexAssign):
            v = s.lookup(st, st.name, scope)
            if v[0] != ARRAY:
                terr(st, "not_array", "%s is not an array" % st.name)
            if not v[1]:
                terr(st, "immutable", "array %s is read-only" % st.name,
                     "use `let mut b: [i64] = copy(%s);` (needs alloc)" % st.name)
            s.expect(st.index, I64, scope)
            s.expect(st.value, I64, scope)
        elif isinstance(st, If):
            s.expect(st.cond, BOOL, scope)
            s.block(st.then, dict(scope))
            s.block(st.els, dict(scope))
        elif isinstance(st, While):
            s.expect(st.cond, BOOL, scope)
            for i in st.invariants:
                s.expect(i, BOOL, scope, contract=True)
            s.expect(st.decreases, I64, scope, contract=True)
            s.block(st.body, dict(scope))
        elif isinstance(st, Return):
            if st.value is None:
                if f.ret != UNIT:
                    terr(st, "return_type", "function returns %s; `return;` is not enough" % TNAME[f.ret.name])
            else:
                if f.ret == UNIT:
                    terr(st, "return_type", "function returns (); use `return;`")
                s.expect(st.value, f.ret, scope)
                if f.ret == ARRAY:
                    s.array_source(st, st.value, scope, allow_local_var=True)
        elif isinstance(st, Assert):
            s.expect(st.cond, BOOL, scope, contract=True)
        elif isinstance(st, ExprStmt):
            if not isinstance(st.expr, Call):
                terr(st, "useless_expr", "expression statement must be a call", "bind it with let or remove it")
            t = s.expr(st.expr, scope)
            if t != UNIT:
                terr(st, "unused_value", "value of type %s is dropped" % TNAME[t.name],
                     "bind it with `let` or `match` it")
        elif isinstance(st, Match):
            t = s.expr(st.scrutinee, scope)
            if t == OPTION:
                need = {"Some", "None"}
            elif t == RESULT:
                need = {"Ok", "Err"}
            else:
                terr(st, "match_type", "can only match Option<i64> or Result<i64>")
            got = [a.ctor for a in st.arms]
            if set(got) != need or len(got) != 2:
                terr(st, "match_arms", "match needs exactly arms %s" % " and ".join(sorted(need)))
            for a in st.arms:
                sc = dict(scope)
                if a.binder is not None:
                    if a.binder in sc:
                        terr(st, "shadow", "%s is already defined" % a.binder, "use a new name")
                    sc[a.binder] = (I64, False, "local")
                s.block(a.body, sc)
        else:
            terr(st, "internal", "unknown statement")

    def array_source(s, st, value, scope, allow_local_var=False):
        """arrays are moved/borrowed explicitly: new arrays come only from alloc/copy/calls"""
        if isinstance(value, Call):
            return
        if allow_local_var and isinstance(value, Var) and scope.get(value.name, (None, None, ""))[2] == "local":
            return
        terr(st, "array_alias", "an array value here must come from alloc(), copy() or a function call",
             "write copy(x) to make an explicit copy (needs `! alloc`)")

    def lookup(s, node, name, scope):
        if name not in scope:
            terr(node, "unknown_name", "unknown variable %s" % name)
        return scope[name]

    # ---- expressions ----
    def expect(s, e, ty, scope, contract=False):
        t = s.expr(e, scope, contract)
        if t != ty:
            terr(e, "type_mismatch", "expected %s, found %s" % (TNAME[ty.name], TNAME[t.name]))
        return t

    def expr(s, e, scope, contract=False):
        t = s._expr(e, scope, contract)
        e.ty = t
        return t

    def _expr(s, e, scope, c):
        if isinstance(e, IntLit):
            if not (-2 ** 63 <= e.value < 2 ** 63):
                terr(e, "int_range", "integer literal out of i64 range")
            return I64
        if isinstance(e, BoolLit):
            return BOOL
        if isinstance(e, Var):
            if e.name == "result" and "result" not in scope:
                terr(e, "result_scope", "`result` is only allowed in ensures")
            return s.lookup(e, e.name, scope)[0]
        if isinstance(e, Unary):
            if e.op == "-":
                s.expect(e.operand, I64, scope, c); return I64
            s.expect(e.operand, BOOL, scope, c); return BOOL
        if isinstance(e, Binary):
            op = e.op
            if op in ("+", "-", "*", "/", "%"):
                s.expect(e.left, I64, scope, c); s.expect(e.right, I64, scope, c); return I64
            if op in ("<", "<=", ">", ">="):
                s.expect(e.left, I64, scope, c); s.expect(e.right, I64, scope, c); return BOOL
            if op in ("==", "!="):
                lt = s.expr(e.left, scope, c)
                if lt == ARRAY:
                    terr(e, "eq_type", "arrays cannot be compared with ==",
                         "compare lengths and elements: len(a) == len(b) && forall k in 0..len(a): a[k] == b[k]")
                if lt not in (I64, BOOL) and not c:
                    terr(e, "eq_type", "== only compares i64 or bool in code", "use match")
                s.expect(e.right, lt, scope, c)
                return BOOL
            if op in ("&&", "||"):
                s.expect(e.left, BOOL, scope, c); s.expect(e.right, BOOL, scope, c); return BOOL
            if op == "==>":
                if not c:
                    terr(e, "contract_only", "==> is only allowed in contracts")
                s.expect(e.left, BOOL, scope, c); s.expect(e.right, BOOL, scope, c); return BOOL
        if isinstance(e, Index):
            s.expect(e.array, ARRAY, scope, c)
            s.expect(e.index, I64, scope, c)
            return I64
        if isinstance(e, Ctor):
            if e.name == "None":
                return OPTION
            s.expect(e.arg, I64, scope, c)
            return OPTION if e.name == "Some" else RESULT
        if isinstance(e, Quant):
            agg = e.kind in ("sum", "count", "max", "min")
            if not c:
                if agg:
                    terr(e, "contract_only", "%s is only allowed in contracts" % e.kind,
                         "compute it with a while loop and state it in ensures, "
                         "e.g. ensures result == sum(k in 0..len(a): a[k])")
                terr(e, "contract_only", "%s is only allowed in contracts" % e.kind)
            s.expect(e.lo, I64, scope, c); s.expect(e.hi, I64, scope, c)
            if e.var in scope:
                terr(e, "shadow", "%s is already defined" % e.var, "use a new name")
            sc = dict(scope); sc[e.var] = (I64, False, "bound")
            s.expect(e.body, BOOL if e.kind in ("forall", "exists", "count") else I64, sc, c)
            return I64 if agg else BOOL
        if isinstance(e, Call):
            return s.call(e, scope, c)
        terr(e, "internal", "unknown expression")

    def call(s, e, scope, c):
        n, a = e.name, e.args

        def arity(k):
            if len(a) != k:
                terr(e, "arity", "%s takes %d argument(s), got %d" % (n, k, len(a)))
        if n == "len":
            arity(1); s.expect(a[0], ARRAY, scope, c); return I64
        if n == "alloc":
            if c: terr(e, "effect_in_contract", "alloc not allowed in contracts")
            arity(2); s.expect(a[0], I64, scope, c); s.expect(a[1], I64, scope, c)
            s.used_effects.add("alloc"); return ARRAY
        if n == "copy":
            if c: terr(e, "effect_in_contract", "copy not allowed in contracts")
            arity(1); s.expect(a[0], ARRAY, scope, c)
            s.used_effects.add("alloc"); return ARRAY
        if n == "print":
            if c: terr(e, "effect_in_contract", "print not allowed in contracts")
            arity(1)
            t = s.expr(a[0], scope, c)
            if t not in (I64, BOOL):
                terr(e, "print_type", "print takes i64 or bool")
            s.used_effects.add("io"); return UNIT
        if n in CONTRACT_ONLY:
            if not c:
                terr(e, "contract_only", "%s is only allowed in contracts" % n, "use match in code")
            arity(1)
            at, rt = CONTRACT_ONLY[n]
            s.expect(a[0], at, scope, c); return rt
        if n not in s.funcs:
            if n in ("sum", "count", "max", "min"):
                terr(e, "unknown_fn", "unknown function %s" % n,
                     "aggregates use the form sum(k in 0..len(a): a[k])")
            terr(e, "unknown_fn", "unknown function %s" % n)
        f = s.funcs[n]
        arity(len(f.params))
        for arg, p in zip(a, f.params):
            s.expect(arg, p.type, scope, c)
        if c and f.effects:
            terr(e, "effect_in_contract", "function %s has effects; not allowed in contracts" % n)
        if c:
            terr(e, "call_in_contract", "calling functions in contracts is not supported in v0.1",
                 "inline the property")
        s.used_effects.update(f.effects)
        s.calls[s.f.name].add(n)
        return f.ret


def check(prog):
    Checker(prog).run()
