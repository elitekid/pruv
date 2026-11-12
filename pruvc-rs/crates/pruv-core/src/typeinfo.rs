//! User struct/enum type information (counterpart of typeinfo.py).
//! `type_name` gives the source spelling of every type, and `TypeTable` indexes the declarations of the checked program.

use crate::ast::*;
use crate::gtype::{dependencies, format_type, is_g3_key, GType};
use std::collections::{HashMap, HashSet};

/// G6 A0: also the internal names of the owned collection types (vec / hashmap / string).
pub const BUILTIN_TYPE_NAMES: [&str; 13] = [
    "i64", "bool", "unit", "array", "option", "result", "array_u8", "array_bool", "str", "vec", "hashmap", "string", "file",
];

/// A name that is not built in is a user type (whether or not it is declared).
pub fn is_user_type(ty: &str) -> bool {
    !BUILTIN_TYPE_NAMES.contains(&ty)
}

/// Whether this is an internal array type name ("array"/"array_u8"/"array_bool").
pub fn is_array_name(n: &str) -> bool {
    array_elem_name(n).is_some()
}

/// Internal array type name -> element type name.
pub fn array_elem_name(n: &str) -> Option<&'static str> {
    match n {
        "array" => Some("i64"),
        "array_u8" => Some("u8"),
        "array_bool" => Some("bool"),
        _ => None,
    }
}

/// Element type name -> internal array type name.
pub fn array_of_elem_name(e: &str) -> Option<&'static str> {
    match e {
        "i64" => Some("array"),
        "u8" => Some("array_u8"),
        "bool" => Some("array_bool"),
        _ => None,
    }
}

/// Source-level spelling. A user type keeps its own name.
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
        "string" => "String".to_string(), // G6 A0
        "file" => "File".to_string(),     // G10 A0
        other => other.to_string(),
    }
}

/// Shared walk: the first position where `pick(type name)` is true.
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

/// Keeps the candidate position with the smallest (line, col) (the one seen first if equal).
fn g2_cand(best: &mut Option<(i64, i64, String)>, line: i64, col: i64, ty: &str) {
    let better = match best {
        None => true,
        Some(b) => (line, col) < (b.0, b.1),
    };
    if better {
        *best = Some((line, col, ty.to_string()));
    }
}

/// Takes every StrLit in an expression as a candidate (listing all variants, with no wildcard).
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
        Expr::Move(_) => {} // G6 A0
        Expr::InoutArg(x) => g2_cand_expr(&x.expr, lits, best), // G5 A0
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

/// Takes the Let types (pick) in a statement and the StrLit of every expression as candidates (listing all variants, with no wildcard).
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
            Stmt::Par(e) => {
                for c in &e.calls {
                    g2_cand_expr(c, lits, best);
                }
            }
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

/// Where a type of a not-yet-implemented layer (an array other than `[i64]`, `str`) first appears: (line, col, internal type name).
/// In function declaration order, in the first function that matches: parameters -> return type -> the smallest (line, col) among that function's candidate positions (body Let types,
/// and, if `str` is not in skip, the StrLit of every expression in requires/ensures/body).
/// Internal names contained in `skip` are skipped.
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

/// Whether any parameter, return or let type of the program has the internal name `name`.
pub fn uses_array_type(prog: &Program, name: &str) -> bool {
    g2_walk(prog, &|t: &str| t == name).is_some()
}

/// G2 B2: whether a parameter, return or (nested) let type is `str`, or any expression in requires/ensures/body has a StrLit.
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

/// Turns `first_g2_unimplemented` into a diagnostic. stage is the name of the blocked layer, such as "verify" / "codegen".
/// If layer is given it is used as the layer name in the message, and if fix is given it replaces the fix hint.
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

// ---------------------------------------------------------------------------
// G3 A1 staging guard (G3_SPEC 7.3): the verifier and both code generators do not support generics yet.
// ---------------------------------------------------------------------------
type G3Cands = Vec<(i64, i64, String)>;

fn g3_push(out: &mut G3Cands, line: i64, col: i64, what: String) {
    out.push((line, col, what));
}

fn g3_ty(out: &mut G3Cands, line: i64, col: i64, ty: &str) {
    if is_g3_key(ty) {
        g3_push(out, line, col, format!("type {}", format_type(&GType::from_key(ty))));
    }
}

fn g3_expr(e: &Expr, out: &mut G3Cands) {
    let app = |out: &mut G3Cands, line: i64, col: i64, targs: &Option<Vec<GType>>| {
        if targs.is_some() {
            g3_push(out, line, col, "a type application".to_string());
        }
    };
    match e {
        Expr::IntLit(_) | Expr::BoolLit(_) | Expr::StrLit(_) | Expr::Var(_) | Expr::Move(_) => {}
        Expr::InoutArg(x) => g3_expr(&x.expr, out), // G5 A0
        Expr::Unary(x) => g3_expr(&x.operand, out),
        Expr::Binary(x) => {
            g3_expr(&x.left, out);
            g3_expr(&x.right, out);
        }
        Expr::Call(x) => {
            app(out, x.line, x.col, &x.targs);
            for a in &x.args {
                g3_expr(a, out);
            }
        }
        Expr::Index(x) => {
            g3_expr(&x.array, out);
            g3_expr(&x.index, out);
        }
        Expr::Ctor(x) => {
            app(out, x.line, x.col, &x.targs);
            if let Some(a) = &x.arg {
                g3_expr(a, out);
            }
        }
        Expr::Quant(x) => {
            g3_expr(&x.lo, out);
            g3_expr(&x.hi, out);
            g3_expr(&x.body, out);
        }
        Expr::StructLit(x) => {
            app(out, x.line, x.col, &x.targs);
            for f in &x.fields {
                g3_expr(&f.value, out);
            }
        }
        Expr::EnumCtor(x) => {
            app(out, x.line, x.col, &x.targs);
            for a in &x.args {
                g3_expr(a, out);
            }
        }
        Expr::FieldAccess(x) => g3_expr(&x.base, out),
        Expr::IsVariant(x) => g3_expr(&x.value, out),
        Expr::VariantField(x) => g3_expr(&x.value, out),
    }
}

fn g3_stmts(stmts: &[Stmt], out: &mut G3Cands) {
    for s in stmts {
        match s {
            Stmt::Let(l) => {
                g3_ty(out, l.line, l.col, &l.ty);
                g3_expr(&l.value, out);
            }
            Stmt::Assign(a) => g3_expr(&a.value, out),
            Stmt::IndexAssign(a) => {
                g3_expr(&a.index, out);
                g3_expr(&a.value, out);
            }
            Stmt::If(i) => {
                g3_expr(&i.cond, out);
                g3_stmts(&i.then, out);
                g3_stmts(&i.els, out);
            }
            Stmt::While(w) => {
                g3_expr(&w.cond, out);
                for inv in &w.invariants {
                    g3_expr(inv, out);
                }
                g3_expr(&w.decreases, out);
                g3_stmts(&w.body, out);
            }
            Stmt::Return(r) => {
                if let Some(v) = &r.value {
                    g3_expr(v, out);
                }
            }
            Stmt::Assert(a) => g3_expr(&a.cond, out),
            Stmt::Par(e) => {
                for c in &e.calls {
                    g3_expr(c, out);
                }
            }
            Stmt::ExprStmt(e) => g3_expr(&e.expr, out),
            Stmt::FieldAssign(f) => g3_expr(&f.value, out),
            Stmt::Match(m) => {
                g3_expr(&m.scrutinee, out);
                for arm in &m.arms {
                    g3_stmts(&arm.body, out);
                }
            }
        }
    }
}

/// First G3 construct of a checked program -> (line, col, what): a type-parameter list, a type application or
/// parameter in any signature / field / let type, or an explicit type application. The smallest (line, col) wins
/// (the first one seen on a tie), exactly like Python.
pub fn first_g3_use(prog: &Program) -> Option<(i64, i64, String)> {
    let mut cands: G3Cands = Vec::new();
    for d in &prog.types {
        if !d.tparams().is_empty() {
            g3_push(&mut cands, d.line(), d.col(), format!("generic type {}", d.name()));
        }
        for f in d.all_fields() {
            g3_ty(&mut cands, f.line, f.col, &f.ty);
        }
    }
    for f in &prog.functions {
        if !f.tparams.is_empty() {
            g3_push(&mut cands, f.line, f.col, format!("generic function {}", f.name));
        }
        for p in &f.params {
            g3_ty(&mut cands, f.line, f.col, &p.ty);
        }
        g3_ty(&mut cands, f.line, f.col, &f.ret);
        for e in &f.requires {
            g3_expr(e, &mut cands);
        }
        for e in &f.ensures {
            g3_expr(e, &mut cands);
        }
        g3_stmts(&f.body, &mut cands);
    }
    let mut best: Option<(i64, i64, String)> = None;
    for c in cands {
        let better = match &best {
            None => true,
            Some(b) => (c.0, c.1) < (b.0, b.1),
        };
        if better {
            best = Some(c);
        }
    }
    best
}

/// PruvError (unsupported_type) for the first G3 construct, or None. Run after type checking, before the verifier,
/// so that --no-verify and every back end reject generics explicitly instead of crashing.
pub fn g3_unimplemented_error(prog: &Program, stage: &str) -> Option<crate::diagnostic::PruvError> {
    let (line, col, what) = first_g3_use(prog)?;
    Some(crate::diagnostic::PruvError::new(
        stage,
        line,
        col,
        "unsupported_type",
        format!("generics are not supported yet ({}): the verify and codegen layers are not implemented", what),
        "avoid type parameters and type arguments for now",
    ))
}

// ---------------------------------------------------------------------------
// G9 A0 staging guard: the verifier and both code generators do not support recursion, decreases, size,
// recursive types or aggregate buffer fields yet (G9_SPEC 10, 11-13 replace this guard batch by batch).
// ---------------------------------------------------------------------------

/// Collects (line, col) of every `size(..)` call under the expression (Python `_g9_size_calls`: a generic walk).
fn g9_size_expr(e: &Expr, out: &mut Vec<(i64, i64)>) {
    match e {
        Expr::IntLit(_) | Expr::BoolLit(_) | Expr::StrLit(_) | Expr::Var(_) | Expr::Move(_) => {}
        Expr::InoutArg(x) => g9_size_expr(&x.expr, out), // G5 A0
        Expr::Unary(x) => g9_size_expr(&x.operand, out),
        Expr::Binary(x) => {
            g9_size_expr(&x.left, out);
            g9_size_expr(&x.right, out);
        }
        Expr::Call(x) => {
            if x.name == "size" {
                out.push((x.line, x.col));
            }
            for a in &x.args {
                g9_size_expr(a, out);
            }
        }
        Expr::Index(x) => {
            g9_size_expr(&x.array, out);
            g9_size_expr(&x.index, out);
        }
        Expr::Ctor(x) => {
            if let Some(a) = &x.arg {
                g9_size_expr(a, out);
            }
        }
        Expr::Quant(x) => {
            g9_size_expr(&x.lo, out);
            g9_size_expr(&x.hi, out);
            g9_size_expr(&x.body, out);
        }
        Expr::StructLit(x) => {
            for f in &x.fields {
                g9_size_expr(&f.value, out);
            }
        }
        Expr::EnumCtor(x) => {
            for a in &x.args {
                g9_size_expr(a, out);
            }
        }
        Expr::FieldAccess(x) => g9_size_expr(&x.base, out),
        Expr::IsVariant(x) => g9_size_expr(&x.value, out),
        Expr::VariantField(x) => g9_size_expr(&x.value, out),
    }
}

fn g9_size_stmts(stmts: &[Stmt], out: &mut Vec<(i64, i64)>) {
    for s in stmts {
        match s {
            Stmt::Let(l) => g9_size_expr(&l.value, out),
            Stmt::Assign(a) => g9_size_expr(&a.value, out),
            Stmt::IndexAssign(a) => {
                g9_size_expr(&a.index, out);
                g9_size_expr(&a.value, out);
            }
            Stmt::If(i) => {
                g9_size_expr(&i.cond, out);
                g9_size_stmts(&i.then, out);
                g9_size_stmts(&i.els, out);
            }
            Stmt::While(w) => {
                g9_size_expr(&w.cond, out);
                for inv in &w.invariants {
                    g9_size_expr(inv, out);
                }
                g9_size_expr(&w.decreases, out);
                g9_size_stmts(&w.body, out);
            }
            Stmt::Return(r) => {
                if let Some(v) = &r.value {
                    g9_size_expr(v, out);
                }
            }
            Stmt::Assert(a) => g9_size_expr(&a.cond, out),
            Stmt::Par(e) => {
                for c in &e.calls {
                    g9_size_expr(c, out);
                }
            }
            Stmt::ExprStmt(e) => g9_size_expr(&e.expr, out),
            Stmt::FieldAssign(f) => g9_size_expr(&f.value, out),
            Stmt::Match(m) => {
                g9_size_expr(&m.scrutinee, out);
                for arm in &m.arms {
                    g9_size_stmts(&arm.body, out);
                }
            }
        }
    }
}

/// First G9 construct of a checked program -> (line, col, what) or None: a function with a decreases clause,
/// a function of a recursive call-graph SCC, a recursive type declaration, an array/str field, a `size` call.
/// The smallest (line, col) wins (the first one seen on a tie), exactly like Python.
pub fn first_g9_use(prog: &Program) -> Option<(i64, i64, String)> {
    let mut cands: Vec<(i64, i64, String)> = Vec::new();
    let mut rec_types: HashSet<&str> = HashSet::new();
    let mut rec_fns: HashSet<&str> = HashSet::new();
    if let Some(meta) = &prog.g9 {
        for scc in &meta.type_sccs {
            rec_types.extend(scc.iter().map(|s| s.as_str()));
        }
        for scc in &meta.fn_sccs {
            rec_fns.extend(scc.iter().map(|s| s.as_str()));
        }
    }
    for d in &prog.types {
        if rec_types.contains(d.name()) {
            cands.push((d.line(), d.col(), format!("recursive type {}", d.name())));
        }
        for fd in d.all_fields() {
            let ft = GType::from_key(&fd.ty);
            if ft.is_array() || ft == GType::str() {
                cands.push((fd.line, fd.col, format!("buffer field {}", fd.name)));
            }
        }
    }
    for f in &prog.functions {
        if let Some(d) = &f.decreases {
            cands.push((d.line(), d.col(), "decreases clause".to_string()));
        }
        if rec_fns.contains(f.name.as_str()) {
            cands.push((f.line, f.col, format!("recursive function {}", f.name)));
        }
        let mut sizes: Vec<(i64, i64)> = Vec::new();
        for e in &f.requires {
            g9_size_expr(e, &mut sizes);
        }
        for e in &f.ensures {
            g9_size_expr(e, &mut sizes);
        }
        g9_size_stmts(&f.body, &mut sizes);
        if let Some(d) = &f.decreases {
            g9_size_expr(d, &mut sizes);
        }
        for (l, c) in sizes {
            cands.push((l, c, "size".to_string()));
        }
    }
    let mut best: Option<(i64, i64, String)> = None;
    for c in cands {
        let better = match &best {
            None => true,
            Some(b) => (c.0, c.1) < (b.0, b.1),
        };
        if better {
            best = Some(c);
        }
    }
    best
}

/// PruvError (unsupported_type) for the first G9 construct, or None. Run right after type checking.
pub fn g9_unimplemented_error(prog: &Program, stage: &str, layer: &str) -> Option<crate::diagnostic::PruvError> {
    let (line, col, _what) = first_g9_use(prog)?;
    Some(crate::diagnostic::PruvError::new(
        stage,
        line,
        col,
        "unsupported_type",
        format!("G9 recursive values and aggregate buffer fields are not implemented by the {} yet", layer),
        "avoid recursion, decreases, size, recursive types and array/str fields for now",
    ))
}

// ---------------------------------------------------------------------------
// G5 A0: inout parameters. `program_uses_inout` (parse level) drives the contextual `old` builtin (G5_SPEC 9; the A0-A2
// staging guard is gone since A3: both back ends lower inout parameters).
// ---------------------------------------------------------------------------

/// Calls `f` on every expression node under `e` (pre-order), operands included (Python generic dataclass walk).
fn g5_walk_expr(e: &Expr, f: &mut dyn FnMut(&Expr)) {
    f(e);
    for k in crate::refine::kids(e) {
        g5_walk_expr(k, f);
    }
}

/// Calls `f` on every expression node of the statements (Python generic dataclass walk).
fn g5_walk_stmts(stmts: &[Stmt], f: &mut dyn FnMut(&Expr)) {
    for s in stmts {
        match s {
            Stmt::Let(l) => g5_walk_expr(&l.value, f),
            Stmt::Assign(a) => g5_walk_expr(&a.value, f),
            Stmt::IndexAssign(a) => {
                g5_walk_expr(&a.index, f);
                g5_walk_expr(&a.value, f);
            }
            Stmt::If(i) => {
                g5_walk_expr(&i.cond, f);
                g5_walk_stmts(&i.then, f);
                g5_walk_stmts(&i.els, f);
            }
            Stmt::While(w) => {
                g5_walk_expr(&w.cond, f);
                for inv in &w.invariants {
                    g5_walk_expr(inv, f);
                }
                g5_walk_expr(&w.decreases, f);
                g5_walk_stmts(&w.body, f);
            }
            Stmt::Return(r) => {
                if let Some(v) = &r.value {
                    g5_walk_expr(v, f);
                }
            }
            Stmt::Assert(a) => g5_walk_expr(&a.cond, f),
            Stmt::Par(e) => {
                for c in &e.calls {
                    g5_walk_expr(c, f);
                }
            }
            Stmt::ExprStmt(e) => g5_walk_expr(&e.expr, f),
            Stmt::FieldAssign(x) => g5_walk_expr(&x.value, f),
            Stmt::Match(m) => {
                g5_walk_expr(&m.scrutinee, f);
                for arm in &m.arms {
                    g5_walk_stmts(&arm.body, f);
                }
            }
        }
    }
}

/// Calls `f` on every expression node of a function: requires, ensures, body, decreases (Python order).
fn g5_walk_fn(fun: &Function, f: &mut dyn FnMut(&Expr)) {
    for e in &fun.requires {
        g5_walk_expr(e, f);
    }
    for e in &fun.ensures {
        g5_walk_expr(e, f);
    }
    g5_walk_stmts(&fun.body, f);
    if let Some(d) = &fun.decreases {
        g5_walk_expr(d, f);
    }
}

/// True if some parameter has the inout mode or some call argument carries the inout marker.
pub fn program_uses_inout(prog: &Program) -> bool {
    // signatures first: a cheap scan that settles most inout programs without walking any body
    if prog.functions.iter().any(|f| f.params.iter().any(|p| p.mode_pos.is_some())) {
        return true;
    }
    for fun in &prog.functions {
        let mut found = false;
        g5_walk_fn(fun, &mut |e| {
            if matches!(e, Expr::InoutArg(_)) {
                found = true;
            }
        });
        if found {
            return true;
        }
    }
    false
}

impl TypeDecl {
    /// The declared name.
    pub fn name(&self) -> &str {
        match self {
            TypeDecl::Struct(s) => &s.name,
            TypeDecl::Enum(e) => &e.name,
        }
    }
    /// The declared type parameters (empty for a non-generic declaration).
    pub fn tparams(&self) -> &[TParam] {
        match self {
            TypeDecl::Struct(s) => &s.tparams,
            TypeDecl::Enum(e) => &e.tparams,
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
    /// For a struct its fields, for an enum the fields of all variants, in declaration order.
    pub fn all_fields(&self) -> Vec<&FieldDecl> {
        match self {
            TypeDecl::Struct(s) => s.fields.iter().collect(),
            TypeDecl::Enum(e) => e.variants.iter().flat_map(|v| v.fields.iter()).collect(),
        }
    }
}

#[derive(Debug, Clone, Default)]
pub struct TypeTable {
    /// Declaration order (first declaration wins, no duplicate names).
    pub decls: Vec<TypeDecl>,
    index: HashMap<String, usize>,
    /// Dependencies first, declaration-stable order: indices into `decls`.
    pub order: Vec<usize>,
    /// Memo of llvmgen::words (word count of the external form) per type key.
    pub words_memo: std::cell::RefCell<HashMap<String, usize>>,
    /// Memo of `holds_buffer` per declared type name.
    pub buffer_memo: std::cell::RefCell<HashMap<String, bool>>,
    /// G9 A0: checker metadata (type_sccs, boxed, extended, fn_sccs), only when the program has a G9 feature.
    pub g9: Option<G9Meta>,
    /// G9 A3 (Python `tt.g9_ext`): names of the extended declarations; set by `llvmgen::new_tt`, empty otherwise.
    pub g9_ext: HashSet<String>,
    /// G9 A3 (Python `tt.g9_boxed`): labels of the boxed fields; set by `llvmgen::new_tt`, empty otherwise.
    pub g9_boxed: HashSet<String>,
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

    /// Declarations listed in dependency order.
    pub fn ordered(&self) -> impl Iterator<Item = &TypeDecl> {
        self.order.iter().map(move |&i| &self.decls[i])
    }

    /// In field order, without duplicates, declared names only.
    /// G9 (Python `TypeTable.holds_buffer`): a value of the declared type `name` can hold an array or str field,
    /// directly or through a field type.
    pub fn holds_buffer(&self, name: &str) -> bool {
        if let Some(&b) = self.buffer_memo.borrow().get(name) {
            return b;
        }
        let b = self.holds_buffer_walk(name);
        self.buffer_memo.borrow_mut().insert(name.to_string(), b);
        b
    }

    fn holds_buffer_walk(&self, name: &str) -> bool {
        let mut seen: HashSet<String> = HashSet::new();
        let mut todo: Vec<String> = vec![name.to_string()];
        while let Some(n) = todo.pop() {
            if seen.contains(&n) {
                continue;
            }
            let d = match self.decl(&n) {
                Some(d) => d,
                None => continue,
            };
            seen.insert(n.clone());
            if d.all_fields().iter().any(|f| is_array_name(&f.ty) || f.ty == "str") {
                return true;
            }
            todo.extend(self.deps(d));
        }
        false
    }

    pub fn deps(&self, d: &TypeDecl) -> Vec<String> {
        let mut out: Vec<String> = Vec::new();
        for f in d.all_fields() {
            // G3: a nominal reference anywhere inside the field type (nested arguments included) is an edge
            for n in dependencies(&GType::from_key(&f.ty)) {
                if self.index.contains_key(&n) && !out.contains(&n) {
                    out.push(n);
                }
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
            return; // mark first: no infinite loop even with a cycle (which the checker rejects)
        }
        for n in self.deps(&self.decls[i]) {
            if let Some(&j) = self.index.get(&n) {
                self.visit(j, seen, order);
            }
        }
        order.push(i);
    }

    // ---- lookup ----
    pub fn decl(&self, ty: &str) -> Option<&TypeDecl> {
        self.index.get(ty).map(|&i| &self.decls[i])
    }

    pub fn is_struct(&self, ty: &str) -> bool {
        matches!(self.decl(ty), Some(TypeDecl::Struct(_))) && is_user_type(ty)
    }

    pub fn is_enum(&self, ty: &str) -> bool {
        matches!(self.decl(ty), Some(TypeDecl::Enum(_))) && is_user_type(ty)
    }

    /// A variant of an enum (None if missing or not an enum).
    pub fn variant(&self, ty: &str, variant: &str) -> Option<&VariantDecl> {
        match self.decl(ty) {
            Some(TypeDecl::Enum(e)) => e.variants.iter().find(|v| v.name == variant),
            _ => None,
        }
    }

    /// A struct's fields, or the fields of an enum's `variant` (declaration order). None if not found.
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
        assert_eq!(BUILTIN_TYPE_NAMES.len(), 13);
        assert_eq!(type_name("string"), "String");
    }
}
