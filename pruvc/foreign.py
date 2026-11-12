"""G6 A0 (docs/G6_SPEC.md section 10): the fixed standard catalog, validation of `trusted rust fn` declarations,
the ownership/liveness checker for collection bindings, and the A0 guard `first_g6_use`.

Everything here runs after (or inside) type checking and only looks at typed ASTs; a program without G6 syntax
passes through unchanged."""
import re

from vast import *
from typeinfo import fn_owner, is_collection, contains_collection, type_name
from refine import _kids as expr_kids


def _err(node, code, msg, fix=""):
    raise PruvError("type", node.line, node.col, code, msg, fix, file=getattr(node, "file", None))   # G4: file only in explicit mode


# ---------------------------------------------------------------------------
# catalog (section 10.3): pseudo declarations without bodies, typed through the ordinary generic call path
# ---------------------------------------------------------------------------
def _p(name, ty, take=False):
    p = Param(name, ty)
    if take:
        p.take = True
    return p


def _vec(t):
    return Type("vec", (t,))


def _map(k, v):
    return Type("hashmap", (k, v))


STRING = Type("string")
CATALOG = {}


def _add(name, bounds, build, effects=()):
    owner = fn_owner(name)
    ps = [mk_param(owner, i, n) for i, (n, _) in enumerate(bounds)]
    params, ret = build(*ps)
    f = Function(0, 0, name, params, ret, list(effects), [], [], [])
    f.tparams = [TypeParam(0, 0, n, b) for n, b in bounds]
    CATALOG[name] = f


_T = [("T", None)]
_KV = [("K", "Element"), ("V", None)]
_add("vec_new", _T, lambda T: ([], _vec(T)), ["alloc"])
_add("vec_push", _T, lambda T: ([_p("v", _vec(T), True), _p("x", T)], _vec(T)), ["alloc"])
_add("vec_get", _T, lambda T: ([_p("v", _vec(T)), _p("i", I64)], T))
_add("map_new", _KV, lambda K, V: ([], _map(K, V)), ["alloc"])
_add("map_get", _KV, lambda K, V: ([_p("m", _map(K, V)), _p("k", K)], mk_option(V)))
_add("map_insert", _KV, lambda K, V: ([_p("m", _map(K, V), True), _p("k", K), _p("v", V)], _map(K, V)), ["alloc"])
_add("string_new", [], lambda: ([], STRING), ["alloc"])
_add("string_push_str", [], lambda: ([_p("s", STRING, True), _p("text", STR)], STRING), ["alloc"])
_add("string_byte", [], lambda: ([_p("s", STRING), _p("i", I64)], I64))
_add("string_to_str", [], lambda: ([_p("s", STRING)], STR), ["alloc"])
# contract-only observers
_add("map_lookup", _KV, lambda K, V: ([_p("m", _map(K, V)), _p("k", K)], mk_option(V)))
_add("map_updated", _KV, lambda K, V: ([_p("after", _map(K, V)), _p("before", _map(K, V)), _p("k", K), _p("v", V)],
                                       BOOL))
CATALOG_NAMES = tuple(CATALOG)
CATALOG_CONTRACT_ONLY = ("map_lookup", "map_updated")


# ---------------------------------------------------------------------------
# trusted rust fn declarations (section 10.4)
# ---------------------------------------------------------------------------
_PATH_RE = re.compile(r"::[A-Za-z_][A-Za-z0-9_]*(?:::[A-Za-z_][A-Za-z0-9_]*)*")


def _scalar_opt(t):
    """Option<i64|bool> / Result<i64|bool>"""
    return t.owner is None and t.name in ("option", "result") and (not t.args or t.args[0] in (I64, BOOL))


def _allowed_result(t):
    return t in (I64, BOOL, UNIT) or _scalar_opt(t)


def _allowed_param(t):
    return t in (I64, BOOL, ARRAY, ARRAY_U8, ARRAY_BOOL, STR) or _scalar_opt(t)


class _Pos:
    def __init__(s, line, col):
        s.line, s.col = line, col


def check_foreign_decl(f, externs):
    """signature (foreign_signature), then path (foreign_path) of a trusted rust fn"""
    if f.tparams:
        _err(f, "foreign_signature", "a trusted rust fn cannot be generic",
             "declare one concrete trusted rust fn per type")
    if not _allowed_result(f.ret):
        _err(f, "foreign_signature", "result type %s is not allowed on a trusted rust fn" % type_name(f.ret),
             "return i64, bool, (), Option<i64|bool> or Result<i64|bool>; convert other results in a Rust adapter")
    for p in f.params:
        if p.take:
            _err(f, "foreign_signature", "take parameter %s is not allowed on a trusted rust fn" % p.name,
                 "remove `take`; a foreign function only reads its arguments")
        if contains_collection(p.type):
            _err(f, "foreign_signature", "collection parameter %s is not allowed on a trusted rust fn" % p.name,
                 "pass i64, bool, Option, Result, arrays or str; wrap collections in a Rust adapter")
        if not _allowed_param(p.type):
            _err(f, "foreign_signature", "parameter %s of type %s is not allowed on a trusted rust fn" % (
                p.name, type_name(p.type)),
                 "use i64, bool, Option<i64|bool>, Result<i64|bool>, [i64], [u8], [bool] or str")
    if not f.ensures:
        _err(f, "foreign_signature", "a trusted rust fn needs at least one ensures",
             "add an ensures clause; `ensures true` documents an unconstrained result")
    info = f.foreign
    at = _Pos(info["line"], info["col"])
    path = info["path"]
    if not _PATH_RE.fullmatch(path):
        _err(at, "foreign_path", "invalid Rust path",
             "write the path as ::std::cmp::min: `::` and identifiers only, no expressions, generics or spaces")
    root = path[2:].split("::")[0]
    if root in ("crate", "self", "super"):
        _err(at, "foreign_path", "relative Rust path root",
             "start the path with ::std or the name of a crate given with --rust-extern")
    if root != "std" and root not in externs:
        _err(at, "foreign_path", "Rust crate %s is not supplied" % root,
             "pass --rust-extern %s=PATH or use a ::std path" % root)


# ---------------------------------------------------------------------------
# ownership / liveness (section 10.4)
# State: dict name -> "live" | "dead" | "maybe" for owned collection bindings; None = unreachable path.
# Borrowed (unmarked collection) parameters are kept in self.bor and never change.
# ---------------------------------------------------------------------------
def _join(a, b):
    if a is None:
        return b
    if b is None:
        return a
    return dict((n, v if b[n] == v else "maybe") for n, v in a.items() if n in b)


class _Ownership:
    def __init__(s, funcs):
        s.funcs = funcs
        s.bor = set()
        s.track = None   # name -> "move" | "borrow" of the outermost call being checked (shared by nested calls)

    def run(s, f):
        s.bor = set(p.name for p in f.params if is_collection(p.type) and not p.take)
        s.block(f.body, dict((p.name, "live") for p in f.params if p.take))

    def block(s, stmts, st):
        declared = []
        for x in stmts:
            if st is None:
                break
            st = s.stmt(x, st, declared)
        if st is not None:
            for n in declared:
                st.pop(n, None)
        return st

    def stmt(s, x, st, declared):
        if isinstance(x, Let):
            s.consume(x.value, st, "let")
            if is_collection(x.type):
                st[x.name] = "live"
                declared.append(x.name)
            return st
        if isinstance(x, Assign):
            s.consume(x.value, st, "assign")
            if x.name in st:
                st[x.name] = "live"
            return st
        if isinstance(x, IndexAssign):
            s.expr(x.index, st)
            s.expr(x.value, st)
            return st
        if isinstance(x, FieldAssign):
            s.expr(x.value, st)
            return st
        if isinstance(x, If):
            s.expr(x.cond, st)
            return _join(s.block(x.then, dict(st)), s.block(x.els, dict(st)))
        if isinstance(x, While):
            entry = dict(st)
            s.expr(x.cond, st)
            end = s.block(x.body, dict(st))
            if end is not None:
                for n, v in entry.items():
                    if v == "live" and end.get(n) != "live":
                        _err(x, "foreign_loop_move", "moved in the loop body and not restored",
                             "%s must be live again at the end of every path of the body: reassign it, e.g. "
                             "%s = f(move %s, ..), or do not consume it inside the loop" % (n, n, n))
            return _join(st, end)
        if isinstance(x, Return):
            if x.value is not None:
                s.consume(x.value, st, "return")
            return None
        if isinstance(x, ExprStmt):
            s.expr(x.expr, st)
            return st
        if isinstance(x, Match):
            s.expr(x.scrutinee, st)
            out = None
            first = True
            for a in x.arms:
                r = s.block(a.body, dict(st))
                out = r if first else _join(out, r)
                first = False
            return out
        return st   # Assert: contract, not subject to liveness

    # ---- uses ----
    def use(s, e, st):
        v = st.get(e.name)
        if v == "dead":
            _err(e, "foreign_move", "use after move",
                 "%s was moved earlier; reassign it before using it again, or avoid the move" % e.name)
        if v == "maybe":
            _err(e, "foreign_move", "binding may have been moved",
                 "%s is moved on some paths; make every path leave it live, or do not use it afterwards" % e.name)

    def move(s, e, st, consuming, track):
        if not is_collection(e.ty):
            _err(e, "foreign_move", "move of a non-collection value",
                 "move applies to Vec, HashMap and String bindings only; use the value directly")
        n = e.name
        if track is not None and n in track:
            if track[n] == "move":
                _err(e, "foreign_move", "consumed twice", "consume %s at most once per call" % n)
            _err(e, "foreign_borrow", "borrowed and moved in one call",
                 "do not pass %s both read-only and with move in one call" % n)
        s.use(e, st)
        if not consuming:
            _err(e, "foreign_move", "move only where ownership is consumed",
                 "use move for a take argument, a let initializer, an assignment or return")
        if n in s.bor:
            _err(e, "foreign_move", "moving a borrowed parameter",
                 "%s is a read parameter; declare it `take %s: ...` to consume it" % (n, n))
        st[n] = "dead"
        if track is not None:
            track[n] = "move"

    def consume(s, e, st, pos):
        """let initializer / assignment / return value"""
        if isinstance(e, Move):
            s.move(e, st, True, None)
        elif isinstance(e, Var) and is_collection(e.ty):
            s.use(e, st)
            if e.name in s.bor:
                if pos == "return":
                    _err(e, "foreign_borrow", "borrowed return", "%s is a read parameter; declare it `take`" % e.name)
                _err(e, "foreign_borrow", "borrowed alias", "%s is a read parameter and cannot be aliased" % e.name)
            if pos == "return":
                _err(e, "foreign_move", "returning an owned binding without move", "write return move %s;" % e.name)
            _err(e, "foreign_move", "alias of an owned binding without move", "write move %s" % e.name)
        else:
            s.expr(e, st)

    # ---- expressions ----
    def expr(s, e, st):
        if isinstance(e, Var):
            if is_collection(e.ty):
                s.use(e, st)
        elif isinstance(e, Move):
            s.move(e, st, False, None)
        elif isinstance(e, Call):
            s.call(e, st)
        elif isinstance(e, Binary) and e.op in ("&&", "||"):
            s.expr(e.left, st)
            before = dict(st)
            s.expr(e.right, st)
            joined = _join(before, st)      # the right operand runs conditionally
            st.clear()
            st.update(joined)
        else:
            for k in expr_kids(e):
                s.expr(k, st)

    def call(s, e, st):
        f = CATALOG.get(e.name) or s.funcs.get(e.name)
        takes = [bool(p.take) for p in f.params] if f is not None else [False] * len(e.args)
        outer = s.track
        track = outer if outer is not None else {}   # nested calls share the outermost call's track (R1)
        s.track = track
        try:
            s.call_args(e, st, takes, track)
        finally:
            s.track = outer

    def call_args(s, e, st, takes, track):
        for arg, take in zip(e.args, takes):
            if take:
                if isinstance(arg, Move):
                    s.move(arg, st, True, track)
                elif isinstance(arg, Var) and is_collection(arg.ty):
                    s.use(arg, st)
                    if arg.name in s.bor:
                        _err(arg, "foreign_move", "moving a borrowed parameter",
                             "%s is a read parameter; declare it `take %s: ...` to consume it" % (arg.name, arg.name))
                    _err(arg, "foreign_move", "missing move in a consuming argument",
                         "write move %s" % arg.name)
                else:
                    s.expr(arg, st)
            elif isinstance(arg, Move):
                s.move(arg, st, False, track)
            elif isinstance(arg, Var) and is_collection(arg.ty):
                if track.get(arg.name) == "move":
                    _err(arg, "foreign_borrow", "borrowed and moved in one call",
                         "do not pass %s both read-only and with move in one call" % arg.name)
                s.use(arg, st)
                track.setdefault(arg.name, "borrow")
            else:
                s.expr(arg, st)


def check_ownership(f, funcs):
    """ownership/liveness of one typed, non-foreign function; funcs: name -> Function of the program"""
    _Ownership(funcs).run(f)


# ---------------------------------------------------------------------------
# A0 guard (section 10.5)
# ---------------------------------------------------------------------------
def _g6_candidates(node, out):
    if isinstance(node, list):
        for x in node:
            _g6_candidates(x, out)
        return
    if not hasattr(node, "__dataclass_fields__") or isinstance(node, Type):
        return
    if isinstance(node, Let) and contains_collection(node.type):
        out.append((node.line, node.col, "a collection local"))
    elif isinstance(node, Move):
        out.append((node.line, node.col, "move"))
    elif isinstance(node, Call) and node.ty is not None and contains_collection(node.ty):
        out.append((node.line, node.col, "a collection value"))
    for fname in node.__dataclass_fields__:
        _g6_candidates(getattr(node, fname), out)


def first_g6_use(prog):
    """first G6 construct of a checked program -> (line, col, what) or None. Source order: functions in order,
    the signature (foreign declaration, take or collection parameter/result) before the body."""
    for f in prog.functions:
        if f.foreign is not None:
            return (f.line, f.col, "trusted rust fn %s" % f.name)
        for p in f.params:
            if p.take or contains_collection(p.type):
                return (f.line, f.col, "parameter %s" % p.name)
        if contains_collection(f.ret):
            return (f.line, f.col, "result type of %s" % f.name)
        cands = []
        _g6_candidates(f.body, cands)
        if cands:
            return min(cands, key=lambda c: (c[0], c[1]))
    return None


def g6_unimplemented_error(prog, stage="codegen"):
    """PruvError (unsupported_type) for the first G6 construct, or None. Run right after type checking."""
    hit = first_g6_use(prog)
    if hit is None:
        return None
    line, col, _what = hit
    return PruvError(stage, line, col, "unsupported_type",
                     "G6 foreign calls and collections are not implemented by the llvm codegen layer yet",
                     "avoid trusted rust fn, Vec, HashMap, String, take and move for now")
