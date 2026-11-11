//! STAGE1 A: 정제 주석 -> 기존 계약(설탕 펼치기). refine.py 를 한 줄씩 옮김.
//!
//! `expand(prog)` 는 Checker::run() 맨 앞에서 한 번 돈다. 합성 노드는 보통 검사기가 타입을 채우고
//! verify/codegen/llvmgen 이 그대로 소비한다. 정제 주석이 없으면 아무것도 바꾸지 않는다.
//!
//! 정수 경계는 부호+정규화 십진 문자열이다(Python 은 임의 정밀도 int). 비교는 `cmp_dec` 로 문자열에서
//! 직접 하므로 20자리 이상 리터럴도 i128 에 의존하지 않고 같은 판정·같은 숫자 표기가 나온다.

use crate::ast::*;
use crate::diagnostic::PruvError;
use std::cmp::Ordering;
use std::collections::HashSet;

type Res<T> = Result<T, PruvError>;

const I64_MIN: &str = "-9223372036854775808";
const I64_MAX: &str = "9223372036854775807";
const MAX_LEN: &str = "1099511627776"; // 2^40

// ---------- 십진 문자열 비교 ----------
fn cmp_mag(a: &str, b: &str) -> Ordering {
    a.len().cmp(&b.len()).then_with(|| a.cmp(b))
}

/// 정규화된 부호 있는 십진 문자열(앞 0 없음, "0" 은 부호 없음) 비교.
fn cmp_dec(a: &str, b: &str) -> Ordering {
    let (an, am) = match a.strip_prefix('-') {
        Some(r) => (true, r),
        None => (false, a),
    };
    let (bn, bm) = match b.strip_prefix('-') {
        Some(r) => (true, r),
        None => (false, b),
    };
    match (an, bn) {
        (false, true) => Ordering::Greater,
        (true, false) => Ordering::Less,
        (false, false) => cmp_mag(am, bm),
        (true, true) => cmp_mag(bm, am),
    }
}

fn in_i64(v: &str) -> bool {
    cmp_dec(v, I64_MIN) != Ordering::Less && cmp_dec(v, I64_MAX) != Ordering::Greater
}

fn terr(r: &Refinement, code: &str, msg: String, fix: &str) -> PruvError {
    PruvError::new("type", r.line, r.col, code, msg, fix)
}

fn validate(r: &Refinement) -> Res<()> {
    if r.shape == "scalar" && r.base != "i64" {
        return Err(terr(
            r,
            "refinement_base",
            format!("a refinement `| L..=U` applies only to i64 or [i64], not to {}", r.base),
            "remove the annotation and state the condition with requires/ensures/assert",
        ));
    }
    for (what, v) in [("lower bound", &r.lo), ("upper bound", &r.hi)] {
        if let Some(v) = v {
            if !in_i64(v) {
                return Err(terr(
                    r,
                    "refinement_bounds",
                    format!("refinement {} {} is outside the i64 range", what, v),
                    "bounds must lie in -9223372036854775808..=9223372036854775807",
                ));
            }
        }
    }
    if let (Some(lo), Some(hi)) = (&r.lo, &r.hi) {
        if cmp_dec(lo, hi) == Ordering::Greater {
            return Err(terr(
                r,
                "refinement_bounds",
                format!("empty refinement range {}..={}: the lower bound exceeds the upper bound", lo, hi),
                "write the smaller bound first; both ends are included",
            ));
        }
    }
    if let Some(m) = &r.maxlen {
        if cmp_dec(m, "0") == Ordering::Less || cmp_dec(m, MAX_LEN) == Ordering::Greater {
            return Err(terr(
                r,
                "refinement_bounds",
                format!("refinement length bound {} is outside 0..=2^40", m),
                "the length bound `<=N` needs 0 <= N <= 1_099_511_627_776",
            ));
        }
    }
    Ok(())
}

// ---------- 일반 AST 보조 ----------
fn kids(e: &Expr) -> Vec<&Expr> {
    match e {
        Expr::Unary(x) => vec![x.operand.as_ref()],
        Expr::Binary(x) => vec![x.left.as_ref(), x.right.as_ref()],
        Expr::Index(x) => vec![x.array.as_ref(), x.index.as_ref()],
        Expr::Ctor(x) => x.arg.iter().map(|a| &**a).collect(),
        Expr::Quant(x) => vec![x.lo.as_ref(), x.hi.as_ref(), x.body.as_ref()],
        Expr::Call(x) => x.args.iter().collect(),
        Expr::StructLit(x) => x.fields.iter().map(|f| &f.value).collect(),
        Expr::EnumCtor(x) => x.args.iter().collect(),
        Expr::FieldAccess(x) => vec![x.base.as_ref()],
        Expr::IsVariant(x) => vec![x.value.as_ref()],
        Expr::VariantField(x) => vec![x.value.as_ref()],
        Expr::IntLit(_) | Expr::BoolLit(_) | Expr::Var(_) => Vec::new(),
    }
}

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

fn fn_names(f: &Function) -> HashSet<String> {
    let mut out: HashSet<String> = f.params.iter().map(|p| p.name.clone()).collect();
    for e in f.requires.iter().chain(f.ensures.iter()) {
        expr_names(e, &mut out);
    }
    stmt_names(&f.body, &mut out);
    out
}

/// k, k_1, k_2, ... 중 names 에 없는 첫 이름(결정적)
pub fn pick_bound_name(names: &HashSet<String>) -> String {
    if !names.contains("k") {
        return "k".to_string();
    }
    let mut i = 1;
    while names.contains(&format!("k_{}", i)) {
        i += 1;
    }
    format!("k_{}", i)
}

fn assigned(stmts: &[Stmt], out: &mut HashSet<String>) {
    for st in stmts {
        match st {
            Stmt::Assign(x) => {
                out.insert(x.name.clone());
            }
            Stmt::IndexAssign(x) => {
                out.insert(x.name.clone());
            }
            Stmt::If(x) => {
                assigned(&x.then, out);
                assigned(&x.els, out);
            }
            Stmt::While(x) => assigned(&x.body, out),
            Stmt::Match(x) => {
                for a in &x.arms {
                    assigned(&a.body, out);
                }
            }
            _ => {}
        }
    }
}

// ---------- 조건 만들기(모든 노드는 주석 위치) ----------
struct At {
    line: i64,
    col: i64,
}

impl At {
    fn new(r: &Refinement) -> At {
        At { line: r.line, col: r.col }
    }
    fn lit(&self, v: &str) -> Expr {
        Expr::IntLit(IntLit { line: self.line, col: self.col, value: v.to_string(), ty: None })
    }
    fn var(&self, n: &str) -> Expr {
        Expr::Var(Var { line: self.line, col: self.col, name: n.to_string(), ty: None })
    }
    fn bin(&self, op: &str, l: Expr, r: Expr) -> Expr {
        Expr::Binary(Binary { line: self.line, col: self.col, op: op.to_string(), left: Box::new(l), right: Box::new(r), ty: None })
    }
    fn length(&self, n: &str) -> Expr {
        Expr::Call(Call { line: self.line, col: self.col, name: "len".to_string(), args: vec![self.var(n)], ty: None })
    }
    /// L <= v && v <= U (v 는 i64 식을 매번 새로 만드는 함수)
    fn within(&self, v: &dyn Fn() -> Expr, r: &Refinement) -> Expr {
        let lo = r.lo.as_deref().unwrap_or("0");
        let hi = r.hi.as_deref().unwrap_or("0");
        let a = self.bin("<=", self.lit(lo), v());
        let b = self.bin("<=", v(), self.lit(hi));
        self.bin("&&", a, b)
    }
}

/// 변수 `name`(`result` 가능)에 대한 정제 r 의 조건들 [(label, expr)]
fn parts(r: &Refinement, name: &str, kname: &str) -> Vec<(&'static str, Expr)> {
    let at = At::new(r);
    if r.shape == "scalar" {
        return vec![("value range", at.within(&|| at.var(name), r))];
    }
    let mut out = Vec::new();
    if let Some(m) = &r.maxlen {
        out.push(("length bound", at.bin("<=", at.length(name), at.lit(m))));
    }
    if r.lo.is_some() {
        let body = at.within(
            &|| Expr::Index(Index { line: at.line, col: at.col, array: Box::new(at.var(name)), index: Box::new(at.var(kname)), ty: None }),
            r,
        );
        out.push((
            "element range",
            Expr::Quant(Quant {
                line: at.line,
                col: at.col,
                kind: "forall".to_string(),
                var: kname.to_string(),
                lo: Box::new(at.lit("0")),
                hi: Box::new(at.length(name)),
                body: Box::new(body),
                ty: None,
            }),
        ));
    }
    out
}

fn synth_assert(r: &Refinement, expr: Expr, code: &str, what: String) -> Stmt {
    Stmt::Assert(Assert { line: r.line, col: r.col, cond: expr, origin_code: Some(code.to_string()), origin_what: Some(what) })
}

/// 선언 순서를 지키는 범위(Python dict). 같은 이름을 다시 넣으면 자리는 두고 값만 바꾼다.
type Scope = Vec<(String, Refinement)>;

fn scope_get<'a>(s: &'a Scope, n: &str) -> Option<&'a Refinement> {
    s.iter().find(|(k, _)| k == n).map(|(_, r)| r)
}

fn scope_set(s: &mut Scope, n: &str, r: Refinement) {
    match s.iter_mut().find(|(k, _)| k == n) {
        Some(slot) => slot.1 = r,
        None => s.push((n.to_string(), r)),
    }
}

struct Expander {
    k: String,
}

impl Expander {
    fn block(&self, stmts: Vec<Stmt>, scope: &mut Scope) -> Vec<Stmt> {
        let mut out: Vec<Stmt> = Vec::with_capacity(stmts.len());
        for mut st in stmts {
            let mut after: Vec<Stmt> = Vec::new();
            match &mut st {
                Stmt::Let(l) => {
                    if let Some(r) = &l.refine {
                        scope_set(scope, &l.name, r.clone());
                        for (label, e) in parts(r, &l.name, &self.k) {
                            let what = format!("the {} of local {} at its declaration (line {})", label, l.name, l.line);
                            after.push(synth_assert(r, e, "refinement_init", what));
                        }
                    }
                }
                Stmt::Assign(a) => {
                    if let Some(r) = scope_get(scope, &a.name) {
                        for (label, e) in parts(r, &a.name, &self.k) {
                            let what = format!("the {} of local {} after the assignment on line {}", label, a.name, a.line);
                            after.push(synth_assert(r, e, "refinement_assign", what));
                        }
                    }
                }
                Stmt::IndexAssign(a) => {
                    if let Some(r) = scope_get(scope, &a.name) {
                        if r.shape == "array" && r.lo.is_some() {
                            // 합성 assert 없음: 검증기가 저장 값의 범위를 증명한다(code refinement_assign)
                            let what = format!("the element range of local {} after the store on line {}", a.name, a.line);
                            a.elem_refine = Some((
                                r.lo.clone().unwrap_or_default(),
                                r.hi.clone().unwrap_or_default(),
                                what,
                            ));
                        }
                    }
                }
                Stmt::If(i) => {
                    let then = std::mem::take(&mut i.then);
                    i.then = self.block(then, &mut scope.clone());
                    let els = std::mem::take(&mut i.els);
                    i.els = self.block(els, &mut scope.clone());
                }
                Stmt::While(w) => {
                    let mut changed = HashSet::new();
                    assigned(&w.body, &mut changed);
                    let mut pre: Vec<Expr> = Vec::new();
                    for (name, r) in scope.iter() {
                        // 선언 순서, 루프 머리에서 살아 있는 것만
                        if changed.contains(name) {
                            pre.extend(parts(r, name, &self.k).into_iter().map(|(_, e)| e));
                        }
                    }
                    if !pre.is_empty() {
                        let old = std::mem::take(&mut w.invariants);
                        pre.extend(old);
                        w.invariants = pre;
                    }
                    let body = std::mem::take(&mut w.body);
                    w.body = self.block(body, &mut scope.clone());
                }
                Stmt::Match(m) => {
                    for a in m.arms.iter_mut() {
                        let body = std::mem::take(&mut a.body);
                        a.body = self.block(body, &mut scope.clone());
                    }
                }
                _ => {}
            }
            out.push(st);
            out.extend(after);
        }
        out
    }

    fn run(&self, f: &mut Function) {
        let mut pre: Vec<Expr> = Vec::new();
        for p in &f.params {
            if let Some(r) = &p.refine {
                pre.extend(parts(r, &p.name, &self.k).into_iter().map(|(_, e)| e));
            }
        }
        if !pre.is_empty() {
            let old = std::mem::take(&mut f.requires);
            pre.extend(old);
            f.requires = pre;
        }
        if let Some(r) = &f.ret_refine {
            let mut ens: Vec<Expr> = parts(r, "result", &self.k).into_iter().map(|(_, e)| e).collect();
            let old = std::mem::take(&mut f.ensures);
            ens.extend(old);
            f.ensures = ens;
        }
        let body = std::mem::take(&mut f.body);
        f.body = self.block(body, &mut Vec::new());
    }
}

fn validate_block(stmts: &[Stmt]) -> Res<()> {
    for st in stmts {
        match st {
            Stmt::Let(l) => {
                if let Some(r) = &l.refine {
                    validate(r)?;
                }
            }
            Stmt::If(i) => {
                validate_block(&i.then)?;
                validate_block(&i.els)?;
            }
            Stmt::While(w) => validate_block(&w.body)?,
            Stmt::Match(m) => {
                for a in &m.arms {
                    validate_block(&a.body)?;
                }
            }
            _ => {}
        }
    }
    Ok(())
}

fn any_let_refine(stmts: &[Stmt]) -> bool {
    stmts.iter().any(|st| match st {
        Stmt::Let(l) => l.refine.is_some(),
        Stmt::If(i) => any_let_refine(&i.then) || any_let_refine(&i.els),
        Stmt::While(w) => any_let_refine(&w.body),
        Stmt::Match(m) => m.arms.iter().any(|a| any_let_refine(&a.body)),
        _ => false,
    })
}

pub fn has_refinements(prog: &Program) -> bool {
    prog.functions
        .iter()
        .any(|f| f.ret_refine.is_some() || f.params.iter().any(|p| p.refine.is_some()) || any_let_refine(&f.body))
}

/// 모든 주석을 검증한 뒤 펼친다. 주석이 없으면 아무것도 하지 않는다.
/// 한 Program 에 한 번만 펼친다: `prog.refined` 표식(Python `_refined`)이 이미 서 있으면 아무것도 하지 않는다.
pub fn expand(prog: &mut Program) -> Res<()> {
    if prog.refined {
        return Ok(());
    }
    prog.refined = true;
    if !has_refinements(prog) {
        return Ok(());
    }
    for f in &prog.functions {
        for p in &f.params {
            if let Some(r) = &p.refine {
                validate(r)?;
            }
        }
        if let Some(r) = &f.ret_refine {
            validate(r)?;
        }
        validate_block(&f.body)?;
    }
    for f in prog.functions.iter_mut() {
        let ex = Expander { k: pick_bound_name(&fn_names(f)) };
        ex.run(f);
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn dec_compare() {
        assert_eq!(cmp_dec("0", "0"), Ordering::Equal);
        assert_eq!(cmp_dec("-1", "0"), Ordering::Less);
        assert_eq!(cmp_dec("-10", "-9"), Ordering::Less);
        assert_eq!(cmp_dec("100", "99"), Ordering::Greater);
        assert!(in_i64("9223372036854775807"));
        assert!(!in_i64("9223372036854775808"));
        assert!(in_i64("-9223372036854775808"));
        assert!(!in_i64("-9223372036854775809"));
        assert!(!in_i64("123456789012345678901234567890"));
    }

    #[test]
    fn bound_name() {
        let mut s: HashSet<String> = HashSet::new();
        assert_eq!(pick_bound_name(&s), "k");
        s.insert("k".to_string());
        assert_eq!(pick_bound_name(&s), "k_1");
        s.insert("k_1".to_string());
        assert_eq!(pick_bound_name(&s), "k_2");
    }
}
