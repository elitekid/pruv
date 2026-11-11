//! Pruv -> Rust 소스 생성기 (codegen.py 의 상수·class Gen·gen_rust 이식).
//! 목표: 같은 프로그램·모드(verified, trust_callers, budget)에서 Python gen_rust 와 바이트 동일.
//! 128~272행 함수(rty·cty·conv·emit_public_types·show·match_sorted_requires·rstr)는 emit_common 것을 쓴다.
//! 규칙: 가변 상태(임시 번호 tmp·계약 변수 bound·cp 사전)는 Python 과 같은 순서로 바꾼다.
//! Python 이 Exception 을 내는 자리는 Err(str(e)) 로 돌려준다(%r 로 찍는 AST 는 {:?} — 도달 불가 경로).

use crate::ast::*;
use crate::emit_common::{emit_public_types, match_sorted_requires, rstr, rty, show, try_conv, try_cty};
use crate::pyrepr::repr_str;
use crate::typeinfo::{is_user_type, TypeTable};
use std::collections::{HashMap, HashSet};

pub type R<T> = Result<T, String>;

pub const ALLOW: &str = "#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]";

pub const SAFE_PRELUDE: &str = r##"#[allow(dead_code)]
#[cold]
#[inline(never)]
fn pruv_oob(i: i64, len: usize) -> ! { panic!("pruv: index out of bounds: {} (len {})", i, len) }
#[allow(dead_code)]
#[cold]
#[inline(never)]
fn pruv_ovf(what: &str) -> ! { panic!("pruv: arithmetic error: {}", what) }
#[allow(dead_code)]
#[inline]
fn pruv_idx(i: i64, len: usize) -> usize { if i >= 0 && (i as u64) < (len as u64) { i as usize } else { pruv_oob(i, len) } }
#[allow(dead_code)]
#[inline]
fn pruv_get(a: &[i64], i: i64) -> i64 { a[pruv_idx(i, a.len())] }
#[allow(dead_code)]
#[inline]
fn pruv_set(a: &mut [i64], i: i64, v: i64) { let k = pruv_idx(i, a.len()); a[k] = v; }
#[allow(dead_code)]
#[inline]
fn pruv_add(a: i64, b: i64) -> i64 { match a.checked_add(b) { Some(v) => v, None => pruv_ovf("overflow in +") } }
#[allow(dead_code)]
#[inline]
fn pruv_sub(a: i64, b: i64) -> i64 { match a.checked_sub(b) { Some(v) => v, None => pruv_ovf("overflow in -") } }
#[allow(dead_code)]
#[inline]
fn pruv_mul(a: i64, b: i64) -> i64 { match a.checked_mul(b) { Some(v) => v, None => pruv_ovf("overflow in *") } }
#[allow(dead_code)]
#[inline]
fn pruv_div(a: i64, b: i64) -> i64 { if b > 0 && a >= 0 { a / b } else { pruv_ovf("division outside domain: need divisor > 0 and dividend >= 0") } }
#[allow(dead_code)]
#[inline]
fn pruv_rem(a: i64, b: i64) -> i64 { if b > 0 && a >= 0 { a % b } else { pruv_ovf("division outside domain: need divisor > 0 and dividend >= 0") } }
#[allow(dead_code)]
#[inline]
fn pruv_neg(a: i64) -> i64 { match a.checked_neg() { Some(v) => v, None => pruv_ovf("overflow in unary -") } }
#[allow(dead_code)]
#[inline]
fn pruv_alloc(n: i64, v: i64) -> ::std::vec::Vec<i64> { if n < 0 || n > (1i64 << 40) { pruv_ovf("alloc length outside 0..2^40") } vec![v; n as usize] }
"##;

pub const CONTRACT_PRELUDE: &str = r##"#[allow(dead_code)]
#[cold]
#[inline(never)]
fn pruv_ud(what: &str) -> ! { panic!("pruv: requires undefined: {}", what) }
#[allow(dead_code)]
#[inline]
fn pruv_cidx(a: &[i64], i: i128) -> i128 { if i >= 0 && i < (a.len() as i128) { a[i as usize] as i128 } else { pruv_ud("array index out of range") } }
#[allow(dead_code)]
#[inline]
fn pruv_cadd(a: i128, b: i128) -> i128 { a.checked_add(b).unwrap_or_else(|| pruv_ud("i128 overflow in +")) }
#[allow(dead_code)]
#[inline]
fn pruv_csub(a: i128, b: i128) -> i128 { a.checked_sub(b).unwrap_or_else(|| pruv_ud("i128 overflow in -")) }
#[allow(dead_code)]
#[inline]
fn pruv_cmul(a: i128, b: i128) -> i128 { a.checked_mul(b).unwrap_or_else(|| pruv_ud("i128 overflow in *")) }
#[allow(dead_code)]
#[inline]
fn pruv_cneg(a: i128) -> i128 { a.checked_neg().unwrap_or_else(|| pruv_ud("i128 overflow in unary -")) }
#[allow(dead_code)]
#[inline]
fn pruv_cdiv(a: i128, b: i128) -> i128 { if b == 0 { pruv_ud("division by zero in /") } a.checked_div_euclid(b).unwrap_or_else(|| pruv_ud("i128 overflow in /")) }
#[allow(dead_code)]
#[inline]
fn pruv_crem(a: i128, b: i128) -> i128 { if b == 0 { pruv_ud("division by zero in %") } a.checked_rem_euclid(b).unwrap_or_else(|| pruv_ud("i128 overflow in %")) }
"##;

/// SAFE_ARITH 표
fn safe_arith(op: &str) -> Option<&'static str> {
    match op {
        "+" => Some("pruv_add"),
        "-" => Some("pruv_sub"),
        "*" => Some("pruv_mul"),
        "/" => Some("pruv_div"),
        "%" => Some("pruv_rem"),
        _ => None,
    }
}

/// CONTRACT_ARITH 표
fn contract_arith(op: &str) -> Option<&'static str> {
    match op {
        "+" => Some("pruv_cadd"),
        "-" => Some("pruv_csub"),
        "*" => Some("pruv_cmul"),
        "/" => Some("pruv_cdiv"),
        "%" => Some("pruv_crem"),
        _ => None,
    }
}

// ---------- 보조 ----------

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

/// Python `a[i]` 의 IndexError
fn arg(a: &[Expr], i: usize) -> R<&Expr> {
    a.get(i).ok_or_else(|| "list index out of range".to_string())
}

/// Python `format(n, "_")`: 세 자리마다 밑줄.
fn fmt_underscore(n: u64) -> String {
    let digits = n.to_string();
    let len = digits.len();
    let mut out = String::new();
    for (i, ch) in digits.chars().enumerate() {
        if i > 0 && (len - i) % 3 == 0 {
            out.push('_');
        }
        out.push(ch);
    }
    out
}

/// TypeTable.decl 의 KeyError
fn k_decl<'t>(tt: &'t TypeTable, ty: &str) -> R<&'t TypeDecl> {
    tt.decl(ty).ok_or_else(|| repr_str(ty))
}

/// TypeTable.variant (struct 이면 AttributeError, 없으면 KeyError)
fn k_variant<'t>(tt: &'t TypeTable, ty: &str, variant: &str) -> R<&'t VariantDecl> {
    match k_decl(tt, ty)? {
        TypeDecl::Enum(e) => e
            .variants
            .iter()
            .find(|v| v.name == variant)
            .ok_or_else(|| repr_str(&format!("{}::{}", ty, variant))),
        TypeDecl::Struct(_) => Err("'StructDecl' object has no attribute 'variants'".to_string()),
    }
}

/// TypeTable.fields
fn k_fields<'t>(tt: &'t TypeTable, ty: &str, variant: Option<&str>) -> R<&'t [FieldDecl]> {
    match k_decl(tt, ty)? {
        TypeDecl::Struct(s) => Ok(&s.fields),
        TypeDecl::Enum(_) => match variant {
            None => Err(repr_str(&format!("enum {} needs a variant", ty))),
            Some(v) => Ok(&k_variant(tt, ty, v)?.fields),
        },
    }
}

/// TypeTable.field_index
fn k_field_index(tt: &TypeTable, ty: &str, name: &str, variant: Option<&str>) -> R<usize> {
    k_fields(tt, ty, variant)?
        .iter()
        .position(|f| f.name == name)
        .ok_or_else(|| repr_str(name))
}

/// `{f.name: f.value for f in e.fields}` 를 리터럴마다 한 번 만든다(중복이면 뒤 것이 이김 = dict).
/// 감사: 필드마다 뒤에서 훑으면 필드 수의 제곱이었다.
fn init_map(fields: &[FieldInit]) -> std::collections::HashMap<&str, &Expr> {
    let mut m = std::collections::HashMap::new();
    for f in fields {
        m.insert(f.name.as_str(), &f.value);
    }
    m
}

/// init_map 조회(없으면 Python KeyError 문장)
fn init_value<'a>(m: &std::collections::HashMap<&str, &'a Expr>, name: &str) -> R<&'a Expr> {
    m.get(name).copied().ok_or_else(|| repr_str(name))
}

fn join_map<T>(xs: &[T], sep: &str, f: impl Fn(&T) -> String) -> String {
    xs.iter().map(f).collect::<Vec<_>>().join(sep)
}

// ---------- Gen ----------

struct Gen<'a> {
    prog: &'a Program,
    budget: u64,
    verified: bool,
    trust: bool,
    out: Vec<String>,
    has_req: HashSet<String>,
    /// requires 진입 검사 중: 이미 바꾼 사용자 타입 매개변수 -> 타입
    cp: Option<HashMap<String, String>>,
    /// 범위 안 한정자 변수(계약 평가)
    bound: Vec<String>,
    tmp: u64,
    table: TypeTable,
    params: HashSet<String>,
}

impl<'a> Gen<'a> {
    fn new(prog: &'a Program, verified: bool, trust_callers: bool, budget: u64) -> Gen<'a> {
        Gen {
            prog,
            budget,
            verified,
            trust: trust_callers,
            out: Vec::new(),
            has_req: prog.functions.iter().filter(|f| !f.requires.is_empty()).map(|f| f.name.clone()).collect(),
            cp: None,
            bound: Vec::new(),
            tmp: 0,
            table: TypeTable::new(&prog.types),
            params: HashSet::new(),
        }
    }

    fn emit(&mut self, ind: usize, line: &str) {
        self.out.push(format!("{}{}", "    ".repeat(ind), line));
    }

    fn prelude(&mut self) -> R<()> {
        let types = emit_public_types(self.prog);
        if !types.is_empty() {
            self.out.push(types);
        }
        if !self.verified {
            self.out.push(SAFE_PRELUDE.to_string());
        }
        if !self.has_req.is_empty() && !self.trust {
            self.out.push(CONTRACT_PRELUDE.to_string());
            let ctypes = self.contract_types()?;
            if !ctypes.is_empty() {
                self.out.push(ctypes);
            }
        }
        Ok(())
    }

    /// pruv_contract__Name 거울 타입과 pruv_to_c__Name 변환기(requires 평가 전용)
    fn contract_types(&self) -> R<String> {
        let attrs = "#[allow(dead_code, non_camel_case_types, non_snake_case, unused_variables)]";
        let mut out: Vec<String> = Vec::new();
        for d in self.table.ordered() {
            let cn = format!("pruv_contract__{}", d.name());
            out.push(attrs.to_string());
            out.push("#[derive(Clone, Copy, PartialEq, Eq)]".to_string());
            match d {
                TypeDecl::Struct(s) => {
                    let mut fs: Vec<String> = Vec::new();
                    for f in &s.fields {
                        fs.push(format!("{}: {}", f.name, try_cty(&f.ty)?));
                    }
                    out.push(format!("struct {} {{ {} }}", cn, fs.join(", ")));
                    out.push(attrs.to_string());
                    out.push("#[inline]".to_string());
                    let mut inits: Vec<String> = Vec::new();
                    for f in &s.fields {
                        inits.push(format!("{}: {}", f.name, try_conv(&f.ty, &format!("v.{}", f.name))?));
                    }
                    out.push(format!(
                        "fn pruv_to_c__{}(v: {}) -> {} {{ {} {{ {} }} }}",
                        s.name,
                        s.name,
                        cn,
                        cn,
                        inits.join(", ")
                    ));
                }
                TypeDecl::Enum(en) => {
                    let mut vs: Vec<String> = Vec::new();
                    let mut arms: Vec<String> = Vec::new();
                    for v in &en.variants {
                        if !v.fields.is_empty() {
                            let mut tys: Vec<String> = Vec::new();
                            for f in &v.fields {
                                tys.push(try_cty(&f.ty)?);
                            }
                            vs.push(format!("{}({})", v.name, tys.join(", ")));
                            let names: Vec<String> = (0..v.fields.len()).map(|i| format!("pruv_a{}", i)).collect();
                            let mut cargs: Vec<String> = Vec::new();
                            for (f, n) in v.fields.iter().zip(names.iter()) {
                                cargs.push(try_conv(&f.ty, n)?);
                            }
                            arms.push(format!(
                                "{}::{}({}) => {}::{}({}),",
                                en.name,
                                v.name,
                                names.join(", "),
                                cn,
                                v.name,
                                cargs.join(", ")
                            ));
                        } else {
                            vs.push(v.name.clone());
                            arms.push(format!("{}::{} => {}::{},", en.name, v.name, cn, v.name));
                        }
                    }
                    out.push(format!("enum {} {{ {} }}", cn, vs.join(", ")));
                    out.push(attrs.to_string());
                    out.push("#[inline]".to_string());
                    out.push(format!(
                        "fn pruv_to_c__{}(v: {}) -> {} {{ match v {{ {} }} }}",
                        en.name,
                        en.name,
                        cn,
                        arms.join(" ")
                    ));
                }
            }
        }
        let mut s = out.join("\n");
        if !out.is_empty() {
            s.push('\n');
        }
        Ok(s)
    }

    fn func(&mut self, f: &Function) -> R<()> {
        self.params = f.params.iter().map(|p| p.name.clone()).collect();
        let ps = join_map(&f.params, ", ", |p| format!("{}: {}", p.name, rty(&p.ty, true)));
        let ret = if f.ret == "unit" { String::new() } else { format!(" -> {}", rty(&f.ret, false)) };
        let has = !f.requires.is_empty();
        let body_name = if has { format!("{}__pruv_body", f.name) } else { f.name.clone() };
        self.emit(0, ALLOW);
        self.emit(0, &format!("{}fn {}({}){} {{", if has { "" } else { "pub " }, body_name, ps, ret));
        self.block(&f.body, 1)?;
        self.emit(0, "}");
        self.emit(0, "");
        if has {
            self.entry(f, &ps, &ret, &body_name)?;
        }
        Ok(())
    }

    /// requires 검사들의 코드(cp 를 채운다)
    fn entry_checks(&mut self, f: &Function) -> R<Vec<String>> {
        let mut checks: Vec<String> = Vec::new();
        for r in &f.requires {
            let msg = format!("pruv: requires violated: {}: {}", f.name, show(r));
            let code = self.c(r)?;
            checks.push(format!("if !({}) {{ panic!(\"{{}}\", {}); }}", code, rstr(&msg)));
        }
        Ok(checks)
    }

    fn entry(&mut self, f: &Function, ps: &str, ret: &str, body_name: &str) -> R<()> {
        self.emit(0, ALLOW);
        self.emit(0, "#[inline]");
        self.emit(0, &format!("pub fn {}({}){} {{", f.name, ps, ret));
        if !self.trust {
            self.cp = Some(HashMap::new());
            let res = self.entry_checks(f);
            let used = self.cp.take().unwrap_or_default();
            let checks = res?;
            for p in &f.params {
                if let Some(ty) = used.get(&p.name) {
                    let line = format!("let pruv_cp_{}: {} = {};", p.name, try_cty(ty)?, try_conv(ty, &p.name)?);
                    self.emit(1, &line);
                }
            }
            if !checks.is_empty() {
                let line = format!("let mut pruv_budget: i64 = {};", fmt_underscore(self.budget));
                self.emit(1, &line);
            }
            for line in &checks {
                self.emit(1, line);
            }
        }
        let args = join_map(&f.params, ", ", |p| p.name.clone());
        self.emit(1, &format!("{}({})", body_name, args));
        self.emit(0, "}");
        self.emit(0, "");
        Ok(())
    }

    // ---------- 계약 평가(requires), i128 ----------

    fn carr(&self, e: &Expr) -> R<String> {
        match e {
            Expr::Var(x) => Ok(x.name.clone()),
            other => Err(format!("codegen: unsupported array expression in contract: {:?}", other)),
        }
    }

    fn c(&mut self, e: &Expr) -> R<String> {
        match e {
            Expr::IntLit(x) => Ok(if x.value.starts_with('-') {
                format!("({}i128)", x.value)
            } else {
                format!("{}i128", x.value)
            }),
            Expr::BoolLit(x) => Ok((if x.value { "true" } else { "false" }).to_string()),
            Expr::Var(x) => {
                if self.bound.iter().any(|b| b == &x.name) {
                    return Ok(x.name.clone());
                }
                if let Some(ty) = &x.ty {
                    if self.cp.is_some() && is_user_type(ty) && self.params.contains(&x.name) {
                        if let Some(cp) = self.cp.as_mut() {
                            cp.insert(x.name.clone(), ty.clone());
                        }
                        return Ok(format!("pruv_cp_{}", x.name));
                    }
                }
                let t = x.ty.as_deref().unwrap_or("i64");
                if t == "i64" || t == "option" || t == "result" || is_user_type(t) {
                    return try_conv(t, &x.name);
                }
                Ok(x.name.clone())
            }
            Expr::Unary(x) => {
                if x.op == "!" {
                    Ok(format!("(!{})", self.c(&x.operand)?))
                } else {
                    Ok(format!("pruv_cneg({})", self.c(&x.operand)?))
                }
            }
            Expr::Binary(x) => {
                let op = x.op.as_str();
                if op == "==>" {
                    let l = self.c(&x.left)?;
                    let r = self.c(&x.right)?;
                    return Ok(format!("(!{} || {})", l, r));
                }
                let l = self.c(&x.left)?;
                let r = self.c(&x.right)?;
                if let Some(f) = contract_arith(op) {
                    return Ok(format!("{}({}, {})", f, l, r));
                }
                Ok(format!("({} {} {})", l, op, r))
            }
            Expr::Index(x) => {
                let a = self.carr(&x.array)?;
                let i = self.c(&x.index)?;
                Ok(format!("pruv_cidx({}, {})", a, i))
            }
            Expr::Ctor(x) => {
                if x.name == "None" {
                    return Ok("None::<i128>".to_string());
                }
                let ctor = match x.name.as_str() {
                    "Some" => "Some",
                    "Ok" => "Ok::<i128, i128>",
                    "Err" => "Err::<i128, i128>",
                    other => return Err(repr_str(other)),
                };
                match &x.arg {
                    Some(a) => Ok(format!("{}({})", ctor, self.c(a)?)),
                    None => Err("codegen: unsupported expression in requires: None".to_string()),
                }
            }
            Expr::Quant(_) => self.cquant(e),
            Expr::StructLit(x) => {
                // 선언 순서로 평가(Rust 는 리터럴 필드를 쓰인 순서로 평가)
                let fs: Vec<FieldDecl> = k_fields(&self.table, &x.name, None)?.to_vec();
                let vals = init_map(&x.fields);
                let mut parts: Vec<String> = Vec::new();
                for f in &fs {
                    let v = init_value(&vals, &f.name)?;
                    parts.push(format!("{}: {}", f.name, self.c(v)?));
                }
                let body = parts.join(", ");
                if !fs.is_empty() {
                    Ok(format!("(pruv_contract__{} {{ {} }})", x.name, body))
                } else {
                    Ok(format!("(pruv_contract__{} {{}})", x.name))
                }
            }
            Expr::EnumCtor(x) => {
                let ctor = format!("pruv_contract__{}::{}", x.enum_name, x.variant);
                if x.args.is_empty() {
                    return Ok(ctor);
                }
                let mut parts: Vec<String> = Vec::new();
                for a in &x.args {
                    parts.push(self.c(a)?);
                }
                Ok(format!("{}({})", ctor, parts.join(", ")))
            }
            Expr::FieldAccess(x) => Ok(format!("{}.{}", self.c(&x.base)?, x.field)),
            Expr::IsVariant(x) => {
                Ok(format!("matches!({}, pruv_contract__{}::{} {{ .. }})", self.c(&x.value)?, x.enum_name, x.variant))
            }
            Expr::VariantField(x) => {
                self.tmp += 1;
                let tmp = format!("pruv_e{}", self.tmp);
                let cn = format!("pruv_contract__{}", x.enum_name);
                let nfields = k_variant(&self.table, &x.enum_name, &x.variant)?.fields.len();
                let idx = k_field_index(&self.table, &x.enum_name, &x.field, Some(&x.variant))?;
                let pats = (0..nfields).map(|i| if i == idx { "pruv_f" } else { "_" }).collect::<Vec<_>>().join(", ");
                let msg = format!("variant_field expected {}::{}.{}", x.enum_name, x.variant, x.field);
                let val = self.c(&x.value)?;
                Ok(format!(
                    "({{ let {tmp}: {cn} = {val}; match {tmp} {{ {cn}::{v}({pats}) => pruv_f, _ => pruv_ud({m}) }} }})",
                    tmp = tmp,
                    cn = cn,
                    val = val,
                    v = x.variant,
                    pats = pats,
                    m = rstr(&msg)
                ))
            }
            Expr::Call(x) => {
                let n = x.name.as_str();
                let a = &x.args;
                if n == "len" {
                    return Ok(format!("({}.len() as i128)", self.carr(arg(a, 0)?)?));
                }
                if n == "is_some" {
                    return Ok(format!("{}.is_some()", self.c(arg(a, 0)?)?));
                }
                if n == "some_val" {
                    return Ok(format!("{}.unwrap_or_else(|| pruv_ud(\"some_val of None\"))", self.c(arg(a, 0)?)?));
                }
                if n == "is_ok" {
                    return Ok(format!("{}.is_ok()", self.c(arg(a, 0)?)?));
                }
                if n == "ok_val" {
                    return Ok(format!("{}.ok().unwrap_or_else(|| pruv_ud(\"ok_val of Err\"))", self.c(arg(a, 0)?)?));
                }
                if n == "err_val" {
                    return Ok(format!("{}.err().unwrap_or_else(|| pruv_ud(\"err_val of Ok\"))", self.c(arg(a, 0)?)?));
                }
                Err(format!("codegen: unsupported expression in requires: {:?}", e))
            }
        }
    }

    fn cquant(&mut self, e: &Expr) -> R<String> {
        let q0 = match e {
            Expr::Quant(q) => q,
            other => return Err(format!("codegen: unsupported expression in requires: {:?}", other)),
        };
        // 정렬 requires 는 O(n) 동치형으로 바꾼다(docs/M0_CONTRACTS.md C):
        // forall pruv_sk in 1..len(a): a[pruv_sk-1] <= a[pruv_sk]
        let owned: Quant;
        let q: &Quant = match match_sorted_requires(e) {
            Some(arr) => {
                let (line, col) = (e.line(), e.col());
                let var = |n: &str| Expr::Var(Var { line, col, name: n.to_string(), ty: None });
                let one = Expr::IntLit(IntLit { line, col, value: "1".to_string(), ty: None });
                let kv = var("pruv_sk");
                let idx = |ix: Expr| {
                    Expr::Index(Index { line, col, array: Box::new(var(&arr)), index: Box::new(ix), ty: None })
                };
                let prev = Expr::Binary(Binary {
                    line,
                    col,
                    op: "-".to_string(),
                    left: Box::new(kv.clone()),
                    right: Box::new(one.clone()),
                    ty: None,
                });
                let body = Expr::Binary(Binary {
                    line,
                    col,
                    op: "<=".to_string(),
                    left: Box::new(idx(prev)),
                    right: Box::new(idx(kv)),
                    ty: None,
                });
                owned = Quant {
                    line,
                    col,
                    kind: "forall".to_string(),
                    var: "pruv_sk".to_string(),
                    lo: Box::new(one),
                    hi: q0.hi.clone(),
                    body: Box::new(body),
                    ty: None,
                };
                &owned
            }
            None => q0,
        };
        self.tmp += 1;
        let n = self.tmp;
        let lo = self.c(&q.lo)?; // 경계는 바깥 범위만 본다
        let hi = self.c(&q.hi)?;
        self.bound.push(q.var.clone());
        let body = self.c(&q.body)?;
        self.bound.pop();
        let k = format!("pruv_k{}", n);
        let r = format!("pruv_r{}", n);
        let h = format!("pruv_hi{}", n);
        let head = format!(
            "{{ let pruv_lo{n}: i128 = {lo}; let {h}: i128 = {hi}; let mut {k}: i128 = pruv_lo{n}; ",
            n = n,
            lo = lo,
            h = h,
            hi = hi,
            k = k
        );
        let lp = format!(
            "while {k} < {h} {{ pruv_budget -= 1; if pruv_budget < 0 {{ pruv_ud(\"contract iteration budget exceeded\"); }} let {v}: i128 = {k}; ",
            k = k,
            h = h,
            v = q.var
        );
        let tail = format!("{} += 1; }} ", k);
        let kind = q.kind.as_str();
        if kind == "forall" {
            return Ok(format!(
                "{}let mut {} = true; {}if !({}) {{ {} = false; break; }} {}{} }}",
                head, r, lp, body, r, tail, r
            ));
        }
        if kind == "exists" {
            return Ok(format!(
                "{}let mut {} = false; {}if {} {{ {} = true; break; }} {}{} }}",
                head, r, lp, body, r, tail, r
            ));
        }
        if kind == "sum" {
            return Ok(format!(
                "{}let mut {}: i128 = 0; {}{} = pruv_cadd({}, {}); {}{} }}",
                head, r, lp, r, r, body, tail, r
            ));
        }
        if kind == "count" {
            return Ok(format!(
                "{}let mut {}: i128 = 0; {}if {} {{ {} += 1; }} {}{} }}",
                head, r, lp, body, r, tail, r
            ));
        }
        // max / min
        let cmp = if kind == "max" { ">" } else { "<" };
        Ok(format!(
            "{head}let mut {r}: ::std::option::Option<i128> = None; {lp}let pruv_v: i128 = {body}; {r} = Some(match {r} {{ None => pruv_v, Some(pruv_a) => if pruv_v {cmp} pruv_a {{ pruv_v }} else {{ pruv_a }} }}); {tail}{r}.unwrap_or_else(|| pruv_ud(\"{kind} over an empty range\")) }}",
            head = head,
            r = r,
            lp = lp,
            body = body,
            cmp = cmp,
            tail = tail,
            kind = kind
        ))
    }

    // ---------- 문 / 코드 식 ----------

    fn block(&mut self, stmts: &[Stmt], ind: usize) -> R<()> {
        for st in stmts {
            self.stmt(st, ind)?;
        }
        Ok(())
    }

    fn stmt(&mut self, st: &Stmt, ind: usize) -> R<()> {
        match st {
            Stmt::Let(x) => {
                let v = self.e(&x.value)?;
                let line = format!("let {}{}: {} = {};", if x.mutable { "mut " } else { "" }, x.name, rty(&x.ty, false), v);
                self.emit(ind, &line);
            }
            Stmt::Assign(x) => {
                let v = self.e(&x.value)?;
                self.emit(ind, &format!("{} = {};", x.name, v));
            }
            Stmt::FieldAssign(x) => {
                // 우변을 임시에 완전히 평가한 뒤 저장
                let decl = match expr_ty(&x.value) {
                    Some(t) => format!("let pruv_v: {} = ", rty(t, false)),
                    None => "let pruv_v = ".to_string(),
                };
                let v = self.e(&x.value)?;
                self.emit(ind, &format!("{{ {}{}; {}.{} = pruv_v; }}", decl, v, x.name, x.fields.join(".")));
            }
            Stmt::IndexAssign(x) => {
                let i = self.e(&x.index)?;
                let v = self.e(&x.value)?;
                if self.verified {
                    self.emit(
                        ind,
                        &format!(
                            "{{ let pruv_i: i64 = {}; let pruv_x: i64 = {}; unsafe {{ *{}.get_unchecked_mut(pruv_i as usize) = pruv_x; }} }}",
                            i, v, x.name
                        ),
                    );
                } else {
                    // 임시 먼저: 인덱스·값이 `a` 를 읽는 동안 `&mut a` 가 살아 있으면 안 된다
                    self.emit(
                        ind,
                        &format!(
                            "{{ let pruv_i: i64 = {}; let pruv_x: i64 = {}; pruv_set(&mut {}, pruv_i, pruv_x); }}",
                            i, v, x.name
                        ),
                    );
                }
            }
            Stmt::If(x) => {
                let c = self.e(&x.cond)?;
                self.emit(ind, &format!("if {} {{", c));
                self.block(&x.then, ind + 1)?;
                if !x.els.is_empty() {
                    self.emit(ind, "} else {");
                    self.block(&x.els, ind + 1)?;
                }
                self.emit(ind, "}");
            }
            Stmt::While(x) => {
                let c = self.e(&x.cond)?;
                self.emit(ind, &format!("while {} {{", c));
                self.block(&x.body, ind + 1)?;
                self.emit(ind, "}");
            }
            Stmt::Return(x) => match &x.value {
                None => self.emit(ind, "return;"),
                Some(v) => {
                    let t = self.e(v)?;
                    self.emit(ind, &format!("return {};", t));
                }
            },
            Stmt::Assert(_) => {}
            Stmt::ExprStmt(x) => {
                let t = self.e(&x.expr)?;
                self.emit(ind, &format!("{};", t));
            }
            Stmt::Match(x) => {
                let s = self.e(&x.scrutinee)?;
                self.emit(ind, &format!("match {} {{", s));
                for a in &x.arms {
                    let name = match &a.enum_name {
                        None => a.ctor.clone(),
                        Some(en) => format!("{}::{}", en, a.ctor),
                    };
                    let pat = if a.binders.is_empty() { name } else { format!("{}({})", name, a.binders.join(", ")) };
                    self.emit(ind + 1, &format!("{} => {{", pat));
                    self.block(&a.body, ind + 2)?;
                    self.emit(ind + 1, "}");
                }
                self.emit(ind, "}");
            }
        }
        Ok(())
    }

    /// 빌린 슬라이스로 쓰는 배열 식
    fn arr_ref(&self, e: &Expr) -> R<String> {
        if let Expr::Var(x) = e {
            if !self.params.contains(&x.name) {
                return Ok(format!("&{}", x.name));
            }
            return Ok(x.name.clone());
        }
        Ok(format!("&{}", self.e(e)?))
    }

    fn e(&self, e: &Expr) -> R<String> {
        match e {
            Expr::IntLit(x) => {
                if x.value == "-9223372036854775808" {
                    return Ok("i64::MIN".to_string());
                }
                Ok(if x.value.starts_with('-') { format!("({}i64)", x.value) } else { format!("{}i64", x.value) })
            }
            Expr::BoolLit(x) => Ok((if x.value { "true" } else { "false" }).to_string()),
            Expr::Var(x) => Ok(x.name.clone()),
            Expr::Unary(x) => {
                if !self.verified && x.op == "-" {
                    return Ok(format!("pruv_neg({})", self.e(&x.operand)?));
                }
                Ok(format!("({}{})", x.op, self.e(&x.operand)?))
            }
            Expr::Binary(x) => {
                if !self.verified {
                    if let Some(f) = safe_arith(&x.op) {
                        let l = self.e(&x.left)?;
                        let r = self.e(&x.right)?;
                        return Ok(format!("{}({}, {})", f, l, r));
                    }
                }
                let l = self.e(&x.left)?;
                let r = self.e(&x.right)?;
                Ok(format!("({} {} {})", l, x.op, r))
            }
            Expr::Index(x) => {
                if !self.verified {
                    let a = self.arr_ref(&x.array)?;
                    let i = self.e(&x.index)?;
                    return Ok(format!("pruv_get({}, {})", a, i));
                }
                let a = self.e(&x.array)?;
                let i = self.e(&x.index)?;
                Ok(format!("(unsafe {{ *{}.get_unchecked(({}) as usize) }})", a, i))
            }
            Expr::Ctor(x) => {
                if x.name == "None" {
                    return Ok("None".to_string());
                }
                match &x.arg {
                    Some(a) => Ok(format!("{}({})", x.name, self.e(a)?)),
                    None => Err("codegen: contract-only expression in code: None".to_string()),
                }
            }
            Expr::StructLit(x) => {
                // 선언 순서 = 왼쪽에서 오른쪽 평가; 괄호로 감싸 `if S { .. }.x` 가 파싱되게 한다
                let fs = k_fields(&self.table, &x.name, None)?;
                if fs.is_empty() {
                    return Ok(format!("({} {{}})", x.name));
                }
                let vals = init_map(&x.fields);
                let mut parts: Vec<String> = Vec::new();
                for f in fs {
                    let v = init_value(&vals, &f.name)?;
                    parts.push(format!("{}: {}", f.name, self.e(v)?));
                }
                Ok(format!("({} {{ {} }})", x.name, parts.join(", ")))
            }
            Expr::EnumCtor(x) => {
                let ctor = format!("{}::{}", x.enum_name, x.variant);
                if x.args.is_empty() {
                    return Ok(ctor);
                }
                let mut parts: Vec<String> = Vec::new();
                for a in &x.args {
                    parts.push(self.e(a)?);
                }
                Ok(format!("{}({})", ctor, parts.join(", ")))
            }
            Expr::FieldAccess(x) => Ok(format!("{}.{}", self.e(&x.base)?, x.field)),
            Expr::Call(x) => {
                let n = x.name.as_str();
                let a = &x.args;
                if n == "len" {
                    return Ok(format!("({}.len() as i64)", self.e(arg(a, 0)?)?));
                }
                if n == "alloc" {
                    if !self.verified {
                        let n0 = self.e(arg(a, 0)?)?;
                        let v0 = self.e(arg(a, 1)?)?;
                        return Ok(format!("pruv_alloc({}, {})", n0, v0));
                    }
                    // 소스 순서: n 먼저, v 나중(vec![v; n] 은 v 를 먼저 평가한다)
                    let n0 = self.e(arg(a, 0)?)?;
                    let v0 = self.e(arg(a, 1)?)?;
                    return Ok(format!(
                        "{{ let pruv_n: i64 = {}; let pruv_v: i64 = {}; vec![pruv_v; pruv_n as usize] }}",
                        n0, v0
                    ));
                }
                if n == "copy" {
                    return Ok(format!("{}.to_vec()", self.e(arg(a, 0)?)?));
                }
                if n == "print" {
                    return Ok(format!("println!(\"{{}}\", {})", self.e(arg(a, 0)?)?));
                }
                let mut args: Vec<String> = Vec::new();
                for x in a {
                    if expr_ty(x).as_deref() == Some("array") {
                        args.push(self.arr_ref(x)?);
                    } else {
                        args.push(self.e(x)?);
                    }
                }
                let mut name = n.to_string();
                if self.verified && self.has_req.contains(&name) {
                    name.push_str("__pruv_body"); // 호출자가 requires 를 증명했다
                }
                Ok(format!("{}({})", name, args.join(", ")))
            }
            other => Err(format!("codegen: contract-only expression in code: {:?}", other)),
        }
    }
}

/// Pruv -> Rust 소스. Err 는 Python 이 Exception 을 내는 자리의 str(e).
pub fn gen_rust(prog: &Program, verified: bool, trust_callers: bool, budget: u64) -> Result<String, String> {
    if let Some(e) = crate::typeinfo::g2_unimplemented_error(prog, "codegen") {
        return Err(format!("unsupported_type: {}", e.message));
    }
    let mut g = Gen::new(prog, verified, trust_callers, budget);
    g.prelude()?;
    for f in &prog.functions {
        g.func(f)?;
    }
    let mut s = g.out.join("\n");
    s.push('\n');
    Ok(s)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn var(n: &str, ty: &str) -> Expr {
        Expr::Var(Var { line: 1, col: 1, name: n.into(), ty: Some(ty.into()) })
    }
    fn int(v: &str) -> Expr {
        Expr::IntLit(IntLit { line: 1, col: 1, value: v.into(), ty: Some("i64".into()) })
    }
    fn bin(op: &str, l: Expr, r: Expr) -> Expr {
        Expr::Binary(Binary { line: 1, col: 1, op: op.into(), left: Box::new(l), right: Box::new(r), ty: Some("i64".into()) })
    }
    fn prog(requires: Vec<Expr>) -> Program {
        let f = Function {
            line: 1,
            col: 1,
            name: "f".into(),
            params: vec![Param { name: "x".into(), ty: "i64".into(), refine: None }],
            ret: "i64".into(),
            effects: vec![],
            requires,
            ensures: vec![],
            body: vec![Stmt::Return(Return { line: 1, col: 1, value: Some(bin("+", var("x", "i64"), int("1"))) })],
            ret_refine: None,
        };
        Program { functions: vec![f], types: vec![], refined: false }
    }

    #[test]
    fn verified_plain() {
        let s = gen_rust(&prog(vec![]), true, false, 1 << 30).unwrap();
        assert_eq!(s, format!("{}\npub fn f(x: i64) -> i64 {{\n    return (x + 1i64);\n}}\n\n", ALLOW));
    }

    #[test]
    fn safe_mode_and_requires() {
        let p = prog(vec![bin(">", var("x", "i64"), int("0"))]);
        let s = gen_rust(&p, false, false, 1 << 30).unwrap();
        assert!(s.starts_with(SAFE_PRELUDE));
        assert!(s.contains(CONTRACT_PRELUDE));
        assert!(s.contains("fn f__pruv_body(x: i64) -> i64 {\n    return pruv_add(x, 1i64);\n}\n"));
        assert!(s.contains("    let mut pruv_budget: i64 = 1_073_741_824;\n"));
        assert!(s.contains(
            "    if !(((x as i128) > 0i128)) { panic!(\"{}\", \"pruv: requires violated: f: (x > 0)\"); }\n    f__pruv_body(x)\n}\n"
        ));
        // trust_callers 면 검사·예산 없음
        let t = gen_rust(&p, true, true, 5).unwrap();
        assert!(!t.contains("pruv_budget") && t.contains("    f__pruv_body(x)\n"));
    }

    #[test]
    fn underscore_format() {
        assert_eq!(fmt_underscore(0), "0");
        assert_eq!(fmt_underscore(999), "999");
        assert_eq!(fmt_underscore(1000), "1_000");
        assert_eq!(fmt_underscore(1 << 30), "1_073_741_824");
        assert_eq!(fmt_underscore(100), "100");
    }
}
