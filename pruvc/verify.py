"""Pruv verifier: symbolic execution + z3. Proves bounds, overflow, contracts, loops."""
import time
import z3
from vast import *
from typeinfo import (TypeTable, is_array, array_elem, array_of, bind_args, substitute, decl_owner, format_type,
                      is_collection)
from foreign import CATALOG, CATALOG_NAMES, FILE, FILE_OBSERVERS

I64_MIN, I64_MAX = -2 ** 63, 2 ** 63 - 1
MAX_LEN = 2 ** 40
TIMEOUT_MS = 8000

_o = z3.Datatype("Opt"); _o.declare("some", ("sval", z3.IntSort())); _o.declare("none")
_r = z3.Datatype("Res"); _r.declare("ok", ("oval", z3.IntSort())); _r.declare("err", ("eval", z3.IntSort()))
Opt, Res = z3.CreateDatatypes(_o, _r)


class _OptOps:
    """the z3 operations of one Option datatype (legacy Opt, or a G3 instance Option<X>)"""
    __slots__ = ("some", "none", "is_some", "is_none", "sval")

    def __init__(s, some, none, is_some, is_none, sval):
        s.some, s.none, s.is_some, s.is_none, s.sval = some, none, is_some, is_none, sval


class _ResOps:
    """the z3 operations of one Result datatype (legacy Res, or a G3 instance Result<X>)"""
    __slots__ = ("ok", "err", "is_ok", "is_err", "oval", "eval")

    def __init__(s, ok, err, is_ok, is_err, oval, eval_):
        s.ok, s.err, s.is_ok, s.is_err, s.oval, s.eval = ok, err, is_ok, is_err, oval, eval_


# the legacy datatypes go through the very same z3 functions as before, so G3-free SMT text is unchanged
_OPT = _OptOps(Opt.some, Opt.none, Opt.is_some, Opt.is_none, Opt.sval)
_RES = _ResOps(Res.ok, Res.err, Res.is_ok, Res.is_err, Res.oval, Res.eval)


def arr_type(elem):
    """array Type holding elem (legacy constants for i64/u8/bool, a structured [T] for an abstract element)"""
    t = array_of(elem)
    return t if t is not None else mk_array(elem)

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


class BudgetExhausted(Exception):
    """STAGE1 B2: the per-function exploration query budget is used up (infer.py catches it)"""


class InferenceTimeout(Exception):
    """STAGE1 B2: wall-clock safety limit (function start + 5 s) during exploration, or an exploration query hitting
    z3's own 500 ms limit (reason exactly "timeout"); rlimit exhaustion ("canceled" etc.) only drops the candidate
    (infer.py catches it)"""


class Probe:
    """STAGE1 B2 exploration state of one function (shared by all its rounds).
    queries: attempts made so far (budget counter); failed: this round's failed candidates
    {cand id: (obligation code, attempt status)} in the order they failed."""

    def __init__(s, max_queries, deadline):
        s.max_queries, s.deadline = max_queries, deadline
        s.queries = 0
        s.failed = {}

    def begin_round(s):
        s.failed = {}

    def tick(s):
        """called before every attempt: budget first, then the wall clock, then count the attempt"""
        if s.queries >= s.max_queries:
            raise BudgetExhausted()
        if time.monotonic() > s.deadline:
            raise InferenceTimeout()
        s.queries += 1

    def fail(s, cand, code, status):
        s.failed[cand] = (code, status)


def walk_loops(stmts):
    """(While, block, index in block) for every loop, preorder: statements in order, a While before its body,
    If then -> els, Match arms in order (STAGE1 B2 loop numbering = position in this sequence)"""
    for i, st in enumerate(stmts):
        if isinstance(st, While):
            yield st, stmts, i
            for x in walk_loops(st.body):
                yield x
        elif isinstance(st, If):
            for x in walk_loops(st.then):
                yield x
            for x in walk_loops(st.els):
                yield x
        elif isinstance(st, Match):
            for a in st.arms:
                for x in walk_loops(a.body):
                    yield x


class TraceRecorder:
    """official query-recording boundary: one entry per obligation, one attempt per solver check"""

    def __init__(s):
        s.obligations = []

    def begin(s, fn, node, code, skipped, phase, round_, cand, file=None):
        entry = {"seq": len(s.obligations), "fn": fn, "line": node.line, "col": node.col, "code": code,
                 "attempts": [], "phase": phase, "round": round_, "cand": cand}
        if file is not None:        # G4 A1: explicit mode only; legacy entries keep their exact key set
            entry["file"] = file
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
        # G3 A2: generic declarations are instantiated lazily, one datatype per complete structural type
        s.pre = pre
        s.fn_index = {f.name: i for i, f in enumerate(prog.functions)}
        s.gcount = 0
        s.ginst = {}        # Type (Option<X>, Result<X>, D<..>) -> z3 sort
        s.gopt, s.gres = {}, {}
        s.gstruct, s.genum = {}, {}
        s.abstract = {}     # (owner, index) -> uninterpreted sort of a function type parameter
        s.abs_name = {}     # sort name -> type-parameter spelling (counterexample rendering)
        s.short = {}        # constructor name of a generic Option/Result instance -> source name
        # G9 A1: recursive nominal type SCCs (one simultaneous datatype each), buffer-field datatypes, and the lazily
        # built recursive wf/size definitions. All of it is empty/unused for a program without a G9 feature.
        meta = getattr(prog, "g9", None)
        s.g9 = meta is not None
        s.scc_of = {}       # recursive type name -> member names of its SCC (declaration order)
        s.recrel = set()    # names of non-generic types that are recursive or (transitively) contain a recursive type
        s.bufs = {}         # "int" | "bool" -> (sort, constructor, length accessor, array accessor)
        s.buf_names = set()
        s.size_f, s.wf_f, s.fixed_memo = {}, {}, {}
        if meta is not None:
            pindex = {}
            for i, d in enumerate(prog.types):
                pindex.setdefault(d.name, i)
            for names in meta["type_sccs"]:
                mem = sorted(names, key=lambda n: pindex[n])
                for n in mem:
                    s.scc_of[n] = mem
            s.recrel = set(s.scc_of)
            changed = bool(s.recrel)
            while changed:
                changed = False
                for d in s.tt.decls.values():
                    if d.name not in s.recrel and not d.tparams and any(n in s.recrel for n in s.tt._deps(d)):
                        s.recrel.add(d.name)
                        changed = True
        s.idx_of = {d.name: i for i, d in enumerate(s.tt.order)}
        s.done = set()
        for d in s.tt.order:
            s._build(d.name)

    def _build(s, name):
        """create the datatype of `name` (its whole recursive SCC at once), dependencies first. For a program
        without recursive types this visits the declarations in tt.order exactly like the old loop."""
        if name in s.done:
            return
        d = s.tt.decls[name]
        group = s.scc_of.get(name) or [name]
        for n in group:
            s.done.add(n)
        if d.tparams:
            return      # generic declarations are instantiated lazily
        members = [s.tt.decls[n] for n in group]
        for mdecl in members:
            for dep in s.tt._deps(mdecl):
                if dep not in group:
                    s._build(dep)
        s._make_group(members)

    def _make_group(s, members):
        gdt = {}
        dts = []
        for d in members:
            tag = "%st%d!" % (s.pre, s.idx_of[d.name])
            dt = z3.Datatype(tag + d.name)
            gdt[d.name] = dt
            dts.append((d, tag, dt))

        def fsort(ft):
            # a field of a member type refers to the datatype under construction (z3 simultaneous declaration)
            if ft.owner is None and not ft.args and ft.name in gdt:
                return gdt[ft.name]
            return s.sort_of(ft)
        for d, tag, dt in dts:
            if isinstance(d, StructDecl):
                dt.declare(tag + d.name, *[(tag + d.name + "." + fd.name, fsort(fd.type)) for fd in d.fields])
            else:
                for v in d.variants:
                    cn = tag + d.name + "::" + v.name
                    dt.declare(cn, *[(cn + "." + fd.name, fsort(fd.type)) for fd in v.fields])
        srts = z3.CreateDatatypes(*[dt for _, _, dt in dts])
        for (d, tag, dt), srt in zip(dts, srts):
            if isinstance(d, StructDecl):
                s.struct[d.name] = (srt.constructor(0), [srt.accessor(0, j) for j in range(len(d.fields))])
            else:
                s.enum[d.name] = {}
                for i, v in enumerate(d.variants):
                    s.enum[d.name][v.name] = (srt.constructor(i), srt.recognizer(i),
                                              [srt.accessor(i, j) for j in range(len(v.fields))])
            s.sorts[d.name] = srt
            s.by_sort[srt.name()] = Type(d.name)

    # ---------- G9 A1: buffer fields ----------
    @staticmethod
    def is_buf(ty):
        """a [i64] / [u8] / [bool] / str field type (never a G3 [T])"""
        return ty.owner is None and not ty.args and ty.name in ("array", "array_u8", "array_bool", "str")

    @staticmethod
    def buf_elem(ty):
        return BOOL if ty.name == "array_bool" else U8 if ty.name in ("array_u8", "str") else I64

    def bufsort(s, ty):
        """datatype Buf(len: Int, arr: Array(Int, elem sort)); one per element sort (Int for i64/u8/str, Bool)"""
        key = "bool" if ty.name == "array_bool" else "int"
        ent = s.bufs.get(key)
        if ent is None:
            tag = "%sbuf!%s" % (s.pre, key)
            dt = z3.Datatype(tag)
            esort = z3.BoolSort() if key == "bool" else z3.IntSort()
            dt.declare(tag + ".mk", (tag + ".len", z3.IntSort()), (tag + ".arr", z3.ArraySort(z3.IntSort(), esort)))
            srt = dt.create()
            ent = (srt, srt.constructor(0), srt.accessor(0, 0), srt.accessor(0, 1))
            s.bufs[key] = ent
            s.buf_names.add(srt.name())
        return ent[0]

    def field_get(s, fty, term, name="field"):
        """adapt a stored field value to the verifier's own model: a buffer field becomes an Arr"""
        if not s.is_buf(fty):
            return term
        s.bufsort(fty)
        ent = s.bufs["bool" if fty.name == "array_bool" else "int"]
        return mk_arr(ent[3](term), ent[2](term), name, s.buf_elem(fty))

    def field_put(s, fty, val):
        """inverse of field_get: an Arr stored into a buffer field becomes a Buf value"""
        if not (s.is_buf(fty) and isinstance(val, Arr)):
            return val
        s.bufsort(fty)
        return s.bufs["bool" if fty.name == "array_bool" else "int"][1](val.n, val.a)

    # ---------- G9 A1: structural size and well-formedness of recursive values ----------
    def rel(s, ty):
        return ty.owner is None and not ty.args and ty.name in s.recrel

    def size_fn(s, name):
        """size_D as an uninterpreted z3 function (one-step equations come from facts(); all members of the SCC of D are declared first, then defined together)"""
        f = s.size_f.get(name)
        if f is not None:
            return f
        group = s.scc_of.get(name) or [name]
        for n in group:
            s.size_f[n] = z3.Function("%ssize!%s" % (s.pre, n), s.sorts[n], z3.IntSort())
        return s.size_f[name]

    def weight(s, fty, t):
        """size weight of a field value t of type fty (None = always 0): nominal values count their own size,
        Some/Ok payloads count their payload, everything else is 0"""
        if fty.owner is not None or fty in (I64, BOOL, OPTION, RESULT) or s.is_buf(fty) or is_collection(fty):
            return None
        if fty.name == "option":
            o = s.opt(fty)
            w = s.weight(fty.args[0], o.sval(t))
            return None if w is None else z3.If(o.is_some(t), w, 0)
        if fty.name == "result":
            o = s.res(fty)
            w = s.weight(fty.args[0], o.oval(t))
            return None if w is None else z3.If(o.is_ok(t), w, 0)
        if s.tt.is_struct(fty) or s.tt.is_enum(fty):
            if not fty.args:
                return s.size_fn(fty.name)(t)
            k = s.fixed_size(fty)
            if k is not None:
                return z3.IntVal(k)          # value-independent size: a constant (no function over a huge finite sort)
            return s.size_inst(fty)(t)       # admitted acyclic G3 application: its own uninterpreted size
        return None

    def fixed_size(s, ty):
        """the size of every value of the user type ty when it does not depend on the value (a struct whose fields are
        all scalars, buffers, collections or such structs), else None. Memoized per structural type, so a nested
        generic application costs one computation per level. z3 is very slow on an uninterpreted function over a deep
        nested finite datatype sort, so such sizes are never left to a function."""
        memo = s.fixed_memo
        if ty in memo:
            return memo[ty]
        memo[ty] = None      # an in-progress (cyclic) type is never fixed
        k = None
        if s.tt.is_struct(ty):
            k = 1
            for _, fty in s.fields_of(ty):
                if fty.owner is not None or fty in (I64, BOOL) or s.is_buf(fty) or is_collection(fty):
                    continue
                if fty in (OPTION, RESULT) or fty.name in ("option", "result") or not s.tt.is_struct(fty):
                    k = None
                    break
                c = s.fixed_size(fty)
                if c is None:
                    k = None
                    break
                k += c
        memo[ty] = k
        return k

    def size_inst(s, ty):
        """size of an admitted acyclic generic application D<X..> as an uninterpreted z3 function per instance
        sort; its one-step equation comes from facts() on observed terms only (never a full value expansion)"""
        srt = s.instance(ty)
        f = s.size_f.get(srt.name())
        if f is None:
            f = s.size_f[srt.name()] = z3.Function("%ssize!%s" % (s.pre, srt.name()), srt, z3.IntSort())
        return f

    def size_sum(s, ty, variant, accs, t):
        total = z3.IntVal(1)
        for (fd, fty), acc in zip(s.fields_of(ty, variant), accs):
            w = s.weight(fty, s.field_get(fty, acc(t), fd.name))
            if w is not None:
                total = total + w
        return total

    def size_value(s, ty, t):
        """one step of size: 1 + the weights of the active constructor's fields"""
        if s.tt.is_struct(ty):
            return s.size_sum(ty, None, s.struct_info(ty)[1], t)
        infos = s.enum_info(ty)
        body = None
        for v in reversed(s.tt.decl(ty).variants):
            _, rec, accs = infos[v.name]
            val = s.size_sum(ty, v.name, accs, t)
            body = val if body is None else z3.If(rec(t), val, body)
        return body

    def wf_fn(s, name):
        """wf_D (recursive types only) as an uninterpreted z3 function over the SCC of D"""
        f = s.wf_f.get(name)
        if f is not None:
            return f
        group = s.scc_of[name]
        for n in group:
            s.wf_f[n] = z3.Function("%swf!%s" % (s.pre, n), s.sorts[n], z3.BoolSort())
        return s.wf_f[name]

    def facts(s, ty, t):
        """valid facts about one observed term t of the non-generic nominal type ty (see tests/g9/model_notes.md):
        size positivity, the one-step size equation, for a recursive type the one-step wf equation, and positivity
        of the size of every direct nominal child (so child-smaller follows from the equation)."""
        n = ty.name
        sf = s.size_fn(n)
        out = [sf(t) >= 1, sf(t) == s.size_value(ty, t)]
        if n in s.scc_of:
            body = _wf_step(s, ty, t)
            out.append(s.wf_fn(n)(t) == (z3.BoolVal(True) if body is None else body))
        d = s.tt.decls[n]
        if isinstance(d, StructDecl):
            groups = [(None, s.struct_info(ty)[1])]
        else:
            groups = [(v.name, s.enum_info(ty)[v.name][2]) for v in d.variants]
        for vname, accs in groups:
            for (fd, fty), acc in zip(s.fields_of(ty, vname), accs):
                if s.rel_nominal(fty):
                    out.append(s.size_fn(fty.name)(acc(t)) >= 1)
                elif fty.owner is None and fty.args and s.is_user(fty) and s.fixed_size(fty) is None:
                    out.append(s.size_inst(fty)(acc(t)) >= 1)
        return out

    def rel_nominal(s, ty):
        """a plain non-generic user struct/enum type"""
        return ty.owner is None and not ty.args and ty.name in s.tt.decls and not s.tt.decls[ty.name].tparams

    def is_user(s, ty):
        return ty.owner is None and ty.name in s.tt.decls

    def sort_of(s, ty):
        if ty == I64:
            return z3.IntSort()
        if ty == BOOL:
            return z3.BoolSort()
        if s.is_buf(ty):        # G9 A1: a buffer field of a struct/enum
            return s.bufsort(ty)
        if ty == OPTION:
            return Opt
        if ty == RESULT:
            return Res
        if ty.owner is not None:
            return s.abstract_sort(ty)
        if not ty.args:
            return s.sorts[ty.name]
        return s.instance(ty)

    # ---------- G3 A2: abstract sorts and generic datatype instances ----------
    def abstract_sort(s, ty):
        """fresh uninterpreted sort g3!<function-declaration-index>!T<i> of a function type parameter"""
        key = (ty.owner, ty.index)
        srt = s.abstract.get(key)
        if srt is None:
            fname = ty.owner[3:] if ty.owner.startswith("fn:") else ty.owner
            name = "g3!%s!T%d" % (s.fn_index.get(fname, fname), ty.index)
            srt = z3.DeclareSort(name)
            s.abstract[key] = srt
            s.abs_name[name] = ty.name
        return srt

    def wf_trivial(s, ty):
        """G3: True when well_formed(ty, v) is None for every v (no i64 leaf and no Result error code inside).
        Cached per type, so the check is linear in the size of the type."""
        cache = s.__dict__.setdefault("_wf_triv", {})
        r = cache.get(ty)
        if r is not None:
            return r
        if ty == I64 or ty == OPTION or ty == RESULT or ty.name == "result":
            r = False
        elif ty.owner is not None:
            r = True
        elif ty.name == "option":
            r = s.wf_trivial(ty.args[0])
        elif ty.owner is None and not ty.args and ty.name in s.scc_of:
            r = False       # G9 A1: a recursive type has the wf_D definition (never trivially true here)
        elif s.tt.is_struct(ty):
            r = all(s.wf_trivial(ft) for fd, ft in s.fields_of(ty))
        elif s.tt.is_enum(ty):
            r = all(s.wf_trivial(ft) for vd in s.tt.decl(ty).variants for fd, ft in s.fields_of(ty, vd.name))
        else:
            r = True
        cache[ty] = r
        return r

    def fields_of(s, ty, variant=None):
        """[(FieldDecl, field type)] with the type arguments of ty substituted into the declared field types"""
        d = s.tt.decl(ty)
        flds = s.tt.fields(ty, variant)
        if not d.tparams:
            return [(fd, fd.type) for fd in flds]
        m = bind_args(decl_owner(ty.name), len(d.tparams), ty.args)
        return [(fd, substitute(fd.type, m)) for fd in flds]

    def instance(s, ty):
        """datatype of Option<X> / Result<X> / D<X..>, built once per complete structural type"""
        srt = s.ginst.get(ty)
        if srt is not None:
            return srt
        s.gcount += 1
        tag = "%sg%d!" % (s.pre, s.gcount)
        dt = z3.Datatype(tag + format_type(ty))
        if ty.name == "option":
            ps = s.sort_of(ty.args[0])
            dt.declare(tag + "Some", (tag + "Some.val", ps))
            dt.declare(tag + "None")
            srt = dt.create()
            s.gopt[ty] = _OptOps(srt.constructor(0), srt.constructor(1)(), srt.recognizer(0), srt.recognizer(1),
                                 srt.accessor(0, 0))
            s.short[tag + "Some"], s.short[tag + "None"] = "Some", "None"
        elif ty.name == "result":
            ps = s.sort_of(ty.args[0])
            dt.declare(tag + "Ok", (tag + "Ok.val", ps))
            dt.declare(tag + "Err", (tag + "Err.val", z3.IntSort()))
            srt = dt.create()
            s.gres[ty] = _ResOps(srt.constructor(0), srt.constructor(1), srt.recognizer(0), srt.recognizer(1),
                                 srt.accessor(0, 0), srt.accessor(1, 0))
            s.short[tag + "Ok"], s.short[tag + "Err"] = "Ok", "Err"
        else:
            d = s.tt.decls[ty.name]
            if isinstance(d, StructDecl):
                fl = [(tag + d.name + "." + fd.name, s.sort_of(ft)) for fd, ft in s.fields_of(ty)]
                dt.declare(tag + d.name, *fl)
                srt = dt.create()
                s.gstruct[ty] = (srt.constructor(0), [srt.accessor(0, j) for j in range(len(fl))])
            else:
                for v in d.variants:
                    cn = tag + d.name + "::" + v.name
                    dt.declare(cn, *[(cn + "." + fd.name, s.sort_of(ft)) for fd, ft in s.fields_of(ty, v.name)])
                srt = dt.create()
                s.genum[ty] = {}
                for i, v in enumerate(d.variants):
                    s.genum[ty][v.name] = (srt.constructor(i), srt.recognizer(i),
                                           [srt.accessor(i, j) for j in range(len(v.fields))])
        s.ginst[ty] = srt
        s.by_sort[srt.name()] = ty
        return srt

    def opt(s, ty):
        """operations of the Option datatype of ty (None / Option<i64> = the legacy one)"""
        if ty is None or ty == OPTION:
            return _OPT
        s.instance(ty)
        return s.gopt[ty]

    def res(s, ty):
        if ty is None or ty == RESULT:
            return _RES
        s.instance(ty)
        return s.gres[ty]

    def struct_info(s, ty):
        """(constructor, [accessor per field]) of a struct type"""
        if not ty.args:
            return s.struct[ty.name]
        s.instance(ty)
        return s.gstruct[ty]

    def enum_info(s, ty):
        """{variant: (constructor, recognizer, [accessor per field])} of an enum type"""
        if not ty.args:
            return s.enum[ty.name]
        s.instance(ty)
        return s.genum[ty]

    def type_of(s, v):
        """Pruv Type of a z3 datatype value (Opt/Res/user), or None"""
        if isinstance(v, File):
            return FILE
        if isinstance(v, Map):      # G6 A1
            return Type("hashmap", (v.kty, v.vty))
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
        return e.name in _TAG_FNS or e.name == "file_byte"
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
    __slots__ = ("a", "n", "name", "elem")

    def __init__(s, a, n, name, elem):
        s.a, s.n, s.name, s.elem = a, n, name, elem


def mk_arr(a, n, name, elem):
    """The only place an Arr is built; elem is the element Type (I64 / U8 / BOOL). Pure: touches no counter."""
    return Arr(a, n, name, elem)


class Map:
    """G6 A1 (G6_SPEC 11.2): a HashMap<K, V> value: membership d: Array(Sort(K), Bool), payload a: Array(Sort(K),
    Sort(V)), size n. kty/vty are the Pruv key/value types."""
    __slots__ = ("d", "a", "n", "name", "kty", "vty")

    def __init__(s, d, a, n, name, kty, vty):
        s.d, s.a, s.n, s.name, s.kty, s.vty = d, a, n, name, kty, vty


class File:
    """G10: three independent Bool fields and a String-shaped byte buffer (size, map)."""
    __slots__ = ("ok", "readable", "writable", "buf")

    def __init__(s, ok, readable, writable, buf):
        s.ok, s.readable, s.writable, s.buf = ok, readable, writable, buf


_COLL = ("vec", "hashmap", "string", "file")
_STRING = Type("string")


class State:
    def __init__(s, env, pc):
        s.env, s.pc = env, pc
        s.obs = frozenset()     # G9 A1: ids of the recursive-value facts already in pc (immutable, shared by forks)

    def fork(s, extra=None):
        n = State(dict(s.env), s.pc + ([extra] if extra is not None else []))
        n.obs = s.obs
        return n


def _wf_of(m, ty, v):
    """well_formed(ty, v): every active leaf is an i64. None when trivially true. m: the Model.
    G9 A1: a recursive nominal type is the application of its wf_D definition; a buffer field (v is an Arr
    adapted by Model.field_get) has 0 <= len <= 2^40 and, for u8/str, the byte domain."""
    if ty == I64:
        return in_range(v)
    if isinstance(v, Arr) and m.is_buf(ty):
        ln = z3.And(v.n >= 0, v.n <= MAX_LEN)
        return z3.And(ln, u8_dom(v)) if v.elem == U8 else ln
    if ty == FILE:
        return z3.And(v.buf.n >= 0, u8_dom(v.buf))
    if ty.owner is None and ty.name in _COLL:     # G6 A1: 0 <= n <= MAX_LEN (and the u8 domain of a String)
        ln = z3.And(v.n >= 0, v.n <= MAX_LEN)
        return z3.And(ln, u8_dom(v)) if ty.name == "string" else ln
    if ty == OPTION:
        return z3.Implies(Opt.is_some(v), in_range(Opt.sval(v)))
    if ty == RESULT:
        return z3.And(z3.Implies(Res.is_ok(v), in_range(Res.oval(v))),
                      z3.Implies(Res.is_err(v), in_range(Res.eval(v))))
    if ty.owner is not None:        # G3: an abstract value has no well-formedness predicate
        return None
    if ty.args and m.wf_trivial(ty):
        # G3: no constrained leaf anywhere inside (e.g. Dup<Dup<T>>); create the datatype as the full walk would,
        # but skip the field recursion, which is exponential in the nesting depth
        if ty.name == "option":
            m.opt(ty)
        elif m.tt.is_struct(ty):
            m.struct_info(ty)
        elif m.tt.is_enum(ty):
            for vd in m.tt.decl(ty).variants:
                m.enum_info(ty)[vd.name]
        return None
    if ty.name == "option":         # G3: Option<X>, X other than i64
        o = m.opt(ty)
        w = _wf_of(m, ty.args[0], o.sval(v))
        return None if w is None else z3.Implies(o.is_some(v), w)
    if ty.name == "result":
        o = m.res(ty)
        w = _wf_of(m, ty.args[0], o.oval(v))
        parts = [] if w is None else [z3.Implies(o.is_ok(v), w)]
        parts.append(z3.Implies(o.is_err(v), in_range(o.eval(v))))
        return _conj(parts)
    if not ty.args and ty.name in m.scc_of:     # G9 A1: recursive type: the definition, never a Python expansion
        return m.wf_fn(ty.name)(v)
    return _wf_step(m, ty, v)


def _wf_step(m, ty, v):
    """one structural step of well_formed for a struct/enum type (the fields are checked with _wf_of)"""
    if m.tt.is_struct(ty):
        accs = m.struct_info(ty)[1]
        return _conj([_wf_of(m, ft, m.field_get(ft, acc(v), fd.name))
                      for (fd, ft), acc in zip(m.fields_of(ty), accs)])
    if m.tt.is_enum(ty):
        parts = []
        for vd in m.tt.decl(ty).variants:
            _, rec, accs = m.enum_info(ty)[vd.name]
            w = _conj([_wf_of(m, ft, m.field_get(ft, acc(v), fd.name))
                       for (fd, ft), acc in zip(m.fields_of(ty, vd.name), accs)])
            if w is not None:
                parts.append(z3.Implies(rec(v), w))
        return _conj(parts)
    return None


def _expr_text(e):
    """source-like text of a contract expression (used to name measures in messages)"""
    if isinstance(e, IntLit):
        return str(e.value)
    if isinstance(e, BoolLit):
        return "true" if e.value else "false"
    if isinstance(e, Var):
        return e.name
    if isinstance(e, Unary):
        return e.op + _expr_text(e.operand)
    if isinstance(e, Binary):
        def side(x):
            return "(%s)" % _expr_text(x) if isinstance(x, Binary) else _expr_text(x)
        return "%s %s %s" % (side(e.left), e.op, side(e.right))
    if isinstance(e, Call):
        return "%s(%s)" % (e.name, ", ".join(_expr_text(a) for a in e.args))
    if isinstance(e, Index):
        return "%s[%s]" % (_expr_text(e.array), _expr_text(e.index))
    if isinstance(e, FieldAccess):
        return "%s.%s" % (_expr_text(e.base), e.field)
    if isinstance(e, Ctor):
        return e.name if e.arg is None else "%s(%s)" % (e.name, _expr_text(e.arg))
    if isinstance(e, Quant):
        return "%s(%s in %s..%s: %s)" % (e.kind, e.var, _expr_text(e.lo), _expr_text(e.hi), _expr_text(e.body))
    if isinstance(e, IsVariant):
        return "is_variant(%s, %s::%s)" % (_expr_text(e.value), e.enum_name, e.variant)
    if isinstance(e, VariantField):
        return "variant_field(%s, %s::%s, %s)" % (_expr_text(e.value), e.enum_name, e.variant, e.field)
    return "..."


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


def u8_dom(arr):
    """G2 A2: every element of a U8 symbolic array is in 0..=255 (bound variable `elem!k`, fixed name, no counter)."""
    k = z3.Int("elem!k")
    A = arr.a
    return z3.ForAll([k], z3.Implies(z3.And(k >= 0, k < arr.n),
                                     z3.And(z3.Select(A, k) >= 0, z3.Select(A, k) <= 255)))


def str_boundary(arr, i):
    """G2 B1 (G2_SPEC 4.4): i is a UTF-8 character boundary of byte array arr (total, no domain)."""
    b = z3.Select(arr.a, i)
    return z3.Or(i == 0, i == arr.n, z3.And(i > 0, i < arr.n, z3.Or(b < 128, b >= 192)))


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
    "recursive_nonneg": "the decreases measure must be >= 0 at function entry and at every recursive call; add a requires, or guard the call with an if/match",
    "recursive_decrease": "the callee's measure must be strictly smaller than the caller's entry measure: recurse on a smaller argument (a child of a match binder, an index one closer to the end), or fix the measure",
    "variant_domain": "guard the lookup so it is only reached for that variant, e.g. `is_variant(e, E::V) && variant_field(e, E::V, f) > 0` or `!is_variant(e, E::V) || ...`",
    "contract_domain": "guard the partial operation earlier in the same contract or in an earlier clause: index range, divisor != 0, is_some/is_ok before some_val/ok_val/err_val, lo < hi before max/min",
    "elem_range": "store or fill only values in 0..=255 into a [u8] array: bound the value with requires, an if, or a loop invariant",
    "string_slice_range": "keep 0 <= lo <= hi <= len(s) for substr(s, lo, hi): bound lo and hi with requires, an if, or a loop invariant (a counterexample str may not be valid UTF-8)",
    "utf8_boundary": "cut a str only at character boundaries: require or check is_char_boundary(s, lo) and is_char_boundary(s, hi) (a counterexample str may not be valid UTF-8)",
}


class FnVerifier:
    def __init__(s, prog, f, errors, model=None, rec=None, qcfg=None, extra=None, probe=None):
        s.rec = rec
        s.qcfg = qcfg if qcfg is not None else QueryConfig()
        # STAGE1 B2: extra = {loop number: [(cand id, expr, text)]} (inferred invariants); probe = exploration
        # state (only candidate obligations are queried, nothing is reported). Both empty = the old path.
        s.extra = extra or {}
        s.probe = probe
        s.loop_no = {id(w): n for n, (w, _, _) in enumerate(walk_loops(f.body))} if s.extra else {}
        s.funcs = {g.name: g for g in prog.functions}
        s.explicit = bool(prog.explicit)    # G4 A1
        s.model = model if model is not None else Model(prog)
        s.f, s.errors = f, errors
        s.k = 0
        s.seen = set()
        s.qstack = []
        s.aggs = {}
        s.lemmas = []
        s.lemma_keys = set()
        s.theta = {}        # G3 A2: callee type-parameter substitution while a callee contract is re-interpreted
        s._opq = {}
        # G9 A1: function SCCs (Program.g9) and the frozen entry value of this function's decreases measure
        meta = getattr(prog, "g9", None)
        s.scc_id = {}
        if meta is not None:
            for i, names in enumerate(meta["fn_sccs"]):
                for n in names:
                    s.scc_id[n] = i
        s.m0 = None
        s._cex_m = None
        # G5 A1: immutable entry snapshots {inout parameter name: entry array}; separate from the current environment.
        # Empty for a function without inout parameters.
        s.snap = {}

    def T(s, ty):
        """type of a checked node under the current contract-instantiation substitution"""
        if ty is not None and s.theta:
            return substitute(ty, s.theta)
        return ty

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
        if ty == STR:   # G2 B1: str = U8 byte array
            return mk_arr(z3.Array(n, z3.IntSort(), z3.IntSort()), z3.Int(n + ".len"), base, U8)
        if is_array(ty):
            elem = array_elem(ty)
            if elem.owner is not None:      # G3: [T] = (Array Int sort(T), length)
                esort = s.model.sort_of(elem)
            else:
                esort = z3.BoolSort() if elem == BOOL else z3.IntSort()
            return mk_arr(z3.Array(n, z3.IntSort(), esort), z3.Int(n + ".len"), base, elem)
        if ty.owner is None and ty.name in _COLL:   # G6 A1: Vec = [T] array, String = u8 array, HashMap = (d, a, n)
            if ty.name == "file":
                buf = mk_arr(z3.Array(n, z3.IntSort(), z3.IntSort()), z3.Int(n + ".size"), base, U8)
                return File(z3.Bool(n + ".ok"), z3.Bool(n + ".readable"), z3.Bool(n + ".writable"), buf)
            if ty.name == "string":
                return mk_arr(z3.Array(n, z3.IntSort(), z3.IntSort()), z3.Int(n + ".len"), base, U8)
            if ty.name == "vec":
                return mk_arr(z3.Array(n, z3.IntSort(), s.model.sort_of(ty.args[0])), z3.Int(n + ".len"), base,
                              ty.args[0])
            ks, vs = s.model.sort_of(ty.args[0]), s.model.sort_of(ty.args[1])
            return Map(z3.Array(n + ".d", ks, z3.BoolSort()), z3.Array(n + ".a", ks, vs), z3.Int(n + ".len"), base,
                       ty.args[0], ty.args[1])
        if ty.owner is not None or ty.name in ("option", "result") or s.model.is_user(ty):
            return z3.Const(n, s.model.sort_of(ty))
        raise Exception("fresh: " + ty.name)

    # ---------- value domain ----------
    def wf(s, ty, v):
        """well_formed(ty, v): every active leaf is an i64. None when trivially true (module-level _wf_of)."""
        return _wf_of(s.model, ty, v)

    def observe(s, st, t, ty, force=False):
        """G9 A1: add the valid one-step size/wf facts of the observed nominal term t (Model.facts) to the path
        condition of st, once per fact. Only for recursive-related types, or any non-generic nominal when forced
        (an explicit `size` call). A no-op for programs without recursive types."""
        m = s.model
        if ty is None or isinstance(t, (Arr, Map, File)):
            return
        if not (m.rel(ty) or (force and m.rel_nominal(ty))):
            return
        tid = t.get_id()            # z3 AST ids: a term (datatype sort) never shares an id with a fact (Bool)
        if tid in st.obs:
            return
        new = [tid]
        for fct in m.facts(ty, t):
            i = fct.get_id()
            if i not in st.obs:
                new.append(i)
                st.pc.append(fct)
        st.obs = st.obs | set(new)

    def rebuild(s, ty, cur, path, new):
        """struct value `cur` of type ty with the field path replaced by `new`"""
        if not path:
            return new
        m = s.model
        i = m.tt.field_index(ty, path[0])
        ctor, accs = m.struct_info(ty)
        vals = [acc(cur) for acc in accs]
        fty = m.fields_of(ty)[i][1]
        if len(path) == 1:
            vals[i] = m.field_put(fty, new)       # G9 A1: a buffer field stores a Buf datatype value
        else:
            vals[i] = s.rebuild(fty, vals[i], path[1:], new)
        return ctor(*vals)

    # ---------- obligations ----------
    def prove(s, st, g, ob, node, code, what, key_extra=None, cand=None):
        probing = s.probe is not None
        if probing and (cand is None or cand in s.probe.failed):
            return      # exploration looks only at candidate obligations that have not failed this round
        key = (node.line, node.col, code) if key_extra is None else (node.line, node.col, code, key_extra)
        skipped = False if probing else key in s.seen
        idx = None
        if s.rec is not None:
            idx = s.rec.begin(s.f.name, node, code, skipped, s.qcfg.phase, s.qcfg.round, cand, file=s.file_of(node))
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

        if probing:
            s._probe_attempts(run, code, cand)
            return
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
        s.errors.append(PruvError("verify", node.line, node.col, code2, msg, FIX.get(code, ""), cex,
                                  file=s.file_of(node)))

    def file_of(s, node):
        """G4 A1: the file of an obligation's node; synthesized nodes (inferred invariants) fall back to the function's
        file. None for every legacy program (nodes carry no file there), so legacy output is unchanged."""
        return getattr(node, "file", None) or s.f.file

    def _probe_attempts(s, run, code, cand):
        """STAGE1 B2 exploration of one candidate obligation: the same two stages as prove (without lemmas, then
        with them if there are any and the first was not unsat); every attempt checks the budget and the clock
        first. An attempt that is unknown with z3 reason exactly "timeout" (the query's own 500 ms wall-clock limit)
        aborts the whole function (InferenceTimeout), as does the 5 s wall clock (Probe.tick). Any other last attempt
        that is not proved (not_proved, resource_unknown, error, or unknown with another reason such as rlimit
        exhaustion "canceled") marks only this candidate failed for this round; the status string is recorded
        as query_status gives it."""
        pr = s.probe
        status = None
        for with_lemmas in (False, True):
            if with_lemmas and not s.lemmas:
                break
            pr.tick()
            try:
                sol, r = run(with_lemmas)
            except z3.Z3Exception:
                status = "error"
                break
            reason = sol.reason_unknown() if r == z3.unknown else None
            status = query_status(r, reason)
            if reason == "timeout":
                raise InferenceTimeout()
            if r == z3.unsat:
                return
        pr.fail(cand, code, status)

    def opaque(s, val):
        """G3 A2 (4.7): token of an abstract model value; ordinals are per abstract sort, in first-seen order of
        this counterexample, and equal model values share one"""
        sname = val.sort().name()
        tab = s._opq.setdefault(sname, {})
        key = val.sexpr()
        if key not in tab:
            tab[key] = len(tab)
        return {"type_parameter": s.model.abs_name[sname], "value": "opaque#%d" % tab[key]}

    def cex(s, m, st):
        out = {}
        s._opq = {}
        s._cex_m = m
        for name, v in st.env.items():
            try:
                if isinstance(v, File):
                    out[name] = {field: z3.is_true(m.eval(getattr(v, field), model_completion=True))
                                 for field in ("ok", "readable", "writable")}
                    out[name]["size"] = m.eval(v.buf.n, model_completion=True).as_long()
                elif isinstance(v, Arr):
                    n = m.eval(v.n, model_completion=True).as_long()
                    if v.elem == BOOL:   # G2 A5: bool elements print as true/false
                        els = [z3.is_true(m.eval(z3.Select(v.a, i), model_completion=True))
                               for i in range(min(max(n, 0), 8))]
                    elif v.elem.owner is not None:   # G3: abstract elements are opaque tokens
                        els = [s.opaque(m.eval(z3.Select(v.a, i), model_completion=True))
                               for i in range(min(max(n, 0), 8))]
                    else:
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

    # G9 A1: display bounds of a recursive counterexample value (they never constrain the solver)
    CEX_MAX_NODES = 64      # nominal constructor nodes printed per value, preorder
    CEX_MAX_DEPTH = 16      # nesting depth printed (the value itself is depth 1)
    CEX_TRUNCATED = "<truncated>"

    def fmt_val(s, v, nested=False):
        """z3 model value -> Pruv syntax on one line (user struct/enum); unknown shapes keep z3's str().
        G3: an abstract value is its opaque token (a dict at the top, `T:opaque#N` inside a datatype).
        A program with a G9 feature takes the bounded printer; any other program the original one."""
        if s.model.g9:
            return s._fmt_g9(v, nested, [0], 1, None)
        return s._fmt_val_old(v, nested)

    def _fmt_buf(s, v, fty):
        """a buffer field value Buf(len, arr): [e0, e1, ...] (first 8 elements) or "bytes" for a str field"""
        m = s._cex_m
        n = v.children()[0].as_long()
        arr = v.children()[1]
        els = []
        for i in range(min(max(n, 0), 8)):
            x = m.eval(z3.Select(arr, z3.IntVal(i)), model_completion=True)
            els.append(z3.is_true(x) if fty.name == "array_bool" else x.as_long())
        more = n > 8
        if fty.name == "str":
            body = "".join(chr(b) if 32 <= b < 127 and chr(b) not in '"\\' else "\\x%02x" % (b & 255) for b in els)
            return '"%s%s"' % (body, "..." if more else "")
        txt = ", ".join(("true" if x else "false") if fty.name == "array_bool" else str(x) for x in els)
        return "[%s%s]" % (txt, (", ..." if txt else "...") if more else "")

    def _fmt_g9(s, v, nested, lim, depth, fty):
        try:
            if z3.is_int_value(v):
                return str(v.as_long())
            if z3.is_bool(v):
                return "true" if z3.is_true(v) else "false"
            sname = v.sort().name()
            if sname in s.model.buf_names:
                return s._fmt_buf(v, fty)
            if sname in s.model.abs_name:
                tok = s.opaque(v)
                return "%s:%s" % (tok["type_parameter"], tok["value"]) if nested else tok
            ty = s.model.type_of(v)
            if ty is not None and ty.name in ("option", "result") and ty.args and z3.is_app(v):
                nm = s.model.short.get(v.decl().name(), v.decl().name())
                ks = [s._fmt_g9(c, True, lim, depth, None) for c in v.children()]
                return nm if not ks else "%s(%s)" % (nm, ", ".join(ks))
            if ty is None or not s.model.is_user(ty) or not z3.is_app(v):
                return str(v)
            if lim[0] >= s.CEX_MAX_NODES or depth > s.CEX_MAX_DEPTH:
                return s.CEX_TRUNCATED
            lim[0] += 1
            dn = v.decl().name()
            decl = s.model.tt.decls.get(ty.name)
            if decl is None:
                return str(v)
            if isinstance(decl, StructDecl):
                ctor, _ = s.model.struct_info(ty)
                if ctor.name() == dn and len(decl.fields) == v.num_args():
                    if not decl.fields:
                        return ty.name
                    kids = [s._fmt_g9(c, True, lim, depth + 1, fd.type) for fd, c in zip(decl.fields, v.children())]
                    return "%s { %s }" % (ty.name, ", ".join("%s: %s" % (fd.name, k) for fd, k in zip(decl.fields, kids)))
            else:
                for vd in decl.variants:
                    ctor = s.model.enum_info(ty)[vd.name][0]
                    if ctor.name() == dn:
                        if not vd.fields:
                            return "%s::%s" % (ty.name, vd.name)
                        kids = [s._fmt_g9(c, True, lim, depth + 1, fd.type) for fd, c in zip(vd.fields, v.children())]
                        return "%s::%s(%s)" % (ty.name, vd.name, ", ".join(kids))
            return str(v)
        except Exception:
            return str(v)

    def _fmt_val_old(s, v, nested=False):
        try:
            if z3.is_int_value(v):
                return str(v.as_long())
            if z3.is_bool(v):
                return "true" if z3.is_true(v) else "false"
            if v.sort().name() in s.model.abs_name:
                tok = s.opaque(v)
                return "%s:%s" % (tok["type_parameter"], tok["value"]) if nested else tok
            ty = s.model.type_of(v)
            if ty is not None and ty.name in ("option", "result") and ty.args and z3.is_app(v):
                nm = s.model.short.get(v.decl().name(), v.decl().name())
                ks = [s.fmt_val(c, True) for c in v.children()]
                return nm if not ks else "%s(%s)" % (nm, ", ".join(ks))
            if ty is None or not s.model.is_user(ty) or not z3.is_app(v):
                return str(v)
            dn = v.decl().name()
            kids = [s.fmt_val(c, True) for c in v.children()]
            if ty.name in s.model.struct or (ty.args and s.model.tt.is_struct(ty)):
                ctor, _ = s.model.struct_info(ty)
                decl = next((d for d in s.model.tt.order if d.name == ty.name), None)
                if ctor.name() == dn and decl is not None and len(decl.fields) == len(kids):
                    if not kids:
                        return ty.name
                    return "%s { %s }" % (ty.name, ", ".join(
                        "%s: %s" % (fd.name, k) for fd, k in zip(decl.fields, kids)))
            elif ty.name in s.model.enum or (ty.args and s.model.tt.is_enum(ty)):
                for vn, (ctor, _, _) in s.model.enum_info(ty).items():
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
        if isinstance(e, StrLit):   # G2 B1: constant byte array, no counter, no assumption
            a = z3.K(z3.IntSort(), z3.IntVal(0))
            for i, b in enumerate(e.value):
                a = z3.Store(a, z3.IntVal(i), z3.IntVal(b))
            return mk_arr(a, z3.IntVal(len(e.value)), "literal", U8)
        if isinstance(e, Var):
            return env[e.name]
        if isinstance(e, Move):     # G6 A1: the current value of the binding
            return env[e.name]
        if isinstance(e, InoutArg):     # G5 A1: the marked place's current array (the call transition rebinds it)
            return s.ev(e.expr, st, g, code, env)
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
            # G2 A5: a bool element is a Bool; G3: an abstract element has no numeric domain: no in_range assumption
            if code and arr.elem != BOOL and arr.elem.owner is None:
                s.assume(st, g, in_range(v))
            return v
        if isinstance(e, Ctor):
            cty = s.T(e.ty)
            if e.name == "None":
                return s.model.opt(cty).none
            v = s.ev(e.arg, st, g, code, env)
            if e.name == "Some":
                return s.model.opt(cty).some(v)
            o = s.model.res(cty)
            return o.ok(v) if e.name == "Ok" else o.err(v)
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
            sty = s.T(e.ty) if e.ty is not None else Type(e.name)
            if s.model.g9:      # G9 A1: buffer fields store Buf values; recursive results expose their facts
                vals = [s.model.field_put(ft, x) for (fd, ft), x in zip(s.model.fields_of(sty), vals)]
                res = s.model.struct_info(sty)[0](*vals)
                s.observe(st, res, sty)
                return res
            return s.model.struct_info(sty)[0](*vals)
        if isinstance(e, EnumCtor):
            vals = [s.ev(a, st, g, code, env) for a in e.args]
            ety = s.T(e.ty) if e.ty is not None else Type(e.enum_name)
            if s.model.g9:
                vals = [s.model.field_put(ft, x) for (fd, ft), x in zip(s.model.fields_of(ety, e.variant), vals)]
                res = s.model.enum_info(ety)[e.variant][0](*vals)
                s.observe(st, res, ety)
                return res
            return s.model.enum_info(ety)[e.variant][0](*vals)
        if isinstance(e, FieldAccess):
            v = s.ev(e.base, st, g, code, env)
            ty = s.model.type_of(v)
            i = s.model.tt.field_index(ty, e.field)
            r = s.model.struct_info(ty)[1][i](v)
            if s.model.g9:      # G9 A1: adapt a buffer field to an Arr; parent and nominal child are observed terms
                s.observe(st, v, ty)        # the parent's one-step wf/size equations give the field's own facts
                fty = s.model.fields_of(ty)[i][1]
                r = s.model.field_get(fty, r, e.field)
                s.observe(st, r, fty)
            return r
        if isinstance(e, IsVariant):
            v = s.ev(e.value, st, g, code, env)
            return s.model.enum_info(s._enum_ty(e, v))[e.variant][1](v)
        if isinstance(e, VariantField):
            v = s.ev(e.value, st, g, code, env)
            ety = s._enum_ty(e, v)
            i = s.model.tt.field_index(ety, e.field, e.variant)
            r = s.model.enum_info(ety)[e.variant][2][i](v)
            if s.model.g9:
                s.observe(st, v, ety)
                fty = s.model.fields_of(ety, e.variant)[i][1]
                r = s.model.field_get(fty, r, e.field)
                s.observe(st, r, fty)
            return r
        raise Exception("ev: %r" % e)

    def _enum_ty(s, e, v):
        """instantiated enum type of an is_variant / variant_field scrutinee: from its z3 sort (already
        substituted), else from the checker's record, else the plain enum name"""
        ty = s.model.type_of(v)
        if ty is not None and ty.name == e.enum_name:
            return ty
        return Type(e.enum_name)

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
            if wo and e.name == "file_byte":
                f = s.ev(e.args[0], st, g, False, env)
                i = s.ev(e.args[1], st, g, False, env)
                parts.append(z3.And(i >= 0, i < f.buf.n))
            if wo and e.name in _TAG_FNS:
                v = s.ev(e.args[0], st, g, False, env)
                vty = s.model.type_of(v)       # G3: the Option/Result instance of the argument
                if e.name == "some_val":
                    parts.append(s.model.opt(vty).is_some(v))
                else:
                    ro = s.model.res(vty)
                    parts.append(ro.is_ok(v) if e.name == "ok_val" else z3.Not(ro.is_ok(v)))
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
            return _conj([inner, s.model.enum_info(s._enum_ty(e, v))[e.variant][1](v)])
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

    def check_dom(s, st, g, e, node, what, env=None, cand=None):
        """prove D(e) separately per code (variant_domain / contract_domain); returns the proven domains.
        cand: STAGE1 B2 candidate id (keys the duplicate suppression and tags the obligation)"""
        obs = s.dom_obligations(e, st, g, st.env if env is None else env)
        for d, code in obs:
            s.prove(st, g, d, node, code, what if code == "variant_domain" else what.replace(
                "variant_field lookups", "partial operations (index, /, %, some_val/ok_val/err_val, max/min)"),
                key_extra=cand, cand=cand)
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
        if e.old is not None:
            # G5 A1: old(a) is the frozen entry array. A callee contract being instantiated at a call site supplies its
            # own pre-call arrays under ("old", name) in its environment; otherwise it is this function's snapshot.
            key = ("old", e.old["param"])
            return env[key] if key in env else s.snap[e.old["param"]]
        args = [s.ev(a, st, g, code, env) for a in e.args]
        if n == "len":
            return args[0].n
        if n == "size":     # G9 A1: contract-only structural size of a non-generic nominal value
            sty = s.model.type_of(args[0])
            s.observe(st, args[0], sty, force=True)
            return s.model.size_fn(sty.name)(args[0])
        if n == "alloc":
            s.prove(st, g, z3.And(args[0] >= 0, args[0] <= MAX_LEN), e, "alloc_negative",
                    "alloc length in 0..2^40")
            tname = getattr(e.ty, "name", None)
            # G2 A5: array_bool -> BOOL elements, no elem_range obligation
            aelem = U8 if tname == "array_u8" else BOOL if tname == "array_bool" else I64
            aty = s.T(e.ty)
            if aty is not None and aty.name == "array" and aty.args:   # G3: alloc of a [T]
                aelem = aty.args[0]
            if aelem == U8:
                s.prove(st, g, z3.And(args[1] >= 0, args[1] <= 255), e, "elem_range",
                        "u8 element range 0..=255 for the alloc fill value")
            s.k += 1
            return mk_arr(z3.K(z3.IntSort(), args[1]), args[0], "alloc", aelem)
        if n == "copy":
            return mk_arr(args[0].a, args[0].n, "copy", args[0].elem)
        if n == "is_char_boundary":
            return str_boundary(args[0], args[1])
        if n == "substr":   # G2 B1 (G2_SPEC 4.4): range -> boundary -> fresh result
            sv, lo, hi = args
            s.prove(st, g, z3.And(lo >= 0, lo <= hi, hi <= sv.n), e, "string_slice_range",
                    "substr range 0 <= lo <= hi <= len(%s)" % sv.name)
            s.prove(st, g, z3.And(str_boundary(sv, lo), str_boundary(sv, hi)), e, "utf8_boundary",
                    "substr cuts of %s at UTF-8 character boundaries" % sv.name)
            res = s.fresh("substr", STR)
            s.assume(st, g, res.n == hi - lo)
            k = z3.Int("str!k")
            s.assume(st, g, z3.ForAll([k], z3.Implies(z3.And(k >= 0, k < res.n),
                                                       z3.Select(res.a, k) == z3.Select(sv.a, lo + k))))
            return res
        if n in CATALOG_NAMES and n not in s.funcs:
            return s.catalog_call(e, args, st, g, code)
        if n == "print":
            return None
        if n in ("is_some", "some_val"):
            o = s.model.opt(s.model.type_of(args[0]))     # G3: the datatype of the argument's own sort
            return o.is_some(args[0]) if n == "is_some" else o.sval(args[0])
        if n in ("is_ok", "ok_val", "err_val"):
            o = s.model.res(s.model.type_of(args[0]))
            return o.is_ok(args[0]) if n == "is_ok" else o.oval(args[0]) if n == "ok_val" else o.eval(args[0])
        f = s.funcs[n]
        cenv = {p.name: a for p, a in zip(f.params, args)}
        # G5 A1 (5.2 step 2): the pre-call arrays freeze as the callee's old bindings (scoped to this contract
        # evaluation: the caller's own snapshot map is never touched)
        ios = [i for i, p in enumerate(f.params) if p.mode is not None]
        for i in ios:
            cenv[("old", f.params[i].name)] = args[i]
        # G3 A2 (4.4): typed re-interpretation of the callee contract under the checker's recorded substitution
        theta = e.inst["subst"] if getattr(e, "inst", None) else {}
        saved, s.theta = s.theta, theta
        try:
            if code:
                # No domain proof of callee requires here: the callee's own run() already proved
                # D(r) under "param wf + earlier requires (values and variant domains)"; the call site
                # proves each earlier requires value and the args satisfy wf, so it would be redundant.
                for r in f.requires:
                    ob = s.ev(r, st, g, False, cenv)
                    s.prove(st, g, ob, e, "call_requires", "precondition of %s (line %d)" % (n, r.line))
                s.termination(e, f, st, g, cenv)    # G9 A1: only a call inside the caller's own recursive SCC
            if ios:
                s.inout_finals(e, f, ios, args, cenv, st, g)    # G5 A1 (5.2 step 5): fresh same-length contents
            if f.ret == UNIT:
                # G6 A1 (11.4): a trusted unit result still assumes its ensures; G9 A1: so does a member of a recursive
                # SCC, after the termination obligations above (also when called from outside the SCC)
                # G4 A1 (G4_SPEC 5): in explicit visibility mode every ordinary unit call assumes its ensures, after
                # the same requires/termination obligations; legacy programs keep their exact old behavior and SMT.
                # G5 A1: every inout call applies its ensures, in legacy single-file mode too
                if ios or f.foreign is not None or n in s.scc_id or s.explicit:
                    for en in f.ensures:
                        s.assume(st, g, s.ev(en, st, g, False, cenv))
                if ios:
                    s.post_refine(e, ios, st, g)
                return None
            rty = substitute(f.ret, theta) if theta else f.ret
            res = s.fresh("ret_" + n, rty)
            if isinstance(res, Arr):
                s.assume(st, g, z3.And(res.n >= 0, res.n <= MAX_LEN))
                if res.elem == U8:
                    s.assume(st, g, u8_dom(res))
            elif isinstance(res, Map):
                s.assume(st, g, z3.And(res.n >= 0, res.n <= MAX_LEN))
            else:
                w = s.wf(rty, res)
                if w is not None:
                    s.assume(st, g, w)
            cenv["result"] = res
            for en in f.ensures:
                s.assume(st, g, s.ev(en, st, g, False, cenv))
            if ios:
                s.post_refine(e, ios, st, g)
            return res
        finally:
            s.theta = saved

    def inout_finals(s, e, f, ios, args, cenv, st, g):
        """G5 A1 (G5_SPEC 5.2 step 5): for every inout argument in parameter order, fresh contents of exactly the
        pre-call length (same length term, same element type, u8 domain for [u8]). The final array is what the
        callee's ensures denote by the parameter name, and it rebinds the caller's marked place. All finals exist
        before any ensures clause is assumed, so relational ensures may connect several of them."""
        for i in ios:
            pre = args[i]
            name = e.args[i].expr.name
            fv = s.fresh(name, arr_type(pre.elem))
            nv = mk_arr(fv.a, pre.n, name, pre.elem)
            if nv.elem == U8:
                s.assume(st, g, u8_dom(nv))
            cenv[f.params[i].name] = nv
            st.env[name] = nv

    def post_refine(s, e, ios, st, g):
        """G5 A1 (G5_SPEC 5.2 step 8): the refinement of every marked refined local must hold right after the call
        (refinement_assign, proved from the callee ensures and the remaining facts; never assumed beforehand). The
        assertions were attached to the inout argument by refine.py."""
        for i in ios:
            for a in getattr(e.args[i], "post_refine", None) or ():
                st.pc.append(s.check_assert(a, st))

    def par(s, p, st):
        """G7 A1 (G7_SPEC 5): one par group. (1) every branch's actuals are evaluated against the group-entry state and
        frozen (callee old = that actual); (2) every branch requires (and applicable recursive decreases) is proven in
        source order against that same entry state, before any ensures is assumed (prove never adds to the path
        condition, so nothing of a sibling is available either); (3) all inout finals of all branches are created with
        the F3 transition (same length, element type, u8 domain) before any ensures; (4) every branch's ensures is
        conjoined into the joined state, also for legacy unit branches without inout; (5) each branch's refined locals
        are checked on a fork that assumes only that branch's own ensures. Unwritten bindings keep their values."""
        st = st.fork()
        brs = []
        for c in p.calls:
            f = s.funcs[c.name]
            args = [s.ev(a, st, [], True) for a in c.args]
            cenv = {pm.name: a for pm, a in zip(f.params, args)}
            ios = [i for i, pm in enumerate(f.params) if pm.mode is not None]
            for i in ios:
                cenv[("old", f.params[i].name)] = args[i]
            theta = c.inst["subst"] if getattr(c, "inst", None) else {}
            brs.append((c, f, args, cenv, ios, theta))
        for c, f, args, cenv, ios, theta in brs:
            saved, s.theta = s.theta, theta
            try:
                for r in f.requires:
                    ob = s.ev(r, st, [], False, cenv)
                    s.prove(st, [], ob, c, "call_requires", "precondition of %s (line %d)" % (c.name, r.line))
                s.termination(c, f, st, [], cenv)
            finally:
                s.theta = saved
        for c, f, args, cenv, ios, theta in brs:
            if ios:
                s.inout_finals(c, f, ios, args, cenv, st, [])
        base = st.fork()        # all finals exist, no ensures assumed yet
        for c, f, args, cenv, ios, theta in brs:
            saved, s.theta = s.theta, theta
            try:
                for en in f.ensures:
                    s.assume(st, [], s.ev(en, st, [], False, cenv))
            finally:
                s.theta = saved
        for c, f, args, cenv, ios, theta in brs:
            if not any(getattr(c.args[i], "post_refine", None) for i in ios):
                continue
            b = base.fork()
            saved, s.theta = s.theta, theta
            try:
                for en in f.ensures:
                    s.assume(b, [], s.ev(en, b, [], False, cenv))
            finally:
                s.theta = saved
            for i in ios:
                for a in getattr(c.args[i], "post_refine", None) or ():
                    st.pc.append(s.check_assert(a, b))
        return st

    def termination(s, e, f, st, g, cenv):
        """G9 A1 (G9_SPEC 5): the obligations of a call s.f -> f inside one recursive SCC, after the callee requires:
        definedness of the instantiated callee measure (existing domain codes), M_f(actuals) >= 0
        (recursive_nonneg), M_f(actuals) < M_s.f(frozen entry value) (recursive_decrease). Only after these the
        caller introduces the fresh result and assumes the callee ensures (so the call's own ensures never justify
        its own decrease or precondition). cenv: the callee parameters bound to the actual argument values."""
        a, b = s.scc_id.get(f.name), s.scc_id.get(s.f.name)
        if a is None or a != b or f.decreases is None or s.m0 is None:
            return
        s.check_dom(st, g, f.decreases, e, "variant_field lookups in the decreases clause of %s are defined" % f.name,
                    cenv)
        mg = s.ev(f.decreases, st, g, False, cenv)
        tg, tf = _expr_text(f.decreases), _expr_text(s.f.decreases)
        s.prove(st, g, mg >= 0, e, "recursive_nonneg",
                "decreases measure of %s (`%s`) >= 0 at this call" % (f.name, tg))
        s.prove(st, g, mg < s.m0, e, "recursive_decrease",
                "decreases measure of %s (`%s`) < decreases measure of %s at its entry (`%s`)" % (f.name, tg, s.f.name, tf))

    def catalog_call(s, e, args, st, g, code):
        """G6 A1 (G6_SPEC 11.3): the standard catalog; every requires is a `call_requires` obligation
        (only in code), then an exact term is the result. G10 fs calls return fresh values with catalog ensures."""
        n = e.name
        rty = s.T(e.ty)

        def need(ob):
            if code:
                s.prove(st, g, ob, e, "call_requires", "precondition of %s (catalog)" % n)

        if n in FILE_OBSERVERS:
            f = args[0]
            if n == "file_size":
                return f.buf.n
            if n == "file_byte":
                i = args[1]
                need(z3.And(i >= 0, i < f.buf.n))
                r = z3.Select(f.buf.a, i)
                if code:
                    s.assume(st, g, z3.And(r >= 0, r <= 255))
                return r
            return getattr(f, n[len("file_"):])
        if n.startswith("file_"):
            f = CATALOG[n]
            # Keep the entry arguments, including a consumed handle, for file_close's ensures.
            cenv = {p.name: a for p, a in zip(f.params, args)}
            for req in f.requires:
                need(s.ev(req, st, g, False, cenv))
            res = s.fresh(n, rty)
            w = s.wf(rty, res)
            if w is not None:
                s.assume(st, g, w)
            cenv["result"] = res
            for en in f.ensures:
                s.assume(st, g, s.ev(en, st, g, False, cenv))
            return res
        if n in ("vec_new", "string_new", "map_new"):
            r = s.fresh(n, rty)
            if n == "map_new":
                kt = z3.K(s.model.sort_of(r.kty), z3.BoolVal(False))
                return Map(kt, r.a, z3.IntVal(0), n, r.kty, r.vty)
            return mk_arr(r.a, z3.IntVal(0), n, r.elem)
        if n == "vec_push":
            v, x = args
            need(v.n < MAX_LEN)
            return mk_arr(z3.Store(v.a, v.n, x), v.n + 1, n, v.elem)
        if n in ("vec_get", "string_byte"):
            v, i = args
            need(z3.And(i >= 0, i < v.n))
            r = z3.Select(v.a, i)
            if code and v.elem in (I64, U8):   # as an array read: an i64/u8 element is a machine integer
                s.assume(st, g, in_range(r))
            return r
        if n in ("map_get", "map_lookup"):
            m, k = args
            return s.map_lookup(m, k, rty)
        if n == "map_insert":
            m, k, x = args
            has = z3.Select(m.d, k)
            need(z3.Or(has, m.n < MAX_LEN))
            return Map(z3.Store(m.d, k, z3.BoolVal(True)), z3.Store(m.a, k, x), m.n + z3.If(has, 0, 1), n, m.kty,
                       m.vty)
        if n == "map_updated":
            aft, bef, k, x = args
            j = z3.Const("map!j", s.model.sort_of(aft.kty))
            return z3.And(aft.d == z3.Store(bef.d, k, z3.BoolVal(True)),
                          aft.n == bef.n + z3.If(z3.Select(bef.d, k), 0, 1),
                          z3.ForAll([j], z3.Implies(z3.Select(aft.d, j),
                                                    z3.Select(aft.a, j) == z3.Select(z3.Store(bef.a, k, x), j))))
        if n == "string_push_str":
            sv, t = args
            need(sv.n + t.n <= MAX_LEN)
            res = s.fresh(n, _STRING)
            s.assume(st, g, res.n == sv.n + t.n)
            k = z3.Int("str!k")
            s.assume(st, g, z3.ForAll([k], z3.Implies(z3.And(k >= 0, k < sv.n),
                                                       z3.Select(res.a, k) == z3.Select(sv.a, k))))
            s.assume(st, g, z3.ForAll([k], z3.Implies(z3.And(k >= 0, k < t.n),
                                                       z3.Select(res.a, sv.n + k) == z3.Select(t.a, k))))
            return res
        if n == "string_to_str":
            return mk_arr(args[0].a, args[0].n, n, U8)
        raise Exception("catalog: " + n)

    def map_lookup(s, m, k, rty):
        """If(m.d[k], Some(m.a[k]), None) as an Option<V> of the call's own result type"""
        o = s.model.opt(rty)
        return z3.If(z3.Select(m.d, k), o.some(z3.Select(m.a, k)), o.none)

    # ---------- statements ----------
    def ensures_ok(s, st, val, node):
        env = dict(st.env)
        for p in s.f.params:
            if p.mode is None:      # G5 A1: ordinary parameters denote their entry values; an inout parameter keeps its
                env[p.name] = s.params[p.name]      # current (final) value, and old(a) resolves through s.snap
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

    # ---------- G5 A1: inout writes in the changed-variable analysis ----------
    def _inout_ops(s, e, out):
        """whole-array operands of the inout arguments of e itself (an inout call is always the complete expression
        of a statement, G5_SPEC 2.1, so nothing below it is visited)"""
        if isinstance(e, Call):
            for a in e.args:
                if isinstance(a, InoutArg) and isinstance(a.expr, Var):
                    out.add(a.expr.name)

    def call_writes(s, stmts, out):
        """names passed inout to calls in let initializers, assignments, returns and expression statements,
        recursively through statement blocks (empty for a program without inout)"""
        for st in stmts:
            if isinstance(st, (Let, Assign)):
                s._inout_ops(st.value, out)
            elif isinstance(st, Return):
                if st.value is not None:
                    s._inout_ops(st.value, out)
            elif isinstance(st, ExprStmt):
                s._inout_ops(st.expr, out)
            elif isinstance(st, Par):      # G7 A0: every branch's inout operands (verification itself is A1)
                for c in st.calls:
                    s._inout_ops(c, out)
            elif isinstance(st, If):
                s.call_writes(st.then, out); s.call_writes(st.els, out)
            elif isinstance(st, While):
                s.call_writes(st.body, out)
            elif isinstance(st, Match):
                for a in st.arms:
                    s.call_writes(a.body, out)
        return out

    def whole_assigned(s, stmts, out):
        """names that a whole-variable assignment in stmts can replace (nested blocks included)"""
        for st in stmts:
            if isinstance(st, Assign):
                out.add(st.name)
            elif isinstance(st, If):
                s.whole_assigned(st.then, out); s.whole_assigned(st.els, out)
            elif isinstance(st, While):
                s.whole_assigned(st.body, out)
            elif isinstance(st, Match):
                for a in st.arms:
                    s.whole_assigned(a.body, out)
        return out

    def havoc(s, st, names, keep=frozenset()):
        """keep: array names whose havoc retains the length term (G5 A1: inout parameters, and locals changed only by
        inout calls); every other array gets an arbitrary well-formed length exactly as before"""
        h = st.fork()
        for n in sorted(names):
            if n not in h.env:
                continue
            old = h.env[n]
            if isinstance(old, File):
                nv = s.fresh(n, FILE)
                h.pc.append(s.wf(FILE, nv))
                h.env[n] = nv
            elif isinstance(old, Arr):
                # G6 A1: an element type without a legacy array type (a Vec<X>) is re-created as a Vec
                legacy = old.elem in (I64, U8, BOOL) or old.elem.owner is not None
                nv = s.fresh(n, arr_type(old.elem) if legacy else Type("vec", (old.elem,)))
                if n in keep:
                    nv = mk_arr(nv.a, old.n, nv.name, nv.elem)
                else:
                    h.pc.append(z3.And(nv.n >= 0, nv.n <= MAX_LEN))
                if nv.elem == U8:
                    h.pc.append(u8_dom(nv))
                h.env[n] = nv
            elif isinstance(old, Map):
                nv = s.fresh(n, Type("hashmap", (old.kty, old.vty)))
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

    def check_assert(s, stmt, st):
        """prove one assertion (user or synthesized by refine.py) on st; returns its value term"""
        s.check_dom(st, [], stmt.cond, stmt, "variant_field lookups in assertion are defined")
        ob = s.ev(stmt.cond, st, [], False)
        if stmt.origin_code is None:
            s.prove(st, [], ob, stmt, "assert", "assertion")
        else:
            # synthesized by refine.py: own code and a source description; the description also keys
            # the duplicate suppression, so different sites of one annotation are all reported
            s.prove(st, [], ob, stmt, stmt.origin_code, stmt.origin_what, stmt.origin_what)
        return ob

    def exec(s, stmt, st):
        if isinstance(stmt, Let) or isinstance(stmt, Assign):
            st = st.fork()
            v = s.ev(stmt.value, st, [], True)
            if isinstance(v, Arr):
                v = mk_arr(v.a, v.n, stmt.name, v.elem)
            st.env[stmt.name] = v
            return [st]
        if isinstance(stmt, IndexAssign):
            st = st.fork()
            arr = st.env[stmt.name]
            i = s.ev(stmt.index, st, [], True)
            v = s.ev(stmt.value, st, [], True)
            s.prove(st, [], z3.And(i >= 0, i < arr.n), stmt, "index_oob", "index in bounds for %s[...] =" % stmt.name)
            if arr.elem == U8:
                s.prove(st, [], z3.And(v >= 0, v <= 255), stmt, "elem_range",
                        "u8 element range 0..=255 for %s[...] =" % stmt.name)
            if stmt.elem_refine is not None:
                # refine.py: the stored value (already evaluated) must lie in the element range. One query, no
                # domain check, no re-evaluation, no forall; not assumed afterwards (it is implied by the path).
                lo, hi, what = stmt.elem_refine
                s.prove(st, [], z3.And(v >= lo, v <= hi), stmt, "refinement_assign", what, what)
            st.env[stmt.name] = mk_arr(z3.Store(arr.a, i, v), arr.n, stmt.name, arr.elem)
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
            sty = s.model.type_of(v)     # G3: the scrutinee's complete (possibly generic) type
            if s.model.g9:
                s.observe(st, v, sty)    # G9 A1: one-step facts of the matched value
            payload =sty.args[0] if sty is not None and sty.args and sty.name in ("option", "result") else I64
            for a in stmt.arms:
                if a.enum_name is not None:
                    ety = sty if sty is not None and sty.name == a.enum_name else Type(a.enum_name)
                    _, rec, accs = s.model.enum_info(ety)[a.ctor]
                    cond = rec(v)
                    vals = [acc(v) for acc in accs]
                    ftys = [ft for _, ft in s.model.fields_of(ety, a.ctor)]
                else:
                    if a.ctor in ("Some", "None"):
                        o = s.model.opt(sty)
                        if a.ctor == "Some": cond, val = o.is_some(v), o.sval(v)
                        else: cond, val = o.is_none(v), None
                    else:
                        o = s.model.res(sty)
                        if a.ctor == "Ok": cond, val = o.is_ok(v), o.oval(v)
                        else: cond, val = o.is_err(v), o.eval(v)
                    vals = [] if val is None else [val]
                    ftys = [I64 if a.ctor == "Err" else payload] * len(vals)
                b = st.fork(cond)
                for name, val, fty in zip(a.binders, vals, ftys):
                    if s.model.g9:       # G9 A1: buffer payloads become Arr views; nominal payloads are observed
                        val = s.model.field_get(fty, val, name)
                        s.observe(b, val, fty)
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
            ob = s.check_assert(stmt, st)
            st = st.fork(ob)
            return [st]
        if isinstance(stmt, ExprStmt):
            st = st.fork()
            s.ev(stmt.expr, st, [], True)
            return [st]
        if isinstance(stmt, While):
            return s.loop(stmt, st)
        if isinstance(stmt, Par):       # G7 A1
            return [s.par(stmt, st)]
        raise Exception("exec: %r" % stmt)

    def loop(s, w, st):
        # (cand id | None, expr, text): the written invariants (required refinement first, then user), then the
        # STAGE1 B2 inferred candidates of this loop in their sorted order
        invs = [(None, inv, None) for inv in w.invariants]
        if s.extra:
            invs = invs + list(s.extra.get(s.loop_no[id(w)], []))
        prev = []   # invariants run in order: an earlier one (proven here) may justify a later one's lookups
        for cid, inv, text in invs:
            if cid is None:
                w_dom, w_ob = "variant_field lookups in loop invariant (entry) are defined", "loop invariant on entry"
            else:
                w_dom = "partial operations in inferred loop invariant `%s` (entry) are defined" % text
                w_ob = "inferred loop invariant `%s` on entry" % text
            prev.extend(s.check_dom(st, prev, inv, inv, w_dom, cand=cid))
            ob = s.ev(inv, st, [], False)
            s.prove(st, [], ob, inv, "invariant_entry", w_ob, cid, cid)
            prev.append(ob)
        names = s.assigned(w.body, set())
        # G5 A1 (5.3): inout call arguments are changed too. Inout parameters keep their entry length; a local changed
        # by inout calls keeps the loop-head length only if no whole assignment in the body can replace it.
        # Without inout, calls = {} and snap = {}: names/keep (and the SMT) are exactly the old ones.
        calls = s.call_writes(w.body, set())
        keep = frozenset()
        if calls or s.snap:
            whole = s.whole_assigned(w.body, set()) if calls else set()
            names = names | calls
            keep = frozenset(n for n in names if n in s.snap or (n in calls and n not in whole))
        # one arbitrary iteration; the invariants held (and were defined) at its start
        b = s.havoc(st, names, keep)
        for _cid, inv, _text in invs:
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
            for cid, inv, text in invs:
                if cid is None:
                    w_dom, w_ob = ("variant_field lookups in loop invariant (preserved) are defined",
                                   "loop invariant preserved")
                else:
                    w_dom = "partial operations in inferred loop invariant `%s` (preserved) are defined" % text
                    w_ob = "inferred loop invariant `%s` preserved" % text
                prev.extend(s.check_dom(end, prev, inv, inv, w_dom, cand=cid))
                ob = s.ev(inv, end, [], False)
                s.prove(end, [], ob, inv, "invariant_preserved", w_ob, cid, cid)
                prev.append(ob)
            if _has_vf(w.decreases):
                # decreases is read at the end of the body: the invariants just proved may justify its lookups
                extra = []
                for _cid, inv, _text in invs:
                    d = s.dom(inv, end, [], end.env)
                    if d is not None:
                        extra.append(d)
                    extra.append(s.ev(inv, end, [], False))
                s.check_dom(end, extra, w.decreases, w.decreases, "variant_field lookups in decreases are defined")
            s.prove(end, [], s.ev(w.decreases, end, [], False) < d0, w.decreases, "decreases_decrease",
                    "decreases strictly decreases")
        # after the loop
        a = s.havoc(st, names, keep)
        for _cid, inv, _text in invs:
            d = s.dom(inv, a, [], a.env, "variant")
            if d is not None:
                a.pc.append(d)
            a.pc.append(s.ev(inv, a, [], False))
        c = s.ev(w.cond, a, [], True)
        a.pc.append(z3.Not(c))
        return [a]

    def run_foreign(s, st):
        """domain-only check of the ensures of a trusted rust fn: fresh result `result!k` with its well-formedness,
        then each ensures is domain-checked under the requires, the result facts and the earlier ensures"""
        f = s.f
        env = dict(st.env)
        if f.ret != UNIT:
            res = s.fresh("result", f.ret)
            if isinstance(res, Arr):
                st.pc.append(z3.And(res.n >= 0, res.n <= MAX_LEN))
                if res.elem == U8:
                    st.pc.append(u8_dom(res))
            elif isinstance(res, Map):
                st.pc.append(z3.And(res.n >= 0, res.n <= MAX_LEN))
            else:
                w = s.wf(f.ret, res)
                if w is not None:
                    st.pc.append(w)
            env["result"] = res
        prev = []
        for en in f.ensures:
            prev.extend(s.check_dom(st, prev, en, en, "variant_field lookups in postcondition (line %d) are defined"
                                    % en.line, env))
            prev.append(s.ev(en, st, [], False, env))

    def run(s):
        f = s.f
        env, pc = {}, []
        for p in f.params:
            v = s.fresh(p.name, p.type)
            if isinstance(v, Arr):
                pc.append(z3.And(v.n >= 0, v.n <= MAX_LEN))
                if v.elem == U8:
                    pc.append(u8_dom(v))
            elif isinstance(v, Map):    # G6 A1
                pc.append(z3.And(v.n >= 0, v.n <= MAX_LEN))
            else:
                w = s.wf(p.type, v)
                if w is not None:
                    pc.append(w)
            env[p.name] = v
        s.params = dict(env)
        # G5 A1 (5.1): the immutable entry snapshots of the inout parameters; the executable name starts as the same
        # array and is rebound by element stores, calls and loop havoc, never the snapshot
        s.snap = {p.name: env[p.name] for p in f.params if p.mode is not None}
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
        if f.decreases is not None and f.foreign is None:
            # G9 A1 (G9_SPEC 5): the measure is defined and >= 0 under the requires at every entry (errors point to the
            # clause); its value is frozen here and is the caller measure of every recursive call in the body
            s.check_dom(st, [], f.decreases, f.decreases, "variant_field lookups in the decreases clause are defined")
            s.m0 = s.ev(f.decreases, st, [], False)
            s.prove(st, [], s.m0 >= 0, f.decreases, "recursive_nonneg",
                    "decreases measure `%s` >= 0 at function entry" % _expr_text(f.decreases))
        if f.foreign is not None:       # G6 A1 (11.4): a trusted declaration has no body and no ensures proof
            s.run_foreign(st)
            return
        for end in s.exec_block(f.body, st):
            if f.ret == UNIT:
                s.ensures_ok(end, None, f)


def verify_program(prog, rec=None, infer=False, report=None):
    """infer=True (STAGE1 B2, --infer): per function, explore template invariant candidates (infer.py), then
    verify the whole function with the survivors as extra loop invariants. report (a list) receives one record
    per loop (docs/STAGE1_B_INFER.md section 5). infer=False: exactly the old path."""
    from typeinfo import g2_unimplemented_error, s5_unimplemented_error
    s5err = s5_unimplemented_error(prog)
    if s5err is not None:
        return [s5err]
    # G3 A2: the verifier handles generics (no guard here); the code generators and pruvc.py still reject them.
    # "array" in skip exempts only the structured [T] (the plain [i64] is never a G2 hit).
    g2err = g2_unimplemented_error(prog, "verify", skip=("array_u8", "array_bool", "str", "array"))  # G2 B1
    if g2err is not None:
        return [g2err]
    errors = []
    model = Model(prog)
    if not infer:
        for f in prog.functions:
            FnVerifier(prog, f, errors, model, rec=rec).run()
        return errors
    import infer as infer_mod      # lazy: infer.py imports this module
    for f in prog.functions:
        res = infer_mod.infer_function(prog, f, model, rec)
        before = len(errors)
        if res.status == "timeout":
            errors.append(PruvError(
                "verify", f.line, f.col, "inference_timeout",
                "invariant inference for %s hit the time safety limit (5 s per function, 500 ms per query)" % f.name,
                "write the loop invariants explicitly, or compile without --infer", file=f.file))
        else:
            FnVerifier(prog, f, errors, model, rec=rec, extra=res.extra()).run()
        if report is not None:
            report.extend(res.records(len(errors) - before))
    return errors
