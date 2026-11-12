//! G6 A0 (docs/G6_SPEC.md section 10; counterpart of foreign.py): the fixed standard catalog, validation of
//! `trusted rust fn` declarations, the ownership/liveness checker for collection bindings, and the A0 guard `first_g6_use`.
//!
//! Everything here runs after (or inside) type checking and only looks at typed ASTs; a program without G6 syntax
//! passes through unchanged. Messages, fixes and positions are those of foreign.py character for character.

use crate::ast::*;
use crate::diagnostic::PruvError;
use crate::gtype::{fn_owner, format_type, key_is_collection, mk_option, mk_param, GType};
use crate::refine::kids as expr_kids;
use std::collections::{HashMap, HashSet};

type Res<T> = Result<T, PruvError>;

fn err(line: i64, col: i64, code: &str, msg: impl Into<String>, fix: impl Into<String>) -> PruvError {
    PruvError::new("type", line, col, code, msg, fix)
}

// ---------------------------------------------------------------------------
// catalog (section 10.3): pseudo declarations without bodies, typed through the ordinary generic call path
// ---------------------------------------------------------------------------

/// One parameter of a catalog function.
#[derive(Debug, Clone)]
pub struct CatParam {
    pub name: &'static str,
    pub ty: GType,
    pub take: bool,
}

/// A catalog function: generic (explicit type arguments are required), effects as declared.
#[derive(Debug, Clone)]
pub struct CatFn {
    pub requires: Vec<Expr>,
    pub ensures: Vec<Expr>,
    pub params: Vec<CatParam>,
    pub ret: GType,
    pub effects: Vec<String>,
    pub tparams: Vec<TParam>,
}

/// CATALOG_NAMES of foreign.py (insertion order).
pub const CATALOG_NAMES: [&str; 23] = [
    "vec_new",
    "vec_push",
    "vec_get",
    "map_new",
    "map_get",
    "map_insert",
    "string_new",
    "string_push_str",
    "string_byte",
    "string_to_str",
    "file_open_read",
    "file_create",
    "file_read_all",
    "file_write_str",
    "file_write_bytes",
    "file_close",
    "file_ok",
    "file_readable",
    "file_writable",
    "file_size",
    "file_byte",
    "map_lookup",
    "map_updated",
];

/// CATALOG_CONTRACT_ONLY of foreign.py.
pub const CATALOG_CONTRACT_ONLY: [&str; 2] = ["map_lookup", "map_updated"];

/// FILE_OBSERVERS of foreign.py (G10 A0): catalog reads that are also allowed in contracts.
pub const FILE_OBSERVERS: [&str; 5] = ["file_ok", "file_readable", "file_writable", "file_size", "file_byte"];

pub fn is_file_observer(name: &str) -> bool {
    FILE_OBSERVERS.contains(&name)
}

pub fn is_catalog(name: &str) -> bool {
    CATALOG_NAMES.contains(&name)
}

pub fn is_catalog_contract_only(name: &str) -> bool {
    CATALOG_CONTRACT_ONLY.contains(&name)
}

fn p(name: &'static str, ty: GType, take: bool) -> CatParam {
    CatParam { name, ty, take }
}

fn vec_of(t: GType) -> GType {
    GType::new("vec", vec![t])
}

fn map_of(k: GType, v: GType) -> GType {
    GType::new("hashmap", vec![k, v])
}

fn string_t() -> GType {
    GType::new("string", Vec::new())
}

fn file_t() -> GType {
    GType::new("file", Vec::new())
}

fn tp(name: &str, bound: Option<&str>) -> TParam {
    TParam { line: 0, col: 0, name: name.to_string(), bound: bound.map(|b| b.to_string()) }
}

/// The catalog declaration of `name`, or None when `name` is not a catalog function.
pub fn catalog_fn(name: &str) -> Option<CatFn> {
    let owner = fn_owner(name);
    // _T = [("T", None)] and _KV = [("K", "Element"), ("V", None)]: parameters are identified by (owner, index)
    let t = || mk_param(&owner, 0, "T");
    let k = || mk_param(&owner, 0, "K");
    let v = || mk_param(&owner, 1, "V");
    let alloc = || vec!["alloc".to_string()];
    let fs = || vec!["fs".to_string()];
    let tp_t = || vec![tp("T", None)];
    let tp_kv = || vec![tp("K", Some("Element")), tp("V", None)];
    let mut f = match name {
        "vec_new" => CatFn { requires: vec![], ensures: vec![], params: vec![], ret: vec_of(t()), effects: alloc(), tparams: tp_t() },
        "vec_push" => CatFn { requires: vec![], ensures: vec![],
            params: vec![p("v", vec_of(t()), true), p("x", t(), false)],
            ret: vec_of(t()),
            effects: alloc(),
            tparams: tp_t(),
        },
        "vec_get" => CatFn { requires: vec![], ensures: vec![],
            params: vec![p("v", vec_of(t()), false), p("i", GType::i64(), false)],
            ret: t(),
            effects: vec![],
            tparams: tp_t(),
        },
        "map_new" => CatFn { requires: vec![], ensures: vec![], params: vec![], ret: map_of(k(), v()), effects: alloc(), tparams: tp_kv() },
        "map_get" => CatFn { requires: vec![], ensures: vec![],
            params: vec![p("m", map_of(k(), v()), false), p("k", k(), false)],
            ret: mk_option(v()),
            effects: vec![],
            tparams: tp_kv(),
        },
        "map_insert" => CatFn { requires: vec![], ensures: vec![],
            params: vec![p("m", map_of(k(), v()), true), p("k", k(), false), p("v", v(), false)],
            ret: map_of(k(), v()),
            effects: alloc(),
            tparams: tp_kv(),
        },
        "string_new" => CatFn { requires: vec![], ensures: vec![], params: vec![], ret: string_t(), effects: alloc(), tparams: vec![] },
        "string_push_str" => CatFn { requires: vec![], ensures: vec![],
            params: vec![p("s", string_t(), true), p("text", GType::str(), false)],
            ret: string_t(),
            effects: alloc(),
            tparams: vec![],
        },
        "string_byte" => CatFn { requires: vec![], ensures: vec![],
            params: vec![p("s", string_t(), false), p("i", GType::i64(), false)],
            ret: GType::i64(),
            effects: vec![],
            tparams: vec![],
        },
        "string_to_str" => CatFn { requires: vec![], ensures: vec![],
            params: vec![p("s", string_t(), false)],
            ret: GType::str(),
            effects: alloc(),
            tparams: vec![],
        },
        // G10 A0: signatures/effects; typed A1 contracts are defined below.
        "file_open_read" | "file_create" => CatFn { requires: vec![], ensures: vec![],
            params: vec![p("path", GType::str(), false)],
            ret: file_t(),
            effects: fs(),
            tparams: vec![],
        },
        "file_read_all" => CatFn { requires: vec![], ensures: vec![],
            params: vec![p("f", file_t(), true)],
            ret: file_t(),
            effects: vec!["fs".to_string(), "alloc".to_string()],
            tparams: vec![],
        },
        "file_write_str" => CatFn { requires: vec![], ensures: vec![],
            params: vec![p("f", file_t(), true), p("text", GType::str(), false)],
            ret: file_t(),
            effects: fs(),
            tparams: vec![],
        },
        "file_write_bytes" => CatFn { requires: vec![], ensures: vec![],
            params: vec![p("f", file_t(), true), p("data", GType::array_u8(), false)],
            ret: file_t(),
            effects: fs(),
            tparams: vec![],
        },
        "file_close" => CatFn { requires: vec![], ensures: vec![], params: vec![p("f", file_t(), true)], ret: GType::bool(), effects: fs(), tparams: vec![] },
        "file_ok" | "file_readable" | "file_writable" => {
            CatFn { requires: vec![], ensures: vec![], params: vec![p("f", file_t(), false)], ret: GType::bool(), effects: vec![], tparams: vec![] }
        }
        "file_size" => CatFn { requires: vec![], ensures: vec![], params: vec![p("f", file_t(), false)], ret: GType::i64(), effects: vec![], tparams: vec![] },
        "file_byte" => CatFn { requires: vec![], ensures: vec![],
            params: vec![p("f", file_t(), false), p("i", GType::i64(), false)],
            ret: GType::i64(),
            effects: vec![],
            tparams: vec![],
        },
        // contract-only observers
        "map_lookup" => CatFn { requires: vec![], ensures: vec![],
            params: vec![p("m", map_of(k(), v()), false), p("k", k(), false)],
            ret: mk_option(v()),
            effects: vec![],
            tparams: tp_kv(),
        },
        "map_updated" => CatFn { requires: vec![], ensures: vec![],
            params: vec![
                p("after", map_of(k(), v()), false),
                p("before", map_of(k(), v()), false),
                p("k", k(), false),
                p("v", v(), false),
            ],
            ret: GType::bool(),
            effects: vec![],
            tparams: tp_kv(),
        },
        _ => return None,
    };
    (f.requires, f.ensures) = file_contracts(name);
    Some(f)
}

/// G10 A1: Python _file_contracts, preserving typed AST shapes, positions and order.
fn file_contracts(name: &str) -> (Vec<Expr>, Vec<Expr>) {
    fn var(n: &str, t: &str) -> Expr { Expr::Var(Var { line: 0, col: 0, name: n.into(), ty: Some(t.into()) }) }
    fn obs(n: &str, v: Expr) -> Expr {
        Expr::Call(Call { line: 0, col: 0, name: format!("file_{}", n), args: vec![v],
            ty: Some(if n == "size" { "i64" } else { "bool" }.into()), targs: None, inst: None, old: None })
    }
    fn bin(op: &str, a: Expr, b: Expr) -> Expr {
        Expr::Binary(Binary { line: 0, col: 0, op: op.into(), left: Box::new(a), right: Box::new(b), ty: Some("bool".into()) })
    }
    fn neg(a: Expr) -> Expr { Expr::Unary(Unary { line: 0, col: 0, op: "!".into(), operand: Box::new(a), ty: Some("bool".into()) }) }
    fn int(n: &str) -> Expr { Expr::IntLit(IntLit { line: 0, col: 0, value: n.into(), ty: Some("i64".into()) }) }
    let result = var("result", "file");
    let f = var("f", "file");
    let ok = obs("ok", result.clone());
    let size = obs("size", result.clone());
    let read = vec![bin("==", obs("readable", result.clone()), ok.clone()), neg(obs("writable", result.clone())), bin("==", size.clone(), int("0"))];
    let write = vec![bin("==", obs("writable", result.clone()), ok.clone()), neg(obs("readable", result.clone())), bin("==", size.clone(), int("0"))];
    match name {
        "file_open_read" => (vec![], read),
        "file_create" => (vec![], write),
        "file_read_all" => (vec![obs("readable", f)], vec![neg(obs("writable", result)), read[0].clone(), bin("==>", ok.clone(), bin(">=", size.clone(), int("0"))), bin("==>", neg(ok), bin("==", size, int("0")))]),
        "file_write_str" | "file_write_bytes" => (vec![obs("writable", f)], vec![neg(obs("readable", result)), write[0].clone(), write[2].clone()]),
        "file_close" => (vec![], vec![bin("==>", var("result", "bool"), obs("ok", f))]),
        "file_size" => (vec![], vec![bin(">=", var("result", "i64"), int("0"))]),
        "file_byte" => (vec![bin("&&", bin("<=", int("0"), var("i", "i64")), bin("<", var("i", "i64"), obs("size", f)))], vec![bin("&&", bin("<=", int("0"), var("result", "i64")), bin("<=", var("result", "i64"), int("255")))]),
        _ => (vec![], vec![]),
    }
}

// ---------------------------------------------------------------------------
// trusted rust fn declarations (section 10.4)
// ---------------------------------------------------------------------------

/// Option<i64|bool> / Result<i64|bool>
fn scalar_opt(t: &GType) -> bool {
    t.owner.is_none()
        && (t.name == "option" || t.name == "result")
        && (t.args.is_empty() || t.args[0] == GType::i64() || t.args[0] == GType::bool())
}

fn allowed_result(t: &GType) -> bool {
    *t == GType::i64() || *t == GType::bool() || *t == GType::unit() || scalar_opt(t)
}

fn allowed_param(t: &GType) -> bool {
    *t == GType::i64()
        || *t == GType::bool()
        || *t == GType::array()
        || *t == GType::array_u8()
        || *t == GType::array_bool()
        || *t == GType::str()
        || scalar_opt(t)
}

fn is_ident(s: &str) -> bool {
    let mut cs = s.chars();
    match cs.next() {
        Some(c) if c.is_ascii_alphabetic() || c == '_' => cs.all(|c| c.is_ascii_alphanumeric() || c == '_'),
        _ => false,
    }
}

/// fullmatch of `::[A-Za-z_][A-Za-z0-9_]*(?:::[A-Za-z_][A-Za-z0-9_]*)*`
fn path_ok(path: &str) -> bool {
    match path.strip_prefix("::") {
        Some(rest) => rest.split("::").all(is_ident),
        None => false,
    }
}

/// signature (foreign_signature), then path (foreign_path) of a trusted rust fn
pub fn check_foreign_decl(f: &Function, externs: &[String]) -> Res<()> {
    let (fl, fc) = (f.line, f.col);
    if !f.tparams.is_empty() {
        return Err(err(
            fl,
            fc,
            "foreign_signature",
            "a trusted rust fn cannot be generic",
            "declare one concrete trusted rust fn per type",
        ));
    }
    let ret = GType::from_key(&f.ret);
    if !allowed_result(&ret) {
        return Err(err(
            fl,
            fc,
            "foreign_signature",
            format!("result type {} is not allowed on a trusted rust fn", format_type(&ret)),
            "return i64, bool, (), Option<i64|bool> or Result<i64|bool>; convert other results in a Rust adapter",
        ));
    }
    for prm in &f.params {
        let pt = GType::from_key(&prm.ty);
        if let Some((ml, mc)) = prm.mode_pos {
            // G5 A0: rejected whether or not the declaration is ever called; points at the `inout` token
            return Err(err(
                ml,
                mc,
                "foreign_signature",
                format!("inout parameter {} is not allowed on a trusted rust fn", prm.name),
                "remove `inout`; a foreign function only reads its arguments",
            ));
        }
        if prm.take {
            return Err(err(
                fl,
                fc,
                "foreign_signature",
                format!("take parameter {} is not allowed on a trusted rust fn", prm.name),
                "remove `take`; a foreign function only reads its arguments",
            ));
        }
        if pt.contains_collection() {
            return Err(err(
                fl,
                fc,
                "foreign_signature",
                format!("collection parameter {} is not allowed on a trusted rust fn", prm.name),
                "pass i64, bool, Option, Result, arrays or str; wrap collections in a Rust adapter",
            ));
        }
        if !allowed_param(&pt) {
            return Err(err(
                fl,
                fc,
                "foreign_signature",
                format!("parameter {} of type {} is not allowed on a trusted rust fn", prm.name, format_type(&pt)),
                "use i64, bool, Option<i64|bool>, Result<i64|bool>, [i64], [u8], [bool] or str",
            ));
        }
    }
    if f.ensures.is_empty() {
        return Err(err(
            fl,
            fc,
            "foreign_signature",
            "a trusted rust fn needs at least one ensures",
            "add an ensures clause; `ensures true` documents an unconstrained result",
        ));
    }
    let info = match &f.foreign {
        Some(i) => i,
        None => return Ok(()),
    };
    let (al, ac) = (info.line, info.col);
    let path = info.path.as_str();
    if !path_ok(path) {
        return Err(err(
            al,
            ac,
            "foreign_path",
            "invalid Rust path",
            "write the path as ::std::cmp::min: `::` and identifiers only, no expressions, generics or spaces",
        ));
    }
    let root = path[2..].split("::").next().unwrap_or("");
    if matches!(root, "crate" | "self" | "super") {
        return Err(err(
            al,
            ac,
            "foreign_path",
            "relative Rust path root",
            "start the path with ::std or the name of a crate given with --rust-extern",
        ));
    }
    if root != "std" && !externs.iter().any(|x| x == root) {
        return Err(err(
            al,
            ac,
            "foreign_path",
            format!("Rust crate {} is not supplied", root),
            format!("pass --rust-extern {}=PATH or use a ::std path", root),
        ));
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// ownership / liveness (section 10.4)
// State: ordered map name -> live | dead | maybe for owned collection bindings; None = unreachable path.
// The map keeps insertion order exactly like the Python dict (the first reported name of a loop error depends on it).
// Borrowed (unmarked collection) parameters are kept in `bor` and never change.
// ---------------------------------------------------------------------------
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
enum V {
    Live,
    Dead,
    Maybe,
}

/// Insertion-ordered map with O(1) lookups: `slots` keeps the order (a popped entry leaves a `None`
/// tombstone, a re-inserted name goes to the end, as in a Python dict), `idx` maps a name to its slot.
#[derive(Clone, Default, Debug)]
struct St {
    slots: Vec<Option<(String, V)>>,
    idx: HashMap<String, usize>,
}

impl St {
    fn get(&self, n: &str) -> Option<V> {
        self.idx.get(n).and_then(|&i| self.slots[i].as_ref()).map(|(_, v)| *v)
    }
    fn set(&mut self, n: &str, v: V) {
        match self.idx.get(n) {
            Some(&i) => {
                if let Some(slot) = self.slots[i].as_mut() {
                    slot.1 = v;
                }
            }
            None => {
                self.idx.insert(n.to_string(), self.slots.len());
                self.slots.push(Some((n.to_string(), v)));
            }
        }
    }
    fn pop(&mut self, n: &str) {
        if let Some(i) = self.idx.remove(n) {
            self.slots[i] = None;
        }
    }
    fn contains(&self, n: &str) -> bool {
        self.idx.contains_key(n)
    }
    fn iter(&self) -> impl Iterator<Item = &(String, V)> {
        self.slots.iter().flatten()
    }
}

fn join(a: Option<St>, b: Option<St>) -> Option<St> {
    let a = match a {
        None => return b,
        Some(a) => a,
    };
    let b = match b {
        None => return Some(a),
        Some(b) => b,
    };
    let mut out = St::default();
    for (n, v) in a.iter() {
        if let Some(bv) = b.get(n) {
            out.set(n, if bv == *v { *v } else { V::Maybe });
        }
    }
    Some(out)
}

fn is_coll(ty: &Option<String>) -> bool {
    match ty {
        Some(k) => key_is_collection(k),
        None => false,
    }
}

/// name -> `take` flags of the program's functions (what Python reads from `s.funcs[name].params[i].take`)
pub type Takes = HashMap<String, Vec<bool>>;

struct Ownership<'a> {
    funcs: &'a Takes,
    bor: HashSet<String>,
    /// name -> "move" | "borrow" of the outermost call being checked (shared by nested calls)
    track: Option<Track>,
}

type Track = HashMap<String, &'static str>;

impl<'a> Ownership<'a> {
    fn run(&mut self, f: &Function) -> Res<()> {
        self.bor = f.params.iter().filter(|p| key_is_collection(&p.ty) && !p.take).map(|p| p.name.clone()).collect();
        let mut st = St::default();
        for p in f.params.iter().filter(|p| p.take) {
            st.set(&p.name, V::Live);
        }
        self.block(&f.body, st)?;
        Ok(())
    }

    fn block(&mut self, stmts: &[Stmt], st: St) -> Res<Option<St>> {
        let mut declared: Vec<String> = Vec::new();
        let mut cur: Option<St> = Some(st);
        for x in stmts {
            let s = match cur.take() {
                Some(s) => s,
                None => break,
            };
            cur = self.stmt(x, s, &mut declared)?;
        }
        if let Some(s) = cur.as_mut() {
            for n in &declared {
                s.pop(n);
            }
        }
        Ok(cur)
    }

    fn stmt(&mut self, x: &Stmt, mut st: St, declared: &mut Vec<String>) -> Res<Option<St>> {
        match x {
            Stmt::Let(l) => {
                self.consume(&l.value, &mut st, "let")?;
                if key_is_collection(&l.ty) {
                    st.set(&l.name, V::Live);
                    declared.push(l.name.clone());
                }
                Ok(Some(st))
            }
            Stmt::Assign(a) => {
                self.consume(&a.value, &mut st, "assign")?;
                if st.contains(&a.name) {
                    st.set(&a.name, V::Live);
                }
                Ok(Some(st))
            }
            Stmt::IndexAssign(a) => {
                self.expr(&a.index, &mut st)?;
                self.expr(&a.value, &mut st)?;
                Ok(Some(st))
            }
            Stmt::FieldAssign(a) => {
                self.expr(&a.value, &mut st)?;
                Ok(Some(st))
            }
            Stmt::If(i) => {
                self.expr(&i.cond, &mut st)?;
                let a = self.block(&i.then, st.clone())?;
                let b = self.block(&i.els, st.clone())?;
                Ok(join(a, b))
            }
            Stmt::While(w) => {
                let entry = st.clone();
                self.expr(&w.cond, &mut st)?;
                let end = self.block(&w.body, st.clone())?;
                if let Some(end) = &end {
                    for (n, v) in entry.iter() {
                        if *v == V::Live && end.get(n) != Some(V::Live) {
                            return Err(err(
                                w.line,
                                w.col,
                                "foreign_loop_move",
                                "moved in the loop body and not restored",
                                format!(
                                    "{} must be live again at the end of every path of the body: reassign it, e.g. \
                                     {} = f(move {}, ..), or do not consume it inside the loop",
                                    n, n, n
                                ),
                            ));
                        }
                    }
                }
                Ok(join(Some(st), end))
            }
            Stmt::Return(r) => {
                if let Some(v) = &r.value {
                    self.consume(v, &mut st, "return")?;
                }
                Ok(None)
            }
            Stmt::ExprStmt(e) => {
                self.expr(&e.expr, &mut st)?;
                Ok(Some(st))
            }
            Stmt::Match(m) => {
                self.expr(&m.scrutinee, &mut st)?;
                let mut out: Option<St> = None;
                let mut first = true;
                for a in &m.arms {
                    let r = self.block(&a.body, st.clone())?;
                    out = if first { r } else { join(out, r) };
                    first = false;
                }
                Ok(out)
            }
            // Assert: contract, not subject to liveness
            Stmt::Assert(_) => Ok(Some(st)),
        }
    }

    // ---- uses ----
    fn use_(&self, name: &str, line: i64, col: i64, st: &St) -> Res<()> {
        match st.get(name) {
            Some(V::Dead) => Err(err(
                line,
                col,
                "foreign_move",
                "use after move",
                format!("{} was moved earlier; reassign it before using it again, or avoid the move", name),
            )),
            Some(V::Maybe) => Err(err(
                line,
                col,
                "foreign_move",
                "binding may have been moved",
                format!("{} is moved on some paths; make every path leave it live, or do not use it afterwards", name),
            )),
            _ => Ok(()),
        }
    }

    fn mv(&mut self, e: &Move, st: &mut St, consuming: bool, tracked: bool) -> Res<()> {
        let (line, col) = (e.line, e.col);
        if !is_coll(&e.ty) {
            return Err(err(
                line,
                col,
                "foreign_move",
                "move of a non-collection value",
                "move applies to Vec, HashMap and String bindings only; use the value directly",
            ));
        }
        let n = e.name.as_str();
        if let (true, Some(t)) = (tracked, self.track.as_ref()) {
            if let Some(kind) = t.get(n) {
                if *kind == "move" {
                    return Err(err(
                        line,
                        col,
                        "foreign_move",
                        "consumed twice",
                        format!("consume {} at most once per call", n),
                    ));
                }
                return Err(err(
                    line,
                    col,
                    "foreign_borrow",
                    "borrowed and moved in one call",
                    format!("do not pass {} both read-only and with move in one call", n),
                ));
            }
        }
        self.use_(n, line, col, st)?;
        if !consuming {
            return Err(err(
                line,
                col,
                "foreign_move",
                "move only where ownership is consumed",
                "use move for a take argument, a let initializer, an assignment or return",
            ));
        }
        if self.bor.contains(n) {
            // G10 specifies foreign_borrow; the established G6 diagnostic stays for the other types.
            let code = if e.ty.as_deref() == Some("file") { "foreign_borrow" } else { "foreign_move" };
            return Err(err(
                line,
                col,
                code,
                "moving a borrowed parameter",
                format!("{} is a read parameter; declare it `take {}: ...` to consume it", n, n),
            ));
        }
        st.set(n, V::Dead);
        if let (true, Some(t)) = (tracked, self.track.as_mut()) {
            t.insert(n.to_string(), "move");
        }
        Ok(())
    }

    /// let initializer / assignment / return value
    fn consume(&mut self, e: &Expr, st: &mut St, pos: &str) -> Res<()> {
        match e {
            Expr::Move(m) => self.mv(m, st, true, false),
            Expr::Var(v) if is_coll(&v.ty) => {
                self.use_(&v.name, v.line, v.col, st)?;
                if self.bor.contains(&v.name) {
                    if pos == "return" {
                        return Err(err(
                            v.line,
                            v.col,
                            "foreign_borrow",
                            "borrowed return",
                            format!("{} is a read parameter; declare it `take`", v.name),
                        ));
                    }
                    return Err(err(
                        v.line,
                        v.col,
                        "foreign_borrow",
                        "borrowed alias",
                        format!("{} is a read parameter and cannot be aliased", v.name),
                    ));
                }
                if pos == "return" {
                    return Err(err(
                        v.line,
                        v.col,
                        "foreign_move",
                        "returning an owned binding without move",
                        format!("write return move {};", v.name),
                    ));
                }
                Err(err(
                    v.line,
                    v.col,
                    "foreign_move",
                    "alias of an owned binding without move",
                    format!("write move {}", v.name),
                ))
            }
            _ => self.expr(e, st),
        }
    }

    // ---- expressions ----
    fn expr(&mut self, e: &Expr, st: &mut St) -> Res<()> {
        match e {
            Expr::Var(v) => {
                if is_coll(&v.ty) {
                    self.use_(&v.name, v.line, v.col, st)?;
                }
                Ok(())
            }
            Expr::Move(m) => self.mv(m, st, false, false),
            Expr::Call(c) => self.call(c, st),
            Expr::Binary(b) if b.op == "&&" || b.op == "||" => {
                self.expr(&b.left, st)?;
                let before = st.clone();
                self.expr(&b.right, st)?;
                // the right operand runs conditionally
                let joined = join(Some(before), Some(st.clone()));
                if let Some(j) = joined {
                    *st = j;
                }
                Ok(())
            }
            _ => {
                for k in expr_kids(e) {
                    self.expr(k, st)?;
                }
                Ok(())
            }
        }
    }

    fn call(&mut self, e: &Call, st: &mut St) -> Res<()> {
        let takes: Vec<bool> = match catalog_fn(&e.name) {
            Some(f) => f.params.iter().map(|p| p.take).collect(),
            None => match self.funcs.get(&e.name) {
                Some(t) => t.clone(),
                None => vec![false; e.args.len()],
            },
        };
        // nested calls share the outermost call's track (audit R1)
        let outer = self.track.is_some();
        if !outer {
            self.track = Some(HashMap::new());
        }
        let r = self.call_args(e, st, &takes);
        if !outer {
            self.track = None;
        }
        r
    }

    fn call_args(&mut self, e: &Call, st: &mut St, takes: &[bool]) -> Res<()> {
        for (arg, take) in e.args.iter().zip(takes.iter()) {
            if *take {
                match arg {
                    Expr::Move(m) => self.mv(m, st, true, true)?,
                    Expr::Var(v) if is_coll(&v.ty) => {
                        self.use_(&v.name, v.line, v.col, st)?;
                        if self.bor.contains(&v.name) {
                            return Err(err(
                                v.line,
                                v.col,
                                "foreign_move",
                                "moving a borrowed parameter",
                                format!("{} is a read parameter; declare it `take {}: ...` to consume it", v.name, v.name),
                            ));
                        }
                        return Err(err(
                            v.line,
                            v.col,
                            "foreign_move",
                            "missing move in a consuming argument",
                            format!("write move {}", v.name),
                        ));
                    }
                    _ => self.expr(arg, st)?,
                }
            } else {
                match arg {
                    Expr::Move(m) => self.mv(m, st, false, true)?,
                    Expr::Var(v) if is_coll(&v.ty) => {
                        if self.track.as_ref().and_then(|t| t.get(&v.name)) == Some(&"move") {
                            return Err(err(
                                v.line,
                                v.col,
                                "foreign_borrow",
                                "borrowed and moved in one call",
                                format!("do not pass {} both read-only and with move in one call", v.name),
                            ));
                        }
                        self.use_(&v.name, v.line, v.col, st)?;
                        if let Some(t) = self.track.as_mut() {
                            t.entry(v.name.clone()).or_insert("borrow");
                        }
                    }
                    _ => self.expr(arg, st)?,
                }
            }
        }
        Ok(())
    }
}

/// ownership/liveness of one typed, non-foreign function; funcs: name -> `take` flags of the program's functions
pub fn check_ownership(f: &Function, funcs: &Takes) -> Res<()> {
    Ownership { funcs, bor: HashSet::new(), track: None }.run(f)
}

// ---------------------------------------------------------------------------
// A0 guard (section 10.5)
// ---------------------------------------------------------------------------
type Cands = Vec<(i64, i64)>;

fn key_contains_collection(key: &str) -> bool {
    match GType::try_from_key(key) {
        Ok(t) => t.contains_collection(),
        Err(_) => false,
    }
}

fn g6_expr(e: &Expr, out: &mut Cands) {
    match e {
        Expr::Move(m) => out.push((m.line, m.col)),
        Expr::Call(c) => {
            if let Some(t) = &c.ty {
                if key_contains_collection(t) {
                    out.push((c.line, c.col));
                }
            }
            for a in &c.args {
                g6_expr(a, out);
            }
        }
        Expr::Unary(x) => g6_expr(&x.operand, out),
        Expr::Binary(x) => {
            g6_expr(&x.left, out);
            g6_expr(&x.right, out);
        }
        Expr::Index(x) => {
            g6_expr(&x.array, out);
            g6_expr(&x.index, out);
        }
        Expr::Ctor(x) => {
            if let Some(a) = &x.arg {
                g6_expr(a, out);
            }
        }
        Expr::Quant(x) => {
            g6_expr(&x.lo, out);
            g6_expr(&x.hi, out);
            g6_expr(&x.body, out);
        }
        Expr::StructLit(x) => {
            for f in &x.fields {
                g6_expr(&f.value, out);
            }
        }
        Expr::EnumCtor(x) => {
            for a in &x.args {
                g6_expr(a, out);
            }
        }
        Expr::FieldAccess(x) => g6_expr(&x.base, out),
        Expr::IsVariant(x) => g6_expr(&x.value, out),
        Expr::VariantField(x) => g6_expr(&x.value, out),
        Expr::InoutArg(x) => g6_expr(&x.expr, out), // G5 A0
        Expr::IntLit(_) | Expr::BoolLit(_) | Expr::StrLit(_) | Expr::Var(_) => {}
    }
}

fn g6_stmts(stmts: &[Stmt], out: &mut Cands) {
    for s in stmts {
        match s {
            Stmt::Let(l) => {
                if key_contains_collection(&l.ty) {
                    out.push((l.line, l.col));
                }
                g6_expr(&l.value, out);
            }
            Stmt::Assign(a) => g6_expr(&a.value, out),
            Stmt::IndexAssign(a) => {
                g6_expr(&a.index, out);
                g6_expr(&a.value, out);
            }
            Stmt::If(i) => {
                g6_expr(&i.cond, out);
                g6_stmts(&i.then, out);
                g6_stmts(&i.els, out);
            }
            Stmt::While(w) => {
                g6_expr(&w.cond, out);
                for inv in &w.invariants {
                    g6_expr(inv, out);
                }
                g6_expr(&w.decreases, out);
                g6_stmts(&w.body, out);
            }
            Stmt::Return(r) => {
                if let Some(v) = &r.value {
                    g6_expr(v, out);
                }
            }
            Stmt::Assert(a) => g6_expr(&a.cond, out),
            Stmt::ExprStmt(e) => g6_expr(&e.expr, out),
            Stmt::FieldAssign(f) => g6_expr(&f.value, out),
            Stmt::Match(m) => {
                g6_expr(&m.scrutinee, out);
                for a in &m.arms {
                    g6_stmts(&a.body, out);
                }
            }
        }
    }
}

/// first G6 construct of a checked program -> (line, col, what) or None. Source order: functions in order,
/// the signature (foreign declaration, take or collection parameter/result) before the body.
pub fn first_g6_use(prog: &Program) -> Option<(i64, i64, String)> {
    for f in &prog.functions {
        if f.foreign.is_some() {
            return Some((f.line, f.col, format!("trusted rust fn {}", f.name)));
        }
        for p in &f.params {
            if p.take || key_contains_collection(&p.ty) {
                return Some((f.line, f.col, format!("parameter {}", p.name)));
            }
        }
        if key_contains_collection(&f.ret) {
            return Some((f.line, f.col, format!("result type of {}", f.name)));
        }
        let mut cands: Cands = Vec::new();
        g6_stmts(&f.body, &mut cands);
        // min by (line, col); the first one wins on a tie, like Python's min(key=..)
        let mut best: Option<(i64, i64)> = None;
        for c in cands {
            if best.map_or(true, |b| c < b) {
                best = Some(c);
            }
        }
        if let Some((l, c)) = best {
            return Some((l, c, "a G6 construct".to_string()));
        }
    }
    None
}

/// PruvError (unsupported_type) for the first G6 construct, or None. Run right after type checking.
pub fn g6_unimplemented_error(prog: &Program, stage: &str) -> Option<PruvError> {
    let (line, col, _what) = first_g6_use(prog)?;
    Some(PruvError::new(
        stage,
        line,
        col,
        "unsupported_type",
        "G6 foreign calls and collections are not implemented by the llvm codegen layer yet",
        "avoid trusted rust fn, Vec, HashMap, String, take and move for now",
    ))
}

// ---------------------------------------------------------------------------
// G10 A0 guard (counterpart of foreign.py g10_unimplemented_error)
// ---------------------------------------------------------------------------

fn key_has_file(key: &str) -> bool {
    fn has(t: &GType) -> bool {
        (t.owner.is_none() && t.name == "file") || t.args.iter().any(has)
    }
    match GType::try_from_key(key) {
        Ok(t) => has(&t),
        Err(_) => false,
    }
}

fn ty_has_file(t: &Option<String>) -> bool {
    t.as_deref().map_or(false, key_has_file)
}

fn g10_expr(e: &Expr) -> bool {
    let own = match e {
        Expr::Call(c) => (is_catalog(&c.name) && c.name.starts_with("file_")) || ty_has_file(&c.ty),
        Expr::Var(v) => ty_has_file(&v.ty),
        Expr::Move(m) => ty_has_file(&m.ty),
        _ => false,
    };
    own || expr_kids(e).into_iter().any(g10_expr)
}

fn g10_stmts(stmts: &[Stmt]) -> bool {
    stmts.iter().any(|s| match s {
        Stmt::Let(l) => key_has_file(&l.ty) || g10_expr(&l.value),
        Stmt::Assign(a) => g10_expr(&a.value),
        Stmt::IndexAssign(a) => g10_expr(&a.index) || g10_expr(&a.value),
        Stmt::If(i) => g10_expr(&i.cond) || g10_stmts(&i.then) || g10_stmts(&i.els),
        Stmt::While(w) => {
            g10_expr(&w.cond) || w.invariants.iter().any(g10_expr) || g10_expr(&w.decreases) || g10_stmts(&w.body)
        }
        Stmt::Return(r) => r.value.as_ref().map_or(false, g10_expr),
        Stmt::Assert(a) => g10_expr(&a.cond),
        Stmt::ExprStmt(e) => g10_expr(&e.expr),
        Stmt::FieldAssign(f) => g10_expr(&f.value),
        Stmt::Match(m) => g10_expr(&m.scrutinee) || m.arms.iter().any(|a| g10_stmts(&a.body)),
    })
}

/// G10 A0 guard: the first function that uses `File` or a `file_*` operation -> codegen/unsupported_type.
/// G10 A2: runs after verification (or its bypass) on LLVM paths.
pub fn g10_unimplemented_error(prog: &Program) -> Option<PruvError> {
    for f in &prog.functions {
        let uses = f.params.iter().any(|p| key_has_file(&p.ty))
            || key_has_file(&f.ret)
            || f.requires.iter().any(g10_expr)
            || f.ensures.iter().any(g10_expr)
            || f.decreases.as_ref().map_or(false, g10_expr)
            || g10_stmts(&f.body);
        if uses {
            return Some(PruvError::new(
                "codegen",
                f.line,
                f.col,
                "unsupported_type",
                "files (G10) are not implemented by the llvm codegen layer yet",
                "avoid File and file_* operations for now",
            ));
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn path_rule() {
        assert!(path_ok("::std::cmp::min"));
        assert!(path_ok("::a"));
        assert!(!path_ok("std::cmp"));
        assert!(!path_ok("::"));
        assert!(!path_ok("::a::"));
        assert!(!path_ok(":::a"));
        assert!(!path_ok("::1a"));
        assert!(!path_ok("::a b"));
    }

    #[test]
    fn catalog_shapes() {
        assert_eq!(CATALOG_NAMES.len(), 23);
        for n in CATALOG_NAMES.iter() {
            assert!(catalog_fn(n).is_some());
        }
        assert!(catalog_fn("len").is_none());
        let f = catalog_fn("vec_push").unwrap();
        assert!(f.params[0].take && !f.params[1].take);
        assert_eq!(f.tparams.len(), 1);
    }

    #[test]
    fn join_keeps_order_and_maybe() {
        let mut a = St::default();
        a.set("x", V::Live);
        a.set("y", V::Dead);
        let mut b = St::default();
        b.set("y", V::Dead);
        b.set("x", V::Dead);
        let j = join(Some(a), Some(b)).unwrap();
        assert_eq!(j.iter().cloned().collect::<Vec<_>>(), vec![("x".to_string(), V::Maybe), ("y".to_string(), V::Dead)]);
    }
}
