//! Symbolic execution of verify.py: `Arr`, `State`, `FnVerifier` (fresh, wf, rebuild, havoc, aggregates, expression `ev`, domain `dom`,
//! statement `exec`, loops, `run`).
//!
//! Function structure, call order, `s.k` increment order, z3 expression construction order and lemma accumulation order are kept the same as verify.py.
//! Line numbers in comments refer to verify.py. Obligations (`prove`), counterexamples and trace are in obligation.rs.
//!
//! In Python, `ev(e, st, g, code, env=None)` reads the same dict via `env = st.env` while appending to `st.pc`.
//! In Rust, `ev` takes `env: &Env` (a snapshot cloned on entry) separately from `st: &mut State`. Since `ev` does not modify env,
//! the semantics are the same. The counterexample (`cex`) reads `st.env`.

use std::cell::RefCell;
use std::collections::{BTreeSet, HashMap, HashSet};
use std::time::Instant;

use pruv_core::ast::{self as ast, Expr, Stmt};
use pruv_core::diagnostic::PruvError;
use pruv_core::gtype::{self, GType, Mapping};

use crate::model::{Elem, Model, NomKind, Prelude, Ty};
use crate::obligation::Trace;
use crate::sys::{Ast, FuncDecl, Sort, Z3};

/// (line, col), 1-based.
pub type Pos = (u32, u32);

/// Internal failures (Python exceptions) are propagated as strings.
pub type R<T> = Result<T, String>;

/// verify.py line 7.
pub const MAX_LEN: i64 = 1 << 40;
/// verify.py line 8.
pub const TIMEOUT_MS: u32 = 8000;

/// verify.py `QueryConfig`: recording boundary of one solver query (phase, round, resource limits).
#[derive(Clone, Debug)]
pub struct QueryConfig {
    /// "verification" | "inference"
    pub phase: String,
    pub round: Option<u32>,
    pub timeout_ms: u32,
    pub rlimit: Option<u32>,
    pub seed: Option<u32>,
}

impl Default for QueryConfig {
    fn default() -> Self {
        QueryConfig { phase: "verification".to_string(), round: None, timeout_ms: TIMEOUT_MS, rlimit: None, seed: None }
    }
}

/// STAGE1 B2: one candidate that inference adds to a loop = (candidate ID, expr, string). An item of verify.py `extra`.
pub type ExtraInv = (String, Expr, String);
/// STAGE1 B2: loop number → that loop's candidates (sorted order). If empty, the existing path.
pub type Extra = HashMap<usize, std::rc::Rc<Vec<ExtraInv>>>;

/// verify.py `BudgetExhausted` / `InferenceTimeout`. Python escapes from deep inside `prove` via an exception, but Rust's
/// `prove` returns no value, so it is flagged in `Probe.abort`, later obligations pass without query or recording, and `exec_block` stops.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum ProbeAbort {
    Budget,
    Timeout,
}

/// verify.py `Probe`: search state of one function (shared by all rounds).
pub struct Probe {
    pub max_queries: usize,
    pub deadline: Instant,
    /// Number of attempts so far (budget counter)
    pub queries: usize,
    /// Candidates that failed this round {ID: (obligation code, attempt status)}
    pub failed: HashMap<String, (String, String)>,
    pub abort: Option<ProbeAbort>,
}

impl Probe {
    pub fn new(max_queries: usize, deadline: Instant) -> Probe {
        Probe { max_queries, deadline, queries: 0, failed: HashMap::new(), abort: None }
    }
    pub fn begin_round(&mut self) {
        self.failed.clear();
    }
    /// verify.py `Probe.tick`: before an attempt, budget → wall clock → count. If exceeded, sets abort and returns false.
    pub fn tick(&mut self) -> bool {
        if self.queries >= self.max_queries {
            self.abort = Some(ProbeAbort::Budget);
            return false;
        }
        if Instant::now() > self.deadline {
            self.abort = Some(ProbeAbort::Timeout);
            return false;
        }
        self.queries += 1;
        true
    }
}

/// verify.py `walk_loops`: (While, the block containing it, index within the block), in pre-order (statement order, a While before its body,
/// If then → els, Match arm order). Loop number = position in this sequence.
pub fn walk_loops(stmts: &[Stmt]) -> Vec<(&ast::While, &[Stmt], usize)> {
    fn go<'s>(stmts: &'s [Stmt], out: &mut Vec<(&'s ast::While, &'s [Stmt], usize)>) {
        for (i, st) in stmts.iter().enumerate() {
            match st {
                Stmt::While(w) => {
                    out.push((w, stmts, i));
                    go(&w.body, out);
                }
                Stmt::If(x) => {
                    go(&x.then, out);
                    go(&x.els, out);
                }
                Stmt::Match(m) => {
                    for a in &m.arms {
                        go(&a.body, out);
                    }
                }
                _ => {}
            }
        }
    }
    let mut out = Vec::new();
    go(stmts, &mut out);
    out
}

/// One invariant item of `loop_`: (candidate ID or None, expr, candidate string or None).
type InvRef<'x> = (Option<&'x str>, &'x Expr, Option<&'x str>);

/// Wording inside verify.py `loop`: (domain what, obligation what).
fn inv_what(cid: Option<&str>, text: Option<&str>, phase: &str) -> (String, String) {
    match cid {
        None => (
            format!("variant_field lookups in loop invariant ({}) are defined", phase),
            if phase == "entry" { "loop invariant on entry".to_string() } else { "loop invariant preserved".to_string() },
        ),
        Some(_) => {
            let t = text.unwrap_or("");
            (
                format!("partial operations in inferred loop invariant `{}` ({}) are defined", t, phase),
                if phase == "entry" {
                    format!("inferred loop invariant `{}` on entry", t)
                } else {
                    format!("inferred loop invariant `{}` preserved", t)
                },
            )
        }
    }
}

/// verify.py `in_range` (line 168). `x >= I64_MIN` is a comparison with a Python int, so it is not flipped (raw).
pub fn in_range(z: &Z3, x: &Ast) -> Ast {
    z.and(&[x.raw_ge(&z.int(i64::MIN)), x.raw_le(&z.int(i64::MAX))])
}

/// verify.py `_conj` (line 72): None is skipped, one item is returned as is, two or more become And.
pub fn conj(z: &Z3, xs: Vec<Option<Ast>>) -> Option<Ast> {
    let xs: Vec<Ast> = xs.into_iter().flatten().collect();
    match xs.len() {
        0 => None,
        1 => Some(xs[0].clone()),
        _ => Some(z.and(&xs)),
    }
}

/// verify.py `_imp` (line 79).
pub fn imp(c: &Ast, d: Option<Ast>) -> Option<Ast> {
    d.map(|d| c.implies(&d))
}

/// Render an integer literal (sign + decimal string) in Python `str(int)` form: strip a leading `+` and zeros; `-0` becomes `0`.
pub fn norm_int(s: &str) -> String {
    let (neg, rest) = match s.strip_prefix('-') {
        Some(r) => (true, r),
        None => (false, s.strip_prefix('+').unwrap_or(s)),
    };
    let d = rest.trim_start_matches('0');
    if d.is_empty() {
        "0".to_string()
    } else if neg {
        format!("-{}", d)
    } else {
        d.to_string()
    }
}

// ---------------------------------------------------------------------------------------------
// Expression-shape helpers (verify.py lines 83-132)
// ---------------------------------------------------------------------------------------------

/// The kind of `_partial_here`: None=all, "variant", "other".
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum PKind {
    All,
    Variant,
    Other,
}

fn is_tag_fn(n: &str) -> bool {
    matches!(n, "some_val" | "ok_val" | "err_val")
}

/// verify.py `_partial_here` (line 86).
fn partial_here(e: &Expr, kind: PKind) -> bool {
    match e {
        Expr::VariantField(_) => kind != PKind::Other,
        _ if kind == PKind::Variant => false,
        Expr::Index(_) => true,
        Expr::Binary(b) => b.op == "/" || b.op == "%",
        Expr::Call(c) => is_tag_fn(&c.name),
        Expr::Quant(q) => q.kind == "max" || q.kind == "min",
        _ => false,
    }
}

/// verify.py `_kids` (line 103).
fn kids(e: &Expr) -> Vec<&Expr> {
    match e {
        Expr::Unary(x) => vec![&*x.operand],
        Expr::Binary(x) => vec![&*x.left, &*x.right],
        Expr::Index(x) => vec![&*x.array, &*x.index],
        Expr::Ctor(x) => x.arg.iter().map(|a| &**a).collect(),
        Expr::Quant(x) => vec![&*x.lo, &*x.hi, &*x.body],
        Expr::Call(x) => x.args.iter().collect(),
        Expr::StructLit(x) => x.fields.iter().map(|f| &f.value).collect(),
        Expr::EnumCtor(x) => x.args.iter().collect(),
        Expr::FieldAccess(x) => vec![&*x.base],
        Expr::IsVariant(x) => vec![&*x.value],
        Expr::VariantField(x) => vec![&*x.value],
        _ => Vec::new(),
    }
}

/// verify.py `_has_vf` (line 127).
pub fn has_vf(e: &Expr, kind: PKind) -> bool {
    if partial_here(e, kind) {
        return true;
    }
    kids(e).into_iter().any(|c| has_vf(c, kind))
}

fn pos(e: &Expr) -> Pos {
    (e.line() as u32, e.col() as u32)
}

/// verify.py `_enum_ty`: the instantiated enum type of an is_variant / variant_field scrutinee: the type of the value
/// (already substituted), else the plain enum name.
fn enum_ty(enum_name: &str, v: &Val) -> Ty {
    if let Val::Dt(_, t) = v {
        if t.name() == enum_name {
            return t.clone();
        }
    }
    Ty::User(enum_name.to_string())
}

/// The datatype value of an argument of is_some / some_val / ... and its type (None for any other value).
fn dt_arg(v: &Val) -> R<(&Ast, &Ty)> {
    match v {
        Val::Dt(a, t) => Ok((a, t)),
        _ => Err("expected an Option/Result value".to_string()),
    }
}

/// The value read from the payload of an Option/Result of type `ty` (some_val / ok_val): `i64` for the legacy types.
fn payload_val(ty: &Ty, a: Ast) -> R<Val> {
    match ty {
        Ty::Inst(g) if !g.args.is_empty() => Val::from_field(&Ty::from_gtype(&g.args[0]), a),
        _ => Ok(Val::Int(a)),
    }
}

fn stmt_pos(s: &Stmt) -> Pos {
    let (l, c) = match s {
        Stmt::Let(x) => (x.line, x.col),
        Stmt::Assign(x) => (x.line, x.col),
        Stmt::IndexAssign(x) => (x.line, x.col),
        Stmt::If(x) => (x.line, x.col),
        Stmt::While(x) => (x.line, x.col),
        Stmt::Return(x) => (x.line, x.col),
        Stmt::Assert(x) => (x.line, x.col),
        Stmt::ExprStmt(x) => (x.line, x.col),
        Stmt::FieldAssign(x) => (x.line, x.col),
        Stmt::Match(x) => (x.line, x.col),
    };
    (l as u32, c as u32)
}

/// verify.py `assigned` (line 671): assigned names (Let excluded). A name-ordered set, so havoc iteration is in sorted order.
pub fn assigned(stmts: &[Stmt], out: &mut BTreeSet<String>) {
    for st in stmts {
        match st {
            Stmt::Assign(a) => {
                out.insert(a.name.clone());
            }
            Stmt::IndexAssign(a) => {
                out.insert(a.name.clone());
            }
            Stmt::FieldAssign(a) => {
                out.insert(a.name.clone());
            }
            Stmt::If(i) => {
                assigned(&i.then, out);
                assigned(&i.els, out);
            }
            Stmt::While(w) => assigned(&w.body, out),
            Stmt::Match(m) => {
                for a in &m.arms {
                    assigned(&a.body, out);
                }
            }
            _ => {}
        }
    }
}

// ---------------------------------------------------------------------------------------------
// Values, environment, state
// ---------------------------------------------------------------------------------------------

#[derive(Clone)]
pub struct Arr {
    pub a: Ast,
    pub n: Ast,
    pub name: String,
    pub elem: Elem,
    /// G3: the element type of an array of abstract elements (`elem == Elem::Abs`), None otherwise.
    pub ety: Option<GType>,
}

impl Arr {
    /// Pure assembly (does not touch the fresh counter).
    pub fn new(a: Ast, n: Ast, name: String, elem: Elem) -> Arr {
        Arr { a, n, name, elem, ety: None }
    }
    /// An array whose elements have the abstract type `ety` (a type parameter).
    pub fn abs(a: Ast, n: Ast, name: String, ety: GType) -> Arr {
        Arr { a, n, name, elem: Elem::Abs, ety: Some(ety) }
    }
    /// A new array value of the same element type (mk_arr(.., arr.elem)).
    pub fn like(&self, a: Ast, n: Ast, name: &str) -> Arr {
        Arr { a, n, name: name.to_string(), elem: self.elem, ety: self.ety.clone() }
    }
    /// The Pruv type of an element read from an abstract array.
    pub fn elem_ty(&self) -> Ty {
        match &self.ety {
            Some(g) => Ty::from_gtype(g),
            None => Ty::I64,
        }
    }
    /// The array type of this value (to make a fresh one of the same shape).
    pub fn array_ty(&self) -> Ty {
        match &self.ety {
            Some(g) => Ty::GArray(g.clone()),
            None => Ty::Array(self.elem),
        }
    }
}

/// Environment value. verify.py distinguishes Int/Bool/Datatype by the z3 expression's sort, but here they are carried as tags.
#[derive(Clone)]
pub enum Val {
    Int(Ast),
    Bool(Ast),
    /// An Opt/Res/user struct/enum value and its Pruv type (= `Model.type_of`).
    Dt(Ast, Ty),
    Arr(Arr),
    /// Python `None` (print, unit function call).
    Unit,
}

impl Val {
    pub fn ast(&self) -> &Ast {
        match self {
            Val::Int(a) | Val::Bool(a) | Val::Dt(a, _) => a,
            Val::Arr(_) | Val::Unit => panic!("value has no single ast"),
        }
    }
    pub fn arr(&self) -> &Arr {
        match self {
            Val::Arr(a) => a,
            _ => panic!("not an array"),
        }
    }
    pub fn try_ast(&self) -> R<&Ast> {
        match self {
            Val::Int(a) | Val::Bool(a) | Val::Dt(a, _) => Ok(a),
            Val::Arr(_) => Err("expected a z3 value, got an array".to_string()),
            Val::Unit => Err("expected a z3 value, got None".to_string()),
        }
    }
    pub fn try_arr(&self) -> R<&Arr> {
        match self {
            Val::Arr(a) => Ok(a),
            _ => Err("expected an array".to_string()),
        }
    }
    /// The value tag of accessor result `a` whose field type is `ty` (the same classification as Python, which distinguishes by z3 sort).
    pub fn from_field(ty: &Ty, a: Ast) -> R<Val> {
        match ty {
            Ty::I64 => Ok(Val::Int(a)),
            Ty::Bool => Ok(Val::Bool(a)),
            Ty::Opt | Ty::Res | Ty::User(_) | Ty::Param(_) | Ty::Inst(_) => Ok(Val::Dt(a, ty.clone())),
            Ty::Array(_) | Ty::GArray(_) | Ty::Str | Ty::Unit => Err(format!("'{}'", ty.name())),
        }
    }
}

/// An environment that preserves insertion order (Python dict).
#[derive(Clone, Default)]
pub struct Env(pub Vec<(String, Val)>);

impl Env {
    pub fn get(&self, name: &str) -> &Val {
        self.try_get(name).unwrap_or_else(|| panic!("unbound variable {name}"))
    }
    pub fn try_get(&self, name: &str) -> Option<&Val> {
        self.0.iter().find(|(k, _)| k == name).map(|(_, v)| v)
    }
    /// dict assignment: if already present, replace only the value, keeping its position.
    pub fn set(&mut self, name: &str, v: Val) {
        if let Some(e) = self.0.iter_mut().find(|(k, _)| k == name) {
            e.1 = v;
        } else {
            self.0.push((name.to_string(), v));
        }
    }
    /// `del env[name]`.
    pub fn remove(&mut self, name: &str) {
        self.0.retain(|(k, _)| k != name);
    }
    pub fn contains(&self, name: &str) -> bool {
        self.0.iter().any(|(k, _)| k == name)
    }
}

#[derive(Clone)]
pub struct State {
    pub env: Env,
    pub pc: Vec<Ast>,
}

impl State {
    /// verify.py `State.fork` (line 146).
    pub fn fork(&self, extra: Option<Ast>) -> State {
        let mut pc = self.pc.clone();
        if let Some(e) = extra {
            pc.push(e);
        }
        State { env: self.env.clone(), pc }
    }
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Arith {
    Add,
    Sub,
    Mul,
}

// ---------------------------------------------------------------------------------------------
// FnVerifier
// ---------------------------------------------------------------------------------------------

/// verify.py `FnVerifier` (line 189). One per function; `k`/`seen`/`aggs`/`lemmas` are per function.
pub struct FnVerifier<'a> {
    pub z: Z3,
    pub prelude: &'a Prelude,
    pub model: &'a Model,
    pub trace: &'a mut Trace,
    pub fname: String,
    /// `s.k`
    pub k: u32,
    pub(crate) seen: HashSet<(u32, u32, String, Option<String>)>,
    pub qstack: Vec<Ast>,
    /// `s.aggs`: (kind, Tc.sexpr(), len(outer)) → F. Insertion order preserved (`len(aggs)` goes into the F name).
    pub(crate) aggs: Vec<((String, String, usize), FuncDecl)>,
    pub lemmas: Vec<Ast>,
    /// The `(kind, F)` item of `lemma_keys`
    pub(crate) lemma_fn_keys: HashSet<(String, String)>,
    /// The `L.sexpr()` item of `lemma_keys`
    pub(crate) lemma_text_keys: HashSet<String>,
    /// `s.params`
    pub params: Env,
    /// `s.errors`(collected by verify_program in function order).
    pub errors: Vec<PruvError>,
    /// `s.funcs`: name → function (the later one if names repeat).
    pub(crate) funcs: HashMap<String, &'a ast::Function>,
    /// `s.f`: the function being proved (None on the prototype path).
    pub(crate) f: Option<&'a ast::Function>,
    /// Solver query configuration (default: verification, TIMEOUT_MS, no rlimit/seed).
    pub qcfg: QueryConfig,
    /// STAGE1 B2 `extra`: loop number → candidates. If empty, the existing path (fresh numbers, SMT and errors unchanged).
    pub extra: Extra,
    /// Loop (While node address) → loop number. Filled only when `extra` is non-empty (`set_extra`).
    pub(crate) loop_no: HashMap<usize, usize>,
    /// STAGE1 B2 search state. If Some, only candidate obligations are queried and no errors are produced.
    pub probe: Option<&'a mut Probe>,
    /// G3 A2: callee type-parameter substitution while a callee contract is re-interpreted (verify.py `theta`).
    pub(crate) theta: Mapping,
    /// G3 A2 (4.7): per abstract sort, the model values seen so far in this counterexample (their order gives `opaque#N`).
    pub(crate) opq: RefCell<HashMap<String, Vec<String>>>,
}

impl<'a> FnVerifier<'a> {
    /// Prototype (hand-builder) path: uses only the pieces, without a program or function.
    pub fn new(z: &Z3, prelude: &'a Prelude, model: &'a Model, trace: &'a mut Trace, fname: &str) -> Self {
        FnVerifier {
            z: z.clone(),
            prelude,
            model,
            trace,
            fname: fname.to_string(),
            k: 0,
            seen: HashSet::new(),
            qstack: Vec::new(),
            aggs: Vec::new(),
            lemmas: Vec::new(),
            lemma_fn_keys: HashSet::new(),
            lemma_text_keys: HashSet::new(),
            params: Env::default(),
            errors: Vec::new(),
            funcs: HashMap::new(),
            f: None,
            qcfg: QueryConfig::default(),
            extra: HashMap::new(),
            loop_no: HashMap::new(),
            probe: None,
            theta: Mapping::new(),
            opq: RefCell::new(HashMap::new()),
        }
    }

    /// verify.py `T(ty)`: a checked node type (a type key) under the current contract-instantiation substitution.
    /// None when the node has no type (or an unparsable one).
    pub(crate) fn t(&self, key: Option<&str>) -> Option<Ty> {
        let k = key?;
        let g = GType::try_from_key(k).ok()?;
        let g = if self.theta.is_empty() { g } else { gtype::substitute(&g, &self.theta) };
        Some(Ty::from_gtype(&g))
    }

    /// verify.py `FnVerifier(.., extra=..)`: fixes the candidates and, if non-empty, builds the loop number table.
    pub fn set_extra(&mut self, extra: Extra) {
        self.loop_no.clear();
        if !extra.is_empty() {
            if let Some(f) = self.f {
                for (n, (w, _, _)) in walk_loops(&f.body).into_iter().enumerate() {
                    self.loop_no.insert(w as *const ast::While as usize, n);
                }
            }
        }
        self.extra = extra;
    }

    pub(crate) fn probe_aborted(&self) -> bool {
        matches!(&self.probe, Some(p) if p.abort.is_some())
    }

    /// `FnVerifier(prog, f, errors, model)`.
    pub fn for_function(
        z: &Z3,
        prelude: &'a Prelude,
        model: &'a Model,
        trace: &'a mut Trace,
        prog: &'a ast::Program,
        f: &'a ast::Function,
    ) -> Self {
        let mut v = FnVerifier::new(z, prelude, model, trace, &f.name);
        for g in &prog.functions {
            v.funcs.insert(g.name.clone(), g);
        }
        v.f = Some(f);
        v
    }

    // ---------- fresh (line 201) ----------
    /// `fresh(base, ty)`: bump k first, then the name is `base!k`; an array length is `base!k.len`.
    pub fn try_fresh(&mut self, base: &str, ty: &Ty) -> R<Val> {
        self.k += 1;
        let n = format!("{}!{}", base, self.k);
        let z = &self.z;
        match ty {
            Ty::I64 => Ok(Val::Int(z.int_const(&n))),
            Ty::Bool => Ok(Val::Bool(z.bool_const(&n))),
            Ty::Opt => Ok(Val::Dt(z.constant(&n, &self.prelude.opt.sort), ty.clone())),
            Ty::Res => Ok(Val::Dt(z.constant(&n, &self.prelude.res.sort), ty.clone())),
            Ty::Array(e) => {
                let int = z.int_sort();
                let esort = if *e == Elem::Bool { z.bool_sort() } else { z.int_sort() };
                let arr_sort = z.array_sort(&int, &esort);
                Ok(Val::Arr(Arr::new(
                    z.constant(&n, &arr_sort),
                    z.int_const(&format!("{}.len", n)),
                    base.to_string(),
                    *e,
                )))
            }
            Ty::Str => {
                let int = z.int_sort();
                let arr_sort = z.array_sort(&int, &int);
                Ok(Val::Arr(Arr::new(
                    z.constant(&n, &arr_sort),
                    z.int_const(&format!("{}.len", n)),
                    base.to_string(),
                    Elem::U8,
                )))
            }
            Ty::User(name) => match self.model.sort_opt(name) {
                Some(s) => Ok(Val::Dt(z.constant(&n, s), ty.clone())),
                None => Err(format!("fresh: {}", name)),
            },
            // G3: an abstract value, or an instance Option<X> / Result<X> / D<..>
            Ty::Param(_) | Ty::Inst(_) => {
                let s = self.model.try_sort_of(ty)?;
                Ok(Val::Dt(z.constant(&n, &s), ty.clone()))
            }
            // G3: [T] = (Array Int sort(T), length)
            Ty::GArray(e) => {
                let int = z.int_sort();
                let len = z.int_const(&format!("{}.len", n));
                if e.owner.is_some() {
                    let esort = self.model.try_sort_of(&Ty::from_gtype(e))?;
                    let arr_sort = z.array_sort(&int, &esort);
                    Ok(Val::Arr(Arr::abs(z.constant(&n, &arr_sort), len, base.to_string(), e.clone())))
                } else {
                    let (esort, elem) = match Ty::from_gtype(e) {
                        Ty::Bool => (z.bool_sort(), Elem::Bool),
                        Ty::User(u) if u == "u8" => (z.int_sort(), Elem::U8),
                        _ => (z.int_sort(), Elem::I64),
                    };
                    let arr_sort = z.array_sort(&int, &esort);
                    Ok(Val::Arr(Arr::new(z.constant(&n, &arr_sort), len, base.to_string(), elem)))
                }
            }
            Ty::Unit => Err("fresh: unit".to_string()),
        }
    }
    /// For the prototype: `Val::Unit` on failure.
    pub fn fresh(&mut self, base: &str, ty: &Ty) -> Val {
        self.try_fresh(base, ty).unwrap_or(Val::Unit)
    }
    pub fn fresh_int(&mut self, base: &str) -> Ast {
        self.fresh(base, &Ty::I64).ast().clone()
    }

    /// Even if the `!dk` constant made by dom()'s Quant branch is unused, `s.k += 1` still happens (line 499).
    pub fn bump_k(&mut self) {
        self.k += 1;
    }

    // ---------- value domain (line 219) ----------
    /// `wf(ty, v)`: all active leaves are i64. None if trivial.
    pub fn wf(&self, ty: &Ty, v: &Ast) -> Option<Ast> {
        self.try_wf(ty, v).ok().flatten()
    }

    /// `wf` that reports an internal failure (Python raises) instead of hiding it.
    pub fn try_wf(&self, ty: &Ty, v: &Ast) -> R<Option<Ast>> {
        let z = &self.z;
        let p = self.prelude;
        let m = self.model;
        Ok(match ty {
            Ty::I64 => Some(in_range(z, v)),
            Ty::Opt => Some(p.is_some(v).implies(&in_range(z, &p.sval(v)))),
            Ty::Res => Some(z.and(&[
                p.is_ok(v).implies(&in_range(z, &p.oval(v))),
                p.is_err(v).implies(&in_range(z, &p.eval(v))),
            ])),
            // G3: an abstract value has no well-formedness predicate
            Ty::Param(_) => None,
            // G3: Option<X>, X other than i64
            Ty::Inst(g) if g.name == "option" => {
                let o = m.opt(Some(ty))?;
                let w = self.try_wf(&Ty::from_gtype(&g.args[0]), &o.sval.apply1(v))?;
                w.map(|w| o.is_some.apply1(v).implies(&w))
            }
            Ty::Inst(g) if g.name == "result" => {
                let o = m.res(Some(ty))?;
                let w = self.try_wf(&Ty::from_gtype(&g.args[0]), &o.oval.apply1(v))?;
                let mut parts: Vec<Option<Ast>> = Vec::new();
                if let Some(w) = w {
                    parts.push(Some(o.is_ok.apply1(v).implies(&w)));
                }
                parts.push(Some(o.is_err.apply1(v).implies(&in_range(z, &o.eval.apply1(v)))));
                conj(z, parts)
            }
            Ty::User(_) | Ty::Inst(_) => match m.nominal_kind(ty) {
                Some(NomKind::Struct) => {
                    let accs = m.struct_info(ty)?.accs;
                    let mut parts: Vec<Option<Ast>> = Vec::new();
                    for ((_, ft), acc) in m.fields_of(ty, None)?.iter().zip(accs.iter()) {
                        parts.push(self.try_wf(ft, &acc.apply1(v))?);
                    }
                    conj(z, parts)
                }
                Some(NomKind::Enum) => {
                    let mut parts: Vec<Option<Ast>> = Vec::new();
                    for vn in m.variant_names(ty) {
                        let vf = m.variant_fns(ty, &vn)?;
                        let mut ws: Vec<Option<Ast>> = Vec::new();
                        for ((_, ft), acc) in m.fields_of(ty, Some(&vn))?.iter().zip(vf.accs.iter()) {
                            ws.push(self.try_wf(ft, &acc.apply1(v))?);
                        }
                        if let Some(w) = conj(z, ws) {
                            parts.push(Some(vf.rec.apply1(v).implies(&w)));
                        }
                    }
                    conj(z, parts)
                }
                None => None,
            },
            Ty::Bool | Ty::Unit | Ty::Array(_) | Ty::GArray(_) | Ty::Str => None,
        })
    }

    /// `rebuild(ty, cur, path, new)` (line 242): the struct value `cur` with the field path replaced by `new`.
    pub fn try_rebuild(&self, ty: &Ty, cur: &Ast, path: &[&str], new: &Ast) -> R<Ast> {
        if path.is_empty() {
            return Ok(new.clone());
        }
        let m = self.model;
        let i = m.field_index_of(ty, path[0], None)?;
        let sf = m.struct_info(ty)?;
        let mut vals: Vec<Ast> = sf.accs.iter().map(|a| a.apply1(cur)).collect();
        let fty = m.fields_of(ty, None)?[i].1.clone();
        let sub = self.try_rebuild(&fty, &vals[i], &path[1..], new)?;
        vals[i] = sub;
        Ok(sf.ctor.apply(&vals))
    }

    // ---------- first part of run() (line 835): for the prototype ----------
    /// `fresh` for each parameter; arrays put `0 <= len <= MAX_LEN` into pc, everything else puts `wf`. Also fills `self.params`.
    pub fn init_params(&mut self, params: &[(&str, Ty)]) -> State {
        let mut env = Env::default();
        let mut pc: Vec<Ast> = Vec::new();
        for (name, ty) in params {
            let v = self.fresh(name, ty);
            match &v {
                Val::Arr(a) => pc.push(self.z.and(&[a.n.ge_i(0), a.n.le_i(MAX_LEN)])),
                Val::Unit => {}
                other => {
                    if let Some(w) = self.wf(ty, other.ast()) {
                        pc.push(w);
                    }
                }
            }
            env.set(name, v);
        }
        self.params = env.clone();
        State { env, pc }
    }

    /// First part of `ensures_ok` (line 647): overlays the parameters' original values on the current env and inserts `result`.
    pub fn ensures_env(&self, st: &State, result: Option<Val>) -> Env {
        let mut env = st.env.clone();
        for (n, v) in &self.params.0 {
            env.set(n, v.clone());
        }
        if let Some(r) = result {
            env.set("result", r);
        }
        env
    }

    // ---------- ev pieces (for the prototype) ----------
    /// `assume(st, g, fact)` (line 340).
    pub fn assume(&self, st: &mut State, g: &[Ast], fact: Ast) {
        if g.is_empty() {
            st.pc.push(fact);
        } else {
            st.pc.push(self.z.and(g).implies(&fact));
        }
    }

    /// Binary `+ - *` (lines 361-385): builds the result and the `in_range(res)` obligation (code "overflow").
    pub fn ev_arith(&mut self, st: &State, g: &[Ast], op: Arith, l: &Ast, r: &Ast, node: Pos) -> Ast {
        let res = match op {
            Arith::Add => l.add(r),
            Arith::Sub => l.sub(r),
            Arith::Mul => l.mul(r),
        };
        let ob = in_range(&self.z, &res);
        self.prove(st, g, &ob, node, "overflow", None);
        res
    }

    /// Binary `/ %` (lines 373-376): obligation `r > 0 && l >= 0` (code "div").
    pub fn ev_div(&mut self, st: &State, g: &[Ast], is_mod: bool, l: &Ast, r: &Ast, node: Pos) -> Ast {
        let ob = self.z.and(&[r.gt_i(0), l.ge_i(0)]);
        self.prove(st, g, &ob, node, "div", None);
        if is_mod {
            l.modulo(r)
        } else {
            l.div(r)
        }
    }

    /// Unary `-` (lines 358-360).
    pub fn ev_neg(&mut self, st: &State, g: &[Ast], v: &Ast, node: Pos) -> Ast {
        let ob = in_range(&self.z, &v.neg());
        self.prove(st, g, &ob, node, "overflow", None);
        v.neg()
    }

    /// Index (lines 386-395): obligation `0 <= i < n` (code "index_oob"); assumes `in_range` of the value read into pc.
    pub fn ev_index(&mut self, st: &mut State, g: &[Ast], arr: &Arr, i: &Ast, node: Pos) -> Ast {
        let ob = self.z.and(&[i.ge_i(0), i.lt(&arr.n)]);
        self.prove(st, g, &ob, node, "index_oob", None);
        let v = arr.a.select(i);
        let w = in_range(&self.z, &v);
        self.assume(st, g, w);
        v
    }

    /// Call `alloc(n, init)` (lines 609-613). `args` = [n, init]. After the "alloc_negative" obligation, `s.k += 1`.
    pub fn ev_alloc(&mut self, st: &State, g: &[Ast], n: &Ast, init: &Ast, node: Pos) -> Arr {
        let ob = self.z.and(&[n.ge_i(0), n.le_i(MAX_LEN)]);
        self.prove(st, g, &ob, node, "alloc_negative", None);
        self.k += 1;
        Arr::new(self.z.const_array(&self.z.int_sort(), init), n.clone(), "alloc".to_string(), Elem::I64)
    }

    // ---------- exec pieces (for the prototype; st is a state the caller has already forked) ----------
    /// IndexAssign (lines 718-725): after the obligation `0 <= i < arr.n` ("index_oob", node = statement), `Store`.
    pub fn index_assign(&mut self, st: &mut State, name: &str, i: &Ast, v: &Ast, node: Pos) {
        let arr = st.env.get(name).arr().clone();
        let ob = self.z.and(&[i.ge_i(0), i.lt(&arr.n)]);
        self.prove(st, &[], &ob, node, "index_oob", None);
        st.env.set(name, Val::Arr(Arr::new(arr.a.store(i, v), arr.n.clone(), name.to_string(), arr.elem)));
    }

    /// FieldAssign (lines 761-766): the right-hand value `v` is computed first by the caller.
    pub fn field_assign(&mut self, st: &mut State, name: &str, path: &[&str], v: &Ast) {
        let Val::Dt(root, ty) = st.env.get(name).clone() else { panic!("field assign on non-struct") };
        let new = self.try_rebuild(&ty, &root, path, v).unwrap_or_else(|_| v.clone());
        st.env.set(name, Val::Dt(new, ty));
    }

    /// One check_dom case (lines 524-543): no query if the domain `d` is None or `simplify(d)` is true,
    /// otherwise `prove(.., code)` and return d (what is returned goes to the caller's `prev`).
    pub fn check_dom_one(&mut self, st: &State, g: &[Ast], d: Option<Ast>, node: Pos, code: &str) -> Option<Ast> {
        let d = d?;
        if d.simplify().is_true() {
            return None;
        }
        self.prove(st, g, &d, node, code, None);
        Some(d)
    }

    // ---------- havoc (line 684) ----------
    /// Iterates in name order (byte order = code point order, Python `sorted`) (the 0A sorting of SPEC §6).
    pub fn havoc_set(&mut self, st: &State, names: &BTreeSet<String>) -> R<State> {
        let mut h = st.fork(None);
        for n in names {
            let Some(old) = h.env.try_get(n).cloned() else { continue };
            match old {
                Val::Arr(old_arr) => {
                    let nv = self.try_fresh(n, &old_arr.array_ty())?;
                    let a = nv.try_arr()?.clone();
                    h.pc.push(self.z.and(&[a.n.ge_i(0), a.n.le_i(MAX_LEN)]));
                    if a.elem == Elem::U8 {
                        h.pc.push(self.u8_dom(&a));
                    }
                    h.env.set(n, Val::Arr(a));
                }
                Val::Int(_) => {
                    let nv = self.try_fresh(n, &Ty::I64)?;
                    let a = nv.try_ast()?.clone();
                    h.pc.push(in_range(&self.z, &a));
                    h.env.set(n, Val::Int(a));
                }
                Val::Bool(_) => {
                    let nv = self.try_fresh(n, &Ty::Bool)?;
                    h.env.set(n, nv);
                }
                Val::Dt(old_ast, ty) => {
                    // Set value: in `name!h{k}`, k uses the value before incrementing and is bumped afterwards (lines 701-702).
                    let nv = self.z.constant(&format!("{}!h{}", n, self.k), &old_ast.sort());
                    self.k += 1;
                    h.env.set(n, Val::Dt(nv.clone(), ty.clone()));
                    if let Some(w) = self.try_wf(&ty, &nv)? {
                        h.pc.push(w);
                    }
                }
                Val::Unit => return Err("havoc: None".to_string()),
            }
        }
        Ok(h)
    }

    /// For the prototype: accepts any order and sorts internally. On failure, returns only forks.
    pub fn havoc(&mut self, st: &State, names: &[&str]) -> State {
        let set: BTreeSet<String> = names.iter().map(|s| s.to_string()).collect();
        self.havoc_set(st, &set).unwrap_or_else(|_| st.fork(None))
    }

    // ---------- quantifier pieces (lines 401-417; for the prototype) ----------
    /// Mid-Quant evaluation: evaluate lo/hi first, then `s.k += 1`, constant `var!q{k}`, qstack push. After evaluating the body, `quant_exit`.
    pub fn quant_enter(&mut self, var: &str) -> Ast {
        self.k += 1;
        let k = self.z.int_const(&format!("{}!q{}", var, self.k));
        self.qstack.push(k.clone());
        k
    }
    pub fn quant_exit(&mut self) {
        self.qstack.pop();
    }
    /// `ForAll([k], Implies(And(k >= lo, k < hi), body))` — no patterns.
    pub fn forall_q(&self, k: &Ast, lo: &Ast, hi: &Ast, body: &Ast) -> Ast {
        let rng = self.z.and(&[k.ge(lo), k.lt(hi)]);
        self.z.forall(std::slice::from_ref(k), &rng.implies(body), &[])
    }
    /// `Exists([k], And(And(k >= lo, k < hi), body))`.
    pub fn exists_q(&self, k: &Ast, lo: &Ast, hi: &Ast, body: &Ast) -> Ast {
        let rng = self.z.and(&[k.ge(lo), k.lt(hi)]);
        self.z.exists(std::slice::from_ref(k), &self.z.and(&[rng, body.clone()]), &[])
    }

    /// G2 A2: element domain of a U8 array`ForAll([k], Implies(And(k >= 0, k < n), And(A[k] >= 0, A[k] <= 255)))`.
    /// The bound variable has the fixed name `elem!k` (does not touch self.k). No patterns.
    pub fn u8_dom(&self, arr: &Arr) -> Ast {
        let k = self.z.int_const("elem!k");
        let rng = self.z.and(&[k.ge_i(0), k.lt(&arr.n)]);
        let sel = arr.a.select(&k);
        let body = self.z.and(&[sel.ge_i(0), sel.le_i(255)]);
        self.z.forall(std::slice::from_ref(&k), &rng.implies(&body), &[])
    }

    /// G2 B1: is `i` a UTF-8 character boundary of the byte array `arr` (total function, no domain)?
    /// `Or(i == 0, i == n, And(i > 0, i < n, Or(b < 128, b >= 192)))`, `b = Select(arr.a, i)`.
    pub fn str_boundary(&self, arr: &Arr, i: &Ast) -> Ast {
        let z = &self.z;
        let b = arr.a.select(i);
        z.or(&[
            i.raw_eq(&z.int(0)),
            i.eq(&arr.n),
            z.and(&[i.gt_i(0), i.lt(&arr.n), z.or(&[b.lt_i(128), b.ge_i(192)])]),
        ])
    }

    // ---------- aggregates + lemmas (lines 545-602) ----------
    /// Translates sum/count/max/min over lo<=k<hi into an uninterpreted function `F(lo, hi, *outer)` and unrolling lemmas.
    /// At call time, this aggregate's own variable `k` must already be gone from `qstack` (after `quant_exit`).
    pub fn aggregate(&mut self, kind: &str, k: &Ast, lo: &Ast, hi: &Ast, t: &Ast) -> Ast {
        let z = self.z.clone();
        let outer: Vec<Ast> = self.qstack.iter().filter(|c| t.occurs(c)).cloned().collect();
        let k0 = z.int_const("agg!k");
        let ps: Vec<Ast> = (0..outer.len()).map(|i| z.int_const(&format!("agg!p{}", i))).collect();

        let mut from = vec![k.clone()];
        let mut to = vec![k0.clone()];
        for (o, p) in outer.iter().zip(ps.iter()) {
            from.push(o.clone());
            to.push(p.clone());
        }
        let tc = t.substitute(&from, &to);
        let key = (kind.to_string(), tc.sexpr(), outer.len());

        let existing = self.aggs.iter().find(|(kk, _)| *kk == key).map(|(_, f)| f.clone());
        let f = match existing {
            Some(f) => f,
            None => {
                let int = z.int_sort();
                let dom: Vec<Sort> = (0..2 + outer.len()).map(|_| int.clone()).collect();
                let f = FuncDecl::new(&z, &format!("agg!{}{}", kind, self.aggs.len()), &dom, &int);
                self.aggs.push((key.clone(), f.clone()));
                f
            }
        };

        let body_at = |x: &Ast| -> Ast {
            let mut from = vec![k0.clone()];
            let mut to = vec![x.clone()];
            for (p, o) in ps.iter().zip(outer.iter()) {
                from.push(p.clone());
                to.push(o.clone());
            }
            tc.substitute(&from, &to)
        };
        let val = |x: &Ast| -> Ast {
            let b = body_at(x);
            if kind == "count" {
                z.ite(&b, &z.int(1), &z.int(0))
            } else {
                b
            }
        };
        // The aggregate of the smaller range with element x attached. `empty`: the smaller range is empty.
        let comb = |smaller: &Ast, x: &Ast, empty: &Ast| -> Ast {
            if kind == "sum" || kind == "count" {
                z.ite(empty, &z.int(0), smaller).add(&val(x))
            } else {
                let better = if kind == "max" { smaller.ge(&val(x)) } else { smaller.le(&val(x)) };
                z.ite(empty, &val(x), &z.ite(&better, smaller, &val(x)))
            }
        };
        let fa = |a: &Ast, b: &Ast| -> Ast {
            let mut args = vec![a.clone(), b.clone()];
            args.extend(outer.iter().cloned());
            f.apply(&args)
        };

        let fk = (kind.to_string(), f.name().to_string());
        if !self.lemma_fn_keys.contains(&fk) {
            // Empty range: sum/count is 0 (no new terms are created, so no matching loop)
            self.lemma_fn_keys.insert(fk);
            if kind == "sum" || kind == "count" {
                let x = z.int_const("agg!x");
                let y = z.int_const("agg!y");
                let os: Vec<Ast> = (0..outer.len()).map(|i| z.int_const(&format!("agg!o{}", i))).collect();
                let mut args = vec![x.clone(), y.clone()];
                args.extend(os.iter().cloned());
                let fapp = f.apply(&args);
                let mut bound = vec![x.clone(), y.clone()];
                bound.extend(os.iter().cloned());
                let body = y.le(&x).implies(&fapp.raw_eq(&z.int(0)));
                self.lemmas.push(z.forall(&bound, &body, &[fapp.clone()]));
            }
        }

        let app = fa(lo, hi);
        let mut facts: Vec<Ast> = Vec::new();
        if kind == "count" {
            facts.push(lo.lt(hi).implies(&z.and(&[app.ge_i(0), app.le(&hi.sub(lo))])));
        }
        let bound_lo = self.qstack.iter().any(|c| lo.occurs(c));
        let bound_hi = self.qstack.iter().any(|c| hi.occurs(c));
        // Unroll by moving only one end: so the quantified lemma does not match its own output again.
        if !bound_hi {
            let hm1 = hi.sub_i(1);
            facts.push(lo.lt(hi).implies(&app.eq(&comb(&fa(lo, &hm1), &hm1, &hm1.le(lo)))));
            facts.push(lo.le(hi).implies(&fa(lo, &hi.add_i(1)).eq(&comb(&app, hi, &hi.le(lo)))));
        }
        if !bound_lo {
            let lp1 = lo.add_i(1);
            facts.push(lo.lt(hi).implies(&app.eq(&comb(&fa(&lp1, hi), lo, &hi.le(&lp1)))));
            let lm1 = lo.sub_i(1);
            facts.push(lo.le(hi).implies(&fa(&lm1, hi).eq(&comb(&app, &lm1, &hi.le(lo)))));
        }
        if !facts.is_empty() {
            let mut l = z.and(&facts);
            let bs: Vec<Ast> = self
                .qstack
                .iter()
                .filter(|c| outer.iter().any(|o| c.same(o)) || lo.occurs(c) || hi.occurs(c))
                .cloned()
                .collect();
            if !bs.is_empty() {
                l = z.forall(&bs, &l, std::slice::from_ref(&app));
            }
            let lk = l.sexpr();
            if self.lemma_text_keys.insert(lk) {
                self.lemmas.push(l);
            }
        }
        app
    }

    // =========================================================================================
    // Expressions (`ev` at line 345)
    // =========================================================================================

    /// `ev` with `st.env` as the snapshot (the env=None call).
    fn ev0(&mut self, e: &Expr, st: &mut State, g: &[Ast], code: bool) -> R<Val> {
        let env = st.env.clone();
        self.ev(e, st, g, code, &env)
    }

    fn ev0_ast(&mut self, e: &Expr, st: &mut State, g: &[Ast], code: bool) -> R<Ast> {
        let v = self.ev0(e, st, g, code)?;
        Ok(v.try_ast()?.clone())
    }

    fn ev_ast(&mut self, e: &Expr, st: &mut State, g: &[Ast], code: bool, env: &Env) -> R<Ast> {
        let v = self.ev(e, st, g, code, env)?;
        Ok(v.try_ast()?.clone())
    }

    /// verify.py `ev(e, st, g, code, env)`. code=True: generates proof obligations and i64 semantics.
    pub(crate) fn ev(&mut self, e: &Expr, st: &mut State, g: &[Ast], code: bool, env: &Env) -> R<Val> {
        let model: &'a Model = self.model;
        match e {
            Expr::IntLit(x) => Ok(Val::Int(self.z.int_str(&norm_int(&x.value)))),
            Expr::BoolLit(x) => Ok(Val::Bool(self.z.bool_val(x.value))),
            Expr::StrLit(x) => {
                // G2 B1: constant byte array. No counters, obligations or assumptions.
                let mut a = self.z.const_array(&self.z.int_sort(), &self.z.int(0));
                for (i, b) in x.value.iter().enumerate() {
                    a = a.store(&self.z.int(i as i64), &self.z.int(*b as i64));
                }
                Ok(Val::Arr(Arr::new(a, self.z.int(x.value.len() as i64), "literal".to_string(), Elem::U8)))
            }
            Expr::Var(x) => env.try_get(&x.name).cloned().ok_or_else(|| format!("'{}'", x.name)),
            Expr::Unary(x) => {
                let v = self.ev_ast(&x.operand, st, g, code, env)?;
                if x.op == "!" {
                    return Ok(Val::Bool(v.not()));
                }
                if code {
                    let ob = in_range(&self.z, &v.neg());
                    self.prove_core(&st.env, &st.pc, g, &ob, pos(e), "overflow", "no overflow in unary -", None);
                }
                Ok(Val::Int(v.neg()))
            }
            Expr::Binary(x) => {
                let op = x.op.as_str();
                if op == "&&" || op == "||" || op == "==>" {
                    let l = self.ev_ast(&x.left, st, g, code, env)?;
                    let mut g2: Vec<Ast> = g.to_vec();
                    g2.push(if op != "||" { l.clone() } else { l.not() });
                    let r = self.ev_ast(&x.right, st, &g2, code, env)?;
                    let res = if op == "&&" {
                        self.z.and(&[l, r])
                    } else if op == "||" {
                        self.z.or(&[l, r])
                    } else {
                        l.implies(&r)
                    };
                    return Ok(Val::Bool(res));
                }
                let l = self.ev_ast(&x.left, st, g, code, env)?;
                let r = self.ev_ast(&x.right, st, g, code, env)?;
                let res = match op {
                    "+" => l.add(&r),
                    "-" => l.sub(&r),
                    "*" => l.mul(&r),
                    "/" | "%" => {
                        if code {
                            let ob = self.z.and(&[r.gt_i(0), l.ge_i(0)]);
                            self.prove_core(&st.env, &st.pc, g, &ob, pos(e), "div", "divisor > 0 and dividend >= 0", None);
                        }
                        return Ok(Val::Int(if op == "/" { l.div(&r) } else { l.modulo(&r) }));
                    }
                    // Both sides are z3 expressions, so eq/ne/lt/.. follow the z3py reflection rule (flipped if the right side is a numeric literal)
                    "==" => return Ok(Val::Bool(l.eq(&r))),
                    "!=" => return Ok(Val::Bool(l.ne(&r))),
                    "<" => return Ok(Val::Bool(l.lt(&r))),
                    "<=" => return Ok(Val::Bool(l.le(&r))),
                    ">" => return Ok(Val::Bool(l.gt(&r))),
                    ">=" => return Ok(Val::Bool(l.ge(&r))),
                    other => return Err(format!("local variable 'res' referenced before assignment ({})", other)),
                };
                if code {
                    let ob = in_range(&self.z, &res);
                    self.prove_core(&st.env, &st.pc, g, &ob, pos(e), "overflow", &format!("no i64 overflow in `{}`", op), None);
                }
                Ok(Val::Int(res))
            }
            Expr::Index(x) => {
                let arr = self.ev(&x.array, st, g, code, env)?;
                let arr = arr.try_arr()?.clone();
                let i = self.ev_ast(&x.index, st, g, code, env)?;
                if code {
                    // `i >= 0` is with a Python int, `i < arr.n` is between z3 expressions (reflection rule)
                    let ob = self.z.and(&[i.ge_i(0), i.lt(&arr.n)]);
                    self.prove_core(
                        &st.env,
                        &st.pc,
                        g,
                        &ob,
                        pos(e),
                        "index_oob",
                        &format!("index in bounds for {}[...]", arr.name),
                        None,
                    );
                }
                let v = arr.a.select(&i);
                // G2 A5: a bool array yields a Bool value without an in_range assumption
                if arr.elem == Elem::Bool {
                    return Ok(Val::Bool(v));
                }
                // G3: an abstract element has no numeric domain: no in_range assumption
                if arr.elem == Elem::Abs {
                    return Ok(Val::Dt(v, arr.elem_ty()));
                }
                if code {
                    let w = in_range(&self.z, &v);
                    self.assume(st, g, w);
                }
                Ok(Val::Int(v))
            }
            Expr::Ctor(x) => {
                // G3: the datatype of the (substituted) type of the constructor application; legacy = Opt / Res
                let cty = self.t(x.ty.as_deref());
                if x.name == "None" {
                    let o = model.opt(cty.as_ref())?;
                    return Ok(Val::Dt(o.none.clone(), cty.unwrap_or(Ty::Opt)));
                }
                let arg = x.arg.as_ref().ok_or_else(|| "None".to_string())?;
                let v = self.ev_ast(arg, st, g, code, env)?;
                match x.name.as_str() {
                    "Some" => {
                        let o = model.opt(cty.as_ref())?;
                        Ok(Val::Dt(o.some.apply1(&v), cty.unwrap_or(Ty::Opt)))
                    }
                    "Ok" | "Err" => {
                        let o = model.res(cty.as_ref())?;
                        let r = if x.name == "Ok" { o.ok.apply1(&v) } else { o.err.apply1(&v) };
                        Ok(Val::Dt(r, cty.unwrap_or(Ty::Res)))
                    }
                    other => Err(format!("'{}'", other)),
                }
            }
            Expr::Quant(x) => {
                let lo = self.ev_ast(&x.lo, st, g, false, env)?;
                let hi = self.ev_ast(&x.hi, st, g, false, env)?;
                self.k += 1;
                let k = self.z.int_const(&format!("{}!q{}", x.var, self.k));
                let mut env2 = env.clone();
                env2.set(&x.var, Val::Int(k.clone()));
                self.qstack.push(k.clone());
                let body = self.ev_ast(&x.body, st, g, false, &env2);
                self.qstack.pop();
                let body = body?;
                if matches!(x.kind.as_str(), "sum" | "count" | "max" | "min") {
                    return Ok(Val::Int(self.aggregate(&x.kind, &k, &lo, &hi, &body)));
                }
                let rng = self.z.and(&[k.ge(&lo), k.lt(&hi)]);
                if x.kind == "forall" {
                    Ok(Val::Bool(self.z.forall(std::slice::from_ref(&k), &rng.implies(&body), &[])))
                } else {
                    Ok(Val::Bool(self.z.exists(std::slice::from_ref(&k), &self.z.and(&[rng, body]), &[])))
                }
            }
            Expr::Call(x) => self.call(e, x, st, g, code, env),
            Expr::StructLit(x) => {
                let mut vals: Vec<Ast> = Vec::new();
                for fi in &x.fields {
                    vals.push(self.ev_ast(&fi.value, st, g, code, env)?);
                }
                let sty = match self.t(x.ty.as_deref()) {
                    Some(t) => t,
                    None => Ty::User(x.name.clone()),
                };
                let sf = model.struct_info(&sty)?;
                Ok(Val::Dt(sf.ctor.apply(&vals), sty))
            }
            Expr::EnumCtor(x) => {
                let mut vals: Vec<Ast> = Vec::new();
                for a in &x.args {
                    vals.push(self.ev_ast(a, st, g, code, env)?);
                }
                let ety = match self.t(x.ty.as_deref()) {
                    Some(t) => t,
                    None => Ty::User(x.enum_name.clone()),
                };
                let vf = model.variant_fns(&ety, &x.variant)?;
                Ok(Val::Dt(vf.ctor.apply(&vals), ety))
            }
            Expr::FieldAccess(x) => {
                let v = self.ev(&x.base, st, g, code, env)?;
                let Val::Dt(va, sty) = &v else { return Err("field access on a non-struct value".to_string()) };
                let sf = model.struct_info(sty)?;
                let idx = model.field_index_of(sty, &x.field, None)?;
                let fty = model.fields_of(sty, None)?[idx].1.clone();
                Val::from_field(&fty, sf.accs[idx].apply1(va))
            }
            Expr::IsVariant(x) => {
                let v = self.ev(&x.value, st, g, code, env)?;
                let ety = enum_ty(&x.enum_name, &v);
                let vf = model.variant_fns(&ety, &x.variant)?;
                Ok(Val::Bool(vf.rec.apply1(v.try_ast()?)))
            }
            Expr::VariantField(x) => {
                let v = self.ev(&x.value, st, g, code, env)?;
                let ety = enum_ty(&x.enum_name, &v);
                let vf = model.variant_fns(&ety, &x.variant)?;
                let idx = model.field_index_of(&ety, &x.field, Some(&x.variant))?;
                let fty = model.fields_of(&ety, Some(&x.variant))?[idx].1.clone();
                Val::from_field(&fty, vf.accs[idx].apply1(v.try_ast()?))
            }
        }
    }

    /// verify.py `call` (line 604).
    fn call(&mut self, e: &Expr, x: &ast::Call, st: &mut State, g: &[Ast], code: bool, env: &Env) -> R<Val> {
        let n = x.name.as_str();
        let mut args: Vec<Val> = Vec::new();
        for a in &x.args {
            args.push(self.ev(a, st, g, code, env)?);
        }
        let arg = |i: usize| -> R<&Val> { args.get(i).ok_or_else(|| "tuple index out of range".to_string()) };
        match n {
            "len" => return Ok(Val::Int(arg(0)?.try_arr()?.n.clone())),
            "alloc" => {
                let a0 = arg(0)?.try_ast()?.clone();
                let a1 = arg(1)?.try_ast()?.clone();
                let ob = self.z.and(&[a0.ge_i(0), a0.le_i(MAX_LEN)]);
                self.prove_core(&st.env, &st.pc, g, &ob, pos(e), "alloc_negative", "alloc length in 0..2^40", None);
                // the element kind comes from the unsubstituted type name (verify.py `tname`), then a structured [T] overrides it
                let tname: Option<String> =
                    x.ty.as_deref().and_then(|k| GType::try_from_key(k).ok()).map(|g| g.name);
                let mut aelem = match tname.as_deref() {
                    Some("array_u8") => Elem::U8,
                    Some("array_bool") => Elem::Bool, // G2 A5
                    _ => Elem::I64,
                };
                let mut aety: Option<GType> = None;
                if let Some(Ty::GArray(el)) = self.t(x.ty.as_deref()) {
                    // G3: alloc of a [T]
                    aelem = if el.owner.is_some() {
                        Elem::Abs
                    } else if el == GType::bool() {
                        Elem::Bool
                    } else if el == GType::u8() {
                        Elem::U8
                    } else {
                        Elem::I64
                    };
                    if el.owner.is_some() {
                        aety = Some(el);
                    }
                }
                if aelem == Elem::U8 {
                    let ob = self.z.and(&[a1.ge_i(0), a1.le_i(255)]);
                    self.prove_core(
                        &st.env,
                        &st.pc,
                        g,
                        &ob,
                        pos(e),
                        "elem_range",
                        "u8 element range 0..=255 for the alloc fill value",
                        None,
                    );
                }
                self.k += 1;
                let ka = self.z.const_array(&self.z.int_sort(), &a1);
                return Ok(Val::Arr(match aety {
                    Some(ety) => Arr::abs(ka, a0, "alloc".to_string(), ety),
                    None => Arr::new(ka, a0, "alloc".to_string(), aelem),
                }));
            }
            "copy" => {
                let a = arg(0)?.try_arr()?;
                return Ok(Val::Arr(a.like(a.a.clone(), a.n.clone(), "copy")));
            }
            "is_char_boundary" => {
                // G2 B1: no obligations or assumptions.
                let sv = arg(0)?.try_arr()?;
                let i = arg(1)?.try_ast()?;
                return Ok(Val::Bool(self.str_boundary(sv, i)));
            }
            "substr" => {
                // G2 B1: range → bounds → new result → length assumption → byte-relation assumption.
                let sv = arg(0)?.try_arr()?.clone();
                let lo = arg(1)?.try_ast()?.clone();
                let hi = arg(2)?.try_ast()?.clone();
                let ob = self.z.and(&[lo.ge_i(0), lo.le(&hi), hi.le(&sv.n)]);
                self.prove_core(
                    &st.env,
                    &st.pc,
                    g,
                    &ob,
                    pos(e),
                    "string_slice_range",
                    &format!("substr range 0 <= lo <= hi <= len({})", sv.name),
                    None,
                );
                let ob = self.z.and(&[self.str_boundary(&sv, &lo), self.str_boundary(&sv, &hi)]);
                self.prove_core(
                    &st.env,
                    &st.pc,
                    g,
                    &ob,
                    pos(e),
                    "utf8_boundary",
                    &format!("substr cuts of {} at UTF-8 character boundaries", sv.name),
                    None,
                );
                let res_v = self.try_fresh("substr", &Ty::Str)?;
                let res = res_v.try_arr()?.clone();
                let len_fact = res.n.eq(&hi.sub(&lo));
                self.assume(st, g, len_fact);
                let k = self.z.int_const("str!k");
                let rng = self.z.and(&[k.ge_i(0), k.lt(&res.n)]);
                let body = res.a.select(&k).eq(&sv.a.select(&lo.add(&k)));
                let fa = self.z.forall(std::slice::from_ref(&k), &rng.implies(&body), &[]);
                self.assume(st, g, fa);
                return Ok(Val::Arr(res));
            }
            "print" => return Ok(Val::Unit),
            // G3: the datatype of the argument's own type (the legacy one for Option<i64> / Result<i64>)
            "is_some" | "some_val" => {
                let (a, ty) = dt_arg(arg(0)?)?;
                let o = self.model.opt(Some(ty))?;
                return if n == "is_some" {
                    Ok(Val::Bool(o.is_some.apply1(a)))
                } else {
                    payload_val(ty, o.sval.apply1(a))
                };
            }
            "is_ok" | "ok_val" | "err_val" => {
                let (a, ty) = dt_arg(arg(0)?)?;
                let o = self.model.res(Some(ty))?;
                return match n {
                    "is_ok" => Ok(Val::Bool(o.is_ok.apply1(a))),
                    "ok_val" => payload_val(ty, o.oval.apply1(a)),
                    _ => Ok(Val::Int(o.eval.apply1(a))),
                };
            }
            _ => {}
        }
        let f: &'a ast::Function = match self.funcs.get(n) {
            Some(f) => f,
            None => return Err(format!("'{}'", n)),
        };
        let mut cenv = Env::default();
        for (p, a) in f.params.iter().zip(args.iter()) {
            cenv.set(&p.name, a.clone());
        }
        // G3 A2 (4.4): typed re-interpretation of the callee contract under the checker's recorded substitution
        let theta: Mapping = match &x.inst {
            Some(i) => i.subst.iter().map(|(o, idx, t)| ((o.clone(), *idx), t.clone())).collect(),
            None => Mapping::new(),
        };
        let saved = std::mem::replace(&mut self.theta, theta);
        let r = self.call_contract(e, f, st, g, code, cenv);
        self.theta = saved;
        r
    }

    /// The part of `call` that runs under the callee's substitution (verify.py `try:` body): requires, fresh result, ensures.
    fn call_contract(&mut self, e: &Expr, f: &'a ast::Function, st: &mut State, g: &[Ast], code: bool, mut cenv: Env) -> R<Val> {
        let n = f.name.as_str();
        if code {
            // The call site does not prove the callee's requires domain (the callee's own run() already proves it).
            for r in &f.requires {
                let ob = self.ev_ast(r, st, g, false, &cenv)?;
                self.prove_core(
                    &st.env,
                    &st.pc,
                    g,
                    &ob,
                    pos(e),
                    "call_requires",
                    &format!("precondition of {} (line {})", n, r.line()),
                    None,
                );
            }
        }
        let ret = Ty::from_name(&f.ret);
        if ret == Ty::Unit {
            return Ok(Val::Unit);
        }
        let rty = if self.theta.is_empty() {
            ret
        } else {
            Ty::from_gtype(&gtype::substitute(&ret.to_gtype(), &self.theta))
        };
        let res = self.try_fresh(&format!("ret_{}", n), &rty)?;
        if let Val::Arr(ra) = &res {
            let w = self.z.and(&[ra.n.ge_i(0), ra.n.le_i(MAX_LEN)]);
            self.assume(st, g, w);
            if ra.elem == Elem::U8 {
                let d = self.u8_dom(ra);
                self.assume(st, g, d);
            }
        } else if let Some(w) = self.try_wf(&rty, res.try_ast()?)? {
            self.assume(st, g, w);
        }
        cenv.set("result", res.clone());
        for en in &f.ensures {
            let v = self.ev_ast(en, st, g, false, &cenv)?;
            self.assume(st, g, v);
        }
        Ok(res)
    }

    // =========================================================================================
    // Domain of a contract (lines 440-543)
    // =========================================================================================

    /// verify.py `dom(e, st, g, env, kind)`: the condition under which all partial operations of contract e are defined (short-circuit order). None=trivial.
    pub(crate) fn dom(&mut self, e: &Expr, st: &mut State, g: &[Ast], env: &Env, kind: PKind) -> R<Option<Ast>> {
        if !has_vf(e, kind) {
            return Ok(None);
        }
        let wo = kind != PKind::Variant; // None / "other"
        let wv = kind != PKind::Other; // None / "variant"
        let model: &'a Model = self.model;
        match e {
            Expr::Unary(x) => self.dom(&x.operand, st, g, env, kind),
            Expr::Binary(x) => {
                let dl = self.dom(&x.left, st, g, env, kind)?;
                if matches!(x.op.as_str(), "&&" | "||" | "==>") {
                    let l = self.ev_ast(&x.left, st, g, false, env)?;
                    let dr = self.dom(&x.right, st, g, env, kind)?;
                    let guard = if x.op == "||" { l.not() } else { l };
                    return Ok(conj(&self.z, vec![dl, imp(&guard, dr)]));
                }
                let dr = self.dom(&x.right, st, g, env, kind)?;
                let mut parts = vec![dl, dr];
                if wo && (x.op == "/" || x.op == "%") {
                    let r = self.ev_ast(&x.right, st, g, false, env)?;
                    parts.push(Some(r.ne_i(0)));
                }
                Ok(conj(&self.z, parts))
            }
            Expr::Index(x) => {
                let p0 = self.dom(&x.array, st, g, env, kind)?;
                let p1 = self.dom(&x.index, st, g, env, kind)?;
                let mut parts = vec![p0, p1];
                if wo {
                    let arr = self.ev(&x.array, st, g, false, env)?;
                    let arr = arr.try_arr()?.clone();
                    let i = self.ev_ast(&x.index, st, g, false, env)?;
                    parts.push(Some(self.z.and(&[i.ge_i(0), i.lt(&arr.n)])));
                }
                Ok(conj(&self.z, parts))
            }
            Expr::Ctor(x) => match &x.arg {
                Some(a) => self.dom(a, st, g, env, kind),
                None => Ok(None),
            },
            Expr::Call(x) => {
                let mut parts: Vec<Option<Ast>> = Vec::new();
                for a in &x.args {
                    parts.push(self.dom(a, st, g, env, kind)?);
                }
                if wo && is_tag_fn(&x.name) {
                    let a0 = x.args.first().ok_or_else(|| "tuple index out of range".to_string())?;
                    let vv = self.ev(a0, st, g, false, env)?;
                    // G3: the Option/Result instance of the argument
                    let (v, vty) = dt_arg(&vv)?;
                    if x.name == "some_val" {
                        parts.push(Some(model.opt(Some(vty))?.is_some.apply1(v)));
                    } else {
                        let ro = model.res(Some(vty))?;
                        let ok = ro.is_ok.apply1(v);
                        parts.push(Some(if x.name == "ok_val" { ok } else { ok.not() }));
                    }
                }
                Ok(conj(&self.z, parts))
            }
            Expr::StructLit(x) => {
                let mut parts: Vec<Option<Ast>> = Vec::new();
                for fi in &x.fields {
                    parts.push(self.dom(&fi.value, st, g, env, kind)?);
                }
                Ok(conj(&self.z, parts))
            }
            Expr::EnumCtor(x) => {
                let mut parts: Vec<Option<Ast>> = Vec::new();
                for a in &x.args {
                    parts.push(self.dom(a, st, g, env, kind)?);
                }
                Ok(conj(&self.z, parts))
            }
            Expr::FieldAccess(x) => self.dom(&x.base, st, g, env, kind),
            Expr::IsVariant(x) => self.dom(&x.value, st, g, env, kind),
            Expr::VariantField(x) => {
                let inner = self.dom(&x.value, st, g, env, kind)?;
                if !wv {
                    return Ok(inner);
                }
                let vv = self.ev(&x.value, st, g, false, env)?;
                let ety = enum_ty(&x.enum_name, &vv);
                let vf = model.variant_fns(&ety, &x.variant)?;
                Ok(conj(&self.z, vec![inner, Some(vf.rec.apply1(vv.try_ast()?))]))
            }
            Expr::Quant(x) => {
                let lo = self.ev_ast(&x.lo, st, g, false, env)?;
                let hi = self.ev_ast(&x.hi, st, g, false, env)?;
                let dlo = self.dom(&x.lo, st, g, env, kind)?;
                let dhi = self.dom(&x.hi, st, g, env, kind)?;
                let mut outer = vec![dlo, dhi];
                if wo && (x.kind == "max" || x.kind == "min") {
                    outer.push(Some(lo.lt(&hi)));
                }
                let outer = conj(&self.z, outer);
                self.k += 1;
                let k = self.z.int_const(&format!("{}!dk{}", x.var, self.k));
                let mut envk = env.clone();
                envk.set(&x.var, Val::Int(k.clone()));
                self.qstack.push(k.clone());
                let dbody = self.dom(&x.body, st, g, &envk, kind);
                self.qstack.pop();
                let Some(dbody) = dbody? else { return Ok(outer) };
                let mut rng = self.z.and(&[k.ge(&lo), k.lt(&hi)]);
                if x.kind == "forall" || x.kind == "exists" {
                    // The body at k is evaluated only when all earlier bodies are true (forall) / false (exists).
                    // The number in the name is the current s.k after computing dbody (line 512).
                    let j = self.z.int_const(&format!("{}!dj{}", x.var, self.k));
                    let mut envj = env.clone();
                    envj.set(&x.var, Val::Int(j.clone()));
                    self.qstack.push(j.clone());
                    let bj = self.ev_ast(&x.body, st, g, false, &envj);
                    self.qstack.pop();
                    let bj = bj?;
                    let cond = self.z.and(&[j.ge(&lo), j.lt(&k)]);
                    let inner = if x.kind == "forall" { bj } else { bj.not() };
                    let prior = self.z.forall(std::slice::from_ref(&j), &cond.implies(&inner), &[]);
                    rng = self.z.and(&[rng, prior]);
                }
                let fa = self.z.forall(std::slice::from_ref(&k), &rng.implies(&dbody), &[]);
                Ok(conj(&self.z, vec![outer, Some(fa)]))
            }
            _ => Ok(None),
        }
    }

    /// verify.py `dom_obligations` (line 524): variant_field → variant_domain, other partial operations → contract_domain.
    fn dom_obligations(&mut self, e: &Expr, st: &mut State, g: &[Ast], env: &Env) -> R<Vec<(Ast, &'static str)>> {
        let mut out: Vec<(Ast, &'static str)> = Vec::new();
        for (kind, code) in [(PKind::Variant, "variant_domain"), (PKind::Other, "contract_domain")] {
            if !has_vf(e, kind) {
                continue;
            }
            let Some(d) = self.dom(e, st, g, env, kind)? else { continue };
            if d.simplify().is_true() {
                continue;
            }
            out.push((d, code));
        }
        Ok(out)
    }

    /// verify.py `check_dom` (line 537): proves D(e) separately per code and returns the domains proved.
    pub(crate) fn check_dom_e(
        &mut self,
        st: &mut State,
        g: &[Ast],
        e: &Expr,
        node: Pos,
        what: &str,
        env: Option<&Env>,
    ) -> R<Vec<Ast>> {
        self.check_dom_cand(st, g, e, node, what, env, None)
    }

    /// `check_dom_e` + STAGE1 B2 candidate ID (`cand`: both the duplicate-suppression key and the recording tag).
    #[allow(clippy::too_many_arguments)]
    pub(crate) fn check_dom_cand(
        &mut self,
        st: &mut State,
        g: &[Ast],
        e: &Expr,
        node: Pos,
        what: &str,
        env: Option<&Env>,
        cand: Option<&str>,
    ) -> R<Vec<Ast>> {
        let envc: Env = match env {
            Some(x) => x.clone(),
            None => st.env.clone(),
        };
        let obs = self.dom_obligations(e, st, g, &envc)?;
        for (d, code) in &obs {
            let w = if *code == "variant_domain" {
                what.to_string()
            } else {
                what.replace(
                    "variant_field lookups",
                    "partial operations (index, /, %, some_val/ok_val/err_val, max/min)",
                )
            };
            self.prove_core_cand(&st.env, &st.pc, g, d, node, code, &w, cand, cand);
        }
        Ok(obs.into_iter().map(|(d, _)| d).collect())
    }

    // =========================================================================================
    // Statements (lines 647-833)
    // =========================================================================================

    /// verify.py `ensures_ok` (line 647).
    fn ensures_ok(&mut self, st: &mut State, val: Option<Val>, node: Pos) -> R<()> {
        let f = self.f.ok_or_else(|| "no function".to_string())?;
        let mut env = st.env.clone();
        for p in &f.params {
            let v = self.params.try_get(&p.name).cloned().ok_or_else(|| format!("'{}'", p.name))?;
            env.set(&p.name, v);
        }
        if let Some(v) = val {
            if !matches!(v, Val::Unit) {
                env.set("result", v);
            }
        }
        let mut prev: Vec<Ast> = Vec::new(); // earlier clauses (domain + value) were proved above and can justify lookups in later clauses
        for en in &f.ensures {
            let what = format!("variant_field lookups in postcondition (line {}) are defined", en.line());
            let ds = self.check_dom_e(st, &prev, en, node, &what, Some(&env))?;
            prev.extend(ds);
            let ob = self.ev_ast(en, st, &[], false, &env)?;
            self.prove_core(&st.env, &st.pc, &[], &ob, node, "ensures", &format!("postcondition (line {})", en.line()), None);
            prev.push(ob);
        }
        Ok(())
    }

    /// verify.py `exec_block` (line 660).
    pub(crate) fn exec_block(&mut self, stmts: &[Stmt], st: State) -> R<Vec<State>> {
        let mut states = vec![st];
        for stmt in stmts {
            // STAGE1 B2: on budget exhaustion or timeout, Python escapes from here via an exception.
            if self.probe_aborted() {
                return Ok(Vec::new());
            }
            let mut nxt: Vec<State> = Vec::new();
            for cur in states {
                nxt.extend(self.exec(stmt, cur)?);
            }
            states = nxt;
            if states.is_empty() {
                break;
            }
        }
        Ok(states)
    }

    /// Let / Assign (lines 711-717).
    fn exec_bind(&mut self, name: &str, value: &Expr, st: State) -> R<Vec<State>> {
        let mut st = st.fork(None);
        let v = self.ev0(value, &mut st, &[], true)?;
        let v = match v {
            Val::Arr(a) => Val::Arr(a.like(a.a.clone(), a.n.clone(), name)),
            other => other,
        };
        st.env.set(name, v);
        Ok(vec![st])
    }

    /// verify.py `exec` (line 710).
    fn exec(&mut self, stmt: &Stmt, st: State) -> R<Vec<State>> {
        if self.probe_aborted() {
            return Ok(Vec::new());
        }
        let model: &'a Model = self.model;
        let spos = stmt_pos(stmt);
        match stmt {
            Stmt::Let(s) => self.exec_bind(&s.name, &s.value, st),
            Stmt::Assign(s) => self.exec_bind(&s.name, &s.value, st),
            Stmt::IndexAssign(s) => {
                let mut st = st.fork(None);
                let arr = st.env.try_get(&s.name).ok_or_else(|| format!("'{}'", s.name))?.try_arr()?.clone();
                let i = self.ev0_ast(&s.index, &mut st, &[], true)?;
                let v = self.ev0_ast(&s.value, &mut st, &[], true)?;
                let ob = self.z.and(&[i.ge_i(0), i.lt(&arr.n)]);
                self.prove_core(
                    &st.env,
                    &st.pc,
                    &[],
                    &ob,
                    spos,
                    "index_oob",
                    &format!("index in bounds for {}[...] =", s.name),
                    None,
                );
                if arr.elem == Elem::U8 {
                    let ob = self.z.and(&[v.ge_i(0), v.le_i(255)]);
                    self.prove_core(
                        &st.env,
                        &st.pc,
                        &[],
                        &ob,
                        spos,
                        "elem_range",
                        &format!("u8 element range 0..=255 for {}[...] =", s.name),
                        None,
                    );
                }
                if let Some((lo, hi, what)) = &s.elem_refine {
                    // refine.rs: one range obligation on the stored value (already computed). No domain check, re-evaluation or forall, and it is not assumed afterwards.
                    let lo: i64 = lo.parse().map_err(|_| format!("refinement bound '{}'", lo))?;
                    let hi: i64 = hi.parse().map_err(|_| format!("refinement bound '{}'", hi))?;
                    let ob = self.z.and(&[v.ge_i(lo), v.le_i(hi)]);
                    self.prove_core(&st.env, &st.pc, &[], &ob, spos, "refinement_assign", what.as_str(), Some(what.as_str()));
                }
                st.env.set(&s.name, Val::Arr(arr.like(arr.a.store(&i, &v), arr.n.clone(), &s.name)));
                Ok(vec![st])
            }
            Stmt::If(s) => {
                let mut st = st.fork(None);
                let c = self.ev0_ast(&s.cond, &mut st, &[], true)?;
                let mut out = self.exec_block(&s.then, st.fork(Some(c.clone())))?;
                out.extend(self.exec_block(&s.els, st.fork(Some(c.not())))?);
                Ok(out)
            }
            Stmt::Match(s) => {
                let mut st = st.fork(None);
                let sv = self.ev0(&s.scrutinee, &mut st, &[], true)?;
                let v = sv.try_ast()?.clone();
                let outer: HashSet<String> = st.env.0.iter().map(|(k, _)| k.clone()).collect();
                let mut out: Vec<State> = Vec::new();
                // G3: the scrutinee's complete (possibly generic) type
                let sty: Option<Ty> = match &sv {
                    Val::Dt(_, t) => Some(t.clone()),
                    _ => None,
                };
                let payload: Ty = match &sty {
                    Some(Ty::Inst(g)) if !g.args.is_empty() && (g.name == "option" || g.name == "result") => {
                        Ty::from_gtype(&g.args[0])
                    }
                    _ => Ty::I64,
                };
                for a in &s.arms {
                    let cond: Ast;
                    let vals: Vec<Ast>;
                    let ftys: Vec<Ty>;
                    if let Some(en) = &a.enum_name {
                        let ety = match &sty {
                            Some(t) if t.name() == en.as_str() => t.clone(),
                            _ => Ty::User(en.clone()),
                        };
                        let vf = model.variant_fns(&ety, &a.ctor)?;
                        cond = vf.rec.apply1(&v);
                        vals = vf.accs.iter().map(|acc| acc.apply1(&v)).collect();
                        ftys = model.fields_of(&ety, Some(&a.ctor))?.into_iter().map(|(_, ft)| ft).collect();
                    } else {
                        let (c, val) = if a.ctor == "Some" || a.ctor == "None" {
                            let o = model.opt(sty.as_ref())?;
                            if a.ctor == "Some" {
                                (o.is_some.apply1(&v), Some(o.sval.apply1(&v)))
                            } else {
                                (o.is_none.apply1(&v), None)
                            }
                        } else {
                            let o = model.res(sty.as_ref())?;
                            if a.ctor == "Ok" {
                                (o.is_ok.apply1(&v), Some(o.oval.apply1(&v)))
                            } else {
                                (o.is_err.apply1(&v), Some(o.eval.apply1(&v)))
                            }
                        };
                        cond = c;
                        vals = val.into_iter().collect();
                        let ft = if a.ctor == "Err" { Ty::I64 } else { payload.clone() };
                        ftys = vals.iter().map(|_| ft.clone()).collect();
                    }
                    let mut b = st.fork(Some(cond));
                    for ((name, val), fty) in a.binders.iter().zip(vals.iter()).zip(ftys.iter()) {
                        b.env.set(name, Val::from_field(fty, val.clone())?);
                        if let Some(w) = self.try_wf(fty, val)? {
                            b.pc.push(w);
                        }
                    }
                    for mut end in self.exec_block(&a.body, b)? {
                        // The binder and the arm's local variables end with the arm; only updates to outer variables remain
                        let drop_keys: Vec<String> =
                            end.env.0.iter().filter(|(k, _)| !outer.contains(k)).map(|(k, _)| k.clone()).collect();
                        for k in drop_keys {
                            end.env.remove(&k);
                        }
                        out.push(end);
                    }
                }
                Ok(out)
            }
            Stmt::FieldAssign(s) => {
                let mut st = st.fork(None);
                let v = self.ev0_ast(&s.value, &mut st, &[], true)?; // right-hand side first, in the state before storing
                let (root, ty) = match st.env.try_get(&s.name) {
                    Some(Val::Dt(r, t)) => (r.clone(), t.clone()),
                    _ => return Err(format!("field assignment on '{}' which is not a struct value", s.name)),
                };
                let path: Vec<&str> = s.fields.iter().map(|f| f.as_str()).collect();
                let new = self.try_rebuild(&ty, &root, &path, &v)?;
                st.env.set(&s.name, Val::Dt(new, ty));
                Ok(vec![st])
            }
            Stmt::Return(s) => {
                let mut st = st.fork(None);
                let v = match &s.value {
                    Some(e) => Some(self.ev0(e, &mut st, &[], true)?),
                    None => None,
                };
                self.ensures_ok(&mut st, v, spos)?;
                Ok(Vec::new())
            }
            Stmt::Assert(s) => {
                let mut st = st;
                self.check_dom_e(&mut st, &[], &s.cond, spos, "variant_field lookups in assertion are defined", None)?;
                let ob = self.ev0_ast(&s.cond, &mut st, &[], false)?;
                match &s.origin_code {
                    None => self.prove_core(&st.env, &st.pc, &[], &ob, spos, "assert", "assertion", None),
                    Some(code) => {
                        // An assert synthesized by refine.rs: its own code and the source description. The description also goes into the duplicate-suppression key,
                        // so multiple points of one annotation are all reported.
                        let what = s.origin_what.as_deref().unwrap_or("");
                        self.prove_core(&st.env, &st.pc, &[], &ob, spos, code, what, Some(what));
                    }
                }
                Ok(vec![st.fork(Some(ob))])
            }
            Stmt::ExprStmt(s) => {
                let mut st = st.fork(None);
                self.ev0(&s.expr, &mut st, &[], true)?;
                Ok(vec![st])
            }
            Stmt::While(w) => {
                let mut st = st;
                self.loop_(w, &mut st)
            }
        }
    }

    /// Loop start state: havoc the assigned variables and assume each invariant's domain (variant) and value.
    fn loop_assume_invariants(&mut self, invs: &[InvRef<'_>], h: &mut State) -> R<()> {
        for &(_cid, inv, _text) in invs {
            let envh = h.env.clone();
            if let Some(d) = self.dom(inv, h, &[], &envh, PKind::Variant)? {
                h.pc.push(d);
            }
            let v = self.ev0_ast(inv, h, &[], false)?;
            h.pc.push(v);
        }
        Ok(())
    }

    /// verify.py `loop` (line 786).
    fn loop_(&mut self, w: &ast::While, st: &mut State) -> R<Vec<State>> {
        if self.probe_aborted() {
            return Ok(Vec::new());
        }
        let dpos = pos(&w.decreases);
        // STAGE1 B2: append this loop's candidates (sorted order) after the written invariants (required refinements → user).
        let extra_here: std::rc::Rc<Vec<ExtraInv>> = if self.extra.is_empty() {
            std::rc::Rc::new(Vec::new())
        } else {
            let n = *self
                .loop_no
                .get(&(w as *const ast::While as usize))
                .ok_or_else(|| "loop number not found".to_string())?;
            match self.extra.get(&n) {
                Some(v) => std::rc::Rc::clone(v),
                None => std::rc::Rc::new(Vec::new()),
            }
        };
        let mut invs: Vec<InvRef<'_>> = w.invariants.iter().map(|i| (None, i, None)).collect();
        for (id, e, t) in extra_here.iter() {
            invs.push((Some(id.as_str()), e, Some(t.as_str())));
        }
        let mut prev: Vec<Ast> = Vec::new(); // invariants in order: an earlier one (proved here) can justify lookups in a later one
        for &(cid, inv, text) in &invs {
            let (w_dom, w_ob) = inv_what(cid, text, "entry");
            let ds = self.check_dom_cand(st, &prev, inv, pos(inv), &w_dom, None, cid)?;
            prev.extend(ds);
            let ob = self.ev0_ast(inv, st, &[], false)?;
            self.prove_core_cand(&st.env, &st.pc, &[], &ob, pos(inv), "invariant_entry", &w_ob, cid, cid);
            prev.push(ob);
        }
        let mut names: BTreeSet<String> = BTreeSet::new();
        assigned(&w.body, &mut names);
        // An arbitrary single iteration: at the start the invariants held (and were defined)
        let mut b = self.havoc_set(st, &names)?;
        self.loop_assume_invariants(&invs, &mut b)?;
        let c = self.ev0_ast(&w.cond, &mut b, &[], true)?;
        b.pc.push(c);
        self.check_dom_e(&mut b, &[], &w.decreases, dpos, "variant_field lookups in decreases are defined", None)?;
        let d0 = self.ev0_ast(&w.decreases, &mut b, &[], false)?;
        let ob = d0.ge_i(0);
        self.prove_core(&b.env, &b.pc, &[], &ob, dpos, "decreases_nonneg", "decreases >= 0", None);
        for mut end in self.exec_block(&w.body, b)? {
            let mut prev: Vec<Ast> = Vec::new();
            for &(cid, inv, text) in &invs {
                let (w_dom, w_ob) = inv_what(cid, text, "preserved");
                let ds = self.check_dom_cand(&mut end, &prev, inv, pos(inv), &w_dom, None, cid)?;
                prev.extend(ds);
                let ob = self.ev0_ast(inv, &mut end, &[], false)?;
                self.prove_core_cand(&end.env, &end.pc, &[], &ob, pos(inv), "invariant_preserved", &w_ob, cid, cid);
                prev.push(ob);
            }
            if has_vf(&w.decreases, PKind::All) {
                // decreases is read at the end of the body: the invariants just proved can justify that lookup
                let mut extra: Vec<Ast> = Vec::new();
                for &(_cid, inv, _text) in &invs {
                    let envp = end.env.clone();
                    if let Some(d) = self.dom(inv, &mut end, &[], &envp, PKind::All)? {
                        extra.push(d);
                    }
                    let v = self.ev0_ast(inv, &mut end, &[], false)?;
                    extra.push(v);
                }
                self.check_dom_e(
                    &mut end,
                    &extra,
                    &w.decreases,
                    dpos,
                    "variant_field lookups in decreases are defined",
                    None,
                )?;
            }
            let dv = self.ev0_ast(&w.decreases, &mut end, &[], false)?;
            let ob = dv.lt(&d0);
            self.prove_core(&end.env, &end.pc, &[], &ob, dpos, "decreases_decrease", "decreases strictly decreases", None);
        }
        // After the loop
        let mut a = self.havoc_set(st, &names)?;
        self.loop_assume_invariants(&invs, &mut a)?;
        let c = self.ev0_ast(&w.cond, &mut a, &[], true)?;
        a.pc.push(c.not());
        Ok(vec![a])
    }

    /// verify.py `run` (line 835).
    pub fn run(&mut self) -> R<()> {
        let f = self.f.ok_or_else(|| "no function".to_string())?;
        let mut env = Env::default();
        let mut pc: Vec<Ast> = Vec::new();
        for p in &f.params {
            let pty = Ty::from_name(&p.ty);
            let v = self.try_fresh(&p.name, &pty)?;
            match &v {
                Val::Arr(a) => {
                    pc.push(self.z.and(&[a.n.ge_i(0), a.n.le_i(MAX_LEN)]));
                    if a.elem == Elem::U8 {
                        pc.push(self.u8_dom(a));
                    }
                }
                other => {
                    if let Some(w) = self.try_wf(&pty, other.try_ast()?)? {
                        pc.push(w);
                    }
                }
            }
            env.set(&p.name, v);
        }
        self.params = env.clone();
        let mut st = State { env, pc };
        for r in &f.requires {
            // D(r) is proved from the preceding requires only, then D(r) && r is assumed in declaration order
            let what = format!("variant_field lookups in requires (line {}) are defined", r.line());
            self.check_dom_e(&mut st, &[], r, pos(r), &what, None)?;
            // Only the variant_field part is assumed: the remaining domains were proved above but are not assumed
            let envc = st.env.clone();
            if let Some(d) = self.dom(r, &mut st, &[], &envc, PKind::Variant)? {
                st.pc.push(d);
            }
            let v = self.ev0_ast(r, &mut st, &[], false)?;
            st.pc.push(v);
        }
        let ret_unit = Ty::from_name(&f.ret) == Ty::Unit;
        let node: Pos = (f.line as u32, f.col as u32);
        for mut end in self.exec_block(&f.body, st)? {
            if ret_unit {
                self.ensures_ok(&mut end, None, node)?;
            }
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reflected_and_literal_comparisons() {
        let z = Z3::new();
        let x = z.int_const("x");
        // If a z3 numeric literal is on the right, reflect (`IntVal(0).__le__(x)`); if it is a Python int, leave as is
        assert_eq!(x.ge(&z.int(0)).sexpr(), "(<= 0 x)");
        assert_eq!(x.ge_i(0).sexpr(), "(>= x 0)");
        assert_eq!(x.ne_i(0).sexpr(), "(distinct x 0)");
    }

    #[test]
    fn int_literals_normalize() {
        assert_eq!(norm_int("+007"), "7");
        assert_eq!(norm_int("-0"), "0");
        assert_eq!(norm_int("-12"), "-12");
        assert_eq!(norm_int("9223372036854775808"), "9223372036854775808");
    }
}
