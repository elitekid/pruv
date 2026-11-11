//! verify.py 의 기호 실행: `Arr`, `State`, `FnVerifier`(fresh, wf, rebuild, havoc, 집계, 식 `ev`, 정의역 `dom`,
//! 문 `exec`, 루프, `run`).
//!
//! 함수 구조·호출 순서·`s.k` 증가 순서·z3 식 생성 순서·보조정리 누적 순서는 verify.py 와 같게 둔다.
//! 주석의 줄 번호는 verify.py 기준이다. 의무(`prove`)·반례·trace 는 obligation.rs.
//!
//! Python 은 `ev(e, st, g, code, env=None)` 에서 `env = st.env` 로 같은 dict 를 읽으면서 `st.pc` 에 덧붙인다.
//! Rust 에서는 `ev` 가 `st: &mut State` 와 별도로 `env: &Env`(진입 때 복제한 스냅샷)를 받는다. `ev` 는 env 를 바꾸지
//! 않으므로 의미가 같다. 반례(`cex`)는 `st.env` 를 읽는다.

use std::collections::{BTreeSet, HashMap, HashSet};
use std::time::Instant;

use pruv_core::ast::{self as ast, Expr, Stmt};
use pruv_core::diagnostic::PruvError;

use crate::model::{Elem, Model, Prelude, Ty, TypeKind};
use crate::obligation::Trace;
use crate::sys::{Ast, FuncDecl, Sort, Z3};

/// (line, col), 1부터.
pub type Pos = (u32, u32);

/// 내부 실패(Python 예외)는 문자열로 올린다.
pub type R<T> = Result<T, String>;

/// verify.py 7행.
pub const MAX_LEN: i64 = 1 << 40;
/// verify.py 8행.
pub const TIMEOUT_MS: u32 = 8000;

/// verify.py `QueryConfig`: solver 질의 한 번의 기록 경계(단계·라운드·자원 한도).
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

/// STAGE1 B2: 추론이 루프에 더하는 후보 한 개 = (후보 ID, 식, 문자열). verify.py `extra` 의 항목.
pub type ExtraInv = (String, Expr, String);
/// STAGE1 B2: 루프 번호 → 그 루프의 후보들(정렬 순서). 비어 있으면 기존 경로.
pub type Extra = HashMap<usize, std::rc::Rc<Vec<ExtraInv>>>;

/// verify.py `BudgetExhausted` / `InferenceTimeout`. Python 은 예외로 `prove` 깊은 곳에서 빠져나오지만 Rust 의
/// `prove` 는 값을 돌려주지 않으므로 `Probe.abort` 에 표시하고, 이후 의무는 질의·기록 없이 지나가며 `exec_block` 이 멈춘다.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum ProbeAbort {
    Budget,
    Timeout,
}

/// verify.py `Probe`: 한 함수의 탐색 상태(모든 회차가 공유).
pub struct Probe {
    pub max_queries: usize,
    pub deadline: Instant,
    /// 지금까지 한 시도 수(예산 계수기)
    pub queries: usize,
    /// 이번 회차에 실패한 후보 {ID: (의무 code, 시도 상태)}
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
    /// verify.py `Probe.tick`: 시도 전에 예산 → 벽시계 → 계수. 넘으면 abort 를 세우고 false.
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

/// verify.py `walk_loops`: (While, 그것이 든 블록, 블록 안 인덱스), 선위 순서(문장 순서, While 은 본문보다 먼저,
/// If then → els, Match 팔 순서). 루프 번호 = 이 열에서의 자리.
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

/// `loop_` 의 불변식 한 항: (후보 ID 또는 None, 식, 후보 문자열 또는 None).
type InvRef<'x> = (Option<&'x str>, &'x Expr, Option<&'x str>);

/// verify.py `loop` 안의 문구: (정의역 what, 의무 what).
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

/// verify.py `in_range` (168행). `x >= I64_MIN` 은 파이썬 int 와의 비교라 뒤집지 않는다(raw).
pub fn in_range(z: &Z3, x: &Ast) -> Ast {
    z.and(&[x.raw_ge(&z.int(i64::MIN)), x.raw_le(&z.int(i64::MAX))])
}

/// verify.py `_conj` (72행): None 은 건너뛰고, 하나면 그대로, 둘 이상이면 And.
pub fn conj(z: &Z3, xs: Vec<Option<Ast>>) -> Option<Ast> {
    let xs: Vec<Ast> = xs.into_iter().flatten().collect();
    match xs.len() {
        0 => None,
        1 => Some(xs[0].clone()),
        _ => Some(z.and(&xs)),
    }
}

/// verify.py `_imp` (79행).
pub fn imp(c: &Ast, d: Option<Ast>) -> Option<Ast> {
    d.map(|d| c.implies(&d))
}

/// 정수 리터럴(부호+십진 문자열)을 Python `str(int)` 꼴로: 앞의 `+`·0 제거, `-0` 은 `0`.
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
// 식 모양 보조 (verify.py 83~132행)
// ---------------------------------------------------------------------------------------------

/// `_partial_here` 의 kind: None=전부, "variant", "other".
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum PKind {
    All,
    Variant,
    Other,
}

fn is_tag_fn(n: &str) -> bool {
    matches!(n, "some_val" | "ok_val" | "err_val")
}

/// verify.py `_partial_here` (86행).
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

/// verify.py `_kids` (103행).
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

/// verify.py `_has_vf` (127행).
pub fn has_vf(e: &Expr, kind: PKind) -> bool {
    if partial_here(e, kind) {
        return true;
    }
    kids(e).into_iter().any(|c| has_vf(c, kind))
}

fn pos(e: &Expr) -> Pos {
    (e.line() as u32, e.col() as u32)
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

/// verify.py `assigned` (671행): 대입되는 이름(Let 은 제외). 이름순 집합이라 havoc 순회가 정렬 순서가 된다.
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
// 값·환경·상태
// ---------------------------------------------------------------------------------------------

#[derive(Clone)]
pub struct Arr {
    pub a: Ast,
    pub n: Ast,
    pub name: String,
    pub elem: Elem,
}

impl Arr {
    /// 순수 조립(fresh 카운터를 건드리지 않는다).
    pub fn new(a: Ast, n: Ast, name: String, elem: Elem) -> Arr {
        Arr { a, n, name, elem }
    }
}

/// 환경 값. verify.py 는 z3 식의 sort 로 Int/Bool/Datatype 을 구분하지만 여기서는 태그로 든다.
#[derive(Clone)]
pub enum Val {
    Int(Ast),
    Bool(Ast),
    /// Opt/Res/사용자 struct·enum 값과 그 Pruv 타입(= `Model.type_of`).
    Dt(Ast, Ty),
    Arr(Arr),
    /// Python `None`(print, unit 함수 호출).
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
    /// 필드 타입이 `ty` 인 접근자 결과 `a` 의 값 태그(z3 sort 로 구분하는 Python 과 같은 분류).
    pub fn from_field(ty: &Ty, a: Ast) -> R<Val> {
        match ty {
            Ty::I64 => Ok(Val::Int(a)),
            Ty::Bool => Ok(Val::Bool(a)),
            Ty::Opt | Ty::Res | Ty::User(_) => Ok(Val::Dt(a, ty.clone())),
            Ty::Array(_) | Ty::Unit => Err(format!("'{}'", ty.name())),
        }
    }
}

/// 삽입 순서를 유지하는 환경(Python dict).
#[derive(Clone, Default)]
pub struct Env(pub Vec<(String, Val)>);

impl Env {
    pub fn get(&self, name: &str) -> &Val {
        self.try_get(name).unwrap_or_else(|| panic!("unbound variable {name}"))
    }
    pub fn try_get(&self, name: &str) -> Option<&Val> {
        self.0.iter().find(|(k, _)| k == name).map(|(_, v)| v)
    }
    /// dict 대입: 이미 있으면 자리를 유지한 채 값만 교체.
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
    /// verify.py `State.fork` (146행).
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

/// verify.py `FnVerifier`(189행). 함수마다 하나, `k`/`seen`/`aggs`/`lemmas` 는 함수 단위.
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
    /// `s.aggs`: (kind, Tc.sexpr(), len(outer)) → F. 삽입 순서 유지(F 이름에 `len(aggs)` 가 들어간다).
    pub(crate) aggs: Vec<((String, String, usize), FuncDecl)>,
    pub lemmas: Vec<Ast>,
    /// `lemma_keys` 의 `(kind, F)` 항목
    pub(crate) lemma_fn_keys: HashSet<(String, String)>,
    /// `lemma_keys` 의 `L.sexpr()` 항목
    pub(crate) lemma_text_keys: HashSet<String>,
    /// `s.params`
    pub params: Env,
    /// `s.errors`(verify_program 이 함수 순서대로 모은다).
    pub errors: Vec<PruvError>,
    /// `s.funcs`: 이름 → 함수(같은 이름이면 뒤의 것).
    pub(crate) funcs: HashMap<String, &'a ast::Function>,
    /// `s.f`: 증명 대상 함수(시제품 경로에서는 None).
    pub(crate) f: Option<&'a ast::Function>,
    /// solver 질의 설정(기본: verification, TIMEOUT_MS, rlimit/seed 없음).
    pub qcfg: QueryConfig,
    /// STAGE1 B2 `extra`: 루프 번호 → 후보들. 비면 기존 경로(fresh 번호·SMT·오류 불변).
    pub extra: Extra,
    /// 루프(While 노드 주소) → 루프 번호. `extra` 가 비어 있지 않을 때만 채운다(`set_extra`).
    pub(crate) loop_no: HashMap<usize, usize>,
    /// STAGE1 B2 탐색 상태. Some 이면 후보 의무만 질의하고 오류는 만들지 않는다.
    pub probe: Option<&'a mut Probe>,
}

impl<'a> FnVerifier<'a> {
    /// 시제품(손 빌더) 경로: 프로그램·함수 없이 조각만 쓴다.
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
        }
    }

    /// verify.py `FnVerifier(.., extra=..)`: 후보를 정하고, 비어 있지 않으면 루프 번호표를 만든다.
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

    // ---------- fresh (201행) ----------
    /// `fresh(base, ty)`: k 를 먼저 올린 뒤 이름 `base!k`; 배열 길이는 `base!k.len`.
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
            Ty::User(name) => match self.model.sort_opt(name) {
                Some(s) => Ok(Val::Dt(z.constant(&n, s), ty.clone())),
                None => Err(format!("fresh: {}", name)),
            },
            Ty::Unit => Err("fresh: unit".to_string()),
        }
    }
    /// 시제품용: 실패하면 `Val::Unit`.
    pub fn fresh(&mut self, base: &str, ty: &Ty) -> Val {
        self.try_fresh(base, ty).unwrap_or(Val::Unit)
    }
    pub fn fresh_int(&mut self, base: &str) -> Ast {
        self.fresh(base, &Ty::I64).ast().clone()
    }

    /// dom() 의 Quant 분기가 만드는 `!dk` 상수는 쓰이지 않아도 `s.k += 1` 은 일어난다(499행).
    pub fn bump_k(&mut self) {
        self.k += 1;
    }

    // ---------- value domain (219행) ----------
    /// `wf(ty, v)`: 활성 leaf 가 전부 i64. 자명하면 None.
    pub fn wf(&self, ty: &Ty, v: &Ast) -> Option<Ast> {
        let z = &self.z;
        let p = self.prelude;
        match ty {
            Ty::I64 => Some(in_range(z, v)),
            Ty::Opt => Some(p.is_some(v).implies(&in_range(z, &p.sval(v)))),
            Ty::Res => Some(z.and(&[
                p.is_ok(v).implies(&in_range(z, &p.oval(v))),
                p.is_err(v).implies(&in_range(z, &p.eval(v))),
            ])),
            Ty::User(name) => match &self.model.decl_opt(name)?.kind {
                TypeKind::Struct(fields) => {
                    let accs = &self.model.struct_fns_opt(name)?.accs;
                    conj(z, fields.iter().zip(accs).map(|(fd, acc)| self.wf(&fd.ty, &acc.apply1(v))).collect())
                }
                TypeKind::Enum(variants) => {
                    let mut parts: Vec<Option<Ast>> = Vec::new();
                    for vd in variants {
                        let vf = self.model.variant_opt(name, &vd.name)?;
                        let w = conj(
                            z,
                            vd.fields.iter().zip(&vf.accs).map(|(fd, acc)| self.wf(&fd.ty, &acc.apply1(v))).collect(),
                        );
                        if let Some(w) = w {
                            parts.push(Some(vf.rec.apply1(v).implies(&w)));
                        }
                    }
                    conj(z, parts)
                }
            },
            Ty::Bool | Ty::Unit | Ty::Array(_) => None,
        }
    }

    /// `rebuild(ty, cur, path, new)` (242행): struct 값 `cur` 의 필드 경로를 `new` 로 바꾼 값.
    pub fn try_rebuild(&self, ty: &Ty, cur: &Ast, path: &[&str], new: &Ast) -> R<Ast> {
        if path.is_empty() {
            return Ok(new.clone());
        }
        let Ty::User(name) = ty else { return Err(format!("'{}'", ty.name())) };
        let i = self.model.field_index_opt(name, path[0]).ok_or_else(|| format!("'{}'", path[0]))?;
        let sf = self.model.struct_fns_opt(name).ok_or_else(|| format!("'{}'", name))?;
        let fields = self.model.struct_fields_opt(name).ok_or_else(|| format!("'{}'", name))?;
        let mut vals: Vec<Ast> = sf.accs.iter().map(|a| a.apply1(cur)).collect();
        let sub = self.try_rebuild(&fields[i].ty, &vals[i], &path[1..], new)?;
        vals[i] = sub;
        Ok(sf.ctor.apply(&vals))
    }

    // ---------- run() 앞부분 (835행): 시제품용 ----------
    /// 매개변수마다 `fresh`, 배열은 `0 <= len <= MAX_LEN`, 그 밖은 `wf` 를 pc 에 넣는다. `self.params` 도 채운다.
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

    /// `ensures_ok` 앞부분(647행): 현재 env 위에 매개변수 원래 값을 덮고 `result` 를 넣는다.
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

    // ---------- ev 조각 (시제품용) ----------
    /// `assume(st, g, fact)` (340행).
    pub fn assume(&self, st: &mut State, g: &[Ast], fact: Ast) {
        if g.is_empty() {
            st.pc.push(fact);
        } else {
            st.pc.push(self.z.and(g).implies(&fact));
        }
    }

    /// Binary `+ - *` (361~385행): 결과를 만들고 `in_range(res)` 의무(code "overflow").
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

    /// Binary `/ %` (373~376행): 의무 `r > 0 && l >= 0` (code "div").
    pub fn ev_div(&mut self, st: &State, g: &[Ast], is_mod: bool, l: &Ast, r: &Ast, node: Pos) -> Ast {
        let ob = self.z.and(&[r.gt_i(0), l.ge_i(0)]);
        self.prove(st, g, &ob, node, "div", None);
        if is_mod {
            l.modulo(r)
        } else {
            l.div(r)
        }
    }

    /// Unary `-` (358~360행).
    pub fn ev_neg(&mut self, st: &State, g: &[Ast], v: &Ast, node: Pos) -> Ast {
        let ob = in_range(&self.z, &v.neg());
        self.prove(st, g, &ob, node, "overflow", None);
        v.neg()
    }

    /// Index (386~395행): 의무 `0 <= i < n` (code "index_oob"), 읽은 값의 `in_range` 를 pc 에 가정.
    pub fn ev_index(&mut self, st: &mut State, g: &[Ast], arr: &Arr, i: &Ast, node: Pos) -> Ast {
        let ob = self.z.and(&[i.ge_i(0), i.lt(&arr.n)]);
        self.prove(st, g, &ob, node, "index_oob", None);
        let v = arr.a.select(i);
        let w = in_range(&self.z, &v);
        self.assume(st, g, w);
        v
    }

    /// Call `alloc(n, init)` (609~613행). `args` = [n, init]. 의무 "alloc_negative" 뒤 `s.k += 1`.
    pub fn ev_alloc(&mut self, st: &State, g: &[Ast], n: &Ast, init: &Ast, node: Pos) -> Arr {
        let ob = self.z.and(&[n.ge_i(0), n.le_i(MAX_LEN)]);
        self.prove(st, g, &ob, node, "alloc_negative", None);
        self.k += 1;
        Arr::new(self.z.const_array(&self.z.int_sort(), init), n.clone(), "alloc".to_string(), Elem::I64)
    }

    // ---------- exec 조각 (시제품용; st 는 호출자가 이미 fork 한 상태) ----------
    /// IndexAssign (718~725행): 의무 `0 <= i < arr.n`("index_oob", node = 문장) 뒤 `Store`.
    pub fn index_assign(&mut self, st: &mut State, name: &str, i: &Ast, v: &Ast, node: Pos) {
        let arr = st.env.get(name).arr().clone();
        let ob = self.z.and(&[i.ge_i(0), i.lt(&arr.n)]);
        self.prove(st, &[], &ob, node, "index_oob", None);
        st.env.set(name, Val::Arr(Arr::new(arr.a.store(i, v), arr.n.clone(), name.to_string(), arr.elem)));
    }

    /// FieldAssign (761~766행): 오른쪽 값 `v` 는 호출자가 먼저 계산한다.
    pub fn field_assign(&mut self, st: &mut State, name: &str, path: &[&str], v: &Ast) {
        let Val::Dt(root, ty) = st.env.get(name).clone() else { panic!("field assign on non-struct") };
        let new = self.try_rebuild(&ty, &root, path, v).unwrap_or_else(|_| v.clone());
        st.env.set(name, Val::Dt(new, ty));
    }

    /// check_dom 한 건 (524~543행): 정의역 `d` 가 None 이거나 `simplify(d)` 가 true 면 질의 없음,
    /// 아니면 `prove(.., code)` 하고 d 를 돌려준다(돌려준 것이 호출자의 `prev` 로 간다).
    pub fn check_dom_one(&mut self, st: &State, g: &[Ast], d: Option<Ast>, node: Pos, code: &str) -> Option<Ast> {
        let d = d?;
        if d.simplify().is_true() {
            return None;
        }
        self.prove(st, g, &d, node, code, None);
        Some(d)
    }

    // ---------- havoc (684행) ----------
    /// 이름순(바이트 순 = 코드포인트 순, Python `sorted`)으로 순회한다(SPEC 6절의 0A 정렬).
    pub fn havoc_set(&mut self, st: &State, names: &BTreeSet<String>) -> R<State> {
        let mut h = st.fork(None);
        for n in names {
            let Some(old) = h.env.try_get(n).cloned() else { continue };
            match old {
                Val::Arr(old_arr) => {
                    let nv = self.try_fresh(n, &Ty::Array(old_arr.elem))?;
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
                    // 집합값: `name!h{k}` 에서 k 는 증가 전 값을 쓰고 그 뒤에 올린다(701~702행).
                    let nv = self.z.constant(&format!("{}!h{}", n, self.k), &old_ast.sort());
                    self.k += 1;
                    h.env.set(n, Val::Dt(nv.clone(), ty.clone()));
                    if let Some(w) = self.wf(&ty, &nv) {
                        h.pc.push(w);
                    }
                }
                Val::Unit => return Err("havoc: None".to_string()),
            }
        }
        Ok(h)
    }

    /// 시제품용: 순서와 상관없이 받고 안에서 정렬한다. 실패하면 forks 만 돌려준다.
    pub fn havoc(&mut self, st: &State, names: &[&str]) -> State {
        let set: BTreeSet<String> = names.iter().map(|s| s.to_string()).collect();
        self.havoc_set(st, &set).unwrap_or_else(|_| st.fork(None))
    }

    // ---------- 양화 조각 (401~417행; 시제품용) ----------
    /// Quant 평가 중간: lo/hi 를 먼저 평가한 뒤 `s.k += 1`, 상수 `var!q{k}`, qstack push. 본문 평가 뒤 `quant_exit`.
    pub fn quant_enter(&mut self, var: &str) -> Ast {
        self.k += 1;
        let k = self.z.int_const(&format!("{}!q{}", var, self.k));
        self.qstack.push(k.clone());
        k
    }
    pub fn quant_exit(&mut self) {
        self.qstack.pop();
    }
    /// `ForAll([k], Implies(And(k >= lo, k < hi), body))` — patterns 없음.
    pub fn forall_q(&self, k: &Ast, lo: &Ast, hi: &Ast, body: &Ast) -> Ast {
        let rng = self.z.and(&[k.ge(lo), k.lt(hi)]);
        self.z.forall(std::slice::from_ref(k), &rng.implies(body), &[])
    }
    /// `Exists([k], And(And(k >= lo, k < hi), body))`.
    pub fn exists_q(&self, k: &Ast, lo: &Ast, hi: &Ast, body: &Ast) -> Ast {
        let rng = self.z.and(&[k.ge(lo), k.lt(hi)]);
        self.z.exists(std::slice::from_ref(k), &self.z.and(&[rng, body.clone()]), &[])
    }

    /// G2 A2: U8 배열의 원소 정의역 `ForAll([k], Implies(And(k >= 0, k < n), And(A[k] >= 0, A[k] <= 255)))`.
    /// 묶인 변수는 고정 이름 `elem!k`(self.k 를 건드리지 않는다). patterns 없음.
    pub fn u8_dom(&self, arr: &Arr) -> Ast {
        let k = self.z.int_const("elem!k");
        let rng = self.z.and(&[k.ge_i(0), k.lt(&arr.n)]);
        let sel = arr.a.select(&k);
        let body = self.z.and(&[sel.ge_i(0), sel.le_i(255)]);
        self.z.forall(std::slice::from_ref(&k), &rng.implies(&body), &[])
    }

    // ---------- 집계 + 보조정리 (545~602행) ----------
    /// sum/count/max/min over lo<=k<hi 를 미해석 함수 `F(lo, hi, *outer)` 와 펼침 보조정리로 옮긴다.
    /// 호출 시점에 `qstack` 에는 이 집계의 자기 변수 `k` 가 이미 빠져 있어야 한다(`quant_exit` 뒤).
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
        // 더 작은 범위의 집계에 원소 x 를 붙인 값. `empty`: 작은 범위가 비어 있음.
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
            // 빈 범위: sum/count 는 0 (새 항을 만들지 않으므로 matching loop 없음)
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
        // 끝을 하나만 옮겨 펼친다: 양화된 보조정리가 자기 출력에 다시 매치되지 않게.
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
    // 식 (345행 `ev`)
    // =========================================================================================

    /// `st.env` 를 스냅샷으로 `ev` (env=None 호출).
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

    /// verify.py `ev(e, st, g, code, env)`. code=True: 증명 의무와 i64 의미 생성.
    pub(crate) fn ev(&mut self, e: &Expr, st: &mut State, g: &[Ast], code: bool, env: &Env) -> R<Val> {
        let model: &'a Model = self.model;
        match e {
            Expr::IntLit(x) => Ok(Val::Int(self.z.int_str(&norm_int(&x.value)))),
            Expr::BoolLit(x) => Ok(Val::Bool(self.z.bool_val(x.value))),
            Expr::StrLit(_) => Err("ev: string literal is not supported yet".to_string()),
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
                    // 두 쪽 모두 z3 식이므로 z3py 반사 규칙(오른쪽이 수 리터럴이면 뒤집힘)을 따르는 eq/ne/lt/..
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
                    // `i >= 0` 은 파이썬 int, `i < arr.n` 은 z3 식끼리(반사 규칙)
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
                // G2 A5: bool 배열은 in_range 가정 없이 Bool 값
                if arr.elem == Elem::Bool {
                    return Ok(Val::Bool(v));
                }
                if code {
                    let w = in_range(&self.z, &v);
                    self.assume(st, g, w);
                }
                Ok(Val::Int(v))
            }
            Expr::Ctor(x) => {
                if x.name == "None" {
                    return Ok(Val::Dt(self.prelude.none(), Ty::Opt));
                }
                let arg = x.arg.as_ref().ok_or_else(|| "None".to_string())?;
                let v = self.ev_ast(arg, st, g, code, env)?;
                match x.name.as_str() {
                    "Some" => Ok(Val::Dt(self.prelude.some(&v), Ty::Opt)),
                    "Ok" => Ok(Val::Dt(self.prelude.ok(&v), Ty::Res)),
                    "Err" => Ok(Val::Dt(self.prelude.err(&v), Ty::Res)),
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
                let sf = model.struct_fns_opt(&x.name).ok_or_else(|| format!("'{}'", x.name))?;
                Ok(Val::Dt(sf.ctor.apply(&vals), Ty::User(x.name.clone())))
            }
            Expr::EnumCtor(x) => {
                let mut vals: Vec<Ast> = Vec::new();
                for a in &x.args {
                    vals.push(self.ev_ast(a, st, g, code, env)?);
                }
                let vf = model.variant_opt(&x.enum_name, &x.variant).ok_or_else(|| format!("'{}'", x.variant))?;
                Ok(Val::Dt(vf.ctor.apply(&vals), Ty::User(x.enum_name.clone())))
            }
            Expr::FieldAccess(x) => {
                let v = self.ev(&x.base, st, g, code, env)?;
                let Val::Dt(va, Ty::User(sname)) = &v else { return Err("field access on a non-struct value".to_string()) };
                let sf = model.struct_fns_opt(sname).ok_or_else(|| format!("'{}'", sname))?;
                let idx = model.field_index_opt(sname, &x.field).ok_or_else(|| format!("'{}'", x.field))?;
                let fty = model
                    .struct_fields_opt(sname)
                    .and_then(|fs| fs.get(idx))
                    .map(|f| f.ty.clone())
                    .ok_or_else(|| format!("'{}'", x.field))?;
                Val::from_field(&fty, sf.accs[idx].apply1(va))
            }
            Expr::IsVariant(x) => {
                let v = self.ev_ast(&x.value, st, g, code, env)?;
                let vf = model.variant_opt(&x.enum_name, &x.variant).ok_or_else(|| format!("'{}'", x.variant))?;
                Ok(Val::Bool(vf.rec.apply1(&v)))
            }
            Expr::VariantField(x) => {
                let v = self.ev_ast(&x.value, st, g, code, env)?;
                let vf = model.variant_opt(&x.enum_name, &x.variant).ok_or_else(|| format!("'{}'", x.variant))?;
                let idx = model
                    .variant_field_index(&x.enum_name, &x.variant, &x.field)
                    .ok_or_else(|| format!("'{}'", x.field))?;
                let fty = model
                    .variant_decl(&x.enum_name, &x.variant)
                    .and_then(|vd| vd.fields.get(idx))
                    .map(|f| f.ty.clone())
                    .ok_or_else(|| format!("'{}'", x.field))?;
                Val::from_field(&fty, vf.accs[idx].apply1(&v))
            }
        }
    }

    /// verify.py `call` (604행).
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
                let aelem = match x.ty.as_deref() {
                    Some("array_u8") => Elem::U8,
                    Some("array_bool") => Elem::Bool, // G2 A5
                    _ => Elem::I64,
                };
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
                return Ok(Val::Arr(Arr::new(
                    self.z.const_array(&self.z.int_sort(), &a1),
                    a0,
                    "alloc".to_string(),
                    aelem,
                )));
            }
            "copy" => {
                let a = arg(0)?.try_arr()?;
                return Ok(Val::Arr(Arr::new(a.a.clone(), a.n.clone(), "copy".to_string(), a.elem)));
            }
            "print" => return Ok(Val::Unit),
            "is_some" => return Ok(Val::Bool(self.prelude.is_some(arg(0)?.try_ast()?))),
            "some_val" => return Ok(Val::Int(self.prelude.sval(arg(0)?.try_ast()?))),
            "is_ok" => return Ok(Val::Bool(self.prelude.is_ok(arg(0)?.try_ast()?))),
            "ok_val" => return Ok(Val::Int(self.prelude.oval(arg(0)?.try_ast()?))),
            "err_val" => return Ok(Val::Int(self.prelude.eval(arg(0)?.try_ast()?))),
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
        if code {
            // 호출 지점은 callee 의 requires 정의역을 증명하지 않는다(callee 자신의 run() 이 이미 증명).
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
        let res = self.try_fresh(&format!("ret_{}", n), &ret)?;
        if let Val::Arr(ra) = &res {
            let w = self.z.and(&[ra.n.ge_i(0), ra.n.le_i(MAX_LEN)]);
            self.assume(st, g, w);
            if ra.elem == Elem::U8 {
                let d = self.u8_dom(ra);
                self.assume(st, g, d);
            }
        } else if let Some(w) = self.wf(&ret, res.try_ast()?) {
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
    // 계약의 정의역 (440~543행)
    // =========================================================================================

    /// verify.py `dom(e, st, g, env, kind)`: 계약 e 의 모든 부분 연산이 정의되는 조건(단락 순서). None=자명.
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
                    let v = self.ev_ast(a0, st, g, false, env)?;
                    parts.push(Some(match x.name.as_str() {
                        "some_val" => self.prelude.is_some(&v),
                        "ok_val" => self.prelude.is_ok(&v),
                        _ => self.prelude.is_ok(&v).not(),
                    }));
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
                let v = self.ev_ast(&x.value, st, g, false, env)?;
                let vf = model.variant_opt(&x.enum_name, &x.variant).ok_or_else(|| format!("'{}'", x.variant))?;
                Ok(conj(&self.z, vec![inner, Some(vf.rec.apply1(&v))]))
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
                    // k 에서의 본문은 앞선 본문이 모두 참(forall)/거짓(exists)일 때만 평가된다.
                    // 이름의 번호는 dbody 계산 뒤의 현재 s.k (512행).
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

    /// verify.py `dom_obligations` (524행): variant_field → variant_domain, 그 밖의 부분 연산 → contract_domain.
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

    /// verify.py `check_dom` (537행): 코드별로 D(e) 를 따로 증명하고 증명한 정의역들을 돌려준다.
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

    /// `check_dom_e` + STAGE1 B2 후보 ID(`cand`: 중복 억제 키이자 기록 꼬리표).
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
    // 문 (647~833행)
    // =========================================================================================

    /// verify.py `ensures_ok` (647행).
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
        let mut prev: Vec<Ast> = Vec::new(); // 앞선 절(정의역+값)은 위에서 증명되어 뒤 절의 조회를 정당화할 수 있다
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

    /// verify.py `exec_block` (660행).
    pub(crate) fn exec_block(&mut self, stmts: &[Stmt], st: State) -> R<Vec<State>> {
        let mut states = vec![st];
        for stmt in stmts {
            // STAGE1 B2: 예산 소진·시간 초과가 나면 Python 은 예외로 여기서 빠져나간다.
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

    /// Let / Assign (711~717행).
    fn exec_bind(&mut self, name: &str, value: &Expr, st: State) -> R<Vec<State>> {
        let mut st = st.fork(None);
        let v = self.ev0(value, &mut st, &[], true)?;
        let v = match v {
            Val::Arr(a) => Val::Arr(Arr::new(a.a, a.n, name.to_string(), a.elem)),
            other => other,
        };
        st.env.set(name, v);
        Ok(vec![st])
    }

    /// verify.py `exec` (710행).
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
                    // refine.rs: 저장 값(이미 계산됨)의 범위 의무 하나. 정의역 검사·재평가·forall 없음, 뒤에 가정하지 않는다.
                    let lo: i64 = lo.parse().map_err(|_| format!("refinement bound '{}'", lo))?;
                    let hi: i64 = hi.parse().map_err(|_| format!("refinement bound '{}'", hi))?;
                    let ob = self.z.and(&[v.ge_i(lo), v.le_i(hi)]);
                    self.prove_core(&st.env, &st.pc, &[], &ob, spos, "refinement_assign", what.as_str(), Some(what.as_str()));
                }
                st.env.set(&s.name, Val::Arr(Arr::new(arr.a.store(&i, &v), arr.n.clone(), s.name.clone(), arr.elem)));
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
                let v = self.ev0_ast(&s.scrutinee, &mut st, &[], true)?;
                let outer: HashSet<String> = st.env.0.iter().map(|(k, _)| k.clone()).collect();
                let mut out: Vec<State> = Vec::new();
                for a in &s.arms {
                    let cond: Ast;
                    let vals: Vec<Ast>;
                    let ftys: Vec<Ty>;
                    if let Some(en) = &a.enum_name {
                        let vf = model.variant_opt(en, &a.ctor).ok_or_else(|| format!("'{}'", a.ctor))?;
                        cond = vf.rec.apply1(&v);
                        vals = vf.accs.iter().map(|acc| acc.apply1(&v)).collect();
                        let vd = model.variant_decl(en, &a.ctor).ok_or_else(|| format!("'{}'", a.ctor))?;
                        ftys = vd.fields.iter().map(|f| f.ty.clone()).collect();
                    } else {
                        let p = self.prelude;
                        let (c, val) = match a.ctor.as_str() {
                            "Some" => (p.is_some(&v), Some(p.sval(&v))),
                            "None" => (p.is_none(&v), None),
                            "Ok" => (p.is_ok(&v), Some(p.oval(&v))),
                            _ => (p.is_err(&v), Some(p.eval(&v))),
                        };
                        cond = c;
                        vals = val.into_iter().collect();
                        ftys = vals.iter().map(|_| Ty::I64).collect();
                    }
                    let mut b = st.fork(Some(cond));
                    for ((name, val), fty) in a.binders.iter().zip(vals.iter()).zip(ftys.iter()) {
                        b.env.set(name, Val::from_field(fty, val.clone())?);
                        if let Some(w) = self.wf(fty, val) {
                            b.pc.push(w);
                        }
                    }
                    for mut end in self.exec_block(&a.body, b)? {
                        // 바인더와 팔의 지역 변수는 팔과 함께 끝난다; 바깥 변수의 갱신만 남는다
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
                let v = self.ev0_ast(&s.value, &mut st, &[], true)?; // 오른쪽 먼저, 저장 전의 상태에서
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
                        // refine.rs 가 합성한 assert: 자기 code 와 원천 설명. 설명이 중복 억제 키에도 들어가
                        // 한 주석의 여러 지점이 모두 보고된다.
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

    /// 루프 시작 상태: 대입되는 변수를 havoc 하고 각 불변식의 정의역(variant)과 값을 가정한다.
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

    /// verify.py `loop` (786행).
    fn loop_(&mut self, w: &ast::While, st: &mut State) -> R<Vec<State>> {
        if self.probe_aborted() {
            return Ok(Vec::new());
        }
        let dpos = pos(&w.decreases);
        // STAGE1 B2: 쓴 불변식(정제 필수 → 사용자) 뒤에 이 루프의 후보(정렬 순서)를 잇는다.
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
        let mut prev: Vec<Ast> = Vec::new(); // 불변식은 차례로: 앞의 것(여기서 증명됨)이 뒤의 조회를 정당화할 수 있다
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
        // 임의의 한 번의 반복: 시작에서 불변식이 성립했고(정의되었고)
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
                // decreases 는 본문 끝에서 읽힌다: 방금 증명한 불변식이 그 조회를 정당화할 수 있다
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
        // 루프 뒤
        let mut a = self.havoc_set(st, &names)?;
        self.loop_assume_invariants(&invs, &mut a)?;
        let c = self.ev0_ast(&w.cond, &mut a, &[], true)?;
        a.pc.push(c.not());
        Ok(vec![a])
    }

    /// verify.py `run` (835행).
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
                    if let Some(w) = self.wf(&pty, other.try_ast()?) {
                        pc.push(w);
                    }
                }
            }
            env.set(&p.name, v);
        }
        self.params = env.clone();
        let mut st = State { env, pc };
        for r in &f.requires {
            // D(r) 는 앞선 requires 만으로 증명하고, 그 뒤 D(r) && r 을 선언 순서대로 가정한다
            let what = format!("variant_field lookups in requires (line {}) are defined", r.line());
            self.check_dom_e(&mut st, &[], r, pos(r), &what, None)?;
            // variant_field 부분만 가정한다: 나머지 정의역은 위에서 증명했지만 가정하지 않는다
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
        // z3 수 리터럴이 오른쪽이면 반사(`IntVal(0).__le__(x)`), 파이썬 int 면 그대로
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
