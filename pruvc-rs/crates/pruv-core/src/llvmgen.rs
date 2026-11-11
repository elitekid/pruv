//! Pruv -> LLVM IR text generator (a port of llvmgen.py lines 1-1327 plus gen_llvm).
//! Goal: for the same program and mode, byte-identical to the first return value of Python's gen_llvm.
//! Rule: mutable state (temp numbers, label numbers, scopes, temp-free lists, contract environment) is changed in the same order as in Python.
//! Python's None is imitated by the string "None" (the default of V's a/b).

use crate::abi::{abi_of, AbiTarget};
use crate::ast::*;
use crate::typeinfo::{is_array_name, is_user_type, uses_array_type, TypeTable};
use std::collections::HashMap;

pub type R<T> = Result<T, String>;

pub const SIGNED_MIN128: i128 = i128::MIN;
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
}

impl Kind {
    pub fn name(self) -> &'static str {
        match self {
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
        _ => format!("%pruv_{}_{}", if c { "c" } else { "t" }, t),
    }
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
    let mut base = 1usize;
    if let TypeDecl::Enum(e) = t_decl(tt, ty)? {
        for v in &e.variants {
            if v.name == variant {
                return Ok(base + i);
            }
            base += v.fields.len();
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
            let fs: Vec<String> = match d {
                TypeDecl::Struct(s) => s.fields.iter().map(|f| st(&f.ty, c)).collect(),
                TypeDecl::Enum(e) => {
                    let mut v = vec!["i64".to_string()];
                    for var in &e.variants {
                        for f in &var.fields {
                            v.push(st(&f.ty, c));
                        }
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
}

pub type Slot = V;

impl V {
    pub fn new(k: Kind, a: impl Into<String>) -> V {
        V { k, a: a.into(), b: "None".to_string(), ty: None }
    }
    pub fn with_b(k: Kind, a: impl Into<String>, b: impl Into<String>) -> V {
        V { k, a: a.into(), b: b.into(), ty: None }
    }
    pub fn agg(a: impl Into<String>, ty: &str) -> V {
        V { k: Kind::Agg, a: a.into(), b: "None".to_string(), ty: Some(ty.to_string()) }
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
}

impl Mod {
    pub fn new() -> Mod {
        Mod { strs: HashMap::new(), order: Vec::new(), uses_repr: false }
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
pub fn ir_params(f: &Function) -> Vec<(String, String)> {
    let mut out = Vec::new();
    for p in &f.params {
        let n = mangle(&p.name);
        if is_arr_name(&p.ty) {
            out.push(("ptr".to_string(), format!("%p.{}.a", n)));
            out.push(("i64".to_string(), format!("%p.{}.n", n)));
        } else if p.ty == "bool" {
            out.push(("i1".to_string(), format!("%p.{}", n)));
        } else if p.ty == "i64" {
            out.push(("i64".to_string(), format!("%p.{}", n)));
        } else if is_agg(&p.ty) {
            out.push((lty(&p.ty), format!("%p.{}", n)));
        } else {
            out.push((OPT.to_string(), format!("%p.{}", n)));
        }
    }
    out
}

/// Parameter list of an internal function definition: array pointers are read-only borrows
pub fn sig_text(params: &[(String, String)]) -> String {
    params
        .iter()
        .map(|(t, n)| {
            format!("{} {}", if t == "ptr" { "ptr noalias nocapture readonly" } else { t.as_str() }, n)
        })
        .collect::<Vec<_>>()
        .join(", ")
}

/// The noreturn call made from a guard's failure block (counterpart of a Python lambda). String constants are registered at call time.
pub enum Fail {
    Panic1(&'static str, String),
    Oob(String, String),
    Requires(String, String),
    /// u8 element range violation: (value SSA, range text). The string is registered when the fail block is emitted.
    Elem(String, &'static str),
}

fn expr_ty(e: &Expr) -> &Option<String> {
    match e {
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

    pub fn render(&self, header: &str) -> String {
        let mut out: Vec<String> = vec![format!("{} {{", header), "entry:".to_string()];
        for a in &self.allocas {
            out.push(format!("  {}", a));
        }
        out.push("  br label %start".to_string());
        out.extend(self.lines.iter().cloned());
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
                Ok(V::agg(r, &ty))
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
        if is_bytes_ty(&v.ty) {
            return self.ins(format!("call void @pruv_free_v2(ptr {}, i64 {}, i64 1, i64 1)", v.a, v.b));
        }
        self.ins(format!("call void @pruv_free(ptr {}, i64 {})", v.a, v.b))
    }

    fn free_scope(&mut self, arrays: &[Slot]) -> R<()> {
        for sl in arrays.iter().rev() {
            let v = self.load(sl)?;
            self.free_val(&v)?;
        }
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
        Ok(v.a.clone())
    }

    pub fn unpack(&mut self, x: &str, ty: &str, c: bool) -> R<V> {
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

    fn evf(&mut self, e: &Expr, c: bool) -> R<V> {
        if c {
            self.cev(e)
        } else {
            self.ev(e, false)
        }
    }

    pub fn mk_struct(&mut self, e: &StructLit, c: bool) -> R<V> {
        let tt = self.tt;
        let ty = e.name.as_str();
        // Look up by name like a Python dict (audit: a linear Vec search is quadratic in the field count). For the same name, the later value wins.
        let mut vals: std::collections::HashMap<&str, V> = std::collections::HashMap::new();
        for fi in &e.fields {
            // Evaluate in source order
            let v = self.evf(&fi.value, c)?;
            vals.insert(fi.name.as_str(), v);
        }
        let mut acc = "zeroinitializer".to_string();
        for (i, fd) in t_fields(tt, ty, None)?.iter().enumerate() {
            let v = vals
                .get(fd.name.as_str())
                .cloned()
                .ok_or_else(|| format!("'{}'", fd.name))?;
            acc = self.put(&acc, ty, i, &v, &fd.ty, c)?;
        }
        Ok(V::agg(acc, ty))
    }

    pub fn mk_enum(&mut self, e: &EnumCtor, c: bool) -> R<V> {
        let tt = self.tt;
        let ty = e.enum_name.as_str();
        let mut vals: Vec<V> = Vec::new();
        for x in &e.args {
            vals.push(self.evf(x, c)?);
        }
        let tag = t_variant_index(tt, ty, &e.variant)?;
        let mut acc = self.op(format!("insertvalue {} zeroinitializer, i64 {}, 0", st(ty, c), tag))?;
        for (i, fd) in t_fields(tt, ty, Some(&e.variant))?.iter().enumerate() {
            let v = vals.get(i).ok_or_else(|| IDX_ERR.to_string())?;
            let pi = payload_index(tt, ty, &e.variant, i)?;
            acc = self.put(&acc, ty, pi, v, &fd.ty, c)?;
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
        let x = self.evf(a, c)?;
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
            } else if is_agg(&p.ty) {
                names.insert(p.name.clone(), Bind::Ssa(V::agg(format!("%p.{}", n), &p.ty)));
            } else {
                let t = self.op(format!("extractvalue {} %p.{}, 0", OPT, n))?;
                let v = self.op(format!("extractvalue {} %p.{}, 1", OPT, n))?;
                names.insert(p.name.clone(), Bind::Ssa(V::with_b(Kind::Opt, t, v)));
            }
        }
        self.scopes.push(Scope { names, arrays: Vec::new() });
        Ok(())
    }

    pub fn emit_ret(&mut self, v: &V) -> R<()> {
        let f = self.f;
        let rt = f.ret.as_str();
        if rt == "unit" {
            self.term("ret void".to_string())
        } else if rt == "i64" || rt == "bool" {
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
        let falls = self.run_block(&f.body, Vec::new())?;
        if falls {
            if f.ret == "unit" {
                self.term("ret void".to_string())?;
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
                let sc = self.scopes.last_mut().ok_or_else(|| IDX_ERR.to_string())?;
                sc.names.insert(x.name.clone(), Bind::Slot(sl.clone()));
                if sl.k == Kind::Arr {
                    sc.arrays.push(sl);
                }
                self.end_temps()
            }
            Stmt::Assign(x) => {
                self.begin_temps();
                let sl = self.lookup(&x.name)?.val().clone();
                let v = self.ev(&x.value, true)?;
                if sl.k == Kind::Arr {
                    let old = self.load(&sl)?;
                    self.free_val(&old)?;
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
                let v = self.ev(&x.value, false)?; // right side first, then root load -> insertvalue chain -> store
                let root = self.load(&sl)?;
                let ty = need_ty(&sl.ty)?.to_string();
                let nv = self.set_path(&root, &ty, &x.fields, &v)?;
                self.store(&sl, &nv)?;
                self.end_temps()
            }
            Stmt::IndexAssign(x) => {
                self.begin_temps();
                let sl = self.lookup(&x.name)?.val().clone();
                let i = self.ev(&x.index, false)?; // index first, then the value (all modes)
                let v = self.ev(&x.value, false)?;
                let a = self.load(&sl)?;
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
            Stmt::ExprStmt(x) => {
                self.begin_temps();
                self.ev(&x.expr, false)?;
                self.end_temps()
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
                let v = self.get(sv, &ty, pi, &fd.ty, false)?;
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
            Expr::Var(x) => match self.lookup(&x.name)? {
                Bind::Ssa(v) => Ok(v),
                Bind::Slot(s) => self.load(&s),
            },
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
            Expr::StructLit(x) => self.mk_struct(x, false),
            Expr::EnumCtor(x) => self.mk_enum(x, false),
            Expr::FieldAccess(x) => {
                let tt = self.tt;
                let b = self.ev(&x.base, false)?;
                let ty = match &b.ty {
                    Some(t) => t.clone(),
                    None => need_ty(expr_ty(&x.base))?.to_string(),
                };
                let i = t_field_index(tt, &ty, &x.field, None)?;
                let fds = t_fields(tt, &ty, None)?;
                let fty = fds.get(i).ok_or_else(|| IDX_ERR.to_string())?.ty.as_str();
                self.get(&b, &ty, i, fty, false)
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
        let n = e.name.as_str();
        let a = &e.args;
        if n == "len" {
            let x = self.ev(arg(a, 0)?, false)?;
            return Ok(V::new(Kind::I64, x.b));
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
        let mut args: Vec<String> = Vec::new();
        for x in a {
            let v = self.ev(x, false)?;
            match v.k {
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
        let callee = format!("@{}__pruv_{}", mangle(&f.name), if self.verified { "body" } else { "entry" });
        let argl = args.join(", ");
        if f.ret == "unit" {
            self.ins(format!("call void {}({})", callee, argl))?;
            return Ok(V::unit());
        }
        let r = self.op(format!("call {} {}({})", lty(&f.ret), callee, argl))?;
        if f.ret == "i64" || f.ret == "bool" {
            return Ok(V::new(vkind(&f.ret), r));
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

    // ---------- contract (requires) evaluation, i128 ----------
    pub fn bind_contract_params(&mut self) -> R<()> {
        self.place("start");
        let f = self.f;
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

    pub fn cev(&mut self, e: &Expr) -> R<V> {
        let und = |msg: String| Fail::Panic1("pruv_panic_undefined", msg);
        let tt = self.tt;
        match e {
            Expr::IntLit(x) => Ok(V::new(Kind::I128, x.value.clone())),
            Expr::BoolLit(x) => Ok(V::new(Kind::I1, if x.value { "true" } else { "false" })),
            Expr::StrLit(x) => {
                // G2 B2: point at the global string directly, without copying
                let g = self.str_global(&x.value);
                Ok(V { k: Kind::Arr, a: g, b: x.value.len().to_string(), ty: Some(STR.to_string()) })
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
                    let r = self.shortcircuit(&l.a, op != "&&", &|g| Ok(g.cev(right)?.a))?;
                    return Ok(V::new(Kind::I1, r));
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
            Expr::StructLit(x) => self.mk_struct(x, true),
            Expr::EnumCtor(x) => self.mk_enum(x, true),
            Expr::FieldAccess(x) => {
                let b = self.cev(&x.base)?;
                let bty = need_ty(&b.ty)?.to_string();
                let i = t_field_index(tt, &bty, &x.field, None)?;
                let fds = t_fields(tt, &bty, None)?;
                let fty = fds.get(i).ok_or_else(|| IDX_ERR.to_string())?.ty.as_str();
                self.get(&b, &bty, i, fty, true)
            }
            Expr::IsVariant(x) => {
                let b = self.cev(&x.value)?;
                let bty = need_ty(&b.ty)?.to_string();
                let k = t_variant_index(tt, &bty, &x.variant)?;
                let tag = self.tag_of(&b, true)?;
                let r = self.op(format!("icmp eq i64 {}, {}", tag, k))?;
                Ok(V::new(Kind::I1, r))
            }
            Expr::VariantField(x) => {
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
                if n == "len" {
                    let v = self.cev(arg(a, 0)?)?;
                    let r = self.op(format!("zext i64 {} to i128", v.b))?;
                    return Ok(V::new(Kind::I128, r));
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
        let budget = match &self.budget {
            Some(b) => b.clone(),
            None => return Err("llvmgen: internal error: no iteration budget slot".to_string()),
        };
        let old = self.op(format!("load i64, ptr {}", budget))?;
        let nv = self.op(format!("sub i64 {}, 1", old))?;
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
        let b = self.cev(&x.body)?;
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
) -> R<String> {
    let mut g = FnGen::new(m, tt, funcs, f, true);
    let params = ir_params(f);
    let rt = lty(&f.ret);
    if trust {
        g.place("start");
    } else {
        g.bind_contract_params()?;
        let bname = "%req.budget".to_string();
        g.budget = Some(bname.clone());
        g.allocas.push(format!("{} = alloca i64", bname));
        g.ins(format!("store i64 {}, ptr {}", budget, bname))?;
        for r in &f.requires {
            let c = g.cev(r)?;
            let msg_fn = g.m.string(&f.name);
            let msg_ex = g.m.string(&crate::emit_common::show(r));
            g.guard(&c.a, Fail::Requires(msg_fn, msg_ex), false)?;
        }
    }
    let args = params.iter().map(|(t, n)| format!("{} {}", t, n)).collect::<Vec<_>>().join(", ");
    let callee = format!("@{}__pruv_body", mangle(&f.name));
    if f.ret == "unit" {
        g.ins(format!("call void {}({})", callee, args))?;
        g.term("ret void".to_string())?;
    } else {
        let r = g.op(format!("call {} {}({})", rt, callee, args))?;
        g.term(format!("ret {} {}", rt, r))?;
    }
    Ok(g.render(&format!("define internal {} @{}__pruv_entry({})", rt, mangle(&f.name), sig_text(&params))))
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
    use crate::codegen::GenError;
    if crate::typeinfo::first_g3_use(prog).is_some() {
        let plan = crate::mono::specialize(prog).map_err(|e| match e {
            crate::mono::MonoError::Limit(p) => GenError::Diag(p),
            crate::mono::MonoError::Internal(m) => GenError::Msg(m),
        })?;
        return gen_llvm_concrete(&plan.program, verified, trust_callers, budget, target).map_err(GenError::Msg);
    }
    gen_llvm_concrete(prog, verified, trust_callers, budget, target).map_err(GenError::Msg)
}

/// The generator proper, for a CONCRETE program (a plan.program of mono.rs, or a program without G3): no type parameter
/// reaches it.
pub fn gen_llvm_concrete(prog: &Program, verified: bool, trust_callers: bool, budget: u64, target: AbiTarget) -> R<(String, String)> {
    if let Some(e) = crate::typeinfo::g2_unimplemented_error(prog, "codegen", None, &["array_u8", "array_bool", "str"], None) {
        // G2 B2: str also opens the generation layer
        return Err(format!("unsupported_type: {}", e.message));
    }
    let tt = TypeTable::new(&prog.types);
    let mut m = Mod::new();
    let mut funcs: HashMap<String, &Function> = HashMap::new();
    for f in &prog.functions {
        funcs.insert(f.name.clone(), f);
    }
    let mut chunks: Vec<String> = Vec::new();
    if !trust_callers && prog.functions.iter().any(|f| !f.requires.is_empty()) {
        chunks.push(cdivrem(&mut m, true));
        chunks.push(cdivrem(&mut m, false));
    }
    for f in &prog.functions {
        let mut g = FnGen::new(&mut m, &tt, &funcs, f, verified);
        g.body()?;
        let params = ir_params(f);
        chunks.push(g.render(&format!(
            "define internal {} @{}__pruv_body({})",
            lty(&f.ret),
            mangle(&f.name),
            sig_text(&params)
        )));
        chunks.push(entry_of(&mut m, &tt, &funcs, f, trust_callers || f.requires.is_empty(), budget)?);
        if !crate::emit_common::is_spec_fn(&f.name) {
            // G3: a generic specialization has no ABI symbol
            chunks.push(abi_of(f, &tt, target, &mut m)?);
        }
    }
    let has_str = crate::typeinfo::uses_str(prog); // G2 B2
    let ir = format!(
        "{}{}\n{}{}{}{}{}{}{}\n{}",
        if target == AbiTarget::WinX64 { WIN_X64_HEADER } else { "" },
        m.render_strings(),
        type_defs(&tt),
        if prog.types.is_empty() { "" } else { "\n" },
        DECLS,
        // G2 A5: DECLS_U8 if u8 or bool is used, and DECLS_BOOL after it if bool is used
        // G2 B2: DECLS_U8 if u8, bool or str is used, and DECLS_STR at the very end if str is used
        if uses_array_type(prog, "array_u8") || uses_array_type(prog, "array_bool") || has_str { DECLS_U8 } else { "" },
        if uses_array_type(prog, "array_bool") { DECLS_BOOL } else { "" },
        if has_str { DECLS_STR } else { "" },
        if m.uses_repr { DECLS_REPR } else { "" }, // G3
        chunks.join("\n")
    );
    let bindings = crate::bindings::gen_bindings(prog)?;
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
            }],
            refined: false,
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
