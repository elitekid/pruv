//! Python 출력 공통 함수(codegen.py 의 rty·cty·conv·emit_public_types·show·
//! match_sorted_requires·rstr 대응). 출력은 Python 과 바이트 동일해야 한다.

use crate::ast::*;
use crate::typeinfo::{is_user_type, TypeTable};

/// 실행용 Rust 타입 철자. 내장 6종과 사용자 타입을 모두 덮으므로 실패 경로가 없다.
pub fn rty(t: &str, param: bool) -> String {
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
        // G2 A5: 폴백에 기대지 않고 명시
        "array_bool" => {
            if param { "&[bool]".to_string() } else { "::std::vec::Vec<bool>".to_string() }
        }
        // G2 B2: str 은 매개변수 &str, 지역·반환 String
        "str" => {
            if param { "&str".to_string() } else { "::std::string::String".to_string() }
        }
        other => other.to_string(),
    }
}

/// Python 의 `%r` 로 찍은 Type.
fn type_repr(t: &str) -> String {
    format!("Type(name='{}')", t)
}

/// 계약(i128) 거울 타입. unit·array 는 Err.
pub fn try_cty(t: &str) -> Result<String, String> {
    match t {
        "i64" => Ok("i128".to_string()),
        "bool" => Ok("bool".to_string()),
        "option" => Ok("::std::option::Option<i128>".to_string()),
        "result" => Ok("::std::result::Result<i128, i128>".to_string()),
        _ if is_user_type(t) => Ok(format!("pruv_contract__{}", t)),
        _ => Err(format!("codegen: type {} has no contract representation", type_repr(t))),
    }
}

/// 정상 경로 전용(계약 표현이 없는 타입이면 패닉; 실패를 받으려면 try_cty).
pub fn cty(t: &str) -> String {
    try_cty(t).unwrap()
}

/// 실행 값 `x`(타입 t)를 계약 값으로 바꾸는 Rust 식. unit·array 는 Err.
pub fn try_conv(t: &str, x: &str) -> Result<String, String> {
    match t {
        "i64" => Ok(format!("({} as i128)", x)),
        "bool" => Ok(x.to_string()),
        "option" => Ok(format!("{}.map(|v| v as i128)", x)),
        "result" => Ok(format!("{}.map(|v| v as i128).map_err(|v| v as i128)", x)),
        _ if is_user_type(t) => Ok(format!("pruv_to_c__{}({})", t, x)),
        _ => Err(format!("codegen: type {} has no contract representation", type_repr(t))),
    }
}

/// 정상 경로 전용(실패하면 패닉; 실패를 받으려면 try_conv).
pub fn conv(t: &str, x: &str) -> String {
    try_conv(t, x).unwrap()
}

/// 사용자 타입마다 `pub struct`/`pub enum`, 의존 먼저(TypeTable.order).
pub fn emit_public_types(prog: &Program) -> String {
    let tt = TypeTable::new(&prog.types);
    let mut out: Vec<String> = Vec::new();
    for d in tt.ordered() {
        out.push("#[allow(dead_code, non_camel_case_types, non_snake_case)]".to_string());
        out.push("#[derive(Clone, Copy, Debug, PartialEq, Eq)]".to_string());
        match d {
            TypeDecl::Struct(s) => {
                if !s.fields.is_empty() {
                    let body: Vec<String> =
                        s.fields.iter().map(|f| format!("pub {}: {}", f.name, rty(&f.ty, false))).collect();
                    out.push(format!("pub struct {} {{ {} }}", s.name, body.join(", ")));
                } else {
                    out.push(format!("pub struct {} {{}}", s.name));
                }
            }
            TypeDecl::Enum(e) => {
                let mut vs: Vec<String> = Vec::new();
                for v in &e.variants {
                    if !v.fields.is_empty() {
                        let fs: Vec<String> = v.fields.iter().map(|f| rty(&f.ty, false)).collect();
                        vs.push(format!("{}({})", v.name, fs.join(", ")));
                    } else {
                        vs.push(v.name.clone());
                    }
                }
                out.push(format!("pub enum {} {{ {} }}", e.name, vs.join(", ")));
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

/// 계약 식의 읽기 쉬운 텍스트(패닉 메시지용).
pub fn show(e: &Expr) -> String {
    match e {
        Expr::IntLit(x) => x.value.clone(),
        Expr::BoolLit(x) => (if x.value { "true" } else { "false" }).to_string(),
        Expr::StrLit(_) => "<str>".to_string(),
        Expr::Var(x) => x.name.clone(),
        Expr::Unary(x) => format!("{}{}", x.op, show(&x.operand)),
        Expr::Binary(x) => format!("({} {} {})", show(&x.left), x.op, show(&x.right)),
        Expr::Index(x) => format!("{}[{}]", show(&x.array), show(&x.index)),
        Expr::Call(x) => format!("{}({})", x.name, show_list(&x.args)),
        Expr::Ctor(x) => match &x.arg {
            None => x.name.clone(),
            Some(a) => format!("{}({})", x.name, show(a)),
        },
        Expr::Quant(x) => format!("{} {} in {}..{}: {}", x.kind, x.var, show(&x.lo), show(&x.hi), show(&x.body)),
        Expr::StructLit(x) => {
            if x.fields.is_empty() {
                format!("{} {{}}", x.name)
            } else {
                let fs: Vec<String> = x.fields.iter().map(|f| format!("{}: {}", f.name, show(&f.value))).collect();
                format!("{} {{ {} }}", x.name, fs.join(", "))
            }
        }
        Expr::EnumCtor(x) => {
            if x.args.is_empty() {
                format!("{}::{}", x.enum_name, x.variant)
            } else {
                format!("{}::{}({})", x.enum_name, x.variant, show_list(&x.args))
            }
        }
        Expr::FieldAccess(x) => format!("{}.{}", show(&x.base), x.field),
        Expr::IsVariant(x) => format!("is_variant({}, {}::{})", show(&x.value), x.enum_name, x.variant),
        Expr::VariantField(x) => {
            format!("variant_field({}, {}::{}, {})", show(&x.value), x.enum_name, x.variant, x.field)
        }
    }
}

/// `len(a)` 호출이면 a 의 이름.
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

/// e 가 구조상 `forall i in 0..len(a): forall j in i..len(a): a[i] <= a[j]`
/// (안쪽 시작 `i` 또는 `i + 1`)이면 배열 이름 a, 아니면 None.
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

/// ASCII 만 쓰는 Rust 문자열 리터럴.
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
        Expr::Call(Call { line: 1, col: 1, name: "len".into(), args: vec![var(n)], ty: None })
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
        let c = Expr::Call(Call { line: 1, col: 1, name: "f".into(), args: vec![int("-3"), var("y")], ty: None });
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
