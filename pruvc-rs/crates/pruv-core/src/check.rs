//! Type, effect and structure checker (counterpart of check.py). Fills in `ty` for every expression.
//! Function structure, check order, code, stage, message and fix match Python character for character.
//!
//! G3 A1: types are `GType` inside the checker; the AST carries them as key strings (gtype.rs `to_key`/`from_key`),
//! which are the plain legacy names for every non-generic program. Type parameters and written type arguments are
//! real AST fields (ast.rs); the checker records the instantiation (`inst`) and `enum_ty` on the nodes (Python check.py).

use crate::ast::*;
use crate::diagnostic::PruvError;
use crate::foreign::{
    catalog_fn, check_foreign_decl, check_ownership, is_catalog, is_catalog_contract_only, is_file_observer, CatFn,
    Takes,
};
use crate::gtype::{
    bind_args, check_arity, collection_arity, decl_owner, dependencies, fn_owner, format_type, is_element, is_value,
    key_is_collection, mk_array, mk_nominal, mk_option, mk_result, substitute, GType, Mapping, ParamId,
};
use crate::typeinfo::{program_uses_inout, TypeTable, BUILTIN_TYPE_NAMES};
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
pub(crate) enum CRes {
    Bool,
    I64,
    /// The Option/Result payload type.
    Payload,
}

/// Built-ins used only in contracts: name -> (argument kind, result).
pub(crate) fn contract_only(n: &str) -> Option<(&'static str, CRes)> {
    match n {
        "is_some" => Some(("option", CRes::Bool)),
        "some_val" => Some(("option", CRes::Payload)),
        "is_ok" => Some(("result", CRes::Bool)),
        "ok_val" => Some(("result", CRes::Payload)),
        "err_val" => Some(("result", CRes::I64)),
        "size" => Some(("size", CRes::I64)), // G9 A0: structural size of a non-generic nominal value
        _ => None,
    }
}

/// G9 A0: strongly connected components of the graph on nodes 0..n-1 (adj[i]: successors of i), iterative Tarjan.
/// -> member lists (each ascending), ordered by their smallest member.
fn sccs(n: usize, adj: &[Vec<usize>]) -> Vec<Vec<usize>> {
    let mut index_of: Vec<i64> = vec![-1; n];
    let mut low: Vec<i64> = vec![0; n];
    let mut on_stack: Vec<bool> = vec![false; n];
    let mut stack: Vec<usize> = Vec::new();
    let mut out: Vec<Vec<usize>> = Vec::new();
    let mut counter: i64 = 0;
    for root in 0..n {
        if index_of[root] != -1 {
            continue;
        }
        index_of[root] = counter;
        low[root] = counter;
        counter += 1;
        stack.push(root);
        on_stack[root] = true;
        let mut work: Vec<(usize, usize)> = vec![(root, 0)];
        while let Some(&(v, i)) = work.last() {
            if i < adj[v].len() {
                let last = work.len() - 1;
                work[last] = (v, i + 1);
                let w = adj[v][i];
                if index_of[w] == -1 {
                    index_of[w] = counter;
                    low[w] = counter;
                    counter += 1;
                    stack.push(w);
                    on_stack[w] = true;
                    work.push((w, 0));
                } else if on_stack[w] {
                    low[v] = low[v].min(index_of[w]);
                }
            } else {
                work.pop();
                if let Some(&(p, _)) = work.last() {
                    low[p] = low[p].min(low[v]);
                }
                if low[v] == index_of[v] {
                    let mut comp: Vec<usize> = Vec::new();
                    loop {
                        let w = stack.pop().unwrap_or(v);
                        on_stack[w] = false;
                        comp.push(w);
                        if w == v {
                            break;
                        }
                    }
                    comp.sort();
                    out.push(comp);
                }
            }
        }
    }
    out.sort_by_key(|c| c[0]);
    out
}

/// G9 A0: shortest cycle start -> ... -> start inside `members` (breadth first, successors in adjacency order);
/// -> nodes beginning and ending with start.
fn cycle_through(start: usize, adj: &[Vec<usize>], members: &[usize]) -> Vec<usize> {
    let members: HashSet<usize> = members.iter().cloned().collect();
    let mut prev: HashMap<usize, Option<usize>> = HashMap::new();
    prev.insert(start, None);
    let mut queue: Vec<usize> = vec![start];
    let mut qi = 0usize;
    while qi < queue.len() {
        let v = queue[qi];
        qi += 1;
        for &w in &adj[v] {
            if !members.contains(&w) {
                continue;
            }
            if w == start {
                let mut chain: Vec<usize> = Vec::new();
                let mut x: Option<usize> = Some(v);
                while let Some(xv) = x {
                    chain.push(xv);
                    x = prev.get(&xv).cloned().unwrap_or(None);
                }
                chain.reverse(); // start ... v
                chain.push(start);
                return chain;
            }
            if !prev.contains_key(&w) {
                prev.insert(w, Some(v));
                queue.push(w);
            }
        }
    }
    vec![start, start]
}

/// G9 A0: [(variant name or None, field)] of a declaration in variant/field source order.
fn decl_fields(d: &TypeDecl) -> Vec<(Option<&str>, &FieldDecl)> {
    match d {
        TypeDecl::Struct(s) => s.fields.iter().map(|f| (None, f)).collect(),
        TypeDecl::Enum(e) => e
            .variants
            .iter()
            .flat_map(|v| v.fields.iter().map(move |f| (Some(v.name.as_str()), f)))
            .collect(),
    }
}

fn field_label(d: &str, vname: Option<&str>, field: &str) -> String {
    match vname {
        None => format!("{}.{}", d, field),
        Some(v) => format!("{}::{}.{}", d, v, field),
    }
}

/// The checked type key of an expression (None before the checker has seen it).
fn expr_ty(e: &Expr) -> &Ty {
    match e {
        Expr::InoutArg(x) => &x.ty,
        Expr::Move(x) => &x.ty,
        Expr::Spent(x) => &x.ty,
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
    }
}

pub(crate) const RESERVED_TYPE_NAMES: [&str; 6] = ["Option", "Result", "Some", "None", "Ok", "Err"];

fn is_tail(s: &str) -> bool {
    s.chars().all(|c| c.is_ascii_alphanumeric() || c == '_')
}

/// ^[A-Z][A-Za-z0-9_]*$ (ASCII)
pub(crate) fn type_name_ok(s: &str) -> bool {
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
pub(crate) fn cap_first(s: &str, upper: bool) -> String {
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
    kind: &'static str, // "param" | "inout" (G5) | "result" | "local" | "bound"
}
type Scope = HashMap<String, Entry>;

#[derive(Clone)]
struct FuncInfo {
    src_name: String,
    line: i64,
    col: i64,
    params: Vec<GType>,
    /// G5 A0: parameter names (position of `old(a)`, messages)
    pnames: Vec<String>,
    /// G5 A0: parameter is `inout`
    inout: Vec<bool>,
    ret: GType,
    effects: Vec<String>,
    tparams: Vec<TParam>,
    /// G6: a `trusted rust fn` (cannot be called in a contract)
    foreign: bool,
}

struct Checker {
    funcs: HashMap<String, Rc<FuncInfo>>,
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
    /// G6: crate names given with --rust-extern
    externs: Vec<String>,
    /// G6: function name -> `take` flags of its parameters (for the ownership checker)
    takes: Takes,
    // ---- G9 A0 metadata ----
    /// recursive type SCCs (names in declaration order), SCC-number order
    type_sccs: Vec<Vec<String>>,
    /// "Decl.field" / "Enum::Variant.field" of every intra-SCC (boxed) field
    boxed: Vec<String>,
    /// (declaration name, variant name or None) holding at least one boxed field
    boxed_decls: HashSet<(String, Option<String>)>,
    /// names of extended declarations
    extended: HashSet<String>,
    /// declarations transitively containing a buffer (array/str) field
    buffered: HashSet<String>,
    /// recursive function SCCs (names in function order)
    fn_sccs: Vec<Vec<String>>,
    /// (caller name, call line, call col, call targs, callee name) of every checked user call
    call_log: Vec<(String, i64, i64, Option<Vec<GType>>, String)>,
    /// root variable names of the enclosing match arms on extended scrutinees
    active_roots: Vec<String>,
    cur_cost: bool,
    s5_errors: Vec<(String, PruvError)>,
    par_groups: Vec<Vec<Expr>>,
    /// G4 A0: explicit visibility mode (the declaration names are resolved identities)
    explicit: bool,
    /// G4 A0: per function (same index as Program.functions): a host entry
    host_entry: Vec<bool>,
    /// G5 A0: enables the contextual builtin `old`
    uses_inout: bool,
    /// G5: kind of the expression being checked: requires/ensures/decreases/invariant/assert/code
    ckind: &'static str,
    /// G5: identity of the call allowed at the statement boundary of the statement being checked
    boundary: Option<usize>,
    /// G5 A0: parameter names of the function being checked
    cur_params: Vec<String>,
}

/// G4 A0: `check_with_externs` for an explicit-mode program: resolves the names of the whole program to identities first
/// (modules::resolve), then runs the same checker plus the host-entry signature rules.
pub fn check_explicit(
    prog: &mut Program,
    g4: &mut crate::modules::G4,
    externs: &[String],
) -> Result<TypeTable, PruvError> {
    crate::modules::resolve(prog, g4)?;
    let src_names: Vec<String> = g4.fn_meta.iter().map(|m| m.src_name.clone()).collect();
    let mut c = Checker::new(prog, externs, &src_names)?;
    prog.uses_inout = Some(c.uses_inout); // G5 A0: lets the staging guard skip its walk for inout-free programs
    c.explicit = true;
    c.host_entry = g4.fn_meta.iter().map(|m| m.host_entry).collect();
    c.run(prog)?;
    Ok(c.tt)
}

/// Checks the program, fills in ty for every expression, and returns the type table.
pub fn check(prog: &mut Program) -> Result<TypeTable, PruvError> {
    check_with_externs(prog, &[])
}

/// `check` with the crate names given with --rust-extern (G6: crates a trusted rust fn path may start with besides std).
pub fn check_with_externs(prog: &mut Program, externs: &[String]) -> Result<TypeTable, PruvError> {
    let mut c = Checker::new(prog, externs, &[])?;
    prog.uses_inout = Some(c.uses_inout); // G5 A0: lets the staging guard skip its walk for inout-free programs
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
        Expr::Spent(x) => x.ty = v,
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
        Expr::Move(x) => x.ty = v,
        Expr::InoutArg(x) => x.ty = v,
    }
}

/// G5: does the full syntax of e (every operand, reachable or not) mention the binding `name`?
fn mentions(e: &Expr, name: &str) -> bool {
    match e {
        Expr::Var(x) if x.name == name => return true,
        Expr::Move(x) if x.name == name => return true,
        _ => {}
    }
    crate::refine::kids(e).into_iter().any(|k| mentions(k, name))
}

/// G5: the identity of a call node, for "the call allowed at the statement boundary" (Python `e is s.boundary`).
fn boundary_of(e: &Expr) -> Option<usize> {
    match e {
        Expr::Call(c) => Some(c as *const Call as usize),
        _ => None,
    }
}

/// The instantiation recorded on a node: declaration identity, type arguments, and the substitution ordered by index.
fn inst_of(decl: String, targs: &[GType], m: &Mapping) -> Inst {
    let mut subst: Vec<(String, usize, GType)> = m.iter().map(|((o, i), t)| (o.clone(), *i, t.clone())).collect();
    subst.sort_by(|a, b| (&a.0, a.1).cmp(&(&b.0, b.1)));
    Inst { decl, args: targs.to_vec(), subst, src_args: None }
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
    /// src_names: explicit mode only, the name of each function as written (Python `Function.src_name`); empty otherwise.
    fn new(prog: &Program, externs: &[String], src_names: &[String]) -> Res<Checker> {
        let mut funcs: HashMap<String, Rc<FuncInfo>> = HashMap::new();
        let mut takes: Takes = HashMap::new();
        let uses_inout = program_uses_inout(prog); // G5 A0: enables the contextual builtin `old`
        for (fi, f) in prog.functions.iter().enumerate() {
            let name = f.name.clone();
            if funcs.contains_key(&name) {
                return Err(terr(f.line, f.col, "dup_fn", format!("function {} defined twice", name), ""));
            }
            if matches!(name.as_str(), "len" | "alloc" | "copy" | "print" | "is_char_boundary" | "substr")
                || contract_only(&name).is_some()
                || is_catalog(&name)
            {
                return Err(terr(f.line, f.col, "reserved", format!("{} is a builtin name", name), "rename the function"));
            }
            let written = src_names.get(fi).map(|s| s.as_str()).unwrap_or(name.as_str());
            if uses_inout && written == "old" {
                return Err(terr(
                    f.line,
                    f.col,
                    "reserved",
                    "old is a builtin name in a program that uses inout",
                    "rename the function",
                ));
            }
            takes.insert(name.clone(), f.params.iter().map(|p| p.take).collect());
            funcs.insert(
                name.clone(),
                Rc::new(FuncInfo {
                    src_name: written.to_string(),
                    line: f.line,
                    col: f.col,
                    params: f.params.iter().map(|p| GType::from_key(&p.ty)).collect(),
                    pnames: f.params.iter().map(|p| p.name.clone()).collect(),
                    inout: f.params.iter().map(|p| p.mode_pos.is_some()).collect(),
                    ret: GType::from_key(&f.ret),
                    effects: f.effects.clone(),
                    tparams: f.tparams.clone(),
                    foreign: f.foreign.is_some(),
                }),
            );
        }
        Ok(Checker {
            funcs,
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
            externs: externs.to_vec(),
            takes,
            type_sccs: Vec::new(),
            boxed: Vec::new(),
            boxed_decls: HashSet::new(),
            extended: HashSet::new(),
            buffered: HashSet::new(),
            fn_sccs: Vec::new(),
            call_log: Vec::new(),
            active_roots: Vec::new(),
            cur_cost: false,
            s5_errors: Vec::new(),
            par_groups: Vec::new(),
            explicit: false,
            host_entry: Vec::new(),
            uses_inout,
            ckind: "code",
            boundary: None,
            cur_params: Vec::new(),
        })
    }

    /// If the value is itself an alloc call and the expected type is an array, sets alloc's result type to that array type.
    fn want_alloc(&mut self, value: &Expr, ty: &GType) {
        if let Expr::Call(c) = value {
            if c.name == "alloc" && ty.is_array() {
                self.alloc_want = Some(ty.clone());
            }
        }
    }

    fn run(&mut self, prog: &mut Program) -> Res<()> {
        crate::refine::expand(prog)?; // STAGE1 A: validate refinement annotations, then expand them into contracts/asserts
        self.declare_types(&prog.types)?;
        self.normalize_types(prog); // G6: Vec/HashMap/String become catalog types unless the program declares them
        // `decls` holds clones taken before normalization (Python shares the nodes): refresh them
        for d in &prog.types {
            self.decls.insert(d.name().to_string(), d.clone());
        }
        // likewise the signatures in `funcs` were taken before normalization (Python reads the shared nodes)
        for f in &prog.functions {
            if let Some(info) = self.funcs.get_mut(&f.name) {
                let mut ni = (**info).clone();
                ni.params = f.params.iter().map(|p| GType::from_key(&p.ty)).collect();
                ni.ret = GType::from_key(&f.ret);
                *info = Rc::new(ni);
            }
        }
        self.arg_decls = self.decls.iter().map(|(n, d)| (n.clone(), d.tparams().len())).collect();
        self.check_tparams(prog)?; // G3: type-parameter lists (type_parameter, generic_bound, generic_main)
        self.resolve_types(prog)?;
        self.type_graph(&prog.types)?; // G9 A0: type SCCs, generic/recursive field rules
        self.inhabitance(&prog.types)?; // G9 A0: every declaration needs a finite value
        self.compute_extended(&prog.types);
        self.check_extended_uses(prog)?;
        self.check_modes(prog)?; // G5 A0: parameter modes, before host entries and bodies
        if self.explicit {
            self.check_entries(prog)?; // G4 A0: host-entry signatures
        }
        self.tt = TypeTable::new(&prog.types);
        for f in prog.functions.iter_mut() {
            self.fn_(f)?;
        }
        self.check_fn_sccs(&prog.functions)?; // G9 A0: measures and stable type parameters of recursive call SCCs
        self.check_par_eligibility(&prog.functions)?; // G7 A0: effects, foreign calls, then nested groups
        self.check_costs(prog)?;
        self.record_g9(prog);
        Ok(())
    }

    fn check_costs(&mut self, prog: &mut Program) -> Res<()> {
        for f in &mut prog.functions {
            if let Some(cost) = &mut f.cost {
                self.cur_name = f.name.clone();
                self.cur_ret = GType::from_key(&f.ret);
                self.cur_cost = true;
                self.cur_params = f.params.iter().map(|p| p.name.clone()).collect();
                self.enter(&fn_owner(&f.name), &f.tparams);
                self.ckind = "cost";
                let scope: Scope = f.params.iter().map(|p| (p.name.clone(), Entry {
                    ty: GType::from_key(&p.ty), mutable: false,
                    kind: if p.mode_pos.is_some() { "inout" } else { "param" },
                })).collect();
                let before = self.s5_errors.len();
                let ty = self.expr(cost, &scope, true)?;
                if ty != i64t() && self.s5_errors.len() == before {
                    self.s5_errors.push((f.name.clone(), terr(cost.line(), cost.col(), "cost_type", "cost expression must have type i64", "")));
                }
            }
        }
        if let Some((_, e)) = self.s5_errors.iter().min_by_key(|(name, e)| (
            prog.functions.iter().position(|f| &f.name == name).unwrap(), e.line, e.col)) {
            return Err(e.clone());
        }
        for f in &prog.functions {
            if f.cost.is_none() { continue; }
            let mut calls = Vec::new();
            cost_calls(&f.body, &mut calls);
            calls.sort_by_key(|c| (c.line, c.col));
            for c in calls {
                let callee = prog.functions.iter().find(|f| f.name == c.name);
                if is_catalog(&c.name) || callee.map_or(false, |f| f.foreign.is_some()) {
                    return Err(PruvError::new("effect", c.line, c.col, "cost_unsupported", "cost functions cannot call foreign, catalog or file operations", ""));
                }
                if callee.map_or(false, |f| f.cost.is_none()) {
                    let name = self.funcs.get(&c.name).map(|f| f.src_name.as_str()).filter(|n| !n.is_empty()).unwrap_or(&c.name);
                    return Err(PruvError::new("effect", c.line, c.col, "cost_callee", format!("`{}` has no cost clause, so its work is unbounded here", name), ""));
                }
            }
        }
        Ok(())
    }

    // ---- user type declarations ----
    fn declare_types(&mut self, types: &[TypeDecl]) -> Res<()> {
        for d in types {
            let (name, line, col) = (d.name(), d.line(), d.col());
            // G4: explicit mode checked the names as written (modules::resolve); the identities are not type-name shaped
            if !self.explicit && !type_name_ok(name) {
                return Err(terr(
                    line,
                    col,
                    "type_name",
                    format!("type name {} must start with an upper-case letter", name),
                    format!("rename it, e.g. {}", cap_first(name, true)),
                ));
            }
            if !self.explicit && RESERVED_TYPE_NAMES.contains(&name) {
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

    // ---- G6 A0: collection spellings ----
    /// The parser yields nominal Vec/HashMap/String; map them to the catalog types unless a user type of that name
    /// is declared (an existing user type keeps its meaning).
    fn norm_type(&self, ty: &GType) -> GType {
        if ty.owner.is_some() {
            return ty.clone();
        }
        let args: Vec<GType> = ty.args.iter().map(|a| self.norm_type(a)).collect();
        let mut name = ty.name.clone();
        if !self.decls.contains_key(&name) {
            name = match name.as_str() {
                "Vec" => "vec".to_string(),
                "HashMap" => "hashmap".to_string(),
                "String" => "string".to_string(),
                "File" => "file".to_string(), // G10 A0
                _ => name.clone(),
            };
        }
        if name == ty.name && args == ty.args {
            return ty.clone();
        }
        if args.len() == 1 {
            if name == "array" {
                return mk_array(args[0].clone());
            }
            if name == "option" {
                return mk_option(args[0].clone());
            }
            if name == "result" {
                return mk_result(args[0].clone());
            }
        }
        GType::new(&name, args)
    }

    /// `norm_type` on an AST type key; a key without any of the three spellings is returned unchanged.
    fn norm_key(&self, key: &str) -> String {
        if !(key.contains("Vec") || key.contains("HashMap") || key.contains("String") || key.contains("File")) {
            return key.to_string();
        }
        self.norm_type(&GType::from_key(key)).to_key()
    }

    fn normalize_types(&self, prog: &mut Program) {
        for d in prog.types.iter_mut() {
            match d {
                TypeDecl::Struct(s) => {
                    for fd in s.fields.iter_mut() {
                        fd.ty = self.norm_key(&fd.ty);
                    }
                }
                TypeDecl::Enum(e) => {
                    for v in e.variants.iter_mut() {
                        for fd in v.fields.iter_mut() {
                            fd.ty = self.norm_key(&fd.ty);
                        }
                    }
                }
            }
        }
        for f in prog.functions.iter_mut() {
            for p in f.params.iter_mut() {
                p.ty = self.norm_key(&p.ty);
            }
            f.ret = self.norm_key(&f.ret);
            for e in f.requires.iter_mut() {
                self.norm_expr(e);
            }
            for e in f.ensures.iter_mut() {
                self.norm_expr(e);
            }
            if let Some(d) = f.cost.as_mut() { self.norm_expr(d); }
            if let Some(d) = f.decreases.as_mut() {
                self.norm_expr(d); // G9 A0
            }
            self.norm_stmts(&mut f.body);
        }
    }

    fn norm_targs(&self, targs: &mut Option<Vec<GType>>) {
        if let Some(v) = targs {
            *v = v.iter().map(|t| self.norm_type(t)).collect();
        }
    }

    fn norm_stmts(&self, stmts: &mut [Stmt]) {
        for st in stmts.iter_mut() {
            match st {
                Stmt::Let(s) => {
                    s.ty = self.norm_key(&s.ty);
                    self.norm_expr(&mut s.value);
                }
                Stmt::Assign(s) => self.norm_expr(&mut s.value),
                Stmt::FieldAssign(s) => self.norm_expr(&mut s.value),
                Stmt::Return(s) => {
                    if let Some(v) = s.value.as_mut() {
                        self.norm_expr(v);
                    }
                }
                Stmt::IndexAssign(s) => {
                    self.norm_expr(&mut s.index);
                    self.norm_expr(&mut s.value);
                }
                Stmt::If(s) => {
                    self.norm_expr(&mut s.cond);
                    self.norm_stmts(&mut s.then);
                    self.norm_stmts(&mut s.els);
                }
                Stmt::While(s) => {
                    self.norm_expr(&mut s.cond);
                    for i in s.invariants.iter_mut() {
                        self.norm_expr(i);
                    }
                    self.norm_expr(&mut s.decreases);
                    self.norm_stmts(&mut s.body);
                }
                Stmt::Assert(s) => self.norm_expr(&mut s.cond),
                Stmt::Par(s) => {
                    for c in &mut s.calls {
                        self.norm_expr(c);
                    }
                }
                Stmt::ExprStmt(s) => self.norm_expr(&mut s.expr),
                Stmt::Match(s) => {
                    self.norm_expr(&mut s.scrutinee);
                    for a in s.arms.iter_mut() {
                        self.norm_stmts(&mut a.body);
                    }
                }
            }
        }
    }

    /// Explicit type arguments (`f::<..>`, `S::<..> {..}`, `E::<..>::V(..)`, `Some::<..>(..)`) of an expression tree.
    fn norm_expr(&self, e: &mut Expr) {
        match e {
            Expr::Call(x) => {
                self.norm_targs(&mut x.targs);
                for a in x.args.iter_mut() {
                    self.norm_expr(a);
                }
            }
            Expr::Ctor(x) => {
                self.norm_targs(&mut x.targs);
                if let Some(a) = x.arg.as_mut() {
                    self.norm_expr(a);
                }
            }
            Expr::StructLit(x) => {
                self.norm_targs(&mut x.targs);
                for f in x.fields.iter_mut() {
                    self.norm_expr(&mut f.value);
                }
            }
            Expr::EnumCtor(x) => {
                self.norm_targs(&mut x.targs);
                for a in x.args.iter_mut() {
                    self.norm_expr(a);
                }
            }
            Expr::Unary(x) => self.norm_expr(&mut x.operand),
            Expr::Binary(x) => {
                self.norm_expr(&mut x.left);
                self.norm_expr(&mut x.right);
            }
            Expr::Index(x) => {
                self.norm_expr(&mut x.array);
                self.norm_expr(&mut x.index);
            }
            Expr::Quant(x) => {
                self.norm_expr(&mut x.lo);
                self.norm_expr(&mut x.hi);
                self.norm_expr(&mut x.body);
            }
            Expr::FieldAccess(x) => self.norm_expr(&mut x.base),
            Expr::IsVariant(x) => self.norm_expr(&mut x.value),
            Expr::VariantField(x) => self.norm_expr(&mut x.value),
            Expr::InoutArg(x) => self.norm_expr(&mut x.expr), // G5 A0
            Expr::Spent(_) | Expr::IntLit(_) | Expr::BoolLit(_) | Expr::StrLit(_) | Expr::Var(_) | Expr::Move(_) => {}
        }
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
            let tps = &f.tparams;
            if f.name == "main" && !tps.is_empty() {
                return Err(terr(
                    f.line,
                    f.col,
                    "generic_main",
                    "main cannot declare type parameters",
                    "make main a plain function; call generic functions from it with explicit type arguments",
                ));
            }
            self.tparam_list(tps)?;
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
        if collection_arity(&ty.name).is_some() {
            // G6: Vec<T>, HashMap<K, V>, String
            for a in &ty.args {
                self.check_type_rec(line, col, a)?;
            }
            if ty.name == "vec" && ty.args.len() == 1 {
                self.collection_payload(line, col, &ty.args[0], "a Vec element")?;
            } else if ty.name == "hashmap" && ty.args.len() == 2 {
                let k = &ty.args[0];
                if k.contains_collection() || !is_element(k, &self.elem_params) {
                    return Err(terr(
                        line,
                        col,
                        "foreign_owned_type",
                        format!("{} cannot be a HashMap key: only i64, bool and Element type parameters can", tn(k)),
                        "use i64 or bool keys, or declare the parameter `: Element`",
                    ));
                }
                self.collection_payload(line, col, &ty.args[1], "a HashMap value")?;
            }
            return Ok(());
        }
        if ty.name == "array" {
            if !ty.args.is_empty() {
                // [X] for X other than i64/u8/bool
                let el = &ty.args[0];
                self.check_type_rec(line, col, el)?;
                if el.contains_collection() {
                    return Err(terr(
                        line,
                        col,
                        "foreign_owned_type",
                        format!("an array cannot hold the collection type {}", tn(el)),
                        "arrays hold i64, bool or an Element type parameter",
                    ));
                }
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

    /// G6: a collection payload is a plain G3 value (never another collection).
    fn collection_payload(&self, line: i64, col: i64, a: &GType, what: &str) -> Res<()> {
        if a.contains_collection() {
            return Err(terr(
                line,
                col,
                "foreign_owned_type",
                format!("{} cannot be the collection type {}", what, tn(a)),
                "collection payloads are plain values; keep every collection in its own binding",
            ));
        }
        let ad = &self.arg_decls;
        let look = |n: &str| ad.get(n).map(|k| (*k, Vec::<GType>::new()));
        if !is_value(a, &look) {
            return Err(terr(
                line,
                col,
                "foreign_owned_type",
                format!(
                    "{} cannot have type {}: only i64, bool, Option, Result, structs, enums and type parameters can",
                    what,
                    tn(a)
                ),
                "arrays, str and () cannot be collection payloads",
            ));
        }
        Ok(())
    }

    /// a: a type argument; tp: the TypeParam it instantiates (None for Option/Result).
    fn check_arg(&self, line: i64, col: i64, a: &GType, tp: Option<&TParam>) -> Res<()> {
        self.check_type_rec(line, col, a)?;
        if a.contains_collection() {
            // G6: collections are never type arguments of Option/Result/user declarations
            return Err(terr(
                line,
                col,
                "foreign_owned_type",
                format!("{} cannot be a type argument", tn(a)),
                "keep collections in their own bindings; Vec<T> and HashMap<K, V> are the only places they appear",
            ));
        }
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
            self.ext_misuse(line, col, a, Some("arg"))?; // G9 A0: extended types are never type arguments
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
                    if !d.tparams().is_empty() && (ft.is_array() || ft == strt()) {
                        // G9 A0
                        return Err(terr(
                            f.line,
                            f.col,
                            "field_type",
                            format!("generic type {} cannot have the array/str field {}", d.name(), f.name),
                            "use a dedicated non-generic declaration",
                        ));
                    }
                    if ft == unitt()
                        || (ft.is_array() && ft != GType::array() && ft != GType::array_u8() && ft != GType::array_bool())
                    {
                        return Err(terr(
                            f.line,
                            f.col,
                            "field_type",
                            format!("field {} cannot have type {}", f.name, tn(&ft)),
                            "fields are i64, bool, Option<i64>, Result<i64> or a user struct/enum",
                        ));
                    }
                    self.check_type(f.line, f.col, &ft)?;
                    if ft.contains_collection() {
                        return Err(terr(
                            f.line,
                            f.col,
                            "foreign_owned_type",
                            format!("field {} cannot have the collection type {}", f.name, tn(&ft)),
                            "collections cannot be struct fields or enum payloads; pass them as separate bindings",
                        ));
                    }
                }
            }
        }
        for f in &prog.functions {
            self.enter(&fn_owner(&f.name), &f.tparams);
            for p in &f.params {
                self.check_type(f.line, f.col, &GType::from_key(&p.ty))?;
            }
            self.check_type(f.line, f.col, &GType::from_key(&f.ret))?;
        }
        Ok(())
    }

    // ---- G9 A0: type graph, inhabitance, extended types ----
    /// A declared user type written without type arguments.
    fn is_plain_nominal(&self, ty: &GType) -> bool {
        ty.owner.is_none()
            && ty.args.is_empty()
            && self.decls.contains_key(&ty.name)
            && !BUILTIN_TYPE_NAMES.contains(&ty.name.as_str())
    }

    fn type_graph(&mut self, types: &[TypeDecl]) -> Res<()> {
        let mut index: HashMap<&str, usize> = HashMap::new();
        for (i, d) in types.iter().enumerate() {
            index.entry(d.name()).or_insert(i);
        }
        let mut adj: Vec<Vec<usize>> = vec![Vec::new(); types.len()];
        for (i, d) in types.iter().enumerate() {
            for (_, fd) in decl_fields(d) {
                // G3: nested type arguments count
                for n in dependencies(&GType::from_key(&fd.ty)) {
                    if let Some(&j) = index.get(n.as_str()) {
                        if !adj[i].contains(&j) {
                            adj[i].push(j);
                        }
                    }
                }
            }
        }
        for comp in sccs(types.len(), &adj) {
            if !(comp.len() > 1 || adj[comp[0]].contains(&comp[0])) {
                continue;
            }
            let names: Vec<String> = comp.iter().map(|&i| types[i].name().to_string()).collect();
            let members: HashSet<&str> = names.iter().map(|n| n.as_str()).collect();
            self.type_sccs.push(names.clone());
            // (a) generic declarations cannot be recursive
            for &i in &comp {
                let d = &types[i];
                if !d.tparams().is_empty() {
                    let cyc: Vec<&str> = cycle_through(i, &adj, &comp).iter().map(|&k| types[k].name()).collect();
                    return Err(terr(
                        d.line(),
                        d.col(),
                        "recursive_generic_type",
                        format!("generic type {} cannot be recursive (cycle: {})", d.name(), cyc.join(" -> ")),
                        "recursive types must be non-generic; write a dedicated enum for the element type",
                    ));
                }
            }
            // (b) intra-SCC fields must be direct nominal fields (these are the boxed edges)
            for &i in &comp {
                let d = &types[i];
                for (vname, fd) in decl_fields(d) {
                    let ft = GType::from_key(&fd.ty);
                    if !dependencies(&ft).iter().any(|n| members.contains(n.as_str())) {
                        continue;
                    }
                    if !(self.is_plain_nominal(&ft) && members.contains(ft.name.as_str())) {
                        return Err(terr(
                            fd.line,
                            fd.col,
                            "recursive_type",
                            format!("recursive field {} must have the type itself, not hide it inside {}", fd.name, tn(&ft)),
                            "use a direct field of a dedicated non-generic type",
                        ));
                    }
                    self.boxed.push(field_label(d.name(), vname, &fd.name));
                    self.boxed_decls.insert((d.name().to_string(), vname.map(|v| v.to_string())));
                }
            }
        }
        Ok(())
    }

    fn inhabitance(&self, types: &[TypeDecl]) -> Res<()> {
        let mut marked: HashSet<String> = HashSet::new();
        // worklist: per struct / per variant count of fields whose type is not yet inhabited
        let mut counts: Vec<Vec<usize>> = Vec::with_capacity(types.len());
        let mut rev: HashMap<String, Vec<(usize, usize)>> = HashMap::new(); // type name -> (decl, unit), one per dependent field
        let mut queue: Vec<usize> = Vec::new();
        for (i, d) in types.iter().enumerate() {
            let units: Vec<&Vec<FieldDecl>> = match d {
                TypeDecl::Struct(s) => vec![&s.fields],
                TypeDecl::Enum(e) => e.variants.iter().map(|v| &v.fields).collect(),
            };
            let mut cs: Vec<usize> = Vec::with_capacity(units.len());
            for (u, fields) in units.iter().enumerate() {
                let mut c = 0usize;
                for fd in fields.iter() {
                    let t = GType::from_key(&fd.ty);
                    if self.is_plain_nominal(&t) {
                        c += 1;
                        rev.entry(t.name.clone()).or_default().push((i, u));
                    }
                }
                cs.push(c);
            }
            if cs.iter().any(|&c| c == 0) {
                queue.push(i);
            }
            counts.push(cs);
        }
        while let Some(i) = queue.pop() {
            let name = types[i].name();
            if marked.contains(name) {
                continue;
            }
            marked.insert(name.to_string());
            if let Some(deps) = rev.get(name) {
                for &(j, u) in deps {
                    counts[j][u] -= 1;
                    if counts[j][u] == 0 && !marked.contains(types[j].name()) {
                        queue.push(j);
                    }
                }
            }
        }
        for d in types {
            if marked.contains(d.name()) {
                continue;
            }
            let mut path: Vec<String> = vec![d.name().to_string()];
            let mut cur: &TypeDecl = d;
            loop {
                let mut nxt: Option<String> = None;
                for (_, fd) in decl_fields(cur) {
                    let t = GType::from_key(&fd.ty);
                    if self.is_plain_nominal(&t) && !marked.contains(&t.name) {
                        nxt = Some(t.name.clone());
                        break;
                    }
                }
                let nxt = match nxt {
                    Some(n) => n,
                    None => break,
                };
                path.push(nxt.clone());
                if path.iter().position(|p| *p == nxt) != Some(path.len() - 1) {
                    break;
                }
                cur = match self.decls.get(&nxt) {
                    Some(c) => c,
                    None => break,
                };
            }
            return Err(terr(
                d.line(),
                d.col(),
                "recursive_type",
                format!("recursive type has no finite value: {}", path.join(" -> ")),
                "add a variant without recursive fields (a base case such as `Empty`)",
            ));
        }
        Ok(())
    }

    /// extended = recursive, or with a buffer field, or with a field mentioning an extended declaration;
    /// buffered = with a buffer field directly or through nested declarations.
    fn compute_extended(&mut self, types: &[TypeDecl]) {
        let rec: HashSet<String> = self.type_sccs.iter().flat_map(|names| names.iter().cloned()).collect();
        let mut direct: HashSet<String> = HashSet::new();
        for d in types {
            if decl_fields(d).iter().any(|(_, fd)| {
                let t = GType::from_key(&fd.ty);
                t.is_array() || t == strt()
            }) {
                direct.insert(d.name().to_string());
            }
        }
        let mut ext: HashSet<String> = rec.union(&direct).cloned().collect();
        let mut buf: HashSet<String> = direct.clone();
        // reverse dependency edges built once: mentioned name -> declaration names mentioning it
        let mut rev: HashMap<String, Vec<String>> = HashMap::new();
        for d in types {
            let mut mentioned: HashSet<String> = HashSet::new();
            for (_, fd) in decl_fields(d) {
                mentioned.extend(dependencies(&GType::from_key(&fd.ty)));
            }
            for n in mentioned {
                rev.entry(n).or_default().push(d.name().to_string());
            }
        }
        for marked in [&mut ext, &mut buf] {
            let mut queue: Vec<String> = marked.iter().cloned().collect();
            while let Some(n) = queue.pop() {
                if let Some(ms) = rev.get(&n) {
                    for m in ms {
                        if marked.insert(m.clone()) {
                            queue.push(m.clone());
                        }
                    }
                }
            }
        }
        self.extended = ext;
        self.buffered = buf;
    }

    fn is_extended(&self, ty: &GType) -> bool {
        ty.owner.is_none() && ty.args.is_empty() && self.extended.contains(&ty.name)
    }

    /// An extended type may not be a type argument (type_argument) or a G6 collection payload (foreign_owned_type).
    fn ext_misuse(&self, line: i64, col: i64, ty: &GType, inside: Option<&str>) -> Res<()> {
        if ty.owner.is_some() {
            return Ok(());
        }
        if ty.is_collection() {
            for a in &ty.args {
                self.ext_misuse(line, col, a, Some("coll"))?;
            }
            return Ok(());
        }
        if self.extended.contains(&ty.name) && ty.args.is_empty() && self.decls.contains_key(&ty.name) {
            if inside == Some("coll") {
                return Err(terr(
                    line,
                    col,
                    "foreign_owned_type",
                    format!("{} cannot be a Vec or HashMap element: it is recursive or holds an array/str", tn(ty)),
                    "keep extended values in their own bindings",
                ));
            }
            if inside == Some("arg") {
                return Err(terr(
                    line,
                    col,
                    "type_argument",
                    format!(
                        "{} cannot be a type argument or an Option/Result payload: it is recursive or holds an array/str",
                        tn(ty)
                    ),
                    "use a dedicated non-generic enum instead",
                ));
            }
            return Ok(());
        }
        let next = if inside == Some("coll") { "coll" } else { "arg" };
        for a in &ty.args {
            self.ext_misuse(line, col, a, Some(next))?;
        }
        Ok(())
    }

    fn check_extended_uses(&self, prog: &Program) -> Res<()> {
        for d in &prog.types {
            for (_, fd) in decl_fields(d) {
                let ft = GType::from_key(&fd.ty);
                if !d.tparams().is_empty() {
                    let hit: Vec<String> = dependencies(&ft).into_iter().filter(|n| self.extended.contains(n)).collect();
                    if let Some(first) = hit.first() {
                        return Err(terr(
                            fd.line,
                            fd.col,
                            "field_type",
                            format!(
                                "generic type {} cannot have the field {} of the extended type {}",
                                d.name(),
                                fd.name,
                                first
                            ),
                            "use a dedicated non-generic declaration",
                        ));
                    }
                }
                self.ext_misuse(fd.line, fd.col, &ft, None)?;
            }
        }
        for f in &prog.functions {
            for p in &f.params {
                self.ext_misuse(f.line, f.col, &GType::from_key(&p.ty), None)?;
            }
            self.ext_misuse(f.line, f.col, &GType::from_key(&f.ret), None)?;
        }
        Ok(())
    }

    /// G5 A0: an inout parameter must be a primitive or Element-generic array ([i64], [u8], [bool], [T: Element]).
    fn check_modes(&self, prog: &Program) -> Res<()> {
        for f in &prog.functions {
            for p in &f.params {
                if let Some((ml, mc)) = p.mode_pos {
                    let pt = GType::from_key(&p.ty);
                    if !pt.is_array() {
                        return Err(terr(
                            ml,
                            mc,
                            "inout_type",
                            format!(
                                "inout parameter {} cannot have the type {}: only [i64], [u8], [bool] and [T] with T: Element can be inout",
                                p.name,
                                tn(&pt)
                            ),
                            format!("declare {} without inout, or give it one of those array types", p.name),
                        ));
                    }
                }
            }
        }
        Ok(())
    }

    /// G4 A0 (explicit mode): a host entry (root `pub`, nongeneric, ordinary function) may not have a collection or an extended
    /// (G9) type in its signature; child `pub` functions and generic functions are not host entries.
    /// G5 A0: it may not have an inout parameter either.
    fn check_entries(&self, prog: &Program) -> Res<()> {
        for (i, f) in prog.functions.iter().enumerate() {
            if !self.host_entry.get(i).copied().unwrap_or(false) {
                continue;
            }
            for p in &f.params {
                if let Some((ml, mc)) = p.mode_pos {
                    return Err(terr(
                        ml,
                        mc,
                        "entry_signature",
                        format!("host entry {} cannot have the inout parameter {}", f.name, p.name),
                        format!(
                            "make {} private or child `pub` and expose a root wrapper that copies the input into a `let mut` local",
                            f.name
                        ),
                    ));
                }
            }
            let mut sig: Vec<(String, &str)> = f.params.iter().map(|p| (format!("parameter {}", p.name), p.ty.as_str())).collect();
            sig.push(("the result".to_string(), f.ret.as_str()));
            for (what, key) in sig {
                let ty = GType::from_key(key);
                if ty.contains_collection() || dependencies(&ty).iter().any(|n| self.extended.contains(n)) {
                    return Err(terr(
                        f.line,
                        f.col,
                        "entry_signature",
                        format!("host entry {} cannot have the type {} in {}", f.name, tn(&ty), what),
                        "keep it Pruv-callable (child `pub` or private) and expose a scalar/value wrapper at the root",
                    ));
                }
            }
        }
        Ok(())
    }

    fn check_fn_sccs(&mut self, functions: &[Function]) -> Res<()> {
        let mut found: Vec<Vec<String>> = Vec::new();
        let names: Vec<&str> = functions.iter().map(|f| f.name.as_str()).collect();
        let mut index: HashMap<&str, usize> = HashMap::new();
        for (i, n) in names.iter().enumerate() {
            index.insert(*n, i);
        }
        let mut adj: Vec<Vec<usize>> = vec![Vec::new(); names.len()];
        for (caller, _, _, _, callee) in &self.call_log {
            if let (Some(&i), Some(&j)) = (index.get(caller.as_str()), index.get(callee.as_str())) {
                if !adj[i].contains(&j) {
                    adj[i].push(j);
                }
            }
        }
        let comps: Vec<Vec<usize>> =
            sccs(names.len(), &adj).into_iter().filter(|comp| comp.len() > 1 || adj[comp[0]].contains(&comp[0])).collect();
        // bucket the call log once per recursive SCC, keeping the original relative order
        let mut scc_of: HashMap<usize, usize> = HashMap::new();
        for (k, comp) in comps.iter().enumerate() {
            for &i in comp {
                scc_of.insert(i, k);
            }
        }
        type Edge<'a> = (usize, i64, i64, &'a Option<Vec<GType>>, usize);
        let mut buckets: Vec<Vec<Edge>> = vec![Vec::new(); comps.len()];
        for (caller, line, col, targs, callee) in &self.call_log {
            if let (Some(&ci), Some(&ce)) = (index.get(caller.as_str()), index.get(callee.as_str())) {
                if let (Some(&a), Some(&b)) = (scc_of.get(&ci), scc_of.get(&ce)) {
                    if a == b {
                        buckets[a].push((ci, *line, *col, targs, ce));
                    }
                }
            }
        }
        for (comp, bucket) in comps.into_iter().zip(buckets.into_iter()) {
            found.push(comp.iter().map(|&i| names[i].to_string()).collect());
            for &i in &comp {
                let f = &functions[i];
                if f.decreases.is_none() {
                    let cyc: Vec<&str> = cycle_through(i, &adj, &comp).iter().map(|&k| names[k]).collect();
                    return Err(terr(
                        f.line,
                        f.col,
                        "recursive_decreases",
                        format!("recursive function {} needs a decreases clause (cycle: {})", f.name, cyc.join(" -> ")),
                        "add `decreases <expr>` after requires/ensures, e.g. `decreases n`",
                    ));
                }
            }
            // (caller index, call line, call col, call targs, callee index), stable-sorted by (caller, line, col)
            let mut edges = bucket;
            edges.sort_by(|a, b| (a.0, a.1, a.2).cmp(&(b.0, b.1, b.2)));
            for (ci, line, col, targs, ce) in edges {
                let caller = &functions[ci];
                let callee = &functions[ce];
                let mut ok = caller.tparams.len() == callee.tparams.len()
                    && caller.tparams.iter().zip(callee.tparams.iter()).all(|(a, b)| a.bound == b.bound);
                if ok {
                    let empty: Vec<GType> = Vec::new();
                    let ta: &Vec<GType> = targs.as_ref().unwrap_or(&empty);
                    let owner = fn_owner(&caller.name);
                    ok = ta.len() == caller.tparams.len()
                        && ta
                            .iter()
                            .enumerate()
                            .all(|(k, t)| t.owner.as_deref() == Some(owner.as_str()) && t.index == k && t.args.is_empty());
                }
                if !ok {
                    let tp_names: Vec<&str> = caller.tparams.iter().map(|tp| tp.name.as_str()).collect();
                    return Err(terr(
                        line,
                        col,
                        "recursive_polymorphism",
                        format!(
                            "recursive call to {} must pass the type parameters <{}> unchanged",
                            callee.name,
                            tp_names.join(", ")
                        ),
                        "call with ::<T, ...> in the same order",
                    ));
                }
            }
        }
        self.fn_sccs = found;
        Ok(())
    }

    /// G9 A0: the metadata on the program and the type table, only when a G9 feature is present.
    fn record_g9(&mut self, prog: &mut Program) {
        if self.type_sccs.is_empty()
            && self.extended.is_empty()
            && self.fn_sccs.is_empty()
            && !prog.functions.iter().any(|f| f.decreases.is_some())
        {
            return;
        }
        let meta = G9Meta {
            type_sccs: self.type_sccs.clone(),
            boxed: self.boxed.clone(),
            extended: prog.types.iter().filter(|d| self.extended.contains(d.name())).map(|d| d.name().to_string()).collect(),
            fn_sccs: self.fn_sccs.clone(),
        };
        prog.g9 = Some(meta.clone());
        self.tt.g9 = Some(meta);
    }

    // ---- functions ----
    fn fn_(&mut self, f: &mut Function) -> Res<()> {
        let fname = f.name.clone();
        let ret = GType::from_key(&f.ret);
        self.enter(&fn_owner(&fname), &f.tparams);
        self.cur_name = fname.clone();
        self.cur_ret = ret.clone();
        self.cur_cost = f.cost.is_some();
        self.cur_params = f.params.iter().map(|p| p.name.clone()).collect();
        if f.foreign.is_some() {
            check_foreign_decl(f, &self.externs)?; // G6: signature, then path of a trusted rust fn
            if let Some(d) = &f.decreases {
                // G9 A0: foreign termination is trusted
                return Err(terr(
                    d.line(),
                    d.col(),
                    "recursive_decreases",
                    "a trusted rust fn cannot have a decreases clause",
                    "remove it; foreign termination is trusted",
                ));
            }
        } else if fname == "main" && (ret.is_collection() || f.params.iter().any(|p| key_is_collection(&p.ty))) {
            return Err(terr(
                f.line,
                f.col,
                "foreign_export",
                "main cannot have a collection parameter or result",
                "give main plain value parameters and result; use collections inside it",
            ));
        }
        let mut scope: Scope = HashMap::new();
        for p in &f.params {
            if scope.contains_key(&p.name) {
                return Err(terr(f.line, f.col, "dup_param", format!("duplicate parameter {}", p.name), ""));
            }
            let pt = GType::from_key(&p.ty);
            if pt == unitt() {
                return Err(terr(f.line, f.col, "unit_param", format!("parameter {} cannot have type ()", p.name), ""));
            }
            if p.take && !pt.is_collection() {
                return Err(terr(
                    f.line,
                    f.col,
                    "foreign_move",
                    "take is only for collection parameters",
                    format!("remove `take` from {}; scalars, arrays and str are passed by value or borrowed", p.name),
                ));
            }
            // G5 A0: an inout parameter allows element stores but, like every parameter, never whole reassignment
            let kind = if p.mode_pos.is_some() { "inout" } else { "param" };
            scope.insert(p.name.clone(), Entry { ty: pt, mutable: false, kind });
        }
        self.used_effects = BTreeSet::new();
        self.ckind = "requires";
        for r in f.requires.iter_mut() {
            self.expect(r, &boolt(), &scope, true, None)?;
        }
        let mut escope = scope.clone();
        if ret != unitt() {
            escope.insert("result".to_string(), Entry { ty: ret.clone(), mutable: false, kind: "result" });
        }
        self.ckind = "ensures";
        for e in f.ensures.iter_mut() {
            self.expect(e, &boolt(), &escope, true, None)?;
        }
        self.ckind = "decreases";
        if let Some(d) = f.decreases.as_mut() {
            // G9 A0: scalar measure over the parameters only (no result)
            self.expect(d, &i64t(), &scope, true, None)?;
        }
        self.ckind = "code";
        if f.foreign.is_some() {
            if ret.is_collection() && !f.effects.iter().any(|e| e == "alloc") {
                // G6b: an owned result allocates
                let mut all: BTreeSet<String> = f.effects.iter().cloned().collect();
                all.insert("alloc".to_string());
                let joined = all.into_iter().collect::<Vec<_>>().join(", ");
                return Err(PruvError::new(
                    "effect",
                    f.line,
                    f.col,
                    "missing_effect",
                    format!("trusted rust fn {} returns {} and must declare `alloc`", fname, format_type(&ret)),
                    format!("add `! {}` after the return type", joined),
                ));
            }
            return Ok(()); // a trusted rust fn has no body to check
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
        check_ownership(f, &self.takes)?; // G6: liveness of collection bindings (after typing)
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
        self.ckind = "code";
        self.boundary = None; // G5: only the statements below that allow a mutating call set it
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
                self.ext_misuse(s.line, s.col, &sty, None)?; // G9 A0
                self.boundary = boundary_of(&s.value);
                self.want_alloc(&s.value, &sty);
                self.expect(&mut s.value, &sty, scope, false, None)?;
                if sty.is_array() || sty == strt() {
                    self.array_source(s.line, s.col, &s.value, scope, false, &sty)?;
                }
                self.own(&s.value);
                scope.insert(s.name.clone(), Entry { ty: sty, mutable: s.mutable, kind: "local" });
            }
            Stmt::Assign(s) => {
                let v = self.lookup(s.line, s.col, &s.name, scope)?;
                self.check_borrow(s.line, s.col, &s.name, &[])?; // G9 A0
                if !v.mutable {
                    if v.kind == "inout" {
                        // G5 A0: element stores are allowed, replacing the binding is not
                        return Err(terr(
                            s.line,
                            s.col,
                            "immutable",
                            format!("inout parameter {} cannot be reassigned as a whole", s.name),
                            format!("store elements with {}[i] = v, or copy into a `let mut` local", s.name),
                        ));
                    }
                    return Err(terr(s.line, s.col, "immutable", format!("{} is not mutable", s.name), Self::immutable_fix(v.kind)));
                }
                self.boundary = boundary_of(&s.value);
                self.want_alloc(&s.value, &v.ty);
                self.expect(&mut s.value, &v.ty, scope, false, None)?;
                if v.ty.is_array() || v.ty == strt() {
                    self.array_source(s.line, s.col, &s.value, scope, false, &v.ty)?;
                }
                self.own(&s.value);
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
                if !v.mutable && v.kind != "inout" {
                    // G5 A0: an inout parameter permits element stores
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
                self.check_borrow(s.line, s.col, &s.name, &s.fields)?; // G9 A0
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
                if cur.is_array() || cur == strt() {
                    // G9 A0: G2 explicit ownership for a buffer field
                    self.array_source(s.line, s.col, &s.value, scope, false, &cur)?;
                }
                self.own(&s.value);
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
                self.ckind = "invariant";
                for i in s.invariants.iter_mut() {
                    self.expect(i, &boolt(), scope, true, None)?;
                }
                self.ckind = "decreases";
                self.expect(&mut s.decreases, &i64t(), scope, true, None)?;
                self.ckind = "code";
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
                        self.boundary = boundary_of(v);
                        self.want_alloc(v, &ret);
                        self.expect(v, &ret, scope, false, None)?;
                        if ret.is_array() || ret == strt() {
                            self.array_source(s.line, s.col, v, scope, true, &ret)?;
                        }
                        self.own(v);
                    }
                }
            }
            Stmt::Assert(s) => {
                self.ckind = "assert";
                self.expect(&mut s.cond, &boolt(), scope, true, None)?;
                self.ckind = "code";
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
                self.boundary = boundary_of(&s.expr);
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
            Stmt::Par(p) => self.par(p, scope)?,
            Stmt::Match(m) => self.match_stmt(m, scope)?,
        }
        Ok(())
    }

    // G7: preserve Python's validation order and source-order alias witnesses.
    fn par(&mut self, p: &mut Par, scope: &Scope) -> Res<()> {
        if p.calls.len() < 2 {
            return Err(terr(p.line, p.col, "parallel_arity",
                format!("a par group needs at least two branch calls, found {}", p.calls.len()),
                "write a single ordinary call instead of a par group"));
        }
        for e in &p.calls {
            self.par_target(e)?;
        }
        for e in &mut p.calls {
            self.ckind = "code";
            self.boundary = boundary_of(e);
            self.expr(e, scope, false)?;
        }
        self.boundary = None;
        for e in &p.calls {
            self.par_args(e)?;
        }
        Self::par_overlap(&p.calls)?;
        self.par_groups.push(p.calls.clone());
        Ok(())
    }

    fn par_target(&self, e: &Expr) -> Res<()> {
        let c = match e {
            Expr::Call(c) => c,
            _ => return Err(terr(e.line(), e.col(), "parallel_call",
                "a par branch must be a call to a Pruv function",
                "call a unit Pruv helper that takes the arrays as inout parameters")),
        };
        let n = &c.name;
        if let Some(f) = self.funcs.get(n) {
            if f.foreign {
                return Err(terr(c.line, c.col, "parallel_call",
                    format!("{} is a trusted rust fn: it cannot be a par branch", n),
                    "call a unit Pruv helper, and keep trusted rust fns outside the par group"));
            }
            if f.ret != unitt() {
                return Err(terr(c.line, c.col, "parallel_call",
                    format!("{} returns {}: a par branch must return ()", n, tn(&f.ret)),
                    "call a unit Pruv helper and pass results back through whole inout arrays"));
            }
        } else if ["len", "alloc", "copy", "print", "is_char_boundary", "substr"].contains(&n.as_str())
            || contract_only(n).is_some() || is_catalog(n) || (n == "old" && self.uses_inout)
        {
            return Err(terr(c.line, c.col, "parallel_call",
                format!("{} is a builtin or catalog operation: it cannot be a par branch", n),
                "call a unit Pruv helper that performs the operation"));
        }
        Ok(())
    }

    fn par_type_ok(&self, t: &GType) -> bool {
        is_element(t, &self.elem_params)
            || matches!(t.to_key().as_str(), "array" | "array_u8" | "array_bool")
            || (t.name == "array" && t.args.len() == 1
                && t.args[0].owner.is_some() && is_element(&t.args[0], &self.elem_params))
    }

    fn par_args(&self, e: &Expr) -> Res<()> {
        if let Expr::Call(c) = e {
            for arg in &c.args {
                if !matches!(arg, Expr::InoutArg(_) | Expr::Var(_) | Expr::IntLit(_) | Expr::BoolLit(_)) {
                    return Err(terr(arg.line(), arg.col(), "parallel_argument",
                        "a par branch argument must be a binding name, an integer or bool literal, or `inout name`",
                        "bind the value before the group, e.g. `let n: i64 = len(a);`, and pass n"));
                }
                let t = expr_ty(arg).as_ref().map(|k| GType::from_key(k));
                if !t.as_ref().map_or(false, |t| self.par_type_ok(t)) {
                    return Err(terr(arg.line(), arg.col(), "parallel_argument",
                        format!("an argument of type {} cannot cross a par branch boundary",
                            t.as_ref().map(tn).unwrap_or("?".into())),
                        "bind a scalar first, or pass whole [i64], [u8] or [bool] arrays"));
                }
            }
        }
        Ok(())
    }

    fn par_overlap(calls: &[Expr]) -> Res<()> {
        // Vectors preserve Python dict insertion order and the first operand at each binding.
        let sets: Vec<_> = calls.iter().map(|e| {
            let mut w: Vec<(&str, &Expr)> = Vec::new();
            let mut r: Vec<(&str, &Expr)> = Vec::new();
            if let Expr::Call(c) = e {
                for a in &c.args {
                    match a {
                        Expr::InoutArg(x) => if let Expr::Var(v) = x.expr.as_ref() {
                            if !w.iter().any(|(n, _)| *n == v.name) {
                                w.push((&v.name, a));
                            }
                        },
                        Expr::Var(v) if v.ty.as_ref().map_or(false, |k| GType::from_key(k).is_array()) => {
                            if !r.iter().any(|(n, _)| *n == v.name) {
                                r.push((&v.name, a));
                            }
                        }
                        _ => {}
                    }
                }
            }
            (w, r)
        }).collect();
        for j in 1..sets.len() {
            for i in 0..j {
                for (name, node) in &sets[j].0 {
                    for (set, theirs) in [(&sets[i].0, "also writes"), (&sets[i].1, "reads")] {
                        if set.iter().any(|(n, _)| n == name) {
                            return Err(Self::par_alias(node, name, j, i, "writes", theirs));
                        }
                    }
                }
                for (name, node) in &sets[j].1 {
                    if sets[i].0.iter().any(|(n, _)| n == name) {
                        return Err(Self::par_alias(node, name, j, i, "reads", "writes"));
                    }
                }
            }
        }
        Ok(())
    }

    fn par_alias(node: &Expr, name: &str, j: usize, i: usize, mine: &str, theirs: &str) -> PruvError {
        terr(node.line(), node.col(), "parallel_alias",
            format!("branch {} {} `{}`, which branch {} {}", j + 1, mine, name, i + 1, theirs),
            "use separate arrays for the two branches, or call the helpers one after another")
    }

    fn check_par_eligibility(&self, functions: &[Function]) -> Res<()> {
        if self.par_groups.is_empty() {
            return Ok(());
        }
        let infos: HashMap<_, _> = functions.iter().map(|f| (f.name.clone(), par_info(f, &self.funcs))).collect();
        for calls in &self.par_groups {
            for e in calls {
                if let Expr::Call(c) = e {
                    // At each branch, effect witnesses take precedence over foreign and nesting witnesses.
                    for kind in 0..3 {
                        if let Some(path) = par_witness(&c.name, kind, &infos) {
                            let last = path.last().unwrap();
                            let info = &infos[last];
                            let (stage, code, msg, fix) = match kind {
                                0 => {
                                    let eff = info.effects[0].as_str();
                                    ("effect", "parallel_effect",
                                        format!("par branch {} reaches {}, which declares the `{}` effect ({})",
                                            c.name, last, eff, path.join(" -> ")),
                                        format!("move the {} work outside the par group", if eff == "io" { "I/O" } else { "file" }))
                                }
                                1 => {
                                    let leaf = info.foreign.as_ref().unwrap();
                                    let mut chain = path.clone();
                                    if leaf != last { chain.push(leaf.clone()); }
                                    ("type", "parallel_foreign",
                                        format!("par branch {} reaches the trusted rust fn or catalog operation {} ({})",
                                            c.name, leaf, chain.join(" -> ")),
                                        "use Pruv computation below the par group, and keep foreign calls outside it".into())
                                }
                                _ => ("type", "parallel_nested",
                                    format!("par branch {} reaches {}, which contains a par group ({})",
                                        c.name, last, path.join(" -> ")),
                                    "keep only the outer par group; call the inner helpers one after another".into()),
                            };
                            return Err(PruvError::new(stage, c.line, c.col, code, msg, fix));
                        }
                    }
                }
            }
        }
        Ok(())
    }

    fn match_stmt(&mut self, m: &mut Match, scope: &mut Scope) -> Res<()> {
        let (line, col) = (m.line, m.col);
        let t = self.expr(&mut m.scrutinee, scope, false)?;
        let user = self.is_enum(&t);
        let root: Option<String> = self.match_root(&m.scrutinee, &t, scope); // G9 A0: root variable of an extended scrutinee path
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
                // G9 A0: a buffer payload is a read view (like a parameter): returning it needs copy()
                let kind = if bt.is_array() || *bt == strt() { "param" } else { "local" };
                sc.insert(b.clone(), Entry { ty: bt.clone(), mutable: false, kind });
            }
            if let Some(r) = &root {
                self.active_roots.push(r.clone());
            }
            self.block(&mut a.body, &mut sc)?;
            if root.is_some() {
                self.active_roots.pop();
            }
        }
        Ok(())
    }

    // ---- G9 A0: ownership of extended values, active-match borrows ----
    /// `value` (already typed) is moved into an owning position (let, assignment, constructor field, return):
    /// a non-fresh extended value is cloned, which needs `alloc`; constructors, literals and calls are fresh.
    fn own(&mut self, value: &Expr) {
        if let Some(k) = expr_ty(value) {
            let t = GType::from_key(k);
            if self.is_extended(&t) && !matches!(value, Expr::EnumCtor(_) | Expr::StructLit(_) | Expr::Call(_)) {
                self.used_effects.insert("alloc".to_string());
            }
        }
    }

    /// A constructor / struct-literal field argument: owning position, G2 explicit ownership for buffers.
    fn own_field(&mut self, value: &Expr, ftype: &GType, scope: &Scope, c: bool) -> Res<()> {
        if c {
            return Ok(());
        }
        if ftype.is_array() || *ftype == strt() {
            self.array_source(value.line(), value.col(), value, scope, false, ftype)?;
        }
        self.own(value);
        Ok(())
    }

    /// A constructor that initializes a boxed field allocates.
    fn ctor_allocs(&mut self, decl_name: &str, variant: Option<&str>, c: bool) {
        if !c && self.boxed_decls.contains(&(decl_name.to_string(), variant.map(|v| v.to_string()))) {
            self.used_effects.insert("alloc".to_string());
        }
    }

    /// Root variable of a match scrutinee that is a variable / field path over an extended type, else None.
    fn match_root(&self, scrut: &Expr, t: &GType, scope: &Scope) -> Option<String> {
        if !self.is_extended(t) {
            return None;
        }
        let mut e: &Expr = scrut;
        while let Expr::FieldAccess(x) = e {
            e = &x.base;
        }
        if let Expr::Var(v) = e {
            if scope.get(&v.name).map(|x| x.kind == "local" || x.kind == "param").unwrap_or(false) {
                return Some(v.name.clone());
            }
        }
        None
    }

    fn check_borrow(&self, line: i64, col: i64, name: &str, fields: &[String]) -> Res<()> {
        if self.active_roots.iter().any(|r| r == name) {
            let mut parts: Vec<&str> = vec![name];
            parts.extend(fields.iter().map(|f| f.as_str()));
            return Err(terr(
                line,
                col,
                "recursive_borrow",
                format!("cannot assign to {} while a match on it is active", parts.join(".")),
                "copy the needed payload into a local, finish the match, then assign",
            ));
        }
        Ok(())
    }

    /// Arrays are moved or borrowed explicitly: a new array comes only from alloc/copy/a call.
    fn array_source(&self, line: i64, col: i64, value: &Expr, scope: &Scope, allow_local_var: bool, ty: &GType) -> Res<()> {
        if matches!(value, Expr::Call(_) | Expr::StrLit(_)) {
            return Ok(());
        }
        if let Expr::Var(v) = value {
            if scope.get(&v.name).map(|x| x.kind == "inout").unwrap_or(false) {
                // G5 A0
                return Err(terr(
                    line,
                    col,
                    "array_alias",
                    format!("inout parameter {} is a borrowed array: it cannot be stored or returned", v.name),
                    format!("write copy({}) to make an independent array (needs `! alloc`)", v.name),
                ));
            }
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

    /// The argument must be an array of any element type (G2 B0: or a str). coll (G6): a Vec/HashMap/String is accepted too.
    fn expect_array(&mut self, e: &mut Expr, scope: &Scope, c: bool, coll: bool) -> Res<GType> {
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
        if !t.is_array() && t != strt() && !(coll && t.is_collection()) {
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
        if self.ckind == "cost" && (matches!(e, Expr::Spent(_))
            || matches!(e, Expr::Var(v) if v.name == "result")
            || matches!(e, Expr::Call(v) if v.name == "old")) {
            self.s5_errors.push((self.cur_name.clone(), terr(e.line(), e.col(), "cost_expr", "cost cannot contain spent, result or old", "")));
            if let Expr::Call(call) = e {
                let mut types = Vec::new();
                for a in &mut call.args { types.push(self.expr(a, scope, c)?); }
                return Ok(types.into_iter().next().unwrap_or_else(i64t));
            }
            return Ok(if matches!(e, Expr::Var(_)) && self.cur_ret != unitt() { self.cur_ret.clone() } else { i64t() });
        }
        if let Expr::Spent(_) = e {
            if !self.cur_cost || !matches!(self.ckind, "invariant" | "assert") {
                self.s5_errors.push((self.cur_name.clone(), terr(e.line(), e.col(), "spent_context", "spent is only allowed in invariant/assert of a cost function", "")));
            }
            return Ok(i64t());
        }
        match e {
            Expr::Spent(_) => unreachable!("spent handled above"),
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
                        if lt.is_collection() {
                            // G6
                            return Err(terr(
                                x.line,
                                x.col,
                                "eq_type",
                                "collections cannot be compared with ==",
                                "compare lengths and elements: len(a) == len(b) && forall k in 0..len(a): a[k] == b[k]",
                            ));
                        }
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
                        if lt.owner.is_none() && dependencies(&lt).iter().any(|n| self.buffered.contains(n)) {
                            // G9 A0
                            return Err(terr(
                                x.line,
                                x.col,
                                "eq_type",
                                format!("values of {} contain arrays or str and cannot be compared with ==", tn(&lt)),
                                "compare tags, lengths and indexed contents instead",
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
            Expr::Move(x) => {
                // G6: liveness and position rules are checked by foreign::check_ownership
                if c {
                    return Err(terr(
                        x.line,
                        x.col,
                        "foreign_move",
                        "move only where ownership is consumed",
                        "contracts read parameters and locals directly; remove `move`",
                    ));
                }
                Ok(self.lookup(x.line, x.col, &x.name, scope)?.ty)
            }
            Expr::Index(x) => {
                let at = self.expect_array(&mut x.array, scope, c, true)?;
                if at.name == "hashmap" && at.owner.is_none() {
                    return Err(terr(
                        x.array.line(),
                        x.array.col(),
                        "type_mismatch",
                        format!("expected {}, found {}", tn(&GType::array()), tn(&at)),
                        "",
                    ));
                }
                self.expect(&mut x.index, &i64t(), scope, c, None)?;
                if at.is_collection() {
                    // G6: contract-only observation of a Vec / String
                    if !c {
                        return Err(terr(
                            x.line,
                            x.col,
                            "contract_only",
                            format!("indexing a {} is only allowed in contracts", tn(&at)),
                            if at.name == "vec" { "use vec_get in code" } else { "use string_byte in code" },
                        ));
                    }
                    return Ok(if at.name == "vec" { at.args.first().cloned().unwrap_or_else(i64t) } else { i64t() });
                }
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
                let name = x.enum_name.clone();
                let targs = x.targs.clone();
                let mut ety = self.enum_type(x.line, x.col, &name)?;
                let tps = self.decls.get(&name).map(|d| d.tparams()).unwrap_or_default();
                let m = self.instantiate(x.line, x.col, &format!("enum {}", name), &decl_owner(&name), tps, &targs)?;
                if let Some(m) = &m {
                    let targs = targs.clone().unwrap_or_default();
                    x.inst = Some(inst_of(decl_owner(&name), &targs, m));
                    ety = mk_nominal(&name, targs);
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
                    self.own_field(arg, &fd.1, scope, c)?; // G9 A0
                }
                self.ctor_allocs(&name, Some(x.variant.as_str()), c); // G9 A0
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
                x.enum_ty = Some(self.variant_target(x.line, x.col, &mut x.value, &x.enum_name, &x.variant, scope, c)?);
                Ok(boolt())
            }
            Expr::VariantField(x) => {
                if !c {
                    return Err(terr(x.line, x.col, "contract_only", "variant_field is only allowed in contracts", "use match in code"));
                }
                let ety = self.variant_target(x.line, x.col, &mut x.value, &x.enum_name, &x.variant, scope, c)?;
                x.enum_ty = Some(ety.clone());
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
            Expr::InoutArg(x) => {
                // G5 A0: valid only as a direct argument of a call (see inout_args)
                Err(terr(
                    x.line,
                    x.col,
                    "inout_argument",
                    "the `inout` marker is only valid on an argument of a function whose parameter is inout",
                    "remove `inout`",
                ))
            }
            Expr::Call(x) => self.call(x, scope, c),
        }
    }

    // ---- user type helpers ----
    /// [(field name, field type)] of the struct / enum variant `ty` names, with the type arguments of `ty` substituted
    /// into the declared field types (G3_SPEC 3.4).
    fn fields_of(&self, ty: &GType, variant: Option<&str>) -> Res<Vec<(String, GType)>> {
        let m = self.bind_decl_args(ty)?;
        let fs = self.tt.fields(&ty.name, variant).unwrap_or(&[]);
        Ok(fs.iter().map(|fd| (fd.name.clone(), substitute(&GType::from_key(&fd.ty), &m))).collect())
    }

    /// The substitution of a nominal application's type arguments for its declaration's parameters.
    fn bind_decl_args(&self, ty: &GType) -> Res<Mapping> {
        let n = self.decls.get(&ty.name).map(|d| d.tparams().len()).unwrap_or(0);
        match bind_args(&decl_owner(&ty.name), n, &ty.args) {
            Ok(m) => Ok(m),
            Err(e) => Err(terr(0, 0, "internal", e.to_string(), "")),
        }
    }

    /// The type of a struct field: find the field first, then substitute only its type (substituting every field made
    /// `x.f` O(fields)); a struct type without type arguments yields the declared type as is.
    fn field_type(&self, line: i64, col: i64, sty: &GType, name: &str) -> Res<GType> {
        let fs = self.tt.fields(&sty.name, None).unwrap_or(&[]);
        for fd in fs {
            if fd.name == name {
                let ft = GType::from_key(&fd.ty);
                if sty.args.is_empty() {
                    return Ok(ft);
                }
                return Ok(substitute(&ft, &self.bind_decl_args(sty)?));
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
        let name = e.name.clone();
        let targs = e.targs.clone();
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
        let m = self.instantiate(e.line, e.col, &format!("struct {}", name), &decl_owner(&name), tps, &targs)?;
        if let Some(m) = &m {
            let targs = targs.clone().unwrap_or_default();
            e.inst = Some(inst_of(decl_owner(&name), &targs, m));
            sty = mk_nominal(&name, targs);
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
            self.own_field(&fi.value, &fd.1, scope, c)?; // G9 A0
        }
        self.ctor_allocs(&name, None, c); // G9 A0
        Ok(sty)
    }

    /// Some / None / Ok / Err. Without type arguments they keep the legacy i64 meaning (G3_SPEC 0.0 item 8);
    /// `Some::<X>(x)`, `None::<X>`, `Ok::<X>(x)`, `Err::<X>(code)` build Option<X> / Result<X> (3.5).
    fn ctor(&mut self, e: &mut Ctor, scope: &Scope, c: bool) -> Res<GType> {
        let name = e.name.clone();
        let targs = match e.targs.clone() {
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
        self.ext_misuse(e.line, e.col, &x, Some("arg"))?; // G9 A0
        let owner = format!("builtin:{}", name);
        let mut m = Mapping::new();
        m.insert((owner.clone(), 0), x.clone());
        e.inst = Some(inst_of(owner, &targs, &m));
        if name == "None" {
            return Ok(mk_option(x));
        }
        let want = if name == "Err" { i64t() } else { x.clone() };
        if let Some(a) = e.arg.as_mut() {
            self.expect(a, &want, scope, c, None)?;
        }
        Ok(if name == "Some" { mk_option(x) } else { mk_result(x) })
    }

    /// map_lookup / map_updated arguments: a key whose type differs from a map argument's key type is a
    /// foreign_contract error; any other mismatch is the ordinary type_mismatch.
    fn observer_args(&mut self, e: &mut Call, cf: &CatFn, m: &Mapping, scope: &Scope, c: bool) -> Res<()> {
        let mut got: Vec<GType> = Vec::new();
        for arg in e.args.iter_mut() {
            got.push(self.expr(arg, scope, c)?);
        }
        let kidx = cf.params.iter().position(|p| p.name == "k").unwrap_or(0);
        for g in &got {
            if g.name == "hashmap" && g.owner.is_none() {
                if let (Some(k0), Some(kt)) = (g.args.first(), got.get(kidx)) {
                    if k0 != kt {
                        return Err(terr(
                            e.args[kidx].line(),
                            e.args[kidx].col(),
                            "foreign_contract",
                            format!("key of type {} does not match the map key type {}", tn(kt), tn(k0)),
                            "pass a key of the map's key type",
                        ));
                    }
                }
            }
        }
        for ((arg, g), prm) in e.args.iter().zip(got.iter()).zip(cf.params.iter()) {
            let want = substitute(&prm.ty, m);
            if *g != want {
                return Err(terr(
                    arg.line(),
                    arg.col(),
                    "type_mismatch",
                    format!("expected {}, found {}", tn(&want), tn(g)),
                    "",
                ));
            }
        }
        Ok(())
    }

    // ---- G5 A0: inout call arguments and old(..) ----
    /// Arguments of a resolved call to a user function whose signature has an inout parameter (or that carries a marker):
    /// per argument marker/place validity and the instantiated type, then exclusive use of every marked binding across the
    /// whole argument list, then the statement-boundary position of the call.
    fn inout_args(&mut self, e: &mut Call, f: &FuncInfo, m: &Mapping, scope: &Scope, c: bool) -> Res<()> {
        let n = e.name.clone();
        let mut marked: Vec<(usize, String)> = Vec::new();
        for i in 0..e.args.len().min(f.params.len()) {
            let want = substitute(&f.params[i], m);
            let pname = f.pnames[i].clone();
            if !f.inout[i] {
                if let Expr::InoutArg(a) = &e.args[i] {
                    return Err(terr(
                        a.line,
                        a.col,
                        "inout_argument",
                        format!("parameter {} of {} is not inout: the `inout` marker is not allowed here", pname, n),
                        format!("remove `inout`, or declare the parameter `inout {}: ...`", pname),
                    ));
                }
                self.expect(&mut e.args[i], &want, scope, c, None)?;
                continue;
            }
            let (aline, acol) = (e.args[i].line(), e.args[i].col());
            let arg: &mut InoutArg = match &mut e.args[i] {
                Expr::InoutArg(a) => a,
                _ => {
                    return Err(terr(
                        aline,
                        acol,
                        "inout_argument",
                        format!("parameter {} of {} is inout: the argument needs the `inout` marker", pname, n),
                        "write `inout name` with a `let mut` local array or an inout parameter",
                    ))
                }
            };
            let what: Option<&str> = match &*arg.expr {
                Expr::Var(_) => None,
                Expr::FieldAccess(_) => Some("a field"),
                Expr::Index(_) => Some("an element"),
                Expr::Call(_) => Some("a call"),
                _ => Some("an expression"),
            };
            if let Some(what) = what {
                return Err(terr(
                    aline,
                    acol,
                    "inout_argument",
                    format!("an inout argument must be the whole name of a local array or an inout parameter, not {}", what),
                    "name a `let mut` local array or an inout parameter of this function",
                ));
            }
            let op: &mut Var = match &mut *arg.expr {
                Expr::Var(v) => v,
                _ => return Err(terr(aline, acol, "internal", "unknown expression", "")),
            };
            let v = self.lookup(op.line, op.col, &op.name, scope)?;
            if v.kind == "local" && !v.mutable {
                return Err(terr(
                    aline,
                    acol,
                    "inout_argument",
                    format!("{} is not mutable: it cannot be passed inout", op.name),
                    "declare it with `let mut`",
                ));
            }
            if v.kind != "inout" && v.kind != "local" {
                return Err(terr(
                    aline,
                    acol,
                    "inout_argument",
                    format!(
                        "{} is a read-only {}: it cannot be passed inout",
                        op.name,
                        if v.kind == "param" { "parameter" } else { "binding" }
                    ),
                    format!("declare the parameter `inout {}: ...`, or copy into a `let mut` local", op.name),
                ));
            }
            if v.ty != want {
                return Err(terr(
                    aline,
                    acol,
                    "inout_argument",
                    format!(
                        "inout argument {} has type {} but parameter {} of {} expects {}",
                        op.name,
                        tn(&v.ty),
                        pname,
                        n,
                        tn(&want)
                    ),
                    "pass an array of exactly the parameter's element type",
                ));
            }
            if self.active_roots.iter().any(|r| *r == op.name) {
                // G9: mutable access while a match view of the root is active
                return Err(terr(
                    aline,
                    acol,
                    "recursive_borrow",
                    format!("cannot pass {} inout while a match on it is active", op.name),
                    "finish the match before the call",
                ));
            }
            op.ty = Some(v.ty.to_key());
            arg.ty = Some(v.ty.to_key());
            marked.push((i, op.name.clone()));
        }
        for (i, name) in &marked {
            if e.args.iter().enumerate().any(|(j, x)| j != *i && mentions(x, name)) {
                return Err(terr(
                    e.args[*i].line(),
                    e.args[*i].col(),
                    "inout_alias",
                    format!("{} is passed inout and also used elsewhere in the arguments of this call", name),
                    format!("compute the other value first, e.g. `let n: i64 = len({});`, then pass n", name),
                ));
            }
        }
        if !c && self.boundary != Some(&*e as *const Call as usize) {
            return Err(terr(
                e.line,
                e.col,
                "inout_context",
                "a call with an inout parameter must be a whole expression statement, let initializer, assignment value or return value",
                "bind the result first: `let r: T = f(inout a);` and use r afterwards",
            ));
        }
        Ok(())
    }

    /// The contextual builtin old(a): context first, then arity and operand.
    fn old_call(&mut self, e: &mut Call, scope: &Scope) -> Res<GType> {
        let (line, col) = (e.line, e.col);
        if !matches!(self.ckind, "ensures" | "invariant" | "assert") {
            return Err(terr(
                line,
                col,
                "old_context",
                "old(..) is only allowed in ensures, loop invariants and asserts",
                "state the property in a contract clause; in code use copy(a) (needs alloc) if the entry value is needed",
            ));
        }
        if e.args.len() != 1 {
            return Err(terr(
                line,
                col,
                "old_argument",
                format!("old takes exactly 1 argument, got {}", e.args.len()),
                "write old(a) with the name of an inout parameter of this function",
            ));
        }
        let entry: Option<Entry> = match &e.args[0] {
            Expr::Var(v) => scope.get(&v.name).filter(|x| x.kind == "inout").cloned(),
            _ => None,
        };
        let entry = match entry {
            Some(x) => x,
            None => {
                return Err(terr(
                    line,
                    col,
                    "old_argument",
                    "the operand of old must be the name of an inout parameter of this function",
                    "write old(a) where `inout a: [..]` is a parameter of the enclosing function",
                ))
            }
        };
        let mut name = String::new();
        if let Expr::Var(v) = &mut e.args[0] {
            v.ty = Some(entry.ty.to_key());
            name = v.name.clone();
        }
        let index = self.cur_params.iter().position(|p| *p == name).unwrap_or(0);
        e.old = Some((name, index));
        Ok(entry.ty)
    }

    fn call(&mut self, e: &mut Call, scope: &Scope, c: bool) -> Res<GType> {
        let n = e.name.clone();
        let targs = e.targs.clone();
        let (line, col) = (e.line, e.col);
        let alen = e.args.len();
        let arity = |k: usize| -> Res<()> {
            if alen != k {
                return Err(terr(line, col, "arity", format!("{} takes {} argument(s), got {}", n, k, alen), ""));
            }
            Ok(())
        };
        let is_builtin = matches!(n.as_str(), "len" | "alloc" | "copy" | "print" | "is_char_boundary" | "substr");
        let is_old = n == "old" && self.uses_inout && !self.funcs.contains_key(&n); // G5 A0: contextual builtin
        if targs.is_some() && !self.funcs.contains_key(&n) && (is_builtin || contract_only(&n).is_some() || is_old) {
            return Err(terr(line, col, "type_arity", format!("builtin {} takes no type arguments", n), "remove the `::<...>`"));
        }
        if is_old {
            return self.old_call(e, scope);
        }
        match n.as_str() {
            "len" => {
                arity(1)?;
                self.expect_array(&mut e.args[0], scope, c, true)?; // G6: also Vec/HashMap/String
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
                let at = self.expect_array(&mut e.args[0], scope, c, false)?;
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
                return Err(terr(
                    line,
                    col,
                    "contract_only",
                    format!("{} is only allowed in contracts", n),
                    if n == "size" { "size is a contract measure; use len or a counter in code" } else { "use match in code" },
                ));
            }
            arity(1)?;
            let t = self.expr(&mut e.args[0], scope, c)?;
            if n == "size" {
                // G9 A0: a non-generic user struct/enum value
                let generic = self.decls.get(&t.name).map(|d| !d.tparams().is_empty()).unwrap_or(false);
                if !(self.is_plain_nominal(&t) && !generic) {
                    return Err(terr(
                        line,
                        col,
                        "size_type",
                        format!("size needs a non-generic struct or enum value, got {}", tn(&t)),
                        "size counts constructors; use len for arrays and strings",
                    ));
                }
                return Ok(i64t());
            }
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
        // G6: fixed standard catalog (G6_SPEC 10.3)
        let cat: Option<CatFn> = catalog_fn(&n);
        let f: Rc<FuncInfo> = if let Some(cf) = &cat {
            if is_catalog_contract_only(&n) {
                if !c {
                    return Err(terr(
                        line,
                        col,
                        "foreign_contract",
                        format!("{} is only allowed in contracts", n),
                        if n == "map_lookup" { "use map_get in code" } else { "state the update in ensures" },
                    ));
                }
            } else if c && !is_file_observer(&n) {
                return Err(terr(
                    line,
                    col,
                    "foreign_contract",
                    format!("{} cannot be called in a contract", n),
                    "contracts observe collections with len(x), x[i], map_lookup and map_updated",
                ));
            }
            Rc::new(FuncInfo {
                src_name: n.clone(),
                line: 0,
                col: 0,
                params: cf.params.iter().map(|p| p.ty.clone()).collect(),
                pnames: cf.params.iter().map(|p| p.name.to_string()).collect(),
                inout: vec![false; cf.params.len()],
                ret: cf.ret.clone(),
                effects: cf.effects.clone(),
                tparams: cf.tparams.clone(),
                foreign: false,
            })
        } else {
            match self.funcs.get(&n) {
                Some(f) => {
                    if c && f.foreign {
                        return Err(terr(
                            line,
                            col,
                            "foreign_contract",
                            format!("trusted rust fn {} cannot be called in a contract", n),
                            "state the property with the arguments' own contents instead",
                        ));
                    }
                    Rc::clone(f)
                }
                None => {
                    let fix = if matches!(n.as_str(), "sum" | "count" | "max" | "min") {
                        "aggregates use the form sum(k in 0..len(a): a[k])"
                    } else {
                        ""
                    };
                    return Err(terr(line, col, "unknown_fn", format!("unknown function {}", n), fix));
                }
            }
        };
        // G3_SPEC 3.4: resolve + arity + admissibility + bounds, substitute the signature, check the arguments
        let m = self.instantiate(line, col, &format!("function {}", n), &fn_owner(&n), &f.tparams, &targs)?;
        if let Some(m) = &m {
            e.inst = Some(inst_of(fn_owner(&n), targs.as_deref().unwrap_or(&[]), m));
        }
        let m = m.unwrap_or_default();
        arity(f.params.len())?;
        match &cat {
            Some(cf) if is_catalog_contract_only(&n) => self.observer_args(e, cf, &m, scope, c)?,
            // G5 A0: marker, place, type, exclusivity and statement context
            None if f.inout.iter().any(|b| *b) || e.args.iter().any(|x| matches!(x, Expr::InoutArg(_))) => {
                self.inout_args(e, &f, &m, scope, c)?
            }
            _ => {
                for (arg, p) in e.args.iter_mut().zip(f.params.iter()) {
                    self.expect(arg, &substitute(p, &m), scope, c, None)?;
                }
            }
        }
        if cat.is_some() {
            self.used_effects.extend(f.effects.iter().cloned());
            return Ok(substitute(&f.ret, &m));
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
        if !f.foreign {
            // G9 A0: foreign calls are leaves of the call graph
            self.call_log.push((self.cur_name.clone(), line, col, targs.clone(), n.clone()));
        }
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
        // G9 A0: a cycle without a base case has no finite value
        assert_eq!(e.message, "recursive type has no finite value: A -> B -> A");
        assert_eq!(e.fix, "add a variant without recursive fields (a base case such as `Empty`)");
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

/// Executable calls only: contracts do not contribute to branch eligibility.
struct ParInfo {
    effects: Vec<String>,
    foreign: Option<String>,
    par: bool,
    callees: Vec<String>,
}

fn par_info(f: &Function, funcs: &HashMap<String, Rc<FuncInfo>>) -> ParInfo {
    let mut info = ParInfo {
        effects: ["io", "fs"].iter().filter(|e| f.effects.iter().any(|x| x == **e)).map(|e| e.to_string()).collect(),
        foreign: f.foreign.as_ref().map(|_| f.name.clone()),
        par: false,
        callees: Vec::new(),
    };
    fn ex(e: &Expr, info: &mut ParInfo, funcs: &HashMap<String, Rc<FuncInfo>>) {
        if let Expr::Call(c) = e {
            if funcs.contains_key(&c.name) {
                if !info.callees.contains(&c.name) { info.callees.push(c.name.clone()); }
            } else if is_catalog(&c.name) && info.foreign.is_none() {
                info.foreign = Some(c.name.clone());
            }
        }
        for k in crate::refine::kids(e) { ex(k, info, funcs); }
    }
    fn walk(stmts: &[Stmt], info: &mut ParInfo, funcs: &HashMap<String, Rc<FuncInfo>>) {
        for st in stmts {
            match st {
                Stmt::Let(x) => ex(&x.value, info, funcs),
                Stmt::Assign(x) => ex(&x.value, info, funcs),
                Stmt::FieldAssign(x) => ex(&x.value, info, funcs),
                Stmt::IndexAssign(x) => {
                    ex(&x.index, info, funcs);
                    ex(&x.value, info, funcs);
                }
                Stmt::If(x) => {
                    ex(&x.cond, info, funcs);
                    walk(&x.then, info, funcs);
                    walk(&x.els, info, funcs);
                }
                Stmt::While(x) => {
                    ex(&x.cond, info, funcs);
                    walk(&x.body, info, funcs);
                }
                Stmt::Return(x) => if let Some(v) = &x.value { ex(v, info, funcs); },
                Stmt::ExprStmt(x) => ex(&x.expr, info, funcs),
                Stmt::Par(x) => {
                    info.par = true;
                    for c in &x.calls { ex(c, info, funcs); }
                }
                Stmt::Match(x) => {
                    ex(&x.scrutinee, info, funcs);
                    for a in &x.arms { walk(&a.body, info, funcs); }
                }
                Stmt::Assert(_) => {},
            }
        }
    }
    walk(&f.body, &mut info, funcs);
    info
}

/// Source-order DFS, including the starting function, with cycles visited only once.
fn par_witness(start: &str, kind: usize, infos: &HashMap<String, ParInfo>) -> Option<Vec<String>> {
    let mut seen = HashSet::new();
    let mut stack = vec![(start.to_string(), vec![start.to_string()])];
    while let Some((n, path)) = stack.pop() {
        if !seen.insert(n.clone()) { continue; }
        let info = &infos[&n];
        let found = match kind {
            0 => !info.effects.is_empty(),
            1 => info.foreign.is_some(),
            _ => info.par,
        };
        if found { return Some(path); }
        for c in info.callees.iter().rev() {
            if !seen.contains(c) {
                let mut p = path.clone();
                p.push(c.clone());
                stack.push((c.clone(), p));
            }
        }
    }
    None
}


// Executable calls only, like Python par_items: assertions and loop contracts do not spend work.
fn cost_calls(stmts: &[Stmt], out: &mut Vec<Call>) {
    fn ex(e: &Expr, out: &mut Vec<Call>) {
        if let Expr::Call(c) = e { out.push(c.clone()); }
        for k in crate::refine::kids(e) { ex(k, out); }
    }
    for st in stmts {
        match st {
            Stmt::Let(x) => ex(&x.value, out),
            Stmt::Assign(x) => ex(&x.value, out),
            Stmt::FieldAssign(x) => ex(&x.value, out),
            Stmt::IndexAssign(x) => { ex(&x.index, out); ex(&x.value, out); }
            Stmt::If(x) => { ex(&x.cond, out); cost_calls(&x.then, out); cost_calls(&x.els, out); }
            Stmt::While(x) => { ex(&x.cond, out); cost_calls(&x.body, out); }
            Stmt::Return(x) => if let Some(v) = &x.value { ex(v, out); },
            Stmt::ExprStmt(x) => ex(&x.expr, out),
            Stmt::Par(x) => for c in &x.calls { ex(c, out); },
            Stmt::Match(x) => {
                ex(&x.scrutinee, out);
                for a in &x.arms { cost_calls(&a.body, out); }
            }
            Stmt::Assert(_) => {},
        }
    }
}
