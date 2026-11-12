"""Pruv type / effect / structure checker. Fills Expr.ty."""
import re
from vast import *
from typeinfo import (TypeTable, BUILTIN_TYPE_NAMES, type_name, is_user_type, is_array, array_elem,  # G2 A5: array_elem
                      TypeArityError, check_arity, bind_args, substitute, is_value, is_element,
                      dependencies, decl_owner, fn_owner,  # G3 A1
                      COLLECTION_ARITY, COLLECTION_SPELLING, is_collection, contains_collection)  # G6 A0
from refine import expand as refine_expand
from refine import _kids as expr_kids
from foreign import (CATALOG, CATALOG_NAMES, CATALOG_CONTRACT_ONLY, check_foreign_decl, check_ownership)  # G6 A0

# name -> (argument kind, result: BOOL | I64 | "payload" = the Option/Result payload type)
CONTRACT_ONLY = {"is_some": ("option", BOOL), "some_val": ("option", "payload"), "is_ok": ("result", BOOL),
                 "ok_val": ("result", "payload"), "err_val": ("result", I64),
                 "size": ("size", I64)}   # G9 A0: structural size of a non-generic nominal value
BUILTIN_FNS = ("len", "alloc", "copy", "print", "is_char_boundary", "substr")
RESERVED_TYPE_NAMES = ("Option", "Result", "Some", "None", "Ok", "Err")
TYPE_NAME_RE = re.compile(r"[A-Z][A-Za-z0-9_]*\Z")
FIELD_NAME_RE = re.compile(r"[a-z][A-Za-z0-9_]*\Z")


def terr(node, code, msg, fix="", stage="type"):
    raise PruvError(stage, node.line, node.col, code, msg, fix, file=getattr(node, "file", None))   # G4: file only in explicit mode


def _sccs(n, adj):
    """G9 A0: strongly connected components of the graph on nodes 0..n-1 (adj[i]: successors of i), iterative Tarjan.
    -> list of member lists (each ascending), ordered by their smallest member."""
    index_of = [-1] * n
    low = [0] * n
    on_stack = [False] * n
    stack = []
    out = []
    counter = 0
    for root in range(n):
        if index_of[root] != -1:
            continue
        index_of[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack[root] = True
        work = [(root, 0)]
        while work:
            v, i = work[-1]
            if i < len(adj[v]):
                work[-1] = (v, i + 1)
                w = adj[v][i]
                if index_of[w] == -1:
                    index_of[w] = low[w] = counter
                    counter += 1
                    stack.append(w)
                    on_stack[w] = True
                    work.append((w, 0))
                elif on_stack[w]:
                    low[v] = min(low[v], index_of[w])
            else:
                work.pop()
                if work:
                    p = work[-1][0]
                    low[p] = min(low[p], low[v])
                if low[v] == index_of[v]:
                    comp = []
                    while True:
                        w = stack.pop()
                        on_stack[w] = False
                        comp.append(w)
                        if w == v:
                            break
                    out.append(sorted(comp))
    out.sort(key=lambda c: c[0])
    return out


def _cycle_through(start, adj, members):
    """shortest cycle start -> ... -> start inside `members` (breadth first, successors in adjacency order);
    -> list of nodes beginning and ending with start"""
    members = set(members)
    prev = {start: None}
    queue = [start]
    qi = 0
    while qi < len(queue):
        v = queue[qi]
        qi += 1
        for w in adj[v]:
            if w not in members:
                continue
            if w == start:
                path = [start]
                x = v
                chain = []
                while x is not None:
                    chain.append(x)
                    x = prev[x]
                chain.reverse()          # start ... v
                return chain + [start]
            if w not in prev:
                prev[w] = v
                queue.append(w)
    return [start, start]


class Checker:
    def __init__(s, prog, externs=()):
        s.prog = prog
        if prog.explicit:                # G4 A0: explicit visibility mode: resolve names to identities first
            from modules import resolve
            resolve(prog)
        s.externs = frozenset(externs)   # G6: crate names given with --rust-extern
        s.funcs = {}
        for f in prog.functions:
            if f.name in s.funcs:
                terr(f, "dup_fn", "function %s defined twice" % f.name)
            if f.name in BUILTIN_FNS or f.name in CONTRACT_ONLY or f.name in CATALOG_NAMES:
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
        # G9 A0 metadata
        s.type_sccs = []          # recursive type SCCs (lists of names in declaration order), SCC-number order
        s.boxed = []              # "Decl.field" / "Enum::Variant.field" of every intra-SCC (boxed) field
        s.boxed_decls = set()     # (declaration name, variant name or None) holding at least one boxed field
        s.extended = set()        # names of extended declarations
        s.buffered = set()        # declarations transitively containing a buffer (array/str) field
        s.fn_sccs = []            # recursive function SCCs (lists of names in function order)
        s.call_log = []           # (caller Function, Call node, callee Function) of every checked user call
        s.active_roots = []       # root variable names of the enclosing match arms on extended scrutinees

    def run(s):
        refine_expand(s.prog)  # STAGE1 A: validate refinement annotations, desugar them into contracts/asserts
        s.declare_types()      # names, duplicates
        s.normalize_types()    # G6: Vec/HashMap/String become catalog types unless the program declares them
        s.arg_decls = {n: (len(d.tparams), []) for n, d in s.decls.items()}
        s.check_tparams()      # G3: type-parameter lists (type_parameter, generic_bound, generic_main)
        s.resolve_types()      # every type reference
        s.type_graph()         # G9 A0: type SCCs, generic/recursive field rules
        s.inhabitance()        # G9 A0: every declaration needs a finite value
        s.compute_extended()
        s.check_extended_uses()
        if s.prog.explicit:
            s.check_entries()      # G4 A0: host-entry signatures
        s.tt = TypeTable(s.prog)
        for f in s.prog.functions:
            s.fn(f)
        s.check_fn_sccs()      # G9 A0: measures and stable type parameters of recursive call SCCs
        s.record_g9()

    # ---- user type declarations ----
    def declare_types(s):
        for d in s.prog.types:
            if d.src_name is None and not TYPE_NAME_RE.match(d.name):   # G4: explicit mode checked the written names
                terr(d, "type_name", "type name %s must start with an upper-case letter" % d.name,
                     "rename it, e.g. %s" % (d.name[:1].upper() + d.name[1:]))
            if d.src_name is None and d.name in RESERVED_TYPE_NAMES:
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

    # ---- G6 A0: collection spellings ----
    def norm_type(s, ty):
        """the parser yields nominal Vec/HashMap/String; map them to the catalog types unless a user type of
        that name is declared (an existing user type keeps its meaning)"""
        if ty.owner is not None:
            return ty
        args = tuple(s.norm_type(a) for a in ty.args)
        name = ty.name
        if name not in s.decls and name in ("Vec", "HashMap", "String"):
            name = {"Vec": "vec", "HashMap": "hashmap", "String": "string"}[name]
        if name == ty.name and args == ty.args:
            return ty
        if name == "array" and len(args) == 1:
            return mk_array(args[0])
        if name == "option" and len(args) == 1:
            return mk_option(args[0])
        if name == "result" and len(args) == 1:
            return mk_result(args[0])
        return Type(name, args)

    def normalize_types(s):
        for d in s.prog.types:
            for fd in (d.fields if isinstance(d, StructDecl) else [x for v in d.variants for x in v.fields]):
                fd.type = s.norm_type(fd.type)
        for f in s.prog.functions:
            for p in f.params:
                p.type = s.norm_type(p.type)
            f.ret = s.norm_type(f.ret)
            for e in f.requires + f.ensures:
                s.norm_expr(e)
            if f.decreases is not None:
                s.norm_expr(f.decreases)
            s.norm_stmts(f.body)

    def norm_stmts(s, stmts):
        for st in stmts:
            if isinstance(st, Let):
                st.type = s.norm_type(st.type)
                s.norm_expr(st.value)
            elif isinstance(st, (Assign, FieldAssign, Return)):
                if st.value is not None:
                    s.norm_expr(st.value)
            elif isinstance(st, IndexAssign):
                s.norm_expr(st.index)
                s.norm_expr(st.value)
            elif isinstance(st, If):
                s.norm_expr(st.cond)
                s.norm_stmts(st.then)
                s.norm_stmts(st.els)
            elif isinstance(st, While):
                s.norm_expr(st.cond)
                for i in st.invariants:
                    s.norm_expr(i)
                s.norm_expr(st.decreases)
                s.norm_stmts(st.body)
            elif isinstance(st, Assert):
                s.norm_expr(st.cond)
            elif isinstance(st, ExprStmt):
                s.norm_expr(st.expr)
            elif isinstance(st, Match):
                s.norm_expr(st.scrutinee)
                for a in st.arms:
                    s.norm_stmts(a.body)

    def norm_expr(s, e):
        targs = getattr(e, "targs", None)
        if targs is not None:
            e.targs = [s.norm_type(t) for t in targs]
        for k in expr_kids(e):
            s.norm_expr(k)

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
        if ty.name in COLLECTION_ARITY:      # G6: Vec<T>, HashMap<K, V>, String
            for a in ty.args:
                s.check_type_rec(node, a)
            if ty.name == "vec":
                s.collection_payload(node, ty.args[0], "a Vec element")
            elif ty.name == "hashmap":
                k = ty.args[0]
                if contains_collection(k) or not is_element(k, s.elem_params):
                    terr(node, "foreign_owned_type", "%s cannot be a HashMap key: only i64, bool and Element type "
                         "parameters can" % type_name(k),
                         "use i64 or bool keys, or declare the parameter `: Element`")
                s.collection_payload(node, ty.args[1], "a HashMap value")
            return
        if ty.name == "array":
            if ty.args:                      # [X] for X other than i64/u8/bool
                el = ty.args[0]
                s.check_type_rec(node, el)
                if contains_collection(el):
                    terr(node, "foreign_owned_type", "an array cannot hold the collection type %s" % type_name(el),
                         "arrays hold i64, bool or an Element type parameter")
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

    def collection_payload(s, node, a, what):
        """G6: a collection payload is a plain G3 value (never another collection)"""
        if contains_collection(a):
            terr(node, "foreign_owned_type", "%s cannot be the collection type %s" % (what, type_name(a)),
                 "collection payloads are plain values; keep every collection in its own binding")
        if not is_value(a, s.arg_decls):
            terr(node, "foreign_owned_type", "%s cannot have type %s: only i64, bool, Option, Result, structs, "
                 "enums and type parameters can" % (what, type_name(a)),
                 "arrays, str and () cannot be collection payloads")

    def check_arg(s, node, a, tp):
        """a: a type argument; tp: the TypeParam it instantiates (None for Option/Result)"""
        s.check_type_rec(node, a)
        if contains_collection(a):     # G6: collections are never type arguments of Option/Result/user declarations
            terr(node, "foreign_owned_type", "%s cannot be a type argument" % type_name(a),
                 "keep collections in their own bindings; Vec<T> and HashMap<K, V> are the only places they appear")
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
            s.ext_misuse(e, a, "arg")      # G9 A0: extended types are never type arguments
        return bind_args(owner, len(tparams), targs)

    def resolve_types(s):
        for d in s.prog.types:
            s.enter(decl_owner(d.name), d.tparams)
            groups = [d.fields] if isinstance(d, StructDecl) else [v.fields for v in d.variants]
            for fields in groups:
                for f in fields:
                    if d.tparams and (is_array(f.type) or f.type == STR):   # G9 A0
                        terr(f, "field_type", "generic type %s cannot have the array/str field %s" % (d.name, f.name),
                             "use a dedicated non-generic declaration")
                    if f.type == UNIT or (is_array(f.type) and f.type not in (ARRAY, ARRAY_U8, ARRAY_BOOL)):
                        terr(f, "field_type", "field %s cannot have type %s" % (f.name, type_name(f.type)),
                             "fields are i64, bool, Option<i64>, Result<i64> or a user struct/enum")
                    s.check_type(f, f.type)
                    if contains_collection(f.type):
                        terr(f, "foreign_owned_type", "field %s cannot have the collection type %s" % (
                            f.name, type_name(f.type)),
                             "collections cannot be struct fields or enum payloads; pass them as separate bindings")
        for f in s.prog.functions:
            s.enter(fn_owner(f.name), f.tparams)
            for p in f.params:
                s.check_type(f, p.type)
            s.check_type(f, f.ret)

    # ---- G9 A0: type graph, inhabitance, extended types ----
    @staticmethod
    def decl_fields(d):
        """[(variant name or None, FieldDecl)] of a declaration in variant/field source order"""
        if isinstance(d, StructDecl):
            return [(None, fd) for fd in d.fields]
        return [(v.name, fd) for v in d.variants for fd in v.fields]

    @staticmethod
    def field_label(d, vname, fd):
        return "%s.%s" % (d.name, fd.name) if vname is None else "%s::%s.%s" % (d.name, vname, fd.name)

    def is_plain_nominal(s, ty):
        """a declared user type written without type arguments"""
        return ty.owner is None and not ty.args and ty.name in s.decls and ty.name not in BUILTIN_TYPE_NAMES

    def type_graph(s):
        types = s.prog.types
        index = {}
        for i, d in enumerate(types):
            index.setdefault(d.name, i)
        adj = [[] for _ in types]
        for i, d in enumerate(types):
            for _, fd in s.decl_fields(d):
                for n in dependencies(fd.type):    # G3: nested type arguments count
                    j = index.get(n)
                    if j is not None and j not in adj[i]:
                        adj[i].append(j)
        for comp in _sccs(len(types), adj):
            if not (len(comp) > 1 or comp[0] in adj[comp[0]]):
                continue
            names = [types[i].name for i in comp]
            members = set(names)
            s.type_sccs.append(names)
            # (a) generic declarations cannot be recursive
            for i in comp:
                d = types[i]
                if d.tparams:
                    cyc = [types[k].name for k in _cycle_through(i, adj, comp)]
                    terr(d, "recursive_generic_type", "generic type %s cannot be recursive (cycle: %s)" % (
                        d.name, " -> ".join(cyc)),
                         "recursive types must be non-generic; write a dedicated enum for the element type")
            # (b) intra-SCC fields must be direct nominal fields (these are the boxed edges)
            for i in comp:
                d = types[i]
                for vname, fd in s.decl_fields(d):
                    if not any(n in members for n in dependencies(fd.type)):
                        continue
                    if not (s.is_plain_nominal(fd.type) and fd.type.name in members):
                        terr(fd, "recursive_type", "recursive field %s must have the type itself, not hide it inside %s" % (
                            fd.name, type_name(fd.type)),
                             "use a direct field of a dedicated non-generic type")
                    s.boxed.append(s.field_label(d, vname, fd))
                    s.boxed_decls.add((d.name, vname))

    def inhabitance(s):
        marked = set()
        # worklist: per struct / per variant count of fields whose type is not yet inhabited
        types = s.prog.types
        counts = []
        rev = {}        # type name -> [(decl index, unit index)], one entry per dependent field
        queue = []
        for i, d in enumerate(types):
            units = [d.fields] if isinstance(d, StructDecl) else [v.fields for v in d.variants]
            cs = []
            for u, fields in enumerate(units):
                c = 0
                for fd in fields:
                    if s.is_plain_nominal(fd.type):
                        c += 1
                        rev.setdefault(fd.type.name, []).append((i, u))
                cs.append(c)
            counts.append(cs)
            if 0 in cs:
                queue.append(i)
        while queue:
            i = queue.pop()
            name = types[i].name
            if name in marked:
                continue
            marked.add(name)
            for j, u in rev.get(name, ()):
                counts[j][u] -= 1
                if counts[j][u] == 0 and types[j].name not in marked:
                    queue.append(j)
        for d in s.prog.types:
            if d.name in marked:
                continue
            path = [d.name]
            cur = d
            while True:
                nxt = None
                for _, fd in s.decl_fields(cur):
                    if s.is_plain_nominal(fd.type) and fd.type.name not in marked:
                        nxt = fd.type.name
                        break
                if nxt is None:
                    break
                path.append(nxt)
                if path.index(nxt) != len(path) - 1:
                    break
                cur = s.decls[nxt]
            terr(d, "recursive_type", "recursive type has no finite value: %s" % " -> ".join(path),
                 "add a variant without recursive fields (a base case such as `Empty`)")

    def compute_extended(s):
        """extended = recursive, or with a buffer field, or with a field mentioning an extended declaration;
        buffered = with a buffer field directly or through nested declarations"""
        rec = set(n for names in s.type_sccs for n in names)
        direct = set()
        for d in s.prog.types:
            if any(is_array(fd.type) or fd.type == STR for _, fd in s.decl_fields(d)):
                direct.add(d.name)
        ext = set(rec) | direct
        buf = set(direct)
        # reverse dependency edges built once: mentioned name -> declaration names mentioning it
        rev = {}
        for d in s.prog.types:
            for n in set(n for _, fd in s.decl_fields(d) for n in dependencies(fd.type)):
                rev.setdefault(n, []).append(d.name)
        for marked in (ext, buf):
            queue = sorted(marked)
            while queue:
                n = queue.pop()
                for m in rev.get(n, ()):
                    if m not in marked:
                        marked.add(m)
                        queue.append(m)
        s.extended = ext
        s.buffered = buf

    def is_extended(s, ty):
        return ty.owner is None and not ty.args and ty.name in s.extended

    def ext_misuse(s, node, ty, inside=None):
        """an extended type may not be a type argument (type_argument) or a G6 collection payload (foreign_owned_type)"""
        if ty.owner is not None:
            return
        if is_collection(ty):
            for a in ty.args:
                s.ext_misuse(node, a, "coll")
            return
        if ty.name in s.extended and not ty.args and ty.name in s.decls:
            if inside == "coll":
                terr(node, "foreign_owned_type", "%s cannot be a Vec or HashMap element: it is recursive or holds an "
                     "array/str" % type_name(ty), "keep extended values in their own bindings")
            if inside == "arg":
                terr(node, "type_argument", "%s cannot be a type argument or an Option/Result payload: it is "
                     "recursive or holds an array/str" % type_name(ty),
                     "use a dedicated non-generic enum instead")
            return
        for a in ty.args:
            s.ext_misuse(node, a, "coll" if inside == "coll" else "arg")

    def check_extended_uses(s):
        for d in s.prog.types:
            for _, fd in s.decl_fields(d):
                if d.tparams:
                    hit = [n for n in dependencies(fd.type) if n in s.extended]
                    if hit:
                        terr(fd, "field_type", "generic type %s cannot have the field %s of the extended type %s" % (
                            d.name, fd.name, hit[0]), "use a dedicated non-generic declaration")
                s.ext_misuse(fd, fd.type)
        for f in s.prog.functions:
            for p in f.params:
                s.ext_misuse(f, p.type)
            s.ext_misuse(f, f.ret)

    def check_entries(s):
        """G4 A0 (explicit mode): a host entry (root `pub`, nongeneric, ordinary function) may not have a collection or an
        extended (G9) type in its signature; child `pub` functions and generic functions are not host entries"""
        for f in s.prog.functions:
            if not f.host_entry:
                continue
            for what, ty in [("parameter %s" % p.name, p.type) for p in f.params] + [("the result", f.ret)]:
                if contains_collection(ty) or any(n in s.extended for n in dependencies(ty)):
                    terr(f, "entry_signature", "host entry %s cannot have the type %s in %s" % (
                        f.name, type_name(ty), what),
                         "keep it Pruv-callable (child `pub` or private) and expose a scalar/value wrapper at the root")

    def check_fn_sccs(s):
        names = [f.name for f in s.prog.functions]
        index = {n: i for i, n in enumerate(names)}
        adj = [[] for _ in names]
        for caller, _call, callee in s.call_log:
            i, j = index[caller.name], index[callee.name]
            if j not in adj[i]:
                adj[i].append(j)
        comps = [comp for comp in _sccs(len(names), adj) if len(comp) > 1 or comp[0] in adj[comp[0]]]
        # bucket the call log once per recursive SCC, keeping the original relative order
        scc_of = {i: k for k, comp in enumerate(comps) for i in comp}
        buckets = [[] for _ in comps]
        for c, call, callee in s.call_log:
            k = scc_of.get(index[c.name])
            if k is not None and scc_of.get(index[callee.name]) == k:
                buckets[k].append((index[c.name], call, callee))
        for comp, bucket in zip(comps, buckets):
            s.fn_sccs.append([names[i] for i in comp])
            for i in comp:
                f = s.prog.functions[i]
                if f.decreases is None:
                    cyc = [names[k] for k in _cycle_through(i, adj, comp)]
                    terr(f, "recursive_decreases", "recursive function %s needs a decreases clause (cycle: %s)" % (
                        f.name, " -> ".join(cyc)), "add `decreases <expr>` after requires/ensures, e.g. `decreases n`")
            edges = bucket
            edges.sort(key=lambda x: (x[0], x[1].line, x[1].col))
            for ci, call, callee in edges:
                caller = s.prog.functions[ci]
                ok = len(caller.tparams) == len(callee.tparams) and \
                    all(a.bound == b.bound for a, b in zip(caller.tparams, callee.tparams))
                if ok:
                    targs = call.targs if call.targs is not None else []
                    ok = len(targs) == len(caller.tparams) and all(
                        t.owner == fn_owner(caller.name) and t.index == k and not t.args
                        for k, t in enumerate(targs))
                if not ok:
                    terr(call, "recursive_polymorphism", "recursive call to %s must pass the type parameters <%s> "
                         "unchanged" % (callee.name, ", ".join(tp.name for tp in caller.tparams)),
                         "call with ::<T, ...> in the same order")

    def record_g9(s):
        """G9 metadata on the program and the type table, only when a G9 feature is present"""
        if not (s.type_sccs or s.extended or s.fn_sccs or any(f.decreases is not None for f in s.prog.functions)):
            return
        meta = {"type_sccs": [list(x) for x in s.type_sccs], "boxed": list(s.boxed),
                "extended": [d.name for d in s.prog.types if d.name in s.extended],
                "fn_sccs": [list(x) for x in s.fn_sccs]}
        s.prog.g9 = meta
        s.tt.g9 = meta

    # ---- function ----
    def fn(s, f):
        s.f = f
        s.enter(fn_owner(f.name), f.tparams)
        s.calls[f.name] = set()
        if f.foreign is not None:
            check_foreign_decl(f, s.externs)
            if f.decreases is not None:     # G9 A0: foreign termination is trusted
                terr(f.decreases, "recursive_decreases", "a trusted rust fn cannot have a decreases clause",
                     "remove it; foreign termination is trusted")
        elif f.name == "main" and (is_collection(f.ret) or any(is_collection(p.type) for p in f.params)):
            terr(f, "foreign_export", "main cannot have a collection parameter or result",
                 "give main plain value parameters and result; use collections inside it")
        scope = {}
        for p in f.params:
            if p.name in scope:
                terr(f, "dup_param", "duplicate parameter %s" % p.name)
            if p.type == UNIT:
                terr(f, "unit_param", "parameter %s cannot have type ()" % p.name)
            if p.take and not is_collection(p.type):
                terr(f, "foreign_move", "take is only for collection parameters",
                     "remove `take` from %s; scalars, arrays and str are passed by value or borrowed" % p.name)
            scope[p.name] = (p.type, False, "param")
        s.used_effects = set()
        for r in f.requires:
            s.expect(r, BOOL, scope, contract=True)
        escope = dict(scope)
        if f.ret != UNIT:
            escope["result"] = (f.ret, False, "result")
        for e in f.ensures:
            s.expect(e, BOOL, escope, contract=True)
        if f.decreases is not None:      # G9 A0: scalar measure over the parameters only (no result)
            s.expect(f.decreases, I64, scope, contract=True)
        if f.foreign is not None:
            return                       # a trusted rust fn has no body to check
        s.block(f.body, dict(scope))
        if f.ret != UNIT and not s.ends_in_return(f.body):
            terr(f, "missing_return", "function %s may reach its end without returning" % f.name,
                 "end every path with `return ...;`")
        for e in sorted(s.used_effects):
            if e not in f.effects:
                terr(f, "missing_effect", "function %s uses effect `%s` but does not declare it" % (f.name, e),
                     "add `! %s` after the return type" % ", ".join(sorted(set(f.effects) | s.used_effects)),
                     stage="effect")
        check_ownership(f, s.funcs)      # G6: liveness of collection bindings (after typing)

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
            s.ext_misuse(st, st.type)
            s.alloc_hint_for(st.value, st.type)
            s.expect(st.value, st.type, scope)
            if is_array(st.type) or st.type == STR:
                s.array_source(st, st.value, scope)
            s.own(st.value)
            scope[st.name] = (st.type, st.mutable, "local")
        elif isinstance(st, Assign):
            v = s.lookup(st, st.name, scope)
            s.check_borrow(st, st.name, [])
            if not v[1]:
                terr(st, "immutable", "%s is not mutable" % st.name,
                     "declare it with `let mut`" if v[2] == "local" else "parameters are immutable; copy into a `let mut` local")
            s.alloc_hint_for(st.value, v[0])
            s.expect(st.value, v[0], scope)
            if is_array(v[0]) or v[0] == STR:
                s.array_source(st, st.value, scope)
            s.own(st.value)
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
            s.check_borrow(st, st.name, st.fields)
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
            if is_array(cur) or cur == STR:      # G9 A0: G2 explicit ownership for a buffer field
                s.array_source(st, st.value, scope)
            s.own(st.value)
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
                s.own(st.value)
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
            root = s.match_root(st.scrutinee, t, scope)   # G9 A0: root variable of an extended scrutinee path
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
                    # G9 A0: a buffer payload is a read view (like a parameter): returning it needs copy()
                    sc[b] = (bt, False, "param" if (is_array(bt) or bt == STR) else "local")
                if root is not None:
                    s.active_roots.append(root)
                s.block(a.body, sc)
                if root is not None:
                    s.active_roots.pop()
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

    # ---- G9 A0: ownership of extended values, active-match borrows ----
    def own(s, value):
        """`value` (already typed) is moved into an owning position (let, assignment, constructor field, return):
        a non-fresh extended value is cloned, which needs `alloc`; constructors, literals and calls are fresh"""
        t = value.ty
        if t is not None and s.is_extended(t) and not isinstance(value, (EnumCtor, StructLit, Call)):
            s.used_effects.add("alloc")

    def own_field(s, value, ftype, scope, c):
        """a constructor / struct-literal field argument: owning position, G2 explicit ownership for buffers"""
        if c:
            return
        if is_array(ftype) or ftype == STR:
            s.array_source(value, value, scope)
        s.own(value)

    def ctor_allocs(s, decl_name, variant, c):
        """a constructor that initializes a boxed field allocates"""
        if not c and (decl_name, variant) in s.boxed_decls:
            s.used_effects.add("alloc")

    def match_root(s, scrut, t, scope):
        """root variable of a match scrutinee that is a variable / field path over an extended type, else None"""
        if not s.is_extended(t):
            return None
        e = scrut
        while isinstance(e, FieldAccess):
            e = e.base
        if isinstance(e, Var) and e.name in scope and scope[e.name][2] in ("local", "param"):
            return e.name
        return None

    def check_borrow(s, st, name, fields):
        if name in s.active_roots:
            terr(st, "recursive_borrow", "cannot assign to %s while a match on it is active" % ".".join([name] + list(fields)),
                 "copy the needed payload into a local, finish the match, then assign")

    def alloc_hint_for(s, value, expected):
        """G2: only a builtin alloc call that IS the right-hand side of a typed let / array reassignment /
        return takes its array type from the expected type"""
        if isinstance(value, Call) and value.name == "alloc" and is_array(expected):
            s.alloc_hint = (value, expected)

    def expect_array(s, e, scope, c, coll=False):
        """the argument must be an array of any element type (G2 B0: or a str); same diagnostic as expect(e, ARRAY, ...)
        coll (G6): a Vec/HashMap/String is accepted too"""
        t = s.expr(e, scope, c)
        if t.owner is not None:
            terr(e, "generic_operation", "%s is an abstract type parameter, not an array" % type_name(t),
                 "only [T] with T: Element can be indexed, measured or copied")
        if not is_array(t) and t != STR and not (coll and is_collection(t)):
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
                if is_collection(lt):   # G6
                    terr(e, "eq_type", "collections cannot be compared with ==",
                         "compare lengths and elements: len(a) == len(b) && forall k in 0..len(a): a[k] == b[k]")
                if is_array(lt):
                    terr(e, "eq_type", "arrays cannot be compared with ==",
                         "compare lengths and elements: len(a) == len(b) && forall k in 0..len(a): a[k] == b[k]")
                if lt == STR:   # G2 B0
                    terr(e, "eq_type", "str values cannot be compared with ==",
                         "compare lengths and bytes: len(a) == len(b) && forall k in 0..len(a): a[k] == b[k]")
                if lt.owner is None and any(n in s.buffered for n in dependencies(lt)):   # G9 A0
                    terr(e, "eq_type", "values of %s contain arrays or str and cannot be compared with ==" % type_name(lt),
                         "compare tags, lengths and indexed contents instead")
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
        if isinstance(e, Move):   # G6: liveness and position rules are checked by foreign.check_ownership
            if c:
                terr(e, "foreign_move", "move only where ownership is consumed",
                     "contracts read parameters and locals directly; remove `move`")
            return s.lookup(e, e.name, scope)[0]
        if isinstance(e, Index):
            at = s.expect_array(e.array, scope, c, coll=True)
            if at.name == "hashmap" and at.owner is None:
                terr(e.array, "type_mismatch", "expected %s, found %s" % (type_name(ARRAY), type_name(at)))
            s.expect(e.index, I64, scope, c)
            if is_collection(at):     # G6: contract-only observation of a Vec / String
                if not c:
                    terr(e, "contract_only", "indexing a %s is only allowed in contracts" % type_name(at),
                         "use vec_get in code" if at.name == "vec" else "use string_byte in code")
                return at.args[0] if at.name == "vec" else I64
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
                s.own_field(arg, ft, scope, c)
            s.ctor_allocs(e.enum_name, e.variant, c)
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
        # find the field first, then substitute only its type (substituting every field made x.f O(fields))
        for fd in s.tt.fields(sty, None):
            if fd.name == name:
                if not sty.args:
                    return fd.type
                d = s.decls[sty.name]
                return substitute(fd.type, bind_args(decl_owner(sty.name), len(d.tparams), sty.args))
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
            s.own_field(fi.value, ft, scope, c)
        s.ctor_allocs(e.name, None, c)
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
        s.ext_misuse(e, x, "arg")      # G9 A0
        e.inst = {"decl": "builtin:" + e.name, "args": (x,), "subst": {("builtin:" + e.name, 0): x}}
        if e.name == "None":
            return mk_option(x)
        s.expect(e.arg, I64 if e.name == "Err" else x, scope, c)
        return mk_option(x) if e.name == "Some" else mk_result(x)

    def observer_args(s, e, f, m, scope, c):
        """map_lookup / map_updated arguments: a key whose type differs from a map argument's key type is a
        foreign_contract error; any other mismatch is the ordinary type_mismatch"""
        got = [s.expr(arg, scope, c) for arg in e.args]
        kidx = [p.name for p in f.params].index("k")
        for g in got:
            if g.name == "hashmap" and g.owner is None and g.args[0] != got[kidx]:
                terr(e.args[kidx], "foreign_contract", "key of type %s does not match the map key type %s" % (
                    type_name(got[kidx]), type_name(g.args[0])),
                     "pass a key of the map's key type")
        for arg, g, p in zip(e.args, got, f.params):
            want = substitute(p.type, m)
            if g != want:
                terr(arg, "type_mismatch", "expected %s, found %s" % (type_name(want), type_name(g)))

    def call(s, e, scope, c):
        n, a = e.name, e.args

        def arity(k):
            if len(a) != k:
                terr(e, "arity", "%s takes %d argument(s), got %d" % (n, k, len(a)))
        if e.targs is not None and n not in s.funcs and (n in BUILTIN_FNS or n in CONTRACT_ONLY):
            terr(e, "type_arity", "builtin %s takes no type arguments" % n, "remove the `::<...>`")
        if n == "len":
            arity(1); s.expect_array(a[0], scope, c, coll=True); return I64   # G6: also Vec/HashMap/String
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
                terr(e, "contract_only", "%s is only allowed in contracts" % n,
                     "size is a contract measure; use len or a counter in code" if n == "size" else "use match in code")
            arity(1)
            kind, rt = CONTRACT_ONLY[n]
            t = s.expr(a[0], scope, c)
            if n == "size":     # G9 A0: a non-generic user struct/enum value
                if not (s.is_plain_nominal(t) and not s.decls[t.name].tparams):
                    terr(e, "size_type", "size needs a non-generic struct or enum value, got %s" % type_name(t),
                         "size counts constructors; use len for arrays and strings")
                return I64
            if t.owner is not None or t.name != kind:
                terr(a[0], "type_mismatch", "expected %s, found %s" % (type_name(OPTION if kind == "option" else RESULT),
                                                                         type_name(t)))
            if rt == "payload":     # G3: the payload type of Option<X> / Result<X>
                return t.args[0] if t.args else I64
            return rt
        catalog = n in CATALOG       # G6: fixed standard catalog (G6_SPEC 10.3)
        if catalog:
            if n in CATALOG_CONTRACT_ONLY:
                if not c:
                    terr(e, "foreign_contract", "%s is only allowed in contracts" % n,
                         "use map_get in code" if n == "map_lookup" else "state the update in ensures")
            elif c:
                terr(e, "foreign_contract", "%s cannot be called in a contract" % n,
                     "contracts observe collections with len(x), x[i], map_lookup and map_updated")
            f = CATALOG[n]
        elif n not in s.funcs:
            if n in ("sum", "count", "max", "min"):
                terr(e, "unknown_fn", "unknown function %s" % n,
                     "aggregates use the form sum(k in 0..len(a): a[k])")
            terr(e, "unknown_fn", "unknown function %s" % n)
        else:
            f = s.funcs[n]
            if c and f.foreign is not None:
                terr(e, "foreign_contract", "trusted rust fn %s cannot be called in a contract" % n,
                     "state the property with the arguments' own contents instead")
        # G3_SPEC 3.4: resolve + arity + admissibility + bounds, substitute the signature, check the arguments
        m = s.instantiate(e, "function %s" % n, fn_owner(n), f.tparams, e.targs)
        if m is not None:
            e.inst = {"decl": fn_owner(n), "args": tuple(e.targs), "subst": m}
        else:
            m = {}
        arity(len(f.params))
        if n in CATALOG_CONTRACT_ONLY:
            s.observer_args(e, f, m, scope, c)
        else:
            for arg, p in zip(a, f.params):
                s.expect(arg, substitute(p.type, m), scope, c)
        if catalog:
            s.used_effects.update(f.effects)
            return substitute(f.ret, m)
        if c and f.effects:
            terr(e, "effect_in_contract", "function %s has effects; not allowed in contracts" % n)
        if c:
            terr(e, "call_in_contract", "calling functions in contracts is not supported in v0.1",
                 "inline the property")
        s.used_effects.update(f.effects)
        s.calls[s.f.name].add(n)
        if f.foreign is None:     # G9 A0: foreign calls are leaves of the call graph
            s.call_log.append((s.f, e, f))
        return substitute(f.ret, m)


def check(prog, externs=()):
    """externs: names given with --rust-extern (crates a trusted rust fn path may start with besides std)"""
    Checker(prog, externs).run()
