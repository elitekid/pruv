//! Pruv AST (counterpart of vast.py): 15 expressions + 10 statements + 9 declarations/helpers = 34 nodes.
//! Type is a single name string. Integers are a sign plus a normalized decimal string (arbitrary length).
//! `ty` is always None at the parse stage (the check stage fills it in).

pub type Type = String;
pub type Ty = Option<String>;

// ---------- expressions ----------
#[derive(Debug, Clone, PartialEq)]
pub struct IntLit { pub line: i64, pub col: i64, pub value: String, pub ty: Ty }
#[derive(Debug, Clone, PartialEq)]
pub struct BoolLit { pub line: i64, pub col: i64, pub value: bool, pub ty: Ty }
#[derive(Debug, Clone, PartialEq)]
pub struct StrLit { pub line: i64, pub col: i64, pub value: Vec<u8>, pub ty: Ty }
#[derive(Debug, Clone, PartialEq)]
pub struct Var { pub line: i64, pub col: i64, pub name: String, pub ty: Ty }
#[derive(Debug, Clone, PartialEq)]
pub struct Unary { pub line: i64, pub col: i64, pub op: String, pub operand: Box<Expr>, pub ty: Ty }
#[derive(Debug, Clone, PartialEq)]
pub struct Binary { pub line: i64, pub col: i64, pub op: String, pub left: Box<Expr>, pub right: Box<Expr>, pub ty: Ty }
#[derive(Debug, Clone, PartialEq)]
pub struct Call { pub line: i64, pub col: i64, pub name: String, pub args: Vec<Expr>, pub ty: Ty }
#[derive(Debug, Clone, PartialEq)]
pub struct Index { pub line: i64, pub col: i64, pub array: Box<Expr>, pub index: Box<Expr>, pub ty: Ty }
#[derive(Debug, Clone, PartialEq)]
pub struct Ctor { pub line: i64, pub col: i64, pub name: String, pub arg: Option<Box<Expr>>, pub ty: Ty }
#[derive(Debug, Clone, PartialEq)]
pub struct Quant {
    pub line: i64, pub col: i64, pub kind: String, pub var: String,
    pub lo: Box<Expr>, pub hi: Box<Expr>, pub body: Box<Expr>, pub ty: Ty,
}
#[derive(Debug, Clone, PartialEq)]
pub struct StructLit { pub line: i64, pub col: i64, pub name: String, pub fields: Vec<FieldInit>, pub ty: Ty }
#[derive(Debug, Clone, PartialEq)]
pub struct EnumCtor { pub line: i64, pub col: i64, pub enum_name: String, pub variant: String, pub args: Vec<Expr>, pub ty: Ty }
#[derive(Debug, Clone, PartialEq)]
pub struct FieldAccess { pub line: i64, pub col: i64, pub base: Box<Expr>, pub field: String, pub ty: Ty }
#[derive(Debug, Clone, PartialEq)]
pub struct IsVariant { pub line: i64, pub col: i64, pub value: Box<Expr>, pub enum_name: String, pub variant: String, pub ty: Ty }
#[derive(Debug, Clone, PartialEq)]
pub struct VariantField {
    pub line: i64, pub col: i64, pub value: Box<Expr>, pub enum_name: String,
    pub variant: String, pub field: String, pub ty: Ty,
}

#[derive(Debug, Clone, PartialEq)]
pub enum Expr {
    IntLit(IntLit),
    BoolLit(BoolLit),
    StrLit(StrLit),
    Var(Var),
    Unary(Unary),
    Binary(Binary),
    Call(Call),
    Index(Index),
    Ctor(Ctor),
    Quant(Quant),
    StructLit(StructLit),
    EnumCtor(EnumCtor),
    FieldAccess(FieldAccess),
    IsVariant(IsVariant),
    VariantField(VariantField),
}

impl Expr {
    pub fn line(&self) -> i64 {
        match self {
            Expr::IntLit(x) => x.line,
            Expr::BoolLit(x) => x.line,
            Expr::StrLit(x) => x.line,
            Expr::Var(x) => x.line,
            Expr::Unary(x) => x.line,
            Expr::Binary(x) => x.line,
            Expr::Call(x) => x.line,
            Expr::Index(x) => x.line,
            Expr::Ctor(x) => x.line,
            Expr::Quant(x) => x.line,
            Expr::StructLit(x) => x.line,
            Expr::EnumCtor(x) => x.line,
            Expr::FieldAccess(x) => x.line,
            Expr::IsVariant(x) => x.line,
            Expr::VariantField(x) => x.line,
        }
    }
    pub fn col(&self) -> i64 {
        match self {
            Expr::IntLit(x) => x.col,
            Expr::BoolLit(x) => x.col,
            Expr::StrLit(x) => x.col,
            Expr::Var(x) => x.col,
            Expr::Unary(x) => x.col,
            Expr::Binary(x) => x.col,
            Expr::Call(x) => x.col,
            Expr::Index(x) => x.col,
            Expr::Ctor(x) => x.col,
            Expr::Quant(x) => x.col,
            Expr::StructLit(x) => x.col,
            Expr::EnumCtor(x) => x.col,
            Expr::FieldAccess(x) => x.col,
            Expr::IsVariant(x) => x.col,
            Expr::VariantField(x) => x.col,
        }
    }
}

// ---------- declarations/helpers ----------
#[derive(Debug, Clone, PartialEq)]
pub struct FieldDecl { pub line: i64, pub col: i64, pub name: String, pub ty: Type }
#[derive(Debug, Clone, PartialEq)]
pub struct VariantDecl { pub line: i64, pub col: i64, pub name: String, pub fields: Vec<FieldDecl> }
#[derive(Debug, Clone, PartialEq)]
pub struct StructDecl { pub line: i64, pub col: i64, pub name: String, pub fields: Vec<FieldDecl> }
#[derive(Debug, Clone, PartialEq)]
pub struct EnumDecl { pub line: i64, pub col: i64, pub name: String, pub variants: Vec<VariantDecl> }
#[derive(Debug, Clone, PartialEq)]
pub struct FieldInit { pub line: i64, pub col: i64, pub name: String, pub value: Expr }
#[derive(Debug, Clone, PartialEq)]
pub struct MatchArm {
    pub line: i64, pub col: i64, pub enum_name: Option<String>, pub ctor: String,
    pub binders: Vec<String>, pub body: Vec<Stmt>,
}
/// STAGE1 A refinement annotation (vast.Refinement). Position = the first token of the annotated type. Type stays the base type.
/// shape "scalar" | "array". lo/hi/maxlen are a sign plus a normalized decimal string (arbitrary length; range checks are in refine.rs).
#[derive(Debug, Clone, PartialEq)]
pub struct Refinement {
    pub line: i64, pub col: i64, pub shape: String, pub base: String,
    pub lo: Option<String>, pub hi: Option<String>, pub maxlen: Option<String>,
}
/// No line/col.
#[derive(Debug, Clone, PartialEq)]
pub struct Param { pub name: String, pub ty: Type, pub refine: Option<Refinement> }

#[derive(Debug, Clone, PartialEq)]
pub enum TypeDecl {
    Struct(StructDecl),
    Enum(EnumDecl),
}

// ---------- statements ----------
#[derive(Debug, Clone, PartialEq)]
pub struct Let {
    pub line: i64, pub col: i64, pub name: String, pub mutable: bool, pub ty: Type, pub value: Expr,
    pub refine: Option<Refinement>,
}
#[derive(Debug, Clone, PartialEq)]
pub struct Assign { pub line: i64, pub col: i64, pub name: String, pub value: Expr }
#[derive(Debug, Clone, PartialEq)]
/// elem_refine: (lo, hi, origin_what) — set by refine.rs only when storing into a refined array that has an element range.
pub struct IndexAssign {
    pub line: i64, pub col: i64, pub name: String, pub index: Expr, pub value: Expr,
    pub elem_refine: Option<(String, String, String)>,
}
#[derive(Debug, Clone, PartialEq)]
pub struct If { pub line: i64, pub col: i64, pub cond: Expr, pub then: Vec<Stmt>, pub els: Vec<Stmt> }
#[derive(Debug, Clone, PartialEq)]
pub struct While { pub line: i64, pub col: i64, pub cond: Expr, pub invariants: Vec<Expr>, pub decreases: Expr, pub body: Vec<Stmt> }
#[derive(Debug, Clone, PartialEq)]
pub struct Return { pub line: i64, pub col: i64, pub value: Option<Expr> }
#[derive(Debug, Clone, PartialEq)]
/// origin_code/origin_what: present only on asserts synthesized by refine.rs (verification error code and a description of the origin).
pub struct Assert {
    pub line: i64, pub col: i64, pub cond: Expr,
    pub origin_code: Option<String>, pub origin_what: Option<String>,
}
#[derive(Debug, Clone, PartialEq)]
pub struct ExprStmt { pub line: i64, pub col: i64, pub expr: Expr }
#[derive(Debug, Clone, PartialEq)]
pub struct FieldAssign { pub line: i64, pub col: i64, pub name: String, pub fields: Vec<String>, pub value: Expr }
#[derive(Debug, Clone, PartialEq)]
pub struct Match { pub line: i64, pub col: i64, pub scrutinee: Expr, pub arms: Vec<MatchArm> }

#[derive(Debug, Clone, PartialEq)]
pub enum Stmt {
    Let(Let),
    Assign(Assign),
    IndexAssign(IndexAssign),
    If(If),
    While(While),
    Return(Return),
    Assert(Assert),
    ExprStmt(ExprStmt),
    FieldAssign(FieldAssign),
    Match(Match),
}

// ---------- top level ----------
#[derive(Debug, Clone, PartialEq)]
pub struct Function {
    pub line: i64, pub col: i64, pub name: String, pub params: Vec<Param>, pub ret: Type,
    pub effects: Vec<String>, pub requires: Vec<Expr>, pub ensures: Vec<Expr>, pub body: Vec<Stmt>,
    pub ret_refine: Option<Refinement>,
}
/// No line/col.
#[derive(Debug, Clone, PartialEq, Default)]
/// refined: a marker that refine::expand has already run (Python `_refined`). Not emitted in the dump.
pub struct Program { pub functions: Vec<Function>, pub types: Vec<TypeDecl>, pub refined: bool }
