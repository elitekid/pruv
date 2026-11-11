//! G3 A3: the shared specialization plan (counterpart of pruvc/mono.py, G3_SPEC 5.1, 5.2).
//!
//! ```text
//! let plan = specialize(&prog)?;   // prog: a fully checked Program; never mutated
//! ```
//!
//! `plan.program` is a NEW, fully concrete Program in which
//!  * every generic function specialization is an ordinary Function named by its stem (`pruv_g3_f_...`);
//!    code generation treats the reserved prefix as "private" (the Python AST has a `private` flag, this AST none),
//!  * every generic nominal application is an ordinary StructDecl / EnumDecl named by its stem (`pruv_g3_t_...`),
//!  * every type key is concrete: a nominal application is its stem, Option<X> / Result<X> keep their argument unless
//!    X is i64 (legacy `option` / `result`), arrays are the legacy `array` / `array_u8` / `array_bool`.
//!
//! Roots are all non-generic functions. Concrete generic calls, struct literals and enum constructors (recorded in
//! `.inst` by the checker) are substituted and followed with a work list. `ensures` is dropped; loop invariants,
//! `decreases` and `requires` are copied (and followed) exactly like Python `cp`, in the same field order, so the
//! first limit trigger (and the position recorded for it) is the same.
//!
//! Limits: 4096 function specializations, 4096 nominal applications, instantiated type depth 128, 65536 type nodes
//! -> `MonoError::Limit` (a PruvError codegen/specialization_limit with Python's exact text); no plan is produced.
//!
//! Python shares sub-types between substitutions, so `measure` there is linear. Here a type is measured
//! "virtually" (template + substitution, without building the substituted type); the type is built only after
//! it passed the limits.

use crate::ast::*;
use crate::diagnostic::PruvError;
use crate::foreign::is_catalog;
use crate::gtype::{
    bind_args, decl_owner, encode, fn_owner, format_type, is_g3_key, mk_array, mk_option, mk_result, spec_fn_stem,
    spec_type_stem, substitute, GType, Mapping, ParamId,
};
use crate::typeinfo::first_g3_use;
use std::collections::{HashMap, VecDeque};

pub const MAX_FN_SPECS: usize = 4096;
pub const MAX_TYPE_APPS: usize = 4096;
pub const MAX_DEPTH: u64 = 128;
pub const MAX_TYPE_NODES: u64 = 1 << 16;

/// Failure of `specialize`: a limit diagnostic (exit 1) or an internal defect (exit 3).
#[derive(Debug, Clone)]
pub enum MonoError {
    Limit(PruvError),
    Internal(String),
}

type MR<T> = Result<T, MonoError>;

/// The programs that use G3 anywhere.
pub fn is_generic_program(prog: &Program) -> bool {
    first_g3_use(prog).is_some()
}

/// One specialization of a generic function (the concrete Function is taken out when the plan is assembled).
struct FnSpec {
    name: String,
    args: Vec<GType>,
    stem: String,
    encs: Vec<String>,
    func: Option<Function>,
}

/// One application of a generic struct/enum.
struct TySpec {
    name: String,
    args: Vec<GType>,
    stem: String,
    encs: Vec<String>,
    decl: Option<TypeDecl>,
}

/// Result of `specialize`: the concrete program, the generic specialization stems in output order and the roots.
#[derive(Debug, Clone)]
pub struct SpecPlan {
    pub program: Program,
    pub fn_stems: Vec<String>,
    pub type_stems: Vec<String>,
    /// non-generic function names in declaration order
    pub roots: Vec<String>,
}

enum Item {
    Fn(usize),
    Ty(usize),
}

/// (depth, tree node count) of a (virtually substituted) type; `kind` tells whether it is exactly i64 (1), bool (2)
/// or u8 (3) so `[X]` / `Option<X>` / `Result<X>` normalize like gtype::substitute; `args` whether it has arguments.
#[derive(Clone, Copy)]
struct Meas {
    depth: u64,
    nodes: u64,
    kind: u8,
    args: bool,
}

const LEAF: Meas = Meas { depth: 1, nodes: 1, kind: 0, args: false };

fn meas_with(t: &GType, pm: &HashMap<ParamId, Meas>) -> Meas {
    if let Some(o) = &t.owner {
        return pm.get(&(o.clone(), t.index)).copied().unwrap_or(LEAF);
    }
    if t.args.is_empty() {
        let kind = match t.name.as_str() {
            "i64" => 1,
            "bool" => 2,
            "u8" => 3,
            _ => 0,
        };
        // the legacy Option<i64> / Result<i64> constants stand for a one-argument application (depth 2)
        if t.name == "option" || t.name == "result" {
            return Meas { depth: 2, nodes: 2, kind: 0, args: false };
        }
        return Meas { depth: 1, nodes: 1, kind, args: false };
    }
    let ms: Vec<Meas> = t.args.iter().map(|a| meas_with(a, pm)).collect();
    let depth = 1 + ms.iter().map(|m| m.depth).max().unwrap_or(0);
    let nodes = ms.iter().fold(1u64, |s, m| s.saturating_add(m.nodes));
    if ms.len() == 1 {
        let k = ms[0].kind;
        if t.name == "array" && (1..=3).contains(&k) {
            return LEAF; // mk_array normalizes to the legacy array
        }
        if (t.name == "option" || t.name == "result") && k == 1 {
            return Meas { depth: 2, nodes: 2, kind: 0, args: false }; // legacy Option<i64> / Result<i64>
        }
    }
    Meas { depth, nodes, kind: 0, args: true }
}

fn put(parts: &mut String, size: &mut usize, limit: usize, s: &str) -> Result<(), ()> {
    parts.push_str(s);
    *size += s.chars().count();
    if *size > limit {
        Err(())
    } else {
        Ok(())
    }
}

struct Mono<'a> {
    prog: &'a Program,
    tindex: HashMap<String, usize>,
    findex: HashMap<String, usize>,
    fns: Vec<FnSpec>,
    fn_idx: HashMap<String, usize>,
    types: Vec<TySpec>,
    ty_idx: HashMap<String, usize>,
    queue: VecDeque<Item>,
    map: Mapping,
    pmeas: HashMap<ParamId, Meas>,
    pos: (i64, i64),
}

impl<'a> Mono<'a> {
    fn new(prog: &'a Program) -> Mono<'a> {
        let mut tindex = HashMap::new();
        for (i, d) in prog.types.iter().enumerate() {
            tindex.entry(d.name().to_string()).or_insert(i); // first declaration wins
        }
        let mut findex = HashMap::new();
        for (i, f) in prog.functions.iter().enumerate() {
            findex.entry(f.name.clone()).or_insert(i);
        }
        Mono {
            prog,
            tindex,
            findex,
            fns: Vec::new(),
            fn_idx: HashMap::new(),
            types: Vec::new(),
            ty_idx: HashMap::new(),
            queue: VecDeque::new(),
            map: Mapping::new(),
            pmeas: HashMap::new(),
            pos: (1, 1),
        }
    }

    fn set_map(&mut self, m: Mapping) {
        let empty: HashMap<ParamId, Meas> = HashMap::new();
        let mut pm = HashMap::new();
        for (k, v) in &m {
            pm.insert(k.clone(), meas_with(v, &empty));
        }
        self.map = m;
        self.pmeas = pm;
    }

    fn meas(&self, t: &GType) -> Meas {
        meas_with(t, &self.pmeas)
    }

    // ---------- errors ----------
    fn limit(&self, msg: String) -> MonoError {
        MonoError::Limit(PruvError::new(
            "codegen",
            self.pos.0,
            self.pos.1,
            "specialization_limit",
            msg,
            "reduce the number or the nesting depth of generic instantiations",
        ))
    }

    /// format_type, cut off after about `limit` characters, of `t` under the current substitution
    fn short_type(&self, t: &GType, limit: usize) -> String {
        let mut parts = String::new();
        let mut size = 0usize;
        let r = self.short_go(t, limit, &mut parts, &mut size);
        if r.is_err() {
            parts.push_str("...");
        }
        parts
    }

    fn short_go(&self, x: &GType, limit: usize, parts: &mut String, size: &mut usize) -> Result<(), ()> {
        if let Some(o) = &x.owner {
            return match self.map.get(&(o.clone(), x.index)) {
                Some(r) => self.short_go(r, limit, parts, size),
                None => put(parts, size, limit, &format_type(x)),
            };
        }
        if x.args.is_empty() {
            return put(parts, size, limit, &format_type(x));
        }
        if x.args.len() == 1 {
            let k = self.meas(&x.args[0]).kind;
            let leaf = match (x.name.as_str(), k) {
                ("option", 1) => Some("Option<i64>"),
                ("result", 1) => Some("Result<i64>"),
                ("array", 1) => Some("[i64]"),
                ("array", 2) => Some("[bool]"),
                ("array", 3) => Some("[u8]"),
                _ => None,
            };
            if let Some(s) = leaf {
                return put(parts, size, limit, s);
            }
        }
        if x.name == "array" {
            put(parts, size, limit, "[")?;
            self.short_go(&x.args[0], limit, parts, size)?;
            return put(parts, size, limit, "]");
        }
        let shown = match x.name.as_str() {
            "option" => "Option",
            "result" => "Result",
            other => other,
        };
        put(parts, size, limit, &format!("{}<", shown))?;
        for (i, a) in x.args.iter().enumerate() {
            if i > 0 {
                put(parts, size, limit, ", ")?;
            }
            self.short_go(a, limit, parts, size)?;
        }
        put(parts, size, limit, ">")
    }

    /// depth and size limits of one (virtual) type, checked before it is built, encoded or lowered
    fn check_shape(&self, m: Meas, what: &str, shown: &GType) -> MR<()> {
        if m.depth > MAX_DEPTH {
            return Err(self.limit(format!(
                "instantiated type nesting depth {} exceeds the limit of {} ({}: {})",
                m.depth,
                MAX_DEPTH,
                what,
                self.short_type(shown, 64)
            )));
        }
        if m.nodes > MAX_TYPE_NODES {
            return Err(self.limit(format!(
                "instantiated type has more than {} nodes ({}: {})",
                MAX_TYPE_NODES,
                what,
                self.short_type(shown, 64)
            )));
        }
        Ok(())
    }

    // ---------- types ----------
    fn ty_key(&mut self, k: &str) -> MR<String> {
        if !is_g3_key(k) {
            return Ok(k.to_string()); // a legacy name: no arguments, no parameter
        }
        let g = GType::try_from_key(k).map_err(MonoError::Internal)?;
        Ok(self.ty_g(&g)?.to_key())
    }

    fn ty_opt(&mut self, k: &Option<String>) -> MR<Option<String>> {
        match k {
            None => Ok(None),
            Some(s) => Ok(Some(self.ty_key(s)?)),
        }
    }

    /// concrete, lowered form of a declared/checked type in the current substitution
    fn ty_g(&mut self, t: &GType) -> MR<GType> {
        if t.owner.is_none() && t.args.is_empty() {
            return Ok(t.clone());
        }
        if let Some(o) = &t.owner {
            if !self.map.contains_key(&(o.clone(), t.index)) {
                return Err(MonoError::Internal(format!("specialization: unbound type parameter {}", t.name)));
            }
        }
        let m = self.meas(t);
        if !m.args {
            return Ok(substitute(t, &self.map));
        }
        self.check_shape(m, "type", t)?;
        let c = substitute(t, &self.map);
        self.lower(&c)
    }

    fn lower(&mut self, c: &GType) -> MR<GType> {
        if c.owner.is_some() {
            return Err(MonoError::Internal(format!("specialization: unbound type parameter {}", c.name)));
        }
        if c.args.is_empty() {
            return Ok(c.clone());
        }
        match c.name.as_str() {
            "array" => Ok(mk_array(self.lower(&c.args[0])?)),
            "option" => Ok(mk_option(self.lower(&c.args[0])?)),
            "result" => Ok(mk_result(self.lower(&c.args[0])?)),
            // G6: Vec<T> / HashMap<K, V> keep their name, the arguments are lowered
            "vec" | "hashmap" => {
                let mut args = Vec::with_capacity(c.args.len());
                for a in &c.args {
                    args.push(self.lower(a)?);
                }
                Ok(GType::new(&c.name, args))
            }
            _ => {
                let stem = self.request_type(&c.name, &c.args)?;
                Ok(GType::new(&stem, Vec::new()))
            }
        }
    }

    /// register the application name<args> (concrete args, already within the limits); returns its stem
    fn request_type(&mut self, name: &str, args: &[GType]) -> MR<String> {
        let stem = spec_type_stem(name, args).map_err(MonoError::Internal)?;
        if self.ty_idx.contains_key(&stem) {
            return Ok(stem);
        }
        if self.types.len() >= MAX_TYPE_APPS {
            let shown: Vec<String> = args.iter().map(|a| self.short_type(a, 32)).collect();
            return Err(self.limit(format!(
                "more than {} distinct generic type applications (trigger: {}<{}>)",
                MAX_TYPE_APPS,
                name,
                shown.join(", ")
            )));
        }
        let mut encs = Vec::new();
        for a in args {
            encs.push(encode(a).map_err(MonoError::Internal)?);
        }
        let i = self.types.len();
        self.types.push(TySpec { name: name.to_string(), args: args.to_vec(), stem: stem.clone(), encs, decl: None });
        self.ty_idx.insert(stem.clone(), i);
        self.queue.push_back(Item::Ty(i));
        Ok(stem)
    }

    /// the application written at a struct literal / enum constructor (templates: `inst.args`)
    fn request_type_inst(&mut self, name: &str, targs: &[GType]) -> MR<String> {
        let whole = GType::new(name, targs.to_vec());
        // an application is never normalized away (a nominal name): depth/size of Type(name, args)
        let m = if targs.is_empty() { LEAF } else { self.app_meas(targs) };
        self.check_shape(m, &format!("application of {}", name), &whole)?;
        let args: Vec<GType> = targs.iter().map(|a| substitute(a, &self.map)).collect();
        self.request_type(name, &args)
    }

    fn app_meas(&self, targs: &[GType]) -> Meas {
        let ms: Vec<Meas> = targs.iter().map(|a| self.meas(a)).collect();
        let depth = 1 + ms.iter().map(|m| m.depth).max().unwrap_or(0);
        let nodes = ms.iter().fold(1u64, |s, m| s.saturating_add(m.nodes));
        Meas { depth, nodes, kind: 0, args: true }
    }

    fn request_fn_inst(&mut self, name: &str, targs: &[GType]) -> MR<String> {
        for a in targs {
            let m = self.meas(a);
            self.check_shape(m, &format!("type argument of function {}", name), a)?;
        }
        let args: Vec<GType> = targs.iter().map(|a| substitute(a, &self.map)).collect();
        let stem = spec_fn_stem(name, &args).map_err(MonoError::Internal)?;
        if self.fn_idx.contains_key(&stem) {
            return Ok(stem);
        }
        if self.fns.len() >= MAX_FN_SPECS {
            let shown: Vec<String> = args.iter().map(|a| self.short_type(a, 32)).collect();
            return Err(self.limit(format!(
                "more than {} distinct generic function specializations (trigger: {}<{}>)",
                MAX_FN_SPECS,
                name,
                shown.join(", ")
            )));
        }
        let mut encs = Vec::new();
        for a in &args {
            encs.push(encode(a).map_err(MonoError::Internal)?);
        }
        let i = self.fns.len();
        self.fns.push(FnSpec { name: name.to_string(), args, stem: stem.clone(), encs, func: None });
        self.fn_idx.insert(stem.clone(), i);
        self.queue.push_back(Item::Fn(i));
        Ok(stem)
    }

    // ---------- copying with substitution (field order = Python dataclass field order) ----------
    fn cp_es(&mut self, es: &[Expr]) -> MR<Vec<Expr>> {
        let mut out = Vec::with_capacity(es.len());
        for e in es {
            out.push(self.cp_e(e)?);
        }
        Ok(out)
    }

    fn bx(&mut self, e: &Expr) -> MR<Box<Expr>> {
        Ok(Box::new(self.cp_e(e)?))
    }

    fn cp_e(&mut self, e: &Expr) -> MR<Expr> {
        Ok(match e {
            Expr::IntLit(x) => {
                Expr::IntLit(IntLit { line: x.line, col: x.col, value: x.value.clone(), ty: self.ty_opt(&x.ty)? })
            }
            Expr::BoolLit(x) => Expr::BoolLit(BoolLit { line: x.line, col: x.col, value: x.value, ty: self.ty_opt(&x.ty)? }),
            Expr::StrLit(x) => {
                Expr::StrLit(StrLit { line: x.line, col: x.col, value: x.value.clone(), ty: self.ty_opt(&x.ty)? })
            }
            Expr::Var(x) => Expr::Var(Var { line: x.line, col: x.col, name: x.name.clone(), ty: self.ty_opt(&x.ty)? }),
            Expr::Move(x) => Expr::Move(Move { line: x.line, col: x.col, name: x.name.clone(), ty: self.ty_opt(&x.ty)? }),
            Expr::Unary(x) => {
                let operand = self.bx(&x.operand)?;
                Expr::Unary(Unary { line: x.line, col: x.col, op: x.op.clone(), operand, ty: self.ty_opt(&x.ty)? })
            }
            Expr::Binary(x) => {
                let left = self.bx(&x.left)?;
                let right = self.bx(&x.right)?;
                Expr::Binary(Binary { line: x.line, col: x.col, op: x.op.clone(), left, right, ty: self.ty_opt(&x.ty)? })
            }
            Expr::Call(x) => {
                let args = self.cp_es(&x.args)?;
                let ty = self.ty_opt(&x.ty)?;
                let mut name = x.name.clone();
                let mut new_inst: Option<Inst> = None;
                if is_catalog(&x.name) {
                    // G6: the name stays; `args` = lowered concrete type arguments, `src_args` = concrete but not
                    // lowered (source-level spelling and the structural encoding of helper names)
                    if let Some(inst) = &x.inst {
                        self.pos = (x.line, x.col);
                        for a in &inst.args {
                            let m = self.meas(a);
                            self.check_shape(m, &format!("type argument of function {}", x.name), a)?;
                        }
                        let src: Vec<GType> = inst.args.iter().map(|a| substitute(a, &self.map)).collect();
                        let mut low: Vec<GType> = Vec::with_capacity(inst.args.len());
                        for a in &inst.args {
                            low.push(self.ty_g(a)?);
                        }
                        new_inst = Some(Inst { decl: inst.decl.clone(), args: low, subst: Vec::new(), src_args: Some(src) });
                    }
                } else if let Some(inst) = &x.inst {
                    self.pos = (x.line, x.col);
                    name = self.request_fn_inst(&x.name, &inst.args)?;
                }
                Expr::Call(Call { line: x.line, col: x.col, name, args, ty, targs: None, inst: new_inst })
            }
            Expr::Index(x) => {
                let array = self.bx(&x.array)?;
                let index = self.bx(&x.index)?;
                Expr::Index(Index { line: x.line, col: x.col, array, index, ty: self.ty_opt(&x.ty)? })
            }
            Expr::Ctor(x) => {
                let arg = match &x.arg {
                    Some(a) => Some(self.bx(a)?),
                    None => None,
                };
                Expr::Ctor(Ctor {
                    line: x.line,
                    col: x.col,
                    name: x.name.clone(),
                    arg,
                    ty: self.ty_opt(&x.ty)?,
                    targs: None,
                    inst: None,
                })
            }
            Expr::Quant(x) => {
                let lo = self.bx(&x.lo)?;
                let hi = self.bx(&x.hi)?;
                let body = self.bx(&x.body)?;
                Expr::Quant(Quant {
                    line: x.line,
                    col: x.col,
                    kind: x.kind.clone(),
                    var: x.var.clone(),
                    lo,
                    hi,
                    body,
                    ty: self.ty_opt(&x.ty)?,
                })
            }
            Expr::StructLit(x) => {
                let mut fields = Vec::with_capacity(x.fields.len());
                for f in &x.fields {
                    fields.push(FieldInit { line: f.line, col: f.col, name: f.name.clone(), value: self.cp_e(&f.value)? });
                }
                let ty = self.ty_opt(&x.ty)?;
                let mut name = x.name.clone();
                if let Some(inst) = &x.inst {
                    self.pos = (x.line, x.col);
                    name = self.request_type_inst(&x.name, &inst.args)?;
                }
                Expr::StructLit(StructLit { line: x.line, col: x.col, name, fields, ty, targs: None, inst: None })
            }
            Expr::EnumCtor(x) => {
                let args = self.cp_es(&x.args)?;
                let ty = self.ty_opt(&x.ty)?;
                let mut enum_name = x.enum_name.clone();
                if let Some(inst) = &x.inst {
                    self.pos = (x.line, x.col);
                    enum_name = self.request_type_inst(&x.enum_name, &inst.args)?;
                }
                Expr::EnumCtor(EnumCtor {
                    line: x.line,
                    col: x.col,
                    enum_name,
                    variant: x.variant.clone(),
                    args,
                    ty,
                    targs: None,
                    inst: None,
                })
            }
            Expr::FieldAccess(x) => {
                let base = self.bx(&x.base)?;
                Expr::FieldAccess(FieldAccess {
                    line: x.line,
                    col: x.col,
                    base,
                    field: x.field.clone(),
                    ty: self.ty_opt(&x.ty)?,
                })
            }
            Expr::IsVariant(x) => {
                let value = self.bx(&x.value)?;
                let ty = self.ty_opt(&x.ty)?;
                let mut enum_name = x.enum_name.clone();
                if let Some(et) = &x.enum_ty {
                    enum_name = self.ty_g(et)?.name;
                }
                Expr::IsVariant(IsVariant {
                    line: x.line,
                    col: x.col,
                    value,
                    enum_name,
                    variant: x.variant.clone(),
                    ty,
                    enum_ty: None,
                })
            }
            Expr::VariantField(x) => {
                let value = self.bx(&x.value)?;
                let ty = self.ty_opt(&x.ty)?;
                let mut enum_name = x.enum_name.clone();
                if let Some(et) = &x.enum_ty {
                    enum_name = self.ty_g(et)?.name;
                }
                Expr::VariantField(VariantField {
                    line: x.line,
                    col: x.col,
                    value,
                    enum_name,
                    variant: x.variant.clone(),
                    field: x.field.clone(),
                    ty,
                    enum_ty: None,
                })
            }
        })
    }

    fn cp_stmts(&mut self, ss: &[Stmt]) -> MR<Vec<Stmt>> {
        let mut out = Vec::with_capacity(ss.len());
        for s in ss {
            out.push(self.cp_s(s)?);
        }
        Ok(out)
    }

    fn cp_s(&mut self, s: &Stmt) -> MR<Stmt> {
        Ok(match s {
            Stmt::Let(x) => {
                let ty = self.ty_key(&x.ty)?;
                let value = self.cp_e(&x.value)?;
                Stmt::Let(Let {
                    line: x.line,
                    col: x.col,
                    name: x.name.clone(),
                    mutable: x.mutable,
                    ty,
                    value,
                    refine: x.refine.clone(),
                })
            }
            Stmt::Assign(x) => {
                Stmt::Assign(Assign { line: x.line, col: x.col, name: x.name.clone(), value: self.cp_e(&x.value)? })
            }
            Stmt::IndexAssign(x) => {
                let index = self.cp_e(&x.index)?;
                let value = self.cp_e(&x.value)?;
                Stmt::IndexAssign(IndexAssign {
                    line: x.line,
                    col: x.col,
                    name: x.name.clone(),
                    index,
                    value,
                    elem_refine: x.elem_refine.clone(),
                })
            }
            Stmt::If(x) => {
                let cond = self.cp_e(&x.cond)?;
                let then = self.cp_stmts(&x.then)?;
                let els = self.cp_stmts(&x.els)?;
                Stmt::If(If { line: x.line, col: x.col, cond, then, els })
            }
            Stmt::While(x) => {
                let cond = self.cp_e(&x.cond)?;
                let invariants = self.cp_es(&x.invariants)?;
                let decreases = self.cp_e(&x.decreases)?;
                let body = self.cp_stmts(&x.body)?;
                Stmt::While(While { line: x.line, col: x.col, cond, invariants, decreases, body })
            }
            Stmt::Return(x) => {
                let value = match &x.value {
                    Some(v) => Some(self.cp_e(v)?),
                    None => None,
                };
                Stmt::Return(Return { line: x.line, col: x.col, value })
            }
            Stmt::Assert(x) => Stmt::Assert(Assert {
                line: x.line,
                col: x.col,
                cond: self.cp_e(&x.cond)?,
                origin_code: x.origin_code.clone(),
                origin_what: x.origin_what.clone(),
            }),
            Stmt::ExprStmt(x) => Stmt::ExprStmt(ExprStmt { line: x.line, col: x.col, expr: self.cp_e(&x.expr)? }),
            Stmt::FieldAssign(x) => Stmt::FieldAssign(FieldAssign {
                line: x.line,
                col: x.col,
                name: x.name.clone(),
                fields: x.fields.clone(),
                value: self.cp_e(&x.value)?,
            }),
            Stmt::Match(x) => {
                let scrutinee = self.cp_e(&x.scrutinee)?;
                let mut arms = Vec::with_capacity(x.arms.len());
                for a in &x.arms {
                    arms.push(MatchArm {
                        line: a.line,
                        col: a.col,
                        enum_name: a.enum_name.clone(),
                        ctor: a.ctor.clone(),
                        binders: a.binders.clone(),
                        body: self.cp_stmts(&a.body)?,
                    });
                }
                // the arms name the scrutinee's (lowered) enum
                if let Some(sty) = expr_ty_of(&scrutinee) {
                    let name = sty.split('<').next().unwrap_or("").to_string();
                    for a in arms.iter_mut() {
                        if a.enum_name.is_some() {
                            a.enum_name = Some(name.clone());
                        }
                    }
                }
                Stmt::Match(Match { line: x.line, col: x.col, scrutinee, arms })
            }
        })
    }

    fn function(&mut self, f: &Function, name: &str, mapping: Mapping) -> MR<Function> {
        self.set_map(mapping);
        self.pos = (f.line, f.col);
        let mut params = Vec::with_capacity(f.params.len());
        for p in &f.params {
            params.push(Param { name: p.name.clone(), ty: self.ty_key(&p.ty)?, refine: p.refine.clone(), take: p.take });
        }
        let ret = self.ty_key(&f.ret)?;
        let requires = self.cp_es(&f.requires)?;
        // G6: the ensures of a trusted rust fn are kept (checked by `--foreign-checks all`)
        let ensures = if f.foreign.is_some() { self.cp_es(&f.ensures)? } else { Vec::new() };
        let body = self.cp_stmts(&f.body)?;
        Ok(Function {
            line: f.line,
            col: f.col,
            name: name.to_string(),
            params,
            ret,
            effects: f.effects.clone(),
            requires,
            ensures,
            body,
            ret_refine: f.ret_refine.clone(),
            tparams: Vec::new(),
            foreign: f.foreign.clone(),
            decreases: None, // G9 A0: G9 programs are rejected before specialization
        })
    }

    fn fields(&mut self, fs: &[FieldDecl]) -> MR<Vec<FieldDecl>> {
        let mut out = Vec::with_capacity(fs.len());
        for fd in fs {
            out.push(FieldDecl { line: fd.line, col: fd.col, name: fd.name.clone(), ty: self.ty_key(&fd.ty)? });
        }
        Ok(out)
    }

    fn type_decl(&mut self, d: &TypeDecl, stem: &str, mapping: Mapping) -> MR<TypeDecl> {
        self.set_map(mapping);
        self.pos = (d.line(), d.col());
        Ok(match d {
            TypeDecl::Struct(s) => TypeDecl::Struct(StructDecl {
                line: s.line,
                col: s.col,
                name: stem.to_string(),
                fields: self.fields(&s.fields)?,
                tparams: Vec::new(),
            }),
            TypeDecl::Enum(e) => {
                let mut variants = Vec::with_capacity(e.variants.len());
                for v in &e.variants {
                    variants.push(VariantDecl {
                        line: v.line,
                        col: v.col,
                        name: v.name.clone(),
                        fields: self.fields(&v.fields)?,
                    });
                }
                TypeDecl::Enum(EnumDecl { line: e.line, col: e.col, name: stem.to_string(), variants, tparams: Vec::new() })
            }
        })
    }

    // ---------- driver ----------
    fn run(mut self) -> MR<SpecPlan> {
        let prog = self.prog;
        let mut plain_types: Vec<(usize, TypeDecl)> = Vec::new();
        for (i, d) in prog.types.iter().enumerate() {
            if !d.tparams().is_empty() || self.tindex.get(d.name()) != Some(&i) {
                continue;
            }
            let nd = self.type_decl(d, d.name(), Mapping::new())?;
            plain_types.push((i, nd));
        }
        let mut roots: HashMap<String, Function> = HashMap::new();
        for (i, f) in prog.functions.iter().enumerate() {
            if f.tparams.is_empty() && self.findex.get(&f.name) == Some(&i) {
                let nf = self.function(f, &f.name, Mapping::new())?;
                roots.insert(f.name.clone(), nf);
            }
        }
        while let Some(item) = self.queue.pop_front() {
            match item {
                Item::Fn(i) => {
                    let (name, stem, args) = {
                        let s = &self.fns[i];
                        (s.name.clone(), s.stem.clone(), s.args.clone())
                    };
                    let fi = self.findex[&name];
                    let f = &prog.functions[fi];
                    let m = bind_args(&fn_owner(&f.name), f.tparams.len(), &args)
                        .map_err(|e| MonoError::Internal(e.to_string()))?;
                    let nf = self.function(f, &stem, m)?;
                    self.fns[i].func = Some(nf);
                }
                Item::Ty(i) => {
                    let (name, stem, args) = {
                        let s = &self.types[i];
                        (s.name.clone(), s.stem.clone(), s.args.clone())
                    };
                    let ti = self.tindex[&name];
                    let d = &prog.types[ti];
                    let m = bind_args(&decl_owner(d.name()), d.tparams().len(), &args)
                        .map_err(|e| MonoError::Internal(e.to_string()))?;
                    let nd = self.type_decl(d, &stem, m)?;
                    self.types[i].decl = Some(nd);
                }
            }
        }
        // ---- output order ----
        let mut by_fn: HashMap<String, Vec<usize>> = HashMap::new();
        for (i, s) in self.fns.iter().enumerate() {
            by_fn.entry(s.name.clone()).or_default().push(i);
        }
        let mut fn_stems: Vec<String> = Vec::new();
        let mut functions: Vec<Function> = Vec::new();
        let mut root_names: Vec<String> = Vec::new();
        for (i, f) in prog.functions.iter().enumerate() {
            if self.findex.get(&f.name) != Some(&i) {
                continue;
            }
            if f.tparams.is_empty() {
                if let Some(nf) = roots.remove(&f.name) {
                    functions.push(nf);
                }
                root_names.push(f.name.clone());
            } else {
                let mut specs = by_fn.remove(&f.name).unwrap_or_default();
                specs.sort_by(|a, b| self.fns[*a].encs.cmp(&self.fns[*b].encs));
                for si in specs {
                    fn_stems.push(self.fns[si].stem.clone());
                    if let Some(nf) = self.fns[si].func.take() {
                        functions.push(nf);
                    }
                }
            }
        }
        let mut keyed: Vec<((usize, Vec<String>), TypeDecl)> =
            plain_types.into_iter().map(|(i, d)| ((i, Vec::new()), d)).collect();
        let mut order: Vec<usize> = (0..self.types.len()).collect();
        order.sort_by(|a, b| {
            let (x, y) = (&self.types[*a], &self.types[*b]);
            (self.tindex[&x.name], &x.encs).cmp(&(self.tindex[&y.name], &y.encs))
        });
        let mut type_stems: Vec<String> = Vec::new();
        for i in order {
            type_stems.push(self.types[i].stem.clone());
            let key = (self.tindex[&self.types[i].name], self.types[i].encs.clone());
            if let Some(d) = self.types[i].decl.take() {
                keyed.push((key, d));
            }
        }
        keyed.sort_by(|a, b| a.0.cmp(&b.0));
        let program = Program { functions, types: keyed.into_iter().map(|(_, d)| d).collect(), refined: prog.refined, g9: None };
        Ok(SpecPlan { program, fn_stems, type_stems, roots: root_names })
    }
}

fn expr_ty_of(e: &Expr) -> &Option<String> {
    match e {
        Expr::IntLit(x) => &x.ty,
        Expr::BoolLit(x) => &x.ty,
        Expr::StrLit(x) => &x.ty,
        Expr::Var(x) => &x.ty,
        Expr::Unary(x) => &x.ty,
        Expr::Binary(x) => &x.ty,
        Expr::Call(x) => &x.ty,
        Expr::Index(x) => &x.ty,
        Expr::Ctor(x) => &x.ty,
        Expr::Quant(x) => &x.ty,
        Expr::StructLit(x) => &x.ty,
        Expr::EnumCtor(x) => &x.ty,
        Expr::FieldAccess(x) => &x.ty,
        Expr::IsVariant(x) => &x.ty,
        Expr::VariantField(x) => &x.ty,
        Expr::Move(x) => &x.ty,
    }
}

/// The specialization plan of a checked program (does not mutate it). `MonoError::Limit` carries the
/// codegen/specialization_limit diagnostic when a limit of G3_SPEC 5.1 is exceeded.
pub fn specialize(prog: &Program) -> Result<SpecPlan, MonoError> {
    Mono::new(prog).run()
}
