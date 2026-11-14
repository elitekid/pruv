//! Pruv -> LLVM IR text generator (a port of llvmgen.py lines 1-1327 plus gen_llvm).
//! Goal: for the same program and mode, byte-identical to the first return value of Python's gen_llvm.
//! Rule: mutable state (temp numbers, label numbers, scopes, temp-free lists, contract environment) is changed in the same order as in Python.
//! Python's None is imitated by the string "None" (the default of V's a/b).

use crate::abi::{abi_of, AbiTarget};
use crate::ast::*;
use crate::typeinfo::{is_array_name, is_user_type, uses_array_type, TypeTable};
use std::collections::{BTreeMap, BTreeSet, HashMap, HashSet};

pub type R<T> = Result<T, String>;

// ---------- G6 A3 (docs/G6_SPEC.md section 13): collections and trusted calls through the shim ----------

pub const G6_UNSUPPORTED_MSG: &str = "G6 foreign calls and collections are not implemented by the llvm codegen layer yet";
pub const G6_UNSUPPORTED_FIX: &str = "avoid trusted rust fn, Vec, HashMap, String, take and move for now";
pub const G6_BRIDGE_DECL: &str = "@pruv_g6_bridge_v1 = external global i8\n";
/// A PruvError (codegen/unsupported_type) raised in the middle of a function body travels through `R<T>` as a string
/// with this prefix and `line:col`; `gen_llvm_concrete_ex` turns it back into the diagnostic.
const G6_DIAG_TAG: &str = "\u{0}g6diag:";

fn g6_diag_err(line: i64, col: i64) -> String {
    format!("{}{}:{}", G6_DIAG_TAG, line, col)
}

/// G9 A3: a PruvError (codegen/unsupported_type, Python `FnGen.g9_unsupported`) raised in the middle of a function body
/// travels like the G6 one: this prefix, then `line:col:what`; `gen_llvm_concrete_ex` turns it back into the diagnostic.
const G9_DIAG_TAG: &str = "\u{0}g9diag:";

fn g9_diag_err(line: i64, col: i64, what: &str) -> String {
    format!("{}{}:{}:{}", G9_DIAG_TAG, line, col, what)
}

/// An owned collection/File type key; never a bound parameter.
pub fn is_collection(t: &str) -> bool {
    if t.starts_with('\u{1}') {
        return false;
    }
    matches!(crate::emit_common::key_name(t), "vec" | "hashmap" | "string" | "file")
}

/// G6: a collection type or one anywhere inside its type arguments.
pub fn contains_collection(t: &str) -> bool {
    match crate::gtype::GType::try_from_key(t) {
        Ok(g) => g.contains_collection(),
        Err(_) => false,
    }
}

pub const SIGNED_MIN128: i128 = i128::MIN;
/// P2: bit builtin -> LLVM instruction (Python BIT_LLVM); later batches add entries.
const BIT_LLVM: [(&str, &str); 3] = [("band", "and"), ("bor", "or"), ("bxor", "xor")];

fn bit_llvm(n: &str) -> Option<&'static str> {
    BIT_LLVM.iter().find(|(k, _)| *k == n).map(|(_, ins)| *ins)
}
pub const OPT: &str = "{ i1, i64 }";
/// Option/Result stored inside a contract aggregate
pub const COPT: &str = "{ i1, i128 }";
pub const ARR: &str = "{ ptr, i64 }";

pub const DECLS: &str = concat!(
    "declare noalias ptr @pruv_alloc(i64, i64) nounwind\n",
    "declare noalias ptr @pruv_copy(ptr nocapture readonly, i64) nounwind\n",
    "declare void @pruv_free(ptr nocapture, i64) nounwind\n",
    "declare void @pruv_print_i64(i64) nounwind\n",
    "declare void @pruv_print_bool(i64) nounwind\n",
    "declare void @pruv_panic_oob(i64, i64) noreturn cold nounwind\n",
    "declare void @pruv_panic_arith(ptr) noreturn cold nounwind\n",
    "declare void @pruv_panic_requires(ptr, ptr) noreturn cold nounwind\n",
    "declare void @pruv_panic_undefined(ptr) noreturn cold nounwind\n",
    "declare { i64, i1 } @llvm.sadd.with.overflow.i64(i64, i64)\n",
    "declare { i64, i1 } @llvm.ssub.with.overflow.i64(i64, i64)\n",
    "declare { i64, i1 } @llvm.smul.with.overflow.i64(i64, i64)\n",
    "declare { i128, i1 } @llvm.sadd.with.overflow.i128(i128, i128)\n",
    "declare { i128, i1 } @llvm.ssub.with.overflow.i128(i128, i128)\n",
    "declare { i128, i1 } @llvm.smul.with.overflow.i128(i128, i128)\n",
);

/// Declarations appended right after DECLS only for `[u8]` programs (G2 A4 §2.9).
pub const DECLS_U8: &str = concat!(
    "declare noalias ptr @pruv_alloc_u8(i64, i64) nounwind\n",
    "declare noalias ptr @pruv_copy_v2(ptr nocapture readonly, i64, i64, i64) nounwind\n",
    "declare void @pruv_free_v2(ptr nocapture, i64, i64, i64) nounwind\n",
    "declare void @pruv_panic_elem(i64, ptr) noreturn cold nounwind\n",
);

/// G2 A5: declarations appended after DECLS_U8 only for programs that use `[bool]`.
pub const DECLS_BOOL: &str = "declare void @pruv_check_bool(ptr nocapture readonly, i64) nounwind\n";

/// G2 B2: declarations appended only for programs that use `str` (after DECLS_U8 and after DECLS_BOOL).
pub const DECLS_STR: &str = concat!(
    "declare i32 @pruv_str_boundary(ptr nocapture readonly, i64, i64) nounwind willreturn memory(argmem: read)\n",
    "declare noalias ptr @pruv_substr(ptr nocapture readonly, i64, i64, i64) nounwind\n",
    "declare void @pruv_check_utf8(ptr nocapture readonly, i64) nounwind\n",
);

/// G3 A4: declaration of the representation-check panic, only emitted when some wrapper rejects an invalid enum ordinal.
pub const DECLS_REPR: &str = "declare void @pruv_panic_repr(i64, ptr) noreturn cold nounwind\n";

/// G9 A3: only emitted when the program has a recursive (boxed) edge. The marker global is kept alive through
/// @llvm.used, so linking a runtime without pruv_runtime_nodes_v1 fails even when no node helper survives inlining.
pub const DECLS_NODE: &str = concat!(
    "declare noalias ptr @pruv_node_alloc_v1(i64, i64) nounwind\n",
    "declare void @pruv_node_free_v1(ptr nocapture, i64, i64) nounwind\n",
    "declare void @pruv_runtime_nodes_v1() nounwind\n",
    "@pruv_nodes_marker = internal global ptr @pruv_runtime_nodes_v1\n",
    "@llvm.used = appending global [1 x ptr] [ptr @pruv_nodes_marker], section \"llvm.metadata\"\n",
);

/// Name prefix of a generated generic nominal instance (`pruv_g3_t_...`).
pub const G3_TYPE_PREFIX: &str = "pruv_g3_t_";

/// G3 A4: true for a structured built-in application key `option<X>` / `result<X>` (X != i64); the legacy
/// `option` / `result` constants are not applications.
pub fn is_gopt(t: &str) -> bool {
    t.starts_with("option<") || t.starts_with("result<")
}

/// The argument key X of `option<X>` / `result<X>` (only for a key accepted by `is_gopt`).
pub fn g_arg(t: &str) -> &str {
    &t[7..t.len() - 1]
}

/// A user struct/enum (including generated generic instances) or a new Option/Result application.
pub fn is_agg(t: &str) -> bool {
    is_gopt(t) || (is_user_type(t) && !crate::gtype::is_g3_key(t))
}

/// Types whose external word form follows the G3 rules (tag normalization, inactive words zero, enum check).
pub fn is_new_app(t: &str) -> bool {
    is_gopt(t) || (is_user_type(t) && t.starts_with(G3_TYPE_PREFIX))
}

const ARRAY_U8: &str = "array_u8";
const ARRAY_BOOL: &str = "array_bool"; // G2 A5
const STR: &str = "str"; // G2 B2

fn is_u8_ty(t: &Option<String>) -> bool {
    t.as_deref() == Some(ARRAY_U8)
}

/// G2 B2: str value (code and contract reads use the same spelling as u8)
fn is_strv(t: &Option<String>) -> bool {
    t.as_deref() == Some(STR)
}

/// G2 B2: whether this is the internal type name of an array or str (`{ ptr, i64 }` representation)
fn is_arr_name(n: &str) -> bool {
    is_array_name(n) || n == STR
}

/// G2 A5: byte arrays (u8, bool, str) — GEP i8, copy/free v2 (1,1)
fn is_bytes_ty(t: &Option<String>) -> bool {
    matches!(t.as_deref(), Some(ARRAY_U8) | Some(ARRAY_BOOL) | Some(STR))
}

/// G2 A5: array type name -> the ty carried in V/Slot (Some only for u8, bool, str)
fn elem_ty(t: &str) -> Option<String> {
    match t {
        ARRAY_U8 => Some(ARRAY_U8.to_string()),
        ARRAY_BOOL => Some(ARRAY_BOOL.to_string()),
        STR => Some(STR.to_string()),
        _ => None,
    }
}

/// Element IR type E (i8 for a byte array, otherwise i64)
fn elem_ir(v: &V) -> &'static str {
    if is_bytes_ty(&v.ty) {
        "i8"
    } else {
        "i64"
    }
}

const NONE_ATTR: &str = "'NoneType' object has no attribute 'name'";
const IDX_ERR: &str = "list index out of range";

// ---------- type helpers ----------

pub fn mangle(n: &str) -> String {
    let mut out = String::new();
    for c in n.chars() {
        if c.is_ascii_alphanumeric() || c == '_' {
            out.push(c);
        } else {
            out.push_str(&format!("${:04x}", c as u32));
        }
    }
    out
}

/// The internal SSA type of a Pruv type
pub fn lty(t: &str) -> String {
    if is_collection(t) {
        // G6 A3: opaque handle
        return "ptr".to_string();
    }
    if is_gopt(t) {
        return st(t, false);
    }
    match t {
        "i64" => "i64".to_string(),
        "bool" => "i1".to_string(),
        "unit" => "void".to_string(),
        "array" | "array_u8" | "array_bool" | "str" => ARR.to_string(), // G2 A5, B2
        "option" | "result" => OPT.to_string(),
        _ => format!("%pruv_t_{}", t),
    }
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Kind {
    I64,
    I1,
    I128,
    Arr,
    Opt,
    Unit,
    Agg,
    /// G6 A3: opaque handle of a Vec/HashMap/String box (a = ptr, ty = the collection type)
    Coll,
    /// G9 contract evaluation: a = ptr to the REAL storage of an extended value, ty = its type
    Ref,
}

impl Kind {
    pub fn name(self) -> &'static str {
        match self {
            Kind::Coll => "coll",
            Kind::Ref => "ref",
            Kind::I64 => "i64",
            Kind::I1 => "i1",
            Kind::I128 => "i128",
            Kind::Arr => "arr",
            Kind::Opt => "opt",
            Kind::Unit => "unit",
            Kind::Agg => "agg",
        }
    }
}

pub fn vkind(t: &str) -> Kind {
    if is_collection(t) {
        // G6 A3
        return Kind::Coll;
    }
    if is_gopt(t) {
        return Kind::Agg;
    }
    match t {
        "i64" => Kind::I64,
        "bool" => Kind::I1,
        "unit" => Kind::Unit,
        "array" | "array_u8" | "array_bool" | "str" => Kind::Arr, // G2 A5, B2
        "option" | "result" => Kind::Opt,
        _ => Kind::Agg,
    }
}

/// Storage type of a value inside an aggregate (c: contract/i128 form)
pub fn st(t: &str, c: bool) -> String {
    if is_gopt(t) {
        let x = st(g_arg(t), c);
        if t.starts_with("option<") {
            return format!("{{ i1, {} }}", x);
        }
        return format!("{{ i1, {}, {} }}", x, if c { "i128" } else { "i64" });
    }
    match t {
        "i64" => {
            if c {
                "i128".to_string()
            } else {
                "i64".to_string()
            }
        }
        "bool" => "i1".to_string(),
        "option" | "result" => {
            if c {
                COPT.to_string()
            } else {
                OPT.to_string()
            }
        }
        // G9 A3: buffer fields keep the { ptr, i64 } form
        "array" | "array_u8" | "array_bool" | "str" => ARR.to_string(),
        _ => format!("%pruv_{}_{}", if c { "c" } else { "t" }, t),
    }
}

/// G9 field label as in prog.g9.boxed: "Struct.field" or "Enum::Variant.field"
pub fn fld_label(dname: &str, vname: Option<&str>, fname: &str) -> String {
    match vname {
        None => format!("{}.{}", dname, fname),
        Some(v) => format!("{}::{}.{}", dname, v, fname),
    }
}

/// Type table of a program (Python `new_tt`): SCC-condensed declaration order for G9 programs (identical to
/// TypeTable::new otherwise), plus the G9 metadata sets tt.g9_ext (extended declaration names) and tt.g9_boxed.
pub fn new_tt(prog: &Program) -> TypeTable {
    let mut tt = crate::emit_common::make_type_table(prog);
    if let Some(meta) = &prog.g9 {
        tt.g9_ext = meta.extended.iter().cloned().collect();
        tt.g9_boxed = meta.boxed.iter().cloned().collect();
    }
    tt
}

/// t is an extended user type (G9): recursive, or holding a buffer or an extended type
pub fn is_ext_t(tt: &TypeTable, t: &str) -> bool {
    !tt.g9_ext.is_empty() && tt.g9_ext.contains(t)
}

/// G5 A3: some parameter has the inout mode (a mutable borrow of caller storage)
pub fn has_inout(f: &Function) -> bool {
    f.params.iter().any(|p| p.mode_pos.is_some())
}

/// G9: a function with an extended type in its signature has no raw ABI wrapper and no binding;
/// G5 A3: neither has a function with an inout parameter (one host-eligibility rule)
pub fn is_internal_fn(f: &Function, tt: &TypeTable) -> bool {
    f.params.iter().any(|p| is_ext_t(tt, &p.ty)) || is_ext_t(tt, &f.ret) || has_inout(f)
}

/// internal LLVM result type: an extended (G9) aggregate result goes through explicit output storage
pub fn ir_ret(tt: &TypeTable, f: &Function) -> String {
    if is_ext_t(tt, &f.ret) {
        "void".to_string()
    } else {
        lty(&f.ret)
    }
}

/// G9: some struct field / enum payload has the internal type `name` (array_u8, array_bool, str)
pub fn type_has_field(prog: &Program, name: &str) -> bool {
    prog.types.iter().any(|d| d.all_fields().iter().any(|f| f.ty == name))
}

fn t_decl<'t>(tt: &'t TypeTable, ty: &str) -> R<&'t TypeDecl> {
    tt.decl(ty).ok_or_else(|| format!("'{}'", ty))
}

fn t_fields<'t>(tt: &'t TypeTable, ty: &str, variant: Option<&str>) -> R<&'t [FieldDecl]> {
    tt.fields(ty, variant).ok_or_else(|| format!("'{}'", variant.unwrap_or(ty)))
}

fn t_field_index(tt: &TypeTable, ty: &str, name: &str, variant: Option<&str>) -> R<usize> {
    tt.field_index(ty, name, variant).ok_or_else(|| format!("'{}' is not in list", name))
}

fn t_variant_index(tt: &TypeTable, ty: &str, variant: &str) -> R<usize> {
    tt.variant_index(ty, variant).ok_or_else(|| format!("'{}' is not in list", variant))
}

/// Storage index of the i-th field of `variant` inside the flattened enum type
pub fn payload_index(tt: &TypeTable, ty: &str, variant: &str, i: usize) -> R<usize> {
    // The variant -> base offset map is computed once per (type table, type) and memoized: rescanning the variants on
    // every call made helper generation quadratic in the number of variants. The cache lives in `words_memo` (the
    // type table's existing per-type memo) under keys that cannot collide with a type key (they start with NUL).
    let key = |v: &str| format!("\u{0}payload\u{0}{}\u{0}{}", ty, v);
    if let Some(&b) = tt.words_memo.borrow().get(&key(variant)) {
        return Ok(b + i);
    }
    if let TypeDecl::Enum(e) = t_decl(tt, ty)? {
        let mut memo = tt.words_memo.borrow_mut();
        let mut base = 1usize;
        let mut found: Option<usize> = None;
        for v in &e.variants {
            memo.insert(key(&v.name), base);
            if v.name == variant && found.is_none() {
                found = Some(base);
            }
            base += v.fields.len();
        }
        if let Some(b) = found {
            return Ok(b + i);
        }
    } else {
        return Err("'StructDecl' object has no attribute 'variants'".to_string());
    }
    Err(format!("'{}'", variant))
}

/// W(T): number of i64 words in the external (pruv_abi_*) form.  Memoized per type table (a nested generic value
/// would otherwise recompute every subtree: quadratic).
pub fn words(tt: &TypeTable, ty: &str) -> R<usize> {
    if let Some(&n) = tt.words_memo.borrow().get(ty) {
        return Ok(n);
    }
    let r = if is_gopt(ty) {
        // G3: 1 + W(X) (+ 1 for the Result error word)
        let x = words(tt, g_arg(ty))?;
        1 + x + if ty.starts_with("result<") { 1 } else { 0 }
    } else {
        match ty {
            "i64" | "bool" => 1,
            "option" | "result" => 2,
            _ => match t_decl(tt, ty)? {
                TypeDecl::Struct(s) => {
                    let mut sum = 0usize;
                    for f in &s.fields {
                        sum += words(tt, &f.ty)?;
                    }
                    sum.max(1)
                }
                TypeDecl::Enum(e) => {
                    let mut sum = 1usize;
                    for v in &e.variants {
                        for f in &v.fields {
                            sum += words(tt, &f.ty)?;
                        }
                    }
                    sum
                }
            },
        }
    };
    tt.words_memo.borrow_mut().insert(ty.to_string(), r);
    Ok(r)
}

pub fn type_defs(tt: &TypeTable) -> String {
    let mut out: Vec<String> = Vec::new();
    for c in [false, true] {
        for d in tt.ordered() {
            if c && tt.g9_ext.contains(d.name()) {
                continue; // G9: an extended value has no i128 contract mirror
            }
            // a boxed (recursive SCC) field is an opaque ptr to an independently allocated node
            let fs_of = |fields: &[FieldDecl], vname: Option<&str>| -> Vec<String> {
                fields
                    .iter()
                    .map(|f| {
                        if !tt.g9_boxed.is_empty() && tt.g9_boxed.contains(&fld_label(d.name(), vname, &f.name)) {
                            "ptr".to_string()
                        } else {
                            st(&f.ty, c)
                        }
                    })
                    .collect()
            };
            let fs: Vec<String> = match d {
                TypeDecl::Struct(s) => fs_of(&s.fields, None),
                TypeDecl::Enum(e) => {
                    let mut v = vec!["i64".to_string()];
                    for var in &e.variants {
                        v.extend(fs_of(&var.fields, Some(var.name.as_str())));
                    }
                    v
                }
            };
            let body = if fs.is_empty() { "{}".to_string() } else { format!("{{ {} }}", fs.join(", ")) };
            out.push(format!("%pruv_{}_{} = type {}", if c { "c" } else { "t" }, d.name(), body));
        }
    }
    let mut s = out.join("\n");
    if !out.is_empty() {
        s.push('\n');
    }
    s
}

// ---------- values and slots ----------

/// SSA value. Meaning by k: i64|i1|i128, arr(a=ptr,b=len), opt(a=tag,b=payload), unit, agg(a=aggregate SSA, ty=type).
/// A Slot has the same shape (arr: a=ptr slot, b=len slot).
#[derive(Clone, Debug)]
pub struct V {
    pub k: Kind,
    pub a: String,
    pub b: String,
    pub ty: Option<String>,
    /// G9 (agg only): address of storage that holds this value when known (a parameter, a local slot, a boxed node,
    /// a call-result slot); lets a read argument pass the pointer instead of spilling a copy.
    pub p: Option<String>,
}

pub type Slot = V;

impl V {
    pub fn new(k: Kind, a: impl Into<String>) -> V {
        V { k, a: a.into(), b: "None".to_string(), ty: None, p: None }
    }
    pub fn with_b(k: Kind, a: impl Into<String>, b: impl Into<String>) -> V {
        V { k, a: a.into(), b: b.into(), ty: None, p: None }
    }
    pub fn agg(a: impl Into<String>, ty: &str) -> V {
        V { k: Kind::Agg, a: a.into(), b: "None".to_string(), ty: Some(ty.to_string()), p: None }
    }
    /// an aggregate value with a known storage address
    pub fn agg_p(a: impl Into<String>, ty: &str, p: impl Into<String>) -> V {
        V { k: Kind::Agg, a: a.into(), b: "None".to_string(), ty: Some(ty.to_string()), p: Some(p.into()) }
    }
    pub fn unit() -> V {
        V::new(Kind::Unit, "None")
    }
}

/// Name binding: ("ssa", V) or ("slot", Slot)
#[derive(Clone, Debug)]
pub enum Bind {
    Ssa(V),
    Slot(Slot),
}

impl Bind {
    fn val(&self) -> &V {
        match self {
            Bind::Ssa(v) | Bind::Slot(v) => v,
        }
    }
}

#[derive(Default)]
struct Scope {
    names: HashMap<String, Bind>,
    arrays: Vec<Slot>,
}

pub struct Mod {
    strs: HashMap<String, String>,
    order: Vec<String>,
    /// G3: a wrapper rejects an invalid enum ordinal through pruv_panic_repr
    pub uses_repr: bool,
    par_types: Vec<String>,
    par_trampolines: Vec<String>,
    /// G6 A3: shim symbol -> declare line (iterated sorted by symbol)
    pub g6_decls: BTreeMap<String, String>,
    /// G6 A3: string_to_str needs the v2 copy/free declarations
    pub g6_v2: bool,
    /// G6 A3: some function references @pruv_g6_bridge_v1
    pub g6_bridge: bool,
    /// G9 A3: types whose runtime-contract size / equality helpers are needed
    pub need_size: BTreeSet<String>,
    pub need_eq: BTreeSet<String>,
    /// G4 A3: explicit visibility mode (Pruv calls use the Rust-backend routing)
    pub explicit: bool,
    /// G4 A3: function name (stem) -> source-qualified identity (Python `f.disp`), explicit mode only
    pub fn_disp: HashMap<String, String>,
}

impl Mod {
    pub fn new() -> Mod {
        Mod {
            strs: HashMap::new(),
            order: Vec::new(),
            uses_repr: false,
            par_types: Vec::new(),
            par_trampolines: Vec::new(),
            g6_decls: BTreeMap::new(),
            g6_v2: false,
            g6_bridge: false,
            need_size: BTreeSet::new(),
            need_eq: BTreeSet::new(),
            explicit: false,
            fn_disp: HashMap::new(),
        }
    }

    pub fn string(&mut self, text: &str) -> String {
        if let Some(n) = self.strs.get(text) {
            return n.clone();
        }
        let n = format!("@.str.{}", self.order.len());
        self.strs.insert(text.to_string(), n.clone());
        self.order.push(text.to_string());
        n
    }

    pub fn render_strings(&self) -> String {
        let mut out: Vec<String> = Vec::new();
        for text in &self.order {
            let b = text.as_bytes();
            let mut body = String::new();
            for &c in b {
                if (32..127).contains(&c) && c != 34 && c != 92 {
                    body.push(c as char);
                } else {
                    body.push_str(&format!("\\{:02X}", c));
                }
            }
            out.push(format!("{} = private unnamed_addr constant [{} x i8] c\"{}\\00\"", self.strs[text], b.len() + 1, body));
        }
        let mut s = out.join("\n");
        if !out.is_empty() {
            s.push('\n');
        }
        s
    }
}

impl Default for Mod {
    fn default() -> Self {
        Mod::new()
    }
}

/// Internal parameter list [(type, name)]
/// G9: an extended result is the leading `ptr %out` (output storage); an extended parameter is a plain `ptr %p.NAME`
/// to valid caller-owned storage (no noalias: the same subtree can be passed twice).
pub fn ir_params(f: &Function, tt: &TypeTable) -> Vec<(String, String)> {
    let mut out = Vec::new();
    if is_ext_t(tt, &f.ret) {
        out.push(("ptr".to_string(), "%out".to_string()));
    }
    for p in &f.params {
        if is_ext_t(tt, &p.ty) {
            out.push(("ptr".to_string(), format!("%p.{}", mangle(&p.name))));
            continue;
        }
        let n = mangle(&p.name);
        if is_arr_name(&p.ty) {
            out.push(("ptr".to_string(), format!("%p.{}.a", n)));
            out.push(("i64".to_string(), format!("%p.{}.n", n)));
        } else if p.ty == "bool" {
            out.push(("i1".to_string(), format!("%p.{}", n)));
        } else if p.ty == "i64" {
            out.push(("i64".to_string(), format!("%p.{}", n)));
        } else if is_collection(&p.ty) {
            // G6 A3: plain opaque handle %p.NAME.h (no readonly/noalias attributes)
            out.push(("ptr".to_string(), format!("%p.{}.h", n)));
        } else if is_agg(&p.ty) {
            out.push((lty(&p.ty), format!("%p.{}", n)));
        } else {
            out.push((OPT.to_string(), format!("%p.{}", n)));
        }
    }
    out
}

/// Parameter list of an internal function definition: array pointers (names ending in `.a`) are read-only borrows;
/// a G6 collection handle `%p.NAME.h` is a plain ptr. G5 A3: with the function `f`, the pointer of an inout parameter
/// is a mutable borrow: `ptr noalias nocapture` (no readonly)
pub fn sig_text(params: &[(String, String)], f: Option<&Function>) -> String {
    let mut_names: Vec<String> = match f {
        Some(f) => f
            .params
            .iter()
            .filter(|p| p.mode_pos.is_some())
            .map(|p| format!("%p.{}.a", mangle(&p.name)))
            .collect(),
        None => Vec::new(),
    };
    params
        .iter()
        .map(|(t, n)| {
            format!(
                "{} {}",
                if t == "ptr" && n.ends_with(".a") {
                    if mut_names.contains(n) { "ptr noalias nocapture" } else { "ptr noalias nocapture readonly" }
                } else {
                    t.as_str()
                },
                n
            )
        })
        .collect::<Vec<_>>()
        .join(", ")
}

/// The noreturn call made from a guard's failure block (counterpart of a Python lambda). String constants are registered at call time.
pub enum Fail {
    Cost,
    Panic1(&'static str, String),
    Oob(String, String),
    Requires(String, String),
    /// u8 element range violation: (value SSA, range text). The string is registered when the fail block is emitted.
    Elem(String, &'static str),
}

pub(crate) fn expr_ty(e: &Expr) -> &Option<String> {
    match e {
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
        Expr::Move(x) => &x.ty,
        Expr::InoutArg(x) => &x.ty,
    }
}

fn arg(a: &[Expr], i: usize) -> R<&Expr> {
    a.get(i).ok_or_else(|| IDX_ERR.to_string())
}

fn need_ty(t: &Option<String>) -> R<&str> {
    t.as_deref().ok_or_else(|| NONE_ATTR.to_string())
}

pub struct FnGen<'a> {
    m: &'a mut Mod,
    tt: &'a TypeTable,
    funcs: &'a HashMap<String, &'a Function>,
    f: &'a Function,
    verified: bool,
    cost: bool,
    cost_bound: String,
    lines: Vec<String>,
    allocas: Vec<String>,
    nt: usize,
    nl: usize,
    nslot: usize,
    nq: usize,
    cur: String,
    dead: bool,
    scopes: Vec<Scope>,
    temps: Vec<Vec<V>>,
    cenv: HashMap<String, V>,
    budget: Option<String>,
    /// G6 A3: this function references @pruv_g6_bridge_v1
    bridge: bool,
    /// G9 A3: the parameter names of the function (Python `s.cparams`, set when the contract parameters are bound)
    cparams: HashSet<String>,
    /// G9: constructor temporaries (type, storage) of the contract expression being evaluated, per region
    cregions: Vec<Vec<(String, String)>>,
}

impl<'a> FnGen<'a> {
    pub fn new(
        m: &'a mut Mod,
        tt: &'a TypeTable,
        funcs: &'a HashMap<String, &'a Function>,
        f: &'a Function,
        verified: bool,
    ) -> FnGen<'a> {
        FnGen {
            m,
            tt,
            funcs,
            f,
            verified,
            cost: !verified && f.cost.is_some(),
            cost_bound: String::new(),
            lines: Vec::new(),
            allocas: Vec::new(),
            nt: 0,
            nl: 0,
            nslot: 0,
            nq: 0,
            cur: "None".to_string(),
            dead: false,
            scopes: Vec::new(),
            temps: Vec::new(),
            cenv: HashMap::new(),
            budget: None,
            bridge: false,
            cparams: HashSet::new(),
            cregions: Vec::new(),
        }
    }

    // ---------- emission ----------
    pub fn ins(&mut self, text: String) -> R<()> {
        if self.dead {
            return Err(format!("llvmgen: internal error: instruction after terminator: {}", text));
        }
        self.lines.push(format!("  {}", text));
        Ok(())
    }

    pub fn term(&mut self, text: String) -> R<()> {
        self.ins(text)?;
        self.dead = true;
        Ok(())
    }

    fn cost_fail(&mut self) -> R<()> {
        self.ins("call void @pruv_panic_cost()".into())
    }

    fn cost_add(&mut self, units: &str) -> R<()> {
        let old = self.op("load i128, ptr %cost.spent".into())?;
        let pair = self.op(format!("call {{ i128, i1 }} @llvm.uadd.with.overflow.i128(i128 {}, i128 {})", old, units))?;
        let value = self.op(format!("extractvalue {{ i128, i1 }} {}, 0", pair))?;
        let overflow = self.op(format!("extractvalue {{ i128, i1 }} {}, 1", pair))?;
        self.guard(&overflow, Fail::Cost, true)?;
        self.ins(format!("store i128 {}, ptr %cost.spent", value))
    }

    fn cost_call(&mut self, name: &str, args: &[String]) -> R<()> {
        let bound = self.op(format!("call i128 @{}__pruv_cost({})", mangle(name), args.join(", ")))?;
        let negative = self.op(format!("icmp slt i128 {}, 0", bound))?;
        self.guard(&negative, Fail::Cost, true)?;
        // Nonnegative i128 bound plus one always fits u128.
        let units = self.op(format!("add i128 {}, 1", bound))?;
        self.cost_add(&units)
    }

    fn cost_check(&mut self) -> R<()> {
        let negative = self.op(format!("icmp slt i128 {}, 0", self.cost_bound))?;
        let spent = self.op("load i128, ptr %cost.spent".into())?;
        let exceeded = self.op(format!("icmp ugt i128 {}, {}", spent, self.cost_bound))?;
        let bad = self.op(format!("or i1 {}, {}", negative, exceeded))?;
        self.guard(&bad, Fail::Cost, true)
    }

    fn parallel(&mut self, st: &Par) -> R<()> {
        // Entry storage can be reused after the synchronous bridge joins.
        let jobs = self.tmp();
        let jt = format!("[{} x %pruv_g7_job]", st.calls.len());
        self.allocas.push(format!("{} = alloca {}", jobs, jt));
        for (i, call) in st.calls.iter().enumerate() {
            let Expr::Call(call) = call else { return Err("invalid par call".into()); };
            let f = self.funcs[&call.name];
            let mut fields = Vec::new();
            let mut cost_args = Vec::new();
            for x in &call.args {
                let x = if let Expr::InoutArg(x) = x { &*x.expr } else { x };
                let v = self.ev(x, false)?;
                if self.cost {
                    if v.k == Kind::Arr {
                        cost_args.extend([format!("ptr {}", v.a), format!("i64 {}", v.b)]);
                    } else {
                        cost_args.push(format!("{} {}", v.k.name(), v.a));
                    }
                }
                if v.k == Kind::Arr {
                    fields.push(("ptr", v.a));
                    fields.push(("i64", v.b));
                } else if v.k == Kind::I1 {
                    fields.push(("i8", self.op(format!("zext i1 {} to i8", v.a))?));
                } else {
                    fields.push((v.k.name(), v.a));
                }
            }
            if self.cost { self.cost_call(&call.name, &cost_args)?; }
            let n = self.m.par_types.len();
            let ct = format!("%pruv_g7_ctx_{}", n);
            let cb = format!("@pruv_g7_cb_{}", n);
            self.m.par_types.push(format!("{} = type {{ {} }}", ct, fields.iter().map(|(t, _)| *t).collect::<Vec<_>>().join(", ")));
            let ctx = self.tmp();
            self.allocas.push(format!("{} = alloca {}", ctx, ct));
            let mut tr = vec![format!("define private void {}(ptr %ctx) {{", cb), "entry:".into()];
            let mut args = Vec::new();
            for (j, (ty, value)) in fields.iter().enumerate() {
                let ptr = self.op(format!("getelementptr inbounds {}, ptr {}, i32 0, i32 {}", ct, ctx, j))?;
                self.ins(format!("store {} {}, ptr {}", ty, value, ptr))?;
                tr.push(format!("  %p{} = getelementptr inbounds {}, ptr %ctx, i32 0, i32 {}", j, ct, j));
                tr.push(format!("  %v{} = load {}, ptr %p{}", j, ty, j));
                if *ty == "i8" {
                    tr.push(format!("  %b{} = icmp ne i8 %v{}, 0", j, j));
                    args.push(format!("i1 %b{}", j));
                } else {
                    args.push(format!("{} %v{}", ty, j));
                }
            }
            let target = if !self.verified && !f.requires.is_empty() { "par_chk" } else { "body" };
            tr.push(format!("  call void @{}__pruv_{}({})", mangle(&f.name), target, args.join(", ")));
            tr.push("  ret void".into());
            tr.push("}".into());
            self.m.par_trampolines.push(tr.join("\n") + "\n");
            for (j, value) in [&cb, &ctx].iter().enumerate() {
                let ptr = self.op(format!("getelementptr inbounds {}, ptr {}, i32 0, i64 {}, i32 {}", jt, jobs, i, j))?;
                self.ins(format!("store ptr {}, ptr {}", value, ptr))?;
            }
        }
        self.ins(format!("call void @pruv_g7_v1_run(ptr {}, i64 {})", jobs, st.calls.len()))
    }

    pub fn tmp(&mut self) -> String {
        self.nt += 1;
        format!("%t{}", self.nt)
    }

    pub fn op(&mut self, text: String) -> R<String> {
        let r = self.tmp();
        self.ins(format!("{} = {}", r, text))?;
        Ok(r)
    }

    pub fn label(&mut self, hint: &str) -> String {
        self.nl += 1;
        format!("{}.{}", hint, self.nl)
    }

    pub fn place(&mut self, lbl: &str) {
        self.lines.push(format!("{}:", lbl));
        self.cur = lbl.to_string();
        self.dead = false;
    }

    pub fn br(&mut self, l: &str) -> R<()> {
        self.term(format!("br label %{}", l))
    }

    pub fn condbr(&mut self, c: &str, a: &str, b: &str) -> R<()> {
        self.term(format!("br i1 {}, label %{}, label %{}", c, a, b))
    }

    fn run_fail(&mut self, f: &Fail) -> R<()> {
        match f {
            Fail::Cost => self.cost_fail(),
            Fail::Panic1(func, msg) => {
                let s = self.m.string(msg);
                self.ins(format!("call void @{}(ptr {})", func, s))
            }
            Fail::Oob(i, n) => self.ins(format!("call void @pruv_panic_oob(i64 {}, i64 {})", i, n)),
            Fail::Requires(a, b) => self.ins(format!("call void @pruv_panic_requires(ptr {}, ptr {})", a, b)),
            Fail::Elem(v, range) => {
                let s = self.m.string(range);
                self.ins(format!("call void @pruv_panic_elem(i64 {}, ptr {})", v, s))
            }
        }
    }

    /// Continue only when cond != fail_when; otherwise call fail in the failure block
    pub fn guard(&mut self, cond: &str, fail: Fail, fail_when: bool) -> R<()> {
        let ok = self.label("ok");
        let bad = self.label("fail");
        if fail_when {
            self.condbr(cond, &bad, &ok)?;
        } else {
            self.condbr(cond, &ok, &bad)?;
        }
        self.place(&bad);
        self.run_fail(&fail)?;
        self.term("unreachable".to_string())?;
        self.place(&ok);
        Ok(())
    }

    pub fn render(&mut self, header: &str) -> String {
        let mut out: Vec<String> = vec![format!("{} {{", header), "entry:".to_string()];
        for a in &self.allocas {
            out.push(format!("  {}", a));
        }
        out.push("  br label %start".to_string());
        if self.bridge {
            // G6 A3: a (volatile) read of the shim's bridge marker keeps the reference alive: linking without the shim
            // fails. lines[0] is the `start:` label.
            if let Some(first) = self.lines.first() {
                out.push(first.clone());
            }
            out.push("  %g6.bridge = load volatile i8, ptr @pruv_g6_bridge_v1".to_string());
            out.extend(self.lines.iter().skip(1).cloned());
            self.m.g6_bridge = true;
        } else {
            out.extend(self.lines.iter().cloned());
        }
        out.push("}".to_string());
        let mut s = out.join("\n");
        s.push('\n');
        s
    }

    // ---------- slots / scopes ----------
    pub fn new_slot(&mut self, name: &str, ty: &str) -> Slot {
        let kind = vkind(ty);
        let base = format!("%l{}.{}", self.nslot, mangle(name));
        self.nslot += 1;
        let a = format!("{}.a", base);
        let b = format!("{}.b", base);
        match kind {
            Kind::I64 => {
                self.allocas.push(format!("{} = alloca i64", a));
                V::new(Kind::I64, a)
            }
            Kind::I1 => {
                self.allocas.push(format!("{} = alloca i1", a));
                V::new(Kind::I1, a)
            }
            Kind::Coll => {
                // G6 A3: owner slot, null-initialized
                self.allocas.push(format!("{} = alloca ptr", a));
                self.allocas.push(format!("store ptr null, ptr {}", a));
                V { k: Kind::Coll, a, b: "None".to_string(), ty: Some(ty.to_string()), p: None }
            }
            Kind::Arr => {
                self.allocas.push(format!("{} = alloca ptr", a));
                self.allocas.push(format!("{} = alloca i64", b));
                let mut sl = V::with_b(Kind::Arr, a, b);
                sl.ty = elem_ty(ty); // G2 A5: Some only for u8 and bool, None otherwise (default unchanged)
                sl
            }
            Kind::Agg => {
                self.allocas.push(format!("{} = alloca {}", a, lty(ty)));
                V::agg(a, ty)
            }
            _ => {
                self.allocas.push(format!("{} = alloca i1", a));
                self.allocas.push(format!("{} = alloca i64", b));
                V::with_b(Kind::Opt, a, b)
            }
        }
    }

    pub fn load(&mut self, sl: &Slot) -> R<V> {
        match sl.k {
            Kind::I64 | Kind::I1 => {
                let r = self.op(format!("load {}, ptr {}", sl.k.name(), sl.a))?;
                Ok(V::new(sl.k, r))
            }
            Kind::Agg => {
                let ty = need_ty(&sl.ty)?.to_string();
                let r = self.op(format!("load {}, ptr {}", lty(&ty), sl.a))?;
                Ok(V::agg_p(r, &ty, sl.a.clone()))
            }
            Kind::Coll => {
                let r = self.op(format!("load ptr, ptr {}", sl.a))?;
                Ok(V { k: Kind::Coll, a: r, b: "None".to_string(), ty: sl.ty.clone(), p: None })
            }
            Kind::Arr => {
                let p = self.op(format!("load ptr, ptr {}", sl.a))?;
                let n = self.op(format!("load i64, ptr {}", sl.b))?;
                let mut v = V::with_b(Kind::Arr, p, n);
                v.ty = sl.ty.clone();
                Ok(v)
            }
            _ => {
                let t = self.op(format!("load i1, ptr {}", sl.a))?;
                let v = self.op(format!("load i64, ptr {}", sl.b))?;
                Ok(V::with_b(Kind::Opt, t, v))
            }
        }
    }

    pub fn store(&mut self, sl: &Slot, v: &V) -> R<()> {
        match sl.k {
            Kind::I64 | Kind::I1 => self.ins(format!("store {} {}, ptr {}", sl.k.name(), v.a, sl.a)),
            Kind::Agg => {
                let ty = need_ty(&sl.ty)?.to_string();
                self.ins(format!("store {} {}, ptr {}", lty(&ty), v.a, sl.a))
            }
            Kind::Coll => self.ins(format!("store ptr {}, ptr {}", v.a, sl.a)),
            Kind::Arr => {
                self.ins(format!("store ptr {}, ptr {}", v.a, sl.a))?;
                self.ins(format!("store i64 {}, ptr {}", v.b, sl.b))
            }
            _ => {
                self.ins(format!("store i1 {}, ptr {}", v.a, sl.a))?;
                self.ins(format!("store i64 {}, ptr {}", v.b, sl.b))
            }
        }
    }

    pub fn lookup(&self, name: &str) -> R<Bind> {
        for sc in self.scopes.iter().rev() {
            if let Some(b) = sc.names.get(name) {
                return Ok(b.clone());
            }
        }
        Err(format!("llvmgen: unknown variable {}", name))
    }

    pub fn push_scope(&mut self) {
        self.scopes.push(Scope::default());
    }

    pub fn free_val(&mut self, v: &V) -> R<()> {
        if v.k == Kind::Coll {
            // G6 A3: a fresh (non-null) collection temporary
            return self.g6_drop(v);
        }
        if v.k == Kind::Agg {
            // G9 A3: an extended temporary
            return self.drop_agg(v);
        }
        if is_bytes_ty(&v.ty) {
            return self.ins(format!("call void @pruv_free_v2(ptr {}, i64 {}, i64 1, i64 1)", v.a, v.b));
        }
        self.ins(format!("call void @pruv_free(ptr {}, i64 {})", v.a, v.b))
    }

    fn free_scope(&mut self, arrays: &[Slot]) -> R<()> {
        for sl in arrays.iter().rev() {
            if sl.k == Kind::Coll {
                self.drop_slot(sl)?;
            } else if sl.k == Kind::Agg {
                // G9 A3: an owned extended local
                let ty = need_ty(&sl.ty)?.to_string();
                self.ins(format!("call void @pruv_drop__{}(ptr {})", ty, sl.a))?;
            } else {
                let v = self.load(sl)?;
                self.free_val(&v)?;
            }
        }
        Ok(())
    }

    // ---------- G9 A3: extended values (ownership helpers) ----------
    fn is_ext(&self, t: &str) -> bool {
        is_ext_t(self.tt, t)
    }

    fn is_ext_opt(&self, t: &Option<String>) -> bool {
        match t {
            Some(t) => is_ext_t(self.tt, t),
            None => false,
        }
    }

    /// The field `fname` (of `variant` for an enum) of the user type ty is a boxed recursive edge.
    fn fb(&self, ty: &str, variant: Option<&str>, fname: &str) -> bool {
        if self.tt.g9_boxed.is_empty() || !crate::emit_common::is_user_key(ty) {
            return false;
        }
        match self.tt.decl(ty) {
            Some(d) => self.tt.g9_boxed.contains(&fld_label(d.name(), variant, fname)),
            None => false,
        }
    }

    /// Address of the storage that holds the aggregate v: its known address, else a fresh entry-block copy.
    fn spill(&mut self, v: &V) -> R<String> {
        if let Some(p) = &v.p {
            return Ok(p.clone());
        }
        let ty = need_ty(&v.ty)?.to_string();
        let base = format!("%sp{}", self.nslot);
        self.nslot += 1;
        self.allocas.push(format!("{} = alloca {}", base, lty(&ty)));
        self.ins(format!("store {} {}, ptr {}", lty(&ty), v.a, base))?;
        Ok(base)
    }

    /// Fresh entry-block output storage for an aggregate result.
    fn new_out(&mut self, ty: &str) -> String {
        let base = format!("%o{}", self.nslot);
        self.nslot += 1;
        self.allocas.push(format!("{} = alloca {}", base, lty(ty)));
        base
    }

    /// A fresh extended value: owned by the destination, or a temporary dropped at the end of the statement.
    fn fresh(&mut self, v: V, owned: bool) -> R<V> {
        if !owned {
            self.temps.last_mut().ok_or_else(|| IDX_ERR.to_string())?.push(v.clone());
        }
        Ok(v)
    }

    /// Deep copy of the extended value v (a view) into new owned storage.
    fn clone_val(&mut self, v: &V) -> R<V> {
        let src = self.spill(v)?;
        let ty = need_ty(&v.ty)?.to_string();
        let dst = self.new_out(&ty);
        self.ins(format!("call void @pruv_clone__{}(ptr {}, ptr {})", ty, src, dst))?;
        let r = self.op(format!("load {}, ptr {}", lty(&ty), dst))?;
        Ok(V::agg_p(r, &ty, dst))
    }

    fn drop_agg(&mut self, v: &V) -> R<()> {
        let ty = need_ty(&v.ty)?.to_string();
        let p = self.spill(v)?;
        self.ins(format!("call void @pruv_drop__{}(ptr {})", ty, p))
    }

    /// Address of the storage of an extended expression in a READ position (argument): a local slot or a parameter is
    /// passed as is, a fresh temporary lives (registered in self.temps) until the end of the statement.
    fn view_ptr(&mut self, e: &Expr) -> R<String> {
        if let Expr::Var(x) = e {
            return match self.lookup(&x.name)? {
                Bind::Slot(s) => Ok(s.a),
                Bind::Ssa(v) => self.spill(&v),
            };
        }
        let v = self.ev(e, false)?;
        self.spill(&v)
    }

    /// Field value of the aggregate `base` (type ty) at storage index idx; a boxed field is a VIEW of the child node
    /// (a shallow load, never dropped through this value).
    fn getf(&mut self, base: &V, ty: &str, idx: usize, fd: &FieldDecl, variant: Option<&str>, c: bool) -> R<V> {
        if !c && self.fb(ty, variant, &fd.name) {
            let x = self.op(format!("extractvalue {} {}, {}", st(ty, c), base.a, idx))?;
            let r = self.op(format!("load {}, ptr {}", lty(&fd.ty), x))?;
            return Ok(V::agg_p(r, &fd.ty, x));
        }
        self.get(base, ty, idx, &fd.ty, c)
    }

    /// insertvalue of the owned field value v; a boxed field first moves into a new node.
    fn putf(&mut self, acc: &str, ty: &str, idx: usize, v: &V, fd: &FieldDecl, variant: Option<&str>, c: bool) -> R<String> {
        if !c && self.fb(ty, variant, &fd.name) {
            let nd = self.op(format!("call ptr @pruv_box__{}({} {})", fd.ty, lty(&fd.ty), v.a))?;
            return self.op(format!("insertvalue {} {}, ptr {}, {}", st(ty, c), acc, nd, idx));
        }
        self.put(acc, ty, idx, v, &fd.ty, c)
    }

    /// Store the owned value v into the field path of the extended local slot sl (in place). The old value of the last
    /// field is released (nodes: drop then free; buffers: free) after v is complete.
    fn assign_path(&mut self, sl: &Slot, path: &[String], v: &V) -> R<()> {
        let tt = self.tt;
        let mut cur = sl.a.clone();
        let mut cty = need_ty(&sl.ty)?.to_string();
        for (k, fname) in path.iter().enumerate() {
            let i = t_field_index(tt, &cty, fname, None)?;
            let fds = t_fields(tt, &cty, None)?;
            let fd = fds.get(i).ok_or_else(|| IDX_ERR.to_string())?;
            let g = self.op(format!("getelementptr inbounds {}, ptr {}, i32 0, i32 {}", lty(&cty), cur, i))?;
            let boxed = self.fb(&cty, None, fname);
            if k + 1 < path.len() {
                cur = if boxed { self.op(format!("load ptr, ptr {}", g))? } else { g };
                cty = fd.ty.clone();
                continue;
            }
            let ft = fd.ty.as_str();
            if boxed {
                let old = self.op(format!("load ptr, ptr {}", g))?;
                self.ins(format!("call void @pruv_dropnode__{}(ptr {})", ft, old))?;
                let nd = self.op(format!("call ptr @pruv_box__{}({} {})", ft, lty(ft), v.a))?;
                self.ins(format!("store ptr {}, ptr {}", nd, g))?;
            } else if is_arr_name(ft) {
                let x = self.op(format!("load {}, ptr {}", ARR, g))?;
                let p0 = self.op(format!("extractvalue {} {}, 0", ARR, x))?;
                let p1 = self.op(format!("extractvalue {} {}, 1", ARR, x))?;
                let mut old = V::with_b(Kind::Arr, p0, p1);
                old.ty = elem_ty(ft);
                self.free_val(&old)?;
                let a = self.agg(v)?;
                self.ins(format!("store {} {}, ptr {}", ARR, a, g))?;
            } else if self.is_ext(ft) {
                self.ins(format!("call void @pruv_drop__{}(ptr {})", ft, g))?;
                self.ins(format!("store {} {}, ptr {}", lty(ft), v.a, g))?;
            } else {
                let x = self.pack(v, ft, false)?;
                self.ins(format!("store {} {}, ptr {}", st(ft, false), x, g))?;
            }
        }
        Ok(())
    }

    /// Move a temporary into a fresh owner slot (returned); the caller registers it in a scope.
    fn hold(&mut self, v: &V) -> R<Slot> {
        let sl = if v.k == Kind::Agg || v.k == Kind::Coll {
            let ty = need_ty(&v.ty)?.to_string();
            self.new_slot("hold", &ty)
        } else {
            let mut sl = self.new_slot("hold", "array");
            sl.ty = v.ty.clone();
            sl
        };
        self.store(&sl, v)?;
        Ok(sl)
    }

    // ---------- G6 A3: shim calls, owner slots ----------
    fn g6_decl(&mut self, sym: &str, ret: &str, argtys: &[&str]) {
        self.m.g6_decls.insert(sym.to_string(), format!("declare {} @{}({}) nounwind", ret, sym, argtys.join(", ")));
        self.bridge = true;
    }

    /// Calls a bridge symbol; args: (llvm type, value). Returns the SSA result ("" for void).
    fn g6_call(&mut self, sym: &str, ret: &str, args: &[(String, String)]) -> R<String> {
        let tys: Vec<&str> = args.iter().map(|(t, _)| t.as_str()).collect();
        self.g6_decl(sym, ret, &tys);
        let a: Vec<String> = args.iter().map(|(t, v)| format!("{} {}", t, v)).collect();
        let a = a.join(", ");
        if ret == "void" {
            self.ins(format!("call void @{}({})", sym, a))?;
            return Ok(String::new());
        }
        self.op(format!("call {} @{}({})", ret, sym, a))
    }

    fn g6_drop(&mut self, v: &V) -> R<()> {
        let ty = need_ty(&v.ty)?.to_string();
        let sym = crate::foreign_shim::drop_sym(&ty)?;
        self.g6_call(&sym, "void", &[("ptr".to_string(), v.a.clone())])?;
        Ok(())
    }

    /// Drops the owner slot's collection if it is non-null (moved-out slots hold null).
    fn drop_slot(&mut self, sl: &Slot) -> R<()> {
        let p = self.op(format!("load ptr, ptr {}", sl.a))?;
        let nn = self.op(format!("icmp ne ptr {}, null", p))?;
        let dl = self.label("gdrop");
        let el = self.label("gdone");
        self.condbr(&nn, &dl, &el)?;
        self.place(&dl);
        let v = V { k: Kind::Coll, a: p, b: "None".to_string(), ty: sl.ty.clone(), p: None };
        self.g6_drop(&v)?;
        self.br(&el)?;
        self.place(&el);
        Ok(())
    }

    pub fn pop_scope(&mut self) -> R<()> {
        let sc = self.scopes.pop().ok_or_else(|| "pop from empty list".to_string())?;
        if !self.dead {
            self.free_scope(&sc.arrays)?;
        }
        Ok(())
    }

    pub fn begin_temps(&mut self) {
        self.temps.push(Vec::new());
    }

    pub fn end_temps(&mut self) -> R<()> {
        let ts = self.temps.pop().ok_or_else(|| "pop from empty list".to_string())?;
        if !self.dead {
            for v in ts.iter().rev() {
                self.free_val(v)?;
            }
        }
        Ok(())
    }

    // ---------- user aggregates (G1) ----------
    /// SSA of the storage type st(ty, c) of value v
    pub fn pack(&mut self, v: &V, ty: &str, c: bool) -> R<String> {
        if ty == "option" || ty == "result" {
            let (ot, pt) = if c { (COPT, "i128") } else { (OPT, "i64") };
            let a = self.op(format!("insertvalue {} undef, i1 {}, 0", ot, v.a))?;
            return self.op(format!("insertvalue {} {}, {} {}, 1", ot, a, pt, v.b));
        }
        if is_arr_name(ty) {
            // G9 A3: a buffer field is stored as { ptr, i64 }
            return self.agg(v);
        }
        Ok(v.a.clone())
    }

    pub fn unpack(&mut self, x: &str, ty: &str, c: bool) -> R<V> {
        if is_arr_name(ty) {
            // G9 A3
            let p0 = self.op(format!("extractvalue {} {}, 0", ARR, x))?;
            let p1 = self.op(format!("extractvalue {} {}, 1", ARR, x))?;
            let mut v = V::with_b(Kind::Arr, p0, p1);
            v.ty = elem_ty(ty);
            return Ok(v);
        }
        match ty {
            "i64" => Ok(V::new(if c { Kind::I128 } else { Kind::I64 }, x)),
            "bool" => Ok(V::new(Kind::I1, x)),
            "option" | "result" => {
                let ot = if c { COPT } else { OPT };
                let t = self.op(format!("extractvalue {} {}, 0", ot, x))?;
                let p = self.op(format!("extractvalue {} {}, 1", ot, x))?;
                Ok(V::with_b(Kind::Opt, t, p))
            }
            _ => Ok(V::agg(x, ty)),
        }
    }

    pub fn put(&mut self, base: &str, ty: &str, idx: usize, v: &V, fty: &str, c: bool) -> R<String> {
        let x = self.pack(v, fty, c)?;
        self.op(format!("insertvalue {} {}, {} {}, {}", st(ty, c), base, st(fty, c), x, idx))
    }

    pub fn get(&mut self, base: &V, ty: &str, idx: usize, fty: &str, c: bool) -> R<V> {
        let x = self.op(format!("extractvalue {} {}, {}", st(ty, c), base.a, idx))?;
        self.unpack(&x, fty, c)
    }

    pub fn tag_of(&mut self, v: &V, c: bool) -> R<String> {
        let ty = need_ty(&v.ty)?.to_string();
        self.op(format!("extractvalue {} {}, 0", st(&ty, c), v.a))
    }

    /// `own`: G9 A3, the operand is evaluated in an owning position (code form only).
    fn evf(&mut self, e: &Expr, c: bool, own: bool) -> R<V> {
        if c {
            self.cev(e)
        } else {
            self.ev(e, own)
        }
    }

    /// `own`: G9 A3, constructor fields of an extended type are owning positions.
    pub fn mk_struct(&mut self, e: &StructLit, c: bool, own: bool) -> R<V> {
        let tt = self.tt;
        let ty = e.name.as_str();
        // Look up by name like a Python dict (audit: a linear Vec search is quadratic in the field count). For the same name, the later value wins.
        let mut vals: std::collections::HashMap<&str, V> = std::collections::HashMap::new();
        for fi in &e.fields {
            // Evaluate in source order
            let v = self.evf(&fi.value, c, own)?;
            vals.insert(fi.name.as_str(), v);
        }
        let mut acc = "zeroinitializer".to_string();
        for (i, fd) in t_fields(tt, ty, None)?.iter().enumerate() {
            let v = vals
                .get(fd.name.as_str())
                .cloned()
                .ok_or_else(|| format!("'{}'", fd.name))?;
            // G9: a boxed field moves into a new node
            acc = self.putf(&acc, ty, i, &v, fd, None, c)?;
        }
        Ok(V::agg(acc, ty))
    }

    pub fn mk_enum(&mut self, e: &EnumCtor, c: bool, own: bool) -> R<V> {
        let tt = self.tt;
        let ty = e.enum_name.as_str();
        let mut vals: Vec<V> = Vec::new();
        for x in &e.args {
            vals.push(self.evf(x, c, own)?);
        }
        let tag = t_variant_index(tt, ty, &e.variant)?;
        let mut acc = self.op(format!("insertvalue {} zeroinitializer, i64 {}, 0", st(ty, c), tag))?;
        for (i, fd) in t_fields(tt, ty, Some(&e.variant))?.iter().enumerate() {
            let v = vals.get(i).ok_or_else(|| IDX_ERR.to_string())?;
            let pi = payload_index(tt, ty, &e.variant, i)?;
            acc = self.putf(&acc, ty, pi, v, fd, Some(&e.variant), c)?;
        }
        Ok(V::agg(acc, ty))
    }

    /// Some/None/Ok/Err of a new Option<X>/Result<X> application (e.ty): zeroinitializer-based, so the unused
    /// payload storage is always zero.
    pub fn mk_gctor(&mut self, e: &Ctor, c: bool) -> R<V> {
        let ty = need_ty(&e.ty)?.to_string();
        if e.name == "None" {
            return Ok(V::agg("zeroinitializer", &ty));
        }
        let a = e.arg.as_ref().ok_or_else(|| "llvmgen: constructor without argument".to_string())?;
        let x = self.evf(a, c, false)?;
        if e.name == "Some" || e.name == "Ok" {
            let acc = self.op(format!("insertvalue {} zeroinitializer, i1 true, 0", st(&ty, c)))?;
            let r = self.put(&acc, &ty, 1, &x, g_arg(&ty), c)?;
            return Ok(V::agg(r, &ty));
        }
        // Err: tag false (zero), error payload in slot 2
        let r = self.op(format!(
            "insertvalue {} zeroinitializer, {} {}, 2",
            st(&ty, c),
            if c { "i128" } else { "i64" },
            x.a
        ))?;
        Ok(V::agg(r, &ty))
    }

    /// match on a new Option<X>/Result<X>: branch on the tag, bind the active payload only inside its arm
    pub fn gmatch(&mut self, st_: &Match, sv: &V) -> R<()> {
        let ty = need_ty(&sv.ty)?.to_string();
        let x = g_arg(&ty).to_string();
        let pos = st_
            .arms
            .iter()
            .find(|a| a.ctor == "Some" || a.ctor == "Ok")
            .ok_or_else(|| IDX_ERR.to_string())?;
        let neg = st_
            .arms
            .iter()
            .find(|a| a.ctor == "None" || a.ctor == "Err")
            .ok_or_else(|| IDX_ERR.to_string())?;
        let tag = self.op(format!("extractvalue {} {}, 0", st(&ty, false), sv.a))?;
        let pl = self.label("armT");
        let nl = self.label("armF");
        let end = self.label("endmatch");
        self.condbr(&tag, &pl, &nl)?;
        let mut reach = false;
        for (arm, lbl) in [(pos, &pl), (neg, &nl)] {
            self.place(lbl);
            let mut bind: Vec<(String, Bind)> = Vec::new();
            if let Some(b0) = arm.binders.first() {
                if arm.ctor == "Some" || arm.ctor == "Ok" {
                    let v = self.get(sv, &ty, 1, &x, false)?;
                    bind.push((b0.clone(), Bind::Ssa(v)));
                } else {
                    let r = self.op(format!("extractvalue {} {}, 2", st(&ty, false), sv.a))?;
                    bind.push((b0.clone(), Bind::Ssa(V::new(Kind::I64, r))));
                }
            }
            if self.run_block(&arm.body, bind)? {
                self.br(&end)?;
                reach = true;
            }
        }
        if reach {
            self.place(&end);
        } else {
            self.dead = true;
        }
        Ok(())
    }

    /// The aggregate `base` (code form) with the nested struct field `path` replaced by v
    pub fn set_path(&mut self, base: &V, ty: &str, path: &[String], v: &V) -> R<V> {
        let tt = self.tt;
        let fds = t_fields(tt, ty, None)?;
        let first = path.first().ok_or_else(|| IDX_ERR.to_string())?;
        let i = t_field_index(tt, ty, first, None)?;
        let fty = fds.get(i).ok_or_else(|| IDX_ERR.to_string())?.ty.as_str();
        let nv = if path.len() == 1 {
            v.clone()
        } else {
            let sub = self.get(base, ty, i, fty, false)?;
            self.set_path(&sub, fty, &path[1..], v)?
        };
        let r = self.put(&base.a, ty, i, &nv, fty, false)?;
        Ok(V::agg(r, ty))
    }

    /// Code value -> contract value (i64 leaves are sign-extended; for an enum only the active variant is converted)
    pub fn to_c(&mut self, x: &V, ty: &str) -> R<V> {
        let tt = self.tt;
        match ty {
            "i64" => {
                let r = self.op(format!("sext i64 {} to i128", x.a))?;
                return Ok(V::new(Kind::I128, r));
            }
            "bool" => return Ok(x.clone()),
            "option" | "result" => {
                let r = self.op(format!("sext i64 {} to i128", x.b))?;
                return Ok(V::with_b(Kind::Opt, x.a.clone(), r));
            }
            _ => {}
        }
        if is_gopt(ty) {
            // G3: widen the payload (and the Result error); the unused payload stays zero
            let xt = g_arg(ty).to_string();
            let t = self.op(format!("extractvalue {} {}, 0", st(ty, false), x.a))?;
            let mut acc = self.op(format!("insertvalue {} zeroinitializer, i1 {}, 0", st(ty, true), t))?;
            let px = self.get(x, ty, 1, &xt, false)?;
            let pc = self.to_c(&px, &xt)?;
            acc = self.put(&acc, ty, 1, &pc, &xt, true)?;
            if ty.starts_with("result<") {
                let er = self.op(format!("extractvalue {} {}, 2", st(ty, false), x.a))?;
                let ec = self.op(format!("sext i64 {} to i128", er))?;
                acc = self.op(format!("insertvalue {} {}, i128 {}, 2", st(ty, true), acc, ec))?;
            }
            return Ok(V::agg(acc, ty));
        }
        let d = t_decl(tt, ty)?;
        match d {
            TypeDecl::Struct(sd) => {
                let mut acc = "zeroinitializer".to_string();
                for (i, f) in sd.fields.iter().enumerate() {
                    let fx = self.get(x, ty, i, &f.ty, false)?;
                    let cx = self.to_c(&fx, &f.ty)?;
                    acc = self.put(&acc, ty, i, &cx, &f.ty, true)?;
                }
                Ok(V::agg(acc, ty))
            }
            TypeDecl::Enum(ed) => {
                let tag = self.tag_of(x, false)?;
                let base = self.op(format!("insertvalue {} zeroinitializer, i64 {}, 0", st(ty, true), tag))?;
                let vs: Vec<&VariantDecl> = ed.variants.iter().filter(|v| !v.fields.is_empty()).collect();
                if vs.is_empty() {
                    return Ok(V::agg(base, ty));
                }
                let lcur = self.cur.clone();
                let join = self.label("cvend");
                let mut lbls: Vec<String> = Vec::new();
                for _ in &vs {
                    lbls.push(self.label("cvv"));
                }
                let mut cases: Vec<String> = Vec::new();
                for (v, l) in vs.iter().zip(&lbls) {
                    cases.push(format!("i64 {}, label %{}", t_variant_index(tt, ty, &v.name)?, l));
                }
                self.term(format!("switch i64 {}, label %{} [ {} ]", tag, join, cases.join(" ")))?;
                let mut entries: Vec<(String, String)> = vec![(base.clone(), lcur)];
                for (v, l) in vs.iter().zip(&lbls) {
                    self.place(l);
                    let mut acc = base.clone();
                    for (i, f) in v.fields.iter().enumerate() {
                        let pi = payload_index(tt, ty, &v.name, i)?;
                        let fx = self.get(x, ty, pi, &f.ty, false)?;
                        let cx = self.to_c(&fx, &f.ty)?;
                        acc = self.put(&acc, ty, pi, &cx, &f.ty, true)?;
                    }
                    entries.push((acc, self.cur.clone()));
                    self.br(&join)?;
                }
                self.place(&join);
                let ents: Vec<String> = entries.iter().map(|(a, b)| format!("[ {}, %{} ]", a, b)).collect();
                let r = self.op(format!("phi {} {}", st(ty, true), ents.join(", ")))?;
                Ok(V::agg(r, ty))
            }
        }
    }

    fn fields_eq(&mut self, l: &V, r: &V, ty: &str, fds: &[FieldDecl], variant: Option<&str>) -> R<String> {
        let tt = self.tt;
        let mut acc = "true".to_string();
        for (i, f) in fds.iter().enumerate() {
            let j = match variant {
                None => i,
                Some(v) => payload_index(tt, ty, v, i)?,
            };
            let lx = self.get(l, ty, j, &f.ty, true)?;
            let rx = self.get(r, ty, j, &f.ty, true)?;
            let e = self.ceq(&lx, &rx, &f.ty)?;
            acc = if acc == "true" { e } else { self.op(format!("and i1 {}, {}", acc, e))? };
        }
        Ok(acc)
    }

    /// Structural equality of two contract values -> i1 (SSA name or literal)
    pub fn ceq(&mut self, l: &V, r: &V, ty: &str) -> R<String> {
        let tt = self.tt;
        match ty {
            "i64" => return self.op(format!("icmp eq i128 {}, {}", l.a, r.a)),
            "bool" => return self.op(format!("icmp eq i1 {}, {}", l.a, r.a)),
            "option" | "result" => {
                let te = self.op(format!("icmp eq i1 {}, {}", l.a, r.a))?;
                let mut pe = self.op(format!("icmp eq i128 {}, {}", l.b, r.b))?;
                if ty == "option" {
                    // The payload of None is not compared
                    let nt = self.op(format!("xor i1 {}, true", l.a))?;
                    pe = self.op(format!("or i1 {}, {}", nt, pe))?;
                }
                return self.op(format!("and i1 {}, {}", te, pe));
            }
            _ => {}
        }
        if is_gopt(ty) {
            // G3: only the active payload is compared
            let xt = g_arg(ty).to_string();
            let tc = st(ty, true);
            let tl = self.op(format!("extractvalue {} {}, 0", tc, l.a))?;
            let tr = self.op(format!("extractvalue {} {}, 0", tc, r.a))?;
            let te = self.op(format!("icmp eq i1 {}, {}", tl, tr))?;
            let lx = self.get(l, ty, 1, &xt, true)?;
            let rx = self.get(r, ty, 1, &xt, true)?;
            let pe = self.ceq(&lx, &rx, &xt)?;
            let nt = self.op(format!("xor i1 {}, true", tl))?;
            if ty.starts_with("option<") {
                let o = self.op(format!("or i1 {}, {}", nt, pe))?;
                return self.op(format!("and i1 {}, {}", te, o));
            }
            let el = self.op(format!("extractvalue {} {}, 2", tc, l.a))?;
            let er = self.op(format!("extractvalue {} {}, 2", tc, r.a))?;
            let ee = self.op(format!("icmp eq i128 {}, {}", el, er))?;
            let a1 = self.op(format!("and i1 {}, {}", tl, pe))?;
            let a2 = self.op(format!("and i1 {}, {}", nt, ee))?;
            let act = self.op(format!("or i1 {}, {}", a1, a2))?;
            return self.op(format!("and i1 {}, {}", te, act));
        }
        let d = t_decl(tt, ty)?;
        match d {
            TypeDecl::Struct(sd) => self.fields_eq(l, r, ty, &sd.fields, None),
            TypeDecl::Enum(ed) => {
                let tl = self.tag_of(l, true)?;
                let tr = self.tag_of(r, true)?;
                let teq = self.op(format!("icmp eq i64 {}, {}", tl, tr))?;
                let vs: Vec<&VariantDecl> = ed.variants.iter().filter(|v| !v.fields.is_empty()).collect();
                if vs.is_empty() {
                    return Ok(teq);
                }
                let lcur = self.cur.clone();
                let same = self.label("ceqs");
                let dflt = self.label("ceqd");
                let end = self.label("ceqe");
                let mut lbls: Vec<String> = Vec::new();
                for _ in &vs {
                    lbls.push(self.label("ceqv"));
                }
                self.condbr(&teq, &same, &end)?;
                let mut entries: Vec<(String, String)> = vec![("false".to_string(), lcur)];
                self.place(&same);
                let mut cases: Vec<String> = Vec::new();
                for (v, lb) in vs.iter().zip(&lbls) {
                    cases.push(format!("i64 {}, label %{}", t_variant_index(tt, ty, &v.name)?, lb));
                }
                self.term(format!("switch i64 {}, label %{} [ {} ]", tl, dflt, cases.join(" ")))?;
                self.place(&dflt); // same tag, variant with no fields
                entries.push(("true".to_string(), dflt.clone()));
                self.br(&end)?;
                for (v, lb) in vs.iter().zip(&lbls) {
                    self.place(lb);
                    let e = self.fields_eq(l, r, ty, &v.fields, Some(&v.name))?;
                    entries.push((e, self.cur.clone()));
                    self.br(&end)?;
                }
                self.place(&end);
                let ents: Vec<String> = entries.iter().map(|(a, b)| format!("[ {}, %{} ]", a, b)).collect();
                self.op(format!("phi i1 {}", ents.join(", ")))
            }
        }
    }

    pub fn agg(&mut self, v: &V) -> R<String> {
        if v.k == Kind::Agg {
            return Ok(v.a.clone());
        }
        if v.k == Kind::Arr {
            let a = self.op(format!("insertvalue {} undef, ptr {}, 0", ARR, v.a))?;
            return self.op(format!("insertvalue {} {}, i64 {}, 1", ARR, a, v.b));
        }
        let a = self.op(format!("insertvalue {} undef, i1 {}, 0", OPT, v.a))?;
        self.op(format!("insertvalue {} {}, i64 {}, 1", OPT, a, v.b))
    }

    // ---------- function skeleton ----------
    pub fn bind_params(&mut self) -> R<()> {
        self.place("start");
        let f = self.f;
        let mut names: HashMap<String, Bind> = HashMap::new();
        let mut owned: Vec<Slot> = Vec::new();
        for p in &f.params {
            let n = mangle(&p.name);
            if is_arr_name(&p.ty) {
                let mut av = V::with_b(Kind::Arr, format!("%p.{}.a", n), format!("%p.{}.n", n));
                if let Some(t) = elem_ty(&p.ty) {
                    av.ty = Some(t); // G2 A5
                }
                names.insert(p.name.clone(), Bind::Ssa(av));
            } else if p.ty == "bool" {
                names.insert(p.name.clone(), Bind::Ssa(V::new(Kind::I1, format!("%p.{}", n))));
            } else if p.ty == "i64" {
                names.insert(p.name.clone(), Bind::Ssa(V::new(Kind::I64, format!("%p.{}", n))));
            } else if is_collection(&p.ty) {
                // G6 A3
                self.bridge = true;
                if p.take {
                    // consuming parameter: an owner slot (the callee drops it unless it is moved out)
                    let sl = self.new_slot(&p.name, &p.ty);
                    self.ins(format!("store ptr %p.{}.h, ptr {}", n, sl.a))?;
                    names.insert(p.name.clone(), Bind::Slot(sl.clone()));
                    owned.push(sl);
                } else {
                    // borrowed: never dropped here
                    names.insert(
                        p.name.clone(),
                        Bind::Ssa(V {
                            k: Kind::Coll,
                            a: format!("%p.{}.h", n),
                            b: "None".to_string(),
                            ty: Some(p.ty.clone()),
                            p: None,
                        }),
                    );
                }
            } else if self.is_ext(&p.ty) {
                // G9 A3: a read view of caller-owned storage; never dropped here
                let pv = self.op(format!("load {}, ptr %p.{}", lty(&p.ty), n))?;
                names.insert(p.name.clone(), Bind::Ssa(V::agg_p(pv, &p.ty, format!("%p.{}", n))));
            } else if is_agg(&p.ty) {
                names.insert(p.name.clone(), Bind::Ssa(V::agg(format!("%p.{}", n), &p.ty)));
            } else {
                let t = self.op(format!("extractvalue {} %p.{}, 0", OPT, n))?;
                let v = self.op(format!("extractvalue {} %p.{}, 1", OPT, n))?;
                names.insert(p.name.clone(), Bind::Ssa(V::with_b(Kind::Opt, t, v)));
            }
        }
        self.scopes.push(Scope { names, arrays: owned });
        Ok(())
    }

    pub fn emit_ret(&mut self, v: &V) -> R<()> {
        if self.cost { self.cost_check()?; }
        let f = self.f;
        let rt = f.ret.as_str();
        if self.is_ext(rt) {
            // G9 A3: explicit output storage; v is an owned value
            self.ins(format!("store {} {}, ptr %out", lty(rt), v.a))?;
            self.term("ret void".to_string())
        } else if rt == "unit" {
            self.term("ret void".to_string())
        } else if rt == "i64" || rt == "bool" || is_collection(rt) {
            self.term(format!("ret {} {}", lty(rt), v.a))
        } else {
            let g = self.agg(v)?;
            self.term(format!("ret {} {}", lty(rt), g))
        }
    }

    // ---------- statements ----------
    /// Lowers a block into its own scope; true if control can fall out of it
    pub fn run_block(&mut self, stmts: &[Stmt], bind: Vec<(String, Bind)>) -> R<bool> {
        self.push_scope();
        if !bind.is_empty() {
            let sc = self.scopes.last_mut().ok_or_else(|| IDX_ERR.to_string())?;
            for (k, v) in bind {
                sc.names.insert(k, v);
            }
        }
        for s in stmts {
            self.stmt(s)?;
            if self.dead {
                break;
            }
        }
        self.pop_scope()?;
        Ok(!self.dead)
    }

    pub fn body(&mut self) -> R<()> {
        self.bind_params()?;
        let f = self.f;
        if self.cost {
            let args = ir_params(f, self.tt).iter().filter(|(_, n)| n != "%out")
                .map(|(t, n)| format!("{} {}", t, n)).collect::<Vec<_>>().join(", ");
            self.cost_bound = self.op(format!("call i128 @{}__pruv_cost({})", mangle(&f.name), args))?;
            self.allocas.push("%cost.spent = alloca i128".into());
            self.ins("store i128 0, ptr %cost.spent".into())?;
        }
        let falls = self.run_block(&f.body, Vec::new())?;
        if falls {
            if f.ret == "unit" {
                // G6 A3: owned (take) parameters; empty for every other program
                let arrays = self.scopes.first().map(|s| s.arrays.clone()).ok_or_else(|| IDX_ERR.to_string())?;
                self.free_scope(&arrays)?;
                self.emit_ret(&V::unit())?;
            } else {
                self.term("unreachable".to_string())?;
            }
        }
        Ok(())
    }

    pub fn stmt(&mut self, st: &Stmt) -> R<()> {
        match st {
            Stmt::Let(x) => {
                self.begin_temps();
                let v = self.ev(&x.value, true)?;
                let sl = self.new_slot(&x.name, &x.ty);
                self.store(&sl, &v)?;
                // an owner released when the scope ends (G9 A3: also an extended local)
                let owner = sl.k == Kind::Arr || sl.k == Kind::Coll || (sl.k == Kind::Agg && self.is_ext_opt(&sl.ty));
                let sc = self.scopes.last_mut().ok_or_else(|| IDX_ERR.to_string())?;
                sc.names.insert(x.name.clone(), Bind::Slot(sl.clone()));
                if owner {
                    sc.arrays.push(sl);
                }
                self.end_temps()
            }
            Stmt::Assign(x) => {
                self.begin_temps();
                let sl = self.lookup(&x.name)?.val().clone();
                // the right side is complete and owned before the old value is destroyed
                let v = self.ev(&x.value, true)?;
                if sl.k == Kind::Arr {
                    let old = self.load(&sl)?;
                    self.free_val(&old)?;
                } else if sl.k == Kind::Coll {
                    // G6 A3: drop the old value (null when moved out) after the right side
                    self.drop_slot(&sl)?;
                } else if sl.k == Kind::Agg && self.is_ext_opt(&sl.ty) {
                    // G9 A3
                    let ty = need_ty(&sl.ty)?.to_string();
                    self.ins(format!("call void @pruv_drop__{}(ptr {})", ty, sl.a))?;
                }
                self.store(&sl, &v)?;
                self.end_temps()
            }
            Stmt::FieldAssign(x) => {
                self.begin_temps();
                let sl = match self.lookup(&x.name)? {
                    Bind::Slot(s) => s,
                    Bind::Ssa(_) => return Err(format!("llvmgen: field assignment to non-local {}", x.name)),
                };
                if self.is_ext_opt(&sl.ty) {
                    // G9 A3: owned right side first, then an in-place store along the path
                    let v = self.ev(&x.value, true)?;
                    self.assign_path(&sl, &x.fields, &v)?;
                    return self.end_temps();
                }
                let v = self.ev(&x.value, false)?; // right side first, then root load -> insertvalue chain -> store
                let root = self.load(&sl)?;
                let ty = need_ty(&sl.ty)?.to_string();
                let nv = self.set_path(&root, &ty, &x.fields, &v)?;
                self.store(&sl, &nv)?;
                self.end_temps()
            }
            Stmt::IndexAssign(x) => {
                self.begin_temps();
                let bind = self.lookup(&x.name)?;
                let i = self.ev(&x.index, false)?; // index first, then the value (all modes)
                let v = self.ev(&x.value, false)?;
                // G5 A3: an inout parameter is a pointer view (ssa), stored through
                let a = match bind {
                    Bind::Ssa(sv) => sv,
                    Bind::Slot(sl) => self.load(&sl)?,
                };
                let g = self.index_ptr(&a, &i)?;
                if a.ty.as_deref() == Some(ARRAY_BOOL) {
                    // G2 A5: no value range check
                    let z = self.op(format!("zext i1 {} to i8", v.a))?;
                    self.ins(format!("store i8 {}, ptr {}", z, g))?;
                } else if is_u8_ty(&a.ty) {
                    if !self.verified {
                        let ok = self.op(format!("icmp ule i64 {}, 255", v.a))?;
                        self.guard(&ok, Fail::Elem(v.a.clone(), "u8 0..=255"), false)?;
                    }
                    let b = self.op(format!("trunc i64 {} to i8", v.a))?;
                    self.ins(format!("store i8 {}, ptr {}", b, g))?;
                } else {
                    self.ins(format!("store i64 {}, ptr {}", v.a, g))?;
                }
                self.end_temps()
            }
            Stmt::If(x) => {
                self.begin_temps();
                let c = self.ev(&x.cond, false)?;
                self.end_temps()?;
                let thn = self.label("then");
                let end = self.label("endif");
                let has_else = !x.els.is_empty();
                let els = if has_else { self.label("else") } else { end.clone() };
                self.condbr(&c.a, &thn, &els)?;
                self.place(&thn);
                let mut reach = false;
                if self.run_block(&x.then, Vec::new())? {
                    self.br(&end)?;
                    reach = true;
                }
                if has_else {
                    self.place(&els);
                    if self.run_block(&x.els, Vec::new())? {
                        self.br(&end)?;
                        reach = true;
                    }
                } else {
                    reach = true;
                }
                if reach {
                    self.place(&end);
                } else {
                    self.dead = true;
                }
                Ok(())
            }
            Stmt::While(x) => {
                let cl = self.label("wcond");
                let bl = self.label("wbody");
                let el = self.label("wend");
                self.br(&cl)?;
                self.place(&cl);
                self.begin_temps();
                let c = self.ev(&x.cond, false)?;
                self.end_temps()?;
                self.condbr(&c.a, &bl, &el)?;
                self.place(&bl);
                if self.cost { self.cost_add("1")?; }
                if self.run_block(&x.body, Vec::new())? {
                    self.br(&cl)?;
                }
                self.place(&el);
                Ok(())
            }
            Stmt::Return(x) => {
                self.begin_temps();
                let mut v = V::unit();
                if let Some(val) = &x.value {
                    v = self.ev(val, true)?;
                    if v.k == Kind::Arr {
                        if let Expr::Var(var) = val {
                            // When returning a local array out: empty the slot so the cleanup below does not free it
                            let sl = self.lookup(&var.name)?.val().clone();
                            self.ins(format!("store ptr null, ptr {}", sl.a))?;
                            self.ins(format!("store i64 0, ptr {}", sl.b))?;
                        }
                    }
                }
                self.end_temps()?;
                for i in (0..self.scopes.len()).rev() {
                    let arrays = self.scopes[i].arrays.clone();
                    self.free_scope(&arrays)?;
                }
                self.emit_ret(&v)
            }
            Stmt::Assert(_) => Ok(()),
            Stmt::Par(p) => self.parallel(p),
            Stmt::ExprStmt(x) => {
                self.begin_temps();
                self.ev(&x.expr, false)?;
                self.end_temps()
            }
            Stmt::Match(x) if self.is_ext_opt(expr_ty(&x.scrutinee)) => {
                // G9 A3: the scrutinee is borrowed, never consumed; every temporary it created (a fresh scrutinee, a
                // fresh base of a field path, a fresh argument) is moved into owner slots of a scope that spans all
                // arms, so it lives until the selected arm exits (also through an early return) and is dropped once.
                self.begin_temps();
                let sv = self.ev(&x.scrutinee, false)?;
                let held = self.temps.pop().ok_or_else(|| "pop from empty list".to_string())?;
                self.push_scope();
                for tv in &held {
                    let sl = self.hold(tv)?;
                    self.scopes.last_mut().ok_or_else(|| IDX_ERR.to_string())?.arrays.push(sl);
                }
                self.user_match(x, &sv)?;
                self.pop_scope()
            }
            Stmt::Match(x) => {
                self.begin_temps();
                let sv = self.ev(&x.scrutinee, false)?;
                self.end_temps()?;
                if sv.k == Kind::Agg && sv.ty.as_deref().map_or(false, is_gopt) {
                    // G3: Option<X>/Result<X>, X != i64
                    return self.gmatch(x, &sv);
                }
                if let Some(first) = x.arms.first() {
                    if first.enum_name.is_some() {
                        return self.user_match(x, &sv);
                    }
                }
                let pos = x
                    .arms
                    .iter()
                    .find(|a| a.ctor == "Some" || a.ctor == "Ok")
                    .ok_or_else(|| IDX_ERR.to_string())?;
                let neg = x
                    .arms
                    .iter()
                    .find(|a| a.ctor == "None" || a.ctor == "Err")
                    .ok_or_else(|| IDX_ERR.to_string())?;
                let pl = self.label("armT");
                let nl = self.label("armF");
                let end = self.label("endmatch");
                self.condbr(&sv.a, &pl, &nl)?;
                let mut reach = false;
                for (arm, lbl) in [(pos, &pl), (neg, &nl)] {
                    self.place(lbl);
                    let mut bind: Vec<(String, Bind)> = Vec::new();
                    if let Some(b0) = arm.binders.first() {
                        bind.push((b0.clone(), Bind::Ssa(V::new(Kind::I64, sv.b.clone()))));
                    }
                    if self.run_block(&arm.body, bind)? {
                        self.br(&end)?;
                        reach = true;
                    }
                }
                if reach {
                    self.place(&end);
                } else {
                    self.dead = true;
                }
                Ok(())
            }
        }
    }

    /// match on a user enum: tag switch; payload extraction only inside the arm block; default is unreachable
    pub fn user_match(&mut self, st: &Match, sv: &V) -> R<()> {
        let tt = self.tt;
        let ty = need_ty(&sv.ty)?.to_string();
        let tag = self.tag_of(sv, false)?;
        let mut arms: Vec<(&MatchArm, String)> = Vec::new();
        for a in &st.arms {
            let l = self.label(&format!("arm{}", a.ctor));
            arms.push((a, l));
        }
        let dflt = self.label("matchdef");
        let end = self.label("endmatch");
        let mut cases: Vec<String> = Vec::new();
        for (a, l) in &arms {
            cases.push(format!("i64 {}, label %{}", t_variant_index(tt, &ty, &a.ctor)?, l));
        }
        self.term(format!("switch i64 {}, label %{} [ {} ]", tag, dflt, cases.join(" ")))?;
        self.place(&dflt);
        self.term("unreachable".to_string())?;
        let mut reach = false;
        for (a, l) in &arms {
            self.place(l);
            let mut bind: Vec<(String, Bind)> = Vec::new();
            let fds = t_fields(tt, &ty, Some(&a.ctor))?;
            for (i, (name, fd)) in a.binders.iter().zip(fds.iter()).enumerate() {
                let pi = payload_index(tt, &ty, &a.ctor, i)?;
                let v = self.getf(sv, &ty, pi, fd, Some(&a.ctor), false)?;
                bind.push((name.clone(), Bind::Ssa(v)));
            }
            if self.run_block(&a.body, bind)? {
                self.br(&end)?;
                reach = true;
            }
        }
        if reach {
            self.place(&end);
        } else {
            self.dead = true;
        }
        Ok(())
    }

    // ---------- code expressions ----------
    pub fn index_ptr(&mut self, a: &V, i: &V) -> R<String> {
        if !self.verified {
            let ok = self.op(format!("icmp ult i64 {}, {}", i.a, a.b))?;
            self.guard(&ok, Fail::Oob(i.a.clone(), a.b.clone()), false)?;
        }
        self.op(format!("getelementptr inbounds {}, ptr {}, i64 {}", elem_ir(a), a.a, i.a))
    }

    pub fn checked(&mut self, ty: &str, name: &str, sym: &str, a: &str, b: &str) -> R<String> {
        let r = self.op(format!("call {{ {}, i1 }} @llvm.{}.with.overflow.{}({} {}, {} {})", ty, name, ty, ty, a, ty, b))?;
        let v = self.op(format!("extractvalue {{ {}, i1 }} {}, 0", ty, r))?;
        let o = self.op(format!("extractvalue {{ {}, i1 }} {}, 1", ty, r))?;
        if ty == "i64" {
            self.guard(&o, Fail::Panic1("pruv_panic_arith", format!("overflow in {}", sym)), true)?;
        } else {
            self.guard(&o, Fail::Panic1("pruv_panic_undefined", format!("i128 overflow in {}", sym)), true)?;
        }
        Ok(v)
    }

    /// G2 B2: registers the literal bytes (valid UTF-8) as a global string and returns `@.str.N`.
    fn str_global(&mut self, value: &[u8]) -> String {
        let text = String::from_utf8_lossy(value).into_owned();
        self.m.string(&text)
    }

    pub fn temp_arr(&mut self, v: V, owned: bool) -> R<V> {
        if !owned {
            self.temps.last_mut().ok_or_else(|| IDX_ERR.to_string())?.push(v.clone());
        }
        Ok(v)
    }

    pub fn shortcircuit(&mut self, l: &str, is_or: bool, rhs: &dyn Fn(&mut FnGen<'a>) -> R<String>) -> R<String> {
        let lcur = self.cur.clone();
        let rl = self.label("rhs");
        let el = self.label("endsc");
        if is_or {
            self.condbr(l, &el, &rl)?;
        } else {
            self.condbr(l, &rl, &el)?;
        }
        self.place(&rl);
        let r = rhs(self)?;
        let rcur = self.cur.clone();
        self.br(&el)?;
        self.place(&el);
        self.op(format!("phi i1 [ {}, %{} ], [ {}, %{} ]", if is_or { "true" } else { "false" }, lcur, r, rcur))
    }

    pub fn ev(&mut self, e: &Expr, owned: bool) -> R<V> {
        match e {
            Expr::Spent(_) => Err("cost_unavailable: Stage 5 cost verification is not implemented yet".into()),
            Expr::IntLit(x) => Ok(V::new(Kind::I64, x.value.clone())),
            Expr::BoolLit(x) => Ok(V::new(Kind::I1, if x.value { "true" } else { "false" })),
            Expr::StrLit(x) => {
                // G2 B2: copy the global string into a new buffer (for an empty string pruv_copy_v2 gives NULL)
                let g = self.str_global(&x.value);
                let l = x.value.len().to_string();
                let p = self.op(format!("call ptr @pruv_copy_v2(ptr {}, i64 {}, i64 1, i64 1)", g, l))?;
                let mut rv = V::with_b(Kind::Arr, p, l);
                rv.ty = Some(STR.to_string());
                self.temp_arr(rv, owned)
            }
            Expr::Var(x) => {
                let v = match self.lookup(&x.name)? {
                    Bind::Ssa(v) => v,
                    Bind::Slot(s) => self.load(&s)?,
                };
                if owned && v.k == Kind::Agg && self.is_ext_opt(&v.ty) {
                    // G9 A3: a named extended value in an owning position
                    return self.clone_val(&v);
                }
                Ok(v)
            }
            Expr::Move(x) => {
                // G6 A3: load the owner slot, then null it
                let sl = self.lookup(&x.name)?.val().clone();
                let v = self.load(&sl)?;
                self.ins(format!("store ptr null, ptr {}", sl.a))?;
                Ok(v)
            }
            // G5 A0: never reaches the generator (the driver's A0 guard stops the program earlier)
            Expr::InoutArg(_) => Err("G5 inout argument reached the LLVM generator".to_string()),
            Expr::Unary(x) => {
                let v = self.ev(&x.operand, false)?;
                if x.op == "!" {
                    let r = self.op(format!("xor i1 {}, true", v.a))?;
                    return Ok(V::new(Kind::I1, r));
                }
                if self.verified {
                    let r = self.op(format!("sub nsw i64 0, {}", v.a))?;
                    return Ok(V::new(Kind::I64, r));
                }
                let r = self.checked("i64", "ssub", "unary -", "0", &v.a)?;
                Ok(V::new(Kind::I64, r))
            }
            Expr::Binary(x) => self.ev_binary(x),
            Expr::Index(x) => {
                let a = self.ev(&x.array, false)?;
                let i = self.ev(&x.index, false)?;
                let g = self.index_ptr(&a, &i)?;
                if a.ty.as_deref() == Some(ARRAY_BOOL) {
                    // G2 A5
                    let x8 = self.op(format!("load i8, ptr {}", g))?;
                    let r = self.op(format!("icmp ne i8 {}, 0", x8))?;
                    return Ok(V::new(Kind::I1, r));
                }
                if is_u8_ty(&a.ty) || is_strv(&a.ty) {
                    let x8 = self.op(format!("load i8, ptr {}", g))?;
                    let r = self.op(format!("zext i8 {} to i64", x8))?;
                    return Ok(V::new(Kind::I64, r));
                }
                let r = self.op(format!("load i64, ptr {}", g))?;
                Ok(V::new(Kind::I64, r))
            }
            Expr::Ctor(x) => {
                if x.ty.as_deref().map_or(false, is_gopt) {
                    return self.mk_gctor(x, false); // G3
                }
                if x.name == "None" {
                    return Ok(V::with_b(Kind::Opt, "false", "0"));
                }
                let a = x.arg.as_ref().ok_or_else(|| "llvmgen: constructor without argument".to_string())?;
                let v = self.ev(a, false)?;
                Ok(V::with_b(Kind::Opt, if x.name == "Some" || x.name == "Ok" { "true" } else { "false" }, v.a))
            }
            Expr::Call(x) => self.ev_call(x, owned),
            Expr::StructLit(x) => {
                if self.is_ext(&x.name) {
                    // G9 A3: constructor fields are owning positions; the result is fresh
                    let r = self.mk_struct(x, false, true)?;
                    return self.fresh(r, owned);
                }
                self.mk_struct(x, false, false)
            }
            Expr::EnumCtor(x) => {
                if self.is_ext(&x.enum_name) {
                    let r = self.mk_enum(x, false, true)?;
                    return self.fresh(r, owned);
                }
                self.mk_enum(x, false, false)
            }
            Expr::FieldAccess(x) => {
                let tt = self.tt;
                let b = self.ev(&x.base, false)?;
                let ty = match &b.ty {
                    Some(t) => t.clone(),
                    None => need_ty(expr_ty(&x.base))?.to_string(),
                };
                let i = t_field_index(tt, &ty, &x.field, None)?;
                let fds = t_fields(tt, &ty, None)?;
                let fd = fds.get(i).ok_or_else(|| IDX_ERR.to_string())?;
                let v = self.getf(&b, &ty, i, fd, None, false)?;
                if owned && v.k == Kind::Agg && self.is_ext(&fd.ty) {
                    // G9 A3: a field path in an owning position clones
                    return self.clone_val(&v);
                }
                Ok(v)
            }
            other => Err(format!("llvmgen: contract-only expression in code: {:?}", other)),
        }
    }

    pub fn ev_binary(&mut self, e: &Binary) -> R<V> {
        let op = e.op.as_str();
        if op == "&&" || op == "||" {
            let l = self.ev(&e.left, false)?;
            let right = &e.right;
            let r = self.shortcircuit(&l.a, op == "||", &|g| {
                g.begin_temps();
                let r = g.ev(right, false)?;
                g.end_temps()?;
                Ok(r.a)
            })?;
            return Ok(V::new(Kind::I1, r));
        }
        let l = self.ev(&e.left, false)?;
        let r = self.ev(&e.right, false)?;
        if op == "+" || op == "-" || op == "*" {
            let name = match op {
                "+" => "add",
                "-" => "sub",
                _ => "mul",
            };
            if self.verified {
                let v = self.op(format!("{} nsw i64 {}, {}", name, l.a, r.a))?;
                return Ok(V::new(Kind::I64, v));
            }
            let v = self.checked("i64", &format!("s{}", name), op, &l.a, &r.a)?;
            return Ok(V::new(Kind::I64, v));
        }
        if op == "/" || op == "%" {
            if !self.verified {
                let c1 = self.op(format!("icmp sgt i64 {}, 0", r.a))?;
                let c2 = self.op(format!("icmp sge i64 {}, 0", l.a))?;
                let ok = self.op(format!("and i1 {}, {}", c1, c2))?;
                self.guard(
                    &ok,
                    Fail::Panic1("pruv_panic_arith", "division outside domain: need divisor > 0 and dividend >= 0".to_string()),
                    false,
                )?;
            }
            let v = self.op(format!("{} i64 {}, {}", if op == "/" { "udiv" } else { "urem" }, l.a, r.a))?;
            return Ok(V::new(Kind::I64, v));
        }
        let cmp = cmp_name(op)?;
        let ty = if l.k == Kind::I1 { "i1" } else { "i64" };
        let v = self.op(format!("icmp {} {} {}, {}", cmp, ty, l.a, r.a))?;
        Ok(V::new(Kind::I1, v))
    }

    pub fn ev_call(&mut self, e: &Call, owned: bool) -> R<V> {
        let result = self.ev_call_inner(e, owned)?;
        if self.cost && matches!(e.name.as_str(), "alloc" | "copy" | "truncate") {
            let length = self.op(format!("zext i64 {} to i128", result.b))?;
            let units = self.op(format!("add i128 {}, 1", length))?;
            self.cost_add(&units)?;
        }
        Ok(result)
    }

    fn ev_call_inner(&mut self, e: &Call, owned: bool) -> R<V> {
        let n = e.name.as_str();
        let a = &e.args;
        if n == "len" {
            let x = self.ev(arg(a, 0)?, false)?;
            if x.k == Kind::Coll {
                // G6 A3
                let ty = need_ty(&x.ty)?.to_string();
                let sym = crate::foreign_shim::len_sym(&ty)?;
                let r = self.g6_call(&sym, "i64", &[("ptr".to_string(), x.a.clone())])?;
                return Ok(V::new(Kind::I64, r));
            }
            return Ok(V::new(Kind::I64, x.b));
        }
        if crate::foreign::is_catalog(n) && !crate::foreign::is_catalog_contract_only(n) && !self.funcs.contains_key(n) {
            // G6 A3: reserved names
            return self.catalog_call(e, owned);
        }
        if n == "alloc" {
            let cnt = self.ev(arg(a, 0)?, false)?; // source order in all modes: n, then v
            let v = self.ev(arg(a, 1)?, false)?;
            let u8a = is_u8_ty(&e.ty);
            if !self.verified {
                let ok = self.op(format!("icmp ult i64 {}, 1099511627777", cnt.a))?;
                self.guard(&ok, Fail::Panic1("pruv_panic_arith", "alloc length outside 0..2^40".to_string()), false)?;
                if u8a {
                    let ok2 = self.op(format!("icmp ule i64 {}, 255", v.a))?;
                    self.guard(&ok2, Fail::Elem(v.a.clone(), "u8 0..=255"), false)?;
                }
            }
            if e.ty.as_deref() == Some(ARRAY_BOOL) {
                // G2 A5: zext i1 -> i64, allocate with pruv_alloc_u8
                let z = self.op(format!("zext i1 {} to i64", v.a))?;
                let p = self.op(format!("call ptr @pruv_alloc_u8(i64 {}, i64 {})", cnt.a, z))?;
                let mut rv = V::with_b(Kind::Arr, p, cnt.a.clone());
                rv.ty = Some(ARRAY_BOOL.to_string());
                return self.temp_arr(rv, owned);
            }
            if u8a {
                let p = self.op(format!("call ptr @pruv_alloc_u8(i64 {}, i64 {})", cnt.a, v.a))?;
                let mut rv = V::with_b(Kind::Arr, p, cnt.a.clone());
                rv.ty = Some(ARRAY_U8.to_string());
                return self.temp_arr(rv, owned);
            }
            let p = self.op(format!("call ptr @pruv_alloc(i64 {}, i64 {})", cnt.a, v.a))?;
            return self.temp_arr(V::with_b(Kind::Arr, p, cnt.a.clone()), owned);
        }
        if n == "copy" {
            let src = self.ev(arg(a, 0)?, false)?;
            if is_bytes_ty(&src.ty) {
                let p = self.op(format!("call ptr @pruv_copy_v2(ptr {}, i64 {}, i64 1, i64 1)", src.a, src.b))?;
                let mut rv = V::with_b(Kind::Arr, p, src.b.clone());
                rv.ty = src.ty.clone();
                return self.temp_arr(rv, owned);
            }
            let p = self.op(format!("call ptr @pruv_copy(ptr {}, i64 {})", src.a, src.b))?;
            return self.temp_arr(V::with_b(Kind::Arr, p, src.b.clone()), owned);
        }
        if n == "truncate" {
            // the first m elements of the array as a new array
            let src = self.ev(arg(a, 0)?, false)?;
            let m = self.ev(arg(a, 1)?, false)?;
            if !self.verified {
                let ok = self.op(format!("icmp ule i64 {}, {}", m.a, src.b))?;
                self.guard(&ok, Fail::Panic1("pruv_panic_arith", "truncate length outside 0..len".to_string()), false)?;
            }
            if is_bytes_ty(&src.ty) {
                let p = self.op(format!("call ptr @pruv_copy_v2(ptr {}, i64 {}, i64 1, i64 1)", src.a, m.a))?;
                let mut rv = V::with_b(Kind::Arr, p, m.a.clone());
                rv.ty = src.ty.clone();
                return self.temp_arr(rv, owned);
            }
            let p = self.op(format!("call ptr @pruv_copy(ptr {}, i64 {})", src.a, m.a))?;
            return self.temp_arr(V::with_b(Kind::Arr, p, m.a.clone()), owned);
        }
        if n == "print" {
            let x = self.ev(arg(a, 0)?, false)?;
            if x.k == Kind::I1 {
                let z = self.op(format!("zext i1 {} to i64", x.a))?;
                self.ins(format!("call void @pruv_print_bool(i64 {})", z))?;
            } else {
                self.ins(format!("call void @pruv_print_i64(i64 {})", x.a))?;
            }
            return Ok(V::unit());
        }
        if n == "is_char_boundary" {
            // G2 B2: argument order s -> i
            let s = self.ev(arg(a, 0)?, false)?;
            let i = self.ev(arg(a, 1)?, false)?;
            let r = self.op(format!("call i32 @pruv_str_boundary(ptr {}, i64 {}, i64 {})", s.a, s.b, i.a))?;
            let c = self.op(format!("icmp ne i32 {}, 0", r))?;
            return Ok(V::new(Kind::I1, c));
        }
        if let Some(ins) = bit_llvm(n) {
            // P2: no flags, same IR with and without --no-verify
            let x = self.ev(arg(a, 0)?, false)?;
            let y = self.ev(arg(a, 1)?, false)?;
            let r = self.op(format!("{} i64 {}, {}", ins, x.a, y.a))?;
            return Ok(V::new(Kind::I64, r));
        }
        if n == "substr" {
            // G2 B2: argument order s -> lo -> hi
            let s = self.ev(arg(a, 0)?, false)?;
            let lo = self.ev(arg(a, 1)?, false)?;
            let hi = self.ev(arg(a, 2)?, false)?;
            let (p, d);
            if self.verified {
                d = self.op(format!("sub i64 {}, {}", hi.a, lo.a))?;
                let g = self.op(format!("getelementptr inbounds i8, ptr {}, i64 {}", s.a, lo.a))?;
                p = self.op(format!("call ptr @pruv_copy_v2(ptr {}, i64 {}, i64 1, i64 1)", g, d))?;
            } else {
                p = self.op(format!("call ptr @pruv_substr(ptr {}, i64 {}, i64 {}, i64 {})", s.a, s.b, lo.a, hi.a))?;
                d = self.op(format!("sub i64 {}, {}", hi.a, lo.a))?;
            }
            let mut rv = V::with_b(Kind::Arr, p, d);
            rv.ty = Some(STR.to_string());
            return self.temp_arr(rv, owned);
        }
        let funcs = self.funcs;
        let f = match funcs.get(n) {
            Some(f) => *f,
            None => return Err(format!("llvmgen: unsupported call in code: {}", n)),
        };
        if f.foreign.is_some() {
            // G6 A3: trusted rust fn through its bridge adapter
            return self.trusted_call(f, e, owned);
        }
        let mut args: Vec<String> = Vec::new();
        for (i, x) in a.iter().enumerate() {
            let prm = f.params.get(i).ok_or_else(|| IDX_ERR.to_string())?;
            if self.is_ext(&prm.ty) {
                // G9 A3: a read argument is a pointer to valid caller-owned storage
                let vp = self.view_ptr(x)?;
                args.push(format!("ptr {}", vp));
                continue;
            }
            if let Expr::InoutArg(ix) = x {
                // G5 A3: the caller's own pointer and length; no copy, ownership stays put
                let v = self.ev(&ix.expr, false)?;
                args.push(format!("ptr {}", v.a));
                args.push(format!("i64 {}", v.b));
                continue;
            }
            let take = prm.take;
            let v = self.ev(x, take)?;
            match v.k {
                Kind::Coll => args.push(format!("ptr {}", v.a)), // G6 A3: opaque handle
                Kind::Arr => {
                    args.push(format!("ptr {}", v.a));
                    args.push(format!("i64 {}", v.b));
                }
                Kind::Opt => {
                    let g = self.agg(&v)?;
                    args.push(format!("{} {}", OPT, g));
                }
                Kind::Agg => {
                    let ty = need_ty(&v.ty)?;
                    args.push(format!("{} {}", lty(ty), v.a));
                }
                k => args.push(format!("{} {}", k.name(), v.a)),
            }
        }
        if self.cost { self.cost_call(&f.name, &args)?; }
        let callee = if self.m.explicit {
            // G4 A3 (docs/G4_SPEC.md 4): verified calls go to the body (requires proved); safe-mode calls go through the
            // checked wrapper only when the callee has a requires (no wrapper exists otherwise)
            format!("@{}__pruv_{}", mangle(&f.name), if !self.verified && !f.requires.is_empty() { "entry" } else { "body" })
        } else {
            format!("@{}__pruv_{}", mangle(&f.name), if self.verified { "body" } else { "entry" })
        };
        if self.is_ext(&f.ret) {
            // G9 A3: explicit output storage; the result is a fresh owned value
            let outp = self.new_out(&f.ret);
            let mut all: Vec<String> = vec![format!("ptr {}", outp)];
            all.extend(args.iter().cloned());
            self.ins(format!("call void {}({})", callee, all.join(", ")))?;
            let r = self.op(format!("load {}, ptr {}", lty(&f.ret), outp))?;
            return self.fresh(V::agg_p(r, &f.ret, outp), owned);
        }
        let argl = args.join(", ");
        if f.ret == "unit" {
            self.ins(format!("call void {}({})", callee, argl))?;
            return Ok(V::unit());
        }
        let r = self.op(format!("call {} {}({})", lty(&f.ret), callee, argl))?;
        if f.ret == "i64" || f.ret == "bool" {
            return Ok(V::new(vkind(&f.ret), r));
        }
        if is_collection(&f.ret) {
            // G6 A3: fresh owned handle; a temporary unless the caller takes it
            let rv = V { k: Kind::Coll, a: r, b: "None".to_string(), ty: Some(f.ret.clone()), p: None };
            return self.temp_arr(rv, owned);
        }
        if is_agg(&f.ret) {
            return Ok(V::agg(r, &f.ret));
        }
        let x0 = self.op(format!("extractvalue {} {}, 0", lty(&f.ret), r))?;
        let x1 = self.op(format!("extractvalue {} {}, 1", lty(&f.ret), r))?;
        if is_arr_name(&f.ret) {
            let mut rv = V::with_b(Kind::Arr, x0, x1);
            if let Some(t) = elem_ty(&f.ret) {
                rv.ty = Some(t); // G2 A5
            }
            return self.temp_arr(rv, owned);
        }
        Ok(V::with_b(Kind::Opt, x0, x1))
    }

    // ---------- G6 A3: catalog operations and trusted rust fn through the bridge ----------
    /// Bridge arguments (type, value) of an evaluated value: handle ptr, bool as i64 0/1, (ptr, len), i64.
    fn g6_arg(&mut self, v: &V) -> R<Vec<(String, String)>> {
        if v.k == Kind::Coll {
            return Ok(vec![("ptr".to_string(), v.a.clone())]);
        }
        if v.k == Kind::I1 {
            let z = self.op(format!("zext i1 {} to i64", v.a))?;
            return Ok(vec![("i64".to_string(), z)]);
        }
        if v.k == Kind::Arr {
            return Ok(vec![("ptr".to_string(), v.a.clone()), ("i64".to_string(), v.b.clone())]);
        }
        Ok(vec![("i64".to_string(), v.a.clone())])
    }

    /// Fresh entry-block out slot of the given llvm type; returns its name.
    fn g6_out(&mut self, kind: &str) -> String {
        let base = format!("%g{}", self.nslot);
        self.nslot += 1;
        self.allocas.push(format!("{} = alloca {}", base, kind));
        base
    }

    fn catalog_call(&mut self, e: &Call, owned: bool) -> R<V> {
        let n = e.name.as_str();
        let cat = crate::foreign::catalog_fn(n).ok_or_else(|| format!("'{}'", n))?;
        let (_low, src) = crate::foreign_shim::inst_types(e);
        let sym = crate::foreign_shim::adapter_sym(&crate::foreign_shim::helper_name(n, &src)?);
        let mut args: Vec<(String, String)> = Vec::new();
        // arguments once, in source order; take arguments are owned values
        for (p, x) in cat.params.iter().zip(e.args.iter()) {
            let v = self.ev(x, p.take)?;
            args.extend(self.g6_arg(&v)?);
        }
        if matches!(
            n,
            "vec_new" | "map_new" | "string_new" | "vec_push" | "map_insert" | "string_push_str"
                | "file_open_read" | "file_create" | "file_read_all" | "file_write_str" | "file_write_bytes"
        ) {
            // a fresh box, or the very same box pointer of a consuming update
            let r = self.g6_call(&sym, "ptr", &args)?;
            let rv = V { k: Kind::Coll, a: r, b: "None".to_string(), ty: e.ty.clone(), p: None };
            return self.temp_arr(rv, owned);
        }
        if matches!(
            n,
            "vec_get" | "string_byte" | "file_close" | "file_ok" | "file_readable" | "file_writable" | "file_size" | "file_byte"
        ) {
            let r = self.g6_call(&sym, "i64", &args)?;
            if e.ty.as_deref() == Some("bool") {
                let c = self.op(format!("icmp ne i64 {}, 0", r))?;
                return Ok(V::new(Kind::I1, c));
            }
            return Ok(V::new(Kind::I64, r));
        }
        if n == "map_get" {
            let tag = self.g6_out("i64");
            let val = self.g6_out("i64");
            let mut a2 = args.clone();
            a2.push(("ptr".to_string(), tag.clone()));
            a2.push(("ptr".to_string(), val.clone()));
            self.g6_call(&sym, "void", &a2)?;
            let t = self.op(format!("load i64, ptr {}", tag))?;
            let x = self.op(format!("load i64, ptr {}", val))?;
            let t1 = self.op(format!("icmp ne i64 {}, 0", t))?;
            if e.ty.as_deref() == Some("option") {
                return Ok(V::with_b(Kind::Opt, t1, x));
            }
            let x1 = self.op(format!("icmp ne i64 {}, 0", x))?; // Option<bool>: { i1, i1 }
            let ety = need_ty(&e.ty)?.to_string();
            let tt_ = st(&ety, false);
            let a0 = self.op(format!("insertvalue {} zeroinitializer, i1 {}, 0", tt_, t1))?;
            let a1 = self.op(format!("insertvalue {} {}, i1 {}, 1", tt_, a0, x1))?;
            return Ok(V::agg(a1, &ety));
        }
        if n == "string_to_str" {
            self.m.g6_v2 = true;
            let d = self.g6_out("ptr");
            let l = self.g6_out("i64");
            let mut a2 = args.clone();
            a2.push(("ptr".to_string(), d.clone()));
            a2.push(("ptr".to_string(), l.clone()));
            self.g6_call(crate::foreign_shim::STRING_BYTES_SYM, "void", &a2)?;
            let dp = self.op(format!("load ptr, ptr {}", d))?;
            let ln = self.op(format!("load i64, ptr {}", l))?;
            let p = self.op(format!("call ptr @pruv_copy_v2(ptr {}, i64 {}, i64 1, i64 1)", dp, ln))?;
            let mut rv = V::with_b(Kind::Arr, p, ln);
            rv.ty = Some(STR.to_string());
            return self.temp_arr(rv, owned);
        }
        Err(format!("llvmgen: unsupported catalog operation {}", n))
    }

    fn trusted_call(&mut self, f: &Function, e: &Call, owned: bool) -> R<V> {
        let mut args: Vec<(String, String)> = Vec::new();
        for x in &e.args {
            let v = self.ev(x, false)?;
            args.extend(self.g6_arg(&v)?);
        }
        let sym = crate::foreign_shim::adapter_sym(&f.name);
        if is_collection(&f.ret) {
            // G6b: a fresh boxed result; a temporary unless the caller takes it
            let r = self.g6_call(&sym, "ptr", &args)?;
            let rv = V { k: Kind::Coll, a: r, b: "None".to_string(), ty: Some(f.ret.clone()), p: None };
            return self.temp_arr(rv, owned);
        }
        if f.ret == "unit" {
            self.g6_call(&sym, "void", &args)?;
            return Ok(V::unit());
        }
        let r = self.g6_call(&sym, "i64", &args)?;
        if f.ret == "bool" {
            let c = self.op(format!("icmp ne i64 {}, 0", r))?;
            return Ok(V::new(Kind::I1, c));
        }
        Ok(V::new(Kind::I64, r))
    }

    // ---------- contract (requires) evaluation, i128 ----------
    pub fn bind_contract_params(&mut self) -> R<()> {
        self.place("start");
        let f = self.f;
        self.cparams = f.params.iter().map(|p| p.name.clone()).collect();
        for p in &f.params {
            let n = mangle(&p.name);
            if is_arr_name(&p.ty) {
                let mut av = V::with_b(Kind::Arr, format!("%p.{}.a", n), format!("%p.{}.n", n));
                if let Some(t) = elem_ty(&p.ty) {
                    av.ty = Some(t); // G2 A5
                }
                self.cenv.insert(p.name.clone(), av);
            } else if p.ty == "bool" {
                self.cenv.insert(p.name.clone(), V::new(Kind::I1, format!("%p.{}", n)));
            } else if p.ty == "i64" {
                let r = self.op(format!("sext i64 %p.{} to i128", n))?;
                self.cenv.insert(p.name.clone(), V::new(Kind::I128, r));
            } else if is_collection(&p.ty) {
                // G6 A3: only len(c) is evaluable in a requires on LLVM
                self.cenv.insert(
                    p.name.clone(),
                    V { k: Kind::Coll, a: format!("%p.{}.h", n), b: "None".to_string(), ty: Some(p.ty.clone()), p: None },
                );
            } else if self.is_ext(&p.ty) {
                // G9 A3: no i128 mirror; contracts read the REAL storage lazily (see cx)
                self.cenv.insert(
                    p.name.clone(),
                    V { k: Kind::Ref, a: format!("%p.{}", n), b: "None".to_string(), ty: Some(p.ty.clone()), p: None },
                );
            } else if is_agg(&p.ty) {
                let c = self.to_c(&V::agg(format!("%p.{}", n), &p.ty), &p.ty)?;
                self.cenv.insert(p.name.clone(), c);
            } else {
                let t = self.op(format!("extractvalue {} %p.{}, 0", OPT, n))?;
                let v = self.op(format!("extractvalue {} %p.{}, 1", OPT, n))?;
                let w = self.op(format!("sext i64 {} to i128", v))?;
                self.cenv.insert(p.name.clone(), V::with_b(Kind::Opt, t, w));
            }
        }
        Ok(())
    }

    // ---------- G9 A3: contract operands over REAL values ----------
    fn tag_ptr(&mut self, ty: &str, p: &str) -> R<String> {
        self.op(format!("getelementptr inbounds {}, ptr {}, i32 0, i32 0", lty(ty), p))
    }

    /// Pointer to the REAL (code form) storage of a contract operand of nominal or buffer type. Nothing is converted
    /// eagerly, so an inactive variant or a skipped operand is never inspected. Supported (same set as the Rust
    /// backend): a parameter, a field path, variant_field (partial: pruv_panic_undefined when the variant is not active;
    /// the tag is checked before the payload address is formed) and nullary constructors.
    fn cx(&mut self, e: &Expr) -> R<String> {
        let tt = self.tt;
        match e {
            Expr::Var(x) => {
                if !self.cparams.contains(&x.name) {
                    return Err(g9_diag_err(x.line, x.col, &format!("the variable {} as an aggregate operand", x.name)));
                }
                let n = mangle(&x.name);
                if self.is_ext_opt(&x.ty) {
                    return Ok(format!("%p.{}", n));
                }
                // a non-extended parameter is an SSA value
                let ty = need_ty(&x.ty)?.to_string();
                self.spill(&V::agg(format!("%p.{}", n), &ty))
            }
            Expr::FieldAccess(x) => {
                let bty = need_ty(expr_ty(&x.base))?.to_string();
                let bp = self.cx(&x.base)?;
                let i = t_field_index(tt, &bty, &x.field, None)?;
                let g = self.op(format!("getelementptr inbounds {}, ptr {}, i32 0, i32 {}", lty(&bty), bp, i))?;
                if self.fb(&bty, None, &x.field) {
                    return self.op(format!("load ptr, ptr {}", g));
                }
                Ok(g)
            }
            Expr::VariantField(x) => {
                let ety = x.enum_name.clone();
                let bp = self.cx(&x.value)?;
                let k = t_variant_index(tt, &ety, &x.variant)?;
                let tp = self.tag_ptr(&ety, &bp)?;
                let tag = self.op(format!("load i64, ptr {}", tp))?;
                let ok = self.op(format!("icmp eq i64 {}, {}", tag, k))?;
                self.guard(
                    &ok,
                    Fail::Panic1(
                        "pruv_panic_undefined",
                        format!(
                            "variant_field expected {}::{}.{}",
                            crate::emit_common::src_name(&x.enum_name),
                            x.variant,
                            x.field
                        ),
                    ),
                    false,
                )?;
                let i = t_field_index(tt, &ety, &x.field, Some(&x.variant))?;
                let pi = payload_index(tt, &ety, &x.variant, i)?;
                let g = self.op(format!("getelementptr inbounds {}, ptr {}, i32 0, i32 {}", lty(&ety), bp, pi))?;
                if self.fb(&ety, Some(&x.variant), &x.field) {
                    return self.op(format!("load ptr, ptr {}", g));
                }
                Ok(g)
            }
            Expr::EnumCtor(x) if x.args.is_empty() => {
                let ety = x.enum_name.clone();
                let k = t_variant_index(tt, &ety, &x.variant)?;
                let v = self.op(format!("insertvalue {} zeroinitializer, i64 {}, 0", st(&ety, false), k))?;
                self.spill(&V::agg(v, &ety))
            }
            Expr::StructLit(x) if x.fields.is_empty() => self.spill(&V::agg("zeroinitializer", &x.name)),
            Expr::EnumCtor(_) | Expr::StructLit(_) => {
                // A constructor with payload is a REAL temporary of the type (code form) in entry-block storage. An
                // extended one owns heap parts: it is dropped when the enclosing evaluation region ends (cregion).
                let v = self.g9_real(e, None)?;
                let ty = need_ty(&v.ty)?.to_string();
                let base = format!("%ct{}", self.nslot);
                self.nslot += 1;
                self.allocas.push(format!("{} = alloca {}", base, lty(&ty)));
                self.ins(format!("store {} {}, ptr {}", lty(&ty), v.a, base))?;
                if self.is_ext(&ty) {
                    self.cregions.last_mut().ok_or_else(|| IDX_ERR.to_string())?.push((ty, base.clone()));
                }
                Ok(base)
            }
            _ => Err(g9_diag_err(e.line(), e.col(), "this expression as an aggregate operand")),
        }
    }

    /// Runs f (a contract evaluation) and then drops the extended constructor temporaries it created, newest first.
    /// A region is a requires clause, a short-circuit right side or a quantifier body iteration: every temporary of a
    /// region is built on the straight-line path that reaches its end.
    fn cregion(&mut self, f: &dyn Fn(&mut FnGen<'a>) -> R<V>) -> R<V> {
        self.cregions.push(Vec::new());
        let r = f(self)?;
        let ts = self.cregions.pop().ok_or_else(|| "pop from empty list".to_string())?;
        for (ty, p) in ts.iter().rev() {
            self.ins(format!("call void @pruv_drop__{}(ptr {})", ty, p))?;
        }
        Ok(r)
    }

    /// V (code form, OWNED) of the REAL value of the contract expression e of declared type ty (default: its own type).
    /// Constructors are built field by field in declaration order; an i64 comes from the i128 contract value through a
    /// checked narrowing; a named value / part is charged its weight and then deep-copied; a buffer is charged its
    /// length and then copied. Same order of effects and messages as the Rust backend.
    fn g9_real(&mut self, e: &Expr, ty: Option<&str>) -> R<V> {
        let tt = self.tt;
        match e {
            Expr::StructLit(x) => {
                let sty = x.name.as_str();
                let mut inits: HashMap<&str, &Expr> = HashMap::new();
                for f in &x.fields {
                    inits.insert(f.name.as_str(), &f.value);
                }
                let mut acc = "zeroinitializer".to_string();
                for (i, fd) in t_fields(tt, sty, None)?.iter().enumerate() {
                    let init = inits.get(fd.name.as_str()).copied().ok_or_else(|| format!("'{}'", fd.name))?;
                    let v = self.g9_real(init, Some(&fd.ty))?;
                    acc = self.putf(&acc, sty, i, &v, fd, None, false)?;
                }
                return Ok(V::agg(acc, sty));
            }
            Expr::EnumCtor(x) => {
                let ety = x.enum_name.as_str();
                let tag = t_variant_index(tt, ety, &x.variant)?;
                let mut acc = self.op(format!("insertvalue {} zeroinitializer, i64 {}, 0", st(ety, false), tag))?;
                for (i, (a, fd)) in x.args.iter().zip(t_fields(tt, ety, Some(&x.variant))?.iter()).enumerate() {
                    let v = self.g9_real(a, Some(&fd.ty))?;
                    let pi = payload_index(tt, ety, &x.variant, i)?;
                    acc = self.putf(&acc, ety, pi, &v, fd, Some(&x.variant), false)?;
                }
                return Ok(V::agg(acc, ety));
            }
            _ => {}
        }
        let t: Option<String> = match ty {
            Some(t) => Some(t.to_string()),
            None => expr_ty(e).clone(),
        };
        if let Expr::Ctor(x) = e {
            let px: String = match t.as_deref() {
                Some(t) if is_gopt(t) => g_arg(t).to_string(),
                _ => "i64".to_string(),
            };
            if let Some(gt) = t.as_deref().filter(|s| is_gopt(s)) {
                if x.name == "None" {
                    return Ok(V::agg("zeroinitializer", gt));
                }
                let a = x.arg.as_ref().ok_or_else(|| "llvmgen: constructor without argument".to_string())?;
                if x.name == "Some" || x.name == "Ok" {
                    let xv = self.g9_real(a, Some(&px))?;
                    let acc = self.op(format!("insertvalue {} zeroinitializer, i1 true, 0", st(gt, false)))?;
                    let r = self.put(&acc, gt, 1, &xv, &px, false)?;
                    return Ok(V::agg(r, gt));
                }
                let xv = self.g9_real(a, Some("i64"))?;
                let r = self.op(format!("insertvalue {} zeroinitializer, i64 {}, 2", st(gt, false), xv.a))?;
                return Ok(V::agg(r, gt));
            }
            if x.name == "None" {
                return Ok(V::with_b(Kind::Opt, "false", "0"));
            }
            let a = x.arg.as_ref().ok_or_else(|| "llvmgen: constructor without argument".to_string())?;
            let xv = self.g9_real(a, Some(if x.name == "Err" { "i64" } else { px.as_str() }))?;
            return Ok(V::with_b(Kind::Opt, if x.name == "Some" || x.name == "Ok" { "true" } else { "false" }, xv.a));
        }
        if t.is_none() || t.as_deref() == Some("i64") {
            let x = self.cev(e)?;
            let tr = self.op(format!("trunc i128 {} to i64", x.a))?;
            let back = self.op(format!("sext i64 {} to i128", tr))?;
            let ok = self.op(format!("icmp eq i128 {}, {}", back, x.a))?;
            self.guard(&ok, Fail::Panic1("pruv_panic_undefined", "constructor field out of i64 range".to_string()), false)?;
            return Ok(V::new(Kind::I64, tr));
        }
        let t = need_ty(&t)?.to_string();
        if t == "bool" {
            let x = self.cev(e)?;
            return Ok(V::new(Kind::I1, x.a));
        }
        if matches!(e, Expr::Var(_) | Expr::FieldAccess(_) | Expr::VariantField(_))
            && (crate::emit_common::is_user_key(&t) || t == "option" || t == "result" || is_gopt(&t))
        {
            if crate::emit_common::is_user_key(&t) && self.tt.holds_buffer(&t) {
                return Err(g9_diag_err(e.line(), e.col(), "a copy of a value holding an array or str"));
            }
            let p = self.cx(e)?;
            self.g9_charge_weight(&t, &p)?;
            if self.is_ext(&t) {
                return self.clone_val(&V::agg_p("None", &t, p));
            }
            let x = self.op(format!("load {}, ptr {}", lty(&t), p))?;
            return self.unpack(&x, &t, false);
        }
        if is_arr_name(&t) {
            let a = self.cev(e)?;
            self.spend_n(&a.b)?;
            let np = if is_bytes_ty(&a.ty) {
                self.op(format!("call ptr @pruv_copy_v2(ptr {}, i64 {}, i64 1, i64 1)", a.a, a.b))?
            } else {
                self.op(format!("call ptr @pruv_copy(ptr {}, i64 {})", a.a, a.b))?
            };
            let mut r = V::with_b(Kind::Arr, np, a.b.clone());
            r.ty = elem_ty(&t);
            return Ok(r);
        }
        Err(g9_diag_err(e.line(), e.col(), "this expression as a constructor field of an aggregate operand"))
    }

    /// e reads a part of a REAL (extended) value through its storage (cx): a variant_field of an extended value, or a
    /// field path below one.
    fn g9_real_path(&self, e: &Expr) -> bool {
        match e {
            Expr::VariantField(x) => self.is_ext_opt(expr_ty(&x.value)) || self.g9_real_path(&x.value),
            Expr::FieldAccess(x) => self.is_ext_opt(expr_ty(&x.base)) || self.g9_real_path(&x.base),
            _ => false,
        }
    }

    /// Charges the contract budget the weight of the value of type t stored at p (one unit per nominal node); a type
    /// without nominal parts costs nothing.
    fn g9_charge_weight(&mut self, t: &str, p: &str) -> R<()> {
        for n in g9_nominals_in(t) {
            self.m.need_size.insert(n);
        }
        let bud = self.budget.clone().ok_or_else(|| "'FnGen' object has no attribute 'budget'".to_string())?;
        g9_weight(self, t, p, &bud)?;
        Ok(())
    }

    /// Value of a field path / variant_field whose root is an extended value: a buffer (arr), an extended value (ref)
    /// or a scalar-like value converted to its contract form.
    fn cload(&mut self, e: &Expr) -> R<V> {
        let p = self.cx(e)?;
        let t = need_ty(expr_ty(e))?.to_string();
        if is_arr_name(&t) {
            let x = self.op(format!("load {}, ptr {}", ARR, p))?;
            let p0 = self.op(format!("extractvalue {} {}, 0", ARR, x))?;
            let p1 = self.op(format!("extractvalue {} {}, 1", ARR, x))?;
            let mut v = V::with_b(Kind::Arr, p0, p1);
            v.ty = elem_ty(&t);
            return Ok(v);
        }
        if self.is_ext(&t) {
            return Ok(V { k: Kind::Ref, a: p, b: "None".to_string(), ty: Some(t), p: None });
        }
        // a whole nominal value is converted whole: charge its weight to the budget first
        self.g9_charge_weight(&t, &p)?;
        let x = self.op(format!("load {}, ptr {}", st(&t, false), p))?;
        let u = self.unpack(&x, &t, false)?;
        self.to_c(&u, &t)
    }

    pub fn cev(&mut self, e: &Expr) -> R<V> {
        let und = |msg: String| Fail::Panic1("pruv_panic_undefined", msg);
        let tt = self.tt;
        match e {
            Expr::Spent(_) => Err("cost_unavailable: Stage 5 cost verification is not implemented yet".into()),
            Expr::IntLit(x) => Ok(V::new(Kind::I128, x.value.clone())),
            Expr::BoolLit(x) => Ok(V::new(Kind::I1, if x.value { "true" } else { "false" })),
            Expr::StrLit(x) => {
                // G2 B2: point at the global string directly, without copying
                let g = self.str_global(&x.value);
                Ok(V { k: Kind::Arr, a: g, b: x.value.len().to_string(), ty: Some(STR.to_string()), p: None })
            }
            Expr::Var(x) => match self.cenv.get(&x.name) {
                Some(v) => Ok(v.clone()),
                None => Err(format!("llvmgen: unsupported variable in requires: {}", x.name)),
            },
            Expr::Unary(x) => {
                let v = self.cev(&x.operand)?;
                if x.op == "!" {
                    let r = self.op(format!("xor i1 {}, true", v.a))?;
                    return Ok(V::new(Kind::I1, r));
                }
                let r = self.checked("i128", "ssub", "unary -", "0", &v.a)?;
                Ok(V::new(Kind::I128, r))
            }
            Expr::Binary(x) => {
                let op = x.op.as_str();
                if op == "&&" || op == "||" || op == "==>" {
                    let mut l = self.cev(&x.left)?;
                    if op == "==>" {
                        let r = self.op(format!("xor i1 {}, true", l.a))?;
                        l = V::new(Kind::I1, r);
                    }
                    let right = &x.right;
                    let r = self.shortcircuit(&l.a, op != "&&", &|g| Ok(g.cregion(&|g2| g2.cev(right))?.a))?;
                    return Ok(V::new(Kind::I1, r));
                }
                if (op == "==" || op == "!=") && self.is_ext_opt(expr_ty(&x.left)) {
                    // G9 A3: structural equality of buffer-free extended aggregates, visited lazily on the real values:
                    // one budget unit per visited node pair, only the active variant's fields are compared
                    let pl = self.cx(&x.left)?;
                    let pr = self.cx(&x.right)?;
                    let lt = need_ty(expr_ty(&x.left))?.to_string();
                    self.m.need_eq.insert(lt.clone());
                    let bud = self
                        .budget
                        .clone()
                        .ok_or_else(|| "'FnGen' object has no attribute 'budget'".to_string())?;
                    let mut eq = self.op(format!("call i1 @pruv_ceq__{}(ptr {}, ptr {}, ptr {})", lt, pl, pr, bud))?;
                    if op == "!=" {
                        eq = self.op(format!("xor i1 {}, true", eq))?;
                    }
                    return Ok(V::new(Kind::I1, eq));
                }
                let l = self.cev(&x.left)?;
                let r = self.cev(&x.right)?;
                if op == "+" || op == "-" || op == "*" {
                    let name = match op {
                        "+" => "sadd",
                        "-" => "ssub",
                        _ => "smul",
                    };
                    let v = self.checked("i128", name, op, &l.a, &r.a)?;
                    return Ok(V::new(Kind::I128, v));
                }
                if op == "/" || op == "%" {
                    let func = if op == "/" { "pruv_cdiv" } else { "pruv_crem" };
                    let v = self.op(format!("call i128 @{}(i128 {}, i128 {})", func, l.a, r.a))?;
                    return Ok(V::new(Kind::I128, v));
                }
                if (op == "==" || op == "!=") && l.k == Kind::Agg {
                    let lty_ = need_ty(&l.ty)?.to_string();
                    let mut eq = self.ceq(&l, &r, &lty_)?;
                    if op == "!=" {
                        eq = self.op(format!("xor i1 {}, true", eq))?;
                    }
                    return Ok(V::new(Kind::I1, eq));
                }
                if (op == "==" || op == "!=") && l.k == Kind::Opt {
                    let te = self.op(format!("icmp eq i1 {}, {}", l.a, r.a))?;
                    let mut pe = self.op(format!("icmp eq i128 {}, {}", l.b, r.b))?;
                    if expr_ty(&x.left).as_deref() == Some("option") {
                        let nt = self.op(format!("xor i1 {}, true", l.a))?;
                        pe = self.op(format!("or i1 {}, {}", nt, pe))?;
                    }
                    let mut eq = self.op(format!("and i1 {}, {}", te, pe))?;
                    if op == "!=" {
                        eq = self.op(format!("xor i1 {}, true", eq))?;
                    }
                    return Ok(V::new(Kind::I1, eq));
                }
                let cmp = cmp_name(op)?;
                let ty = if l.k == Kind::I1 { "i1" } else { "i128" };
                let v = self.op(format!("icmp {} {} {}, {}", cmp, ty, l.a, r.a))?;
                Ok(V::new(Kind::I1, v))
            }
            Expr::Index(x) => {
                if expr_ty(&x.array).as_deref().map_or(false, is_collection) {
                    // G6 A3: not evaluable on LLVM yet
                    return Err(g6_diag_err(x.line, x.col));
                }
                let a = self.cev(&x.array)?;
                let i = self.cev(&x.index)?;
                let ln = self.op(format!("zext i64 {} to i128", a.b))?;
                let ok = self.op(format!("icmp ult i128 {}, {}", i.a, ln))?;
                self.guard(&ok, und("array index out of range".to_string()), false)?;
                let ii = self.op(format!("trunc i128 {} to i64", i.a))?;
                if a.ty.as_deref() == Some(ARRAY_BOOL) {
                    // G2 A5
                    let g = self.op(format!("getelementptr inbounds i8, ptr {}, i64 {}", a.a, ii))?;
                    let x8 = self.op(format!("load i8, ptr {}", g))?;
                    let b = self.op(format!("icmp ne i8 {}, 0", x8))?;
                    return Ok(V::new(Kind::I1, b));
                }
                if is_u8_ty(&a.ty) || is_strv(&a.ty) {
                    let g = self.op(format!("getelementptr inbounds i8, ptr {}, i64 {}", a.a, ii))?;
                    let x8 = self.op(format!("load i8, ptr {}", g))?;
                    let r = self.op(format!("zext i8 {} to i128", x8))?;
                    return Ok(V::new(Kind::I128, r));
                }
                let g = self.op(format!("getelementptr inbounds i64, ptr {}, i64 {}", a.a, ii))?;
                let v = self.op(format!("load i64, ptr {}", g))?;
                let r = self.op(format!("sext i64 {} to i128", v))?;
                Ok(V::new(Kind::I128, r))
            }
            Expr::Ctor(x) => {
                if x.ty.as_deref().map_or(false, is_gopt) {
                    return self.mk_gctor(x, true); // G3
                }
                if x.name == "None" {
                    return Ok(V::with_b(Kind::Opt, "false", "0"));
                }
                let a = x.arg.as_ref().ok_or_else(|| "llvmgen: constructor without argument".to_string())?;
                let v = self.cev(a)?;
                Ok(V::with_b(Kind::Opt, if x.name == "Some" || x.name == "Ok" { "true" } else { "false" }, v.a))
            }
            Expr::Quant(_) => self.cquant(e),
            Expr::StructLit(x) => self.mk_struct(x, true, false),
            Expr::EnumCtor(x) => self.mk_enum(x, true, false),
            Expr::FieldAccess(x) => {
                if self.is_ext_opt(expr_ty(&x.base)) || self.g9_real_path(&x.base) {
                    // G9: a field of a real value, read through its storage
                    return self.cload(e);
                }
                let b = self.cev(&x.base)?;
                let bty = need_ty(&b.ty)?.to_string();
                let i = t_field_index(tt, &bty, &x.field, None)?;
                let fds = t_fields(tt, &bty, None)?;
                let fty = fds.get(i).ok_or_else(|| IDX_ERR.to_string())?.ty.as_str();
                self.get(&b, &bty, i, fty, true)
            }
            Expr::IsVariant(x) => {
                if self.is_ext_opt(expr_ty(&x.value)) || self.g9_real_path(&x.value) {
                    // G9: the tag of the real value
                    let ety = need_ty(expr_ty(&x.value))?.to_string();
                    let p = self.cx(&x.value)?;
                    let tp = self.tag_ptr(&ety, &p)?;
                    let tag = self.op(format!("load i64, ptr {}", tp))?;
                    let k = t_variant_index(tt, &ety, &x.variant)?;
                    let r = self.op(format!("icmp eq i64 {}, {}", tag, k))?;
                    return Ok(V::new(Kind::I1, r));
                }
                let b = self.cev(&x.value)?;
                let bty = need_ty(&b.ty)?.to_string();
                let k = t_variant_index(tt, &bty, &x.variant)?;
                let tag = self.tag_of(&b, true)?;
                let r = self.op(format!("icmp eq i64 {}, {}", tag, k))?;
                Ok(V::new(Kind::I1, r))
            }
            // G6 A0: `move` is checked but never lowered (the driver's A0 guard stops the program earlier)
            Expr::Move(_) => Err("G6 move reached the LLVM generator".to_string()),
            // G5 A0: an inout marker is checked but never lowered (the driver's A0 guard stops the program earlier)
            Expr::InoutArg(_) => Err("G5 inout argument reached the LLVM generator".to_string()),
            Expr::VariantField(x) => {
                if self.is_ext_opt(expr_ty(&x.value)) || self.g9_real_path(&x.value) {
                    return self.cload(e);
                }
                let b = self.cev(&x.value)?;
                let bty = need_ty(&b.ty)?.to_string();
                let k = t_variant_index(tt, &bty, &x.variant)?;
                let tag = self.tag_of(&b, true)?;
                let ok = self.op(format!("icmp eq i64 {}, {}", tag, k))?;
                self.guard(
                    &ok,
                    und(format!("variant_field expected {}::{}.{}", x.enum_name, x.variant, x.field)),
                    false,
                )?;
                let i = t_field_index(tt, &bty, &x.field, Some(&x.variant))?;
                let fds = t_fields(tt, &bty, Some(&x.variant))?;
                let fd = fds.get(i).ok_or_else(|| IDX_ERR.to_string())?;
                let pi = payload_index(tt, &bty, &x.variant, i)?;
                self.get(&b, &bty, pi, &fd.ty, true)
            }
            Expr::Call(x) => {
                let n = x.name.as_str();
                let a = &x.args;
                if crate::foreign::FILE_OBSERVERS.contains(&n) {
                    let v = self.cev(arg(a, 0)?)?;
                    let mut args = vec![("ptr".to_string(), v.a)];
                    if n == "file_byte" {
                        let i = self.cev(arg(a, 1)?)?;
                        let size = self.g6_call(&crate::foreign_shim::adapter_sym("pruv_g6_file_size"), "i64", &args)?;
                        let size = self.op(format!("zext i64 {} to i128", size))?;
                        let ok = self.op(format!("icmp ult i128 {}, {}", i.a, size))?;
                        self.guard(&ok, und("array index out of range".to_string()), false)?;
                        args.push(("i64".to_string(), self.op(format!("trunc i128 {} to i64", i.a))?));
                    }
                    let r = self.g6_call(&crate::foreign_shim::adapter_sym(&format!("pruv_g6_{}", n)), "i64", &args)?;
                    if x.ty.as_deref() == Some("bool") {
                        return Ok(V::new(Kind::I1, self.op(format!("icmp ne i64 {}, 0", r))?));
                    }
                    return Ok(V::new(Kind::I128, self.op(format!("zext i64 {} to i128", r))?));
                }
                if n == "size" {
                    // G9 A3: structural size of the real value, checked i128 additions, one unit per node
                    let p = self.cx(arg(a, 0)?)?;
                    let aty = need_ty(expr_ty(arg(a, 0)?))?.to_string();
                    self.m.need_size.insert(aty.clone());
                    let bud = self
                        .budget
                        .clone()
                        .ok_or_else(|| "'FnGen' object has no attribute 'budget'".to_string())?;
                    let r = self.op(format!("call i128 @pruv_csize__{}(ptr {}, ptr {})", aty, p, bud))?;
                    return Ok(V::new(Kind::I128, r));
                }
                if n == "len" {
                    let v = self.cev(arg(a, 0)?)?;
                    if v.k == Kind::Coll {
                        // G6 A3
                        let vty = need_ty(&v.ty)?.to_string();
                        let sym = crate::foreign_shim::len_sym(&vty)?;
                        let ln = self.g6_call(&sym, "i64", &[("ptr".to_string(), v.a.clone())])?;
                        let r = self.op(format!("zext i64 {} to i128", ln))?;
                        return Ok(V::new(Kind::I128, r));
                    }
                    let r = self.op(format!("zext i64 {} to i128", v.b))?;
                    return Ok(V::new(Kind::I128, r));
                }
                if crate::foreign::is_catalog_contract_only(n) {
                    // G6 A3: map_lookup / map_updated: not evaluable on LLVM yet
                    return Err(g6_diag_err(x.line, x.col));
                }
                if n == "is_char_boundary" {
                    // G2 B2
                    let s = self.cev(arg(a, 0)?)?;
                    let i = self.cev(arg(a, 1)?)?;
                    let ln = self.op(format!("zext i64 {} to i128", s.b))?;
                    let ok = self.op(format!("icmp ule i128 {}, {}", i.a, ln))?;
                    let t = self.op(format!("trunc i128 {} to i64", i.a))?;
                    let u = self.op(format!("select i1 {}, i64 {}, i64 -1", ok, t))?;
                    let r = self.op(format!("call i32 @pruv_str_boundary(ptr {}, i64 {}, i64 {})", s.a, s.b, u))?;
                    let c = self.op(format!("icmp ne i32 {}, 0", r))?;
                    return Ok(V::new(Kind::I1, c));
                }
                if let Some(ins) = bit_llvm(n) {
                    // P2: both i128 arguments must be inside i64; then the op on i128 is exact
                    let x = self.cev(arg(a, 0)?)?;
                    let y = self.cev(arg(a, 1)?)?;
                    for v in [&x, &y] {
                        let t = self.op(format!("add i128 {}, 9223372036854775808", v.a))?;
                        let ok = self.op(format!("icmp ult i128 {}, 18446744073709551616", t))?;
                        self.guard(&ok, und(format!("argument outside i64 in {}", n)), false)?;
                    }
                    let r = self.op(format!("{} i128 {}, {}", ins, x.a, y.a))?;
                    return Ok(V::new(Kind::I128, r));
                }
                if n == "is_some" || n == "is_ok" {
                    let v = self.cev(arg(a, 0)?)?;
                    if v.k == Kind::Agg {
                        // G3: tag of a new Option/Result
                        let ty = need_ty(&v.ty)?.to_string();
                        let r = self.op(format!("extractvalue {} {}, 0", st(&ty, true), v.a))?;
                        return Ok(V::new(Kind::I1, r));
                    }
                    return Ok(V::new(Kind::I1, v.a));
                }
                if n == "some_val" || n == "ok_val" || n == "err_val" {
                    let o = self.cev(arg(a, 0)?)?;
                    if o.k == Kind::Agg {
                        // G3: selectors of a new Option/Result look only at the active payload
                        let oty = need_ty(&o.ty)?.to_string();
                        let tc = st(&oty, true);
                        let tag = self.op(format!("extractvalue {} {}, 0", tc, o.a))?;
                        if n == "err_val" {
                            self.guard(&tag, und("err_val of Ok".to_string()), true)?;
                            let r = self.op(format!("extractvalue {} {}, 2", tc, o.a))?;
                            return Ok(V::new(Kind::I128, r));
                        }
                        let msg = if n == "some_val" { "some_val of None" } else { "ok_val of Err" };
                        self.guard(&tag, und(msg.to_string()), false)?;
                        return self.get(&o, &oty, 1, g_arg(&oty), true);
                    }
                    if n == "err_val" {
                        self.guard(&o.a, und("err_val of Ok".to_string()), true)?;
                    } else {
                        let msg = if n == "some_val" { "some_val of None" } else { "ok_val of Err" };
                        self.guard(&o.a, und(msg.to_string()), false)?;
                    }
                    return Ok(V::new(Kind::I128, o.b));
                }
                Err(format!("llvmgen: unsupported expression in requires: {:?}", e))
            }
        }
    }

    /// Consumes 1 unit of the requires iteration budget (docs/M0_CONTRACTS.md B)
    pub fn spend(&mut self) -> R<()> {
        self.spend_n("1")
    }

    /// Consumes n units of the budget. The budget is never negative at rest and n is a non-negative length, so the
    /// subtraction cannot overflow.
    pub fn spend_n(&mut self, n: &str) -> R<()> {
        let budget = match &self.budget {
            Some(b) => b.clone(),
            None => return Err("llvmgen: internal error: no iteration budget slot".to_string()),
        };
        let old = self.op(format!("load i64, ptr {}", budget))?;
        let nv = self.op(format!("sub i64 {}, {}", old, n))?;
        self.ins(format!("store i64 {}, ptr {}", nv, budget))?;
        let ok = self.op(format!("icmp sge i64 {}, 0", nv))?;
        self.guard(&ok, Fail::Panic1("pruv_panic_undefined", "contract iteration budget exceeded".to_string()), false)
    }

    /// The O(n) form of the sorted precondition forall: forall k in 1..len(a): a[k-1] <= a[k]
    pub fn csorted(&mut self, name: &str, q: usize) -> R<V> {
        let arr = self.cenv.get(name).cloned().ok_or_else(|| format!("'{}'", name))?;
        let k = format!("%q{}.k", q);
        let r = format!("%q{}.r", q);
        self.allocas.push(format!("{} = alloca i64", k));
        self.allocas.push(format!("{} = alloca i1", r));
        self.ins(format!("store i64 1, ptr {}", k))?;
        self.ins(format!("store i1 true, ptr {}", r))?;
        let cl = self.label("qc");
        let bl = self.label("qb");
        let nl = self.label("qn");
        let el = self.label("qe");
        self.br(&cl)?;
        self.place(&cl);
        let kv = self.op(format!("load i64, ptr {}", k))?;
        let c = self.op(format!("icmp slt i64 {}, {}", kv, arr.b))?;
        self.condbr(&c, &bl, &el)?;
        self.place(&bl);
        self.spend()?;
        let pk = self.op(format!("sub i64 {}, 1", kv))?;
        let le;
        if is_u8_ty(&arr.ty) {
            let g0 = self.op(format!("getelementptr inbounds i8, ptr {}, i64 {}", arr.a, pk))?;
            let g1 = self.op(format!("getelementptr inbounds i8, ptr {}, i64 {}", arr.a, kv))?;
            let x0 = self.op(format!("load i8, ptr {}", g0))?;
            let x1 = self.op(format!("load i8, ptr {}", g1))?;
            let z0 = self.op(format!("zext i8 {} to i64", x0))?;
            let z1 = self.op(format!("zext i8 {} to i64", x1))?;
            le = self.op(format!("icmp sle i64 {}, {}", z0, z1))?;
        } else {
            let g0 = self.op(format!("getelementptr inbounds i64, ptr {}, i64 {}", arr.a, pk))?;
            let g1 = self.op(format!("getelementptr inbounds i64, ptr {}, i64 {}", arr.a, kv))?;
            let x0 = self.op(format!("load i64, ptr {}", g0))?;
            let x1 = self.op(format!("load i64, ptr {}", g1))?;
            le = self.op(format!("icmp sle i64 {}, {}", x0, x1))?;
        }
        let stop = self.label("qstop");
        self.condbr(&le, &nl, &stop)?;
        self.place(&stop);
        self.ins(format!("store i1 false, ptr {}", r))?;
        self.br(&el)?;
        self.place(&nl);
        let k2 = self.op(format!("add i64 {}, 1", kv))?;
        self.ins(format!("store i64 {}, ptr {}", k2, k))?;
        self.br(&cl)?;
        self.place(&el);
        let res = self.op(format!("load i1, ptr {}", r))?;
        Ok(V::new(Kind::I1, res))
    }

    pub fn cquant(&mut self, e: &Expr) -> R<V> {
        let x = match e {
            Expr::Quant(q) => q,
            _ => return Err("llvmgen: internal error: cquant on non-quantifier".to_string()),
        };
        if x.kind == "forall" {
            if let Some(sorted_arr) = crate::emit_common::match_sorted_requires(e) {
                // G2 B2: if the matched array is a str, skip the fast path and take the general path
                let is_str = self.cenv.get(&sorted_arr).map_or(false, |v| is_strv(&v.ty));
                if !is_str {
                    let q = self.nq;
                    self.nq += 1;
                    return self.csorted(&sorted_arr, q);
                }
            }
        }
        let lo = self.cev(&x.lo)?;
        let hi = self.cev(&x.hi)?;
        let q = self.nq;
        self.nq += 1;
        let k = format!("%q{}.k", q);
        let r = format!("%q{}.r", q);
        let h = format!("%q{}.h", q);
        let kind = x.kind.as_str();
        let is_mm = kind == "max" || kind == "min";
        self.allocas.push(format!("{} = alloca i128", k));
        let rty = if kind == "forall" || kind == "exists" { "i1" } else { "i128" };
        self.allocas.push(format!("{} = alloca {}", r, rty));
        if is_mm {
            self.allocas.push(format!("{} = alloca i1", h));
        }
        self.ins(format!("store i128 {}, ptr {}", lo.a, k))?;
        if kind == "forall" {
            self.ins(format!("store i1 true, ptr {}", r))?;
        } else if kind == "exists" {
            self.ins(format!("store i1 false, ptr {}", r))?;
        } else {
            self.ins(format!("store i128 0, ptr {}", r))?;
        }
        if is_mm {
            self.ins(format!("store i1 false, ptr {}", h))?;
        }
        let cl = self.label("qc");
        let bl = self.label("qb");
        let nl = self.label("qn");
        let el = self.label("qe");
        self.br(&cl)?;
        self.place(&cl);
        let kv = self.op(format!("load i128, ptr {}", k))?;
        let c = self.op(format!("icmp slt i128 {}, {}", kv, hi.a))?;
        self.condbr(&c, &bl, &el)?;
        self.place(&bl);
        self.spend()?;
        let saved = self.cenv.get(&x.var).cloned();
        self.cenv.insert(x.var.clone(), V::new(Kind::I128, kv.clone()));
        let body = &x.body;
        let b = self.cregion(&|g| g.cev(body))?;
        match saved {
            None => {
                self.cenv.remove(&x.var);
            }
            Some(s) => {
                self.cenv.insert(x.var.clone(), s);
            }
        }
        if kind == "forall" || kind == "exists" {
            let stop = self.label("qstop");
            if kind == "forall" {
                self.condbr(&b.a, &nl, &stop)?;
            } else {
                self.condbr(&b.a, &stop, &nl)?;
            }
            self.place(&stop);
            self.ins(format!("store i1 {}, ptr {}", if kind == "forall" { "false" } else { "true" }, r))?;
            self.br(&el)?;
        } else {
            let old = self.op(format!("load i128, ptr {}", r))?;
            let nv;
            if kind == "sum" {
                nv = self.checked("i128", "sadd", "+", &old, &b.a)?;
            } else if kind == "count" {
                let z = self.op(format!("zext i1 {} to i128", b.a))?;
                nv = self.op(format!("add i128 {}, {}", old, z))?;
            } else {
                let hv = self.op(format!("load i1, ptr {}", h))?;
                let cmp = self.op(format!("icmp {} i128 {}, {}", if kind == "max" { "sgt" } else { "slt" }, b.a, old))?;
                let nh = self.op(format!("xor i1 {}, true", hv))?;
                let better = self.op(format!("or i1 {}, {}", nh, cmp))?;
                nv = self.op(format!("select i1 {}, i128 {}, i128 {}", better, b.a, old))?;
                self.ins(format!("store i1 true, ptr {}", h))?;
            }
            self.ins(format!("store i128 {}, ptr {}", nv, r))?;
            self.br(&nl)?;
        }
        self.place(&nl);
        let k2 = self.op(format!("add i128 {}, 1", kv))?;
        self.ins(format!("store i128 {}, ptr {}", k2, k))?;
        self.br(&cl)?;
        self.place(&el);
        if is_mm {
            let hv = self.op(format!("load i1, ptr {}", h))?;
            self.guard(&hv, Fail::Panic1("pruv_panic_undefined", format!("{} over an empty range", kind)), false)?;
        }
        let res = self.op(format!("load {}, ptr {}", rty, r))?;
        Ok(V::new(if rty == "i1" { Kind::I1 } else { Kind::I128 }, res))
    }
}

fn cmp_name(op: &str) -> R<&'static str> {
    match op {
        "==" => Ok("eq"),
        "!=" => Ok("ne"),
        "<" => Ok("slt"),
        "<=" => Ok("sle"),
        ">" => Ok("sgt"),
        ">=" => Ok("sge"),
        _ => Err(format!("'{}'", op)),
    }
}

pub fn entry_of(
    m: &mut Mod,
    tt: &TypeTable,
    funcs: &HashMap<String, &Function>,
    f: &Function,
    trust: bool,
    budget: u64,
    cost: bool,
) -> R<String> {
    let mut g = FnGen::new(m, tt, funcs, f, true);
    let mut params = ir_params(f, tt);
    let rt = ir_ret(tt, f); // G9 A3: "void" for an extended result (output storage is the leading `ptr %out`)
    if trust && !cost {
        g.place("start");
    } else {
        g.bind_contract_params()?;
        let bname = "%req.budget".to_string();
        g.budget = Some(bname.clone());
        g.allocas.push(format!("{} = alloca i64", bname));
        g.ins(format!("store i64 {}, ptr {}", budget, bname))?;
        for r in f.requires.iter().filter(|_| !trust) {
            let c = g.cregion(&|g2| g2.cev(r))?;
            // G4: the source-qualified identity, not the stem
            let disp = g.m.fn_disp.get(&f.name).cloned().unwrap_or_else(|| f.name.clone());
            let msg_fn = g.m.string(&disp);
            let msg_ex = g.m.string(&crate::emit_common::show(r));
            g.guard(&c.a, Fail::Requires(msg_fn, msg_ex), false)?;
        }
    }
    if cost {
        let expr = f.cost.as_ref().ok_or_else(|| "missing cost bound".to_string())?;
        let value = g.cregion(&|g2| g2.cev(expr))?;
        g.term(format!("ret i128 {}", value.a))?;
        params.retain(|(_, n)| n != "%out");
        return Ok(g.render(&format!("define internal i128 @{}__pruv_cost({})", mangle(&f.name), sig_text(&params, None))));
    }
    let args = params.iter().map(|(t, n)| format!("{} {}", t, n)).collect::<Vec<_>>().join(", ");
    let callee = format!("@{}__pruv_body", mangle(&f.name));
    if f.ret == "unit" || rt == "void" {
        g.ins(format!("call void {}({})", callee, args))?;
        g.term("ret void".to_string())?;
    } else {
        let r = g.op(format!("call {} {}({})", rt, callee, args))?;
        g.term(format!("ret {} {}", rt, r))?;
    }
    Ok(g.render(&format!("define internal {} @{}__pruv_entry({})", rt, mangle(&f.name), sig_text(&params, Some(f)))))
}

// ======================================================================================================================
// G9 A3: recursive values and aggregate buffer fields (docs/G9_SPEC.md 4, 6, 7, 13); counterpart of the g9_* section of
// llvmgen.py (see its design note: layout, values, ownership, calls and the stable helper names).
// ======================================================================================================================

/// [(variant name or None, tag or None, fields)] in declaration order
type Var9<'t> = (Option<&'t str>, Option<usize>, &'t [FieldDecl]);

/// A function that stands in for `None` (the helper generators have no function): never read by the helper code.
fn dummy_fn() -> Function {
    Function {
        line: 0,
        col: 0,
        name: String::new(),
        params: vec![],
        ret: "unit".to_string(),
        effects: vec![],
        requires: vec![],
        ensures: vec![],
        body: vec![],
        ret_refine: None,
        tparams: vec![],
        foreign: None,
        cost: None, decreases: None,
    }
}

fn g9_gep(g: &mut FnGen, t: &str, p: &str, idx: usize) -> R<String> {
    g.op(format!("getelementptr inbounds {}, ptr {}, i32 0, i32 {}", t, p, idx))
}

fn g9_variants(d: &TypeDecl) -> Vec<Var9<'_>> {
    match d {
        TypeDecl::Struct(s) => vec![(None, None, s.fields.as_slice())],
        TypeDecl::Enum(e) => e
            .variants
            .iter()
            .enumerate()
            .map(|(i, v)| (Some(v.name.as_str()), Some(i), v.fields.as_slice()))
            .collect(),
    }
}

/// storage index of field i of variant vn (a struct: vn is None) inside the aggregate
fn g9_sidx(tt: &TypeTable, ty: &str, vn: Option<&str>, i: usize) -> R<usize> {
    match vn {
        None => Ok(i),
        Some(v) => payload_index(tt, ty, v, i),
    }
}

/// emit(variant name, fields) for the variants in vs. A struct runs it inline. An enum switches on the tag of the value
/// at `base` and continues, on every path, at a join label that is left as the current block.
fn g9_each_variant<'a>(
    g: &mut FnGen<'a>,
    ty: &str,
    d: &TypeDecl,
    base: &str,
    vs: &[Var9<'_>],
    emit: &mut dyn FnMut(&mut FnGen<'a>, Option<&str>, &[FieldDecl]) -> R<()>,
) -> R<()> {
    if let TypeDecl::Struct(_) = d {
        for (vn, _t, fs) in vs {
            emit(g, *vn, fs)?;
        }
        return Ok(());
    }
    if vs.is_empty() {
        return Ok(());
    }
    let tp = g.tag_ptr(ty, base)?;
    let tag = g.op(format!("load i64, ptr {}", tp))?;
    let done = g.label("gdone");
    let mut lbls: Vec<String> = Vec::new();
    for _ in vs {
        lbls.push(g.label("gv"));
    }
    let mut cases: Vec<String> = Vec::new();
    for ((_vn, t, _fs), l) in vs.iter().zip(&lbls) {
        cases.push(format!("i64 {}, label %{}", t.unwrap_or(0), l));
    }
    g.term(format!("switch i64 {}, label %{} [ {} ]", tag, done, cases.join(" ")))?;
    for ((vn, _t, fs), l) in vs.iter().zip(&lbls) {
        g.place(l);
        emit(g, *vn, fs)?;
        g.br(&done)?;
    }
    g.place(&done);
    Ok(())
}

/// (size, align) SSA names of the node type T computed by the backend from the target layout
fn g9_node_layout(g: &mut FnGen, t: &str) -> R<(String, String)> {
    let z = g.op(format!("getelementptr {}, ptr null, i32 1", t))?;
    let size = g.op(format!("ptrtoint ptr {} to i64", z))?;
    let a = g.op(format!("getelementptr {{ i8, {} }}, ptr null, i32 0, i32 1", t))?;
    let align = g.op(format!("ptrtoint ptr {} to i64", a))?;
    Ok((size, align))
}

fn g9_drop_text(m: &mut Mod, tt: &TypeTable, d: &TypeDecl) -> R<String> {
    let ty = d.name().to_string();
    let tl = lty(&ty);
    let df = dummy_fn();
    let funcs: HashMap<String, &Function> = HashMap::new();
    let mut g = FnGen::new(&mut *m, tt, &funcs, &df, true);
    g.place("start");
    let vs: Vec<Var9<'_>> = g9_variants(d)
        .into_iter()
        .filter(|(_, _, fs)| fs.iter().any(|f| is_arr_name(&f.ty) || g.is_ext(&f.ty)))
        .collect();
    g9_each_variant(&mut g, &ty, d, "%v", &vs, &mut |g, vn, fs| {
        for (i, f) in fs.iter().enumerate() {
            let ft = f.ty.as_str();
            if !(is_arr_name(ft) || g.is_ext(ft)) {
                continue;
            }
            let gp = g9_gep(g, &tl, "%v", g9_sidx(tt, &ty, vn, i)?)?;
            if g.fb(&ty, vn, &f.name) {
                // a boxed child: its contents first, then its node
                let c = g.op(format!("load ptr, ptr {}", gp))?;
                g.ins(format!("call void @pruv_dropnode__{}(ptr {})", ft, c))?;
            } else if is_arr_name(ft) {
                let x = g.op(format!("load {}, ptr {}", ARR, gp))?;
                let p0 = g.op(format!("extractvalue {} {}, 0", ARR, x))?;
                let p1 = g.op(format!("extractvalue {} {}, 1", ARR, x))?;
                let mut av = V::with_b(Kind::Arr, p0, p1);
                av.ty = elem_ty(ft);
                g.free_val(&av)?;
            } else {
                // an inline extended child (not a node)
                g.ins(format!("call void @pruv_drop__{}(ptr {})", ft, gp))?;
            }
        }
        Ok(())
    })?;
    g.term("ret void".to_string())?;
    Ok(g.render(&format!("define internal void @pruv_drop__{}(ptr %v)", d.name())))
}

fn g9_clone_text(m: &mut Mod, tt: &TypeTable, d: &TypeDecl) -> R<String> {
    let ty = d.name().to_string();
    let tl = lty(&ty);
    let df = dummy_fn();
    let funcs: HashMap<String, &Function> = HashMap::new();
    let mut g = FnGen::new(&mut *m, tt, &funcs, &df, true);
    g.place("start");
    // shallow copy: scalars, inactive null/zero slots; owners are fixed below
    let v0 = g.op(format!("load {}, ptr %src", tl))?;
    g.ins(format!("store {} {}, ptr %dst", tl, v0))?;
    let vs: Vec<Var9<'_>> = g9_variants(d)
        .into_iter()
        .filter(|(_, _, fs)| fs.iter().any(|f| is_arr_name(&f.ty) || g.is_ext(&f.ty)))
        .collect();
    g9_each_variant(&mut g, &ty, d, "%src", &vs, &mut |g, vn, fs| {
        for (i, f) in fs.iter().enumerate() {
            let ft = f.ty.as_str();
            if !(is_arr_name(ft) || g.is_ext(ft)) {
                continue;
            }
            let idx = g9_sidx(tt, &ty, vn, i)?;
            let gs = g9_gep(g, &tl, "%src", idx)?;
            let gd = g9_gep(g, &tl, "%dst", idx)?;
            if g.fb(&ty, vn, &f.name) {
                let c = g.op(format!("load ptr, ptr {}", gs))?;
                let nb = g.op(format!("call ptr @pruv_clonenode__{}(ptr {})", ft, c))?;
                g.ins(format!("store ptr {}, ptr {}", nb, gd))?;
            } else if is_arr_name(ft) {
                let x = g.op(format!("load {}, ptr {}", ARR, gs))?;
                let p = g.op(format!("extractvalue {} {}, 0", ARR, x))?;
                let n = g.op(format!("extractvalue {} {}, 1", ARR, x))?;
                let np = if is_bytes_ty(&elem_ty(ft)) {
                    g.op(format!("call ptr @pruv_copy_v2(ptr {}, i64 {}, i64 1, i64 1)", p, n))?
                } else {
                    g.op(format!("call ptr @pruv_copy(ptr {}, i64 {})", p, n))?
                };
                let a1 = g.op(format!("insertvalue {} {}, ptr {}, 0", ARR, x, np))?;
                g.ins(format!("store {} {}, ptr {}", ARR, a1, gd))?;
            } else {
                g.ins(format!("call void @pruv_clone__{}(ptr {}, ptr {})", ft, gs, gd))?;
            }
        }
        Ok(())
    })?;
    g.term("ret void".to_string())?;
    Ok(g.render(&format!("define internal void @pruv_clone__{}(ptr %src, ptr %dst)", d.name())))
}

/// box / dropnode / clonenode of a type that is the target of a boxed edge
fn g9_node_texts(m: &mut Mod, tt: &TypeTable, d: &TypeDecl) -> R<Vec<String>> {
    let n = d.name().to_string();
    let tl = lty(&n);
    let mut out: Vec<String> = Vec::new();
    let df = dummy_fn();
    let funcs: HashMap<String, &Function> = HashMap::new();
    {
        let mut g = FnGen::new(&mut *m, tt, &funcs, &df, true);
        g.place("start");
        let (size, align) = g9_node_layout(&mut g, &tl)?;
        let p = g.op(format!("call ptr @pruv_node_alloc_v1(i64 {}, i64 {})", size, align))?;
        g.ins(format!("store {} %v, ptr {}", tl, p))?;
        g.term(format!("ret ptr {}", p))?;
        out.push(g.render(&format!("define internal ptr @pruv_box__{}({} %v)", n, tl)));
    }
    {
        let mut g = FnGen::new(&mut *m, tt, &funcs, &df, true);
        g.place("start");
        g.ins(format!("call void @pruv_drop__{}(ptr %n)", n))?;
        let (size, align) = g9_node_layout(&mut g, &tl)?;
        g.ins(format!("call void @pruv_node_free_v1(ptr %n, i64 {}, i64 {})", size, align))?;
        g.term("ret void".to_string())?;
        out.push(g.render(&format!("define internal void @pruv_dropnode__{}(ptr %n)", n)));
    }
    {
        let mut g = FnGen::new(&mut *m, tt, &funcs, &df, true);
        g.place("start");
        let (size, align) = g9_node_layout(&mut g, &tl)?;
        let p = g.op(format!("call ptr @pruv_node_alloc_v1(i64 {}, i64 {})", size, align))?;
        g.ins(format!("call void @pruv_clone__{}(ptr %src, ptr {})", n, p))?;
        g.term(format!("ret ptr {}", p))?;
        out.push(g.render(&format!("define internal ptr @pruv_clonenode__{}(ptr %src)", n)));
    }
    Ok(out)
}

/// size / equality walk into t: a nominal value, or Option / Result of one
fn g9_walks(t: &str) -> bool {
    if is_gopt(t) {
        return g9_walks(g_arg(t));
    }
    crate::emit_common::is_user_key(t)
}

/// i128 SSA value of weight(value stored at p) (G9_SPEC 3), or None when it is statically 0. Some / Ok weigh their
/// payload, None / Err 0; a nominal value weighs its size (one budget unit per node, inside pruv_csize). bud is the
/// budget pointer the size helper charges.
fn g9_weight(g: &mut FnGen, t: &str, p: &str, bud: &str) -> R<Option<String>> {
    if is_gopt(t) {
        let x = g_arg(t);
        if !g9_walks(x) {
            return Ok(None);
        }
        let tl = st(t, false);
        let g0 = g9_gep(g, &tl, p, 0)?;
        let tag = g.op(format!("load i1, ptr {}", g0))?;
        let pl = g9_gep(g, &tl, p, 1)?;
        let lcur = g.cur.clone();
        let yes = g.label("gwy");
        let end = g.label("gwe");
        g.condbr(&tag, &yes, &end)?;
        g.place(&yes);
        let w = g9_weight(g, x, &pl, bud)?.unwrap_or_else(|| "None".to_string());
        let wcur = g.cur.clone();
        g.br(&end)?;
        g.place(&end);
        let r = g.op(format!("phi i128 [ 0, %{} ], [ {}, %{} ]", lcur, w, wcur))?;
        return Ok(Some(r));
    }
    if crate::emit_common::is_user_key(t) {
        let r = g.op(format!("call i128 @pruv_csize__{}(ptr {}, ptr {})", t, p, bud))?;
        return Ok(Some(r));
    }
    Ok(None)
}

/// 1 + the weights of the ACTIVE fields of one variant, checked i128 additions in field order
fn g9_size_fold(g: &mut FnGen, tt: &TypeTable, ty: &str, tl: &str, vn: Option<&str>, fs: &[FieldDecl]) -> R<String> {
    let mut acc = "1".to_string();
    for (i, f) in fs.iter().enumerate() {
        if !g9_walks(&f.ty) {
            continue;
        }
        let mut gp = g9_gep(g, tl, "%v", g9_sidx(tt, ty, vn, i)?)?;
        if g.fb(ty, vn, &f.name) {
            gp = g.op(format!("load ptr, ptr {}", gp))?;
        }
        let w = g9_weight(g, &f.ty, &gp, "%bud")?.unwrap_or_else(|| "None".to_string());
        acc = g.checked("i128", "sadd", "+", &acc, &w)?;
    }
    Ok(acc)
}

/// pruv_csize__T: 1 + the weights of the ACTIVE fields, checked i128 additions in field order, one budget unit
fn g9_size_text(m: &mut Mod, tt: &TypeTable, d: &TypeDecl) -> R<String> {
    let ty = d.name().to_string();
    let tl = lty(&ty);
    let df = dummy_fn();
    let funcs: HashMap<String, &Function> = HashMap::new();
    let mut g = FnGen::new(&mut *m, tt, &funcs, &df, true);
    g.place("start");
    g.budget = Some("%bud".to_string());
    g.spend()?;
    match d {
        TypeDecl::Struct(s) => {
            let acc = g9_size_fold(&mut g, tt, &ty, &tl, None, &s.fields)?;
            g.term(format!("ret i128 {}", acc))?;
        }
        TypeDecl::Enum(_) => {
            g.allocas.push("%res = alloca i128".to_string());
            g.ins("store i128 1, ptr %res".to_string())?;
            let vs: Vec<Var9<'_>> = g9_variants(d)
                .into_iter()
                .filter(|(_, _, fs)| fs.iter().any(|f| g9_walks(&f.ty)))
                .collect();
            g9_each_variant(&mut g, &ty, d, "%v", &vs, &mut |g, vn, fs| {
                let acc = g9_size_fold(g, tt, &ty, &tl, vn, fs)?;
                g.ins(format!("store i128 {}, ptr %res", acc))
            })?;
            let r = g.op("load i128, ptr %res".to_string())?;
            g.term(format!("ret i128 {}", r))?;
        }
    }
    Ok(g.render(&format!("define internal i128 @pruv_csize__{}(ptr %v, ptr %bud)", d.name())))
}

/// i1 SSA value: structural equality of the values stored at pa and pb (type t)
fn g9_eq_val(g: &mut FnGen, t: &str, pa: &str, pb: &str) -> R<String> {
    if is_gopt(t) {
        // Option<X> / Result<X>: equal tags, then the active payload only
        let tl = st(t, false);
        let x = g_arg(t);
        let ga = g9_gep(g, &tl, pa, 0)?;
        let ta = g.op(format!("load i1, ptr {}", ga))?;
        let gb = g9_gep(g, &tl, pb, 0)?;
        let tb = g.op(format!("load i1, ptr {}", gb))?;
        let te = g.op(format!("icmp eq i1 {}, {}", ta, tb))?;
        let lcur = g.cur.clone();
        let l1 = g.label("gqa");
        let lend = g.label("gqe");
        g.condbr(&te, &l1, &lend)?;
        g.place(&l1);
        let l2 = g.label("gqb");
        if t.starts_with("option<") {
            g.condbr(&ta, &l2, &lend)?; // None == None
            g.place(&l2);
            let ax = g9_gep(g, &tl, pa, 1)?;
            let bx = g9_gep(g, &tl, pb, 1)?;
            let e = g9_eq_val(g, x, &ax, &bx)?;
            let l2cur = g.cur.clone();
            g.br(&lend)?;
            g.place(&lend);
            return g.op(format!("phi i1 [ false, %{} ], [ true, %{} ], [ {}, %{} ]", lcur, l1, e, l2cur));
        }
        let l3 = g.label("gqc");
        g.condbr(&ta, &l2, &l3)?;
        g.place(&l2);
        let ax = g9_gep(g, &tl, pa, 1)?;
        let bx = g9_gep(g, &tl, pb, 1)?;
        let e = g9_eq_val(g, x, &ax, &bx)?;
        let l2cur = g.cur.clone();
        g.br(&lend)?;
        g.place(&l3);
        let ga2 = g9_gep(g, &tl, pa, 2)?;
        let ea = g.op(format!("load i64, ptr {}", ga2))?;
        let gb2 = g9_gep(g, &tl, pb, 2)?;
        let eb = g.op(format!("load i64, ptr {}", gb2))?;
        let e3 = g.op(format!("icmp eq i64 {}, {}", ea, eb))?;
        let l3cur = g.cur.clone();
        g.br(&lend)?;
        g.place(&lend);
        return g.op(format!("phi i1 [ false, %{} ], [ {}, %{} ], [ {}, %{} ]", lcur, e, l2cur, e3, l3cur));
    }
    if t == "option" || t == "result" {
        // legacy Option<i64> / Result<i64>: { i1, i64 }
        let la = g.op(format!("load {}, ptr {}", OPT, pa))?;
        let lb = g.op(format!("load {}, ptr {}", OPT, pb))?;
        let ta = g.op(format!("extractvalue {} {}, 0", OPT, la))?;
        let tb = g.op(format!("extractvalue {} {}, 0", OPT, lb))?;
        let va = g.op(format!("extractvalue {} {}, 1", OPT, la))?;
        let vb = g.op(format!("extractvalue {} {}, 1", OPT, lb))?;
        let te = g.op(format!("icmp eq i1 {}, {}", ta, tb))?;
        let mut pe = g.op(format!("icmp eq i64 {}, {}", va, vb))?;
        if t == "option" {
            let nt = g.op(format!("xor i1 {}, true", ta))?;
            pe = g.op(format!("or i1 {}, {}", nt, pe))?;
        }
        return g.op(format!("and i1 {}, {}", te, pe));
    }
    if t == "i64" || t == "bool" {
        let ty = if t == "i64" { "i64" } else { "i1" };
        let la = g.op(format!("load {}, ptr {}", ty, pa))?;
        let lb = g.op(format!("load {}, ptr {}", ty, pb))?;
        return g.op(format!("icmp eq {} {}, {}", ty, la, lb));
    }
    if crate::emit_common::is_user_key(t) {
        return g.op(format!("call i1 @pruv_ceq__{}(ptr {}, ptr {}, ptr %bud)", t, pa, pb));
    }
    Err(format!("llvmgen: internal error: no structural equality for type {}", t))
}

/// the equal-fields chain of one variant: every field of fs must be equal, else jump to `fail`; ends with `ret i1 true`
fn g9_eq_conj(g: &mut FnGen, tt: &TypeTable, ty: &str, tl: &str, fail: &str, vn: Option<&str>, fs: &[FieldDecl]) -> R<()> {
    for (i, f) in fs.iter().enumerate() {
        let idx = g9_sidx(tt, ty, vn, i)?;
        let mut pa = g9_gep(g, tl, "%a", idx)?;
        let mut pb = g9_gep(g, tl, "%b", idx)?;
        if g.fb(ty, vn, &f.name) {
            pa = g.op(format!("load ptr, ptr {}", pa))?;
            pb = g.op(format!("load ptr, ptr {}", pb))?;
        }
        let e = g9_eq_val(g, &f.ty, &pa, &pb)?;
        let nxt = g.label("ceqn");
        g.condbr(&e, &nxt, fail)?;
        g.place(&nxt);
    }
    g.term("ret i1 true".to_string())
}

/// pruv_ceq__T: one budget unit, then equal tags and the fields of the active variant, left to right
fn g9_eq_text(m: &mut Mod, tt: &TypeTable, d: &TypeDecl) -> R<String> {
    let ty = d.name().to_string();
    let tl = lty(&ty);
    let df = dummy_fn();
    let funcs: HashMap<String, &Function> = HashMap::new();
    let mut g = FnGen::new(&mut *m, tt, &funcs, &df, true);
    g.place("start");
    g.budget = Some("%bud".to_string());
    g.spend()?;
    let fail = g.label("ceqf");
    match d {
        TypeDecl::Struct(s) => g9_eq_conj(&mut g, tt, &ty, &tl, &fail, None, &s.fields)?,
        TypeDecl::Enum(_) => {
            let pa = g.tag_ptr(&ty, "%a")?;
            let tl_ = g.op(format!("load i64, ptr {}", pa))?;
            let pb = g.tag_ptr(&ty, "%b")?;
            let tr = g.op(format!("load i64, ptr {}", pb))?;
            let same = g.label("ceqs");
            let dflt = g.label("ceqt");
            let teq = g.op(format!("icmp eq i64 {}, {}", tl_, tr))?;
            g.condbr(&teq, &same, &fail)?;
            g.place(&same);
            let vs: Vec<Var9<'_>> = g9_variants(d).into_iter().filter(|(_, _, fs)| !fs.is_empty()).collect();
            let mut lbls: Vec<String> = Vec::new();
            for _ in &vs {
                lbls.push(g.label("ceqv"));
            }
            let mut cases: Vec<String> = Vec::new();
            for ((_vn, t, _fs), l) in vs.iter().zip(&lbls) {
                cases.push(format!("i64 {}, label %{}", t.unwrap_or(0), l));
            }
            g.term(format!("switch i64 {}, label %{} [ {} ]", tl_, dflt, cases.join(" ")))?;
            g.place(&dflt);
            g.term("ret i1 true".to_string())?;
            for ((vn, _t, fs), l) in vs.iter().zip(&lbls) {
                g.place(l);
                g9_eq_conj(&mut g, tt, &ty, &tl, &fail, *vn, fs)?;
            }
        }
    }
    g.place(&fail);
    g.term("ret i1 false".to_string())?;
    Ok(g.render(&format!("define internal i1 @pruv_ceq__{}(ptr %a, ptr %b, ptr %bud)", d.name())))
}

/// names of the user types a field of type t can contribute to `size` / structural equality: the type itself, or the
/// payload type of Option / Result (arrays, str and scalars contribute nothing)
fn g9_nominals_in(t: &str) -> Vec<String> {
    if is_gopt(t) {
        return g9_nominals_in(g_arg(t));
    }
    if crate::emit_common::is_user_key(t) {
        return vec![t.to_string()];
    }
    Vec::new()
}

/// clone / drop / node helpers of every extended type (SCC-condensed order), then the contract size / equality helpers
/// the requires checks needed (closed over the nominal field types, declaration order)
fn g9_helper_chunks(m: &mut Mod, tt: &TypeTable) -> R<Vec<String>> {
    let mut targets: HashSet<String> = HashSet::new();
    for d in tt.ordered() {
        for (vn, _t, fs) in g9_variants(d) {
            for f in fs {
                if tt.g9_boxed.contains(&fld_label(d.name(), vn, &f.name)) {
                    targets.insert(f.ty.clone());
                }
            }
        }
    }
    let mut chunks: Vec<String> = Vec::new();
    for d in tt.ordered() {
        if !tt.g9_ext.contains(d.name()) {
            continue;
        }
        chunks.push(g9_drop_text(m, tt, d)?);
        chunks.push(g9_clone_text(m, tt, d)?);
        if targets.contains(d.name()) {
            chunks.extend(g9_node_texts(m, tt, d)?);
        }
    }
    let close = |seed: &BTreeSet<String>| -> BTreeSet<String> {
        let mut out: BTreeSet<String> = BTreeSet::new();
        let mut work: Vec<String> = seed.iter().cloned().collect();
        while let Some(n) = work.pop() {
            if out.contains(&n) {
                continue;
            }
            let d = match tt.decl(&n) {
                Some(d) => d,
                None => continue,
            };
            out.insert(n);
            for (_vn, _t, fs) in g9_variants(d) {
                for f in fs {
                    work.extend(g9_nominals_in(&f.ty));
                }
            }
        }
        out
    };
    let sizes = close(&m.need_size);
    let eqs = close(&m.need_eq);
    for d in &tt.decls {
        if sizes.contains(d.name()) {
            chunks.push(g9_size_text(m, tt, d)?);
        }
        if eqs.contains(d.name()) {
            chunks.push(g9_eq_text(m, tt, d)?);
        }
    }
    Ok(chunks)
}

// ---------- requires helper functions ----------
pub fn cdivrem(m: &mut Mod, is_div: bool) -> String {
    let (nm, sym) = if is_div { ("pruv_cdiv", "/") } else { ("pruv_crem", "%") };
    let z = m.string(&format!("division by zero in {}", sym));
    let o = m.string(&format!("i128 overflow in {}", sym));
    let res = if is_div { "%qq" } else { "%rr" };
    format!(
        "define internal i128 @{nm}(i128 %a, i128 %b) {{\n\
entry:\n\
\x20 %z = icmp eq i128 %b, 0\n\
\x20 br i1 %z, label %dz, label %c1\n\
dz:\n\
\x20 call void @pruv_panic_undefined(ptr {z})\n\
\x20 unreachable\n\
c1:\n\
\x20 %am = icmp eq i128 %a, {min}\n\
\x20 %bm = icmp eq i128 %b, -1\n\
\x20 %ov = and i1 %am, %bm\n\
\x20 br i1 %ov, label %of, label %c2\n\
of:\n\
\x20 call void @pruv_panic_undefined(ptr {o})\n\
\x20 unreachable\n\
c2:\n\
\x20 %q = sdiv i128 %a, %b\n\
\x20 %r = srem i128 %a, %b\n\
\x20 %neg = icmp slt i128 %r, 0\n\
\x20 %bp = icmp sgt i128 %b, 0\n\
\x20 %ra = add i128 %r, %b\n\
\x20 %rs = sub i128 %r, %b\n\
\x20 %r2 = select i1 %bp, i128 %ra, i128 %rs\n\
\x20 %rr = select i1 %neg, i128 %r2, i128 %r\n\
\x20 %qd = select i1 %bp, i128 -1, i128 1\n\
\x20 %q2 = add i128 %q, %qd\n\
\x20 %qq = select i1 %neg, i128 %q2, i128 %q\n\
\x20 ret i128 {res}\n\
}}\n",
        nm = nm,
        z = z,
        min = SIGNED_MIN128,
        o = o,
        res = res
    )
}

/// Program -> (IR text, Rust bindings text). Err is the message at the place where Python raises an exception.
pub fn gen_llvm(prog: &Program, verified: bool, trust_callers: bool, budget: u64) -> R<(String, String)> {
    gen_llvm_for(prog, verified, trust_callers, budget, AbiTarget::SysV)
}

const WIN_X64_HEADER: &str = "target datalayout = \"e-m:w-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-f80:128-n8:16:32:64-S128\"\ntarget triple = \"x86_64-pc-windows-msvc\"\n\n";

fn g6_scalar(t: &str) -> bool {
    t == "i64" || t == "bool"
}

/// G6_SPEC 13.1 collections, plus the G10 File handle.
fn g6_coll_ok(t: &str) -> bool {
    use crate::gtype::GType;
    match GType::try_from_key(t) {
        Ok(g) => match g.name.as_str() {
            "vec" => g.args.first().map_or(false, |a| g6_scalar(&a.to_key())),
            "hashmap" => g.args.len() >= 2 && g6_scalar(&g.args[0].to_key()) && g6_scalar(&g.args[1].to_key()),
            _ => matches!(g.name.as_str(), "string" | "file"),
        },
        Err(_) => false,
    }
}

/// a type that may occur in a G6 program on LLVM: no collection, or a supported one (never nested)
fn g6_type_ok(t: &str) -> bool {
    if is_collection(t) {
        return g6_coll_ok(t);
    }
    !contains_collection(t)
}

/// PruvError codegen/unsupported_type for the first G6 construct outside G6_SPEC 13.1, or None. Source order:
/// functions in order, the signature before the body, inside a body the earliest position.
pub fn g6_llvm_error(prog: &Program) -> Option<crate::diagnostic::PruvError> {
    use crate::foreign_shim::{walk_stmts, Node};
    crate::foreign::first_g6_use(prog)?;
    let err = |line: i64, col: i64| {
        crate::diagnostic::PruvError::new("codegen", line, col, "unsupported_type", G6_UNSUPPORTED_MSG, G6_UNSUPPORTED_FIX)
    };
    for f in &prog.functions {
        if f.foreign.is_some() {
            // G6b: catalog String or exactly Vec<i64> results are boxed handles
            let owned = crate::gtype::GType::try_from_key(&f.ret).map(|t| crate::foreign::owned_result(&t)).unwrap_or(false);
            let ok = (matches!(f.ret.as_str(), "i64" | "bool" | "unit") || owned)
                && f.params.iter().all(|p| {
                    matches!(p.ty.as_str(), "i64" | "bool" | "array" | "array_u8" | "array_bool" | "str") && !p.take
                });
            if !ok {
                return Some(err(f.line, f.col));
            }
            continue;
        }
        if f.params.iter().any(|p| !g6_type_ok(&p.ty)) || !g6_type_ok(&f.ret) {
            return Some(err(f.line, f.col));
        }
        let mut bad: Vec<(i64, i64)> = Vec::new();
        walk_stmts(&f.body, &mut |n: Node<'_>| match n {
            Node::Let(l) => {
                if !g6_type_ok(&l.ty) {
                    bad.push((l.line, l.col));
                }
            }
            Node::Expr(e) => {
                if let Some(t) = expr_ty(e) {
                    if !g6_type_ok(t) {
                        bad.push((e.line(), e.col()));
                    }
                }
                if let Expr::Call(c) = e {
                    if crate::foreign::is_catalog(&c.name) && !crate::foreign::is_catalog_contract_only(&c.name) {
                        if let Some(inst) = &c.inst {
                            if !inst.args.iter().all(|a| g6_scalar(&a.to_key())) {
                                bad.push((c.line, c.col));
                            }
                        }
                    }
                }
            }
        });
        if let Some(&(line, col)) = bad.iter().min() {
            return Some(err(line, col));
        }
    }
    None
}

fn is_coll_fn(f: &Function) -> bool {
    f.params.iter().any(|p| is_collection(&p.ty)) || is_collection(&f.ret)
}

/// Python `is_host_abi_fn`: a function that gets `pruv_abi_*` wrappers: legacy = every ordinary function that is not a
/// specialization or collection/extended-bearing; G4 explicit mode = additionally only the host entries (a child-public
/// function is never exported just because Pruv callers can name it). `host` = the function's host-entry flag.
pub fn is_host_abi_fn(f: &Function, tt: &TypeTable, explicit: bool, host: bool) -> bool {
    f.foreign.is_none()
        && !crate::emit_common::is_spec_fn(&f.name)
        && !is_coll_fn(f)
        && !has_inout(f)
        && !is_internal_fn(f, tt)
        && (host || !explicit)
}

/// Generation with a chosen target ABI. SysV is byte-identical to gen_llvm.
pub fn gen_llvm_for(prog: &Program, verified: bool, trust_callers: bool, budget: u64, target: AbiTarget) -> R<(String, String)> {
    gen_llvm_any(prog, verified, trust_callers, budget, target).map_err(|e| match e {
        crate::codegen::GenError::Msg(m) => m,
        crate::codegen::GenError::Diag(p) => format!("{}: {}", p.code, p.message),
    })
}

/// Python `gen_llvm`: a program that uses generics is specialized first (shared plan, mono.rs; a specialization limit is
/// a diagnostic) and lowered from the concrete program; any other program is lowered directly.
pub fn gen_llvm_any(
    prog: &Program,
    verified: bool,
    trust_callers: bool,
    budget: u64,
    target: AbiTarget,
) -> Result<(String, String), crate::codegen::GenError> {
    gen_llvm_any_ex(prog, verified, trust_callers, budget, target, "requires")
}

/// `gen_llvm_any` with the G6 boundary check mode of the shim helpers (requires|all|off, docs/G6_SPEC.md 12.3).
/// A G6 program outside the supported subset (G6_SPEC 13.1) is a codegen/unsupported_type diagnostic.
pub fn gen_llvm_any_ex(
    prog: &Program,
    verified: bool,
    trust_callers: bool,
    budget: u64,
    target: AbiTarget,
    foreign_checks: &str,
) -> Result<(String, String), crate::codegen::GenError> {
    gen_llvm_any_ex_g4(prog, None, verified, trust_callers, budget, target, foreign_checks)
}

/// `gen_llvm_any` for a checked program of explicit visibility mode (G4 A3; `g4` = None is `gen_llvm_any`).
pub fn gen_llvm_any_g4(
    prog: &Program,
    g4: Option<&crate::modules::G4>,
    verified: bool,
    trust_callers: bool,
    budget: u64,
    target: AbiTarget,
) -> Result<(String, String), crate::codegen::GenError> {
    gen_llvm_any_ex_g4(prog, g4, verified, trust_callers, budget, target, "requires")
}

/// `gen_llvm_any_ex` with the explicit-mode data (G4 A3): explicit mode always goes through the specialization plan, which
/// names every function and type by its Rust stem (Python `gen_llvm`: `first_g3_use(prog) is not None or prog.explicit`).
pub fn gen_llvm_any_ex_g4(
    prog: &Program,
    g4: Option<&crate::modules::G4>,
    verified: bool,
    trust_callers: bool,
    budget: u64,
    target: AbiTarget,
    foreign_checks: &str,
) -> Result<(String, String), crate::codegen::GenError> {
    use crate::codegen::GenError;
    if !matches!(foreign_checks, "requires" | "all" | "off") {
        return Err(GenError::Msg("foreign_checks must be requires, all or off".to_string()));
    }
    if crate::typeinfo::first_g3_use(prog).is_some() || g4.is_some() {
        let plan = crate::mono::specialize_g4(prog, g4).map_err(|e| match e {
            crate::mono::MonoError::Limit(p) => GenError::Diag(p),
            crate::mono::MonoError::Internal(m) => GenError::Msg(m),
        })?;
        return gen_llvm_concrete_ex(&plan.program, verified, trust_callers, budget, target, foreign_checks);
    }
    gen_llvm_concrete_ex(prog, verified, trust_callers, budget, target, foreign_checks)
}

/// The generator proper, for a CONCRETE program (a plan.program of mono.rs, or a program without G3): no type parameter
/// reaches it.
pub fn gen_llvm_concrete(prog: &Program, verified: bool, trust_callers: bool, budget: u64, target: AbiTarget) -> R<(String, String)> {
    gen_llvm_concrete_ex(prog, verified, trust_callers, budget, target, "requires").map_err(|e| match e {
        crate::codegen::GenError::Msg(m) => m,
        crate::codegen::GenError::Diag(p) => format!("{}: {}", p.code, p.message),
    })
}

/// `gen_llvm_concrete` with the G6 check mode; a diagnostic (G6 outside 13.1) is `GenError::Diag`.
pub fn gen_llvm_concrete_ex(
    prog: &Program,
    verified: bool,
    trust_callers: bool,
    budget: u64,
    target: AbiTarget,
    foreign_checks: &str,
) -> Result<(String, String), crate::codegen::GenError> {
    use crate::codegen::GenError;
    if !matches!(foreign_checks, "requires" | "all" | "off") {
        return Err(GenError::Msg("foreign_checks must be requires, all or off".to_string()));
    }
    if let Some(e) = g6_llvm_error(prog) {
        return Err(GenError::Diag(e));
    }
    gen_llvm_body(prog, verified, trust_callers, budget, target, foreign_checks).map_err(|s| match s.strip_prefix(G6_DIAG_TAG) {
        Some(rest) => {
            let mut it = rest.split(':');
            let line: i64 = it.next().and_then(|x| x.parse().ok()).unwrap_or(0);
            let col: i64 = it.next().and_then(|x| x.parse().ok()).unwrap_or(0);
            GenError::Diag(crate::diagnostic::PruvError::new(
                "codegen",
                line,
                col,
                "unsupported_type",
                G6_UNSUPPORTED_MSG,
                G6_UNSUPPORTED_FIX,
            ))
        }
        None => match s.strip_prefix(G9_DIAG_TAG) {
            // G9 A3: FnGen.g9_unsupported (a contract operand the LLVM backend cannot evaluate)
            Some(rest) => {
                let mut it = rest.splitn(3, ':');
                let line: i64 = it.next().and_then(|x| x.parse().ok()).unwrap_or(0);
                let col: i64 = it.next().and_then(|x| x.parse().ok()).unwrap_or(0);
                let what = it.next().unwrap_or("");
                GenError::Diag(crate::diagnostic::PruvError::new(
                    "codegen",
                    line,
                    col,
                    "unsupported_type",
                    &format!("{} is not supported in a runtime requires by the llvm codegen layer yet", what),
                    "compare tags with is_variant and fields with variant_field, or move the check into the body",
                ))
            }
            None => GenError::Msg(s),
        },
    })
}

fn gen_llvm_body(
    prog: &Program,
    verified: bool,
    trust_callers: bool,
    budget: u64,
    target: AbiTarget,
    foreign_checks: &str,
) -> R<(String, String)> {
    fn collect_par(stmts: &[Stmt], names: &mut BTreeSet<String>) {
        for stmt in stmts {
            match stmt {
                Stmt::Par(p) => for call in &p.calls {
                    if let Expr::Call(c) = call { names.insert(c.name.clone()); }
                },
                Stmt::If(x) => { collect_par(&x.then, names); collect_par(&x.els, names); }
                Stmt::While(x) => collect_par(&x.body, names),
                Stmt::Match(x) => for arm in &x.arms { collect_par(&arm.body, names); },
                _ => {}
            }
        }
    }
    let mut par_targets = BTreeSet::new();
    for f in &prog.functions { collect_par(&f.body, &mut par_targets); }
    let is_g6 = crate::foreign::first_g6_use(prog).is_some();
    if let Some(e) = crate::typeinfo::g2_unimplemented_error(prog, "codegen", None, &["array_u8", "array_bool", "str"], None) {
        // G2 B2: str also opens the generation layer
        return Err(format!("unsupported_type: {}", e.message));
    }
    // G4 A3: the identities behind the Rust names (panic / enum texts); cleared again when the generator returns
    struct DispGuard;
    impl Drop for DispGuard {
        fn drop(&mut self) {
            crate::emit_common::set_type_disp(HashMap::new());
        }
    }
    let _disp_guard = DispGuard;
    crate::emit_common::set_type_disp(prog.explicit.as_ref().map(|x| x.tdisp.clone()).unwrap_or_default());
    // G9: SCC-condensed order and the extended / boxed metadata (identical to TypeTable::new otherwise)
    let tt = new_tt(prog);
    let mut m = Mod::new();
    let explicit = prog.explicit.is_some();
    m.explicit = explicit;
    // G4 A3: per function (parallel to prog.functions): host entry flag; the display identity map
    let hosts: Vec<bool> = match &prog.explicit {
        Some(x) => x.fns.iter().map(|mk| mk.host_entry).collect(),
        None => Vec::new(),
    };
    if let Some(x) = &prog.explicit {
        for (f, mk) in prog.functions.iter().zip(x.fns.iter()) {
            m.fn_disp.entry(f.name.clone()).or_insert_with(|| mk.disp.clone());
        }
    }
    let mut funcs: HashMap<String, &Function> = HashMap::new();
    for f in &prog.functions {
        funcs.insert(f.name.clone(), f);
    }
    let mut chunks: Vec<String> = Vec::new();
    // G4 A3 (docs/G4_SPEC.md 4, same policy as codegen.Gen): the functions that get a checked `__pruv_entry`.
    // Verified: only host entries with a requires (none under trust_callers); safe mode: every function with a requires,
    // also under trust_callers (it removes only the host-boundary checks)
    let checked_entry = |f: &Function, host: bool| -> bool {
        !f.requires.is_empty() && f.foreign.is_none() && (!verified || (host && !trust_callers))
    };
    let need_cdiv = if explicit {
        prog.functions.iter().enumerate().any(|(i, f)| checked_entry(f, hosts.get(i).copied().unwrap_or(false)))
    } else {
        // G5 A3: an inout entry checks also under trust_callers
        prog.functions.iter().any(|f| {
            !f.requires.is_empty() && f.foreign.is_none() && (!trust_callers || (!verified && has_inout(f)))
        })
    };
    let need_cdiv = need_cdiv || (!verified && prog.functions.iter().any(|f| !f.requires.is_empty() && par_targets.contains(&f.name)));
    let cost_used = !verified && prog.functions.iter().any(|f| f.cost.is_some());
    if need_cdiv || cost_used {
        chunks.push(cdivrem(&mut m, true));
        chunks.push(cdivrem(&mut m, false));
    }
    for (fi, f) in prog.functions.iter().enumerate() {
        if f.foreign.is_some() {
            // G6 A3: a trusted rust fn has no body; its calls go to the shim adapter
            continue;
        }
        // G6 A3: collection-bearing functions are internal (no ABI wrapper, no binding); G9 A3: so are functions with
        // an extended type in their signature
        let coll = is_coll_fn(f) || is_internal_fn(f, &tt);
        let mut g = FnGen::new(&mut m, &tt, &funcs, f, verified);
        g.body()?;
        let params = ir_params(f, &tt);
        let cost = g.cost;
        let body = g.render(&format!(
            "define internal {} @{}__pruv_body({})",
            ir_ret(&tt, f),
            mangle(&f.name),
            sig_text(&params, Some(f))
        ));
        if cost { chunks.push(entry_of(&mut m, &tt, &funcs, f, trust_callers, budget, true)?); }
        chunks.push(body);
        if !verified && !f.requires.is_empty() && par_targets.contains(&f.name) {
            chunks.push(entry_of(&mut m, &tt, &funcs, f, false, budget, false)?.replace(
                &format!("@{}__pruv_entry(", mangle(&f.name)),
                &format!("@{}__pruv_par_chk(", mangle(&f.name))));
        }
        if explicit {
            // G4 A3: bodies and checked wrappers are internal; only a host entry gets pruv_abi_* (and its typed variant).
            // The host boundary calls the checked wrapper unless trust_callers skips the check (or there is no requires).
            let host = hosts.get(fi).copied().unwrap_or(false);
            let checked = checked_entry(f, host);
            if checked {
                chunks.push(entry_of(&mut m, &tt, &funcs, f, false, budget, false)?);
            }
            if is_host_abi_fn(f, &tt, true, host) {
                chunks.push(crate::abi::abi_of_target(
                    f,
                    &tt,
                    target,
                    &mut m,
                    if checked && !trust_callers { "entry" } else { "body" },
                )?);
            }
            continue;
        }
        if !(coll && verified) {
            // verified callers call the body; the entry only serves safe-mode callers
            // G5 A3: the entry of an inout function is internal and always checked (trust_callers does not waive it)
            chunks.push(entry_of(
                &mut m,
                &tt,
                &funcs,
                f,
                (trust_callers && !has_inout(f)) || f.requires.is_empty(),
                budget,
                false,
            )?);
        }
        if !crate::emit_common::is_spec_fn(&f.name) && !coll {
            // G3: a generic specialization has no ABI symbol
            chunks.push(abi_of(f, &tt, target, &mut m)?);
        }
    }
    if !tt.g9_ext.is_empty() || !m.need_size.is_empty() || !m.need_eq.is_empty() {
        // G9 A3: clone / drop / node helpers, then the contract helpers above
        chunks.extend(g9_helper_chunks(&mut m, &tt)?);
    }
    // G9 A3: buffer fields count as uses of the buffer runtime declarations
    let has_str = crate::typeinfo::uses_str(prog, !verified) || type_has_field(prog, "str"); // G2 B2
    let g9_u8 = type_has_field(prog, "array_u8") || type_has_field(prog, "array_bool");
    // G6 A3: bridge marker and the shim symbols used, sorted by symbol
    let mut g6decls = String::new();
    if m.g6_bridge || !m.g6_decls.is_empty() {
        g6decls.push_str(G6_BRIDGE_DECL);
        for line in m.g6_decls.values() {
            g6decls.push_str(line);
            g6decls.push('\n');
        }
    }
    let mut ir = format!(
        "{}{}\n{}{}{}{}{}{}{}{}{}\n{}",
        if target == AbiTarget::WinX64 { WIN_X64_HEADER } else { "" },
        m.render_strings(),
        type_defs(&tt),
        if prog.types.is_empty() { "" } else { "\n" },
        DECLS,
        // G2 A5: DECLS_U8 if u8 or bool is used, and DECLS_BOOL after it if bool is used
        // G2 B2: DECLS_U8 if u8, bool or str is used, and DECLS_STR at the very end if str is used
        // G6 A3: DECLS_U8 also when string_to_str copies through pruv_copy_v2
        // G9 A3: DECLS_U8 also for a [u8] / [bool] buffer field
        if uses_array_type(prog, "array_u8") || uses_array_type(prog, "array_bool") || has_str || m.g6_v2 || g9_u8 {
            DECLS_U8
        } else {
            ""
        },
        if uses_array_type(prog, "array_bool") { DECLS_BOOL } else { "" },
        if has_str { DECLS_STR } else { "" },
        if m.uses_repr { DECLS_REPR } else { "" }, // G3
        if !tt.g9_boxed.is_empty() { DECLS_NODE } else { "" }, // G9 A3
        g6decls,
        chunks.join("\n")
    );
    if !m.par_trampolines.is_empty() {
        ir = format!("%pruv_g7_job = type {{ ptr, ptr }}\n{}\n{}", m.par_types.join("\n"), ir);
        ir.push_str("declare void @pruv_g7_v1_run(ptr, i64) nounwind\n");
        ir.push_str(&m.par_trampolines.join("\n"));
    }
    let mut shim = if is_g6 {
        Some(crate::foreign_shim::build_shim(prog, verified, trust_callers, budget, foreign_checks)?)
    } else {
        None
    };
    if prog.functions.iter().any(|f| crate::foreign::first_par(&f.body).is_some()) {
        shim.get_or_insert_with(String::new).push_str(&crate::parallel_shim::build_shim());
    }
    if cost_used {
        ir.push_str("declare void @pruv_panic_cost() noreturn cold nounwind\n");
        ir.push_str("declare { i128, i1 } @llvm.uadd.with.overflow.i128(i128, i128)\n");
        shim.get_or_insert_with(String::new).push_str(r#"
#[no_mangle]
pub extern "C" fn pruv_panic_cost() -> ! {
    eprintln!("pruv: cost exceeded");
    ::std::process::exit(101);
}
"#);
    }
    let bindings = crate::bindings::gen_bindings_with(prog, shim.as_deref(), verified)?;
    Ok((ir, bindings))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn mangle_and_types() {
        assert_eq!(mangle("a_b1"), "a_b1");
        assert_eq!(mangle("a.é"), "a$002e$00e9");
        assert_eq!(lty("bool"), "i1");
        assert_eq!(lty("Point"), "%pruv_t_Point");
        assert_eq!(st("i64", true), "i128");
        assert_eq!(st("Point", true), "%pruv_c_Point");
    }

    #[test]
    fn strings_render() {
        let mut m = Mod::new();
        assert_eq!(m.string("a\"b"), "@.str.0");
        assert_eq!(m.string("a\"b"), "@.str.0");
        assert_eq!(m.string("é"), "@.str.1");
        assert_eq!(
            m.render_strings(),
            "@.str.0 = private unnamed_addr constant [4 x i8] c\"a\\22b\\00\"\n@.str.1 = private unnamed_addr constant [3 x i8] c\"\\C3\\A9\\00\"\n"
        );
    }

    #[test]
    fn fn_gen_labels_and_guard() {
        let tt = TypeTable::new(&[]);
        let funcs: HashMap<String, &Function> = HashMap::new();
        let f = Function {
            line: 1,
            col: 1,
            name: "f".into(),
            params: vec![],
            ret: "unit".into(),
            effects: vec![],
            requires: vec![],
            ensures: vec![],
            body: vec![],
            ret_refine: None,
            tparams: vec![],
            foreign: None,
            cost: None, decreases: None,
        };
        let mut m = Mod::new();
        let mut g = FnGen::new(&mut m, &tt, &funcs, &f, false);
        g.place("start");
        let c = g.op("icmp eq i64 1, 1".to_string()).unwrap();
        g.guard(&c, Fail::Panic1("pruv_panic_arith", "x".to_string()), false).unwrap();
        let text = g.render("define internal void @f__pruv_body()");
        assert!(text.contains("  %t1 = icmp eq i64 1, 1\n  br i1 %t1, label %ok.1, label %fail.2\nfail.2:\n"));
    }

    fn opt_prog() -> Program {
        Program {
            types: vec![],
            functions: vec![Function {
                line: 1,
                col: 1,
                name: "f".into(),
                params: vec![],
                ret: "option".into(),
                effects: vec![],
                requires: vec![],
                ensures: vec![],
                body: vec![],
                ret_refine: None,
                tparams: vec![],
                foreign: None,
                cost: None, decreases: None,
            }],
            refined: false,
            g9: None,
            explicit: None,
            uses_inout: None,
        }
    }

    #[test]
    fn gen_llvm_for_targets() {
        let p = opt_prog();
        let (sys, b1) = gen_llvm(&p, false, false, 1000).unwrap_or_else(|e| panic!("{}", e));
        let (sys2, _) = gen_llvm_for(&p, false, false, 1000, AbiTarget::SysV).unwrap();
        assert_eq!(sys, sys2);
        assert!(sys.contains("define { i64, i64 } @pruv_abi_f()"));
        assert!(!sys.contains("target triple"));
        let (win, b2) = gen_llvm_for(&p, false, false, 1000, AbiTarget::WinX64).unwrap();
        let mut lines = win.lines();
        assert!(lines.next().unwrap().starts_with("target datalayout = \"e-m:w-p270:32:32"));
        assert_eq!(lines.next().unwrap(), "target triple = \"x86_64-pc-windows-msvc\"");
        assert_eq!(lines.next().unwrap(), "");
        assert!(win.contains("define void @pruv_abi_f(ptr sret({ i64, i64 }) align 8 %sret) {"));
        assert_eq!(b1, b2);
    }

    #[test]
    fn cdivrem_text() {
        let mut m = Mod::new();
        let t = cdivrem(&mut m, true);
        assert!(t.starts_with("define internal i128 @pruv_cdiv(i128 %a, i128 %b) {\nentry:\n  %z = icmp eq i128 %b, 0\n"));
        assert!(t.contains("icmp eq i128 %a, -170141183460469231731687303715884105728\n"));
        assert!(t.ends_with("  ret i128 %qq\n}\n"));
    }
}
