"""Vow -> Rust. Contracts are erased; proven accesses use get_unchecked."""
from vast import *

ALLOW = "#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, dead_code, unreachable_code)]"


def rty(t, param=False):
    return {"i64": "i64", "bool": "bool", "unit": "()", "option": "Option<i64>",
            "result": "Result<i64, i64>"}.get(t.name) or ("&[i64]" if param else "Vec<i64>")


class Gen:
    def __init__(s, prog):
        s.prog = prog
        s.out = []

    def emit(s, ind, line):
        s.out.append("    " * ind + line)

    def fn(s, f):
        s.params = {p.name for p in f.params}
        ps = ", ".join("%s: %s" % (p.name, rty(p.type, True)) for p in f.params)
        ret = "" if f.ret == UNIT else " -> " + rty(f.ret)
        s.emit(0, ALLOW)
        s.emit(0, "pub fn %s(%s)%s {" % (f.name, ps, ret))
        s.block(f.body, 1)
        s.emit(0, "}")
        s.emit(0, "")

    def block(s, stmts, ind):
        for st in stmts:
            s.stmt(st, ind)

    def stmt(s, st, ind):
        if isinstance(st, Let):
            s.emit(ind, "let %s%s: %s = %s;" % ("mut " if st.mutable else "", st.name, rty(st.type), s.e(st.value)))
        elif isinstance(st, Assign):
            s.emit(ind, "%s = %s;" % (st.name, s.e(st.value)))
        elif isinstance(st, IndexAssign):
            s.emit(ind, "unsafe { *%s.get_unchecked_mut((%s) as usize) = %s; }" % (st.name, s.e(st.index), s.e(st.value)))
        elif isinstance(st, If):
            s.emit(ind, "if %s {" % s.e(st.cond))
            s.block(st.then, ind + 1)
            if st.els:
                s.emit(ind, "} else {")
                s.block(st.els, ind + 1)
            s.emit(ind, "}")
        elif isinstance(st, While):
            s.emit(ind, "while %s {" % s.e(st.cond))
            s.block(st.body, ind + 1)
            s.emit(ind, "}")
        elif isinstance(st, Return):
            s.emit(ind, "return;" if st.value is None else "return %s;" % s.e(st.value))
        elif isinstance(st, Assert):
            pass
        elif isinstance(st, ExprStmt):
            s.emit(ind, s.e(st.expr) + ";")
        elif isinstance(st, Match):
            s.emit(ind, "match %s {" % s.e(st.scrutinee))
            for a in st.arms:
                pat = a.ctor if a.binder is None else "%s(%s)" % (a.ctor, a.binder)
                s.emit(ind + 1, "%s => {" % pat)
                s.block(a.body, ind + 2)
                s.emit(ind + 1, "}")
            s.emit(ind, "}")

    def arr_ref(s, e):
        """an array expression used as a borrowed slice"""
        if isinstance(e, Var) and e.name not in s.params:
            return "&" + e.name
        if isinstance(e, Var):
            return e.name
        return "&" + s.e(e)

    def e(s, e):
        if isinstance(e, IntLit):
            if e.value == -2 ** 63:
                return "i64::MIN"
            return "(%di64)" % e.value if e.value < 0 else "%di64" % e.value
        if isinstance(e, BoolLit):
            return "true" if e.value else "false"
        if isinstance(e, Var):
            return e.name
        if isinstance(e, Unary):
            return "(%s%s)" % (e.op, s.e(e.operand))
        if isinstance(e, Binary):
            return "(%s %s %s)" % (s.e(e.left), e.op, s.e(e.right))
        if isinstance(e, Index):
            return "(unsafe { *%s.get_unchecked((%s) as usize) })" % (s.e(e.array), s.e(e.index))
        if isinstance(e, Ctor):
            return "None" if e.name == "None" else "%s(%s)" % (e.name, s.e(e.arg))
        if isinstance(e, Call):
            n, a = e.name, e.args
            if n == "len":
                return "(%s.len() as i64)" % s.e(a[0])
            if n == "alloc":
                return "vec![%s; (%s) as usize]" % (s.e(a[1]), s.e(a[0]))
            if n == "copy":
                return "%s.to_vec()" % s.e(a[0])
            if n == "print":
                return 'println!("{}", %s)' % s.e(a[0])
            args = [s.arr_ref(x) if x.ty == ARRAY else s.e(x) for x in a]
            return "%s(%s)" % (n, ", ".join(args))
        raise Exception("codegen: contract-only expression in code: %r" % e)


def gen_rust(prog):
    g = Gen(prog)
    for f in prog.functions:
        g.fn(f)
    return "\n".join(g.out) + "\n"
