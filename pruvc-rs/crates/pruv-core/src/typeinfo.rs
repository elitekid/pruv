//! 사용자 struct/enum 타입 정보(typeinfo.py 대응).
//! `type_name` 은 모든 타입의 소스 철자를, `TypeTable` 은 검사된 프로그램의 선언을 색인한다.

use crate::ast::*;
use std::collections::{HashMap, HashSet};

pub const BUILTIN_TYPE_NAMES: [&str; 9] =
    ["i64", "bool", "unit", "array", "option", "result", "array_u8", "array_bool", "str"];

/// 내장이 아닌 이름이면 사용자 타입(선언 여부와 무관).
pub fn is_user_type(ty: &str) -> bool {
    !BUILTIN_TYPE_NAMES.contains(&ty)
}

/// 배열 내부 타입 이름("array"/"array_u8"/"array_bool")인가.
pub fn is_array_name(n: &str) -> bool {
    array_elem_name(n).is_some()
}

/// 배열 내부 타입 이름 → 원소 타입 이름.
pub fn array_elem_name(n: &str) -> Option<&'static str> {
    match n {
        "array" => Some("i64"),
        "array_u8" => Some("u8"),
        "array_bool" => Some("bool"),
        _ => None,
    }
}

/// 원소 타입 이름 → 배열 내부 타입 이름.
pub fn array_of_elem_name(e: &str) -> Option<&'static str> {
    match e {
        "i64" => Some("array"),
        "u8" => Some("array_u8"),
        "bool" => Some("array_bool"),
        _ => None,
    }
}

/// 소스 수준 철자. 사용자 타입은 자기 이름 그대로.
pub fn type_name(ty: &str) -> String {
    match ty {
        "i64" => "i64".to_string(),
        "bool" => "bool".to_string(),
        "str" => "str".to_string(),
        "unit" => "()".to_string(),
        "array" => "[i64]".to_string(),
        "array_u8" => "[u8]".to_string(),
        "array_bool" => "[bool]".to_string(),
        "option" => "Option<i64>".to_string(),
        "result" => "Result<i64>".to_string(),
        other => other.to_string(),
    }
}

/// 걷기 공통: `pick(타입 이름)` 이 참인 첫 자리.
fn g2_in_stmts(stmts: &[Stmt], pick: &dyn Fn(&str) -> bool) -> Option<(i64, i64, String)> {
    for s in stmts {
        match s {
            Stmt::Let(l) => {
                if pick(&l.ty) {
                    return Some((l.line, l.col, l.ty.clone()));
                }
            }
            Stmt::If(i) => {
                if let Some(r) = g2_in_stmts(&i.then, pick) {
                    return Some(r);
                }
                if let Some(r) = g2_in_stmts(&i.els, pick) {
                    return Some(r);
                }
            }
            Stmt::While(w) => {
                if let Some(r) = g2_in_stmts(&w.body, pick) {
                    return Some(r);
                }
            }
            Stmt::Match(m) => {
                for arm in &m.arms {
                    if let Some(r) = g2_in_stmts(&arm.body, pick) {
                        return Some(r);
                    }
                }
            }
            _ => {}
        }
    }
    None
}

fn g2_walk(prog: &Program, pick: &dyn Fn(&str) -> bool) -> Option<(i64, i64, String)> {
    for f in &prog.functions {
        for p in &f.params {
            if pick(&p.ty) {
                return Some((f.line, f.col, p.ty.clone()));
            }
        }
        if pick(&f.ret) {
            return Some((f.line, f.col, f.ret.clone()));
        }
        if let Some(r) = g2_in_stmts(&f.body, pick) {
            return Some(r);
        }
    }
    None
}

/// 후보 위치 중 (line, col) 이 가장 작은 것을 남긴다(같으면 먼저 본 것).
fn g2_cand(best: &mut Option<(i64, i64, String)>, line: i64, col: i64, ty: &str) {
    let better = match best {
        None => true,
        Some(b) => (line, col) < (b.0, b.1),
    };
    if better {
        *best = Some((line, col, ty.to_string()));
    }
}

/// 식 안의 모든 StrLit 을 후보로(와일드카드 없이 모든 변형을 나열).
fn g2_cand_expr(e: &Expr, lits: bool, best: &mut Option<(i64, i64, String)>) {
    match e {
        Expr::IntLit(_) => {}
        Expr::BoolLit(_) => {}
        Expr::StrLit(x) => {
            if lits {
                g2_cand(best, x.line, x.col, "str");
            }
        }
        Expr::Var(_) => {}
        Expr::Unary(x) => g2_cand_expr(&x.operand, lits, best),
        Expr::Binary(x) => {
            g2_cand_expr(&x.left, lits, best);
            g2_cand_expr(&x.right, lits, best);
        }
        Expr::Call(x) => {
            for a in &x.args {
                g2_cand_expr(a, lits, best);
            }
        }
        Expr::Index(x) => {
            g2_cand_expr(&x.array, lits, best);
            g2_cand_expr(&x.index, lits, best);
        }
        Expr::Ctor(x) => {
            if let Some(a) = &x.arg {
                g2_cand_expr(a, lits, best);
            }
        }
        Expr::Quant(x) => {
            g2_cand_expr(&x.lo, lits, best);
            g2_cand_expr(&x.hi, lits, best);
            g2_cand_expr(&x.body, lits, best);
        }
        Expr::StructLit(x) => {
            for f in &x.fields {
                g2_cand_expr(&f.value, lits, best);
            }
        }
        Expr::EnumCtor(x) => {
            for a in &x.args {
                g2_cand_expr(a, lits, best);
            }
        }
        Expr::FieldAccess(x) => g2_cand_expr(&x.base, lits, best),
        Expr::IsVariant(x) => g2_cand_expr(&x.value, lits, best),
        Expr::VariantField(x) => g2_cand_expr(&x.value, lits, best),
    }
}

/// 문장 안의 Let 타입(pick)과 모든 식의 StrLit 을 후보로(와일드카드 없이 모든 변형을 나열).
fn g2_cand_stmts(stmts: &[Stmt], pick: &dyn Fn(&str) -> bool, lits: bool, best: &mut Option<(i64, i64, String)>) {
    for s in stmts {
        match s {
            Stmt::Let(l) => {
                if pick(&l.ty) {
                    g2_cand(best, l.line, l.col, &l.ty);
                }
                g2_cand_expr(&l.value, lits, best);
            }
            Stmt::Assign(a) => g2_cand_expr(&a.value, lits, best),
            Stmt::IndexAssign(a) => {
                g2_cand_expr(&a.index, lits, best);
                g2_cand_expr(&a.value, lits, best);
            }
            Stmt::If(i) => {
                g2_cand_expr(&i.cond, lits, best);
                g2_cand_stmts(&i.then, pick, lits, best);
                g2_cand_stmts(&i.els, pick, lits, best);
            }
            Stmt::While(w) => {
                g2_cand_expr(&w.cond, lits, best);
                for inv in &w.invariants {
                    g2_cand_expr(inv, lits, best);
                }
                g2_cand_expr(&w.decreases, lits, best);
                g2_cand_stmts(&w.body, pick, lits, best);
            }
            Stmt::Return(r) => {
                if let Some(v) = &r.value {
                    g2_cand_expr(v, lits, best);
                }
            }
            Stmt::Assert(a) => g2_cand_expr(&a.cond, lits, best),
            Stmt::ExprStmt(e) => g2_cand_expr(&e.expr, lits, best),
            Stmt::FieldAssign(f) => g2_cand_expr(&f.value, lits, best),
            Stmt::Match(m) => {
                g2_cand_expr(&m.scrutinee, lits, best);
                for arm in &m.arms {
                    g2_cand_stmts(&arm.body, pick, lits, best);
                }
            }
        }
    }
}

/// 아직 구현 안 한 층의 타입(`[i64]` 가 아닌 배열, `str`)이 처음 나오는 곳: (line, col, 내부 타입 이름).
/// 함수 선언 순서대로, 걸린 첫 함수에서: 매개변수 → 반환 타입 → 그 함수의 후보 위치(본문 Let 타입,
/// `str` 이 skip 에 없으면 requires/ensures/본문 모든 식의 StrLit) 중 (line, col) 최소.
/// `skip` 에 든 내부 이름은 건너뛴다.
pub fn first_g2_unimplemented(prog: &Program, skip: &[&str]) -> Option<(i64, i64, String)> {
    let pick = |t: &str| (t == "str" || (is_array_name(t) && t != "array")) && !skip.contains(&t);
    let lits = !skip.contains(&"str");
    for f in &prog.functions {
        for p in &f.params {
            if pick(&p.ty) {
                return Some((f.line, f.col, p.ty.clone()));
            }
        }
        if pick(&f.ret) {
            return Some((f.line, f.col, f.ret.clone()));
        }
        let mut best: Option<(i64, i64, String)> = None;
        for e in &f.requires {
            g2_cand_expr(e, lits, &mut best);
        }
        for e in &f.ensures {
            g2_cand_expr(e, lits, &mut best);
        }
        g2_cand_stmts(&f.body, &pick, lits, &mut best);
        if best.is_some() {
            return best;
        }
    }
    None
}

/// 프로그램의 매개변수·반환·let 타입 중 내부 이름이 `name` 인 자리가 있는가.
pub fn uses_array_type(prog: &Program, name: &str) -> bool {
    g2_walk(prog, &|t: &str| t == name).is_some()
}

/// G2 B2: 매개변수·반환·(중첩) let 타입이 `str` 이거나 requires/ensures/본문 어느 식이든 StrLit 이 있는가.
pub fn uses_str(prog: &Program) -> bool {
    let pick = |t: &str| t == "str";
    for f in &prog.functions {
        if f.params.iter().any(|p| p.ty == "str") || f.ret == "str" {
            return true;
        }
        let mut best: Option<(i64, i64, String)> = None;
        for e in &f.requires {
            g2_cand_expr(e, true, &mut best);
        }
        for e in &f.ensures {
            g2_cand_expr(e, true, &mut best);
        }
        g2_cand_stmts(&f.body, &pick, true, &mut best);
        if best.is_some() {
            return true;
        }
    }
    false
}

/// `first_g2_unimplemented` 를 진단으로. stage 는 "verify" / "codegen" 등 막힌 층 이름.
/// layer 가 있으면 메시지의 층 이름으로 쓰고, fix 가 있으면 고침 안내를 바꾼다.
pub fn g2_unimplemented_error(
    prog: &Program,
    stage: &str,
    layer: Option<&str>,
    skip: &[&str],
    fix: Option<&str>,
) -> Option<crate::diagnostic::PruvError> {
    let (line, col, ty) = first_g2_unimplemented(prog, skip)?;
    if ty == "str" {
        return Some(crate::diagnostic::PruvError::new(
            stage,
            line,
            col,
            "unsupported_type",
            format!("str is not supported yet: the {} layer is not implemented", layer.unwrap_or(stage)),
            fix.unwrap_or("do not use str yet"),
        ));
    }
    Some(crate::diagnostic::PruvError::new(
        stage,
        line,
        col,
        "unsupported_type",
        format!(
            "{} arrays are not supported yet: the {} layer is not implemented",
            type_name(&ty),
            layer.unwrap_or(stage)
        ),
        fix.unwrap_or("use [i64] for now"),
    ))
}

impl TypeDecl {
    pub fn name(&self) -> &str {
        match self {
            TypeDecl::Struct(s) => &s.name,
            TypeDecl::Enum(e) => &e.name,
        }
    }
    pub fn line(&self) -> i64 {
        match self {
            TypeDecl::Struct(s) => s.line,
            TypeDecl::Enum(e) => e.line,
        }
    }
    pub fn col(&self) -> i64 {
        match self {
            TypeDecl::Struct(s) => s.col,
            TypeDecl::Enum(e) => e.col,
        }
    }
    /// 구조체는 필드, enum 은 모든 변형의 필드를 선언 순서로.
    pub fn all_fields(&self) -> Vec<&FieldDecl> {
        match self {
            TypeDecl::Struct(s) => s.fields.iter().collect(),
            TypeDecl::Enum(e) => e.variants.iter().flat_map(|v| v.fields.iter()).collect(),
        }
    }
}

#[derive(Debug, Clone, Default)]
pub struct TypeTable {
    /// 선언 순서(첫 선언 우선, 이름 중복 없음).
    pub decls: Vec<TypeDecl>,
    index: HashMap<String, usize>,
    /// 의존 먼저·선언 안정 순서: `decls` 의 인덱스.
    pub order: Vec<usize>,
}

impl TypeTable {
    pub fn new(types: &[TypeDecl]) -> TypeTable {
        let mut t = TypeTable::default();
        for d in types {
            if !t.index.contains_key(d.name()) {
                t.index.insert(d.name().to_string(), t.decls.len());
                t.decls.push(d.clone());
            }
        }
        t.build_order();
        t
    }

    /// 의존 순서로 나열한 선언.
    pub fn ordered(&self) -> impl Iterator<Item = &TypeDecl> {
        self.order.iter().map(move |&i| &self.decls[i])
    }

    /// 필드 순서대로, 중복 없이, 선언된 이름만.
    pub fn deps(&self, d: &TypeDecl) -> Vec<String> {
        let mut out: Vec<String> = Vec::new();
        for f in d.all_fields() {
            if is_user_type(&f.ty) && self.index.contains_key(&f.ty) && !out.contains(&f.ty) {
                out.push(f.ty.clone());
            }
        }
        out
    }

    fn build_order(&mut self) {
        let mut seen: HashSet<usize> = HashSet::new();
        let mut order: Vec<usize> = Vec::new();
        for i in 0..self.decls.len() {
            self.visit(i, &mut seen, &mut order);
        }
        self.order = order;
    }

    fn visit(&self, i: usize, seen: &mut HashSet<usize>, order: &mut Vec<usize>) {
        if !seen.insert(i) {
            return; // 먼저 표시: 순환(검사기가 거부)이 있어도 무한 반복 없음
        }
        for n in self.deps(&self.decls[i]) {
            if let Some(&j) = self.index.get(&n) {
                self.visit(j, seen, order);
            }
        }
        order.push(i);
    }

    // ---- 조회 ----
    pub fn decl(&self, ty: &str) -> Option<&TypeDecl> {
        self.index.get(ty).map(|&i| &self.decls[i])
    }

    pub fn is_struct(&self, ty: &str) -> bool {
        matches!(self.decl(ty), Some(TypeDecl::Struct(_))) && is_user_type(ty)
    }

    pub fn is_enum(&self, ty: &str) -> bool {
        matches!(self.decl(ty), Some(TypeDecl::Enum(_))) && is_user_type(ty)
    }

    /// enum 의 변형(없거나 enum 이 아니면 None).
    pub fn variant(&self, ty: &str, variant: &str) -> Option<&VariantDecl> {
        match self.decl(ty) {
            Some(TypeDecl::Enum(e)) => e.variants.iter().find(|v| v.name == variant),
            _ => None,
        }
    }

    /// struct 필드, 또는 enum 의 `variant` 필드(선언 순서). 찾지 못하면 None.
    pub fn fields(&self, ty: &str, variant: Option<&str>) -> Option<&[FieldDecl]> {
        match self.decl(ty)? {
            TypeDecl::Struct(s) => Some(&s.fields),
            TypeDecl::Enum(_) => self.variant(ty, variant?).map(|v| v.fields.as_slice()),
        }
    }

    pub fn field_index(&self, ty: &str, name: &str, variant: Option<&str>) -> Option<usize> {
        self.fields(ty, variant)?.iter().position(|f| f.name == name)
    }

    pub fn variant_index(&self, ty: &str, variant: &str) -> Option<usize> {
        match self.decl(ty) {
            Some(TypeDecl::Enum(e)) => e.variants.iter().position(|v| v.name == variant),
            _ => None,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn names() {
        assert_eq!(type_name("unit"), "()");
        assert_eq!(type_name("array"), "[i64]");
        assert_eq!(type_name("option"), "Option<i64>");
        assert_eq!(type_name("result"), "Result<i64>");
        assert_eq!(type_name("Point"), "Point");
        assert!(is_user_type("Point"));
        assert!(!is_user_type("i64"));
        assert_eq!(type_name("array_u8"), "[u8]");
        assert_eq!(type_name("array_bool"), "[bool]");
        assert!(!is_user_type("array_u8"));
        assert!(!is_user_type("array_bool"));
        assert_eq!(BUILTIN_TYPE_NAMES.len(), 9);
    }
}
