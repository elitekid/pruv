//! Pruv -> Rust source generator (a port of codegen.py's constants, class Gen and gen_rust).
//! Goal: for the same program and mode (verified, trust_callers, budget), byte-identical to Python's gen_rust.
//! The functions at lines 128-272 (rty, cty, conv, emit_public_types, show, match_sorted_requires, rstr) use the ones in emit_common.
//! Rule: mutable state (temp number tmp, contract variable bound, cp dictionary) is changed in the same order as in Python.
//! Places where Python raises an Exception return Err(str(e)) (an AST printed with %r becomes {:?} — an unreachable path).

use crate::ast::*;
use crate::diagnostic::PruvError;
use crate::emit_common::{
    emit_public_types_with, is_spec_fn, is_user_key, key_name, make_type_table, match_sorted_requires, rstr, rty, rty_g,
    show, src_name, try_conv, try_conv_g, try_cty, try_cty_g,
};
use crate::foreign::{catalog_fn, is_catalog};
use crate::foreign_codegen::ForeignGen;
use crate::gtype::{is_g3_key, key_is_collection, mk_option, GType};
use crate::pyrepr::repr_str;
use crate::typeinfo::{array_elem_name, is_array_name, uses_array_type, uses_str, TypeTable};
use std::collections::{HashMap, HashSet};

pub type R<T> = Result<T, String>;

pub const ALLOW: &str = "#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]";

// ---------------------------------------------------------------------------
// G6 (docs/G6_SPEC.md section 12): extra attributes and preludes, emitted only for programs that use G6.
// ---------------------------------------------------------------------------

/// ALLOW without its closing `)]`, plus `unused_assignments, unused_comparisons`
pub const ALLOW_G6: &str = "#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]";

const UD_OLD: &str = r##"#[allow(dead_code)]
#[cold]
#[inline(never)]
fn pruv_ud(what: &str) -> ! { panic!("pruv: requires undefined: {}", what) }
"##;

// pruv_ud with a boundary context: a foreign helper sets the context (RAII guard), so that an undefined contract
// inside it reports `pruv: foreign contract undefined: NAME: what`; elsewhere the message is unchanged.
const UD_G6: &str = r##"::std::thread_local! { static PRUV_CTX: ::std::cell::Cell<&'static str> = ::std::cell::Cell::new(""); }
#[allow(dead_code)]
struct PruvCtx;
impl ::std::ops::Drop for PruvCtx { fn drop(&mut self) { PRUV_CTX.with(|c| c.set("")); } }
#[allow(dead_code)]
fn pruv_ctx(name: &'static str) -> PruvCtx { PRUV_CTX.with(|c| c.set(name)); PruvCtx }
#[allow(dead_code)]
#[cold]
#[inline(never)]
fn pruv_ud(what: &str) -> ! {
    let c: &'static str = PRUV_CTX.with(|c| c.get());
    if c.is_empty() { panic!("pruv: requires undefined: {}", what) } else { panic!("pruv: foreign contract undefined: {}: {}", c, what) }
}
"##;

/// CONTRACT_PRELUDE with `pruv_ud` replaced by the context-aware one (Python CONTRACT_PRELUDE_G6)
pub fn contract_prelude_g6() -> String {
    CONTRACT_PRELUDE.replace(UD_OLD, UD_G6)
}

pub const FILE_PRELUDE: &str = "struct pruv_File { file: ::std::option::Option<::std::fs::File>, ok: bool, readable: bool, writable: bool, buf: ::std::vec::Vec<u8> }\n";

pub const G6_PRELUDE: &str = r##"#[allow(dead_code)]
#[cold]
#[inline(never)]
fn pruv_g6_req(name: &str, what: &str) -> ! { panic!("pruv: foreign requires violated: {}: {}", name, what) }
#[allow(dead_code)]
#[cold]
#[inline(never)]
fn pruv_g6_ens(name: &str, what: &str) -> ! { panic!("pruv: foreign ensures violated: {}: {}", name, what) }
#[allow(dead_code)]
#[cold]
#[inline(never)]
fn pruv_g6_repr(what: &str) -> ! { panic!("pruv: invalid representation: {}", what) }
#[allow(dead_code)]
#[inline]
fn pruv_g6_charge(budget: &mut i64, n: usize) { let n: i64 = if n > (i64::MAX as usize) { i64::MAX } else { n as i64 }; *budget = budget.saturating_sub(n); if *budget < 0 { pruv_ud("budget") } }
"##;

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

// ---------------------------------------------------------------------------
// G9 A2: runtime contract helpers for `size` and for equality of extended (buffer-free recursive) values. They are emitted
// only when a runtime requires needs them (see Gen::g9_helper_texts) and share the entry's iteration budget.
// ---------------------------------------------------------------------------
const G9_TICK: &str = r##"#[allow(dead_code)]
#[inline]
fn pruv_g9_tick(pruv_budget: &mut i64) { *pruv_budget -= 1; if *pruv_budget < 0 { pruv_ud("contract iteration budget exceeded") } }
"##;
const G9_HELPER_ALLOW: &str =
    "#[allow(dead_code, non_camel_case_types, non_snake_case, unused_variables, unreachable_patterns)]";

/// names of the user types a field of type t can contribute to `size` / structural equality (Python `nominals_in`)
fn nominals_in(t: &GType) -> Vec<String> {
    if t.owner.is_none() && !t.args.is_empty() && (t.name == "option" || t.name == "result") {
        return nominals_in(&t.args[0]);
    }
    if t.is_user_type() {
        return vec![t.name.clone()];
    }
    Vec::new()
}

fn is_optres(t: &GType) -> bool {
    t.owner.is_none() && !t.args.is_empty() && (t.name == "option" || t.name == "result")
}

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

/// G3: the payload type of a structured Option<X> / Result<X> node type (`e.ty.args[0]` in Python), else None.
fn payload_type(ty: &Option<String>) -> Option<GType> {
    let t = ty.as_deref()?;
    if !is_g3_key(t) {
        return None;
    }
    let g = GType::try_from_key(t).ok()?;
    if g.owner.is_none() && !g.args.is_empty() {
        return Some(g.args[0].clone());
    }
    None
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

/// P2: bit builtin -> Rust operator (Python BIT_RUST, same order); later batches add entries. The contract helper
/// pruv_c<name> is emitted only when a contract uses the builtin.
const BIT_RUST: [(&str, &str); 7] = [
    ("band", "&"),
    ("bor", "|"),
    ("bxor", "^"),
    ("wrapping_shl", "<<"),
    ("ushr", ">>"),
    ("wrapping_add", "wrapping_add"),
    ("wrapping_mul", "wrapping_mul"),
];

/// P2 batch 3: wrapping arithmetic is an i64 method call instead of an operator (Python WRAP_RUST).
fn is_wrap_rust(n: &str) -> bool {
    n == "wrapping_add" || n == "wrapping_mul"
}

/// Python CONTRACT_WRAP_HELPER % (name, name, name)
fn contract_wrap_helper(n: &str) -> String {
    format!(
        "#[allow(dead_code)]\n#[inline]\nfn pruv_c{n}(a: i128, b: i128) -> i128 {{ if a < (i64::MIN as i128) || a > (i64::MAX as i128) || b < (i64::MIN as i128) || b > (i64::MAX as i128) {{ pruv_ud(\"argument outside i64 in {n}\") }} ((a as i64).{n}(b as i64)) as i128 }}\n",
        n = n
    )
}

fn bit_rust(n: &str) -> Option<&'static str> {
    BIT_RUST.iter().find(|(k, _)| *k == n).map(|(_, op)| *op)
}

/// P2 batch 4: Python CONTRACT_LOAD_HELPER (load_be in a runtime contract, included only when used)
const CONTRACT_LOAD_HELPER: &str = "#[allow(dead_code)]\n#[inline]\nfn pruv_cload_be(a: &[u8], i: i128, n: usize) -> i128 { if i < 0 || i > (a.len() as i128) - (n as i128) { pruv_ud(\"array index out of range\") } let mut w: u64 = 0; for k in 0..n { w = (w << 8) | (a[(i as usize) + k] as u64); } ((w as i64) as i128) }\n";

/// P2 batch 2: --no-verify helper name of a shift builtin (Python SHIFT_SAFE); None for the other bit builtins.
fn shift_safe(n: &str) -> Option<&'static str> {
    match n {
        "wrapping_shl" => Some("pruv_shl"),
        "ushr" => Some("pruv_ushr"),
        _ => None,
    }
}

/// Python SAFE_SHIFT_HELPER % (helper, op)
fn safe_shift_helper(helper: &str, op: &str) -> String {
    format!(
        "#[allow(dead_code)]\n#[inline]\nfn {helper}(a: i64, k: i64) -> i64 {{ if k < 0 || k >= 64 {{ pruv_ovf(\"shift count outside 0..64\") }} (((a) as u64) {op} ((k) as u32)) as i64 }}\n",
        helper = helper,
        op = op
    )
}

/// Python CONTRACT_SHIFT_HELPER % (name, name, name, op)
fn contract_shift_helper(n: &str, op: &str) -> String {
    format!(
        "#[allow(dead_code)]\n#[inline]\nfn pruv_c{n}(a: i128, b: i128) -> i128 {{ if a < (i64::MIN as i128) || a > (i64::MAX as i128) || b < (i64::MIN as i128) || b > (i64::MAX as i128) {{ pruv_ud(\"argument outside i64 in {n}\") }} if b < 0 || b >= 64 {{ pruv_ud(\"shift count outside 0..64 in {n}\") }} ((((a as i64) as u64) {op} (b as u32)) as i64) as i128 }}\n",
        n = n,
        op = op
    )
}

/// Python CONTRACT_BIT_HELPER % (name, name, op)
fn contract_bit_helper(n: &str, op: &str) -> String {
    format!(
        "#[allow(dead_code)]\n#[inline]\nfn pruv_c{n}(a: i128, b: i128) -> i128 {{ if a < (i64::MIN as i128) || a > (i64::MAX as i128) || b < (i64::MIN as i128) || b > (i64::MAX as i128) {{ pruv_ud(\"argument outside i64 in {n}\") }} ((a as i64) {op} (b as i64)) as i128 }}\n",
        n = n,
        op = op
    )
}

// ---------- helpers ----------

fn expr_ty(e: &Expr) -> &Option<String> {
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

/// G6: (K, V) of a `hashmap<K,V>` typed expression (Python `a.ty.args[0], a.ty.args[1]`)
fn map_type_args(e: &Expr) -> R<(GType, GType)> {
    let t = expr_ty(e).as_deref().ok_or_else(|| "'NoneType' object has no attribute 'args'".to_string())?;
    let g = GType::try_from_key(t)?;
    if g.args.len() < 2 {
        return Err("tuple index out of range".to_string());
    }
    Ok((g.args[0].clone(), g.args[1].clone()))
}

/// The IndexError of Python `a[i]`
fn arg(a: &[Expr], i: usize) -> R<&Expr> {
    a.get(i).ok_or_else(|| "list index out of range".to_string())
}

/// Python `format(n, "_")`: an underscore every three digits.
pub(crate) fn fmt_underscore(n: u64) -> String {
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
    storage: crate::storage::StoragePlan,
    function_name: String,
    budget: u64,
    verified: bool,
    trust: bool,
    out: Vec<String>,
    cost: bool,
    cost_used: bool,
    has_req: HashSet<String>,
    par_callees: HashSet<String>,
    par_hook: String,
    /// During the requires entry check: user-type parameters already converted -> type
    cp: Option<HashMap<String, String>>,
    /// Quantifier variables in scope (contract evaluation)
    bound: Vec<String>,
    tmp: u64,
    table: TypeTable,
    params: HashSet<String>,
    /// G5 A2: inout parameters of the function being generated (`&mut [T]` bindings)
    inouts: HashSet<String>,
    /// G5 A2: the inout code paths only run for a program that uses inout (unchecked program: assume it may)
    g5: bool,
    /// G5 A2 (legacy mode): a function with an inout parameter has an always-checked private wrapper, also under
    /// trust_callers, so its contract prelude is needed there too
    inout_req: bool,
    /// Variable type table (parameters and let; copied and restored per block)
    vars: HashMap<String, String>,
    /// G6: the program uses G6 (a foreign declaration, a collection, take or move)
    g6: bool,
    g10: bool,
    /// the attribute of every emitted function (ALLOW, or ALLOW_G6 for a G6 program)
    allow: &'static str,
    /// function name -> declaration (first one wins)
    fmap: HashMap<String, &'a Function>,
    /// collection parameters of the current function that are borrowed (not `take`)
    borrowed: HashSet<String>,
    /// boundary helpers and manifest data (only for a G6 program)
    fg: Option<ForeignGen>,
    /// G9 A2: the program carries G9 metadata
    g9: bool,
    /// G9 A2: extended declaration names (Clone, never Copy)
    ext: HashSet<String>,
    /// G9 A2: boxed field labels ("Struct.field" / "Enum::Variant.field")
    boxed: HashSet<String>,
    /// G9 A2: names bound to a Rust reference (extended parameters, match payload views, buffer payload views)
    refs: HashSet<String>,
    /// owned extended locals the current return statement may move (return_movable)
    moving: HashSet<String>,
    /// names borrowed as the scrutinee of an enclosing match_ext arm
    pinned: HashSet<String>,
    /// enclosing blocks being emitted: (names declared so far, names named later, loop body)
    frames: Vec<(HashSet<String>, HashSet<String>, bool)>,
    /// G9 A2: types whose runtime contract helpers (size / equality) are needed
    need_size: HashSet<String>,
    need_eq: HashSet<String>,
    /// P2: band/bor/bxor used in a runtime contract (filled while contracts are generated)
    need_bits: HashSet<String>,
    /// P2 batch 2: shifts used in code under --no-verify (pruv_shl / pruv_ushr helpers)
    need_shift: HashSet<String>,
    /// P2 batch 4: load_be used in a runtime contract (pruv_cload_be helper)
    need_load_be: bool,
    /// G9 A2: the diagnostic raised by g9_unsupported (the R error is only a marker)
    diag: Option<PruvError>,
    /// G4 A2 (explicit visibility mode, docs/G4_SPEC.md 4): only host entries are `pub`. Verified: just the entries that have
    /// a requires get a checked wrapper (host boundary; none under trust_callers) and every Pruv call goes to the body. Safe
    /// mode (--no-verify): EVERY function with a requires has a checked wrapper and every Pruv call goes through it; under
    /// trust_callers the entry's pub wrapper skips the checks and an extra private checked wrapper `<entry>__pruv_chk`
    /// serves the Pruv callers.
    explicit: bool,
    /// G4 A2: the host entries (Rust names)
    entries: HashSet<String>,
    /// G4 A2: some function needs the runtime contract helpers (explicit mode)
    checks_needed: bool,
    /// G4 A2: function name -> its explicit-mode attributes (empty outside explicit mode)
    fmarks: HashMap<String, &'a FnMark>,
}

impl<'a> Gen<'a> {
    fn new(prog: &'a Program, verified: bool, trust_callers: bool, budget: u64, foreign_checks: &str) -> Gen<'a> {
        fn collect_par(stmts: &[Stmt], names: &mut HashSet<String>) {
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
        let mut par_callees = HashSet::new();
        for f in &prog.functions { collect_par(&f.body, &mut par_callees); }
        let g6 = crate::foreign::first_g6_use(prog).is_some();
        let mut fmap: HashMap<String, &'a Function> = HashMap::new();
        for f in &prog.functions {
            fmap.entry(f.name.clone()).or_insert(f);
        }
        let explicit = prog.explicit.is_some();
        let mut fmarks: HashMap<String, &'a FnMark> = HashMap::new();
        if let Some(x) = &prog.explicit {
            for (f, m) in prog.functions.iter().zip(x.fns.iter()) {
                fmarks.entry(f.name.clone()).or_insert(m);
            }
        }
        let is_host = |f: &Function| fmarks.get(&f.name).map_or(false, |m| m.host_entry);
        let entries: HashSet<String> = prog.functions.iter().filter(|f| is_host(*f)).map(|f| f.name.clone()).collect();
        let checks_needed = explicit
            && prog.functions.iter().any(|f| {
                !f.requires.is_empty() && f.foreign.is_none() && (!verified || (is_host(f) && !trust_callers))
            });
        Gen {
            storage: crate::storage::plan_storage(prog, verified),
            function_name: String::new(),
            prog,
            explicit,
            entries,
            checks_needed,
            fmarks,
            budget,
            verified,
            trust: trust_callers,
            out: Vec::new(),
            cost: false,
            cost_used: !verified && prog.functions.iter().any(|f| f.cost.is_some()),
            par_callees,
            par_hook: std::env::var("PRUV_G7_TEST_HOOK").unwrap_or_default(),
            has_req: prog
                .functions
                .iter()
                .filter(|f| !f.requires.is_empty() && f.foreign.is_none())
                .map(|f| f.name.clone())
                .collect(),
            cp: None,
            bound: Vec::new(),
            tmp: 0,
            table: make_type_table(prog),
            params: HashSet::new(),
            inouts: HashSet::new(),
            g5: prog.uses_inout != Some(false),
            inout_req: prog.uses_inout != Some(false)
                && !explicit
                && prog.functions.iter().any(|f| {
                    !f.requires.is_empty() && f.foreign.is_none() && f.params.iter().any(|p| p.mode_pos.is_some())
                }),
            vars: HashMap::new(),
            g6,
            g10: crate::foreign::uses_files(prog),
            allow: if g6 { ALLOW_G6 } else { ALLOW },
            fmap,
            borrowed: HashSet::new(),
            fg: if g6 { Some(ForeignGen::new(foreign_checks, budget)) } else { None },
            g9: prog.g9.is_some(),
            ext: prog.g9.as_ref().map(|m| m.extended.iter().cloned().collect()).unwrap_or_default(),
            boxed: prog.g9.as_ref().map(|m| m.boxed.iter().cloned().collect()).unwrap_or_default(),
            refs: HashSet::new(),
            moving: HashSet::new(),
            pinned: HashSet::new(),
            frames: Vec::new(),
            need_size: HashSet::new(),
            need_eq: HashSet::new(),
            need_bits: HashSet::new(),
            need_shift: HashSet::new(),
            need_load_be: false,
            diag: None,
        }
    }

    /// G9: some struct field / enum payload has the internal type `name` (array_u8, array_bool, str)
    fn field_uses(&self, name: &str) -> bool {
        self.prog.types.iter().any(|d| d.all_fields().iter().any(|f| f.ty == name))
    }

    /// t is an extended user type (G9): recursive, or holding a buffer or an extended type
    fn is_ext(&self, t: Option<&str>) -> bool {
        !self.ext.is_empty() && t.map_or(false, |t| !is_g3_key(t) && self.ext.contains(t))
    }

    /// rty, except that an extended parameter is a shared reference `&Name` (read view)
    fn rt(&self, t: &str, param: bool) -> String {
        if param && self.is_ext(Some(t)) {
            return format!("&{}", t);
        }
        rty(t, param)
    }

    fn layout(&self, e: &Expr) -> &'static str {
        let width = self.storage.layout_of(e);
        if width == "i64" && !self.storage.contains_node(e) {
            if let Expr::Var(v) = e { return self.storage.parameter(&self.function_name, &v.name); }
        }
        width
    }
    fn rt_width(&self, t: &str, param: bool, width: &str) -> String {
        if t == "array" && width != "i64" {
            return if param { format!("&[{}]", width) } else { format!("::std::vec::Vec<{}>", width) };
        }
        self.rt(t, param)
    }

    /// G9: the diagnostic of a runtime requires the Rust backend cannot lower; the returned String is only a marker
    fn g9_unsupported(&mut self, e: &Expr, what: &str) -> String {
        self.diag = Some(PruvError::new(
            "codegen",
            crate::diagnostic::plain_line(e.line()), // Python raises this without `file`
            e.col(),
            "unsupported_type",
            format!("{} is not supported in a runtime requires by the Rust backend yet", what),
            "compare tags with is_variant and fields with variant_field, or move the check into the body",
        ));
        "G9 unsupported runtime requires".to_string()
    }

    /// the LAST field of the assignment path root.f1.f2... is a Box edge (follows the declared field types)
    fn path_boxed(&self, root: &str, fields: &[String]) -> bool {
        let mut cur: Option<String> = self.vars.get(root).cloned();
        let mut boxed = false;
        for fname in fields {
            let c = match &cur {
                Some(c) if !is_g3_key(c) => c.clone(),
                _ => return false,
            };
            let decl = match self.table.decl(&c) {
                Some(d) => d,
                None => return false,
            };
            let sd = match decl {
                TypeDecl::Struct(s) => s,
                TypeDecl::Enum(_) => return false,
            };
            boxed = self.boxed.contains(&format!("{}.{}", c, fname));
            let mut nxt: Option<String> = None;
            for fd in &sd.fields {
                if fd.name == *fname {
                    nxt = Some(fd.ty.clone());
                }
            }
            cur = nxt;
        }
        boxed
    }

    /// the field `field` of the struct type base_ty is a Box edge
    fn field_boxed(&self, base_ty: &Option<String>, field: &str) -> bool {
        !self.boxed.is_empty()
            && base_ty.as_deref().map_or(false, |t| self.boxed.contains(&format!("{}.{}", key_name(t), field)))
    }

    fn fg_mut(&mut self) -> R<&mut ForeignGen> {
        self.fg.as_mut().ok_or_else(|| "codegen: foreign helper requested outside a G6 program".to_string())
    }

    /// G3 specializations, G6 collection-bearing functions and (G9) functions with an extended type in their signature
    /// are private Rust items (this includes their checked entry wrappers)
    fn private(&self, f: &Function) -> bool {
        is_spec_fn(&f.name)
            || f.params.iter().any(|p| key_is_collection(&p.ty))
            || key_is_collection(&f.ret)
            || f.params.iter().any(|p| self.is_ext(Some(&p.ty)))
            || self.is_ext(Some(&f.ret))
            || (self.g5 && f.params.iter().any(|p| p.mode_pos.is_some())) // G5: no public API for a mutable borrow
    }

    fn emit(&mut self, ind: usize, line: &str) {
        self.out.push(format!("{}{}", "    ".repeat(ind), line));
    }

    fn prelude(&mut self) -> R<()> {
        if self.g10 {
            self.out.push(FILE_PRELUDE.to_string());
        }
        let types = emit_public_types_with(self.prog, &self.table);
        if !types.is_empty() {
            self.out.push(types);
        }
        let mut u8_used = uses_array_type(self.prog, "array_u8") || self.g10;
        let mut bool_used = uses_array_type(self.prog, "array_bool"); // G2 A5
        let mut str_used = uses_str(self.prog, !self.verified); // G2 B2; S5: an erased cost bound emits nothing
        if self.g9 {
            // G9: the G2 helpers are emitted by usage; uses_array_type / uses_str look at parameters, results and lets only
            u8_used = u8_used || self.field_uses("array_u8");
            bool_used = bool_used || self.field_uses("array_bool");
            str_used = str_used || self.field_uses("str");
        }
        if self.g6 && !str_used {
            // G6: a String parameter can be indexed in a runtime requires (pruv_cidx_str)
            str_used = uses_array_type(self.prog, "string");
        }
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
        let checks = if self.explicit {
            self.checks_needed
        } else {
            !self.has_req.is_empty() && (!self.trust || self.inout_req || (!self.par_callees.is_empty() && !self.verified))
        };
        if checks || self.g6 || self.cost_used {
            if self.g6 {
                self.out.push(contract_prelude_g6());
            } else {
                self.out.push(CONTRACT_PRELUDE.to_string());
            }
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
            if self.g6 {
                self.out.push(G6_PRELUDE.to_string());
            }
        }
        Ok(())
    }

    /// The pruv_contract__Name mirror type and the pruv_to_c__Name converter (for requires evaluation only)
    fn contract_types(&self) -> R<String> {
        let attrs = "#[allow(dead_code, non_camel_case_types, non_snake_case, unused_variables)]";
        let mut out: Vec<String> = Vec::new();
        for d in self.table.ordered() {
            if self.ext.contains(d.name()) {
                continue; // G9: extended values have no i128 mirror; contracts read them through references (cx)
            }
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
        self.function_name = f.name.clone();
        if f.foreign.is_some() {
            return Ok(()); // G6: a trusted rust fn has no body; its boundary helper is emitted on first use
        }
        self.params = f.params.iter().map(|p| p.name.clone()).collect();
        if self.g5 {
            self.inouts = f.params.iter().filter(|p| p.mode_pos.is_some()).map(|p| p.name.clone()).collect();
        }
        self.vars = f.params.iter().map(|p| (p.name.clone(), p.ty.clone())).collect();
        self.borrowed =
            f.params.iter().filter(|p| key_is_collection(&p.ty) && !p.take).map(|p| p.name.clone()).collect();
        self.refs = f.params.iter().filter(|p| self.is_ext(Some(&p.ty))).map(|p| p.name.clone()).collect();
        let ps = join_map(&f.params, ", ", |p| {
            if p.mode_pos.is_some() {
                // G5 A2: an inout parameter is a mutable slice borrow (`&mut [T]`)
                format!("{}: &mut {}", p.name, &rty(&p.ty, true)[1..])
            } else {
                format!("{}: {}", p.name, self.rt_width(&p.ty, !p.take, self.storage.layout_of(p)))
            }
        });
        let ret = if f.ret == "unit" { String::new() } else { format!(" -> {}", self.rt_width(&f.ret, false, self.storage.layout_of(f))) };
        let has = !f.requires.is_empty();
        let body_name = if has { format!("{}__pruv_body", f.name) } else { f.name.clone() };
        // G3: generic specializations (and G6 collection-bearing functions) are private items; G4 A2: only host entries
        // without a checked wrapper are `pub`
        let host = self.entries.contains(&f.name);
        let vis = if self.explicit {
            if host && !has { "pub " } else { "" }
        } else if has || self.private(f) {
            ""
        } else {
            "pub "
        };
        let allow = self.allow;
        self.emit(0, allow);
        self.emit(0, &format!("{}fn {}({}){} {{", vis, body_name, ps, ret));
        self.cost = !self.verified && f.cost.is_some();
        if self.cost {
            let args = join_map(&f.params, ", ", |p| p.name.clone());
            self.emit(1, &format!("let pruv_cost: i128 = {}__pruv_cost({});", f.name, args));
            self.emit(1, "let mut pruv_spent: u128 = 0;");
        }
        self.block(&f.body, 1)?;
        if self.cost && f.ret == "unit" {
            self.emit(1, Self::cost_check());
        }
        self.emit(0, "}");
        self.emit(0, "");
        if self.cost {
            let cps = join_map(&f.params, ", ", |p| format!("{}: {}", p.name, self.rt(&p.ty, true)));
            self.emit(0, allow);
            self.emit(0, &format!("fn {}__pruv_cost({}) -> i128 {{", f.name, cps));
            // The bound is evaluated only inside the callee's requires (spec 5: requires before contract_domain).
            let (conversions, checks) =
                if !f.requires.is_empty() && !self.trust { self.req_checks(f)? } else { (Vec::new(), Vec::new()) };
            for line in &conversions {
                self.emit(1, line);
            }
            self.emit(1, &format!("let mut pruv_budget: i64 = {};", fmt_underscore(self.budget)));
            for line in &checks {
                self.emit(1, line);
            }
            let code = self.c(f.cost.as_ref().unwrap())?;
            self.emit(1, &code);
            self.emit(0, "}");
            self.emit(0, "");
        }
        if has {
            if !self.explicit {
                // G5: a wrapper of an inout function always checks (trust_callers does not waive it)
                let chk = if self.inouts.is_empty() { None } else { Some(true) };
                self.entry(f, &ps, &ret, &body_name, None, None, chk)?;
                if !self.verified && self.trust && self.inouts.is_empty() && self.par_callees.contains(&f.name) {
                    let name = format!("{}__pruv_par_chk", f.name);
                    self.entry(f, &ps, &ret, &body_name, Some(&name), Some(false), Some(true))?;
                }
            } else if self.verified {
                if host {
                    // the checked host wrapper; no other function has a wrapper in verified mode
                    let checked = !self.trust;
                    self.entry(f, &ps, &ret, &body_name, Some(f.name.as_str()), Some(true), Some(checked))?;
                }
            } else if host {
                let checked = !self.trust;
                self.entry(f, &ps, &ret, &body_name, Some(f.name.as_str()), Some(true), Some(checked))?;
                if self.trust {
                    // Pruv callers of the entry keep the safe-mode check
                    let chk = format!("{}__pruv_chk", f.name);
                    self.entry(f, &ps, &ret, &body_name, Some(chk.as_str()), Some(false), Some(true))?;
                }
            } else {
                self.entry(f, &ps, &ret, &body_name, Some(f.name.as_str()), Some(false), Some(true))?;
            }
        }
        Ok(())
    }

    fn cost_add(units: &str) -> String {
        format!("pruv_spent = pruv_spent.checked_add({}).unwrap_or_else(|| panic!(\"pruv: cost exceeded\"));", units)
    }

    fn cost_check() -> &'static str {
        "if pruv_cost < 0 || pruv_spent > pruv_cost as u128 { panic!(\"pruv: cost exceeded\"); }"
    }

    fn cost_call(name: &str, args: &[String]) -> String {
        format!("let pruv_units = {}__pruv_cost({}); if pruv_units < 0 {{ panic!(\"pruv: cost exceeded\"); }} {}",
            name, args.join(", "), Self::cost_add("(pruv_units as u128).checked_add(1).unwrap_or_else(|| panic!(\"pruv: cost exceeded\"))"))
    }

    fn cost_buffer(&self, result: String) -> String {
        if self.cost {
            format!("{{ let pruv_buffer = {}; {} pruv_buffer }}", result,
                Self::cost_add("(pruv_buffer.len() as u128).checked_add(1).unwrap_or_else(|| panic!(\"pruv: cost exceeded\"))"))
        } else {
            result
        }
    }

    /// the source-qualified name of a function (explicit mode: its identity; otherwise the name itself)
    fn disp_of(&self, name: &str) -> String {
        match self.fmarks.get(name) {
            Some(m) => m.disp.clone(),
            None => name.to_string(),
        }
    }

    /// explicit mode: the Rust name a Pruv call of the function `n` invokes (see Gen::new)
    fn callee(&self, n: &str) -> String {
        if !self.has_req.contains(n) {
            return n.to_string();
        }
        if self.verified {
            return format!("{}__pruv_body", n); // the caller proved requires
        }
        if self.trust && self.entries.contains(n) {
            format!("{}__pruv_chk", n)
        } else {
            n.to_string()
        }
    }

    /// Code of the requires checks (fills cp)
    fn entry_checks(&mut self, f: &Function) -> R<Vec<String>> {
        let mut checks: Vec<String> = Vec::new();
        let disp = self.disp_of(&f.name);
        for r in &f.requires {
            let msg = format!("pruv: requires violated: {}: {}", disp, show(r));
            let code = self.c(r)?;
            checks.push(format!("if !({}) {{ panic!(\"{{}}\", {}); }}", code, rstr(&msg)));
        }
        Ok(checks)
    }

    /// (parameter conversion lines, requires check lines) of f's runtime requires
    fn req_checks(&mut self, f: &Function) -> R<(Vec<String>, Vec<String>)> {
        self.cp = Some(HashMap::new());
        let res = self.entry_checks(f);
        let used = self.cp.take().unwrap_or_default();
        let checks = res?;
        let mut conversions = Vec::new();
        for p in &f.params {
            if let Some(ty) = used.get(&p.name) {
                conversions.push(format!("let pruv_cp_{}: {} = {};", p.name, try_cty(ty)?, try_conv(ty, &p.name)?));
            }
        }
        Ok((conversions, checks))
    }

    /// the checked wrapper of f. Legacy (`None` arguments): `pub` unless private, named f.name, checks unless trust_callers.
    /// Explicit mode passes the wrapper name, its visibility and whether it checks.
    #[allow(clippy::too_many_arguments)]
    fn entry(
        &mut self,
        f: &Function,
        ps: &str,
        ret: &str,
        body_name: &str,
        name: Option<&str>,
        is_pub: Option<bool>,
        checked: Option<bool>,
    ) -> R<()> {
        let name = name.unwrap_or(f.name.as_str());
        let is_pub = is_pub.unwrap_or_else(|| !self.private(f));
        let checked = checked.unwrap_or(!self.trust);
        let allow = self.allow;
        self.emit(0, allow);
        self.emit(0, "#[inline]");
        let vis = if is_pub { "pub " } else { "" };
        self.emit(0, &format!("{}fn {}({}){} {{", vis, name, ps, ret));
        if checked {
            let (conversions, checks) = self.req_checks(f)?;
            for line in &conversions {
                self.emit(1, line);
            }
            if !checks.is_empty() {
                let line = format!("let mut pruv_budget: i64 = {};", fmt_underscore(self.budget));
                self.emit(1, &line);
            }
            for line in &checks {
                self.emit(1, line);
            }
        }
        let args = join_map(&f.params, ", ", |p| {
            if p.mode_pos.is_some() { format!("&mut *{}", p.name) } else { p.name.clone() }
        });
        self.emit(1, &format!("{}({})", body_name, args));
        self.emit(0, "}");
        self.emit(0, "");
        Ok(())
    }

    // ---------- contract (requires) evaluation, i128 ----------

    fn carr(&mut self, e: &Expr) -> R<String> {
        match e {
            Expr::Var(x) => Ok(x.name.clone()),
            Expr::StrLit(x) => Ok(lit_str(&x.value)), // G2 B2
            // G9: a buffer field of a real (extended) value
            Expr::FieldAccess(_) | Expr::VariantField(_) if self.g9 => self.cx(e),
            other => Err(format!("codegen: unsupported array expression in contract: {:?}", other)),
        }
    }

    // ---------- G9: contract operands over REAL values ----------

    /// Rust expression of type `&R(T)` for a contract operand of nominal or buffer type, evaluated on the REAL parameter
    /// values (Python `cx`). Supported: a parameter, a field path, variant_field and nullary constructors.
    fn cx(&mut self, e: &Expr) -> R<String> {
        match e {
            Expr::Var(x) => {
                if self.bound.iter().any(|b| b == &x.name) || !self.params.contains(&x.name) {
                    return Err(self.g9_unsupported(e, &format!("the variable {} as an aggregate operand", x.name)));
                }
                if self.is_ext(x.ty.as_deref()) {
                    Ok(x.name.clone())
                } else {
                    Ok(format!("(&{})", x.name))
                }
            }
            Expr::FieldAccess(x) => {
                let deref = if self.field_boxed(expr_ty(&x.base), &x.field) { "*" } else { "" };
                let base = self.cx(&x.base)?;
                Ok(format!("(&{}({}).{})", deref, base, x.field))
            }
            Expr::VariantField(x) => {
                if g9_owned(&x.value) {
                    // the selected value is a fresh constructor (or a part of one): select from the OWNED temporary and
                    // borrow the moved-out field, so no reference into a block-local temporary escapes its block
                    return Ok(format!("(&{})", self.g9_owned_expr(e)?));
                }
                self.tmp += 1;
                let tmp = format!("pruv_e{}", self.tmp);
                let nfields = k_variant(&self.table, &x.enum_name, &x.variant)?.fields.len();
                let idx = k_field_index(&self.table, &x.enum_name, &x.field, Some(&x.variant))?;
                let fty = k_variant(&self.table, &x.enum_name, &x.variant)?.fields[idx].ty.clone();
                let pats = (0..nfields).map(|i| if i == idx { "pruv_f" } else { "_" }).collect::<Vec<_>>().join(", ");
                let msg = format!(
                    "variant_field expected {}::{}.{}",
                    src_name(&x.enum_name),
                    x.variant,
                    x.field
                );
                let val = self.cx(&x.value)?;
                Ok(format!(
                    "({{ let {tmp}: &{en} = {val}; match {tmp} {{ {en}::{v}({pats}) => {{ let pruv_r: &{rt} = pruv_f; pruv_r }} _ => pruv_ud({m}) }} }})",
                    tmp = tmp,
                    en = x.enum_name,
                    val = val,
                    v = x.variant,
                    pats = pats,
                    rt = rty(&fty, false),
                    m = rstr(&msg)
                ))
            }
            // a constructor (with or without payload) is a REAL temporary value of the type; a reference to it lives
            // through the enclosing statement. Every i64 field is converted from the i128 contract value (checked).
            Expr::EnumCtor(_) | Expr::StructLit(_) => Ok(format!("(&{})", self.g9_real(e, None)?)),
            _ => Err(self.g9_unsupported(e, "this expression as an aggregate operand")),
        }
    }

    /// OWNED Rust value of `e` (g9_owned(e)): a constructor is built (g9_real); a part is moved out of the owned value of
    /// its base (a Box edge is unboxed). Python `g9_owned_expr`.
    fn g9_owned_expr(&mut self, e: &Expr) -> R<String> {
        match e {
            Expr::EnumCtor(_) | Expr::StructLit(_) => self.g9_real(e, None),
            Expr::FieldAccess(x) => {
                let deref = if self.field_boxed(expr_ty(&x.base), &x.field) { "*" } else { "" };
                let base = self.g9_owned_expr(&x.base)?;
                Ok(format!("({}({}).{})", deref, base, x.field))
            }
            Expr::VariantField(x) => {
                let nfields = k_variant(&self.table, &x.enum_name, &x.variant)?.fields.len();
                let idx = k_field_index(&self.table, &x.enum_name, &x.field, Some(&x.variant))?;
                let pats = (0..nfields).map(|i| if i == idx { "pruv_f" } else { "_" }).collect::<Vec<_>>().join(", ");
                let boxed = self.boxed.contains(&format!("{}::{}.{}", x.enum_name, x.variant, x.field));
                let msg = format!("variant_field expected {}::{}.{}", src_name(&x.enum_name), x.variant, x.field);
                let val = self.g9_owned_expr(&x.value)?;
                Ok(format!(
                    "(match {} {{ {}::{}({}) => {}, _ => pruv_ud({}) }})",
                    val,
                    x.enum_name,
                    x.variant,
                    pats,
                    if boxed { "*pruv_f" } else { "pruv_f" },
                    rstr(&msg)
                ))
            }
            _ => Err(self.g9_unsupported(e, "this expression as an aggregate operand")),
        }
    }

    /// a constructor field of declared type `ty`: the real value, boxed on a recursive edge (Python `g9_field_real`)
    fn g9_field_real(&mut self, x: &Expr, ty: &str, label: &str) -> R<String> {
        let v = self.g9_real(x, Some(ty))?;
        Ok(if self.boxed.contains(label) { format!("::std::boxed::Box::new({})", v) } else { v })
    }

    /// Rust expression of the REAL (executed representation) OWNED value of the contract expression `e` (declared type
    /// `ty`, default the type of e); Python `g9_real`.
    fn g9_real(&mut self, e: &Expr, ty: Option<&str>) -> R<String> {
        match e {
            Expr::StructLit(x) => {
                let fs: Vec<FieldDecl> = k_fields(&self.table, &x.name, None)?.to_vec();
                if fs.is_empty() {
                    return Ok(format!("{} {{}}", x.name));
                }
                let vals = init_map(&x.fields);
                let mut parts: Vec<String> = Vec::new();
                for f in &fs {
                    let v = init_value(&vals, &f.name)?;
                    let fv = self.g9_field_real(v, &f.ty, &format!("{}.{}", x.name, f.name))?;
                    parts.push(format!("{}: {}", f.name, fv));
                }
                return Ok(format!("{} {{ {} }}", x.name, parts.join(", ")));
            }
            Expr::EnumCtor(x) => {
                let ctor = format!("{}::{}", x.enum_name, x.variant);
                if x.args.is_empty() {
                    return Ok(ctor);
                }
                let vf: Vec<FieldDecl> = k_variant(&self.table, &x.enum_name, &x.variant)?.fields.to_vec();
                let mut parts: Vec<String> = Vec::new();
                for (a, fd) in x.args.iter().zip(vf.iter()) {
                    parts.push(self.g9_field_real(a, &fd.ty, &format!("{}::{}.{}", x.enum_name, x.variant, fd.name))?);
                }
                return Ok(format!("{}({})", ctor, parts.join(", ")));
            }
            _ => {}
        }
        let t: Option<String> = match ty {
            Some(s) => Some(s.to_string()),
            None => expr_ty(e).clone(),
        };
        if let Expr::Ctor(x) = e {
            let px: String = payload_type(&t).map(|g| g.to_key()).unwrap_or_else(|| "i64".to_string());
            let rx = rty(&px, false);
            if x.name == "None" {
                return Ok(format!("None::<{}>", rx));
            }
            let a = match &x.arg {
                Some(a) => a,
                None => return Err("codegen: unsupported expression in requires: None".to_string()),
            };
            if x.name == "Some" {
                return Ok(format!("Some::<{}>({})", rx, self.g9_real(a, Some(&px))?));
            }
            let at = if x.name == "Ok" { px.clone() } else { "i64".to_string() };
            return Ok(format!("{}::<{}, i64>({})", x.name, rx, self.g9_real(a, Some(&at))?));
        }
        let tk: Option<&str> = t.as_deref();
        if tk.is_none() || tk == Some("i64") {
            return Ok(format!(
                "i64::try_from({}).unwrap_or_else(|_| pruv_ud(\"constructor field out of i64 range\"))",
                self.c(e)?
            ));
        }
        let tk = tk.unwrap_or("i64");
        if tk == "bool" {
            return self.c(e);
        }
        if matches!(e, Expr::Var(_) | Expr::FieldAccess(_) | Expr::VariantField(_))
            && (is_user_key(tk) || key_name(tk) == "option" || key_name(tk) == "result")
        {
            if is_user_key(tk) && self.table.holds_buffer(tk) {
                return Err(self.g9_unsupported(e, "a copy of a value holding an array or str"));
            }
            // a copy of a named value / part is charged first: its weight (one unit per nominal node)
            let g = GType::from_key(tk);
            let w = self.g9_weight(&g, "pruv_c", "&mut pruv_budget");
            if w == "0i128" {
                return Ok(format!("::std::clone::Clone::clone({})", self.cx(e)?));
            }
            for n in nominals_in(&g) {
                self.need_size.insert(n);
            }
            let r = self.cx(e)?;
            return Ok(format!(
                "({{ let pruv_c: &{} = {}; let _ = {}; ::std::clone::Clone::clone(pruv_c) }})",
                rty(tk, false),
                r,
                w
            ));
        }
        if is_array_name(tk) {
            let a = self.carr(e)?;
            // the buffer expression is evaluated once: bound, charged by its length, then copied
            return Ok(format!("({{ let pruv_b: &[_] = {}; {} pruv_b.to_vec() }})", a, g9_charge("pruv_b.len()")));
        }
        if tk == "str" {
            let a = self.carr(e)?;
            return Ok(format!("({{ let pruv_b: &str = {}; {} pruv_b.to_owned() }})", a, g9_charge("pruv_b.len()")));
        }
        Err(self.g9_unsupported(e, "this expression as a constructor field of an aggregate operand"))
    }

    /// `e` reads a part of a REAL (extended) value through references (cx): a variant_field of an extended value, or a
    /// field path below one (Python `g9_real_path`)
    fn g9_real_path(&self, e: &Expr) -> bool {
        match e {
            Expr::VariantField(x) => self.is_ext(expr_ty(&x.value).as_deref()) || self.g9_real_path(&x.value),
            Expr::FieldAccess(x) => self.is_ext(expr_ty(&x.base).as_deref()) || self.g9_real_path(&x.base),
            _ => false,
        }
    }

    /// contract value of type `ty` from `reference` (a Rust expression of type `&R(ty)`). A value holding nominal parts is
    /// converted whole, so the conversion is charged to the shared budget first: one unit per nominal node visited
    /// (Python `g9_metered`).
    fn g9_metered(&mut self, ty: &str, reference: &str) -> R<String> {
        let g = GType::from_key(ty);
        let noms = nominals_in(&g);
        if noms.is_empty() {
            return try_conv(ty, &format!("(*{})", reference));
        }
        for n in noms {
            self.need_size.insert(n);
        }
        let w = self.g9_weight(&g, "pruv_m", "&mut pruv_budget");
        Ok(format!(
            "({{ let pruv_m: &{} = {}; let _ = {}; {} }})",
            rty(ty, false),
            reference,
            w,
            try_conv(ty, "(*pruv_m)")?
        ))
    }

    fn c(&mut self, e: &Expr) -> R<String> {
        match e {
            Expr::Spent(_) => Err("cost_unavailable: Stage 5 cost verification is not implemented yet".into()),
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
                if self.is_ext(x.ty.as_deref()) {
                    // G9: an extended value is only an operand of size / == / is_variant / field access
                    return Err(self.g9_unsupported(e, &format!("the extended value {} as a plain operand", x.name)));
                }
                if let Some(ty) = &x.ty {
                    if self.cp.is_some() && is_user_key(ty) && self.params.contains(&x.name) {
                        if let Some(cp) = self.cp.as_mut() {
                            cp.insert(x.name.clone(), ty.clone());
                        }
                        return Ok(format!("pruv_cp_{}", x.name));
                    }
                }
                let t = x.ty.as_deref().unwrap_or("i64");
                let tn = key_name(t);
                if tn == "i64" || tn == "option" || tn == "result" || is_user_key(t) {
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
                if (op == "==" || op == "!=") && self.is_ext(expr_ty(&x.left).as_deref()) {
                    // G9: structural equality of buffer-free extended aggregates, visited lazily on the real values;
                    // every visited node pair costs one budget unit; only the active variant's fields are compared
                    let tn = key_name(expr_ty(&x.left).as_deref().unwrap_or("")).to_string();
                    self.need_eq.insert(tn.clone());
                    let l = self.cx(&x.left)?;
                    let r = self.cx(&x.right)?;
                    let code = format!("pruv_ceq__{}({}, {}, &mut pruv_budget)", tn, l, r);
                    return Ok(if op == "==" { code } else { format!("(!{})", code) });
                }
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
                let aty = expr_ty(&x.array).as_deref();
                if aty.map_or(false, |t| key_name(t) == "vec") {
                    // G6: checked read of a vector element
                    let et = x.ty.as_deref().ok_or_else(|| "codegen: vector index without a type".to_string())?;
                    return Ok(format!(
                        "({{ let pruv_i: i128 = {}; if pruv_i >= 0 && pruv_i < ({}.len() as i128) {{ let pruv_x: {} = {}[pruv_i as usize]; {} }} else {{ pruv_ud(\"vector index out of range\") }} }})",
                        i,
                        a,
                        rty(et, false),
                        a,
                        try_conv(et, "pruv_x")?
                    ));
                }
                if aty == Some("string") {
                    // G6
                    return Ok(format!("pruv_cidx_str(&{}, {})", a, i));
                }
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
                if self.layout(&x.array) != "i64" {
                    return Ok(format!("{{ let pruv_a = {}; let pruv_i: i128 = {}; if pruv_i >= 0 && pruv_i < pruv_a.len() as i128 {{ pruv_a[pruv_i as usize] as i128 }} else {{ pruv_ud(\"array index out of range\") }} }}", a, i));
                }
                Ok(format!("pruv_cidx({}, {})", a, i))
            }
            Expr::Ctor(x) => {
                // G3: Option<X> / Result<X> with X != i64 carry an explicit payload type
                if let Some(g) = payload_type(&x.ty) {
                    let cx = try_cty_g(&g)?;
                    if x.name == "None" {
                        return Ok(format!("None::<{}>", cx));
                    }
                    let a = match &x.arg {
                        Some(a) => self.c(a)?,
                        None => return Err("codegen: unsupported expression in requires: None".to_string()),
                    };
                    if x.name == "Some" {
                        return Ok(format!("Some::<{}>({})", cx, a));
                    }
                    return Ok(format!("{}::<{}, i128>({})", x.name, cx, a));
                }
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
            Expr::FieldAccess(x) => {
                if self.is_ext(expr_ty(&x.base).as_deref()) || self.g9_real_path(&x.base) {
                    // G9: a field of a real value (extended struct, or a part of one) is read from the original
                    // reference; only the field itself is converted (a nominal field is converted whole and charged)
                    let fty = expr_ty(e);
                    if self.is_ext(fty.as_deref()) || fty.as_deref().map_or(false, |t| is_array_name(t) || t == "str") {
                        return Err(self.g9_unsupported(e, &format!("the aggregate field {} as a plain operand", x.field)));
                    }
                    let t = fty.as_deref().ok_or_else(|| "'NoneType' object has no attribute 'owner'".to_string())?;
                    if !nominals_in(&GType::from_key(t)).is_empty() {
                        let r = self.cx(e)?;
                        return self.g9_metered(t, &r);
                    }
                    let base = self.cx(&x.base)?;
                    return try_conv(t, &format!("({}).{}", base, x.field));
                }
                Ok(format!("{}.{}", self.c(&x.base)?, x.field))
            }
            Expr::IsVariant(x) => {
                if self.is_ext(expr_ty(&x.value).as_deref()) || self.g9_real_path(&x.value) {
                    let v = self.cx(&x.value)?;
                    return Ok(format!("matches!({}, {}::{} {{ .. }})", v, x.enum_name, x.variant));
                }
                Ok(format!("matches!({}, pruv_contract__{}::{} {{ .. }})", self.c(&x.value)?, x.enum_name, x.variant))
            }
            // G6 A0: `move` is checked but never lowered (the driver's A0 guard stops the program earlier)
            Expr::Move(_) => Err("G6 move reached the Rust generator".to_string()),
            // G5 A0: an inout marker is checked but never lowered (the driver's A0 guard stops the program earlier)
            Expr::InoutArg(_) => Err("G5 inout argument reached the Rust generator".to_string()),
            Expr::VariantField(x) if self.is_ext(expr_ty(&x.value).as_deref()) || self.g9_real_path(&x.value) => {
                let fty = expr_ty(e);
                if self.is_ext(fty.as_deref()) || fty.as_deref().map_or(false, |t| is_array_name(t) || t == "str") {
                    return Err(self.g9_unsupported(e, &format!("the aggregate field {} as a plain operand", x.field)));
                }
                self.tmp += 1;
                let tmp = format!("pruv_e{}", self.tmp);
                let nfields = k_variant(&self.table, &x.enum_name, &x.variant)?.fields.len();
                let idx = k_field_index(&self.table, &x.enum_name, &x.field, Some(&x.variant))?;
                let pats = (0..nfields).map(|i| if i == idx { "pruv_f" } else { "_" }).collect::<Vec<_>>().join(", ");
                let msg = format!("variant_field expected {}::{}.{}", src_name(&x.enum_name), x.variant, x.field);
                let val = self.cx(&x.value)?;
                let t = fty.as_deref().ok_or_else(|| "'NoneType' object has no attribute 'owner'".to_string())?;
                let cv = self.g9_metered(t, "pruv_f")?;
                Ok(format!(
                    "({{ let {tmp}: &{en} = {val}; match {tmp} {{ {en}::{v}({pats}) => {cv}, _ => pruv_ud({m}) }} }})",
                    tmp = tmp,
                    en = x.enum_name,
                    val = val,
                    v = x.variant,
                    pats = pats,
                    cv = cv,
                    m = rstr(&msg)
                ))
            }
            Expr::VariantField(x) => {
                self.tmp += 1;
                let tmp = format!("pruv_e{}", self.tmp);
                let cn = format!("pruv_contract__{}", x.enum_name);
                let nfields = k_variant(&self.table, &x.enum_name, &x.variant)?.fields.len();
                let idx = k_field_index(&self.table, &x.enum_name, &x.field, Some(&x.variant))?;
                let pats = (0..nfields).map(|i| if i == idx { "pruv_f" } else { "_" }).collect::<Vec<_>>().join(", ");
                // G4: source-qualified in explicit mode
                let en = if self.explicit { src_name(&x.enum_name) } else { x.enum_name.clone() };
                let msg = format!("variant_field expected {}::{}.{}", en, x.variant, x.field);
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
                if n == "size" {
                    // G9: structural size on the real value, checked i128 additions, one budget unit per node visited
                    let a0 = arg(a, 0)?;
                    let tn = key_name(
                        expr_ty(a0).as_deref().ok_or_else(|| "'NoneType' object has no attribute 'name'".to_string())?,
                    )
                    .to_string();
                    self.need_size.insert(tn.clone());
                    let v = self.cx(a0)?;
                    return Ok(format!("pruv_csize__{}({}, &mut pruv_budget)", tn, v));
                }
                if matches!(n, "file_ok" | "file_readable" | "file_writable") {
                    return Ok(format!("({}).{}", self.c(arg(a, 0)?)?, &n[5..]));
                }
                if n == "file_size" {
                    return Ok(format!("(({}).buf.len() as i128)", self.c(arg(a, 0)?)?));
                }
                if n == "file_byte" {
                    return Ok(format!("pruv_cidx_u8(&({}).buf, {})", self.c(arg(a, 0)?)?, self.c(arg(a, 1)?)?));
                }
                if n == "map_lookup" {
                    // G6: finite-map lookup, Option mirror of the stored value
                    let (kt, vt) = map_type_args(arg(a, 0)?)?;
                    let key = self.c(arg(a, 1)?)?;
                    let m0 = self.carr(arg(a, 0)?)?;
                    let look = if kt == GType::i64() {
                        format!("i64::try_from({}).ok().and_then(|pruv_k| {}.get(&pruv_k).copied())", key, m0)
                    } else {
                        format!("{}.get(&{}).copied()", m0, key)
                    };
                    return Ok(format!("({})", try_conv_g(&mk_option(vt), &format!("({})", look))?));
                }
                if n == "map_updated" {
                    // G6: generated scan helper; shares the entry's iteration budget
                    let (kt, vt) = map_type_args(arg(a, 0)?)?;
                    let src: Vec<GType> = match x.inst.as_ref().and_then(|i| i.src_args.clone()) {
                        Some(s) => s,
                        None => vec![kt.clone(), vt.clone()],
                    };
                    let helper = self.fg_mut()?.map_updated_helper(&kt, &vt, &src)?;
                    let a0 = self.carr(arg(a, 0)?)?;
                    let a1 = self.carr(arg(a, 1)?)?;
                    let a2 = self.c(arg(a, 2)?)?;
                    let a3 = self.c(arg(a, 3)?)?;
                    return Ok(format!("{}(&{}, &{}, {}, {}, &mut pruv_budget)", helper, a0, a1, a2, a3));
                }
                if n == "is_char_boundary" {
                    // G2 B2
                    let s0 = self.carr(arg(a, 0)?)?;
                    let i0 = self.c(arg(a, 1)?)?;
                    return Ok(format!("pruv_cboundary({}, {})", s0, i0));
                }
                if n == "load_be" {
                    // P2 batch 4: bounds checked inside the helper
                    self.need_load_be = true;
                    let nb = crate::check::word_width(arg(a, 2)?).unwrap_or(0);
                    let a0 = self.carr(arg(a, 0)?)?;
                    let a1 = self.c(arg(a, 1)?)?;
                    return Ok(format!("pruv_cload_be({}, {}, {})", a0, a1, nb));
                }
                if bit_rust(n).is_some() {
                    // P2: i128 arguments checked inside i64 by the helper
                    self.need_bits.insert(n.to_string());
                    let a0 = self.c(arg(a, 0)?)?;
                    let a1 = self.c(arg(a, 1)?)?;
                    return Ok(format!("pruv_c{}({}, {})", n, a0, a1));
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

    // ---------- G9: generated contract helpers (size, structural equality) ----------

    /// Rust i128 expression for weight(value) (G9_SPEC 3); x names a variable of type `&R(t)`.
    /// Scalars, arrays and str weigh 0; a nominal value weighs its size; Some / Ok weigh their payload; None / Err 0.
    /// `bud` is the budget argument expression (`pruv_budget` inside a helper, where it is a `&mut i64`).
    fn g9_weight(&self, t: &GType, x: &str, bud: &str) -> String {
        if is_optres(t) {
            let inner = self.g9_weight(&t.args[0], "pruv_w", bud);
            if inner == "0i128" {
                return "0i128".to_string();
            }
            if t.name == "option" {
                return format!(
                    "match {} {{ ::std::option::Option::Some(pruv_w) => {}, ::std::option::Option::None => 0i128 }}",
                    x, inner
                );
            }
            return format!(
                "match {} {{ ::std::result::Result::Ok(pruv_w) => {}, ::std::result::Result::Err(_) => 0i128 }}",
                x, inner
            );
        }
        if t.is_user_type() {
            return format!("pruv_csize__{}({}, {})", t.name, x, bud);
        }
        "0i128".to_string()
    }

    /// equality has to walk into t (a nominal value, or Option / Result of one)
    fn g9_walks(&self, t: &GType) -> bool {
        if is_optres(t) {
            return self.g9_walks(&t.args[0]);
        }
        t.is_user_type()
    }

    /// Rust bool expression: structural equality of the values behind the references x and y (type `&R(t)`)
    fn g9_eq(&self, t: &GType, x: &str, y: &str) -> String {
        if is_optres(t) && self.g9_walks(&t.args[0]) {
            let inner = self.g9_eq(&t.args[0], "pruv_p", "pruv_q");
            if t.name == "option" {
                return format!(
                    "(match ({}, {}) {{ (::std::option::Option::Some(pruv_p), ::std::option::Option::Some(pruv_q)) => {}, (::std::option::Option::None, ::std::option::Option::None) => true, _ => false }})",
                    x, y, inner
                );
            }
            return format!(
                "(match ({}, {}) {{ (::std::result::Result::Ok(pruv_p), ::std::result::Result::Ok(pruv_q)) => {}, (::std::result::Result::Err(pruv_p), ::std::result::Result::Err(pruv_q)) => (*pruv_p == *pruv_q), _ => false }})",
                x, y, inner
            );
        }
        if t.is_user_type() {
            return format!("pruv_ceq__{}({}, {}, pruv_budget)", t.name, x, y);
        }
        format!("(*{} == *{})", x, y)
    }

    /// pruv_csize__Name: 1 + sum of the weights of the ACTIVE fields, one budget unit per call (= per node)
    fn g9_size_text(&self, d: &TypeDecl) -> String {
        let n = d.name();
        let mut lines: Vec<String> = vec![
            G9_HELPER_ALLOW.to_string(),
            format!("fn pruv_csize__{}(v: &{}, pruv_budget: &mut i64) -> i128 {{", n, n),
            "    pruv_g9_tick(pruv_budget);".to_string(),
        ];
        let unit = |fields: &[FieldDecl]| -> (Vec<String>, Vec<String>) {
            let mut binds: Vec<String> = Vec::new();
            let mut ws: Vec<String> = Vec::new();
            for (i, f) in fields.iter().enumerate() {
                let w = self.g9_weight(&GType::from_key(&f.ty), &format!("pruv_a{}", i), "pruv_budget");
                if w == "0i128" {
                    binds.push("_".to_string());
                } else {
                    binds.push(format!("pruv_a{}", i));
                    ws.push(w);
                }
            }
            (binds, ws)
        };
        // sequential accumulator statements (linear text, no nested pruv_cadd(pruv_cadd(..)..) chain)
        let stmts = |ws: &[String]| -> Vec<String> {
            let mut v: Vec<String> = vec!["let mut pruv_s: i128 = 1i128;".to_string()];
            for w in ws {
                v.push(format!("pruv_s = pruv_cadd(pruv_s, {});", w));
            }
            v
        };
        let fold = |ws: &[String]| -> String {
            match ws.len() {
                0 => "1i128".to_string(),
                1 => format!("pruv_cadd(1i128, {})", ws[0]),
                _ => format!("{{ {} pruv_s }}", stmts(ws).join(" ")),
            }
        };
        match d {
            TypeDecl::Struct(s) => {
                let (binds, ws) = unit(&s.fields);
                if !s.fields.is_empty() {
                    let parts: Vec<String> =
                        s.fields.iter().zip(binds.iter()).map(|(f, b)| format!("{}: {}", f.name, b)).collect();
                    lines.push(format!("    let {} {{ {} }} = v;", n, parts.join(", ")));
                }
                if ws.len() >= 2 {
                    for x in stmts(&ws) {
                        lines.push(format!("    {}", x));
                    }
                    lines.push("    pruv_s".to_string());
                } else {
                    lines.push(format!("    {}", fold(&ws)));
                }
            }
            TypeDecl::Enum(en) => {
                lines.push("    match v {".to_string());
                for v in &en.variants {
                    if v.fields.is_empty() {
                        lines.push(format!("        {}::{} => 1i128,", n, v.name));
                        continue;
                    }
                    let (binds, ws) = unit(&v.fields);
                    lines.push(format!("        {}::{}({}) => {},", n, v.name, binds.join(", "), fold(&ws)));
                }
                lines.push("    }".to_string());
            }
        }
        lines.push("}".to_string());
        format!("{}\n", lines.join("\n"))
    }

    /// pruv_ceq__Name: structural equality; fields are compared left to right and only for the same active variant
    fn g9_eq_text(&self, d: &TypeDecl) -> String {
        let n = d.name();
        let mut lines: Vec<String> = vec![
            G9_HELPER_ALLOW.to_string(),
            format!("fn pruv_ceq__{}(a: &{}, b: &{}, pruv_budget: &mut i64) -> bool {{", n, n, n),
            "    pruv_g9_tick(pruv_budget);".to_string(),
        ];
        let conj = |fields: &[FieldDecl]| -> String {
            if fields.is_empty() {
                return "true".to_string();
            }
            fields
                .iter()
                .enumerate()
                .map(|(i, f)| self.g9_eq(&GType::from_key(&f.ty), &format!("pruv_a{}", i), &format!("pruv_b{}", i)))
                .collect::<Vec<_>>()
                .join(" && ")
        };
        match d {
            TypeDecl::Struct(s) => {
                if !s.fields.is_empty() {
                    for (side, var) in [("a", "pruv_a"), ("b", "pruv_b")] {
                        let parts: Vec<String> =
                            s.fields.iter().enumerate().map(|(i, f)| format!("{}: {}{}", f.name, var, i)).collect();
                        lines.push(format!("    let {} {{ {} }} = {};", n, parts.join(", "), side));
                    }
                }
                lines.push(format!("    {}", conj(&s.fields)));
            }
            TypeDecl::Enum(en) => {
                lines.push("    match (a, b) {".to_string());
                for v in &en.variants {
                    if v.fields.is_empty() {
                        lines.push(format!("        ({}::{}, {}::{}) => true,", n, v.name, n, v.name));
                        continue;
                    }
                    let pa = (0..v.fields.len()).map(|i| format!("pruv_a{}", i)).collect::<Vec<_>>().join(", ");
                    let pb = (0..v.fields.len()).map(|i| format!("pruv_b{}", i)).collect::<Vec<_>>().join(", ");
                    lines.push(format!(
                        "        ({}::{}({}), {}::{}({})) => {},",
                        n,
                        v.name,
                        pa,
                        n,
                        v.name,
                        pb,
                        conj(&v.fields)
                    ));
                }
                lines.push("        _ => false,".to_string());
                lines.push("    }".to_string());
            }
        }
        lines.push("}".to_string());
        format!("{}\n", lines.join("\n"))
    }

    /// the helpers the runtime requires of this program need, in declaration order (size, then equality, per type).
    /// need_size / need_eq hold the operand types seen; both are closed over the nominal types of the fields.
    fn g9_helper_texts(&self) -> Vec<String> {
        if self.need_size.is_empty() && self.need_eq.is_empty() {
            return Vec::new();
        }
        let close = |seed: &HashSet<String>| -> HashSet<String> {
            let mut out: HashSet<String> = HashSet::new();
            let mut work: Vec<String> = seed.iter().cloned().collect();
            work.sort();
            while let Some(n) = work.pop() {
                if out.contains(&n) {
                    continue;
                }
                let d = match self.table.decl(&n) {
                    Some(d) => d,
                    None => continue,
                };
                out.insert(n);
                for f in d.all_fields() {
                    work.extend(nominals_in(&GType::from_key(&f.ty)));
                }
            }
            out
        };
        let sizes = close(&self.need_size);
        let eqs = close(&self.need_eq);
        let mut texts: Vec<String> = vec![G9_TICK.to_string()];
        for d in &self.table.decls {
            if sizes.contains(d.name()) {
                texts.push(self.g9_size_text(d));
            }
            if eqs.contains(d.name()) {
                texts.push(self.g9_eq_text(d));
            }
        }
        texts
    }

    // ---------- G9: owning and viewing extended values (executable code) ----------

    /// Rust `&T` for an extended expression in a READ position (argument, match scrutinee): no clone, no alloc.
    fn view(&mut self, e: &Expr) -> R<String> {
        match e {
            Expr::Var(x) => Ok(if self.refs.contains(&x.name) { x.name.clone() } else { format!("&{}", x.name) }),
            Expr::FieldAccess(x) => {
                let deref = if self.field_boxed(expr_ty(&x.base), &x.field) { "*" } else { "" };
                Ok(format!("&{}{}", deref, self.e(e)?))
            }
            _ => Ok(format!("&({})", self.e(e)?)),
        }
    }

    /// an expression in an OWNING position (let, assignment, constructor field, return). A named value or a field path is
    /// cloned explicitly; a fresh temporary (constructor, literal, call) moves. Other types: plain self.e.
    fn own_e(&mut self, e: &Expr) -> R<String> {
        if let Expr::Var(v) = e {
            if !self.ext.is_empty() && self.is_ext(expr_ty(e).as_deref()) && self.moving.contains(&v.name) {
                return self.e(e);
            }
        }
        if !self.ext.is_empty()
            && self.is_ext(expr_ty(e).as_deref())
            && matches!(e, Expr::Var(_) | Expr::FieldAccess(_))
        {
            return Ok(format!("::std::clone::Clone::clone({})", self.view(e)?));
        }
        self.e(e)
    }

    /// names of owned extended locals that the returned expression e may move instead of clone: a return is the last
    /// use of every local, so a local named exactly once in e (no other move or borrow of it in e) that is not a
    /// reference (parameter / payload view) and not the scrutinee of an enclosing match arm moves.
    fn return_movable(&self, e: Option<&Expr>) -> HashSet<String> {
        let mut out = HashSet::new();
        let e = match e {
            Some(e) => e,
            None => return out,
        };
        if self.ext.is_empty() {
            // P2 batch 4: `return truncate(x, m)` of an owned local array shortens x in place in every program
            if !self.cost {
                if let Expr::Call(c) = e {
                    if c.name == "truncate" && c.args.len() == 2 {
                        if let Expr::Var(v) = &c.args[0] {
                            if self.vars.contains_key(&v.name)
                                && !self.params.contains(&v.name)
                                && !self.refs.contains(&v.name)
                                && !self.pinned.contains(&v.name)
                            {
                                let mut m_names = HashSet::new();
                                crate::refine::expr_names(&c.args[1], &mut m_names);
                                if !m_names.contains(&v.name) {
                                    out.insert(v.name.clone());
                                }
                            }
                        }
                    }
                }
            }
            return out;
        }
        fn walk(x: &Expr, counts: &mut HashMap<String, usize>) {
            match x {
                Expr::Var(v) => *counts.entry(v.name.clone()).or_insert(0) += 1,
                Expr::Move(v) => *counts.entry(v.name.clone()).or_insert(0) += 1,
                _ => {}
            }
            for k in crate::refine::kids(x) {
                walk(k, counts);
            }
        }
        let mut counts = HashMap::new();
        walk(e, &mut counts);
        for (n, c) in counts {
            if c == 1 && !self.refs.contains(&n) && !self.params.contains(&n) && !self.pinned.contains(&n) {
                out.insert(n);
            }
        }
        out
    }

    /// the value stored into the field `label` of a constructor / literal: owned, boxed on a recursive edge
    fn field_value(&mut self, x: &Expr, label: &str) -> R<String> {
        let v = self.own_e(x)?;
        Ok(if self.boxed.contains(label) { format!("::std::boxed::Box::new({})", v) } else { v })
    }

    // ---------- statements / code expressions ----------

    fn block(&mut self, stmts: &[Stmt], ind: usize) -> R<()> {
        self.block_in(stmts, ind, &[], false)
    }

    fn block_in(&mut self, stmts: &[Stmt], ind: usize, decls: &[String], lp: bool) -> R<()> {
        let saved = self.vars.clone();
        let saved_refs = self.refs.clone();
        let mut later: Vec<HashSet<String>> = vec![HashSet::new(); stmts.len() + 1];
        for i in (0..stmts.len()).rev() {
            let mut n = later[i + 1].clone();
            crate::refine::stmt_names(std::slice::from_ref(&stmts[i]), &mut n);
            later[i] = n;
        }
        self.frames.push((decls.iter().cloned().collect(), HashSet::new(), lp));
        for (i, st) in stmts.iter().enumerate() {
            let top = self.frames.len() - 1;
            self.frames[top].1 = std::mem::take(&mut later[i + 1]);
            let r = self.stmt(st, ind);
            if r.is_err() {
                self.frames.pop();
                return r;
            }
            if let Stmt::Let(x) = st {
                let top = self.frames.len() - 1;
                self.frames[top].0.insert(x.name.clone());
            }
        }
        self.frames.pop();
        self.vars = saved;
        self.refs = saved_refs;
        Ok(())
    }

    /// the statement being emitted is the last use of local `name`: no later statement of any enclosing block up to
    /// the one declaring it names it, and no loop body lies between (a parameter or binder view is never dead here).
    fn dead_after(&self, name: &str) -> bool {
        if self.refs.contains(name) || self.params.contains(name) || self.pinned.contains(name) {
            return false;
        }
        for (decls, later, lp) in self.frames.iter().rev() {
            if later.contains(name) {
                return false;
            }
            if decls.contains(name) {
                return true;
            }
            if *lp {
                return false;
            }
        }
        false
    }

    /// a let / assignment whose value is copy(v) of an owned local v at its last use moves v (see dead_after)
    fn last_copy(&self, target: &str, e: &Expr) -> HashSet<String> {
        let mut out = HashSet::new();
        if !self.ext.is_empty() && !self.cost {
            if let Expr::Call(c) = e {
                if c.name == "truncate" && c.args.len() == 2 {
                    if let Expr::Var(v) = &c.args[0] {
                        // the length argument naming the array again (e.g. len(truncate(a, 1))) keeps it borrowed: no move
                        let mut m_names = HashSet::new();
                        crate::refine::expr_names(&c.args[1], &mut m_names);
                        if v.name != target && self.dead_after(&v.name) && !m_names.contains(&v.name) {
                            out.insert(v.name.clone());
                        }
                    }
                }
                if c.name == "copy" && c.args.len() == 1 {
                    if let Expr::Var(v) = &c.args[0] {
                        if v.name != target && self.dead_after(&v.name) {
                            out.insert(v.name.clone());
                        }
                    }
                    // copy(v.f) of an unboxed field of an owned local v at its last use moves the field out of v
                    if let Expr::FieldAccess(x) = &c.args[0] {
                        if let Expr::Var(v) = &*x.base {
                            if v.name != target && !self.field_boxed(&v.ty, &x.field) && self.dead_after(&v.name) {
                                out.insert(v.name.clone());
                            }
                        }
                    }
                }
            }
        }
        out
    }

    /// match on an extended enum: the scrutinee is borrowed (a view, never cloned) and every payload binder is an
    /// arm-local view, unless the match consumes the scrutinee (below).
    fn match_ext(&mut self, x: &Match, ind: usize) -> R<()> {
        let sty = key_name(expr_ty(&x.scrutinee).as_deref().unwrap_or("")).to_string();
        // Consuming match: a match on an owned local that no arm and no later statement names again (dead_after) is
        // that local's last use, so it is matched by value and payloads bind as owned values a return or copy moves.
        let mut consume = match &x.scrutinee {
            Expr::Var(v) => !self.cost && self.dead_after(&v.name),
            _ => false,
        };
        if consume {
            let mut named = HashSet::new();
            for a in &x.arms {
                named.extend(a.binders.iter().cloned());
                crate::refine::stmt_names(&a.body, &mut named);
            }
            if let Expr::Var(v) = &x.scrutinee {
                consume = consume && !named.contains(&v.name);
            }
        }
        let sv = if consume { self.e(&x.scrutinee)? } else { self.view(&x.scrutinee)? };
        self.emit(ind, &format!("match {} {{", sv));
        for a in &x.arms {
            let name = match &a.enum_name {
                None => a.ctor.clone(),
                Some(en) => format!("{}::{}", en, a.ctor),
            };
            let pat = if a.binders.is_empty() { name } else { format!("{}({})", name, a.binders.join(", ")) };
            self.emit(ind + 1, &format!("{} => {{", pat));
            let saved_vars = self.vars.clone();
            let saved_refs = self.refs.clone();
            let saved_pinned = self.pinned.clone();
            // the local a field-path scrutinee (h.e) borrows from is pinned too
            let mut root = &x.scrutinee;
            while let Expr::FieldAccess(f) = root {
                root = &*f.base;
            }
            if let Expr::Var(v) = root {
                self.pinned.insert(v.name.clone());
            }
            let fields: Vec<FieldDecl> = k_variant(&self.table, &sty, &a.ctor)?.fields.clone();
            for (b, fd) in a.binders.iter().zip(fields.iter()) {
                let ft = fd.ty.as_str();
                if self.is_ext(Some(ft)) && consume {
                    let boxed = self.boxed.contains(&format!("{}::{}.{}", sty, a.ctor, fd.name));
                    self.emit(ind + 2, &format!("let {}: {} = {}{};", b, ft, if boxed { "*" } else { "" }, b));
                    self.refs.remove(b);
                } else if self.is_ext(Some(ft)) {
                    self.emit(ind + 2, &format!("let {}: &{} = {};", b, ft, b));
                    self.refs.insert(b.clone());
                } else if (is_array_name(ft) || ft == "str") && consume {
                    self.emit(ind + 2, &format!("let {}: {} = {};", b, rty(ft, false), b));
                    self.refs.remove(b);
                } else if is_array_name(ft) || ft == "str" {
                    self.emit(ind + 2, &format!("let {}: {} = {};", b, rty(ft, true), b));
                    self.refs.insert(b.clone());
                } else if consume {
                    self.emit(ind + 2, &format!("let {}: {} = {};", b, rty(ft, false), b));
                    self.refs.remove(b);
                } else {
                    self.emit(ind + 2, &format!("let {}: {} = *{};", b, rty(ft, false), b));
                    self.refs.remove(b);
                }
                self.vars.insert(b.clone(), fd.ty.clone());
            }
            self.block_in(&a.body, ind + 2, &a.binders, false)?;
            self.vars = saved_vars;
            self.refs = saved_refs;
            self.pinned = saved_pinned;
            self.emit(ind + 1, "}");
        }
        self.emit(ind, "}");
        Ok(())
    }

    fn stmt(&mut self, st: &Stmt, ind: usize) -> R<()> {
        match st {
            Stmt::Let(x) => {
                self.moving = self.last_copy(&x.name, &x.value);
                let v = self.own_e(&x.value);
                self.moving.clear();
                let v = v?;
                let line = format!("let {}{}: {} = {};", if x.mutable { "mut " } else { "" }, x.name, self.rt_width(&x.ty, false, self.storage.layout_of(x)), v);
                self.emit(ind, &line);
                self.vars.insert(x.name.clone(), x.ty.clone());
                self.refs.remove(&x.name); // G9: a local is an owned value, never a reference
            }
            Stmt::Assign(x) => {
                self.moving = self.last_copy(&x.name, &x.value);
                let v = self.own_e(&x.value);
                self.moving.clear();
                let v = v?;
                self.emit(ind, &format!("{} = {};", x.name, v));
            }
            Stmt::FieldAssign(x) => {
                // Fully evaluate the right-hand side into a temporary, then store
                let decl = match expr_ty(&x.value) {
                    Some(t) => format!("let pruv_v: {} = ", rty(t, false)),
                    None => "let pruv_v = ".to_string(),
                };
                let mut stored = "pruv_v".to_string();
                if !self.boxed.is_empty() && self.path_boxed(&x.name, &x.fields) {
                    stored = "::std::boxed::Box::new(pruv_v)".to_string(); // the assigned field is a recursive (Box) edge
                }
                let v = self.own_e(&x.value)?;
                self.emit(ind, &format!("{{ {}{}; {}.{} = {}; }}", decl, v, x.name, x.fields.join("."), stored));
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
                                "{{ let pruv_i: i64 = {}; let pruv_x: bool = {}; pruv_set_bool({}, pruv_i, pruv_x); }}",
                                i, v, self.mut_ref(&x.name)
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
                                "{{ let pruv_i: i64 = {}; let pruv_x: i64 = {}; pruv_set_u8({}, pruv_i, pruv_x); }}",
                                i, v, self.mut_ref(&x.name)
                            ),
                        );
                    }
                } else if self.verified {
                    self.emit(
                        ind,
                        &format!(
                            "{{ let pruv_i: i64 = {}; let pruv_x: i64 = {}; unsafe {{ *{}.get_unchecked_mut(pruv_i as usize) = pruv_x{}; }} }}",
                            i, v, x.name, if self.storage.layout_of(x) != "i64" { format!(" as {}", self.storage.layout_of(x)) } else { String::new() }
                        ),
                    );
                } else {
                    // Temporaries first: `&mut a` must not be alive while the index and value read `a`
                    self.emit(
                        ind,
                        &format!(
                            "{{ let pruv_i: i64 = {}; let pruv_x: i64 = {}; pruv_set({}, pruv_i, pruv_x); }}",
                            i, v, self.mut_ref(&x.name)
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
                if self.cost {
                    self.emit(ind + 1, &Self::cost_add("1"));
                }
                self.block_in(&x.body, ind + 1, &[], true)?;
                self.emit(ind, "}");
            }
            Stmt::Return(x) if self.cost => {
                self.moving = self.return_movable(x.value.as_ref());
                if let Some(v) = &x.value {
                    let t = self.own_e(v)?;
                    self.emit(ind, &format!("let pruv_return = {};", t));
                }
                self.moving.clear();
                self.emit(ind, Self::cost_check());
                self.emit(ind, if x.value.is_some() { "return pruv_return;" } else { "return;" });
            }
            Stmt::Return(x) => match &x.value {
                None => self.emit(ind, "return;"),
                Some(v) => {
                    self.moving = self.return_movable(Some(v));
                    let t = self.own_e(v)?;
                    self.moving.clear();
                    self.emit(ind, &format!("return {};", t));
                }
            },
            Stmt::Assert(_) => {}
            Stmt::Par(p) => self.parallel(p, ind)?,
            Stmt::ExprStmt(x) => {
                let t = self.e(&x.expr)?;
                self.emit(ind, &format!("{};", t));
            }
            Stmt::Match(x) if self.is_ext(expr_ty(&x.scrutinee).as_deref()) => {
                self.match_ext(x, ind)?;
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

    /// G5: a mutable borrow of the array `name`: a reborrow for an inout parameter (already `&mut [T]`)
    fn parallel(&mut self, st: &Par, ind: usize) -> R<()> {
        self.emit(ind, "{");
        let hook = matches!(self.par_hook.as_str(), "spawn" | "panic" | "overlap");
        if hook {
            self.emit(ind + 1, "let pruv_gate = &(::std::sync::Mutex::new((false, 0usize, 0usize)), ::std::sync::Condvar::new());");
        }
        let ind = ind + 1;
        self.emit(ind, "::std::thread::scope(|pruv_scope| {");
        let d = ind + 1;
        let mut prepared = Vec::new();
        for (i, expr) in st.calls.iter().enumerate() {
            let call = match expr {
                Expr::Call(c) => c,
                _ => return Err("codegen: par branch is not a call".into()),
            };
            let mut args = Vec::new();
            for (j, x) in call.args.iter().enumerate() {
                let n = format!("pruv_arg_{}_{}", i, j);
                let (ty, val) = if let Expr::InoutArg(ia) = x {
                    let name = match ia.expr.as_ref() {
                        Expr::Var(v) => &v.name,
                        _ => return Err("codegen: inout operand is not a variable".into()),
                    };
                    (format!("&mut {}", &rty(&self.vars[name], true)[1..]), self.mut_ref(name))
                } else {
                    let ty = expr_ty(x).as_deref().ok_or("codegen: par argument has no type")?;
                    if is_array_name(&ty) {
                        (self.rt_width(ty, true, self.layout(x)), self.arr_ref(x)?)
                    } else {
                        (rty(ty, false), self.e(x)?)
                    }
                };
                self.emit(d, &format!("let {}: {} = {};", n, ty, val));
                args.push(n);
            }
            let mut n = if self.explicit { self.callee(&call.name) } else { call.name.clone() };
            if !self.explicit && self.has_req.contains(&call.name) {
                if self.verified {
                    n.push_str("__pruv_body");
                } else if self.trust && !call.args.iter().any(|x| matches!(x, Expr::InoutArg(_))) {
                    n.push_str("__pruv_par_chk");
                }
            }
            if self.cost {
                self.emit(d, &Self::cost_call(&call.name, &args));
            }
            prepared.push(format!("{}({});", n, args.join(", ")));
        }
        self.emit(d, "let mut pruv_handles = ::std::vec::Vec::new();");
        self.emit(d, "let mut pruv_spawn_failed = false;");
        for (i, call) in prepared.iter().enumerate() {
            self.emit(d, "if !pruv_spawn_failed {");
            if self.par_hook == "spawn" && i == 1 {
                self.emit(d + 1, "pruv_spawn_failed = true;");
            } else {
                self.emit(d + 1, "match ::std::thread::Builder::new().spawn_scoped(pruv_scope, move || {");
                if hook {
                    self.emit(d + 2, "let mut gate = pruv_gate.0.lock().unwrap();");
                    self.emit(d + 2, "gate.1 += 1; pruv_gate.1.notify_all();");
                    self.emit(d + 2, "while !gate.0 || gate.1 < gate.2 { gate = pruv_gate.1.wait(gate).unwrap(); }");
                    self.emit(d + 2, "::std::mem::drop(gate);");
                    if self.par_hook == "panic" && i == 0 {
                        self.emit(d + 2, "panic!(\"pruv test worker panic\");");
                    }
                }
                self.emit(d + 2, call);
                self.emit(d + 1, "}) {");
                self.emit(d + 2, "::std::result::Result::Ok(h) => pruv_handles.push(h),");
                self.emit(d + 2, "::std::result::Result::Err(_) => pruv_spawn_failed = true,");
                self.emit(d + 1, "}");
            }
            self.emit(d, "}");
        }
        if hook {
            self.emit(d, "{ let mut gate = pruv_gate.0.lock().unwrap(); gate.0 = true; gate.2 = pruv_handles.len(); pruv_gate.1.notify_all(); }");
        }
        self.emit(d, "let mut pruv_panicked = false;");
        self.emit(d, "for h in pruv_handles {");
        self.emit(d + 1, "if h.join().is_err() { pruv_panicked = true; }");
        if hook { self.emit(d + 1, "eprintln!(\"pruv test joined\");"); }
        self.emit(d, "}");
        self.emit(d, "if pruv_spawn_failed { eprintln!(\"pruv: parallel spawn failed\"); ::std::process::exit(101); }");
        self.emit(d, "if pruv_panicked { ::std::process::exit(101); }");
        self.emit(ind, "});");
        self.emit(ind - 1, "}");
        Ok(())
    }

    fn mut_ref(&self, name: &str) -> String {
        if self.inouts.contains(name) { format!("&mut *{}", name) } else { format!("&mut {}", name) }
    }

    /// An array expression used as a borrowed slice
    fn arr_ref(&mut self, e: &Expr) -> R<String> {
        if let Expr::StrLit(x) = e {
            if !self.cost {
                return Ok(lit_str(&x.value)); // a string literal is borrowed as its &'static str (no alloc)
            }
        }
        if let Expr::Var(x) = e {
            if self.refs.contains(&x.name) {
                return Ok(x.name.clone()); // G9: a buffer payload view is already a reference
            }
            if self.inouts.contains(&x.name) {
                return Ok(format!("&*{}", x.name)); // G5: a shared reborrow of an inout parameter
            }
            if !self.params.contains(&x.name) {
                return Ok(format!("&{}", x.name));
            }
            return Ok(x.name.clone());
        }
        Ok(format!("&{}", self.e(e)?))
    }

    /// a collection expression in a borrow position (G6 section 12.1)
    fn cref(&mut self, x: &Expr) -> R<String> {
        if let Expr::Var(v) = x {
            return Ok(if self.borrowed.contains(&v.name) { v.name.clone() } else { format!("&{}", v.name) });
        }
        Ok(format!("&({})", self.e(x)?))
    }

    /// executable catalog operation -> call of its private boundary helper
    fn catalog_call(&mut self, x: &Call) -> R<String> {
        let cat = catalog_fn(&x.name).ok_or_else(|| repr_str(&x.name))?;
        let (low, src): (Vec<GType>, Vec<GType>) = match &x.inst {
            Some(i) => (i.args.clone(), i.src_args.clone().unwrap_or_else(|| i.args.clone())),
            None => (Vec::new(), Vec::new()),
        };
        let name = self.fg_mut()?.catalog_helper(&x.name, &low, &src)?;
        // string_to_str of an owned local that the enclosing return moves: the String itself is the copy.
        if x.name == "string_to_str" && !self.cost {
            if let Some(a @ Expr::Var(v)) = x.args.first() {
                if self.moving.contains(&v.name) {
                    return self.e(a);
                }
            }
        }
        let mut args: Vec<String> = Vec::new();
        for (p, xa) in cat.params.iter().zip(x.args.iter()) {
            if p.ty.is_collection() {
                if p.take {
                    args.push(self.e(xa)?);
                } else {
                    args.push(self.cref(xa)?);
                }
            } else if p.ty == GType::str() || (x.name == "file_write_bytes" && p.ty == GType::new("array_u8", vec![])) {
                args.push(self.arr_ref(xa)?);
            } else {
                args.push(self.e(xa)?);
            }
        }
        Ok(format!("{}({})", name, args.join(", ")))
    }

    /// private helper `NAME` of a `trusted rust fn`: selected requires, catch_unwind around the Rust call, selected
    /// ensures. Emitted once, on first use.
    fn trusted_helper(&mut self, f: &Function) -> R<()> {
        if self.fg_mut()?.has_item(&f.name) {
            return Ok(());
        }
        self.fg_mut()?.set_op(&f.name);
        let mut new_params: HashSet<String> = f.params.iter().map(|p| p.name.clone()).collect();
        new_params.insert("result".to_string());
        let new_vars: HashMap<String, String> = f.params.iter().map(|p| (p.name.clone(), p.ty.clone())).collect();
        let saved_params = std::mem::replace(&mut self.params, new_params);
        let saved_vars = std::mem::replace(&mut self.vars, new_vars);
        let saved_cp = self.cp.take();
        let saved_bound = std::mem::take(&mut self.bound);
        let saved_tmp = std::mem::replace(&mut self.tmp, 0);
        let saved_borrowed = std::mem::take(&mut self.borrowed);
        let res = self.trusted_text(f);
        self.params = saved_params;
        self.vars = saved_vars;
        self.cp = saved_cp;
        self.bound = saved_bound;
        self.tmp = saved_tmp;
        self.borrowed = saved_borrowed;
        let text = res?;
        self.fg_mut()?.add_item(&f.name, text);
        Ok(())
    }

    fn trusted_text(&mut self, f: &Function) -> R<String> {
        let (req, ens) = {
            let fg = self.fg_mut()?;
            (fg.req, fg.ens)
        };
        let name = f.name.as_str();
        // G4 A2: messages name the source identity, the helper keeps its stem
        let disp = self.disp_of(name);
        let mut body: Vec<String> = Vec::new();
        if req {
            for r in &f.requires {
                let code = self.c(r)?;
                body.push(format!("if !({}) {{ pruv_g6_req({}, {}); }}", code, rstr(&disp), rstr(&show(r))));
            }
        }
        let args = join_map(&f.params, ", ", |p| p.name.clone());
        let rt = rty(&f.ret, false);
        let path = match &f.foreign {
            Some(i) => i.path.as_str(),
            None => return Err("'NoneType' object is not subscriptable".to_string()),
        };
        body.push(format!(
            "let result: {} = match ::std::panic::catch_unwind(::std::panic::AssertUnwindSafe(|| {}({}))) {{",
            rt, path, args
        ));
        body.push("    Ok(pruv_r) => pruv_r,".to_string());
        body.push(format!("    Err(_) => panic!({}),", rstr(&format!("pruv: foreign panic: {}", disp))));
        body.push("};".to_string());
        if key_is_collection(&f.ret) {
            // G6b: an owned result's length fits the 2^40 model in every check mode
            body.push(format!(
                "if (result.len() as u128) > (1u128 << 40) {{ pruv_g6_repr({}); }}",
                rstr(&format!("{}: result length", disp))
            ));
        }
        if ens {
            for x in &f.ensures {
                let code = self.c(x)?;
                body.push(format!("if !({}) {{ pruv_g6_ens({}, {}); }}", code, rstr(&disp), rstr(&show(x))));
            }
        }
        body.push("result".to_string());
        let ps = join_map(&f.params, ", ", |p| format!("{}: {}", p.name, rty(&p.ty, true)));
        let ret: Option<&str> = if f.ret == "unit" { None } else { Some(rt.as_str()) };
        Ok(self.fg_mut()?.fn_trusted(name, &ps, ret, &body, &disp))
    }

    fn e(&mut self, e: &Expr) -> R<String> {
        match e {
            Expr::Spent(_) => Err("cost_unavailable: Stage 5 cost verification is not implemented yet".into()),
            Expr::Move(x) => Ok(x.name.clone()), // G6: Rust moves
            // G5 A0: never reaches the generator (the driver's A0 guard stops the program earlier)
            Expr::InoutArg(_) => Err("G5 inout argument reached the Rust generator".to_string()),
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
                if u8r || self.layout(&x.array) != "i64" {
                    return Ok(format!("((unsafe {{ *{}.get_unchecked(({}) as usize) }}) as i64)", a, i));
                }
                Ok(format!("(unsafe {{ *{}.get_unchecked(({}) as usize) }})", a, i))
            }
            Expr::Ctor(x) => {
                // G3: explicit payload type, never left to Rust inference
                if let Some(g) = payload_type(&x.ty) {
                    let rx = rty_g(&g, false);
                    if x.name == "None" {
                        return Ok(format!("None::<{}>", rx));
                    }
                    let a = match &x.arg {
                        Some(a) => self.e(a)?,
                        None => return Err("codegen: contract-only expression in code: None".to_string()),
                    };
                    if x.name == "Some" {
                        return Ok(format!("Some::<{}>({})", rx, a));
                    }
                    return Ok(format!("{}::<{}, i64>({})", x.name, rx, a));
                }
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
                let fs: Vec<FieldDecl> = k_fields(&self.table, &x.name, None)?.to_vec();
                if fs.is_empty() {
                    return Ok(format!("({} {{}})", x.name));
                }
                let vals = init_map(&x.fields);
                let mut parts: Vec<String> = Vec::new();
                for f in &fs {
                    let v = init_value(&vals, &f.name)?;
                    if !self.ext.is_empty() {
                        // G9: constructor fields are owning positions; a recursive edge is boxed
                        let fv = self.field_value(v, &format!("{}.{}", x.name, f.name))?;
                        parts.push(format!("{}: {}", f.name, fv));
                    } else {
                        parts.push(format!("{}: {}", f.name, self.e(v)?));
                    }
                }
                Ok(format!("({} {{ {} }})", x.name, parts.join(", ")))
            }
            Expr::EnumCtor(x) => {
                let ctor = format!("{}::{}", x.enum_name, x.variant);
                if x.args.is_empty() {
                    return Ok(ctor);
                }
                let mut parts: Vec<String> = Vec::new();
                if !self.ext.is_empty() {
                    // G9
                    let vf: Vec<FieldDecl> = k_variant(&self.table, &x.enum_name, &x.variant)?.fields.clone();
                    for (a, fd) in x.args.iter().zip(vf.iter()) {
                        parts.push(self.field_value(a, &format!("{}::{}.{}", x.enum_name, x.variant, fd.name))?);
                    }
                } else {
                    for a in &x.args {
                        parts.push(self.e(a)?);
                    }
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
                        return Ok(self.cost_buffer(format!("{}({}, {})", f, n0, v0)));
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
                        if u8a { " as u8".to_string() } else if self.layout(e) != "i64" { format!(" as {}", self.layout(e)) } else { String::new() }
                    ));
                }
                if n == "copy" {
                    // copy of an owned local that the enclosing return moves: the local itself is the copy.
                    if !self.cost {
                        if let a0 @ Expr::Var(v) = arg(a, 0)? {
                            if self.moving.contains(&v.name) {
                                return self.e(a0);
                            }
                        }
                        if let a0 @ Expr::FieldAccess(x) = arg(a, 0)? {
                            if let Expr::Var(v) = &*x.base {
                                if self.moving.contains(&v.name) && !self.field_boxed(&v.ty, &x.field) {
                                    return self.e(a0);
                                }
                            }
                        }
                    }
                    if expr_ty(arg(a, 0)?).as_deref() == Some("str") {
                        // G2 B2
                        let result = format!("{}.to_owned()", self.e(arg(a, 0)?)?);
                        return Ok(self.cost_buffer(result));
                    }
                    let result = format!("{}.to_vec()", self.e(arg(a, 0)?)?);
                    return Ok(self.cost_buffer(result));
                }
                if n == "truncate" {
                    // truncate of an owned local at its last use shortens the local in place; otherwise copy the prefix
                    if !self.cost {
                        if let a0 @ Expr::Var(v) = arg(a, 0)? {
                            if self.moving.contains(&v.name) {
                                let m0 = self.e(arg(a, 1)?)?;
                                let t0 = self.e(a0)?;
                                let chk = if self.verified {
                                    ""
                                } else {
                                    "if pruv_m < 0 || (pruv_m as u64) > (pruv_t.len() as u64) { pruv_oob(pruv_m, pruv_t.len()) } "
                                };
                                return Ok(format!(
                                    "{{ let pruv_m: i64 = {}; let mut pruv_t = {}; {}pruv_t.truncate(pruv_m as usize); pruv_t }}",
                                    m0, t0, chk
                                ));
                            }
                        }
                    }
                    let a0 = self.arr_ref(arg(a, 0)?)?;
                    let m0 = self.e(arg(a, 1)?)?;
                    let result = if !self.verified {
                        format!("{{ let pruv_a = {}; let pruv_m: i64 = {}; if pruv_m < 0 || (pruv_m as u64) > (pruv_a.len() as u64) {{ pruv_oob(pruv_m, pruv_a.len()) }} pruv_a[..(pruv_m as usize)].to_vec() }}", a0, m0)
                    } else {
                        format!("{{ let pruv_a = {}; let pruv_m: i64 = {}; unsafe {{ pruv_a.get_unchecked(..(pruv_m as usize)) }}.to_vec() }}", a0, m0)
                    };
                    return Ok(self.cost_buffer(result));
                }
                if n == "load_be" {
                    // P2 batch 4: big-endian word of a[i..i+nb]; unchecked slice when verified
                    let nb = crate::check::word_width(arg(a, 2)?).unwrap_or(0);
                    let chk = if self.verified {
                        String::new()
                    } else {
                        format!("if pruv_i < 0 || (pruv_i as u64) + {} > (pruv_a.len() as u64) {{ pruv_oob(pruv_i, pruv_a.len()) }} ", nb)
                    };
                    let rng = format!("(pruv_i as usize)..((pruv_i as usize) + {})", nb);
                    let sl = if self.verified {
                        format!("unsafe {{ pruv_a.get_unchecked({}) }}", rng)
                    } else {
                        format!("&pruv_a[{}]", rng)
                    };
                    let tail = if nb == 8 {
                        format!("i64::from_be_bytes(<[u8; 8] as ::std::convert::TryFrom<&[u8]>>::try_from({}).unwrap())", sl)
                    } else {
                        format!(
                            "let mut pruv_w = [0u8; 8]; pruv_w[{}..].copy_from_slice({}); u64::from_be_bytes(pruv_w) as i64",
                            8 - nb,
                            sl
                        )
                    };
                    let a0 = self.arr_ref(arg(a, 0)?)?;
                    let a1 = self.e(arg(a, 1)?)?;
                    return Ok(format!("{{ let pruv_a: &[u8] = {}; let pruv_i: i64 = {}; {}{} }}", a0, a1, chk, tail));
                }
                if n == "store_be" {
                    // P2 batch 4: low 8*nb bits of w, big-endian, into a[i..i+nb]
                    let nb = crate::check::word_width(arg(a, 3)?).unwrap_or(0);
                    let name = match arg(a, 0)? {
                        Expr::InoutArg(ia) => match ia.expr.as_ref() {
                            Expr::Var(v) => v.name.clone(),
                            other => return Err(format!("codegen: inout operand is not a variable: {:?}", other)),
                        },
                        other => return Err(format!("codegen: inout operand is not a variable: {:?}", other)),
                    };
                    let chk = if self.verified {
                        String::new()
                    } else {
                        format!(
                            "if pruv_i < 0 || (pruv_i as u64) + {} > ({}.len() as u64) {{ pruv_oob(pruv_i, {}.len()) }} ",
                            nb, name, name
                        )
                    };
                    let rng = format!("(pruv_i as usize)..((pruv_i as usize) + {})", nb);
                    let dst = if self.verified {
                        format!("unsafe {{ {}.get_unchecked_mut({}) }}", name, rng)
                    } else {
                        format!("{}[{}]", name, rng)
                    };
                    let a1 = self.e(arg(a, 1)?)?;
                    let a2 = self.e(arg(a, 2)?)?;
                    return Ok(format!(
                        "{{ let pruv_i: i64 = {}; let pruv_w: i64 = {}; {}{}.copy_from_slice(&(pruv_w as u64).to_be_bytes()[{}..]); }}",
                        a1,
                        a2,
                        chk,
                        dst,
                        8 - nb
                    ));
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
                if let (Some(op), Some(helper)) = (bit_rust(n), shift_safe(n)) {
                    // P2 batch 2: --no-verify checks the count in a helper; verified relies on shift_range
                    let a0 = self.e(arg(a, 0)?)?;
                    let a1 = self.e(arg(a, 1)?)?;
                    if !self.verified {
                        self.need_shift.insert(n.to_string());
                        return Ok(format!("{}({}, {})", helper, a0, a1));
                    }
                    return Ok(format!("(((({}) as u64) {} (({}) as u32)) as i64)", a0, op, a1));
                }
                if is_wrap_rust(n) {
                    // P2 batch 3: wraps by definition, same text with and without --no-verify
                    let a0 = self.e(arg(a, 0)?)?;
                    let a1 = self.e(arg(a, 1)?)?;
                    return Ok(format!("({}).{}({})", a0, n, a1));
                }
                if let Some(op) = bit_rust(n) {
                    // P2: no overflow possible, same text with and without --no-verify
                    let a0 = self.e(arg(a, 0)?)?;
                    let a1 = self.e(arg(a, 1)?)?;
                    return Ok(format!("({} {} {})", a0, op, a1));
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
                if self.g6 && is_catalog(n) {
                    return self.catalog_call(x); // G6: executable catalog operation
                }
                let callee: Option<&'a Function> = if self.g6 { self.fmap.get(n).copied() } else { None };
                if let Some(cf) = callee {
                    if cf.foreign.is_some() {
                        if let Some(fg) = self.fg.as_mut() {
                            fg.called.insert(n.to_string());
                        }
                        self.trusted_helper(cf)?; // emitted on first use; the helper checks the selected requires itself
                    }
                }
                let mut args: Vec<String> = Vec::new();
                for (i, xa) in a.iter().enumerate() {
                    let is_move = matches!(xa, Expr::Move(_));
                    let coll = expr_ty(xa).as_deref().map_or(false, key_is_collection);
                    if let Expr::InoutArg(ia) = xa {
                        // G5: `inout name` -> a mutable borrow / reborrow, in source order
                        let nm = match ia.expr.as_ref() {
                            Expr::Var(v) => v.name.clone(),
                            other => return Err(format!("codegen: inout operand is not a variable: {:?}", other)),
                        };
                        args.push(self.mut_ref(&nm));
                    } else if self.g6 && (is_move || coll) {
                        let take = is_move || callee.map_or(false, |c| c.params.get(i).map_or(false, |p| p.take));
                        if take {
                            args.push(self.e(xa)?);
                        } else {
                            args.push(self.cref(xa)?);
                        }
                    } else if !self.ext.is_empty() && self.is_ext(expr_ty(xa).as_deref()) {
                        args.push(self.view(xa)?); // G9: an extended argument is a read view; a fresh temporary lives through the call
                    } else if expr_ty(xa).as_deref().map_or(false, |t| is_array_name(t) || t == "str") {
                        args.push(self.arr_ref(xa)?);
                    } else {
                        args.push(self.e(xa)?);
                    }
                }
                let mut captured = Vec::new();
                if self.cost && self.fmap.contains_key(n) {
                    for (i, arg) in args.iter().enumerate() {
                        captured.push(format!("let pruv_cost_arg_{} = {};", i, arg));
                    }
                    args = (0..args.len()).map(|i| format!("pruv_cost_arg_{}", i)).collect();
                    captured.push(Self::cost_call(n, &args));
                }
                let mut name = n.to_string();
                if self.explicit {
                    name = self.callee(&name); // G4 A2
                } else if self.verified && self.has_req.contains(&name) {
                    name.push_str("__pruv_body"); // the caller proved the requires
                }
                let call = format!("{}({})", name, args.join(", "));
                Ok(if captured.is_empty() { call } else { format!("{{ {} {} }}", captured.join(" "), call) })
            }
            other => Err(format!("codegen: contract-only expression in code: {:?}", other)),
        }
    }
}

/// G6 A3 (foreign_shim.py build_shim): the A2 boundary helpers of a concrete G6 program, discovered by generating every
/// function with a Gen created for the same program and check mode (trust=True: the entry checks of the Rust source
/// backend are not emitted, the LLVM entries evaluate requires themselves): (helper name, text) in first-use order.
pub fn shim_helpers(
    prog: &Program,
    verified: bool,
    budget: u64,
    foreign_checks: &str,
    observers: &[(String, Vec<GType>)],
) -> R<Vec<(String, String)>> {
    let mut g = Gen::new(prog, verified, true, budget, foreign_checks);
    for f in &prog.functions {
        g.func(f)?;
    }
    if let Some(fg) = g.fg.as_mut() {
        for (op, low) in observers {
            fg.catalog_helper(op, low, low)?;
        }
    }
    match g.fg.as_ref() {
        Some(fg) => Ok(fg.items().to_vec()),
        None => Ok(Vec::new()),
    }
}

/// Failure of `gen_rust_any`: a diagnostic (PruvError, the specialization limit) or Python's str(Exception).
#[derive(Debug, Clone)]
pub enum GenError {
    Diag(crate::diagnostic::PruvError),
    Msg(String),
}

/// Pruv -> Rust source for any checked program (Python `gen_rust`): a program that uses generics is specialized first
/// (shared plan, mono.rs) and generated from the concrete program; any other program is generated directly.
pub fn gen_rust_any(prog: &Program, verified: bool, trust_callers: bool, budget: u64) -> Result<String, GenError> {
    gen_rust_ex(prog, verified, trust_callers, budget, "requires", &[]).map(|(text, _)| text)
}

/// `gen_rust_any` for a checked program of explicit visibility mode (`g4` = Some; None is `gen_rust_any`).
pub fn gen_rust_any_g4(
    prog: &Program,
    g4: Option<&crate::modules::G4>,
    verified: bool,
    trust_callers: bool,
    budget: u64,
) -> Result<String, GenError> {
    gen_rust_ex_g4(prog, g4, verified, trust_callers, budget, "requires", &[]).map(|(text, _)| text)
}

/// Python `gen_rust_ex`: (rust text, manifest text or None). The manifest (G6_SPEC 12.4) exists only for a program that
/// uses G6; externs: (name, path) as given with --rust-extern.
pub fn gen_rust_ex(
    prog: &Program,
    verified: bool,
    trust_callers: bool,
    budget: u64,
    foreign_checks: &str,
    externs: &[(String, String)],
) -> Result<(String, Option<String>), GenError> {
    gen_rust_ex_g4(prog, None, verified, trust_callers, budget, foreign_checks, externs)
}

/// `gen_rust_ex` for a program of explicit visibility mode (G4 A2): it always goes through the specialization plan, which
/// names every function and type by its Rust stem. `g4` = None is the legacy entry point.
pub fn gen_rust_ex_g4(
    prog: &Program,
    g4: Option<&crate::modules::G4>,
    verified: bool,
    trust_callers: bool,
    budget: u64,
    foreign_checks: &str,
    externs: &[(String, String)],
) -> Result<(String, Option<String>), GenError> {
    if !matches!(foreign_checks, "requires" | "all" | "off") {
        return Err(GenError::Msg("foreign_checks must be requires, all or off".to_string()));
    }
    if crate::typeinfo::first_g3_use(prog).is_some() || g4.is_some() {
        let plan = crate::mono::specialize_g4(prog, g4).map_err(|e| match e {
            crate::mono::MonoError::Limit(p) => GenError::Diag(p),
            crate::mono::MonoError::Internal(m) => GenError::Msg(m),
        })?;
        return gen_rust_concrete_ex(&plan.program, verified, trust_callers, budget, foreign_checks, externs);
    }
    gen_rust_concrete_ex(prog, verified, trust_callers, budget, foreign_checks, externs)
}

/// Pruv -> Rust source. Err is the str(e) at the place where Python raises an Exception. A generic program is
/// specialized first; a specialization limit is reported as "specialization_limit: <message>".
pub fn gen_rust(prog: &Program, verified: bool, trust_callers: bool, budget: u64) -> Result<String, String> {
    gen_rust_any(prog, verified, trust_callers, budget).map_err(|e| match e {
        GenError::Msg(m) => m,
        GenError::Diag(p) => format!("{}: {}", p.code, p.message),
    })
}

/// The generator proper, for a CONCRETE program (no type parameters; a plan.program of mono.rs, or a program without G3).
pub fn gen_rust_concrete(prog: &Program, verified: bool, trust_callers: bool, budget: u64) -> Result<String, String> {
    gen_rust_concrete_ex(prog, verified, trust_callers, budget, "requires", &[]).map(|(text, _)| text).map_err(|e| match e {
        GenError::Msg(m) => m,
        GenError::Diag(p) => format!("{}: {}", p.code, p.message),
    })
}

/// `gen_rust_concrete` with the G6 boundary check mode and the --rust-extern specs; also returns the manifest text
/// (only for a program that uses G6).
pub fn gen_rust_concrete_ex(
    prog: &Program,
    verified: bool,
    trust_callers: bool,
    budget: u64,
    foreign_checks: &str,
    externs: &[(String, String)],
) -> Result<(String, Option<String>), GenError> {
    if !matches!(foreign_checks, "requires" | "all" | "off") {
        return Err(GenError::Msg("foreign_checks must be requires, all or off".to_string()));
    }
    if let Some(e) = crate::typeinfo::g2_unimplemented_error(prog, "codegen", None, &["array_u8", "array_bool", "str"], None) { // G2 B2
        return Err(GenError::Msg(format!("unsupported_type: {}", e.message)));
    }
    // G4 A2: the identities behind the Rust names (panic text); cleared again when the generator returns
    struct DispGuard;
    impl Drop for DispGuard {
        fn drop(&mut self) {
            crate::emit_common::set_type_disp(HashMap::new());
        }
    }
    let _disp_guard = DispGuard;
    crate::emit_common::set_type_disp(prog.explicit.as_ref().map(|x| x.tdisp.clone()).unwrap_or_default());
    let mut g = Gen::new(prog, verified, trust_callers, budget, foreign_checks);
    let mut mark = 0usize;
    let res: R<()> = (|| {
        g.prelude()?;
        mark = g.out.len();
        for f in &prog.functions {
            g.func(f)?;
        }
        Ok(())
    })();
    if let Err(msg) = res {
        // G9: a runtime requires the Rust backend cannot lower is a diagnostic (Python PruvError)
        return Err(match g.diag.take() {
            Some(p) => GenError::Diag(p),
            None => GenError::Msg(msg),
        });
    }
    // G9: size / equality helpers discovered while the requires checks were generated go in front of the functions
    // (declaration order); nothing at all is added when no runtime requires needs them
    let g9_texts = g.g9_helper_texts();
    drop(g.out.splice(mark..mark, g9_texts));
    // P2: contract helpers of the bit builtins the requires checks used, in table order
    let bit_texts: Vec<String> = BIT_RUST
        .iter()
        .filter(|(k, _)| g.need_bits.contains(*k))
        .map(|(k, op)| {
            if shift_safe(k).is_some() {
                contract_shift_helper(k, op)
            } else if is_wrap_rust(k) {
                contract_wrap_helper(k)
            } else {
                contract_bit_helper(k, op)
            }
        })
        .collect();
    drop(g.out.splice(mark..mark, bit_texts));
    // P2 batch 2: --no-verify shift helpers used by the code, in table order
    let shift_texts: Vec<String> = BIT_RUST
        .iter()
        .filter(|(k, _)| g.need_shift.contains(*k))
        .filter_map(|(k, op)| shift_safe(k).map(|h| safe_shift_helper(h, op)))
        .collect();
    drop(g.out.splice(mark..mark, shift_texts));
    // P2 batch 4: the load_be contract helper, when a runtime contract used it
    if g.need_load_be {
        drop(g.out.splice(mark..mark, vec![CONTRACT_LOAD_HELPER.to_string()]));
    }
    let mut manifest: Option<String> = None;
    if g.g6 {
        // helpers are discovered while the functions are generated; they go in front of them, in first-use order
        let (texts, m) = match g.fg.as_ref() {
            Some(fg) => (fg.helper_texts(), fg.manifest(prog, externs)),
            None => (Vec::new(), String::new()),
        };
        drop(g.out.splice(mark..mark, texts));
        manifest = Some(m);
    }
    let mut s = g.out.join("\n");
    s.push('\n');
    Ok((s, manifest))
}

/// `e` denotes a fresh constructor value, or a field / variant_field part of one (Python `Gen.g9_owned`)
fn g9_owned(e: &Expr) -> bool {
    match e {
        Expr::EnumCtor(_) | Expr::StructLit(_) => true,
        Expr::VariantField(x) => g9_owned(&x.value),
        Expr::FieldAccess(x) => g9_owned(&x.base),
        _ => false,
    }
}

/// charge the shared contract budget `n` units (a Rust usize expression) before a buffer copy (Python `Gen.g9_charge`)
fn g9_charge(n: &str) -> String {
    format!(
        "{{ let pruv_n: usize = {}; pruv_budget = pruv_budget.saturating_sub(i64::try_from(pruv_n).unwrap_or(i64::MAX)); if pruv_budget < 0 {{ pruv_ud(\"contract iteration budget exceeded\") }} }}",
        n
    )
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
            params: vec![Param { name: "x".into(), ty: "i64".into(), refine: None, take: false, mode_pos: None }],
            ret: "i64".into(),
            effects: vec![],
            requires,
            ensures: vec![],
            body: vec![Stmt::Return(Return { line: 1, col: 1, value: Some(bin("+", var("x", "i64"), int("1"))) })],
            ret_refine: None,
            tparams: vec![],
            foreign: None,
            cost: None, decreases: None,
        };
        Program { functions: vec![f], types: vec![], refined: false, g9: None, explicit: None, uses_inout: None }
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
            params: vec![Param { name: "a".into(), ty: aty.into(), refine: None, take: false, mode_pos: None }],
            ret: "i64".into(),
            effects: vec![],
            requires: vec![],
            ensures: vec![],
            body: vec![Stmt::Return(Return { line: 1, col: 1, value: Some(idx) })],
            ret_refine: None,
            tparams: vec![],
            foreign: None,
            cost: None, decreases: None,
        };
        Program { functions: vec![f], types: vec![], refined: false, g9: None, explicit: None, uses_inout: None }
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
