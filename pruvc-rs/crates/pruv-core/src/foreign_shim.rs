//! G6 A3 (docs/G6_SPEC.md section 13; counterpart of pruvc/foreign_shim.py): the Rust shim of the LLVM bridge.
//!
//! `build_shim` returns the text of `mod pruv_g6_shim { .. }`, which `bindings::gen_bindings_with` appends to the generated
//! Rust host bindings of a G6 program. The module contains the contract/G6 preludes the helpers need, the bridge runtime,
//! exactly the A2 boundary helpers the program uses (texts produced by `codegen::shim_helpers`, i.e. a Gen created for the
//! same program and check mode), one `#[no_mangle] pub extern "C"` adapter per helper named `pruv_g6_v1_<helper name>`,
//! one `pruv_g6_v1_drop__<C>` and `pruv_g6_v1_len__<C>` per collection type <C>, `pruv_g6_v1_string_bytes` (only when
//! string_to_str is used) and `#[no_mangle] pub static pruv_g6_bridge_v1: u8 = 1;`.
//! <C> is the G3 structural encoding of the collection type: vec__i, vec__b, hashmap__i__b, string.
//! Output must be byte-identical to Python's.

use crate::ast::*;
use crate::codegen::{
    contract_prelude_g6, shim_helpers, CONTRACT_PRELUDE_BOOL, CONTRACT_PRELUDE_STR, CONTRACT_PRELUDE_U8, FILE_PRELUDE, G6_PRELUDE,
};
use crate::emit_common::rty_g;
use crate::foreign::{is_catalog, is_catalog_contract_only, FILE_OBSERVERS};
use crate::gtype::{encode, GType};
use crate::llvmgen::{expr_ty, is_collection};
use crate::typeinfo::{uses_array_type, uses_str};
use std::collections::{BTreeMap, HashMap};

type R<T> = Result<T, String>;

pub const PREFIX: &str = "pruv_g6_v1_";
pub const BRIDGE_SYM: &str = "pruv_g6_bridge_v1";
pub const STRING_BYTES_SYM: &str = "pruv_g6_v1_string_bytes";

/// the A2 helper name of a catalog instance (ForeignGen.catalog_helper)
pub fn helper_name(op: &str, src: &[GType]) -> R<String> {
    let mut s = format!("pruv_g6_{}", op);
    for t in src {
        s.push_str("__");
        s.push_str(&encode(t)?);
    }
    Ok(s)
}

pub fn adapter_sym(helper: &str) -> String {
    format!("{}{}", PREFIX, helper)
}

/// <C>: G3 encoding of a collection type
pub fn cname(t: &GType) -> R<String> {
    match t.name.as_str() {
        "vec" => {
            let a = t.args.first().ok_or_else(|| "list index out of range".to_string())?;
            Ok(format!("vec__{}", encode(a)?))
        }
        "hashmap" => {
            if t.args.len() < 2 {
                return Err("list index out of range".to_string());
            }
            Ok(format!("hashmap__{}__{}", encode(&t.args[0])?, encode(&t.args[1])?))
        }
        "file" => Ok("File".to_string()),
        _ => Ok("string".to_string()),
    }
}

fn parse_key(key: &str) -> R<GType> {
    GType::try_from_key(key)
}

/// `pruv_g6_v1_drop__<C>` of the collection type key `key`
pub fn drop_sym(key: &str) -> R<String> {
    Ok(format!("{}drop__{}", PREFIX, cname(&parse_key(key)?)?))
}

/// `pruv_g6_v1_len__<C>` of the collection type key `key`
pub fn len_sym(key: &str) -> R<String> {
    Ok(format!("{}len__{}", PREFIX, cname(&parse_key(key)?)?))
}

/// (low, src) type arguments of a catalog call as codegen.catalog_call computes them
pub fn inst_types(e: &Call) -> (Vec<GType>, Vec<GType>) {
    match &e.inst {
        None => (Vec::new(), Vec::new()),
        Some(inst) => {
            let low = inst.args.clone();
            let mut src = inst.src_args.clone().unwrap_or_else(|| low.clone());
            if src.is_empty() && !low.is_empty() {
                src = low.clone();
            }
            (low, src)
        }
    }
}

// ---------------------------------------------------------------------------
// program scan
// ---------------------------------------------------------------------------

/// A visited AST node: a `let` statement or an expression (every dataclass node of a body that carries a type).
pub enum Node<'a> {
    Let(&'a Let),
    Expr(&'a Expr),
}

pub fn walk_stmts(stmts: &[Stmt], f: &mut dyn FnMut(Node<'_>)) {
    for s in stmts {
        walk_stmt(s, f);
    }
}

fn walk_stmt(s: &Stmt, f: &mut dyn FnMut(Node<'_>)) {
    match s {
        Stmt::Let(l) => {
            f(Node::Let(l));
            walk_expr(&l.value, f);
        }
        Stmt::Assign(a) => walk_expr(&a.value, f),
        Stmt::IndexAssign(a) => {
            walk_expr(&a.index, f);
            walk_expr(&a.value, f);
        }
        Stmt::If(i) => {
            walk_expr(&i.cond, f);
            walk_stmts(&i.then, f);
            walk_stmts(&i.els, f);
        }
        Stmt::While(w) => {
            walk_expr(&w.cond, f);
            for inv in &w.invariants {
                walk_expr(inv, f);
            }
            walk_expr(&w.decreases, f);
            walk_stmts(&w.body, f);
        }
        Stmt::Return(r) => {
            if let Some(v) = &r.value {
                walk_expr(v, f);
            }
        }
        Stmt::Assert(a) => walk_expr(&a.cond, f),
        Stmt::ExprStmt(x) => walk_expr(&x.expr, f),
        Stmt::FieldAssign(x) => walk_expr(&x.value, f),
        Stmt::Match(m) => {
            walk_expr(&m.scrutinee, f);
            for arm in &m.arms {
                walk_stmts(&arm.body, f);
            }
        }
    }
}

fn walk_expr(e: &Expr, f: &mut dyn FnMut(Node<'_>)) {
    f(Node::Expr(e));
    match e {
        Expr::Move(_) | Expr::IntLit(_) | Expr::BoolLit(_) | Expr::StrLit(_) | Expr::Var(_) => {}
        Expr::InoutArg(x) => walk_expr(&x.expr, f), // G5 A0
        Expr::Unary(x) => walk_expr(&x.operand, f),
        Expr::Binary(x) => {
            walk_expr(&x.left, f);
            walk_expr(&x.right, f);
        }
        Expr::Call(x) => {
            for a in &x.args {
                walk_expr(a, f);
            }
        }
        Expr::Index(x) => {
            walk_expr(&x.array, f);
            walk_expr(&x.index, f);
        }
        Expr::Ctor(x) => {
            if let Some(a) = &x.arg {
                walk_expr(a, f);
            }
        }
        Expr::Quant(x) => {
            walk_expr(&x.lo, f);
            walk_expr(&x.hi, f);
            walk_expr(&x.body, f);
        }
        Expr::StructLit(x) => {
            for fi in &x.fields {
                walk_expr(&fi.value, f);
            }
        }
        Expr::EnumCtor(x) => {
            for a in &x.args {
                walk_expr(a, f);
            }
        }
        Expr::FieldAccess(x) => walk_expr(&x.base, f),
        Expr::IsVariant(x) => walk_expr(&x.value, f),
        Expr::VariantField(x) => walk_expr(&x.value, f),
    }
}

type Cats = HashMap<String, (String, Vec<GType>)>;
type Colls = BTreeMap<String, GType>;

fn add_coll(colls: &mut Colls, key: &str, err: &mut Option<String>) {
    if !is_collection(key) {
        return;
    }
    match parse_key(key).and_then(|g| cname(&g).map(|c| (c, g))) {
        Ok((c, g)) => {
            colls.entry(c).or_insert(g);
        }
        Err(e) => {
            if err.is_none() {
                *err = Some(e);
            }
        }
    }
}

/// (cats, colls, trusted, observers): cats: helper name -> (op, low types); colls: <C> -> collection type (sorted by <C>);
/// trusted: name -> Function of the trusted declarations called from a body;
/// observers: File helpers in Python catalog insertion order (including implicit file_size).
fn collect<'a>(prog: &'a Program) -> R<(Cats, Colls, HashMap<String, &'a Function>, Vec<(String, Vec<GType>)>)> {
    let mut cats: Cats = HashMap::new();
    let mut observers = Vec::new();
    let mut colls: Colls = BTreeMap::new();
    let mut trusted: HashMap<String, &'a Function> = HashMap::new();
    let mut fmap: HashMap<&str, &'a Function> = HashMap::new();
    for f in &prog.functions {
        fmap.entry(f.name.as_str()).or_insert(f);
    }
    let mut err: Option<String> = None;
    for f in &prog.functions {
        if f.foreign.is_some() {
            continue;
        }
        for p in &f.params {
            add_coll(&mut colls, &p.ty, &mut err);
        }
        add_coll(&mut colls, &f.ret, &mut err);
        let mut visit = |n: Node<'_>| match n {
            Node::Let(l) => add_coll(&mut colls, &l.ty, &mut err),
            Node::Expr(e) => {
                if let Some(t) = expr_ty(e) {
                    add_coll(&mut colls, t, &mut err);
                }
                if let Expr::Call(c) = e {
                    if is_catalog(&c.name) && !is_catalog_contract_only(&c.name) {
                        let (low, src) = inst_types(c);
                        match helper_name(&c.name, &src) {
                            Ok(h) => {
                                if !cats.contains_key(&h) && FILE_OBSERVERS.contains(&c.name.as_str()) {
                                    observers.push((c.name.clone(), low.clone()));
                                }
                                cats.entry(h).or_insert((c.name.clone(), low));
                                if c.name == "file_byte" {
                                    let size = "pruv_g6_file_size".to_string();
                                    if !cats.contains_key(&size) {
                                        observers.push(("file_size".to_string(), vec![]));
                                    }
                                    cats.entry(size).or_insert(("file_size".to_string(), vec![]));
                                }
                            }
                            Err(e2) => {
                                if err.is_none() {
                                    err = Some(e2);
                                }
                            }
                        }
                    } else if let Some(tf) = fmap.get(c.name.as_str()) {
                        if tf.foreign.is_some() {
                            trusted.entry(c.name.clone()).or_insert(*tf);
                        }
                    }
                }
            }
        };
        walk_stmts(&f.body, &mut visit);
        for e in f.requires.iter().chain(f.ensures.iter()) {
            walk_expr(e, &mut |n| {
                if let Node::Expr(Expr::Call(c)) = &n {
                    if FILE_OBSERVERS.contains(&c.name.as_str()) {
                        visit(n);
                    }
                }
            });
        }
        if let Some(e) = err.take() {
            return Err(e);
        }
    }
    Ok((cats, colls, trusted, observers))
}

// ---------------------------------------------------------------------------
// bridge runtime text
// ---------------------------------------------------------------------------
const BRIDGE_RUNTIME: &str = r##"mod pruv_g6_c {
    extern "C" {
        pub fn fflush(stream: *mut ::std::ffi::c_void) -> i32;
        pub fn atexit(cb: extern "C" fn()) -> i32;
    }
}
type PruvH = *mut ::std::ffi::c_void;
#[no_mangle]
pub static pruv_g6_bridge_v1: u8 = 1;
static PRUV_G6_LIVE: ::std::sync::atomic::AtomicI64 = ::std::sync::atomic::AtomicI64::new(0);
static PRUV_G6_ONCE: ::std::sync::Once = ::std::sync::Once::new();
extern "C" fn pruv_g6_report() {
    let n: i64 = PRUV_G6_LIVE.load(::std::sync::atomic::Ordering::SeqCst);
    let _ = ::std::io::Write::write_fmt(&mut ::std::io::stderr(), format_args!("pruv-g6-live: {}\n", n));
}
fn pruv_g6_register() {
    PRUV_G6_ONCE.call_once(|| {
        if ::std::env::var("PRUV_G6_COUNT").map(|v| v == "1").unwrap_or(false) {
            unsafe { pruv_g6_c::atexit(pruv_g6_report); }
        }
    });
}
fn pruv_g6_guard<R, F: FnOnce() -> R>(f: F) -> R {
    match ::std::panic::catch_unwind(::std::panic::AssertUnwindSafe(f)) {
        Ok(r) => r,
        Err(_) => {
            unsafe { pruv_g6_c::fflush(::std::ptr::null_mut()); }
            ::std::process::exit(101)
        }
    }
}
fn pruv_g6_b(x: i64) -> bool { match x { 0 => false, 1 => true, _ => pruv_g6_repr("bool") } }
fn pruv_g6_new<T>(v: T) -> PruvH {
    pruv_g6_register();
    PRUV_G6_LIVE.fetch_add(1, ::std::sync::atomic::Ordering::SeqCst);
    ::std::boxed::Box::into_raw(::std::boxed::Box::new(v)) as PruvH
}
fn pruv_g6_ref<'a, T>(h: PruvH) -> &'a T {
    if h.is_null() { pruv_g6_repr("null handle") }
    unsafe { &*(h as *const T) }
}
fn pruv_g6_upd<T: Default, F: FnOnce(T) -> T>(h: PruvH, f: F) -> PruvH {
    if h.is_null() { pruv_g6_repr("null handle") }
    unsafe {
        let p: *mut T = h as *mut T;
        let old: T = ::std::mem::take(&mut *p);
        let new: T = f(old);
        *p = new;
    }
    h
}
fn pruv_g6_free<T>(h: PruvH) {
    if h.is_null() { return; }
    unsafe { drop(::std::boxed::Box::from_raw(h as *mut T)); }
    PRUV_G6_LIVE.fetch_sub(1, ::std::sync::atomic::Ordering::SeqCst);
}
fn pruv_g6_nlen(n: i64) -> usize { if n < 0 || n > (1i64 << 40) { pruv_g6_repr("length") } n as usize }
fn pruv_g6_slice<'a, T>(p: *const T, n: i64) -> &'a [T] {
    let n: usize = pruv_g6_nlen(n);
    if n == 0 { return &[]; }
    if p.is_null() { pruv_g6_repr("NULL data") }
    if (p as usize) % ::std::mem::align_of::<T>() != 0 { pruv_g6_repr("alignment") }
    unsafe { ::std::slice::from_raw_parts(p, n) }
}
fn pruv_g6_bools<'a>(p: *const u8, n: i64) -> &'a [bool] {
    let s: &[u8] = pruv_g6_slice::<u8>(p, n);
    for b in s.iter() { if *b > 1 { pruv_g6_repr("bool") } }
    unsafe { ::std::slice::from_raw_parts(s.as_ptr() as *const bool, s.len()) }
}
fn pruv_g6_str<'a>(p: *const u8, n: i64) -> &'a str {
    match ::std::str::from_utf8(pruv_g6_slice::<u8>(p, n)) { Ok(s) => s, Err(_) => pruv_g6_repr("utf-8") }
}
fn pruv_g6_out(p: *mut i64) -> *mut i64 { if p.is_null() { pruv_g6_repr("null output") } p }
"##;

const MOD_ALLOW: &str = "#[allow(dead_code, unused_imports, unused_variables, unused_mut, unused_parens, unused_unsafe, non_snake_case, non_camel_case_types, non_upper_case_globals, improper_ctypes_definitions, unreachable_code, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]";

// ---------------------------------------------------------------------------
// adapters
// ---------------------------------------------------------------------------
fn cin(t: &GType, x: &str) -> String {
    if *t == GType::i64() {
        x.to_string()
    } else {
        format!("pruv_g6_b({})", x)
    }
}

fn cout(t: &GType, x: &str) -> String {
    if *t == GType::i64() {
        x.to_string()
    } else {
        format!("({}) as i64", x)
    }
}

fn rty_t(t: &GType) -> String {
    rty_g(t, false)
}

fn fn_text(sym: &str, params: &str, ret: Option<&str>, body: &str) -> String {
    let r = match ret {
        None => String::new(),
        Some(r) => format!(" -> {}", r),
    };
    format!("#[no_mangle]\npub extern \"C\" fn {}({}){} {{\n    {}\n}}\n", sym, params, r, body)
}

fn low_at(low: &[GType], i: usize) -> R<&GType> {
    low.get(i).ok_or_else(|| "tuple index out of range".to_string())
}

fn cat_adapter(helper: &str, op: &str, low: &[GType]) -> R<String> {
    let s = adapter_sym(helper);
    if op.starts_with("file_") {
        return Ok(file_adapter(&s, helper, op));
    }
    let mut t: Option<&GType> = None;
    let mut k: Option<&GType> = None;
    let mut v: Option<&GType> = None;
    let c: String;
    if matches!(op, "vec_new" | "vec_push" | "vec_get") {
        let tt = low_at(low, 0)?;
        t = Some(tt);
        c = rty_t(&GType::new("vec", vec![tt.clone()]));
    } else if matches!(op, "map_new" | "map_get" | "map_insert") {
        let kk = low_at(low, 0)?;
        let vv = low_at(low, 1)?;
        k = Some(kk);
        v = Some(vv);
        c = rty_t(&GType::new("hashmap", vec![kk.clone(), vv.clone()]));
    } else {
        c = "::std::string::String".to_string();
    }
    match op {
        "vec_new" | "map_new" | "string_new" => Ok(fn_text(
            &s,
            "",
            Some("PruvH"),
            &format!("pruv_g6_guard(|| pruv_g6_new::<{}>({}()))", c, helper),
        )),
        "vec_push" => {
            let t = t.ok_or_else(|| "unreachable".to_string())?;
            Ok(fn_text(
                &s,
                "v: PruvH, x: i64",
                Some("PruvH"),
                &format!(
                    "pruv_g6_guard(|| {{ let pruv_x: {} = {}; pruv_g6_upd::<{}, _>(v, |pruv_o| {}(pruv_o, pruv_x)) }})",
                    rty_t(t),
                    cin(t, "x"),
                    c,
                    helper
                ),
            ))
        }
        "vec_get" => {
            let t = t.ok_or_else(|| "unreachable".to_string())?;
            Ok(fn_text(
                &s,
                "v: PruvH, i: i64",
                Some("i64"),
                &format!(
                    "pruv_g6_guard(|| {{ let pruv_r: {} = {}(pruv_g6_ref::<{}>(v), i); {} }})",
                    rty_t(t),
                    helper,
                    c,
                    cout(t, "pruv_r")
                ),
            ))
        }
        "map_get" => {
            let k = k.ok_or_else(|| "unreachable".to_string())?;
            let v = v.ok_or_else(|| "unreachable".to_string())?;
            Ok(fn_text(
                &s,
                "m: PruvH, k: i64, tag: *mut i64, val: *mut i64",
                None,
                &format!(
                    "pruv_g6_guard(|| {{ let pruv_k: {} = {}; let pruv_r: ::std::option::Option<{}> = {}(pruv_g6_ref::<{}>(m), pruv_k); \
                     let pruv_t: *mut i64 = pruv_g6_out(tag); let pruv_v: *mut i64 = pruv_g6_out(val); \
                     unsafe {{ match pruv_r {{ ::std::option::Option::Some(pruv_x) => {{ *pruv_t = 1; *pruv_v = {}; }} \
                     ::std::option::Option::None => {{ *pruv_t = 0; *pruv_v = 0; }} }} }} }})",
                    rty_t(k),
                    cin(k, "k"),
                    rty_t(v),
                    helper,
                    c,
                    cout(v, "pruv_x")
                ),
            ))
        }
        "map_insert" => {
            let k = k.ok_or_else(|| "unreachable".to_string())?;
            let v = v.ok_or_else(|| "unreachable".to_string())?;
            Ok(fn_text(
                &s,
                "m: PruvH, k: i64, v: i64",
                Some("PruvH"),
                &format!(
                    "pruv_g6_guard(|| {{ let pruv_k: {} = {}; let pruv_v: {} = {}; \
                     pruv_g6_upd::<{}, _>(m, |pruv_o| {}(pruv_o, pruv_k, pruv_v)) }})",
                    rty_t(k),
                    cin(k, "k"),
                    rty_t(v),
                    cin(v, "v"),
                    c,
                    helper
                ),
            ))
        }
        "string_push_str" => Ok(fn_text(
            &s,
            "s: PruvH, p: *const u8, n: i64",
            Some("PruvH"),
            &format!(
                "pruv_g6_guard(|| {{ let pruv_t: &str = pruv_g6_str(p, n); \
                 pruv_g6_upd::<{}, _>(s, |pruv_o| {}(pruv_o, pruv_t)) }})",
                c, helper
            ),
        )),
        "string_byte" => Ok(fn_text(
            &s,
            "s: PruvH, i: i64",
            Some("i64"),
            &format!("pruv_g6_guard(|| {}(pruv_g6_ref::<{}>(s), i))", helper, c),
        )),
        _ => Err(format!("foreign_shim: no adapter for catalog operation {}", op)),
    }
}

fn file_adapter(sym: &str, helper: &str, op: &str) -> String {
    if matches!(op, "file_open_read" | "file_create") {
        return fn_text(sym, "p: *const u8, n: i64", Some("PruvH"),
            &format!("pruv_g6_guard(|| pruv_g6_new({}(pruv_g6_str(p, n))))", helper));
    }
    let mut params = "h: PruvH".to_string();
    let mut arg = "";
    if op == "file_byte" {
        params.push_str(", i: i64");
        arg = ", i";
    }
    if FILE_OBSERVERS.contains(&op) {
        return fn_text(sym, &params, Some("i64"),
            &format!("pruv_g6_guard(|| {}(pruv_g6_ref::<pruv_File>(h){}) as i64)", helper, arg));
    }
    let mut body = String::new();
    if matches!(op, "file_write_str" | "file_write_bytes") {
        params.push_str(", p: *const u8, n: i64");
        arg = ", pruv_data";
        let conv = if op == "file_write_str" { "pruv_g6_str(p, n)" } else { "pruv_g6_slice::<u8>(p, n)" };
        body.push_str(&format!("let pruv_data = {}; ", conv));
    }
    // Consume the box before the A2 helper; File has no Default placeholder.
    body.push_str(r#"if h.is_null() { pruv_g6_repr("null handle") } let f: pruv_File = unsafe { *::std::boxed::Box::from_raw(h as *mut pruv_File) }; PRUV_G6_LIVE.fetch_sub(1, ::std::sync::atomic::Ordering::SeqCst); "#);
    let call = format!("{}(f{})", helper, arg);
    body.push_str(&if op == "file_close" { format!("{} as i64", call) } else { format!("pruv_g6_new({})", call) });
    fn_text(sym, &params, Some(if op == "file_close" { "i64" } else { "PruvH" }),
        &format!("pruv_g6_guard(|| {{ {} }})", body))
}

fn trusted_adapter(f: &Function) -> R<String> {
    let mut params: Vec<String> = Vec::new();
    let mut args: Vec<String> = Vec::new();
    for (i, p) in f.params.iter().enumerate() {
        match p.ty.as_str() {
            "i64" => {
                params.push(format!("a{}: i64", i));
                args.push(format!("a{}", i));
            }
            "bool" => {
                params.push(format!("a{}: i64", i));
                args.push(format!("pruv_g6_b(a{})", i));
            }
            "str" => {
                params.push(format!("a{}: *const u8", i));
                params.push(format!("n{}: i64", i));
                args.push(format!("pruv_g6_str(a{}, n{})", i, i));
            }
            "array" => {
                params.push(format!("a{}: *const i64", i));
                params.push(format!("n{}: i64", i));
                args.push(format!("pruv_g6_slice::<i64>(a{}, n{})", i, i));
            }
            "array_u8" => {
                params.push(format!("a{}: *const u8", i));
                params.push(format!("n{}: i64", i));
                args.push(format!("pruv_g6_slice::<u8>(a{}, n{})", i, i));
            }
            "array_bool" => {
                params.push(format!("a{}: *const u8", i));
                params.push(format!("n{}: i64", i));
                args.push(format!("pruv_g6_bools(a{}, n{})", i, i));
            }
            other => return Err(format!("foreign_shim: unsupported trusted parameter type {}", other)),
        }
    }
    let call = format!("{}({})", f.name, args.join(", "));
    let s = adapter_sym(&f.name);
    let ps = params.join(", ");
    if f.ret == "unit" {
        return Ok(fn_text(&s, &ps, None, &format!("pruv_g6_guard(|| {{ {}; }})", call)));
    }
    if f.ret == "bool" {
        return Ok(fn_text(
            &s,
            &ps,
            Some("i64"),
            &format!("pruv_g6_guard(|| {{ let pruv_r: bool = {}; pruv_r as i64 }})", call),
        ));
    }
    Ok(fn_text(&s, &ps, Some("i64"), &format!("pruv_g6_guard(|| {})", call)))
}

fn coll_adapters(t: &GType) -> R<String> {
    let c = rty_t(t);
    if t.name == "file" {
        return Ok(fn_text(&format!("{}drop__{}", PREFIX, cname(t)?), "h: PruvH", None,
            "pruv_g6_guard(|| pruv_g6_free::<pruv_File>(h))"));
    }
    let mut out = fn_text(
        &format!("{}len__{}", PREFIX, cname(t)?),
        "h: PruvH",
        Some("i64"),
        &format!("pruv_g6_guard(|| pruv_g6_ref::<{}>(h).len() as i64)", c),
    );
    out.push_str(&fn_text(
        &format!("{}drop__{}", PREFIX, cname(t)?),
        "h: PruvH",
        None,
        &format!("pruv_g6_guard(|| pruv_g6_free::<{}>(h))", c),
    ));
    Ok(out)
}

fn string_bytes_adapter() -> String {
    fn_text(
        STRING_BYTES_SYM,
        "h: PruvH, data: *mut *const u8, len: *mut i64",
        None,
        "pruv_g6_guard(|| { let pruv_s: &::std::string::String = pruv_g6_ref::<::std::string::String>(h); \
         if data.is_null() || len.is_null() { pruv_g6_repr(\"null output\") } \
         unsafe { *data = pruv_s.as_ptr(); *len = pruv_s.len() as i64; } })",
    )
}

// ---------------------------------------------------------------------------
// the module
// ---------------------------------------------------------------------------

/// text of `mod pruv_g6_shim` for the (concrete) program prog; deterministic
pub fn build_shim(prog: &Program, verified: bool, _trust_callers: bool, budget: u64, foreign_checks: &str) -> R<String> {
    let (cats, colls, trusted, observers) = collect(prog)?;
    // helper discovery: exactly the A2 helpers (same texts, same mode and budget). The entry checks of the Rust
    // source backend are not emitted here (trust=True): the LLVM entries evaluate requires themselves.
    let items = shim_helpers(prog, verified, budget, foreign_checks, &observers)?;
    let mut out: Vec<String> = Vec::new();
    out.push(MOD_ALLOW.to_string());
    out.push("mod pruv_g6_shim {".to_string());
    let g10 = crate::foreign::uses_files(prog);
    if g10 {
        out.push(FILE_PRELUDE.to_string());
    }
    out.push(contract_prelude_g6());
    if uses_array_type(prog, "array_u8") || g10 {
        out.push(CONTRACT_PRELUDE_U8.to_string());
    }
    if uses_array_type(prog, "array_bool") {
        out.push(CONTRACT_PRELUDE_BOOL.to_string());
    }
    if uses_str(prog) {
        out.push(CONTRACT_PRELUDE_STR.to_string());
    }
    out.push(G6_PRELUDE.to_string());
    out.push(BRIDGE_RUNTIME.to_string());
    let mut adapters: Vec<String> = Vec::new();
    for (name, text) in &items {
        if let Some((op, _)) = cats.get(name) {
            if op == "string_to_str" {
                continue; // replaced by the borrowed view pruv_g6_v1_string_bytes
            }
        }
        if !cats.contains_key(name) && !trusted.contains_key(name) {
            continue; // contract scans (map_updated) are not used by the LLVM entries
        }
        out.push(text.clone());
        if let Some((op, low)) = cats.get(name) {
            adapters.push(cat_adapter(name, op, low)?);
        } else if let Some(f) = trusted.get(name) {
            adapters.push(trusted_adapter(f)?);
        }
    }
    if cats.values().any(|(op, _)| op == "string_to_str") {
        adapters.push(string_bytes_adapter());
    }
    for t in colls.values() {
        adapters.push(coll_adapters(t)?);
    }
    out.extend(adapters);
    out.push("}".to_string());
    let mut s = out.join("\n");
    s.push('\n');
    Ok(s)
}
