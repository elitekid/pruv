"""Pruv type / effect / structure checker. Fills Expr.ty."""
import re
from vast import *
from typeinfo import TypeTable, type_name, is_user_type

CONTRACT_ONLY = {"is_some": (OPTION, BOOL), "some_val": (OPTION, I64), "is_ok": (RESULT, BOOL),
                 "ok_val": (RESULT, I64), "err_val": (RESULT, I64)}
RESERVED_TYPE_NAMES = ("Option", "Result", "Some", "None", "Ok", "Err")
TYPE_NAME_RE = re.compile(r"[A-Z][A-Za-z0-9_]*\Z")
FIELD_NAME_RE = re.compile(r"[a-z][A-Za-z0-9_]*\Z")


def terr(node, code, msg, fix="", stage="type"):
    raise PruvError(stage, node.line, node.col, code, msg, fix)


class Checker:
    def __init__(s, prog):
        s.prog = prog
        s.funcs = {}
        for f in prog.functions:
            if f.name in s.funcs:
                terr(f, "dup_fn", "function %s defined twice" % f.name)
            if f.name in ("len", "alloc", "copy", "print") or f.name in CONTRACT_ONLY:
                terr(f, "reserved", "%s is a builtin name" % f.name, "rename the function")
            s.funcs[f.name] = f
        s.calls = {}
        s.decls = {}      # type name -> TypeDecl (first declaration)
        s.tt = None

    def run(s):
        s.declare_types()      # names, duplicates
        s.resolve_types()      # every type reference
        s.type_recursion()
        s.tt = TypeTable(s.prog)
        for f in s.prog.functions:
            s.fn(f)
        s.no_recursion()

    # ---- user type declarations ----
    def declare_types(s):
        for d in s.prog.types:
            if not TYPE_NAME_RE.match(d.name):
                terr(d, "type_name", "type name %s must start with an upper-case letter" % d.name,
                     "rename it, e.g. %s" % (d.name[:1].upper() + d.name[1:]))
            if d.name in RESERVED_TYPE_NAMES:
                terr(d, "reserved", "%s is a builtin name" % d.name, "rename the type")
            if d.name in s.decls:
                terr(d, "dup_type", "type %s defined twice" % d.name)
            if d.name in s.funcs:
                terr(d, "name_collision", "%s is both a type and a function" % d.name,
                     "rename the type or the function")
            s.decls[d.name] = d
            if isinstance(d, StructDecl):
                s.check_field_names(d.fields, "struct %s" % d.name)
            else:
                if not d.variants:
                    terr(d, "empty_enum", "enum %s has no variants" % d.name, "add at least one variant")
                seen = set()
                for v in d.variants:
                    if not TYPE_NAME_RE.match(v.name):
                        terr(v, "variant_name", "variant name %s must start with an upper-case letter" % v.name,
                             "rename it, e.g. %s" % (v.name[:1].upper() + v.name[1:]))
                    if v.name in seen:
                        terr(v, "dup_variant", "variant %s defined twice in enum %s" % (v.name, d.name))
                    seen.add(v.name)
                    s.check_field_names(v.fields, "variant %s::%s" % (d.name, v.name))

    def check_field_names(s, fields, where):
        seen = set()
        for f in fields:
            if not FIELD_NAME_RE.match(f.name):
                terr(f, "field_name", "field name %s must start with a lower-case letter" % f.name,
                     "rename it, e.g. %s" % (f.name[:1].lower() + f.name[1:]))
            if f.name in seen:
                terr(f, "dup_field", "field %s defined twice in %s" % (f.name, where))
            seen.add(f.name)

    def check_type_ref(s, node, ty):
        if is_user_type(ty) and ty.name not in s.decls:
            terr(node, "unknown_type", "unknown type %s" % ty.name,
                 "declare it with `struct %s { ... }` or `enum %s { ... }`" % (ty.name, ty.name))

    def resolve_types(s):
        for d in s.prog.types:
            groups = [d.fields] if isinstance(d, StructDecl) else [v.fields for v in d.variants]
            for fields in groups:
                for f in fields:
                    if f.type == UNIT or f.type == ARRAY:
                        terr(f, "field_type", "field %s cannot have type %s" % (f.name, type_name(f.type)),
                             "fields are i64, bool, Option<i64>, Result<i64> or a user struct/enum")
                    s.check_type_ref(f, f.type)
        for f in s.prog.functions:
            for p in f.params:
                s.check_type_ref(f, p.type)
            s.check_type_ref(f, f.ret)

    def type_recursion(s):
        state = {}

        def deps(d):
            fields = d.fields if isinstance(d, StructDecl) else [x for v in d.variants for x in v.fields]
            out = []
            for f in fields:
                if is_user_type(f.type) and f.type.name not in out:
                    out.append(f.type.name)
            return out

        def visit(n, path):
            if state.get(n) == 1:
                cyc = path[path.index(n):] + [n]
                terr(s.decls[n], "recursive_type", "recursive type is not allowed: %s" % " -> ".join(cyc),
                     "types have fixed size; remove the cycle")
            if state.get(n) == 2:
                return
            state[n] = 1
            for c in deps(s.decls[n]):
                visit(c, path + [n])
            state[n] = 2
        for d in s.prog.types:
            visit(d.name, [])

    def no_recursion(s):
        state = {}

        def visit(n, path):
            if state.get(n) == 1:
                f = s.funcs[n]
                terr(f, "recursion", "recursion is not allowed: %s" % " -> ".join(path + [n]),
                     "rewrite with a while loop")
            if state.get(n) == 2:
                return
            state[n] = 1
            for c in sorted(s.calls.get(n, ())):
                visit(c, path + [n])
            state[n] = 2
        for n in s.funcs:
            visit(n, [])

    # ---- function ----
    def fn(s, f):
        s.f = f
        s.calls[f.name] = set()
        scope = {}
        for p in f.params:
            if p.name in scope:
                terr(f, "dup_param", "duplicate parameter %s" % p.name)
            if p.type == UNIT:
                terr(f, "unit_param", "parameter %s cannot have type ()" % p.name)
            scope[p.name] = (p.type, False, "param")
        s.used_effects = set()
        for r in f.requires:
            s.expect(r, BOOL, scope, contract=True)
        escope = dict(scope)
        if f.ret != UNIT:
            escope["result"] = (f.ret, False, "result")
        for e in f.ensures:
            s.expect(e, BOOL, escope, contract=True)
        s.block(f.body, dict(scope))
        if f.ret != UNIT and not s.ends_in_return(f.body):
            terr(f, "missing_return", "function %s may reach its end without returning" % f.name,
                 "end every path with `return ...;`")
        for e in sorted(s.used_effects):
            if e not in f.effects:
                terr(f, "missing_effect", "function %s uses effect `%s` but does not declare it" % (f.name, e),
                     "add `! %s` after the return type" % ", ".join(sorted(set(f.effects) | s.used_effects)),
                     stage="effect")

    def ends_in_return(s, stmts):
        if not stmts:
            return False
        last = stmts[-1]
        if isinstance(last, Return):
            return True
        if isinstance(last, If):
            return s.ends_in_return(last.then) and s.ends_in_return(last.els)
        if isinstance(last, Match):
            return all(s.ends_in_return(a.body) for a in last.arms)
        return False

    # ---- statements ----
    def block(s, stmts, scope):
        for st in stmts:
            s.stmt(st, scope)

    def stmt(s, st, scope):
        f = s.f
        if isinstance(st, Let):
            if st.name in scope:
                terr(st, "shadow", "%s is already defined; shadowing is not allowed" % st.name,
                     "use a new name")
            if st.type == UNIT:
                terr(st, "unit_let", "cannot bind a () value")
            s.check_type_ref(st, st.type)
            s.expect(st.value, st.type, scope)
            if st.type == ARRAY:
                s.array_source(st, st.value, scope)
            scope[st.name] = (st.type, st.mutable, "local")
        elif isinstance(st, Assign):
            v = s.lookup(st, st.name, scope)
            if not v[1]:
                terr(st, "immutable", "%s is not mutable" % st.name,
                     "declare it with `let mut`" if v[2] == "local" else "parameters are immutable; copy into a `let mut` local")
            s.expect(st.value, v[0], scope)
            if v[0] == ARRAY:
                s.array_source(st, st.value, scope)
        elif isinstance(st, IndexAssign):
            v = s.lookup(st, st.name, scope)
            if v[0] != ARRAY:
                terr(st, "not_array", "%s is not an array" % st.name)
            if not v[1]:
                terr(st, "immutable", "array %s is read-only" % st.name,
                     "use `let mut b: [i64] = copy(%s);` (needs alloc)" % st.name)
            s.expect(st.index, I64, scope)
            s.expect(st.value, I64, scope)
        elif isinstance(st, FieldAssign):
            v = s.lookup(st, st.name, scope)
            cur = v[0]
            for fname in st.fields:
                if not s.tt.is_struct(cur):
                    terr(st, "not_struct", "cannot assign field %s: %s is not a struct" % (fname, type_name(cur)),
                         "field assignment paths run through structs only; assign the whole enum value instead")
                cur = s.field_decl(st, cur, fname).type
            if not v[1]:
                terr(st, "immutable", "%s is not mutable" % st.name,
                     "declare it with `let mut`" if v[2] == "local" else "parameters are immutable; copy into a `let mut` local")
            s.expect(st.value, cur, scope)
        elif isinstance(st, If):
            s.expect(st.cond, BOOL, scope)
            s.block(st.then, dict(scope))
            s.block(st.els, dict(scope))
        elif isinstance(st, While):
            s.expect(st.cond, BOOL, scope)
            for i in st.invariants:
                s.expect(i, BOOL, scope, contract=True)
            s.expect(st.decreases, I64, scope, contract=True)
            s.block(st.body, dict(scope))
        elif isinstance(st, Return):
            if st.value is None:
                if f.ret != UNIT:
                    terr(st, "return_type", "function returns %s; `return;` is not enough" % type_name(f.ret))
            else:
                if f.ret == UNIT:
                    terr(st, "return_type", "function returns (); use `return;`")
                s.expect(st.value, f.ret, scope)
                if f.ret == ARRAY:
                    s.array_source(st, st.value, scope, allow_local_var=True)
        elif isinstance(st, Assert):
            s.expect(st.cond, BOOL, scope, contract=True)
        elif isinstance(st, ExprStmt):
            if not isinstance(st.expr, Call):
                terr(st, "useless_expr", "expression statement must be a call", "bind it with let or remove it")
            t = s.expr(st.expr, scope)
            if t != UNIT:
                terr(st, "unused_value", "value of type %s is dropped" % type_name(t),
                     "bind it with `let` or `match` it")
        elif isinstance(st, Match):
            t = s.expr(st.scrutinee, scope)
            user = s.tt.is_enum(t)
            if t == OPTION:
                need = {"Some", "None"}
            elif t == RESULT:
                need = {"Ok", "Err"}
            elif user:
                need = [v.name for v in s.tt.decl(t).variants]
            else:
                terr(st, "match_type", "can only match Option<i64>, Result<i64> or a user enum")
            if not user:
                got = [a.ctor for a in st.arms]
                if set(got) != need or len(got) != 2 or any(a.enum_name is not None for a in st.arms):
                    terr(st, "match_arms", "match needs exactly arms %s" % " and ".join(sorted(need)))
            else:
                seen = set()
                for a in st.arms:
                    if a.enum_name != t.name:
                        terr(a, "match_arms", "arm %s does not belong to enum %s" % (
                            ("%s::%s" % (a.enum_name, a.ctor)) if a.enum_name else a.ctor, t.name),
                             "match arms are written %s::Variant" % t.name)
                    if a.ctor not in need:
                        terr(a, "unknown_variant", "enum %s has no variant %s" % (t.name, a.ctor))
                    if a.ctor in seen:
                        terr(a, "match_arms", "arm %s::%s appears twice" % (t.name, a.ctor))
                    seen.add(a.ctor)
                missing = [n for n in need if n not in seen]
                if missing:
                    terr(st, "match_arms", "match is missing arm(s): %s" % ", ".join(
                        "%s::%s" % (t.name, n) for n in missing))
            for a in st.arms:
                sc = dict(scope)
                node = a if user else st
                if user:
                    ftypes = [f.type for f in s.tt.fields(t, a.ctor)]
                    if len(a.binders) != len(ftypes):
                        terr(a, "match_arity", "%s::%s has %d field(s), the pattern binds %d" % (
                            t.name, a.ctor, len(ftypes), len(a.binders)),
                             "bind every field, in declaration order")
                else:
                    ftypes = [I64] * len(a.binders)
                for b, bt in zip(a.binders, ftypes):
                    if b in sc:
                        terr(node, "shadow", "%s is already defined" % b, "use a new name")
                    sc[b] = (bt, False, "local")
                s.block(a.body, sc)
        else:
            terr(st, "internal", "unknown statement")

    def array_source(s, st, value, scope, allow_local_var=False):
        """arrays are moved/borrowed explicitly: new arrays come only from alloc/copy/calls"""
        if isinstance(value, Call):
            return
        if allow_local_var and isinstance(value, Var) and scope.get(value.name, (None, None, ""))[2] == "local":
            return
        terr(st, "array_alias", "an array value here must come from alloc(), copy() or a function call",
             "write copy(x) to make an explicit copy (needs `! alloc`)")

    def lookup(s, node, name, scope):
        if name not in scope:
            terr(node, "unknown_name", "unknown variable %s" % name)
        return scope[name]

    # ---- expressions ----
    def expect(s, e, ty, scope, contract=False):
        t = s.expr(e, scope, contract)
        if t != ty:
            terr(e, "type_mismatch", "expected %s, found %s" % (type_name(ty), type_name(t)))
        return t

    def expr(s, e, scope, contract=False):
        t = s._expr(e, scope, contract)
        e.ty = t
        return t

    def _expr(s, e, scope, c):
        if isinstance(e, IntLit):
            if not (-2 ** 63 <= e.value < 2 ** 63):
                terr(e, "int_range", "integer literal out of i64 range")
            return I64
        if isinstance(e, BoolLit):
            return BOOL
        if isinstance(e, Var):
            if e.name == "result" and "result" not in scope:
                terr(e, "result_scope", "`result` is only allowed in ensures")
            return s.lookup(e, e.name, scope)[0]
        if isinstance(e, Unary):
            if e.op == "-":
                s.expect(e.operand, I64, scope, c); return I64
            s.expect(e.operand, BOOL, scope, c); return BOOL
        if isinstance(e, Binary):
            op = e.op
            if op in ("+", "-", "*", "/", "%"):
                s.expect(e.left, I64, scope, c); s.expect(e.right, I64, scope, c); return I64
            if op in ("<", "<=", ">", ">="):
                s.expect(e.left, I64, scope, c); s.expect(e.right, I64, scope, c); return BOOL
            if op in ("==", "!="):
                lt = s.expr(e.left, scope, c)
                if lt == ARRAY:
                    terr(e, "eq_type", "arrays cannot be compared with ==",
                         "compare lengths and elements: len(a) == len(b) && forall k in 0..len(a): a[k] == b[k]")
                if lt not in (I64, BOOL) and not c:
                    terr(e, "eq_type", "== only compares i64 or bool in code", "use match")
                s.expect(e.right, lt, scope, c)
                return BOOL
            if op in ("&&", "||"):
                s.expect(e.left, BOOL, scope, c); s.expect(e.right, BOOL, scope, c); return BOOL
            if op == "==>":
                if not c:
                    terr(e, "contract_only", "==> is only allowed in contracts")
                s.expect(e.left, BOOL, scope, c); s.expect(e.right, BOOL, scope, c); return BOOL
        if isinstance(e, Index):
            s.expect(e.array, ARRAY, scope, c)
            s.expect(e.index, I64, scope, c)
            return I64
        if isinstance(e, Ctor):
            if e.name == "None":
                return OPTION
            s.expect(e.arg, I64, scope, c)
            return OPTION if e.name == "Some" else RESULT
        if isinstance(e, Quant):
            agg = e.kind in ("sum", "count", "max", "min")
            if not c:
                if agg:
                    terr(e, "contract_only", "%s is only allowed in contracts" % e.kind,
                         "compute it with a while loop and state it in ensures, "
                         "e.g. ensures result == sum(k in 0..len(a): a[k])")
                terr(e, "contract_only", "%s is only allowed in contracts" % e.kind)
            s.expect(e.lo, I64, scope, c); s.expect(e.hi, I64, scope, c)
            if e.var in scope:
                terr(e, "shadow", "%s is already defined" % e.var, "use a new name")
            sc = dict(scope); sc[e.var] = (I64, False, "bound")
            s.expect(e.body, BOOL if e.kind in ("forall", "exists", "count") else I64, sc, c)
            return I64 if agg else BOOL
        if isinstance(e, StructLit):
            return s.struct_lit(e, scope, c)
        if isinstance(e, EnumCtor):
            ety = s.enum_type(e, e.enum_name)
            fields = s.variant_decl(e, ety, e.variant).fields
            if len(e.args) != len(fields):
                terr(e, "arity", "%s::%s takes %d argument(s), got %d" % (
                    e.enum_name, e.variant, len(fields), len(e.args)))
            for arg, fd in zip(e.args, fields):
                s.expect(arg, fd.type, scope, c)
            return ety
        if isinstance(e, FieldAccess):
            bt = s.expr(e.base, scope, c)
            if not s.tt.is_struct(bt):
                terr(e, "not_struct", "cannot read field %s: %s is not a struct" % (e.field, type_name(bt)),
                     "enum payloads are read with match" if s.tt.is_enum(bt) else "")
            return s.field_decl(e, bt, e.field).type
        if isinstance(e, IsVariant):
            if not c:
                terr(e, "contract_only", "is_variant is only allowed in contracts", "use match in code")
            s.variant_target(e, scope, c)
            return BOOL
        if isinstance(e, VariantField):
            if not c:
                terr(e, "contract_only", "variant_field is only allowed in contracts", "use match in code")
            ety = s.variant_target(e, scope, c)
            vd = s.variant_decl(e, ety, e.variant)
            for fd in vd.fields:
                if fd.name == e.field:
                    return fd.type
            terr(e, "unknown_field", "variant %s::%s has no field %s" % (e.enum_name, e.variant, e.field))
        if isinstance(e, Call):
            return s.call(e, scope, c)
        terr(e, "internal", "unknown expression")

    # ---- user type helpers ----
    def field_decl(s, node, sty, name):
        for fd in s.tt.fields(sty):
            if fd.name == name:
                return fd
        terr(node, "unknown_field", "struct %s has no field %s" % (sty.name, name))

    def enum_type(s, node, name):
        """Type of a named enum; unknown_type / not_enum otherwise"""
        if name not in s.decls:
            terr(node, "unknown_type", "unknown type %s" % name)
        ty = Type(name)
        if not s.tt.is_enum(ty):
            terr(node, "not_enum", "%s is not an enum" % name)
        return ty

    def variant_decl(s, node, ety, variant):
        for v in s.tt.decl(ety).variants:
            if v.name == variant:
                return v
        terr(node, "unknown_variant", "enum %s has no variant %s" % (ety.name, variant))

    def variant_target(s, e, scope, c):
        """shared by is_variant / variant_field: value, enum and variant checks"""
        vt = s.expr(e.value, scope, c)
        ety = s.enum_type(e, e.enum_name)
        s.variant_decl(e, ety, e.variant)
        if vt != ety:
            terr(e.value, "type_mismatch", "expected %s, found %s" % (type_name(ety), type_name(vt)))
        return ety

    def struct_lit(s, e, scope, c):
        if e.name not in s.decls:
            terr(e, "unknown_type", "unknown type %s" % e.name)
        sty = Type(e.name)
        if not s.tt.is_struct(sty):
            terr(e, "not_struct", "%s is not a struct" % e.name,
                 "enum values are written %s::Variant" % e.name)
        fields = s.tt.fields(sty)
        declared = [f.name for f in fields]
        for fi in e.fields:
            if fi.name not in declared:
                terr(fi, "unknown_field", "struct %s has no field %s" % (e.name, fi.name))
        given = [fi.name for fi in e.fields]
        if given != declared:
            if len(set(given)) != len(given):
                dup = [n for n in given if given.count(n) > 1][0]
                why = "field %s is given twice" % dup
            elif set(given) != set(declared):
                why = "missing field(s): %s" % ", ".join(n for n in declared if n not in given)
            else:
                why = "fields must be written in declaration order: %s" % ", ".join(declared)
            terr(e, "struct_fields", "%s literal: %s" % (e.name, why),
                 "write every field exactly once, in declaration order")
        for fi, fd in zip(e.fields, fields):
            s.expect(fi.value, fd.type, scope, c)
        return sty

    def call(s, e, scope, c):
        n, a = e.name, e.args

        def arity(k):
            if len(a) != k:
                terr(e, "arity", "%s takes %d argument(s), got %d" % (n, k, len(a)))
        if n == "len":
            arity(1); s.expect(a[0], ARRAY, scope, c); return I64
        if n == "alloc":
            if c: terr(e, "effect_in_contract", "alloc not allowed in contracts")
            arity(2); s.expect(a[0], I64, scope, c); s.expect(a[1], I64, scope, c)
            s.used_effects.add("alloc"); return ARRAY
        if n == "copy":
            if c: terr(e, "effect_in_contract", "copy not allowed in contracts")
            arity(1); s.expect(a[0], ARRAY, scope, c)
            s.used_effects.add("alloc"); return ARRAY
        if n == "print":
            if c: terr(e, "effect_in_contract", "print not allowed in contracts")
            arity(1)
            t = s.expr(a[0], scope, c)
            if t not in (I64, BOOL):
                terr(e, "print_type", "print takes i64 or bool")
            s.used_effects.add("io"); return UNIT
        if n in CONTRACT_ONLY:
            if not c:
                terr(e, "contract_only", "%s is only allowed in contracts" % n, "use match in code")
            arity(1)
            at, rt = CONTRACT_ONLY[n]
            s.expect(a[0], at, scope, c); return rt
        if n not in s.funcs:
            if n in ("sum", "count", "max", "min"):
                terr(e, "unknown_fn", "unknown function %s" % n,
                     "aggregates use the form sum(k in 0..len(a): a[k])")
            terr(e, "unknown_fn", "unknown function %s" % n)
        f = s.funcs[n]
        arity(len(f.params))
        for arg, p in zip(a, f.params):
            s.expect(arg, p.type, scope, c)
        if c and f.effects:
            terr(e, "effect_in_contract", "function %s has effects; not allowed in contracts" % n)
        if c:
            terr(e, "call_in_contract", "calling functions in contracts is not supported in v0.1",
                 "inline the property")
        s.used_effects.update(f.effects)
        s.calls[s.f.name].add(n)
        return f.ret


def check(prog):
    Checker(prog).run()
