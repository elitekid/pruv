//! Type, effect and structure checker (counterpart of check.py). Fills in `ty` for every expression.
//! Function structure, check order, code, stage, message and fix match Python character for character.

use crate::ast::*;
use crate::diagnostic::PruvError;
use crate::typeinfo::{is_array_name, is_user_type, type_name, TypeTable};
use std::collections::{BTreeSet, HashMap, HashSet};
use std::rc::Rc;

const I64: &str = "i64";
const BOOL: &str = "bool";
const UNIT: &str = "unit";
const ARRAY: &str = "array";
const STR: &str = "str";
const OPTION: &str = "option";
const RESULT: &str = "result";

type Res<T> = Result<T, PruvError>;

/// Built-ins used only in contracts: name -> (argument types, result type).
fn contract_only(n: &str) -> Option<(&'static str, &'static str)> {
    match n {
        "is_some" => Some((OPTION, BOOL)),
        "some_val" => Some((OPTION, I64)),
        "is_ok" => Some((RESULT, BOOL)),
        "ok_val" => Some((RESULT, I64)),
        "err_val" => Some((RESULT, I64)),
        _ => None,
    }
}

const RESERVED_TYPE_NAMES: [&str; 6] = ["Option", "Result", "Some", "None", "Ok", "Err"];

fn is_tail(s: &str) -> bool {
    s.chars().all(|c| c.is_ascii_alphanumeric() || c == '_')
}

/// ^[A-Z][A-Za-z0-9_]*$ (ASCII)
fn type_name_ok(s: &str) -> bool {
    match s.chars().next() {
        Some(c) if c.is_ascii_uppercase() => is_tail(&s[1..]),
        _ => false,
    }
}

/// ^[a-z][A-Za-z0-9_]*$ (ASCII)
fn field_name_ok(s: &str) -> bool {
    match s.chars().next() {
        Some(c) if c.is_ascii_lowercase() => is_tail(&s[1..]),
        _ => false,
    }
}

/// Converts only the first character to ASCII case (names are ASCII identifiers, never empty).
fn cap_first(s: &str, upper: bool) -> String {
    let mut it = s.chars();
    match it.next() {
        Some(c) => {
            let c = if upper { c.to_ascii_uppercase() } else { c.to_ascii_lowercase() };
            format!("{}{}", c, it.as_str())
        }
        None => String::new(),
    }
}

fn terr(line: i64, col: i64, code: &str, msg: impl Into<String>, fix: impl Into<String>) -> PruvError {
    PruvError::new("type", line, col, code, msg, fix)
}

/// Whether the integer literal (sign plus decimal string) is in the i64 range: -2^63 <= v < 2^63.
fn int_in_range(v: &str) -> bool {
    let (neg, rest) = if let Some(r) = v.strip_prefix('-') {
        (true, r)
    } else if let Some(r) = v.strip_prefix('+') {
        (false, r)
    } else {
        (false, v)
    };
    let d = rest.trim_start_matches('0');
    let limit = if neg { "9223372036854775808" } else { "9223372036854775807" };
    d.len() < limit.len() || (d.len() == limit.len() && d <= limit)
}

#[derive(Clone)]
struct Entry {
    ty: String,
    mutable: bool,
    kind: &'static str, // "param" | "result" | "local" | "bound"
}
type Scope = HashMap<String, Entry>;

struct FuncInfo {
    line: i64,
    col: i64,
    params: Vec<String>,
    ret: String,
    effects: Vec<String>,
}

struct Checker {
    funcs: HashMap<String, Rc<FuncInfo>>,
    func_order: Vec<String>,
    calls: HashMap<String, BTreeSet<String>>,
    decls: HashMap<String, TypeDecl>, // first declaration
    tt: TypeTable,
    cur_name: String,
    cur_ret: String,
    used_effects: BTreeSet<String>,
    /// Expected array type, turned on only when the right-hand expression of a let/reassignment/return is itself an alloc call (alloc takes it right away).
    alloc_want: Option<String>,
}

/// Checks the program, fills in ty for every expression, and returns the type table.
pub fn check(prog: &mut Program) -> Result<TypeTable, PruvError> {
    let mut c = Checker::new(prog)?;
    c.run(prog)?;
    Ok(c.tt)
}

fn ends_in_return(stmts: &[Stmt]) -> bool {
    match stmts.last() {
        None => false,
        Some(Stmt::Return(_)) => true,
        Some(Stmt::If(i)) => ends_in_return(&i.then) && ends_in_return(&i.els),
        Some(Stmt::Match(m)) => m.arms.iter().all(|a| ends_in_return(&a.body)),
        Some(_) => false,
    }
}

fn set_ty(e: &mut Expr, t: &str) {
    let v = Some(t.to_string());
    match e {
        Expr::IntLit(x) => x.ty = v,
        Expr::BoolLit(x) => x.ty = v,
        Expr::StrLit(x) => x.ty = v,
        Expr::Var(x) => x.ty = v,
        Expr::Unary(x) => x.ty = v,
        Expr::Binary(x) => x.ty = v,
        Expr::Call(x) => x.ty = v,
        Expr::Index(x) => x.ty = v,
        Expr::Ctor(x) => x.ty = v,
        Expr::Quant(x) => x.ty = v,
        Expr::StructLit(x) => x.ty = v,
        Expr::EnumCtor(x) => x.ty = v,
        Expr::FieldAccess(x) => x.ty = v,
        Expr::IsVariant(x) => x.ty = v,
        Expr::VariantField(x) => x.ty = v,
    }
}

impl Checker {
    fn new(prog: &Program) -> Res<Checker> {
        let mut funcs: HashMap<String, Rc<FuncInfo>> = HashMap::new();
        let mut func_order = Vec::new();
        for f in &prog.functions {
            if funcs.contains_key(&f.name) {
                return Err(terr(f.line, f.col, "dup_fn", format!("function {} defined twice", f.name), ""));
            }
            if matches!(f.name.as_str(), "len" | "alloc" | "copy" | "print" | "is_char_boundary" | "substr") || contract_only(&f.name).is_some() {
                return Err(terr(f.line, f.col, "reserved", format!("{} is a builtin name", f.name), "rename the function"));
            }
            funcs.insert(
                f.name.clone(),
                Rc::new(FuncInfo {
                    line: f.line,
                    col: f.col,
                    params: f.params.iter().map(|p| p.ty.clone()).collect(),
                    ret: f.ret.clone(),
                    effects: f.effects.clone(),
                }),
            );
            func_order.push(f.name.clone());
        }
        Ok(Checker {
            funcs,
            func_order,
            calls: HashMap::new(),
            decls: HashMap::new(),
            tt: TypeTable::default(),
            cur_name: String::new(),
            cur_ret: String::new(),
            used_effects: BTreeSet::new(),
            alloc_want: None,
        })
    }

    /// If the value is itself an alloc call and the expected type is an array, sets alloc's result type to that array type.
    fn want_alloc(&mut self, value: &Expr, ty: &str) {
        if let Expr::Call(c) = value {
            if c.name == "alloc" && is_array_name(ty) {
                self.alloc_want = Some(ty.to_string());
            }
        }
    }

    fn run(&mut self, prog: &mut Program) -> Res<()> {
        crate::refine::expand(prog)?; // STAGE1 A: validate refinement annotations, then expand them into contracts/asserts
        self.declare_types(&prog.types)?;
        self.resolve_types(prog)?;
        self.type_recursion(&prog.types)?;
        self.tt = TypeTable::new(&prog.types);
        for f in prog.functions.iter_mut() {
            self.fn_(f)?;
        }
        self.no_recursion()
    }

    // ---- user type declarations ----
    fn declare_types(&mut self, types: &[TypeDecl]) -> Res<()> {
        for d in types {
            let (name, line, col) = (d.name(), d.line(), d.col());
            if !type_name_ok(name) {
                return Err(terr(
                    line,
                    col,
                    "type_name",
                    format!("type name {} must start with an upper-case letter", name),
                    format!("rename it, e.g. {}", cap_first(name, true)),
                ));
            }
            if RESERVED_TYPE_NAMES.contains(&name) {
                return Err(terr(line, col, "reserved", format!("{} is a builtin name", name), "rename the type"));
            }
            if self.decls.contains_key(name) {
                return Err(terr(line, col, "dup_type", format!("type {} defined twice", name), ""));
            }
            if self.funcs.contains_key(name) {
                return Err(terr(
                    line,
                    col,
                    "name_collision",
                    format!("{} is both a type and a function", name),
                    "rename the type or the function",
                ));
            }
            self.decls.insert(name.to_string(), d.clone());
            match d {
                TypeDecl::Struct(s) => self.check_field_names(&s.fields, &format!("struct {}", name))?,
                TypeDecl::Enum(e) => {
                    if e.variants.is_empty() {
                        return Err(terr(line, col, "empty_enum", format!("enum {} has no variants", name), "add at least one variant"));
                    }
                    // Duplicate checking uses a set like a Python set (audit: a Vec is O(n^2)).
                    let mut seen: HashSet<&str> = HashSet::new();
                    for v in &e.variants {
                        if !type_name_ok(&v.name) {
                            return Err(terr(
                                v.line,
                                v.col,
                                "variant_name",
                                format!("variant name {} must start with an upper-case letter", v.name),
                                format!("rename it, e.g. {}", cap_first(&v.name, true)),
                            ));
                        }
                        if seen.contains(v.name.as_str()) {
                            return Err(terr(
                                v.line,
                                v.col,
                                "dup_variant",
                                format!("variant {} defined twice in enum {}", v.name, name),
                                "",
                            ));
                        }
                        seen.insert(&v.name);
                        self.check_field_names(&v.fields, &format!("variant {}::{}", name, v.name))?;
                    }
                }
            }
        }
        Ok(())
    }

    fn check_field_names(&self, fields: &[FieldDecl], wher: &str) -> Res<()> {
        let mut seen: HashSet<&str> = HashSet::new();
        for f in fields {
            if !field_name_ok(&f.name) {
                return Err(terr(
                    f.line,
                    f.col,
                    "field_name",
                    format!("field name {} must start with a lower-case letter", f.name),
                    format!("rename it, e.g. {}", cap_first(&f.name, false)),
                ));
            }
            if seen.contains(f.name.as_str()) {
                return Err(terr(f.line, f.col, "dup_field", format!("field {} defined twice in {}", f.name, wher), ""));
            }
            seen.insert(&f.name);
        }
        Ok(())
    }

    fn check_type_ref(&self, line: i64, col: i64, ty: &str) -> Res<()> {
        if is_user_type(ty) && !self.decls.contains_key(ty) {
            return Err(terr(
                line,
                col,
                "unknown_type",
                format!("unknown type {}", ty),
                format!("declare it with `struct {} {{ ... }}` or `enum {} {{ ... }}`", ty, ty),
            ));
        }
        Ok(())
    }

    fn resolve_types(&self, prog: &Program) -> Res<()> {
        for d in &prog.types {
            let groups: Vec<&Vec<FieldDecl>> = match d {
                TypeDecl::Struct(s) => vec![&s.fields],
                TypeDecl::Enum(e) => e.variants.iter().map(|v| &v.fields).collect(),
            };
            for fields in groups {
                for f in fields {
                    if f.ty == UNIT || is_array_name(&f.ty) || f.ty == STR {
                        return Err(terr(
                            f.line,
                            f.col,
                            "field_type",
                            format!("field {} cannot have type {}", f.name, type_name(&f.ty)),
                            "fields are i64, bool, Option<i64>, Result<i64> or a user struct/enum",
                        ));
                    }
                    self.check_type_ref(f.line, f.col, &f.ty)?;
                }
            }
        }
        for f in &prog.functions {
            for p in &f.params {
                self.check_type_ref(f.line, f.col, &p.ty)?;
            }
            self.check_type_ref(f.line, f.col, &f.ret)?;
        }
        Ok(())
    }

    fn type_recursion(&self, types: &[TypeDecl]) -> Res<()> {
        fn deps(d: &TypeDecl) -> Vec<String> {
            let mut out: Vec<String> = Vec::new();
            for f in d.all_fields() {
                if is_user_type(&f.ty) && !out.contains(&f.ty) {
                    out.push(f.ty.clone());
                }
            }
            out
        }
        fn visit(decls: &HashMap<String, TypeDecl>, state: &mut HashMap<String, u8>, n: &str, path: &mut Vec<String>) -> Res<()> {
            let d = match decls.get(n) {
                Some(d) => d,
                None => return Ok(()), // already guaranteed by resolve_types
            };
            match state.get(n).copied() {
                Some(1) => {
                    let at = path.iter().position(|p| p == n).unwrap_or(0);
                    let mut cyc: Vec<String> = path[at..].to_vec();
                    cyc.push(n.to_string());
                    return Err(terr(
                        d.line(),
                        d.col(),
                        "recursive_type",
                        format!("recursive type is not allowed: {}", cyc.join(" -> ")),
                        "types have fixed size; remove the cycle",
                    ));
                }
                Some(2) => return Ok(()),
                _ => {}
            }
            state.insert(n.to_string(), 1);
            path.push(n.to_string());
            for c in deps(d) {
                visit(decls, state, &c, path)?;
            }
            path.pop();
            state.insert(n.to_string(), 2);
            Ok(())
        }
        let mut state: HashMap<String, u8> = HashMap::new();
        for d in types {
            let mut path: Vec<String> = Vec::new();
            visit(&self.decls, &mut state, d.name(), &mut path)?;
        }
        Ok(())
    }

    fn no_recursion(&self) -> Res<()> {
        fn visit(s: &Checker, state: &mut HashMap<String, u8>, n: &str, path: &mut Vec<String>) -> Res<()> {
            match state.get(n).copied() {
                Some(1) => {
                    let (line, col) = s.funcs.get(n).map(|f| (f.line, f.col)).unwrap_or((0, 0));
                    let mut p = path.clone();
                    p.push(n.to_string());
                    return Err(terr(
                        line,
                        col,
                        "recursion",
                        format!("recursion is not allowed: {}", p.join(" -> ")),
                        "rewrite with a while loop",
                    ));
                }
                Some(2) => return Ok(()),
                _ => {}
            }
            state.insert(n.to_string(), 1);
            path.push(n.to_string());
            let callees: Vec<String> = s.calls.get(n).map(|c| c.iter().cloned().collect()).unwrap_or_default();
            for c in callees {
                visit(s, state, &c, path)?;
            }
            path.pop();
            state.insert(n.to_string(), 2);
            Ok(())
        }
        let mut state: HashMap<String, u8> = HashMap::new();
        for n in &self.func_order {
            let mut path: Vec<String> = Vec::new();
            visit(self, &mut state, n, &mut path)?;
        }
        Ok(())
    }

    // ---- functions ----
    fn fn_(&mut self, f: &mut Function) -> Res<()> {
        self.cur_name = f.name.clone();
        self.cur_ret = f.ret.clone();
        self.calls.insert(f.name.clone(), BTreeSet::new());
        let mut scope: Scope = HashMap::new();
        for p in &f.params {
            if scope.contains_key(&p.name) {
                return Err(terr(f.line, f.col, "dup_param", format!("duplicate parameter {}", p.name), ""));
            }
            if p.ty == UNIT {
                return Err(terr(f.line, f.col, "unit_param", format!("parameter {} cannot have type ()", p.name), ""));
            }
            scope.insert(p.name.clone(), Entry { ty: p.ty.clone(), mutable: false, kind: "param" });
        }
        self.used_effects = BTreeSet::new();
        for r in f.requires.iter_mut() {
            self.expect(r, BOOL, &scope, true)?;
        }
        let mut escope = scope.clone();
        if f.ret != UNIT {
            escope.insert("result".to_string(), Entry { ty: f.ret.clone(), mutable: false, kind: "result" });
        }
        for e in f.ensures.iter_mut() {
            self.expect(e, BOOL, &escope, true)?;
        }
        let mut body_scope = scope.clone();
        self.block(&mut f.body, &mut body_scope)?;
        if f.ret != UNIT && !ends_in_return(&f.body) {
            return Err(terr(
                f.line,
                f.col,
                "missing_return",
                format!("function {} may reach its end without returning", f.name),
                "end every path with `return ...;`",
            ));
        }
        for e in &self.used_effects {
            if !f.effects.contains(e) {
                let mut all: BTreeSet<String> = f.effects.iter().cloned().collect();
                all.extend(self.used_effects.iter().cloned());
                let joined = all.into_iter().collect::<Vec<_>>().join(", ");
                return Err(PruvError::new(
                    "effect",
                    f.line,
                    f.col,
                    "missing_effect",
                    format!("function {} uses effect `{}` but does not declare it", f.name, e),
                    format!("add `! {}` after the return type", joined),
                ));
            }
        }
        Ok(())
    }

    // ---- statements ----
    fn block(&mut self, stmts: &mut [Stmt], scope: &mut Scope) -> Res<()> {
        for st in stmts.iter_mut() {
            self.stmt(st, scope)?;
        }
        Ok(())
    }

    fn lookup(&self, line: i64, col: i64, name: &str, scope: &Scope) -> Res<Entry> {
        match scope.get(name) {
            Some(v) => Ok(v.clone()),
            None => Err(terr(line, col, "unknown_name", format!("unknown variable {}", name), "")),
        }
    }

    fn immutable_fix(kind: &str) -> &'static str {
        if kind == "local" {
            "declare it with `let mut`"
        } else {
            "parameters are immutable; copy into a `let mut` local"
        }
    }

    fn stmt(&mut self, st: &mut Stmt, scope: &mut Scope) -> Res<()> {
        match st {
            Stmt::Let(s) => {
                if scope.contains_key(&s.name) {
                    return Err(terr(
                        s.line,
                        s.col,
                        "shadow",
                        format!("{} is already defined; shadowing is not allowed", s.name),
                        "use a new name",
                    ));
                }
                if s.ty == UNIT {
                    return Err(terr(s.line, s.col, "unit_let", "cannot bind a () value", ""));
                }
                self.check_type_ref(s.line, s.col, &s.ty)?;
                self.want_alloc(&s.value, &s.ty);
                self.expect(&mut s.value, &s.ty, scope, false)?;
                if is_array_name(&s.ty) || s.ty == STR {
                    self.array_source(s.line, s.col, &s.value, scope, false, &s.ty)?;
                }
                scope.insert(s.name.clone(), Entry { ty: s.ty.clone(), mutable: s.mutable, kind: "local" });
            }
            Stmt::Assign(s) => {
                let v = self.lookup(s.line, s.col, &s.name, scope)?;
                if !v.mutable {
                    return Err(terr(s.line, s.col, "immutable", format!("{} is not mutable", s.name), Self::immutable_fix(v.kind)));
                }
                self.want_alloc(&s.value, &v.ty);
                self.expect(&mut s.value, &v.ty, scope, false)?;
                if is_array_name(&v.ty) || v.ty == STR {
                    self.array_source(s.line, s.col, &s.value, scope, false, &v.ty)?;
                }
            }
            Stmt::IndexAssign(s) => {
                let v = self.lookup(s.line, s.col, &s.name, scope)?;
                if v.ty == STR {
                    return Err(terr(
                        s.line,
                        s.col,
                        "immutable_string",
                        format!("{} is a str; its bytes cannot be changed", s.name),
                        "build a new str with substr() or copy() instead",
                    ));
                }
                if !is_array_name(&v.ty) {
                    return Err(terr(s.line, s.col, "not_array", format!("{} is not an array", s.name), ""));
                }
                if !v.mutable {
                    return Err(terr(
                        s.line,
                        s.col,
                        "immutable",
                        format!("array {} is read-only", s.name),
                        format!("use `let mut b: {} = copy({});` (needs alloc)", type_name(&v.ty), s.name),
                    ));
                }
                // G2 A5: if the element is bool, the expected value type is bool
                let want_val: &str = if v.ty == "array_bool" { BOOL } else { I64 };
                self.expect(&mut s.index, I64, scope, false)?;
                self.expect(&mut s.value, want_val, scope, false)?;
            }
            Stmt::FieldAssign(s) => {
                let v = self.lookup(s.line, s.col, &s.name, scope)?;
                let mut cur = v.ty.clone();
                for fname in &s.fields {
                    if !self.tt.is_struct(&cur) {
                        return Err(terr(
                            s.line,
                            s.col,
                            "not_struct",
                            format!("cannot assign field {}: {} is not a struct", fname, type_name(&cur)),
                            "field assignment paths run through structs only; assign the whole enum value instead",
                        ));
                    }
                    cur = self.field_decl(s.line, s.col, &cur, fname)?;
                }
                if !v.mutable {
                    return Err(terr(s.line, s.col, "immutable", format!("{} is not mutable", s.name), Self::immutable_fix(v.kind)));
                }
                self.expect(&mut s.value, &cur, scope, false)?;
            }
            Stmt::If(s) => {
                self.expect(&mut s.cond, BOOL, scope, false)?;
                let mut sc = scope.clone();
                self.block(&mut s.then, &mut sc)?;
                let mut sc = scope.clone();
                self.block(&mut s.els, &mut sc)?;
            }
            Stmt::While(s) => {
                self.expect(&mut s.cond, BOOL, scope, false)?;
                for i in s.invariants.iter_mut() {
                    self.expect(i, BOOL, scope, true)?;
                }
                self.expect(&mut s.decreases, I64, scope, true)?;
                let mut sc = scope.clone();
                self.block(&mut s.body, &mut sc)?;
            }
            Stmt::Return(s) => {
                let ret = self.cur_ret.clone();
                match &mut s.value {
                    None => {
                        if ret != UNIT {
                            return Err(terr(
                                s.line,
                                s.col,
                                "return_type",
                                format!("function returns {}; `return;` is not enough", type_name(&ret)),
                                "",
                            ));
                        }
                    }
                    Some(v) => {
                        if ret == UNIT {
                            return Err(terr(s.line, s.col, "return_type", "function returns (); use `return;`", ""));
                        }
                        self.want_alloc(v, &ret);
                        self.expect(v, &ret, scope, false)?;
                        if is_array_name(&ret) || ret == STR {
                            self.array_source(s.line, s.col, v, scope, true, &ret)?;
                        }
                    }
                }
            }
            Stmt::Assert(s) => {
                self.expect(&mut s.cond, BOOL, scope, true)?;
            }
            Stmt::ExprStmt(s) => {
                if !matches!(s.expr, Expr::Call(_)) {
                    return Err(terr(
                        s.line,
                        s.col,
                        "useless_expr",
                        "expression statement must be a call",
                        "bind it with let or remove it",
                    ));
                }
                let t = self.expr(&mut s.expr, scope, false)?;
                if t != UNIT {
                    return Err(terr(
                        s.line,
                        s.col,
                        "unused_value",
                        format!("value of type {} is dropped", type_name(&t)),
                        "bind it with `let` or `match` it",
                    ));
                }
            }
            Stmt::Match(m) => self.match_stmt(m, scope)?,
        }
        Ok(())
    }

    fn match_stmt(&mut self, m: &mut Match, scope: &mut Scope) -> Res<()> {
        let (line, col) = (m.line, m.col);
        let t = self.expr(&mut m.scrutinee, scope, false)?;
        let user = self.tt.is_enum(&t);
        let need: Vec<String> = if t == OPTION {
            vec!["Some".to_string(), "None".to_string()]
        } else if t == RESULT {
            vec!["Ok".to_string(), "Err".to_string()]
        } else if user {
            match self.tt.decl(&t) {
                Some(TypeDecl::Enum(e)) => e.variants.iter().map(|v| v.name.clone()).collect(),
                _ => Vec::new(),
            }
        } else {
            return Err(terr(line, col, "match_type", "can only match Option<i64>, Result<i64> or a user enum", ""));
        };
        if !user {
            let got: Vec<&String> = m.arms.iter().map(|a| &a.ctor).collect();
            let got_set: BTreeSet<&String> = got.iter().cloned().collect();
            let need_set: BTreeSet<&String> = need.iter().collect();
            if got_set != need_set || got.len() != 2 || m.arms.iter().any(|a| a.enum_name.is_some()) {
                let sorted: Vec<&String> = need_set.into_iter().collect();
                let joined = sorted.iter().map(|s| s.as_str()).collect::<Vec<_>>().join(" and ");
                return Err(terr(line, col, "match_arms", format!("match needs exactly arms {}", joined), ""));
            }
        } else {
            let mut seen: Vec<&str> = Vec::new();
            for a in &m.arms {
                if a.enum_name.as_deref() != Some(t.as_str()) {
                    let what = match &a.enum_name {
                        Some(en) if !en.is_empty() => format!("{}::{}", en, a.ctor),
                        _ => a.ctor.clone(),
                    };
                    return Err(terr(
                        a.line,
                        a.col,
                        "match_arms",
                        format!("arm {} does not belong to enum {}", what, t),
                        format!("match arms are written {}::Variant", t),
                    ));
                }
                if !need.contains(&a.ctor) {
                    return Err(terr(a.line, a.col, "unknown_variant", format!("enum {} has no variant {}", t, a.ctor), ""));
                }
                if seen.contains(&a.ctor.as_str()) {
                    return Err(terr(a.line, a.col, "match_arms", format!("arm {}::{} appears twice", t, a.ctor), ""));
                }
                seen.push(&a.ctor);
            }
            let missing: Vec<String> = need.iter().filter(|n| !seen.contains(&n.as_str())).map(|n| format!("{}::{}", t, n)).collect();
            if !missing.is_empty() {
                return Err(terr(line, col, "match_arms", format!("match is missing arm(s): {}", missing.join(", ")), ""));
            }
        }
        for a in m.arms.iter_mut() {
            let mut sc = scope.clone();
            let (nl, nc) = if user { (a.line, a.col) } else { (line, col) };
            let ftypes: Vec<String> = if user {
                let v: Vec<String> = self
                    .tt
                    .fields(&t, Some(a.ctor.as_str()))
                    .unwrap_or(&[])
                    .iter()
                    .map(|f| f.ty.clone())
                    .collect();
                if a.binders.len() != v.len() {
                    return Err(terr(
                        a.line,
                        a.col,
                        "match_arity",
                        format!("{}::{} has {} field(s), the pattern binds {}", t, a.ctor, v.len(), a.binders.len()),
                        "bind every field, in declaration order",
                    ));
                }
                v
            } else {
                vec![I64.to_string(); a.binders.len()]
            };
            for (b, bt) in a.binders.iter().zip(ftypes.iter()) {
                if sc.contains_key(b) {
                    return Err(terr(nl, nc, "shadow", format!("{} is already defined", b), "use a new name"));
                }
                sc.insert(b.clone(), Entry { ty: bt.clone(), mutable: false, kind: "local" });
            }
            self.block(&mut a.body, &mut sc)?;
        }
        Ok(())
    }

    /// Arrays are moved or borrowed explicitly: a new array comes only from alloc/copy/a call.
    fn array_source(&self, line: i64, col: i64, value: &Expr, scope: &Scope, allow_local_var: bool, ty: &str) -> Res<()> {
        if matches!(value, Expr::Call(_) | Expr::StrLit(_)) {
            return Ok(());
        }
        if allow_local_var {
            if let Expr::Var(v) = value {
                if scope.get(&v.name).map(|x| x.kind == "local").unwrap_or(false) {
                    return Ok(());
                }
            }
        }
        Err(terr(
            line,
            col,
            "array_alias",
            if ty == STR {
                "a str value here must come from a string literal, copy(), substr() or a function call"
            } else {
                "an array value here must come from alloc(), copy() or a function call"
            },
            "write copy(x) to make an explicit copy (needs `! alloc`)",
        ))
    }

    // ---- expressions ----
    fn expect(&mut self, e: &mut Expr, ty: &str, scope: &Scope, contract: bool) -> Res<String> {
        let t = self.expr(e, scope, contract)?;
        if t != ty {
            return Err(terr(
                e.line(),
                e.col(),
                "type_mismatch",
                format!("expected {}, found {}", type_name(ty), type_name(&t)),
                "",
            ));
        }
        Ok(t)
    }

    fn expr(&mut self, e: &mut Expr, scope: &Scope, contract: bool) -> Res<String> {
        let t = self.expr_inner(e, scope, contract)?;
        set_ty(e, &t);
        Ok(t)
    }

    fn expr_inner(&mut self, e: &mut Expr, scope: &Scope, c: bool) -> Res<String> {
        match e {
            Expr::IntLit(x) => {
                if !int_in_range(&x.value) {
                    return Err(terr(x.line, x.col, "int_range", "integer literal out of i64 range", ""));
                }
                Ok(I64.to_string())
            }
            Expr::BoolLit(_) => Ok(BOOL.to_string()),
            Expr::StrLit(_) => {
                if !c {
                    self.used_effects.insert("alloc".to_string());
                }
                Ok(STR.to_string())
            }
            Expr::Var(x) => {
                if x.name == "result" && !scope.contains_key("result") {
                    return Err(terr(x.line, x.col, "result_scope", "`result` is only allowed in ensures", ""));
                }
                Ok(self.lookup(x.line, x.col, &x.name, scope)?.ty)
            }
            Expr::Unary(x) => {
                if x.op == "-" {
                    self.expect(&mut x.operand, I64, scope, c)?;
                    Ok(I64.to_string())
                } else {
                    self.expect(&mut x.operand, BOOL, scope, c)?;
                    Ok(BOOL.to_string())
                }
            }
            Expr::Binary(x) => {
                let op = x.op.clone();
                match op.as_str() {
                    "+" | "-" | "*" | "/" | "%" => {
                        self.expect(&mut x.left, I64, scope, c)?;
                        self.expect(&mut x.right, I64, scope, c)?;
                        Ok(I64.to_string())
                    }
                    "<" | "<=" | ">" | ">=" => {
                        self.expect(&mut x.left, I64, scope, c)?;
                        self.expect(&mut x.right, I64, scope, c)?;
                        Ok(BOOL.to_string())
                    }
                    "==" | "!=" => {
                        let lt = self.expr(&mut x.left, scope, c)?;
                        if is_array_name(&lt) {
                            return Err(terr(
                                x.line,
                                x.col,
                                "eq_type",
                                "arrays cannot be compared with ==",
                                "compare lengths and elements: len(a) == len(b) && forall k in 0..len(a): a[k] == b[k]",
                            ));
                        }
                        if lt == STR {
                            return Err(terr(
                                x.line,
                                x.col,
                                "eq_type",
                                "str values cannot be compared with ==",
                                "compare lengths and bytes: len(a) == len(b) && forall k in 0..len(a): a[k] == b[k]",
                            ));
                        }
                        if lt != I64 && lt != BOOL && !c {
                            return Err(terr(x.line, x.col, "eq_type", "== only compares i64 or bool in code", "use match"));
                        }
                        self.expect(&mut x.right, &lt, scope, c)?;
                        Ok(BOOL.to_string())
                    }
                    "&&" | "||" => {
                        self.expect(&mut x.left, BOOL, scope, c)?;
                        self.expect(&mut x.right, BOOL, scope, c)?;
                        Ok(BOOL.to_string())
                    }
                    "==>" => {
                        if !c {
                            return Err(terr(x.line, x.col, "contract_only", "==> is only allowed in contracts", ""));
                        }
                        self.expect(&mut x.left, BOOL, scope, c)?;
                        self.expect(&mut x.right, BOOL, scope, c)?;
                        Ok(BOOL.to_string())
                    }
                    _ => Err(terr(x.line, x.col, "internal", "unknown expression", "")),
                }
            }
            Expr::Index(x) => {
                let at = self.expr(&mut x.array, scope, c)?;
                if !is_array_name(&at) && at != STR {
                    return Err(terr(
                        x.array.line(),
                        x.array.col(),
                        "type_mismatch",
                        format!("expected {}, found {}", type_name(ARRAY), type_name(&at)),
                        "",
                    ));
                }
                self.expect(&mut x.index, I64, scope, c)?;
                // G2 A5: reading a bool array gives bool
                if at == "array_bool" {
                    return Ok(BOOL.to_string());
                }
                Ok(I64.to_string())
            }
            Expr::Ctor(x) => {
                if x.name == "None" {
                    return Ok(OPTION.to_string());
                }
                if let Some(a) = x.arg.as_mut() {
                    self.expect(a, I64, scope, c)?;
                }
                Ok(if x.name == "Some" { OPTION } else { RESULT }.to_string())
            }
            Expr::Quant(x) => {
                let agg = matches!(x.kind.as_str(), "sum" | "count" | "max" | "min");
                if !c {
                    if agg {
                        return Err(terr(
                            x.line,
                            x.col,
                            "contract_only",
                            format!("{} is only allowed in contracts", x.kind),
                            "compute it with a while loop and state it in ensures, e.g. ensures result == sum(k in 0..len(a): a[k])",
                        ));
                    }
                    return Err(terr(x.line, x.col, "contract_only", format!("{} is only allowed in contracts", x.kind), ""));
                }
                self.expect(&mut x.lo, I64, scope, c)?;
                self.expect(&mut x.hi, I64, scope, c)?;
                if scope.contains_key(&x.var) {
                    return Err(terr(x.line, x.col, "shadow", format!("{} is already defined", x.var), "use a new name"));
                }
                let mut sc = scope.clone();
                sc.insert(x.var.clone(), Entry { ty: I64.to_string(), mutable: false, kind: "bound" });
                let body_ty = if matches!(x.kind.as_str(), "forall" | "exists" | "count") { BOOL } else { I64 };
                self.expect(&mut x.body, body_ty, &sc, c)?;
                Ok(if agg { I64 } else { BOOL }.to_string())
            }
            Expr::StructLit(x) => self.struct_lit(x, scope, c),
            Expr::EnumCtor(x) => {
                let ety = self.enum_type(x.line, x.col, &x.enum_name)?;
                let fields = self.variant_fields(x.line, x.col, &ety, &x.variant)?;
                if x.args.len() != fields.len() {
                    return Err(terr(
                        x.line,
                        x.col,
                        "arity",
                        format!("{}::{} takes {} argument(s), got {}", x.enum_name, x.variant, fields.len(), x.args.len()),
                        "",
                    ));
                }
                for (arg, fd) in x.args.iter_mut().zip(fields.iter()) {
                    self.expect(arg, &fd.1, scope, c)?;
                }
                Ok(ety)
            }
            Expr::FieldAccess(x) => {
                let bt = self.expr(&mut x.base, scope, c)?;
                if !self.tt.is_struct(&bt) {
                    return Err(terr(
                        x.line,
                        x.col,
                        "not_struct",
                        format!("cannot read field {}: {} is not a struct", x.field, type_name(&bt)),
                        if self.tt.is_enum(&bt) { "enum payloads are read with match" } else { "" },
                    ));
                }
                self.field_decl(x.line, x.col, &bt, &x.field)
            }
            Expr::IsVariant(x) => {
                if !c {
                    return Err(terr(x.line, x.col, "contract_only", "is_variant is only allowed in contracts", "use match in code"));
                }
                self.variant_target(x.line, x.col, &mut x.value, &x.enum_name, &x.variant, scope, c)?;
                Ok(BOOL.to_string())
            }
            Expr::VariantField(x) => {
                if !c {
                    return Err(terr(x.line, x.col, "contract_only", "variant_field is only allowed in contracts", "use match in code"));
                }
                let ety = self.variant_target(x.line, x.col, &mut x.value, &x.enum_name, &x.variant, scope, c)?;
                let vd = self.variant_fields(x.line, x.col, &ety, &x.variant)?;
                for fd in &vd {
                    if fd.0 == x.field {
                        return Ok(fd.1.clone());
                    }
                }
                Err(terr(
                    x.line,
                    x.col,
                    "unknown_field",
                    format!("variant {}::{} has no field {}", x.enum_name, x.variant, x.field),
                    "",
                ))
            }
            Expr::Call(x) => self.call(x, scope, c),
        }
    }

    // ---- user type helpers ----
    /// The type of a struct field (the type only, not the (name, type) pair).
    fn field_decl(&self, line: i64, col: i64, sty: &str, name: &str) -> Res<String> {
        for fd in self.tt.fields(sty, None).unwrap_or(&[]) {
            if fd.name == name {
                return Ok(fd.ty.clone());
            }
        }
        Err(terr(line, col, "unknown_field", format!("struct {} has no field {}", sty, name), ""))
    }

    /// The type of a named enum; unknown_type if missing, not_enum if it is not an enum.
    fn enum_type(&self, line: i64, col: i64, name: &str) -> Res<String> {
        if !self.decls.contains_key(name) {
            return Err(terr(line, col, "unknown_type", format!("unknown type {}", name), ""));
        }
        if !self.tt.is_enum(name) {
            return Err(terr(line, col, "not_enum", format!("{} is not an enum", name), ""));
        }
        Ok(name.to_string())
    }

    /// List of (name, type) fields of a variant.
    fn variant_fields(&self, line: i64, col: i64, ety: &str, variant: &str) -> Res<Vec<(String, String)>> {
        match self.tt.variant(ety, variant) {
            Some(v) => Ok(v.fields.iter().map(|f| (f.name.clone(), f.ty.clone())).collect()),
            None => Err(terr(line, col, "unknown_variant", format!("enum {} has no variant {}", ety, variant), "")),
        }
    }

    /// Shared by is_variant / variant_field: checks the value, enum and variant.
    #[allow(clippy::too_many_arguments)]
    fn variant_target(
        &mut self,
        line: i64,
        col: i64,
        value: &mut Expr,
        enum_name: &str,
        variant: &str,
        scope: &Scope,
        c: bool,
    ) -> Res<String> {
        let vt = self.expr(value, scope, c)?;
        let ety = self.enum_type(line, col, enum_name)?;
        self.variant_fields(line, col, &ety, variant)?;
        if vt != ety {
            return Err(terr(
                value.line(),
                value.col(),
                "type_mismatch",
                format!("expected {}, found {}", type_name(&ety), type_name(&vt)),
                "",
            ));
        }
        Ok(ety)
    }

    fn struct_lit(&mut self, e: &mut StructLit, scope: &Scope, c: bool) -> Res<String> {
        if !self.decls.contains_key(&e.name) {
            return Err(terr(e.line, e.col, "unknown_type", format!("unknown type {}", e.name), ""));
        }
        if !self.tt.is_struct(&e.name) {
            return Err(terr(
                e.line,
                e.col,
                "not_struct",
                format!("{} is not a struct", e.name),
                format!("enum values are written {}::Variant", e.name),
            ));
        }
        let fields: Vec<(String, String)> = self
            .tt
            .fields(&e.name, None)
            .unwrap_or(&[])
            .iter()
            .map(|f| (f.name.clone(), f.ty.clone()))
            .collect();
        let declared: Vec<&str> = fields.iter().map(|f| f.0.as_str()).collect();
        for fi in &e.fields {
            if !declared.contains(&fi.name.as_str()) {
                return Err(terr(fi.line, fi.col, "unknown_field", format!("struct {} has no field {}", e.name, fi.name), ""));
            }
        }
        let given: Vec<&str> = e.fields.iter().map(|f| f.name.as_str()).collect();
        if given != declared {
            let uniq: BTreeSet<&str> = given.iter().cloned().collect();
            let why = if uniq.len() != given.len() {
                let dup = given.iter().find(|n| given.iter().filter(|m| m == n).count() > 1).cloned().unwrap_or("");
                format!("field {} is given twice", dup)
            } else if uniq != declared.iter().cloned().collect::<BTreeSet<&str>>() {
                let miss: Vec<&str> = declared.iter().filter(|n| !given.contains(*n)).cloned().collect();
                format!("missing field(s): {}", miss.join(", "))
            } else {
                format!("fields must be written in declaration order: {}", declared.join(", "))
            };
            return Err(terr(
                e.line,
                e.col,
                "struct_fields",
                format!("{} literal: {}", e.name, why),
                "write every field exactly once, in declaration order",
            ));
        }
        for (fi, fd) in e.fields.iter_mut().zip(fields.iter()) {
            self.expect(&mut fi.value, &fd.1, scope, c)?;
        }
        Ok(e.name.clone())
    }

    fn call(&mut self, e: &mut Call, scope: &Scope, c: bool) -> Res<String> {
        let n = e.name.clone();
        let (line, col) = (e.line, e.col);
        let alen = e.args.len();
        let arity = |k: usize| -> Res<()> {
            if alen != k {
                return Err(terr(line, col, "arity", format!("{} takes {} argument(s), got {}", n, k, alen), ""));
            }
            Ok(())
        };
        match n.as_str() {
            "len" => {
                arity(1)?;
                let at = self.expr(&mut e.args[0], scope, c)?;
                if !is_array_name(&at) && at != STR {
                    return Err(terr(
                        e.args[0].line(),
                        e.args[0].col(),
                        "type_mismatch",
                        format!("expected {}, found {}", type_name(ARRAY), type_name(&at)),
                        "",
                    ));
                }
                return Ok(I64.to_string());
            }
            "alloc" => {
                let want = self.alloc_want.take();
                if c {
                    return Err(terr(line, col, "effect_in_contract", "alloc not allowed in contracts", ""));
                }
                arity(2)?;
                self.expect(&mut e.args[0], I64, scope, c)?;
                // G2 A5: if the hint is array_bool, the expected value type is bool
                let vwant: &str = if want.as_deref() == Some("array_bool") { BOOL } else { I64 };
                self.expect(&mut e.args[1], vwant, scope, c)?;
                self.used_effects.insert("alloc".to_string());
                return Ok(want.unwrap_or_else(|| ARRAY.to_string()));
            }
            "copy" => {
                if c {
                    return Err(terr(line, col, "effect_in_contract", "copy not allowed in contracts", ""));
                }
                arity(1)?;
                let at = self.expr(&mut e.args[0], scope, c)?;
                if !is_array_name(&at) && at != STR {
                    return Err(terr(
                        e.args[0].line(),
                        e.args[0].col(),
                        "type_mismatch",
                        format!("expected {}, found {}", type_name(ARRAY), type_name(&at)),
                        "",
                    ));
                }
                self.used_effects.insert("alloc".to_string());
                return Ok(at);
            }
            "is_char_boundary" => {
                arity(2)?;
                self.expect(&mut e.args[0], STR, scope, c)?;
                self.expect(&mut e.args[1], I64, scope, c)?;
                return Ok(BOOL.to_string());
            }
            "substr" => {
                if c {
                    return Err(terr(line, col, "effect_in_contract", "substr not allowed in contracts", ""));
                }
                arity(3)?;
                self.expect(&mut e.args[0], STR, scope, c)?;
                self.expect(&mut e.args[1], I64, scope, c)?;
                self.expect(&mut e.args[2], I64, scope, c)?;
                self.used_effects.insert("alloc".to_string());
                return Ok(STR.to_string());
            }
            "print" => {
                if c {
                    return Err(terr(line, col, "effect_in_contract", "print not allowed in contracts", ""));
                }
                arity(1)?;
                let t = self.expr(&mut e.args[0], scope, c)?;
                if t != I64 && t != BOOL {
                    return Err(terr(line, col, "print_type", "print takes i64 or bool", ""));
                }
                self.used_effects.insert("io".to_string());
                return Ok(UNIT.to_string());
            }
            _ => {}
        }
        if let Some((at, rt)) = contract_only(&n) {
            if !c {
                return Err(terr(line, col, "contract_only", format!("{} is only allowed in contracts", n), "use match in code"));
            }
            arity(1)?;
            self.expect(&mut e.args[0], at, scope, c)?;
            return Ok(rt.to_string());
        }
        let f = match self.funcs.get(&n) {
            Some(f) => Rc::clone(f),
            None => {
                let fix = if matches!(n.as_str(), "sum" | "count" | "max" | "min") {
                    "aggregates use the form sum(k in 0..len(a): a[k])"
                } else {
                    ""
                };
                return Err(terr(line, col, "unknown_fn", format!("unknown function {}", n), fix));
            }
        };
        arity(f.params.len())?;
        for (arg, p) in e.args.iter_mut().zip(f.params.iter()) {
            self.expect(arg, p, scope, c)?;
        }
        if c && !f.effects.is_empty() {
            return Err(terr(
                line,
                col,
                "effect_in_contract",
                format!("function {} has effects; not allowed in contracts", n),
                "",
            ));
        }
        if c {
            return Err(terr(
                line,
                col,
                "call_in_contract",
                "calling functions in contracts is not supported in v0.1",
                "inline the property",
            ));
        }
        self.used_effects.extend(f.effects.iter().cloned());
        self.calls.entry(self.cur_name.clone()).or_default().insert(n.clone());
        Ok(f.ret.clone())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn run(src: &str) -> Result<TypeTable, PruvError> {
        let mut p = crate::parse(src).expect("parse");
        check(&mut p)
    }

    #[test]
    fn int_range_edges() {
        assert!(int_in_range("9223372036854775807"));
        assert!(!int_in_range("9223372036854775808"));
        assert!(int_in_range("-9223372036854775808"));
        assert!(!int_in_range("-9223372036854775809"));
        assert!(int_in_range("0"));
        assert!(!int_in_range("100000000000000000000000000000000000000000"));
    }

    #[test]
    fn recursive_type_message() {
        let e = run("struct A { b: B }\nstruct B { a: A }\n").unwrap_err();
        assert_eq!(e.code, "recursive_type");
        assert_eq!(e.message, "recursive type is not allowed: A -> B -> A");
        assert_eq!(e.fix, "types have fixed size; remove the cycle");
    }

    #[test]
    fn missing_effect_fix() {
        let e = run("fn f(x: i64) -> () { print(x); return; }").unwrap_err();
        assert_eq!(e.stage, "effect");
        assert_eq!(e.code, "missing_effect");
        assert_eq!(e.message, "function f uses effect `io` but does not declare it");
        assert_eq!(e.fix, "add `! io` after the return type");
    }

    #[test]
    fn type_name_fix_capitalizes() {
        let e = run("struct point { x: i64 }").unwrap_err();
        assert_eq!(e.code, "type_name");
        assert_eq!(e.fix, "rename it, e.g. Point");
    }

    #[test]
    fn int_literal_out_of_range() {
        let e = run("fn f() -> i64 { return 9223372036854775808; }").unwrap_err();
        assert_eq!(e.code, "int_range");
    }
}
