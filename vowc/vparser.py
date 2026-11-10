"""Vow lexer + recursive-descent parser -> vast.Program"""
import re
from vast import *

KEYWORDS = {"fn", "let", "mut", "if", "else", "while", "return", "match", "true", "false",
            "invariant", "decreases", "requires", "ensures", "assert", "forall", "exists",
            "in", "Some", "None", "Ok", "Err", "struct", "enum", "is_variant", "variant_field"}
# Rust keywords that are not Vow keywords: user names go into the generated Rust unchanged.
RUST_KEYWORDS = {"as", "async", "await", "break", "const", "continue", "crate", "dyn", "enum", "extern", "for",
                 "impl", "loop", "mod", "move", "pub", "ref", "self", "Self", "static", "struct", "super",
                 "trait", "type", "unsafe", "use", "where", "abstract", "become", "box", "do", "final", "gen",
                 "macro", "override", "priv", "try", "typeof", "unsized", "virtual", "yield", "union", "_"}
TOKEN_RE = re.compile(r"""
 (?P<ws>[ \t\r]+) | (?P<nl>\n) | (?P<comment>//[^\n]*)
|(?P<int>[0-9][0-9_]*)
|(?P<id>[A-Za-z_][A-Za-z0-9_]*)
|(?P<op>==>|==|!=|<=|>=|&&|\|\||->|=>|::|\.\.|\.|[-+*/%<>=!(){}\[\],:;])
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
            if v not in KEYWORDS and (v.startswith("vow_") or "__" in v or v in RUST_KEYWORDS):
                raise VowError("parse", line, col, "reserved_name",
                               "name %r is reserved for the compiler" % v,
                               "rename it; names starting with vow_, containing __, `_` and Rust keywords are reserved")
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
            if s.at("struct"):
                p.types.append(s.struct_decl())
            elif s.at("enum"):
                p.types.append(s.enum_decl())
            else:
                p.functions.append(s.function())
        return p

    def unsupported(s, what, tok):
        raise VowError("parse", tok.line, tok.col, "unsupported_type",
                       "%s is not supported" % what,
                       "arrays hold i64 and Option/Result hold i64; user types can only be used directly")

    def field_decl(s):
        n = s.ident()
        s.expect(":")
        return FieldDecl(n.line, n.col, n.val, s.type_())

    def field_list(s, close):
        """`name: Type, ...` up to (not including) `close`; trailing comma allowed"""
        out = []
        while not s.at(close):
            out.append(s.field_decl())
            if not s.at(close):
                s.expect(",")
        return out

    def struct_decl(s):
        kw = s.expect("struct")
        n = s.ident()
        s.expect("{")
        fields = s.field_list("}")
        s.expect("}")
        return StructDecl(kw.line, kw.col, n.val, fields)

    def enum_decl(s):
        kw = s.expect("enum")
        n = s.ident()
        s.expect("{")
        variants = []
        while not s.at("}"):
            v = s.ident()
            fields = []
            if s.at("("):
                lp = s.next()
                if s.at(")"):
                    s.err("a variant without fields is written without parentheses",
                          "write `%s` instead of `%s()`" % (v.val, v.val), lp)
                fields = s.field_list(")")
                s.expect(")")
            variants.append(VariantDecl(v.line, v.col, v.val, fields))
            if not s.at("}"):
                s.expect(",")
        s.expect("}")
        return EnumDecl(kw.line, kw.col, n.val, variants)

    def type_(s):
        t = s.peek()
        if s.at("("):
            s.next(); s.expect(")"); return UNIT
        if s.at("["):
            s.next()
            e = s.ident()
            if e.val != "i64":
                if e.val[0].isupper():
                    s.unsupported("[%s]" % e.val, e)
                s.err("only [i64] arrays exist", "use [i64]", e)
            s.expect("]"); return ARRAY
        n = s.ident()
        if n.val == "i64": return I64
        if n.val == "bool": return BOOL
        if n.val in ("Option", "Result"):
            s.expect("<")
            e = s.ident()
            if e.val != "i64":
                if e.val[0].isupper():
                    s.unsupported("%s<%s>" % (n.val, e.val), e)
                s.err("%s only holds i64" % n.val, "use %s<i64>" % n.val, e)
            s.expect(">")
            return OPTION if n.val == "Option" else RESULT
        # a user type: the checker resolves the name. Lower-case spellings of the
        # built-in Type names must not alias them.
        if n.val in ("unit", "array", "option", "result"):
            s.err("unknown type %r" % n.val, "use i64, bool, (), [i64], Option<i64>, Result<i64> or a declared struct/enum", n)
        return Type(n.val)

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
                if ct.kind == "id" and s.at("::"):
                    s.next()
                    vt = s.ident()
                    binders = []
                    if s.at("("):
                        lp = s.next()
                        if s.at(")"):
                            s.err("a pattern lists one name per field; a variant without fields has no parentheses",
                                  "write `%s::%s =>`" % (ct.val, vt.val), lp)
                        while True:
                            binders.append(s.ident().val)
                            if not s.at(","):
                                break
                            s.next()
                        s.expect(")")
                    s.expect("=>")
                    arms.append(MatchArm(ct.line, ct.col, ct.val, vt.val, binders, s.block()))
                else:
                    if ct.val not in ("Some", "None", "Ok", "Err"):
                        s.err("match arm must be Some(x), None, Ok(x), Err(x) or Enum::Variant(...)", "", ct)
                    binders = []
                    if ct.val != "None":
                        s.expect("("); binders = [s.ident().val]; s.expect(")")
                    s.expect("=>")
                    arms.append(MatchArm(ct.line, ct.col, None, ct.val, binders, s.block()))
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
        if t.kind == "id" and s.at(".", 1):
            # field assignment `p.a.b = e;`, otherwise an expression statement
            save = s.i
            n = s.next().val
            path = []
            while s.at("."):
                s.next()
                path.append(s.ident().val)
            if s.at("="):
                s.next()
                v = s.expr(); s.expect(";")
                return FieldAssign(L, C, n, path, v)
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
        while True:
            if s.at("["):
                t = s.next()
                i = s.expr(); s.expect("]")
                e = Index(t.line, t.col, e, i)
            elif s.at("."):
                s.next()
                f = s.ident()
                e = FieldAccess(e.line, e.col, e, f.val)
            else:
                break
        return e

    def enum_ref(s):
        """`Enum::Variant` -> (enum token, variant token)"""
        en = s.ident()
        s.expect("::")
        return en, s.ident()

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
        if s.at("is_variant"):
            s.next(); s.expect("(")
            v = s.expr(); s.expect(",")
            en, vt = s.enum_ref()
            s.expect(")")
            return IsVariant(t.line, t.col, v, en.val, vt.val)
        if s.at("variant_field"):
            s.next(); s.expect("(")
            v = s.expr(); s.expect(",")
            en, vt = s.enum_ref()
            s.expect(",")
            f = s.ident()
            s.expect(")")
            return VariantField(t.line, t.col, v, en.val, vt.val, f.val)
        if t.kind == "id":
            s.next()
            if s.at("::"):
                s.next()
                vt = s.ident()
                args = []
                if s.at("("):
                    lp = s.next()
                    if s.at(")"):
                        s.err("empty parentheses after a variant",
                              "write `%s::%s` for a variant without fields, or pass its fields as arguments"
                              % (t.val, vt.val), lp)
                    while not s.at(")"):
                        args.append(s.expr())
                        if not s.at(")"):
                            s.expect(",")
                    s.expect(")")
                return EnumCtor(t.line, t.col, t.val, vt.val, args)
            if t.val[0].isupper() and s.at("{"):
                s.next()
                inits = []
                while not s.at("}"):
                    fn = s.ident()
                    s.expect(":")
                    inits.append(FieldInit(fn.line, fn.col, fn.val, s.expr()))
                    if not s.at("}"):
                        s.expect(",")
                s.expect("}")
                return StructLit(t.line, t.col, t.val, inits)
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
