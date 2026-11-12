"""Pruv lexer + recursive-descent parser -> vast.Program"""
import re
from vast import *
from typeinfo import decl_owner, fn_owner

KEYWORDS = {"fn", "let", "mut", "if", "else", "while", "return", "match", "true", "false",
            "cost", "spent", "invariant", "decreases", "requires", "ensures", "assert", "forall", "exists",
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
    return a.val in ("i64", "bool", "u8", "Option", "Result") or a.val[:1].isupper()


_MOD_NAME_RE = re.compile(r"[a-z][A-Za-z0-9_]*\Z")   # G4: module names
_STR_ESC = {'"': 0x22, "\\": 0x5C, "n": 0x0A, "r": 0x0D, "t": 0x09, "0": 0x00}


def _lex_string(src, pos, line, lstart):
    """G2 B0: read a string literal starting at the opening quote src[pos].
    -> (raw text with quotes, position after the closing quote). Raises PruvError at the first bad character."""
    qcol = pos - lstart + 1
    i = pos + 1
    n = len(src)
    while True:
        if i >= n:
            raise PruvError("parse", line, qcol, "string_unterminated",
                            "unterminated string literal", 'close it with "')
        c = src[i]
        if c == '"':
            return src[pos:i + 1], i + 1
        if c == "\\":
            if i + 1 >= n:
                raise PruvError("parse", line, qcol, "string_unterminated",
                                "unterminated string literal", 'close it with "')
            d = src[i + 1]
            if d not in _STR_ESC:
                raise PruvError("parse", line, i - lstart + 1, "string_escape",
                                "unsupported escape %r in a string literal" % (c + d),
                                'use one of \\" \\\\ \\n \\r \\t \\0')
            i += 2
            continue
        if c == "\n":
            raise PruvError("parse", line, i - lstart + 1, "string_character",
                            "a string literal cannot span lines",
                            "close the string before the line break, or write \\n")
        o = ord(c)
        if o < 0x20 or o == 0x7F:
            raise PruvError("parse", line, i - lstart + 1, "string_character",
                            "a string literal cannot contain the control character %r" % c,
                            "write it as an escape (\\n, \\r, \\t, \\0) or remove it")
        i += 1


def _decode_string(raw):
    """raw literal text (already validated by _lex_string) -> bytes"""
    body = raw[1:-1]
    out = bytearray()
    i = 0
    while i < len(body):
        c = body[i]
        if c == "\\":
            out.append(_STR_ESC[body[i + 1]])
            i += 2
        else:
            out.extend(c.encode("utf-8"))
            i += 1
    return bytes(out)


# G6 A0: `move` is a Rust keyword (reserved name) but also contextual syntax: it is a move token only when a
# name, number, string, `(` or `[` follows it and it does not sit in a declaration position; everywhere else it
# stays the old reserved_name error.
_MOVE_AHEAD = re.compile(r"(?:[ \t\r\n]|//[^\n]*(?=\n|\Z))*[A-Za-z_0-9\"(\[]")


def _move_token(src, end, toks):
    if toks and ((toks[-1].kind == "kw" and toks[-1].val in ("fn", "let", "mut"))
                 or (toks[-1].kind == "op" and toks[-1].val in (".", "::"))):
        return False
    return _MOVE_AHEAD.match(src, end) is not None


# G4 A0: `mod`, `pub` and `crate` are Rust keywords (reserved names) but also contextual module syntax. They become a
# `kw` token only in the positions below; everywhere else they stay the old reserved_name error.
#   mod   at top level (brace depth 0), at the start of an item (first token, after `}` or `;`, or after `pub`), and
#         followed by a name, a string or `{` (so `mod x;`, `mod "p";`, `mod x { }` reach the module-syntax errors)
#   pub   at top level, at the start of an item (or after another `pub`), followed by fn/struct/enum/mod/trusted/rust/pub
#   crate right before `::`, not after fn/let/mut/struct/enum and not after `.` or `::`
_G4_SKIP = r"(?:[ \t\r\n]|//[^\n]*(?=\n|\Z))*"
_G4_MOD_AHEAD = re.compile(_G4_SKIP + r"[A-Za-z_\"{]")
_G4_PUB_AHEAD = re.compile(_G4_SKIP + r"(?:fn|struct|enum|mod|pub|trusted|rust)(?![A-Za-z0-9_])")
_G4_CRATE_AHEAD = re.compile(_G4_SKIP + r"::")


def _g4_token(word, src, end, toks, depth):
    prev = toks[-1] if toks else None
    if word == "crate":
        if prev is not None and ((prev.kind == "kw" and prev.val in ("fn", "let", "mut", "struct", "enum"))
                                 or (prev.kind == "op" and prev.val in (".", "::"))):
            return False
        return _G4_CRATE_AHEAD.match(src, end) is not None
    if depth != 0:
        return False
    start = prev is None or (prev.kind == "op" and prev.val in ("}", ";")) or (prev.kind == "kw" and prev.val == "pub")
    if not start:
        return False
    if word == "mod":
        return _G4_MOD_AHEAD.match(src, end) is not None
    return _G4_PUB_AHEAD.match(src, end) is not None


def lex(src, toks=None):
    """`toks` (optional) receives the tokens; on a lex error it keeps the ones read so far (G4 sniff)"""
    if toks is None:
        toks = []
    pos, line, lstart = 0, 1, 0
    depth = 0   # G4: brace depth
    while pos < len(src):
        if src[pos] == '"':
            raw, end_pos = _lex_string(src, pos, line, lstart)
            col = pos - lstart + 1
            toks.append(Tok("str", raw, line, col, col + len(raw)))
            pos = end_pos
            continue
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
            # `move move`: the second one is a Move token too, so the parser reports foreign_syntax
            if v == "move" and ((toks and toks[-1].kind == "move") or _move_token(src, m.end(), toks)):
                toks.append(Tok("move", v, line, col, col + len(v)))
                pos = m.end()
                continue
            if v in ("mod", "pub", "crate") and _g4_token(v, src, m.end(), toks, depth):
                toks.append(Tok("kw", v, line, col, col + len(v)))
                pos = m.end()
                continue
            if v not in KEYWORDS and (v.startswith("pruv_") or "__" in v or v in RUST_KEYWORDS):
                raise PruvError("parse", line, col, "reserved_name",
                               "name %r is reserved for the compiler" % v,
                               "rename it; names starting with pruv_, containing __, `_` and Rust keywords are reserved")
            toks.append(Tok("kw" if v in KEYWORDS else "id", v, line, col, col + len(v)))
        elif k == "op":
            if v == "|" and not _bar_after_type(toks):
                # a lone `|` outside a type position stays the lexical error it always was
                raise PruvError("parse", line, col, "bad_char", "unexpected character %r" % v, "remove it")
            if v == "{":
                depth += 1
            elif v == "}" and depth > 0:
                depth -= 1
            toks.append(Tok("op", v, line, col, col + len(v)))
        pos = m.end()
    toks.append(Tok("eof", None, line, pos - lstart + 1))
    return toks


class Parser:
    def __init__(s, src):
        s.t = lex(src)
        s.i = 0
        s.scope = {}   # G3: type-parameter name -> bound parameter Type, inside a generic declaration

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
        p.items = []
        p.mods = []
        while s.peek().kind != "eof":
            pub = None
            if s.at("pub"):               # G4: visibility of the next item
                pub = s.next()
                if s.at("pub"):
                    s.visibility_syntax(s.peek(), "`pub` is written once", "remove the second `pub`")
                if s.at("mod"):
                    s.visibility_syntax(pub, "`pub mod` is not supported: module namespaces have no visibility",
                                        "write `mod name;`")
            if s.at("mod"):
                p.mods.append(s.mod_decl())
            elif s.at("struct"):
                d = s.struct_decl()
                d.pub = pub is not None
                p.types.append(d)
                p.items.append(d)
            elif s.at("enum"):
                d = s.enum_decl()
                d.pub = pub is not None
                p.types.append(d)
                p.items.append(d)
            elif s.peek().kind == "id" and s.peek().val == "trusted":
                t = s.peek()
                if pub is not None:
                    s.visibility_syntax(pub, "a trusted rust fn cannot be `pub`",
                                        "keep it private and expose it through a public Pruv function with explicit contracts")
                if not (s.peek(1).kind == "id" and s.peek(1).val == "rust" and s.at("fn", 2)):
                    s.foreign_syntax(t, "expected `rust fn` after `trusted`",
                                     'write `trusted rust fn name(..) -> T ensures .. = "::path";`')
                s.next(); s.next()
                f = s.function(t)
                p.functions.append(f)
                p.items.append(f)
            elif s.peek().kind == "id" and s.peek().val == "rust" and s.at("fn", 1):
                s.foreign_syntax(s.peek(), "missing `trusted`", "write `trusted rust fn ...`")
            else:
                f = s.function()
                f.pub = pub is not None
                p.functions.append(f)
                p.items.append(f)
            if pub is not None:
                p.has_pub = True
        return p

    # ---- G4 A0: module declarations and paths ----
    def visibility_syntax(s, tok, msg, fix=""):
        raise PruvError("parse", tok.line, tok.col, "visibility_syntax", msg, fix)

    def module_syntax(s, tok, msg, fix=""):
        raise PruvError("parse", tok.line, tok.col, "module_syntax", msg, fix)

    def path_syntax(s, tok, msg, fix="write an absolute path such as crate::math::clamp"):
        raise PruvError("parse", tok.line, tok.col, "path_syntax", msg, fix)

    def mod_decl(s):
        """`mod name;` at top level -> ModDecl"""
        kw = s.next()
        t = s.peek()
        if t.kind == "str":
            s.module_syntax(t, "a module path cannot be a string", "write `mod name;`; the file is <name>.pruv")
        if s.at("{"):
            s.module_syntax(t, "inline modules are not supported", "move the items into <name>.pruv and write `mod name;`")
        if t.kind != "id":
            s.module_syntax(t, "expected a module name after `mod`", "write `mod name;`")
        s.next()
        if not _MOD_NAME_RE.match(t.val):
            s.module_syntax(t, "module name %s must match [a-z][A-Za-z0-9_]*" % t.val,
                            "rename it, e.g. %s" % (t.val[:1].lower() + t.val[1:]))
        if s.at("{"):
            s.module_syntax(s.peek(), "inline modules are not supported",
                            "move the items into %s.pruv and write `mod %s;`" % (t.val, t.val))
        if not s.at(";"):
            s.module_syntax(s.peek(), "expected ';' after `mod %s`" % t.val, "write `mod %s;`" % t.val)
        s.next()
        return ModDecl(kw.line, kw.col, t.val)

    def crate_path(s, allow_targs):
        """at `crate`: `crate::a::b` -> (crate token, [segment names]); stops before a `::<` when allow_targs"""
        t = s.next()
        segs = []
        while s.at("::"):
            if s.at("<", 1):
                if allow_targs and segs:
                    break
                s.path_syntax(s.peek(1), "type arguments are not allowed here",
                              "attach type arguments to the item: crate::m::f::<T>(x)")
            s.next()
            n = s.peek()
            if n.kind != "id":
                s.path_syntax(n, "expected a name after `::` in a path, found %s" % (
                    "end of file" if n.kind == "eof" else repr(n.val)))
            segs.append(s.next().val)
        if not segs:
            s.path_syntax(s.peek(), "a path needs at least one name after `crate::`")
        return t, segs

    def type_path(s):
        """a `crate::..` path in a type position -> a pseudo identifier token whose value is the full path"""
        t, segs = s.crate_path(False)
        return Tok("id", "crate::" + "::".join(segs), t.line, t.col, None)

    def foreign_syntax(s, tok, msg, fix=""):
        raise PruvError("parse", tok.line, tok.col, "foreign_syntax", msg, fix)

    def inout_syntax(s, tok, msg, fix=""):
        raise PruvError("parse", tok.line, tok.col, "inout_syntax", msg, fix)

    def parallel_syntax(s, tok, msg, fix="write semicolon-terminated calls: `par { f(inout a); g(inout b); }`"):
        raise PruvError("parse", tok.line, tok.col, "parallel_syntax", msg, fix)

    def par_stmt(s):
        """G7 A0: at the contextual `par` followed by `{`: `par { call; call; ... }` (no trailing semicolon).
        Every member must be a semicolon-terminated call; fewer than two branches is the checker's type/parallel_arity."""
        t = s.next()
        s.next()   # `{`
        calls = []
        while not s.at("}"):
            if s.peek().kind == "eof":
                s.parallel_syntax(s.peek(), "unclosed par block", "add '}'")
            m = s.peek()
            try:
                e = s.expr()
            except PruvError as ex:
                if ex.code != "syntax":
                    raise
                raise PruvError("parse", ex.line, ex.col, "parallel_syntax",
                                "malformed par block: " + ex.message,
                                "write semicolon-terminated calls: `par { f(inout a); g(inout b); }`")
            if not isinstance(e, Call):
                s.parallel_syntax(m, "a par block member must be a call", "write only calls, e.g. `f(inout a);`")
            if not s.at(";"):
                s.parallel_syntax(s.peek(), "a par block call must end with ';'", "insert ';' after the call")
            s.next()
            calls.append(e)
        s.next()   # `}`
        if s.at(";"):
            s.parallel_syntax(s.peek(), "a par block takes no trailing ';'", "remove the ';' after '}'")
        return Par(t.line, t.col, calls)

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

    # ---- G3 A1: type parameters and type applications ----
    def generic_syntax(s, tok, msg, fix=""):
        raise PruvError("parse", tok.line, tok.col, "generic_syntax", msg, fix)

    def type_params(s, owner):
        """`<T, U: Element>` (the `<` is the current token) -> [TypeParam]. Also installs the parse scope:
        inside the declaration a bare parameter name is a bound parameter type (owner identity + index)."""
        s.expect("<")
        if s.at(">"):
            s.generic_syntax(s.peek(), "a type-parameter list cannot be empty",
                             "remove `<>`, or declare at least one parameter, e.g. <T>")
        out = []
        while True:
            n = s.ident()
            bound = None
            if s.at(":"):
                s.next()
                b = s.peek()
                if b.kind != "id":
                    s.generic_syntax(b, "expected a bound name after ':'", "the only bound is Element: <T: Element>")
                s.next()
                bound = b.val
                if s.at("+"):
                    s.generic_syntax(s.peek(), "bound lists are not supported",
                                     "a parameter has at most one bound: <T: Element>")
            out.append(TypeParam(n.line, n.col, n.val, bound))
            if not s.at(","):
                break
            s.next()
            if s.at(">"):
                s.generic_syntax(s.peek(), "a type-parameter list has no trailing comma", "remove the last ','")
        s.expect(">")
        s.scope = {}
        for i, tp in enumerate(out):
            s.scope.setdefault(tp.name, mk_param(owner, i, tp.name))
        return out

    def type_arg_list(s, expr):
        """type arguments after an already consumed `<`, through the closing `>` -> [Type].
        expr: expression position, where a malformed list is a generic_syntax error."""
        out = []
        while True:
            if s.at(">") or s.at(","):
                s.generic_syntax(s.peek(), "missing type argument",
                                 "write a type between the angle brackets, e.g. Pair<i64, bool>")
            out.append(s.type_r(False)[0])
            if not s.at(","):
                break
            s.next()
        if not s.at(">"):
            if expr:
                s.generic_syntax(s.peek(), "malformed type application: expected '>' after the type arguments",
                                 "write f::<T>(x), Pair::<A, B> { .. } or Choice::<A, B>::Left(x)")
            s.expect(">")
        s.next()
        return out

    def expr_targs(s):
        """at `::` `<` in an expression: consume `::<T, ...>` -> [Type]"""
        s.expect("::")
        s.expect("<")
        return s.type_arg_list(True)

    def named_type(s, n):
        """n: an already consumed identifier naming a type parameter, Option/Result or a user type
        -> Type (no refinement; type arguments are parsed here)."""
        if n.val in ("Option", "Result"):
            s.expect("<")
            a = s.peek()
            if a.kind == "id" and a.val in ("u8", "i32"):
                s.unsupported("%s<%s>" % (n.val, a.val), a)
            args = s.type_arg_list(False)
            if len(args) == 1:
                return mk_option(args[0]) if n.val == "Option" else mk_result(args[0])
            return Type("option" if n.val == "Option" else "result", tuple(args))   # wrong arity: the checker reports it
        if s.at("<"):
            s.next()
            # also a parameter applied to arguments (`T<X>`): kept unresolved, the checker reports it
            return Type(n.val, tuple(s.type_arg_list(False)))
        if n.val in s.scope:
            return s.scope[n.val]
        return Type(n.val)

    def struct_decl(s):
        kw = s.expect("struct")
        n = s.ident()
        tparams = s.type_params(decl_owner(n.val)) if s.at("<") else ()
        s.expect("{")
        fields = s.field_list("}")
        s.expect("}")
        s.scope = {}
        d = StructDecl(kw.line, kw.col, n.val, fields)
        d.tparams = tparams
        return d

    def enum_decl(s):
        kw = s.expect("enum")
        n = s.ident()
        tparams = s.type_params(decl_owner(n.val)) if s.at("<") else ()
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
        s.scope = {}
        d = EnumDecl(kw.line, kw.col, n.val, variants)
        d.tparams = tparams
        return d

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
            e = s.type_path() if s.at("crate") else s.ident()   # G4: a qualified element type
            if e.val in ("i64", "u8", "bool"):
                elem = {"i64": I64, "u8": U8, "bool": BOOL}[e.val]
            elif e.val[0].isupper() or e.val.startswith("crate::"):
                elem = s.named_type(e)   # G3: a type parameter (checker: needs Element); other types: checker rejects
            else:
                # G2 A5: [bool] joins the element names
                s.err("only [i64], [u8] and [bool] arrays exist", "use [i64], [u8] or [bool]", e)
            aty = mk_array(elem)   # [i64]/[u8]/[bool] -> the legacy constants (G2 A5)
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
                return aty, None
            return aty, Refinement(t.line, t.col, "array", e.val, lo, hi, maxlen)
        n = s.type_path() if s.at("crate") else s.ident()   # G4: a qualified type path
        if n.val in ("u8", "i32"):
            raise PruvError("parse", n.line, n.col, "element_storage_type",
                            "%s is only an array element type" % n.val,
                            "use i64 for a scalar, or [u8] for a byte array")
        if n.val == "i64": ty = I64
        elif n.val == "bool": ty = BOOL
        elif n.val == "str": ty = STR   # G2 B0
        else:
            # Option/Result, a type parameter or a user type (G3: with optional type arguments); the checker
            # resolves the names. Lower-case spellings of the built-in Type names must not alias them.
            if n.val in ("unit", "array", "option", "result", "array_u8", "array_bool", "array_i32"):
                s.err("unknown type %r" % n.val, "use i64, bool, (), [i64], Option<i64>, Result<i64> or a declared struct/enum", n)
            ty = s.named_type(n)
        if s.at("|"):
            if not allow:
                s.ref_position(s.peek())
            s.next()
            lo, hi = s.ref_range()
            # a non-i64 base is reported by refine.py as type/refinement_base
            return ty, Refinement(t.line, t.col, "scalar", n.val, lo, hi, None)
        return ty, None

    def function(s, foreign=None):
        """foreign: the `trusted` token of a `trusted rust fn` declaration (its `rust` was consumed), else None"""
        kw = s.expect("fn")
        if foreign is not None:
            kw = foreign
        name = s.ident().val
        tparams = s.type_params(fn_owner(name)) if s.at("<") else ()
        s.expect("(")
        params = []
        while not s.at(")"):
            take = False
            mode_tok = None
            t0 = s.peek()
            if t0.kind == "id" and t0.val == "take" and s.peek(1).kind == "id":
                if s.peek(2).kind == "op" and s.peek(2).val == ":":
                    s.next()
                    take = True
                elif s.peek(1).val == "inout" and s.peek(2).kind == "id":   # G5: `take inout name`
                    s.inout_syntax(t0, "a parameter cannot be both take and inout",
                                   "keep one mode: `take name: Type` or `inout name: [i64]`")
                else:
                    s.foreign_syntax(t0, "malformed take parameter", "write `take name: Type`")
            elif t0.kind == "id" and t0.val == "inout" and not (s.peek(1).kind == "op" and s.peek(1).val == ":"):
                # G5: contextual `inout` before a parameter name (`inout: T` is an ordinary parameter named inout)
                mode_tok = s.next()
                n1 = s.peek()
                if n1.kind != "id":
                    s.inout_syntax(mode_tok, "inout needs a parameter name", "write `inout name: [i64]`")
                if n1.val in ("take", "inout") and s.peek(1).kind == "id":
                    s.inout_syntax(n1, "a parameter has at most one mode",
                                   "keep one mode: `take name: Type` or `inout name: [i64]`")
            pn = s.ident().val
            s.expect(":")
            pt, pr = s.type_r(True)
            param = Param(pn, pt, pr)
            if take:
                param.take = True
            if mode_tok is not None:
                param.mode = "inout"
                param.mode_pos = (mode_tok.line, mode_tok.col)
            params.append(param)
            if not s.at(")"):
                s.expect(",")
        s.expect(")")
        if s.at("cost"):
            s.cost_syntax(s.peek())
        s.expect("->")
        ret, ret_refine = s.type_r(True)
        effects = []
        if s.at("!"):
            s.next()
            while True:
                e = s.ident()
                if e.val not in ("io", "alloc", "fs"):
                    s.err("unknown effect %r" % e.val, "effects are io, alloc, fs", e)
                effects.append(e.val)
                if not s.at(","):
                    break
                s.next()
        req, ens = [], []
        late_req = None   # Stage 5: first requires after an ensures (rejected only in cost headers)
        while s.at("requires") or s.at("ensures"):
            kt = s.next()
            k = kt.val
            if k == "requires" and ens and late_req is None:
                late_req = kt
            (req if k == "requires" else ens).append(s.expr())
        decreases = s.decreases_clause()   # G9 A0: at most one measure, after all requires/ensures
        cost = s.cost_clause()
        if cost is not None and late_req is not None:
            s.cost_syntax(late_req)
        info = None
        if foreign is not None:
            if s.at("{"):
                s.foreign_syntax(s.peek(), "a trusted rust fn has no body", 'end it with `= "::path";`')
            if not s.at("="):
                s.foreign_syntax(s.peek(), "missing Rust path", 'write `= "::std::cmp::min";` after the contracts')
            s.next()
            pt = s.peek()
            if pt.kind != "str":
                s.foreign_syntax(pt, "missing Rust path", 'write the path as a string, e.g. "::std::cmp::min"')
            s.next()
            s.expect(";")
            info = {"path": _decode_string(pt.val).decode("utf-8"), "line": pt.line, "col": pt.col}
            body = []
        else:
            body = s.block()
        s.scope = {}
        f = Function(kw.line, kw.col, name, params, ret, effects, req, ens, body, ret_refine)
        f.tparams = tparams
        if info is not None:
            f.foreign = info
        if cost is not None:
            f.cost = cost
        if decreases is not None:
            f.decreases = decreases
        return f

    def cost_clause(s):
        if not s.at("cost"):
            return None
        t = s.next()
        bad = s.cost_syntax
        if s.peek().val in ("{", "=", ";", "cost", "requires", "ensures", "decreases") or s.peek().kind == "eof":
            bad(t)
        try:
            e = s.expr()
        except PruvError:
            bad(s.peek())
        if s.peek().val in ("cost", "requires", "ensures", "decreases", ",", "!", "->"):
            bad(s.peek())
        return e

    def cost_syntax(s, tok):
        raise PruvError("parse", tok.line, tok.col, "cost_syntax",
                        "cost needs one expression and must be the last header clause",
                        "write requires* ensures* decreases? cost <i64 expression>")

    def decreases_syntax(s, tok, msg, fix):
        raise PruvError("parse", tok.line, tok.col, "decreases_syntax", msg, fix)

    def decreases_clause(s):
        """G9 A0: optional `decreases Expr` of a function header (after requires/ensures, before `{` or `=`).
        -> the expression or None. Duplicate, empty, tuple and misplaced clauses are parse/decreases_syntax."""
        expr = None
        if s.at("decreases"):
            s.next()
            t = s.peek()
            if (t.kind == "op" and t.val in ("{", "=", ";")) or t.kind == "eof":
                s.decreases_syntax(t, "empty decreases clause", "write one scalar measure, e.g. `decreases n`")
            if s.at("("):
                # a parenthesized group with a top-level comma is a tuple measure
                depth = 0
                k = 0
                while True:
                    tk = s.peek(k)
                    if tk.kind == "eof":
                        break
                    if tk.kind == "op" and tk.val in ("(", "["):
                        depth += 1
                    elif tk.kind == "op" and tk.val in (")", "]"):
                        depth -= 1
                        if depth <= 0:
                            break
                    elif tk.kind == "op" and tk.val == "," and depth == 1:
                        s.decreases_syntax(tk, "a decreases clause takes one scalar measure, not a tuple",
                                           "combine the measures into one i64 expression, e.g. `decreases 2 * n + 1`")
                    elif tk.kind == "op" and tk.val in ("{", "}", ";"):
                        break
                    k += 1
            expr = s.expr()
            if s.at(","):
                s.decreases_syntax(s.peek(), "a decreases clause takes one scalar measure, not a list",
                                   "combine the measures into one i64 expression, e.g. `decreases 2 * n + 1`")
        if s.at("decreases"):
            s.decreases_syntax(s.peek(), "a function has at most one decreases clause",
                               "keep a single `decreases <expr>` after requires/ensures")
        if s.at("requires") or s.at("ensures"):
            s.decreases_syntax(s.peek(), "%s must come before decreases" % s.peek().val,
                               "move `decreases` after all requires/ensures clauses")
        return expr

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
        if t.kind == "id" and t.val == "par" and s.at("{", 1):
            return s.par_stmt()
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
                if s.at("crate"):
                    # G4: `crate::m::Enum::Variant(x) =>`; the last segment is the variant
                    ct, segs = s.crate_path(False)
                    if len(segs) < 2:
                        s.path_syntax(ct, "a variant pattern is written crate::module::Enum::Variant")
                    binders = []
                    if s.at("("):
                        lp = s.next()
                        if s.at(")"):
                            s.err("a pattern lists one name per field; a variant without fields has no parentheses",
                                  "write `%s::%s =>`" % ("::".join(["crate"] + segs[:-1]), segs[-1]), lp)
                        while True:
                            binders.append(s.ident().val)
                            if not s.at(","):
                                break
                            s.next()
                        s.expect(")")
                    s.expect("=>")
                    arms.append(MatchArm(ct.line, ct.col, "::".join(["crate"] + segs[:-1]), segs[-1], binders,
                                         s.block()))
                    if s.at(","):
                        s.next()
                    continue
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
        """`Enum::Variant` -> (enum token, variant token); G4: also `crate::m::Enum::Variant` (enum token value =
        the enum's path)"""
        if s.at("crate"):
            ct, segs = s.crate_path(False)
            if len(segs) < 2:
                s.path_syntax(ct, "a variant is written crate::module::Enum::Variant")
            vt = Tok("id", segs[-1], ct.line, ct.col, None)
            return Tok("id", "::".join(["crate"] + segs[:-1]), ct.line, ct.col, None), vt
        en = s.ident()
        s.expect("::")
        return en, s.ident()

    def is_inout_marker(s):
        """G5: at an `inout` that marks a call argument: the token after it starts an operand (a name, number, string,
        or a keyword/path that can start an expression). `inout` followed by an operator, `(`, `[`, `.`, `,` or `)` stays
        an ordinary identifier."""
        t = s.peek()
        if not (t.kind == "id" and t.val == "inout"):
            return False
        n = s.peek(1)
        if n.kind in ("id", "int", "str"):
            return True
        return n.kind == "kw" and n.val in ("true", "false", "None", "Some", "Ok", "Err", "crate")

    def arg_expr(s):
        """one call argument: an expression, or the G5 marker `inout <operand>` (one postfix expression, kept as
        written so the checker can reject fields, elements and calls as places)"""
        if s.is_inout_marker():
            t = s.next()
            e = s.postfix()
            if not (s.at(",") or s.at(")")):
                s.inout_syntax(t, "malformed inout argument: the marker takes a single operand",
                               "write `inout name`; compute other values into a local first")
            return InoutArg(t.line, t.col, e)
        return s.expr()

    def call_args(s):
        """at `(`: the argument list of a call or constructor"""
        s.next()
        args = []
        while not s.at(")"):
            args.append(s.arg_expr())
            if not s.at(")"):
                s.expect(",")
        s.expect(")")
        return args

    def crate_expr(s):
        """G4: an absolute path in an expression.
          crate::m::f(args) / crate::m::Enum::Variant(args)  -> Call(name = the whole path) (the resolver tells a
                                                                function from a variant constructor)
          crate::m::Enum::Variant                            -> EnumCtor without arguments
          crate::m::S { .. }                                  -> StructLit
          crate::m::f::<T>(args), crate::m::S::<A> { .. }, crate::m::E::<A>::V(args): type arguments attach to the item"""
        t, segs = s.crate_path(True)
        path = "::".join(["crate"] + segs)
        if s.at("::") and s.at("<", 1):
            targs = s.expr_targs()
            if not (s.at("::") or s.at("(") or (s.at("{") and segs[-1][0].isupper())):
                s.generic_syntax(s.peek(), "a type application must be followed by `(`, `{` or `::Variant`",
                                 "write crate::m::f::<T>(x), crate::m::Pair::<A, B> { .. } or crate::m::Choice::<A, B>::Left(x)")
            if s.at("::"):
                s.next()
                vt = s.ident()
                args = []
                if s.at("("):
                    lp = s.peek()
                    args = s.call_args()
                    if not args:
                        s.err("empty parentheses after a variant",
                              "write `%s::%s` for a variant without fields, or pass its fields as arguments"
                              % (path, vt.val), lp)
                ec = EnumCtor(t.line, t.col, path, vt.val, args)
                ec.targs = targs
                return ec
            if s.at("{"):
                sl = StructLit(t.line, t.col, path, s.struct_inits())
                sl.targs = targs
                return sl
            call = Call(t.line, t.col, path, s.call_args())
            call.targs = targs
            return call
        if s.at("("):
            return Call(t.line, t.col, path, s.call_args())
        if s.at("{") and segs[-1][0].isupper():
            return StructLit(t.line, t.col, path, s.struct_inits())
        if len(segs) < 2:
            s.path_syntax(t, "a path expression must be a call, a struct literal or an enum variant",
                          "write crate::module::f(x), crate::module::S { .. } or crate::module::Enum::Variant")
        return EnumCtor(t.line, t.col, "::".join(["crate"] + segs[:-1]), segs[-1], [])

    def struct_inits(s):
        """at `{`: `name: expr, ...` up to and including `}` -> [FieldInit]"""
        s.next()
        inits = []
        while not s.at("}"):
            fn = s.ident()
            s.expect(":")
            inits.append(FieldInit(fn.line, fn.col, fn.val, s.expr()))
            if not s.at("}"):
                s.expect(",")
        s.expect("}")
        return inits

    def primary(s):
        t = s.peek()
        if t.kind == "int":
            s.next(); return IntLit(t.line, t.col, t.val)
        if t.kind == "str":   # G2 B0
            s.next(); return StrLit(t.line, t.col, _decode_string(t.val))
        if t.kind == "move":   # G6: `move name`
            s.next()
            n = s.peek()
            if n.kind != "id":
                s.foreign_syntax(t, "move takes a binding name", "write `move name`")
            s.next()
            return Move(t.line, t.col, n.val)
        if s.at("true") or s.at("false"):
            s.next(); return BoolLit(t.line, t.col, t.val == "true")
        if s.at("("):
            s.next(); e = s.expr(); s.expect(")"); return e
        if s.at("None"):
            s.next()
            c = Ctor(t.line, t.col, "None", None)
            if s.at("::") and s.at("<", 1):
                c.targs = s.expr_targs()      # G3: None::<T>
            return c
        if s.at("Some") or s.at("Ok") or s.at("Err"):
            s.next()
            targs = s.expr_targs() if (s.at("::") and s.at("<", 1)) else None   # G3: Some::<T>(x)
            s.expect("("); a = s.expr(); s.expect(")")
            c = Ctor(t.line, t.col, t.val, a)
            c.targs = targs
            return c
        if s.at("spent"):
            s.next(); return Spent(t.line, t.col)
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
        if s.at("crate"):
            return s.crate_expr()
        if t.kind == "id":
            s.next()
            targs = None
            if s.at("::") and s.at("<", 1):
                # G3: f::<T>(x), S::<A, B> { .. }, E::<A, B>::V(x)
                targs = s.expr_targs()
                if not (s.at("::") or s.at("(") or (s.at("{") and t.val[0].isupper())):
                    s.generic_syntax(s.peek(), "a type application must be followed by `(`, `{` or `::Variant`",
                                     "write f::<T>(x), Pair::<A, B> { .. } or Choice::<A, B>::Left(x)")
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
                ec = EnumCtor(t.line, t.col, t.val, vt.val, args)
                ec.targs = targs
                return ec
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
                sl = StructLit(t.line, t.col, t.val, inits)
                sl.targs = targs
                return sl
            if s.at("("):
                s.next()
                args = []
                while not s.at(")"):
                    args.append(s.arg_expr())
                    if not s.at(")"):
                        s.expect(",")
                s.expect(")")
                call = Call(t.line, t.col, t.val, args)
                call.targs = targs
                return call
            return Var(t.line, t.col, t.val)
        s.err("expected an expression, found %r" % (t.val,))


def parse(src):
    return Parser(src).program()
