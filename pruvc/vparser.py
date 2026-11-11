"""Pruv lexer + recursive-descent parser -> vast.Program"""
import re
from vast import *

KEYWORDS = {"fn", "let", "mut", "if", "else", "while", "return", "match", "true", "false",
            "invariant", "decreases", "requires", "ensures", "assert", "forall", "exists",
            "in", "Some", "None", "Ok", "Err", "struct", "enum", "is_variant", "variant_field"}
# Rust keywords that are not Pruv keywords: user names go into the generated Rust unchanged.
RUST_KEYWORDS = {"as", "async", "await", "break", "const", "continue", "crate", "dyn", "enum", "extern", "for",
                 "impl", "loop", "mod", "move", "pub", "ref", "self", "Self", "static", "struct", "super",
                 "trait", "type", "unsafe", "use", "where", "abstract", "become", "box", "do", "final", "gen",
                 "macro", "override", "priv", "try", "typeof", "unsized", "virtual", "yield", "union", "_"}
TOKEN_RE = re.compile(r"""
 (?P<ws>[ \t\r]+) | (?P<nl>\n) | (?P<comment>//[^\n]*)
|(?P<int>[0-9][0-9_]*)
|(?P<id>[A-Za-z_][A-Za-z0-9_]*)
|(?P<op>==>|==|!=|<=|>=|&&|\|\||->|=>|::|\.\.|\.|\||[-+*/%<>=!(){}\[\],:;])
""", re.X)


class Tok:
    __slots__ = ("kind", "val", "line", "col", "end")

    def __init__(s, kind, val, line, col, end=None):
        s.kind, s.val, s.line, s.col, s.end = kind, val, line, col, end   # end: column after the token (same line)

    def __repr__(s):
        return "%s(%r)" % (s.kind, s.val)


def _bar_after_type(toks):
    """STAGE1 A: `|` is a token only right after a type-looking name in a type position
    (`x: i64 |`, `-> i64 |`, `[i64 |`, `Option<i64 |`); everywhere else it is the old bad_char."""
    if len(toks) < 2:
        return False
    a, b = toks[-1], toks[-2]
    if a.kind != "id" or b.kind != "op" or b.val not in (":", "->", "[", "<"):
        return False
    return a.val in ("i64", "bool", "Option", "Result") or a.val[:1].isupper()


def lex(src):
    toks, pos, line, lstart = [], 0, 1, 0
    while pos < len(src):
        m = TOKEN_RE.match(src, pos)
        if not m:
            raise PruvError("parse", line, pos - lstart + 1, "bad_char",
                           "unexpected character %r" % src[pos], "remove it")
        k = m.lastgroup
        v = m.group(k)
        col = pos - lstart + 1
        if k == "nl":
            line += 1
            lstart = m.end()
        elif k == "int":
            if v.endswith("_"):
                raise PruvError("parse", line, col, "bad_int", "integer literal ends with _", "")
            toks.append(Tok("int", int(v.replace("_", "")), line, col, col + len(v)))
        elif k == "id":
            if v not in KEYWORDS and (v.startswith("pruv_") or "__" in v or v in RUST_KEYWORDS):
                raise PruvError("parse", line, col, "reserved_name",
                               "name %r is reserved for the compiler" % v,
                               "rename it; names starting with pruv_, containing __, `_` and Rust keywords are reserved")
            toks.append(Tok("kw" if v in KEYWORDS else "id", v, line, col, col + len(v)))
        elif k == "op":
            if v == "|" and not _bar_after_type(toks):
                # a lone `|` outside a type position stays the lexical error it always was
                raise PruvError("parse", line, col, "bad_char", "unexpected character %r" % v, "remove it")
            toks.append(Tok("op", v, line, col, col + len(v)))
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
        raise PruvError("parse", t.line, t.col, "syntax", msg, fix)

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
        raise PruvError("parse", tok.line, tok.col, "unsupported_type",
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
        """a type in a position where refinements are not allowed (fields, ...)"""
        return s.type_r(False)[0]

    # ---- STAGE1 A: refinement annotations ----
    def ref_position(s, tok):
        raise PruvError("parse", tok.line, tok.col, "refinement_position",
                        "a refinement annotation is only allowed on a parameter, a return type or a let/let mut type",
                        "move the condition into requires/ensures/invariant, or annotate the parameter/local instead")

    def ref_syntax(s, tok, msg, fix=""):
        raise PruvError("parse", tok.line, tok.col, "refinement_syntax", msg,
                        fix or "write bounds as signed decimal integer literals, e.g. -1_000_000_000..=1_000_000_000")

    def ref_int(s, what):
        """signed decimal integer literal (unbounded Python int; the range is checked by refine.py)"""
        t = s.peek()
        sign = 1
        if s.at("-") or s.at("+"):
            sign = -1 if t.val == "-" else 1
            s.next()
        n = s.peek()
        if n.kind != "int":
            s.ref_syntax(n, "refinement %s must be a decimal integer literal, found %s" % (
                what, "end of file" if n.kind == "eof" else repr(n.val)))
        s.next()
        nx = s.peek()
        if nx.kind == "id" and nx.line == n.line and nx.col == n.end:
            if nx.val[0] in "eE" and all(c in "0123456789" for c in nx.val[1:]):
                fix = "exponent notation is not supported: write the full decimal number, e.g. 1_000_000_000 for 1e9"
            else:
                fix = "only plain decimal integer literals are allowed: write the full decimal number, e.g. 16 instead of 0x10"
            s.ref_syntax(nx, "refinement %s must be a decimal integer literal; `%s%s` is not one" % (
                what, n.val, nx.val), fix)
        for op in ("*", "+", "-", "/", "%"):
            if s.at(op):
                s.ref_syntax(nx, "refinement %s must be a single integer literal, found an expression with `%s`" % (
                    what, op), "bounds are integer literals only: compute the value and write it out, e.g. 0..=6 instead of 0..=2*3")
        return sign * n.val

    def ref_range(s):
        """`L..=U` after `|`"""
        lo = s.ref_int("lower bound")
        if not s.at(".."):
            s.ref_syntax(s.peek(), "expected '..=' after the lower bound of a refinement",
                         "a value range is written closed: `L..=U` (both ends included)")
        dd = s.next()
        eq = s.peek()
        if not (s.at("=") and eq.line == dd.line and eq.col == dd.col + 2):
            s.ref_syntax(eq, "expected '..=' (closed range) in a refinement, found '..'",
                         "a value range is written `L..=U`; `L..U` is only used by forall/exists/sum/count/max/min and excludes U")
        s.next()
        hi = s.ref_int("upper bound")
        return lo, hi

    def ref_len(s):
        """`; <= N` (the `;` not consumed yet)"""
        s.expect(";")
        s.expect("<=")
        return s.ref_int("length bound")

    def type_r(s, allow):
        """-> (Type, Refinement or None). `allow`: refinement annotations are legal here."""
        t = s.peek()
        if s.at("("):
            s.next(); s.expect(")"); return UNIT, None
        if s.at("["):
            s.next()
            e = s.ident()
            if e.val != "i64":
                if e.val[0].isupper():
                    s.unsupported("[%s]" % e.val, e)
                s.err("only [i64] arrays exist", "use [i64]", e)
            lo = hi = maxlen = None
            if s.at("|"):
                if not allow:
                    s.ref_position(s.peek())
                s.next()
                lo, hi = s.ref_range()
            if s.at(";") and s.at("<=", 1):
                if not allow:
                    s.ref_position(s.peek())
                maxlen = s.ref_len()
            elif lo is not None and s.at(";"):
                s.ref_syntax(s.peek(), "expected ']' or '; <=N' after the element range")
            elif s.at(";"):
                s.ref_syntax(s.peek(), "expected '<=' after ';' in an array length bound",
                             "write the length bound as `<=N`, e.g. [i64; <=8]")
            s.expect("]")
            if lo is None and maxlen is None:
                return ARRAY, None
            return ARRAY, Refinement(t.line, t.col, "array", "i64", lo, hi, maxlen)
        n = s.ident()
        if n.val == "i64": ty = I64
        elif n.val == "bool": ty = BOOL
        elif n.val in ("Option", "Result"):
            s.expect("<")
            e = s.ident()
            if s.at("|"):
                s.ref_position(s.peek())
            if e.val != "i64":
                if e.val[0].isupper():
                    s.unsupported("%s<%s>" % (n.val, e.val), e)
                s.err("%s only holds i64" % n.val, "use %s<i64>" % n.val, e)
            s.expect(">")
            ty = OPTION if n.val == "Option" else RESULT
        else:
            # a user type: the checker resolves the name. Lower-case spellings of the
            # built-in Type names must not alias them.
            if n.val in ("unit", "array", "option", "result"):
                s.err("unknown type %r" % n.val, "use i64, bool, (), [i64], Option<i64>, Result<i64> or a declared struct/enum", n)
            ty = Type(n.val)
        if s.at("|"):
            if not allow:
                s.ref_position(s.peek())
            s.next()
            lo, hi = s.ref_range()
            # a non-i64 base is reported by refine.py as type/refinement_base
            return ty, Refinement(t.line, t.col, "scalar", n.val, lo, hi, None)
        return ty, None

    def function(s):
        kw = s.expect("fn")
        name = s.ident().val
        s.expect("(")
        params = []
        while not s.at(")"):
            pn = s.ident().val
            s.expect(":")
            pt, pr = s.type_r(True)
            params.append(Param(pn, pt, pr))
            if not s.at(")"):
                s.expect(",")
        s.expect(")")
        s.expect("->")
        ret, ret_refine = s.type_r(True)
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
        return Function(kw.line, kw.col, name, params, ret, effects, req, ens, body, ret_refine)

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
            ty, rf = s.type_r(True)
            s.expect("=")
            v = s.expr()
            s.expect(";")
            return Let(L, C, n, mut, ty, v, rf)
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
