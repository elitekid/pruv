"""Vow AST. Shared interface between parser, checker, verifier and codegen.
Python 3.9: no match statements, no `X | Y` type unions at runtime.
Every node has `line` and `col` (1-based) of its first token.
Checker fills `Expr.ty` with a Type after type checking."""
from dataclasses import dataclass, field
from typing import List, Optional

# ---------- types ----------
@dataclass(frozen=True)
class Type:
    name: str  # "i64" | "bool" | "unit" | "array" | "option" | "result"

I64 = Type("i64"); BOOL = Type("bool"); UNIT = Type("unit")
ARRAY = Type("array"); OPTION = Type("option"); RESULT = Type("result")

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

@dataclass
class Assign(Stmt):
    name: str
    value: Expr

@dataclass
class IndexAssign(Stmt):
    name: str
    index: Expr
    value: Expr

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

@dataclass
class ExprStmt(Stmt):
    expr: Expr         # Call returning unit (incl. print)

@dataclass
class MatchArm:
    ctor: str          # "Some" | "None" | "Ok" | "Err"
    binder: Optional[str]
    body: List[Stmt]

@dataclass
class Match(Stmt):
    scrutinee: Expr
    arms: List[MatchArm]   # exactly 2, order as written

# ---------- top level ----------
@dataclass
class Param:
    name: str
    type: Type

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

@dataclass
class Program:
    functions: List[Function] = field(default_factory=list)

class VowError(Exception):
    """Raise for any compile error. stage: parse|type|effect|verify|rustc."""
    def __init__(self, stage, line, col, code, message, fix="", counterexample=None):
        super().__init__(message)
        self.stage = stage; self.line = line; self.col = col; self.code = code
        self.message = message; self.fix = fix; self.counterexample = counterexample

    def to_json(self):
        import json
        d = {"stage": self.stage, "line": self.line, "col": self.col, "code": self.code,
             "message": self.message, "fix": self.fix}
        if self.counterexample is not None:
            d["counterexample"] = self.counterexample
        return json.dumps(d, ensure_ascii=False)
