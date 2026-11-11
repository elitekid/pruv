"""Pruv type / effect / structure checker. Fills Expr.ty."""
import re
from vast import *
from typeinfo import (TypeTable, BUILTIN_TYPE_NAMES, type_name, is_user_type, is_array, array_elem,  # G2 A5: array_elem
                      TypeArityError, check_arity, bind_args, substitute, is_value, is_element,
                      dependencies, decl_owner, fn_owner)  # G3 A1
from refine import expand as refine_expand

# name -> (argument kind, result: BOOL | I64 | "payload" = the Option/Result payload type)
CONTRACT_ONLY = {"is_some": ("option", BOOL), "some_val": ("option", "payload"), "is_ok": ("result", BOOL),
                 "ok_val": ("result", "payload"), "err_val": ("result", I64)}
BUILTIN_FNS = ("len", "alloc", "copy", "print", "is_char_boundary", "substr")
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
            if f.name in BUILTIN_FNS or f.name in CONTRACT_ONLY:
                terr(f, "reserved", "%s is a builtin name" % f.name, "rename the function")
            s.funcs[f.name] = f
        s.calls = {}
        s.decls = {}      # type name -> TypeDecl (first declaration)
        s.tt = None
        s.alloc_hint = None   # G2: (alloc Call node, expected array type) for the three allowed sites
        # G3: type-parameter context of the declaration being checked
        s.ctx_names = set()       # names of its type parameters
        s.ctx_generic = False     # does the declaration declare type parameters?
        s.elem_params = set()     # identities (owner, index) of its Element-bounded parameters
        s.arg_decls = {}          # type name -> (number of type parameters, []) for typeinfo.check_arity/is_value

    def run(s):
        refine_expand(s.prog)  # STAGE1 A: validate refinement annotations, desugar them into contracts/asserts
        s.declare_types()      # names, duplicates
        s.arg_decls = {n: (len(d.tparams), []) for n, d in s.decls.items()}
        s.check_tparams()      # G3: type-parameter lists (type_parameter, generic_bound, generic_main)
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

    # ---- G3: type parameters and type applications ----
    def enter(s, owner, tparams):
        """make the type-parameter list of the declaration being checked the current context"""
        s.ctx_names = set(tp.name for tp in tparams)
        s.ctx_generic = bool(tparams)
        s.elem_params = set((owner, i) for i, tp in enumerate(tparams) if tp.bound == "Element")

    def check_tparams(s):
        for d in s.prog.types:
            s.tparam_list(d.tparams)
        for f in s.prog.functions:
            if f.name == "main" and f.tparams:
                terr(f, "generic_main", "main cannot declare type parameters",
                     "make main a plain function; call generic functions from it with explicit type arguments")
            s.tparam_list(f.tparams)

    def tparam_list(s, tparams):
        seen = set()
        for tp in tparams:
            if not TYPE_NAME_RE.match(tp.name):
                terr(tp, "type_parameter", "type parameter %s must start with an upper-case letter" % tp.name,
                     "rename it, e.g. %s" % (tp.name[:1].upper() + tp.name[1:]))
            if tp.name in RESERVED_TYPE_NAMES or tp.name in s.decls:
                terr(tp, "type_parameter", "type parameter %s shadows a declared or built-in type" % tp.name,
                     "choose a name that is not a type, e.g. T")
            if tp.name in seen:
                terr(tp, "type_parameter", "type parameter %s is declared twice" % tp.name,
                     "give every parameter of a declaration its own name")
            seen.add(tp.name)
            if tp.bound is not None and tp.bound != "Element":
                terr(tp, "generic_bound", "unknown bound %s on type parameter %s" % (tp.bound, tp.name),
                     "the only bound is Element: <%s: Element>" % tp.name)

    def check_type(s, node, ty):
        """every type reference: arity, known names, type-argument and bound rules (G3_SPEC 3.1, 3.2, 3.4)"""
        try:
            check_arity(ty, s.arg_decls)
        except TypeArityError as ex:
            terr(node, "type_arity", str(ex), "give the exact number of type arguments, e.g. Option<i64>, Pair<i64, bool>")
        s.check_type_rec(node, ty)

    def check_type_rec(s, node, ty):
        if ty.owner is not None:
            return
        if ty.name in ("option", "result"):
            for a in ty.args:
                s.check_arg(node, a, None)
            return
        if ty.name == "array":
            if ty.args:                      # [X] for X other than i64/u8/bool
                el = ty.args[0]
                s.check_type_rec(node, el)
                if el.owner is not None:
                    if (el.owner, el.index) not in s.elem_params:
                        terr(node, "generic_bound", "[%s] requires %s: Element" % (el.name, el.name),
                             "declare the parameter as <%s: Element>" % el.name)
                else:
                    terr(node, "type_argument", "%s cannot be an array element" % type_name(el),
                         "arrays hold i64, bool or an Element type parameter")
            return
        if ty.name in BUILTIN_TYPE_NAMES:
            return
        if ty.name in s.ctx_names:
            terr(node, "type_parameter", "type parameter %s is not a type constructor" % ty.name,
                 "write %s without type arguments" % ty.name)
        d = s.decls.get(ty.name)
        if d is None:
            if s.ctx_generic:
                terr(node, "type_parameter", "unknown type %s: it is neither declared nor a type parameter of this declaration" % ty.name,
                     "declare it in the type-parameter list, e.g. <%s>, or declare the type" % ty.name)
            terr(node, "unknown_type", "unknown type %s" % ty.name,
                 "declare it with `struct %s { ... }` or `enum %s { ... }`" % (ty.name, ty.name))
        for a, tp in zip(ty.args, d.tparams):
            s.check_arg(node, a, tp)

    def check_arg(s, node, a, tp):
        """a: a type argument; tp: the TypeParam it instantiates (None for Option/Result)"""
        s.check_type_rec(node, a)
        if not is_value(a, s.arg_decls):
            terr(node, "type_argument", "%s is not a valid type argument: only i64, bool, Option, Result, "
                 "structs, enums and type parameters are" % type_name(a),
                 "arrays, str and () cannot be type arguments")
        if tp is not None and tp.bound == "Element" and not is_element(a, s.elem_params):
            terr(node, "generic_bound", "%s does not satisfy the bound Element of %s" % (type_name(a), tp.name),
                 "only i64, bool and type parameters declared `: Element` satisfy Element")

    def instantiate(s, e, what, owner, tparams, targs):
        """steps 1-4 of G3_SPEC 3.4 for a call / literal / constructor `e` written with `targs` (None = no type
        application) -> substitution {(owner, index): Type}, or None for a non-generic declaration"""
        if targs is None:
            if tparams:
                terr(e, "type_arity", "%s expects %d type argument(s)" % (what, len(tparams)),
                     "write the type arguments explicitly, e.g. %s::<T>; they are never inferred" % what.split()[-1])
            return None
        if not tparams:
            terr(e, "type_arity", "%s takes no type arguments" % what, "remove the `::<...>`")
        if len(targs) != len(tparams):
            terr(e, "type_arity", "%s expects %d type argument(s), got %d" % (what, len(tparams), len(targs)),
                 "give exactly one type argument per type parameter")
        for a, tp in zip(targs, tparams):
            s.check_type(e, a)
            s.check_arg(e, a, tp)
        return bind_args(owner, len(tparams), targs)

    def resolve_types(s):
        for d in s.prog.types:
            s.enter(decl_owner(d.name), d.tparams)
            groups = [d.fields] if isinstance(d, StructDecl) else [v.fields for v in d.variants]
            for fields in groups:
                for f in fields:
                    if f.type == UNIT or is_array(f.type) or f.type == STR:
                        terr(f, "field_type", "field %s cannot have type %s" % (f.name, type_name(f.type)),
                             "fields are i64, bool, Option<i64>, Result<i64> or a user struct/enum")
                    s.check_type(f, f.type)
        for f in s.prog.functions:
            s.enter(fn_owner(f.name), f.tparams)
            for p in f.params:
                s.check_type(f, p.type)
            s.check_type(f, f.ret)

    def type_recursion(s):
        state = {}

        def deps(d):
            fields = d.fields if isinstance(d, StructDecl) else [x for v in d.variants for x in v.fields]
            out = []
            for f in fields:
                for n in dependencies(f.type):    # G3: nested type arguments count
                    if n in s.decls and n not in out:
                        out.append(n)
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
        s.enter(fn_owner(f.name), f.tparams)
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
            s.check_type(st, st.type)
            s.alloc_hint_for(st.value, st.type)
            s.expect(st.value, st.type, scope)
            if is_array(st.type) or st.type == STR:
                s.array_source(st, st.value, scope)
            scope[st.name] = (st.type, st.mutable, "local")
        elif isinstance(st, Assign):
            v = s.lookup(st, st.name, scope)
            if not v[1]:
                terr(st, "immutable", "%s is not mutable" % st.name,
                     "declare it with `let mut`" if v[2] == "local" else "parameters are immutable; copy into a `let mut` local")
            s.alloc_hint_for(st.value, v[0])
            s.expect(st.value, v[0], scope)
            if is_array(v[0]) or v[0] == STR:
                s.array_source(st, st.value, scope)
        elif isinstance(st, IndexAssign):
            v = s.lookup(st, st.name, scope)
            if v[0] == STR:
                terr(st, "immutable_string", "%s is a str; its bytes cannot be changed" % st.name,
                     "build a new str with substr() or copy() instead")
            if not is_array(v[0]):
                terr(st, "not_array", "%s is not an array" % st.name)
            if not v[1]:
                terr(st, "immutable", "array %s is read-only" % st.name,
                     "use `let mut b: %s = copy(%s);` (needs alloc)" % (type_name(v[0]), st.name))
            s.expect(st.index, I64, scope)
            # G2 A5: stored value is bool for a bool array; G3: exactly T for a [T]
            s.expect(st.value, s.elem_type(v[0]), scope)
        elif isinstance(st, FieldAssign):
            v = s.lookup(st, st.name, scope)
            cur = v[0]
            for fname in st.fields:
                if cur.owner is not None:
                    terr(st, "generic_operation", "cannot assign field %s: %s is an abstract type parameter" % (
                        fname, type_name(cur)), "a type parameter has no fields")
                if not s.tt.is_struct(cur):
                    terr(st, "not_struct", "cannot assign field %s: %s is not a struct" % (fname, type_name(cur)),
                         "field assignment paths run through structs only; assign the whole enum value instead")
                cur = s.field_type(st, cur, fname)
            if not v[1]:
                terr(st, "immutable", "%s is not mutable" % st.name,
                     "declare it with `let mut`" if v[2] == "local" else "parameters are immutable; copy into a `let mut` local")
            s.expect(st.value, cur, scope)
        elif isinstance(st, If):
            s.expect(st.cond, BOOL, scope, op="a condition")
            s.block(st.then, dict(scope))
            s.block(st.els, dict(scope))
        elif isinstance(st, While):
            s.expect(st.cond, BOOL, scope, op="a condition")
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
                s.alloc_hint_for(st.value, f.ret)
                s.expect(st.value, f.ret, scope)
                if is_array(f.ret) or f.ret == STR:
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
            if t.owner is not None:
                terr(st, "generic_operation", "cannot match a value of the abstract type %s" % t.name,
                     "a type parameter has no variants; match on an Option, Result or enum that contains it")
            if t.name == "option":
                need = {"Some", "None"}
            elif t.name == "result":
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
                    ftypes = [ft for _, ft in s.fields_of(t, a.ctor)]
                    if len(a.binders) != len(ftypes):
                        terr(a, "match_arity", "%s::%s has %d field(s), the pattern binds %d" % (
                            t.name, a.ctor, len(ftypes), len(a.binders)),
                             "bind every field, in declaration order")
                else:
                    # G3: the Some/Ok binder has the payload type of Option<X> / Result<X>; Err binds the i64 code
                    payload = t.args[0] if t.args and a.ctor != "Err" else I64
                    ftypes = [payload] * len(a.binders)
                for b, bt in zip(a.binders, ftypes):
                    if b in sc:
                        terr(node, "shadow", "%s is already defined" % b, "use a new name")
                    sc[b] = (bt, False, "local")
                s.block(a.body, sc)
        else:
            terr(st, "internal", "unknown statement")

    def array_source(s, st, value, scope, allow_local_var=False):
        """arrays are moved/borrowed explicitly: new arrays come only from alloc/copy/calls"""
        if isinstance(value, (Call, StrLit)):
            return
        if allow_local_var and isinstance(value, Var) and scope.get(value.name, (None, None, ""))[2] == "local":
            return
        if value.ty == STR:   # G2 B0
            terr(st, "array_alias", "a str value here must come from a string literal, copy(), substr() or a function call",
                 "write copy(x) to make an explicit copy (needs `! alloc`)")
        terr(st, "array_alias", "an array value here must come from alloc(), copy() or a function call",
             "write copy(x) to make an explicit copy (needs `! alloc`)")

    def alloc_hint_for(s, value, expected):
        """G2: only a builtin alloc call that IS the right-hand side of a typed let / array reassignment /
        return takes its array type from the expected type"""
        if isinstance(value, Call) and value.name == "alloc" and is_array(expected):
            s.alloc_hint = (value, expected)

    def expect_array(s, e, scope, c):
        """the argument must be an array of any element type (G2 B0: or a str); same diagnostic as expect(e, ARRAY, ...)"""
        t = s.expr(e, scope, c)
        if t.owner is not None:
            terr(e, "generic_operation", "%s is an abstract type parameter, not an array" % type_name(t),
                 "only [T] with T: Element can be indexed, measured or copied")
        if not is_array(t) and t != STR:
            terr(e, "type_mismatch", "expected %s, found %s" % (type_name(ARRAY), type_name(t)))
        return t

    @staticmethod
    def elem_type(at):
        """type of an element read from / stored into the array type `at`: T for [T]; bool for [bool]; else i64"""
        if at.name == "array" and at.args:
            return at.args[0]
        return BOOL if at == ARRAY_BOOL else I64

    def lookup(s, node, name, scope):
        if name not in scope:
            terr(node, "unknown_name", "unknown variable %s" % name)
        return scope[name]

    # ---- expressions ----
    def expect(s, e, ty, scope, contract=False, op=None):
        """op: what the operand is used for (arithmetic, comparison, ...) when the operation needs a concrete
        type: an abstract type parameter there is a generic_operation error rather than a plain mismatch"""
        t = s.expr(e, scope, contract)
        if t != ty:
            if op is not None and t.owner is not None:
                terr(e, "generic_operation", "%s is not allowed on the abstract type %s" % (op, t.name),
                     "a type parameter can be copied, passed, returned and stored; == works on it in contracts only")
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
        if isinstance(e, StrLit):   # G2 B0
            if not c:
                s.used_effects.add("alloc")
            return STR
        if isinstance(e, Var):
            if e.name == "result" and "result" not in scope:
                terr(e, "result_scope", "`result` is only allowed in ensures")
            return s.lookup(e, e.name, scope)[0]
        if isinstance(e, Unary):
            if e.op == "-":
                s.expect(e.operand, I64, scope, c, op="unary minus"); return I64
            s.expect(e.operand, BOOL, scope, c, op="a boolean operation"); return BOOL
        if isinstance(e, Binary):
            op = e.op
            if op in ("+", "-", "*", "/", "%"):
                s.expect(e.left, I64, scope, c, op="arithmetic")
                s.expect(e.right, I64, scope, c, op="arithmetic"); return I64
            if op in ("<", "<=", ">", ">="):
                s.expect(e.left, I64, scope, c, op="ordering")
                s.expect(e.right, I64, scope, c, op="ordering"); return BOOL
            if op in ("==", "!="):
                lt = s.expr(e.left, scope, c)
                if is_array(lt):
                    terr(e, "eq_type", "arrays cannot be compared with ==",
                         "compare lengths and elements: len(a) == len(b) && forall k in 0..len(a): a[k] == b[k]")
                if lt == STR:   # G2 B0
                    terr(e, "eq_type", "str values cannot be compared with ==",
                         "compare lengths and bytes: len(a) == len(b) && forall k in 0..len(a): a[k] == b[k]")
                if lt.owner is not None and not c:
                    terr(e, "generic_operation", "== is not allowed on the abstract type %s in code" % lt.name,
                         "runtime equality only compares i64 or bool; == on a type parameter works in contracts")
                if lt not in (I64, BOOL) and not c:
                    terr(e, "eq_type", "== only compares i64 or bool in code", "use match")
                s.expect(e.right, lt, scope, c)
                return BOOL
            if op in ("&&", "||"):
                s.expect(e.left, BOOL, scope, c, op="a boolean operation")
                s.expect(e.right, BOOL, scope, c, op="a boolean operation"); return BOOL
            if op == "==>":
                if not c:
                    terr(e, "contract_only", "==> is only allowed in contracts")
                s.expect(e.left, BOOL, scope, c, op="a boolean operation")
                s.expect(e.right, BOOL, scope, c, op="a boolean operation"); return BOOL
        if isinstance(e, Index):
            at = s.expect_array(e.array, scope, c)
            s.expect(e.index, I64, scope, c)
            return s.elem_type(at)  # G2 A5: bool array reads bool; G3: [T] reads T
        if isinstance(e, Ctor):
            return s.ctor(e, scope, c)
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
            s.expect(e.body, BOOL if e.kind in ("forall", "exists", "count") else I64, sc, c,
                     op="a quantifier body" if e.kind in ("forall", "exists", "count") else "an aggregate (%s)" % e.kind)
            return I64 if agg else BOOL
        if isinstance(e, StructLit):
            return s.struct_lit(e, scope, c)
        if isinstance(e, EnumCtor):
            ety = s.enum_type(e, e.enum_name)
            m = s.instantiate(e, "enum %s" % e.enum_name, decl_owner(e.enum_name), s.decls[e.enum_name].tparams,
                              e.targs)
            if m is not None:
                ety = mk_nominal(e.enum_name, e.targs)
                e.inst = {"decl": decl_owner(e.enum_name), "args": tuple(e.targs), "subst": m}
            s.variant_decl(e, ety, e.variant)
            fields = s.fields_of(ety, e.variant)
            if len(e.args) != len(fields):
                terr(e, "arity", "%s::%s takes %d argument(s), got %d" % (
                    e.enum_name, e.variant, len(fields), len(e.args)))
            for arg, (fd, ft) in zip(e.args, fields):
                s.expect(arg, ft, scope, c)
            return ety
        if isinstance(e, FieldAccess):
            bt = s.expr(e.base, scope, c)
            if bt.owner is not None:
                terr(e, "generic_operation", "cannot read field %s: %s is an abstract type parameter" % (
                    e.field, type_name(bt)), "a type parameter has no fields")
            if not s.tt.is_struct(bt):
                terr(e, "not_struct", "cannot read field %s: %s is not a struct" % (e.field, type_name(bt)),
                     "enum payloads are read with match" if s.tt.is_enum(bt) else "")
            return s.field_type(e, bt, e.field)
        if isinstance(e, IsVariant):
            if not c:
                terr(e, "contract_only", "is_variant is only allowed in contracts", "use match in code")
            e.enum_ty = s.variant_target(e, scope, c)
            return BOOL
        if isinstance(e, VariantField):
            if not c:
                terr(e, "contract_only", "variant_field is only allowed in contracts", "use match in code")
            ety = s.variant_target(e, scope, c)
            e.enum_ty = ety
            for fd, ft in s.fields_of(ety, e.variant):
                if fd.name == e.field:
                    return ft
            terr(e, "unknown_field", "variant %s::%s has no field %s" % (e.enum_name, e.variant, e.field))
        if isinstance(e, Call):
            return s.call(e, scope, c)
        terr(e, "internal", "unknown expression")

    # ---- user type helpers ----
    def fields_of(s, ty, variant=None):
        """[(FieldDecl, field type)] of the struct / enum variant `ty` names, with the type arguments of `ty`
        substituted into the declared field types (G3_SPEC 3.4)"""
        d = s.decls[ty.name]
        m = bind_args(decl_owner(ty.name), len(d.tparams), ty.args)
        return [(fd, substitute(fd.type, m)) for fd in s.tt.fields(ty, variant)]

    def field_type(s, node, sty, name):
        for fd, ft in s.fields_of(sty):
            if fd.name == name:
                return ft
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
        # G3: no explicit type arguments here; they come from the checked scrutinee, which keeps its full type
        if vt.owner is not None or vt.name != ety.name:
            terr(e.value, "type_mismatch", "expected %s, found %s" % (type_name(ety), type_name(vt)))
        return vt

    def struct_lit(s, e, scope, c):
        if e.name not in s.decls:
            terr(e, "unknown_type", "unknown type %s" % e.name)
        sty = Type(e.name)
        if not s.tt.is_struct(sty):
            terr(e, "not_struct", "%s is not a struct" % e.name,
                 "enum values are written %s::Variant" % e.name)
        m = s.instantiate(e, "struct %s" % e.name, decl_owner(e.name), s.decls[e.name].tparams, e.targs)
        if m is not None:
            sty = mk_nominal(e.name, e.targs)
            e.inst = {"decl": decl_owner(e.name), "args": tuple(e.targs), "subst": m}
        fields = [fd for fd, _ in s.fields_of(sty)]
        ftypes = [ft for _, ft in s.fields_of(sty)]
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
        for fi, ft in zip(e.fields, ftypes):
            s.expect(fi.value, ft, scope, c)
        return sty

    def ctor(s, e, scope, c):
        """Some / None / Ok / Err. Without type arguments they keep the legacy i64 meaning (G3_SPEC 0.0 item 8);
        `Some::<X>(x)`, `None::<X>`, `Ok::<X>(x)`, `Err::<X>(code)` build Option<X> / Result<X> (3.5)."""
        if e.targs is None:
            if e.name == "None":
                return OPTION
            s.expect(e.arg, I64, scope, c)
            return OPTION if e.name == "Some" else RESULT
        if len(e.targs) != 1:
            terr(e, "type_arity", "%s::<..> takes exactly 1 type argument, got %d" % (e.name, len(e.targs)),
                 "write %s::<T>" % e.name)
        x = e.targs[0]
        s.check_type(e, x)
        s.check_arg(e, x, None)
        e.inst = {"decl": "builtin:" + e.name, "args": (x,), "subst": {("builtin:" + e.name, 0): x}}
        if e.name == "None":
            return mk_option(x)
        s.expect(e.arg, I64 if e.name == "Err" else x, scope, c)
        return mk_option(x) if e.name == "Some" else mk_result(x)

    def call(s, e, scope, c):
        n, a = e.name, e.args

        def arity(k):
            if len(a) != k:
                terr(e, "arity", "%s takes %d argument(s), got %d" % (n, k, len(a)))
        if e.targs is not None and n not in s.funcs and (n in BUILTIN_FNS or n in CONTRACT_ONLY):
            terr(e, "type_arity", "builtin %s takes no type arguments" % n, "remove the `::<...>`")
        if n == "len":
            arity(1); s.expect_array(a[0], scope, c); return I64
        if n == "alloc":
            if c: terr(e, "effect_in_contract", "alloc not allowed in contracts")
            arity(2); s.expect(a[0], I64, scope, c)
            h = s.alloc_hint
            # G2 A5: the fill value is bool when the hinted type is [bool]; G3: T when it is [T]
            s.expect(a[1], s.elem_type(h[1]) if h is not None and h[0] is e else I64, scope, c)
            s.used_effects.add("alloc")
            return h[1] if h is not None and h[0] is e else ARRAY
        if n == "copy":
            if c: terr(e, "effect_in_contract", "copy not allowed in contracts")
            arity(1); at = s.expect_array(a[0], scope, c)
            s.used_effects.add("alloc"); return at
        if n == "is_char_boundary":   # G2 B0
            arity(2); s.expect(a[0], STR, scope, c); s.expect(a[1], I64, scope, c)
            return BOOL
        if n == "substr":   # G2 B0
            if c: terr(e, "effect_in_contract", "substr not allowed in contracts")
            arity(3); s.expect(a[0], STR, scope, c); s.expect(a[1], I64, scope, c); s.expect(a[2], I64, scope, c)
            s.used_effects.add("alloc"); return STR
        if n == "print":
            if c: terr(e, "effect_in_contract", "print not allowed in contracts")
            arity(1)
            t = s.expr(a[0], scope, c)
            if t.owner is not None:
                terr(e, "generic_operation", "print cannot take the abstract type %s" % t.name,
                     "print takes a concrete i64 or bool")
            if t not in (I64, BOOL):
                terr(e, "print_type", "print takes i64 or bool")
            s.used_effects.add("io"); return UNIT
        if n in CONTRACT_ONLY:
            if not c:
                terr(e, "contract_only", "%s is only allowed in contracts" % n, "use match in code")
            arity(1)
            kind, rt = CONTRACT_ONLY[n]
            t = s.expr(a[0], scope, c)
            if t.owner is not None or t.name != kind:
                terr(a[0], "type_mismatch", "expected %s, found %s" % (type_name(OPTION if kind == "option" else RESULT),
                                                                         type_name(t)))
            if rt == "payload":     # G3: the payload type of Option<X> / Result<X>
                return t.args[0] if t.args else I64
            return rt
        if n not in s.funcs:
            if n in ("sum", "count", "max", "min"):
                terr(e, "unknown_fn", "unknown function %s" % n,
                     "aggregates use the form sum(k in 0..len(a): a[k])")
            terr(e, "unknown_fn", "unknown function %s" % n)
        f = s.funcs[n]
        # G3_SPEC 3.4: resolve + arity + admissibility + bounds, substitute the signature, check the arguments
        m = s.instantiate(e, "function %s" % n, fn_owner(n), f.tparams, e.targs)
        if m is not None:
            e.inst = {"decl": fn_owner(n), "args": tuple(e.targs), "subst": m}
        else:
            m = {}
        arity(len(f.params))
        for arg, p in zip(a, f.params):
            s.expect(arg, substitute(p.type, m), scope, c)
        if c and f.effects:
            terr(e, "effect_in_contract", "function %s has effects; not allowed in contracts" % n)
        if c:
            terr(e, "call_in_contract", "calling functions in contracts is not supported in v0.1",
                 "inline the property")
        s.used_effects.update(f.effects)
        s.calls[s.f.name].add(n)
        return substitute(f.ret, m)


def check(prog):
    Checker(prog).run()
