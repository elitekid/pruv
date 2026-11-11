//! Pruv -> Rust source generator (a port of codegen.py's constants, class Gen and gen_rust).
//! Goal: for the same program and mode (verified, trust_callers, budget), byte-identical to Python's gen_rust.
//! The functions at lines 128-272 (rty, cty, conv, emit_public_types, show, match_sorted_requires, rstr) use the ones in emit_common.
//! Rule: mutable state (temp number tmp, contract variable bound, cp dictionary) is changed in the same order as in Python.
//! Places where Python raises an Exception return Err(str(e)) (an AST printed with %r becomes {:?} — an unreachable path).

use crate::ast::*;
use crate::emit_common::{emit_public_types, match_sorted_requires, rstr, rty, show, try_conv, try_cty};
use crate::pyrepr::repr_str;
use crate::typeinfo::{array_elem_name, is_array_name, is_user_type, uses_array_type, uses_str, TypeTable};
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

/// Appended right after SAFE_PRELUDE only in safe mode for programs that use `[u8]`.
pub const SAFE_PRELUDE_U8: &str = r##"#[allow(dead_code)]
#[cold]
#[inline(never)]
fn pruv_elem_oor(v: i64) -> ! { panic!("pruv: element out of range: {} (u8 0..=255)", v) }
#[allow(dead_code)]
#[inline]
fn pruv_get_u8(a: &[u8], i: i64) -> i64 { a[pruv_idx(i, a.len())] as i64 }
#[allow(dead_code)]
#[inline]
fn pruv_set_u8(a: &mut [u8], i: i64, v: i64) { let k = pruv_idx(i, a.len()); if v < 0 || v > 255 { pruv_elem_oor(v) } a[k] = v as u8; }
#[allow(dead_code)]
#[inline]
fn pruv_alloc_u8(n: i64, v: i64) -> ::std::vec::Vec<u8> { if n < 0 || n > (1i64 << 40) { pruv_ovf("alloc length outside 0..2^40") } if v < 0 || v > 255 { pruv_elem_oor(v) } vec![v as u8; n as usize] }
"##;

/// Appended right after CONTRACT_PRELUDE only for the runtime requires check of programs that use `[u8]`.
pub const CONTRACT_PRELUDE_U8: &str = r##"#[allow(dead_code)]
#[inline]
fn pruv_cidx_u8(a: &[u8], i: i128) -> i128 { if i >= 0 && i < (a.len() as i128) { a[i as usize] as i128 } else { pruv_ud("array index out of range") } }
"##;

// G2 A5: appended after SAFE_PRELUDE_U8 (if present) only in safe mode for programs that use `[bool]`.
pub const SAFE_PRELUDE_BOOL: &str = r##"#[allow(dead_code)]
#[inline]
fn pruv_get_bool(a: &[bool], i: i64) -> bool { a[pruv_idx(i, a.len())] }
#[allow(dead_code)]
#[inline]
fn pruv_set_bool(a: &mut [bool], i: i64, v: bool) { let k = pruv_idx(i, a.len()); a[k] = v; }
#[allow(dead_code)]
#[inline]
fn pruv_alloc_bool(n: i64, v: bool) -> ::std::vec::Vec<bool> { if n < 0 || n > (1i64 << 40) { pruv_ovf("alloc length outside 0..2^40") } vec![v; n as usize] }
"##;

// G2 A5: appended after CONTRACT_PRELUDE_U8 (if present) only for the runtime requires check of programs that use `[bool]`.
pub const CONTRACT_PRELUDE_BOOL: &str = r##"#[allow(dead_code)]
#[inline]
fn pruv_cidx_bool(a: &[bool], i: i128) -> bool { if i >= 0 && i < (a.len() as i128) { a[i as usize] } else { pruv_ud("array index out of range") } }
"##;

// G2 B2: appended after the user types for programs that use str, regardless of mode.
pub const STR_PRELUDE: &str = r##"#[allow(dead_code)]
#[inline]
fn pruv_str_boundary(a: &str, i: i64) -> bool { i >= 0 && (i as u64) <= (a.len() as u64) && a.is_char_boundary(i as usize) }
"##;

// G2 B2: appended after SAFE_PRELUDE_BOOL (if present) only in safe mode for programs that use str.
pub const SAFE_PRELUDE_STR: &str = r##"#[allow(dead_code)]
#[cold]
#[inline(never)]
fn pruv_slice_oob(lo: i64, hi: i64, len: usize) -> ! { panic!("pruv: string slice out of bounds: {}..{} (len {})", lo, hi, len) }
#[allow(dead_code)]
#[cold]
#[inline(never)]
fn pruv_slice_cut(lo: i64, hi: i64, len: usize) -> ! { panic!("pruv: UTF-8 boundary error: {}..{} (len {})", lo, hi, len) }
#[allow(dead_code)]
#[inline]
fn pruv_get_str(a: &str, i: i64) -> i64 { a.as_bytes()[pruv_idx(i, a.len())] as i64 }
#[allow(dead_code)]
#[inline]
fn pruv_substr(a: &str, lo: i64, hi: i64) -> ::std::string::String { if !(lo >= 0 && lo <= hi && (hi as u64) <= (a.len() as u64)) { pruv_slice_oob(lo, hi, a.len()) } if !(a.is_char_boundary(lo as usize) && a.is_char_boundary(hi as usize)) { pruv_slice_cut(lo, hi, a.len()) } ::std::string::String::from(&a[(lo as usize)..(hi as usize)]) }
"##;

// G2 B2: appended after CONTRACT_PRELUDE_BOOL (if present) only for the runtime requires check of programs that use str.
pub const CONTRACT_PRELUDE_STR: &str = r##"#[allow(dead_code)]
#[inline]
fn pruv_cidx_str(a: &str, i: i128) -> i128 { if i >= 0 && i < (a.len() as i128) { a.as_bytes()[i as usize] as i128 } else { pruv_ud("array index out of range") } }
#[allow(dead_code)]
#[inline]
fn pruv_cboundary(a: &str, i: i128) -> bool { i >= 0 && i <= (a.len() as i128) && a.is_char_boundary(i as usize) }
"##;

/// G2 B2: string literal spelling LIT (spec 1.2). The bytes are UTF-8, guaranteed by the parser.
fn lit_str(bytes: &[u8]) -> String {
    let mut s = String::from("\"");
    for ch in String::from_utf8_lossy(bytes).chars() {
        let c = ch as u32;
        if (0x20..=0x7E).contains(&c) && ch != '"' && ch != '\\' {
            s.push(ch);
        } else {
            s.push_str(&format!("\\u{{{:x}}}", c));
        }
    }
    s.push('"');
    s
}

/// The array element type name of the expression ("i64" if it is not an array).
fn elem_of(e: &Expr) -> &'static str {
    expr_ty(e).as_deref().and_then(array_elem_name).unwrap_or("i64")
}

/// SAFE_ARITH table
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

/// CONTRACT_ARITH table
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

// ---------- helpers ----------

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

/// The IndexError of Python `a[i]`
fn arg(a: &[Expr], i: usize) -> R<&Expr> {
    a.get(i).ok_or_else(|| "list index out of range".to_string())
}

/// Python `format(n, "_")`: an underscore every three digits.
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

/// The KeyError of TypeTable.decl
fn k_decl<'t>(tt: &'t TypeTable, ty: &str) -> R<&'t TypeDecl> {
    tt.decl(ty).ok_or_else(|| repr_str(ty))
}

/// TypeTable.variant (AttributeError for a struct, KeyError if missing)
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

/// Builds `{f.name: f.value for f in e.fields}` once per literal (on duplicates the later one wins = dict).
/// Audit: scanning from the back for every field was quadratic in the field count.
fn init_map(fields: &[FieldInit]) -> std::collections::HashMap<&str, &Expr> {
    let mut m = std::collections::HashMap::new();
    for f in fields {
        m.insert(f.name.as_str(), &f.value);
    }
    m
}

/// init_map lookup (the Python KeyError message if missing)
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
    /// During the requires entry check: user-type parameters already converted -> type
    cp: Option<HashMap<String, String>>,
    /// Quantifier variables in scope (contract evaluation)
    bound: Vec<String>,
    tmp: u64,
    table: TypeTable,
    params: HashSet<String>,
    /// Variable type table (parameters and let; copied and restored per block)
    vars: HashMap<String, String>,
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
            vars: HashMap::new(),
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
        let u8_used = uses_array_type(self.prog, "array_u8");
        let bool_used = uses_array_type(self.prog, "array_bool"); // G2 A5
        let str_used = uses_str(self.prog); // G2 B2
        if str_used {
            self.out.push(STR_PRELUDE.to_string());
        }
        if !self.verified {
            self.out.push(SAFE_PRELUDE.to_string());
            if u8_used {
                self.out.push(SAFE_PRELUDE_U8.to_string());
            }
            if bool_used {
                self.out.push(SAFE_PRELUDE_BOOL.to_string());
            }
            if str_used {
                self.out.push(SAFE_PRELUDE_STR.to_string());
            }
        }
        if !self.has_req.is_empty() && !self.trust {
            self.out.push(CONTRACT_PRELUDE.to_string());
            if u8_used {
                self.out.push(CONTRACT_PRELUDE_U8.to_string());
            }
            if bool_used {
                self.out.push(CONTRACT_PRELUDE_BOOL.to_string());
            }
            if str_used {
                self.out.push(CONTRACT_PRELUDE_STR.to_string());
            }
            let ctypes = self.contract_types()?;
            if !ctypes.is_empty() {
                self.out.push(ctypes);
            }
        }
        Ok(())
    }

    /// The pruv_contract__Name mirror type and the pruv_to_c__Name converter (for requires evaluation only)
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
        self.vars = f.params.iter().map(|p| (p.name.clone(), p.ty.clone())).collect();
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

    /// Code of the requires checks (fills cp)
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

    // ---------- contract (requires) evaluation, i128 ----------

    fn carr(&self, e: &Expr) -> R<String> {
        match e {
            Expr::Var(x) => Ok(x.name.clone()),
            Expr::StrLit(x) => Ok(lit_str(&x.value)), // G2 B2
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
            Expr::StrLit(x) => Ok(lit_str(&x.value)), // G2 B2
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
                if expr_ty(&x.array).as_deref() == Some("str") {
                    // G2 B2: split before reaching elem_of
                    return Ok(format!("pruv_cidx_str({}, {})", a, i));
                }
                if elem_of(&x.array) == "u8" {
                    return Ok(format!("pruv_cidx_u8({}, {})", a, i));
                }
                if elem_of(&x.array) == "bool" {
                    // G2 A5
                    return Ok(format!("pruv_cidx_bool({}, {})", a, i));
                }
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
                // Evaluate in declaration order (Rust evaluates literal fields in the order written)
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
                if n == "is_char_boundary" {
                    // G2 B2
                    let s0 = self.carr(arg(a, 0)?)?;
                    let i0 = self.c(arg(a, 1)?)?;
                    return Ok(format!("pruv_cboundary({}, {})", s0, i0));
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
        // A sorted requires is rewritten into its O(n) equivalent form (docs/M0_CONTRACTS.md C):
        // forall pruv_sk in 1..len(a): a[pruv_sk-1] <= a[pruv_sk]
        let owned: Quant;
        // Type of the original array variable: the ty of the Var argument of `len(a)` in e.hi
        let arr_ty0: Option<String> = match &*q0.hi {
            Expr::Call(c) => c.args.first().and_then(|x| expr_ty(x).clone()),
            _ => None,
        };
        // G2 B2: the sorted fast path is not used for str arrays (general path)
        let sorted = if arr_ty0.as_deref() == Some("str") { None } else { match_sorted_requires(e) };
        let q: &Quant = match sorted {
            Some(arr) => {
                let (line, col) = (e.line(), e.col());
                let arr_ty: Option<String> = arr_ty0.clone();
                let var = |n: &str| Expr::Var(Var { line, col, name: n.to_string(), ty: None });
                let one = Expr::IntLit(IntLit { line, col, value: "1".to_string(), ty: None });
                let kv = var("pruv_sk");
                let idx = |ix: Expr| {
                    Expr::Index(Index {
                        line,
                        col,
                        array: Box::new(Expr::Var(Var { line, col, name: arr.clone(), ty: arr_ty.clone() })),
                        index: Box::new(ix),
                        ty: Some("i64".to_string()),
                    })
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
        let lo = self.c(&q.lo)?; // the bounds see only the outer scope
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

    // ---------- statements / code expressions ----------

    fn block(&mut self, stmts: &[Stmt], ind: usize) -> R<()> {
        let saved = self.vars.clone();
        for st in stmts {
            self.stmt(st, ind)?;
        }
        self.vars = saved;
        Ok(())
    }

    fn stmt(&mut self, st: &Stmt, ind: usize) -> R<()> {
        match st {
            Stmt::Let(x) => {
                let v = self.e(&x.value)?;
                let line = format!("let {}{}: {} = {};", if x.mutable { "mut " } else { "" }, x.name, rty(&x.ty, false), v);
                self.emit(ind, &line);
                self.vars.insert(x.name.clone(), x.ty.clone());
            }
            Stmt::Assign(x) => {
                let v = self.e(&x.value)?;
                self.emit(ind, &format!("{} = {};", x.name, v));
            }
            Stmt::FieldAssign(x) => {
                // Fully evaluate the right-hand side into a temporary, then store
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
                let is_u8 = self.vars.get(&x.name).map(|t| t.as_str()) == Some("array_u8");
                let is_bool = self.vars.get(&x.name).map(|t| t.as_str()) == Some("array_bool"); // G2 A5
                if is_bool {
                    if self.verified {
                        self.emit(
                            ind,
                            &format!(
                                "{{ let pruv_i: i64 = {}; let pruv_x: bool = {}; unsafe {{ *{}.get_unchecked_mut(pruv_i as usize) = pruv_x; }} }}",
                                i, v, x.name
                            ),
                        );
                    } else {
                        self.emit(
                            ind,
                            &format!(
                                "{{ let pruv_i: i64 = {}; let pruv_x: bool = {}; pruv_set_bool(&mut {}, pruv_i, pruv_x); }}",
                                i, v, x.name
                            ),
                        );
                    }
                } else if is_u8 {
                    if self.verified {
                        self.emit(
                            ind,
                            &format!(
                                "{{ let pruv_i: i64 = {}; let pruv_x: i64 = {}; unsafe {{ *{}.get_unchecked_mut(pruv_i as usize) = pruv_x as u8; }} }}",
                                i, v, x.name
                            ),
                        );
                    } else {
                        self.emit(
                            ind,
                            &format!(
                                "{{ let pruv_i: i64 = {}; let pruv_x: i64 = {}; pruv_set_u8(&mut {}, pruv_i, pruv_x); }}",
                                i, v, x.name
                            ),
                        );
                    }
                } else if self.verified {
                    self.emit(
                        ind,
                        &format!(
                            "{{ let pruv_i: i64 = {}; let pruv_x: i64 = {}; unsafe {{ *{}.get_unchecked_mut(pruv_i as usize) = pruv_x; }} }}",
                            i, v, x.name
                        ),
                    );
                } else {
                    // Temporaries first: `&mut a` must not be alive while the index and value read `a`
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

    /// An array expression used as a borrowed slice
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
            Expr::StrLit(x) => Ok(format!("::std::string::String::from({})", lit_str(&x.value))), // G2 B2
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
            Expr::Index(x) if expr_ty(&x.array).as_deref() == Some("str") => {
                // G2 B2: split before reaching elem_of
                if !self.verified {
                    let a = self.arr_ref(&x.array)?;
                    let i = self.e(&x.index)?;
                    return Ok(format!("pruv_get_str({}, {})", a, i));
                }
                let a = self.e(&x.array)?;
                let i = self.e(&x.index)?;
                Ok(format!("((unsafe {{ *{}.as_bytes().get_unchecked(({}) as usize) }}) as i64)", a, i))
            }
            Expr::Index(x) => {
                let u8r = elem_of(&x.array) == "u8";
                let boolr = elem_of(&x.array) == "bool"; // G2 A5
                if !self.verified {
                    let a = self.arr_ref(&x.array)?;
                    let i = self.e(&x.index)?;
                    if boolr {
                        return Ok(format!("pruv_get_bool({}, {})", a, i));
                    }
                    if u8r {
                        return Ok(format!("pruv_get_u8({}, {})", a, i));
                    }
                    return Ok(format!("pruv_get({}, {})", a, i));
                }
                let a = self.e(&x.array)?;
                let i = self.e(&x.index)?;
                if u8r {
                    return Ok(format!("((unsafe {{ *{}.get_unchecked(({}) as usize) }}) as i64)", a, i));
                }
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
                // Declaration order = left-to-right evaluation; wrap in parentheses so that `if S { .. }.x` parses
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
                    let u8a = x.ty.as_deref() == Some("array_u8");
                    let boola = x.ty.as_deref() == Some("array_bool"); // G2 A5
                    if !self.verified {
                        let n0 = self.e(arg(a, 0)?)?;
                        let v0 = self.e(arg(a, 1)?)?;
                        let f = if boola {
                            "pruv_alloc_bool"
                        } else if u8a {
                            "pruv_alloc_u8"
                        } else {
                            "pruv_alloc"
                        };
                        return Ok(format!("{}({}, {})", f, n0, v0));
                    }
                    // Source order: n first, v later (vec![v; n] evaluates v first)
                    let n0 = self.e(arg(a, 0)?)?;
                    let v0 = self.e(arg(a, 1)?)?;
                    if boola {
                        return Ok(format!(
                            "{{ let pruv_n: i64 = {}; let pruv_v: bool = {}; vec![pruv_v; pruv_n as usize] }}",
                            n0, v0
                        ));
                    }
                    return Ok(format!(
                        "{{ let pruv_n: i64 = {}; let pruv_v: i64 = {}; vec![pruv_v{}; pruv_n as usize] }}",
                        n0,
                        v0,
                        if u8a { " as u8" } else { "" }
                    ));
                }
                if n == "copy" {
                    if expr_ty(arg(a, 0)?).as_deref() == Some("str") {
                        // G2 B2
                        return Ok(format!("{}.to_owned()", self.e(arg(a, 0)?)?));
                    }
                    return Ok(format!("{}.to_vec()", self.e(arg(a, 0)?)?));
                }
                if n == "print" {
                    return Ok(format!("println!(\"{{}}\", {})", self.e(arg(a, 0)?)?));
                }
                if n == "is_char_boundary" {
                    // G2 B2
                    let s0 = self.arr_ref(arg(a, 0)?)?;
                    let i0 = self.e(arg(a, 1)?)?;
                    return Ok(format!("pruv_str_boundary({}, {})", s0, i0));
                }
                if n == "substr" {
                    // G2 B2: argument evaluation order s -> lo -> hi
                    let s0 = self.arr_ref(arg(a, 0)?)?;
                    let lo = self.e(arg(a, 1)?)?;
                    let hi = self.e(arg(a, 2)?)?;
                    if !self.verified {
                        return Ok(format!("pruv_substr({}, {}, {})", s0, lo, hi));
                    }
                    return Ok(format!(
                        "{{ let pruv_s: &str = {}; let pruv_lo: i64 = {}; let pruv_hi: i64 = {}; ::std::string::String::from(unsafe {{ pruv_s.get_unchecked((pruv_lo as usize)..(pruv_hi as usize)) }}) }}",
                        s0, lo, hi
                    ));
                }
                let mut args: Vec<String> = Vec::new();
                for x in a {
                    if expr_ty(x).as_deref().map_or(false, |t| is_array_name(t) || t == "str") {
                        args.push(self.arr_ref(x)?);
                    } else {
                        args.push(self.e(x)?);
                    }
                }
                let mut name = n.to_string();
                if self.verified && self.has_req.contains(&name) {
                    name.push_str("__pruv_body"); // the caller proved the requires
                }
                Ok(format!("{}({})", name, args.join(", ")))
            }
            other => Err(format!("codegen: contract-only expression in code: {:?}", other)),
        }
    }
}

/// Pruv -> Rust source. Err is the str(e) at the place where Python raises an Exception.
pub fn gen_rust(prog: &Program, verified: bool, trust_callers: bool, budget: u64) -> Result<String, String> {
    if let Some(e) = crate::typeinfo::g2_unimplemented_error(prog, "codegen", None, &["array_u8", "array_bool", "str"], None) { // G2 B2
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
        // with trust_callers there is no check or budget
        let t = gen_rust(&p, true, true, 5).unwrap();
        assert!(!t.contains("pruv_budget") && t.contains("    f__pruv_body(x)\n"));
    }

    fn arr_prog(aty: &str) -> Program {
        let idx = Expr::Index(Index {
            line: 1,
            col: 1,
            array: Box::new(var("a", aty)),
            index: Box::new(int("0")),
            ty: Some("i64".into()),
        });
        let f = Function {
            line: 1,
            col: 1,
            name: "g".into(),
            params: vec![Param { name: "a".into(), ty: aty.into(), refine: None }],
            ret: "i64".into(),
            effects: vec![],
            requires: vec![],
            ensures: vec![],
            body: vec![Stmt::Return(Return { line: 1, col: 1, value: Some(idx) })],
            ret_refine: None,
        };
        Program { functions: vec![f], types: vec![], refined: false }
    }

    #[test]
    fn u8_prelude_only_when_used() {
        let u = gen_rust(&arr_prog("array_u8"), false, false, 1 << 30).unwrap();
        assert!(u.contains(SAFE_PRELUDE_U8));
        assert!(u.contains(&format!("{}\n{}", SAFE_PRELUDE, SAFE_PRELUDE_U8)));
        assert!(u.contains("pruv_get_u8(a, 0i64)"));
        let v = gen_rust(&arr_prog("array_u8"), true, false, 1 << 30).unwrap();
        assert!(!v.contains(SAFE_PRELUDE_U8));
        assert!(v.contains("((unsafe { *a.get_unchecked((0i64) as usize) }) as i64)"));
        let i = gen_rust(&arr_prog("array"), false, false, 1 << 30).unwrap();
        assert!(!i.contains(SAFE_PRELUDE_U8));
        assert!(i.contains("pruv_get(a, 0i64)"));
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
