//! Rust bindings generator for the LLVM backend (counterparts of llvmgen.py's rust_ty, rs_ser, rs_de, gen_bindings).
//! The output must be byte-identical to Python's.

use crate::ast::*;
use crate::emit_common::{emit_public_types, is_spec_fn, rty};
use crate::llvmgen::{g_arg, is_agg, is_gopt};
use crate::typeinfo::{is_array_name, is_user_type, uses_array_type, uses_str, TypeTable};

pub const ALLOW: &str = "#[allow(dead_code, non_snake_case, unused)]";

const HOST_ALLOC: &str = r##"#[no_mangle]
pub extern "C" fn pruv_host_alloc(len: i64) -> *mut i64 {
    let layout = match ::std::alloc::Layout::array::<i64>(len as usize) {
        Ok(l) => l,
        Err(_) => ::std::alloc::handle_alloc_error(::std::alloc::Layout::new::<i64>()),
    };
    let p = unsafe { ::std::alloc::alloc(layout) } as *mut i64;
    if p.is_null() { ::std::alloc::handle_alloc_error(layout); }
    p
}"##;

const HOST_ALLOC_ZEROED: &str = r##"#[no_mangle]
pub extern "C" fn pruv_host_alloc_zeroed(len: i64) -> *mut i64 {
    let layout = match ::std::alloc::Layout::array::<i64>(len as usize) {
        Ok(l) => l,
        Err(_) => ::std::alloc::handle_alloc_error(::std::alloc::Layout::new::<i64>()),
    };
    let p = unsafe { ::std::alloc::alloc_zeroed(layout) } as *mut i64;
    if p.is_null() { ::std::alloc::handle_alloc_error(layout); }
    p
}"##;

const HOST_ALLOC_V2: &str = r##"#[no_mangle]
pub extern "C" fn pruv_host_alloc_v2(len: i64, size: i64, align: i64) -> *mut u8 {
    let layout = match (len as usize).checked_mul(size as usize).and_then(|b| ::std::alloc::Layout::from_size_align(b, align as usize).ok()) {
        Some(l) => l,
        None => ::std::alloc::handle_alloc_error(::std::alloc::Layout::new::<u8>()),
    };
    let p = unsafe { ::std::alloc::alloc(layout) };
    if p.is_null() { ::std::alloc::handle_alloc_error(layout); }
    p
}"##;

const HOST_ALLOC_ZEROED_V2: &str = r##"#[no_mangle]
pub extern "C" fn pruv_host_alloc_zeroed_v2(len: i64, size: i64, align: i64) -> *mut u8 {
    let layout = match (len as usize).checked_mul(size as usize).and_then(|b| ::std::alloc::Layout::from_size_align(b, align as usize).ok()) {
        Some(l) => l,
        None => ::std::alloc::handle_alloc_error(::std::alloc::Layout::new::<u8>()),
    };
    let p = unsafe { ::std::alloc::alloc_zeroed(layout) };
    if p.is_null() { ::std::alloc::handle_alloc_error(layout); }
    p
}"##;

const HOST_FREE_V2: &str = r##"#[no_mangle]
pub extern "C" fn pruv_host_free_v2(data: *mut u8, len: i64, size: i64, align: i64) {
    if data.is_null() || len <= 0 { return; }
    if let Some(layout) = (len as usize).checked_mul(size as usize).and_then(|b| ::std::alloc::Layout::from_size_align(b, align as usize).ok()) {
        unsafe { ::std::alloc::dealloc(data, layout) };
    }
}"##;

const HOST_FLUSH: &str = r##"#[no_mangle]
pub extern "C" fn pruv_host_flush() {
    let _ = ::std::io::Write::flush(&mut ::std::io::stdout());
}"##;

const HOST_FREE: &str = r##"#[no_mangle]
pub extern "C" fn pruv_host_free(data: *mut i64, len: i64) {
    if data.is_null() || len <= 0 { return; }
    if let Ok(layout) = ::std::alloc::Layout::array::<i64>(len as usize) {
        unsafe { ::std::alloc::dealloc(data as *mut u8, layout) };
    }
}"##;

/// Number of i64 words in the external (pruv_abi_*) form (llvmgen.words).
fn words(tt: &TypeTable, ty: &str) -> Result<i64, String> {
    // the same (memoized) count as the wrapper generator, so both sides agree by construction
    crate::llvmgen::words(tt, ty).map(|n| n as i64)
}

/// Python's `tt.decls[name]` KeyError (str(e) == the quoted name).
fn decl<'a>(tt: &'a TypeTable, ty: &str) -> Result<&'a TypeDecl, String> {
    tt.decl(ty).ok_or_else(|| format!("'{}'", ty))
}

/// Whether the function name is mangled (it changes if it has a `[^A-Za-z0-9_]` character).
fn needs_mangling(n: &str) -> bool {
    n.chars().any(|c| !(c.is_ascii_alphanumeric() || c == '_'))
}

/// G2 A5: if there is a [bool] parameter, the binding calls pruv_abi_<f>__typed, which has no byte check.
fn typed_abi_name(f: &Function) -> String {
    // G2 B2: the same for &str
    if f.params.iter().any(|p| p.ty == "array_bool" || p.ty == "str") {
        format!("{}__typed", f.name)
    } else {
        f.name.clone()
    }
}

fn rust_ty(t: &str, param: bool) -> String {
    if is_gopt(t) {
        // G3: ::std::option::Option<R(X)> / ::std::result::Result<R(X), i64>
        return rty(t, false);
    }
    if is_user_type(t) {
        return t.to_string();
    }
    match t {
        "i64" => "i64".to_string(),
        "bool" => "bool".to_string(),
        "unit" => "()".to_string(),
        "option" => "::std::option::Option<i64>".to_string(),
        "result" => "::std::result::Result<i64, i64>".to_string(),
        "array_u8" => (if param { "&[u8]" } else { "::std::vec::Vec<u8>" }).to_string(),
        "array_bool" => (if param { "&[bool]" } else { "::std::vec::Vec<bool>" }).to_string(), // G2 A5
        "str" => (if param { "&str" } else { "::std::string::String" }).to_string(), // G2 B2
        _ => (if param { "&[i64]" } else { "::std::vec::Vec<i64>" }).to_string(),
    }
}

/// Rust statements that write the value `expr` (Copy) into the word array `arr` at `off`.
fn rs_ser(tt: &TypeTable, ty: &str, expr: &str, arr: &str, off: i64, ctr: &mut i64) -> Result<Vec<String>, String> {
    if is_gopt(ty) {
        // G3: the word array starts zeroed, so only the active words are written
        *ctr += 1;
        let v = format!("pruv__b{}", *ctr);
        let x = g_arg(ty);
        let inner = rs_ser(tt, x, &v, arr, off + 1, ctr)?.join(" ");
        if ty.starts_with("option<") {
            return Ok(vec![format!(
                "match {} {{ Some({}) => {{ {}[{}] = 1; {} }} None => {{ {}[{}] = 0; }} }}",
                expr, v, arr, off, inner, arr, off
            )]);
        }
        return Ok(vec![format!(
            "match {} {{ Ok({}) => {{ {}[{}] = 1; {} }} Err({}) => {{ {}[{}] = 0; {}[{}] = {}; }} }}",
            expr,
            v,
            arr,
            off,
            inner,
            v,
            arr,
            off,
            arr,
            off + 1 + words(tt, x)?,
            v
        )]);
    }
    match ty {
        "i64" => return Ok(vec![format!("{}[{}] = {};", arr, off, expr)]),
        "bool" => return Ok(vec![format!("{}[{}] = ({}) as i64;", arr, off, expr)]),
        "option" | "result" => {
            *ctr += 1;
            let v = format!("pruv__b{}", *ctr);
            if ty == "option" {
                return Ok(vec![format!(
                    "match {} {{ Some({}) => {{ {}[{}] = 1; {}[{}] = {}; }} None => {{ {}[{}] = 0; {}[{}] = 0; }} }}",
                    expr, v, arr, off, arr, off + 1, v, arr, off, arr, off + 1
                )]);
            }
            return Ok(vec![format!(
                "match {} {{ Ok({}) => {{ {}[{}] = 1; {}[{}] = {}; }} Err({}) => {{ {}[{}] = 0; {}[{}] = {}; }} }}",
                expr, v, arr, off, arr, off + 1, v, v, arr, off, arr, off + 1, v
            )]);
        }
        _ => {}
    }
    match decl(tt, ty)? {
        TypeDecl::Struct(s) => {
            let mut out = Vec::new();
            let mut o = off;
            for f in &s.fields {
                out.extend(rs_ser(tt, &f.ty, &format!("{}.{}", expr, f.name), arr, o, ctr)?);
                o += words(tt, &f.ty)?;
            }
            Ok(out)
        }
        TypeDecl::Enum(d) => {
            let mut arms: Vec<String> = Vec::new();
            let mut o = off + 1;
            for (k, v) in d.variants.iter().enumerate() {
                let mut names: Vec<String> = Vec::new();
                let mut stmts: Vec<String> = vec![format!("{}[{}] = {};", arr, off, k)];
                for f in &v.fields {
                    *ctr += 1;
                    let nm = format!("pruv__b{}", *ctr);
                    stmts.extend(rs_ser(tt, &f.ty, &nm, arr, o, ctr)?);
                    names.push(nm);
                    o += words(tt, &f.ty)?;
                }
                let pat = if names.is_empty() {
                    format!("{}::{}", d.name, v.name)
                } else {
                    format!("{}::{}({})", d.name, v.name, names.join(", "))
                };
                arms.push(format!("{} => {{ {} }}", pat, stmts.join(" ")));
            }
            Ok(vec![format!("match {} {{ {} }}", expr, arms.join(" "))])
        }
    }
}

/// Rust expression that rebuilds a ty value from the word array `arr` at `off` (safe constructors only).
fn rs_de(tt: &TypeTable, ty: &str, arr: &str, off: i64) -> Result<String, String> {
    if is_gopt(ty) {
        // G3
        let x = g_arg(ty);
        let xe = rs_de(tt, x, arr, off + 1)?;
        if ty.starts_with("option<") {
            return Ok(format!("(if {}[{}] != 0 {{ Some({}) }} else {{ None }})", arr, off, xe));
        }
        return Ok(format!(
            "(if {}[{}] != 0 {{ Ok({}) }} else {{ Err({}[{}]) }})",
            arr,
            off,
            xe,
            arr,
            off + 1 + words(tt, x)?
        ));
    }
    match ty {
        "i64" => return Ok(format!("{}[{}]", arr, off)),
        "bool" => return Ok(format!("({}[{}] != 0)", arr, off)),
        "option" => {
            return Ok(format!("(if {}[{}] != 0 {{ Some({}[{}]) }} else {{ None }})", arr, off, arr, off + 1));
        }
        "result" => {
            return Ok(format!(
                "(if {}[{}] != 0 {{ Ok({}[{}]) }} else {{ Err({}[{}]) }})",
                arr, off, arr, off + 1, arr, off + 1
            ));
        }
        _ => {}
    }
    match decl(tt, ty)? {
        TypeDecl::Struct(s) => {
            let mut parts: Vec<String> = Vec::new();
            let mut o = off;
            for f in &s.fields {
                parts.push(format!("{}: {}", f.name, rs_de(tt, &f.ty, arr, o)?));
                o += words(tt, &f.ty)?;
            }
            Ok(format!("{} {{ {} }}", s.name, parts.join(", ")))
        }
        TypeDecl::Enum(d) => {
            let mut arms: Vec<String> = Vec::new();
            let mut o = off + 1;
            for (k, v) in d.variants.iter().enumerate() {
                let mut args: Vec<String> = Vec::new();
                for f in &v.fields {
                    args.push(rs_de(tt, &f.ty, arr, o)?);
                    o += words(tt, &f.ty)?;
                }
                let tail = if args.is_empty() { String::new() } else { format!("({})", args.join(", ")) };
                arms.push(format!("{} => {}::{}{},", k, d.name, v.name, tail));
            }
            Ok(format!("(match {}[{}] {{ {} _ => ::std::unreachable!() }})", arr, off, arms.join(" ")))
        }
    }
}

pub fn gen_bindings(prog: &Program) -> Result<String, String> {
    let tt = TypeTable::new(&prog.types);
    let mut o: Vec<String> = Vec::new();
    o.push("// generated by pruvc llvmgen -- Rust bindings for the LLVM back end (include with #[path] mod sol;)".to_string());
    if !prog.types.is_empty() {
        let publ = emit_public_types(prog);
        if publ.contains("#[derive") {
            o.push(publ.replace("#[derive", &format!("{}\n#[derive", ALLOW)));
        } else {
            o.push(publ);
        }
    }
    o.push(ALLOW.to_string());
    o.push("#[repr(C)]\npub struct Pruv__Array { pub data: *mut i64, pub len: i64 }".to_string());
    if uses_array_type(prog, "array_u8") {
        o.push(ALLOW.to_string());
        o.push("#[repr(C)]\npub struct Pruv__ArrayU8 { pub data: *mut u8, pub len: i64 }".to_string());
    }
    if uses_array_type(prog, "array_bool") {
        // G2 A5
        o.push(ALLOW.to_string());
        o.push("#[repr(C)]\npub struct Pruv__ArrayBool { pub data: *mut u8, pub len: i64 }".to_string());
    }
    if uses_str(prog) {
        // G2 B2
        o.push(ALLOW.to_string());
        o.push("#[repr(C)]\npub struct Pruv__Str { pub data: *mut u8, pub len: i64 }".to_string());
    }
    o.push(ALLOW.to_string());
    o.push("#[repr(C)]\npub struct Pruv__Tagged { pub tag: i64, pub value: i64 }".to_string());
    for h in [HOST_ALLOC, HOST_ALLOC_ZEROED, HOST_FLUSH, HOST_FREE, HOST_ALLOC_V2, HOST_ALLOC_ZEROED_V2, HOST_FREE_V2] {
        o.push(ALLOW.to_string());
        o.push(h.to_string());
    }
    // G3: specializations of generic functions are private (no ABI symbol, not callable from the bindings)
    let pubs: Vec<&Function> = prog.functions.iter().filter(|f| !is_spec_fn(&f.name)).collect();
    let returns_array = pubs.iter().any(|f| is_array_name(&f.ret) || f.ret == "str"); // G2 B2: str returns are counted too
    let mut decls: Vec<String> = Vec::new();
    for f in &pubs {
        if needs_mangling(&f.name) {
            return Err(format!(
                "llvmgen: function name {} needs mangling; the bindings use the raw name",
                f.name
            ));
        }
        let mut ps: Vec<&str> = Vec::new();
        for p in &f.params {
            if p.ty == "array_u8" || p.ty == "array_bool" || p.ty == "str" {
                // G2 A5: bool is also *const u8 (G2 B2: so is str)
                ps.extend(["*const u8", "i64"]);
            } else if p.ty == "array" {
                ps.extend(["*const i64", "i64"]);
            } else if p.ty == "option" || p.ty == "result" {
                ps.extend(["i64", "i64"]);
            } else if is_agg(&p.ty) {
                ps.push("*const i64");
            } else {
                ps.push("i64");
            }
        }
        if f.ret == "array_u8" {
            ps.push("*mut Pruv__ArrayU8");
        } else if f.ret == "array_bool" {
            ps.push("*mut Pruv__ArrayBool"); // G2 A5
        } else if f.ret == "str" {
            ps.push("*mut Pruv__Str"); // G2 B2
        } else if f.ret == "array" {
            ps.push("*mut Pruv__Array");
        } else if is_agg(&f.ret) {
            ps.push("*mut i64");
        }
        let ret = if f.ret == "i64" || f.ret == "bool" {
            " -> i64"
        } else if f.ret == "option" || f.ret == "result" {
            " -> Pruv__Tagged"
        } else {
            ""
        };
        let plist: Vec<String> = ps.iter().enumerate().map(|(i, t)| format!("p{}: {}", i, t)).collect();
        decls.push(format!("    fn pruv_abi_{}({}){};", typed_abi_name(f), plist.join(", "), ret));
    }
    if pubs.iter().any(|f| f.ret == "array_bool") {
        // G2 A5: after all pruv_abi_* lines, before the marker line
        decls.push("    fn pruv_check_bool(p0: *const u8, p1: i64);".to_string());
    }
    if pubs.iter().any(|f| f.ret == "str") {
        // G2 B2: after the check_bool line, before the marker line
        decls.push("    fn pruv_check_utf8(p0: *const u8, p1: i64);".to_string());
    }
    if returns_array {
        decls.push("    fn pruv_runtime_rust_allocator_v2();".to_string());
    }
    o.push(ALLOW.to_string());
    o.push(format!("extern \"C\" {{\n{}\n}}", decls.join("\n")));
    for f in &pubs {
        let ps: Vec<String> = f.params.iter().map(|p| format!("{}: {}", p.name, rust_ty(&p.ty, true))).collect();
        let ps = ps.join(", ");
        let ret = if f.ret == "unit" { String::new() } else { format!(" -> {}", rust_ty(&f.ret, false)) };
        let mut pre: Vec<String> = Vec::new();
        let mut args: Vec<String> = Vec::new();
        for p in &f.params {
            if p.ty == "i64" {
                args.push(p.name.clone());
            } else if p.ty == "bool" {
                args.push(format!("{} as i64", p.name));
            } else if p.ty == "array_bool" {
                // G2 A5
                args.push(format!("{}.as_ptr() as *const u8", p.name));
                args.push(format!("{}.len() as i64", p.name));
            } else if p.ty == "str" {
                // G2 B2
                args.push(format!("{}.as_ptr()", p.name));
                args.push(format!("{}.len() as i64", p.name));
            } else if is_array_name(&p.ty) {
                args.push(format!("{}.as_ptr()", p.name));
                args.push(format!("{}.len() as i64", p.name));
            } else if is_agg(&p.ty) {
                let w = format!("pruv__w_{}", p.name);
                pre.push(format!("let mut {} = [0i64; {}];", w, words(&tt, &p.ty)?));
                let mut ctr = 0i64;
                pre.extend(rs_ser(&tt, &p.ty, &p.name, &w, 0, &mut ctr)?);
                args.push(format!("{}.as_ptr()", w));
            } else {
                if p.ty == "option" {
                    pre.push(format!(
                        "let (pruv__t_{}, pruv__v_{}): (i64, i64) = match {} {{ Some(v) => (1, v), None => (0, 0) }};",
                        p.name, p.name, p.name
                    ));
                } else {
                    pre.push(format!(
                        "let (pruv__t_{}, pruv__v_{}): (i64, i64) = match {} {{ Ok(v) => (1, v), Err(v) => (0, v) }};",
                        p.name, p.name, p.name
                    ));
                }
                args.push(format!("pruv__t_{}", p.name));
                args.push(format!("pruv__v_{}", p.name));
            }
        }
        let mut body: Vec<String> = Vec::new();
        if f.effects.iter().any(|e| e == "io") {
            body.push("::std::io::Write::flush(&mut ::std::io::stdout());".to_string());
        }
        if is_array_name(&f.ret) || f.ret == "str" {
            body.push(
                "let _ = ::std::hint::black_box(pruv_runtime_rust_allocator_v2 as unsafe extern \"C\" fn());".to_string(),
            );
        }
        body.extend(pre);
        let call = format!("pruv_abi_{}({})", typed_abi_name(f), args.join(", "));
        let mut args_out = args.clone();
        args_out.push("&mut pruv__out".to_string());
        let callo = format!("pruv_abi_{}({})", typed_abi_name(f), args_out.join(", "));
        if f.ret == "unit" {
            body.push(format!("{};", call));
        } else if f.ret == "i64" {
            body.push(call);
        } else if f.ret == "bool" {
            body.push(format!("{} != 0", call));
        } else if f.ret == "array_bool" {
            // G2 A5: after the check, take it as a Rust bool
            body.push("let mut pruv__out = Pruv__ArrayBool { data: ::std::ptr::null_mut(), len: 0 };".to_string());
            body.push(format!("{};", callo));
            body.push("pruv_check_bool(pruv__out.data, pruv__out.len);".to_string());
            body.push(
                "if pruv__out.len > 0 { ::std::vec::Vec::from_raw_parts(pruv__out.data as *mut bool, pruv__out.len as usize, \
                 pruv__out.len as usize) } else { ::std::vec::Vec::new() }"
                    .to_string(),
            );
        } else if f.ret == "str" {
            // G2 B2: after the check, take it as a Rust String
            body.push("let mut pruv__out = Pruv__Str { data: ::std::ptr::null_mut(), len: 0 };".to_string());
            body.push(format!("{};", callo));
            body.push("pruv_check_utf8(pruv__out.data, pruv__out.len);".to_string());
            body.push(
                "if pruv__out.len > 0 { ::std::string::String::from_utf8_unchecked(::std::vec::Vec::from_raw_parts(pruv__out.data, \
                 pruv__out.len as usize, pruv__out.len as usize)) } else { ::std::string::String::new() }"
                    .to_string(),
            );
        } else if is_array_name(&f.ret) {
            let out_ty = if f.ret == "array_u8" { "Pruv__ArrayU8" } else { "Pruv__Array" };
            body.push(format!("let mut pruv__out = {} {{ data: ::std::ptr::null_mut(), len: 0 }};", out_ty));
            body.push(format!("{};", callo));
            body.push(
                "if pruv__out.len > 0 { ::std::vec::Vec::from_raw_parts(pruv__out.data, pruv__out.len as usize, \
                 pruv__out.len as usize) } else { ::std::vec::Vec::new() }"
                    .to_string(),
            );
        } else if is_agg(&f.ret) {
            body.push(format!("let mut pruv__out = [0i64; {}];", words(&tt, &f.ret)?));
            let mut a2 = args.clone();
            a2.push("pruv__out.as_mut_ptr()".to_string());
            body.push(format!("pruv_abi_{}({});", typed_abi_name(f), a2.join(", ")));
            body.push(rs_de(&tt, &f.ret, "pruv__out", 0)?);
        } else {
            body.push(format!("let pruv__out = {};", call));
            if f.ret == "option" {
                body.push("if pruv__out.tag != 0 { Some(pruv__out.value) } else { None }".to_string());
            } else {
                body.push("if pruv__out.tag != 0 { Ok(pruv__out.value) } else { Err(pruv__out.value) }".to_string());
            }
        }
        o.push(ALLOW.to_string());
        let body_txt: Vec<String> = body.iter().map(|b| format!("        {}", b)).collect();
        o.push(format!(
            "#[inline]\npub fn {}({}){} {{\n    unsafe {{\n{}\n    }}\n}}",
            f.name,
            ps,
            ret,
            body_txt.join("\n")
        ));
    }
    let mut s = o.join("\n");
    s.push('\n');
    Ok(s)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn func(name: &str, params: Vec<(&str, &str)>, ret: &str) -> Function {
        Function {
            line: 1, col: 1, name: name.into(),
            params: params.into_iter().map(|(n, t)| Param { name: n.into(), ty: t.into(), refine: None, take: false }).collect(),
            ret: ret.into(), effects: vec![], requires: vec![], ensures: vec![], body: vec![], ret_refine: None, tparams: vec![],
            foreign: None,
        }
    }

    #[test]
    fn simple_function() {
        let prog = Program { functions: vec![func("f", vec![("x", "i64"), ("a", "array")], "bool")], types: vec![], refined: false };
        let s = gen_bindings(&prog).unwrap();
        assert!(s.contains("    fn pruv_abi_f(p0: i64, p1: *const i64, p2: i64) -> i64;"));
        assert!(s.contains("pub fn f(x: i64, a: &[i64]) -> bool {"));
        assert!(s.contains("        pruv_abi_f(x, a.as_ptr(), a.len() as i64) != 0"));
        assert!(s.ends_with("    }\n}\n"));
    }

    #[test]
    fn mangling_error() {
        let prog = Program { functions: vec![func("f\u{e9}", vec![], "unit")], types: vec![], refined: false };
        assert_eq!(
            gen_bindings(&prog).unwrap_err(),
            "llvmgen: function name f\u{e9} needs mangling; the bindings use the raw name"
        );
    }

    #[test]
    fn struct_param_ser() {
        let st = TypeDecl::Struct(StructDecl {
            line: 1, col: 1, name: "P".into(),
            fields: vec![
                FieldDecl { line: 1, col: 1, name: "x".into(), ty: "i64".into() },
                FieldDecl { line: 1, col: 1, name: "b".into(), ty: "bool".into() },
            ],
            tparams: vec![],
        });
        let tt = TypeTable::new(&[st]);
        let mut c = 0;
        assert_eq!(
            rs_ser(&tt, "P", "p", "w", 0, &mut c).unwrap(),
            vec!["w[0] = p.x;".to_string(), "w[1] = (p.b) as i64;".to_string()]
        );
        assert_eq!(rs_de(&tt, "P", "o", 0).unwrap(), "P { x: o[0], b: (o[1] != 0) }");
    }
}
