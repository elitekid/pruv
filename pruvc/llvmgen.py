"""Pruv -> LLVM IR (text) + Rust bindings.  gen_llvm(prog, verified=True, trust_callers=False, budget=1 << 30)
returns (ir_text, rust_bindings_text).  Semantics reference: codegen.py (Rust back end);
format spec: docs/M1_LLVM_SPEC.md.

Modes (two independent axes, same meaning as codegen.py):
  verified=True   Output of a program the verifier proved: + - * are `add/sub/mul nsw`, unary - is
                  `sub nsw 0, x`, / and % are `udiv/urem` (verifier proved dividend >= 0, divisor > 0),
                  array accesses are `getelementptr inbounds` without checks.  No checks at all.
  verified=False  (--no-verify, "safe mode") nothing is assumed: + - * and unary - use
                  llvm.s*.with.overflow.i64 (fail -> pruv_panic_arith "overflow in +" ...), / and %
                  check `divisor > 0 && dividend >= 0` (fail -> "division outside domain: ..."),
                  index read/write checks 0 <= i < len (fail -> pruv_panic_oob), alloc(n, v) checks
                  0 <= n <= 2^40.  No `nsw` is ever emitted in safe mode.
  trust_callers=False (default)  the entry function checks every `requires` (i128) before the body;
                  trust_callers=True: entry calls the body without checks.

Generated names (user identifiers never start with `pruv_` nor contain `__`, so no collisions):
  @f__pruv_body    internal; the function body.  Inner calls: verified -> f__pruv_body (the caller proved
                  requires), safe -> f__pruv_entry.
  @f__pruv_entry   internal; evaluates requires (declaration order, first failure panics with
                  pruv_panic_requires(fn, show(expr))) and calls the body.
  @pruv_abi_f      external C-ABI wrapper used by the Rust bindings (bool -> i64, Option/Result args as
                  two i64, array results through a trailing `ptr out`, Option/Result results by value as { i64, i64 }).
  @pruv_cdiv/@pruv_crem  internal i128 Euclidean division for requires (only if some entry checks).
  @.str.N         private string constants.
Local IR names: %tN temporaries, %lN.name.{a,b} local slots (entry-block alloca), %p.name parameters,
%qN.* quantifier slots, labels `hint.N` (per-function counters).

Ownership of arrays is tracked at compile time (borrowed params; alloc/copy/array-returning call
results are owned).  Block-scoped locals are freed (pruv_free) in reverse declaration order when the
block ends or at `return`; `a = f(..)` frees the old value after evaluating the right side; call-result
temporaries are freed at the end of the statement/condition (only on the executed path).
"""
import re
from vast import *
import codegen
from codegen import show
from typeinfo import TypeTable, is_user_type, is_array, uses_array_type, uses_str  # G2 B2: uses_str

SIGNED_MIN128 = -170141183460469231731687303715884105728
OPT = "{ i1, i64 }"
COPT = "{ i1, i128 }"       # Option/Result stored inside a contract aggregate (%pruv_c_*)
ARR = "{ ptr, i64 }"

# G1 (docs/M2_G1_SPEC.md section 5): user struct/enum layout
#   %pruv_t_Name  struct: its fields in order ({} if none); enum: { i64 tag, every variant's payload fields in
#                variant order then field order }.  Inactive payload is always zeroinitializer-derived.
#   %pruv_c_Name  same shape for requires evaluation: integer leaves are i128, Option/Result are { i1, i128 }.

DECLS = """\
declare noalias ptr @pruv_alloc(i64, i64) nounwind
declare noalias ptr @pruv_copy(ptr nocapture readonly, i64) nounwind
declare void @pruv_free(ptr nocapture, i64) nounwind
declare void @pruv_print_i64(i64) nounwind
declare void @pruv_print_bool(i64) nounwind
declare void @pruv_panic_oob(i64, i64) noreturn cold nounwind
declare void @pruv_panic_arith(ptr) noreturn cold nounwind
declare void @pruv_panic_requires(ptr, ptr) noreturn cold nounwind
declare void @pruv_panic_undefined(ptr) noreturn cold nounwind
declare { i64, i1 } @llvm.sadd.with.overflow.i64(i64, i64)
declare { i64, i1 } @llvm.ssub.with.overflow.i64(i64, i64)
declare { i64, i1 } @llvm.smul.with.overflow.i64(i64, i64)
declare { i128, i1 } @llvm.sadd.with.overflow.i128(i128, i128)
declare { i128, i1 } @llvm.ssub.with.overflow.i128(i128, i128)
declare { i128, i1 } @llvm.smul.with.overflow.i128(i128, i128)
"""

# G2 A4 (docs/G2_A4_IMPL.md 2.9): only emitted when the program uses [u8]
DECLS_U8 = """\
declare noalias ptr @pruv_alloc_u8(i64, i64) nounwind
declare noalias ptr @pruv_copy_v2(ptr nocapture readonly, i64, i64, i64) nounwind
declare void @pruv_free_v2(ptr nocapture, i64, i64, i64) nounwind
declare void @pruv_panic_elem(i64, ptr) noreturn cold nounwind
"""


# G2 A5 (docs/G2_A5_IMPL.md 4.2): only emitted when the program uses [bool]
DECLS_BOOL = "declare void @pruv_check_bool(ptr nocapture readonly, i64) nounwind\n"

# G2 B2 (docs/G2_B2_IMPL.md 2.7): only emitted when the program uses str
DECLS_STR = ("declare i32 @pruv_str_boundary(ptr nocapture readonly, i64, i64) nounwind willreturn memory(argmem: read)\n"
             "declare noalias ptr @pruv_substr(ptr nocapture readonly, i64, i64, i64) nounwind\n"
             "declare void @pruv_check_utf8(ptr nocapture readonly, i64) nounwind\n")


def is_arr(t):  # G2 B2: array-like type (arrays and str share the { ptr, i64 } representation)
    return is_array(t) or t.name == "str"


def elem_ty(t):
    """element info carried in V/Slot.ty of an array: ARRAY_U8 for [u8], ARRAY_BOOL for [bool], STR for str,
    None for [i64]"""
    if t is not None and t.name == "array_u8":
        return ARRAY_U8
    if t is not None and t.name == "array_bool":  # G2 A5
        return ARRAY_BOOL
    if t is not None and t.name == "str":  # G2 B2
        return STR
    return None


def is_u8(v):
    return v.ty is not None and v.ty.name == "array_u8"


def is_bytes(v):  # G2 A5/B2: byte-sized element arrays ([u8], [bool] or str)
    return v.ty is not None and v.ty.name in ("array_u8", "array_bool", "str")


def is_strv(v):  # G2 B2
    return v.ty is not None and v.ty.name == "str"


def is_boolarr(v):  # G2 A5
    return v.ty is not None and v.ty.name == "array_bool"


def mangle(n):
    return re.sub(r"[^A-Za-z0-9_]", lambda m: "$%04x" % ord(m.group()), n)


# G3 A4 (docs/G3_SPEC.md 5.4/5.5): the back end consumes the concrete specialization plan (mono.py), so no type
# parameter ever reaches it.  New built-in applications Option<X> / Result<X> with X != i64 are ordinary aggregates
# (V.k == "agg", V.ty = the Option/Result type with its argument):
#   Option<X>  { i1 present, L(X) payload }                 contract form { i1, Lc(X) }
#   Result<X>  { i1 is_ok, L(X) ok_payload, i64 error }     contract form { i1, Lc(X), i128 }
# Unused payload storage is zero (every constructor starts from zeroinitializer, deserialization masks inactive
# words); equality and selectors look only at the active payload.  Legacy Option<i64>/Result<i64> are unchanged.
G3_TYPE_PREFIX = "pruv_g3_t_"
DECLS_REPR = "declare void @pruv_panic_repr(i64, ptr) noreturn cold nounwind\n"


def gopt(t):
    """True for a new built-in application Option<X> / Result<X> (X != i64); False for the legacy constants"""
    return t.name in ("option", "result") and bool(t.args) and t.owner is None


def is_agg(t):
    """user struct/enum (incl. generated generic instances) or a new Option/Result application"""
    return is_user_type(t) or gopt(t)


def is_new_app(t):
    """types whose external word form follows the G3 rules (tag normalization, inactive words zero, enum check)"""
    return gopt(t) or (is_user_type(t) and t.name.startswith(G3_TYPE_PREFIX))


def lty(t):
    """internal SSA type of a Pruv type"""
    if gopt(t):
        return st(t)
    r = {"i64": "i64", "bool": "i1", "unit": "void", "array": ARR, "array_u8": ARR, "array_bool": ARR,
         "str": ARR, "option": OPT, "result": OPT}.get(t.name)
    return r if r is not None else "%%pruv_t_%s" % t.name


def vkind(t):
    if gopt(t):
        return "agg"
    return {"i64": "i64", "bool": "i1", "unit": "unit", "array": "arr", "array_u8": "arr", "array_bool": "arr",
            "str": "arr", "option": "opt", "result": "opt"}.get(t.name, "agg")


def st(t, c=False):
    """storage type of a value of type t inside an aggregate (c: contract/i128 form)"""
    n = t.name
    if gopt(t):
        x = st(t.args[0], c)
        if n == "option":
            return "{ i1, %s }" % x
        return "{ i1, %s, %s }" % (x, "i128" if c else "i64")
    if n == "i64":
        return "i128" if c else "i64"
    if n == "bool":
        return "i1"
    if n in ("option", "result"):
        return COPT if c else OPT
    return "%%pruv_%s_%s" % ("c" if c else "t", n)


def payload_index(tt, ty, variant, i):
    """storage index of field i of `variant` inside the flattened enum %pruv_t_/%pruv_c_ type"""
    base = 1
    for v in tt.decl(ty).variants:
        if v.name == variant:
            return base + i
        base += len(v.fields)
    raise KeyError(variant)


def words(tt, ty):
    """W(T): number of i64 words of the external (pruv_abi_*) form.  Memoized per type table (a nested generic
    value would otherwise recompute every subtree: quadratic)."""
    memo = tt.__dict__.setdefault("_words_memo", {})
    r = memo.get(ty)
    if r is not None:
        return r
    n = ty.name
    if n in ("i64", "bool"):
        r = 1
    elif gopt(ty):  # G3: 1 + W(X) (+ 1 for the Result error word)
        r = 1 + words(tt, ty.args[0]) + (1 if n == "result" else 0)
    elif n in ("option", "result"):
        r = 2
    else:
        d = tt.decl(ty)
        if isinstance(d, StructDecl):
            r = max(1, sum(words(tt, f.type) for f in d.fields))
        else:
            r = 1 + sum(words(tt, f.type) for v in d.variants for f in v.fields)
    memo[ty] = r
    return r


def type_defs(tt):
    out = []
    for c in (False, True):
        for d in tt.order:
            if isinstance(d, StructDecl):
                fs = [st(f.type, c) for f in d.fields]
            else:
                fs = ["i64"] + [st(f.type, c) for v in d.variants for f in v.fields]
            out.append("%%pruv_%s_%s = type %s" % ("c" if c else "t", d.name, "{ %s }" % ", ".join(fs) if fs else "{}"))
    return "\n".join(out) + ("\n" if out else "")


class V:
    """an SSA value: k in i64 | i1 | i128 | arr (a=ptr, b=len) | opt (a=tag i1, b=payload) | unit |
    agg (a=aggregate SSA of a user struct/enum, ty=its Type; %pruv_t_* in code, %pruv_c_* in requires)"""
    __slots__ = ("k", "a", "b", "ty")

    def __init__(s, k, a=None, b=None, ty=None):
        s.k, s.a, s.b, s.ty = k, a, b, ty


class Slot:
    __slots__ = ("k", "a", "b", "ty")

    def __init__(s, k, a, b=None, ty=None):
        s.k, s.a, s.b, s.ty = k, a, b, ty


class Mod:
    def __init__(s, tt=None):
        s.tt = tt
        s.strs = {}
        s.order = []
        s.uses_repr = False     # G3: the wrappers reject an invalid enum ordinal through pruv_panic_repr

    def string(s, text):
        if text not in s.strs:
            s.strs[text] = "@.str.%d" % len(s.order)
            s.order.append(text)
        return s.strs[text]

    def render_strings(s):
        out = []
        for text in s.order:
            b = text.encode("utf-8")
            body = "".join(chr(c) if 32 <= c < 127 and c not in (34, 92) else "\\%02X" % c for c in b)
            out.append('%s = private unnamed_addr constant [%d x i8] c"%s\\00"' % (s.strs[text], len(b) + 1, body))
        return "\n".join(out) + ("\n" if out else "")


def ir_params(f):
    """internal parameter list [(type, name)]"""
    out = []
    for p in f.params:
        n = mangle(p.name)
        if is_arr(p.type):
            out += [("ptr", "%%p.%s.a" % n), ("i64", "%%p.%s.n" % n)]
        elif p.type == BOOL:
            out.append(("i1", "%%p.%s" % n))
        elif p.type == I64:
            out.append(("i64", "%%p.%s" % n))
        elif is_agg(p.type):
            out.append((lty(p.type), "%%p.%s" % n))
        else:
            out.append((OPT, "%%p.%s" % n))
    return out


def sig_text(params):
    """definition parameter list of an internal function: array pointers are read-only borrows"""
    return ", ".join("%s %s" % ("ptr noalias nocapture readonly" if t == "ptr" else t, n) for t, n in params)


class FnGen:
    def __init__(s, m, funcs, f, verified):
        s.m, s.funcs, s.f, s.verified = m, funcs, f, verified
        s.lines = []
        s.allocas = []
        s.nt = s.nl = s.nslot = s.nq = 0
        s.cur = None
        s.dead = False
        s.scopes = []
        s.temps = []
        s.cenv = {}
        s.tt = m.tt

    # ---------- emission ----------
    def ins(s, text):
        if s.dead:
            raise Exception("llvmgen: internal error: instruction after terminator: %s" % text)
        s.lines.append("  " + text)

    def term(s, text):
        s.ins(text)
        s.dead = True

    def tmp(s):
        s.nt += 1
        return "%%t%d" % s.nt

    def op(s, text):
        r = s.tmp()
        s.ins("%s = %s" % (r, text))
        return r

    def label(s, hint):
        s.nl += 1
        return "%s.%d" % (hint, s.nl)

    def place(s, lbl):
        s.lines.append(lbl + ":")
        s.cur = lbl
        s.dead = False

    def br(s, l):
        s.term("br label %%%s" % l)

    def condbr(s, c, a, b):
        s.term("br i1 %s, label %%%s, label %%%s" % (c, a, b))

    def guard(s, cond, failfn, fail_when):
        """continue only when cond != fail_when; else run failfn (a noreturn call) in a fail block"""
        ok, bad = s.label("ok"), s.label("fail")
        if fail_when:
            s.condbr(cond, bad, ok)
        else:
            s.condbr(cond, ok, bad)
        s.place(bad)
        failfn()
        s.term("unreachable")
        s.place(ok)

    def panic1(s, fn, msg):
        return lambda: s.ins("call void @%s(ptr %s)" % (fn, s.m.string(msg)))

    def panic_elem(s, x):
        return lambda: s.ins("call void @pruv_panic_elem(i64 %s, ptr %s)" % (x, s.m.string("u8 0..=255")))

    def render(s, header):
        out = [header + " {", "entry:"] + ["  " + a for a in s.allocas] + ["  br label %start"]
        out += s.lines
        out.append("}")
        return "\n".join(out) + "\n"

    # ---------- slots / scopes ----------
    def new_slot(s, name, ty, prefix="l"):
        kind = vkind(ty)
        base = "%%%s%d.%s" % (prefix, s.nslot, mangle(name))
        s.nslot += 1
        a, b = base + ".a", base + ".b"
        if kind == "i64":
            s.allocas.append("%s = alloca i64" % a)
            return Slot("i64", a)
        if kind == "i1":
            s.allocas.append("%s = alloca i1" % a)
            return Slot("i1", a)
        if kind == "arr":
            s.allocas.append("%s = alloca ptr" % a)
            s.allocas.append("%s = alloca i64" % b)
            return Slot("arr", a, b, elem_ty(ty))
        if kind == "agg":
            s.allocas.append("%s = alloca %s" % (a, lty(ty)))
            return Slot("agg", a, None, ty)
        s.allocas.append("%s = alloca i1" % a)
        s.allocas.append("%s = alloca i64" % b)
        return Slot("opt", a, b)

    def load(s, sl):
        if sl.k in ("i64", "i1"):
            return V(sl.k, s.op("load %s, ptr %s" % (sl.k, sl.a)))
        if sl.k == "agg":
            return V("agg", s.op("load %s, ptr %s" % (lty(sl.ty), sl.a)), None, sl.ty)
        if sl.k == "arr":
            p = s.op("load ptr, ptr %s" % sl.a)
            n = s.op("load i64, ptr %s" % sl.b)
            return V("arr", p, n, sl.ty)
        t = s.op("load i1, ptr %s" % sl.a)
        v = s.op("load i64, ptr %s" % sl.b)
        return V("opt", t, v)

    def store(s, sl, v):
        if sl.k in ("i64", "i1"):
            s.ins("store %s %s, ptr %s" % (sl.k, v.a, sl.a))
        elif sl.k == "agg":
            s.ins("store %s %s, ptr %s" % (lty(sl.ty), v.a, sl.a))
        elif sl.k == "arr":
            s.ins("store ptr %s, ptr %s" % (v.a, sl.a))
            s.ins("store i64 %s, ptr %s" % (v.b, sl.b))
        else:
            s.ins("store i1 %s, ptr %s" % (v.a, sl.a))
            s.ins("store i64 %s, ptr %s" % (v.b, sl.b))

    def lookup(s, name):
        for sc in reversed(s.scopes):
            if name in sc["names"]:
                return sc["names"][name]
        raise Exception("llvmgen: unknown variable %s" % name)

    def push_scope(s):
        s.scopes.append({"names": {}, "arrays": []})

    def free_val(s, v):
        if is_bytes(v):  # G2 A5
            s.ins("call void @pruv_free_v2(ptr %s, i64 %s, i64 1, i64 1)" % (v.a, v.b))
        else:
            s.ins("call void @pruv_free(ptr %s, i64 %s)" % (v.a, v.b))

    def free_scope(s, sc):
        for sl in reversed(sc["arrays"]):
            s.free_val(s.load(sl))

    def pop_scope(s):
        sc = s.scopes.pop()
        if not s.dead:
            s.free_scope(sc)

    def begin_temps(s):
        s.temps.append([])

    def end_temps(s):
        ts = s.temps.pop()
        if not s.dead:
            for v in reversed(ts):
                s.free_val(v)

    # ---------- user aggregates (G1) ----------
    def pack(s, v, ty, c):
        """SSA value of storage type st(ty, c) for the value v"""
        if ty.name in ("option", "result") and not gopt(ty):
            ot, pt = (COPT, "i128") if c else (OPT, "i64")
            a = s.op("insertvalue %s undef, i1 %s, 0" % (ot, v.a))
            return s.op("insertvalue %s %s, %s %s, 1" % (ot, a, pt, v.b))
        return v.a

    def unpack(s, x, ty, c):
        n = ty.name
        if n == "i64":
            return V("i128" if c else "i64", x)
        if n == "bool":
            return V("i1", x)
        if n in ("option", "result") and not gopt(ty):
            ot = COPT if c else OPT
            t = s.op("extractvalue %s %s, 0" % (ot, x))
            p = s.op("extractvalue %s %s, 1" % (ot, x))
            return V("opt", t, p)
        return V("agg", x, None, ty)

    def put(s, base, ty, idx, v, fty, c):
        """insertvalue of field value v (type fty) at storage index idx of aggregate `base` (type ty)"""
        x = s.pack(v, fty, c)
        return s.op("insertvalue %s %s, %s %s, %d" % (st(ty, c), base, st(fty, c), x, idx))

    def get(s, base, ty, idx, fty, c):
        x = s.op("extractvalue %s %s, %d" % (st(ty, c), base.a, idx))
        return s.unpack(x, fty, c)

    def tag_of(s, v, c):
        return s.op("extractvalue %s %s, 0" % (st(v.ty, c), v.a))

    def mk_struct(s, e, evf, c):
        ty = Type(e.name)
        vals = {}
        for fi in e.fields:                 # source order evaluation
            vals[fi.name] = evf(fi.value)
        acc = "zeroinitializer"
        for i, fd in enumerate(s.tt.fields(ty)):
            acc = s.put(acc, ty, i, vals[fd.name], fd.type, c)
        return V("agg", acc, None, ty)

    def mk_enum(s, e, evf, c):
        ty = Type(e.enum_name)
        vals = [evf(x) for x in e.args]     # left to right
        tag = s.tt.variant_index(ty, e.variant)
        acc = s.op("insertvalue %s zeroinitializer, i64 %d, 0" % (st(ty, c), tag))
        for i, fd in enumerate(s.tt.fields(ty, e.variant)):
            acc = s.put(acc, ty, payload_index(s.tt, ty, e.variant, i), vals[i], fd.type, c)
        return V("agg", acc, None, ty)

    def mk_gctor(s, e, evf, c):
        """Some/None/Ok/Err of a new Option<X>/Result<X> application (e.ty): zeroinitializer-based, so the unused
        payload storage is always zero"""
        ty = e.ty
        if e.name == "None":
            return V("agg", "zeroinitializer", None, ty)
        x = evf(e.arg)
        if e.name in ("Some", "Ok"):
            acc = s.op("insertvalue %s zeroinitializer, i1 true, 0" % st(ty, c))
            return V("agg", s.put(acc, ty, 1, x, ty.args[0], c), None, ty)
        # Err: tag false (zero), error payload in slot 2
        return V("agg", s.op("insertvalue %s zeroinitializer, %s %s, 2" % (st(ty, c), "i128" if c else "i64", x.a)),
                 None, ty)

    def gmatch(s, st_, sv):
        """match on a new Option<X>/Result<X>: branch on the tag, bind the active payload only inside its arm"""
        ty = sv.ty
        X = ty.args[0]
        pos = [a for a in st_.arms if a.ctor in ("Some", "Ok")][0]
        neg = [a for a in st_.arms if a.ctor in ("None", "Err")][0]
        tag = s.op("extractvalue %s %s, 0" % (st(ty), sv.a))
        pl, nl_, end = s.label("armT"), s.label("armF"), s.label("endmatch")
        s.condbr(tag, pl, nl_)
        reach = False
        for arm, lbl in ((pos, pl), (neg, nl_)):
            s.place(lbl)
            bind = None
            if arm.binders:
                if arm.ctor in ("Some", "Ok"):
                    bind = {arm.binders[0]: ("ssa", s.get(sv, ty, 1, X, False))}
                else:
                    bind = {arm.binders[0]: ("ssa", V("i64", s.op("extractvalue %s %s, 2" % (st(ty), sv.a))))}
            if s.run_block(arm.body, bind):
                s.br(end)
                reach = True
        if reach:
            s.place(end)
        else:
            s.dead = True

    def set_path(s, base, ty, path, v):
        """aggregate `base` (code form) with the nested struct field `path` replaced by v"""
        fds = s.tt.fields(ty)
        i = s.tt.field_index(ty, path[0])
        fty = fds[i].type
        if len(path) == 1:
            nv = v
        else:
            sub = s.get(base, ty, i, fty, False)
            nv = s.set_path(sub, fty, path[1:], v)
        return V("agg", s.put(base.a, ty, i, nv, fty, False), None, ty)

    def to_c(s, x, ty):
        """code value -> contract value (i64 leaves sign-extended; enums convert the active variant only)"""
        n = ty.name
        if n == "i64":
            return V("i128", s.op("sext i64 %s to i128" % x.a))
        if n == "bool":
            return x
        if gopt(ty):  # G3: widen the payload (and the Result error); the unused payload stays zero
            X = ty.args[0]
            t = s.op("extractvalue %s %s, 0" % (st(ty), x.a))
            acc = s.op("insertvalue %s zeroinitializer, i1 %s, 0" % (st(ty, True), t))
            acc = s.put(acc, ty, 1, s.to_c(s.get(x, ty, 1, X, False), X), X, True)
            if n == "result":
                er = s.op("extractvalue %s %s, 2" % (st(ty), x.a))
                ec = s.op("sext i64 %s to i128" % er)
                acc = s.op("insertvalue %s %s, i128 %s, 2" % (st(ty, True), acc, ec))
            return V("agg", acc, None, ty)
        if n in ("option", "result"):
            return V("opt", x.a, s.op("sext i64 %s to i128" % x.b))
        d = s.tt.decl(ty)
        if isinstance(d, StructDecl):
            acc = "zeroinitializer"
            for i, f in enumerate(d.fields):
                fx = s.get(x, ty, i, f.type, False)
                acc = s.put(acc, ty, i, s.to_c(fx, f.type), f.type, True)
            return V("agg", acc, None, ty)
        tag = s.tag_of(x, False)
        base = s.op("insertvalue %s zeroinitializer, i64 %s, 0" % (st(ty, True), tag))
        vs = [v for v in d.variants if v.fields]
        if not vs:
            return V("agg", base, None, ty)
        lcur, join = s.cur, s.label("cvend")
        lbls = [s.label("cvv") for _ in vs]
        s.term("switch i64 %s, label %%%s [ %s ]" % (tag, join, " ".join(
            "i64 %d, label %%%s" % (s.tt.variant_index(ty, v.name), l) for v, l in zip(vs, lbls))))
        entries = [(base, lcur)]
        for v, l in zip(vs, lbls):
            s.place(l)
            acc = base
            for i, f in enumerate(v.fields):
                pi = payload_index(s.tt, ty, v.name, i)
                fx = s.get(x, ty, pi, f.type, False)
                acc = s.put(acc, ty, pi, s.to_c(fx, f.type), f.type, True)
            entries.append((acc, s.cur))
            s.br(join)
        s.place(join)
        r = s.op("phi %s %s" % (st(ty, True), ", ".join("[ %s, %%%s ]" % e for e in entries)))
        return V("agg", r, None, ty)

    def ceq(s, l, r, ty):
        """structural equality of two contract values of type ty -> i1 (SSA name or literal)"""
        n = ty.name
        if n == "i64":
            return s.op("icmp eq i128 %s, %s" % (l.a, r.a))
        if n == "bool":
            return s.op("icmp eq i1 %s, %s" % (l.a, r.a))
        if gopt(ty):  # G3: only the active payload is compared
            X = ty.args[0]
            T = st(ty, True)
            tl = s.op("extractvalue %s %s, 0" % (T, l.a))
            tr = s.op("extractvalue %s %s, 0" % (T, r.a))
            te = s.op("icmp eq i1 %s, %s" % (tl, tr))
            pe = s.ceq(s.get(l, ty, 1, X, True), s.get(r, ty, 1, X, True), X)
            nt = s.op("xor i1 %s, true" % tl)
            if n == "option":
                return s.op("and i1 %s, %s" % (te, s.op("or i1 %s, %s" % (nt, pe))))
            el = s.op("extractvalue %s %s, 2" % (T, l.a))
            er = s.op("extractvalue %s %s, 2" % (T, r.a))
            ee = s.op("icmp eq i128 %s, %s" % (el, er))
            act = s.op("or i1 %s, %s" % (s.op("and i1 %s, %s" % (tl, pe)), s.op("and i1 %s, %s" % (nt, ee))))
            return s.op("and i1 %s, %s" % (te, act))
        if n in ("option", "result"):
            te = s.op("icmp eq i1 %s, %s" % (l.a, r.a))
            pe = s.op("icmp eq i128 %s, %s" % (l.b, r.b))
            if n == "option":           # a None payload is not compared
                nt = s.op("xor i1 %s, true" % l.a)
                pe = s.op("or i1 %s, %s" % (nt, pe))
            return s.op("and i1 %s, %s" % (te, pe))

        def fields_eq(fds, pidx):
            acc = "true"
            for i, f in enumerate(fds):
                j = pidx(i)
                e = s.ceq(s.get(l, ty, j, f.type, True), s.get(r, ty, j, f.type, True), f.type)
                acc = e if acc == "true" else s.op("and i1 %s, %s" % (acc, e))
            return acc
        d = s.tt.decl(ty)
        if isinstance(d, StructDecl):
            return fields_eq(d.fields, lambda i: i)
        tl, tr = s.tag_of(l, True), s.tag_of(r, True)
        teq = s.op("icmp eq i64 %s, %s" % (tl, tr))
        vs = [v for v in d.variants if v.fields]
        if not vs:
            return teq
        lcur = s.cur
        same, dflt, end = s.label("ceqs"), s.label("ceqd"), s.label("ceqe")
        lbls = [s.label("ceqv") for _ in vs]
        s.condbr(teq, same, end)
        entries = [("false", lcur)]
        s.place(same)
        s.term("switch i64 %s, label %%%s [ %s ]" % (tl, dflt, " ".join(
            "i64 %d, label %%%s" % (s.tt.variant_index(ty, v.name), lb) for v, lb in zip(vs, lbls))))
        s.place(dflt)           # same tag, variant without fields
        entries.append(("true", dflt))
        s.br(end)
        for v, lb in zip(vs, lbls):
            s.place(lb)
            e = fields_eq(v.fields, lambda i, v=v: payload_index(s.tt, ty, v.name, i))
            entries.append((e, s.cur))
            s.br(end)
        s.place(end)
        return s.op("phi i1 %s" % ", ".join("[ %s, %%%s ]" % e for e in entries))

    def agg(s, v):
        if v.k == "agg":
            return v.a
        if v.k == "arr":
            a = s.op("insertvalue %s undef, ptr %s, 0" % (ARR, v.a))
            return s.op("insertvalue %s %s, i64 %s, 1" % (ARR, a, v.b))
        a = s.op("insertvalue %s undef, i1 %s, 0" % (OPT, v.a))
        return s.op("insertvalue %s %s, i64 %s, 1" % (OPT, a, v.b))

    # ---------- function frame ----------
    def bind_params(s):
        s.place("start")
        names = {}
        for p in s.f.params:
            n = mangle(p.name)
            if is_arr(p.type):
                names[p.name] = ("ssa", V("arr", "%%p.%s.a" % n, "%%p.%s.n" % n, elem_ty(p.type)))
            elif p.type == BOOL:
                names[p.name] = ("ssa", V("i1", "%%p.%s" % n))
            elif p.type == I64:
                names[p.name] = ("ssa", V("i64", "%%p.%s" % n))
            elif is_agg(p.type):
                names[p.name] = ("ssa", V("agg", "%%p.%s" % n, None, p.type))
            else:
                t = s.op("extractvalue %s %%p.%s, 0" % (OPT, n))
                v = s.op("extractvalue %s %%p.%s, 1" % (OPT, n))
                names[p.name] = ("ssa", V("opt", t, v))
        s.scopes.append({"names": names, "arrays": []})

    def emit_ret(s, v):
        rt = s.f.ret
        if rt == UNIT:
            s.term("ret void")
        elif rt in (I64, BOOL):
            s.term("ret %s %s" % (lty(rt), v.a))
        else:
            g = s.agg(v)
            s.term("ret %s %s" % (lty(rt), g))

    # ---------- statements ----------
    def run_block(s, stmts, bind=None):
        """lower a block in its own scope; returns True if control can fall through"""
        s.push_scope()
        if bind:
            s.scopes[-1]["names"].update(bind)
        for st in stmts:
            s.stmt(st)
            if s.dead:
                break
        s.pop_scope()
        return not s.dead

    def body(s):
        s.bind_params()
        falls = s.run_block(s.f.body)
        if falls:
            if s.f.ret == UNIT:
                s.term("ret void")
            else:
                s.term("unreachable")

    def stmt(s, st):
        if isinstance(st, Let):
            s.begin_temps()
            v = s.ev(st.value, True)
            sl = s.new_slot(st.name, st.type)
            s.store(sl, v)
            sc = s.scopes[-1]
            sc["names"][st.name] = ("slot", sl)
            if sl.k == "arr":
                sc["arrays"].append(sl)
            s.end_temps()
        elif isinstance(st, Assign):
            s.begin_temps()
            sl = s.lookup(st.name)[1]
            v = s.ev(st.value, True)
            if sl.k == "arr":
                s.free_val(s.load(sl))
            s.store(sl, v)
            s.end_temps()
        elif isinstance(st, FieldAssign):
            s.begin_temps()
            kind, sl = s.lookup(st.name)
            if kind != "slot":
                raise Exception("llvmgen: field assignment to non-local %s" % st.name)
            v = s.ev(st.value)              # right side first, then root load -> insertvalue chain -> store
            root = s.load(sl)
            s.store(sl, s.set_path(root, sl.ty, st.fields, v))
            s.end_temps()
        elif isinstance(st, IndexAssign):
            s.begin_temps()
            sl = s.lookup(st.name)[1]
            i = s.ev(st.index)      # index first, then value, in every mode
            v = s.ev(st.value)
            a = s.load(sl)
            g = s.index_ptr(a, i)
            if is_boolarr(a):  # G2 A5
                z = s.op("zext i1 %s to i8" % v.a)
                s.ins("store i8 %s, ptr %s" % (z, g))
            elif is_u8(a):
                if not s.verified:
                    ok = s.op("icmp ule i64 %s, 255" % v.a)
                    s.guard(ok, s.panic_elem(v.a), False)
                b = s.op("trunc i64 %s to i8" % v.a)
                s.ins("store i8 %s, ptr %s" % (b, g))
            else:
                s.ins("store i64 %s, ptr %s" % (v.a, g))
            s.end_temps()
        elif isinstance(st, If):
            s.begin_temps()
            c = s.ev(st.cond)
            s.end_temps()
            thn, end = s.label("then"), s.label("endif")
            els = s.label("else") if st.els else end
            s.condbr(c.a, thn, els)
            s.place(thn)
            reach = False
            if s.run_block(st.then):
                s.br(end)
                reach = True
            if st.els:
                s.place(els)
                if s.run_block(st.els):
                    s.br(end)
                    reach = True
            else:
                reach = True
            if reach:
                s.place(end)
            else:
                s.dead = True
        elif isinstance(st, While):
            cl, bl, el = s.label("wcond"), s.label("wbody"), s.label("wend")
            s.br(cl)
            s.place(cl)
            s.begin_temps()
            c = s.ev(st.cond)
            s.end_temps()
            s.condbr(c.a, bl, el)
            s.place(bl)
            if s.run_block(st.body):
                s.br(cl)
            s.place(el)
        elif isinstance(st, Return):
            s.begin_temps()
            v = V("unit")
            if st.value is not None:
                v = s.ev(st.value, True)
                if v.k == "arr" and isinstance(st.value, Var):
                    # moving a local array out: empty its slot so the cleanup below does not free it
                    sl = s.lookup(st.value.name)[1]
                    s.ins("store ptr null, ptr %s" % sl.a)
                    s.ins("store i64 0, ptr %s" % sl.b)
            s.end_temps()
            for sc in reversed(s.scopes):
                s.free_scope(sc)
            s.emit_ret(v)
        elif isinstance(st, Assert):
            pass
        elif isinstance(st, ExprStmt):
            s.begin_temps()
            s.ev(st.expr)
            s.end_temps()
        elif isinstance(st, Match):
            s.begin_temps()
            sv = s.ev(st.scrutinee)
            s.end_temps()
            if sv.k == "agg" and sv.ty is not None and gopt(sv.ty):  # G3: Option<X>/Result<X>, X != i64
                s.gmatch(st, sv)
                return
            if st.arms and st.arms[0].enum_name is not None:
                s.user_match(st, sv)
                return
            pos = [a for a in st.arms if a.ctor in ("Some", "Ok")][0]
            neg = [a for a in st.arms if a.ctor in ("None", "Err")][0]
            pl, nl_, end = s.label("armT"), s.label("armF"), s.label("endmatch")
            s.condbr(sv.a, pl, nl_)
            reach = False
            for arm, lbl in ((pos, pl), (neg, nl_)):
                s.place(lbl)
                bind = None
                if arm.binders:
                    bind = {arm.binders[0]: ("ssa", V("i64", sv.b))}
                if s.run_block(arm.body, bind):
                    s.br(end)
                    reach = True
            if reach:
                s.place(end)
            else:
                s.dead = True
        else:
            raise Exception("llvmgen: unsupported statement %r" % st)

    def user_match(s, st, sv):
        """match on a user enum: tag switch; payload extraction only inside the arm block; default unreachable"""
        ty = sv.ty
        tag = s.tag_of(sv, False)
        arms = [(a, s.label("arm" + a.ctor)) for a in st.arms]
        dflt, end = s.label("matchdef"), s.label("endmatch")
        s.term("switch i64 %s, label %%%s [ %s ]" % (tag, dflt, " ".join(
            "i64 %d, label %%%s" % (s.tt.variant_index(ty, a.ctor), l) for a, l in arms)))
        s.place(dflt)
        s.term("unreachable")
        reach = False
        for a, l in arms:
            s.place(l)
            bind = {}
            for i, (name, fd) in enumerate(zip(a.binders, s.tt.fields(ty, a.ctor))):
                bind[name] = ("ssa", s.get(sv, ty, payload_index(s.tt, ty, a.ctor, i), fd.type, False))
            if s.run_block(a.body, bind):
                s.br(end)
                reach = True
        if reach:
            s.place(end)
        else:
            s.dead = True

    # ---------- code expressions ----------
    def index_ptr(s, a, i):
        if not s.verified:
            ok = s.op("icmp ult i64 %s, %s" % (i.a, a.b))
            s.guard(ok, lambda: s.ins("call void @pruv_panic_oob(i64 %s, i64 %s)" % (i.a, a.b)), False)
        return s.op("getelementptr inbounds %s, ptr %s, i64 %s" % ("i8" if is_bytes(a) else "i64", a.a, i.a))  # G2 A5: bytes = u8|bool

    def checked(s, ty, name, sym, a, b):
        r = s.op("call { %s, i1 } @llvm.%s.with.overflow.%s(%s %s, %s %s)" % (ty, name, ty, ty, a, ty, b))
        v = s.op("extractvalue { %s, i1 } %s, 0" % (ty, r))
        o = s.op("extractvalue { %s, i1 } %s, 1" % (ty, r))
        if ty == "i64":
            s.guard(o, s.panic1("pruv_panic_arith", "overflow in " + sym), True)
        else:
            s.guard(o, s.panic1("pruv_panic_undefined", "i128 overflow in " + sym), True)
        return v

    def temp_arr(s, v, owned):
        if not owned:
            s.temps[-1].append(v)
        return v

    def shortcircuit(s, l, rhs, is_or):
        lcur = s.cur
        rl, el = s.label("rhs"), s.label("endsc")
        if is_or:
            s.condbr(l, el, rl)
        else:
            s.condbr(l, rl, el)
        s.place(rl)
        r = rhs()
        rcur = s.cur
        s.br(el)
        s.place(el)
        return s.op("phi i1 [ %s, %%%s ], [ %s, %%%s ]" % ("true" if is_or else "false", lcur, r, rcur))

    def ev(s, e, owned=False):
        if isinstance(e, IntLit):
            return V("i64", str(e.value))
        if isinstance(e, BoolLit):
            return V("i1", "true" if e.value else "false")
        if isinstance(e, Var):
            kind, x = s.lookup(e.name)
            return x if kind == "ssa" else s.load(x)
        if isinstance(e, Unary):
            x = s.ev(e.operand)
            if e.op == "!":
                return V("i1", s.op("xor i1 %s, true" % x.a))
            if s.verified:
                return V("i64", s.op("sub nsw i64 0, %s" % x.a))
            return V("i64", s.checked("i64", "ssub", "unary -", "0", x.a))
        if isinstance(e, Binary):
            return s.ev_binary(e)
        if isinstance(e, Index):
            a = s.ev(e.array)
            i = s.ev(e.index)
            g = s.index_ptr(a, i)
            if is_boolarr(a):  # G2 A5
                x = s.op("load i8, ptr %s" % g)
                return V("i1", s.op("icmp ne i8 %s, 0" % x))
            if is_u8(a) or is_strv(a):  # G2 B2: str reads like u8
                x = s.op("load i8, ptr %s" % g)
                return V("i64", s.op("zext i8 %s to i64" % x))
            return V("i64", s.op("load i64, ptr %s" % g))
        if isinstance(e, StrLit):  # G2 B2
            nm = s.m.string(e.value.decode("utf-8"))
            ln = str(len(e.value))
            p = s.op("call ptr @pruv_copy_v2(ptr %s, i64 %s, i64 1, i64 1)" % (nm, ln))
            return s.temp_arr(V("arr", p, ln, STR), owned)
        if isinstance(e, Ctor):
            if e.ty is not None and gopt(e.ty):  # G3
                return s.mk_gctor(e, s.ev, False)
            if e.name == "None":
                return V("opt", "false", "0")
            x = s.ev(e.arg)
            return V("opt", "true" if e.name in ("Some", "Ok") else "false", x.a)
        if isinstance(e, Call):
            return s.ev_call(e, owned)
        if isinstance(e, StructLit):
            return s.mk_struct(e, s.ev, False)
        if isinstance(e, EnumCtor):
            return s.mk_enum(e, s.ev, False)
        if isinstance(e, FieldAccess):
            b = s.ev(e.base)
            ty = b.ty if b.ty is not None else e.base.ty
            i = s.tt.field_index(ty, e.field)
            return s.get(b, ty, i, s.tt.fields(ty)[i].type, False)
        raise Exception("llvmgen: contract-only expression in code: %r" % e)

    def ev_binary(s, e):
        op = e.op
        if op in ("&&", "||"):
            l = s.ev(e.left)

            def rhs():
                s.begin_temps()
                r = s.ev(e.right)
                s.end_temps()
                return r.a
            return V("i1", s.shortcircuit(l.a, rhs, op == "||"))
        l = s.ev(e.left)
        r = s.ev(e.right)
        if op in ("+", "-", "*"):
            name = {"+": "add", "-": "sub", "*": "mul"}[op]
            if s.verified:
                return V("i64", s.op("%s nsw i64 %s, %s" % (name, l.a, r.a)))
            return V("i64", s.checked("i64", "s" + name, op, l.a, r.a))
        if op in ("/", "%"):
            if not s.verified:
                c1 = s.op("icmp sgt i64 %s, 0" % r.a)
                c2 = s.op("icmp sge i64 %s, 0" % l.a)
                ok = s.op("and i1 %s, %s" % (c1, c2))
                s.guard(ok, s.panic1("pruv_panic_arith",
                                     "division outside domain: need divisor > 0 and dividend >= 0"), False)
            return V("i64", s.op("%s i64 %s, %s" % ("udiv" if op == "/" else "urem", l.a, r.a)))
        cmp = {"==": "eq", "!=": "ne", "<": "slt", "<=": "sle", ">": "sgt", ">=": "sge"}[op]
        ty = "i1" if l.k == "i1" else "i64"
        return V("i1", s.op("icmp %s %s %s, %s" % (cmp, ty, l.a, r.a)))

    def ev_call(s, e, owned):
        n, a = e.name, e.args
        if n == "len":
            return V("i64", s.ev(a[0]).b)
        if n == "alloc":
            cnt = s.ev(a[0])        # source order in every mode: n then v
            v = s.ev(a[1])
            if not s.verified:
                ok = s.op("icmp ult i64 %s, 1099511627777" % cnt.a)
                s.guard(ok, s.panic1("pruv_panic_arith", "alloc length outside 0..2^40"), False)
            if e.ty is not None and e.ty.name == "array_bool":  # G2 A5
                z = s.op("zext i1 %s to i64" % v.a)
                p = s.op("call ptr @pruv_alloc_u8(i64 %s, i64 %s)" % (cnt.a, z))
                return s.temp_arr(V("arr", p, cnt.a, ARRAY_BOOL), owned)
            if e.ty is not None and e.ty.name == "array_u8":
                if not s.verified:
                    ok = s.op("icmp ule i64 %s, 255" % v.a)
                    s.guard(ok, s.panic_elem(v.a), False)
                p = s.op("call ptr @pruv_alloc_u8(i64 %s, i64 %s)" % (cnt.a, v.a))
                return s.temp_arr(V("arr", p, cnt.a, ARRAY_U8), owned)
            p = s.op("call ptr @pruv_alloc(i64 %s, i64 %s)" % (cnt.a, v.a))
            return s.temp_arr(V("arr", p, cnt.a), owned)
        if n == "copy":
            src = s.ev(a[0])
            if not s.verified:
                pass    # spec: same checks as proof mode (none)
            if is_bytes(src):  # G2 A5
                p = s.op("call ptr @pruv_copy_v2(ptr %s, i64 %s, i64 1, i64 1)" % (src.a, src.b))
                return s.temp_arr(V("arr", p, src.b, src.ty), owned)
            p = s.op("call ptr @pruv_copy(ptr %s, i64 %s)" % (src.a, src.b))
            return s.temp_arr(V("arr", p, src.b), owned)
        if n == "is_char_boundary":  # G2 B2: s then i
            sv = s.ev(a[0])
            iv = s.ev(a[1])
            r = s.op("call i32 @pruv_str_boundary(ptr %s, i64 %s, i64 %s)" % (sv.a, sv.b, iv.a))
            return V("i1", s.op("icmp ne i32 %s, 0" % r))
        if n == "substr":  # G2 B2: s, lo, hi in order
            sv = s.ev(a[0])
            lo = s.ev(a[1])
            hi = s.ev(a[2])
            if s.verified:
                d = s.op("sub i64 %s, %s" % (hi.a, lo.a))
                g = s.op("getelementptr inbounds i8, ptr %s, i64 %s" % (sv.a, lo.a))
                p = s.op("call ptr @pruv_copy_v2(ptr %s, i64 %s, i64 1, i64 1)" % (g, d))
            else:
                p = s.op("call ptr @pruv_substr(ptr %s, i64 %s, i64 %s, i64 %s)" % (sv.a, sv.b, lo.a, hi.a))
                d = s.op("sub i64 %s, %s" % (hi.a, lo.a))
            return s.temp_arr(V("arr", p, d, STR), owned)
        if n == "print":
            x = s.ev(a[0])
            if x.k == "i1":
                z = s.op("zext i1 %s to i64" % x.a)
                s.ins("call void @pruv_print_bool(i64 %s)" % z)
            else:
                s.ins("call void @pruv_print_i64(i64 %s)" % x.a)
            return V("unit")
        if n not in s.funcs:
            raise Exception("llvmgen: unsupported call in code: %s" % n)
        f = s.funcs[n]
        args = []
        for x in a:
            v = s.ev(x)
            if v.k == "arr":
                args += ["ptr %s" % v.a, "i64 %s" % v.b]
            elif v.k == "opt":
                args.append("%s %s" % (OPT, s.agg(v)))
            elif v.k == "agg":
                args.append("%s %s" % (lty(v.ty), v.a))
            else:
                args.append("%s %s" % (v.k, v.a))
        callee = "@%s__pruv_%s" % (mangle(f.name), "body" if s.verified else "entry")
        if f.ret == UNIT:
            s.ins("call void %s(%s)" % (callee, ", ".join(args)))
            return V("unit")
        r = s.op("call %s %s(%s)" % (lty(f.ret), callee, ", ".join(args)))
        if f.ret in (I64, BOOL):
            return V(vkind(f.ret), r)
        if is_agg(f.ret):
            return V("agg", r, None, f.ret)
        x0 = s.op("extractvalue %s %s, 0" % (lty(f.ret), r))
        x1 = s.op("extractvalue %s %s, 1" % (lty(f.ret), r))
        if is_arr(f.ret):
            return s.temp_arr(V("arr", x0, x1, elem_ty(f.ret)), owned)
        return V("opt", x0, x1)

    # ---------- contract evaluation (requires), i128 ----------
    def bind_contract_params(s):
        s.place("start")
        for p in s.f.params:
            n = mangle(p.name)
            if is_arr(p.type):
                s.cenv[p.name] = V("arr", "%%p.%s.a" % n, "%%p.%s.n" % n, elem_ty(p.type))
            elif p.type == BOOL:
                s.cenv[p.name] = V("i1", "%%p.%s" % n)
            elif p.type == I64:
                s.cenv[p.name] = V("i128", s.op("sext i64 %%p.%s to i128" % n))
            elif is_agg(p.type):
                s.cenv[p.name] = s.to_c(V("agg", "%%p.%s" % n, None, p.type), p.type)
            else:
                t = s.op("extractvalue %s %%p.%s, 0" % (OPT, n))
                v = s.op("extractvalue %s %%p.%s, 1" % (OPT, n))
                s.cenv[p.name] = V("opt", t, s.op("sext i64 %s to i128" % v))

    def cev(s, e):
        und = lambda msg: s.panic1("pruv_panic_undefined", msg)
        if isinstance(e, IntLit):
            return V("i128", str(e.value))
        if isinstance(e, BoolLit):
            return V("i1", "true" if e.value else "false")
        if isinstance(e, Var):
            if e.name not in s.cenv:
                raise Exception("llvmgen: unsupported variable in requires: %s" % e.name)
            return s.cenv[e.name]
        if isinstance(e, Unary):
            x = s.cev(e.operand)
            if e.op == "!":
                return V("i1", s.op("xor i1 %s, true" % x.a))
            return V("i128", s.checked("i128", "ssub", "unary -", "0", x.a))
        if isinstance(e, Binary):
            op = e.op
            if op in ("&&", "||", "==>"):
                l = s.cev(e.left)
                if op == "==>":
                    l = V("i1", s.op("xor i1 %s, true" % l.a))
                return V("i1", s.shortcircuit(l.a, lambda: s.cev(e.right).a, op != "&&"))
            l = s.cev(e.left)
            r = s.cev(e.right)
            if op in ("+", "-", "*"):
                name = {"+": "sadd", "-": "ssub", "*": "smul"}[op]
                return V("i128", s.checked("i128", name, op, l.a, r.a))
            if op in ("/", "%"):
                fn = "pruv_cdiv" if op == "/" else "pruv_crem"
                return V("i128", s.op("call i128 @%s(i128 %s, i128 %s)" % (fn, l.a, r.a)))
            if op in ("==", "!=") and l.k == "agg":
                eq = s.ceq(l, r, l.ty)
                if op == "!=":
                    eq = s.op("xor i1 %s, true" % eq)
                return V("i1", eq)
            if op in ("==", "!=") and l.k == "opt":
                te = s.op("icmp eq i1 %s, %s" % (l.a, r.a))
                pe = s.op("icmp eq i128 %s, %s" % (l.b, r.b))
                if e.left.ty is not None and e.left.ty.name == "option":
                    nt = s.op("xor i1 %s, true" % l.a)
                    pe = s.op("or i1 %s, %s" % (nt, pe))
                eq = s.op("and i1 %s, %s" % (te, pe))
                if op == "!=":
                    eq = s.op("xor i1 %s, true" % eq)
                return V("i1", eq)
            cmp = {"==": "eq", "!=": "ne", "<": "slt", "<=": "sle", ">": "sgt", ">=": "sge"}[op]
            return V("i1", s.op("icmp %s %s %s, %s" % (cmp, "i1" if l.k == "i1" else "i128", l.a, r.a)))
        if isinstance(e, Index):
            a = s.cev(e.array)
            i = s.cev(e.index)
            ln = s.op("zext i64 %s to i128" % a.b)
            ok = s.op("icmp ult i128 %s, %s" % (i.a, ln))
            s.guard(ok, und("array index out of range"), False)
            ii = s.op("trunc i128 %s to i64" % i.a)
            if is_boolarr(a):  # G2 A5
                g = s.op("getelementptr inbounds i8, ptr %s, i64 %s" % (a.a, ii))
                x = s.op("load i8, ptr %s" % g)
                return V("i1", s.op("icmp ne i8 %s, 0" % x))
            if is_u8(a) or is_strv(a):  # G2 B2: str reads like u8
                g = s.op("getelementptr inbounds i8, ptr %s, i64 %s" % (a.a, ii))
                x = s.op("load i8, ptr %s" % g)
                return V("i128", s.op("zext i8 %s to i128" % x))
            g = s.op("getelementptr inbounds i64, ptr %s, i64 %s" % (a.a, ii))
            x = s.op("load i64, ptr %s" % g)
            return V("i128", s.op("sext i64 %s to i128" % x))
        if isinstance(e, StrLit):  # G2 B2: no copy
            return V("arr", s.m.string(e.value.decode("utf-8")), str(len(e.value)), STR)
        if isinstance(e, Ctor):
            if e.ty is not None and gopt(e.ty):  # G3
                return s.mk_gctor(e, s.cev, True)
            if e.name == "None":
                return V("opt", "false", "0")
            x = s.cev(e.arg)
            return V("opt", "true" if e.name in ("Some", "Ok") else "false", x.a)
        if isinstance(e, Quant):
            return s.cquant(e)
        if isinstance(e, StructLit):
            return s.mk_struct(e, s.cev, True)
        if isinstance(e, EnumCtor):
            return s.mk_enum(e, s.cev, True)
        if isinstance(e, FieldAccess):
            b = s.cev(e.base)
            i = s.tt.field_index(b.ty, e.field)
            return s.get(b, b.ty, i, s.tt.fields(b.ty)[i].type, True)
        if isinstance(e, IsVariant):
            b = s.cev(e.value)
            k = s.tt.variant_index(b.ty, e.variant)
            return V("i1", s.op("icmp eq i64 %s, %d" % (s.tag_of(b, True), k)))
        if isinstance(e, VariantField):
            b = s.cev(e.value)
            k = s.tt.variant_index(b.ty, e.variant)
            ok = s.op("icmp eq i64 %s, %d" % (s.tag_of(b, True), k))
            s.guard(ok, und("variant_field expected %s::%s.%s" % (e.enum_name, e.variant, e.field)), False)
            i = s.tt.field_index(b.ty, e.field, e.variant)
            fd = s.tt.fields(b.ty, e.variant)[i]
            return s.get(b, b.ty, payload_index(s.tt, b.ty, e.variant, i), fd.type, True)
        if isinstance(e, Call):
            n, a = e.name, e.args
            if n == "len":
                return V("i128", s.op("zext i64 %s to i128" % s.cev(a[0]).b))
            if n == "is_char_boundary":  # G2 B2
                sv = s.cev(a[0])
                iv = s.cev(a[1])
                ln = s.op("zext i64 %s to i128" % sv.b)
                ok = s.op("icmp ule i128 %s, %s" % (iv.a, ln))
                t = s.op("trunc i128 %s to i64" % iv.a)
                u = s.op("select i1 %s, i64 %s, i64 -1" % (ok, t))
                r = s.op("call i32 @pruv_str_boundary(ptr %s, i64 %s, i64 %s)" % (sv.a, sv.b, u))
                return V("i1", s.op("icmp ne i32 %s, 0" % r))
            if n in ("is_some", "is_ok"):
                o = s.cev(a[0])
                if o.k == "agg":  # G3: tag of a new Option/Result
                    return V("i1", s.op("extractvalue %s %s, 0" % (st(o.ty, True), o.a)))
                return V("i1", o.a)
            if n in ("some_val", "ok_val", "err_val"):
                o = s.cev(a[0])
                if o.k == "agg":  # G3: selectors of a new Option/Result look only at the active payload
                    T = st(o.ty, True)
                    tag = s.op("extractvalue %s %s, 0" % (T, o.a))
                    if n == "err_val":
                        s.guard(tag, und("err_val of Ok"), True)
                        return V("i128", s.op("extractvalue %s %s, 2" % (T, o.a)))
                    s.guard(tag, und("some_val of None" if n == "some_val" else "ok_val of Err"), False)
                    return s.get(o, o.ty, 1, o.ty.args[0], True)
                if n == "err_val":
                    s.guard(o.a, und("err_val of Ok"), True)
                else:
                    s.guard(o.a, und("some_val of None" if n == "some_val" else "ok_val of Err"), False)
                return V("i128", o.b)
        raise Exception("llvmgen: unsupported expression in requires: %r" % e)

    def spend(s):
        """consume one unit of the per-entry requires iteration budget (docs/M0_CONTRACTS.md B)"""
        if not hasattr(s, "budget"):
            raise Exception("llvmgen: internal error: no iteration budget slot")
        old = s.op("load i64, ptr %s" % s.budget)
        nv = s.op("sub i64 %s, 1" % old)
        s.ins("store i64 %s, ptr %s" % (nv, s.budget))
        ok = s.op("icmp sge i64 %s, 0" % nv)
        s.guard(ok, s.panic1("pruv_panic_undefined", "contract iteration budget exceeded"), False)

    def csorted(s, name, q):
        """O(n) form of the sorted-precondition forall: forall k in 1..len(a): a[k-1] <= a[k]"""
        arr = s.cenv[name]
        k, r = "%%q%d.k" % q, "%%q%d.r" % q
        s.allocas.append("%s = alloca i64" % k)
        s.allocas.append("%s = alloca i1" % r)
        s.ins("store i64 1, ptr %s" % k)
        s.ins("store i1 true, ptr %s" % r)
        cl, bl, nl_, el = s.label("qc"), s.label("qb"), s.label("qn"), s.label("qe")
        s.br(cl)
        s.place(cl)
        kv = s.op("load i64, ptr %s" % k)
        c = s.op("icmp slt i64 %s, %s" % (kv, arr.b))
        s.condbr(c, bl, el)
        s.place(bl)
        s.spend()
        pk = s.op("sub i64 %s, 1" % kv)
        if is_u8(arr):
            g0 = s.op("getelementptr inbounds i8, ptr %s, i64 %s" % (arr.a, pk))
            g1 = s.op("getelementptr inbounds i8, ptr %s, i64 %s" % (arr.a, kv))
            x0 = s.op("load i8, ptr %s" % g0)
            x1 = s.op("load i8, ptr %s" % g1)
            z0 = s.op("zext i8 %s to i64" % x0)
            z1 = s.op("zext i8 %s to i64" % x1)
            le = s.op("icmp sle i64 %s, %s" % (z0, z1))
        else:
            g0 = s.op("getelementptr inbounds i64, ptr %s, i64 %s" % (arr.a, pk))
            g1 = s.op("getelementptr inbounds i64, ptr %s, i64 %s" % (arr.a, kv))
            x0 = s.op("load i64, ptr %s" % g0)
            x1 = s.op("load i64, ptr %s" % g1)
            le = s.op("icmp sle i64 %s, %s" % (x0, x1))
        stop = s.label("qstop")
        s.condbr(le, nl_, stop)
        s.place(stop)
        s.ins("store i1 false, ptr %s" % r)
        s.br(el)
        s.place(nl_)
        k2 = s.op("add i64 %s, 1" % kv)
        s.ins("store i64 %s, ptr %s" % (k2, k))
        s.br(cl)
        s.place(el)
        return V("i1", s.op("load i1, ptr %s" % r))

    def cquant(s, e):
        if e.kind == "forall":
            sorted_arr = codegen.match_sorted_requires(e)
            if sorted_arr is not None and not (sorted_arr in s.cenv and is_strv(s.cenv[sorted_arr])):  # G2 B2: no fast path for str
                q = s.nq
                s.nq += 1
                return s.csorted(sorted_arr, q)
        lo = s.cev(e.lo)
        hi = s.cev(e.hi)
        q = s.nq
        s.nq += 1
        k, r, h = "%%q%d.k" % q, "%%q%d.r" % q, "%%q%d.h" % q
        kind = e.kind
        s.allocas.append("%s = alloca i128" % k)
        rty = "i1" if kind in ("forall", "exists") else "i128"
        s.allocas.append("%s = alloca %s" % (r, rty))
        if kind in ("max", "min"):
            s.allocas.append("%s = alloca i1" % h)
        s.ins("store i128 %s, ptr %s" % (lo.a, k))
        if kind == "forall":
            s.ins("store i1 true, ptr %s" % r)
        elif kind == "exists":
            s.ins("store i1 false, ptr %s" % r)
        else:
            s.ins("store i128 0, ptr %s" % r)
        if kind in ("max", "min"):
            s.ins("store i1 false, ptr %s" % h)
        cl, bl, nl_, el = s.label("qc"), s.label("qb"), s.label("qn"), s.label("qe")
        s.br(cl)
        s.place(cl)
        kv = s.op("load i128, ptr %s" % k)
        c = s.op("icmp slt i128 %s, %s" % (kv, hi.a))
        s.condbr(c, bl, el)
        s.place(bl)
        s.spend()
        saved = s.cenv.get(e.var)
        s.cenv[e.var] = V("i128", kv)
        b = s.cev(e.body)
        if saved is None:
            del s.cenv[e.var]
        else:
            s.cenv[e.var] = saved
        if kind in ("forall", "exists"):
            stop = s.label("qstop")
            if kind == "forall":
                s.condbr(b.a, nl_, stop)
            else:
                s.condbr(b.a, stop, nl_)
            s.place(stop)
            s.ins("store i1 %s, ptr %s" % ("false" if kind == "forall" else "true", r))
            s.br(el)
        else:
            old = s.op("load i128, ptr %s" % r)
            if kind == "sum":
                nv = s.checked("i128", "sadd", "+", old, b.a)
            elif kind == "count":
                z = s.op("zext i1 %s to i128" % b.a)
                nv = s.op("add i128 %s, %s" % (old, z))
            else:
                hv = s.op("load i1, ptr %s" % h)
                cmp = s.op("icmp %s i128 %s, %s" % ("sgt" if kind == "max" else "slt", b.a, old))
                nh = s.op("xor i1 %s, true" % hv)
                better = s.op("or i1 %s, %s" % (nh, cmp))
                nv = s.op("select i1 %s, i128 %s, i128 %s" % (better, b.a, old))
                s.ins("store i1 true, ptr %s" % h)
            s.ins("store i128 %s, ptr %s" % (nv, r))
            s.br(nl_)
        s.place(nl_)
        k2 = s.op("add i128 %s, 1" % kv)
        s.ins("store i128 %s, ptr %s" % (k2, k))
        s.br(cl)
        s.place(el)
        if kind in ("max", "min"):
            hv = s.op("load i1, ptr %s" % h)
            s.guard(hv, s.panic1("pruv_panic_undefined", "%s over an empty range" % kind), False)
        res = s.op("load %s, ptr %s" % (rty, r))
        return V(rty, res)


def entry_of(m, funcs, f, trust, budget=1 << 30):
    g = FnGen(m, funcs, f, True)
    params = ir_params(f)
    rt = lty(f.ret)
    if trust:
        g.place("start")
    else:
        g.bind_contract_params()
        g.budget = "%req.budget"
        g.allocas.append("%s = alloca i64" % g.budget)
        g.ins("store i64 %d, ptr %s" % (budget, g.budget))
        for r in f.requires:
            c = g.cev(r)
            msg_fn = m.string(f.name)
            msg_ex = m.string(show(r))
            g.guard(c.a, lambda a=msg_fn, b=msg_ex: g.ins("call void @pruv_panic_requires(ptr %s, ptr %s)" % (a, b)),
                    False)
    args = ", ".join("%s %s" % (t, n) for t, n in params)
    callee = "@%s__pruv_body" % mangle(f.name)
    if f.ret == UNIT:
        g.ins("call void %s(%s)" % (callee, args))
        g.term("ret void")
    else:
        r = g.op("call %s %s(%s)" % (rt, callee, args))
        g.term("ret %s %s" % (rt, r))
    return g.render("define internal %s @%s__pruv_entry(%s)" % (rt, mangle(f.name), sig_text(params)))


class Words:
    """IR text for the external word form of user types (docs/M2_G1_SPEC.md section 5, W(T))"""

    def __init__(s, tt):
        s.tt, s.lines, s.n = tt, [], 0
        s.checks = []       # G3: (valid i1, raw tag word, type name) of every enum ordinal that must be rejected if invalid
        s.stm, s.hn = {}, {}  # caches: storage type text per type, "contains a G3 application" per type

    def S(s, ty):
        """st(ty) (non-contract form), cached per type"""
        r = s.stm.get(ty)
        if r is None:
            if gopt(ty):
                x = s.S(ty.args[0])
                r = "{ i1, %s }" % x if ty.name == "option" else "{ i1, %s, i64 }" % x
            else:
                r = st(ty)
            s.stm[ty] = r
        return r

    def has_new(s, ty):
        """whether ty is, or contains by value, a G3 application (its words follow the G3 rules)"""
        r = s.hn.get(ty)
        if r is None:
            if is_new_app(ty):
                r = True
            elif not is_user_type(ty):
                r = False
            else:
                d = s.tt.decl(ty)
                fs = d.fields if isinstance(d, StructDecl) else [f for v in d.variants for f in v.fields]
                r = any(s.has_new(f.type) for f in fs)
            s.hn[ty] = r
        return r

    def op(s, text):
        s.n += 1
        r = "%%w.%d" % s.n
        s.lines.append("%s = %s" % (r, text))
        return r

    def gep(s, ptr, off):
        return s.op("getelementptr inbounds i64, ptr %s, i64 %d" % (ptr, off))

    def rd(s, ptr, off):
        return s.op("load i64, ptr %s" % s.gep(ptr, off))

    def wr(s, ptr, off, v):
        g = s.gep(ptr, off)
        s.lines.append("store i64 %s, ptr %s" % (v, g))

    def de(s, ty, ptr, off, act="true"):
        """read a value of type ty from words at ptr[off..]; returns an SSA name of type st(ty).
        Legacy types keep the G1 reading; a G3 application (new Option/Result, generated generic instance) and
        everything below it is read by de_new (masked inactive words, enum ordinal checks).  act is "true" or an i1
        telling whether this legacy value is active: it only matters for a G3 application reached through legacy
        structs/enums, whose ordinal check happens only when its whole path is active (an inactive one reads zero)."""
        n = ty.name
        if is_new_app(ty):
            return s.de_new(ty, ptr, off, act)
        if n == "i64":
            return s.rd(ptr, off)
        if n == "bool":
            return s.op("icmp ne i64 %s, 0" % s.rd(ptr, off))
        if n in ("option", "result"):
            t = s.op("icmp ne i64 %s, 0" % s.rd(ptr, off))
            p = s.rd(ptr, off + 1)
            a = s.op("insertvalue %s undef, i1 %s, 0" % (OPT, t))
            return s.op("insertvalue %s %s, i64 %s, 1" % (OPT, a, p))
        d = s.tt.decl(ty)
        T = st(ty)
        acc = "zeroinitializer"
        if isinstance(d, StructDecl):
            o = off
            for i, f in enumerate(d.fields):
                x = s.de(f.type, ptr, o, act)
                acc = s.op("insertvalue %s %s, %s %s, %d" % (T, acc, s.S(f.type), x, i))
                o += words(s.tt, f.type)
            return acc
        tag = s.rd(ptr, off)
        acc = s.op("insertvalue %s zeroinitializer, i64 %s, 0" % (T, tag))
        o, idx = off + 1, 1
        for k, v in enumerate(d.variants):
            ak = act
            if any(s.has_new(f.type) for f in v.fields):    # only then is the activity of this payload observable
                ak = s.op("icmp eq i64 %s, %d" % (tag, k))
                if act != "true":
                    ak = s.op("and i1 %s, %s" % (act, ak))
            for f in v.fields:
                x = s.de(f.type, ptr, o, ak)
                acc = s.op("insertvalue %s %s, %s %s, %d" % (T, acc, s.S(f.type), x, idx))
                o += words(s.tt, f.type)
                idx += 1
        return acc

    def de_new(s, ty, ptr, off, act):
        """G3 reading of a value of type ty from words at ptr[off..].  act is "true" or an i1 SSA name telling
        whether this value is semantically active: inactive words are read as zero (deterministic storage, ignored
        semantically), bool/tag words normalize by nonzero-to-true, and the ordinal of every nominal enum that is
        active must be < the variant count (recorded in s.checks; the wrapper rejects before requires/body)."""
        n = ty.name
        on = act != "true"
        if n == "i64":
            w = s.rd(ptr, off)
            return s.op("select i1 %s, i64 %s, i64 0" % (act, w)) if on else w
        if n == "bool":
            c = s.op("icmp ne i64 %s, 0" % s.rd(ptr, off))
            return s.op("and i1 %s, %s" % (act, c)) if on else c
        if gopt(ty):
            X = ty.args[0]
            T = s.S(ty)
            t = s.op("icmp ne i64 %s, 0" % s.rd(ptr, off))
            if on:
                t = s.op("and i1 %s, %s" % (act, t))
            x = s.de_new(X, ptr, off + 1, t)
            acc = s.op("insertvalue %s zeroinitializer, i1 %s, 0" % (T, t))
            acc = s.op("insertvalue %s %s, %s %s, 1" % (T, acc, s.S(X), x))
            if n == "result":
                ew = s.rd(ptr, off + 1 + words(s.tt, X))
                ea = s.op("xor i1 %s, true" % t)
                if on:
                    ea = s.op("and i1 %s, %s" % (act, ea))
                e = s.op("select i1 %s, i64 %s, i64 0" % (ea, ew))
                acc = s.op("insertvalue %s %s, i64 %s, 2" % (T, acc, e))
            return acc
        if n in ("option", "result"):       # legacy Option<i64>/Result<i64> nested in a G3 value
            t = s.op("icmp ne i64 %s, 0" % s.rd(ptr, off))
            if on:
                t = s.op("and i1 %s, %s" % (act, t))
            p = s.rd(ptr, off + 1)
            pa = t if n == "option" else act
            if pa != "true":
                p = s.op("select i1 %s, i64 %s, i64 0" % (pa, p))
            a = s.op("insertvalue %s undef, i1 %s, 0" % (OPT, t))
            return s.op("insertvalue %s %s, i64 %s, 1" % (OPT, a, p))
        d = s.tt.decl(ty)
        T = st(ty)
        acc = "zeroinitializer"
        if isinstance(d, StructDecl):
            o = off
            for i, f in enumerate(d.fields):
                x = s.de_new(f.type, ptr, o, act)
                acc = s.op("insertvalue %s %s, %s %s, %d" % (T, acc, s.S(f.type), x, i))
                o += words(s.tt, f.type)
            return acc
        w = s.rd(ptr, off)
        ok = s.op("icmp ult i64 %s, %d" % (w, len(d.variants)))
        if on:
            ok = s.op("or i1 %s, %s" % (s.op("xor i1 %s, true" % act), ok))
        s.checks.append((ok, w, ty.name))
        tag = s.op("select i1 %s, i64 %s, i64 0" % (act, w)) if on else w
        acc = s.op("insertvalue %s zeroinitializer, i64 %s, 0" % (T, tag))
        o, idx = off + 1, 1
        for k, v in enumerate(d.variants):
            ak = None
            if v.fields:
                ak = s.op("icmp eq i64 %s, %d" % (w, k))
                if on:
                    ak = s.op("and i1 %s, %s" % (act, ak))
            for f in v.fields:
                x = s.de_new(f.type, ptr, o, ak)
                acc = s.op("insertvalue %s %s, %s %s, %d" % (T, acc, s.S(f.type), x, idx))
                o += words(s.tt, f.type)
                idx += 1
        return acc

    def ser_new(s, ty, x, ptr, off, act):
        """G3 writing of the SSA value x (type st(ty)) as words at ptr[off..].  act is "true" or an i1 telling whether
        this value is semantically active.  Every inactive word is written explicitly as zero (a legacy-ABI value
        may carry dirty inactive storage), propagating the activity recursively: an Option payload is active when
        the tag is set, a Result error word when it is not, an enum payload when the tag selects its variant."""
        n = ty.name
        on = act != "true"
        if n == "i64":
            s.wr(ptr, off, s.op("select i1 %s, i64 %s, i64 0" % (act, x)) if on else x)
        elif n == "bool":
            b = s.op("and i1 %s, %s" % (act, x)) if on else x
            s.wr(ptr, off, s.op("zext i1 %s to i64" % b))
        elif gopt(ty):  # tag word, payload words, (Result) error word
            X = ty.args[0]
            T = s.S(ty)
            t = s.op("extractvalue %s %s, 0" % (T, x))
            if on:
                t = s.op("and i1 %s, %s" % (act, t))
            s.wr(ptr, off, s.op("zext i1 %s to i64" % t))
            s.ser_new(X, s.op("extractvalue %s %s, 1" % (T, x)), ptr, off + 1, t)
            if n == "result":
                e = s.op("extractvalue %s %s, 2" % (T, x))
                ea = s.op("xor i1 %s, true" % t)
                if on:
                    ea = s.op("and i1 %s, %s" % (act, ea))
                e = s.op("select i1 %s, i64 %s, i64 0" % (ea, e))
                s.wr(ptr, off + 1 + words(s.tt, X), e)
        elif n in ("option", "result"):      # legacy Option<i64>/Result<i64> nested in a G3 value
            t = s.op("extractvalue %s %s, 0" % (OPT, x))
            p = s.op("extractvalue %s %s, 1" % (OPT, x))
            if on:
                t = s.op("and i1 %s, %s" % (act, t))
            pa = t if n == "option" else act
            if pa != "true":
                p = s.op("select i1 %s, i64 %s, i64 0" % (pa, p))
            s.wr(ptr, off, s.op("zext i1 %s to i64" % t))
            s.wr(ptr, off + 1, p)
        else:
            d = s.tt.decl(ty)
            T = st(ty)
            if isinstance(d, StructDecl):
                if not d.fields:
                    s.wr(ptr, off, "0")
                o = off
                for i, f in enumerate(d.fields):
                    s.ser_new(f.type, s.op("extractvalue %s %s, %d" % (T, x, i)), ptr, o, act)
                    o += words(s.tt, f.type)
                return
            tag = s.op("extractvalue %s %s, 0" % (T, x))
            s.wr(ptr, off, s.op("select i1 %s, i64 %s, i64 0" % (act, tag)) if on else tag)
            o, idx = off + 1, 1
            for k, v in enumerate(d.variants):
                ak = None
                if v.fields:
                    ak = s.op("icmp eq i64 %s, %d" % (tag, k))
                    if on:
                        ak = s.op("and i1 %s, %s" % (act, ak))
                for f in v.fields:
                    s.ser_new(f.type, s.op("extractvalue %s %s, %d" % (T, x, idx)), ptr, o, ak)
                    o += words(s.tt, f.type)
                    idx += 1

    def ser(s, ty, x, ptr, off, act="true"):
        """write the SSA value x (type st(ty)) as words at ptr[off..].  A purely legacy value is written as is (the
        legacy ABI output stays byte-identical); a G3 application and everything nested in it goes through ser_new,
        also when it hangs below a legacy struct/enum (act: whether that legacy value is active)."""
        n = ty.name
        if is_new_app(ty):
            s.ser_new(ty, x, ptr, off, act)
        elif n == "i64":
            s.wr(ptr, off, x)
        elif n == "bool":
            s.wr(ptr, off, s.op("zext i1 %s to i64" % x))
        elif n in ("option", "result"):
            t = s.op("extractvalue %s %s, 0" % (OPT, x))
            p = s.op("extractvalue %s %s, 1" % (OPT, x))
            if n == "option":           # None payload is serialized as 0
                p = s.op("select i1 %s, i64 %s, i64 0" % (t, p))
            s.wr(ptr, off, s.op("zext i1 %s to i64" % t))
            s.wr(ptr, off + 1, p)
        else:
            d = s.tt.decl(ty)
            T = st(ty)
            if isinstance(d, StructDecl):
                if not d.fields:
                    s.wr(ptr, off, "0")
                o = off
                for i, f in enumerate(d.fields):
                    s.ser(f.type, s.op("extractvalue %s %s, %d" % (T, x, i)), ptr, o, act)
                    o += words(s.tt, f.type)
                return
            # legacy words are written as they are; only a G3 application below has its inactivity made explicit
            tag = s.op("extractvalue %s %s, 0" % (T, x))
            s.wr(ptr, off, tag)
            o, idx = off + 1, 1
            for k, v in enumerate(d.variants):
                ak = act
                if any(s.has_new(f.type) for f in v.fields):
                    ak = s.op("icmp eq i64 %s, %d" % (tag, k))
                    if act != "true":
                        ak = s.op("and i1 %s, %s" % (act, ak))
                for f in v.fields:
                    s.ser(f.type, s.op("extractvalue %s %s, %d" % (T, x, idx)), ptr, o, ak)
                    o += words(s.tt, f.type)
                    idx += 1


def abi_of(f, tt, m=None):
    n = mangle(f.name)
    ext, pre, args = [], [], []
    w = Words(tt)
    for p in f.params:
        q = mangle(p.name)
        if is_agg(p.type):
            ext.append("ptr %%a.%s" % q)
            args.append("%s %s" % (lty(p.type), w.de(p.type, "%%a.%s" % q, 0)))
            pre += w.lines
            w.lines = []
        elif p.type == I64:
            ext.append("i64 %%a.%s" % q)
            args.append("i64 %%a.%s" % q)
        elif p.type == BOOL:
            ext.append("i64 %%a.%s" % q)
            pre.append("%%c.%s = icmp ne i64 %%a.%s, 0" % (q, q))
            args.append("i1 %%c.%s" % q)
        elif is_arr(p.type):
            ext += ["ptr %%a.%s.a" % q, "i64 %%a.%s.n" % q]
            if p.type.name == "array_bool":  # G2 A5: representation check before entry
                pre.append("call void @pruv_check_bool(ptr %%a.%s.a, i64 %%a.%s.n)" % (q, q))
            elif p.type.name == "str":  # G2 B2: UTF-8 check before requires/body
                pre.append("call void @pruv_check_utf8(ptr %%a.%s.a, i64 %%a.%s.n)" % (q, q))
            args += ["ptr %%a.%s.a" % q, "i64 %%a.%s.n" % q]
        else:
            ext += ["i64 %%a.%s.t" % q, "i64 %%a.%s.v" % q]
            pre.append("%%c.%s.t = icmp ne i64 %%a.%s.t, 0" % (q, q))
            pre.append("%%c.%s.g1 = insertvalue %s undef, i1 %%c.%s.t, 0" % (q, OPT, q))
            pre.append("%%c.%s.g = insertvalue %s %%c.%s.g1, i64 %%a.%s.v, 1" % (q, OPT, q, q))
            args.append("%s %%c.%s.g" % (OPT, q))
    rt = f.ret
    entry = "@%s__pruv_entry" % n
    body = ["  " + x for x in pre]
    for k, (okv, wv, tname) in enumerate(w.checks):
        # G3: an invalid nominal enum ordinal is rejected here, before the entry (requires) and the body run
        msg = m.string("enum " + tname)
        m.uses_repr = True
        body.append("  br i1 %s, label %%enum.ok%d, label %%enum.bad%d" % (okv, k, k))
        body.append("enum.bad%d:" % k)
        body.append("  call void @pruv_panic_repr(i64 %s, ptr %s)" % (wv, msg))
        body.append("  unreachable")
        body.append("enum.ok%d:" % k)
    if is_arr(rt):
        ext.append("ptr %out")
        body.append("  %%r = call %s %s(%s)" % (lty(rt), entry, ", ".join(args)))
        body.append("  %%x0 = extractvalue %s %%r, 0" % lty(rt))
        body.append("  %%x1 = extractvalue %s %%r, 1" % lty(rt))
        body.append("  %o0 = getelementptr inbounds { ptr, i64 }, ptr %out, i32 0, i32 0")
        body.append("  %o1 = getelementptr inbounds { ptr, i64 }, ptr %out, i32 0, i32 1")
        body.append("  store ptr %x0, ptr %o0")
        body.append("  store i64 %x1, ptr %o1")
        body.append("  ret void")
        ret = "void"
    elif rt in (OPTION, RESULT):
        # returned by value as { i64, i64 } (two registers on macOS arm64 / SysV x86-64)
        body.append("  %%r = call %s %s(%s)" % (lty(rt), entry, ", ".join(args)))
        body.append("  %%x0 = extractvalue %s %%r, 0" % lty(rt))
        body.append("  %%x1 = extractvalue %s %%r, 1" % lty(rt))
        body.append("  %x0z = zext i1 %x0 to i64")
        body.append("  %t0 = insertvalue { i64, i64 } undef, i64 %x0z, 0")
        body.append("  %t1 = insertvalue { i64, i64 } %t0, i64 %x1, 1")
        body.append("  ret { i64, i64 } %t1")
        ret = "{ i64, i64 }"
    elif is_agg(rt):
        ext.append("ptr %out")
        body.append("  %%r = call %s %s(%s)" % (lty(rt), entry, ", ".join(args)))
        w.ser(rt, "%r", "%out", 0)
        body += ["  " + x for x in w.lines]
        body.append("  ret void")
        ret = "void"
    elif rt == UNIT:
        body.append("  call void %s(%s)" % (entry, ", ".join(args)))
        body.append("  ret void")
        ret = "void"
    elif rt == BOOL:
        body.append("  %%r = call i1 %s(%s)" % (entry, ", ".join(args)))
        body.append("  %rz = zext i1 %r to i64")
        body.append("  ret i64 %rz")
        ret = "i64"
    else:
        body.append("  %%r = call i64 %s(%s)" % (entry, ", ".join(args)))
        body.append("  ret i64 %r")
        ret = "i64"
    out = "define %s @pruv_abi_%s(%s) {\nentry:\n%s\n}\n" % (ret, n, ", ".join(ext), "\n".join(body))
    if any(p.type.name in ("array_bool", "str") for p in f.params):
        # G2 A5/B2: typed Rust bindings pass &[bool] / &str (valid by type) to this entry without the check
        tb = [x for x in body if not (x.startswith("  call void @pruv_check_bool(")
                                      or x.startswith("  call void @pruv_check_utf8("))]
        out += "\ndefine %s @pruv_abi_%s__typed(%s) {\nentry:\n%s\n}\n" % (ret, n, ", ".join(ext), "\n".join(tb))
    return out


# ---------- helper functions for requires ----------
def cdivrem(m, is_div):
    nm, sym = ("pruv_cdiv", "/") if is_div else ("pruv_crem", "%")
    z = m.string("division by zero in " + sym)
    o = m.string("i128 overflow in " + sym)
    res = "%qq" if is_div else "%rr"
    return """\
define internal i128 @%s(i128 %%a, i128 %%b) {
entry:
  %%z = icmp eq i128 %%b, 0
  br i1 %%z, label %%dz, label %%c1
dz:
  call void @pruv_panic_undefined(ptr %s)
  unreachable
c1:
  %%am = icmp eq i128 %%a, %d
  %%bm = icmp eq i128 %%b, -1
  %%ov = and i1 %%am, %%bm
  br i1 %%ov, label %%of, label %%c2
of:
  call void @pruv_panic_undefined(ptr %s)
  unreachable
c2:
  %%q = sdiv i128 %%a, %%b
  %%r = srem i128 %%a, %%b
  %%neg = icmp slt i128 %%r, 0
  %%bp = icmp sgt i128 %%b, 0
  %%ra = add i128 %%r, %%b
  %%rs = sub i128 %%r, %%b
  %%r2 = select i1 %%bp, i128 %%ra, i128 %%rs
  %%rr = select i1 %%neg, i128 %%r2, i128 %%r
  %%qd = select i1 %%bp, i128 -1, i128 1
  %%q2 = add i128 %%q, %%qd
  %%qq = select i1 %%neg, i128 %%q2, i128 %%q
  ret i128 %s
}
""" % (nm, z, SIGNED_MIN128, o, res)


# ---------- Rust bindings ----------
def typed_abi_name(f):
    """G2 A5: the bindings call pruv_abi_<f>__typed (no [bool] byte check) when f has a [bool] parameter"""
    return f.name + ("__typed" if any(p.type.name in ("array_bool", "str") for p in f.params) else "")  # G2 B2


def rust_ty(t, param):
    if gopt(t):  # G3: ::std::option::Option<R(X)> / ::std::result::Result<R(X), i64>
        return codegen.rty(t)
    if is_user_type(t):
        return t.name
    if t.name == "array_u8":
        return "&[u8]" if param else "::std::vec::Vec<u8>"
    if t.name == "array_bool":  # G2 A5
        return "&[bool]" if param else "::std::vec::Vec<bool>"
    if t.name == "str":  # G2 B2
        return "&str" if param else "::std::string::String"
    return {"i64": "i64", "bool": "bool", "unit": "()", "option": "::std::option::Option<i64>",
            "result": "::std::result::Result<i64, i64>"}.get(t.name) or (
        "&[i64]" if param else "::std::vec::Vec<i64>")


ALLOW = "#[allow(dead_code, non_snake_case, unused)]"


def rs_ser(tt, ty, expr, arr, off, ctr):
    """Rust statements writing `expr` (a Copy value of type ty) into the word array `arr` at off"""
    n = ty.name
    if n == "i64":
        return ["%s[%d] = %s;" % (arr, off, expr)]
    if n == "bool":
        return ["%s[%d] = (%s) as i64;" % (arr, off, expr)]
    if gopt(ty):  # G3: the word array starts zeroed, so only the active words are written
        ctr[0] += 1
        v = "pruv__b%d" % ctr[0]
        inner = " ".join(rs_ser(tt, ty.args[0], v, arr, off + 1, ctr))
        if n == "option":
            return ["match %s { Some(%s) => { %s[%d] = 1; %s } None => { %s[%d] = 0; } }"
                    % (expr, v, arr, off, inner, arr, off)]
        return ["match %s { Ok(%s) => { %s[%d] = 1; %s } Err(%s) => { %s[%d] = 0; %s[%d] = %s; } }"
                % (expr, v, arr, off, inner, v, arr, off, arr, off + 1 + words(tt, ty.args[0]), v)]
    if n in ("option", "result"):
        ctr[0] += 1
        v = "pruv__b%d" % ctr[0]
        a, b = ("Some", "None") if n == "option" else ("Ok", "Err")
        if n == "option":
            return ["match %s { Some(%s) => { %s[%d] = 1; %s[%d] = %s; } None => { %s[%d] = 0; %s[%d] = 0; } }"
                    % (expr, v, arr, off, arr, off + 1, v, arr, off, arr, off + 1)]
        return ["match %s { Ok(%s) => { %s[%d] = 1; %s[%d] = %s; } Err(%s) => { %s[%d] = 0; %s[%d] = %s; } }"
                % (expr, v, arr, off, arr, off + 1, v, v, arr, off, arr, off + 1, v)]
    d = tt.decl(ty)
    if isinstance(d, StructDecl):
        out, o = [], off
        for f in d.fields:
            out += rs_ser(tt, f.type, "%s.%s" % (expr, f.name), arr, o, ctr)
            o += words(tt, f.type)
        return out
    arms, o = [], off + 1
    for k, v in enumerate(d.variants):
        names, stmts = [], ["%s[%d] = %d;" % (arr, off, k)]
        for f in v.fields:
            ctr[0] += 1
            nm = "pruv__b%d" % ctr[0]
            names.append(nm)
            stmts += rs_ser(tt, f.type, nm, arr, o, ctr)
            o += words(tt, f.type)
        pat = "%s::%s(%s)" % (d.name, v.name, ", ".join(names)) if names else "%s::%s" % (d.name, v.name)
        arms.append("%s => { %s }" % (pat, " ".join(stmts)))
    return ["match %s { %s }" % (expr, " ".join(arms))]


def rs_de(tt, ty, arr, off):
    """Rust expression rebuilding a value of type ty from the word array `arr` at off (safe constructors only)"""
    n = ty.name
    if n == "i64":
        return "%s[%d]" % (arr, off)
    if n == "bool":
        return "(%s[%d] != 0)" % (arr, off)
    if gopt(ty):  # G3
        x = rs_de(tt, ty.args[0], arr, off + 1)
        if n == "option":
            return "(if %s[%d] != 0 { Some(%s) } else { None })" % (arr, off, x)
        return "(if %s[%d] != 0 { Ok(%s) } else { Err(%s[%d]) })" % (arr, off, x, arr, off + 1 + words(tt, ty.args[0]))
    if n == "option":
        return "(if %s[%d] != 0 { Some(%s[%d]) } else { None })" % (arr, off, arr, off + 1)
    if n == "result":
        return "(if %s[%d] != 0 { Ok(%s[%d]) } else { Err(%s[%d]) })" % (arr, off, arr, off + 1, arr, off + 1)
    d = tt.decl(ty)
    if isinstance(d, StructDecl):
        parts, o = [], off
        for f in d.fields:
            parts.append("%s: %s" % (f.name, rs_de(tt, f.type, arr, o)))
            o += words(tt, f.type)
        return "%s { %s }" % (d.name, ", ".join(parts))
    arms, o = [], off + 1
    for k, v in enumerate(d.variants):
        args = []
        for f in v.fields:
            args.append(rs_de(tt, f.type, arr, o))
            o += words(tt, f.type)
        arms.append("%d => %s::%s%s," % (k, d.name, v.name, "(%s)" % ", ".join(args) if args else ""))
    return "(match %s[%d] { %s _ => ::std::unreachable!() })" % (arr, off, " ".join(arms))


def gen_bindings(prog):
    tt = TypeTable(prog)
    o = []
    o.append("// generated by pruvc llvmgen -- Rust bindings for the LLVM back end (include with #[path] mod sol;)")
    if prog.types:
        pub = codegen.emit_public_types(prog)
        o.append(pub.replace("#[derive", ALLOW + "\n#[derive") if "#[derive" in pub else pub)
    o.append(ALLOW)
    o.append("#[repr(C)]\npub struct Pruv__Array { pub data: *mut i64, pub len: i64 }")
    if uses_array_type(prog, "array_u8"):
        o.append(ALLOW)
        o.append("#[repr(C)]\npub struct Pruv__ArrayU8 { pub data: *mut u8, pub len: i64 }")
    if uses_array_type(prog, "array_bool"):  # G2 A5
        o.append(ALLOW)
        o.append("#[repr(C)]\npub struct Pruv__ArrayBool { pub data: *mut u8, pub len: i64 }")
    if uses_str(prog):  # G2 B2
        o.append(ALLOW)
        o.append("#[repr(C)]\npub struct Pruv__Str { pub data: *mut u8, pub len: i64 }")
    o.append(ALLOW)
    o.append("#[repr(C)]\npub struct Pruv__Tagged { pub tag: i64, pub value: i64 }")
    o.append(ALLOW)
    o.append("""\
#[no_mangle]
pub extern "C" fn pruv_host_alloc(len: i64) -> *mut i64 {
    let layout = match ::std::alloc::Layout::array::<i64>(len as usize) {
        Ok(l) => l,
        Err(_) => ::std::alloc::handle_alloc_error(::std::alloc::Layout::new::<i64>()),
    };
    let p = unsafe { ::std::alloc::alloc(layout) } as *mut i64;
    if p.is_null() { ::std::alloc::handle_alloc_error(layout); }
    p
}""")
    o.append(ALLOW)
    o.append("""\
#[no_mangle]
pub extern "C" fn pruv_host_alloc_zeroed(len: i64) -> *mut i64 {
    let layout = match ::std::alloc::Layout::array::<i64>(len as usize) {
        Ok(l) => l,
        Err(_) => ::std::alloc::handle_alloc_error(::std::alloc::Layout::new::<i64>()),
    };
    let p = unsafe { ::std::alloc::alloc_zeroed(layout) } as *mut i64;
    if p.is_null() { ::std::alloc::handle_alloc_error(layout); }
    p
}""")
    o.append(ALLOW)
    o.append("""\
#[no_mangle]
pub extern "C" fn pruv_host_flush() {
    let _ = ::std::io::Write::flush(&mut ::std::io::stdout());
}""")
    o.append(ALLOW)
    o.append("""\
#[no_mangle]
pub extern "C" fn pruv_host_free(data: *mut i64, len: i64) {
    if data.is_null() || len <= 0 { return; }
    if let Ok(layout) = ::std::alloc::Layout::array::<i64>(len as usize) {
        unsafe { ::std::alloc::dealloc(data as *mut u8, layout) };
    }
}""")
    o.append(ALLOW)
    o.append("""\
#[no_mangle]
pub extern "C" fn pruv_host_alloc_v2(len: i64, size: i64, align: i64) -> *mut u8 {
    let layout = match (len as usize).checked_mul(size as usize).and_then(|b| ::std::alloc::Layout::from_size_align(b, align as usize).ok()) {
        Some(l) => l,
        None => ::std::alloc::handle_alloc_error(::std::alloc::Layout::new::<u8>()),
    };
    let p = unsafe { ::std::alloc::alloc(layout) };
    if p.is_null() { ::std::alloc::handle_alloc_error(layout); }
    p
}""")
    o.append(ALLOW)
    o.append("""\
#[no_mangle]
pub extern "C" fn pruv_host_alloc_zeroed_v2(len: i64, size: i64, align: i64) -> *mut u8 {
    let layout = match (len as usize).checked_mul(size as usize).and_then(|b| ::std::alloc::Layout::from_size_align(b, align as usize).ok()) {
        Some(l) => l,
        None => ::std::alloc::handle_alloc_error(::std::alloc::Layout::new::<u8>()),
    };
    let p = unsafe { ::std::alloc::alloc_zeroed(layout) };
    if p.is_null() { ::std::alloc::handle_alloc_error(layout); }
    p
}""")
    o.append(ALLOW)
    o.append("""\
#[no_mangle]
pub extern "C" fn pruv_host_free_v2(data: *mut u8, len: i64, size: i64, align: i64) {
    if data.is_null() || len <= 0 { return; }
    if let Some(layout) = (len as usize).checked_mul(size as usize).and_then(|b| ::std::alloc::Layout::from_size_align(b, align as usize).ok()) {
        unsafe { ::std::alloc::dealloc(data, layout) };
    }
}""")
    # G3: specializations of generic functions are private (no ABI symbol, not callable from the bindings)
    pubs = [f for f in prog.functions if not getattr(f, "private", False)]
    returns_array = any(is_arr(f.ret) for f in pubs)  # G2 B2: str counts
    decls = []
    for f in pubs:
        if mangle(f.name) != f.name:
            raise Exception("llvmgen: function name %s needs mangling; the bindings use the raw name" % f.name)
        ps = []
        for p in f.params:
            if p.type.name in ("array_u8", "array_bool", "str"):  # G2 A5/B2
                ps += ["*const u8", "i64"]
            elif p.type == ARRAY:
                ps += ["*const i64", "i64"]
            elif p.type in (OPTION, RESULT):
                ps += ["i64", "i64"]
            elif is_agg(p.type):
                ps.append("*const i64")
            else:
                ps.append("i64")
        if f.ret.name == "array_u8":
            ps.append("*mut Pruv__ArrayU8")
        elif f.ret.name == "array_bool":  # G2 A5
            ps.append("*mut Pruv__ArrayBool")
        elif f.ret.name == "str":  # G2 B2
            ps.append("*mut Pruv__Str")
        elif f.ret == ARRAY:
            ps.append("*mut Pruv__Array")
        elif is_agg(f.ret):
            ps.append("*mut i64")
        ret = " -> i64" if f.ret in (I64, BOOL) else (" -> Pruv__Tagged" if f.ret in (OPTION, RESULT) else "")
        decls.append("    fn pruv_abi_%s(%s)%s;" % (typed_abi_name(f), ", ".join("p%d: %s" % (i, t) for i, t in enumerate(ps)), ret))
    if any(f.ret.name == "array_bool" for f in pubs):  # G2 A5
        decls.append("    fn pruv_check_bool(p0: *const u8, p1: i64);")
    if any(f.ret.name == "str" for f in pubs):  # G2 B2
        decls.append("    fn pruv_check_utf8(p0: *const u8, p1: i64);")
    if returns_array:
        decls.append("    fn pruv_runtime_rust_allocator_v2();")
    o.append(ALLOW)
    o.append('extern "C" {\n%s\n}' % "\n".join(decls))
    for f in pubs:
        ps = ", ".join("%s: %s" % (p.name, rust_ty(p.type, True)) for p in f.params)
        ret = "" if f.ret == UNIT else " -> " + rust_ty(f.ret, False)
        pre, args = [], []
        for p in f.params:
            if p.type == I64:
                args.append(p.name)
            elif p.type == BOOL:
                args.append("%s as i64" % p.name)
            elif p.type.name == "array_bool":  # G2 A5
                args += ["%s.as_ptr() as *const u8" % p.name, "%s.len() as i64" % p.name]
            elif p.type.name == "str":  # G2 B2
                args += ["%s.as_ptr()" % p.name, "%s.len() as i64" % p.name]
            elif is_array(p.type):
                args += ["%s.as_ptr()" % p.name, "%s.len() as i64" % p.name]
            elif is_agg(p.type):
                w = "pruv__w_" + p.name
                pre.append("let mut %s = [0i64; %d];" % (w, words(tt, p.type)))
                pre += rs_ser(tt, p.type, p.name, w, 0, [0])
                args.append(w + ".as_ptr()")
            else:
                a, b = ("Some", "None") if p.type == OPTION else ("Ok", "Err")
                pre.append("let (pruv__t_%s, pruv__v_%s): (i64, i64) = match %s { %s(v) => (1, v), %s(v) => (0, v) };"
                           % (p.name, p.name, p.name, a, b))
                if p.type == OPTION:
                    pre[-1] = ("let (pruv__t_%s, pruv__v_%s): (i64, i64) = match %s { Some(v) => (1, v), None => (0, 0) };"
                               % (p.name, p.name, p.name))
                args += ["pruv__t_" + p.name, "pruv__v_" + p.name]
        body = []
        if "io" in f.effects:
            body.append("::std::io::Write::flush(&mut ::std::io::stdout());")
        if is_arr(f.ret):
            body.append("let _ = ::std::hint::black_box(pruv_runtime_rust_allocator_v2 as unsafe extern \"C\" fn());")
        body += pre
        call = "pruv_abi_%s(%s)" % (typed_abi_name(f), ", ".join(args))
        callo = "pruv_abi_%s(%s)" % (typed_abi_name(f), ", ".join(args + ["&mut pruv__out"]))
        if f.ret == UNIT:
            body.append(call + ";")
        elif f.ret == I64:
            body.append(call)
        elif f.ret == BOOL:
            body.append(call + " != 0")
        elif f.ret.name == "array_bool":  # G2 A5
            body.append("let mut pruv__out = Pruv__ArrayBool { data: ::std::ptr::null_mut(), len: 0 };")
            body.append(callo + ";")
            body.append("pruv_check_bool(pruv__out.data, pruv__out.len);")
            body.append("if pruv__out.len > 0 { ::std::vec::Vec::from_raw_parts(pruv__out.data as *mut bool, pruv__out.len as usize, "
                        "pruv__out.len as usize) } else { ::std::vec::Vec::new() }")
        elif f.ret.name == "str":  # G2 B2
            body.append("let mut pruv__out = Pruv__Str { data: ::std::ptr::null_mut(), len: 0 };")
            body.append(callo + ";")
            body.append("pruv_check_utf8(pruv__out.data, pruv__out.len);")
            body.append("if pruv__out.len > 0 { ::std::string::String::from_utf8_unchecked(::std::vec::Vec::from_raw_parts("
                        "pruv__out.data, pruv__out.len as usize, pruv__out.len as usize)) } else { ::std::string::String::new() }")
        elif is_array(f.ret):
            body.append("let mut pruv__out = %s { data: ::std::ptr::null_mut(), len: 0 };"
                        % ("Pruv__ArrayU8" if f.ret.name == "array_u8" else "Pruv__Array"))
            body.append(callo + ";")
            body.append("if pruv__out.len > 0 { ::std::vec::Vec::from_raw_parts(pruv__out.data, pruv__out.len as usize, "
                        "pruv__out.len as usize) } else { ::std::vec::Vec::new() }")
        elif is_agg(f.ret):
            body.append("let mut pruv__out = [0i64; %d];" % words(tt, f.ret))
            body.append("pruv_abi_%s(%s);" % (typed_abi_name(f), ", ".join(args + ["pruv__out.as_mut_ptr()"])))
            body.append(rs_de(tt, f.ret, "pruv__out", 0))
        else:
            a, b = ("Some", "None") if f.ret == OPTION else ("Ok", "Err")
            body.append("let pruv__out = %s;" % call)
            if f.ret == OPTION:
                body.append("if pruv__out.tag != 0 { Some(pruv__out.value) } else { None }")
            else:
                body.append("if pruv__out.tag != 0 { Ok(pruv__out.value) } else { Err(pruv__out.value) }")
        o.append(ALLOW)
        o.append("#[inline]\npub fn %s(%s)%s {\n    unsafe {\n%s\n    }\n}" %
                 (f.name, ps, ret, "\n".join("        " + b for b in body)))
    return "\n".join(o) + "\n"


def gen_llvm(prog, verified=True, trust_callers=False, budget=1 << 30, plan=None):
    """plan: a mono.SpecPlan for a generic program (computed here when omitted; PruvError specialization_limit
    propagates).  The generator works on the concrete plan.program only: no type parameter reaches LLVM."""
    from typeinfo import g2_unimplemented_error, first_g3_use
    if plan is None and first_g3_use(prog) is not None:
        from mono import specialize
        plan = specialize(prog)
    if plan is not None:
        prog = plan.program
    g2err = g2_unimplemented_error(prog, "codegen", skip=("array_u8", "array_bool", "str"))  # G2 B2
    if g2err is not None:  # same as the Rust generator's Err(String); drivers reject earlier with the diagnostic
        raise RuntimeError("unsupported_type: %s" % g2err.message)
    tt = TypeTable(prog)
    m = Mod(tt)
    funcs = {f.name: f for f in prog.functions}
    chunks = []
    if not trust_callers and any(f.requires for f in prog.functions):
        chunks.append(cdivrem(m, True))
        chunks.append(cdivrem(m, False))
    for f in prog.functions:
        g = FnGen(m, funcs, f, verified)
        g.body()
        params = ir_params(f)
        chunks.append(g.render("define internal %s @%s__pruv_body(%s)" % (lty(f.ret), mangle(f.name), sig_text(params))))
        chunks.append(entry_of(m, funcs, f, trust_callers or not f.requires, budget))
        if not getattr(f, "private", False):  # G3: a generic specialization has no ABI symbol
            chunks.append(abi_of(f, tt, m))
    has_str = uses_str(prog)  # G2 B2: walk the AST once
    ir = m.render_strings() + "\n" + type_defs(tt) + ("\n" if prog.types else "") + DECLS + (
        DECLS_U8 if (uses_array_type(prog, "array_u8") or uses_array_type(prog, "array_bool") or has_str)
        else "") + (
        DECLS_BOOL if uses_array_type(prog, "array_bool") else "") + (
        DECLS_STR if has_str else "") + (
        DECLS_REPR if m.uses_repr else "") + "\n" + "\n".join(chunks)  # G2 A5/B2, G3
    return ir, gen_bindings(prog)
