"""Deterministic post-mono array storage analysis; AST and logical types unchanged.

Create signature nodes in function/parameter source order, then each function's requires, ensures and body nodes in
statement/expression preorder (children left to right). Stable keys are tuples:
('param', function, position), ('result', function), ('binding', function, statement
ordinal), ('expr', function, expression ordinal). Ordinals start at zero per
function. Object identity is an auxiliary lookup only, never an ordering key.
Lexical scopes resolve variables. Union-find attaches larger root to smaller.
Connect init/reassignment, argument/formal, return/result, call/result and
copy/truncate/old source/result. Allocation inherits its consumer's component.
Declarations contribute inclusive ranges; missing bounds pin i64. Aggregate
fields/payloads, unknown flows, foreign calls, host signatures and inout pin i64.
Generic [T] becomes an unrefined declaration after mono and therefore pins.
Explicit hosts are host_entry; legacy hosts follow Gen.private's exclusions.
Unknown consumers pin their array operands. Contracts only read arrays.
Union all declared ranges per component; missing range or any pin yields i64.
Otherwise choose u8/u16/u32 for nonnegative ranges, i8/i16/i32 for negative lower
bounds, smallest fitting width; else i64. verified=False pins all components.
Only plain i64 arrays participate. Entries retain creation order.

API: plan_storage(program_after_mono, verified) -> StoragePlan.
layout_of(AST node or stable key) -> width string, default i64; Function nodes
mean result slots, Param/Let/IndexAssign and expressions are supported.
parameter(function_name, name) handles synthesized contract Vars.
entries: ordered tuple of (key, width). elem_size/alignment(width): byte count.
"""
from vast import *
from refine import _kids
from typeinfo import is_collection


def range_layout(lo, hi):
    for bits in (8, 16, 32):
        if lo >= 0 and hi < 1 << bits:
            return 'u%d' % bits
        if lo < 0 and -(1 << (bits - 1)) <= lo and hi < 1 << (bits - 1):
            return 'i%d' % bits
    return 'i64'


def elem_size(layout):
    return int(layout[1:]) // 8


alignment = elem_size


class StoragePlan:
    def layout_of(self, node):
        key = node if isinstance(node, tuple) else self.objects.get(id(node))
        return self.layouts.get(key, 'i64')

    def parameter(self, function, name):
        return self.layouts.get(self.params.get((function, name)), 'i64')


def plan_storage(program_after_mono, verified=True):
    prog = program_after_mono
    out = StoragePlan()
    out.objects, out.params = {}, {}
    keys, parent, bounds, pinned = [], [], [], []
    lookup = {}
    def array(t):
        return t is not None and t.name == 'array' and not t.args and t.owner is None
    def node(key, obj=None, refine=None, declaration=False, pin=False):
        i = len(keys)
        keys.append(key); parent.append(i); lookup[key] = i
        valid = refine is not None and refine.base == 'i64' and refine.lo is not None and refine.hi is not None
        bounds.append((refine.lo, refine.hi) if valid else None)
        pinned.append(pin or not verified or (declaration and not valid))
        if obj is not None: out.objects[id(obj)] = key
        return i
    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]; i = parent[i]
        return i
    def pin(i):
        if i is not None: pinned[i] = True
    def join(a, b):
        if a is None or b is None:
            pin(a); pin(b); return
        a, b = root(a), root(b)
        parent[max(a, b)] = min(a, b)
    fmap = {f.name: f for f in prog.functions}
    ext = (prog.g9 or {}).get('extended', ())
    for f in prog.functions:
        private = (getattr(f, 'private', False) or any(is_collection(p.type) or p.type.name in ext or p.mode == 'inout' for p in f.params)
                   or is_collection(f.ret) or f.ret.name in ext)
        host = f.host_entry if prog.explicit else not private
        for j, p in enumerate(f.params):
            if array(p.type):
                key = ('param', f.name, j)
                node(key, p, p.refine, True, host or p.mode == 'inout' or f.foreign is not None)
                out.params[f.name, p.name] = key
        if array(f.ret): node(('result', f.name), f, f.ret_refine, True, host or f.foreign is not None)
    for f in prog.functions:
        env = {p.name: lookup.get(('param', f.name, j)) for j, p in enumerate(f.params)}
        sn = en = 0
        def expr(e, scope):
            nonlocal en
            if e is None: return None
            number = en; en += 1
            n = node(('expr', f.name, number), e) if array(getattr(e, 'ty', None)) else None
            kids = _kids(e)
            known = (Var, Move, InoutArg, Call, Index, Quant, Unary, Binary,
                     IntLit, BoolLit, StrLit, Ctor, StructLit, EnumCtor,
                     FieldAccess, IsVariant, VariantField, Spent)
            if not isinstance(e, known):
                # Unknown syntax must not hide an array operand from the pin.
                from dataclasses import fields, is_dataclass
                def collect(x):
                    if isinstance(x, Expr): kids.append(x)
                    elif isinstance(x, (list, tuple)):
                        for v in x: collect(v)
                    elif is_dataclass(x):
                        for fd in fields(x): collect(getattr(x, fd.name))
                if is_dataclass(e):
                    for fd in fields(e): collect(getattr(e, fd.name))
            children = [expr(c, scope) for c in kids]
            if isinstance(e, (Var, Move)):
                if n is not None: join(n, scope.get(e.name))
            elif isinstance(e, InoutArg):
                if children: pin(children[0])
                if n is not None: join(n, children[0])
            elif isinstance(e, Call):
                if e.name in ('copy', 'truncate', 'old'):
                    if n is not None: join(n, children[0])
                elif e.name == 'alloc': pass
                elif e.name in fmap:
                    for j, c in enumerate(children):
                        if c is not None: join(c, lookup.get(('param', e.name, j)))
                    if n is not None: join(n, lookup.get(('result', e.name)))
                elif e.name != 'len':
                    pin(n)
                    for c in children: pin(c)
            elif isinstance(e, Binary):
                pin(n)
                for c in children: pin(c)
            elif isinstance(e, (Index, Quant, Unary, IntLit, BoolLit, StrLit)):
                pin(n)
            else:
                pin(n)
                for c in children: pin(c)
            return n
        def block(stmts, outer):
            nonlocal sn
            scope = dict(outer)
            for st in stmts:
                number = sn; sn += 1
                if isinstance(st, Let):
                    n = node(('binding', f.name, number), st, st.refine, True) if array(st.type) else None
                    v = expr(st.value, scope)
                    if n is not None or v is not None: join(n, v)
                    scope[st.name] = n
                elif isinstance(st, Assign):
                    v = expr(st.value, scope)
                    if v is not None or scope.get(st.name) is not None: join(scope.get(st.name), v)
                elif isinstance(st, Return):
                    v = expr(st.value, scope)
                    if v is not None: join(v, lookup.get(('result', f.name)))
                elif isinstance(st, IndexAssign):
                    out.objects[id(st)] = keys[scope[st.name]] if scope.get(st.name) is not None else None
                    expr(st.index, scope); expr(st.value, scope)
                elif isinstance(st, If):
                    expr(st.cond, scope); block(st.then, scope); block(st.els, scope)
                elif isinstance(st, While):
                    expr(st.cond, scope)
                    for inv in st.invariants: expr(inv, scope)
                    expr(st.decreases, scope); block(st.body, scope)
                elif isinstance(st, Assert): expr(st.cond, scope)
                elif isinstance(st, ExprStmt): expr(st.expr, scope)
                elif isinstance(st, FieldAssign): pin(expr(st.value, scope))
                elif isinstance(st, Par):
                    for c in st.calls: expr(c, scope)
                elif isinstance(st, Match):
                    expr(st.scrutinee, scope)
                    for arm in st.arms:
                        inner = dict(scope)
                        for name in arm.binders: inner[name] = None
                        block(arm.body, inner)
                else:
                    for v in scope.values(): pin(v)
                    from dataclasses import fields, is_dataclass
                    def unknown(x):
                        if isinstance(x, Expr): pin(expr(x, scope))
                        elif isinstance(x, list):
                            for v in x: unknown(v)
                        elif is_dataclass(x):
                            for fd in fields(x): unknown(getattr(x, fd.name))
                    unknown(st)
        for e in f.requires: expr(e, env)
        renv = dict(env); renv['result'] = lookup.get(('result', f.name))
        for e in f.ensures: expr(e, renv)
        block(f.body, env)
    ranges, pins = {}, {}
    for i in range(len(keys)):
        r = root(i)
        pins[r] = pins.get(r, False) or pinned[i]
        if bounds[i] is not None:
            lo, hi = bounds[i]
            if r in ranges: lo, hi = min(lo, ranges[r][0]), max(hi, ranges[r][1])
            ranges[r] = lo, hi
    out.entries = tuple((key, 'i64' if pins[root(i)] or root(i) not in ranges else range_layout(*ranges[root(i)]))
                        for i, key in enumerate(keys))
    out.layouts = dict(out.entries)
    return out
