//! Common Python-output functions (counterparts of codegen.py's rty, cty, conv, emit_public_types, show,
//! match_sorted_requires, rstr). The output must be byte-identical to Python's.

use crate::ast::*;
use crate::gtype::{is_g3_key, GType};
use crate::typeinfo::{is_user_type, TypeTable};

/// G3: a generic specialization function (stem `pruv_g3_f_...`); such functions are private Rust items.
/// The prefix `pruv_` is reserved, so no user function can carry it.
pub fn is_spec_fn(name: &str) -> bool {
    name.starts_with("pruv_g3_f_")
}

thread_local! {
    /// G4 A2: Rust name of a nominal type -> its source-qualified identity, for the program being generated (Python keeps it
    /// as `src_name` on the specialized nodes). Empty outside explicit visibility mode.
    static TYPE_DISP: std::cell::RefCell<std::collections::HashMap<String, String>> =
        std::cell::RefCell::new(std::collections::HashMap::new());
}

/// G4 A2: registers the identities of the explicit-mode program about to be generated (an empty map clears them).
pub fn set_type_disp(m: std::collections::HashMap<String, String>) {
    TYPE_DISP.with(|t| *t.borrow_mut() = m);
}

/// G4 A3 (Python `getattr(d, "disp", name)`): the registered source-qualified identity of a nominal type, or the name itself
/// outside explicit visibility mode (unlike `src_name`, a G3 stem is NOT unwrapped here).
pub fn type_disp(name: &str) -> String {
    TYPE_DISP.with(|t| t.borrow().get(name).cloned()).unwrap_or_else(|| name.to_string())
}

/// G3: the declaration name a generated type stem (`pruv_g3_t_<len>_<name>_...`) was made from; any other name as is.
/// G4 A2: in explicit mode the identity the type was declared with (`crate::m::Name`).
/// Used where Python keeps `src_name` (panic messages of requires).
pub fn src_name(name: &str) -> String {
    if let Some(d) = TYPE_DISP.with(|t| t.borrow().get(name).cloned()) {
        return d;
    }
    if let Some(rest) = name.strip_prefix("pruv_g3_t_") {
        if let Some(us) = rest.find('_') {
            if let Ok(n) = rest[..us].parse::<usize>() {
                let start = us + 1;
                if let Some(s) = rest.get(start..start + n) {
                    return s.to_string();
                }
            }
        }
    }
    name.to_string()
}

/// The type name of a key: the text before the argument list (`option` for `option<bool>`).
pub fn key_name(t: &str) -> &str {
    t.split('<').next().unwrap_or(t)
}

/// A user struct/enum name; a structured key (`option<bool>`) is not one.
pub fn is_user_key(t: &str) -> bool {
    !is_g3_key(t) && is_user_type(t)
}

fn structured_builtin(g: &GType) -> bool {
    g.owner.is_none() && !g.args.is_empty() && (g.name == "option" || g.name == "result")
}

/// Rust type spelling of a structured type (G3): Option<X> / Result<X> with X != i64.
pub fn rty_g(g: &GType, param: bool) -> String {
    if structured_builtin(g) {
        let x = rty_g(&g.args[0], false);
        if g.name == "option" {
            return format!("::std::option::Option<{}>", x);
        }
        return format!("::std::result::Result<{}, i64>", x);
    }
    // G6: owned collections; a borrowed parameter is a reference
    if g.owner.is_none() {
        let r = match (g.name.as_str(), g.args.len()) {
            ("vec", 1) => Some(format!("::std::vec::Vec<{}>", rty_g(&g.args[0], false))),
            ("hashmap", 2) => Some(format!(
                "::std::collections::HashMap<{}, {}>",
                rty_g(&g.args[0], false),
                rty_g(&g.args[1], false)
            )),
            _ => None,
        };
        if let Some(r) = r {
            return if param { format!("&{}", r) } else { r };
        }
    }
    rty_name(&g.name, param)
}

/// Rust type spelling for execution. It covers all 6 built-ins and user types, so there is no failure path.
pub fn rty(t: &str, param: bool) -> String {
    if is_g3_key(t) {
        if let Ok(g) = GType::try_from_key(t) {
            return rty_g(&g, param);
        }
    }
    rty_name(t, param)
}

fn rty_name(t: &str, param: bool) -> String {
    match t {
        "i64" => "i64".to_string(),
        "bool" => "bool".to_string(),
        "unit" => "()".to_string(),
        "option" => "::std::option::Option<i64>".to_string(),
        "result" => "::std::result::Result<i64, i64>".to_string(),
        "array" => {
            if param { "&[i64]".to_string() } else { "::std::vec::Vec<i64>".to_string() }
        }
        "array_u8" => {
            if param { "&[u8]".to_string() } else { "::std::vec::Vec<u8>".to_string() }
        }
        // G2 A5: stated explicitly instead of relying on the fallback
        "array_bool" => {
            if param { "&[bool]".to_string() } else { "::std::vec::Vec<bool>".to_string() }
        }
        // G2 B2: str is &str as a parameter, String as a local or return value
        "str" => {
            if param { "&str".to_string() } else { "::std::string::String".to_string() }
        }
        // G10: File is owned; a borrowed parameter is a reference
        "file" => {
            if param { "&PruvFile".to_string() } else { "PruvFile".to_string() }
        }
        // G6: String is owned; a borrowed parameter is a reference
        "string" => {
            if param { "&::std::string::String".to_string() } else { "::std::string::String".to_string() }
        }
        other => other.to_string(),
    }
}

/// A Type printed with Python's `%r`.
fn type_repr(t: &str) -> String {
    format!("Type(name='{}')", t)
}

/// Contract (i128) mirror of a structured type (G3): C(Option<X>) = Option<C(X)>, C(Result<X>) = Result<C(X), i128>.
pub fn try_cty_g(g: &GType) -> Result<String, String> {
    if structured_builtin(g) {
        let x = try_cty_g(&g.args[0])?;
        if g.name == "option" {
            return Ok(format!("::std::option::Option<{}>", x));
        }
        return Ok(format!("::std::result::Result<{}, i128>", x));
    }
    try_cty_name(&g.name)
}

/// Contract (i128) mirror type. Err for unit and array.
pub fn try_cty(t: &str) -> Result<String, String> {
    if is_g3_key(t) {
        if let Ok(g) = GType::try_from_key(t) {
            return try_cty_g(&g);
        }
    }
    try_cty_name(t)
}

fn try_cty_name(t: &str) -> Result<String, String> {
    match t {
        "i64" => Ok("i128".to_string()),
        "bool" => Ok("bool".to_string()),
        "option" => Ok("::std::option::Option<i128>".to_string()),
        "result" => Ok("::std::result::Result<i128, i128>".to_string()),
        _ if is_user_type(t) => Ok(format!("pruv_contract__{}", t)),
        _ => Err(format!("codegen: type {} has no contract representation", type_repr(t))),
    }
}

/// Normal path only (panics for a type with no contract representation; use try_cty to receive the failure).
pub fn cty(t: &str) -> String {
    try_cty(t).unwrap()
}

/// Contract conversion of a structured type (G3): recursive, the payload first.
pub fn try_conv_g(g: &GType, x: &str) -> Result<String, String> {
    if structured_builtin(g) {
        let inner = try_conv_g(&g.args[0], "v")?;
        let mapped = if inner == "v" { x.to_string() } else { format!("{}.map(|v| {})", x, inner) };
        if g.name == "option" {
            return Ok(mapped);
        }
        return Ok(format!("{}.map_err(|v| v as i128)", mapped));
    }
    try_conv_name(&g.name, x)
}

/// Rust expression converting the runtime value `x` (of type t) to a contract value. Err for unit and array.
pub fn try_conv(t: &str, x: &str) -> Result<String, String> {
    if is_g3_key(t) {
        if let Ok(g) = GType::try_from_key(t) {
            return try_conv_g(&g, x);
        }
    }
    try_conv_name(t, x)
}

fn try_conv_name(t: &str, x: &str) -> Result<String, String> {
    match t {
        "i64" => Ok(format!("({} as i128)", x)),
        "bool" => Ok(x.to_string()),
        "option" => Ok(format!("{}.map(|v| v as i128)", x)),
        "result" => Ok(format!("{}.map(|v| v as i128).map_err(|v| v as i128)", x)),
        _ if is_user_type(t) => Ok(format!("pruv_to_c__{}({})", t, x)),
        _ => Err(format!("codegen: type {} has no contract representation", type_repr(t))),
    }
}

/// Normal path only (panics on failure; use try_conv to receive the failure).
pub fn conv(t: &str, x: &str) -> String {
    try_conv(t, x).unwrap()
}

/// G9 A2 (Python `condensed_type_order`): indices into `tt.decls` in dependency-first order over the SCC condensation of
/// the field-dependency graph. Iterative Tarjan: roots in declaration order, successors in field order (first
/// occurrence), a component is emitted when its root finishes, the members of one component in declaration order.
pub fn condensed_type_order(tt: &TypeTable) -> Vec<usize> {
    let count = tt.decls.len();
    let mut index: std::collections::HashMap<&str, usize> = std::collections::HashMap::new();
    for (i, d) in tt.decls.iter().enumerate() {
        index.insert(d.name(), i);
    }
    let mut adj: Vec<Vec<usize>> = Vec::with_capacity(count);
    for d in &tt.decls {
        let mut out: Vec<usize> = Vec::new();
        for f in d.all_fields() {
            for m in crate::gtype::dependencies(&GType::from_key(&f.ty)) {
                if let Some(&j) = index.get(m.as_str()) {
                    if !out.contains(&j) {
                        out.push(j);
                    }
                }
            }
        }
        adj.push(out);
    }
    let mut num: Vec<i64> = vec![-1; count];
    let mut low: Vec<i64> = vec![0; count];
    let mut onstack: Vec<bool> = vec![false; count];
    let mut stack: Vec<usize> = Vec::new();
    let mut comps: Vec<Vec<usize>> = Vec::new();
    let mut counter: i64 = 0;
    for root in 0..count {
        if num[root] != -1 {
            continue;
        }
        num[root] = counter;
        low[root] = counter;
        counter += 1;
        stack.push(root);
        onstack[root] = true;
        let mut work: Vec<(usize, usize)> = vec![(root, 0)];
        while let Some((v, pos)) = work.pop() {
            if pos < adj[v].len() {
                work.push((v, pos + 1));
                let w = adj[v][pos];
                if num[w] == -1 {
                    num[w] = counter;
                    low[w] = counter;
                    counter += 1;
                    stack.push(w);
                    onstack[w] = true;
                    work.push((w, 0));
                } else if onstack[w] {
                    low[v] = low[v].min(num[w]);
                }
            } else {
                if low[v] == num[v] {
                    let mut comp: Vec<usize> = Vec::new();
                    loop {
                        let w = stack.pop().unwrap();
                        onstack[w] = false;
                        comp.push(w);
                        if w == v {
                            break;
                        }
                    }
                    comps.push(comp);
                }
                if let Some(&(parent, _)) = work.last() {
                    low[parent] = low[parent].min(low[v]);
                }
            }
        }
    }
    let mut out: Vec<usize> = Vec::with_capacity(count);
    for mut comp in comps {
        comp.sort();
        out.extend(comp);
    }
    out
}

/// G9 A2 (Python `make_type_table`): the type table of a program; a G9 program gets the condensed dependency order.
pub fn make_type_table(prog: &Program) -> TypeTable {
    let mut tt = TypeTable::new(&prog.types);
    if prog.g9.is_some() {
        tt.order = condensed_type_order(&tt);
    }
    tt
}

/// A `pub struct`/`pub enum` per user type, dependencies first (TypeTable.order).
pub fn emit_public_types(prog: &Program) -> String {
    emit_public_types_with(prog, &make_type_table(prog))
}

/// `emit_public_types` over a given table (Python `emit_public_types(prog, order)`): G9: an extended type derives Clone,
/// never Copy; a boxed field (recursive edge) is `::std::boxed::Box<Child>`.
pub fn emit_public_types_with(prog: &Program, tt: &TypeTable) -> String {
    let (ext, boxed): (std::collections::HashSet<&str>, std::collections::HashSet<&str>) = match &prog.g9 {
        Some(m) => (m.extended.iter().map(|s| s.as_str()).collect(), m.boxed.iter().map(|s| s.as_str()).collect()),
        None => (Default::default(), Default::default()),
    };
    let fty = |ty: &str, label: &str| -> String {
        let r = rty(ty, false);
        if boxed.contains(label) { format!("::std::boxed::Box<{}>", r) } else { r }
    };
    // G4 A2: in explicit mode only a source-`pub` type is a `pub` Rust item
    let explicit = prog.explicit.as_ref();
    let pubs: std::collections::HashMap<&str, bool> = match explicit {
        Some(x) => prog.types.iter().zip(x.type_pub.iter()).map(|(d, p)| (d.name(), *p)).collect(),
        None => Default::default(),
    };
    let mut out: Vec<String> = Vec::new();
    for d in tt.ordered() {
        let pv = if explicit.is_none() || pubs.get(d.name()).copied().unwrap_or(true) { "pub " } else { "" };
        out.push(format!(
            "#[allow(dead_code, non_camel_case_types, non_snake_case{})]",
            if explicit.is_some() { ", private_interfaces" } else { "" }
        ));
        if ext.contains(d.name()) {
            out.push("#[derive(Clone, Debug)]".to_string());
        } else {
            out.push("#[derive(Clone, Copy, Debug, PartialEq, Eq)]".to_string());
        }
        match d {
            TypeDecl::Struct(s) => {
                if !s.fields.is_empty() {
                    let body: Vec<String> = s
                        .fields
                        .iter()
                        .map(|f| format!("{}{}: {}", pv, f.name, fty(&f.ty, &format!("{}.{}", s.name, f.name))))
                        .collect();
                    out.push(format!("{}struct {} {{ {} }}", pv, s.name, body.join(", ")));
                } else {
                    out.push(format!("{}struct {} {{}}", pv, s.name));
                }
            }
            TypeDecl::Enum(e) => {
                let mut vs: Vec<String> = Vec::new();
                for v in &e.variants {
                    if !v.fields.is_empty() {
                        let fs: Vec<String> = v
                            .fields
                            .iter()
                            .map(|f| fty(&f.ty, &format!("{}::{}.{}", e.name, v.name, f.name)))
                            .collect();
                        vs.push(format!("{}({})", v.name, fs.join(", ")));
                    } else {
                        vs.push(v.name.clone());
                    }
                }
                out.push(format!("{}enum {} {{ {} }}", pv, e.name, vs.join(", ")));
            }
        }
        out.push(String::new());
    }
    let mut s = out.join("\n");
    if !out.is_empty() {
        s.push('\n');
    }
    s
}

fn show_list(xs: &[Expr]) -> String {
    xs.iter().map(show).collect::<Vec<_>>().join(", ")
}

/// Human-readable text of a contract expression (for panic messages).
pub fn show(e: &Expr) -> String {
    match e {
        Expr::IntLit(x) => x.value.clone(),
        Expr::BoolLit(x) => (if x.value { "true" } else { "false" }).to_string(),
        Expr::StrLit(_) => "<str>".to_string(),
        Expr::Var(x) => x.name.clone(),
        Expr::Move(x) => format!("move {}", x.name), // G6 A0: never reaches a generator (guarded in the driver)
        Expr::InoutArg(x) => format!("inout {}", show(&x.expr)), // G5 A0: never reaches a generator (guarded in the driver)
        Expr::Unary(x) => format!("{}{}", x.op, show(&x.operand)),
        Expr::Binary(x) => format!("({} {} {})", show(&x.left), x.op, show(&x.right)),
        Expr::Index(x) => format!("{}[{}]", show(&x.array), show(&x.index)),
        Expr::Call(x) => format!("{}({})", x.name, show_list(&x.args)),
        Expr::Ctor(x) => match &x.arg {
            None => x.name.clone(),
            Some(a) => format!("{}({})", x.name, show(a)),
        },
        Expr::Quant(x) => format!("{} {} in {}..{}: {}", x.kind, x.var, show(&x.lo), show(&x.hi), show(&x.body)),
        // G3: a specialized node is named by its stem; the message shows the declaration name as written
        Expr::StructLit(x) => {
            if x.fields.is_empty() {
                format!("{} {{}}", src_name(&x.name))
            } else {
                let fs: Vec<String> = x.fields.iter().map(|f| format!("{}: {}", f.name, show(&f.value))).collect();
                format!("{} {{ {} }}", src_name(&x.name), fs.join(", "))
            }
        }
        Expr::EnumCtor(x) => {
            if x.args.is_empty() {
                format!("{}::{}", src_name(&x.enum_name), x.variant)
            } else {
                format!("{}::{}({})", src_name(&x.enum_name), x.variant, show_list(&x.args))
            }
        }
        Expr::FieldAccess(x) => format!("{}.{}", show(&x.base), x.field),
        Expr::IsVariant(x) => format!("is_variant({}, {}::{})", show(&x.value), src_name(&x.enum_name), x.variant),
        Expr::VariantField(x) => {
            format!("variant_field({}, {}::{}, {})", show(&x.value), src_name(&x.enum_name), x.variant, x.field)
        }
    }
}

/// The name of a if this is a `len(a)` call.
fn len_of(x: &Expr) -> Option<&str> {
    if let Expr::Call(c) = x {
        if c.name == "len" && c.args.len() == 1 {
            if let Expr::Var(v) = &c.args[0] {
                return Some(&v.name);
            }
        }
    }
    None
}

/// The array name a if e is structurally `forall i in 0..len(a): forall j in i..len(a): a[i] <= a[j]`
/// (inner start `i` or `i + 1`), otherwise None.
pub fn match_sorted_requires(e: &Expr) -> Option<String> {
    let q1 = match e {
        Expr::Quant(q) if q.kind == "forall" => q,
        _ => return None,
    };
    match &*q1.lo {
        Expr::IntLit(l) if l.value == "0" => {}
        _ => return None,
    }
    let a = len_of(&q1.hi)?;
    if a.is_empty() {
        return None;
    }
    let q2 = match &*q1.body {
        Expr::Quant(q) if q.kind == "forall" => q,
        _ => return None,
    };
    if q2.var == q1.var || a == q1.var || a == q2.var {
        return None;
    }
    let mut lo: &Expr = &q2.lo;
    if let Expr::Binary(b) = lo {
        if b.op == "+" {
            if let Expr::IntLit(r) = &*b.right {
                if r.value == "1" {
                    lo = &*b.left;
                }
            }
        }
    }
    match lo {
        Expr::Var(v) if v.name == q1.var => {}
        _ => return None,
    }
    if len_of(&q2.hi) != Some(a) {
        return None;
    }
    let b = match &*q2.body {
        Expr::Binary(b) if b.op == "<=" => b,
        _ => return None,
    };
    let (l, r) = match (&*b.left, &*b.right) {
        (Expr::Index(l), Expr::Index(r)) => (l, r),
        _ => return None,
    };
    for (ix, v) in [(l, &q1.var), (r, &q2.var)] {
        let ok = matches!(&*ix.array, Expr::Var(x) if x.name == a)
            && matches!(&*ix.index, Expr::Var(x) if &x.name == v);
        if !ok {
            return None;
        }
    }
    Some(a.to_string())
}

/// A Rust string literal using ASCII only.
pub fn rstr(text: &str) -> String {
    let mut out = String::from("\"");
    for ch in text.chars() {
        let c = ch as u32;
        if ch == '\\' || ch == '"' {
            out.push('\\');
            out.push(ch);
        } else if (32..127).contains(&c) {
            out.push(ch);
        } else {
            out.push_str(&format!("\\u{{{:x}}}", c));
        }
    }
    out.push('"');
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn var(n: &str) -> Expr {
        Expr::Var(Var { line: 1, col: 1, name: n.into(), ty: None })
    }
    fn int(v: &str) -> Expr {
        Expr::IntLit(IntLit { line: 1, col: 1, value: v.into(), ty: None })
    }
    fn bin(op: &str, l: Expr, r: Expr) -> Expr {
        Expr::Binary(Binary { line: 1, col: 1, op: op.into(), left: Box::new(l), right: Box::new(r), ty: None })
    }
    fn len(n: &str) -> Expr {
        Expr::Call(Call { line: 1, col: 1, name: "len".into(), args: vec![var(n)], ty: None, targs: None, inst: None, old: None })
    }
    fn idx(a: &str, i: &str) -> Expr {
        Expr::Index(Index { line: 1, col: 1, array: Box::new(var(a)), index: Box::new(var(i)), ty: None })
    }
    fn forall(v: &str, lo: Expr, hi: Expr, body: Expr) -> Expr {
        Expr::Quant(Quant {
            line: 1, col: 1, kind: "forall".into(), var: v.into(),
            lo: Box::new(lo), hi: Box::new(hi), body: Box::new(body), ty: None,
        })
    }
    fn sorted(inner_lo: Expr) -> Expr {
        forall("i", int("0"), len("a"), forall("j", inner_lo, len("a"), bin("<=", idx("a", "i"), idx("a", "j"))))
    }

    #[test]
    fn show_basic() {
        let e = bin("+", var("x"), Expr::BoolLit(BoolLit { line: 1, col: 1, value: true, ty: None }));
        assert_eq!(show(&e), "(x + true)");
        assert_eq!(show(&sorted(var("i"))), "forall i in 0..len(a): forall j in i..len(a): (a[i] <= a[j])");
        let c = Expr::Call(Call { line: 1, col: 1, name: "f".into(), args: vec![int("-3"), var("y")], ty: None, targs: None, inst: None, old: None });
        assert_eq!(show(&c), "f(-3, y)");
    }

    #[test]
    fn sorted_match() {
        assert_eq!(match_sorted_requires(&sorted(var("i"))), Some("a".to_string()));
        assert_eq!(match_sorted_requires(&sorted(bin("+", var("i"), int("1")))), Some("a".to_string()));
        assert_eq!(match_sorted_requires(&sorted(bin("+", var("i"), int("2")))), None);
        assert_eq!(match_sorted_requires(&var("a")), None);
    }

    #[test]
    fn rstr_escapes() {
        assert_eq!(rstr("a\"b\\c"), "\"a\\\"b\\\\c\"");
        assert_eq!(rstr("é\n"), "\"\\u{e9}\\u{a}\"");
        assert_eq!(rstr("~\u{7f}"), "\"~\\u{7f}\"");
    }

    #[test]
    fn types() {
        assert_eq!(rty("array", true), "&[i64]");
        assert_eq!(rty("array", false), "::std::vec::Vec<i64>");
        assert_eq!(rty("array_u8", true), "&[u8]");
        assert_eq!(rty("array_u8", false), "::std::vec::Vec<u8>");
        assert_eq!(cty("Point"), "pruv_contract__Point");
        assert_eq!(conv("option", "x"), "x.map(|v| v as i128)");
        assert!(try_cty("unit").is_err());
    }
}
