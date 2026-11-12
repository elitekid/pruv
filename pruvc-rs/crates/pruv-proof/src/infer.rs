//! STAGE1 B2: template Houdini invariant inference (`--infer`). A line-by-line port of pruvc/infer.py. Spec: docs/STAGE1_B_INFER.md.
//!
//! Per function: build candidate invariants from fixed templates (§3), then run Houdini rounds (4.1): in each round all live candidates are
//! supplied as extra loop invariants and the whole function is verified; candidates whose entry/preservation obligations are not proved are dropped. Done when nothing is dropped.
//! Afterwards `verify_program_opts` verifies once more with the surviving candidates (4.2).
//!
//! B+ (spec 3.7, inference config version 2): added kinds 12 (value range), 13 (output array prefix) and 14 (early-return prefix).
//!
//! Where the port differs from Python:
//! - Integer arithmetic is i128 (saturating). Python uses arbitrary precision, but values outside i64 never produce a candidate anyway.
//! - The `_Skip` exception becomes an `Option` (`None` = no candidate is produced).
//! - A fresh z3 context, Prelude and Model (same seq) is created per round (see the comment in lib.rs).
//! - Budget/time exhaustion sets `Probe.abort` instead of raising (`ProbeAbort` in symbolic.rs).

use std::collections::{BTreeSet, HashMap, HashSet};
use std::time::{Duration, Instant};

use pruv_core::ast::{self as ast, Expr, Stmt};
use pruv_core::gtype::GType;
use pruv_core::pyjson::Json;
use pruv_core::refine::pick_bound_name;

use crate::model::{Model, Prelude, TypeDecl};
use crate::obligation::Trace;
use crate::symbolic::{norm_int, walk_loops, Extra, ExtraInv, FnVerifier, Probe, ProbeAbort, QueryConfig, R};
use crate::sys::Z3;

/// INFER_CONFIG
pub const MAX_CANDIDATES: usize = 64; // per loop, after sorting and dedup (the truncated count is `capped`)
pub const MAX_QUERIES: usize = 512; // per function, all solver attempts (a lemma retry counts as 1)
pub const RLIMIT: u32 = 100000;
pub const TIMEOUT_MS: u32 = 500;
pub const SEED: u32 = 0;
pub const MAX_SECONDS: u64 = 5; // per-function wall clock

const I64_MAX: i128 = i64::MAX as i128;

type Rng = (i128, i128);

// ---------------------------------------------------------------------------
// Output (3.5)
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

/// infer.py `show`. None = a node the output function does not know (Python `_Skip`).
pub fn show(e: &Expr) -> Option<String> {
    match e {
        Expr::Spent(_) => None,
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
// AST helpers
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
        Expr::InoutArg(x) => vec![&*x.expr], // G5 A0
        Expr::Spent(_) | Expr::IntLit(_) | Expr::BoolLit(_) | Expr::StrLit(_) | Expr::Var(_) | Expr::Move(_) => Vec::new(),
    }
}

// refine.py `_expr_names` / `_stmt_names` / `_fn_names` (private in pruv_core::refine, so ported as is)
fn expr_names(e: &Expr, out: &mut HashSet<String>) {
    match e {
        Expr::Spent(_) => {},
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
            Stmt::Par(x) => {
                for c in &x.calls {
                    expr_names(c, out);
                }
            }
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
    for e in f.requires.iter().chain(f.ensures.iter()).chain(f.cost.iter()) {
        expr_names(e, &mut out);
    }
    stmt_names(&f.body, &mut out);
    out
}

/// Is the structure the same (excluding positions and checker types):infer.py `_shape(a) == _shape(b)`.
fn shape_eq(a: &Expr, b: &Expr) -> bool {
    match (a, b) {
        (Expr::Spent(_), Expr::Spent(_)) => true,
        (Expr::IntLit(x), Expr::IntLit(y)) => norm_int(&x.value) == norm_int(&y.value),
        (Expr::BoolLit(x), Expr::BoolLit(y)) => x.value == y.value,
        (Expr::StrLit(x), Expr::StrLit(y)) => x.value == y.value,
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

/// infer.py `_free`: free variable names of e (quantified variables are bound inside the quantifier body).
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

/// References to Assign / IndexAssign / FieldAssign (including nested blocks).
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

/// infer.py `_expr_inout` (G5 A1): whole-array operands of the inout arguments of e itself (G5_SPEC 2.1: an inout call is
/// always the complete expression of a statement, so nothing below it is visited).
fn expr_inout(e: &Expr, out: &mut BTreeSet<String>) {
    if let Expr::Call(c) = e {
        for a in &c.args {
            if let Expr::InoutArg(ia) = a {
                if let Expr::Var(v) = &*ia.expr {
                    out.insert(v.name.clone());
                }
            }
        }
    }
}

/// infer.py `_stmt_inout` (G5 A1): names written by inout calls in the own expressions of one statement.
fn stmt_inout(st: &Stmt) -> BTreeSet<String> {
    let mut out = BTreeSet::new();
    match st {
        Stmt::Let(x) => expr_inout(&x.value, &mut out),
        Stmt::Assign(x) => expr_inout(&x.value, &mut out),
        Stmt::Return(x) => {
            if let Some(v) = &x.value {
                expr_inout(v, &mut out);
            }
        }
        Stmt::Par(x) => {
            for c in &x.calls {
                expr_inout(c, &mut out);
            }
        }
        Stmt::ExprStmt(x) => expr_inout(&x.expr, &mut out),
        _ => {}
    }
    out
}

/// infer.py `_call_written` (G5 A1): every name written by an inout call, nested blocks included.
fn call_written(stmts: &[Stmt], out: &mut BTreeSet<String>) {
    for st in stmts {
        out.extend(stmt_inout(st));
        match st {
            Stmt::If(x) => {
                call_written(&x.then, out);
                call_written(&x.els, out);
            }
            Stmt::While(x) => call_written(&x.body, out),
            Stmt::Match(m) => {
                for a in &m.arms {
                    call_written(&a.body, out);
                }
            }
            _ => {}
        }
    }
}

fn assigned(stmts: &[Stmt]) -> BTreeSet<String> {
    let mut v = Vec::new();
    assign_stmts(stmts, &mut v);
    let mut out: BTreeSet<String> = v.iter().map(|a| a.name().to_string()).collect();
    call_written(stmts, &mut out); // G5 A1
    out
}

/// Names declared inside the loop body (let, match binders): not visible at the loop head.
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

/// infer.py `_init`: the value of `name` at the loop in block[idx] = the nearest preceding let/assignment in the same block. None if a preceding
/// if/while/match assigns it first, or if there is none. skip_index: an IndexAssign of that name is skipped.
fn init<'s>(block: &'s [Stmt], idx: usize, name: &str, skip_index: bool) -> Option<&'s Expr> {
    for j in (0..idx).rev() {
        let st = &block[j];
        if stmt_inout(st).contains(name) {
            return None; // G5 A1: an inout call write invalidates every earlier initializer/content fact
        }
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

/// infer.py `_lit`: the value of an integer literal (IntLit, or its unary minus), else None.
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

/// Expressions the loop does not change (3.1)
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

/// Array internal type name → element kind ("i64"/"u8"/"bool", "abs" for a G3 `[T]` = abstract element). None if not an array.
fn arr_elem_of(ty: &str) -> Option<&'static str> {
    match ty {
        "array" => Some("i64"),
        "array_u8" => Some("u8"),
        "array_bool" => Some("bool"),
        _ => {
            if pruv_core::gtype::is_g3_key(ty) {
                if let Ok(g) = pruv_core::gtype::GType::try_from_key(ty) {
                    if g.owner.is_none() && g.name == "array" && !g.args.is_empty() {
                        return Some("abs");
                    }
                }
            }
            None
        }
    }
}

/// Does the type key mention a type parameter anywhere (`T`, `[T]`, `Option<T>`, `Pair<T, i64>`, ...)?
/// A key contains the byte 1 exactly when a bound parameter occurs in it.
fn key_has_param(key: &str) -> bool {
    key.contains('\u{1}')
}

/// G3 A2: type table {name: type key} of the parameters and locals visible at the head of loop `w` (infer.py `_scope_types`).
type TyEnv = Vec<(String, String)>;

fn tyenv_set(env: &mut TyEnv, name: &str, ty: Option<&str>) {
    env.retain(|(n, _)| n != name);
    if let Some(t) = ty {
        env.push((name.to_string(), t.to_string()));
    }
}

fn tyenv_get<'t>(env: &'t [(String, String)], name: &str) -> Option<&'t str> {
    env.iter().find(|(n, _)| n == name).map(|(_, t)| t.as_str())
}

// G2 A5: per-loop-position table. The environment is updated in statement order (a `let` sets the name),
// and the environment on reaching the target loop node (pointer identity) is that loop's table. Inner blocks are entered with a copied environment.
fn find_loop_env(stmts: &[Stmt], env: &mut TyEnv, w: &ast::While) -> bool {
    for st in stmts {
        match st {
            Stmt::Let(x) => tyenv_set(env, &x.name, Some(&x.ty)),
            Stmt::If(x) => {
                for blk in [&x.then, &x.els] {
                    let mut e2 = env.clone();
                    if find_loop_env(blk, &mut e2, w) {
                        *env = e2;
                        return true;
                    }
                }
            }
            Stmt::While(x) => {
                if std::ptr::eq(x, w) {
                    return true;
                }
                let mut e2 = env.clone();
                if find_loop_env(&x.body, &mut e2, w) {
                    *env = e2;
                    return true;
                }
            }
            Stmt::Match(m) => {
                for a in &m.arms {
                    let mut e2 = env.clone();
                    for bn in &a.binders {
                        tyenv_set(&mut e2, bn, None);
                    }
                    if find_loop_env(&a.body, &mut e2, w) {
                        *env = e2;
                        return true;
                    }
                }
            }
            _ => {}
        }
    }
    false
}

/// infer.py `_scope_types`: types of the parameters and locals visible at the head of loop `w`.
fn scope_types(f: &ast::Function, w: &ast::While) -> TyEnv {
    let mut env: TyEnv = Vec::new();
    for p in &f.params {
        tyenv_set(&mut env, &p.name, Some(&p.ty));
    }
    let mut e2 = env.clone();
    if find_loop_env(&f.body, &mut e2, w) {
        e2
    } else {
        env
    }
}

/// Table of array name → element kind visible at the head of loop `w` (starting from the parameters).
fn elem_types(f: &ast::Function, w: &ast::While) -> Vec<(String, &'static str)> {
    let mut out: Vec<(String, &'static str)> = Vec::new();
    for (n, t) in scope_types(f, w) {
        if let Some(k) = arr_elem_of(&t) {
            out.push((n, k));
        }
    }
    out
}

fn elem_type_of<'t>(tab: &'t [(String, &'static str)], name: &str) -> Option<&'t str> {
    tab.iter().find(|(n, _)| n == name).map(|(_, e)| *e)
}

/// Does e contain an Index of an array whose element type is bool (or, G3, abstract)?
fn reads_bool_elem(e: &Expr, tab: &[(String, &'static str)]) -> bool {
    if let Expr::Index(x) = e {
        if let Expr::Var(a) = &*x.array {
            if matches!(elem_type_of(tab, &a.name), Some("bool") | Some("abs")) {
                return true;
            }
        }
    }
    kids(e).into_iter().any(|c| reads_bool_elem(c, tab))
}

/// The checker type of an expression node (None before checking and on freshly built nodes).
fn expr_ty(e: &Expr) -> Option<&String> {
    match e {
        Expr::Spent(x) => x.ty.as_ref(),
        Expr::IntLit(x) => x.ty.as_ref(),
        Expr::BoolLit(x) => x.ty.as_ref(),
        Expr::StrLit(x) => x.ty.as_ref(),
        Expr::Var(x) => x.ty.as_ref(),
        Expr::Unary(x) => x.ty.as_ref(),
        Expr::Binary(x) => x.ty.as_ref(),
        Expr::Call(x) => x.ty.as_ref(),
        Expr::Index(x) => x.ty.as_ref(),
        Expr::Ctor(x) => x.ty.as_ref(),
        Expr::Quant(x) => x.ty.as_ref(),
        Expr::StructLit(x) => x.ty.as_ref(),
        Expr::EnumCtor(x) => x.ty.as_ref(),
        Expr::FieldAccess(x) => x.ty.as_ref(),
        Expr::IsVariant(x) => x.ty.as_ref(),
        Expr::VariantField(x) => x.ty.as_ref(),
        Expr::Move(x) => x.ty.as_ref(),
        Expr::InoutArg(x) => x.ty.as_ref(),
    }
}

/// G3 A2 (4.8): does the candidate expression read a value whose static type involves a type parameter?
/// Decided on typed expressions: checker types on cloned nodes, and the position-based type table for names.
/// `len(x)` only reads the length, so it stays allowed for an abstract array.
fn abstract_expr(e: &Expr, tenv: &[(String, String)]) -> bool {
    if let Expr::Call(c) = e {
        if c.name == "len" {
            return false;
        }
    }
    if let Expr::Var(v) = e {
        if tyenv_get(tenv, &v.name).map_or(false, key_has_param) {
            return true;
        }
    }
    if expr_ty(e).map_or(false, |t| key_has_param(t)) {
        return true;
    }
    if let Expr::Index(x) = e {
        if let Expr::Var(a) = &*x.array {
            if tyenv_get(tenv, &a.name).map_or(false, key_has_param) {
                return true;
            }
        }
    }
    kids(e).into_iter().any(|c| abstract_expr(c, tenv))
}

/// G6 A1 (G6_SPEC 11.4; infer.py `_mentions_collection`): does the candidate mention a variable of collection type
/// (Vec/HashMap/String), or a `move`? Even `len(v)` counts.
fn mentions_collection(e: &Expr, tenv: &[(String, String)]) -> bool {
    if matches!(e, Expr::Move(_)) {
        return true;
    }
    if let Expr::Var(v) = e {
        return tyenv_get(tenv, &v.name)
            .map_or(false, |t| GType::try_from_key(t).map_or(false, |g| g.contains_collection()));
    }
    kids(e).into_iter().any(|c| mentions_collection(c, tenv))
}

/// `forall K in 0..len(x): A && B` in requires, {array name: (L, U)} (the first one per array). Preserves the requires order.
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
            let mut side: Option<(bool, i128)> = None; // (true = lo, value)
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

/// (lower bound, upper bound) of a term, or None (3.1 rng). Computed with saturating i128.
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
// Building candidate nodes: every node is at the loop position (3.4)
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
    /// Literal. None if |n| > i64 max (Python `_Skip`). Negatives are unary minus.
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
            targs: None,
            inst: None,
            old: None,
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

    /// A copy of e (at the loop position). sub = (name, factory): free Vars of that name are replaced by factory().
    /// Var and Quant are new nodes (no type); everything else carries over the original node's `ty` as is (same as Python `clone`).
    fn clone_e(&self, e: &Expr, sub: Option<(&str, &dyn Fn() -> Expr)>) -> Expr {
        let (line, col) = (self.line, self.col);
        match e {
            Expr::Var(x) => match sub {
                Some((n, f)) if x.name == n => f(),
                _ => Expr::Var(ast::Var { line, col, name: x.name.clone(), ty: None }),
            },
            // G6 A0: never reaches the proof layer (the driver's A0 guard stops the program earlier)
            Expr::Move(x) => Expr::Move(ast::Move { line, col, name: x.name.clone(), ty: None }),
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
            Expr::Spent(x) => Expr::Spent(ast::Spent { line, col, ty: x.ty.clone() }),
            Expr::IntLit(x) => Expr::IntLit(ast::IntLit { line, col, value: x.value.clone(), ty: x.ty.clone() }),
            Expr::BoolLit(x) => Expr::BoolLit(ast::BoolLit { line, col, value: x.value, ty: x.ty.clone() }),
            Expr::StrLit(x) => Expr::StrLit(ast::StrLit { line, col, value: x.value.clone(), ty: x.ty.clone() }),
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
                targs: x.targs.clone(),
                inst: x.inst.clone(),
                old: None,
            }),
            // G5 A0: never reaches the proof layer (the driver's A0 guard stops the program earlier)
            Expr::InoutArg(x) => Expr::InoutArg(ast::InoutArg {
                line,
                col,
                expr: Box::new(self.clone_e(&x.expr, sub)),
                ty: x.ty.clone(),
                post_refine: x.post_refine.clone(),
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
                targs: x.targs.clone(),
                inst: x.inst.clone(),
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
                targs: x.targs.clone(),
                inst: x.inst.clone(),
            }),
            Expr::EnumCtor(x) => Expr::EnumCtor(ast::EnumCtor {
                line,
                col,
                enum_name: x.enum_name.clone(),
                variant: x.variant.clone(),
                args: x.args.iter().map(|a| self.clone_e(a, sub)).collect(),
                ty: x.ty.clone(),
                targs: x.targs.clone(),
                inst: x.inst.clone(),
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
                enum_ty: x.enum_ty.clone(),
            }),
            Expr::VariantField(x) => Expr::VariantField(ast::VariantField {
                line,
                col,
                value: Box::new(self.clone_e(&x.value, sub)),
                enum_name: x.enum_name.clone(),
                variant: x.variant.clone(),
                field: x.field.clone(),
                ty: x.ty.clone(),
                enum_ty: x.enum_ty.clone(),
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
// Candidate generation (§3)
// ---------------------------------------------------------------------------
struct Cand {
    kind: u32,
    text: String,
    expr: Expr,
}

/// Does the expression contain a Call node other than `len` (user function, alloc, copy, print, is_some, etc.)? If so, no candidate is produced:
/// in a contract context the callee's requires is not checked and its ensures is assumed, which pollutes the path condition.
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

/// Left-hand N of a candidate expression: v if lo is IntLit 0, otherwise v - lo
fn n_of(b: &Bld, v: &str, lo: &Expr) -> Expr {
    if matches!(lo, Expr::IntLit(x) if lit_val(x) == Some(0)) {
        b.var(v)
    } else {
        b.bin("-", b.var(v), b.cl(lo))
    }
}

/// t if c0 == 0, otherwise c0 + t
fn with_c0(b: &Bld, c0: i128, t: Expr) -> Option<Expr> {
    if c0 == 0 {
        Some(t)
    } else {
        Some(b.bin("+", b.lit(c0)?, t))
    }
}

/// Coefficient c * N: 0 if c == 0, N if c == 1
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

/// "max" / "min": if X compares T and Var m in max/min form.
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

/// Candidates of loop w [(kind, string, expr)] (unsorted, may contain duplicates).
/// 3.1 counter definition: (pos(v), step c, lo = init(v)). None otherwise.
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

/// 3.7 srng(p): (lower bound, upper bound) of p from the top-level && terms of f.requires, each the first one found.
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
            // (true if lower bound, value)
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

/// 3.7 irng(e): (lower bound, upper bound) of an initial-value expression.
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
    let etab = elem_types(f, w); // G2 A5: per-loop-position table
    let m = assigned(&w.body);
    let mut cw: BTreeSet<String> = BTreeSet::new(); // G5 A1: names written by inout calls (never counter/store/prefix templates)
    call_written(&w.body, &mut cw);
    let mut loc: BTreeSet<String> = BTreeSet::new();
    locals(&w.body, &mut loc);
    let ns: BTreeSet<String> = m.union(&loc).cloned().collect();
    let mut asg: Vec<Asg> = Vec::new();
    assign_stmts(&w.body, &mut asg);
    let count_of = |name: &str| asg.iter().filter(|a| a.name() == name).count();
    let mut out: Vec<Cand> = Vec::new();

    // v occurs in e, and every other free name is outside M and not declared in the loop body
    let stable = |e: &Expr, v: &str| -> bool {
        let names = free_set(e);
        names.contains(v) && !names.iter().any(|n| n != v && ns.contains(n))
    };

    // ---- counters ----
    for v in &m {
        let mine: Vec<Asg> = asg.iter().filter(|s| s.name() == v.as_str()).copied().collect();
        if cw.contains(v) || mine.len() != 1 {
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

        // kind 1
        push(&mut out, 1, Some(b.bin("<=", b.cl(lo), b.var(v))));
        // kinds 2, 3: boundary expression of the loop condition
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

        // ---- accumulation statements before pos(v) ----
        for st2 in &w.body[..pos] {
            match st2 {
                // Simple sum:s = s + T | s = T + s
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
                // Conditional accumulation / max / min:if X { ... }
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
                    // max / min:if X { m = T; }
                    let mname = inner.name.as_str();
                    let tt = &inner.value;
                    let fr = free_set(tt);
                    if mname != v.as_str()
                        && count_of(mname) == 1
                        && fr.contains(v)
                        && !fr.iter().any(|n| loc.contains(n))
                    {
                        if let Some(kind) = maxmin(&i2.cond, mname, tt) {
                            // None = lower bound lo below, Some(n) = literal n
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

    // ---- B+ (spec 3.7, version 2): kinds 12, 13, 14 ----
    // Counter set CTR (all 3.1 definitions, in name-sorted order)
    let mut ctr: Vec<(&String, usize, i128, &Expr)> = Vec::new();
    for v in &m {
        if cw.contains(v) {
            continue; // G5 A1
        }
        if let Some((pos, c, lo)) = counter_info(w, &asg, &m, block, idx, v) {
            ctr.push((v, pos, c, lo));
        }
    }

    // kind 12: initial range of a scalar that is not a counter
    for v in &m {
        if ctr.iter().any(|(n, _, _, _)| *n == v) || cw.contains(v) {
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

    // kinds 13, 14
    for (v, pos, c, lo) in &ctr {
        if *c != 1 {
            continue;
        }
        let v: &str = v.as_str();
        for st2 in &w.body[..*pos] {
            match st2 {
                // 13: output array prefix `b[v] = E;`
                Stmt::IndexAssign(ia) if is_var(&ia.index, v) => {
                    let bn = ia.name.as_str();
                    if cw.contains(bn) || count_of(bn) != 1 {
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
                // 14: early-return prefix`if C { return R; }`
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

    // ---- arrays used only for element storage (kinds 4, 5) ----
    for bn in &m {
        let all_index = asg.iter().filter(|s| s.name() == bn.as_str()).all(|s| matches!(s, Asg::I(_)));
        if cw.contains(bn) || !all_index {
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
        for (src, (lo_, hi_)) in ranges {
            // only when the source array of the range and the target array have the same element type (not used if not found in the table)
            match (elem_type_of(&etab, src), elem_type_of(&etab, bn)) {
                (Some(a), Some(c2)) if a == c2 => {}
                _ => continue,
            }
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
    // G3 A2 (4.8): no template may read an abstract value (decided on typed expressions; all kinds).
    let tenv = scope_types(f, w);
    out.retain(|c| !abstract_expr(&c.expr, &tenv));
    // G6 A1 (G6_SPEC 11.4): no candidate about a collection-typed variable (infer.py `_mentions_collection`).
    out.retain(|c| !mentions_collection(&c.expr, &tenv));
    // No candidates (kinds 5-14) that read or write an array whose element type is bool (G3: or abstract).
    out.retain(|c| !(c.kind >= 5 && reads_bool_elem(&c.expr, &etab)));
    out
}

/// (sorted, deduplicated, truncated candidates; pre-truncation count `generated`; truncated count `capped`)
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
// Houdini driver (4.1) and report (5)
// ---------------------------------------------------------------------------
/// Record of one dropped candidate
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
    /// Live candidates (ID, expr, string)
    pub alive: Vec<ExtraInv>,
    pub dropped: Vec<Dropped>,
    /// (kind number, candidate) of the initial candidate list (after truncation, in rank order). Used by the version 1 fallback (4.1).
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
    /// Whether the version 1 fallback was done (4.1)
    pub fallback: bool,
    /// G4 A1: the function's file (explicit visibility mode only); the report records carry it as "file".
    pub file: Option<String>,
}

impl InferResult {
    /// {loop number: surviving candidates}. Loops with no candidates are absent (an empty table if all are empty).
    pub fn extra(&self) -> Extra {
        let mut m: Extra = HashMap::new();
        for l in &self.loops {
            if !l.alive.is_empty() {
                m.insert(l.n, std::rc::Rc::new(l.alive.clone()));
            }
        }
        m
    }

    /// One report record per loop. new_errors = number of final verification errors of this function.
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
                ("line".to_string(), Json::int(pruv_core::diagnostic::plain_line(l.line))),
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
            if let Some(file) = &self.file {
                // G4 A1: explicit mode only (legacy records keep their exact key set; keys are sorted on output)
                rec.push(("file".to_string(), Json::Str(file.clone())));
            }
            if self.fallback {
                rec.push(("fallback".to_string(), Json::str("v1")));
            }
            out.push(Json::Obj(rec));
        }
        out
    }
}

/// Houdini round iteration (4.1). `r` is the round number so far (counting continues). On budget exhaustion or timeout, sets `res.status` and
/// empties all candidates. Shared by the first search and the fallback search.
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
            break; // no (more) candidates: no round
        }
        *r += 1;
        probe.begin_round();
        let run_result: R<()> = {
            let z = Z3::new();
            let pre = Prelude::new(&z);
            let model = Model::for_program(&z, &pre, decls, prog, seq)?;
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
            // Budget exhausted / timeout: Python left run via an exception, so internal errors after that are not seen.
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

/// infer.py `infer_function`: candidates + Houdini rounds for one function (+ 4.1 version 1 fallback). Does not touch the error list.
/// A fresh z3 context, Prelude and Model (same `seq`) is created per round.
pub fn infer_function(
    prog: &ast::Program,
    f: &ast::Function,
    decls: &[TypeDecl],
    seq: u32,
    rec: &mut Trace,
) -> R<InferResult> {
    if let Some(e) = pruv_core::typeinfo::s5_unimplemented_error(prog) { return Err(format!("{}: {}", e.code, e.message)); }
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
        file: pruv_core::diagnostic::file_of_tag(pruv_core::diagnostic::line_tag(f.line)),
    };
    let deadline = Instant::now() + Duration::from_secs(MAX_SECONDS);
    let mut probe = Probe::new(MAX_QUERIES, deadline);
    let mut r: u32 = 0;
    houdini_rounds(prog, f, decls, seq, rec, &mut res, &mut probe, &mut r)?;
    let mut queries = probe.queries;

    // 4.1 version 1 fallback: if the budget was exhausted and the initial candidates included kind 12 or above, retry with kinds 1-11 only.
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
