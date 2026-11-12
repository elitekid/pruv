"""Independent reference interpreter for a subset of Pruv (written from SPEC.md only).

Does NOT import anything from pruvc/.  Python 3.9, stdlib only, unbounded ints.

Supported subset (anything else -> OracleUnsupported):
  * top level: `fn`, `struct Name { f: T, ... }`, `enum Name { V, W(a: T, b: T), ... }` declarations
    (any order, forward references ok).
  * types: i64, bool, [i64], (), Option<i64>, Result<i64>, user struct/enum names.
    Statements: let / let mut / x = e / a[i] = e / v.f.g = e / if-else if-else / while (invariant*, decreases) /
    return / assert / print / call statement / match (Option, Result, user enum; arms in any order).
  * expressions: unary - !, * / %, + -, non-associative comparisons, &&, ||, ==> (right assoc),
    literals, vars, `result`, calls, len/alloc/copy, a[i], v.f, `S { f: e }`, `E::V` / `E::V(e, ..)`,
    Some/None/Ok/Err; contract-only forall/exists/sum/count/max/min, is_some/some_val/is_ok/ok_val/err_val,
    is_variant/variant_field, == != on Option/Result/struct/enum.
    A quantifier/aggregate body extends as far right as possible (full `==>` level expression).

G2 (docs/G2_Q1_IMPL.md 5.1): types [u8] ("array_u8"), [bool] ("array_bool"), str ("str"; value = immutable
  `bytes`, run()/check_requires() also take a Python str / UTF-8 bytes for str parameters); string literals
  (escapes \\" \\\\ \\n \\r \\t \\0); is_char_boundary / substr; alloc narrow type only right of a typed `let`, right of
  a reassignment of that variable, right after `return`; faults elem_range / slice_range / slice_cut.
  `[u8 | ..]` refinements and `==`/`!=` on str -> OracleUnsupported.

G3 (docs/G3_SPEC.md, SPEC.md 6c; switched on only when the source has generic syntax): `fn f<T, U: Element>`, `struct S<A, B>`,
  `enum E<A, B>`, type applications (`Pair<i64, bool>`, `Option<Option<T>>`, `Option<Pair<..>>`, `[T]`) and explicit instantiations
  `f::<..>(..)`, `Some::<T>(x)`, `None::<T>`, `Ok::<T>(x)`, `Err::<T>(c)`, `S::<A, B> { .. }`, `E::<A, B>::V(..)`. Values are untyped at run
  time, so type arguments are parsed and dropped; abstract equality in contracts is structural equality of the values.

G6 (docs/G6_SPEC.md 10-13, SPEC.md 6d; switched on like G3 by catalog names, `trusted` or the type names Vec/HashMap/String):
  types Vec<T> (Python list), HashMap<K, V> (`_GMap`, a wrapper around a dict so it is not mistaken for an Option dict), String
  (bytes); `take` parameters (parsed, no run-time meaning: values are never aliased because every catalog operation builds a new
  object); `move x` (evaluates to the variable's value; liveness is the compiler's business, the generator only produces
  programs that pass the ownership rules); the catalog vec_new/vec_push/vec_get, map_new/map_get/map_insert,
  string_new/string_push_str/string_byte/string_to_str, `len` on collections; contract-only v[i], s[i], map_lookup, map_updated;
  `trusted rust fn NAME(..) -> T ensures .. = "::std::cmp::min" | "::std::cmp::max";` (ensures are trusted, never evaluated).
  vec_get / string_byte with an index outside 0..len fault with kind "foreign_requires" (stderr prefix
  `pruv: foreign requires violated:`) in BOTH modes: foreign requires are checked at run time in verified builds too
  (G6_SPEC 5.1, 12.2).  The requires of a trusted fn are checked the same way.

G5 (docs/G5_SPEC.md 2-5, section 14; switched on by the contextual `inout` parameter marker, no flag): `fn f(inout a: [T], ..)`, call
  arguments `f(inout x, ..)` (the marker must sit exactly on the inout parameters, else OracleUnsupported), `old(a)` in
  ensures / invariants / asserts. An inout argument is the caller's own list (no copy): the callee's element stores mutate the
  caller's owner in place, forwarded `inout a` reaches the same list again, and `old(a)` is a copy frozen at function entry
  (taken after the requires check). `ensures` see the FINAL contents of inout parameters (other parameters keep their entry
  values). run() reports `inout_final` (final arrays of the top-level function's own inout parameters) and `inout_calls` (number
  of calls of inout functions) only for programs that use inout; the expected values come from this interpreter alone.

VALUES: i64 int, bool bool, array list, unit None.  Option/Result are JSON-friendly dicts
  {"tag": "Some", "v": 3} / {"tag": "None"} / {"tag": "Ok", "v": 3} / {"tag": "Err", "v": -2}; this is also the
  format run()/check_requires() take for arguments and run() gives back for the return value.
  Struct {"struct": N, "fields": {f: v}}, enum {"enum": N, "variant": V, "fields": {f: v}} (internal).
  Values have copy semantics: let / assignment / argument passing / return / constructor operands deep-copy.

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
    evaluates the value first; see tests/runtime/fz01_index_assign_order.pruv); oob is checked after both.
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
  | (?P<str>"(?:[^"\\\n]|\\[^\n])*")
  | (?P<id>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<op>==>|==|=>|!=|<=|>=|&&|\|\||->|\.\.|::|[-+*/%<>=!(){}\[\],:;.|])
""", re.X)
_CONTRACT_FNS = ("is_some", "some_val", "is_ok", "ok_val", "err_val")
# G6: executable catalog (name -> arity); contract-only map_lookup/map_updated are handled in cev
_CATALOG = {"vec_new": 0, "vec_push": 2, "vec_get": 2, "map_new": 0, "map_get": 2, "map_insert": 3,
            "string_new": 0, "string_push_str": 2, "string_byte": 2, "string_to_str": 1}
_FRESH_CATALOG = frozenset(["vec_new", "vec_push", "map_new", "map_insert", "string_new", "string_push_str"])
_G6_NAMES = frozenset(list(_CATALOG) + ["map_lookup", "map_updated", "trusted", "Vec", "HashMap", "String"])
_FOREIGN_NATIVE = {"::std::cmp::min": lambda a, b: min(a, b), "::std::cmp::max": lambda a, b: max(a, b)}


class _GMap(object):
    """G6 HashMap value: a wrapper around a dict (keys i64 or bool, one kind per map). It is a separate class so that
    isinstance(v, dict) (Option/Result/struct/enum values) stays false for it."""

    def __init__(self, d=None):
        self.d = dict(d) if d else {}

    def __len__(self):
        return len(self.d)
_ESCAPES = {'"': '"', "\\": "\\", "n": "\n", "r": "\r", "t": "\t", "0": "\0"}


def _decode_str(text, line):
    """Source characters inside the quotes -> UTF-8 bytes. Only the escapes \\\" \\\\ \\n \\r \\t \\0 are allowed."""
    body, out, i = text[1:-1], [], 0
    while i < len(body):
        c = body[i]
        if c == "\\":
            if i + 1 >= len(body) or body[i + 1] not in _ESCAPES:
                raise OracleParseError("line %d: bad string escape" % line)
            out.append(_ESCAPES[body[i + 1]])
            i += 2
            continue
        if ord(c) < 0x20:
            raise OracleParseError("line %d: control character in string literal" % line)
        out.append(c)
        i += 1
    try:
        return "".join(out).encode("utf-8")
    except UnicodeEncodeError:
        raise OracleParseError("line %d: string literal is not UTF-8" % line)


def _lex(src):
    toks, pos, line = [], 0, 1
    while pos < len(src):
        m = _TOK.match(src, pos)
        if not m:
            raise OracleParseError("line %d: bad character %r" % (line, src[pos]))
        k, text = m.lastgroup, m.group()
        if k == "int":
            toks.append(("int", int(text.replace("_", "")), line))
        elif k == "str":
            toks.append(("str", _decode_str(text, line), line))
        elif k != "ws":
            toks.append((k, text, line))
        line += text.count("\n")
        pos = m.end()
    toks.append(("eof", "", line))
    return toks


# ---------------------------------------------------------------- parser
class _Fn(object):
    cost = None
    foreign = None      # G6: the Rust path string of a `trusted rust fn` (body is empty), else None
    decreases = None    # G9: function-level `decreases e`; evaluated only with run(..., fn_decreases=True)
    inout = frozenset()  # G5: names of the `inout` (mutable array borrow) parameters

    def __init__(self, name, params, ret, requires, ensures, body, line):
        self.name, self.params, self.ret = name, params, ret
        self.requires, self.ensures, self.body, self.line = requires, ensures, body, line


class Program(object):
    def __init__(self, fns, structs=None, enums=None):
        self.fns = fns
        self.structs = structs or {}   # name -> [(field, type)]
        self.enums = enums or {}       # name -> {variant: [(field, type)]}


class _Parser(object):
    def __init__(self, src):
        self.t = _lex(src)
        self.p = 0
        # pre-scan so type names are known regardless of declaration order
        self.struct_names, self.enum_names = set(), set()
        # G3: generic syntax (`fn f<T>`, `struct S<A>`, `enum E<A>`, or an explicit `::<..>`) switches generic parsing on.
        # Without it the parser behaves exactly as before (e.g. Option<Option<i64>> stays unsupported).
        self.g3 = False
        self.tparams = set()    # type parameter names of the declaration being parsed
        for i in range(len(self.t) - 1):
            a, b = self.t[i], self.t[i + 1]
            if a[0] == "id" and a[1] in _G6_NAMES:
                self.g3 = True      # G6 sources use explicit type arguments and Option<bool>: same parsing as G3
            if a[0] == "id" and b[0] == "id":
                if a[1] == "struct":
                    self.struct_names.add(b[1])
                elif a[1] == "enum":
                    self.enum_names.add(b[1])
                if a[1] in ("fn", "struct", "enum") and i + 2 < len(self.t) and self.t[i + 2][1] == "<" \
                        and self.t[i + 2][0] == "op":
                    self.g3 = True
            if a[0] == "op" and a[1] == "::" and b[0] == "op" and b[1] == "<":
                self.g3 = True

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
        return self.next()[1]

    # types
    def type_(self):
        if self.is_("("):
            self.next()
            self.eat(")")
            return "unit"
        if self.is_("["):
            self.next()
            el = self.peek()
            if el[0] == "id" and el[1] in ("u8", "bool"):
                self.next()
                if self.is_("|"):
                    raise OracleUnsupported("refined array type")
                self.eat("]")
                return "array_u8" if el[1] == "u8" else "array_bool"
            if self.g3 and el[0] == "id" and el[1] in self.tparams:     # G3: [T] with T: Element
                self.next()
                self.eat("]")
                return "arr"
            self.eat("i64")
            if self.is_("|"):
                raise OracleUnsupported("refined array type")
            self.eat("]")
            return "arr"
        t = self.peek()
        if t[0] == "id" and t[1] == "str":
            self.next()
            return "str"
        if t[0] == "id" and t[1] in ("i64", "bool"):
            self.next()
            return t[1]
        if t[0] == "id" and t[1] in ("Option", "Result"):
            self.next()
            self.eat("<")
            if self.g3:
                self.type_()    # G3: i64, bool, T, Pair<..>, Option<..>, ... (values are untyped at run time)
            else:
                if not self.is_("i64"):
                    raise OracleUnsupported("unsupported type argument of %s" % t[1])
                self.next()
            self.eat(">")
            return t[1]
        if t[0] == "id" and t[1] in ("Vec", "HashMap", "String") \
                and t[1] not in self.struct_names and t[1] not in self.enum_names:
            # G6 catalog collections (a user type of the same name keeps its own meaning)
            self.next()
            if t[1] == "String":
                return "string"
            targs = self.type_args()
            if len(targs) != (1 if t[1] == "Vec" else 2):
                self.err("wrong number of type arguments for %s" % t[1])
            return "vec" if t[1] == "Vec" else "hashmap"
        if t[0] == "id" and (t[1] in self.struct_names or t[1] in self.enum_names):
            self.next()
            if self.g3 and self.is_("<"):
                self.type_args()
            return t[1]
        if self.g3 and t[0] == "id" and t[1] in self.tparams:
            self.next()
            return "T"
        if t[0] == "id":
            raise OracleUnsupported("unsupported type %s" % t[1])
        self.err("expected type")

    def type_args(self):
        """G3: `<T1, T2, ..>` of a type application or an explicit call/constructor instantiation."""
        self.eat("<")
        out = [self.type_()]
        while self.is_(","):
            self.next()
            out.append(self.type_())
        self.eat(">")
        return out

    def tparam_list(self):
        """G3: optional `<T, U: Element>` after the name of a fn/struct/enum -> set of type parameter names."""
        names = set()
        if self.g3 and self.is_("<"):
            self.next()
            while True:
                names.add(self.ident())
                if self.is_(":"):
                    self.next()
                    self.ident()
                if not self.is_(","):
                    break
                self.next()
            self.eat(">")
        return names

    # program
    def program(self):
        fns, structs, enums = {}, {}, {}
        while self.peek()[0] != "eof":
            if self.is_("fn"):
                f = self.fn()
                if f.name in fns:
                    self.err("duplicate fn %s" % f.name)
                fns[f.name] = f
            elif self.is_("struct"):
                self.next()
                name = self.ident()
                if name in structs or name in enums:
                    self.err("duplicate type %s" % name)
                self.tparams = self.tparam_list()
                structs[name] = self.fields_("{", "}")
            elif self.is_("enum"):
                self.next()
                name = self.ident()
                if name in structs or name in enums:
                    self.err("duplicate type %s" % name)
                self.tparams = self.tparam_list()
                self.eat("{")
                variants = {}
                while not self.is_("}"):
                    vn = self.ident()
                    if vn in variants:
                        self.err("duplicate variant %s" % vn)
                    variants[vn] = self.fields_("(", ")") if self.is_("(") else []
                    if not self.is_("}"):
                        self.eat(",")
                self.eat("}")
                if not variants:
                    self.err("enum needs a variant")
                enums[name] = variants
            elif self.is_("trusted") and self.is_("rust", 1):
                f = self.foreign_fn()
                if f.name in fns:
                    self.err("duplicate fn %s" % f.name)
                fns[f.name] = f
            elif self.peek()[0] == "id":
                raise OracleUnsupported("unsupported top-level item %s" % self.peek()[1])
            else:
                self.err("expected fn")
        if not fns:
            self.err("no functions")
        return Program(fns, structs, enums)

    def fields_(self, open_, close):
        """`{ f: T, ... }` or `(f: T, ...)` -> [(field, type)] (trailing comma allowed)"""
        self.eat(open_)
        out = []
        while not self.is_(close):
            fname = self.ident()
            if any(fname == x for x, _t in out):
                self.err("duplicate field %s" % fname)
            self.eat(":")
            out.append((fname, self.type_()))
            if not self.is_(close):
                self.eat(",")
        self.eat(close)
        return out

    def fn(self):
        line = self.eat("fn")[2]
        name = self.ident()
        self.tparams = self.tparam_list()
        self.eat("(")
        params = []
        inout = set()
        while not self.is_(")"):
            pn = self.ident()
            if pn == "take" and self.peek()[0] == "id" and self.is_(":", 1):
                pn = self.ident()       # G6: `take v: Vec<T>` (consuming parameter; no run-time meaning here)
            elif pn == "inout" and self.peek()[0] == "id" and self.is_(":", 1):
                pn = self.ident()       # G5: `inout a: [i64]` (the caller's array is mutated in place)
                inout.add(pn)
            self.eat(":")
            params.append((pn, self.type_()))
            if pn in inout and params[-1][1] not in ("arr", "array_u8", "array_bool"):
                raise OracleUnsupported("inout parameter %s is not an array" % pn)
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
        req, ens, dec, cost = [], [], None, None
        while self.is_("requires") or self.is_("ensures") or self.is_("decreases") or self.is_("cost"):
            kw = self.next()
            if kw[1] == "cost":
                cost = self.imp()
                continue
            if kw[1] == "decreases":
                # G9: exactly one function-level measure; the oracle is a value interpreter and does not check it
                if dec is not None:
                    self.err("duplicate decreases")
                dec = (self.imp(), kw[2])
                continue
            (req if kw[1] == "requires" else ens).append((self.imp(), kw[2]))
        self.scopes = [dict(params)]
        self.cur_ret = ret
        fn_ = _Fn(name, params, ret, req, ens, self.block(), line)
        fn_.cost = cost
        fn_.decreases = dec
        if inout:
            fn_.inout = frozenset(inout)
        return fn_

    def foreign_fn(self):
        """G6: `trusted rust fn NAME(params) -> T [! effects] (requires|ensures)* = "::path";` -> _Fn with .foreign = path."""
        line = self.eat("trusted")[2]
        self.eat("rust")
        self.eat("fn")
        name = self.ident()
        self.tparams = self.tparam_list()
        self.eat("(")
        params = []
        while not self.is_(")"):
            pn = self.ident()
            self.eat(":")
            params.append((pn, self.type_()))
            if not self.is_(")"):
                self.eat(",")
        self.eat(")")
        self.eat("->")
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
        self.eat("=")
        t = self.peek()
        if t[0] != "str":
            self.err("missing Rust path")
        self.next()
        self.eat(";")
        f = _Fn(name, params, ret, req, ens, [], line)
        f.foreign = t[1].decode("utf-8")
        return f

    def lookup_ty(self, name):
        for sc in reversed(self.scopes):
            if name in sc:
                return sc[name]
        return None

    @staticmethod
    def narrow(e, ty, first):
        """If `alloc(n, v)` appears whole directly at a typed position (right of let, right of a reassignment, after return),
        attach that array type (5th slot). Otherwise it is [i64]."""
        # the parser leaves no node for parentheses, so `(alloc(..))` is narrowed too (same as the compiler's check.py alloc_hint_for)
        if ty in ("array_u8", "array_bool") and e[0] == "call" and e[1] == "alloc" and len(e[2]) == 2:
            return e + (ty,)
        return e

    def block(self):
        self.eat("{")
        out = []
        self.scopes.append({})
        while not self.is_("}"):
            out.append(self.stmt())
        self.scopes.pop()
        self.eat("}")
        return out

    def stmt(self):
        t = self.peek()
        line = t[2]
        if self.is_("par") and self.is_("{", 1):
            self.next()
            self.eat("{")
            calls = []
            while not self.is_("}"):
                e = self.imp()
                if e[0] != "call":
                    raise OracleUnsupported("par branch must be a call")
                calls.append(e)
                self.eat(";")
            self.eat("}")
            if len(calls) < 2:
                raise OracleUnsupported("par needs two branches")
            return ("par", line, calls)
        if self.is_("match"):
            return self.match_stmt()
        if self.is_("let"):
            self.next()
            if self.is_("mut"):
                self.next()
            name = self.ident()
            self.eat(":")
            ty = self.type_()
            self.eat("=")
            first = self.peek()
            e = self.narrow(self.imp(), ty, first)
            self.eat(";")
            self.scopes[-1][name] = ty
            return ("let", line, name, e, ty)
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
                first = self.peek()
                e = self.narrow(self.imp(), self.cur_ret, first)
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
                first = self.peek()
                e = self.narrow(self.imp(), self.lookup_ty(name), first)
                self.eat(";")
                return ("assign", line, name, e)
            if self.is_(".", 1):
                name = self.ident()
                path = []
                while self.is_("."):
                    self.next()
                    path.append(self.ident())
                self.eat("=")
                e = self.imp()
                self.eat(";")
                return ("fassign", line, name, path, e)
            if self.is_("[", 1):
                name = self.ident()
                self.next()
                i = self.imp()
                self.eat("]")
                self.eat("=")
                e = self.imp()
                self.eat(";")
                return ("aassign", line, name, i, e, self.lookup_ty(name))
            if self.is_("(", 1):
                e = self.imp()
                self.eat(";")
                if e[0] != "call":
                    self.err("bad expression statement")
                return ("expr", line, e)
            if self.g3 and self.is_("::", 1) and self.is_("<", 2):
                e = self.imp()          # G5: `exchange::<i64>(inout w, i, j);` (explicit instantiation as a statement)
                self.eat(";")
                if e[0] != "call":
                    self.err("bad expression statement")
                return ("expr", line, e)
        self.err("bad statement")

    def call_arg(self):
        """G5: one call argument; `inout x` marks the whole mutable-borrow place (a bare identifier follows `inout`)."""
        if self.is_("inout") and self.peek(1)[0] == "id":
            self.next()
            return ("inout", self.ident())
        return self.imp()

    def match_stmt(self):
        line = self.eat("match")[2]
        scrut = self.imp()
        self.eat("{")
        arms = []
        while not self.is_("}"):
            key, binders = self.pattern()
            self.eat("=>")
            arms.append((key, binders, self.block()))
            if self.is_(","):
                self.next()
        self.eat("}")
        return ("match", line, scrut, arms)

    def pattern(self):
        """-> (key, binding names). key: 'Some' 'None' 'Ok' 'Err' or 'Enum::Variant'"""
        t = self.peek()
        if t[0] == "id" and t[1] in ("Some", "Ok", "Err"):
            self.next()
            self.eat("(")
            b = self.ident()
            self.eat(")")
            return t[1], [b]
        if t[0] == "id" and t[1] == "None":
            self.next()
            return "None", []
        en = self.ident()
        self.eat("::")
        vn = self.ident()
        binders = []
        if self.is_("("):
            self.next()
            while not self.is_(")"):
                binders.append(self.ident())
                if not self.is_(")"):
                    self.eat(",")
            self.eat(")")
        return "%s::%s" % (en, vn), binders

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
        while True:
            if self.is_("["):
                self.next()
                i = self.imp()
                self.eat("]")
                e = ("idx", e, i)
            elif self.is_("."):
                self.next()
                e = ("field", e, self.ident())
            else:
                break
        return e

    def range_(self):
        lo = self.add()
        self.eat("..")
        return lo, self.add()

    def generic_primary(self, name, line):
        """G3: `f::<T>(..)`, `Some::<T>(x)`, `None::<T>`, `Ok::<T>(x)`, `Err::<T>(c)`, `S::<A, B> { .. }`,
        `E::<A, B>::V(..)`. The type arguments are parsed and dropped: values carry no type at run time."""
        self.next()
        self.next()
        self.type_args()
        if name == "None":
            return ("ctor", "None", None)
        if name in ("Some", "Ok", "Err"):
            self.eat("(")
            a = self.imp()
            self.eat(")")
            return ("ctor", name, a)
        if name in self.struct_names and self.is_("{"):
            self.next()
            fields = []
            while not self.is_("}"):
                fname = self.ident()
                self.eat(":")
                fields.append((fname, self.imp()))
                if not self.is_("}"):
                    self.eat(",")
            self.eat("}")
            return ("slit", name, fields)
        if name in self.enum_names and self.is_("::"):
            self.next()
            vn = self.ident()
            args = []
            if self.is_("("):
                self.next()
                while not self.is_(")"):
                    args.append(self.imp())
                    if not self.is_(")"):
                        self.eat(",")
                self.eat(")")
            return ("ector", name, vn, args)
        if self.is_("("):
            self.next()
            args = []
            while not self.is_(")"):
                args.append(self.call_arg())
                if not self.is_(")"):
                    self.eat(",")
            self.eat(")")
            return ("call", name, args, line)
        self.err("bad generic expression")

    def primary(self):
        t = self.peek()
        if t[0] == "int":
            self.next()
            return ("int", t[1])
        if t[0] == "str":
            self.next()
            return ("str", t[1])
        if self.is_("("):
            self.next()
            e = self.imp()
            self.eat(")")
            return e
        if t[0] != "id":
            self.err("expected expression")
        name = t[1]
        if name == "move" and self.peek(1)[0] == "id":
            self.next()                     # G6: `move x`
            return ("move", self.next()[1])
        if self.g3 and self.is_("::", 1) and self.is_("<", 2):
            return self.generic_primary(name, t[2])
        if name == "None":
            self.next()
            return ("ctor", "None", None)
        if name in ("Some", "Ok", "Err") and self.is_("(", 1):
            self.next()
            self.next()
            a = self.imp()
            self.eat(")")
            return ("ctor", name, a)
        if name in _CONTRACT_FNS and self.is_("(", 1):
            self.next()
            self.next()
            a = self.imp()
            self.eat(")")
            return ("cfn", name, a)
        if name in ("is_variant", "variant_field") and self.is_("(", 1):
            self.next()
            self.next()
            a = self.imp()
            self.eat(",")
            en = self.ident()
            self.eat("::")
            vn = self.ident()
            if name == "is_variant":
                self.eat(")")
                return ("is_variant", a, en, vn)
            self.eat(",")
            fld = self.ident()
            self.eat(")")
            return ("variant_field", a, en, vn, fld)
        if self.is_("::", 1):
            # enum construction: Enum::V or Enum::V(e1, e2)
            self.next()
            self.next()
            vn = self.ident()
            args = []
            if self.is_("("):
                self.next()
                while not self.is_(")"):
                    args.append(self.imp())
                    if not self.is_(")"):
                        self.eat(",")
                self.eat(")")
            return ("ector", name, vn, args)
        if name in self.struct_names and self.is_("{", 1):
            self.next()
            self.next()
            fields = []
            while not self.is_("}"):
                fname = self.ident()
                self.eat(":")
                fields.append((fname, self.imp()))
                if not self.is_("}"):
                    self.eat(",")
            self.eat("}")
            return ("slit", name, fields)
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
                args.append(self.call_arg())
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


def _boundary(s, i):
    """G2_SPEC 4.4: UTF-8 character boundary. Negative or above n is false, 0 and n are true, in between it holds when the byte is not a continuation byte (128..=191)."""
    if not isinstance(s, bytes):
        raise OracleUnsupported("is_char_boundary on a non-str")
    n = len(s)
    if i < 0 or i > n:
        return False
    if i == 0 or i == n:
        return True
    return s[i] < 128 or s[i] >= 192


def _cp(v):
    """Value copy: arrays (list) shallowly (elements are only integers), dicts (Option/Result/struct/enum) deeply."""
    if isinstance(v, list):
        return list(v)
    if isinstance(v, _GMap):
        return _GMap(v.d)
    if isinstance(v, dict):
        return dict((k, _cp(x)) for k, x in v.items())
    return v


def _g9_size(v):
    """G9 `size(x)` (SPEC 6e): the number of struct/enum constructors in the value (only the active payload of an enum is
    walked); scalars, arrays, strings, Option/Result wrappers count 0 but the payload of Some / Ok is walked (None / Err
    hold no nominal value). Written from the SPEC sentence, not from the compiler."""
    if isinstance(v, dict) and ("struct" in v or "enum" in v):
        return 1 + sum(_g9_size(x) for x in v["fields"].values())
    if isinstance(v, dict) and v.get("tag") in ("Some", "Ok"):
        return _g9_size(v.get("v"))
    return 0


class _Interp(object):
    def __init__(self, prog, max_steps, mode="safe"):
        if mode not in ("safe", "proof"):
            raise ValueError("mode must be 'safe' or 'proof'")
        self.prog, self.max_steps, self.steps, self.mode = prog, max_steps, 0, mode
        self.output, self.failures = [], []
        # Opt-in (G9 mutation grading): check function-level `decreases` at every call inside a recursive
        # SCC: callee measure defined, >= 0 and < the caller's frozen entry measure ("decreases <fn> line N").
        self.fn_decreases, self._frames, self._scc = False, [], None
        self.cost_frames, self.cost_calls = [], []
        self.inout_calls = 0    # G5: number of calls of functions with inout parameters

    def scc_of(self, name):
        if self._scc is None:
            fns = self.prog.fns
            def calls(x, out):
                if isinstance(x, (tuple, list)):
                    if len(x) >= 2 and x[0] == "call" and isinstance(x[1], str) and x[1] in fns:
                        out.add(x[1])
                    for y in x:
                        calls(y, out)
                return out
            edges = dict((n, calls(f.body, set())) for n, f in fns.items())
            def reach(a):
                seen, todo = set(), [a]
                while todo:
                    for b in edges[todo.pop()]:
                        if b not in seen:
                            seen.add(b)
                            todo.append(b)
                return seen
            r = dict((n, reach(n)) for n in fns)
            self._scc = dict((n, frozenset(m for m in fns if m in r[n] and n in r[m])) for n in fns)
        return self._scc.get(name, frozenset())

    # ---- struct / enum / Option / Result values (shared by code and contracts; operands computed via evalf)
    def build(self, e, evalf):
        k = e[0]
        if k == "ctor":
            if e[1] == "None":
                return {"tag": "None"}
            return {"tag": e[1], "v": _cp(evalf(e[2]))}
        if k == "slit":
            decl = self.prog.structs.get(e[1])
            if decl is None:
                raise OracleUnsupported("unknown struct %s" % e[1])
            if [f for f, _e in e[2]] != [f for f, _t in decl]:
                raise OracleUnsupported("struct literal %s: fields not in declaration order" % e[1])
            vals = {}
            for f, fe in e[2]:          # source order (= declaration order), left to right
                vals[f] = _cp(evalf(fe))
            return {"struct": e[1], "fields": vals}
        if k == "ector":
            decl = self.variant_decl(e[1], e[2])
            if len(decl) != len(e[3]):
                raise OracleUnsupported("variant %s::%s arity" % (e[1], e[2]))
            vals = {}
            for (f, _t), ae in zip(decl, e[3]):
                vals[f] = _cp(evalf(ae))
            return {"enum": e[1], "variant": e[2], "fields": vals}
        raise OracleUnsupported("bad value expression %r" % (k,))

    def variant_decl(self, en, vn):
        d = self.prog.enums.get(en)
        if d is None or vn not in d:
            raise OracleUnsupported("unknown variant %s::%s" % (en, vn))
        return d[vn]

    @staticmethod
    def get_field(v, f):
        if not (isinstance(v, dict) and "struct" in v and f in v["fields"]):
            raise OracleUnsupported("field access .%s on a non-struct" % f)
        return v["fields"][f]

    def charge(self, units):
        if self.cost_frames and self.cost_frames[-1]["bound"] is not None:
            frame = self.cost_frames[-1]
            frame["spent"] += units
            if self.mode == "safe" and (units < 0 or frame["spent"] >= 2 ** 128):
                raise _Fault("cost_exceeded", frame["function"])

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
        if k == "str":
            return e[1]
        if k == "var":
            if e[1] == "spent" and self.cost_frames:
                return self.cost_frames[-1]["spent"]
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
            if isinstance(x, bytes) or isinstance(y, bytes):
                raise OracleUnsupported("operator %s on str in contract" % op)
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
        if k in ("ctor", "slit", "ector"):
            return self.build(e, lambda x: self.cev(x, env, lim))
        if k == "field":
            return chk(self.get_field(self.cev(e[1], env, lim), e[2]))
        if k == "cfn":
            name = e[1]
            v = self.cev(e[2], env, lim)
            want = ("Some", "None") if name in ("is_some", "some_val") else ("Ok", "Err")
            if not (isinstance(v, dict) and v.get("tag") in want):
                raise OracleUnsupported("%s on a wrong type" % name)
            if name in ("is_some", "is_ok"):
                return v["tag"] == want[0]
            need = "Err" if name == "err_val" else want[0]
            if v["tag"] != need:
                raise _Undef(name)      # some_val(None), ok_val(Err), err_val(Ok)
            return chk(v["v"])
        if k in ("is_variant", "variant_field"):
            v = self.cev(e[1], env, lim)
            decl = self.variant_decl(e[2], e[3])
            if not (isinstance(v, dict) and v.get("enum") == e[2]):
                raise OracleUnsupported("%s on a wrong type" % k)
            if k == "is_variant":
                return v["variant"] == e[3]
            if e[4] not in [f for f, _t in decl]:
                raise OracleUnsupported("variant %s::%s has no field %s" % (e[2], e[3], e[4]))
            if v["variant"] != e[3]:
                raise _Undef("variant_field")
            return chk(v["fields"][e[4]])
        if k == "call":
            if e[1] == "len" and len(e[2]) == 1:
                return chk(len(self.cev(e[2][0], env, lim)))
            if e[1] == "is_char_boundary" and len(e[2]) == 2:
                s = self.cev(e[2][0], env, lim)
                i = self.cev(e[2][1], env, lim)
                return _boundary(s, i)
            if e[1] == "size" and len(e[2]) == 1 and "size" not in self.prog.fns:      # G9
                v = self.cev(e[2][0], env, lim)
                if not (isinstance(v, dict) and ("struct" in v or "enum" in v)):
                    raise OracleUnsupported("size() of a non-struct/enum value")
                self.steps += _g9_size(v)      # run-time requires/ensures cost one budget unit per node visited
                if self.steps > self.max_steps:
                    raise _Fault("limit", "steps")
                return chk(_g9_size(v))
            if e[1] == "map_lookup" and len(e[2]) == 2:       # G6: total, Some(value) if the key is present
                gm = self.cev(e[2][0], env, lim)
                gk = self.cev(e[2][1], env, lim)
                if not isinstance(gm, _GMap):
                    raise OracleUnsupported("map_lookup on a non-map")
                if gk in gm.d:
                    return {"tag": "Some", "v": gm.d[gk]}
                return {"tag": "None"}
            if e[1] == "map_updated" and len(e[2]) == 4:      # G6: after == before with key k set to v (domain + payload + size)
                after = self.cev(e[2][0], env, lim)
                before = self.cev(e[2][1], env, lim)
                gk = self.cev(e[2][2], env, lim)
                gv = self.cev(e[2][3], env, lim)
                if not (isinstance(after, _GMap) and isinstance(before, _GMap)):
                    raise OracleUnsupported("map_updated on a non-map")
                want = dict(before.d)
                want[gk] = gv
                return after.d == want
            if e[1] == "old" and len(e[2]) == 1 and "old" not in self.prog.fns:     # G5: entry value of an inout parameter
                a = e[2][0]
                if a[0] != "var" or ("old " + a[1]) not in env:
                    raise OracleUnsupported("old() of something other than an inout parameter")
                return env["old " + a[1]]       # the frozen entry copy (taken before the body ran)
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
        if k == "str":
            return e[1]
        if k == "var" or k == "move":
            if e[1] not in env:
                raise OracleUnsupported("unbound variable %s" % e[1])
            return env[e[1]]
        if k == "inout":
            # G5: a marked argument names the caller's own array; it is handed over as is (no copy), so the callee's
            # element stores land in the caller's owner
            if e[1] not in env or not isinstance(env[e[1]], list):
                raise OracleUnsupported("inout argument %s is not an array binding" % e[1])
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
            if isinstance(x, (dict, list, bytes)) or isinstance(y, (dict, list, bytes)):
                raise OracleUnsupported("operator %s on a non-scalar in code" % op)
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
        if k in ("ctor", "slit", "ector"):
            return self.build(e, lambda x: self.ev(x, env))
        if k == "field":
            return self.get_field(self.ev(e[1], env), e[2])
        if k == "call":
            name, args = e[1], e[2]
            if name == "len" and len(args) == 1:
                return len(self.ev(args[0], env))
            if name == "copy" and len(args) == 1:
                src = self.ev(args[0], env)
                self.charge(1 + len(src))
                return src if isinstance(src, bytes) else list(src)
            if name == "is_char_boundary" and len(args) == 2:
                s = self.ev(args[0], env)
                i = self.ev(args[1], env)
                return _boundary(s, i)
            if name == "substr" and len(args) == 3:
                s = self.ev(args[0], env)
                lo = self.ev(args[1], env)
                hi = self.ev(args[2], env)
                if not isinstance(s, bytes):
                    raise OracleUnsupported("substr on a non-str")
                detail = "%d %d %d" % (lo, hi, len(s))
                if not 0 <= lo <= hi <= len(s):
                    raise _Fault("slice_range", detail)
                if not (_boundary(s, lo) and _boundary(s, hi)):
                    raise _Fault("slice_cut", detail)
                return s[lo:hi]
            if name == "alloc" and len(args) == 2:
                n = self.ev(args[0], env)
                v = self.ev(args[1], env)
                if n < 0 or n > 2 ** 40:
                    raise _Fault("overflow", "alloc")
                if len(e) > 4 and e[4] == "array_u8" and not 0 <= v <= 255:
                    raise _Fault("elem_range", str(v))
                if n > ALLOC_SIM_MAX:
                    raise OracleUnsupported("alloc too large to simulate")
                self.charge(1 + n)
                return [v] * n
            if name in _CATALOG and name not in self.prog.fns:
                return self.catalog(name, [self.ev(a, env) for a in args])
            return self.call(name, [self.ev(a, env) for a in args], top=False,
                             marks=[a[0] == "inout" for a in args])
        raise OracleUnsupported("contract-only expression %s in code" % (k,))

    # ---- G6 catalog (arguments already evaluated, left to right). Every operation builds a NEW object, so a value that was
    # `move`d (or copied by let/argument passing) can never be observed through another name.
    def catalog(self, name, a):
        if len(a) != _CATALOG[name]:
            raise OracleUnsupported("arity of %s" % name)

        def need(x, typ, what):
            if not isinstance(x, typ):
                raise OracleUnsupported("%s: argument is not a %s" % (name, what))
            return x

        def in_range(i, n):
            if not (isinstance(i, int) and not isinstance(i, bool)):
                raise OracleUnsupported("%s: index is not an integer" % name)
            if not 0 <= i < n:
                # catalog requires `0 <= i < len` is checked at run time in every mode (G6_SPEC 5.1, 12.2)
                raise _Fault("foreign_requires", "%s index %d len %d" % (name, i, n))

        if name == "vec_new":
            return []
        if name == "vec_push":
            v = list(need(a[0], list, "Vec"))
            v.append(_cp(a[1]))
            return v
        if name == "vec_get":
            v = need(a[0], list, "Vec")
            in_range(a[1], len(v))
            return v[a[1]]
        if name == "map_new":
            return _GMap()
        if name == "map_get":
            m = need(a[0], _GMap, "HashMap")
            if a[1] in m.d:
                return {"tag": "Some", "v": m.d[a[1]]}
            return {"tag": "None"}
        if name == "map_insert":
            m = _GMap(need(a[0], _GMap, "HashMap").d)
            m.d[a[1]] = _cp(a[2])
            return m
        if name == "string_new":
            return b""
        if name == "string_push_str":
            return need(a[0], bytes, "String") + need(a[1], bytes, "str")
        if name == "string_byte":
            s = need(a[0], bytes, "String")
            in_range(a[1], len(s))
            return s[a[1]]
        if name == "string_to_str":
            return need(a[0], bytes, "String")
        raise OracleUnsupported("catalog function %s" % name)

    def foreign_call(self, fn, penv):
        """G6: a call of a `trusted rust fn`. Requires are checked at run time in every mode; ensures are trusted."""
        for idx, (ce, _ln) in enumerate(fn.requires, 1):
            st, v = self.cbool(ce, penv, True)
            if st == "undef":
                raise _Fault("foreign_undefined", "%s clause %d: %s" % (fn.name, idx, v))
            if not v:
                raise _Fault("foreign_requires", "%s clause %d" % (fn.name, idx))
        native = _FOREIGN_NATIVE.get(fn.foreign)
        if native is None:
            raise OracleUnsupported("trusted rust fn %s: no native model for %s" % (fn.name, fn.foreign))
        return native(*[penv[pn] for pn, _t in fn.params])

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

    def call(self, name, args, top=True, marks=None):
        fn = self.prog.fns.get(name)
        if fn is None:
            raise OracleUnsupported("unknown function %s" % name)
        if len(args) != len(fn.params):
            raise OracleUnsupported("arity mismatch calling %s" % name)
        if marks is not None and (fn.inout or any(marks)):
            # G5: the call must carry `inout` exactly on the inout parameters (the compiler rejects anything else)
            if any(m != (pn in fn.inout) for m, (pn, _pt) in zip(marks, fn.params)):
                raise OracleUnsupported("inout marker mismatch calling %s" % name)
        penv = {}
        for (pn, _pt), a in zip(fn.params, args):
            # Array parameters are views of the owner; only inout permits stores.
            penv[pn] = a if pn in fn.inout or isinstance(a, list) else _cp(a)
        if fn.foreign is not None:
            return self.foreign_call(fn, penv)
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
        bound = None
        if fn.cost is not None:
            try:
                bound = self.cev(fn.cost, penv, self.mode == "safe")
            except _Undef:
                raise _Fault("requires_undefined", name + " cost i128")
        if not top and self.cost_frames and self.cost_frames[-1]["bound"] is not None:
            if bound is None:
                raise OracleUnsupported("unbounded cost callee " + name)
            if self.mode == "safe" and bound < 0:
                raise _Fault("cost_exceeded", name)
            self.charge(1 + bound)
        frame = {"function": name, "bound": bound, "spent": 0}
        measure = None
        if self.fn_decreases and fn.decreases is not None:
            dexp, dln = fn.decreases
            st, m = self.cbool(dexp, penv, False)
            ok = st != "undef" and m >= 0
            if ok:
                measure = m
            caller = self._frames[-1] if self._frames else None
            if caller is not None and caller[0] in self.scc_of(name):
                if not ok or caller[1] is None or not m < caller[1]:
                    ok = False
            if not ok:
                self.fail("decreases %s line %d" % (name, dln))
        env = dict(penv)
        for pn in fn.inout:
            env["old " + pn] = list(penv[pn])       # old(a): frozen at function entry (after the requires check)
        if fn.inout:
            self.inout_calls += 1
        ret, returned = None, False
        self._frames.append((name, measure))
        self.cost_frames.append(frame)
        try:
            self.block(fn, fn.body, env)
        except _Return as r:
            ret, returned = r.v, True
        finally:
            self._frames.pop()
            self.cost_frames.pop()
            if bound is not None:
                self.cost_calls.append(dict(frame))
        if bound is not None and frame["spent"] > bound:
            if self.mode == "safe":
                raise _Fault("cost_exceeded", name)
            self.fail("cost_bound " + name)
        if fn.ret != "unit" and not returned:
            raise OracleUnsupported("function %s falls off the end" % name)
        ret = _cp(ret)
        eenv = dict(penv)       # an inout parameter denotes its FINAL contents here (same list object as in env)
        for pn in fn.inout:
            eenv["old " + pn] = env["old " + pn]
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
        if k == "par":
            # Capture once at group entry, then interpret branches in source order.
            captured = [(e[1], [self.ev(a, env) for a in e[2]],
                         [a[0] == "inout" for a in e[2]]) for e in s[2]]
            for name, values, marks in captured:
                self.call(name, values, top=False, marks=marks)
        elif k == "let" or k == "assign":
            if k == "assign" and s[2] not in env:
                raise OracleUnsupported("assignment to unbound %s" % s[2])
            e = s[3]
            v = self.ev(e, env)
            # constructor results are fresh values (they copy their inserted argument, and the catalog never
            # mutates an element in place): skip the second copy so repeated appends cost one copy each
            fresh = e[0] == "call" and e[1] in _FRESH_CATALOG and e[1] not in self.prog.fns
            env[s[2]] = v if fresh else _cp(v)
        elif k == "aassign":
            if s[2] in dict(fn.params) and s[2] not in fn.inout:
                raise OracleUnsupported("store through immutable array view")
            a = env.get(s[2])
            if not isinstance(a, list):
                raise OracleUnsupported("indexed assignment to non-array %s" % s[2])
            i = self.ev(s[3], env)
            v = self.ev(s[4], env)
            if not 0 <= i < len(a):
                raise _Fault("oob", "index")
            if s[5] == "array_u8" and not 0 <= v <= 255:
                raise _Fault("elem_range", str(v))
            a[i] = v
        elif k == "fassign":
            # q.a.b = e: only the value is computed (no other operands to evaluate); the local struct is modified in place
            v = _cp(self.ev(s[4], env))
            obj, path = env.get(s[2]), s[3]
            for f in path[:-1]:
                obj = self.get_field(obj, f)
            self.get_field(obj, path[-1])      # check that the field exists
            obj["fields"][path[-1]] = v
        elif k == "match":
            v = self.ev(s[2], env)
            if isinstance(v, dict) and "tag" in v:
                key, vals = v["tag"], ([v["v"]] if "v" in v else [])
            elif isinstance(v, dict) and "enum" in v:
                key, vals = "%s::%s" % (v["enum"], v["variant"]), list(v["fields"].values())
            else:
                raise OracleUnsupported("match on a non-Option/Result/enum value")
            arm = None
            for akey, binders, blk in s[3]:
                if akey == key:
                    arm = (binders, blk)
                    break
            if arm is None:
                raise OracleUnsupported("match has no arm for %s" % key)
            binders, blk = arm
            if len(binders) != len(vals):
                raise OracleUnsupported("match arm %s: binder count" % key)
            saved = [(b, b in env, env.get(b)) for b in binders]
            try:
                for b, x in zip(binders, vals):
                    env[b] = _cp(x)
                self.block(fn, blk, env)
            finally:
                for b, had, old in reversed(saved):
                    if had:
                        env[b] = old
                    else:
                        env.pop(b, None)
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
                self.charge(1)
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
            if isinstance(v, (list, bytes)):
                raise OracleUnsupported("print of array")
            self.output.append(format_value(v))
        elif k == "expr":
            self.ev(s[2], env)
        else:
            raise OracleUnsupported("statement %s" % k)


# ---------------------------------------------------------------- public API
def format_value(v):
    """String identical to Rust `{:?}` output: -5, true, [1, -2], [], Some(3), None, Ok(3), Err(-2), ().
    Structs and enums follow the #[derive(Debug)] shape of the generated Rust (`pub struct N { pub f: T }` and
    `pub enum E { V(T, U), W }` in pruvc/codegen.py:177-191): `Point { x: 1, y: -2 }`, a struct without fields `Name`,
    enums `Empty` / `Hit(Point { x: 3, y: 4 }, true)` (the payload is a tuple form without field names)."""
    if v is None:
        return "()"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, bytes):        # str: list of byte integers ({:?} of as_bytes() in the Rust driver)
        return "[" + ", ".join(str(x) for x in v) + "]"
    if isinstance(v, list):
        return "[" + ", ".join(format_value(x) for x in v) + "]"
    if isinstance(v, dict):
        if "tag" in v:
            return "None" if v["tag"] == "None" else "%s(%s)" % (v["tag"], format_value(v["v"]))
        if "struct" in v:
            if not v["fields"]:
                return v["struct"]
            return "%s { %s }" % (v["struct"], ", ".join(
                "%s: %s" % (f, format_value(x)) for f, x in v["fields"].items()))
        if "enum" in v:
            if not v["fields"]:
                return v["variant"]
            return "%s(%s)" % (v["variant"], ", ".join(format_value(x) for x in v["fields"].values()))
        raise OracleUnsupported("format_value of an unknown dict")
    return str(v)


def _str_arg(v):
    """str argument (Python str or UTF-8 bytes) -> bytes. Surrogates and invalid UTF-8 raise OracleUnsupported."""
    if isinstance(v, str):
        try:
            return v.encode("utf-8")
        except UnicodeEncodeError:
            raise OracleUnsupported("str argument is not encodable as UTF-8")
    if isinstance(v, bytes):
        try:
            v.decode("utf-8")
        except UnicodeDecodeError:
            raise OracleUnsupported("str argument is not valid UTF-8")
        return v
    raise OracleUnsupported("argument is not a str")


def _prep_args(fn, args):
    """New argument list in which Python str inputs for str parameters are converted to UTF-8 bytes."""
    return [_str_arg(a) if pt == "str" else a for (_pn, pt), a in zip(fn.params, args)]


def _check_arg(prog, ty, v):
    """Lightly check that a user-type argument value matches the program declaration (name, field order, variant). Raises OracleUnsupported if not.
    i64/bool/[i64]/Option/Result are not checked (existing behavior kept). array_u8, array_bool, and str have their value format checked."""
    if ty == "array_u8":
        if not (isinstance(v, list) and all(isinstance(x, int) and not isinstance(x, bool) and 0 <= x <= 255
                                            for x in v)):
            raise OracleUnsupported("argument is not a [u8] of 0..=255 ints")
        return
    if ty == "array_bool":
        if not (isinstance(v, list) and all(isinstance(x, bool) for x in v)):
            raise OracleUnsupported("argument is not a [bool] of bools")
        return
    if ty == "str":
        _str_arg(v)
        return
    if ty in prog.structs:
        if not (isinstance(v, dict) and v.get("struct") == ty):
            raise OracleUnsupported("argument is not struct %s" % ty)
        decl = prog.structs[ty]
    elif ty in prog.enums:
        if not (isinstance(v, dict) and v.get("enum") == ty):
            raise OracleUnsupported("argument is not enum %s" % ty)
        if v.get("variant") not in prog.enums[ty]:
            raise OracleUnsupported("unknown variant %s::%s" % (ty, v.get("variant")))
        decl = prog.enums[ty][v["variant"]]
    else:
        return
    fields = v.get("fields")
    if not isinstance(fields, dict) or list(fields) != [f for f, _t in decl]:
        raise OracleUnsupported("argument %s: fields do not match the declaration" % ty)
    for f, t in decl:
        _check_arg(prog, t, fields[f])


def _check_args(prog, fn, args):
    for (_pn, pt), a in zip(fn.params, args):
        _check_arg(prog, pt, a)


def run(prog, fn_name, args, max_steps=2_000_000, mode="safe", fn_decreases=False):
    fn0 = prog.fns.get(fn_name)
    if fn0 is not None and len(args) == len(fn0.params):
        _check_args(prog, fn0, args)
        args = _prep_args(fn0, args)
    it = _Interp(prog, max_steps, mode)
    it.fn_decreases = fn_decreases
    kind, value, detail = "ok", None, ""
    cargs = [_cp(a) for a in args]
    try:
        value = it.call(fn_name, cargs, top=True)
    except _Fault as f:
        kind, detail, value = f.kind, f.detail, None
    res = {"kind": kind, "value": value, "detail": detail, "output": it.output,
           "contract_failures": it.failures}
    if it.cost_calls:
        res["cost_calls"] = it.cost_calls
    # G5 (keys only appear for programs that use inout, so other results are unchanged): the final contents of the
    # top-level function's own inout parameters (mutated in place) and the number of inout calls that ran
    if fn0 is not None and fn0.inout and len(cargs) == len(fn0.params):
        res["inout_final"] = dict((pn, list(cargs[i])) for i, (pn, _t) in enumerate(fn0.params) if pn in fn0.inout)
    if it.inout_calls:
        res["inout_calls"] = it.inout_calls
    return res


def check_requires(prog, fn_name, args):
    fn = prog.fns.get(fn_name)
    if fn is None or len(args) != len(fn.params):
        raise OracleUnsupported("bad function/arity")
    _check_args(prog, fn, args)
    args = _prep_args(fn, args)
    it = _Interp(prog, 2_000_000)
    penv = dict((pn, _cp(a)) for (pn, _t), a in zip(fn.params, args))
    try:
        st, _i, _w = it.check_req(fn, penv)
    except _Fault:
        return "undefined"
    return st


def expected_stderr_prefix(result):
    k, d = result["kind"], result["detail"]
    if k == "cost_exceeded":
        return "pruv: cost exceeded"
    if k == "requires_violated":
        return "pruv: requires violated: %s:" % d.split()[0]
    if k == "requires_undefined":
        return "pruv: requires undefined:"
    if k == "oob":
        return "pruv: index out of bounds:"
    if k == "overflow":
        return "pruv: arithmetic error: alloc length" if d == "alloc" else "pruv: arithmetic error: overflow in " + d
    if k == "div_domain":
        return "pruv: arithmetic error: division outside domain"
    if k == "foreign_requires":
        return "pruv: foreign requires violated:"
    if k == "foreign_undefined":
        return "pruv: foreign contract undefined:"
    if k == "elem_range":
        return "pruv: element out of range: %s (u8 0..=255)" % d
    if k in ("slice_range", "slice_cut"):
        lo, hi, n = d.split()
        head = "string slice out of bounds" if k == "slice_range" else "UTF-8 boundary error"
        return "pruv: %s: %s..%s (len %s)" % (head, lo, hi, n)
    return None


# ---------------------------------------------------------------- G4: multi-module programs
# The oracle resolves module paths itself (written from SPEC.md 6f / docs/G4_SPEC.md 2-3 only, no compiler code):
#   * root.pruv is the root; `mod name;` in the file of module P loads P/name.pruv (root: name.pruv);
#   * `crate::a::b::item[::Variant]` names item `item` of module crate::a::b; an unqualified item name means the
#     item of the SAME module (never a parent, sibling or the whole program); builtins stay as they are;
#   * the modules are flattened into one single-file program in which every non-root item gets a unique mangled name
#     (`m<module number>_<name>`), so same-named items of different modules stay distinct; root items keep their
#     names (the host entry `f` stays `f`). The flat program is then run by the ordinary interpreter above.
# Visibility is NOT checked here (the compiler does that; the generator only emits legal programs).
_G4_TOK = re.compile(r"""
    (?P<com>//[^\n]*)
  | (?P<path>\bcrate(?:\s*::\s*[A-Za-z_][A-Za-z0-9_]*)+)
  | (?P<mod>\bmod\s+[A-Za-z_][A-Za-z0-9_]*\s*;)
  | (?P<pub>\bpub\b)
  | (?P<num>\d[A-Za-z0-9_]*)
  | (?P<id>[A-Za-z_][A-Za-z0-9_]*)
""", re.X)
_G4_ITEM = re.compile(r"\b(?:fn|struct|enum)\s+([A-Za-z_][A-Za-z0-9_]*)")
_G4_MODDECL = re.compile(r"^[ \t]*mod\s+([A-Za-z_][A-Za-z0-9_]*)\s*;", re.M)


def _g4_load(files):
    """files {relative path: source} -> (module path tuple -> comment-free source, load order). Root first, depth first."""
    mods, order = {}, []

    def load(path):
        rel = ("/".join(path) + ".pruv") if path else "root.pruv"
        if rel not in files:
            raise OracleParseError("module file missing: %s" % rel)
        text = re.sub(r"//[^\n]*", "", files[rel])
        mods[path] = text
        order.append(path)
        for nm in _G4_MODDECL.findall(text):
            if path + (nm,) in mods:
                raise OracleParseError("module %s declared twice" % "::".join(path + (nm,)))
            load(path + (nm,))

    load(())
    return mods, order


def flatten_modules(files):
    """-> single-file source of a multi-module program (see the block comment above)."""
    mods, order = _g4_load(files)
    items = dict((p, set(_G4_ITEM.findall(t))) for p, t in mods.items())

    def mangle(path, name):
        return name if not path else "m%d_%s" % (order.index(path), name)

    def rewrite(path, text):
        def resolve(segs):
            cur, i = (), 0
            while i < len(segs) and cur + (segs[i],) in mods:
                cur += (segs[i],)
                i += 1
            if i >= len(segs):
                raise OracleUnsupported("path crate::%s names a module, not an item" % "::".join(segs))
            if segs[i] not in items[cur]:
                raise OracleUnsupported("crate::%s: module %s has no item %s"
                                        % ("::".join(segs), "::".join(("crate",) + cur), segs[i]))
            return mangle(cur, segs[i]) + "".join("::" + s for s in segs[i + 1:])

        def sub(m):
            k = m.lastgroup
            if k in ("com", "mod", "pub"):
                return ""
            if k == "path":
                return resolve(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", m.group())[1:])
            if k == "id" and m.group() in items[path]:
                before = text[:m.start()].rstrip()
                after = text[m.end():].lstrip()
                if before.endswith(".") or before.endswith("::"):
                    return m.group()               # field access / variant name, never an item
                if after.startswith(":") and not after.startswith("::"):
                    return m.group()               # `name: T` parameter / field label
                return mangle(path, m.group())
            return m.group()

        return _G4_TOK.sub(sub, text)

    return "\n".join(rewrite(p, mods[p]) for p in order) + "\n"


def parse_modules(files):
    """Program of a multi-module source tree ({relative path: source}, root = "root.pruv")."""
    flat = flatten_modules(files)
    prog = parse_program(flat)
    prog.flat_src = flat
    return prog


# ---------------------------------------------------------------- self-test
def _selftest():
    def go(src, fn, args, **kw):
        return run(parse_program(src), fn, args, **kw)

    here = os.path.dirname(os.path.abspath(__file__))
    ex = os.path.join(here, "..", "..", "examples")

    def load(name):
        with open(os.path.join(ex, name)) as f:
            return f.read()

    r = go(load("sum.pruv"), "sum", [[1, 2, 3]])
    assert r["kind"] == "ok" and r["value"] == 6 and not r["contract_failures"], r
    assert go(load("sum.pruv"), "sum", [[2_000_000_000]])["kind"] == "requires_violated"
    pre = parse_program(load("prefix.pruv"))
    r = run(pre, "prefix", [[1, 2, 3]])
    assert r["value"] == [0, 1, 3, 6] and not r["contract_failures"], r
    r = run(pre, "main", [])
    assert r["output"] == ["21"], r
    bs = parse_program(load("bsearch.pruv"))
    r = run(bs, "bsearch", [[1, 3, 5], 3])
    assert r["kind"] == "ok" and r["value"] == {"tag": "Some", "v": 1} and not r["contract_failures"], r
    r = run(bs, "bsearch", [[1, 3, 5], 4])
    assert r["value"] == {"tag": "None"} and not r["contract_failures"], r

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
    assert expected_stderr_prefix(r) == "pruv: arithmetic error: overflow in unary -"
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
    assert expected_stderr_prefix(r) == "pruv: requires violated: f:"

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
    assert expected_stderr_prefix(r) == "pruv: requires violated: g:"
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

    _selftest_values(go)
    print("oracle self-test OK")


def _selftest_values(go):
    """Tests of newer constructs: structs, enums, Option/Result, array returns, etc."""
    import sys
    SOME = lambda v: {"tag": "Some", "v": v}
    NONE = {"tag": "None"}
    OK = lambda v: {"tag": "Ok", "v": v}
    ERR = lambda v: {"tag": "Err", "v": v}

    # 1) struct: copy independence after field assignment (let copy, argument-passing and return copies, nested field assignment)
    src = ("struct P { x: i64, y: i64 }\n"
           "fn f() -> i64 {\n let a: P = P { x: 1, y: 2 };\n let mut b: P = a;\n b.x = 10;\n"
           " return a.x * 100 + b.x;\n}\n")
    assert go(src, "f", [])["value"] == 110
    src = ("struct P { x: i64, y: i64 }\nstruct L { o: P, n: i64 }\n"
           "fn bump(p: L) -> L\n ensures result.o.x == p.o.x + 1\n{\n let mut q: L = p;\n"
           " q.o.x = q.o.x + 1;\n return q;\n}\n"
           "fn f() -> i64 {\n let a: L = L { o: P { x: 5, y: 0 }, n: 1 };\n let b: L = bump(a);\n"
           " return a.o.x * 10 + b.o.x;\n}\n")
    r = go(src, "f", [])
    assert r["value"] == 56 and not r["contract_failures"], r      # a is unchanged (5*10 + 6)

    # 2) enum match (arm order does not matter, variant without payload)
    src = ("enum Ev { Empty, Hit(a: i64, b: i64), Fail(code: i64), }\n"
           "fn s(e: Ev) -> i64 {\n match e {\n  Ev::Fail(c) => { return -c; }\n"
           "  Ev::Hit(a, b) => { return a * 10 + b; }\n  Ev::Empty => { return 0; }\n }\n}\n"
           "fn f() -> i64 { return s(Ev::Hit(3, 4)) + s(Ev::Fail(5)) * 1000 + s(Ev::Empty); }\n")
    assert go(src, "f", [])["value"] == 34 - 5000

    # 3) Option return + ensures some_val; an ensures outside the domain is recorded as a failure
    src = ("fn pick(n: i64) -> Option<i64>\n ensures is_some(result) ==> some_val(result) == n\n"
           "{\n if n > 0 { return Some(n); }\n return None;\n}\n"
           "fn bad(n: i64) -> Option<i64>\n ensures some_val(result) > 0\n{\n if n > 0 { return Some(n); }\n"
           " return None;\n}\n")
    r = go(src, "pick", [5])
    assert r["value"] == SOME(5) and not r["contract_failures"], r
    assert go(src, "pick", [-1])["value"] == NONE and not go(src, "pick", [-1])["contract_failures"]
    assert not go(src, "bad", [2])["contract_failures"]
    assert go(src, "bad", [-2])["contract_failures"] == ["ensures bad clause 1"]   # some_val(None): outside the domain

    # 4) some_val(None) in requires -> requires_undefined; with a guard, requires_violated
    src = ("fn g(o: Option<i64>) -> i64\n requires some_val(o) > 0\n{ return 1; }\n"
           "fn h(o: Option<i64>) -> i64\n requires is_some(o) && some_val(o) > 0\n{ return 1; }\n")
    p = parse_program(src)
    r = run(p, "g", [NONE])
    assert r["kind"] == "requires_undefined" and expected_stderr_prefix(r) == "pruv: requires undefined:", r
    assert run(p, "g", [SOME(-1)])["kind"] == "requires_violated"
    assert run(p, "g", [SOME(4)])["value"] == 1
    assert run(p, "h", [NONE])["kind"] == "requires_violated"
    assert check_requires(p, "g", [NONE]) == "undefined" and check_requires(p, "h", [NONE]) == "violated"
    assert check_requires(p, "h", [SOME(1)]) == "ok"

    # 5) variant_field domain: undefined for a different variant (requires gives requires_undefined, inner calls depend on the mode)
    src = ("enum Ev { Empty, Hit(value: i64) }\n"
           "fn f(e: Ev) -> i64\n requires variant_field(e, Ev::Hit, value) > 0\n{ return 0; }\n"
           "fn k(e: Ev) -> i64\n requires !is_variant(e, Ev::Hit) || variant_field(e, Ev::Hit, value) > 0\n"
           "{ return 0; }\n"
           "fn w() -> i64 { return f(Ev::Empty); }\n"
           "fn w2() -> i64 { return k(Ev::Empty) + k(Ev::Hit(3)); }\n"
           "fn w3() -> i64 { return k(Ev::Hit(-3)); }\n")
    p = parse_program(src)
    assert run(p, "w", [])["kind"] == "requires_undefined"
    r = run(p, "w", [], mode="proof")
    assert r["kind"] == "ok" and r["contract_failures"] == ["call_requires f clause 1"], r
    assert run(p, "w2", [])["kind"] == "ok"
    r = run(p, "w3", [])
    assert r["kind"] == "requires_violated" and r["detail"].startswith("k "), r

    # 6) array return + reassignment of a local array (copy / alloc / function result)
    src = ("fn mk(n: i64) -> [i64] ! alloc\n requires n >= 0\n ensures len(result) == n\n"
           "{ return alloc(n, 7); }\n"
           "fn f(a: [i64]) -> i64 ! alloc {\n let mut b: [i64] = copy(a);\n b = mk(3);\n b[0] = 1;\n"
           " let mut c: [i64] = alloc(2, 9);\n c = copy(b);\n b[1] = 5;\n"
           " return len(b) * 1000 + b[0] * 100 + b[1] * 10 + c[1];\n}\n"
           "fn g(a: [i64]) -> [i64] ! alloc { let mut b: [i64] = alloc(1, 0); b = alloc(len(a) + 1, 4); return b; }\n")
    p = parse_program(src)
    r = run(p, "mk", [3])
    assert r["value"] == [7, 7, 7] and not r["contract_failures"], r
    assert run(p, "mk", [-1])["kind"] == "requires_violated"
    assert run(p, "f", [[]])["value"] == 3157
    assert run(p, "g", [[1, 2]])["value"] == [4, 4, 4]

    # 7) two array parameters
    src = ("fn dot(a: [i64], b: [i64]) -> i64\n requires len(a) == len(b)\n{\n let mut i: i64 = 0;\n"
           " let mut s: i64 = 0;\n while i < len(a)\n  invariant 0 <= i && i <= len(a)\n"
           "  decreases len(a) - i\n {\n  s = s + a[i] * b[i];\n  i = i + 1;\n }\n return s;\n}\n")
    p = parse_program(src)
    r = run(p, "dot", [[1, 2, 3], [4, 5, 6]])
    assert r["value"] == 32 and not r["contract_failures"], r
    assert run(p, "dot", [[1], [1, 2]])["kind"] == "requires_violated"

    # 8) Result argument/return (dict form), overflow, == / != in contracts and the ok_val / err_val domain
    src = ("fn r(x: Result<i64>) -> Result<i64> {\n match x {\n  Err(c) => { return Err(c - 1); }\n"
           "  Ok(v) => { return Ok(v + 1); }\n }\n}\n"
           "fn e(o: Option<i64>) -> Option<i64>\n ensures result == o\n ensures !(result != o)\n{ return o; }\n"
           "fn h(x: Result<i64>) -> i64\n ensures err_val(x) > 0\n{ return 0; }\n"
           "fn h2(x: Result<i64>) -> i64\n ensures ok_val(x) > 0\n{ return 0; }\n"
           "fn d(o: Option<i64>) -> i64\n ensures result == 0 && o != Some(1)\n{ return 0; }\n")
    p = parse_program(src)
    assert run(p, "r", [OK(3)])["value"] == OK(4)
    assert run(p, "r", [ERR(-2)])["value"] == ERR(-3)
    r = run(p, "r", [OK(I64_MAX)])
    assert (r["kind"], r["detail"]) == ("overflow", "+"), r
    assert run(p, "e", [SOME(2)])["contract_failures"] == [] and run(p, "e", [NONE])["value"] == NONE
    assert run(p, "h", [ERR(3)])["contract_failures"] == []
    assert run(p, "h", [OK(3)])["contract_failures"] == ["ensures h clause 1"]       # err_val(Ok)
    assert run(p, "h2", [ERR(3)])["contract_failures"] == ["ensures h2 clause 1"]    # ok_val(Err)
    assert run(p, "d", [SOME(1)])["contract_failures"] == ["ensures d clause 1"]
    assert run(p, "d", [NONE])["contract_failures"] == []
    a = [SOME(1)]
    run(p, "e", a)
    assert a == [SOME(1)]   # the argument is unchanged

    # 9) struct literal inside a contract (arithmetic is mathematical) and enum == (compares variant and fields too)
    src = ("struct P { x: i64, y: i64 }\nenum Ev { Empty, Hit(a: i64, b: i64) }\n"
           "fn m(a: i64) -> i64\n ensures P { x: a * 2, y: 0 } == P { x: a + a, y: 0 }\n{ return 0; }\n"
           "fn t(n: i64) -> Ev\n ensures result == Ev::Hit(n, 2)\n{ return Ev::Hit(n, 2); }\n"
           "fn u(n: i64) -> Ev\n ensures result == Ev::Hit(n, 3)\n{ return Ev::Hit(n, 2); }\n"
           "fn c() -> () {\n assert Ev::Hit(1, 2) == Ev::Hit(1, 2) && Ev::Hit(1, 2) != Ev::Hit(1, 3)"
           " && Ev::Empty != Ev::Hit(1, 2) && Ev::Empty == Ev::Empty;\n}\n"
           "fn c2() -> () {\n assert Ev::Hit(1, 2) == Ev::Hit(1, 3);\n}\n")
    p = parse_program(src)
    r = run(p, "m", [I64_MAX])
    assert r["kind"] == "ok" and not r["contract_failures"], r      # 2^64-2 does not overflow inside the struct
    assert run(p, "t", [3])["contract_failures"] == []
    assert run(p, "u", [3])["contract_failures"] == ["ensures u clause 1"]
    assert run(p, "c", [])["contract_failures"] == []
    cf2 = run(p, "c2", [])["contract_failures"]
    assert len(cf2) == 1 and cf2[0].startswith("assert c2 line "), cf2

    # 10) evaluation order: struct fields, enum payloads, and Some go left to right
    src = ("struct S { x: i64, y: i64 }\nenum E { N, V(a: i64, b: i64) }\n"
           "fn p(x: i64) -> i64 ! io { print(x); return x; }\n"
           "fn f() -> i64 ! io {\n let s: S = S { x: p(1), y: p(2) };\n let e: E = E::V(p(3), p(4));\n"
           " let o: Option<i64> = Some(p(5));\n let mut r: i64 = s.x + s.y;\n"
           " match e {\n  E::N => { r = 0; }\n  E::V(a, b) => { r = r + a + b; }\n }\n"
           " match o {\n  None => { r = 0; }\n  Some(v) => { r = r + v; }\n }\n return r;\n}\n")
    r = go(src, "f", [])
    assert r["output"] == ["1", "2", "3", "4", "5"] and r["value"] == 3 + 7 + 5, r

    # 11) format_value uses the Rust {:?} format
    assert format_value(-5) == "-5" and format_value(True) == "true" and format_value(False) == "false"
    assert format_value([1, -2]) == "[1, -2]" and format_value([]) == "[]" and format_value(None) == "()"
    assert format_value(SOME(3)) == "Some(3)" and format_value(NONE) == "None"
    assert format_value(OK(3)) == "Ok(3)" and format_value(ERR(-2)) == "Err(-2)"

    # 11b) struct/enum Debug shape (nesting, Option fields, empty struct/variant)
    def S(n, **kw):
        return {"struct": n, "fields": kw}

    def E(n, v, **kw):
        return {"enum": n, "variant": v, "fields": kw}
    pt = S("Point", x=1, y=-2)
    assert format_value(pt) == "Point { x: 1, y: -2 }"
    assert format_value(S("Empty")) == "Empty"
    assert format_value(E("Event", "Empty")) == "Empty"
    assert format_value(E("Event", "Hit", pt=S("Point", x=3, y=4), ok=True)) == "Hit(Point { x: 3, y: 4 }, true)"
    assert format_value(S("W", o=SOME(3), m=NONE, r=ERR(-1))) == "W { o: Some(3), m: None, r: Err(-1) }"
    assert format_value(S("Outer", p=pt, e=E("Event", "Hit", pt=pt, ok=False))) == \
        "Outer { p: Point { x: 1, y: -2 }, e: Hit(Point { x: 1, y: -2 }, false) }"

    # 11c) function taking a struct argument and returning a copy with a changed field; argument format check
    src = ("struct Point { x: i64, y: i64 }\nenum Event { Empty, Hit(pt: Point, ok: bool) }\n"
           "fn f(p: Point, d: i64) -> Point\n requires d >= 0\n ensures result.x == p.x + d\n"
           "{ let mut q: Point = p; q.x = q.x + d; return q; }\n"
           "fn g(e: Event) -> Event { return e; }\n")
    p = parse_program(src)
    arg = S("Point", x=1, y=2)
    r = run(p, "f", [arg, 5])
    assert r["kind"] == "ok" and r["value"] == S("Point", x=6, y=2) and not r["contract_failures"], r
    assert format_value(r["value"]) == "Point { x: 6, y: 2 }"
    assert arg == S("Point", x=1, y=2)                  # the argument is unchanged
    assert check_requires(p, "f", [arg, -1]) == "violated" and check_requires(p, "f", [arg, 0]) == "ok"
    ev = E("Event", "Hit", pt=arg, ok=True)
    r = run(p, "g", [ev])
    assert r["value"] == ev and format_value(r["value"]) == "Hit(Point { x: 1, y: 2 }, true)", r
    assert format_value(run(p, "g", [E("Event", "Empty")])["value"]) == "Empty"
    for badargs in ([S("Pointt", x=1, y=2), 1], [S("Point", y=2, x=1), 1], [S("Point", x=1), 1],
                    [E("Event", "Empty"), 1], [3, 1]):
        try:
            run(p, "f", badargs)
            assert False, badargs
        except OracleUnsupported:
            pass
    for badargs in ([E("Event", "Nope")], [E("Event", "Hit", pt=S("Point", x=1), ok=True)],
                    [E("Event", "Hit", pt=arg)]):
        try:
            check_requires(p, "g", badargs)
            assert False, badargs
        except OracleUnsupported:
            pass

    # 13) G2: [u8]·[bool]·str
    def fails(src, fn, args, kind, prefix=None, detail=None, **kw):
        r = go(src, fn, args, **kw)
        assert r["kind"] == kind, r
        if detail is not None:
            assert r["detail"] == detail, r
        if prefix is not None:
            assert expected_stderr_prefix(r) == prefix, (r, expected_stderr_prefix(r))
        return r

    # 13a) type strings
    pg = parse_program("fn f(a: [u8], b: [bool], s: str, c: [i64]) -> str ! alloc { return s; }")
    assert pg.fns["f"].params == [("a", "array_u8"), ("b", "array_bool"), ("s", "str"), ("c", "arr")]
    assert pg.fns["f"].ret == "str"
    for bad in ["fn f(a: [u8 | 0..=9; <=4]) -> i64 { return 0; }", "fn f(o: Option<str>) -> i64 { return 0; }"]:
        try:
            parse_program(bad)
            assert False, bad
        except OracleUnsupported:
            pass

    # 13b) is_char_boundary expressions (code and contracts),"aé" = 97 195 169, "a😀" = 97 240 159 152 128
    bsrc = "fn b(s: str, i: i64) -> bool { return is_char_boundary(s, i); }"
    for s, exp in [("aé", {-1: False, 0: True, 1: True, 2: False, 3: True, 4: False}),
                   ("a\U0001F600", {1: True, 2: False, 3: False, 4: False, 5: True, 6: False}),
                   ("", {-1: False, 0: True, 1: False})]:
        for i, want in exp.items():
            r = go(bsrc, "b", [s, i])
            assert r["kind"] == "ok" and r["value"] is want, (s, i, r)
    csrc = "fn c(s: str, i: i64) -> () requires is_char_boundary(s, i) { }"
    pc = parse_program(csrc)
    assert check_requires(pc, "c", ["aé", 1]) == "ok" and check_requires(pc, "c", ["aé", 2]) == "violated"
    assert check_requires(pc, "c", ["aé", 3]) == "ok" and check_requires(pc, "c", ["aé", -1]) == "violated"
    assert check_requires(pc, "c", ["aé", 2 ** 100]) == "violated"
    assert go(csrc, "c", ["aé", 2])["kind"] == "requires_violated"
    esrc = "fn e(s: str) -> i64 ensures forall k in 0..len(s): is_char_boundary(s, k) ==> s[k] != 169 { return 0; }"
    assert go(esrc, "e", ["aé"])["contract_failures"] == []

    # 13c) substr: slice_range comes before slice_cut
    ssrc = "fn sub(s: str, lo: i64, hi: i64) -> str ! alloc { return substr(s, lo, hi); }"
    for mode in ("safe", "proof"):
        r = go(ssrc, "sub", ["é", 0, 2], mode=mode)
        assert r["kind"] == "ok" and r["value"] == b"\xc3\xa9" and format_value(r["value"]) == "[195, 169]", r
        r = go(ssrc, "sub", ["é", 1, 1], mode=mode)
        assert r["kind"] == "slice_cut" and r["detail"] == "1 1 2", r
        assert expected_stderr_prefix(r) == "pruv: UTF-8 boundary error: 1..1 (len 2)"
        r = go(ssrc, "sub", ["é", 1, 3], mode=mode)         # end out of range + start not on a boundary -> range
        assert r["kind"] == "slice_range" and r["detail"] == "1 3 2", r
        assert expected_stderr_prefix(r) == "pruv: string slice out of bounds: 1..3 (len 2)"
        assert go(ssrc, "sub", ["é", 2, 1], mode=mode)["kind"] == "slice_range"
        assert go(ssrc, "sub", ["é", -1, 1], mode=mode)["kind"] == "slice_range"
    assert go(ssrc, "sub", ["", 0, 0])["value"] == b""
    assert format_value(b"") == "[]" and format_value(b"hi") == "[104, 105]"

    # 13d) alloc: length -> value range, the value is checked even when length is 0, narrow-type positions
    asrc = "fn a(n: i64, v: i64) -> [u8] ! alloc { let x: [u8] = alloc(n, v); return x; }"
    fails(asrc, "a", [-1, 300], "overflow", "pruv: arithmetic error: alloc length", "alloc")
    fails(asrc, "a", [0, 300], "elem_range", "pruv: element out of range: 300 (u8 0..=255)", "300")
    fails(asrc, "a", [2, -1], "elem_range", "pruv: element out of range: -1 (u8 0..=255)")
    assert go(asrc, "a", [2, 255])["value"] == [255, 255]
    assert go(asrc, "a", [0, 0])["value"] == []
    fails("fn a(v: i64) -> [u8] ! alloc { return alloc(1, v); }", "a", [300], "elem_range")
    fails("fn a(v: i64) -> [u8] ! alloc { let mut x: [u8] = alloc(1, 0); x = alloc(1, v); return x; }",
          "a", [256], "elem_range")
    # outside a narrow position it is [i64]
    r = go("fn a(v: i64) -> i64 { let x: [u8] = copy(alloc(2, v)); return len(x) + x[0]; }", "a", [300])
    assert r["kind"] == "ok" and r["value"] == 302, r
    r = go("fn a(v: i64) -> i64 { let x: [i64] = alloc(2, v); return x[1]; }", "a", [300])
    assert r["kind"] == "ok" and r["value"] == 300, r
    bsrc2 = "fn ab(n: i64) -> [bool] ! alloc { let x: [bool] = alloc(n, true); x[0] = false; return x; }"
    r = go(bsrc2, "ab", [2])
    assert r["value"] == [False, True] and format_value(r["value"]) == "[false, true]", r
    fails(bsrc2, "ab", [0], "oob", "pruv: index out of bounds:")

    # 13e) [u8] store: index -> value range
    st = ("fn st(a: [u8], i: i64, v: i64) -> [u8] ! alloc { let mut b: [u8] = copy(a); b[i] = v; return b; }")
    fails(st, "st", [[1, 2], 5, 300], "oob", "pruv: index out of bounds:")
    fails(st, "st", [[1, 2], -1, 300], "oob")
    fails(st, "st", [[1, 2], 1, 300], "elem_range", "pruv: element out of range: 300 (u8 0..=255)")
    fails(st, "st", [[1, 2], 0, -1], "elem_range")
    r = go(st, "st", [[1, 2], 1, 255])
    assert r["value"] == [1, 255] and format_value(r["value"]) == "[1, 255]", r
    r = go("fn st(a: [i64], i: i64, v: i64) -> [i64] ! alloc { let mut b: [i64] = copy(a); b[i] = v; return b; }",
           "st", [[1, 2], 1, 300])
    assert r["value"] == [1, 300], r

    # 13f) string literals: escapes, multi-byte, str operations
    lit = r'fn lit() -> str ! alloc { return "\" \\ \n \r \t \0 ' + "é" + r'"; }'
    r = go(lit, "lit", [])
    assert r["value"] == b'" \\ \n \r \t \x00 \xc3\xa9', r
    assert go('fn f() -> i64 { return len("é"); }', "f", [])["value"] == 2
    assert go('fn f() -> str ! alloc { return "é"; }', "f", [])["value"] == b"\xc3\xa9"
    assert format_value(go('fn f() -> str ! alloc { return "é"; }', "f", [])["value"]) == "[195, 169]"
    assert go('fn f() -> i64 { return "é"[1]; }', "f", [])["value"] == 169
    r = go('fn f() -> str ! alloc { let s: str = "a\U0001F600"; return substr(s, 1, 5); }', "f", [])
    assert r["value"] == "\U0001F600".encode("utf-8"), r
    fails('fn f() -> str ! alloc { let s: str = "a\U0001F600"; return substr(s, 1, 3); }', "f", [],
          "slice_cut", "pruv: UTF-8 boundary error: 1..3 (len 5)")
    for badlit in [r'fn f() -> str { return "\x"; }', 'fn f() -> str { return "abc; }',
                   'fn f() -> str { return "a\nb"; }'.replace("\\n", "\n")]:
        try:
            parse_program(badlit)
            assert False, badlit
        except OracleParseError:
            pass
    try:
        go('fn f(s: str) -> bool { return s == "a"; }', "f", ["a"])
        assert False
    except OracleUnsupported:
        pass

    # 13g) str indexing, len, copy, input checks
    ssrc2 = "fn g(s: str, i: i64) -> i64 { let t: str = copy(s); return len(t) * 1000 + t[i]; }"
    assert go(ssrc2, "g", ["aé", 2])["value"] == 3169
    fails(ssrc2, "g", ["aé", 3], "oob", "pruv: index out of bounds:")
    fails(ssrc2, "g", ["aé", -1], "oob")
    cnt = ("fn cnt(s: str) -> i64 { let mut n: i64 = 0; let mut i: i64 = 0; "
           "while i < len(s) invariant 0 <= i && i <= len(s) decreases len(s) - i "
           "{ if s[i] < 128 || s[i] >= 192 { n = n + 1; } i = i + 1; } return n; }")
    r = go(cnt, "cnt", ["aé\U0001F600"])
    assert r["kind"] == "ok" and r["value"] == 3 and not r["contract_failures"], r
    assert go(cnt, "cnt", [b"a\xc3\xa9"])["value"] == 2
    for badarg in ([[256]], [[True]], ["x"], [None]):
        try:
            go("fn f(a: [u8]) -> i64 { return len(a); }", "f", badarg)
            assert False, badarg
        except OracleUnsupported:
            pass
    for badarg in ([[1]], ["\ud800"], [b"\xff"], [3]):
        try:
            go("fn f(a: str) -> i64 { return len(a); }", "f", badarg)
            assert False, badarg
        except OracleUnsupported:
            pass
    try:
        go("fn f(a: [bool]) -> i64 { return len(a); }", "f", [[1]])
        assert False
    except OracleUnsupported:
        pass
    assert go("fn f(a: [bool]) -> [bool] ! alloc { return copy(a); }", "f", [[True, False]])["value"] == [True, False]

    # 12) _cp also deep-copies dicts, unsupported constructs raise OracleUnsupported, and pruvc is not imported
    d = {"struct": "P", "fields": {"x": 1}}
    c = _cp(d)
    c["fields"]["x"] = 2
    assert d["fields"]["x"] == 1
    for bad in ["fn f(o: Option<Option<i64>>) -> i64 { return 0; }",
                "struct P { x: i64 }\nfn f() -> i64 { return P { y: 1 }.y; }\n",
                "fn f() -> i64 { match 3 { Some(v) => { return v; } } }"]:
        try:
            go(bad, "f", [])
            assert False, bad
        except (OracleUnsupported, OracleParseError):
            pass
    assert not any(m == "pruvc" or m.startswith("pruvc.") for m in sys.modules)


def _selftest_g3():
    """G3 (docs/G3_SPEC.md, SPEC.md 6c): generic declarations, explicit type arguments, nested type applications.
    Values are untyped at run time, so type arguments are parsed and dropped."""
    def go(src, fn, args, **kw):
        return run(parse_program(src), fn, args, **kw)

    # Option<T> fallback at bool, guarded payload access in the contract
    src = ("fn get_or<T>(o: Option<T>, d: T) -> T\n"
           "  ensures is_some(o) ==> result == some_val(o)\n"
           "  ensures !is_some(o) ==> result == d\n"
           "{\n  match o {\n    Some(v) => { return v; }\n    None => { return d; }\n  }\n}\n"
           "fn f(o: Option<bool>, d: bool) -> bool\n"
           "  ensures is_some(o) ==> result == some_val(o)\n"
           "{\n  return get_or::<bool>(o, d);\n}\n")
    r = go(src, "f", [{"tag": "Some", "v": True}, False])
    assert r["kind"] == "ok" and r["value"] is True and not r["contract_failures"], r
    r = go(src, "f", [{"tag": "None"}, False])
    assert r["kind"] == "ok" and r["value"] is False and not r["contract_failures"], r
    # nested Option and Result with explicit constructors
    src = ("fn wrap<T>(x: T) -> Option<T>\n  ensures is_some(result) && some_val(result) == x\n"
           "{\n  return Some::<T>(x);\n}\n"
           "fn f(x: i64) -> Option<Option<i64>> {\n  let o: Option<i64> = wrap::<i64>(x);\n"
           "  return wrap::<Option<i64>>(o);\n}\n"
           "fn g(c: i64) -> Result<bool> {\n  return Err::<bool>(c);\n}\n"
           "fn h() -> Option<bool> {\n  return None::<bool>;\n}\n")
    prog = parse_program(src)
    r = run(prog, "f", [4])
    assert r["value"] == {"tag": "Some", "v": {"tag": "Some", "v": 4}} and not r["contract_failures"], r
    assert format_value(r["value"]) == "Some(Some(4))"
    assert run(prog, "g", [7])["value"] == {"tag": "Err", "v": 7}
    assert run(prog, "h", [])["value"] == {"tag": "None"}
    # generic struct, swap, projections at i64/bool
    src = ("struct Pair<A, B> {\n  first: A,\n  second: B\n}\n"
           "fn swap<A, B>(p: Pair<A, B>) -> Pair<B, A>\n  ensures result.first == p.second\n"
           "{\n  return Pair::<B, A> { first: p.second, second: p.first };\n}\n"
           "fn f(a: i64, b: bool) -> i64\n  ensures result == a\n{\n"
           "  let p: Pair<i64, bool> = Pair::<i64, bool> { first: a, second: b };\n"
           "  let q: Pair<bool, i64> = swap::<i64, bool>(p);\n  return q.second;\n}\n")
    r = go(src, "f", [5, True])
    assert r["kind"] == "ok" and r["value"] == 5 and not r["contract_failures"], r
    # a false ensures is recorded, not a fault
    r = go(src.replace("ensures result == a", "ensures result == a + 1"), "f", [5, True])
    assert r["kind"] == "ok" and r["contract_failures"] == ["ensures f clause 1"], r
    # generic enum, match and variant_field
    src = ("enum Choice<A, B> {\n  Left(value: A),\n  Right(value: B)\n}\n"
           "fn left_or<A, B>(c: Choice<A, B>, d: A) -> A\n"
           "  ensures is_variant(c, Choice::Left) ==> result == variant_field(c, Choice::Left, value)\n"
           "{\n  match c {\n    Choice::Left(x) => { return x; }\n    Choice::Right(y) => { return d; }\n  }\n}\n"
           "fn f(t: bool, x: i64, y: bool, d: i64) -> i64 {\n  if t {\n"
           "    let c: Choice<i64, bool> = Choice::<i64, bool>::Left(x);\n    return left_or::<i64, bool>(c, d);\n  }\n"
           "  let e: Choice<i64, bool> = Choice::<i64, bool>::Right(y);\n  return left_or::<i64, bool>(e, d);\n}\n")
    assert go(src, "f", [True, 3, False, 9])["value"] == 3
    assert go(src, "f", [False, 3, False, 9])["value"] == 9
    # [T] reads, copies and stores; bounded forall in the contract and a loop invariant
    src = ("fn rev<T: Element>(a: [T]) -> [T] ! alloc\n  ensures len(result) == len(a)\n"
           "  ensures forall k in 0..len(a): result[k] == a[len(a) - 1 - k]\n{\n"
           "  let mut out: [T] = copy(a);\n  let mut i: i64 = 0;\n  while i < len(a)\n"
           "    invariant 0 <= i && i <= len(a)\n    invariant len(out) == len(a)\n"
           "    invariant forall j in 0..i: out[j] == a[len(a) - 1 - j]\n    decreases len(a) - i\n  {\n"
           "    out[i] = a[len(a) - 1 - i];\n    i = i + 1;\n  }\n  return out;\n}\n"
           "fn f(a: [bool]) -> [bool] ! alloc {\n  return rev::<bool>(a);\n}\n")
    r = go(src, "f", [[True, False, False]])
    assert r["value"] == [False, False, True] and not r["contract_failures"], r
    assert format_value(r["value"]) == "[false, false, true]"
    # without generic syntax the old restriction stays
    try:
        go("fn f(o: Option<bool>) -> i64 { return 0; }", "f", [{"tag": "None"}])
        assert False
    except OracleUnsupported:
        pass


def _selftest_g6():
    """G6 (docs/G6_SPEC.md 10-13): collections, take/move, catalog, contract observers, trusted min/max."""
    def go(src, fn, args, **kw):
        return run(parse_program(src), fn, args, **kw)

    # examples/g6_histogram.pruv: HashMap<i64, i64>, borrowed and taken maps, map_get + match
    src = ("fn bump(take m: HashMap<i64, i64>, k: i64) -> HashMap<i64, i64> ! alloc\n"
           "  requires len(m) < 1000000\n  ensures len(result) <= len(m) + 1\n{\n"
           "  let c: Option<i64> = map_get::<i64, i64>(m, k);\n  match c {\n"
           "    Some(n) => {\n      if n < 1000000 {\n        return map_insert::<i64, i64>(move m, k, n + 1);\n      }\n"
           "      return move m;\n    }\n    None => { return map_insert::<i64, i64>(move m, k, 1); }\n  }\n}\n"
           "fn count_of(m: HashMap<i64, i64>, k: i64) -> i64 {\n"
           "  let c: Option<i64> = map_get::<i64, i64>(m, k);\n  match c {\n"
           "    Some(n) => { return n; }\n    None => { return 0; }\n  }\n}\n"
           "fn most_of_three(a: i64, b: i64, c: i64) -> i64 ! alloc {\n"
           "  let mut m: HashMap<i64, i64> = map_new::<i64, i64>();\n  m = bump(move m, a);\n  m = bump(move m, b);\n"
           "  m = bump(move m, c);\n  return count_of(m, a);\n}\n")
    r = go(src, "most_of_three", [1, 1, 2])
    assert r["kind"] == "ok" and r["value"] == 2 and not r["contract_failures"], r
    assert go(src, "most_of_three", [5, 6, 7])["value"] == 1
    # examples/g6_string_build.pruv: String from str parameters/literals (multibyte), string_to_str
    src = ("fn greet(name: str) -> str ! alloc\n  requires len(name) <= 1000\n  ensures len(result) == 7 + len(name)\n{\n"
           "  let mut s: String = string_new();\n  s = string_push_str(move s, \"hello, \");\n"
           "  s = string_push_str(move s, name);\n  return string_to_str(s);\n}\n")
    r = go(src, "greet", ["wörld"])
    assert r["kind"] == "ok" and r["value"] == "hello, wörld".encode("utf-8") and not r["contract_failures"], r
    assert format_value(go(src, "greet", ["a"])["value"]) == "[104, 101, 108, 108, 111, 44, 32, 97]"
    # examples/g6_vec_running_sum.pruv + vec_get faults (foreign requires, both modes)
    src = ("fn prefix_sums(a: [i64]) -> i64 ! alloc\n  requires len(a) <= 1000\n"
           "  requires forall k in 0..len(a): 0 <= a[k] && a[k] <= 1000\n  ensures 0 <= result && result <= 1000000\n{\n"
           "  let mut v: Vec<i64> = vec_new::<i64>();\n  let mut s: i64 = 0;\n  let mut i: i64 = 0;\n  while i < len(a)\n"
           "    invariant 0 <= i && i <= len(a)\n    invariant len(v) == i\n    invariant 0 <= s && s <= 1000 * i\n"
           "    invariant forall k in 0..i: 0 <= v[k] && v[k] <= 1000 * i\n    decreases len(a) - i\n  {\n"
           "    s = s + a[i];\n    v = vec_push::<i64>(move v, s);\n    i = i + 1;\n  }\n"
           "  if len(v) == 0 {\n    return 0;\n  }\n  return vec_get::<i64>(v, len(v) - 1);\n}\n")
    for mode in ("safe", "proof"):
        r = go(src, "prefix_sums", [[1, 2, 3]], mode=mode)
        assert r["kind"] == "ok" and r["value"] == 6 and not r["contract_failures"], r
        assert go(src, "prefix_sums", [[2000]], mode=mode)["kind"] == "requires_violated"
    src = ("fn f(i: i64) -> i64 ! alloc {\n  let mut v: Vec<i64> = vec_new::<i64>();\n"
           "  v = vec_push::<i64>(move v, 5);\n  return vec_get::<i64>(v, i);\n}\n")
    for mode in ("safe", "proof"):
        assert go(src, "f", [0], mode=mode)["value"] == 5
        for bad in (1, -1):
            r = go(src, "f", [bad], mode=mode)
            assert r["kind"] == "foreign_requires", r
            assert expected_stderr_prefix(r) == "pruv: foreign requires violated:"
    src = ("fn f(i: i64) -> i64 ! alloc {\n  let mut s: String = string_new();\n"
           "  s = string_push_str(move s, \"hé\");\n  return string_byte(s, i);\n}\n")
    assert [go(src, "f", [i])["value"] for i in range(3)] == [104, 0xC3, 0xA9]
    assert go(src, "f", [3])["kind"] == "foreign_requires"
    # examples/g6_min_clamp.pruv: trusted rust fn with the std::cmp::min / max contracts
    src = ("trusted rust fn rust_min(a: i64, b: i64) -> i64\n  ensures result <= a && result <= b\n"
           "  ensures result == a || result == b\n  = \"::std::cmp::min\";\n\n"
           "trusted rust fn rust_max(a: i64, b: i64) -> i64\n  ensures result >= a && result >= b\n"
           "  ensures result == a || result == b\n  = \"::std::cmp::max\";\n\n"
           "fn clamp(x: i64, lo: i64, hi: i64) -> i64\n  requires lo <= hi\n  ensures lo <= result && result <= hi\n{\n"
           "  return rust_min(rust_max(x, lo), hi);\n}\n")
    assert [go(src, "clamp", [x, 0, 10])["value"] for x in (-5, 4, 15)] == [0, 4, 10]
    assert go(src, "clamp", [1, 5, 4])["kind"] == "requires_violated"
    # take helper + map_updated / map_lookup observers; a false ensures is recorded, not a fault
    src = ("fn put(take m: HashMap<i64, i64>, k: i64, x: i64) -> HashMap<i64, i64> ! alloc\n"
           "  requires len(m) < 1000000\n  ensures map_updated::<i64, i64>(result, m, k, x)\n"
           "  ensures map_lookup::<i64, i64>(result, k) == Some::<i64>(x)\n{\n"
           "  return map_insert::<i64, i64>(move m, k, x);\n}\n"
           "fn f(k: i64, x: i64, y: i64, q: i64) -> i64 ! alloc {\n"
           "  let mut m: HashMap<i64, i64> = map_new::<i64, i64>();\n  m = put(move m, k, x);\n  m = put(move m, k, y);\n"
           "  let r: Option<i64> = map_get::<i64, i64>(m, q);\n  match r {\n    Some(v) => { return v; }\n"
           "    None => { return -1; }\n  }\n}\n")
    r = go(src, "f", [3, 10, 20, 3])
    assert r["value"] == 20 and not r["contract_failures"], r
    assert go(src, "f", [3, 10, 20, 4])["value"] == -1
    bad = src.replace("map_updated::<i64, i64>(result, m, k, x)", "map_updated::<i64, i64>(result, m, k, x + 1)")
    assert go(bad, "f", [3, 10, 20, 3])["contract_failures"] == ["ensures put clause 1", "ensures put clause 2"] or \
        go(bad, "f", [3, 10, 20, 3])["contract_failures"] == ["ensures put clause 1"], go(bad, "f", [3, 10, 20, 3])
    # bool keys and values, Vec<bool>, take helper that returns `move`, branch move with reinitialization
    src = ("fn grow(take v: Vec<bool>, x: bool) -> Vec<bool> ! alloc\n  requires len(v) < 1000\n"
           "  ensures len(result) == len(v) + 1\n  ensures result[len(v)] == x\n"
           "  ensures forall i in 0..len(v): result[i] == v[i]\n{\n"
           "  let mut w: Vec<bool> = move v;\n  w = vec_push::<bool>(move w, x);\n  return move w;\n}\n"
           "fn f(flag: bool, n: i64) -> bool ! alloc {\n"
           "  let mut m: HashMap<bool, bool> = map_new::<bool, bool>();\n"
           "  m = map_insert::<bool, bool>(move m, flag, true);\n  m = map_insert::<bool, bool>(move m, true, false);\n"
           "  let mut v: Vec<bool> = vec_new::<bool>();\n  v = grow(move v, flag);\n  if n > 0 {\n"
           "    let t: Vec<bool> = move v;\n    v = grow(move t, true);\n  } else {\n    v = grow(move v, false);\n  }\n"
           "  if len(v) > 5 {\n    return false;\n  }\n"
           "  let r: Option<bool> = map_get::<bool, bool>(m, flag);\n  match r {\n    Some(b) => { return b && vec_get::<bool>(v, 0) == flag; }\n"
           "    None => { return false; }\n  }\n}\n")
    r = go(src, "f", [True, 1])
    assert r["kind"] == "ok" and r["value"] is False and not r["contract_failures"], r     # map[true] was replaced by false
    r = go(src, "f", [False, 0])
    assert r["kind"] == "ok" and r["value"] is True and not r["contract_failures"], r
    # a user type named like a catalog type keeps its meaning (no collection parse)
    try:
        go("struct String { x: i64 }\nfn f(s: String) -> i64 { return s.x; }", "f",
           [{"struct": "String", "fields": {"x": 4}}])
    except OracleUnsupported:
        pass


def _selftest_g9():
    """G9 (docs/G9_SPEC.md, SPEC.md 6e): function-level `decreases`, size(), recursive types, mutual recursion, token cursor
    descent, buffer-field clones. Expected values were computed by hand."""
    import sys
    sys.setrecursionlimit(max(sys.getrecursionlimit(), 6000))

    def go(src, fn, args, **kw):
        return run(parse_program(src), fn, args, **kw)

    # examples/g9_linked_struct.pruv shape: Node <-> Link, size() in contracts, recursion with `decreases`
    src = ("struct Node { value: i64, next: Link }\nenum Link { End, More(node: Node) }\n"
           "fn single(v: i64) -> Node ! alloc\n  ensures size(result) == 2 && result.value == v\n"
           "{\n  return Node { value: v, next: Link::End };\n}\n"
           "fn push(n: Node, v: i64) -> Node ! alloc\n  ensures size(result) == size(n) + 2 && result.value == v\n"
           "{\n  return Node { value: v, next: Link::More(n) };\n}\n"
           "fn grow(k: i64) -> Node ! alloc\n  requires k >= 0\n  ensures size(result) == 2 * k + 2\n  decreases k\n{\n"
           "  if k == 0 { return single(0); }\n  let r: Node = grow(k - 1);\n  return push(r, k);\n}\n"
           "fn node_len(n: Node) -> i64\n  requires size(n) <= 1000\n  ensures 2 * result == size(n)\n"
           "  decreases size(n)\n{\n  return 1 + link_len(n.next);\n}\n"
           "fn link_len(l: Link) -> i64\n  requires size(l) <= 1000\n  ensures 2 * result + 1 == size(l)\n"
           "  decreases size(l)\n{\n  match l {\n    Link::End => { return 0; }\n    Link::More(n) => { return node_len(n); }\n  }\n}\n"
           "fn f(k: i64) -> i64 ! alloc\n  requires k >= 0 && k <= 100\n  ensures result == k + 1\n{\n"
           "  let g: Node = grow(k);\n  return node_len(g);\n}\n")
    for mode in ("safe", "proof"):
        r = go(src, "f", [3], mode=mode)
        assert r["kind"] == "ok" and r["value"] == 4 and not r["contract_failures"], r
        assert go(src, "f", [-1], mode=mode)["kind"] == "requires_violated"
    bad = src.replace("ensures result == k + 1", "ensures result == k + 2")
    assert go(bad, "f", [3], mode="proof")["contract_failures"] == ["ensures f clause 1"]
    # mutual recursion with phase measures (examples/g9_phase_measure.pruv with C = 2, D = 1)
    src = ("fn ping(n: i64) -> i64\n  requires 0 <= n && n <= 20\n  ensures result == 2 * n + 1\n  decreases 2 * n + 1\n{\n"
           "  if n == 0 { return 1; }\n  return pong(n);\n}\n"
           "fn pong(n: i64) -> i64\n  requires 1 <= n && n <= 20\n  ensures result == 2 * n + 1\n  decreases 2 * n\n{\n"
           "  return 2 + ping(n - 1);\n}\n")
    r = go(src, "ping", [3], mode="proof")
    assert r["kind"] == "ok" and r["value"] == 7 and not r["contract_failures"], r
    # token cursor descent (bench/g9/solutions/ref/q03.pruv): atom 0, open 1, close 2
    src = ("fn value_end(a: [i64], i: i64) -> i64\n  requires 0 <= i && i <= len(a) && len(a) <= 20\n"
           "  ensures result == 0 - 1 || (i < result && result <= len(a))\n"
           "  decreases 2 * (len(a) - i) + 1\n{\n"
           "  if i == len(a) { return 0 - 1; }\n  if a[i] == 0 { return i + 1; }\n  if a[i] != 1 { return 0 - 1; }\n"
           "  return items_end(a, i + 1);\n}\n"
           "fn items_end(a: [i64], j: i64) -> i64\n  requires 0 <= j && j <= len(a) && len(a) <= 20\n"
           "  ensures result == 0 - 1 || (j < result && result <= len(a))\n  decreases 2 * (len(a) - j) + 2\n{\n"
           "  if j == len(a) { return 0 - 1; }\n  if a[j] == 2 { return j + 1; }\n"
           "  let k: i64 = value_end(a, j);\n  if k < 0 { return 0 - 1; }\n  return items_end(a, k);\n}\n"
           "fn f(a: [i64]) -> bool\n  requires len(a) <= 20\n  ensures result ==> len(a) >= 1\n{\n"
           "  return value_end(a, 0) == len(a);\n}\n")
    for arr, want in (([1, 0, 0, 2], True), ([1, 0], False), ([0], True), ([0, 0], False), ([], False), ([1, 1, 2, 2], True)):
        r = go(src, "f", [arr], mode="proof")
        assert r["kind"] == "ok" and r["value"] is want and not r["contract_failures"], (arr, r)
    # buffer-field clone: copy into a mutable local, replace the field, the original keeps its elements
    src = ("struct Bag { items: [i64], tag: i64 }\n"
           "fn with_first(b: Bag, v: i64) -> Bag ! alloc\n  requires len(b.items) >= 1\n"
           "  ensures len(result.items) == len(b.items)\n  ensures result.items[0] == v\n{\n"
           "  let mut c: Bag = b;\n  let mut arr: [i64] = copy(c.items);\n  arr[0] = v;\n  c.items = copy(arr);\n  return c;\n}\n"
           "fn f(a: [i64], v: i64) -> i64 ! alloc\n  requires 1 <= len(a) && len(a) <= 20\n"
           "  requires -1000 <= a[0] && a[0] <= 1000 && -1000 <= v && v <= 1000\n{\n"
           "  let b: Bag = Bag { items: copy(a), tag: 1 };\n  let c: Bag = with_first(b, v);\n"
           "  return b.items[0] * 100 + c.items[0];\n}\n")
    r = go(src, "f", [[5, 6], 9], mode="proof")
    assert r["kind"] == "ok" and r["value"] == 509 and not r["contract_failures"], r
    assert go(src, "f", [[], 9])["kind"] == "requires_violated"


def _selftest_g4():
    """G4 (docs/G4_SPEC.md 2-3): module loading, `crate::` path resolution, distinct same-named items."""
    files = {
        "root.pruv": ("mod a;\nmod b;\n"
                      "pub fn f(x: i64) -> i64\n  requires 0 <= x && x <= 100\n  ensures result == 3 * x + 3\n{\n"
                      "  let p: crate::a::util::T = crate::a::util::f(x);\n"
                      "  let q: crate::b::util::T = crate::b::util::f(x);\n"
                      "  return helper(p.v + q.v + q.w);\n}\n"
                      "fn helper(x: i64) -> i64\n  ensures result == x\n{\n  return x;\n}\n"),
        "a.pruv": "mod util;\n",
        "a/util.pruv": ("pub struct T { v: i64 }\n"
                        "pub fn f(x: i64) -> T\n  ensures result.v == x + 1\n{\n  return T { v: x + 1 };\n}\n"),
        "b.pruv": "mod util;\n",
        "b/util.pruv": ("pub struct T { v: i64, w: i64 }\n"
                        "pub fn f(x: i64) -> T\n  ensures result.v == x + 1 && result.w == x + 1\n{\n"
                        "  return crate::b::util::T { v: x + 1, w: x + 1 };\n}\n"),
    }
    prog = parse_modules(files)
    for mode in ("safe", "proof"):
        r = run(prog, "f", [10], mode=mode)
        assert r["kind"] == "ok" and r["value"] == 33 and not r["contract_failures"], r
        assert run(prog, "f", [101], mode=mode)["kind"] == "requires_violated"
    assert check_requires(prog, "f", [5]) == "ok" and check_requires(prog, "f", [-1]) == "violated"
    # the same leaf names `f` / `T` in the three modules must stay three distinct items
    assert len([n for n in prog.fns if n.endswith("_f") or n == "f"]) == 3, sorted(prog.fns)
    assert len(prog.structs) == 2, sorted(prog.structs)
    for bad in (dict(files, **{"root.pruv": files["root.pruv"].replace("crate::a::util::f", "crate::a::nope::f")}),
                dict(files, **{"root.pruv": files["root.pruv"].replace("crate::b::util::f", "crate::b::util::g")})):
        try:
            parse_modules(bad)
            assert False, "unknown path accepted"
        except OracleUnsupported:
            pass


def _selftest_g5():
    """G5 (docs/G5_SPEC.md 2-5): inout parameters mutate the caller's owner in place, old(..) is frozen at entry,
    ensures see the final contents, the top-level run reports the final inout arrays."""
    setat = ("fn set_at(inout a: [i64], i: i64, v: i64) -> ()\n  requires 0 <= i && i < len(a)\n"
             "  ensures len(a) == len(old(a))\n  ensures a[i] == v\n"
             "  ensures forall k in 0..len(a): k != i ==> a[k] == old(a)[k]\n{\n  a[i] = v;\n}\n")
    src = (setat +
           "fn bad(inout a: [i64]) -> ()\n  requires len(a) >= 1\n  ensures a[0] == old(a)[0]\n{\n  a[0] = a[0] + 1;\n}\n"
           "fn two(inout a: [i64], i: i64) -> ()\n  requires 0 <= i && i + 1 < len(a)\n"
           "  ensures a[i] == 7 && a[i + 1] == 8\n{\n  set_at(inout a, i, 7);\n  set_at(inout a, i + 1, 8);\n}\n"
           "fn f(a: [i64], i: i64) -> [i64] ! alloc\n  requires 0 <= i && i < len(a)\n{\n"
           "  let mut w: [i64] = copy(a);\n  set_at(inout w, i, 7);\n  set_at(inout w, 0, 8);\n  return w;\n}\n"
           "fn g(a: [i64]) -> [i64] ! alloc\n  requires len(a) >= 1\n{\n"
           "  let mut w: [i64] = copy(a);\n  bad(inout w);\n  return w;\n}\n"
           "fn h(a: [i64], i: i64) -> [i64] ! alloc\n  requires 0 <= i && i + 1 < len(a)\n{\n"
           "  let mut w: [i64] = copy(a);\n  two(inout w, i);\n  return w;\n}\n")
    prog = parse_program(src)
    arr = [1, 2, 3]
    for mode in ("safe", "proof"):
        r = run(prog, "f", [arr, 1], mode=mode)
        assert r["kind"] == "ok" and r["value"] == [8, 7, 3] and not r["contract_failures"], r
        assert r["inout_calls"] == 2 and arr == [1, 2, 3], (r, arr)          # the caller's input is never mutated
        r = run(prog, "h", [arr, 1], mode=mode)
        assert r["kind"] == "ok" and r["value"] == [1, 7, 8] and not r["contract_failures"], r
        r = run(prog, "g", [arr], mode=mode)                                  # old() is the entry value, not the latest
        assert r["kind"] == "ok" and r["value"] == [2, 2, 3], r
        assert r["contract_failures"] == ["ensures bad clause 1"], r
        r = run(prog, "set_at", [arr, 1, 9], mode=mode)                       # top-level inout: final array is reported
        assert r["kind"] == "ok" and r["value"] is None and r["inout_final"] == {"a": [1, 9, 3]}, r
        assert arr == [1, 2, 3]
    assert run(prog, "f", [arr, 3])["kind"] == "requires_violated"
    assert run(prog, "set_at", [arr, 3, 9])["kind"] == "requires_violated"
    # a missing or extra marker is not a G5 program
    for bad in (src.replace("set_at(inout w, 0, 8)", "set_at(w, 0, 8)"),
                src.replace("bad(inout w)", "bad(inout w, inout w)")):
        try:
            run(parse_program(bad), "f", [arr, 1])
            run(parse_program(bad), "g", [arr])
            assert False, "marker mismatch accepted"
        except OracleUnsupported:
            pass
    # recursion with a function-level measure, a loop invariant over old(), a generic instance as a statement, [u8] / [bool]
    src = ("fn fill_from(inout a: [i64], i: i64, v: i64) -> ()\n  requires 0 <= i && i <= len(a)\n"
           "  ensures len(a) == len(old(a))\n  ensures forall k in i..len(a): a[k] == v\n"
           "  ensures forall k in 0..i: a[k] == old(a)[k]\n  decreases len(a) - i\n{\n"
           "  if i < len(a) {\n    a[i] = v;\n    fill_from(inout a, i + 1, v);\n  }\n}\n"
           "fn exchange<T: Element>(inout b: [T], i: i64, j: i64) -> ()\n"
           "  requires 0 <= i && i < len(b) && 0 <= j && j < len(b)\n  ensures b[i] == old(b)[j]\n"
           "  ensures b[j] == old(b)[i]\n{\n  let x: T = b[i];\n  let y: T = b[j];\n  b[i] = y;\n  b[j] = x;\n}\n"
           "fn put_byte(inout b: [u8], i: i64, v: i64) -> ()\n  requires 0 <= i && i < len(b) && 0 <= v && v <= 255\n"
           "  ensures b[i] == v\n{\n  b[i] = v;\n}\n"
           "fn inc_all(inout a: [i64]) -> ()\n  ensures forall k in 0..len(a): a[k] == old(a)[k] + 1\n{\n"
           "  let n: i64 = len(a);\n  let mut i: i64 = 0;\n  while i < n\n    invariant 0 <= i && i <= n\n"
           "    invariant n == len(old(a))\n    invariant forall k in 0..i: a[k] == old(a)[k] + 1\n"
           "    invariant forall k in i..n: a[k] == old(a)[k]\n    decreases n - i\n  {\n"
           "    a[i] = a[i] + 1;\n    i = i + 1;\n  }\n}\n"
           "fn f(a: [i64], fl: [bool], u: [u8], i: i64) -> [i64] ! alloc\n  requires 0 <= i && i <= len(a) && len(fl) >= 1"
           " && len(u) >= 1\n{\n"
           "  let mut w: [i64] = copy(a);\n  let mut x: [bool] = copy(fl);\n  let mut y: [u8] = copy(u);\n"
           "  fill_from(inout w, i, 5);\n  inc_all(inout w);\n  exchange::<bool>(inout x, 0, 0);\n"
           "  exchange::<i64>(inout w, 0, i - i);\n  put_byte(inout y, 0, 255);\n  return w;\n}\n")
    prog = parse_program(src)
    for mode in ("safe", "proof"):
        r = run(prog, "f", [[1, 2, 3], [True], [0], 1], mode=mode)
        assert r["kind"] == "ok" and r["value"] == [2, 6, 6] and not r["contract_failures"], r
        assert r["inout_calls"] == 7, r          # fill_from x3 (recursion), inc_all, exchange x2, put_byte
    r = run(prog, "put_byte", [[1, 2], 0, 256], mode="proof")
    assert r["kind"] == "requires_violated", r


def _selftest_g7():
    src = """fn put(inout a: [i64], src: [i64]) -> ()
      requires len(a) > 0 && len(src) > 0
      ensures a[0] == src[0]
      ensures forall k in 1..len(a): a[k] == old(a)[k]
    { a[0] = src[0]; }
    fn f(inout a: [i64], inout b: [i64], src: [i64]) -> () {
      par { put(inout a, src); put(inout b, src); }
    }"""
    for mode in ("safe", "proof"):
        r = run(parse_program(src), "f", [[1, 2], [3, 4], [9]], mode=mode)
        assert r["kind"] == "ok" and r["inout_final"] == {"a": [9, 2], "b": [9, 4]}, r
    import generate
    import random
    for i in range(30):
        case = generate.generate_g7_case(71, i)
        for a in generate.candidate_inputs(case, random.Random(i), 8):
            for mode in ("safe", "proof"):
                r = run(parse_modules(case["files"]), "f", a, mode=mode)
                assert r["kind"] == "ok" and not r.get("contract_failures"), (i, a, r)
    print("G7 oracle self-test passed")


def _selftest_s5():
    import generate
    for i in range(len(generate.S5_FAMILIES)):
        case = generate.generate_s5_case(81, i)
        for values in generate.s5_inputs(81, i, 8):
            r = run(parse_program(case["src"]), "f", values)
            assert r["kind"] == "ok" and not r["contract_failures"], (case["kind"], values, r)
            if case["twin_src"]:
                twin = parse_program(case["twin_src"])
                proof = run(twin, "f", values, mode="proof")
                last = proof["cost_calls"][-1]
                expected = "cost_exceeded" if last["spent"] > last["bound"] else "ok"
                assert run(twin, "f", values)["kind"] == expected
    # Independent constants catch wrong units, actual-vs-declared charging and frame leakage.
    src = ("fn g() -> () cost 7 {} fn f() -> () ! alloc cost 20 "
           "{ g(); let a: [i64] = alloc(3, 0); let b: [i64] = copy(a); }")
    r = run(parse_program(src), "f", [])
    assert r["cost_calls"] == [{"function": "g", "bound": 7, "spent": 0},
                               {"function": "f", "bound": 20, "spent": 16}], r
    assert run(parse_program("fn f() -> () cost -1 {}"), "f", [])["kind"] == "cost_exceeded"
    print("oracle s5 self-test: OK")


def g8_value(name, args):
    """Independent mathematical values; never parse std or use compiler/SMT output."""
    def option(v):
        return {"tag": "Some", "v": v}
    if name in ("checked_add", "checked_sub"):
        a, b = args
        v = a + b if name == "checked_add" else a - b
        return option(v) if -(1 << 63) <= v < (1 << 63) else {"tag": "None"}
    if name == "min":
        return min(args)
    if name == "max":
        return max(args)
    if name == "abs":
        assert args[0] > -(1 << 63)
        return abs(args[0])
    if name == "clamp":
        x, lo, hi = args
        assert lo <= hi
        return min(hi, max(lo, x))
    a = args[0]
    if name == "sum":
        assert len(a) <= 1000000 and all(-1000000000 <= x <= 1000000000 for x in a)
        return sum(a)
    if name == "contains":
        return args[1] in a
    if name == "index_of":
        return option(a.index(args[1])) if args[1] in a else {"tag": "None"}
    if name == "is_sorted":
        return all(x <= y for x, y in zip(a, a[1:]))
    if name == "array_max":
        assert a
        return max(a)
    if name == "reverse":
        return a[::-1]
    raise OracleUnsupported("G8 function: " + name)


def g8_run(case, args):
    kind = case["kind"]
    if kind == "sum_add":
        value = g8_value("checked_add", [g8_value("sum", [a]) for a in args])
    elif kind == "max_clamp":
        value = g8_value("clamp", [g8_value("array_max", args)] + case["bounds"])
    elif kind == "reverse_index":
        value = g8_value("index_of", [g8_value("reverse", [args[0]]), args[1]])
    else:
        value = g8_value(kind, args)
    return {"kind": "ok", "value": value, "output": [], "contract_failures": []}


def _selftest_g8():
    mn, mx = -(1 << 63), (1 << 63) - 1
    some = lambda v: {"tag": "Some", "v": v}
    none = {"tag": "None"}
    rows = [("min", [mn, mx], mn), ("max", [mn, mx], mx),
            ("abs", [mn + 1], mx), ("clamp", [mn, 0, 0], 0),
            ("clamp", [mx, -2, 2], 2), ("clamp", [1, -2, 2], 1),
            ("checked_add", [mx, 1], none), ("checked_add", [mn, -1], none),
            ("checked_add", [mn, mx], some(-1)), ("checked_add", [mx - 1, 1], some(mx)),
            ("checked_sub", [mn, 1], none), ("checked_sub", [mx, -1], none),
            ("checked_sub", [0, mn], none), ("checked_sub", [-1, mn], some(mx)),
            ("sum", [[]], 0), ("sum", [[1000000000] * 8], 8000000000),
            ("sum", [[-1000000000] * 8], -8000000000),
            ("contains", [[], 0], False), ("contains", [[2, 2], 2], True),
            ("index_of", [[2, 3, 2], 2], some(0)), ("index_of", [[2], 3], none),
            ("index_of", [[], 0], none), ("is_sorted", [[]], True),
            ("is_sorted", [[7, 7, 7]], True), ("is_sorted", [[3, 2, 1]], False),
            ("array_max", [[mn, -1, mn]], -1), ("reverse", [[]], []),
            ("reverse", [[mn, 0, mx]], [mx, 0, mn])]
    for name, args, expected in rows:
        assert g8_value(name, args) == expected, (name, args)
    assert g8_run({"kind": "sum_add"}, [[1, 2], [-5]])["value"] == some(-2)
    assert g8_run({"kind": "max_clamp", "bounds": [-2, 2]}, [[-8, 9]])["value"] == 2
    assert g8_run({"kind": "reverse_index"}, [[4, 2, 4, 9], 4])["value"] == some(1)
    print("oracle g8 self-test: OK")


if __name__ == "__main__":
    _selftest_g8()
    _selftest()
    _selftest_g3()
    _selftest_g6()
    _selftest_g9()
    _selftest_g4()
    _selftest_g5()
    _selftest_g7()
    _selftest_s5()
