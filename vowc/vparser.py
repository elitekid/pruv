"""Vow lexer + recursive-descent parser -> vast.Program"""
import re
from vast import *

KEYWORDS = {"fn", "let", "mut", "if", "else", "while", "return", "match", "true", "false",
            "invariant", "decreases", "requires", "ensures", "assert", "forall", "exists",
            "in", "Some", "None", "Ok", "Err"}
TOKEN_RE = re.compile(r"""
 (?P<ws>[ \t\r]+) | (?P<nl>\n) | (?P<comment>//[^\n]*)
|(?P<int>[0-9][0-9_]*)
|(?P<id>[A-Za-z_][A-Za-z0-9_]*)
|(?P<op>==>|==|!=|<=|>=|&&|\|\||->|=>|\.\.|[-+*/%<>=!(){}\[\],:;])
""", re.X)


class Tok:
    __slots__ = ("kind", "val", "line", "col")

    def __init__(s, kind, val, line, col):
        s.kind, s.val, s.line, s.col = kind, val, line, col

    def __repr__(s):
        return "%s(%r)" % (s.kind, s.val)


def lex(src):
    toks, pos, line, lstart = [], 0, 1, 0
    while pos < len(src):
        m = TOKEN_RE.match(src, pos)
        if not m:
            raise VowError("parse", line, pos - lstart + 1, "bad_char",
                           "unexpected character %r" % src[pos], "remove it")
        k = m.lastgroup
        v = m.group(k)
        col = pos - lstart + 1
        if k == "nl":
            line += 1
            lstart = m.end()
        elif k == "int":
            if v.endswith("_"):
                raise VowError("parse", line, col, "bad_int", "integer literal ends with _", "")
            toks.append(Tok("int", int(v.replace("_", "")), line, col))
        elif k == "id":
            toks.append(Tok("kw" if v in KEYWORDS else "id", v, line, col))
        elif k == "op":
            toks.append(Tok("op", v, line, col))
        pos = m.end()
    toks.append(Tok("eof", None, line, pos - lstart + 1))
    return toks


class Parser:
    def __init__(s, src):
        s.t = lex(src)
        s.i = 0

    # helpers
    def peek(s, k=0):
        return s.t[s.i + k]

    def at(s, val, k=0):
        t = s.t[s.i + k]
        return t.kind in ("op", "kw") and t.val == val

    def next(s):
        t = s.t[s.i]
        s.i += 1
        return t

    def err(s, msg, fix="", tok=None):
        t = tok or s.peek()
        raise VowError("parse", t.line, t.col, "syntax", msg, fix)

    def expect(s, val):
        if not s.at(val):
            t = s.peek()
            s.err("expected '%s' but found %s" % (val, "end of file" if t.kind == "eof" else repr(t.val)),
                  "insert '%s'" % val)
        return s.next()

    def ident(s):
        t = s.peek()
        if t.kind != "id":
            s.err("expected identifier, found %r" % (t.val,))
        return s.next()

    # program
    def program(s):
        p = Program()
        while s.peek().kind != "eof":
            p.functions.append(s.function())
        return p

    def type_(s):
        t = s.peek()
        if s.at("("):
            s.next(); s.expect(")"); return UNIT
        if s.at("["):
            s.next()
            e = s.ident()
            if e.val != "i64":
                s.err("only [i64] arrays exist", "use [i64]", e)
            s.expect("]"); return ARRAY
        n = s.ident()
        if n.val == "i64": return I64
        if n.val == "bool": return BOOL
        if n.val in ("Option", "Result"):
            s.expect("<")
            e = s.ident()
            if e.val != "i64":
                s.err("%s only holds i64" % n.val, "use %s<i64>" % n.val, e)
            s.expect(">")
            return OPTION if n.val == "Option" else RESULT
        s.err("unknown type %r" % n.val, "use i64, bool, (), [i64], Option<i64>, Result<i64>", n)

    def function(s):
        kw = s.expect("fn")
        name = s.ident().val
        s.expect("(")
        params = []
        while not s.at(")"):
            pn = s.ident().val
            s.expect(":")
            params.append(Param(pn, s.type_()))
            if not s.at(")"):
                s.expect(",")
        s.expect(")")
        s.expect("->")
        ret = s.type_()
        effects = []
        if s.at("!"):
            s.next()
            while True:
                e = s.ident()
                if e.val not in ("io", "alloc"):
                    s.err("unknown effect %r" % e.val, "effects are io, alloc", e)
                effects.append(e.val)
                if not s.at(","):
                    break
                s.next()
        req, ens = [], []
        while s.at("requires") or s.at("ensures"):
            k = s.next().val
            (req if k == "requires" else ens).append(s.expr())
        body = s.block()
        return Function(kw.line, kw.col, name, params, ret, effects, req, ens, body)

    def block(s):
        s.expect("{")
        out = []
        while not s.at("}"):
            if s.peek().kind == "eof":
                s.err("unclosed block", "add '}'")
            out.append(s.stmt())
        s.expect("}")
        return out

    def stmt(s):
        t = s.peek()
        L, C = t.line, t.col
        if s.at("let"):
            s.next()
            mut = False
            if s.at("mut"):
                s.next(); mut = True
            n = s.ident().val
            if not s.at(":"):
                s.err("let needs a type annotation", "write `let %s: i64 = ...;`" % n)
            s.next()
            ty = s.type_()
            s.expect("=")
            v = s.expr()
            s.expect(";")
            return Let(L, C, n, mut, ty, v)
        if s.at("if"):
            return s.if_()
        if s.at("while"):
            s.next()
            cond = s.expr()
            invs, dec = [], None
            while s.at("invariant") or s.at("decreases"):
                k = s.next()
                if k.val == "invariant":
                    invs.append(s.expr())
                else:
                    if dec is not None:
                        s.err("only one decreases clause", "", k)
                    dec = s.expr()
            if dec is None:
                s.err("while loop needs a `decreases <expr>` clause", "add `decreases n - i` before '{'")
            return While(L, C, cond, invs, dec, s.block())
        if s.at("return"):
            s.next()
            if s.at(";"):
                s.next(); return Return(L, C, None)
            v = s.expr(); s.expect(";")
            return Return(L, C, v)
        if s.at("assert"):
            s.next()
            v = s.expr(); s.expect(";")
            return Assert(L, C, v)
        if s.at("match"):
            s.next()
            scr = s.expr()
            s.expect("{")
            arms = []
            while not s.at("}"):
                ct = s.next()
                if ct.val not in ("Some", "None", "Ok", "Err"):
                    s.err("match arm must be Some(x), None, Ok(x) or Err(x)", "", ct)
                b = None
                if ct.val != "None":
                    s.expect("("); b = s.ident().val; s.expect(")")
                s.expect("=>")
                arms.append(MatchArm(ct.val, b, s.block()))
                if s.at(","):
                    s.next()
            s.expect("}")
            return Match(L, C, scr, arms)
        if t.kind == "id" and s.at("=", 1):
            n = s.next().val; s.next()
            v = s.expr(); s.expect(";")
            return Assign(L, C, n, v)
        if t.kind == "id" and s.at("[", 1):
            # could be index-assign
            save = s.i
            n = s.next().val; s.next()
            idx = s.expr(); s.expect("]")
            if s.at("="):
                s.next()
                v = s.expr(); s.expect(";")
                return IndexAssign(L, C, n, idx, v)
            s.i = save
        e = s.expr()
        s.expect(";")
        return ExprStmt(L, C, e)

    def if_(s):
        t = s.expect("if")
        cond = s.expr()
        then = s.block()
        els = []
        if s.at("else"):
            s.next()
            els = [s.if_()] if s.at("if") else s.block()
        return If(t.line, t.col, cond, then, els)

    # expressions (precedence climbing)
    def expr(s):
        return s.implies()

    def implies(s):
        l = s.or_()
        if s.at("==>"):
            t = s.next()
            return Binary(t.line, t.col, "==>", l, s.implies())
        return l

    def or_(s):
        l = s.and_()
        while s.at("||"):
            t = s.next(); l = Binary(t.line, t.col, "||", l, s.and_())
        return l

    def and_(s):
        l = s.cmp()
        while s.at("&&"):
            t = s.next(); l = Binary(t.line, t.col, "&&", l, s.cmp())
        return l

    def cmp(s):
        l = s.add()
        for op in ("==", "!=", "<=", ">=", "<", ">"):
            if s.at(op):
                t = s.next()
                r = s.add()
                for op2 in ("==", "!=", "<=", ">=", "<", ">"):
                    if s.at(op2):
                        s.err("comparisons cannot be chained", "use `a < b && b < c`")
                return Binary(t.line, t.col, op, l, r)
        return l

    def add(s):
        l = s.mul()
        while s.at("+") or s.at("-"):
            t = s.next(); l = Binary(t.line, t.col, t.val, l, s.mul())
        return l

    def mul(s):
        l = s.unary()
        while s.at("*") or s.at("/") or s.at("%"):
            t = s.next(); l = Binary(t.line, t.col, t.val, l, s.unary())
        return l

    def unary(s):
        if s.at("-") or s.at("!"):
            t = s.next()
            o = s.unary()
            if t.val == "-" and isinstance(o, IntLit):
                return IntLit(t.line, t.col, -o.value)
            return Unary(t.line, t.col, t.val, o)
        return s.postfix()

    def postfix(s):
        e = s.primary()
        while s.at("["):
            t = s.next()
            i = s.expr(); s.expect("]")
            e = Index(t.line, t.col, e, i)
        return e

    def primary(s):
        t = s.peek()
        if t.kind == "int":
            s.next(); return IntLit(t.line, t.col, t.val)
        if s.at("true") or s.at("false"):
            s.next(); return BoolLit(t.line, t.col, t.val == "true")
        if s.at("("):
            s.next(); e = s.expr(); s.expect(")"); return e
        if s.at("None"):
            s.next(); return Ctor(t.line, t.col, "None", None)
        if s.at("Some") or s.at("Ok") or s.at("Err"):
            s.next(); s.expect("("); a = s.expr(); s.expect(")")
            return Ctor(t.line, t.col, t.val, a)
        if s.at("result"):
            s.next(); return Var(t.line, t.col, "result")
        if s.at("forall") or s.at("exists"):
            s.next()
            v = s.ident().val
            s.expect("in")
            lo = s.add(); s.expect(".."); hi = s.add(); s.expect(":")
            body = s.expr()
            return Quant(t.line, t.col, t.val, v, lo, hi, body)
        if (t.kind == "id" and t.val in ("sum", "count", "max", "min")
                and s.at("(", 1) and s.peek(2).kind == "id" and s.at("in", 3)):
            s.next(); s.next()
            v = s.ident().val
            s.expect("in")
            lo = s.add(); s.expect(".."); hi = s.add(); s.expect(":")
            body = s.expr()
            s.expect(")")
            return Quant(t.line, t.col, t.val, v, lo, hi, body)
        if t.kind == "id":
            s.next()
            if s.at("("):
                s.next()
                args = []
                while not s.at(")"):
                    args.append(s.expr())
                    if not s.at(")"):
                        s.expect(",")
                s.expect(")")
                return Call(t.line, t.col, t.val, args)
            return Var(t.line, t.col, t.val)
        s.err("expected an expression, found %r" % (t.val,))


def parse(src):
    return Parser(src).program()
