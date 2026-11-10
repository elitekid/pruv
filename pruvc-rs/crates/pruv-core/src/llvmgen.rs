//! Pruv -> LLVM IR 텍스트 생성기 (llvmgen.py 1~1327행 + gen_llvm 이식).
//! 목표: 같은 프로그램·모드에서 Python gen_llvm 의 첫 반환값과 바이트 동일.
//! 규칙: 가변 상태(임시 번호·라벨 번호·스코프·임시 해제 목록·계약 환경)는 Python 과 같은 순서로 바꾼다.
//! Python 의 None 은 문자열 "None" 으로 흉내 낸다(V 의 a/b 기본값).

use crate::abi::abi_of;
use crate::ast::*;
use crate::typeinfo::{is_user_type, TypeTable};
use std::collections::HashMap;

pub type R<T> = Result<T, String>;

pub const SIGNED_MIN128: i128 = i128::MIN;
pub const OPT: &str = "{ i1, i64 }";
/// 계약 집합체 안에 저장되는 Option/Result
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

const NONE_ATTR: &str = "'NoneType' object has no attribute 'name'";
const IDX_ERR: &str = "list index out of range";

// ---------- 타입 보조 ----------

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

/// Pruv 타입의 내부 SSA 타입
pub fn lty(t: &str) -> String {
    match t {
        "i64" => "i64".to_string(),
        "bool" => "i1".to_string(),
        "unit" => "void".to_string(),
        "array" => ARR.to_string(),
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
    match t {
        "i64" => Kind::I64,
        "bool" => Kind::I1,
        "unit" => Kind::Unit,
        "array" => Kind::Arr,
        "option" | "result" => Kind::Opt,
        _ => Kind::Agg,
    }
}

/// 집합체 안 값의 저장 타입(c: 계약/i128 형태)
pub fn st(t: &str, c: bool) -> String {
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

/// 평탄화된 enum 타입 안에서 `variant` 의 i 번째 필드 저장 인덱스
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

/// W(T): 외부(pruv_abi_*) 형태의 i64 워드 수
pub fn words(tt: &TypeTable, ty: &str) -> R<usize> {
    match ty {
        "i64" | "bool" => Ok(1),
        "option" | "result" => Ok(2),
        _ => match t_decl(tt, ty)? {
            TypeDecl::Struct(s) => {
                let mut sum = 0usize;
                for f in &s.fields {
                    sum += words(tt, &f.ty)?;
                }
                Ok(sum.max(1))
            }
            TypeDecl::Enum(e) => {
                let mut sum = 1usize;
                for v in &e.variants {
                    for f in &v.fields {
                        sum += words(tt, &f.ty)?;
                    }
                }
                Ok(sum)
            }
        },
    }
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

// ---------- 값·슬롯 ----------

/// SSA 값. k 별 의미: i64|i1|i128, arr(a=ptr,b=len), opt(a=tag,b=payload), unit, agg(a=집합체 SSA, ty=타입).
/// 슬롯(Slot)도 같은 모양이다(arr: a=ptr 슬롯, b=len 슬롯).
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

/// 이름 바인딩: ("ssa", V) 또는 ("slot", Slot)
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
}

impl Mod {
    pub fn new() -> Mod {
        Mod { strs: HashMap::new(), order: Vec::new() }
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

/// 내부 매개변수 목록 [(타입, 이름)]
pub fn ir_params(f: &Function) -> Vec<(String, String)> {
    let mut out = Vec::new();
    for p in &f.params {
        let n = mangle(&p.name);
        if p.ty == "array" {
            out.push(("ptr".to_string(), format!("%p.{}.a", n)));
            out.push(("i64".to_string(), format!("%p.{}.n", n)));
        } else if p.ty == "bool" {
            out.push(("i1".to_string(), format!("%p.{}", n)));
        } else if p.ty == "i64" {
            out.push(("i64".to_string(), format!("%p.{}", n)));
        } else if is_user_type(&p.ty) {
            out.push((lty(&p.ty), format!("%p.{}", n)));
        } else {
            out.push((OPT.to_string(), format!("%p.{}", n)));
        }
    }
    out
}

/// 내부 함수 정의의 매개변수 목록: 배열 포인터는 읽기 전용 빌림
pub fn sig_text(params: &[(String, String)]) -> String {
    params
        .iter()
        .map(|(t, n)| {
            format!("{} {}", if t == "ptr" { "ptr noalias nocapture readonly" } else { t.as_str() }, n)
        })
        .collect::<Vec<_>>()
        .join(", ")
}

/// guard 의 실패 블록에서 부르는 noreturn 호출(Python 람다 대응). 문자열 상수는 호출 시점에 등록한다.
pub enum Fail {
    Panic1(&'static str, String),
    Oob(String, String),
    Requires(String, String),
}

fn expr_ty(e: &Expr) -> &Option<String> {
    match e {
        Expr::IntLit(x) => &x.ty,
        Expr::BoolLit(x) => &x.ty,
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

    // ---------- 방출 ----------
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
        }
    }

    /// cond != fail_when 일 때만 계속; 아니면 실패 블록에서 fail 호출
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

    // ---------- 슬롯 / 스코프 ----------
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
                V::with_b(Kind::Arr, a, b)
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
                Ok(V::with_b(Kind::Arr, p, n))
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

    // ---------- 사용자 집합체(G1) ----------
    /// 값 v 의 저장 타입 st(ty, c) SSA
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
        let mut vals: Vec<(String, V)> = Vec::new();
        for fi in &e.fields {
            // 소스 순서 평가
            let v = self.evf(&fi.value, c)?;
            if let Some(slot) = vals.iter_mut().find(|(n, _)| *n == fi.name) {
                slot.1 = v;
            } else {
                vals.push((fi.name.clone(), v));
            }
        }
        let mut acc = "zeroinitializer".to_string();
        for (i, fd) in t_fields(tt, ty, None)?.iter().enumerate() {
            let v = vals
                .iter()
                .find(|(n, _)| *n == fd.name)
                .map(|(_, v)| v.clone())
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

    /// 집합체 `base`(코드 형태)에서 중첩 struct 필드 `path` 를 v 로 바꾼 값
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

    /// 코드 값 -> 계약 값(i64 잎은 부호 확장; enum 은 활성 변형만 변환)
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

    /// 두 계약 값의 구조적 동등 -> i1 (SSA 이름 또는 리터럴)
    pub fn ceq(&mut self, l: &V, r: &V, ty: &str) -> R<String> {
        let tt = self.tt;
        match ty {
            "i64" => return self.op(format!("icmp eq i128 {}, {}", l.a, r.a)),
            "bool" => return self.op(format!("icmp eq i1 {}, {}", l.a, r.a)),
            "option" | "result" => {
                let te = self.op(format!("icmp eq i1 {}, {}", l.a, r.a))?;
                let mut pe = self.op(format!("icmp eq i128 {}, {}", l.b, r.b))?;
                if ty == "option" {
                    // None 의 payload 는 비교하지 않는다
                    let nt = self.op(format!("xor i1 {}, true", l.a))?;
                    pe = self.op(format!("or i1 {}, {}", nt, pe))?;
                }
                return self.op(format!("and i1 {}, {}", te, pe));
            }
            _ => {}
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
                self.place(&dflt); // 같은 태그, 필드 없는 변형
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

    // ---------- 함수 틀 ----------
    pub fn bind_params(&mut self) -> R<()> {
        self.place("start");
        let f = self.f;
        let mut names: HashMap<String, Bind> = HashMap::new();
        for p in &f.params {
            let n = mangle(&p.name);
            if p.ty == "array" {
                names.insert(p.name.clone(), Bind::Ssa(V::with_b(Kind::Arr, format!("%p.{}.a", n), format!("%p.{}.n", n))));
            } else if p.ty == "bool" {
                names.insert(p.name.clone(), Bind::Ssa(V::new(Kind::I1, format!("%p.{}", n))));
            } else if p.ty == "i64" {
                names.insert(p.name.clone(), Bind::Ssa(V::new(Kind::I64, format!("%p.{}", n))));
            } else if is_user_type(&p.ty) {
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

    // ---------- 문 ----------
    /// 블록을 자기 스코프로 낮춘다; 제어가 흘러 나올 수 있으면 true
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
                let v = self.ev(&x.value, false)?; // 오른쪽 먼저, 그다음 루트 load -> insertvalue 사슬 -> store
                let root = self.load(&sl)?;
                let ty = need_ty(&sl.ty)?.to_string();
                let nv = self.set_path(&root, &ty, &x.fields, &v)?;
                self.store(&sl, &nv)?;
                self.end_temps()
            }
            Stmt::IndexAssign(x) => {
                self.begin_temps();
                let sl = self.lookup(&x.name)?.val().clone();
                let i = self.ev(&x.index, false)?; // 인덱스 먼저, 그다음 값(모든 모드)
                let v = self.ev(&x.value, false)?;
                let a = self.load(&sl)?;
                let g = self.index_ptr(&a, &i)?;
                self.ins(format!("store i64 {}, ptr {}", v.a, g))?;
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
                            // 지역 배열을 내보낼 때: 슬롯을 비워 아래 정리가 해제하지 않게 한다
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

    /// 사용자 enum 의 match: 태그 switch; payload 추출은 arm 블록 안에서만; default 는 unreachable
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
                bind.retain(|(n, _)| n != name);
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

    // ---------- 코드 식 ----------
    pub fn index_ptr(&mut self, a: &V, i: &V) -> R<String> {
        if !self.verified {
            let ok = self.op(format!("icmp ult i64 {}, {}", i.a, a.b))?;
            self.guard(&ok, Fail::Oob(i.a.clone(), a.b.clone()), false)?;
        }
        self.op(format!("getelementptr inbounds i64, ptr {}, i64 {}", a.a, i.a))
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
                let r = self.op(format!("load i64, ptr {}", g))?;
                Ok(V::new(Kind::I64, r))
            }
            Expr::Ctor(x) => {
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
            let cnt = self.ev(arg(a, 0)?, false)?; // 모든 모드에서 소스 순서: n 다음 v
            let v = self.ev(arg(a, 1)?, false)?;
            if !self.verified {
                let ok = self.op(format!("icmp ult i64 {}, 1099511627777", cnt.a))?;
                self.guard(&ok, Fail::Panic1("pruv_panic_arith", "alloc length outside 0..2^40".to_string()), false)?;
            }
            let p = self.op(format!("call ptr @pruv_alloc(i64 {}, i64 {})", cnt.a, v.a))?;
            return self.temp_arr(V::with_b(Kind::Arr, p, cnt.a.clone()), owned);
        }
        if n == "copy" {
            let src = self.ev(arg(a, 0)?, false)?;
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
        if is_user_type(&f.ret) {
            return Ok(V::agg(r, &f.ret));
        }
        let x0 = self.op(format!("extractvalue {} {}, 0", lty(&f.ret), r))?;
        let x1 = self.op(format!("extractvalue {} {}, 1", lty(&f.ret), r))?;
        if f.ret == "array" {
            return self.temp_arr(V::with_b(Kind::Arr, x0, x1), owned);
        }
        Ok(V::with_b(Kind::Opt, x0, x1))
    }

    // ---------- 계약(requires) 평가, i128 ----------
    pub fn bind_contract_params(&mut self) -> R<()> {
        self.place("start");
        let f = self.f;
        for p in &f.params {
            let n = mangle(&p.name);
            if p.ty == "array" {
                self.cenv.insert(p.name.clone(), V::with_b(Kind::Arr, format!("%p.{}.a", n), format!("%p.{}.n", n)));
            } else if p.ty == "bool" {
                self.cenv.insert(p.name.clone(), V::new(Kind::I1, format!("%p.{}", n)));
            } else if p.ty == "i64" {
                let r = self.op(format!("sext i64 %p.{} to i128", n))?;
                self.cenv.insert(p.name.clone(), V::new(Kind::I128, r));
            } else if is_user_type(&p.ty) {
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
                let g = self.op(format!("getelementptr inbounds i64, ptr {}, i64 {}", a.a, ii))?;
                let v = self.op(format!("load i64, ptr {}", g))?;
                let r = self.op(format!("sext i64 {} to i128", v))?;
                Ok(V::new(Kind::I128, r))
            }
            Expr::Ctor(x) => {
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
                if n == "is_some" || n == "is_ok" {
                    let v = self.cev(arg(a, 0)?)?;
                    return Ok(V::new(Kind::I1, v.a));
                }
                if n == "some_val" || n == "ok_val" || n == "err_val" {
                    let o = self.cev(arg(a, 0)?)?;
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

    /// requires 반복 예산 1 단위 소비(docs/M0_CONTRACTS.md B)
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

    /// sorted 사전조건 forall 의 O(n) 형태: forall k in 1..len(a): a[k-1] <= a[k]
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
        let g0 = self.op(format!("getelementptr inbounds i64, ptr {}, i64 {}", arr.a, pk))?;
        let g1 = self.op(format!("getelementptr inbounds i64, ptr {}, i64 {}", arr.a, kv))?;
        let x0 = self.op(format!("load i64, ptr {}", g0))?;
        let x1 = self.op(format!("load i64, ptr {}", g1))?;
        let le = self.op(format!("icmp sle i64 {}, {}", x0, x1))?;
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
                let q = self.nq;
                self.nq += 1;
                return self.csorted(&sorted_arr, q);
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

// ---------- requires 보조 함수 ----------
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

/// 프로그램 -> (IR 텍스트, Rust 바인딩 텍스트). Err 는 Python 이 예외를 내는 자리의 메시지.
pub fn gen_llvm(prog: &Program, verified: bool, trust_callers: bool, budget: u64) -> R<(String, String)> {
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
        chunks.push(abi_of(f, &tt)?);
    }
    let ir = format!(
        "{}\n{}{}{}\n{}",
        m.render_strings(),
        type_defs(&tt),
        if prog.types.is_empty() { "" } else { "\n" },
        DECLS,
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
        };
        let mut m = Mod::new();
        let mut g = FnGen::new(&mut m, &tt, &funcs, &f, false);
        g.place("start");
        let c = g.op("icmp eq i64 1, 1".to_string()).unwrap();
        g.guard(&c, Fail::Panic1("pruv_panic_arith", "x".to_string()), false).unwrap();
        let text = g.render("define internal void @f__pruv_body()");
        assert!(text.contains("  %t1 = icmp eq i64 1, 1\n  br i1 %t1, label %ok.1, label %fail.2\nfail.2:\n"));
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
