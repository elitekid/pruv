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
  G9 A3 helpers   @pruv_drop__T / @pruv_clone__T / @pruv_box__T / @pruv_dropnode__T / @pruv_clonenode__T (extended
                  types), @pruv_csize__T / @pruv_ceq__T (runtime contracts); see the G9 A3 design note before class Words.
G4 A3 (explicit visibility mode, docs/G4_SPEC.md 4, 7; Program.explicit): the program is the mono plan, so every function and
type already carries its Rust stem (same stems, order and entry set as codegen.py).  Bodies and checked `__pruv_entry`
wrappers are `internal`; `pruv_abi_<entry>` (and `__typed`) exist only for host entries (root `pub`, nongeneric).  Verified:
only a host entry with a requires has a checked `__pruv_entry` (none under trust_callers) and every Pruv call goes to the
body; safe mode: every function with a requires has one and Pruv calls go through it, also under trust_callers (which only
makes the host-boundary `pruv_abi_*` call the body directly).  Representation checks in `pruv_abi_*` run in every mode.
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
from typeinfo import is_collection, contains_collection, encode  # G6 A3
from foreign import CATALOG, CATALOG_CONTRACT_ONLY, first_g6_use  # G6 A3
import foreign_shim  # G6 A3

G6_UNSUPPORTED_MSG = "G6 foreign calls and collections are not implemented by the llvm codegen layer yet"
G6_UNSUPPORTED_FIX = "avoid trusted rust fn, Vec, HashMap, String, take and move for now"
G6_BRIDGE_DECL = "@pruv_g6_bridge_v1 = external global i8\n"

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

# G9 A3: only emitted when the program has a recursive (boxed) edge.  The marker global is kept alive through
# @llvm.used, so linking a runtime without pruv_runtime_nodes_v1 fails even when no node helper survives inlining.
DECLS_NODE = ("declare noalias ptr @pruv_node_alloc_v1(i64, i64) nounwind\n"
              "declare void @pruv_node_free_v1(ptr nocapture, i64, i64) nounwind\n"
              "declare void @pruv_runtime_nodes_v1() nounwind\n"
              "@pruv_nodes_marker = internal global ptr @pruv_runtime_nodes_v1\n"
              '@llvm.used = appending global [1 x ptr] [ptr @pruv_nodes_marker], section "llvm.metadata"\n')

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
    if is_collection(t):  # G6 A3: opaque handle
        return "ptr"
    if gopt(t):
        return st(t)
    r = {"i64": "i64", "bool": "i1", "unit": "void", "array": ARR, "array_u8": ARR, "array_bool": ARR,
         "str": ARR, "option": OPT, "result": OPT}.get(t.name)
    return r if r is not None else "%%pruv_t_%s" % t.name


def vkind(t):
    if is_collection(t):  # G6 A3
        return "coll"
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
    if n in ("array", "array_u8", "array_bool", "str"):  # G9 A3: buffer fields keep the { ptr, i64 } form
        return ARR
    return "%%pruv_%s_%s" % ("c" if c else "t", n)


def payload_index(tt, ty, variant, i):
    """storage index of field i of `variant` inside the flattened enum %pruv_t_/%pruv_c_ type"""
    # the variant -> base offset map is computed once per (type table, type name): rescanning the variants on every
    # call made helper generation quadratic in the number of variants
    memo = tt.__dict__.setdefault("_payload_memo", {})
    offs = memo.get(ty.name)
    if offs is None:
        offs, base = {}, 1
        for v in tt.decl(ty).variants:
            offs[v.name] = base
            base += len(v.fields)
        memo[ty.name] = offs
    if variant not in offs:
        raise KeyError(variant)
    return offs[variant] + i


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


def fld_label(d, vname, fname):
    """G9 field label as in prog.g9["boxed"]: "Struct.field" or "Enum::Variant.field" """
    return "%s.%s" % (d.name, fname) if vname is None else "%s::%s.%s" % (d.name, vname, fname)


def new_tt(prog):
    """type table of a program: SCC-condensed declaration order for G9 programs (identical to TypeTable otherwise),
    plus the G9 metadata sets tt.g9_ext (extended declaration names) and tt.g9_boxed (boxed field labels)"""
    tt = codegen.make_type_table(prog)
    tt.g9_ext, tt.g9_boxed = codegen.g9_sets(prog)
    return tt


def is_ext_t(tt, t):
    """t is an extended user type (G9): recursive, or holding a buffer or an extended type"""
    return bool(tt.g9_ext) and t is not None and t.owner is None and not t.args and t.name in tt.g9_ext


def type_defs(tt):
    out = []
    ext, boxed = tt.g9_ext, tt.g9_boxed
    for c in (False, True):
        for d in tt.order:
            if c and d.name in ext:     # G9: an extended value has no i128 contract mirror
                continue

            def fs_of(fields, vname):
                # a boxed (recursive SCC) field is an opaque ptr to an independently allocated node
                return ["ptr" if fld_label(d, vname, f.name) in boxed else st(f.type, c) for f in fields]
            if isinstance(d, StructDecl):
                fs = fs_of(d.fields, None)
            else:
                fs = ["i64"]
                for v in d.variants:
                    fs += fs_of(v.fields, v.name)
            out.append("%%pruv_%s_%s = type %s" % ("c" if c else "t", d.name, "{ %s }" % ", ".join(fs) if fs else "{}"))
    return "\n".join(out) + ("\n" if out else "")


def type_has_field(prog, name):
    """G9: some struct field / enum payload has the internal type `name` (array_u8, array_bool, str)"""
    for d in prog.types:
        fields = d.fields if isinstance(d, StructDecl) else [f for v in d.variants for f in v.fields]
        if any(f.type.name == name for f in fields):
            return True
    return False


class V:
    """an SSA value: k in i64 | i1 | i128 | arr (a=ptr, b=len) | opt (a=tag i1, b=payload) | unit |
    agg (a=aggregate SSA of a user struct/enum, ty=its Type; %pruv_t_* in code, %pruv_c_* in requires) |
    coll (G6: a=ptr, an opaque handle of a Vec/HashMap/String box, ty=its Type) |
    ref (G9 contract evaluation: a=ptr to the REAL storage of an extended value, ty=its Type).
    p (G9, agg only): address of storage that holds this value when known (a parameter, a local slot, a boxed
    node, a call-result slot); lets a read argument pass the pointer instead of spilling a copy."""
    __slots__ = ("k", "a", "b", "ty", "p")

    def __init__(s, k, a=None, b=None, ty=None, p=None):
        s.k, s.a, s.b, s.ty, s.p = k, a, b, ty, p


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
        s.g6_decls = {}         # G6 A3: shim symbol -> declare line
        s.g6_v2 = False         # G6 A3: string_to_str needs the v2 copy/free declarations
        s.g6_bridge = False     # G6 A3: some function references @pruv_g6_bridge_v1
        s.need_size = set()     # G9 A3: types whose runtime-contract size / equality helpers are needed
        s.need_eq = set()
        s.explicit = False      # G4 A3: explicit visibility mode (set by gen_llvm); Pruv calls use the Rust-backend routing

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


def ir_ret(tt, f):
    """internal LLVM result type: an extended (G9) aggregate result goes through explicit output storage"""
    return "void" if is_ext_t(tt, f.ret) else lty(f.ret)


def has_inout(f):
    """G5 A3: some parameter has the inout mode (a mutable borrow of caller storage)"""
    return any(p.mode == "inout" for p in f.params)


def is_internal_fn(f, tt):
    """G9: a function with an extended type in its signature has no raw ABI wrapper and no binding;
    G5 A3: neither has a function with an inout parameter (one host-eligibility rule)"""
    return any(is_ext_t(tt, p.type) for p in f.params) or is_ext_t(tt, f.ret) or has_inout(f)


def ir_params(f, tt=None):
    """internal parameter list [(type, name)].  G9: an extended result is the leading `ptr %out` (output storage);
    an extended parameter is a plain `ptr %p.NAME` to valid caller-owned storage (no noalias: the same subtree can
    be passed twice)."""
    out = []
    if tt is not None and is_ext_t(tt, f.ret):
        out.append(("ptr", "%out"))
    for p in f.params:
        if tt is not None and is_ext_t(tt, p.type):
            out.append(("ptr", "%%p.%s" % mangle(p.name)))
            continue
        n = mangle(p.name)
        if is_arr(p.type):
            out += [("ptr", "%%p.%s.a" % n), ("i64", "%%p.%s.n" % n)]
        elif p.type == BOOL:
            out.append(("i1", "%%p.%s" % n))
        elif p.type == I64:
            out.append(("i64", "%%p.%s" % n))
        elif is_collection(p.type):  # G6 A3: plain opaque handle %p.NAME.h (no readonly/noalias attributes)
            out.append(("ptr", "%%p.%s.h" % n))
        elif is_agg(p.type):
            out.append((lty(p.type), "%%p.%s" % n))
        else:
            out.append((OPT, "%%p.%s" % n))
    return out


def sig_text(params, f=None):
    """definition parameter list of an internal function: array pointers are read-only borrows (their IR names
    end in .a; a G6 collection handle %p.NAME.h is a plain ptr).  G5 A3: with the function `f`, the pointer of an
    inout parameter is a mutable borrow: `ptr noalias nocapture` (no readonly)"""
    mut = set("%%p.%s.a" % mangle(p.name) for p in f.params if p.mode == "inout") if f is not None else ()
    return ", ".join("%s %s" % (("ptr noalias nocapture" if n in mut else "ptr noalias nocapture readonly")
                                if t == "ptr" and n.endswith(".a") else t, n)
                     for t, n in params)


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
        s.cregions = []     # G9: constructor temporaries of the contract expression being evaluated, per region
        s.tt = m.tt
        s.bridge = False    # G6 A3: this function references @pruv_g6_bridge_v1

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
        lines = s.lines
        if s.bridge:
            # G6 A3: a (volatile) read of the shim's bridge marker keeps the reference alive: linking without the
            # shim fails.  lines[0] is the `start:` label.
            lines = lines[:1] + ["  %g6.bridge = load volatile i8, ptr @pruv_g6_bridge_v1"] + lines[1:]
            s.m.g6_bridge = True
        out += lines
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
        if kind == "coll":  # G6 A3: owner slot, null-initialized
            s.allocas.append("%s = alloca ptr" % a)
            s.allocas.append("store ptr null, ptr %s" % a)
            return Slot("coll", a, None, ty)
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
            return V("agg", s.op("load %s, ptr %s" % (lty(sl.ty), sl.a)), None, sl.ty, sl.a)
        if sl.k == "coll":
            return V("coll", s.op("load ptr, ptr %s" % sl.a), None, sl.ty)
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
        elif sl.k == "coll":
            s.ins("store ptr %s, ptr %s" % (v.a, sl.a))
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

    # ---------- G9 A3: extended values (ownership helpers) ----------
    def is_ext(s, t):
        return is_ext_t(s.tt, t)

    def fb(s, ty, variant, fname):
        """the field `fname` (of `variant` for an enum) of the user type ty is a boxed recursive edge"""
        return bool(s.tt.g9_boxed) and is_user_type(ty) and fld_label(s.tt.decl(ty), variant, fname) in s.tt.g9_boxed

    def spill(s, v):
        """address of storage that holds the aggregate v: its known address, else a fresh entry-block copy"""
        if v.p is not None:
            return v.p
        base = "%%sp%d" % s.nslot
        s.nslot += 1
        s.allocas.append("%s = alloca %s" % (base, lty(v.ty)))
        s.ins("store %s %s, ptr %s" % (lty(v.ty), v.a, base))
        return base

    def new_out(s, ty):
        """fresh entry-block output storage for an aggregate result"""
        base = "%%o%d" % s.nslot
        s.nslot += 1
        s.allocas.append("%s = alloca %s" % (base, lty(ty)))
        return base

    def fresh(s, v, owned):
        """a fresh extended value: owned by the destination, or a temporary dropped at the end of the statement"""
        if not owned:
            s.temps[-1].append(v)
        return v

    def clone_val(s, v):
        """deep copy of the extended value v (a view) into new owned storage"""
        src = s.spill(v)
        dst = s.new_out(v.ty)
        s.ins("call void @pruv_clone__%s(ptr %s, ptr %s)" % (v.ty.name, src, dst))
        return V("agg", s.op("load %s, ptr %s" % (lty(v.ty), dst)), None, v.ty, dst)

    def drop_agg(s, v):
        s.ins("call void @pruv_drop__%s(ptr %s)" % (v.ty.name, s.spill(v)))

    def view_ptr(s, e):
        """address of the storage of an extended expression in a READ position (argument): a local slot or a
        parameter is passed as is, a fresh temporary lives (registered in s.temps) until the end of the statement"""
        if isinstance(e, Var):
            kind, x = s.lookup(e.name)
            if kind == "slot":
                return x.a
            return s.spill(x)
        return s.spill(s.ev(e))

    def getf(s, base, ty, idx, fd, variant, c=False):
        """field value of the aggregate `base` (type ty) at storage index idx; a boxed field is a VIEW of the child
        node (a shallow load, never dropped through this value)"""
        if not c and s.fb(ty, variant, fd.name):
            x = s.op("extractvalue %s %s, %d" % (st(ty, c), base.a, idx))
            return V("agg", s.op("load %s, ptr %s" % (lty(fd.type), x)), None, fd.type, x)
        return s.get(base, ty, idx, fd.type, c)

    def putf(s, acc, ty, idx, v, fd, variant, c=False):
        """insertvalue of the owned field value v; a boxed field first moves into a new node"""
        if not c and s.fb(ty, variant, fd.name):
            nd = s.op("call ptr @pruv_box__%s(%s %s)" % (fd.type.name, lty(fd.type), v.a))
            return s.op("insertvalue %s %s, ptr %s, %d" % (st(ty, c), acc, nd, idx))
        return s.put(acc, ty, idx, v, fd.type, c)

    def assign_path(s, sl, path, v):
        """store the owned value v into the field path of the extended local slot sl (in place).  The old value of
        the last field is released (nodes: drop then free; buffers: free) after v is complete."""
        cur, cty = sl.a, sl.ty
        for k, fname in enumerate(path):
            i = s.tt.field_index(cty, fname)
            fd = s.tt.fields(cty)[i]
            g = s.op("getelementptr inbounds %s, ptr %s, i32 0, i32 %d" % (lty(cty), cur, i))
            boxed = s.fb(cty, None, fname)
            if k < len(path) - 1:
                cur = s.op("load ptr, ptr %s" % g) if boxed else g
                cty = fd.type
                continue
            ft = fd.type
            if boxed:
                old = s.op("load ptr, ptr %s" % g)
                s.ins("call void @pruv_dropnode__%s(ptr %s)" % (ft.name, old))
                nd = s.op("call ptr @pruv_box__%s(%s %s)" % (ft.name, lty(ft), v.a))
                s.ins("store ptr %s, ptr %s" % (nd, g))
            elif is_arr(ft):
                x = s.op("load %s, ptr %s" % (ARR, g))
                s.free_val(V("arr", s.op("extractvalue %s %s, 0" % (ARR, x)), s.op("extractvalue %s %s, 1" % (ARR, x)),
                             elem_ty(ft)))
                s.ins("store %s %s, ptr %s" % (ARR, s.agg(v), g))
            elif s.is_ext(ft):
                s.ins("call void @pruv_drop__%s(ptr %s)" % (ft.name, g))
                s.ins("store %s %s, ptr %s" % (lty(ft), v.a, g))
            else:
                s.ins("store %s %s, ptr %s" % (st(ft), s.pack(v, ft, False), g))

    def free_val(s, v):
        if v.k == "coll":  # G6 A3: a fresh (non-null) collection temporary
            s.g6_drop(v)
        elif v.k == "agg":  # G9 A3: an extended temporary
            s.drop_agg(v)
        elif is_bytes(v):  # G2 A5
            s.ins("call void @pruv_free_v2(ptr %s, i64 %s, i64 1, i64 1)" % (v.a, v.b))
        else:
            s.ins("call void @pruv_free(ptr %s, i64 %s)" % (v.a, v.b))

    def free_scope(s, sc):
        for sl in reversed(sc["arrays"]):
            if sl.k == "coll":
                s.drop_slot(sl)
            elif sl.k == "agg":     # G9 A3: an owned extended local
                s.ins("call void @pruv_drop__%s(ptr %s)" % (sl.ty.name, sl.a))
            else:
                s.free_val(s.load(sl))

    def hold(s, v):
        """move a temporary into a fresh owner slot (returned); the caller registers it in a scope"""
        if v.k == "agg":
            sl = s.new_slot("hold", v.ty)
        elif v.k == "coll":
            sl = s.new_slot("hold", v.ty)
        else:
            sl = s.new_slot("hold", ARRAY)
            sl.ty = v.ty
        s.store(sl, v)
        return sl

    # ---------- G6 A3: shim calls, owner slots ----------
    def g6_decl(s, sym, ret, argtys):
        s.m.g6_decls[sym] = "declare %s @%s(%s) nounwind" % (ret, sym, ", ".join(argtys))
        s.bridge = True

    def g6_call(s, sym, ret, args):
        """call a bridge symbol; args: [(llvm type, value)]; returns the SSA result (None for void)"""
        s.g6_decl(sym, ret, [t for t, _ in args])
        a = ", ".join("%s %s" % (t, v) for t, v in args)
        if ret == "void":
            s.ins("call void @%s(%s)" % (sym, a))
            return None
        return s.op("call %s @%s(%s)" % (ret, sym, a))

    def g6_drop(s, v):
        s.g6_call(foreign_shim.drop_sym(v.ty), "void", [("ptr", v.a)])

    def drop_slot(s, sl):
        """drop the owner slot's collection if it is non-null (moved-out slots hold null)"""
        p = s.op("load ptr, ptr %s" % sl.a)
        nn = s.op("icmp ne ptr %s, null" % p)
        dl, el = s.label("gdrop"), s.label("gdone")
        s.condbr(nn, dl, el)
        s.place(dl)
        s.g6_drop(V("coll", p, None, sl.ty))
        s.br(el)
        s.place(el)

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
        if is_arr(ty):  # G9 A3: a buffer field is stored as { ptr, i64 }
            return s.agg(v)
        return v.a

    def unpack(s, x, ty, c):
        n = ty.name
        if is_arr(ty):  # G9 A3
            return V("arr", s.op("extractvalue %s %s, 0" % (ARR, x)), s.op("extractvalue %s %s, 1" % (ARR, x)),
                     elem_ty(ty))
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
            acc = s.putf(acc, ty, i, vals[fd.name], fd, None, c)    # G9: a boxed field moves into a new node
        return V("agg", acc, None, ty)

    def mk_enum(s, e, evf, c):
        ty = Type(e.enum_name)
        vals = [evf(x) for x in e.args]     # left to right
        tag = s.tt.variant_index(ty, e.variant)
        acc = s.op("insertvalue %s zeroinitializer, i64 %d, 0" % (st(ty, c), tag))
        for i, fd in enumerate(s.tt.fields(ty, e.variant)):
            acc = s.putf(acc, ty, payload_index(s.tt, ty, e.variant, i), vals[i], fd, e.variant, c)
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
        owned = []
        for p in s.f.params:
            n = mangle(p.name)
            if is_arr(p.type):
                names[p.name] = ("ssa", V("arr", "%%p.%s.a" % n, "%%p.%s.n" % n, elem_ty(p.type)))
            elif p.type == BOOL:
                names[p.name] = ("ssa", V("i1", "%%p.%s" % n))
            elif p.type == I64:
                names[p.name] = ("ssa", V("i64", "%%p.%s" % n))
            elif is_collection(p.type):  # G6 A3
                s.bridge = True
                if p.take:   # consuming parameter: an owner slot (the callee drops it unless it is moved out)
                    sl = s.new_slot(p.name, p.type)
                    s.ins("store ptr %%p.%s.h, ptr %s" % (n, sl.a))
                    names[p.name] = ("slot", sl)
                    owned.append(sl)
                else:        # borrowed: never dropped here
                    names[p.name] = ("ssa", V("coll", "%%p.%s.h" % n, None, p.type))
            elif s.is_ext(p.type):   # G9 A3: a read view of caller-owned storage; never dropped here
                pv = s.op("load %s, ptr %%p.%s" % (lty(p.type), n))
                names[p.name] = ("ssa", V("agg", pv, None, p.type, "%%p.%s" % n))
            elif is_agg(p.type):
                names[p.name] = ("ssa", V("agg", "%%p.%s" % n, None, p.type))
            else:
                t = s.op("extractvalue %s %%p.%s, 0" % (OPT, n))
                v = s.op("extractvalue %s %%p.%s, 1" % (OPT, n))
                names[p.name] = ("ssa", V("opt", t, v))
        s.scopes.append({"names": names, "arrays": owned})

    def emit_ret(s, v):
        rt = s.f.ret
        if s.is_ext(rt):    # G9 A3: explicit output storage; v is an owned value
            s.ins("store %s %s, ptr %%out" % (lty(rt), v.a))
            s.term("ret void")
        elif rt == UNIT:
            s.term("ret void")
        elif rt in (I64, BOOL) or is_collection(rt):
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
                s.free_scope(s.scopes[0])   # G6 A3: owned (take) parameters; empty for every other program
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
            if sl.k == "arr" or sl.k == "coll" or (sl.k == "agg" and s.is_ext(sl.ty)):
                sc["arrays"].append(sl)     # an owner released when the scope ends
            s.end_temps()
        elif isinstance(st, Assign):
            s.begin_temps()
            sl = s.lookup(st.name)[1]
            v = s.ev(st.value, True)        # the right side is complete and owned before the old value is destroyed
            if sl.k == "arr":
                s.free_val(s.load(sl))
            elif sl.k == "coll":   # G6 A3: drop the old value (null when moved out) after the right side
                s.drop_slot(sl)
            elif sl.k == "agg" and s.is_ext(sl.ty):   # G9 A3
                s.ins("call void @pruv_drop__%s(ptr %s)" % (sl.ty.name, sl.a))
            s.store(sl, v)
            s.end_temps()
        elif isinstance(st, FieldAssign):
            s.begin_temps()
            kind, sl = s.lookup(st.name)
            if kind != "slot":
                raise Exception("llvmgen: field assignment to non-local %s" % st.name)
            if s.is_ext(sl.ty):             # G9 A3: owned right side first, then an in-place store along the path
                v = s.ev(st.value, True)
                s.assign_path(sl, st.fields, v)
                s.end_temps()
                return
            v = s.ev(st.value)              # right side first, then root load -> insertvalue chain -> store
            root = s.load(sl)
            s.store(sl, s.set_path(root, sl.ty, st.fields, v))
            s.end_temps()
        elif isinstance(st, IndexAssign):
            s.begin_temps()
            kind, sl = s.lookup(st.name)
            i = s.ev(st.index)      # index first, then value, in every mode
            v = s.ev(st.value)
            a = sl if kind == "ssa" else s.load(sl)     # G5 A3: an inout parameter is a pointer view, stored through
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
        elif isinstance(st, Par):      # G7 A0: the staging guard stops first; never drop a group silently
            raise PruvError("codegen", st.line, st.col, "parallel_unavailable",
                            "G7 verification is not implemented yet", "remove the par block until G7 is completed")
        elif isinstance(st, Match) and s.is_ext(st.scrutinee.ty):
            # G9 A3: the scrutinee is borrowed, never consumed; every temporary it created (a fresh scrutinee, a
            # fresh base of a field path, a fresh argument) is moved into owner slots of a scope that spans all
            # arms, so it lives until the selected arm exits (also through an early return) and is dropped once.
            s.begin_temps()
            sv = s.ev(st.scrutinee)
            held = s.temps.pop()
            s.push_scope()
            for tv in held:
                s.scopes[-1]["arrays"].append(s.hold(tv))
            s.user_match(st, sv)
            s.pop_scope()
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
                bind[name] = ("ssa", s.getf(sv, ty, payload_index(s.tt, ty, a.ctor, i), fd, a.ctor, False))
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
            v = x if kind == "ssa" else s.load(x)
            if owned and v.k == "agg" and s.is_ext(v.ty):   # G9 A3: a named extended value in an owning position
                return s.clone_val(v)
            return v
        if isinstance(e, Move):   # G6 A3: load the owner slot, then null it
            kind, x = s.lookup(e.name)
            v = s.load(x)
            s.ins("store ptr null, ptr %s" % x.a)
            return v
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
            if s.is_ext(Type(e.name)):   # G9 A3: constructor fields are owning positions; the result is fresh
                return s.fresh(s.mk_struct(e, lambda x: s.ev(x, True), False), owned)
            return s.mk_struct(e, s.ev, False)
        if isinstance(e, EnumCtor):
            if s.is_ext(Type(e.enum_name)):
                return s.fresh(s.mk_enum(e, lambda x: s.ev(x, True), False), owned)
            return s.mk_enum(e, s.ev, False)
        if isinstance(e, FieldAccess):
            b = s.ev(e.base)
            ty = b.ty if b.ty is not None else e.base.ty
            i = s.tt.field_index(ty, e.field)
            fd = s.tt.fields(ty)[i]
            v = s.getf(b, ty, i, fd, None, False)
            if owned and v.k == "agg" and s.is_ext(fd.type):   # G9 A3: a field path in an owning position clones
                return s.clone_val(v)
            return v
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
            x = s.ev(a[0])
            if x.k == "coll":   # G6 A3
                return V("i64", s.g6_call(foreign_shim.len_sym(x.ty), "i64", [("ptr", x.a)]))
            return V("i64", x.b)
        if n in CATALOG and n not in CATALOG_CONTRACT_ONLY and n not in s.funcs:   # G6 A3: reserved names
            return s.catalog_call(e, owned)
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
        if f.foreign is not None:   # G6 A3: trusted rust fn through its bridge adapter
            return s.trusted_call(f, e)
        args = []
        for i, x in enumerate(a):
            if s.is_ext(f.params[i].type):   # G9 A3: a read argument is a pointer to valid caller-owned storage
                args.append("ptr %s" % s.view_ptr(x))
                continue
            if isinstance(x, InoutArg):   # G5 A3: the caller's own pointer and length; no copy, ownership stays put
                v = s.ev(x.expr)
                args += ["ptr %s" % v.a, "i64 %s" % v.b]
                continue
            v = s.ev(x, f.params[i].take)
            if v.k == "coll":   # G6 A3: opaque handle
                args.append("ptr %s" % v.a)
            elif v.k == "arr":
                args += ["ptr %s" % v.a, "i64 %s" % v.b]
            elif v.k == "opt":
                args.append("%s %s" % (OPT, s.agg(v)))
            elif v.k == "agg":
                args.append("%s %s" % (lty(v.ty), v.a))
            else:
                args.append("%s %s" % (v.k, v.a))
        if s.m.explicit:
            # G4 A3 (docs/G4_SPEC.md 4): verified calls go to the body (requires proved); safe-mode calls go through the
            # checked wrapper only when the callee has a requires (no wrapper exists otherwise)
            callee = "@%s__pruv_%s" % (mangle(f.name), "entry" if (not s.verified and f.requires) else "body")
        else:
            callee = "@%s__pruv_%s" % (mangle(f.name), "body" if s.verified else "entry")
        if s.is_ext(f.ret):   # G9 A3: explicit output storage; the result is a fresh owned value
            outp = s.new_out(f.ret)
            s.ins("call void %s(%s)" % (callee, ", ".join(["ptr %s" % outp] + args)))
            r = s.op("load %s, ptr %s" % (lty(f.ret), outp))
            return s.fresh(V("agg", r, None, f.ret, outp), owned)
        if f.ret == UNIT:
            s.ins("call void %s(%s)" % (callee, ", ".join(args)))
            return V("unit")
        r = s.op("call %s %s(%s)" % (lty(f.ret), callee, ", ".join(args)))
        if f.ret in (I64, BOOL):
            return V(vkind(f.ret), r)
        if is_collection(f.ret):   # G6 A3: fresh owned handle; a temporary unless the caller takes it
            return s.temp_arr(V("coll", r, None, f.ret), owned)
        if is_agg(f.ret):
            return V("agg", r, None, f.ret)
        x0 = s.op("extractvalue %s %s, 0" % (lty(f.ret), r))
        x1 = s.op("extractvalue %s %s, 1" % (lty(f.ret), r))
        if is_arr(f.ret):
            return s.temp_arr(V("arr", x0, x1, elem_ty(f.ret)), owned)
        return V("opt", x0, x1)

    # ---------- G6 A3: catalog operations and trusted rust fn through the bridge ----------
    def g6_arg(s, v):
        """bridge arguments [(type, value)] of an evaluated value: handle ptr, bool as i64 0/1, (ptr, len), i64"""
        if v.k == "coll":
            return [("ptr", v.a)]
        if v.k == "i1":
            return [("i64", s.op("zext i1 %s to i64" % v.a))]
        if v.k == "arr":
            return [("ptr", v.a), ("i64", v.b)]
        return [("i64", v.a)]

    def g6_out(s, kind):
        """fresh entry-block out slot of the given llvm type; returns its name"""
        base = "%%g%d" % s.nslot
        s.nslot += 1
        s.allocas.append("%s = alloca %s" % (base, kind))
        return base

    def catalog_call(s, e, owned):
        n = e.name
        cat = CATALOG[n]
        low, src = foreign_shim.inst_types(e)
        sym = foreign_shim.adapter_sym(foreign_shim.helper_name(n, src))
        args = []
        for p, x in zip(cat.params, e.args):   # arguments once, in source order; take arguments are owned values
            args += s.g6_arg(s.ev(x, bool(p.take)))
        if n in ("vec_new", "map_new", "string_new", "vec_push", "map_insert", "string_push_str",
                 "file_open_read", "file_create", "file_read_all", "file_write_str", "file_write_bytes"):
            r = s.g6_call(sym, "ptr", args)     # a fresh box, or the very same box pointer of a consuming update
            return s.temp_arr(V("coll", r, None, e.ty), owned)
        if n in ("vec_get", "string_byte", "file_close", "file_ok", "file_readable",
                 "file_writable", "file_size", "file_byte"):
            r = s.g6_call(sym, "i64", args)
            if e.ty == BOOL:
                return V("i1", s.op("icmp ne i64 %s, 0" % r))
            return V("i64", r)
        if n == "map_get":
            tag, val = s.g6_out("i64"), s.g6_out("i64")
            s.g6_call(sym, "void", args + [("ptr", tag), ("ptr", val)])
            t = s.op("load i64, ptr %s" % tag)
            x = s.op("load i64, ptr %s" % val)
            t1 = s.op("icmp ne i64 %s, 0" % t)
            if e.ty == OPTION:
                return V("opt", t1, x)
            x1 = s.op("icmp ne i64 %s, 0" % x)      # Option<bool>: { i1, i1 }
            T = st(e.ty)
            a0 = s.op("insertvalue %s zeroinitializer, i1 %s, 0" % (T, t1))
            return V("agg", s.op("insertvalue %s %s, i1 %s, 1" % (T, a0, x1)), None, e.ty)
        if n == "string_to_str":
            s.m.g6_v2 = True
            d, l = s.g6_out("ptr"), s.g6_out("i64")
            s.g6_call(foreign_shim.STRING_BYTES_SYM, "void", args + [("ptr", d), ("ptr", l)])
            dp = s.op("load ptr, ptr %s" % d)
            ln = s.op("load i64, ptr %s" % l)
            p = s.op("call ptr @pruv_copy_v2(ptr %s, i64 %s, i64 1, i64 1)" % (dp, ln))
            return s.temp_arr(V("arr", p, ln, STR), owned)
        raise Exception("llvmgen: unsupported catalog operation %s" % n)

    def trusted_call(s, f, e):
        args = []
        for x in e.args:
            args += s.g6_arg(s.ev(x))
        sym = foreign_shim.adapter_sym(f.name)
        if f.ret == UNIT:
            s.g6_call(sym, "void", args)
            return V("unit")
        r = s.g6_call(sym, "i64", args)
        if f.ret == BOOL:
            return V("i1", s.op("icmp ne i64 %s, 0" % r))
        return V("i64", r)

    # ---------- contract evaluation (requires), i128 ----------
    def bind_contract_params(s):
        s.place("start")
        s.cparams = set(p.name for p in s.f.params)
        for p in s.f.params:
            n = mangle(p.name)
            if is_arr(p.type):
                s.cenv[p.name] = V("arr", "%%p.%s.a" % n, "%%p.%s.n" % n, elem_ty(p.type))
            elif p.type == BOOL:
                s.cenv[p.name] = V("i1", "%%p.%s" % n)
            elif p.type == I64:
                s.cenv[p.name] = V("i128", s.op("sext i64 %%p.%s to i128" % n))
            elif is_collection(p.type):   # G6 A3: only len(c) is evaluable in a requires on LLVM
                s.cenv[p.name] = V("coll", "%%p.%s.h" % n, None, p.type)
            elif s.is_ext(p.type):   # G9 A3: no i128 mirror; contracts read the REAL storage lazily (see cx)
                s.cenv[p.name] = V("ref", "%%p.%s" % n, None, p.type)
            elif is_agg(p.type):
                s.cenv[p.name] = s.to_c(V("agg", "%%p.%s" % n, None, p.type), p.type)
            else:
                t = s.op("extractvalue %s %%p.%s, 0" % (OPT, n))
                v = s.op("extractvalue %s %%p.%s, 1" % (OPT, n))
                s.cenv[p.name] = V("opt", t, s.op("sext i64 %s to i128" % v))

    # ---------- G9 A3: contract operands over REAL values ----------
    def g9_unsupported(s, e, what):
        return PruvError("codegen", e.line, e.col, "unsupported_type",
                         "%s is not supported in a runtime requires by the llvm codegen layer yet" % what,
                         "compare tags with is_variant and fields with variant_field, or move the check into the body")

    def tag_ptr(s, ty, p):
        return s.op("getelementptr inbounds %s, ptr %s, i32 0, i32 0" % (lty(ty), p))

    def cx(s, e):
        """pointer to the REAL (code form) storage of a contract operand of nominal or buffer type.  Nothing is
        converted eagerly, so an inactive variant or a skipped operand is never inspected.  Supported (same set as the
        Rust backend): a parameter, a field path, variant_field (partial: pruv_panic_undefined when the variant is not
        active; the tag is checked before the payload address is formed) and nullary constructors."""
        und = lambda msg: s.panic1("pruv_panic_undefined", msg)
        if isinstance(e, Var):
            if e.name not in s.cparams:
                raise s.g9_unsupported(e, "the variable %s as an aggregate operand" % e.name)
            n = mangle(e.name)
            if s.is_ext(e.ty):
                return "%%p.%s" % n
            return s.spill(V("agg", "%%p.%s" % n, None, e.ty))     # a non-extended parameter is an SSA value
        if isinstance(e, FieldAccess):
            bty = e.base.ty
            bp = s.cx(e.base)
            i = s.tt.field_index(bty, e.field)
            g = s.op("getelementptr inbounds %s, ptr %s, i32 0, i32 %d" % (lty(bty), bp, i))
            if s.fb(bty, None, e.field):
                g = s.op("load ptr, ptr %s" % g)
            return g
        if isinstance(e, VariantField):
            ety = Type(e.enum_name)
            bp = s.cx(e.value)
            k = s.tt.variant_index(ety, e.variant)
            tag = s.op("load i64, ptr %s" % s.tag_ptr(ety, bp))
            ok = s.op("icmp eq i64 %s, %d" % (tag, k))
            s.guard(ok, und("variant_field expected %s::%s.%s" % (getattr(e, "src_name", e.enum_name), e.variant, e.field)),
                    False)
            i = s.tt.field_index(ety, e.field, e.variant)
            g = s.op("getelementptr inbounds %s, ptr %s, i32 0, i32 %d" % (
                lty(ety), bp, payload_index(s.tt, ety, e.variant, i)))
            if s.fb(ety, e.variant, e.field):
                g = s.op("load ptr, ptr %s" % g)
            return g
        if isinstance(e, EnumCtor) and not e.args:
            ety = Type(e.enum_name)
            x = s.op("insertvalue %s zeroinitializer, i64 %d, 0" % (st(ety), s.tt.variant_index(ety, e.variant)))
            return s.spill(V("agg", x, None, ety))
        if isinstance(e, StructLit) and not e.fields:
            return s.spill(V("agg", "zeroinitializer", None, Type(e.name)))
        if isinstance(e, (EnumCtor, StructLit)):
            # a constructor with payload is a REAL temporary of the type (code form) in entry-block storage.  An
            # extended one owns heap parts: it is dropped when the enclosing evaluation region ends (cregion).
            v = s.g9_real(e)
            base = "%%ct%d" % s.nslot
            s.nslot += 1
            s.allocas.append("%s = alloca %s" % (base, lty(v.ty)))
            s.ins("store %s %s, ptr %s" % (lty(v.ty), v.a, base))
            if s.is_ext(v.ty):
                s.cregions[-1].append((v.ty, base))
            return base
        raise s.g9_unsupported(e, "this expression as an aggregate operand")

    def cregion(s, fn):
        """run fn (a contract evaluation) and then drop the extended constructor temporaries it created, newest first.
        A region is a requires clause, a short-circuit right side or a quantifier body iteration: every temporary of
        a region is built on the straight-line path that reaches its end."""
        s.cregions.append([])
        r = fn()
        for ty, p in reversed(s.cregions.pop()):
            s.ins("call void @pruv_drop__%s(ptr %s)" % (ty.name, p))
        return r

    def g9_real(s, e, ty=None):
        """V (code form, OWNED) of the REAL value of the contract expression e of declared type ty (default e.ty).
        Constructors are built field by field in declaration order; an i64 comes from the i128 contract value through
        a checked narrowing; a named value / part is charged its weight and then deep-copied; a buffer is charged its
        length and then copied.  Same order of effects and messages as the Rust backend."""
        if isinstance(e, StructLit):
            sty = Type(e.name)
            inits = {f.name: f.value for f in e.fields}
            acc = "zeroinitializer"
            for i, fd in enumerate(s.tt.fields(sty)):
                acc = s.putf(acc, sty, i, s.g9_real(inits[fd.name], fd.type), fd, None, False)
            return V("agg", acc, None, sty)
        if isinstance(e, EnumCtor):
            ety = Type(e.enum_name)
            acc = s.op("insertvalue %s zeroinitializer, i64 %d, 0" % (st(ety), s.tt.variant_index(ety, e.variant)))
            for i, (a, fd) in enumerate(zip(e.args, s.tt.fields(ety, e.variant))):
                acc = s.putf(acc, ety, payload_index(s.tt, ety, e.variant, i), s.g9_real(a, fd.type), fd, e.variant,
                             False)
            return V("agg", acc, None, ety)
        t = ty if ty is not None else e.ty
        if isinstance(e, Ctor):
            px = t.args[0] if t is not None and t.args else I64
            if t is not None and gopt(t):
                if e.name == "None":
                    return V("agg", "zeroinitializer", None, t)
                if e.name in ("Some", "Ok"):
                    x = s.g9_real(e.arg, px)
                    acc = s.op("insertvalue %s zeroinitializer, i1 true, 0" % st(t))
                    return V("agg", s.put(acc, t, 1, x, px, False), None, t)
                x = s.g9_real(e.arg, I64)
                return V("agg", s.op("insertvalue %s zeroinitializer, i64 %s, 2" % (st(t), x.a)), None, t)
            if e.name == "None":
                return V("opt", "false", "0")
            x = s.g9_real(e.arg, px if e.name != "Err" else I64)
            return V("opt", "true" if e.name in ("Some", "Ok") else "false", x.a)
        if t is None or (t.owner is None and t.name == "i64"):
            x = s.cev(e)
            tr = s.op("trunc i128 %s to i64" % x.a)
            back = s.op("sext i64 %s to i128" % tr)
            ok = s.op("icmp eq i128 %s, %s" % (back, x.a))
            s.guard(ok, s.panic1("pruv_panic_undefined", "constructor field out of i64 range"), False)
            return V("i64", tr)
        if t.owner is None and t.name == "bool":
            return V("i1", s.cev(e).a)
        if isinstance(e, (Var, FieldAccess, VariantField)) and (is_user_type(t) or t.name in ("option", "result")):
            if is_user_type(t) and not t.args and s.tt.holds_buffer(t.name):
                raise s.g9_unsupported(e, "a copy of a value holding an array or str")
            p = s.cx(e)
            s.g9_charge_weight(t, p)
            if s.is_ext(t):
                return s.clone_val(V("agg", None, None, t, p))
            return s.unpack(s.op("load %s, ptr %s" % (lty(t), p)), t, False)
        if is_arr(t):
            a = s.cev(e)
            s.spend(a.b)
            if is_bytes(a):
                np_ = s.op("call ptr @pruv_copy_v2(ptr %s, i64 %s, i64 1, i64 1)" % (a.a, a.b))
            else:
                np_ = s.op("call ptr @pruv_copy(ptr %s, i64 %s)" % (a.a, a.b))
            return V("arr", np_, a.b, elem_ty(t))
        raise s.g9_unsupported(e, "this expression as a constructor field of an aggregate operand")

    def g9_real_path(s, e):
        """e reads a part of a REAL (extended) value through its storage (cx): a variant_field of an extended value, or
        a field path below one"""
        if isinstance(e, VariantField):
            return s.is_ext(e.value.ty) or s.g9_real_path(e.value)
        if isinstance(e, FieldAccess):
            return s.is_ext(e.base.ty) or s.g9_real_path(e.base)
        return False

    def g9_charge_weight(s, t, p):
        """charge the contract budget the weight of the value of type t stored at p (one unit per nominal node); a
        type without nominal parts costs nothing"""
        for n in codegen.nominals_in(t):
            s.m.need_size.add(n)
        g9_weight(s, t, p, s.budget)

    def cload(s, e):
        """value of a field path / variant_field whose root is an extended value: a buffer (arr), an extended value
        (ref) or a scalar-like value converted to its contract form.  A whole nominal value is converted whole, so
        its weight is charged to the budget first."""
        p = s.cx(e)
        t = e.ty
        if is_arr(t):
            x = s.op("load %s, ptr %s" % (ARR, p))
            return V("arr", s.op("extractvalue %s %s, 0" % (ARR, x)), s.op("extractvalue %s %s, 1" % (ARR, x)),
                     elem_ty(t))
        if s.is_ext(t):
            return V("ref", p, None, t)
        s.g9_charge_weight(t, p)
        x = s.op("load %s, ptr %s" % (st(t), p))
        return s.to_c(s.unpack(x, t, False), t)

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
                return V("i1", s.shortcircuit(l.a, lambda: s.cregion(lambda: s.cev(e.right)).a, op != "&&"))
            if op in ("==", "!=") and s.is_ext(e.left.ty):
                # G9 A3: structural equality of buffer-free extended aggregates, visited lazily on the real values:
                # one budget unit per visited node pair, only the active variant's fields are compared
                pl = s.cx(e.left)
                pr = s.cx(e.right)
                s.m.need_eq.add(e.left.ty.name)
                eq = s.op("call i1 @pruv_ceq__%s(ptr %s, ptr %s, ptr %s)" % (e.left.ty.name, pl, pr, s.budget))
                if op == "!=":
                    eq = s.op("xor i1 %s, true" % eq)
                return V("i1", eq)
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
            if e.array.ty is not None and is_collection(e.array.ty):   # G6 A3: not evaluable on LLVM yet
                raise PruvError("codegen", e.line, e.col, "unsupported_type", G6_UNSUPPORTED_MSG, G6_UNSUPPORTED_FIX)
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
            if s.is_ext(e.base.ty) or s.g9_real_path(e.base):   # G9: a field of a real value, read through its storage
                return s.cload(e)
            b = s.cev(e.base)
            i = s.tt.field_index(b.ty, e.field)
            return s.get(b, b.ty, i, s.tt.fields(b.ty)[i].type, True)
        if isinstance(e, IsVariant):
            if s.is_ext(e.value.ty) or s.g9_real_path(e.value):    # G9: the tag of the real value
                ety = e.value.ty
                p = s.cx(e.value)
                tag = s.op("load i64, ptr %s" % s.tag_ptr(ety, p))
                return V("i1", s.op("icmp eq i64 %s, %d" % (tag, s.tt.variant_index(ety, e.variant))))
            b = s.cev(e.value)
            k = s.tt.variant_index(b.ty, e.variant)
            return V("i1", s.op("icmp eq i64 %s, %d" % (s.tag_of(b, True), k)))
        if isinstance(e, VariantField) and (s.is_ext(e.value.ty) or s.g9_real_path(e.value)):
            return s.cload(e)
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
            if n in ("file_ok", "file_readable", "file_writable", "file_size", "file_byte"):
                x = s.cev(a[0])
                args = [("ptr", x.a)]
                if n == "file_byte":
                    i = s.cev(a[1])
                    size = s.g6_call(foreign_shim.adapter_sym("pruv_g6_file_size"), "i64", args)
                    size = s.op("zext i64 %s to i128" % size)
                    ok = s.op("icmp ult i128 %s, %s" % (i.a, size))
                    s.guard(ok, und("array index out of range"), False)
                    args += [("i64", s.op("trunc i128 %s to i64" % i.a))]
                r = s.g6_call(foreign_shim.adapter_sym("pruv_g6_" + n), "i64", args)
                if e.ty == BOOL:
                    return V("i1", s.op("icmp ne i64 %s, 0" % r))
                return V("i128", s.op("zext i64 %s to i128" % r))
            if n == "size":   # G9 A3: structural size of the real value, checked i128 additions, one unit per node
                p = s.cx(a[0])
                s.m.need_size.add(a[0].ty.name)
                return V("i128", s.op("call i128 @pruv_csize__%s(ptr %s, ptr %s)" % (a[0].ty.name, p, s.budget)))
            if n == "len":
                x = s.cev(a[0])
                if x.k == "coll":   # G6 A3
                    ln = s.g6_call(foreign_shim.len_sym(x.ty), "i64", [("ptr", x.a)])
                    return V("i128", s.op("zext i64 %s to i128" % ln))
                return V("i128", s.op("zext i64 %s to i128" % x.b))
            if n in CATALOG_CONTRACT_ONLY:   # G6 A3: map_lookup / map_updated: not evaluable on LLVM yet
                raise PruvError("codegen", e.line, e.col, "unsupported_type", G6_UNSUPPORTED_MSG, G6_UNSUPPORTED_FIX)
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

    def spend(s, n="1"):
        """consume n units (default one) of the per-entry requires iteration budget (docs/M0_CONTRACTS.md B).  The
        budget is never negative at rest and n is a non-negative length, so the subtraction cannot overflow."""
        if not hasattr(s, "budget"):
            raise Exception("llvmgen: internal error: no iteration budget slot")
        old = s.op("load i64, ptr %s" % s.budget)
        nv = s.op("sub i64 %s, %s" % (old, n))
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
        b = s.cregion(lambda: s.cev(e.body))
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
    params = ir_params(f, m.tt)
    rt = ir_ret(m.tt, f)    # G9 A3: "void" for an extended result (output storage is the leading `ptr %out`)
    if trust:
        g.place("start")
    else:
        g.bind_contract_params()
        g.budget = "%req.budget"
        g.allocas.append("%s = alloca i64" % g.budget)
        g.ins("store i64 %d, ptr %s" % (budget, g.budget))
        for r in f.requires:
            c = g.cregion(lambda r=r: g.cev(r))
            msg_fn = m.string(getattr(f, "disp", f.name))   # G4: the source-qualified identity, not the stem
            msg_ex = m.string(show(r))
            g.guard(c.a, lambda a=msg_fn, b=msg_ex: g.ins("call void @pruv_panic_requires(ptr %s, ptr %s)" % (a, b)),
                    False)
    args = ", ".join("%s %s" % (t, n) for t, n in params)
    callee = "@%s__pruv_body" % mangle(f.name)
    if f.ret == UNIT or rt == "void":
        g.ins("call void %s(%s)" % (callee, args))
        g.term("ret void")
    else:
        r = g.op("call %s %s(%s)" % (rt, callee, args))
        g.term("ret %s %s" % (rt, r))
    return g.render("define internal %s @%s__pruv_entry(%s)" % (rt, mangle(f.name), sig_text(params, f)))


# ======================================================================================================================
# G9 A3: recursive values and aggregate buffer fields (docs/G9_SPEC.md 4, 6, 7, 13)
#
# Design note.
#  Layout.  An ordinary acyclic aggregate stays inline (%pruv_t_Name, declaration order).  A field whose type is in the
#    same recursive type SCC as its container (prog.g9["boxed"]) is an opaque `ptr` to an independently allocated node
#    holding one %pruv_t_Child; buffers ([i64], [u8], [bool], str) are { ptr, i64 }.  An enum is { i64 tag, every
#    variant's payload slots }: inactive pointers are null, inactive scalar storage is zero, and only the ACTIVE payload
#    is ever loaded, cloned, compared, sized or dropped.  Node size and alignment come from the target's own layout
#    (getelementptr-from-null, evaluated by the backend), never from Python host sizes.
#  Values.  Code evaluates an extended aggregate as an SSA value that is a shallow copy of its storage.  Whether a value
#    OWNS its resources is decided syntactically, as in the Rust backend: a constructor or a call result is fresh; a
#    variable, a parameter, a match binder or a field path is a borrowed VIEW.  A view is never dropped.
#  Ownership.  Owners are local slots (dropped, in reverse order, when their scope ends and on `return`), fresh
#    temporaries (dropped at the end of the statement; a fresh match scrutinee, and everything created while evaluating
#    it, is moved into a scope that spans all arms), constructor fields and the output storage of a result.  An owning
#    position (let, assignment, constructor field, return, field replacement) receives a fresh value as is and CLONES a
#    view.  An assignment evaluates its right side and takes ownership of the result before the old value is dropped.
#  Calls.  An extended read argument is `ptr` to valid caller-owned storage (a slot, a parameter, a node, or a spilled
#    copy of a fresh temporary that lives through the call).  An extended result is written through the leading
#    `ptr %out`.  Extended signatures are internal (no ABI wrapper, no binding).  Pointer parameters carry no noalias:
#    the same subtree may be passed twice.
#  Helpers (stable names, SCC-condensed declaration order): pruv_drop__T(ptr) releases the owned parts of the value at
#    the pointer, children first, but never the root storage itself; pruv_clone__T(ptr src, ptr dst) writes a deep copy;
#    pruv_box__T / pruv_dropnode__T / pruv_clonenode__T allocate, release and clone a node (pruv_node_alloc_v1 /
#    pruv_node_free_v1); pruv_csize__T and pruv_ceq__T implement `size` and `==` in runtime contracts (checked i128
#    addition, one budget unit per visited node, same messages as the Rust backend helpers).
# ======================================================================================================================
def g9_gep(g, T, p, idx):
    return g.op("getelementptr inbounds %s, ptr %s, i32 0, i32 %d" % (T, p, idx))


def g9_variants(d):
    """[(variant name or None, tag or None, fields)] in declaration order"""
    if isinstance(d, StructDecl):
        return [(None, None, d.fields)]
    return [(v.name, i, v.fields) for i, v in enumerate(d.variants)]


def g9_sidx(tt, ty, vn, i):
    """storage index of field i of variant vn (a struct: vn is None) inside the aggregate"""
    return i if vn is None else payload_index(tt, ty, vn, i)


def g9_each_variant(g, ty, d, base, vs, emit):
    """emit(variant name, fields) for the variants in vs.  A struct runs it inline.  An enum switches on the tag of
    the value at `base` and continues, on every path, at a join label that is left as the current block."""
    if isinstance(d, StructDecl):
        for vn, _t, fs in vs:
            emit(vn, fs)
        return
    if not vs:
        return
    tag = g.op("load i64, ptr %s" % g.tag_ptr(ty, base))
    done = g.label("gdone")
    lbls = [g.label("gv") for _ in vs]
    g.term("switch i64 %s, label %%%s [ %s ]" % (tag, done, " ".join(
        "i64 %d, label %%%s" % (t, l) for (_vn, t, _fs), l in zip(vs, lbls))))
    for (vn, _t, fs), l in zip(vs, lbls):
        g.place(l)
        emit(vn, fs)
        g.br(done)
    g.place(done)


def g9_node_layout(g, T):
    """(size, align) SSA names of the node type T computed by the backend from the target layout"""
    z = g.op("getelementptr %s, ptr null, i32 1" % T)
    size = g.op("ptrtoint ptr %s to i64" % z)
    a = g.op("getelementptr { i8, %s }, ptr null, i32 0, i32 1" % T)
    align = g.op("ptrtoint ptr %s to i64" % a)
    return size, align


def g9_drop_text(m, tt, d):
    ty = Type(d.name)
    T = lty(ty)
    g = FnGen(m, {}, None, True)
    g.place("start")

    def emit(vn, fs):
        for i, f in enumerate(fs):
            ft = f.type
            if not (is_arr(ft) or g.is_ext(ft)):
                continue
            gp = g9_gep(g, T, "%v", g9_sidx(tt, ty, vn, i))
            if g.fb(ty, vn, f.name):       # a boxed child: its contents first, then its node
                c = g.op("load ptr, ptr %s" % gp)
                g.ins("call void @pruv_dropnode__%s(ptr %s)" % (ft.name, c))
            elif is_arr(ft):
                x = g.op("load %s, ptr %s" % (ARR, gp))
                g.free_val(V("arr", g.op("extractvalue %s %s, 0" % (ARR, x)), g.op("extractvalue %s %s, 1" % (ARR, x)),
                             elem_ty(ft)))
            else:                          # an inline extended child (not a node)
                g.ins("call void @pruv_drop__%s(ptr %s)" % (ft.name, gp))
    vs = [(vn, t, fs) for vn, t, fs in g9_variants(d) if any(is_arr(f.type) or g.is_ext(f.type) for f in fs)]
    g9_each_variant(g, ty, d, "%v", vs, emit)
    g.term("ret void")
    return g.render("define internal void @pruv_drop__%s(ptr %%v)" % d.name)


def g9_clone_text(m, tt, d):
    ty = Type(d.name)
    T = lty(ty)
    g = FnGen(m, {}, None, True)
    g.place("start")
    v0 = g.op("load %s, ptr %%src" % T)      # shallow copy: scalars, inactive null/zero slots; owners are fixed below
    g.ins("store %s %s, ptr %%dst" % (T, v0))

    def emit(vn, fs):
        for i, f in enumerate(fs):
            ft = f.type
            if not (is_arr(ft) or g.is_ext(ft)):
                continue
            idx = g9_sidx(tt, ty, vn, i)
            gs = g9_gep(g, T, "%src", idx)
            gd = g9_gep(g, T, "%dst", idx)
            if g.fb(ty, vn, f.name):
                c = g.op("load ptr, ptr %s" % gs)
                nb = g.op("call ptr @pruv_clonenode__%s(ptr %s)" % (ft.name, c))
                g.ins("store ptr %s, ptr %s" % (nb, gd))
            elif is_arr(ft):
                x = g.op("load %s, ptr %s" % (ARR, gs))
                p = g.op("extractvalue %s %s, 0" % (ARR, x))
                n = g.op("extractvalue %s %s, 1" % (ARR, x))
                if is_bytes(V("arr", p, n, elem_ty(ft))):
                    np_ = g.op("call ptr @pruv_copy_v2(ptr %s, i64 %s, i64 1, i64 1)" % (p, n))
                else:
                    np_ = g.op("call ptr @pruv_copy(ptr %s, i64 %s)" % (p, n))
                a1 = g.op("insertvalue %s %s, ptr %s, 0" % (ARR, x, np_))
                g.ins("store %s %s, ptr %s" % (ARR, a1, gd))
            else:
                g.ins("call void @pruv_clone__%s(ptr %s, ptr %s)" % (ft.name, gs, gd))
    vs = [(vn, t, fs) for vn, t, fs in g9_variants(d) if any(is_arr(f.type) or g.is_ext(f.type) for f in fs)]
    g9_each_variant(g, ty, d, "%src", vs, emit)
    g.term("ret void")
    return g.render("define internal void @pruv_clone__%s(ptr %%src, ptr %%dst)" % d.name)


def g9_node_texts(m, tt, d):
    """box / dropnode / clonenode of a type that is the target of a boxed edge"""
    n, T = d.name, lty(Type(d.name))
    out = []
    g = FnGen(m, {}, None, True)
    g.place("start")
    size, align = g9_node_layout(g, T)
    p = g.op("call ptr @pruv_node_alloc_v1(i64 %s, i64 %s)" % (size, align))
    g.ins("store %s %%v, ptr %s" % (T, p))
    g.term("ret ptr %s" % p)
    out.append(g.render("define internal ptr @pruv_box__%s(%s %%v)" % (n, T)))
    g = FnGen(m, {}, None, True)
    g.place("start")
    g.ins("call void @pruv_drop__%s(ptr %%n)" % n)
    size, align = g9_node_layout(g, T)
    g.ins("call void @pruv_node_free_v1(ptr %%n, i64 %s, i64 %s)" % (size, align))
    g.term("ret void")
    out.append(g.render("define internal void @pruv_dropnode__%s(ptr %%n)" % n))
    g = FnGen(m, {}, None, True)
    g.place("start")
    size, align = g9_node_layout(g, T)
    p = g.op("call ptr @pruv_node_alloc_v1(i64 %s, i64 %s)" % (size, align))
    g.ins("call void @pruv_clone__%s(ptr %%src, ptr %s)" % (n, p))
    g.term("ret ptr %s" % p)
    out.append(g.render("define internal ptr @pruv_clonenode__%s(ptr %%src)" % n))
    return out


def g9_walks(t):
    """size / equality walk into t: a nominal value, or Option / Result of one"""
    if gopt(t):
        return g9_walks(t.args[0])
    return is_user_type(t)


def g9_weight(g, t, p, bud="%bud"):
    """i128 SSA value of weight(value stored at p) (G9_SPEC 3), or None when it is statically 0.  Some / Ok weigh their
    payload, None / Err 0; a nominal value weighs its size (one budget unit per node, inside pruv_csize).  bud is the
    budget pointer the size helper charges."""
    if gopt(t):
        X = t.args[0]
        if not g9_walks(X):
            return None
        T = st(t)
        tag = g.op("load i1, ptr %s" % g9_gep(g, T, p, 0))
        pl = g9_gep(g, T, p, 1)
        lcur, yes, end = g.cur, g.label("gwy"), g.label("gwe")
        g.condbr(tag, yes, end)
        g.place(yes)
        w = g9_weight(g, X, pl, bud)
        wcur = g.cur
        g.br(end)
        g.place(end)
        return g.op("phi i128 [ 0, %%%s ], [ %s, %%%s ]" % (lcur, w, wcur))
    if is_user_type(t):
        return g.op("call i128 @pruv_csize__%s(ptr %s, ptr %s)" % (t.name, p, bud))
    return None


def g9_size_text(m, tt, d):
    """pruv_csize__T: 1 + the weights of the ACTIVE fields, checked i128 additions in field order, one budget unit"""
    ty = Type(d.name)
    T = lty(ty)
    g = FnGen(m, {}, None, True)
    g.place("start")
    g.budget = "%bud"
    g.spend()

    def fold(vn, fs):
        acc = "1"
        for i, f in enumerate(fs):
            if not g9_walks(f.type):
                continue
            gp = g9_gep(g, T, "%v", g9_sidx(tt, ty, vn, i))
            if g.fb(ty, vn, f.name):
                gp = g.op("load ptr, ptr %s" % gp)
            acc = g.checked("i128", "sadd", "+", acc, g9_weight(g, f.type, gp))
        return acc
    if isinstance(d, StructDecl):
        g.term("ret i128 %s" % fold(None, d.fields))
    else:
        g.allocas.append("%res = alloca i128")
        g.ins("store i128 1, ptr %res")
        vs = [(vn, t, fs) for vn, t, fs in g9_variants(d) if any(g9_walks(f.type) for f in fs)]
        g9_each_variant(g, ty, d, "%v", vs, lambda vn, fs: g.ins("store i128 %s, ptr %%res" % fold(vn, fs)))
        g.term("ret i128 %s" % g.op("load i128, ptr %res"))
    return g.render("define internal i128 @pruv_csize__%s(ptr %%v, ptr %%bud)" % d.name)


def g9_eq_val(g, t, pa, pb):
    """i1 SSA value: structural equality of the values stored at pa and pb (type t)"""
    n = t.name
    if gopt(t):     # Option<X> / Result<X>: equal tags, then the active payload only
        T = st(t)
        X = t.args[0]
        ta = g.op("load i1, ptr %s" % g9_gep(g, T, pa, 0))
        tb = g.op("load i1, ptr %s" % g9_gep(g, T, pb, 0))
        te = g.op("icmp eq i1 %s, %s" % (ta, tb))
        lcur, l1, lend = g.cur, g.label("gqa"), g.label("gqe")
        g.condbr(te, l1, lend)
        g.place(l1)
        l2 = g.label("gqb")
        if n == "option":
            g.condbr(ta, l2, lend)          # None == None
            g.place(l2)
            e = g9_eq_val(g, X, g9_gep(g, T, pa, 1), g9_gep(g, T, pb, 1))
            l2cur = g.cur
            g.br(lend)
            g.place(lend)
            return g.op("phi i1 [ false, %%%s ], [ true, %%%s ], [ %s, %%%s ]" % (lcur, l1, e, l2cur))
        l3 = g.label("gqc")
        g.condbr(ta, l2, l3)
        g.place(l2)
        e = g9_eq_val(g, X, g9_gep(g, T, pa, 1), g9_gep(g, T, pb, 1))
        l2cur = g.cur
        g.br(lend)
        g.place(l3)
        ea = g.op("load i64, ptr %s" % g9_gep(g, T, pa, 2))
        eb = g.op("load i64, ptr %s" % g9_gep(g, T, pb, 2))
        e3 = g.op("icmp eq i64 %s, %s" % (ea, eb))
        l3cur = g.cur
        g.br(lend)
        g.place(lend)
        return g.op("phi i1 [ false, %%%s ], [ %s, %%%s ], [ %s, %%%s ]" % (lcur, e, l2cur, e3, l3cur))
    if n in ("option", "result"):   # legacy Option<i64> / Result<i64>: { i1, i64 }
        la = g.op("load %s, ptr %s" % (OPT, pa))
        lb = g.op("load %s, ptr %s" % (OPT, pb))
        ta, tb = g.op("extractvalue %s %s, 0" % (OPT, la)), g.op("extractvalue %s %s, 0" % (OPT, lb))
        va, vb = g.op("extractvalue %s %s, 1" % (OPT, la)), g.op("extractvalue %s %s, 1" % (OPT, lb))
        te = g.op("icmp eq i1 %s, %s" % (ta, tb))
        pe = g.op("icmp eq i64 %s, %s" % (va, vb))
        if n == "option":
            pe = g.op("or i1 %s, %s" % (g.op("xor i1 %s, true" % ta), pe))
        return g.op("and i1 %s, %s" % (te, pe))
    if n == "i64" or n == "bool":
        ty = "i64" if n == "i64" else "i1"
        return g.op("icmp eq %s %s, %s" % (ty, g.op("load %s, ptr %s" % (ty, pa)), g.op("load %s, ptr %s" % (ty, pb))))
    if is_user_type(t):
        return g.op("call i1 @pruv_ceq__%s(ptr %s, ptr %s, ptr %%bud)" % (n, pa, pb))
    raise Exception("llvmgen: internal error: no structural equality for type %s" % n)


def g9_eq_text(m, tt, d):
    """pruv_ceq__T: one budget unit, then equal tags and the fields of the active variant, left to right"""
    ty = Type(d.name)
    T = lty(ty)
    g = FnGen(m, {}, None, True)
    g.place("start")
    g.budget = "%bud"
    g.spend()
    fail = g.label("ceqf")

    def conj(vn, fs):
        for i, f in enumerate(fs):
            idx = g9_sidx(tt, ty, vn, i)
            pa, pb = g9_gep(g, T, "%a", idx), g9_gep(g, T, "%b", idx)
            if g.fb(ty, vn, f.name):
                pa, pb = g.op("load ptr, ptr %s" % pa), g.op("load ptr, ptr %s" % pb)
            e = g9_eq_val(g, f.type, pa, pb)
            nxt = g.label("ceqn")
            g.condbr(e, nxt, fail)
            g.place(nxt)
        g.term("ret i1 true")
    if isinstance(d, StructDecl):
        conj(None, d.fields)
    else:
        tl = g.op("load i64, ptr %s" % g.tag_ptr(ty, "%a"))
        tr = g.op("load i64, ptr %s" % g.tag_ptr(ty, "%b"))
        same, dflt = g.label("ceqs"), g.label("ceqt")
        g.condbr(g.op("icmp eq i64 %s, %s" % (tl, tr)), same, fail)
        g.place(same)
        vs = [(vn, t, fs) for vn, t, fs in g9_variants(d) if fs]
        lbls = [g.label("ceqv") for _ in vs]
        g.term("switch i64 %s, label %%%s [ %s ]" % (tl, dflt, " ".join(
            "i64 %d, label %%%s" % (t, l) for (_vn, t, _fs), l in zip(vs, lbls))))
        g.place(dflt)
        g.term("ret i1 true")
        for (vn, _t, fs), l in zip(vs, lbls):
            g.place(l)
            conj(vn, fs)
    g.place(fail)
    g.term("ret i1 false")
    return g.render("define internal i1 @pruv_ceq__%s(ptr %%a, ptr %%b, ptr %%bud)" % d.name)


def g9_helper_chunks(m, tt):
    """clone / drop / node helpers of every extended type (SCC-condensed order), then the contract size / equality
    helpers the requires checks needed (closed over the nominal field types, declaration order)"""
    boxed = tt.g9_boxed
    targets = set()
    for d in tt.order:
        for vn, _t, fs in g9_variants(d):
            for f in fs:
                if fld_label(d, vn, f.name) in boxed:
                    targets.add(f.type.name)
    chunks = []
    for d in tt.order:
        if d.name not in tt.g9_ext:
            continue
        chunks.append(g9_drop_text(m, tt, d))
        chunks.append(g9_clone_text(m, tt, d))
        if d.name in targets:
            chunks.extend(g9_node_texts(m, tt, d))

    def close(seed):
        out, work = set(), sorted(seed)
        while work:
            n = work.pop()
            if n in out or n not in tt.decls:
                continue
            out.add(n)
            for _vn, _t, fs in g9_variants(tt.decls[n]):
                for f in fs:
                    work.extend(codegen.nominals_in(f.type))
        return out
    sizes, eqs = close(m.need_size), close(m.need_eq)
    for d in tt.decls.values():
        if d.name in sizes:
            chunks.append(g9_size_text(m, tt, d))
        if d.name in eqs:
            chunks.append(g9_eq_text(m, tt, d))
    return chunks


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
        s.checks.append((ok, w, getattr(d, "disp", ty.name)))   # G4: source-qualified type identity in explicit mode
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


def abi_of(f, tt, m=None, target="entry"):
    """target: which internal function the wrapper calls, `entry` (checked, legacy) or `body` (G4 explicit mode when the
    host boundary needs no requires check). The representation checks below run in every mode."""
    if has_inout(f) or is_internal_fn(f, tt):   # G5 A3: defensive, an inout function is never host-visible
        raise Exception("llvmgen: %s has no host ABI wrapper (inout or extended signature)" % f.name)
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
    entry = "@%s__pruv_%s" % (n, target)
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


def is_host_abi_fn(f, tt, explicit):
    """a function that gets `pruv_abi_*` wrappers: legacy = every ordinary function that is not a specialization or
    collection/extended-bearing; G4 explicit mode = additionally only the host entries (a child-public function is
    never exported just because Pruv callers can name it)"""
    return (f.foreign is None and not getattr(f, "private", False) and not _is_coll_fn(f)
            and not has_inout(f) and not is_internal_fn(f, tt) and (f.host_entry or not explicit))


def entry_type_closure(prog, tt):
    """G4 A3: names of the nominal types reachable from the host entry signatures (parameters and results), following
    Option/Result arguments and struct fields / enum payloads, with a visited set (cycles)"""
    seen = set()
    work = []
    for f in prog.functions:
        if is_host_abi_fn(f, tt, True):
            work += [p.type for p in f.params] + [f.ret]
    while work:
        t = work.pop()
        work += list(t.args or [])
        if is_user_type(t) and t.name not in seen:
            seen.add(t.name)
            d = tt.decls.get(t.name)
            if d is not None:
                fields = d.fields if isinstance(d, StructDecl) else [x for v in d.variants for x in v.fields]
                work += [x.type for x in fields]
    return seen


def gen_bindings(prog, shim=None):
    """shim: the `mod pruv_g6_shim` text of a G6 program (foreign_shim.build_shim); None for every other program"""
    tt = new_tt(prog)
    explicit = bool(getattr(prog, "explicit", False))
    o = []
    o.append("// generated by pruvc llvmgen -- Rust bindings for the LLVM back end (include with #[path] mod sol;)")
    if prog.types:
        if explicit:
            # G4 A3 (docs/G4_SPEC.md 7): only the nominal types the host entry signatures depend on, transitively
            # (declaration order of the type table is kept)
            need = entry_type_closure(prog, tt)
            pub = codegen.emit_public_types(prog, [d for d in tt.order if d.name in need]) if need else ""
        else:
            pub = codegen.emit_public_types(prog)
        if pub:
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
    # G6 A3: trusted declarations and collection-bearing functions have no binding
    # G9 A3: a function with an extended type in its signature has no binding either
    pubs = [f for f in prog.functions if not getattr(f, "private", False) and f.foreign is None
            and not _is_coll_fn(f) and not has_inout(f) and not is_internal_fn(f, tt)
            and (f.host_entry or not explicit)]   # G4: entries only; G5 A3: never an inout function
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
    if shim is not None:   # G6 A3: the bridge shim module, exactly once, last
        o.append(shim.rstrip("\n"))
    return "\n".join(o) + "\n"


def _g6_scalar(t):
    return t == I64 or t == BOOL


def _g6_coll_ok(t):
    """G6_SPEC 13.1 collections, plus the G10 File handle."""
    if t.name == "vec":
        return _g6_scalar(t.args[0])
    if t.name == "hashmap":
        return _g6_scalar(t.args[0]) and _g6_scalar(t.args[1])
    return t.name in ("string", "file")


def _g6_type_ok(t):
    """a type that may occur in a G6 program on LLVM: no collection, or a supported one (never nested)"""
    if is_collection(t):
        return _g6_coll_ok(t)
    return not contains_collection(t)


def g6_llvm_error(prog):
    """PruvError codegen/unsupported_type for the first G6 construct outside G6_SPEC 13.1, or None.  Source order:
    functions in order, the signature before the body, inside a body the earliest position."""
    if first_g6_use(prog) is None:
        return None

    def err(line, col):
        e = PruvError("codegen", line, col, "unsupported_type", G6_UNSUPPORTED_MSG, G6_UNSUPPORTED_FIX)
        e.file = getattr(f, "file", None)   # explicit mode: the function's source file (Rust: the tagged line)
        return e

    for f in prog.functions:
        if f.foreign is not None:
            ok = f.ret in (I64, BOOL, UNIT) and all(
                p.type in (I64, BOOL, ARRAY, ARRAY_U8, ARRAY_BOOL, STR) and not p.take for p in f.params)
            if not ok:
                return err(f.line, f.col)
            continue
        if any(not _g6_type_ok(p.type) for p in f.params) or not _g6_type_ok(f.ret):
            return err(f.line, f.col)
        bad = []

        def visit(n):
            if isinstance(n, Let) and not _g6_type_ok(n.type):
                bad.append((n.line, n.col))
            ty = getattr(n, "ty", None)
            if ty is not None and not _g6_type_ok(ty):
                bad.append((n.line, n.col))
            if isinstance(n, Call) and n.name in CATALOG and n.name not in CATALOG_CONTRACT_ONLY and n.inst:
                if not all(_g6_scalar(a) for a in n.inst["args"]):
                    bad.append((n.line, n.col))

        foreign_shim._walk(f.body, visit)
        if bad:
            line, col = min(bad)
            return err(line, col)
    return None


def _is_coll_fn(f):
    return any(is_collection(p.type) for p in f.params) or is_collection(f.ret)


def gen_llvm(prog, verified=True, trust_callers=False, budget=1 << 30, plan=None, foreign_checks="requires"):
    """plan: a mono.SpecPlan for a generic program (computed here when omitted; PruvError specialization_limit
    propagates).  The generator works on the concrete plan.program only: no type parameter reaches LLVM.
    foreign_checks: G6 boundary check mode of the shim helpers (requires|all|off, docs/G6_SPEC.md 12.3).
    A G6 program outside the supported subset (G6_SPEC 13.1) raises PruvError codegen/unsupported_type."""
    from typeinfo import g2_unimplemented_error, first_g3_use
    if foreign_checks not in ("requires", "all", "off"):
        raise ValueError("foreign_checks must be requires, all or off")
    if plan is None and (first_g3_use(prog) is not None or prog.explicit):   # G4 A3: explicit mode names via mono
        from mono import specialize
        plan = specialize(prog)
    if plan is not None:
        prog = plan.program
    explicit = bool(getattr(prog, "explicit", False))
    g6err = g6_llvm_error(prog)
    if g6err is not None:
        raise g6err
    is_g6 = first_g6_use(prog) is not None
    g2err = g2_unimplemented_error(prog, "codegen", skip=("array_u8", "array_bool", "str"))  # G2 B2
    if g2err is not None:  # same as the Rust generator's Err(String); drivers reject earlier with the diagnostic
        raise RuntimeError("unsupported_type: %s" % g2err.message)
    tt = new_tt(prog)   # G9: SCC-condensed order and the extended / boxed metadata (identical to TypeTable otherwise)
    m = Mod(tt)
    m.explicit = explicit
    funcs = {f.name: f for f in prog.functions}
    chunks = []

    def checked_entry(f):
        """G4 A3 (docs/G4_SPEC.md 4, same policy as codegen.Gen): the functions that get a checked `__pruv_entry`.
        Verified: only host entries with a requires (none under trust_callers); safe mode: every function with a
        requires, also under trust_callers (it removes only the host-boundary checks)"""
        return bool(f.requires) and f.foreign is None and (not verified or (f.host_entry and not trust_callers))

    if explicit:
        need_cdiv = any(checked_entry(f) for f in prog.functions)
    else:
        need_cdiv = any(f.requires and f.foreign is None and (not trust_callers or (not verified and has_inout(f)))
                        for f in prog.functions)    # G5 A3: an inout entry checks also under trust_callers
    if need_cdiv:
        chunks.append(cdivrem(m, True))
        chunks.append(cdivrem(m, False))
    for f in prog.functions:
        if f.foreign is not None:   # G6 A3: a trusted rust fn has no body; its calls go to the shim adapter
            continue
        # G6 A3: collection-bearing functions are internal (no ABI wrapper, no binding); G9 A3: so are functions with
        # an extended type in their signature
        coll = _is_coll_fn(f) or is_internal_fn(f, tt)
        g = FnGen(m, funcs, f, verified)
        g.body()
        params = ir_params(f, tt)
        chunks.append(g.render("define internal %s @%s__pruv_body(%s)" % (ir_ret(tt, f), mangle(f.name), sig_text(params, f))))
        if explicit:
            # G4 A3: bodies and checked wrappers are internal; only a host entry gets pruv_abi_* (and its typed variant).
            # The host boundary calls the checked wrapper unless trust_callers skips the check (or there is no requires).
            if checked_entry(f):
                chunks.append(entry_of(m, funcs, f, False, budget))
            if is_host_abi_fn(f, tt, True):
                chunks.append(abi_of(f, tt, m, "entry" if (checked_entry(f) and not trust_callers) else "body"))
            continue
        if not (coll and verified):   # verified callers call the body; the entry only serves safe-mode callers
            # G5 A3: the entry of an inout function is internal and always checked (trust_callers does not waive it)
            chunks.append(entry_of(m, funcs, f, (trust_callers and not has_inout(f)) or not f.requires, budget))
        if not getattr(f, "private", False) and not coll:  # G3: a generic specialization has no ABI symbol
            chunks.append(abi_of(f, tt, m))
    if tt.g9_ext or m.need_size or m.need_eq:   # G9 A3: clone / drop / node helpers, then the contract helpers above
        chunks.extend(g9_helper_chunks(m, tt))
    # G9 A3: buffer fields count as uses of the buffer runtime declarations
    has_str = uses_str(prog) or type_has_field(prog, "str")  # G2 B2: walk the AST once
    g6decls = ""
    if m.g6_bridge or m.g6_decls:   # G6 A3: bridge marker and the shim symbols used, sorted by symbol
        g6decls = G6_BRIDGE_DECL + "".join(m.g6_decls[k] + "\n" for k in sorted(m.g6_decls))
    g9_u8 = type_has_field(prog, "array_u8") or type_has_field(prog, "array_bool")
    ir = m.render_strings() + "\n" + type_defs(tt) + ("\n" if prog.types else "") + DECLS + (
        DECLS_U8 if (uses_array_type(prog, "array_u8") or uses_array_type(prog, "array_bool") or has_str or m.g6_v2
                     or g9_u8)
        else "") + (
        DECLS_BOOL if uses_array_type(prog, "array_bool") else "") + (
        DECLS_STR if has_str else "") + (
        DECLS_REPR if m.uses_repr else "") + (
        DECLS_NODE if tt.g9_boxed else "") + g6decls + "\n" + "\n".join(chunks)  # G2 A5/B2, G3, G6 A3, G9 A3
    shim = None
    if is_g6:
        shim = foreign_shim.build_shim(prog, verified, trust_callers, budget, foreign_checks)
    return ir, gen_bindings(prog, shim)
