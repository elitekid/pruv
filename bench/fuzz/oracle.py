"""Independent reference interpreter for a subset of Vow (written from SPEC.md only).

Does NOT import anything from vowc/.  Python 3.9, stdlib only, unbounded ints.

Supported subset (anything else -> OracleUnsupported):
  * top level: only `fn` declarations (any order, forward calls ok); no struct/enum/match/Option/Result.
  * types: i64, bool, [i64], ().  Statements: let / let mut / x = e / a[i] = e / if-else if-else /
    while (invariant*, decreases) / return / assert / print / call statement.
  * expressions: unary - !, * / %, + -, non-associative comparisons, &&, ||, ==> (right assoc),
    literals, vars, `result`, calls, len/alloc/copy, a[i]; contract-only forall/exists/sum/count/max/min.
    A quantifier/aggregate body extends as far right as possible (full `==>` level expression).

Semantics:
  CODE (bodies): values are i64.  + - * unary-: result outside i64 -> fault "overflow" (detail "+","-","*",
    "unary -").  / %: divisor > 0 and dividend >= 0 else fault "div_domain".  a[i] read/write out of range
    -> fault "oob".  alloc(n, v): n < 0 or n > 2^40 -> fault "overflow" detail "alloc" (n above 10^7 but
    within 2^40 cannot be simulated -> OracleUnsupported).  && || short-circuit.  Arrays are values (copied).
  CONTRACT (requires/ensures/invariant/assert/decreases): unbounded ints; / % Euclidean (-7/2==-4, -7%2==1);
    divisor 0, out-of-range index, max/min over an empty range -> undefined.  forall/exists go up from lo and
    stop at the first false/true k; sum/count/max/min evaluate every k.  && || ==> short-circuit.
    Calls to user functions inside contracts -> OracleUnsupported.
    Requires evaluated at call entry additionally have an i128 limit (value outside i128 -> undefined "i128").
  SCOPING: blocks (if/else branches, loop bodies, fn bodies) are scopes; a `let` is visible only until the end
    of its block; assignment to an outer variable updates the outer binding.  (The real checker forbids
    shadowing; sibling-scope reuse of a name after a block ends is fine.)  a[i] = e evaluates the index first,
    then the value (source order) -- the oracle's CHOSEN semantics (the compiler's proof mode currently
    evaluates the value first; see tests/runtime/fz01_index_assign_order.vow); oob is checked after both.
  MODES: run(..., mode="safe"|"proof", default "safe").  The TOP-LEVEL call always checks requires at run
    time (i128 limit) in both modes (checked public entry).  Inner calls from code: "safe" = same run-time
    check (fault on violated/undefined); "proof" (compiled program calls the unchecked body) = never fault:
    each requires clause is evaluated mathematically WITHOUT the i128 limit; every false/undefined clause K
    is RECORDED as "call_requires <callee> clause K", then the body runs anyway.
  CALLS (top level and from code): (a) requires clauses left to right (contract ctx, i128 limit): undefined ->
    fault "requires_undefined", false -> fault "requires_violated" (detail "<fn> clause <K>", K 1-based);
    (b) body in code ctx; per loop: invariants evaluated before every condition test; at each iteration
    start (condition true) d0 = decreases must be defined and >= 0; after EACH body execution that completes
    normally (no return) d1 must be defined and d1 < d0 (so the last iteration is checked too);
    failures/undefined are RECORDED ("invariant <fn> line N", "decreases <fn> line N", "assert <fn> line N");
    (c) at return, each ensures with `result` bound; false/undefined -> "ensures <fn> clause K" (1-based);
    (d) step limit: statements + loop iterations + quantifier iterations > max_steps -> fault "limit".
  Faults abort the run.  Contract failures are recorded (deduplicated, in order of first occurrence).
"""
import os
import re

I64_MIN, I64_MAX = -(2 ** 63), 2 ** 63 - 1
I128_MIN, I128_MAX = -(2 ** 127), 2 ** 127 - 1
ALLOC_SIM_MAX = 10_000_000


class OracleUnsupported(Exception):
    pass


class OracleParseError(Exception):
    pass


class _Fault(Exception):
    def __init__(self, kind, detail=""):
        Exception.__init__(self, kind, detail)
        self.kind, self.detail = kind, detail


class _Undef(Exception):
    pass


class _Return(Exception):
    def __init__(self, v):
        Exception.__init__(self)
        self.v = v


# ---------------------------------------------------------------- lexer
_TOK = re.compile(r"""
    (?P<ws>\s+|//[^\n]*)
  | (?P<int>\d[\d_]*)
  | (?P<id>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<op>==>|==|!=|<=|>=|&&|\|\||->|\.\.|::|[-+*/%<>=!(){}\[\],:;.])
""", re.X)
_UNSUPPORTED_KW = {"struct", "enum", "match", "Some", "None", "Ok", "Err", "is_variant", "variant_field",
                   "Option", "Result", "is_some", "some_val", "is_ok", "ok_val", "err_val", "mut_"}


def _lex(src):
    toks, pos, line = [], 0, 1
    while pos < len(src):
        m = _TOK.match(src, pos)
        if not m:
            raise OracleParseError("line %d: bad character %r" % (line, src[pos]))
        k, text = m.lastgroup, m.group()
        if k == "int":
            toks.append(("int", int(text.replace("_", "")), line))
        elif k != "ws":
            toks.append((k, text, line))
        line += text.count("\n")
        pos = m.end()
    toks.append(("eof", "", line))
    return toks


# ---------------------------------------------------------------- parser
class _Fn(object):
    def __init__(self, name, params, ret, requires, ensures, body, line):
        self.name, self.params, self.ret = name, params, ret
        self.requires, self.ensures, self.body, self.line = requires, ensures, body, line


class Program(object):
    def __init__(self, fns):
        self.fns = fns


class _Parser(object):
    def __init__(self, src):
        self.t = _lex(src)
        self.p = 0

    def peek(self, k=0):
        return self.t[min(self.p + k, len(self.t) - 1)]

    def is_(self, text, k=0):
        t = self.peek(k)
        return t[0] in ("op", "id") and t[1] == text

    def next(self):
        t = self.t[self.p]
        self.p += 1
        return t

    def err(self, msg):
        raise OracleParseError("line %d: %s (at %r)" % (self.peek()[2], msg, self.peek()[1]))

    def eat(self, text):
        if not self.is_(text):
            self.err("expected %r" % text)
        return self.next()

    def ident(self):
        t = self.peek()
        if t[0] != "id":
            self.err("expected identifier")
        if t[1] in _UNSUPPORTED_KW:
            raise OracleUnsupported("unsupported keyword %s" % t[1])
        return self.next()[1]

    # types
    def type_(self):
        if self.is_("("):
            self.next()
            self.eat(")")
            return "unit"
        if self.is_("["):
            self.next()
            self.eat("i64")
            self.eat("]")
            return "arr"
        t = self.peek()
        if t[0] == "id" and t[1] in ("i64", "bool"):
            self.next()
            return t[1]
        if t[0] == "id":
            raise OracleUnsupported("unsupported type %s" % t[1])
        self.err("expected type")

    # program
    def program(self):
        fns = {}
        while self.peek()[0] != "eof":
            if self.is_("fn"):
                f = self.fn()
                if f.name in fns:
                    self.err("duplicate fn %s" % f.name)
                fns[f.name] = f
            elif self.peek()[0] == "id":
                raise OracleUnsupported("unsupported top-level item %s" % self.peek()[1])
            else:
                self.err("expected fn")
        if not fns:
            self.err("no functions")
        return Program(fns)

    def fn(self):
        line = self.eat("fn")[2]
        name = self.ident()
        self.eat("(")
        params = []
        while not self.is_(")"):
            pn = self.ident()
            self.eat(":")
            params.append((pn, self.type_()))
            if not self.is_(")"):
                self.eat(",")
        self.eat(")")
        ret = "unit"
        if self.is_("->"):
            self.next()
            ret = self.type_()
        if self.is_("!"):
            self.next()
            self.ident()
            while self.is_(","):
                self.next()
                self.ident()
        req, ens = [], []
        while self.is_("requires") or self.is_("ensures"):
            kw = self.next()
            (req if kw[1] == "requires" else ens).append((self.imp(), kw[2]))
        return _Fn(name, params, ret, req, ens, self.block(), line)

    def block(self):
        self.eat("{")
        out = []
        while not self.is_("}"):
            out.append(self.stmt())
        self.eat("}")
        return out

    def stmt(self):
        t = self.peek()
        line = t[2]
        if t[0] == "id" and t[1] in _UNSUPPORTED_KW:
            raise OracleUnsupported("unsupported statement %s" % t[1])
        if self.is_("let"):
            self.next()
            if self.is_("mut"):
                self.next()
            name = self.ident()
            self.eat(":")
            self.type_()
            self.eat("=")
            e = self.imp()
            self.eat(";")
            return ("let", line, name, e)
        if self.is_("if"):
            return self.if_stmt()
        if self.is_("while"):
            self.next()
            cond = self.imp()
            invs, dec = [], None
            while self.is_("invariant"):
                kw = self.next()
                invs.append((self.imp(), kw[2]))
            if self.is_("decreases"):
                kw = self.next()
                dec = (self.imp(), kw[2])
            else:
                self.err("while needs decreases")
            return ("while", line, cond, invs, dec, self.block())
        if self.is_("return"):
            self.next()
            e = None
            if not self.is_(";"):
                e = self.imp()
            self.eat(";")
            return ("return", line, e)
        if self.is_("assert"):
            self.next()
            e = self.imp()
            self.eat(";")
            return ("assert", line, e)
        if self.is_("print") and self.is_("(", 1):
            self.next()
            self.next()
            e = self.imp()
            self.eat(")")
            self.eat(";")
            return ("print", line, e)
        if t[0] == "id":
            if self.is_("=", 1):
                name = self.ident()
                self.next()
                e = self.imp()
                self.eat(";")
                return ("assign", line, name, e)
            if self.is_("[", 1):
                name = self.ident()
                self.next()
                i = self.imp()
                self.eat("]")
                self.eat("=")
                e = self.imp()
                self.eat(";")
                return ("aassign", line, name, i, e)
            if self.is_("(", 1):
                e = self.imp()
                self.eat(";")
                if e[0] != "call":
                    self.err("bad expression statement")
                return ("expr", line, e)
        self.err("bad statement")

    def if_stmt(self):
        line = self.eat("if")[2]
        cond = self.imp()
        then = self.block()
        els = []
        if self.is_("else"):
            self.next()
            if self.is_("if"):
                els = [self.if_stmt()]
            else:
                els = self.block()
        return ("if", line, cond, then, els)

    # expressions
    def imp(self):
        l = self.or_()
        if self.is_("==>"):
            self.next()
            return ("bin", "==>", l, self.imp())
        return l

    def or_(self):
        l = self.and_()
        while self.is_("||"):
            self.next()
            l = ("bin", "||", l, self.and_())
        return l

    def and_(self):
        l = self.cmp_()
        while self.is_("&&"):
            self.next()
            l = ("bin", "&&", l, self.cmp_())
        return l

    def cmp_(self):
        l = self.add()
        t = self.peek()
        if t[0] == "op" and t[1] in ("==", "!=", "<", "<=", ">", ">="):
            self.next()
            r = self.add()
            t2 = self.peek()
            if t2[0] == "op" and t2[1] in ("==", "!=", "<", "<=", ">", ">="):
                self.err("comparison is non-associative")
            return ("bin", t[1], l, r)
        return l

    def add(self):
        l = self.mul()
        while self.is_("+") or self.is_("-"):
            op = self.next()[1]
            l = ("bin", op, l, self.mul())
        return l

    def mul(self):
        l = self.unary()
        while self.is_("*") or self.is_("/") or self.is_("%"):
            op = self.next()[1]
            l = ("bin", op, l, self.unary())
        return l

    def unary(self):
        if self.is_("-"):
            self.next()
            return ("neg", self.unary())
        if self.is_("!"):
            self.next()
            return ("not", self.unary())
        e = self.primary()
        while self.is_("["):
            self.next()
            i = self.imp()
            self.eat("]")
            e = ("idx", e, i)
        return e

    def range_(self):
        lo = self.add()
        self.eat("..")
        return lo, self.add()

    def primary(self):
        t = self.peek()
        if t[0] == "int":
            self.next()
            return ("int", t[1])
        if self.is_("("):
            self.next()
            e = self.imp()
            self.eat(")")
            return e
        if t[0] != "id":
            self.err("expected expression")
        name = t[1]
        if name in _UNSUPPORTED_KW:
            raise OracleUnsupported("unsupported expression %s" % name)
        if name in ("true", "false"):
            self.next()
            return ("bool", name == "true")
        if name == "result":
            self.next()
            return ("result",)
        if name in ("forall", "exists"):
            self.next()
            k = self.ident()
            self.eat("in")
            lo, hi = self.range_()
            self.eat(":")
            return (name, k, lo, hi, self.imp(), t[2])
        if name in ("sum", "count", "max", "min") and self.is_("(", 1) and self.peek(2)[0] == "id" \
                and self.is_("in", 3):
            self.next()
            self.next()
            k = self.ident()
            self.eat("in")
            lo, hi = self.range_()
            self.eat(":")
            body = self.imp()
            self.eat(")")
            return ("agg", name, k, lo, hi, body, t[2])
        self.next()
        if self.is_("("):
            self.next()
            args = []
            while not self.is_(")"):
                args.append(self.imp())
                if not self.is_(")"):
                    self.eat(",")
            self.eat(")")
            return ("call", name, args, t[2])
        return ("var", name)


def parse_program(src):
    return _Parser(src).program()


# ---------------------------------------------------------------- semantics helpers
def _ediv(x, y):
    if y == 0:
        raise _Undef("div0")
    return (x - x % abs(y)) // y


def _emod(x, y):
    if y == 0:
        raise _Undef("div0")
    return x % abs(y)


def _cp(v):
    return list(v) if isinstance(v, list) else v


class _Interp(object):
    def __init__(self, prog, max_steps, mode="safe"):
        if mode not in ("safe", "proof"):
            raise ValueError("mode must be 'safe' or 'proof'")
        self.prog, self.max_steps, self.steps, self.mode = prog, max_steps, 0, mode
        self.output, self.failures = [], []

    def tick(self):
        self.steps += 1
        if self.steps > self.max_steps:
            raise _Fault("limit", "steps")

    def fail(self, msg):
        if msg not in self.failures:
            self.failures.append(msg)

    # ---- contract evaluation (unbounded ints; lim => i128 limit)
    def cev(self, e, env, lim):
        k = e[0]

        def chk(v):
            if lim and not isinstance(v, bool) and isinstance(v, int) and not (I128_MIN <= v <= I128_MAX):
                raise _Undef("i128")
            return v

        if k == "int":
            return chk(e[1])
        if k == "bool":
            return e[1]
        if k == "var":
            if e[1] not in env:
                raise OracleUnsupported("unbound variable %s" % e[1])
            return env[e[1]]
        if k == "result":
            if "result" not in env:
                raise OracleUnsupported("result outside ensures")
            return env["result"]
        if k == "neg":
            return chk(-self.cev(e[1], env, lim))
        if k == "not":
            return not self.cev(e[1], env, lim)
        if k == "idx":
            a = self.cev(e[1], env, lim)
            i = self.cev(e[2], env, lim)
            if not 0 <= i < len(a):
                raise _Undef("index")
            return chk(a[i])
        if k == "bin":
            op = e[1]
            if op == "&&":
                return bool(self.cev(e[3], env, lim)) if self.cev(e[2], env, lim) else False
            if op == "||":
                return True if self.cev(e[2], env, lim) else bool(self.cev(e[3], env, lim))
            if op == "==>":
                return bool(self.cev(e[3], env, lim)) if self.cev(e[2], env, lim) else True
            x = self.cev(e[2], env, lim)
            y = self.cev(e[3], env, lim)
            if op == "+":
                return chk(x + y)
            if op == "-":
                return chk(x - y)
            if op == "*":
                return chk(x * y)
            if op == "/":
                return chk(_ediv(x, y))
            if op == "%":
                return chk(_emod(x, y))
            if op == "==":
                return x == y
            if op == "!=":
                return x != y
            if op == "<":
                return x < y
            if op == "<=":
                return x <= y
            if op == ">":
                return x > y
            return x >= y
        if k == "call":
            if e[1] == "len" and len(e[2]) == 1:
                return chk(len(self.cev(e[2][0], env, lim)))
            raise OracleUnsupported("call to %s in contract" % e[1])
        if k in ("forall", "exists"):
            _, name, lo_e, hi_e, body, _ln = e
            lo, hi = self.cev(lo_e, env, lim), self.cev(hi_e, env, lim)
            had, old = name in env, env.get(name)
            try:
                for i in range(lo, hi):
                    self.tick()
                    env[name] = i
                    v = self.cev(body, env, lim)
                    if k == "forall" and not v:
                        return False
                    if k == "exists" and v:
                        return True
            finally:
                if had:
                    env[name] = old
                else:
                    env.pop(name, None)
            return k == "forall"
        if k == "agg":
            _, kind, name, lo_e, hi_e, body, _ln = e
            lo, hi = self.cev(lo_e, env, lim), self.cev(hi_e, env, lim)
            if kind in ("max", "min") and lo >= hi:
                raise _Undef("empty %s" % kind)
            had, old = name in env, env.get(name)
            acc = None
            try:
                for i in range(lo, hi):
                    self.tick()
                    env[name] = i
                    v = self.cev(body, env, lim)
                    if kind == "sum":
                        acc = chk((acc or 0) + v)
                    elif kind == "count":
                        acc = (acc or 0) + (1 if v else 0)
                    elif acc is None:
                        acc = v
                    else:
                        acc = max(acc, v) if kind == "max" else min(acc, v)
            finally:
                if had:
                    env[name] = old
                else:
                    env.pop(name, None)
            return 0 if acc is None else acc
        raise OracleUnsupported("bad contract expression %r" % (k,))

    def cbool(self, e, env, lim):
        """Contract evaluation -> (status, value) with status 'ok' | 'undef'."""
        try:
            return "ok", self.cev(e, env, lim)
        except _Undef as u:
            return "undef", str(u)

    # ---- code evaluation (i64)
    def ev(self, e, env):
        k = e[0]
        if k == "int":
            if e[1] > I64_MAX:
                raise OracleUnsupported("integer literal out of i64 range in code")
            return e[1]
        if k == "bool":
            return e[1]
        if k == "var":
            if e[1] not in env:
                raise OracleUnsupported("unbound variable %s" % e[1])
            return env[e[1]]
        if k == "neg":
            v = -self.ev(e[1], env)
            if v > I64_MAX:
                raise _Fault("overflow", "unary -")
            return v
        if k == "not":
            return not self.ev(e[1], env)
        if k == "idx":
            a = self.ev(e[1], env)
            i = self.ev(e[2], env)
            if not 0 <= i < len(a):
                raise _Fault("oob", "index")
            return a[i]
        if k == "bin":
            op = e[1]
            if op == "&&":
                return bool(self.ev(e[3], env)) if self.ev(e[2], env) else False
            if op == "||":
                return True if self.ev(e[2], env) else bool(self.ev(e[3], env))
            if op == "==>":
                raise OracleUnsupported("==> in code")
            x = self.ev(e[2], env)
            y = self.ev(e[3], env)
            if op in ("+", "-", "*"):
                v = x + y if op == "+" else x - y if op == "-" else x * y
                if not I64_MIN <= v <= I64_MAX:
                    raise _Fault("overflow", op)
                return v
            if op in ("/", "%"):
                if not (y > 0 and x >= 0):
                    raise _Fault("div_domain", op)
                return x // y if op == "/" else x % y
            return {"==": x == y, "!=": x != y, "<": x < y, "<=": x <= y, ">": x > y, ">=": x >= y}[op]
        if k == "call":
            name, args = e[1], e[2]
            if name == "len" and len(args) == 1:
                return len(self.ev(args[0], env))
            if name == "copy" and len(args) == 1:
                return list(self.ev(args[0], env))
            if name == "alloc" and len(args) == 2:
                n = self.ev(args[0], env)
                v = self.ev(args[1], env)
                if n < 0 or n > 2 ** 40:
                    raise _Fault("overflow", "alloc")
                if n > ALLOC_SIM_MAX:
                    raise OracleUnsupported("alloc too large to simulate")
                return [v] * n
            return self.call(name, [self.ev(a, env) for a in args], top=False)
        raise OracleUnsupported("contract-only expression %s in code" % (k,))

    # ---- calls
    def check_req(self, fn, penv):
        """-> ('ok'|'violated'|'undefined', clause_index_1based)"""
        for idx, (ce, _ln) in enumerate(fn.requires, 1):
            st, v = self.cbool(ce, penv, True)
            if st == "undef":
                return "undefined", idx, v
            if not v:
                return "violated", idx, ""
        return "ok", 0, ""

    def call(self, name, args, top=True):
        fn = self.prog.fns.get(name)
        if fn is None:
            raise OracleUnsupported("unknown function %s" % name)
        if len(args) != len(fn.params):
            raise OracleUnsupported("arity mismatch calling %s" % name)
        penv = {}
        for (pn, _pt), a in zip(fn.params, args):
            penv[pn] = _cp(a)
        if top or self.mode != "proof":
            st, idx, why = self.check_req(fn, penv)
            if st == "undefined":
                raise _Fault("requires_undefined", "%s clause %d: %s" % (name, idx, why))
            if st == "violated":
                raise _Fault("requires_violated", "%s clause %d" % (name, idx))
        else:
            # proof-mode inner call: unchecked body; requires evaluated mathematically (no i128 limit)
            for idx, (ce, _ln) in enumerate(fn.requires, 1):
                st, v = self.cbool(ce, penv, False)
                if st == "undef" or not v:
                    self.fail("call_requires %s clause %d" % (name, idx))
        env = dict(penv)
        ret, returned = None, False
        try:
            self.block(fn, fn.body, env)
        except _Return as r:
            ret, returned = r.v, True
        if fn.ret != "unit" and not returned:
            raise OracleUnsupported("function %s falls off the end" % name)
        ret = _cp(ret)
        eenv = dict(penv)
        eenv["result"] = ret
        for idx, (ce, _ln) in enumerate(fn.ensures, 1):
            st, v = self.cbool(ce, eenv, False)
            if st == "undef" or not v:
                self.fail("ensures %s clause %d" % (name, idx))
        return ret

    # ---- statements
    def block(self, fn, stmts, env):
        # Block scope: `let` bindings made here are dropped (or the shadowed binding restored) at block end;
        # plain assignments update whatever binding is visible, i.e. the outer one.
        declared = []
        try:
            for s in stmts:
                if s[0] == "let":
                    declared.append((s[2], s[2] in env, env.get(s[2])))
                self.stmt(fn, s, env)
        finally:
            for name, had, old in reversed(declared):
                if had:
                    env[name] = old
                else:
                    env.pop(name, None)

    def stmt(self, fn, s, env):
        self.tick()
        k, line = s[0], s[1]
        if k == "let" or k == "assign":
            if k == "assign" and s[2] not in env:
                raise OracleUnsupported("assignment to unbound %s" % s[2])
            env[s[2]] = _cp(self.ev(s[3], env))
        elif k == "aassign":
            a = env.get(s[2])
            if not isinstance(a, list):
                raise OracleUnsupported("indexed assignment to non-array %s" % s[2])
            i = self.ev(s[3], env)
            v = self.ev(s[4], env)
            if not 0 <= i < len(a):
                raise _Fault("oob", "index")
            a[i] = v
        elif k == "if":
            self.block(fn, s[3] if self.ev(s[2], env) else s[4], env)
        elif k == "while":
            _, _l, cond, invs, dec, body = s
            while True:
                self.tick()
                for ie, iln in invs:
                    st, v = self.cbool(ie, env, False)
                    if st == "undef" or not v:
                        self.fail("invariant %s line %d" % (fn.name, iln))
                if not self.ev(cond, env):
                    break
                st0, d0 = self.cbool(dec[0], env, False)
                if st0 == "undef" or d0 < 0:
                    self.fail("decreases %s line %d" % (fn.name, dec[1]))
                self.block(fn, body, env)   # a `return` propagates: no end-of-body check
                st1, d1 = self.cbool(dec[0], env, False)
                if st1 == "undef" or st0 == "undef" or not d1 < d0:
                    self.fail("decreases %s line %d" % (fn.name, dec[1]))
        elif k == "return":
            raise _Return(None if s[2] is None else self.ev(s[2], env))
        elif k == "assert":
            st, v = self.cbool(s[2], env, False)
            if st == "undef" or not v:
                self.fail("assert %s line %d" % (fn.name, line))
        elif k == "print":
            v = self.ev(s[2], env)
            if isinstance(v, list):
                raise OracleUnsupported("print of array")
            self.output.append(format_value(v))
        elif k == "expr":
            self.ev(s[2], env)
        else:
            raise OracleUnsupported("statement %s" % k)


# ---------------------------------------------------------------- public API
def format_value(v):
    if v is None:
        return "()"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, list):
        return "[" + ", ".join(format_value(x) for x in v) + "]"
    return str(v)


def run(prog, fn_name, args, max_steps=2_000_000, mode="safe"):
    it = _Interp(prog, max_steps, mode)
    kind, value, detail = "ok", None, ""
    try:
        value = it.call(fn_name, [_cp(a) for a in args], top=True)
    except _Fault as f:
        kind, detail, value = f.kind, f.detail, None
    return {"kind": kind, "value": value, "detail": detail, "output": it.output,
            "contract_failures": it.failures}


def check_requires(prog, fn_name, args):
    fn = prog.fns.get(fn_name)
    if fn is None or len(args) != len(fn.params):
        raise OracleUnsupported("bad function/arity")
    it = _Interp(prog, 2_000_000)
    penv = dict((pn, _cp(a)) for (pn, _t), a in zip(fn.params, args))
    try:
        st, _i, _w = it.check_req(fn, penv)
    except _Fault:
        return "undefined"
    return st


def expected_stderr_prefix(result):
    k, d = result["kind"], result["detail"]
    if k == "requires_violated":
        return "vow: requires violated: %s:" % d.split()[0]
    if k == "requires_undefined":
        return "vow: requires undefined:"
    if k == "oob":
        return "vow: index out of bounds:"
    if k == "overflow":
        return "vow: arithmetic error: alloc length" if d == "alloc" else "vow: arithmetic error: overflow in " + d
    if k == "div_domain":
        return "vow: arithmetic error: division outside domain"
    return None


# ---------------------------------------------------------------- self-test
def _selftest():
    def go(src, fn, args, **kw):
        return run(parse_program(src), fn, args, **kw)

    here = os.path.dirname(os.path.abspath(__file__))
    ex = os.path.join(here, "..", "..", "examples")

    def load(name):
        with open(os.path.join(ex, name)) as f:
            return f.read()

    r = go(load("sum.vow"), "sum", [[1, 2, 3]])
    assert r["kind"] == "ok" and r["value"] == 6 and not r["contract_failures"], r
    assert go(load("sum.vow"), "sum", [[2_000_000_000]])["kind"] == "requires_violated"
    pre = parse_program(load("prefix.vow"))
    r = run(pre, "prefix", [[1, 2, 3]])
    assert r["value"] == [0, 1, 3, 6] and not r["contract_failures"], r
    r = run(pre, "main", [])
    assert r["output"] == ["21"], r
    try:
        parse_program(load("bsearch.vow"))
    except OracleUnsupported:
        pass  # Option return type is outside the subset

    # Euclidean contract division
    t = "fn t(x: i64, y: i64) -> ()\n requires y != 0\n{\n assert x / y == %d && x %% y == %d;\n}\n"
    for x, y, q, m in [(-7, 2, -4, 1), (7, -2, -3, 1), (-7, -2, 4, 1), (7, 2, 3, 1)]:
        r = go(t % (q, m), "t", [x, y])
        assert r["kind"] == "ok" and not r["contract_failures"], (x, y, r)
    assert go(t % (3, 2), "t", [-7, 2])["contract_failures"] == ["assert t line 4"]

    # overflow
    for op, a, b, d in [("+", I64_MAX, 1, "+"), ("-", I64_MIN, 1, "-"), ("*", 2 ** 62, 2, "*")]:
        r = go("fn f(x: i64, y: i64) -> i64 { return x %s y; }" % op, "f", [a, b])
        assert (r["kind"], r["detail"]) == ("overflow", d), r
    r = go("fn f(x: i64) -> i64 { return -x; }", "f", [I64_MIN])
    assert (r["kind"], r["detail"]) == ("overflow", "unary -"), r
    assert expected_stderr_prefix(r) == "vow: arithmetic error: overflow in unary -"
    r = go("fn f(n: i64) -> [i64] ! alloc { return alloc(n, 0); }", "f", [-1])
    assert (r["kind"], r["detail"]) == ("overflow", "alloc"), r
    assert go("fn f(x: i64, y: i64) -> i64 { return x + y; }", "f", [I64_MAX - 1, 1])["value"] == I64_MAX

    # oob
    src = "fn f(a: [i64], i: i64) -> i64 { return a[i]; }"
    assert go(src, "f", [[1], 1])["kind"] == "oob"
    assert go(src, "f", [[1], -1])["kind"] == "oob"
    assert go(src, "f", [[5], 0])["value"] == 5
    src = "fn f(i: i64) -> i64 ! alloc { let mut b: [i64] = alloc(2, 0); b[i] = 9; return b[0]; }"
    assert go(src, "f", [2])["kind"] == "oob" and go(src, "f", [0])["value"] == 9

    # div_domain
    src = "fn f(x: i64, y: i64) -> i64 { return x / y; }"
    for x, y in [(5, 0), (5, -1), (-5, 2)]:
        r = go(src, "f", [x, y])
        assert r["kind"] == "div_domain", (x, y, r)
    assert go(src, "f", [7, 2])["value"] == 3
    assert go("fn f(x: i64) -> i64 { return x % 3; }", "f", [-1])["kind"] == "div_domain"

    # requires order: violated vs undefined
    good = "fn f(a: [i64], i: i64) -> i64\n requires 0 <= i && i < len(a) && a[i] > 0\n{ return a[i]; }"
    bad = "fn f(a: [i64], i: i64) -> i64\n requires a[i] > 0 && 0 <= i && i < len(a)\n{ return a[i]; }"
    assert go(good, "f", [[1], 5])["kind"] == "requires_violated"
    assert go(good, "f", [[-1], 0])["kind"] == "requires_violated"
    assert go(good, "f", [[3], 0])["value"] == 3
    assert go(bad, "f", [[1], 5])["kind"] == "requires_undefined"
    assert check_requires(parse_program(good), "f", [[1], 5]) == "violated"
    assert check_requires(parse_program(bad), "f", [[1], 5]) == "undefined"
    assert check_requires(parse_program(good), "f", [[1], 0]) == "ok"
    r = go(good, "f", [[1], 5])
    assert expected_stderr_prefix(r) == "vow: requires violated: f:"

    # forall / exists early stop
    fa = "fn f(a: [i64]) -> i64\n requires forall k in 0..5: a[k] > 0\n{ return 0; }"
    assert go(fa, "f", [[-1]])["kind"] == "requires_violated"      # stops at k=0
    assert go(fa, "f", [[1]])["kind"] == "requires_undefined"      # reaches k=1: oob
    ex_ = "fn f(a: [i64]) -> i64\n requires exists k in 0..5: a[k] > 0\n{ return 0; }"
    assert go(ex_, "f", [[1]])["kind"] == "ok"                     # stops at k=0
    assert go(ex_, "f", [[-1]])["kind"] == "requires_undefined"

    # max over empty range undefined; aggregates
    mx = "fn f(n: i64) -> i64\n requires max(k in 0..n: k) >= 0\n{ return 0; }"
    assert go(mx, "f", [0])["kind"] == "requires_undefined"
    assert go(mx, "f", [3])["kind"] == "ok"
    ag = ("fn f(a: [i64]) -> i64\n ensures result == sum(k in 0..len(a): a[k]) && "
          "count(k in 0..len(a): a[k] > 1) == 2 && max(k in 0..len(a): a[k]) == 3 && "
          "min(k in 0..len(a): a[k]) == 1 && sum(k in 3..1: 7) == 0\n{ return 6; }")
    r = go(ag, "f", [[1, 2, 3]])
    assert r["value"] == 6 and not r["contract_failures"], r

    # invariant / decreases / assert / ensures recording
    src = ("fn f(n: i64) -> i64\n ensures result == 0\n{\n let mut i: i64 = 0;\n"
           " while i < n\n  invariant i < 2\n  decreases 5\n {\n  i = i + 1;\n }\n"
           " assert i == 99;\n return i;\n}\n")
    r = go(src, "f", [3])
    assert r["kind"] == "ok" and r["value"] == 3, r
    assert "invariant f line 6" in r["contract_failures"], r
    assert "decreases f line 7" in r["contract_failures"], r
    assert "assert f line 11" in r["contract_failures"], r
    assert "ensures f clause 1" in r["contract_failures"], r
    r = go(src, "f", [1])
    assert not any(c.startswith("invariant") for c in r["contract_failures"]), r
    assert "decreases f line 7" in r["contract_failures"], r   # constant decreases never strictly drops

    # i128 limit applies to requires only
    big = ("fn f(x: i64) -> i64\n requires x * x * x * x * x > 0\n ensures x * x * x * x * x > 0\n"
           "{ return 1; }")
    assert go(big, "f", [I64_MAX])["kind"] == "requires_undefined"
    assert go(big, "f", [3])["kind"] == "ok"

    # calls: callee requires checked, names the callee; nested effects; limit
    src = ("fn g(x: i64) -> i64 requires x > 0 { return x; }\n"
           "fn f(x: i64) -> i64 { print(x); print(x > 0); return g(x - 1); }\n")
    r = go(src, "f", [1])
    assert r["kind"] == "requires_violated" and r["detail"].startswith("g "), r
    assert r["output"] == ["1", "true"], r
    assert expected_stderr_prefix(r) == "vow: requires violated: g:"
    r = go("fn f() -> () { while true decreases 1 { } }", "f", [], max_steps=1000)
    assert r["kind"] == "limit" and expected_stderr_prefix(r) is None, r
    assert format_value([1, 2]) == "[1, 2]" and format_value(True) == "true" and format_value(-3) == "-3"

    # decreases: last body execution must also strictly decrease
    src = ("fn f() -> i64 { let mut i: i64 = 0; while i < 1 invariant 0 <= i && i <= 1 decreases 1 "
           "{ i = i + 1; } return i; }")
    r = go(src, "f", [])
    assert r["kind"] == "ok" and r["value"] == 1 and r["contract_failures"] == ["decreases f line 1"], r
    ok = ("fn f() -> i64 { let mut i: i64 = 0; while i < 3 invariant 0 <= i && i <= 3 decreases 3 - i "
          "{ i = i + 1; } return i; }")
    assert not go(ok, "f", [])["contract_failures"]
    # a returning body is not checked for decrease
    ret = "fn f() -> i64 { while true decreases 1 { return 5; } return 0; }"
    assert go(ret, "f", [])["contract_failures"] == []

    # mode-aware inner calls
    src = ("fn g(x: i64) -> i64 requires ((x * x) * (x * x)) * ((x * x) * (x * x)) >= 0 { return 1; }\n"
           "fn f(x: i64) -> i64 { return g(x); }\n")
    r = go(src, "f", [I64_MAX])
    assert r["kind"] == "requires_undefined", r
    assert go(src, "f", [I64_MAX], mode="safe")["kind"] == "requires_undefined"
    r = go(src, "f", [I64_MAX], mode="proof")
    assert r["kind"] == "ok" and r["value"] == 1 and not r["contract_failures"], r
    # top-level call is always checked, even in proof mode
    assert go(src, "g", [I64_MAX], mode="proof")["kind"] == "requires_undefined"
    src = ("fn g(x: i64) -> i64 requires x > 0 { return x; }\n"
           "fn f(x: i64) -> i64 { return g(x - 1); }\n")
    assert go(src, "f", [1])["kind"] == "requires_violated"
    r = go(src, "f", [1], mode="proof")
    assert r["kind"] == "ok" and r["value"] == 0 and r["contract_failures"] == ["call_requires g clause 1"], r
    assert go(src, "f", [1], mode="proof")["kind"] == "ok"

    # block scoping
    src = ("fn f(c: bool) -> i64 { let mut s: i64 = 0; if c { let t: i64 = 1; s = s + t; } "
           "let t: i64 = 2; if c { s = s + t; } else { let u: i64 = 7; s = s + u; } "
           "let mut i: i64 = 0; while i < 2 decreases 2 - i { let w: i64 = i; s = s + w; i = i + 1; } "
           "let w: i64 = 100; return s + w; }")
    assert go(src, "f", [True])["value"] == 1 + 2 + 0 + 1 + 100
    assert go(src, "f", [False])["value"] == 7 + 0 + 1 + 100
    try:
        go("fn f(c: bool) -> i64 { if c { let t: i64 = 1; } return t; }", "f", [True])
        assert False, "block-local leaked"
    except OracleUnsupported:
        pass
    print("oracle self-test OK")


if __name__ == "__main__":
    _selftest()
