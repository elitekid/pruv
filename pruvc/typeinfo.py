"""Shared type information for user structs/enums (G1).
`type_name` prints any Type; `TypeTable` indexes the declarations of a checked Program.
The checker validates declarations first; later passes build a TypeTable from the checked program."""
from typing import Dict, List, Optional

from vast import *

BUILTIN_TYPE_NAMES = frozenset(["i64", "bool", "unit", "array", "option", "result", "array_u8", "array_bool", "str"])
_BUILTIN_PRINT = {"i64": "i64", "bool": "bool", "unit": "()", "array": "[i64]", "option": "Option<i64>",
                  "result": "Result<i64>", "array_u8": "[u8]", "array_bool": "[bool]", "str": "str"}


# G2 A0: one place for array type queries (internal array types -> element type).
ARRAY_ELEM = {"array": I64, "array_u8": U8, "array_bool": BOOL}
_ARRAY_OF = {"i64": ARRAY, "u8": ARRAY_U8, "bool": ARRAY_BOOL}


def is_array(ty: Type) -> bool:
    return ty.name in ARRAY_ELEM


def array_elem(ty: Type) -> Optional[Type]:
    """Element type of an array type; None when ty is not an array type."""
    if ty.name == "array" and ty.args:
        return ty.args[0]            # G3: [X] for X other than i64/u8/bool
    return ARRAY_ELEM.get(ty.name)


def array_of(elem: Type) -> Optional[Type]:
    """Array type holding elem; None when no such array type exists."""
    return _ARRAY_OF.get(elem.name)


def is_user_type(ty: Type) -> bool:
    """True for a Type that names a user struct/enum (declared or not)."""
    return ty.name not in BUILTIN_TYPE_NAMES and ty.owner is None


def type_name(ty: Type) -> str:
    """Source-level spelling of a type; a user type prints as its own name.
    Legacy types print exactly as before; structured types (G3) print via format_type."""
    if ty.args or ty.owner is not None:
        return format_type(ty)
    return _BUILTIN_PRINT.get(ty.name, ty.name)


# ---------------------------------------------------------------------------
# G3 A0: shared structured-type API (G3_SPEC 7.2). Independent of the checker:
# declarations are described by `decls`, a dict or callable  name -> (nparams, fields)  or None, where
# fields is the flat list of field Types of the declaration (all variants for an enum), written with
# mk_param(decl_owner(name), i, <param name>) for its i-th type parameter.
# ---------------------------------------------------------------------------
class TypeArityError(ValueError):
    """Wrong number of type arguments."""


def decl_owner(name: str) -> str:
    return "type:" + name


def fn_owner(name: str) -> str:
    return "fn:" + name


def is_param(ty: Type) -> bool:
    return ty.owner is not None


def param_id(ty: Type):
    """Identity of a bound parameter: (declaration owner, index)."""
    return (ty.owner, ty.index)


def type_eq(a: Type, b: Type) -> bool:
    """Structural equality; parameters are equal iff owner and index are equal."""
    return a == b


def format_type(ty: Type) -> str:
    """Source spelling: "Pair<i64, bool>", "[T]", "Option<bool>". Legacy types print as in the old dumps."""
    if ty.owner is not None:
        return ty.name
    if not ty.args:
        return _BUILTIN_PRINT.get(ty.name, ty.name)
    inner = ", ".join(format_type(a) for a in ty.args)
    if ty.name == "array":
        return "[%s]" % inner
    if ty.name == "option":
        return "Option<%s>" % inner
    if ty.name == "result":
        return "Result<%s>" % inner
    return "%s<%s>" % (ty.name, inner)


legacy_dump = type_name   # dump formatting: identical to the pre-G3 output for every legacy type


def _lookup(decls, name):
    if decls is None:
        return None
    return decls(name) if callable(decls) else decls.get(name)


def _is_nominal(ty: Type) -> bool:
    return ty.owner is None and ty.name not in BUILTIN_TYPE_NAMES


def bind_args(owner: str, nparams: int, args) -> dict:
    """Substitution mapping for a declaration's parameters; TypeArityError on a count mismatch."""
    if len(args) != nparams:
        raise TypeArityError("%s expects %d type argument(s), got %d" % (owner, nparams, len(args)))
    return {(owner, i): a for i, a in enumerate(args)}


def substitute(ty: Type, mapping: dict) -> Type:
    """Simultaneous substitution: mapping {(owner, index): Type}. Parameters carry declaration identity,
    so equal parameter names of different declarations never collide, and replacements are not re-substituted."""
    if ty.owner is not None:
        return mapping.get((ty.owner, ty.index), ty)
    if not ty.args:
        return ty
    args = tuple(substitute(a, mapping) for a in ty.args)
    if ty.name == "array":
        return mk_array(args[0])
    if ty.name == "option":
        return mk_option(args[0])
    if ty.name == "result":
        return mk_result(args[0])
    return mk_nominal(ty.name, args)


def check_arity(ty: Type, decls) -> None:
    """TypeArityError if any Option/Result/array/nominal application inside ty has the wrong argument count.
    Nominal names unknown to decls are skipped (the checker reports them)."""
    if ty.owner is None and ty.args:
        if ty.name in ("option", "result", "array") and len(ty.args) != 1:
            raise TypeArityError("%s expects 1 type argument, got %d" % (ty.name, len(ty.args)))
    if _is_nominal(ty):
        info = _lookup(decls, ty.name)
        if info is not None and info[0] != len(ty.args):
            raise TypeArityError("%s expects %d type argument(s), got %d" % (ty.name, info[0], len(ty.args)))
    for a in ty.args:
        check_arity(a, decls)


def nominal_fields(ty: Type, decls) -> list:
    """Field types of a nominal application with its arguments substituted."""
    nparams, fields = _lookup(decls, ty.name)
    m = bind_args(decl_owner(ty.name), nparams, ty.args)
    return [substitute(f, m) for f in fields]


def is_value(ty: Type, decls, _seen=()) -> bool:
    """Admissible value (G3_SPEC 3.1): i64, bool, Option<V>, Result<V>, D<V..> whose substituted fields are
    values, or a type parameter (it ranges over values). Not arrays, str, unit, u8."""
    if ty == I64 or ty == BOOL or ty.owner is not None:
        return True
    if ty.name in ("option", "result"):
        return all(is_value(a, decls, _seen) for a in ty.args)
    if not _is_nominal(ty):
        return False
    info = _lookup(decls, ty.name)
    if info is None or info[0] != len(ty.args) or ty.name in _seen:
        return False
    if not all(is_value(a, decls, _seen) for a in ty.args):
        return False
    return all(is_value(f, decls, _seen + (ty.name,)) for f in nominal_fields(ty, decls))


def is_element(ty: Type, element_params=()) -> bool:
    """Element (G3_SPEC 3.2): exactly i64, bool, or a parameter whose identity is in element_params."""
    if ty == I64 or ty == BOOL:
        return True
    return ty.owner is not None and param_id(ty) in element_params


def dependencies(ty: Type) -> list:
    """Names of nominal declarations referenced anywhere inside ty (nested args included),
    in first-occurrence (pre-order) order, without duplicates."""
    out: list = []

    def walk(t):
        if _is_nominal(t) and t.name not in out:
            out.append(t.name)
        for a in t.args:
            walk(a)
    walk(ty)
    return out


def encode(ty: Type) -> str:
    """Canonical specialization encoding (G3_SPEC 5.2); only concrete value types are encodable."""
    if ty == I64:
        return "i"
    if ty == BOOL:
        return "b"
    if ty.owner is None and ty.name in ("option", "result"):
        return ("o" if ty.name == "option" else "r") + encode(ty.args[0] if ty.args else I64)
    if _is_nominal(ty):
        return "n%d_%s_%d" % (len(ty.name.encode("utf-8")), ty.name, len(ty.args)) + \
            "".join("_" + encode(a) for a in ty.args)
    raise ValueError("type %s has no specialization encoding" % format_type(ty))


def _stem(kind: str, name: str, args) -> str:
    s = "pruv_g3_%s_%d_%s_%d" % (kind, len(name.encode("utf-8")), name, len(args))
    return s + "".join("_" + encode(a) for a in args)


def spec_fn_stem(name: str, args) -> str:
    """pruv_g3_f_<len>_<name>_<arity>_<encoded args> (no trailing part when arity is 0)."""
    return _stem("f", name, args)


def spec_type_stem(name: str, args) -> str:
    """pruv_g3_t_<len>_<name>_<arity>_<encoded args>."""
    return _stem("t", name, args)


def _g2_hit(ty, skip):
    return ((is_array(ty) and ty != ARRAY) or ty == STR) and ty.name not in skip


def _g2_candidates(node, skip, out):
    """collect (line, col, ty) candidates under node: Lets with a hit type, and (when "str" is not
    skipped) every StrLit. Generic walk over dataclass fields (Types are skipped)."""
    if isinstance(node, list):
        for x in node:
            _g2_candidates(x, skip, out)
        return
    if not hasattr(node, "__dataclass_fields__") or isinstance(node, Type):
        return
    if isinstance(node, Let) and _g2_hit(node.type, skip):
        out.append((node.line, node.col, node.type))
    elif isinstance(node, StrLit) and "str" not in skip:
        out.append((node.line, node.col, STR))
    for fname in node.__dataclass_fields__:
        _g2_candidates(getattr(node, fname), skip, out)


def first_g2_unimplemented(prog, skip=()):
    """G2: first non-[i64] array type or str the proof/codegen layers do not implement yet.
    -> (line, col, ty) or None. Per function (declaration order): first param, return type, then the
    smallest (line, col) among body Lets and (unless "str" is skipped) string literals anywhere in the function.
    skip: internal type names (e.g. "array_u8") that are ignored."""
    for fn in prog.functions:
        for p in fn.params:
            if _g2_hit(p.type, skip):
                return (fn.line, fn.col, p.type)
        if _g2_hit(fn.ret, skip):
            return (fn.line, fn.col, fn.ret)
        cands = []
        _g2_candidates(fn.requires, skip, cands)
        _g2_candidates(fn.ensures, skip, cands)
        _g2_candidates(fn.body, skip, cands)
        if cands:
            return min(cands, key=lambda c: (c[0], c[1]))
    return None


def _any_array_named(stmts, name):
    for st in stmts:
        if isinstance(st, Let):
            if st.type.name == name:
                return True
        elif isinstance(st, If):
            if _any_array_named(st.then, name) or _any_array_named(st.els, name):
                return True
        elif isinstance(st, While):
            if _any_array_named(st.body, name):
                return True
        elif isinstance(st, Match):
            for arm in st.arms:
                if _any_array_named(arm.body, name):
                    return True
    return False


def uses_array_type(prog, name):
    """True if some param, return type or let type of the program is the internal type `name`."""
    for fn in prog.functions:
        for p in fn.params:
            if p.type.name == name:
                return True
        if fn.ret.name == name:
            return True
        if _any_array_named(fn.body, name):
            return True
    return False


def _has_str_node(node):
    """True if a StrLit or a Let of type str occurs under node (generic dataclass walk; Types are skipped)."""
    if isinstance(node, list):
        return any(_has_str_node(x) for x in node)
    if not hasattr(node, "__dataclass_fields__") or isinstance(node, Type):
        return False
    if isinstance(node, StrLit):
        return True
    if isinstance(node, Let) and node.type.name == "str":
        return True
    for fname in node.__dataclass_fields__:
        if _has_str_node(getattr(node, fname)):
            return True
    return False


def uses_str(prog):
    """G2 B2: True if some param/return/let type is str or any requires/ensures/body expression has a string literal."""
    if uses_array_type(prog, "str"):
        return True
    for fn in prog.functions:
        if _has_str_node(fn.requires) or _has_str_node(fn.ensures) or _has_str_node(fn.body):
            return True
    return False


def g2_unimplemented_error(prog, stage, layer=None, skip=(), fix=None):
    """PruvError for the first unimplemented array type, or None. stage: "verify" | "codegen"."""
    f = first_g2_unimplemented(prog, skip)
    if f is None:
        return None
    line, col, ty = f
    if ty == STR:
        return PruvError(stage, line, col, "unsupported_type",
                         "str is not supported yet: the %s layer is not implemented" % (layer or stage),
                         fix or "do not use str yet")
    return PruvError(stage, line, col, "unsupported_type",
                     "%s arrays are not supported yet: the %s layer is not implemented" % (type_name(ty), layer or stage),
                     fix or "use [i64] for now")


class TypeTable:
    def __init__(self, prog: Program):
        # first declaration wins if a name is repeated (the checker rejects duplicates)
        self.decls: Dict[str, TypeDecl] = {}
        for d in prog.types:
            if d.name not in self.decls:
                self.decls[d.name] = d
        self.order: List[TypeDecl] = []
        self._build_order()

    # ---- dependency-first, declaration-stable order ----
    def _deps(self, d: TypeDecl) -> List[str]:
        out: List[str] = []
        for f in self._all_fields(d):
            if is_user_type(f.type) and f.type.name in self.decls and f.type.name not in out:
                out.append(f.type.name)
        return out

    @staticmethod
    def _all_fields(d: TypeDecl) -> List[FieldDecl]:
        if isinstance(d, StructDecl):
            return list(d.fields)
        out: List[FieldDecl] = []
        for v in d.variants:
            out.extend(v.fields)
        return out

    def _build_order(self) -> None:
        seen = set()

        def visit(d: TypeDecl) -> None:
            if d.name in seen:
                return
            seen.add(d.name)          # marked first: a cycle (rejected by the checker) cannot loop
            for n in self._deps(d):
                visit(self.decls[n])
            self.order.append(d)
        for d in self.decls.values():
            visit(d)

    # ---- queries ----
    def decl(self, ty: Type) -> TypeDecl:
        return self.decls[ty.name]

    def is_struct(self, ty: Type) -> bool:
        return isinstance(self.decls.get(ty.name), StructDecl) and is_user_type(ty)

    def is_enum(self, ty: Type) -> bool:
        return isinstance(self.decls.get(ty.name), EnumDecl) and is_user_type(ty)

    def variant(self, ty: Type, variant: str) -> VariantDecl:
        for v in self.decl(ty).variants:
            if v.name == variant:
                return v
        raise KeyError("%s::%s" % (ty.name, variant))

    def fields(self, ty: Type, variant: Optional[str] = None) -> List[FieldDecl]:
        """Struct fields, or the fields of `variant` for an enum, in declaration order."""
        d = self.decl(ty)
        if isinstance(d, StructDecl):
            return d.fields
        if variant is None:
            raise KeyError("enum %s needs a variant" % ty.name)
        return self.variant(ty, variant).fields

    def field_index(self, ty: Type, name: str, variant: Optional[str] = None) -> int:
        for i, f in enumerate(self.fields(ty, variant)):
            if f.name == name:
                return i
        raise KeyError(name)

    def variant_index(self, ty: Type, variant: str) -> int:
        for i, v in enumerate(self.decl(ty).variants):
            if v.name == variant:
                return i
        raise KeyError("%s::%s" % (ty.name, variant))
