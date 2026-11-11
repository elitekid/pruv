"""Shared type information for user structs/enums (G1).
`type_name` prints any Type; `TypeTable` indexes the declarations of a checked Program.
The checker validates declarations first; later passes build a TypeTable from the checked program."""
from typing import Dict, List, Optional

from vast import *

BUILTIN_TYPE_NAMES = frozenset(["i64", "bool", "unit", "array", "option", "result"])
_BUILTIN_PRINT = {"i64": "i64", "bool": "bool", "unit": "()", "array": "[i64]", "option": "Option<i64>",
                  "result": "Result<i64>"}


# G2 A0: one place for array type queries (internal array types -> element type).
ARRAY_ELEM = {"array": I64, "array_u8": U8, "array_bool": BOOL}
_ARRAY_OF = {"i64": ARRAY, "u8": ARRAY_U8, "bool": ARRAY_BOOL}


def is_array(ty: Type) -> bool:
    return ty.name in ARRAY_ELEM


def array_elem(ty: Type) -> Optional[Type]:
    """Element type of an array type; None when ty is not an array type."""
    return ARRAY_ELEM.get(ty.name)


def array_of(elem: Type) -> Optional[Type]:
    """Array type holding elem; None when no such array type exists."""
    return _ARRAY_OF.get(elem.name)


def is_user_type(ty: Type) -> bool:
    """True for a Type that names a user struct/enum (declared or not)."""
    return ty.name not in BUILTIN_TYPE_NAMES


def type_name(ty: Type) -> str:
    """Source-level spelling of a type; a user type prints as its own name."""
    return _BUILTIN_PRINT.get(ty.name, ty.name)


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
