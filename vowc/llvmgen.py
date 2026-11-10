"""Vow -> LLVM IR (text) + Rust bindings.  gen_llvm(prog, verified=True, trust_callers=False)
returns (ir_text, rust_bindings_text).  Semantics reference: codegen.py (Rust back end);
format spec: docs/M1_LLVM_SPEC.md.

Modes (two independent axes, same meaning as codegen.py):
  verified=True   Output of a program the verifier proved: + - * are `add/sub/mul nsw`, unary - is
                  `sub nsw 0, x`, / and % are `udiv/urem` (verifier proved dividend >= 0, divisor > 0),
                  array accesses are `getelementptr inbounds` without checks.  No checks at all.
  verified=False  (--no-verify, "safe mode") nothing is assumed: + - * and unary - use
                  llvm.s*.with.overflow.i64 (fail -> vow_panic_arith "overflow in +" ...), / and %
                  check `divisor > 0 && dividend >= 0` (fail -> "division outside domain: ..."),
                  index read/write checks 0 <= i < len (fail -> vow_panic_oob), alloc(n, v) checks
                  0 <= n <= 2^40.  No `nsw` is ever emitted in safe mode.
  trust_callers=False (default)  the entry function checks every `requires` (i128) before the body;
                  trust_callers=True: entry calls the body without checks.

Generated names (user identifiers never start with `vow_` nor contain `__`, so no collisions):
  @f__vow_body    internal; the function body.  Inner calls: verified -> f__vow_body (the caller proved
                  requires), safe -> f__vow_entry.
  @f__vow_entry   internal; evaluates requires (declaration order, first failure panics with
                  vow_panic_requires(fn, show(expr))) and calls the body.
  @vow_abi_f      external C-ABI wrapper used by the Rust bindings (bool -> i64, Option/Result args as
                  two i64, array results through a trailing `ptr out`, Option/Result results by value as { i64, i64 }).
  @vow_cdiv/@vow_crem  internal i128 Euclidean division for requires (only if some entry checks).
  @.str.N         private string constants.
Local IR names: %tN temporaries, %lN.name.{a,b} local slots (entry-block alloca), %p.name parameters,
%qN.* quantifier slots, labels `hint.N` (per-function counters).

Ownership of arrays is tracked at compile time (borrowed params; alloc/copy/array-returning call
results are owned).  Block-scoped locals are freed (vow_free) in reverse declaration order when the
block ends or at `return`; `a = f(..)` frees the old value after evaluating the right side; call-result
temporaries are freed at the end of the statement/condition (only on the executed path).
"""
import re
from vast import *
from codegen import show

SIGNED_MIN128 = -170141183460469231731687303715884105728
OPT = "{ i1, i64 }"
ARR = "{ ptr, i64 }"

DECLS = """\
declare noalias ptr @vow_alloc(i64, i64) nounwind
declare noalias ptr @vow_copy(ptr nocapture readonly, i64) nounwind
declare void @vow_free(ptr nocapture, i64) nounwind
declare void @vow_print_i64(i64) nounwind
declare void @vow_print_bool(i64) nounwind
declare void @vow_panic_oob(i64, i64) noreturn cold nounwind
declare void @vow_panic_arith(ptr) noreturn cold nounwind
declare void @vow_panic_requires(ptr, ptr) noreturn cold nounwind
declare void @vow_panic_undefined(ptr) noreturn cold nounwind
declare { i64, i1 } @llvm.sadd.with.overflow.i64(i64, i64)
declare { i64, i1 } @llvm.ssub.with.overflow.i64(i64, i64)
declare { i64, i1 } @llvm.smul.with.overflow.i64(i64, i64)
declare { i128, i1 } @llvm.sadd.with.overflow.i128(i128, i128)
declare { i128, i1 } @llvm.ssub.with.overflow.i128(i128, i128)
declare { i128, i1 } @llvm.smul.with.overflow.i128(i128, i128)
"""


def mangle(n):
    return re.sub(r"[^A-Za-z0-9_]", lambda m: "$%04x" % ord(m.group()), n)


def lty(t):
    """internal SSA type of a Vow type"""
    return {"i64": "i64", "bool": "i1", "unit": "void", "array": ARR,
            "option": OPT, "result": OPT}[t.name]


def vkind(t):
    return {"i64": "i64", "bool": "i1", "unit": "unit", "array": "arr",
            "option": "opt", "result": "opt"}[t.name]


class V:
    """an SSA value: k in i64 | i1 | i128 | arr (a=ptr, b=len) | opt (a=tag i1, b=payload) | unit"""
    __slots__ = ("k", "a", "b")

    def __init__(s, k, a=None, b=None):
        s.k, s.a, s.b = k, a, b


class Slot:
    __slots__ = ("k", "a", "b")

    def __init__(s, k, a, b=None):
        s.k, s.a, s.b = k, a, b


class Mod:
    def __init__(s):
        s.strs = {}
        s.order = []

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
        if p.type == ARRAY:
            out += [("ptr", "%%p.%s.a" % n), ("i64", "%%p.%s.n" % n)]
        elif p.type == BOOL:
            out.append(("i1", "%%p.%s" % n))
        elif p.type == I64:
            out.append(("i64", "%%p.%s" % n))
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
            return Slot("arr", a, b)
        s.allocas.append("%s = alloca i1" % a)
        s.allocas.append("%s = alloca i64" % b)
        return Slot("opt", a, b)

    def load(s, sl):
        if sl.k in ("i64", "i1"):
            return V(sl.k, s.op("load %s, ptr %s" % (sl.k, sl.a)))
        if sl.k == "arr":
            p = s.op("load ptr, ptr %s" % sl.a)
            n = s.op("load i64, ptr %s" % sl.b)
            return V("arr", p, n)
        t = s.op("load i1, ptr %s" % sl.a)
        v = s.op("load i64, ptr %s" % sl.b)
        return V("opt", t, v)

    def store(s, sl, v):
        if sl.k in ("i64", "i1"):
            s.ins("store %s %s, ptr %s" % (sl.k, v.a, sl.a))
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
        s.ins("call void @vow_free(ptr %s, i64 %s)" % (v.a, v.b))

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

    def agg(s, v):
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
            if p.type == ARRAY:
                names[p.name] = ("ssa", V("arr", "%%p.%s.a" % n, "%%p.%s.n" % n))
            elif p.type == BOOL:
                names[p.name] = ("ssa", V("i1", "%%p.%s" % n))
            elif p.type == I64:
                names[p.name] = ("ssa", V("i64", "%%p.%s" % n))
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
        elif isinstance(st, IndexAssign):
            s.begin_temps()
            sl = s.lookup(st.name)[1]
            if s.verified:      # canonical Rust: `*a.get_unchecked_mut(i) = v` evaluates the right side first
                v = s.ev(st.value)
                i = s.ev(st.index)
            else:
                i = s.ev(st.index)
                v = s.ev(st.value)
            a = s.load(sl)
            g = s.index_ptr(a, i)
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
            pos = [a for a in st.arms if a.ctor in ("Some", "Ok")][0]
            neg = [a for a in st.arms if a.ctor in ("None", "Err")][0]
            pl, nl_, end = s.label("armT"), s.label("armF"), s.label("endmatch")
            s.condbr(sv.a, pl, nl_)
            reach = False
            for arm, lbl in ((pos, pl), (neg, nl_)):
                s.place(lbl)
                bind = None
                if arm.binder is not None:
                    bind = {arm.binder: ("ssa", V("i64", sv.b))}
                if s.run_block(arm.body, bind):
                    s.br(end)
                    reach = True
            if reach:
                s.place(end)
            else:
                s.dead = True
        else:
            raise Exception("llvmgen: unsupported statement %r" % st)

    # ---------- code expressions ----------
    def index_ptr(s, a, i):
        if not s.verified:
            ok = s.op("icmp ult i64 %s, %s" % (i.a, a.b))
            s.guard(ok, lambda: s.ins("call void @vow_panic_oob(i64 %s, i64 %s)" % (i.a, a.b)), False)
        return s.op("getelementptr inbounds i64, ptr %s, i64 %s" % (a.a, i.a))

    def checked(s, ty, name, sym, a, b):
        r = s.op("call { %s, i1 } @llvm.%s.with.overflow.%s(%s %s, %s %s)" % (ty, name, ty, ty, a, ty, b))
        v = s.op("extractvalue { %s, i1 } %s, 0" % (ty, r))
        o = s.op("extractvalue { %s, i1 } %s, 1" % (ty, r))
        if ty == "i64":
            s.guard(o, s.panic1("vow_panic_arith", "overflow in " + sym), True)
        else:
            s.guard(o, s.panic1("vow_panic_undefined", "i128 overflow in " + sym), True)
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
            return V("i64", s.op("load i64, ptr %s" % g))
        if isinstance(e, Ctor):
            if e.name == "None":
                return V("opt", "false", "0")
            x = s.ev(e.arg)
            return V("opt", "true" if e.name in ("Some", "Ok") else "false", x.a)
        if isinstance(e, Call):
            return s.ev_call(e, owned)
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
                s.guard(ok, s.panic1("vow_panic_arith",
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
            if s.verified:
                v = s.ev(a[1])      # same order as codegen.py: vec![v; n]
                cnt = s.ev(a[0])
            else:
                cnt = s.ev(a[0])
                v = s.ev(a[1])
                ok = s.op("icmp ult i64 %s, 1099511627777" % cnt.a)
                s.guard(ok, s.panic1("vow_panic_arith", "alloc length outside 0..2^40"), False)
            p = s.op("call ptr @vow_alloc(i64 %s, i64 %s)" % (cnt.a, v.a))
            return s.temp_arr(V("arr", p, cnt.a), owned)
        if n == "copy":
            src = s.ev(a[0])
            if not s.verified:
                pass    # spec: same checks as proof mode (none)
            p = s.op("call ptr @vow_copy(ptr %s, i64 %s)" % (src.a, src.b))
            return s.temp_arr(V("arr", p, src.b), owned)
        if n == "print":
            x = s.ev(a[0])
            if x.k == "i1":
                z = s.op("zext i1 %s to i64" % x.a)
                s.ins("call void @vow_print_bool(i64 %s)" % z)
            else:
                s.ins("call void @vow_print_i64(i64 %s)" % x.a)
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
            else:
                args.append("%s %s" % (v.k, v.a))
        callee = "@%s__vow_%s" % (mangle(f.name), "body" if s.verified else "entry")
        if f.ret == UNIT:
            s.ins("call void %s(%s)" % (callee, ", ".join(args)))
            return V("unit")
        r = s.op("call %s %s(%s)" % (lty(f.ret), callee, ", ".join(args)))
        if f.ret in (I64, BOOL):
            return V(vkind(f.ret), r)
        x0 = s.op("extractvalue %s %s, 0" % (lty(f.ret), r))
        x1 = s.op("extractvalue %s %s, 1" % (lty(f.ret), r))
        if f.ret == ARRAY:
            return s.temp_arr(V("arr", x0, x1), owned)
        return V("opt", x0, x1)

    # ---------- contract evaluation (requires), i128 ----------
    def bind_contract_params(s):
        s.place("start")
        for p in s.f.params:
            n = mangle(p.name)
            if p.type == ARRAY:
                s.cenv[p.name] = V("arr", "%%p.%s.a" % n, "%%p.%s.n" % n)
            elif p.type == BOOL:
                s.cenv[p.name] = V("i1", "%%p.%s" % n)
            elif p.type == I64:
                s.cenv[p.name] = V("i128", s.op("sext i64 %%p.%s to i128" % n))
            else:
                t = s.op("extractvalue %s %%p.%s, 0" % (OPT, n))
                v = s.op("extractvalue %s %%p.%s, 1" % (OPT, n))
                s.cenv[p.name] = V("opt", t, s.op("sext i64 %s to i128" % v))

    def cev(s, e):
        und = lambda msg: s.panic1("vow_panic_undefined", msg)
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
                fn = "vow_cdiv" if op == "/" else "vow_crem"
                return V("i128", s.op("call i128 @%s(i128 %s, i128 %s)" % (fn, l.a, r.a)))
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
            g = s.op("getelementptr inbounds i64, ptr %s, i64 %s" % (a.a, ii))
            x = s.op("load i64, ptr %s" % g)
            return V("i128", s.op("sext i64 %s to i128" % x))
        if isinstance(e, Ctor):
            if e.name == "None":
                return V("opt", "false", "0")
            x = s.cev(e.arg)
            return V("opt", "true" if e.name in ("Some", "Ok") else "false", x.a)
        if isinstance(e, Quant):
            return s.cquant(e)
        if isinstance(e, Call):
            n, a = e.name, e.args
            if n == "len":
                return V("i128", s.op("zext i64 %s to i128" % s.cev(a[0]).b))
            if n in ("is_some", "is_ok"):
                return V("i1", s.cev(a[0]).a)
            if n in ("some_val", "ok_val", "err_val"):
                o = s.cev(a[0])
                if n == "err_val":
                    s.guard(o.a, und("err_val of Ok"), True)
                else:
                    s.guard(o.a, und("some_val of None" if n == "some_val" else "ok_val of Err"), False)
                return V("i128", o.b)
        raise Exception("llvmgen: unsupported expression in requires: %r" % e)

    def cquant(s, e):
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
            s.guard(hv, s.panic1("vow_panic_undefined", "%s over an empty range" % kind), False)
        res = s.op("load %s, ptr %s" % (rty, r))
        return V(rty, res)


def entry_of(m, funcs, f, trust):
    g = FnGen(m, funcs, f, True)
    params = ir_params(f)
    rt = lty(f.ret)
    if trust:
        g.place("start")
    else:
        g.bind_contract_params()
        for r in f.requires:
            c = g.cev(r)
            msg_fn = m.string(f.name)
            msg_ex = m.string(show(r))
            g.guard(c.a, lambda a=msg_fn, b=msg_ex: g.ins("call void @vow_panic_requires(ptr %s, ptr %s)" % (a, b)),
                    False)
    args = ", ".join("%s %s" % (t, n) for t, n in params)
    callee = "@%s__vow_body" % mangle(f.name)
    if f.ret == UNIT:
        g.ins("call void %s(%s)" % (callee, args))
        g.term("ret void")
    else:
        r = g.op("call %s %s(%s)" % (rt, callee, args))
        g.term("ret %s %s" % (rt, r))
    return g.render("define internal %s @%s__vow_entry(%s)" % (rt, mangle(f.name), sig_text(params)))


def abi_of(f):
    n = mangle(f.name)
    ext, pre, args = [], [], []
    for p in f.params:
        q = mangle(p.name)
        if p.type == I64:
            ext.append("i64 %%a.%s" % q)
            args.append("i64 %%a.%s" % q)
        elif p.type == BOOL:
            ext.append("i64 %%a.%s" % q)
            pre.append("%%c.%s = icmp ne i64 %%a.%s, 0" % (q, q))
            args.append("i1 %%c.%s" % q)
        elif p.type == ARRAY:
            ext += ["ptr %%a.%s.a" % q, "i64 %%a.%s.n" % q]
            args += ["ptr %%a.%s.a" % q, "i64 %%a.%s.n" % q]
        else:
            ext += ["i64 %%a.%s.t" % q, "i64 %%a.%s.v" % q]
            pre.append("%%c.%s.t = icmp ne i64 %%a.%s.t, 0" % (q, q))
            pre.append("%%c.%s.g1 = insertvalue %s undef, i1 %%c.%s.t, 0" % (q, OPT, q))
            pre.append("%%c.%s.g = insertvalue %s %%c.%s.g1, i64 %%a.%s.v, 1" % (q, OPT, q, q))
            args.append("%s %%c.%s.g" % (OPT, q))
    rt = f.ret
    entry = "@%s__vow_entry" % n
    body = ["  " + x for x in pre]
    if rt == ARRAY:
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
    return "define %s @vow_abi_%s(%s) {\nentry:\n%s\n}\n" % (ret, n, ", ".join(ext), "\n".join(body))


# ---------- helper functions for requires ----------
def cdivrem(m, is_div):
    nm, sym = ("vow_cdiv", "/") if is_div else ("vow_crem", "%")
    z = m.string("division by zero in " + sym)
    o = m.string("i128 overflow in " + sym)
    res = "%qq" if is_div else "%rr"
    return """\
define internal i128 @%s(i128 %%a, i128 %%b) {
entry:
  %%z = icmp eq i128 %%b, 0
  br i1 %%z, label %%dz, label %%c1
dz:
  call void @vow_panic_undefined(ptr %s)
  unreachable
c1:
  %%am = icmp eq i128 %%a, %d
  %%bm = icmp eq i128 %%b, -1
  %%ov = and i1 %%am, %%bm
  br i1 %%ov, label %%of, label %%c2
of:
  call void @vow_panic_undefined(ptr %s)
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
def rust_ty(t, param):
    return {"i64": "i64", "bool": "bool", "unit": "()", "option": "Option<i64>",
            "result": "Result<i64, i64>"}.get(t.name) or ("&[i64]" if param else "Vec<i64>")


ALLOW = "#[allow(dead_code, non_snake_case, unused)]"


def gen_bindings(prog):
    o = []
    o.append("// generated by vowc llvmgen -- Rust bindings for the LLVM back end (include with #[path] mod sol;)")
    o.append(ALLOW)
    o.append("#[repr(C)]\npub struct Vow__Array { pub data: *mut i64, pub len: i64 }")
    o.append(ALLOW)
    o.append("#[repr(C)]\npub struct Vow__Tagged { pub tag: i64, pub value: i64 }")
    o.append(ALLOW)
    o.append("""\
#[no_mangle]
pub extern "C" fn vow_host_alloc(len: i64) -> *mut i64 {
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
pub extern "C" fn vow_host_alloc_zeroed(len: i64) -> *mut i64 {
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
pub extern "C" fn vow_host_flush() {
    let _ = ::std::io::Write::flush(&mut ::std::io::stdout());
}""")
    o.append(ALLOW)
    o.append("""\
#[no_mangle]
pub extern "C" fn vow_host_free(data: *mut i64, len: i64) {
    if data.is_null() || len <= 0 { return; }
    if let Ok(layout) = ::std::alloc::Layout::array::<i64>(len as usize) {
        unsafe { ::std::alloc::dealloc(data as *mut u8, layout) };
    }
}""")
    returns_array = any(f.ret == ARRAY for f in prog.functions)
    decls = []
    for f in prog.functions:
        if mangle(f.name) != f.name:
            raise Exception("llvmgen: function name %s needs mangling; the bindings use the raw name" % f.name)
        ps = []
        for p in f.params:
            if p.type == ARRAY:
                ps += ["*const i64", "i64"]
            elif p.type in (OPTION, RESULT):
                ps += ["i64", "i64"]
            else:
                ps.append("i64")
        if f.ret == ARRAY:
            ps.append("*mut Vow__Array")
        ret = " -> i64" if f.ret in (I64, BOOL) else (" -> Vow__Tagged" if f.ret in (OPTION, RESULT) else "")
        decls.append("    fn vow_abi_%s(%s)%s;" % (f.name, ", ".join("p%d: %s" % (i, t) for i, t in enumerate(ps)), ret))
    if returns_array:
        decls.append("    fn vow_runtime_rust_allocator_v1();")
    o.append(ALLOW)
    o.append('extern "C" {\n%s\n}' % "\n".join(decls))
    for f in prog.functions:
        ps = ", ".join("%s: %s" % (p.name, rust_ty(p.type, True)) for p in f.params)
        ret = "" if f.ret == UNIT else " -> " + rust_ty(f.ret, False)
        pre, args = [], []
        for p in f.params:
            if p.type == I64:
                args.append(p.name)
            elif p.type == BOOL:
                args.append("%s as i64" % p.name)
            elif p.type == ARRAY:
                args += ["%s.as_ptr()" % p.name, "%s.len() as i64" % p.name]
            else:
                a, b = ("Some", "None") if p.type == OPTION else ("Ok", "Err")
                pre.append("let (vow__t_%s, vow__v_%s): (i64, i64) = match %s { %s(v) => (1, v), %s(v) => (0, v) };"
                           % (p.name, p.name, p.name, a, b))
                if p.type == OPTION:
                    pre[-1] = ("let (vow__t_%s, vow__v_%s): (i64, i64) = match %s { Some(v) => (1, v), None => (0, 0) };"
                               % (p.name, p.name, p.name))
                args += ["vow__t_" + p.name, "vow__v_" + p.name]
        body = []
        if "io" in f.effects:
            body.append("::std::io::Write::flush(&mut ::std::io::stdout());")
        if f.ret == ARRAY:
            body.append("let _ = ::std::hint::black_box(vow_runtime_rust_allocator_v1 as unsafe extern \"C\" fn());")
        body += pre
        call = "vow_abi_%s(%s)" % (f.name, ", ".join(args))
        callo = "vow_abi_%s(%s)" % (f.name, ", ".join(args + ["&mut vow__out"]))
        if f.ret == UNIT:
            body.append(call + ";")
        elif f.ret == I64:
            body.append(call)
        elif f.ret == BOOL:
            body.append(call + " != 0")
        elif f.ret == ARRAY:
            body.append("let mut vow__out = Vow__Array { data: ::std::ptr::null_mut(), len: 0 };")
            body.append(callo + ";")
            body.append("if vow__out.len > 0 { Vec::from_raw_parts(vow__out.data, vow__out.len as usize, "
                        "vow__out.len as usize) } else { Vec::new() }")
        else:
            a, b = ("Some", "None") if f.ret == OPTION else ("Ok", "Err")
            body.append("let vow__out = %s;" % call)
            if f.ret == OPTION:
                body.append("if vow__out.tag != 0 { Some(vow__out.value) } else { None }")
            else:
                body.append("if vow__out.tag != 0 { Ok(vow__out.value) } else { Err(vow__out.value) }")
        o.append(ALLOW)
        o.append("#[inline]\npub fn %s(%s)%s {\n    unsafe {\n%s\n    }\n}" %
                 (f.name, ps, ret, "\n".join("        " + b for b in body)))
    return "\n".join(o) + "\n"


def gen_llvm(prog, verified=True, trust_callers=False):
    m = Mod()
    funcs = {f.name: f for f in prog.functions}
    chunks = []
    if not trust_callers and any(f.requires for f in prog.functions):
        chunks.append(cdivrem(m, True))
        chunks.append(cdivrem(m, False))
    for f in prog.functions:
        g = FnGen(m, funcs, f, verified)
        g.body()
        params = ir_params(f)
        chunks.append(g.render("define internal %s @%s__vow_body(%s)" % (lty(f.ret), mangle(f.name), sig_text(params))))
        chunks.append(entry_of(m, funcs, f, trust_callers or not f.requires))
        chunks.append(abi_of(f))
    ir = m.render_strings() + "\n" + DECLS + "\n" + "\n".join(chunks)
    return ir, gen_bindings(prog)
