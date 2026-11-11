//! STAGE1 B2: 템플릿 Houdini 불변식 추론(`--infer`). pruvc/infer.py 를 줄 단위로 옮긴다. 명세: docs/STAGE1_B_INFER.md.
//!
//! 함수마다: 고정 템플릿으로 후보 불변식을 만들고(3절), Houdini 회차를 돈다(4.1): 회차마다 살아 있는 후보 전부를
//! 추가 루프 불변식으로 주고 함수 전체를 검증해, 진입·보존 의무가 증명되지 않은 후보를 뺀다. 아무것도 안 빠지면 끝.
//! 그 뒤 `verify_program_opts` 가 살아남은 후보로 한 번 더 검증한다(4.2).
//!
//! B+ (명세 3.7, 추론 설정 버전 2): 종류 12(값 범위)·13(출력 배열 접두)·14(조기 반환 접두)를 더했다.
//!
//! Python 과 다르게 옮긴 곳:
//! - 정수 계산은 i128(포화 연산). Python 은 임의 정밀도지만 i64 밖의 값은 어차피 후보를 만들지 않는다.
//! - `_Skip` 예외는 `Option` 으로(`None` = 후보를 만들지 않음).
//! - 회차마다 새 z3 컨텍스트·Prelude·Model(같은 seq) 을 만든다(lib.rs 주석).
//! - 예산·시간 초과는 예외 대신 `Probe.abort` 표시(symbolic.rs 의 `ProbeAbort`).

use std::collections::{BTreeSet, HashMap, HashSet};
use std::time::{Duration, Instant};

use pruv_core::ast::{self as ast, Expr, Stmt};
use pruv_core::pyjson::Json;
use pruv_core::refine::pick_bound_name;

use crate::model::{Model, Prelude, TypeDecl};
use crate::obligation::Trace;
use crate::symbolic::{norm_int, walk_loops, Extra, ExtraInv, FnVerifier, Probe, ProbeAbort, QueryConfig, R};
use crate::sys::Z3;

/// INFER_CONFIG
pub const MAX_CANDIDATES: usize = 64; // 루프마다, 정렬·중복 제거 뒤(잘린 수는 `capped`)
pub const MAX_QUERIES: usize = 512; // 함수마다, 모든 solver 시도(보조정리 재시도도 1)
pub const RLIMIT: u32 = 100000;
pub const TIMEOUT_MS: u32 = 500;
pub const SEED: u32 = 0;
pub const MAX_SECONDS: u64 = 5; // 함수마다 벽시계

const I64_MAX: i128 = i64::MAX as i128;

type Rng = (i128, i128);

// ---------------------------------------------------------------------------
// 출력 (3.5)
// ---------------------------------------------------------------------------
fn prec(op: &str) -> u8 {
    match op {
        "==>" => 1,
        "||" => 2,
        "&&" => 3,
        "==" | "!=" | "<" | "<=" | ">" | ">=" => 4,
        "+" | "-" => 5,
        "*" | "/" | "%" => 6,
        _ => 0,
    }
}

fn is_quantifier(e: &Expr) -> bool {
    matches!(e, Expr::Quant(q) if q.kind == "forall" || q.kind == "exists")
}

/// infer.py `show`. None = 출력 함수가 모르는 노드(Python `_Skip`).
pub fn show(e: &Expr) -> Option<String> {
    match e {
        Expr::IntLit(x) => Some(norm_int(&x.value)),
        Expr::BoolLit(x) => Some(if x.value { "true" } else { "false" }.to_string()),
        Expr::Var(x) => Some(x.name.clone()),
        Expr::Unary(x) => {
            let mut o = show(&x.operand)?;
            if matches!(&*x.operand, Expr::Binary(_)) || is_quantifier(&x.operand) {
                o = format!("({})", o);
            }
            Some(format!("{}{}", x.op, o))
        }
        Expr::Binary(x) => {
            let p = prec(&x.op);
            let mut l = show(&x.left)?;
            let mut r = show(&x.right)?;
            if is_quantifier(&x.left) {
                l = format!("({})", l);
            } else if let Expr::Binary(lb) = &*x.left {
                let lp = prec(&lb.op);
                if lp < p || (lp == p && x.op == "==>") {
                    l = format!("({})", l);
                }
            }
            if is_quantifier(&x.right) {
                r = format!("({})", r);
            } else if let Expr::Binary(rb) = &*x.right {
                let rp = prec(&rb.op);
                if rp < p || (rp == p && x.op != "==>") {
                    r = format!("({})", r);
                }
            }
            Some(format!("{} {} {}", l, x.op, r))
        }
        Expr::Index(x) => Some(format!("{}[{}]", show(&x.array)?, show(&x.index)?)),
        Expr::Call(x) => {
            let mut parts: Vec<String> = Vec::new();
            for a in &x.args {
                parts.push(show(a)?);
            }
            Some(format!("{}({})", x.name, parts.join(", ")))
        }
        Expr::Ctor(x) => match &x.arg {
            None => Some(x.name.clone()),
            Some(a) => Some(format!("{}({})", x.name, show(a)?)),
        },
        Expr::Quant(x) => {
            let rng = format!("{} in {}..{}: {}", x.var, show(&x.lo)?, show(&x.hi)?, show(&x.body)?);
            if is_quantifier(e) {
                Some(format!("{} {}", x.kind, rng))
            } else {
                Some(format!("{}({})", x.kind, rng))
            }
        }
        _ => None,
    }
}

// ---------------------------------------------------------------------------
// AST 보조
// ---------------------------------------------------------------------------
/// refine.py `_kids`
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
        Expr::IntLit(_) | Expr::BoolLit(_) | Expr::Var(_) => Vec::new(),
    }
}

// refine.py `_expr_names` / `_stmt_names` / `_fn_names` (pruv_core::refine 에서는 비공개라 그대로 옮겼다)
fn expr_names(e: &Expr, out: &mut HashSet<String>) {
    match e {
        Expr::Var(x) => {
            out.insert(x.name.clone());
        }
        Expr::Call(x) => {
            out.insert(x.name.clone());
        }
        Expr::Quant(x) => {
            out.insert(x.var.clone());
        }
        _ => {}
    }
    for c in kids(e) {
        expr_names(c, out);
    }
}

fn stmt_names(stmts: &[Stmt], out: &mut HashSet<String>) {
    for st in stmts {
        match st {
            Stmt::Let(x) => {
                out.insert(x.name.clone());
                expr_names(&x.value, out);
            }
            Stmt::Assign(x) => {
                out.insert(x.name.clone());
                expr_names(&x.value, out);
            }
            Stmt::FieldAssign(x) => {
                out.insert(x.name.clone());
                expr_names(&x.value, out);
            }
            Stmt::IndexAssign(x) => {
                out.insert(x.name.clone());
                expr_names(&x.index, out);
                expr_names(&x.value, out);
            }
            Stmt::If(x) => {
                expr_names(&x.cond, out);
                stmt_names(&x.then, out);
                stmt_names(&x.els, out);
            }
            Stmt::While(x) => {
                expr_names(&x.cond, out);
                for i in &x.invariants {
                    expr_names(i, out);
                }
                expr_names(&x.decreases, out);
                stmt_names(&x.body, out);
            }
            Stmt::Return(x) => {
                if let Some(v) = &x.value {
                    expr_names(v, out);
                }
            }
            Stmt::Assert(x) => expr_names(&x.cond, out),
            Stmt::ExprStmt(x) => expr_names(&x.expr, out),
            Stmt::Match(x) => {
                expr_names(&x.scrutinee, out);
                for a in &x.arms {
                    for b in &a.binders {
                        out.insert(b.clone());
                    }
                    stmt_names(&a.body, out);
                }
            }
        }
    }
}

fn fn_names(f: &ast::Function) -> HashSet<String> {
    let mut out: HashSet<String> = f.params.iter().map(|p| p.name.clone()).collect();
    for e in f.requires.iter().chain(f.ensures.iter()) {
        expr_names(e, &mut out);
    }
    stmt_names(&f.body, &mut out);
    out
}

/// 구조(위치·검사기 타입 제외)가 같은가: infer.py `_shape(a) == _shape(b)`.
fn shape_eq(a: &Expr, b: &Expr) -> bool {
    match (a, b) {
        (Expr::IntLit(x), Expr::IntLit(y)) => norm_int(&x.value) == norm_int(&y.value),
        (Expr::BoolLit(x), Expr::BoolLit(y)) => x.value == y.value,
        (Expr::Var(x), Expr::Var(y)) => x.name == y.name,
        (Expr::Unary(x), Expr::Unary(y)) => x.op == y.op && shape_eq(&x.operand, &y.operand),
        (Expr::Binary(x), Expr::Binary(y)) => {
            x.op == y.op && shape_eq(&x.left, &y.left) && shape_eq(&x.right, &y.right)
        }
        (Expr::Call(x), Expr::Call(y)) => {
            x.name == y.name && x.args.len() == y.args.len() && x.args.iter().zip(&y.args).all(|(p, q)| shape_eq(p, q))
        }
        (Expr::Index(x), Expr::Index(y)) => shape_eq(&x.array, &y.array) && shape_eq(&x.index, &y.index),
        (Expr::Ctor(x), Expr::Ctor(y)) => {
            x.name == y.name
                && match (&x.arg, &y.arg) {
                    (None, None) => true,
                    (Some(p), Some(q)) => shape_eq(p, q),
                    _ => false,
                }
        }
        (Expr::Quant(x), Expr::Quant(y)) => {
            x.kind == y.kind
                && x.var == y.var
                && shape_eq(&x.lo, &y.lo)
                && shape_eq(&x.hi, &y.hi)
                && shape_eq(&x.body, &y.body)
        }
        (Expr::StructLit(x), Expr::StructLit(y)) => {
            x.name == y.name
                && x.fields.len() == y.fields.len()
                && x.fields.iter().zip(&y.fields).all(|(p, q)| p.name == q.name && shape_eq(&p.value, &q.value))
        }
        (Expr::EnumCtor(x), Expr::EnumCtor(y)) => {
            x.enum_name == y.enum_name
                && x.variant == y.variant
                && x.args.len() == y.args.len()
                && x.args.iter().zip(&y.args).all(|(p, q)| shape_eq(p, q))
        }
        (Expr::FieldAccess(x), Expr::FieldAccess(y)) => x.field == y.field && shape_eq(&x.base, &y.base),
        (Expr::IsVariant(x), Expr::IsVariant(y)) => {
            x.enum_name == y.enum_name && x.variant == y.variant && shape_eq(&x.value, &y.value)
        }
        (Expr::VariantField(x), Expr::VariantField(y)) => {
            x.enum_name == y.enum_name
                && x.variant == y.variant
                && x.field == y.field
                && shape_eq(&x.value, &y.value)
        }
        _ => false,
    }
}

/// infer.py `_free`: e 의 자유 변수 이름(양화 변수는 양화 본문 안에서 묶인다).
fn free(e: &Expr, bound: &mut Vec<String>, out: &mut HashSet<String>) {
    match e {
        Expr::Var(x) => {
            if !bound.iter().any(|b| *b == x.name) {
                out.insert(x.name.clone());
            }
        }
        Expr::Quant(q) => {
            free(&q.lo, bound, out);
            free(&q.hi, bound, out);
            bound.push(q.var.clone());
            free(&q.body, bound, out);
            bound.pop();
        }
        _ => {
            for c in kids(e) {
                free(c, bound, out);
            }
        }
    }
}

fn free_set(e: &Expr) -> HashSet<String> {
    let mut out = HashSet::new();
    free(e, &mut Vec::new(), &mut out);
    out
}

/// Assign / IndexAssign / FieldAssign 참조(중첩 블록 포함).
#[derive(Clone, Copy)]
enum Asg<'s> {
    A(&'s ast::Assign),
    I(&'s ast::IndexAssign),
    F(&'s ast::FieldAssign),
}

impl<'s> Asg<'s> {
    fn name(&self) -> &'s str {
        match self {
            Asg::A(x) => &x.name,
            Asg::I(x) => &x.name,
            Asg::F(x) => &x.name,
        }
    }
}

fn assign_stmts<'s>(stmts: &'s [Stmt], out: &mut Vec<Asg<'s>>) {
    for st in stmts {
        match st {
            Stmt::Assign(x) => out.push(Asg::A(x)),
            Stmt::IndexAssign(x) => out.push(Asg::I(x)),
            Stmt::FieldAssign(x) => out.push(Asg::F(x)),
            Stmt::If(x) => {
                assign_stmts(&x.then, out);
                assign_stmts(&x.els, out);
            }
            Stmt::While(x) => assign_stmts(&x.body, out),
            Stmt::Match(m) => {
                for a in &m.arms {
                    assign_stmts(&a.body, out);
                }
            }
            _ => {}
        }
    }
}

fn assigned(stmts: &[Stmt]) -> BTreeSet<String> {
    let mut v = Vec::new();
    assign_stmts(stmts, &mut v);
    v.iter().map(|a| a.name().to_string()).collect()
}

/// 루프 본문 안에서 선언된 이름(let, match 바인더): 루프 머리에서는 보이지 않는다.
fn locals(stmts: &[Stmt], out: &mut BTreeSet<String>) {
    for st in stmts {
        match st {
            Stmt::Let(x) => {
                out.insert(x.name.clone());
            }
            Stmt::If(x) => {
                locals(&x.then, out);
                locals(&x.els, out);
            }
            Stmt::While(x) => locals(&x.body, out),
            Stmt::Match(m) => {
                for a in &m.arms {
                    for b in &a.binders {
                        out.insert(b.clone());
                    }
                    locals(&a.body, out);
                }
            }
            _ => {}
        }
    }
}

/// infer.py `_init`: block[idx] 의 루프에서 `name` 의 값 = 같은 블록의 가장 가까운 앞선 let/대입. 앞선
/// if/while/match 가 먼저 대입하면, 또는 없으면 None. skip_index: 그 이름의 IndexAssign 은 넘어간다.
fn init<'s>(block: &'s [Stmt], idx: usize, name: &str, skip_index: bool) -> Option<&'s Expr> {
    for j in (0..idx).rev() {
        let st = &block[j];
        match st {
            Stmt::Let(x) if x.name == name => return Some(&x.value),
            Stmt::Assign(x) if x.name == name => return Some(&x.value),
            Stmt::IndexAssign(x) if skip_index && x.name == name => continue,
            Stmt::If(_) | Stmt::While(_) | Stmt::Match(_) => {
                if assigned(std::slice::from_ref(st)).contains(name) {
                    return None;
                }
            }
            _ => {}
        }
    }
    None
}

fn lit_val(x: &ast::IntLit) -> Option<i128> {
    norm_int(&x.value).parse::<i128>().ok()
}

/// infer.py `_lit`: 정수 리터럴(IntLit, 또는 그 단항 마이너스)의 값, 아니면 None.
fn lit(e: &Expr) -> Option<i128> {
    match e {
        Expr::IntLit(x) => lit_val(x),
        Expr::Unary(u) if u.op == "-" => match &*u.operand {
            Expr::IntLit(x) => lit_val(x).map(|v| -v),
            _ => None,
        },
        _ => None,
    }
}

fn is_var(e: &Expr, name: &str) -> bool {
    matches!(e, Expr::Var(x) if x.name == name)
}

fn is_len_var(e: &Expr, m: &BTreeSet<String>) -> bool {
    match e {
        Expr::Call(c) if c.name == "len" && c.args.len() == 1 => {
            matches!(&c.args[0], Expr::Var(v) if !m.contains(&v.name))
        }
        _ => false,
    }
}

/// 루프가 바꾸지 않는 식 (3.1)
fn invariant_expr(e: &Expr, m: &BTreeSet<String>) -> bool {
    if matches!(e, Expr::IntLit(_)) {
        return true;
    }
    if let Expr::Var(x) = e {
        return !m.contains(&x.name);
    }
    if is_len_var(e, m) {
        return true;
    }
    match e {
        Expr::Unary(x) => x.op == "-" && invariant_expr(&x.operand, m),
        Expr::Binary(x) => {
            matches!(x.op.as_str(), "+" | "-" | "*") && invariant_expr(&x.left, m) && invariant_expr(&x.right, m)
        }
        _ => false,
    }
}

fn conj_terms(e: &Expr) -> Vec<&Expr> {
    match e {
        Expr::Binary(b) if b.op == "&&" => {
            let mut v = conj_terms(&b.left);
            v.extend(conj_terms(&b.right));
            v
        }
        _ => vec![e],
    }
}

/// `forall K in 0..len(x): A && B` requires 에서 {배열 이름: (L, U)}(배열마다 처음 것). requires 순서를 유지한다.
fn elem_ranges(f: &ast::Function) -> Vec<(String, Rng)> {
    let mut out: Vec<(String, Rng)> = Vec::new();
    for r in &f.requires {
        let q = match r {
            Expr::Quant(q) if q.kind == "forall" => q,
            _ => continue,
        };
        let lo_zero = matches!(&*q.lo, Expr::IntLit(x) if lit_val(x) == Some(0));
        let x = match &*q.hi {
            Expr::Call(c) if lo_zero && c.name == "len" && c.args.len() == 1 => match &c.args[0] {
                Expr::Var(v) => v.name.clone(),
                _ => continue,
            },
            _ => continue,
        };
        if out.iter().any(|(n, _)| *n == x) {
            continue;
        }
        let body = match &*q.body {
            Expr::Binary(b) if b.op == "&&" => b,
            _ => continue,
        };
        let is_elem = |e: &Expr| -> bool {
            match e {
                Expr::Index(i) => is_var(&i.array, &x) && is_var(&i.index, &q.var),
                _ => false,
            }
        };
        let mut lo: Option<i128> = None;
        let mut hi: Option<i128> = None;
        let mut ok = true;
        for t in [&*body.left, &*body.right] {
            let mut side: Option<(bool, i128)> = None; // (true = lo, 값)
            if let Expr::Binary(tb) = t {
                if tb.op == ">=" || tb.op == "<=" {
                    let lv = lit(&tb.right);
                    let rv = lit(&tb.left);
                    if let (true, Some(v)) = (is_elem(&tb.left), lv) {
                        side = Some((tb.op == ">=", v));
                    } else if let (true, Some(v)) = (is_elem(&tb.right), rv) {
                        side = Some((tb.op != ">=", v));
                    }
                }
            }
            match side {
                None => ok = false,
                Some((true, v)) if lo.is_none() => lo = Some(v),
                Some((false, v)) if hi.is_none() => hi = Some(v),
                Some(_) => ok = false,
            }
        }
        if ok {
            if let (Some(l), Some(h)) = (lo, hi) {
                out.push((x, (l, h)));
            }
        }
    }
    out
}

/// 항의 (하한, 상한) 또는 None (3.1 rng). 계산은 포화 i128.
fn rng(e: &Expr, ranges: &[(String, Rng)], m: &BTreeSet<String>) -> Option<Rng> {
    match e {
        Expr::IntLit(x) => lit_val(x).map(|v| (v, v)),
        Expr::Unary(x) => {
            if x.op != "-" {
                return None;
            }
            let r = rng(&x.operand, ranges, m)?;
            Some((r.1.saturating_neg(), r.0.saturating_neg()))
        }
        Expr::Index(x) => match &*x.array {
            Expr::Var(a) if !m.contains(&a.name) => ranges.iter().find(|(n, _)| *n == a.name).map(|(_, r)| *r),
            _ => None,
        },
        Expr::Binary(x) if matches!(x.op.as_str(), "+" | "-" | "*") => {
            let a = rng(&x.left, ranges, m)?;
            let b = rng(&x.right, ranges, m)?;
            match x.op.as_str() {
                "+" => Some((a.0.saturating_add(b.0), a.1.saturating_add(b.1))),
                "-" => Some((a.0.saturating_sub(b.1), a.1.saturating_sub(b.0))),
                _ => {
                    let ps = [
                        a.0.saturating_mul(b.0),
                        a.0.saturating_mul(b.1),
                        a.1.saturating_mul(b.0),
                        a.1.saturating_mul(b.1),
                    ];
                    Some((*ps.iter().min().unwrap_or(&0), *ps.iter().max().unwrap_or(&0)))
                }
            }
        }
        _ => None,
    }
}

// ---------------------------------------------------------------------------
// 후보 노드 만들기: 모든 노드는 루프 위치(3.4)
// ---------------------------------------------------------------------------
struct Bld {
    line: i64,
    col: i64,
    k: String,
}

impl Bld {
    fn int(&self, n: i128) -> Expr {
        Expr::IntLit(ast::IntLit { line: self.line, col: self.col, value: n.to_string(), ty: None })
    }
    /// 리터럴. |n| > i64 최대면 None(Python `_Skip`). 음수는 단항 마이너스.
    fn lit(&self, n: i128) -> Option<Expr> {
        if n.unsigned_abs() > I64_MAX as u128 {
            return None;
        }
        if n < 0 {
            Some(Expr::Unary(ast::Unary {
                line: self.line,
                col: self.col,
                op: "-".to_string(),
                operand: Box::new(self.int(-n)),
                ty: None,
            }))
        } else {
            Some(self.int(n))
        }
    }
    fn var(&self, n: &str) -> Expr {
        Expr::Var(ast::Var { line: self.line, col: self.col, name: n.to_string(), ty: None })
    }
    fn bin(&self, op: &str, l: Expr, r: Expr) -> Expr {
        Expr::Binary(ast::Binary {
            line: self.line,
            col: self.col,
            op: op.to_string(),
            left: Box::new(l),
            right: Box::new(r),
            ty: None,
        })
    }
    fn not(&self, e: Expr) -> Expr {
        Expr::Unary(ast::Unary {
            line: self.line,
            col: self.col,
            op: "!".to_string(),
            operand: Box::new(e),
            ty: None,
        })
    }
    fn length(&self, n: &str) -> Expr {
        Expr::Call(ast::Call {
            line: self.line,
            col: self.col,
            name: "len".to_string(),
            args: vec![self.var(n)],
            ty: None,
        })
    }
    fn index(&self, a: &str, i: Expr) -> Expr {
        Expr::Index(ast::Index {
            line: self.line,
            col: self.col,
            array: Box::new(self.var(a)),
            index: Box::new(i),
            ty: None,
        })
    }
    fn quant(&self, kind: &str, var: &str, lo: Expr, hi: Expr, body: Expr) -> Expr {
        Expr::Quant(ast::Quant {
            line: self.line,
            col: self.col,
            kind: kind.to_string(),
            var: var.to_string(),
            lo: Box::new(lo),
            hi: Box::new(hi),
            body: Box::new(body),
            ty: None,
        })
    }

    /// e 의 복사본(루프 위치). sub = (이름, 공장): 그 이름의 자유 Var 가 공장() 으로 바뀐다.
    /// Var·Quant 는 새 노드(타입 없음), 그 밖은 원래 노드의 `ty` 를 그대로 가져온다(Python `clone` 과 같다).
    fn clone_e(&self, e: &Expr, sub: Option<(&str, &dyn Fn() -> Expr)>) -> Expr {
        let (line, col) = (self.line, self.col);
        match e {
            Expr::Var(x) => match sub {
                Some((n, f)) if x.name == n => f(),
                _ => Expr::Var(ast::Var { line, col, name: x.name.clone(), ty: None }),
            },
            Expr::Quant(x) => {
                let inner = match sub {
                    Some((n, _)) if x.var == n => None,
                    other => other,
                };
                Expr::Quant(ast::Quant {
                    line,
                    col,
                    kind: x.kind.clone(),
                    var: x.var.clone(),
                    lo: Box::new(self.clone_e(&x.lo, sub)),
                    hi: Box::new(self.clone_e(&x.hi, sub)),
                    body: Box::new(self.clone_e(&x.body, inner)),
                    ty: None,
                })
            }
            Expr::IntLit(x) => Expr::IntLit(ast::IntLit { line, col, value: x.value.clone(), ty: x.ty.clone() }),
            Expr::BoolLit(x) => Expr::BoolLit(ast::BoolLit { line, col, value: x.value, ty: x.ty.clone() }),
            Expr::Unary(x) => Expr::Unary(ast::Unary {
                line,
                col,
                op: x.op.clone(),
                operand: Box::new(self.clone_e(&x.operand, sub)),
                ty: x.ty.clone(),
            }),
            Expr::Binary(x) => Expr::Binary(ast::Binary {
                line,
                col,
                op: x.op.clone(),
                left: Box::new(self.clone_e(&x.left, sub)),
                right: Box::new(self.clone_e(&x.right, sub)),
                ty: x.ty.clone(),
            }),
            Expr::Call(x) => Expr::Call(ast::Call {
                line,
                col,
                name: x.name.clone(),
                args: x.args.iter().map(|a| self.clone_e(a, sub)).collect(),
                ty: x.ty.clone(),
            }),
            Expr::Index(x) => Expr::Index(ast::Index {
                line,
                col,
                array: Box::new(self.clone_e(&x.array, sub)),
                index: Box::new(self.clone_e(&x.index, sub)),
                ty: x.ty.clone(),
            }),
            Expr::Ctor(x) => Expr::Ctor(ast::Ctor {
                line,
                col,
                name: x.name.clone(),
                arg: x.arg.as_ref().map(|a| Box::new(self.clone_e(a, sub))),
                ty: x.ty.clone(),
            }),
            Expr::StructLit(x) => Expr::StructLit(ast::StructLit {
                line,
                col,
                name: x.name.clone(),
                fields: x
                    .fields
                    .iter()
                    .map(|f| ast::FieldInit { line, col, name: f.name.clone(), value: self.clone_e(&f.value, sub) })
                    .collect(),
                ty: x.ty.clone(),
            }),
            Expr::EnumCtor(x) => Expr::EnumCtor(ast::EnumCtor {
                line,
                col,
                enum_name: x.enum_name.clone(),
                variant: x.variant.clone(),
                args: x.args.iter().map(|a| self.clone_e(a, sub)).collect(),
                ty: x.ty.clone(),
            }),
            Expr::FieldAccess(x) => Expr::FieldAccess(ast::FieldAccess {
                line,
                col,
                base: Box::new(self.clone_e(&x.base, sub)),
                field: x.field.clone(),
                ty: x.ty.clone(),
            }),
            Expr::IsVariant(x) => Expr::IsVariant(ast::IsVariant {
                line,
                col,
                value: Box::new(self.clone_e(&x.value, sub)),
                enum_name: x.enum_name.clone(),
                variant: x.variant.clone(),
                ty: x.ty.clone(),
            }),
            Expr::VariantField(x) => Expr::VariantField(ast::VariantField {
                line,
                col,
                value: Box::new(self.clone_e(&x.value, sub)),
                enum_name: x.enum_name.clone(),
                variant: x.variant.clone(),
                field: x.field.clone(),
                ty: x.ty.clone(),
            }),
        }
    }

    fn cl(&self, e: &Expr) -> Expr {
        self.clone_e(e, None)
    }

    /// T[v := k]
    fn at_k(&self, e: &Expr, v: &str) -> Expr {
        let f: &dyn Fn() -> Expr = &|| self.var(&self.k);
        self.clone_e(e, Some((v, f)))
    }
}

// ---------------------------------------------------------------------------
// 후보 생성 (3절)
// ---------------------------------------------------------------------------
struct Cand {
    kind: u32,
    text: String,
    expr: Expr,
}

/// 식 안에 `len` 이 아닌 Call 노드가 있는가(사용자 함수·alloc·copy·print·is_some 등). 있으면 후보를 만들지 않는다:
/// 계약 문맥에서 callee requires 가 검사되지 않고 ensures 가 가정되어 경로 조건이 오염되기 때문.
fn has_non_len_call(e: &Expr) -> bool {
    if let Expr::Call(c) = e {
        if c.name != "len" {
            return true;
        }
    }
    kids(e).into_iter().any(has_non_len_call)
}

fn push(out: &mut Vec<Cand>, kind: u32, e: Option<Expr>) {
    if let Some(e) = e {
        if has_non_len_call(&e) {
            return;
        }
        if let Some(text) = show(&e) {
            out.push(Cand { kind, text, expr: e });
        }
    }
}

/// 후보 식의 왼쪽 N: lo 가 IntLit 0 이면 v, 아니면 v - lo
fn n_of(b: &Bld, v: &str, lo: &Expr) -> Expr {
    if matches!(lo, Expr::IntLit(x) if lit_val(x) == Some(0)) {
        b.var(v)
    } else {
        b.bin("-", b.var(v), b.cl(lo))
    }
}

/// c0 == 0 이면 t, 아니면 c0 + t
fn with_c0(b: &Bld, c0: i128, t: Expr) -> Option<Expr> {
    if c0 == 0 {
        Some(t)
    } else {
        Some(b.bin("+", b.lit(c0)?, t))
    }
}

/// 계수 c * N: c == 0 이면 0, c == 1 이면 N
fn coef(b: &Bld, c: i128, n: Expr) -> Option<Expr> {
    if c == 0 {
        b.lit(0)
    } else if c == 1 {
        Some(n)
    } else {
        Some(b.bin("*", b.lit(c)?, n))
    }
}

/// `s = s + T` / `s = T + s` → (s, T)
fn acc(st: &ast::Assign) -> Option<(&str, &Expr)> {
    if let Expr::Binary(b) = &st.value {
        if b.op == "+" {
            if is_var(&b.left, &st.name) {
                return Some((&st.name, &b.right));
            }
            if is_var(&b.right, &st.name) {
                return Some((&st.name, &b.left));
            }
        }
    }
    None
}

/// "max" / "min": X 가 T 와 Var m 을 최대/최소 꼴로 비교하면.
fn maxmin(x: &Expr, m: &str, t: &Expr) -> Option<&'static str> {
    let xb = match x {
        Expr::Binary(b) => b,
        _ => return None,
    };
    if is_var(&xb.right, m) && shape_eq(&xb.left, t) {
        if xb.op == ">" || xb.op == ">=" {
            return Some("max");
        }
        if xb.op == "<" || xb.op == "<=" {
            return Some("min");
        }
    }
    if is_var(&xb.left, m) && shape_eq(&xb.right, t) {
        if xb.op == "<" || xb.op == "<=" {
            return Some("max");
        }
        if xb.op == ">" || xb.op == ">=" {
            return Some("min");
        }
    }
    None
}

/// 루프 w 의 후보 [(종류, 문자열, 식)] (정렬 전, 중복 있을 수 있음).
/// 3.1 카운터 정의: (pos(v), 증가폭 c, lo = init(v)). 아니면 None.
fn counter_info<'a>(
    w: &'a ast::While,
    asg: &[Asg<'a>],
    m: &BTreeSet<String>,
    block: &'a [Stmt],
    idx: usize,
    v: &str,
) -> Option<(usize, i128, &'a Expr)> {
    let mine: Vec<Asg<'a>> = asg.iter().filter(|s| s.name() == v).copied().collect();
    if mine.len() != 1 {
        return None;
    }
    let st = match mine[0] {
        Asg::A(a) => a,
        _ => return None,
    };
    let mut pos: Option<usize> = None;
    for (j, bs) in w.body.iter().enumerate() {
        if let Stmt::Assign(x) = bs {
            if std::ptr::eq(x, st) {
                pos = Some(j);
            }
        }
    }
    let pos = pos?;
    let c = match &st.value {
        Expr::Binary(bv) if bv.op == "+" && is_var(&bv.left, v) => match &*bv.right {
            Expr::IntLit(x) => lit_val(x).filter(|n| *n >= 1)?,
            _ => return None,
        },
        _ => return None,
    };
    let lo = init(block, idx, v, false)?;
    if !invariant_expr(lo, m) {
        return None;
    }
    Some((pos, c, lo))
}

/// 3.7 srng(p): f.requires 의 최상위 && 항에서 p 의 (하한, 상한), 각각 처음 찾은 것.
fn srng(p: &str, f: &ast::Function) -> (Option<i128>, Option<i128>) {
    let mut lo: Option<i128> = None;
    let mut hi: Option<i128> = None;
    for r in &f.requires {
        for t in conj_terms(r) {
            let tb = match t {
                Expr::Binary(x) => x,
                _ => continue,
            };
            let lp = is_var(&tb.left, p);
            let rp = is_var(&tb.right, p);
            let lv = lit(&tb.left);
            let rv = lit(&tb.right);
            // (하한이면 true, 값)
            let found: Option<(bool, i128)> = match tb.op.as_str() {
                ">=" => match (lp, rv, rp, lv) {
                    (true, Some(c), _, _) => Some((true, c)),
                    (_, _, true, Some(c)) => Some((false, c)),
                    _ => None,
                },
                ">" => match (lp, rv, rp, lv) {
                    (true, Some(c), _, _) => Some((true, c.saturating_add(1))),
                    (_, _, true, Some(c)) => Some((false, c.saturating_sub(1))),
                    _ => None,
                },
                "<=" => match (lp, rv, rp, lv) {
                    (true, Some(c), _, _) => Some((false, c)),
                    (_, _, true, Some(c)) => Some((true, c)),
                    _ => None,
                },
                "<" => match (lp, rv, rp, lv) {
                    (true, Some(c), _, _) => Some((false, c.saturating_sub(1))),
                    (_, _, true, Some(c)) => Some((true, c.saturating_add(1))),
                    _ => None,
                },
                _ => None,
            };
            match found {
                Some((true, c)) if lo.is_none() => lo = Some(c),
                Some((false, c)) if hi.is_none() => hi = Some(c),
                _ => {}
            }
        }
    }
    (lo, hi)
}

/// 3.7 irng(e): 시작값 식의 (하한, 상한).
fn irng(
    e: &Expr,
    f: &ast::Function,
    ranges: &[(String, Rng)],
    m: &BTreeSet<String>,
) -> (Option<i128>, Option<i128>) {
    if let Some(n) = lit(e) {
        return (Some(n), Some(n));
    }
    match e {
        Expr::Var(p) if !m.contains(&p.name) => srng(&p.name, f),
        Expr::Index(x) => match &*x.array {
            Expr::Var(a) if !m.contains(&a.name) => match ranges.iter().find(|(n, _)| *n == a.name) {
                Some((_, (l, u))) => (Some(*l), Some(*u)),
                None => (None, None),
            },
            _ => (None, None),
        },
        _ => (None, None),
    }
}

fn gen(
    w: &ast::While,
    block: &[Stmt],
    idx: usize,
    kname: &str,
    ranges: &[(String, Rng)],
    f: &ast::Function,
) -> Vec<Cand> {
    let b = Bld { line: w.line, col: w.col, k: kname.to_string() };
    let m = assigned(&w.body);
    let mut loc: BTreeSet<String> = BTreeSet::new();
    locals(&w.body, &mut loc);
    let ns: BTreeSet<String> = m.union(&loc).cloned().collect();
    let mut asg: Vec<Asg> = Vec::new();
    assign_stmts(&w.body, &mut asg);
    let count_of = |name: &str| asg.iter().filter(|a| a.name() == name).count();
    let mut out: Vec<Cand> = Vec::new();

    // e 에 v 가 나오고 다른 자유 이름은 모두 M 밖이고 루프 본문에서 선언되지 않았다
    let stable = |e: &Expr, v: &str| -> bool {
        let names = free_set(e);
        names.contains(v) && !names.iter().any(|n| n != v && ns.contains(n))
    };

    // ---- 카운터 ----
    for v in &m {
        let mine: Vec<Asg> = asg.iter().filter(|s| s.name() == v.as_str()).copied().collect();
        if mine.len() != 1 {
            continue;
        }
        let st = match mine[0] {
            Asg::A(a) => a,
            _ => continue,
        };
        let mut pos: Option<usize> = None;
        for (j, bs) in w.body.iter().enumerate() {
            if let Stmt::Assign(x) = bs {
                if std::ptr::eq(x, st) {
                    pos = Some(j);
                }
            }
        }
        let pos = match pos {
            Some(p) => p,
            None => continue,
        };
        let step_ok = match &st.value {
            Expr::Binary(bv) => {
                bv.op == "+"
                    && is_var(&bv.left, v)
                    && matches!(&*bv.right, Expr::IntLit(x) if lit_val(x).map_or(false, |n| n >= 1))
            }
            _ => false,
        };
        if !step_ok {
            continue;
        }
        let lo = match init(block, idx, v, false) {
            Some(l) if invariant_expr(l, &m) => l,
            _ => continue,
        };
        let lov = lit(lo);

        // 종류 1
        push(&mut out, 1, Some(b.bin("<=", b.cl(lo), b.var(v))));
        // 종류 2, 3: 루프 조건의 경계 식
        for t in conj_terms(&w.cond) {
            let tb = match t {
                Expr::Binary(x) => x,
                _ => continue,
            };
            let (e_opt, plus1): (Option<&Expr>, bool) = match tb.op.as_str() {
                "<" if is_var(&tb.left, v) => (Some(&*tb.right), false),
                ">" if is_var(&tb.right, v) => (Some(&*tb.left), false),
                "<=" if is_var(&tb.left, v) => (Some(&*tb.right), true),
                ">=" if is_var(&tb.right, v) => (Some(&*tb.left), true),
                _ => (None, false),
            };
            let e = match e_opt {
                Some(e) if invariant_expr(e, &m) => e,
                _ => continue,
            };
            let up = || -> Expr {
                let x = b.cl(e);
                if plus1 {
                    b.bin("+", x, b.int(1))
                } else {
                    x
                }
            };
            push(&mut out, 2, Some(b.bin("<=", b.var(v), up())));
            if lov.is_some() {
                push(
                    &mut out,
                    3,
                    Some(b.bin("||", b.bin("<=", b.var(v), up()), b.bin("==", b.var(v), b.cl(lo)))),
                );
            }
        }

        // ---- pos(v) 앞의 누적 문장 ----
        for st2 in &w.body[..pos] {
            match st2 {
                // 단순 합: s = s + T | s = T + s
                Stmt::Assign(a2) => {
                    if let Some((s_name, t)) = acc(a2) {
                        let c0 = init(block, idx, s_name, false).and_then(lit);
                        if let Some(c0) = c0 {
                            if s_name != v.as_str() && count_of(s_name) == 1 && stable(t, v) {
                                let sum = b.quant("sum", kname, b.cl(lo), b.var(v), b.at_k(t, v));
                                push(
                                    &mut out,
                                    6,
                                    with_c0(&b, c0, sum).map(|rhs| b.bin("==", b.var(s_name), rhs)),
                                );
                                if let Some(r) = rng(t, ranges, &m) {
                                    push(
                                        &mut out,
                                        11,
                                        coef(&b, r.0, n_of(&b, v, lo))
                                            .and_then(|x| with_c0(&b, c0, x))
                                            .map(|rhs| b.bin(">=", b.var(s_name), rhs)),
                                    );
                                    push(
                                        &mut out,
                                        11,
                                        coef(&b, r.1, n_of(&b, v, lo))
                                            .and_then(|x| with_c0(&b, c0, x))
                                            .map(|rhs| b.bin("<=", b.var(s_name), rhs)),
                                    );
                                }
                            }
                        }
                    }
                }
                // 조건부 누적 / 최대 / 최소: if X { ... }
                Stmt::If(i2) if i2.els.is_empty() && i2.then.len() == 1 && matches!(i2.then[0], Stmt::Assign(_)) => {
                    let inner = match &i2.then[0] {
                        Stmt::Assign(x) => x,
                        _ => continue,
                    };
                    if let Some((s_name, t)) = acc(inner) {
                        let c0 = init(block, idx, s_name, false).and_then(lit);
                        let is_count = matches!(t, Expr::IntLit(x) if lit_val(x) == Some(1));
                        if let Some(c0) = c0 {
                            if s_name != v.as_str()
                                && count_of(s_name) == 1
                                && stable(&i2.cond, v)
                                && (is_count || stable(t, v))
                            {
                                if is_count {
                                    let cnt = b.quant("count", kname, b.cl(lo), b.var(v), b.at_k(&i2.cond, v));
                                    push(
                                        &mut out,
                                        7,
                                        with_c0(&b, c0, cnt).map(|rhs| b.bin("==", b.var(s_name), rhs)),
                                    );
                                    push(&mut out, 11, b.lit(c0).map(|l| b.bin(">=", b.var(s_name), l)));
                                    push(
                                        &mut out,
                                        11,
                                        with_c0(&b, c0, n_of(&b, v, lo)).map(|rhs| b.bin("<=", b.var(s_name), rhs)),
                                    );
                                } else if let Some(r) = rng(t, ranges, &m) {
                                    let r = (r.0.min(0), r.1.max(0));
                                    push(
                                        &mut out,
                                        11,
                                        coef(&b, r.0, n_of(&b, v, lo))
                                            .and_then(|x| with_c0(&b, c0, x))
                                            .map(|rhs| b.bin(">=", b.var(s_name), rhs)),
                                    );
                                    push(
                                        &mut out,
                                        11,
                                        coef(&b, r.1, n_of(&b, v, lo))
                                            .and_then(|x| with_c0(&b, c0, x))
                                            .map(|rhs| b.bin("<=", b.var(s_name), rhs)),
                                    );
                                }
                            }
                        }
                    }
                    // 최대 / 최소: if X { m = T; }
                    let mname = inner.name.as_str();
                    let tt = &inner.value;
                    let fr = free_set(tt);
                    if mname != v.as_str()
                        && count_of(mname) == 1
                        && fr.contains(v)
                        && !fr.iter().any(|n| loc.contains(n))
                    {
                        if let Some(kind) = maxmin(&i2.cond, mname, tt) {
                            // None = 아래 경계 lo, Some(n) = 리터럴 n
                            let mut bs: Vec<Option<i128>> = vec![None];
                            let initm = init(block, idx, mname, false);
                            if let (Some(lv), Some(im)) = (lov, initm) {
                                if lv >= 1 {
                                    let n1 = lv - 1;
                                    let f: &dyn Fn() -> Expr = &|| b.int(n1);
                                    if shape_eq(im, &b.clone_e(tt, Some((v.as_str(), f)))) {
                                        bs.push(Some(n1));
                                    }
                                }
                            }
                            let cmp = if kind == "max" { "<=" } else { ">=" };
                            let bound = |bo: Option<i128>| -> Option<Expr> {
                                match bo {
                                    None => Some(b.cl(lo)),
                                    Some(n) => b.lit(n),
                                }
                            };
                            for bo in bs {
                                let e8 = (|| -> Option<Expr> {
                                    Some(b.bin(
                                        "==>",
                                        b.bin("<", bound(bo)?, b.var(v)),
                                        b.bin(
                                            "==",
                                            b.var(mname),
                                            b.quant(kind, kname, bound(bo)?, b.var(v), b.at_k(tt, v)),
                                        ),
                                    ))
                                })();
                                push(&mut out, 8, e8);
                                let e9 = (|| -> Option<Expr> {
                                    Some(b.quant(
                                        "forall",
                                        kname,
                                        bound(bo)?,
                                        b.var(v),
                                        b.bin(cmp, b.at_k(tt, v), b.var(mname)),
                                    ))
                                })();
                                push(&mut out, 9, e9);
                                let e10 = (|| -> Option<Expr> {
                                    Some(b.bin(
                                        "==>",
                                        b.bin("<", bound(bo)?, b.var(v)),
                                        b.quant(
                                            "exists",
                                            kname,
                                            bound(bo)?,
                                            b.var(v),
                                            b.bin("==", b.at_k(tt, v), b.var(mname)),
                                        ),
                                    ))
                                })();
                                push(&mut out, 10, e10);
                            }
                        }
                    }
                }
                _ => {}
            }
        }
    }

    // ---- B+ (명세 3.7, 버전 2): 종류 12, 13, 14 ----
    // 카운터 집합 CTR (3.1 정의 전부, 이름 정렬 순)
    let mut ctr: Vec<(&String, usize, i128, &Expr)> = Vec::new();
    for v in &m {
        if let Some((pos, c, lo)) = counter_info(w, &asg, &m, block, idx, v) {
            ctr.push((v, pos, c, lo));
        }
    }

    // 종류 12: 카운터가 아닌 스칼라의 시작 범위
    for v in &m {
        if ctr.iter().any(|(n, _, _, _)| *n == v) {
            continue;
        }
        if !asg.iter().filter(|s| s.name() == v.as_str()).all(|s| matches!(s, Asg::A(_))) {
            continue;
        }
        let iv = match init(block, idx, v, false) {
            Some(e) => e,
            None => continue,
        };
        let (lb, ub) = irng(iv, f, ranges, &m);
        if let Some(l) = lb {
            push(&mut out, 12, b.lit(l).map(|x| b.bin(">=", b.var(v), x)));
        }
        if let Some(u) = ub {
            push(&mut out, 12, b.lit(u).map(|x| b.bin("<=", b.var(v), x)));
        }
    }

    // 종류 13, 14
    for (v, pos, c, lo) in &ctr {
        if *c != 1 {
            continue;
        }
        let v: &str = v.as_str();
        for st2 in &w.body[..*pos] {
            match st2 {
                // 13: 출력 배열 접두 `b[v] = E;`
                Stmt::IndexAssign(ia) if is_var(&ia.index, v) => {
                    let bn = ia.name.as_str();
                    if count_of(bn) != 1 {
                        continue;
                    }
                    if !asg.iter().filter(|s| s.name() == bn).all(|s| matches!(s, Asg::I(_))) {
                        continue;
                    }
                    let init_ok = match init(block, idx, bn, true) {
                        Some(Expr::Call(cl)) => {
                            (cl.name == "alloc" && cl.args.len() == 2 && invariant_expr(&cl.args[0], &m))
                                || (cl.name == "copy"
                                    && cl.args.len() == 1
                                    && matches!(&cl.args[0], Expr::Var(x) if !m.contains(&x.name)))
                        }
                        _ => false,
                    };
                    if !init_ok {
                        continue;
                    }
                    let fe = free_set(&ia.value);
                    if fe.iter().any(|n| n != v && ns.contains(n)) {
                        continue;
                    }
                    push(
                        &mut out,
                        13,
                        Some(b.quant(
                            "forall",
                            kname,
                            b.cl(lo),
                            b.var(v),
                            b.bin("==", b.index(bn, b.var(kname)), b.at_k(&ia.value, v)),
                        )),
                    );
                }
                // 14: 조기 반환 접두 `if C { return R; }`
                Stmt::If(i2)
                    if i2.els.is_empty() && i2.then.len() == 1 && matches!(i2.then[0], Stmt::Return(_)) =>
                {
                    if stable(&i2.cond, v) {
                        push(
                            &mut out,
                            14,
                            Some(b.quant("forall", kname, b.cl(lo), b.var(v), b.not(b.at_k(&i2.cond, v)))),
                        );
                    }
                }
                _ => {}
            }
        }
    }

    // ---- 원소 저장으로만 쓰이는 배열 (종류 4, 5) ----
    for bn in &m {
        let all_index = asg.iter().filter(|s| s.name() == bn.as_str()).all(|s| matches!(s, Asg::I(_)));
        if !all_index {
            continue;
        }
        let init_e = match init(block, idx, bn, true) {
            Some(Expr::Call(c)) => c,
            _ => continue,
        };
        let c: Option<i128>;
        let e_node: Expr;
        if init_e.name == "alloc" && init_e.args.len() == 2 && invariant_expr(&init_e.args[0], &m) {
            e_node = init_e.args[0].clone();
            c = lit(&init_e.args[1]);
        } else if init_e.name == "copy"
            && init_e.args.len() == 1
            && matches!(&init_e.args[0], Expr::Var(x) if !m.contains(&x.name))
        {
            let an = match &init_e.args[0] {
                Expr::Var(x) => x.name.as_str(),
                _ => continue,
            };
            e_node = b.length(an);
            c = None;
        } else {
            continue;
        }
        push(&mut out, 4, Some(b.bin("==", b.length(bn), b.cl(&e_node))));
        let mut pairs: Vec<Rng> = Vec::new();
        for (_, (lo_, hi_)) in ranges {
            let p = match c {
                Some(cv) => ((*lo_).min(cv), (*hi_).max(cv)),
                None => (*lo_, *hi_),
            };
            if !pairs.contains(&p) {
                pairs.push(p);
            }
        }
        if pairs.is_empty() {
            if let Some(cv) = c {
                pairs.push((cv, cv));
            }
        }
        for (lo_, hi_) in pairs {
            let e5 = (|| -> Option<Expr> {
                Some(b.quant(
                    "forall",
                    kname,
                    b.lit(0)?,
                    b.length(bn),
                    b.bin(
                        "&&",
                        b.bin("<=", b.lit(lo_)?, b.index(bn, b.var(kname))),
                        b.bin("<=", b.index(bn, b.var(kname)), b.lit(hi_)?),
                    ),
                ))
            })();
            push(&mut out, 5, e5);
        }
    }
    out
}

/// (정렬·중복 제거·자른 후보, 자르기 전 수 `generated`, 잘린 수 `capped`)
fn candidates_for_loop(
    w: &ast::While,
    block: &[Stmt],
    idx: usize,
    kname: &str,
    ranges: &[(String, Rng)],
    f: &ast::Function,
) -> (Vec<Cand>, usize, usize) {
    let mut raw = gen(w, block, idx, kname, ranges, f);
    raw.sort_by(|a, b| (a.kind, &a.text).cmp(&(b.kind, &b.text)));
    let mut seen: HashSet<String> = HashSet::new();
    let mut uniq: Vec<Cand> = Vec::new();
    for c in raw {
        if seen.insert(c.text.clone()) {
            uniq.push(c);
        }
    }
    let generated = uniq.len();
    let capped = generated.saturating_sub(MAX_CANDIDATES);
    uniq.truncate(MAX_CANDIDATES);
    (uniq, generated, capped)
}

// ---------------------------------------------------------------------------
// Houdini 구동 (4.1) 과 보고 (5)
// ---------------------------------------------------------------------------
/// 빠진 후보 한 개의 기록
pub struct Dropped {
    pub cand: String,
    pub text: String,
    pub round: u32,
    pub code: String,
    pub status: String,
}

pub struct LoopInfo {
    pub n: usize,
    pub line: i64,
    pub col: i64,
    pub generated: usize,
    pub capped: usize,
    /// 살아 있는 후보 (ID, 식, 문자열)
    pub alive: Vec<ExtraInv>,
    pub dropped: Vec<Dropped>,
    /// 처음 후보 목록(자른 뒤, 순위 순)의 (종류 번호, 후보). 버전 1 되돌림(4.1)이 쓴다.
    pub initial: Vec<(u32, ExtraInv)>,
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum InferStatus {
    Ok,
    BudgetExhausted,
    Timeout,
}

impl InferStatus {
    fn as_str(self) -> &'static str {
        match self {
            InferStatus::Ok => "ok",
            InferStatus::BudgetExhausted => "budget_exhausted",
            InferStatus::Timeout => "timeout",
        }
    }
}

pub struct InferResult {
    pub fname: String,
    pub loops: Vec<LoopInfo>,
    pub status: InferStatus,
    pub rounds: u32,
    pub queries: usize,
    /// 버전 1 되돌림을 했는가(4.1)
    pub fallback: bool,
}

impl InferResult {
    /// {루프 번호: 살아남은 후보들}. 후보가 없는 루프는 없다(전부 비면 빈 표).
    pub fn extra(&self) -> Extra {
        let mut m: Extra = HashMap::new();
        for l in &self.loops {
            if !l.alive.is_empty() {
                m.insert(l.n, std::rc::Rc::new(l.alive.clone()));
            }
        }
        m
    }

    /// 루프마다 보고 레코드 하나. new_errors = 이 함수의 최종 검증 오류 수.
    pub fn records(&self, new_errors: usize) -> Vec<Json> {
        let mut out = Vec::new();
        for l in &self.loops {
            let status = if l.generated == 0 {
                "none"
            } else if self.status != InferStatus::Ok {
                self.status.as_str()
            } else if new_errors == 0 {
                "verified"
            } else {
                "selected"
            };
            let invariants: Vec<Json> =
                l.alive.iter().map(|(_, _, text)| Json::Str(format!("invariant {}", text))).collect();
            let dropped: Vec<Json> = l
                .dropped
                .iter()
                .map(|d| {
                    Json::Obj(vec![
                        ("cand".to_string(), Json::Str(d.cand.clone())),
                        ("text".to_string(), Json::Str(d.text.clone())),
                        ("round".to_string(), Json::int(d.round as i64)),
                        ("code".to_string(), Json::Str(d.code.clone())),
                        ("status".to_string(), Json::Str(d.status.clone())),
                    ])
                })
                .collect();
            let mut rec = vec![
                ("fn".to_string(), Json::Str(self.fname.clone())),
                ("loop".to_string(), Json::int(l.n as i64)),
                ("line".to_string(), Json::int(l.line)),
                ("col".to_string(), Json::int(l.col)),
                ("status".to_string(), Json::str(status)),
                ("invariants".to_string(), Json::Arr(invariants)),
                ("generated".to_string(), Json::int(l.generated as i64)),
                ("capped".to_string(), Json::int(l.capped as i64)),
                ("kept".to_string(), Json::int(l.alive.len() as i64)),
                ("dropped".to_string(), Json::Arr(dropped)),
                ("rounds".to_string(), Json::int(self.rounds as i64)),
                ("queries".to_string(), Json::int(self.queries as i64)),
            ];
            if self.fallback {
                rec.push(("fallback".to_string(), Json::str("v1")));
            }
            out.push(Json::Obj(rec));
        }
        out
    }
}

/// Houdini 회차 반복(4.1). `r` 은 지금까지의 회차 번호(이어서 센다). 예산 소진·시간 초과면 `res.status` 를 정하고
/// 후보를 모두 비운다. 첫 탐색과 되돌림 탐색이 같이 쓴다.
fn houdini_rounds(
    prog: &ast::Program,
    f: &ast::Function,
    decls: &[TypeDecl],
    seq: u32,
    rec: &mut Trace,
    res: &mut InferResult,
    probe: &mut Probe,
    r: &mut u32,
) -> R<()> {
    loop {
        let extra = res.extra();
        if extra.is_empty() {
            break; // 후보가 (더) 없다: 회차 없음
        }
        *r += 1;
        probe.begin_round();
        let run_result: R<()> = {
            let z = Z3::new();
            let pre = Prelude::new(&z);
            let model = Model::with_seq(&z, &pre, decls, seq)?;
            let mut fv = FnVerifier::for_function(&z, &pre, &model, &mut *rec, prog, f);
            fv.qcfg = QueryConfig {
                phase: "inference".to_string(),
                round: Some(*r),
                timeout_ms: TIMEOUT_MS,
                rlimit: Some(RLIMIT),
                seed: Some(SEED),
            };
            fv.set_extra(extra);
            fv.probe = Some(&mut *probe);
            let out = fv.run();
            drop(fv);
            out
        };
        if let Some(a) = probe.abort {
            // 예산 소진·시간 초과: Python 은 예외로 run 을 떠났으므로 그 뒤의 내부 오류는 보지 않는다.
            res.status = match a {
                ProbeAbort::Budget => InferStatus::BudgetExhausted,
                ProbeAbort::Timeout => InferStatus::Timeout,
            };
            for l in res.loops.iter_mut() {
                l.alive.clear();
            }
            break;
        }
        run_result?;
        if probe.failed.is_empty() {
            break;
        }
        for l in res.loops.iter_mut() {
            let mut keep: Vec<ExtraInv> = Vec::new();
            for c in std::mem::take(&mut l.alive) {
                if let Some((code, status)) = probe.failed.get(&c.0) {
                    l.dropped.push(Dropped {
                        cand: c.0.clone(),
                        text: c.2.clone(),
                        round: *r,
                        code: code.clone(),
                        status: status.clone(),
                    });
                } else {
                    keep.push(c);
                }
            }
            l.alive = keep;
        }
    }
    Ok(())
}

/// infer.py `infer_function`: 함수 하나의 후보 + Houdini 회차(+ 4.1 버전 1 되돌림). 오류 목록은 건드리지 않는다.
/// 회차마다 새 z3 컨텍스트·Prelude·Model(같은 `seq`)을 만든다.
pub fn infer_function(
    prog: &ast::Program,
    f: &ast::Function,
    decls: &[TypeDecl],
    seq: u32,
    rec: &mut Trace,
) -> R<InferResult> {
    let kname = pick_bound_name(&fn_names(f));
    let ranges = elem_ranges(f);
    let mut loops: Vec<LoopInfo> = Vec::new();
    for (n, (w, block, idx)) in walk_loops(&f.body).into_iter().enumerate() {
        let (cands, generated, capped) = candidates_for_loop(w, block, idx, &kname, &ranges, f);
        let initial: Vec<(u32, ExtraInv)> = cands
            .into_iter()
            .enumerate()
            .map(|(i, c)| (c.kind, (format!("L{}#{}", n, i), c.expr, c.text)))
            .collect();
        let alive: Vec<ExtraInv> = initial.iter().map(|(_, e)| e.clone()).collect();
        loops.push(LoopInfo { n, line: w.line, col: w.col, generated, capped, alive, dropped: Vec::new(), initial });
    }
    let mut res = InferResult {
        fname: f.name.clone(),
        loops,
        status: InferStatus::Ok,
        rounds: 0,
        queries: 0,
        fallback: false,
    };
    let deadline = Instant::now() + Duration::from_secs(MAX_SECONDS);
    let mut probe = Probe::new(MAX_QUERIES, deadline);
    let mut r: u32 = 0;
    houdini_rounds(prog, f, decls, seq, rec, &mut res, &mut probe, &mut r)?;
    let mut queries = probe.queries;

    // 4.1 버전 1 되돌림: 예산 소진이고 처음 후보에 종류 12 이상이 있었으면 종류 1~11 만으로 다시.
    let had_new_kind = res.loops.iter().any(|l| l.initial.iter().any(|(k, _)| *k >= 12));
    if res.status == InferStatus::BudgetExhausted && had_new_kind {
        res.fallback = true;
        res.status = InferStatus::Ok;
        for l in res.loops.iter_mut() {
            l.alive = l.initial.iter().filter(|(k, _)| *k <= 11).map(|(_, e)| e.clone()).collect();
            l.dropped.clear();
        }
        let mut probe2 = Probe::new(MAX_QUERIES, deadline);
        houdini_rounds(prog, f, decls, seq, rec, &mut res, &mut probe2, &mut r)?;
        queries += probe2.queries;
    }
    res.rounds = r;
    res.queries = queries;
    Ok(res)
}
