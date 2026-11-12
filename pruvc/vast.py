"""Pruv AST. Shared interface between parser, checker, verifier and codegen.
Python 3.9: no match statements, no `X | Y` type unions at runtime.
Every node has `line` and `col` (1-based) of its first token.
Checker fills `Expr.ty` with a Type after type checking."""
from dataclasses import dataclass, field
from typing import List, Optional

# ---------- types ----------
@dataclass(frozen=True, eq=False)
class Type:
    """name: "i64" | "bool" | "unit" | "array" | "option" | "result" | ... | a user nominal name | a parameter name.
    G3 A0 optional fields (all defaults leave every legacy type unchanged, so legacy equality/hash/print are as before):
      args:  type arguments of a structured type: Option<X> / Result<X> -> (X,); [X] -> (X,); D<X0,..> -> (X0,..).
      owner/index: set only on a bound type parameter: owner is the declaration identity ("fn:<name>" or
             "type:<name>", see typeinfo.fn_owner/decl_owner) and index its position in that declaration's list.
    Build structured types with the mk_* constructors: they normalize to the legacy constants
    (Option<i64> -> OPTION, Result<i64> -> RESULT, [i64]/[u8]/[bool] -> ARRAY/ARRAY_U8/ARRAY_BOOL)."""
    name: str
    args: tuple = ()
    owner: Optional[str] = None
    index: int = -1

    def _key(self):
        # a parameter's identity is (owner, index); its name is only for printing (same rule as gtype.rs)
        return ("param", self.owner, self.index) if self.owner is not None else (self.name, self.args)

    def __eq__(self, other):
        return isinstance(other, Type) and self._key() == other._key()

    def __hash__(self):
        return hash(self._key())

I64 = Type("i64"); BOOL = Type("bool"); UNIT = Type("unit")
ARRAY = Type("array"); OPTION = Type("option"); RESULT = Type("result")
# G2 A0: internal-only types (never accepted as source spelling). ARRAY stays the [i64] array.
U8 = Type("u8")
ARRAY_U8 = Type("array_u8"); ARRAY_BOOL = Type("array_bool")
# G2 B0: the string type (not an array); internal name equals the source spelling
STR = Type("str")

# ---------- G3 A0: structured type constructors ----------
def mk_param(owner: str, index: int, name: str) -> Type:
    """A bound type parameter: identity is (owner, index); the name is for printing."""
    return Type(name, (), owner, index)

def mk_option(x: Type) -> Type:
    return OPTION if x == I64 else Type("option", (x,))

def mk_result(x: Type) -> Type:
    return RESULT if x == I64 else Type("result", (x,))

def mk_array(x: Type) -> Type:
    if x == I64: return ARRAY
    if x == U8: return ARRAY_U8
    if x == BOOL: return ARRAY_BOOL
    return Type("array", (x,))

def mk_nominal(name: str, args=()) -> Type:
    """User struct/enum type, applied to args (empty for a non-generic declaration)."""
    return Type(name, tuple(args))

# ---------- expressions ----------
@dataclass
class Expr:
    line: int
    col: int

@dataclass
class IntLit(Expr):
    value: int
    ty: Optional[Type] = None

@dataclass
class BoolLit(Expr):
    value: bool
    ty: Optional[Type] = None

@dataclass
class StrLit(Expr):
    value: bytes       # UTF-8 bytes of the literal (G2 B0)
    ty: Optional[Type] = None

@dataclass
class Var(Expr):
    name: str          # also "result" inside ensures
    ty: Optional[Type] = None

@dataclass
class Unary(Expr):
    op: str            # "-" | "!"
    operand: Expr
    ty: Optional[Type] = None

@dataclass
class Binary(Expr):
    op: str            # + - * / % == != < <= > >= && || ==>
    left: Expr
    right: Expr
    ty: Optional[Type] = None

@dataclass
class Call(Expr):
    # user functions and builtins: len, alloc, copy, print,
    # contract-only: is_some, some_val, is_ok, ok_val, err_val
    name: str
    args: List[Expr]
    ty: Optional[Type] = None

@dataclass
class Index(Expr):
    array: Expr
    index: Expr
    ty: Optional[Type] = None

@dataclass
class Ctor(Expr):
    name: str          # "Some" | "None" | "Ok" | "Err"
    arg: Optional[Expr]
    ty: Optional[Type] = None

@dataclass
class Quant(Expr):
    kind: str          # "forall" | "exists" | "sum" | "count" | "max" | "min" (aggregates: contract-only, i64 result)
    var: str
    lo: Expr
    hi: Expr           # exclusive
    body: Expr
    ty: Optional[Type] = None

@dataclass
class Move(Expr):
    name: str          # G6: `move name` (consumes an owned collection binding)
    ty: Optional[Type] = None

@dataclass
class InoutArg(Expr):
    # G5 A0: the call-argument marker `inout <operand>`; line/col = the `inout` token. The operand is kept as written
    # (the checker requires a plain Var naming a mutable local array or an inout parameter of the caller). It is only
    # valid directly as an argument of a call, never a value-producing expression of its own.
    expr: Expr
    ty: Optional[Type] = None

# ---------- G1: structs and enums ----------
# A user type is Type("Point"): nominal, equal iff the names are equal.
@dataclass
class FieldDecl:
    line: int
    col: int
    name: str
    type: Type

@dataclass
class VariantDecl:
    line: int
    col: int
    name: str
    fields: List[FieldDecl]

@dataclass
class TypeDecl:
    line: int
    col: int
    name: str

@dataclass
class StructDecl(TypeDecl):
    fields: List[FieldDecl]

@dataclass
class EnumDecl(TypeDecl):
    variants: List[VariantDecl]

@dataclass
class FieldInit:
    line: int
    col: int
    name: str
    value: Expr

@dataclass
class StructLit(Expr):
    name: str
    fields: List[FieldInit]
    ty: Optional[Type] = None

@dataclass
class EnumCtor(Expr):
    enum_name: str
    variant: str
    args: List[Expr]
    ty: Optional[Type] = None

@dataclass
class FieldAccess(Expr):
    base: Expr
    field: str
    ty: Optional[Type] = None

@dataclass
class IsVariant(Expr):          # contract-only
    value: Expr
    enum_name: str
    variant: str
    ty: Optional[Type] = None

@dataclass
class VariantField(Expr):       # contract-only
    value: Expr
    enum_name: str
    variant: str
    field: str
    ty: Optional[Type] = None

# ---------- statements ----------
@dataclass
class Stmt:
    line: int
    col: int

@dataclass
class Let(Stmt):
    name: str
    mutable: bool
    type: Type
    value: Expr
    refine: Optional["Refinement"] = None   # STAGE1 A: refinement annotation (None = plain type)

@dataclass
class Assign(Stmt):
    name: str
    value: Expr

@dataclass
class IndexAssign(Stmt):
    name: str
    index: Expr
    value: Expr
    # set only by refine.py on a store into a refined array with an element range:
    # [lo, hi, origin_what] (ints, str). verify proves `lo <= value <= hi` after the index_oob obligation.
    elem_refine: Optional[list] = None

@dataclass
class If(Stmt):
    cond: Expr
    then: List[Stmt]
    els: List[Stmt]    # empty if no else; `else if` becomes [If(...)]

@dataclass
class While(Stmt):
    cond: Expr
    invariants: List[Expr]
    decreases: Expr
    body: List[Stmt]

@dataclass
class Return(Stmt):
    value: Optional[Expr]

@dataclass
class Assert(Stmt):
    cond: Expr
    # set only on assertions synthesized by refine.py: the verify error code
    # ("refinement_init" | "refinement_assign") and a source description for the message
    origin_code: Optional[str] = None
    origin_what: Optional[str] = None

@dataclass
class ExprStmt(Stmt):
    expr: Expr         # Call returning unit (incl. print)

@dataclass
class FieldAssign(Stmt):
    name: str              # root local variable
    fields: List[str]      # non-empty path: `p.a.b = e` -> name="p", fields=["a", "b"]
    value: Expr

@dataclass
class MatchArm:
    line: int
    col: int
    enum_name: Optional[str]   # None for Option/Result arms, the enum name for user enums
    ctor: str                  # "Some" | "None" | "Ok" | "Err" or a variant name ("Hit")
    binders: List[str]         # Some/Ok/Err: one name; None: []; user variant: one per field
    body: List[Stmt]

@dataclass
class Match(Stmt):
    scrutinee: Expr
    arms: List[MatchArm]   # Option/Result: exactly 2; user enum: one per variant; order as written

# ---------- STAGE1 A: refinement annotations ----------
@dataclass
class Refinement:
    """Position (line, col) = first token of the annotated type. Pure metadata: Type stays the base type.
    shape "scalar": `i64 | lo..=hi` (base = the written base type name; only "i64" is valid).
    shape "array":  `[i64 | lo..=hi; <=maxlen]` or `[u8 | lo..=hi; <=maxlen]`; base is "i64" or "u8" (the written
                    element name; u8 bounds must lie in 0..=255); lo/hi both None (no element range),
                    maxlen None (no length bound).
    Bounds are unchecked Python ints here; refine.py reports type/refinement_bounds."""
    line: int
    col: int
    shape: str
    base: str
    lo: Optional[int]
    hi: Optional[int]
    maxlen: Optional[int]

# ---------- top level ----------
@dataclass
class Param:
    name: str
    type: Type
    refine: Optional[Refinement] = None

@dataclass
class Function:
    line: int
    col: int
    name: str
    params: List[Param]
    ret: Type
    effects: List[str]       # subset of ["io", "alloc"]
    requires: List[Expr]
    ensures: List[Expr]
    body: List[Stmt]
    ret_refine: Optional[Refinement] = None

@dataclass
class Program:
    functions: List[Function] = field(default_factory=list)
    types: List[TypeDecl] = field(default_factory=list)

# ---------- G3 A1: generics ----------
# Plain class attributes, deliberately NOT dataclass fields: the legacy AST schema and the parse/check dumps
# (tests/diff_py_adapter.py) stay byte-identical, and a node without G3 syntax never carries a value here.
class TypeParam:
    """One entry of a declaration's type-parameter list: `T` or `T: Element` (bound is the bound's spelling)."""
    def __init__(self, line, col, name, bound=None):
        self.line, self.col, self.name, self.bound = line, col, name, bound

Function.tparams = ()      # tuple/list of TypeParam; empty = not generic
TypeDecl.tparams = ()      # inherited by StructDecl / EnumDecl
# explicit type arguments as written (list of Type) on `f::<..>(..)`, `S::<..> {..}`, `E::<..>::V(..)`,
# `Some::<T>(x)` / `None::<T>` / `Ok::<T>(x)` / `Err::<T>(c)`; None = no type application written
Call.targs = None
StructLit.targs = None
EnumCtor.targs = None
Ctor.targs = None
# set by the checker on those four nodes when they were instantiated explicitly:
# {"decl": "fn:f" | "type:S" | "builtin:Some" ..., "args": tuple of Type, "subst": {(owner, index): Type}}
Call.inst = None
StructLit.inst = None
EnumCtor.inst = None
Ctor.inst = None
# set by the checker on IsVariant / VariantField: the complete instantiated enum type of the scrutinee
IsVariant.enum_ty = None
VariantField.enum_ty = None

# ---------- G6 A0: foreign declarations and ownership ----------
# Same convention as G3: plain class attributes, so every dump of a G6-free program is unchanged.
Param.take = False         # `take name: Type` (consuming collection parameter)
Function.foreign = None    # trusted rust fn: {"path": "::std::cmp::min", "line": L, "col": C} (line/col of the path
                           # string token); the body is []

# ---------- G9 A0: recursion, decreases, extended types ----------
# Same convention: plain class attributes, set on an instance only when a G9 feature is present.
Function.decreases = None  # the `decreases Expr` clause of a function header (None = absent)
Program.g9 = None          # checker metadata dict (see check.Checker.g9_meta), only when a G9 feature exists

# ---------- G5 A0: inout parameters ----------
# Same convention: plain class attributes (absent by default), so every dump of a G5-free program is unchanged.
Param.mode = None          # "inout" for `inout name: [..]` (None = ordinary read parameter)
Param.mode_pos = None      # (line, col) of the `inout` token of the parameter
Call.old = None            # set by the checker on a resolved builtin `old(a)`: {"param": name, "index": position}


# ---------- G4 A0: modules, visibility, source identity ----------
# Same convention: plain class attributes, never dataclass fields, so every legacy dump is unchanged.
class ModDecl:
    """`mod name;` (parse level). line/col = the `mod` token."""
    def __init__(self, line, col, name):
        self.line, self.col, self.name = line, col, name
        self.file = None


# every node can carry the repo-relative file it came from (set only in explicit visibility mode)
for _cls in (Expr, Stmt, FieldDecl, VariantDecl, FieldInit, MatchArm, Refinement, Param, Function, TypeDecl,
             TypeParam):
    _cls.file = None
Function.pub = False        # `pub fn`
TypeDecl.pub = False        # `pub struct` / `pub enum`
Function.src_name = None    # explicit mode: the name as written; Function.name then holds the resolved identity
TypeDecl.src_name = None
Function.mod_path = None    # explicit mode: tuple of module components of the defining module (() = root)
TypeDecl.mod_path = None
Function.host_entry = False  # explicit mode: root `pub` nongeneric ordinary function
Program.items = None        # ordered items (Function / StructDecl / EnumDecl) of the whole program
Program.mods = ()           # parse level: the ModDecl list of this file
Program.has_pub = False     # parse level: this file has a valid top-level `pub`
Program.explicit = False    # explicit visibility mode (root has `mod` or top-level `pub`)
Program.modules = None      # explicit mode: [modules.Module] in root-first depth-first order
Program.entries = None      # explicit mode, after resolution: identities of the host entries
Program.main = None         # explicit mode, after resolution: identity of the root main (or None)


class PruvError(Exception):
    """Raise for any compile error. stage: parse|type|effect|verify|rustc.
    G4: `file` (repo-relative root-directory path with `/`) is set only for explicit-mode programs."""
    def __init__(self, stage, line, col, code, message, fix="", counterexample=None, file=None):
        super().__init__(message)
        self.stage = stage; self.line = line; self.col = col; self.code = code
        self.message = message; self.fix = fix; self.counterexample = counterexample; self.file = file

    def to_json(self):
        import json
        d = {"stage": self.stage, "line": self.line, "col": self.col, "code": self.code,
             "message": self.message, "fix": self.fix}
        if self.file is not None:
            d["file"] = self.file
        if self.counterexample is not None:
            d["counterexample"] = self.counterexample
        return json.dumps(d, ensure_ascii=False)
