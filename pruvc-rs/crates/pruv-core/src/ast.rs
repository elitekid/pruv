//! Pruv AST (counterpart of vast.py): 15 expressions + 10 statements + 9 declarations/helpers = 34 nodes.
//! Type is a single name string. Integers are a sign plus a normalized decimal string (arbitrary length).
//! `ty` is always None at the parse stage (the check stage fills it in).

pub type Type = String;
pub type Ty = Option<String>;

// ---------- G3: generics ----------
// Names are always plain. The G3 extras are real optional fields (Python keeps them as class attributes, vast.py):
//  * `tparams` on Function / StructDecl / EnumDecl (empty = not generic), filled by the parser;
//  * `targs` on Call / StructLit / EnumCtor / Ctor (None = no type application written), filled by the parser;
//  * `inst` on the same four nodes: the instantiation the checker recorded (declaration identity, type arguments, substitution);
//  * `enum_ty` on IsVariant / VariantField: the checked type of the scrutinee, filled by the checker.
// A structured type inside `ty` / `type` / `ret` strings is still a `GType` key (gtype.rs `to_key`/`try_from_key`);
// a legacy type is its plain name, as before.
use crate::gtype::GType;
use std::collections::HashMap;

/// One entry of a type-parameter list (`T` or `T: Element`); `bound` is the bound's spelling.
#[derive(Debug, Clone, PartialEq)]
pub struct TParam {
    pub line: i64,
    pub col: i64,
    pub name: String,
    pub bound: Option<String>,
}

/// The instantiation recorded by the checker on a generic Call / StructLit / EnumCtor / Ctor (Python `node.inst`).
/// `decl`: the declaration identity (`fn:f`, `type:S`, `builtin:Some`); `subst`: (owner, index, replacement) ordered by index.
#[derive(Debug, Clone, PartialEq)]
pub struct Inst {
    pub decl: String,
    pub args: Vec<GType>,
    pub subst: Vec<(String, usize, GType)>,
    /// G6 A2: set only by mono on a catalog call: the concrete, NOT lowered type arguments (`args` are then the lowered
    /// ones); None as the checker leaves it.
    pub src_args: Option<Vec<GType>>,
}

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
pub struct Call {
    pub line: i64, pub col: i64, pub name: String, pub args: Vec<Expr>, pub ty: Ty,
    pub targs: Option<Vec<GType>>, pub inst: Option<Inst>,
    /// G5 A0: set by the checker on a resolved builtin `old(a)`: (parameter name, parameter position).
    pub old: Option<(String, usize)>,
}
#[derive(Debug, Clone, PartialEq)]
pub struct Index { pub line: i64, pub col: i64, pub array: Box<Expr>, pub index: Box<Expr>, pub ty: Ty }
#[derive(Debug, Clone, PartialEq)]
pub struct Ctor {
    pub line: i64, pub col: i64, pub name: String, pub arg: Option<Box<Expr>>, pub ty: Ty,
    pub targs: Option<Vec<GType>>, pub inst: Option<Inst>,
}
#[derive(Debug, Clone, PartialEq)]
pub struct Quant {
    pub line: i64, pub col: i64, pub kind: String, pub var: String,
    pub lo: Box<Expr>, pub hi: Box<Expr>, pub body: Box<Expr>, pub ty: Ty,
}
#[derive(Debug, Clone, PartialEq)]
pub struct StructLit {
    pub line: i64, pub col: i64, pub name: String, pub fields: Vec<FieldInit>, pub ty: Ty,
    pub targs: Option<Vec<GType>>, pub inst: Option<Inst>,
}
#[derive(Debug, Clone, PartialEq)]
pub struct EnumCtor {
    pub line: i64, pub col: i64, pub enum_name: String, pub variant: String, pub args: Vec<Expr>, pub ty: Ty,
    pub targs: Option<Vec<GType>>, pub inst: Option<Inst>,
}
#[derive(Debug, Clone, PartialEq)]
pub struct FieldAccess { pub line: i64, pub col: i64, pub base: Box<Expr>, pub field: String, pub ty: Ty }
#[derive(Debug, Clone, PartialEq)]
pub struct IsVariant {
    pub line: i64, pub col: i64, pub value: Box<Expr>, pub enum_name: String, pub variant: String, pub ty: Ty,
    pub enum_ty: Option<GType>,
}
#[derive(Debug, Clone, PartialEq)]
pub struct VariantField {
    pub line: i64, pub col: i64, pub value: Box<Expr>, pub enum_name: String,
    pub variant: String, pub field: String, pub ty: Ty, pub enum_ty: Option<GType>,
}

/// G6 A0: `move name` (consumes an owned collection binding). Counterpart of vast.Move.
#[derive(Debug, Clone, PartialEq)]
pub struct Move { pub line: i64, pub col: i64, pub name: String, pub ty: Ty }

/// G5 A0: the call-argument marker `inout <operand>`; line/col = the `inout` token. The operand is kept as written (the
/// checker requires a plain Var naming a mutable local array or an inout parameter of the caller). Counterpart of vast.InoutArg.
#[derive(Debug, Clone, PartialEq)]
/// `post_refine`: G5 A1, set by refine.rs (Python `a.post_refine`): the synthesized assertions of the refined local this
/// argument names, proved right after the call transition. Not emitted in the dump; empty everywhere else (also in mono copies).
pub struct InoutArg { pub line: i64, pub col: i64, pub expr: Box<Expr>, pub ty: Ty, pub post_refine: Vec<Assert> }

#[derive(Debug, Clone, PartialEq)]
pub enum Expr {
    InoutArg(InoutArg),
    Move(Move),
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
            Expr::InoutArg(x) => x.line,
            Expr::Move(x) => x.line,
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
            Expr::InoutArg(x) => x.col,
            Expr::Move(x) => x.col,
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
pub struct StructDecl { pub line: i64, pub col: i64, pub name: String, pub fields: Vec<FieldDecl>, pub tparams: Vec<TParam> }
#[derive(Debug, Clone, PartialEq)]
pub struct EnumDecl { pub line: i64, pub col: i64, pub name: String, pub variants: Vec<VariantDecl>, pub tparams: Vec<TParam> }
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
/// No line/col. `take`: G6 A0 `take name: Type` (consuming collection parameter).
/// `mode_pos`: G5 A0 `inout name: [..]` -> Some((line, col)) of the `inout` token (Python `Param.mode == "inout"` + `mode_pos`).
#[derive(Debug, Clone, PartialEq)]
pub struct Param {
    pub name: String, pub ty: Type, pub refine: Option<Refinement>, pub take: bool,
    pub mode_pos: Option<(i64, i64)>,
}

/// G6 A0: the declaration data of a `trusted rust fn` (Python `Function.foreign`): the Rust path and the
/// line/col of the path string token. The body of such a function is empty.
#[derive(Debug, Clone, PartialEq)]
pub struct ForeignInfo { pub path: String, pub line: i64, pub col: i64 }

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
    pub ret_refine: Option<Refinement>, pub tparams: Vec<TParam>,
    /// G6 A0: Some for a `trusted rust fn`.
    pub foreign: Option<ForeignInfo>,
    /// G9 A0: the `decreases Expr` clause of the function header (None = absent).
    pub decreases: Option<Expr>,
}

/// G9 A0: checker metadata recorded on the program and the type table, only when a G9 feature is present
/// (Python `Program.g9` / `TypeTable.g9`, a dict with these four keys).
#[derive(Debug, Clone, PartialEq, Default)]
pub struct G9Meta {
    /// recursive type SCCs (names in declaration order), SCC-number order
    pub type_sccs: Vec<Vec<String>>,
    /// "Decl.field" / "Enum::Variant.field" of every intra-SCC (boxed) field
    pub boxed: Vec<String>,
    /// names of extended declarations, in declaration order
    pub extended: Vec<String>,
    /// recursive function SCCs (names in function order)
    pub fn_sccs: Vec<Vec<String>>,
}

// ---------- G4 A0: modules and visibility (parse level) ----------
// `Program` is unchanged: the explicit-mode data (modules, `pub`, source names, host entries) lives in modules.rs `G4`,
// next to the program the module loader returns. Node positions carry the source file in their line number (diagnostic.rs).

/// `mod name;` (vast.ModDecl). line/col = the `mod` token.
#[derive(Debug, Clone, PartialEq)]
pub struct ModDecl { pub line: i64, pub col: i64, pub name: String }

/// A top-level item of one file, in source order: an index into `Program.functions` / `Program.types` (Python `Program.items`).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Item { Fn(usize), Ty(usize) }

/// G4 A2: the explicit-mode attributes of one concrete function (Python `pub` / `host_entry` / `disp` set by mono).
#[derive(Debug, Clone, PartialEq)]
pub struct FnMark {
    pub is_pub: bool,
    pub host_entry: bool,
    /// the source-qualified identity (panic text, manifests)
    pub disp: String,
}

/// G4 A2: explicit-mode data of a CONCRETE (specialized) program (Python `Program.explicit` plus the attributes mono puts on
/// the concrete declarations). Only mono.rs builds it; `None` on every other program.
#[derive(Debug, Clone, PartialEq, Default)]
pub struct Explicit {
    /// parallel to `Program.functions`
    pub fns: Vec<FnMark>,
    /// `pub` of every declaration, parallel to `Program.types`
    pub type_pub: Vec<bool>,
    /// Rust name (stem) of a nominal type -> the identity it was declared with (Python `src_name` of the nodes)
    pub tdisp: HashMap<String, String>,
}

/// No line/col.
#[derive(Debug, Clone, PartialEq, Default)]
/// refined: a marker that refine::expand has already run (Python `_refined`). Not emitted in the dump.
/// g9: G9 A0 checker metadata (Python `Program.g9`), None unless a G9 feature is present. Not emitted in the dump.
/// explicit: G4 A2, Some only on the concrete program of an explicit visibility program (built by mono.rs).
/// uses_inout: G5 A0, set by the checker (Python `Program.uses_inout`); None = not checked yet. Not emitted in the dump.
pub struct Program {
    pub functions: Vec<Function>,
    pub types: Vec<TypeDecl>,
    pub refined: bool,
    pub g9: Option<G9Meta>,
    pub explicit: Option<Explicit>,
    pub uses_inout: Option<bool>,
}
