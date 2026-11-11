//! G3 A0: the structured type and its shared API (counterpart of the G3 part of vast.py / typeinfo.py, G3_SPEC 7.2).
//!
//! Nothing in the existing pipeline uses this module yet (A1 will); it is independent of the checker.
//! Declarations are described by a lookup `name -> Some((nparams, fields))`, where `fields` is the flat list of
//! field types of the declaration (all variants for an enum), written with `mk_param(&decl_owner(name), i, <param name>)`
//! for its i-th type parameter.

use std::collections::HashMap;
use std::fmt;
use std::hash::{Hash, Hasher};

use crate::typeinfo::BUILTIN_TYPE_NAMES;

/// A structured type, mirroring Python's `Type(name, args, owner, index)`.
///
/// * legacy types: `name` only (`i64`, `bool`, `unit`, `array`, `option`, `result`, `array_u8`, `array_bool`, `str`, `u8`,
///   or a non-generic user type name), `args` empty;
/// * structured types: `args` holds the type arguments (`Option<X>`, `Result<X>`, `[X]` -> `[X]`; `D<X0,..>` -> `[X0,..]`);
/// * a bound type parameter: `owner` is the declaration identity (`fn:<name>` / `type:<name>`) and `index` its position;
///   `name` is only for printing.
///
/// Build structured types with the `mk_*` functions: they normalize to the legacy form
/// (`Option<i64>` -> `option`, `Result<i64>` -> `result`, `[i64]`/`[u8]`/`[bool]` -> `array`/`array_u8`/`array_bool`).
///
/// Equality and hashing are structural; a parameter's identity is (owner, index), its name is ignored.
#[derive(Debug, Clone)]
pub struct GType {
    pub name: String,
    pub args: Vec<GType>,
    pub owner: Option<String>,
    pub index: usize,
}

impl PartialEq for GType {
    fn eq(&self, other: &GType) -> bool {
        if self.owner.is_some() || other.owner.is_some() {
            return self.owner == other.owner && self.index == other.index;
        }
        self.name == other.name && self.args == other.args
    }
}

impl Eq for GType {}

impl Hash for GType {
    fn hash<H: Hasher>(&self, state: &mut H) {
        match &self.owner {
            Some(o) => {
                1u8.hash(state);
                o.hash(state);
                self.index.hash(state);
            }
            None => {
                0u8.hash(state);
                self.name.hash(state);
                self.args.hash(state);
            }
        }
    }
}

impl GType {
    /// A raw type with no normalization (a legacy name, or an application built by hand).
    pub fn new(name: &str, args: Vec<GType>) -> GType {
        GType { name: name.to_string(), args, owner: None, index: 0 }
    }
    pub fn i64() -> GType {
        GType::new("i64", Vec::new())
    }
    pub fn bool() -> GType {
        GType::new("bool", Vec::new())
    }
    pub fn unit() -> GType {
        GType::new("unit", Vec::new())
    }
    pub fn u8() -> GType {
        GType::new("u8", Vec::new())
    }
    pub fn str() -> GType {
        GType::new("str", Vec::new())
    }
    /// Legacy `[i64]`.
    pub fn array() -> GType {
        GType::new("array", Vec::new())
    }
    /// Legacy `Option<i64>`.
    pub fn option() -> GType {
        GType::new("option", Vec::new())
    }
    /// Legacy `Result<i64>`.
    pub fn result() -> GType {
        GType::new("result", Vec::new())
    }
    pub fn array_u8() -> GType {
        GType::new("array_u8", Vec::new())
    }
    pub fn array_bool() -> GType {
        GType::new("array_bool", Vec::new())
    }

    /// Whether this is a bound type parameter.
    pub fn is_param(&self) -> bool {
        self.owner.is_some()
    }

    /// Whether this names a user struct/enum (declared or not); not a built-in name and not a parameter.
    pub fn is_user_type(&self) -> bool {
        self.owner.is_none() && !BUILTIN_TYPE_NAMES.contains(&self.name.as_str())
    }

    /// Whether this is an array type (legacy or structured).
    pub fn is_array(&self) -> bool {
        matches!(self.name.as_str(), "array" | "array_u8" | "array_bool")
    }

    /// Element type of an array type; None when this is not an array type.
    pub fn array_elem(&self) -> Option<GType> {
        if self.name == "array" && !self.args.is_empty() {
            return Some(self.args[0].clone());
        }
        match self.name.as_str() {
            "array" => Some(GType::i64()),
            "array_u8" => Some(GType::u8()),
            "array_bool" => Some(GType::bool()),
            _ => None,
        }
    }

    /// Legacy array type holding `elem`; None when no such legacy array type exists.
    pub fn array_of(elem: &GType) -> Option<GType> {
        if *elem == GType::i64() {
            Some(GType::array())
        } else if *elem == GType::u8() {
            Some(GType::array_u8())
        } else if *elem == GType::bool() {
            Some(GType::array_bool())
        } else {
            None
        }
    }
}

// ---------- keys: the string form carried in the AST (ast.rs `Type = String`) ----------

/// Whether an AST type string is a structured (G3) key rather than a legacy plain name.
pub fn is_g3_key(s: &str) -> bool {
    s.contains('<') || s.contains('\u{1}')
}

impl GType {
    /// The AST string of this type: the plain name for a legacy type (unchanged from before G3),
    /// `name<k0,k1>` for an application, `\u{1}owner\u{1}index\u{1}name` for a bound parameter.
    pub fn to_key(&self) -> String {
        if let Some(o) = &self.owner {
            return format!("\u{1}{}\u{1}{}\u{1}{}", o, self.index, self.name);
        }
        if self.args.is_empty() {
            return self.name.clone();
        }
        let inner = self.args.iter().map(|a| a.to_key()).collect::<Vec<_>>().join(",");
        format!("{}<{}>", self.name, inner)
    }

    /// Inverse of `to_key` (a legacy plain name parses to the legacy type).
    pub fn from_key(s: &str) -> GType {
        let b = s.as_bytes();
        let mut i = 0usize;
        parse_key(b, &mut i)
    }
}

fn take_until(b: &[u8], i: &mut usize, stop: &dyn Fn(u8) -> bool) -> String {
    let start = *i;
    while *i < b.len() && !stop(b[*i]) {
        *i += 1;
    }
    String::from_utf8_lossy(&b[start..*i]).to_string()
}

fn parse_key(b: &[u8], i: &mut usize) -> GType {
    if *i < b.len() && b[*i] == 1 {
        *i += 1;
        let owner = take_until(b, i, &|c| c == 1);
        *i += 1;
        let index: usize = take_until(b, i, &|c| c == 1).parse().unwrap_or(0);
        *i += 1;
        let name = take_until(b, i, &|c| c == b',' || c == b'>');
        return GType { name, args: Vec::new(), owner: Some(owner), index };
    }
    let name = take_until(b, i, &|c| c == b'<' || c == b',' || c == b'>');
    let mut args = Vec::new();
    if *i < b.len() && b[*i] == b'<' {
        *i += 1;
        loop {
            args.push(parse_key(b, i));
            if *i < b.len() && b[*i] == b',' {
                *i += 1;
                continue;
            }
            break;
        }
        if *i < b.len() && b[*i] == b'>' {
            *i += 1;
        }
    }
    GType { name, args, owner: None, index: 0 }
}

// ---------- constructors ----------

/// A bound type parameter: identity is (owner, index); the name is for printing.
pub fn mk_param(owner: &str, index: usize, name: &str) -> GType {
    GType { name: name.to_string(), args: Vec::new(), owner: Some(owner.to_string()), index }
}

pub fn mk_option(x: GType) -> GType {
    if x == GType::i64() {
        GType::option()
    } else {
        GType::new("option", vec![x])
    }
}

pub fn mk_result(x: GType) -> GType {
    if x == GType::i64() {
        GType::result()
    } else {
        GType::new("result", vec![x])
    }
}

pub fn mk_array(x: GType) -> GType {
    if x == GType::i64() {
        GType::array()
    } else if x == GType::u8() {
        GType::array_u8()
    } else if x == GType::bool() {
        GType::array_bool()
    } else {
        GType::new("array", vec![x])
    }
}

/// User struct/enum type applied to `args` (empty for a non-generic declaration).
pub fn mk_nominal(name: &str, args: Vec<GType>) -> GType {
    GType::new(name, args)
}

// ---------- owners, identity ----------

/// Wrong number of type arguments (or an undeclared name where a declaration is required).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TypeArityError(pub String);

impl fmt::Display for TypeArityError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for TypeArityError {}

/// Identity of a bound parameter: (declaration owner, index).
pub type ParamId = (String, usize);

/// Substitution mapping: parameter identity -> replacement type.
pub type Mapping = HashMap<ParamId, GType>;

/// Declaration lookup: `name -> Some((nparams, flat field types))`, or None when undeclared.
pub type Decls<'a> = &'a dyn Fn(&str) -> Option<(usize, Vec<GType>)>;

pub fn decl_owner(name: &str) -> String {
    format!("type:{}", name)
}

pub fn fn_owner(name: &str) -> String {
    format!("fn:{}", name)
}

/// Identity of a bound parameter; None when `ty` is not a parameter.
pub fn param_id(ty: &GType) -> Option<ParamId> {
    ty.owner.as_ref().map(|o| (o.clone(), ty.index))
}

/// Structural equality; parameters are equal iff owner and index are equal.
pub fn type_eq(a: &GType, b: &GType) -> bool {
    a == b
}

// ---------- printing ----------

fn builtin_print(name: &str) -> &str {
    match name {
        "i64" => "i64",
        "bool" => "bool",
        "unit" => "()",
        "array" => "[i64]",
        "option" => "Option<i64>",
        "result" => "Result<i64>",
        "array_u8" => "[u8]",
        "array_bool" => "[bool]",
        "str" => "str",
        other => other,
    }
}

/// Source spelling: "Pair<i64, bool>", "[T]", "Option<bool>". Legacy types print as in the old dumps.
pub fn format_type(ty: &GType) -> String {
    if ty.owner.is_some() {
        return ty.name.clone();
    }
    if ty.args.is_empty() {
        return builtin_print(&ty.name).to_string();
    }
    let inner = ty.args.iter().map(format_type).collect::<Vec<_>>().join(", ");
    match ty.name.as_str() {
        "array" => format!("[{}]", inner),
        "option" => format!("Option<{}>", inner),
        "result" => format!("Result<{}>", inner),
        other => format!("{}<{}>", other, inner),
    }
}

// ---------- substitution, arity ----------

fn is_nominal(ty: &GType) -> bool {
    ty.owner.is_none() && !BUILTIN_TYPE_NAMES.contains(&ty.name.as_str())
}

/// Substitution mapping for a declaration's parameters; TypeArityError on a count mismatch.
pub fn bind_args(owner: &str, nparams: usize, args: &[GType]) -> Result<Mapping, TypeArityError> {
    if args.len() != nparams {
        return Err(TypeArityError(format!(
            "{} expects {} type argument(s), got {}",
            owner,
            nparams,
            args.len()
        )));
    }
    Ok(args.iter().enumerate().map(|(i, a)| ((owner.to_string(), i), a.clone())).collect())
}

/// Simultaneous substitution. Parameters carry declaration identity, so equal parameter names of different
/// declarations never collide, and replacements are not re-substituted.
pub fn substitute(ty: &GType, mapping: &Mapping) -> GType {
    if let Some(o) = &ty.owner {
        return match mapping.get(&(o.clone(), ty.index)) {
            Some(r) => r.clone(),
            None => ty.clone(),
        };
    }
    if ty.args.is_empty() {
        return ty.clone();
    }
    let mut args: Vec<GType> = ty.args.iter().map(|a| substitute(a, mapping)).collect();
    match ty.name.as_str() {
        "array" => mk_array(args.swap_remove(0)),
        "option" => mk_option(args.swap_remove(0)),
        "result" => mk_result(args.swap_remove(0)),
        other => mk_nominal(other, args),
    }
}

/// Err if any Option/Result/array/nominal application inside `ty` has the wrong argument count.
/// Nominal names unknown to `decls` are skipped (the checker reports them).
pub fn check_arity(ty: &GType, decls: Decls) -> Result<(), TypeArityError> {
    if ty.owner.is_none()
        && !ty.args.is_empty()
        && matches!(ty.name.as_str(), "option" | "result" | "array")
        && ty.args.len() != 1
    {
        return Err(TypeArityError(format!("{} expects 1 type argument, got {}", ty.name, ty.args.len())));
    }
    if is_nominal(ty) {
        if let Some((n, _)) = decls(&ty.name) {
            if n != ty.args.len() {
                return Err(TypeArityError(format!(
                    "{} expects {} type argument(s), got {}",
                    ty.name,
                    n,
                    ty.args.len()
                )));
            }
        }
    }
    for a in &ty.args {
        check_arity(a, decls)?;
    }
    Ok(())
}

/// Field types of a nominal application with its arguments substituted.
/// Err on an arity mismatch, or when the declaration is unknown.
pub fn nominal_fields(ty: &GType, decls: Decls) -> Result<Vec<GType>, TypeArityError> {
    let (nparams, fields) = match decls(&ty.name) {
        Some(d) => d,
        None => return Err(TypeArityError(format!("unknown declaration {}", ty.name))),
    };
    let m = bind_args(&decl_owner(&ty.name), nparams, &ty.args)?;
    Ok(fields.iter().map(|f| substitute(f, &m)).collect())
}

// ---------- admissibility ----------

fn is_value_seen(ty: &GType, decls: Decls, seen: &[String]) -> bool {
    if *ty == GType::i64() || *ty == GType::bool() || ty.owner.is_some() {
        return true;
    }
    if ty.name == "option" || ty.name == "result" {
        return ty.args.iter().all(|a| is_value_seen(a, decls, seen));
    }
    if !is_nominal(ty) {
        return false;
    }
    match decls(&ty.name) {
        Some((n, _)) if n == ty.args.len() && !seen.contains(&ty.name) => {}
        _ => return false,
    }
    if !ty.args.iter().all(|a| is_value_seen(a, decls, seen)) {
        return false;
    }
    let mut inner: Vec<String> = seen.to_vec();
    inner.push(ty.name.clone());
    match nominal_fields(ty, decls) {
        Ok(fields) => fields.iter().all(|f| is_value_seen(f, decls, &inner)),
        Err(_) => false,
    }
}

/// Admissible value (G3_SPEC 3.1): i64, bool, Option<V>, Result<V>, D<V..> whose substituted fields are
/// values, or a type parameter (it ranges over values). Not arrays, str, unit, u8.
pub fn is_value(ty: &GType, decls: Decls) -> bool {
    is_value_seen(ty, decls, &[])
}

/// Element (G3_SPEC 3.2): exactly i64, bool, or a parameter whose identity is in `element_params`.
pub fn is_element(ty: &GType, element_params: &[ParamId]) -> bool {
    if *ty == GType::i64() || *ty == GType::bool() {
        return true;
    }
    match param_id(ty) {
        Some(id) => element_params.contains(&id),
        None => false,
    }
}

/// Names of nominal declarations referenced anywhere inside `ty` (nested args included),
/// in first-occurrence (pre-order) order, without duplicates.
pub fn dependencies(ty: &GType) -> Vec<String> {
    fn walk(t: &GType, out: &mut Vec<String>) {
        if is_nominal(t) && !out.contains(&t.name) {
            out.push(t.name.clone());
        }
        for a in &t.args {
            walk(a, out);
        }
    }
    let mut out = Vec::new();
    walk(ty, &mut out);
    out
}

// ---------- canonical encoding, stems ----------

/// Canonical specialization encoding (G3_SPEC 5.2); only concrete value types are encodable (Err otherwise).
pub fn encode(ty: &GType) -> Result<String, String> {
    if *ty == GType::i64() {
        return Ok("i".to_string());
    }
    if *ty == GType::bool() {
        return Ok("b".to_string());
    }
    if ty.owner.is_none() && (ty.name == "option" || ty.name == "result") {
        let prefix = if ty.name == "option" { "o" } else { "r" };
        let inner = match ty.args.first() {
            Some(a) => encode(a)?,
            None => "i".to_string(),
        };
        return Ok(format!("{}{}", prefix, inner));
    }
    if is_nominal(ty) {
        let mut s = format!("n{}_{}_{}", ty.name.len(), ty.name, ty.args.len());
        for a in &ty.args {
            s.push('_');
            s.push_str(&encode(a)?);
        }
        return Ok(s);
    }
    Err(format!("type {} has no specialization encoding", format_type(ty)))
}

fn stem(kind: &str, name: &str, args: &[GType]) -> Result<String, String> {
    let mut s = format!("pruv_g3_{}_{}_{}_{}", kind, name.len(), name, args.len());
    for a in args {
        s.push('_');
        s.push_str(&encode(a)?);
    }
    Ok(s)
}

/// `pruv_g3_f_<len>_<name>_<arity>_<encoded args>` (no trailing part when the arity is 0).
pub fn spec_fn_stem(name: &str, args: &[GType]) -> Result<String, String> {
    stem("f", name, args)
}

/// `pruv_g3_t_<len>_<name>_<arity>_<encoded args>`.
pub fn spec_type_stem(name: &str, args: &[GType]) -> Result<String, String> {
    stem("t", name, args)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashSet;

    // struct Pair<T, U> { a: T, b: U }; enum Choice<T> { Left(T), Right(i64) }; struct Wrap<T> { p: Pair<T, T> }
    // struct Point { x: i64 }; struct Bad { a: [i64] }; struct Cyc<T> { c: Cyc<T> }; struct Arr<T> { xs: [T] }
    fn p(decl: &str, i: usize, name: &str) -> GType {
        mk_param(&decl_owner(decl), i, name)
    }

    fn decls(n: &str) -> Option<(usize, Vec<GType>)> {
        match n {
            "Pair" => Some((2, vec![p("Pair", 0, "T"), p("Pair", 1, "U")])),
            "Choice" => Some((1, vec![p("Choice", 0, "T"), GType::i64()])),
            "Wrap" => {
                let wt = p("Wrap", 0, "T");
                Some((1, vec![mk_nominal("Pair", vec![wt.clone(), wt])]))
            }
            "Point" => Some((0, vec![GType::i64()])),
            "Bad" => Some((0, vec![GType::array()])),
            "Cyc" => Some((1, vec![mk_nominal("Cyc", vec![p("Cyc", 0, "T")])])),
            "Arr" => Some((1, vec![mk_array(p("Arr", 0, "T"))])),
            _ => None,
        }
    }

    fn ft() -> GType {
        mk_param(&fn_owner("f"), 0, "T")
    }
    fn gt() -> GType {
        mk_param(&fn_owner("g"), 0, "T")
    }
    fn point() -> GType {
        mk_nominal("Point", vec![])
    }
    fn nom(name: &str, args: Vec<GType>) -> GType {
        mk_nominal(name, args)
    }
    fn map1(k: &GType, v: GType) -> Mapping {
        let mut m = Mapping::new();
        m.insert(param_id(k).unwrap(), v);
        m
    }
    fn hash_of(t: &GType) -> u64 {
        use std::collections::hash_map::DefaultHasher;
        let mut h = DefaultHasher::new();
        t.hash(&mut h);
        h.finish()
    }

    #[test]
    fn legacy_constants_unchanged() {
        assert_eq!(GType::i64().name, "i64");
        assert!(GType::i64().args.is_empty());
        assert_eq!(GType::new("array", vec![]), GType::array());
        assert_eq!(hash_of(&GType::new("option", vec![])), hash_of(&GType::option()));
        assert_eq!(point(), GType::new("Point", vec![]));
    }

    #[test]
    fn option_i64_normalizes() {
        assert_eq!(mk_option(GType::i64()), GType::option());
    }

    #[test]
    fn result_i64_normalizes() {
        assert_eq!(mk_result(GType::i64()), GType::result());
    }

    #[test]
    fn arrays_normalize() {
        assert_eq!(mk_array(GType::i64()), GType::array());
        assert_eq!(mk_array(GType::u8()), GType::array_u8());
        assert_eq!(mk_array(GType::bool()), GType::array_bool());
    }

    #[test]
    fn option_bool_is_structured() {
        let t = mk_option(GType::bool());
        assert_ne!(t, GType::option());
        assert_eq!(t.args, vec![GType::bool()]);
        assert_eq!(t, mk_option(GType::bool()));
        assert_eq!(hash_of(&t), hash_of(&mk_option(GType::bool())));
    }

    #[test]
    fn legacy_dump_strings() {
        let tys = [
            GType::i64(),
            GType::bool(),
            GType::unit(),
            GType::array(),
            GType::option(),
            GType::result(),
            GType::array_u8(),
            GType::array_bool(),
            GType::str(),
            point(),
        ];
        let got: Vec<String> = tys.iter().map(format_type).collect();
        assert_eq!(
            got,
            ["i64", "bool", "()", "[i64]", "Option<i64>", "Result<i64>", "[u8]", "[bool]", "str", "Point"]
        );
    }

    #[test]
    fn format_structured() {
        assert_eq!(format_type(&nom("Pair", vec![GType::i64(), GType::bool()])), "Pair<i64, bool>");
        assert_eq!(format_type(&mk_array(ft())), "[T]");
        assert_eq!(format_type(&mk_option(GType::bool())), "Option<bool>");
        assert_eq!(format_type(&mk_result(p("Pair", 0, "T"))), "Result<T>");
        assert_eq!(format_type(&nom("Choice", vec![mk_option(GType::bool())])), "Choice<Option<bool>>");
    }

    #[test]
    fn substitute_param_case() {
        assert_eq!(substitute(&ft(), &map1(&ft(), GType::bool())), GType::bool());
    }

    #[test]
    fn substitute_through_args() {
        let t = nom("Pair", vec![ft(), mk_array(ft())]);
        assert_eq!(
            substitute(&t, &map1(&ft(), GType::i64())),
            nom("Pair", vec![GType::i64(), GType::array()])
        );
    }

    #[test]
    fn substitute_normalizes_legacy() {
        assert_eq!(substitute(&mk_option(ft()), &map1(&ft(), GType::i64())), GType::option());
        assert_eq!(substitute(&mk_result(ft()), &map1(&ft(), GType::i64())), GType::result());
        assert_eq!(substitute(&mk_array(ft()), &map1(&ft(), GType::u8())), GType::array_u8());
    }

    #[test]
    fn capture_avoidance_same_name() {
        // f's T and g's T are both printed "T" but have different identity
        let t = nom("Pair", vec![ft(), gt()]);
        let out = substitute(&t, &map1(&ft(), GType::i64()));
        assert_ne!(ft(), gt());
        assert_eq!(out, nom("Pair", vec![GType::i64(), gt()]));
    }

    #[test]
    fn capture_avoidance_simultaneous() {
        // T := (g's T) is not re-substituted by g's T := bool
        let t = nom("Pair", vec![ft(), gt()]);
        let mut m = Mapping::new();
        m.insert(param_id(&ft()).unwrap(), gt());
        m.insert(param_id(&gt()).unwrap(), GType::bool());
        assert_eq!(substitute(&t, &m), nom("Pair", vec![gt(), GType::bool()]));
    }

    #[test]
    fn unmapped_param_kept() {
        let pt = p("Pair", 0, "T");
        assert_eq!(substitute(&pt, &map1(&p("Pair", 1, "U"), GType::i64())), pt);
    }

    #[test]
    fn same_name_two_declarations_distinct() {
        assert_ne!(p("Pair", 0, "T"), p("Choice", 0, "T"));
        assert_ne!(p("Pair", 0, "T"), p("Pair", 1, "T"));
        let set: HashSet<GType> = [p("Pair", 0, "T"), p("Choice", 0, "T"), p("Pair", 0, "T")].into_iter().collect();
        assert_eq!(set.len(), 2);
    }

    #[test]
    fn repeated_parameter() {
        let pt = p("Pair", 0, "T");
        let m = bind_args(&decl_owner("Pair"), 2, &[GType::bool(), GType::bool()]).unwrap();
        assert_eq!(
            substitute(&nom("Pair", vec![pt.clone(), pt.clone()]), &map1(&pt, GType::i64())),
            nom("Pair", vec![GType::i64(), GType::i64()])
        );
        assert_eq!(
            nominal_fields(&nom("Pair", vec![GType::bool(), GType::bool()]), &decls).unwrap(),
            vec![GType::bool(), GType::bool()]
        );
        assert_eq!(m[&(decl_owner("Pair"), 1)], GType::bool());
    }

    #[test]
    fn nested_application_fields() {
        let t = nom("Wrap", vec![mk_option(GType::bool())]);
        assert_eq!(
            nominal_fields(&t, &decls).unwrap(),
            vec![nom("Pair", vec![mk_option(GType::bool()), mk_option(GType::bool())])]
        );
    }

    #[test]
    fn nested_substitution() {
        let t = nom("Choice", vec![nom("Pair", vec![ft(), mk_option(ft())])]);
        let out = substitute(&t, &map1(&ft(), GType::bool()));
        assert_eq!(out, nom("Choice", vec![nom("Pair", vec![GType::bool(), mk_option(GType::bool())])]));
    }

    #[test]
    fn arity_errors() {
        assert!(bind_args(&decl_owner("Pair"), 2, &[GType::i64()]).is_err());
        assert!(check_arity(&nom("Pair", vec![GType::i64()]), &decls).is_err());
        assert!(check_arity(&nom("Point", vec![GType::i64()]), &decls).is_err());
        assert!(check_arity(&mk_option(nom("Choice", vec![])), &decls).is_err());
        assert!(check_arity(&GType::new("option", vec![GType::i64(), GType::bool()]), &decls).is_err());
        assert!(check_arity(&nom("Pair", vec![GType::i64(), GType::bool()]), &decls).is_ok());
        assert_eq!(
            bind_args(&decl_owner("Pair"), 2, &[GType::i64()]).unwrap_err().to_string(),
            "type:Pair expects 2 type argument(s), got 1"
        );
    }

    #[test]
    fn admissible_scalars_and_builtins() {
        assert!(is_value(&GType::i64(), &decls));
        assert!(is_value(&GType::bool(), &decls));
        assert!(is_value(&GType::option(), &decls));
        assert!(is_value(&GType::result(), &decls));
        assert!(is_value(&mk_option(GType::bool()), &decls));
        assert!(is_value(&mk_result(mk_option(GType::bool())), &decls));
    }

    #[test]
    fn inadmissible_types() {
        let tys = [
            GType::array(),
            GType::array_u8(),
            GType::array_bool(),
            GType::str(),
            GType::unit(),
            GType::u8(),
            mk_option(GType::u8()),
            mk_option(GType::array()),
            mk_option(GType::str()),
        ];
        assert!(!tys.iter().any(|t| is_value(t, &decls)));
    }

    #[test]
    fn admissible_nominal() {
        assert!(is_value(&point(), &decls));
        assert!(is_value(&nom("Pair", vec![GType::i64(), mk_option(GType::bool())]), &decls));
        assert!(is_value(&nom("Wrap", vec![GType::bool()]), &decls));
        assert!(is_value(&ft(), &decls));
    }

    #[test]
    fn inadmissible_nominal() {
        assert!(!is_value(&nom("Bad", vec![]), &decls)); // field is an array
        assert!(!is_value(&nom("Pair", vec![GType::i64(), GType::str()]), &decls)); // array-like argument
        assert!(!is_value(&nom("Arr", vec![GType::i64()]), &decls)); // substituted field is [i64]
        assert!(!is_value(&nom("Pair", vec![GType::i64()]), &decls)); // wrong arity
        assert!(!is_value(&nom("Nope", vec![]), &decls)); // unknown declaration
        assert!(!is_value(&nom("Cyc", vec![GType::i64()]), &decls)); // cycle guard
    }

    #[test]
    fn admissible_with_closure_decls() {
        let table: HashMap<String, (usize, Vec<GType>)> =
            ["Pair"].iter().map(|n| (n.to_string(), decls(n).unwrap())).collect();
        let f = |n: &str| table.get(n).cloned();
        assert!(is_value(&nom("Pair", vec![GType::i64(), GType::bool()]), &f));
    }

    #[test]
    fn element_check() {
        let ep = vec![param_id(&ft()).unwrap()];
        assert!(is_element(&GType::i64(), &[]));
        assert!(is_element(&GType::bool(), &[]));
        assert!(is_element(&ft(), &ep));
        assert!(!is_element(&ft(), &[]));
        assert!(!is_element(&gt(), &ep));
        assert!(!is_element(&point(), &[]));
        assert!(!is_element(&GType::u8(), &[]));
        assert!(!is_element(&mk_option(GType::i64()), &[]));
        assert!(!is_element(&GType::array(), &[]));
    }

    #[test]
    fn dependencies_nested() {
        let t = nom(
            "Pair",
            vec![mk_option(point()), nom("Choice", vec![nom("Pair", vec![GType::i64(), point()])])],
        );
        assert_eq!(dependencies(&t), ["Pair", "Point", "Choice"]);
        assert!(dependencies(&mk_array(GType::i64())).is_empty());
        assert!(dependencies(&mk_array(ft())).is_empty());
        assert_eq!(dependencies(&mk_result(nom("Wrap", vec![GType::bool()]))), ["Wrap"]);
    }

    #[test]
    fn encode_scalars_and_builtins() {
        assert_eq!(encode(&GType::i64()).unwrap(), "i");
        assert_eq!(encode(&GType::bool()).unwrap(), "b");
        assert_eq!(encode(&mk_option(GType::bool())).unwrap(), "ob");
        assert_eq!(encode(&mk_result(mk_option(GType::i64()))).unwrap(), "roi");
        assert_eq!(encode(&GType::option()).unwrap(), "oi");
        assert_eq!(encode(&GType::result()).unwrap(), "ri");
    }

    #[test]
    fn encode_nominal() {
        assert_eq!(encode(&point()).unwrap(), "n5_Point_0");
        assert_eq!(encode(&nom("Pair", vec![GType::i64(), GType::bool()])).unwrap(), "n4_Pair_2_i_b");
        assert_eq!(
            encode(&nom("Choice", vec![nom("Pair", vec![GType::bool(), mk_option(GType::i64())])])).unwrap(),
            "n6_Choice_1_n4_Pair_2_b_oi"
        );
    }

    #[test]
    fn encode_name_with_underscore_and_utf8() {
        assert_eq!(encode(&nom("A_b", vec![GType::i64()])).unwrap(), "n3_A_b_1_i");
        assert_eq!(encode(&nom("é", vec![])).unwrap(), "n2_é_0");
    }

    #[test]
    fn encode_rejects_non_values() {
        assert!(encode(&ft()).is_err());
        assert!(encode(&GType::array()).is_err());
        assert!(encode(&mk_option(GType::str())).is_err());
    }

    #[test]
    fn stem_examples() {
        assert_eq!(spec_fn_stem("identity", &[GType::i64()]).unwrap(), "pruv_g3_f_8_identity_1_i");
        assert_eq!(spec_type_stem("Pair", &[GType::i64(), GType::bool()]).unwrap(), "pruv_g3_t_4_Pair_2_i_b");
        assert_eq!(spec_fn_stem("f", &[]).unwrap(), "pruv_g3_f_1_f_0");
    }

    #[test]
    fn legacy_helpers_still_work() {
        assert!(GType::array_u8().is_array());
        assert_eq!(GType::array().array_elem(), Some(GType::i64()));
        assert_eq!(GType::array_bool().array_elem(), Some(GType::bool()));
        assert_eq!(GType::array_of(&GType::u8()), Some(GType::array_u8()));
        assert!(!GType::option().is_user_type());
        assert!(point().is_user_type());
        assert!(!ft().is_user_type());
        assert_eq!(mk_array(ft()).array_elem(), Some(ft()));
        assert!(mk_array(ft()).is_array());
    }
}
