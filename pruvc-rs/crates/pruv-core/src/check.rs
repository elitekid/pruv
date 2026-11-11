//! Type, effect and structure checker (counterpart of check.py). Fills in `ty` for every expression.
//! Function structure, check order, code, stage, message and fix match Python character for character.
//!
//! G3 A1: types are `GType` inside the checker; the AST carries them as key strings (gtype.rs `to_key`/`from_key`),
//! which are the plain legacy names for every non-generic program. Type parameters and type arguments are read from the
//! name suffixes described in ast.rs.

use crate::ast::*;
use crate::diagnostic::PruvError;
use crate::gtype::{
    bind_args, check_arity, decl_owner, dependencies, fn_owner, format_type, is_element, is_value, mk_nominal, mk_option,
    mk_result, substitute, GType, Mapping, ParamId,
};
use crate::typeinfo::{TypeTable, BUILTIN_TYPE_NAMES};
use std::collections::{BTreeSet, HashMap, HashSet};
use std::rc::Rc;

type Res<T> = Result<T, PruvError>;

fn i64t() -> GType {
    GType::i64()
}
fn boolt() -> GType {
    GType::bool()
}
fn unitt() -> GType {
    GType::unit()
}
fn strt() -> GType {
    GType::str()
}

/// What a contract-only built-in returns.
enum CRes {
    Bool,
    I64,
    /// The Option/Result payload type.
    Payload,
}

/// Built-ins used only in contracts: name -> (argument kind, result).
fn contract_only(n: &str) -> Option<(&'static str, CRes)> {
    match n {
        "is_some" => Some(("option", CRes::Bool)),
        "some_val" => Some(("option", CRes::Payload)),
        "is_ok" => Some(("result", CRes::Bool)),
        "ok_val" => Some(("result", CRes::Payload)),
        "err_val" => Some(("result", CRes::I64)),
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

/// The type name as source spelling (Python `type_name`).
fn tn(t: &GType) -> String {
    format_type(t)
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
    ty: GType,
    mutable: bool,
    kind: &'static str, // "param" | "result" | "local" | "bound"
}
type Scope = HashMap<String, Entry>;

struct FuncInfo {
    line: i64,
    col: i64,
    params: Vec<GType>,
    ret: GType,
    effects: Vec<String>,
    tparams: Vec<TParam>,
}

struct Checker {
    funcs: HashMap<String, Rc<FuncInfo>>,
    func_order: Vec<String>,
    calls: HashMap<String, BTreeSet<String>>,
    decls: HashMap<String, TypeDecl>, // first declaration
    tt: TypeTable,
    cur_name: String,
    cur_ret: GType,
    used_effects: BTreeSet<String>,
    /// Expected array type, turned on only when the right-hand expression of a let/reassignment/return is itself an alloc call (alloc takes it right away).
    alloc_want: Option<GType>,
    // G3: type-parameter context of the declaration being checked
    ctx_names: HashSet<String>,
    ctx_generic: bool,
    elem_params: Vec<ParamId>,
    /// type name -> number of type parameters (for gtype::check_arity / is_value)
    arg_decls: HashMap<String, usize>,
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

fn set_ty(e: &mut Expr, t: &GType) {
    let v = Some(t.to_key());
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

/// Type arguments written on a node (None = no type application).
fn targs_of(name: &str) -> Option<Vec<GType>> {
    name_targs(name).map(|v| v.iter().map(|k| GType::from_key(k)).collect())
}

/// Type of an element read from / stored into the array type `at`: T for [T]; bool for [bool]; else i64.
fn elem_type(at: &GType) -> GType {
    if at.name == "array" && !at.args.is_empty() {
        return at.args[0].clone();
    }
    if *at == GType::array_bool() {
        boolt()
    } else {
        i64t()
    }
}

impl Checker {
    fn new(prog: &Program) -> Res<Checker> {
        let mut funcs: HashMap<String, Rc<FuncInfo>> = HashMap::new();
        let mut func_order = Vec::new();
        for f in &prog.functions {
            let name = g3_base(&f.name).to_string();
            if funcs.contains_key(&name) {
                return Err(terr(f.line, f.col, "dup_fn", format!("function {} defined twice", name), ""));
            }
            if matches!(name.as_str(), "len" | "alloc" | "copy" | "print" | "is_char_boundary" | "substr") || contract_only(&name).is_some() {
                return Err(terr(f.line, f.col, "reserved", format!("{} is a builtin name", name), "rename the function"));
            }
            funcs.insert(
                name.clone(),
                Rc::new(FuncInfo {
                    line: f.line,
                    col: f.col,
                    params: f.params.iter().map(|p| GType::from_key(&p.ty)).collect(),
                    ret: GType::from_key(&f.ret),
                    effects: f.effects.clone(),
                    tparams: name_tparams(&f.name),
                }),
            );
            func_order.push(name);
        }
        Ok(Checker {
            funcs,
            func_order,
            calls: HashMap::new(),
            decls: HashMap::new(),
            tt: TypeTable::default(),
            cur_name: String::new(),
            cur_ret: unitt(),
            used_effects: BTreeSet::new(),
            alloc_want: None,
            ctx_names: HashSet::new(),
            ctx_generic: false,
            elem_params: Vec::new(),
            arg_decls: HashMap::new(),
        })
    }

    /// If the value is itself an alloc call and the expected type is an array, sets alloc's result type to that array type.
    fn want_alloc(&mut self, value: &Expr, ty: &GType) {
        if let Expr::Call(c) = value {
            if g3_base(&c.name) == "alloc" && ty.is_array() {
                self.alloc_want = Some(ty.clone());
            }
        }
    }

    fn run(&mut self, prog: &mut Program) -> Res<()> {
        crate::refine::expand(prog)?; // STAGE1 A: validate refinement annotations, then expand them into contracts/asserts
        self.declare_types(&prog.types)?;
        self.arg_decls = self.decls.iter().map(|(n, d)| (n.clone(), d.tparams().len())).collect();
        self.check_tparams(prog)?; // G3: type-parameter lists (type_parameter, generic_bound, generic_main)
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

    // ---- G3: type parameters and type applications ----
    /// Makes the type-parameter list of the declaration being checked the current context.
    fn enter(&mut self, owner: &str, tparams: &[TParam]) {
        self.ctx_names = tparams.iter().map(|t| t.name.clone()).collect();
        self.ctx_generic = !tparams.is_empty();
        self.elem_params = tparams
            .iter()
            .enumerate()
            .filter(|(_, t)| t.bound.as_deref() == Some("Element"))
            .map(|(i, _)| (owner.to_string(), i))
            .collect();
    }

    fn check_tparams(&self, prog: &Program) -> Res<()> {
        for d in &prog.types {
            self.tparam_list(&d.tparams())?;
        }
        for f in &prog.functions {
            let tps = name_tparams(&f.name);
            if g3_base(&f.name) == "main" && !tps.is_empty() {
                return Err(terr(
                    f.line,
                    f.col,
                    "generic_main",
                    "main cannot declare type parameters",
                    "make main a plain function; call generic functions from it with explicit type arguments",
                ));
            }
            self.tparam_list(&tps)?;
        }
        Ok(())
    }

    fn tparam_list(&self, tparams: &[TParam]) -> Res<()> {
        let mut seen: HashSet<&str> = HashSet::new();
        for tp in tparams {
            if !type_name_ok(&tp.name) {
                return Err(terr(
                    tp.line,
                    tp.col,
                    "type_parameter",
                    format!("type parameter {} must start with an upper-case letter", tp.name),
                    format!("rename it, e.g. {}", cap_first(&tp.name, true)),
                ));
            }
            if RESERVED_TYPE_NAMES.contains(&tp.name.as_str()) || self.decls.contains_key(&tp.name) {
                return Err(terr(
                    tp.line,
                    tp.col,
                    "type_parameter",
                    format!("type parameter {} shadows a declared or built-in type", tp.name),
                    "choose a name that is not a type, e.g. T",
                ));
            }
            if seen.contains(tp.name.as_str()) {
                return Err(terr(
                    tp.line,
                    tp.col,
                    "type_parameter",
                    format!("type parameter {} is declared twice", tp.name),
                    "give every parameter of a declaration its own name",
                ));
            }
            seen.insert(&tp.name);
            if let Some(b) = &tp.bound {
                if b != "Element" {
                    return Err(terr(
                        tp.line,
                        tp.col,
                        "generic_bound",
                        format!("unknown bound {} on type parameter {}", b, tp.name),
                        format!("the only bound is Element: <{}: Element>", tp.name),
                    ));
                }
            }
        }
        Ok(())
    }

    /// Every type reference: arity, known names, type-argument and bound rules (G3_SPEC 3.1, 3.2, 3.4).
    fn check_type(&self, line: i64, col: i64, ty: &GType) -> Res<()> {
        let ad = &self.arg_decls;
        let look = |n: &str| ad.get(n).map(|k| (*k, Vec::<GType>::new()));
        if let Err(ex) = check_arity(ty, &look) {
            return Err(terr(
                line,
                col,
                "type_arity",
                ex.to_string(),
                "give the exact number of type arguments, e.g. Option<i64>, Pair<i64, bool>",
            ));
        }
        self.check_type_rec(line, col, ty)
    }

    fn check_type_rec(&self, line: i64, col: i64, ty: &GType) -> Res<()> {
        if ty.owner.is_some() {
            return Ok(());
        }
        if ty.name == "option" || ty.name == "result" {
            for a in &ty.args {
                self.check_arg(line, col, a, None)?;
            }
            return Ok(());
        }
        if ty.name == "array" {
            if !ty.args.is_empty() {
                // [X] for X other than i64/u8/bool
                let el = &ty.args[0];
                self.check_type_rec(line, col, el)?;
                if let Some(o) = &el.owner {
                    if !self.elem_params.contains(&(o.clone(), el.index)) {
                        return Err(terr(
                            line,
                            col,
                            "generic_bound",
                            format!("[{}] requires {}: Element", el.name, el.name),
                            format!("declare the parameter as <{}: Element>", el.name),
                        ));
                    }
                } else {
                    return Err(terr(
                        line,
                        col,
                        "type_argument",
                        format!("{} cannot be an array element", tn(el)),
                        "arrays hold i64, bool or an Element type parameter",
                    ));
                }
            }
            return Ok(());
        }
        if BUILTIN_TYPE_NAMES.contains(&ty.name.as_str()) {
            return Ok(());
        }
        if self.ctx_names.contains(&ty.name) {
            return Err(terr(
                line,
                col,
                "type_parameter",
                format!("type parameter {} is not a type constructor", ty.name),
                format!("write {} without type arguments", ty.name),
            ));
        }
        let d = match self.decls.get(&ty.name) {
            Some(d) => d,
            None => {
                if self.ctx_generic {
                    return Err(terr(
                        line,
                        col,
                        "type_parameter",
                        format!("unknown type {}: it is neither declared nor a type parameter of this declaration", ty.name),
                        format!("declare it in the type-parameter list, e.g. <{}>, or declare the type", ty.name),
                    ));
                }
                return Err(terr(
                    line,
                    col,
                    "unknown_type",
                    format!("unknown type {}", ty.name),
                    format!("declare it with `struct {} {{ ... }}` or `enum {} {{ ... }}`", ty.name, ty.name),
                ));
            }
        };
        let tps = d.tparams();
        for (a, tp) in ty.args.iter().zip(tps.iter()) {
            self.check_arg(line, col, a, Some(tp))?;
        }
        Ok(())
    }

    /// a: a type argument; tp: the TypeParam it instantiates (None for Option/Result).
    fn check_arg(&self, line: i64, col: i64, a: &GType, tp: Option<&TParam>) -> Res<()> {
        self.check_type_rec(line, col, a)?;
        let ad = &self.arg_decls;
        let look = |n: &str| ad.get(n).map(|k| (*k, Vec::<GType>::new()));
        if !is_value(a, &look) {
            return Err(terr(
                line,
                col,
                "type_argument",
                format!(
                    "{} is not a valid type argument: only i64, bool, Option, Result, structs, enums and type parameters are",
                    tn(a)
                ),
                "arrays, str and () cannot be type arguments",
            ));
        }
        if let Some(tp) = tp {
            if tp.bound.as_deref() == Some("Element") && !is_element(a, &self.elem_params) {
                return Err(terr(
                    line,
                    col,
                    "generic_bound",
                    format!("{} does not satisfy the bound Element of {}", tn(a), tp.name),
                    "only i64, bool and type parameters declared `: Element` satisfy Element",
                ));
            }
        }
        Ok(())
    }

    /// Steps 1-4 of G3_SPEC 3.4 for a call / literal / constructor written with `targs` (None = no type application)
    /// -> substitution, or None for a non-generic declaration.
    #[allow(clippy::too_many_arguments)]
    fn instantiate(
        &self,
        line: i64,
        col: i64,
        what: &str,
        owner: &str,
        tparams: &[TParam],
        targs: &Option<Vec<GType>>,
    ) -> Res<Option<Mapping>> {
        let targs = match targs {
            None => {
                if !tparams.is_empty() {
                    let last = what.split_whitespace().last().unwrap_or("");
                    return Err(terr(
                        line,
                        col,
                        "type_arity",
                        format!("{} expects {} type argument(s)", what, tparams.len()),
                        format!("write the type arguments explicitly, e.g. {}::<T>; they are never inferred", last),
                    ));
                }
                return Ok(None);
            }
            Some(t) => t,
        };
        if tparams.is_empty() {
            return Err(terr(line, col, "type_arity", format!("{} takes no type arguments", what), "remove the `::<...>`"));
        }
        if targs.len() != tparams.len() {
            return Err(terr(
                line,
                col,
                "type_arity",
                format!("{} expects {} type argument(s), got {}", what, tparams.len(), targs.len()),
                "give exactly one type argument per type parameter",
            ));
        }
        for (a, tp) in targs.iter().zip(tparams.iter()) {
            self.check_type(line, col, a)?;
            self.check_arg(line, col, a, Some(tp))?;
        }
        match bind_args(owner, tparams.len(), targs) {
            Ok(m) => Ok(Some(m)),
            Err(e) => Err(terr(line, col, "internal", e.to_string(), "")),
        }
    }

    fn resolve_types(&mut self, prog: &Program) -> Res<()> {
        for d in &prog.types {
            self.enter(&decl_owner(d.name()), &d.tparams());
            let groups: Vec<&Vec<FieldDecl>> = match d {
                TypeDecl::Struct(s) => vec![&s.fields],
                TypeDecl::Enum(e) => e.variants.iter().map(|v| &v.fields).collect(),
            };
            for fields in groups {
                for f in fields {
                    let ft = GType::from_key(&f.ty);
                    if ft == unitt() || ft.is_array() || ft == strt() {
                        return Err(terr(
                            f.line,
                            f.col,
                            "field_type",
                            format!("field {} cannot have type {}", f.name, tn(&ft)),
                            "fields are i64, bool, Option<i64>, Result<i64> or a user struct/enum",
                        ));
                    }
                    self.check_type(f.line, f.col, &ft)?;
                }
            }
        }
        for f in &prog.functions {
            self.enter(&fn_owner(g3_base(&f.name)), &name_tparams(&f.name));
            for p in &f.params {
                self.check_type(f.line, f.col, &GType::from_key(&p.ty))?;
            }
            self.check_type(f.line, f.col, &GType::from_key(&f.ret))?;
        }
        Ok(())
    }

    fn type_recursion(&self, types: &[TypeDecl]) -> Res<()> {
        fn deps(decls: &HashMap<String, TypeDecl>, d: &TypeDecl) -> Vec<String> {
            let mut out: Vec<String> = Vec::new();
            for f in d.all_fields() {
                // G3: nested type arguments count
                for n in dependencies(&GType::from_key(&f.ty)) {
                    if decls.contains_key(&n) && !out.contains(&n) {
                        out.push(n);
                    }
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
            for c in deps(decls, d) {
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
        let fname = g3_base(&f.name).to_string();
        let ret = GType::from_key(&f.ret);
        self.enter(&fn_owner(&fname), &name_tparams(&f.name));
        self.cur_name = fname.clone();
        self.cur_ret = ret.clone();
        self.calls.insert(fname.clone(), BTreeSet::new());
        let mut scope: Scope = HashMap::new();
        for p in &f.params {
            if scope.contains_key(&p.name) {
                return Err(terr(f.line, f.col, "dup_param", format!("duplicate parameter {}", p.name), ""));
            }
            let pt = GType::from_key(&p.ty);
            if pt == unitt() {
                return Err(terr(f.line, f.col, "unit_param", format!("parameter {} cannot have type ()", p.name), ""));
            }
            scope.insert(p.name.clone(), Entry { ty: pt, mutable: false, kind: "param" });
        }
        self.used_effects = BTreeSet::new();
        for r in f.requires.iter_mut() {
            self.expect(r, &boolt(), &scope, true, None)?;
        }
        let mut escope = scope.clone();
        if ret != unitt() {
            escope.insert("result".to_string(), Entry { ty: ret.clone(), mutable: false, kind: "result" });
        }
        for e in f.ensures.iter_mut() {
            self.expect(e, &boolt(), &escope, true, None)?;
        }
        let mut body_scope = scope.clone();
        self.block(&mut f.body, &mut body_scope)?;
        if ret != unitt() && !ends_in_return(&f.body) {
            return Err(terr(
                f.line,
                f.col,
                "missing_return",
                format!("function {} may reach its end without returning", fname),
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
                    format!("function {} uses effect `{}` but does not declare it", fname, e),
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

    /// Whether `t` names a declared struct (a type parameter never does).
    fn is_struct(&self, t: &GType) -> bool {
        t.owner.is_none() && self.tt.is_struct(&t.name)
    }

    fn is_enum(&self, t: &GType) -> bool {
        t.owner.is_none() && self.tt.is_enum(&t.name)
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
                let sty = GType::from_key(&s.ty);
                if sty == unitt() {
                    return Err(terr(s.line, s.col, "unit_let", "cannot bind a () value", ""));
                }
                self.check_type(s.line, s.col, &sty)?;
                self.want_alloc(&s.value, &sty);
                self.expect(&mut s.value, &sty, scope, false, None)?;
                if sty.is_array() || sty == strt() {
                    self.array_source(s.line, s.col, &s.value, scope, false, &sty)?;
                }
                scope.insert(s.name.clone(), Entry { ty: sty, mutable: s.mutable, kind: "local" });
            }
            Stmt::Assign(s) => {
                let v = self.lookup(s.line, s.col, &s.name, scope)?;
                if !v.mutable {
                    return Err(terr(s.line, s.col, "immutable", format!("{} is not mutable", s.name), Self::immutable_fix(v.kind)));
                }
                self.want_alloc(&s.value, &v.ty);
                self.expect(&mut s.value, &v.ty, scope, false, None)?;
                if v.ty.is_array() || v.ty == strt() {
                    self.array_source(s.line, s.col, &s.value, scope, false, &v.ty)?;
                }
            }
            Stmt::IndexAssign(s) => {
                let v = self.lookup(s.line, s.col, &s.name, scope)?;
                if v.ty == strt() {
                    return Err(terr(
                        s.line,
                        s.col,
                        "immutable_string",
                        format!("{} is a str; its bytes cannot be changed", s.name),
                        "build a new str with substr() or copy() instead",
                    ));
                }
                if !v.ty.is_array() {
                    return Err(terr(s.line, s.col, "not_array", format!("{} is not an array", s.name), ""));
                }
                if !v.mutable {
                    return Err(terr(
                        s.line,
                        s.col,
                        "immutable",
                        format!("array {} is read-only", s.name),
                        format!("use `let mut b: {} = copy({});` (needs alloc)", tn(&v.ty), s.name),
                    ));
                }
                self.expect(&mut s.index, &i64t(), scope, false, None)?;
                // G2 A5: stored value is bool for a bool array; G3: exactly T for a [T]
                let want_val = elem_type(&v.ty);
                self.expect(&mut s.value, &want_val, scope, false, None)?;
            }
            Stmt::FieldAssign(s) => {
                let v = self.lookup(s.line, s.col, &s.name, scope)?;
                let mut cur = v.ty.clone();
                for fname in &s.fields {
                    if cur.owner.is_some() {
                        return Err(terr(
                            s.line,
                            s.col,
                            "generic_operation",
                            format!("cannot assign field {}: {} is an abstract type parameter", fname, tn(&cur)),
                            "a type parameter has no fields",
                        ));
                    }
                    if !self.is_struct(&cur) {
                        return Err(terr(
                            s.line,
                            s.col,
                            "not_struct",
                            format!("cannot assign field {}: {} is not a struct", fname, tn(&cur)),
                            "field assignment paths run through structs only; assign the whole enum value instead",
                        ));
                    }
                    cur = self.field_type(s.line, s.col, &cur, fname)?;
                }
                if !v.mutable {
                    return Err(terr(s.line, s.col, "immutable", format!("{} is not mutable", s.name), Self::immutable_fix(v.kind)));
                }
                self.expect(&mut s.value, &cur, scope, false, None)?;
            }
            Stmt::If(s) => {
                self.expect(&mut s.cond, &boolt(), scope, false, Some("a condition"))?;
                let mut sc = scope.clone();
                self.block(&mut s.then, &mut sc)?;
                let mut sc = scope.clone();
                self.block(&mut s.els, &mut sc)?;
            }
            Stmt::While(s) => {
                self.expect(&mut s.cond, &boolt(), scope, false, Some("a condition"))?;
                for i in s.invariants.iter_mut() {
                    self.expect(i, &boolt(), scope, true, None)?;
                }
                self.expect(&mut s.decreases, &i64t(), scope, true, None)?;
                let mut sc = scope.clone();
                self.block(&mut s.body, &mut sc)?;
            }
            Stmt::Return(s) => {
                let ret = self.cur_ret.clone();
                match &mut s.value {
                    None => {
                        if ret != unitt() {
                            return Err(terr(
                                s.line,
                                s.col,
                                "return_type",
                                format!("function returns {}; `return;` is not enough", tn(&ret)),
                                "",
                            ));
                        }
                    }
                    Some(v) => {
                        if ret == unitt() {
                            return Err(terr(s.line, s.col, "return_type", "function returns (); use `return;`", ""));
                        }
                        self.want_alloc(v, &ret);
                        self.expect(v, &ret, scope, false, None)?;
                        if ret.is_array() || ret == strt() {
                            self.array_source(s.line, s.col, v, scope, true, &ret)?;
                        }
                    }
                }
            }
            Stmt::Assert(s) => {
                self.expect(&mut s.cond, &boolt(), scope, true, None)?;
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
                if t != unitt() {
                    return Err(terr(
                        s.line,
                        s.col,
                        "unused_value",
                        format!("value of type {} is dropped", tn(&t)),
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
        let user = self.is_enum(&t);
        if t.owner.is_some() {
            return Err(terr(
                line,
                col,
                "generic_operation",
                format!("cannot match a value of the abstract type {}", t.name),
                "a type parameter has no variants; match on an Option, Result or enum that contains it",
            ));
        }
        let need: Vec<String> = if t.name == "option" {
            vec!["Some".to_string(), "None".to_string()]
        } else if t.name == "result" {
            vec!["Ok".to_string(), "Err".to_string()]
        } else if user {
            match self.tt.decl(&t.name) {
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
                if a.enum_name.as_deref() != Some(t.name.as_str()) {
                    let what = match &a.enum_name {
                        Some(en) if !en.is_empty() => format!("{}::{}", en, a.ctor),
                        _ => a.ctor.clone(),
                    };
                    return Err(terr(
                        a.line,
                        a.col,
                        "match_arms",
                        format!("arm {} does not belong to enum {}", what, t.name),
                        format!("match arms are written {}::Variant", t.name),
                    ));
                }
                if !need.contains(&a.ctor) {
                    return Err(terr(a.line, a.col, "unknown_variant", format!("enum {} has no variant {}", t.name, a.ctor), ""));
                }
                if seen.contains(&a.ctor.as_str()) {
                    return Err(terr(a.line, a.col, "match_arms", format!("arm {}::{} appears twice", t.name, a.ctor), ""));
                }
                seen.push(&a.ctor);
            }
            let missing: Vec<String> = need.iter().filter(|n| !seen.contains(&n.as_str())).map(|n| format!("{}::{}", t.name, n)).collect();
            if !missing.is_empty() {
                return Err(terr(line, col, "match_arms", format!("match is missing arm(s): {}", missing.join(", ")), ""));
            }
        }
        for a in m.arms.iter_mut() {
            let mut sc = scope.clone();
            let (nl, nc) = if user { (a.line, a.col) } else { (line, col) };
            let ftypes: Vec<GType> = if user {
                let v: Vec<GType> = self.fields_of(&t, Some(a.ctor.as_str()))?.into_iter().map(|(_, ft)| ft).collect();
                if a.binders.len() != v.len() {
                    return Err(terr(
                        a.line,
                        a.col,
                        "match_arity",
                        format!("{}::{} has {} field(s), the pattern binds {}", t.name, a.ctor, v.len(), a.binders.len()),
                        "bind every field, in declaration order",
                    ));
                }
                v
            } else {
                // G3: the Some/Ok binder has the payload type of Option<X> / Result<X>; Err binds the i64 code
                let payload = if !t.args.is_empty() && a.ctor != "Err" { t.args[0].clone() } else { i64t() };
                vec![payload; a.binders.len()]
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
    fn array_source(&self, line: i64, col: i64, value: &Expr, scope: &Scope, allow_local_var: bool, ty: &GType) -> Res<()> {
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
            if *ty == strt() {
                "a str value here must come from a string literal, copy(), substr() or a function call"
            } else {
                "an array value here must come from alloc(), copy() or a function call"
            },
            "write copy(x) to make an explicit copy (needs `! alloc`)",
        ))
    }

    /// The argument must be an array of any element type (G2 B0: or a str).
    fn expect_array(&mut self, e: &mut Expr, scope: &Scope, c: bool) -> Res<GType> {
        let t = self.expr(e, scope, c)?;
        if t.owner.is_some() {
            return Err(terr(
                e.line(),
                e.col(),
                "generic_operation",
                format!("{} is an abstract type parameter, not an array", tn(&t)),
                "only [T] with T: Element can be indexed, measured or copied",
            ));
        }
        if !t.is_array() && t != strt() {
            return Err(terr(
                e.line(),
                e.col(),
                "type_mismatch",
                format!("expected {}, found {}", tn(&GType::array()), tn(&t)),
                "",
            ));
        }
        Ok(t)
    }

    // ---- expressions ----
    /// op: what the operand is used for (arithmetic, comparison, ...) when the operation needs a concrete type:
    /// an abstract type parameter there is a generic_operation error rather than a plain mismatch.
    fn expect(&mut self, e: &mut Expr, ty: &GType, scope: &Scope, contract: bool, op: Option<&str>) -> Res<GType> {
        let t = self.expr(e, scope, contract)?;
        if t != *ty {
            if let Some(op) = op {
                if t.owner.is_some() {
                    return Err(terr(
                        e.line(),
                        e.col(),
                        "generic_operation",
                        format!("{} is not allowed on the abstract type {}", op, t.name),
                        "a type parameter can be copied, passed, returned and stored; == works on it in contracts only",
                    ));
                }
            }
            return Err(terr(
                e.line(),
                e.col(),
                "type_mismatch",
                format!("expected {}, found {}", tn(ty), tn(&t)),
                "",
            ));
        }
        Ok(t)
    }

    fn expr(&mut self, e: &mut Expr, scope: &Scope, contract: bool) -> Res<GType> {
        let t = self.expr_inner(e, scope, contract)?;
        set_ty(e, &t);
        Ok(t)
    }

    fn expr_inner(&mut self, e: &mut Expr, scope: &Scope, c: bool) -> Res<GType> {
        match e {
            Expr::IntLit(x) => {
                if !int_in_range(&x.value) {
                    return Err(terr(x.line, x.col, "int_range", "integer literal out of i64 range", ""));
                }
                Ok(i64t())
            }
            Expr::BoolLit(_) => Ok(boolt()),
            Expr::StrLit(_) => {
                if !c {
                    self.used_effects.insert("alloc".to_string());
                }
                Ok(strt())
            }
            Expr::Var(x) => {
                if x.name == "result" && !scope.contains_key("result") {
                    return Err(terr(x.line, x.col, "result_scope", "`result` is only allowed in ensures", ""));
                }
                Ok(self.lookup(x.line, x.col, &x.name, scope)?.ty)
            }
            Expr::Unary(x) => {
                if x.op == "-" {
                    self.expect(&mut x.operand, &i64t(), scope, c, Some("unary minus"))?;
                    Ok(i64t())
                } else {
                    self.expect(&mut x.operand, &boolt(), scope, c, Some("a boolean operation"))?;
                    Ok(boolt())
                }
            }
            Expr::Binary(x) => {
                let op = x.op.clone();
                match op.as_str() {
                    "+" | "-" | "*" | "/" | "%" => {
                        self.expect(&mut x.left, &i64t(), scope, c, Some("arithmetic"))?;
                        self.expect(&mut x.right, &i64t(), scope, c, Some("arithmetic"))?;
                        Ok(i64t())
                    }
                    "<" | "<=" | ">" | ">=" => {
                        self.expect(&mut x.left, &i64t(), scope, c, Some("ordering"))?;
                        self.expect(&mut x.right, &i64t(), scope, c, Some("ordering"))?;
                        Ok(boolt())
                    }
                    "==" | "!=" => {
                        let lt = self.expr(&mut x.left, scope, c)?;
                        if lt.is_array() {
                            return Err(terr(
                                x.line,
                                x.col,
                                "eq_type",
                                "arrays cannot be compared with ==",
                                "compare lengths and elements: len(a) == len(b) && forall k in 0..len(a): a[k] == b[k]",
                            ));
                        }
                        if lt == strt() {
                            return Err(terr(
                                x.line,
                                x.col,
                                "eq_type",
                                "str values cannot be compared with ==",
                                "compare lengths and bytes: len(a) == len(b) && forall k in 0..len(a): a[k] == b[k]",
                            ));
                        }
                        if lt.owner.is_some() && !c {
                            return Err(terr(
                                x.line,
                                x.col,
                                "generic_operation",
                                format!("== is not allowed on the abstract type {} in code", lt.name),
                                "runtime equality only compares i64 or bool; == on a type parameter works in contracts",
                            ));
                        }
                        if lt != i64t() && lt != boolt() && !c {
                            return Err(terr(x.line, x.col, "eq_type", "== only compares i64 or bool in code", "use match"));
                        }
                        self.expect(&mut x.right, &lt, scope, c, None)?;
                        Ok(boolt())
                    }
                    "&&" | "||" => {
                        self.expect(&mut x.left, &boolt(), scope, c, Some("a boolean operation"))?;
                        self.expect(&mut x.right, &boolt(), scope, c, Some("a boolean operation"))?;
                        Ok(boolt())
                    }
                    "==>" => {
                        if !c {
                            return Err(terr(x.line, x.col, "contract_only", "==> is only allowed in contracts", ""));
                        }
                        self.expect(&mut x.left, &boolt(), scope, c, Some("a boolean operation"))?;
                        self.expect(&mut x.right, &boolt(), scope, c, Some("a boolean operation"))?;
                        Ok(boolt())
                    }
                    _ => Err(terr(x.line, x.col, "internal", "unknown expression", "")),
                }
            }
            Expr::Index(x) => {
                let at = self.expect_array(&mut x.array, scope, c)?;
                self.expect(&mut x.index, &i64t(), scope, c, None)?;
                // G2 A5: a bool array reads bool; G3: [T] reads T
                Ok(elem_type(&at))
            }
            Expr::Ctor(x) => self.ctor(x, scope, c),
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
                self.expect(&mut x.lo, &i64t(), scope, c, None)?;
                self.expect(&mut x.hi, &i64t(), scope, c, None)?;
                if scope.contains_key(&x.var) {
                    return Err(terr(x.line, x.col, "shadow", format!("{} is already defined", x.var), "use a new name"));
                }
                let mut sc = scope.clone();
                sc.insert(x.var.clone(), Entry { ty: i64t(), mutable: false, kind: "bound" });
                let boolean_body = matches!(x.kind.as_str(), "forall" | "exists" | "count");
                let body_ty = if boolean_body { boolt() } else { i64t() };
                let what = if boolean_body { "a quantifier body".to_string() } else { format!("an aggregate ({})", x.kind) };
                self.expect(&mut x.body, &body_ty, &sc, c, Some(what.as_str()))?;
                Ok(if agg { i64t() } else { boolt() })
            }
            Expr::StructLit(x) => self.struct_lit(x, scope, c),
            Expr::EnumCtor(x) => {
                let name = g3_base(&x.enum_name).to_string();
                let targs = targs_of(&x.enum_name);
                let mut ety = self.enum_type(x.line, x.col, &name)?;
                let tps = self.decls.get(&name).map(|d| d.tparams()).unwrap_or_default();
                let m = self.instantiate(x.line, x.col, &format!("enum {}", name), &decl_owner(&name), &tps, &targs)?;
                if m.is_some() {
                    ety = mk_nominal(&name, targs.clone().unwrap_or_default());
                }
                self.variant_decl(x.line, x.col, &ety, &x.variant)?;
                let fields = self.fields_of(&ety, Some(x.variant.as_str()))?;
                if x.args.len() != fields.len() {
                    return Err(terr(
                        x.line,
                        x.col,
                        "arity",
                        format!("{}::{} takes {} argument(s), got {}", name, x.variant, fields.len(), x.args.len()),
                        "",
                    ));
                }
                for (arg, fd) in x.args.iter_mut().zip(fields.iter()) {
                    self.expect(arg, &fd.1, scope, c, None)?;
                }
                Ok(ety)
            }
            Expr::FieldAccess(x) => {
                let bt = self.expr(&mut x.base, scope, c)?;
                if bt.owner.is_some() {
                    return Err(terr(
                        x.line,
                        x.col,
                        "generic_operation",
                        format!("cannot read field {}: {} is an abstract type parameter", x.field, tn(&bt)),
                        "a type parameter has no fields",
                    ));
                }
                if !self.is_struct(&bt) {
                    return Err(terr(
                        x.line,
                        x.col,
                        "not_struct",
                        format!("cannot read field {}: {} is not a struct", x.field, tn(&bt)),
                        if self.is_enum(&bt) { "enum payloads are read with match" } else { "" },
                    ));
                }
                self.field_type(x.line, x.col, &bt, &x.field)
            }
            Expr::IsVariant(x) => {
                if !c {
                    return Err(terr(x.line, x.col, "contract_only", "is_variant is only allowed in contracts", "use match in code"));
                }
                self.variant_target(x.line, x.col, &mut x.value, &x.enum_name, &x.variant, scope, c)?;
                Ok(boolt())
            }
            Expr::VariantField(x) => {
                if !c {
                    return Err(terr(x.line, x.col, "contract_only", "variant_field is only allowed in contracts", "use match in code"));
                }
                let ety = self.variant_target(x.line, x.col, &mut x.value, &x.enum_name, &x.variant, scope, c)?;
                for (fname, ft) in self.fields_of(&ety, Some(x.variant.as_str()))? {
                    if fname == x.field {
                        return Ok(ft);
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
    /// [(field name, field type)] of the struct / enum variant `ty` names, with the type arguments of `ty` substituted
    /// into the declared field types (G3_SPEC 3.4).
    fn fields_of(&self, ty: &GType, variant: Option<&str>) -> Res<Vec<(String, GType)>> {
        let n = self.decls.get(&ty.name).map(|d| d.tparams().len()).unwrap_or(0);
        let m = match bind_args(&decl_owner(&ty.name), n, &ty.args) {
            Ok(m) => m,
            Err(e) => return Err(terr(0, 0, "internal", e.to_string(), "")),
        };
        let fs = self.tt.fields(&ty.name, variant).unwrap_or(&[]);
        Ok(fs.iter().map(|fd| (fd.name.clone(), substitute(&GType::from_key(&fd.ty), &m))).collect())
    }

    /// The type of a struct field.
    fn field_type(&self, line: i64, col: i64, sty: &GType, name: &str) -> Res<GType> {
        for (fname, ft) in self.fields_of(sty, None)? {
            if fname == name {
                return Ok(ft);
            }
        }
        Err(terr(line, col, "unknown_field", format!("struct {} has no field {}", sty.name, name), ""))
    }

    /// The type of a named enum; unknown_type if missing, not_enum if it is not an enum.
    fn enum_type(&self, line: i64, col: i64, name: &str) -> Res<GType> {
        if !self.decls.contains_key(name) {
            return Err(terr(line, col, "unknown_type", format!("unknown type {}", name), ""));
        }
        if !self.tt.is_enum(name) {
            return Err(terr(line, col, "not_enum", format!("{} is not an enum", name), ""));
        }
        Ok(GType::new(name, Vec::new()))
    }

    fn variant_decl(&self, line: i64, col: i64, ety: &GType, variant: &str) -> Res<()> {
        match self.tt.variant(&ety.name, variant) {
            Some(_) => Ok(()),
            None => Err(terr(line, col, "unknown_variant", format!("enum {} has no variant {}", ety.name, variant), "")),
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
    ) -> Res<GType> {
        let vt = self.expr(value, scope, c)?;
        let ety = self.enum_type(line, col, enum_name)?;
        self.variant_decl(line, col, &ety, variant)?;
        // G3: no explicit type arguments here; they come from the checked scrutinee, which keeps its full type
        if vt.owner.is_some() || vt.name != ety.name {
            return Err(terr(
                value.line(),
                value.col(),
                "type_mismatch",
                format!("expected {}, found {}", tn(&ety), tn(&vt)),
                "",
            ));
        }
        Ok(vt)
    }

    fn struct_lit(&mut self, e: &mut StructLit, scope: &Scope, c: bool) -> Res<GType> {
        let name = g3_base(&e.name).to_string();
        let targs = targs_of(&e.name);
        if !self.decls.contains_key(&name) {
            return Err(terr(e.line, e.col, "unknown_type", format!("unknown type {}", name), ""));
        }
        if !self.tt.is_struct(&name) {
            return Err(terr(
                e.line,
                e.col,
                "not_struct",
                format!("{} is not a struct", name),
                format!("enum values are written {}::Variant", name),
            ));
        }
        let mut sty = GType::new(&name, Vec::new());
        let tps = self.decls.get(&name).map(|d| d.tparams()).unwrap_or_default();
        let m = self.instantiate(e.line, e.col, &format!("struct {}", name), &decl_owner(&name), &tps, &targs)?;
        if m.is_some() {
            sty = mk_nominal(&name, targs.clone().unwrap_or_default());
        }
        let fields: Vec<(String, GType)> = self.fields_of(&sty, None)?;
        let declared: Vec<&str> = fields.iter().map(|f| f.0.as_str()).collect();
        for fi in &e.fields {
            if !declared.contains(&fi.name.as_str()) {
                return Err(terr(fi.line, fi.col, "unknown_field", format!("struct {} has no field {}", name, fi.name), ""));
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
                format!("{} literal: {}", name, why),
                "write every field exactly once, in declaration order",
            ));
        }
        for (fi, fd) in e.fields.iter_mut().zip(fields.iter()) {
            self.expect(&mut fi.value, &fd.1, scope, c, None)?;
        }
        Ok(sty)
    }

    /// Some / None / Ok / Err. Without type arguments they keep the legacy i64 meaning (G3_SPEC 0.0 item 8);
    /// `Some::<X>(x)`, `None::<X>`, `Ok::<X>(x)`, `Err::<X>(code)` build Option<X> / Result<X> (3.5).
    fn ctor(&mut self, e: &mut Ctor, scope: &Scope, c: bool) -> Res<GType> {
        let name = g3_base(&e.name).to_string();
        let targs = match targs_of(&e.name) {
            None => {
                if name == "None" {
                    return Ok(GType::option());
                }
                if let Some(a) = e.arg.as_mut() {
                    self.expect(a, &i64t(), scope, c, None)?;
                }
                return Ok(if name == "Some" { GType::option() } else { GType::result() });
            }
            Some(t) => t,
        };
        if targs.len() != 1 {
            return Err(terr(
                e.line,
                e.col,
                "type_arity",
                format!("{}::<..> takes exactly 1 type argument, got {}", name, targs.len()),
                format!("write {}::<T>", name),
            ));
        }
        let x = targs[0].clone();
        self.check_type(e.line, e.col, &x)?;
        self.check_arg(e.line, e.col, &x, None)?;
        if name == "None" {
            return Ok(mk_option(x));
        }
        let want = if name == "Err" { i64t() } else { x.clone() };
        if let Some(a) = e.arg.as_mut() {
            self.expect(a, &want, scope, c, None)?;
        }
        Ok(if name == "Some" { mk_option(x) } else { mk_result(x) })
    }

    fn call(&mut self, e: &mut Call, scope: &Scope, c: bool) -> Res<GType> {
        let n = g3_base(&e.name).to_string();
        let targs = targs_of(&e.name);
        let (line, col) = (e.line, e.col);
        let alen = e.args.len();
        let arity = |k: usize| -> Res<()> {
            if alen != k {
                return Err(terr(line, col, "arity", format!("{} takes {} argument(s), got {}", n, k, alen), ""));
            }
            Ok(())
        };
        let is_builtin = matches!(n.as_str(), "len" | "alloc" | "copy" | "print" | "is_char_boundary" | "substr");
        if targs.is_some() && !self.funcs.contains_key(&n) && (is_builtin || contract_only(&n).is_some()) {
            return Err(terr(line, col, "type_arity", format!("builtin {} takes no type arguments", n), "remove the `::<...>`"));
        }
        match n.as_str() {
            "len" => {
                arity(1)?;
                self.expect_array(&mut e.args[0], scope, c)?;
                return Ok(i64t());
            }
            "alloc" => {
                let want = self.alloc_want.take();
                if c {
                    return Err(terr(line, col, "effect_in_contract", "alloc not allowed in contracts", ""));
                }
                arity(2)?;
                self.expect(&mut e.args[0], &i64t(), scope, c, None)?;
                // G2 A5: the fill value is bool when the hinted type is [bool]; G3: T when it is [T]
                let vwant = match &want {
                    Some(h) => elem_type(h),
                    None => i64t(),
                };
                self.expect(&mut e.args[1], &vwant, scope, c, None)?;
                self.used_effects.insert("alloc".to_string());
                return Ok(want.unwrap_or_else(GType::array));
            }
            "copy" => {
                if c {
                    return Err(terr(line, col, "effect_in_contract", "copy not allowed in contracts", ""));
                }
                arity(1)?;
                let at = self.expect_array(&mut e.args[0], scope, c)?;
                self.used_effects.insert("alloc".to_string());
                return Ok(at);
            }
            "is_char_boundary" => {
                arity(2)?;
                self.expect(&mut e.args[0], &strt(), scope, c, None)?;
                self.expect(&mut e.args[1], &i64t(), scope, c, None)?;
                return Ok(boolt());
            }
            "substr" => {
                if c {
                    return Err(terr(line, col, "effect_in_contract", "substr not allowed in contracts", ""));
                }
                arity(3)?;
                self.expect(&mut e.args[0], &strt(), scope, c, None)?;
                self.expect(&mut e.args[1], &i64t(), scope, c, None)?;
                self.expect(&mut e.args[2], &i64t(), scope, c, None)?;
                self.used_effects.insert("alloc".to_string());
                return Ok(strt());
            }
            "print" => {
                if c {
                    return Err(terr(line, col, "effect_in_contract", "print not allowed in contracts", ""));
                }
                arity(1)?;
                let t = self.expr(&mut e.args[0], scope, c)?;
                if t.owner.is_some() {
                    return Err(terr(
                        line,
                        col,
                        "generic_operation",
                        format!("print cannot take the abstract type {}", t.name),
                        "print takes a concrete i64 or bool",
                    ));
                }
                if t != i64t() && t != boolt() {
                    return Err(terr(line, col, "print_type", "print takes i64 or bool", ""));
                }
                self.used_effects.insert("io".to_string());
                return Ok(unitt());
            }
            _ => {}
        }
        if let Some((kind, rt)) = contract_only(&n) {
            if !c {
                return Err(terr(line, col, "contract_only", format!("{} is only allowed in contracts", n), "use match in code"));
            }
            arity(1)?;
            let t = self.expr(&mut e.args[0], scope, c)?;
            if t.owner.is_some() || t.name != kind {
                let want = if kind == "option" { GType::option() } else { GType::result() };
                return Err(terr(
                    e.args[0].line(),
                    e.args[0].col(),
                    "type_mismatch",
                    format!("expected {}, found {}", tn(&want), tn(&t)),
                    "",
                ));
            }
            return Ok(match rt {
                CRes::Bool => boolt(),
                CRes::I64 => i64t(),
                // G3: the payload type of Option<X> / Result<X>
                CRes::Payload => {
                    if t.args.is_empty() {
                        i64t()
                    } else {
                        t.args[0].clone()
                    }
                }
            });
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
        // G3_SPEC 3.4: resolve + arity + admissibility + bounds, substitute the signature, check the arguments
        let m = self.instantiate(line, col, &format!("function {}", n), &fn_owner(&n), &f.tparams, &targs)?.unwrap_or_default();
        arity(f.params.len())?;
        for (arg, p) in e.args.iter_mut().zip(f.params.iter()) {
            self.expect(arg, &substitute(p, &m), scope, c, None)?;
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
        Ok(substitute(&f.ret, &m))
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
