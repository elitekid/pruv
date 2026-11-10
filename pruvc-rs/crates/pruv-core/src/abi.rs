//! 외부 워드 형태(pruv_abi_*) IR 텍스트: llvmgen.py 의 Words 클래스와 abi_of(1124~1288행) 이식.
//! docs/M2_G1_SPEC.md 5절 W(T).

use crate::ast::*;
use crate::llvmgen::{lty, mangle, st, words, R, OPT};
use crate::typeinfo::{is_user_type, TypeTable};

pub struct Words<'a> {
    tt: &'a TypeTable,
    pub lines: Vec<String>,
    pub n: usize,
}

impl<'a> Words<'a> {
    pub fn new(tt: &'a TypeTable) -> Words<'a> {
        Words { tt, lines: Vec::new(), n: 0 }
    }

    pub fn op(&mut self, text: String) -> String {
        self.n += 1;
        let r = format!("%w.{}", self.n);
        self.lines.push(format!("{} = {}", r, text));
        r
    }

    pub fn gep(&mut self, ptr: &str, off: usize) -> String {
        self.op(format!("getelementptr inbounds i64, ptr {}, i64 {}", ptr, off))
    }

    pub fn rd(&mut self, ptr: &str, off: usize) -> String {
        let g = self.gep(ptr, off);
        self.op(format!("load i64, ptr {}", g))
    }

    pub fn wr(&mut self, ptr: &str, off: usize, v: &str) {
        let g = self.gep(ptr, off);
        self.lines.push(format!("store i64 {}, ptr {}", v, g));
    }

    /// words ptr[off..] 에서 타입 ty 의 값을 읽는다; st(ty) 타입 SSA 이름을 돌려준다
    pub fn de(&mut self, ty: &str, ptr: &str, off: usize) -> R<String> {
        let tt = self.tt;
        match ty {
            "i64" => return Ok(self.rd(ptr, off)),
            "bool" => {
                let x = self.rd(ptr, off);
                return Ok(self.op(format!("icmp ne i64 {}, 0", x)));
            }
            "option" | "result" => {
                let x = self.rd(ptr, off);
                let t = self.op(format!("icmp ne i64 {}, 0", x));
                let p = self.rd(ptr, off + 1);
                let a = self.op(format!("insertvalue {} undef, i1 {}, 0", OPT, t));
                return Ok(self.op(format!("insertvalue {} {}, i64 {}, 1", OPT, a, p)));
            }
            _ => {}
        }
        let d = tt.decl(ty).ok_or_else(|| format!("'{}'", ty))?;
        let tstr = st(ty, false);
        let mut acc = "zeroinitializer".to_string();
        match d {
            TypeDecl::Struct(sd) => {
                let mut o = off;
                for (i, f) in sd.fields.iter().enumerate() {
                    let x = self.de(&f.ty, ptr, o)?;
                    acc = self.op(format!("insertvalue {} {}, {} {}, {}", tstr, acc, st(&f.ty, false), x, i));
                    o += words(tt, &f.ty)?;
                }
                Ok(acc)
            }
            TypeDecl::Enum(ed) => {
                let tag = self.rd(ptr, off);
                acc = self.op(format!("insertvalue {} zeroinitializer, i64 {}, 0", tstr, tag));
                let mut o = off + 1;
                let mut idx = 1usize;
                for v in &ed.variants {
                    for f in &v.fields {
                        let x = self.de(&f.ty, ptr, o)?;
                        acc = self.op(format!("insertvalue {} {}, {} {}, {}", tstr, acc, st(&f.ty, false), x, idx));
                        o += words(tt, &f.ty)?;
                        idx += 1;
                    }
                }
                Ok(acc)
            }
        }
    }

    /// SSA 값 x(타입 st(ty))를 ptr[off..] 에 워드로 쓴다
    pub fn ser(&mut self, ty: &str, x: &str, ptr: &str, off: usize) -> R<()> {
        let tt = self.tt;
        match ty {
            "i64" => {
                self.wr(ptr, off, x);
                Ok(())
            }
            "bool" => {
                let z = self.op(format!("zext i1 {} to i64", x));
                self.wr(ptr, off, &z);
                Ok(())
            }
            "option" | "result" => {
                let t = self.op(format!("extractvalue {} {}, 0", OPT, x));
                let mut p = self.op(format!("extractvalue {} {}, 1", OPT, x));
                if ty == "option" {
                    // None 의 payload 는 0 으로 직렬화
                    p = self.op(format!("select i1 {}, i64 {}, i64 0", t, p));
                }
                let z = self.op(format!("zext i1 {} to i64", t));
                self.wr(ptr, off, &z);
                self.wr(ptr, off + 1, &p);
                Ok(())
            }
            _ => {
                let d = tt.decl(ty).ok_or_else(|| format!("'{}'", ty))?;
                let tstr = st(ty, false);
                match d {
                    TypeDecl::Struct(sd) => {
                        if sd.fields.is_empty() {
                            self.wr(ptr, off, "0");
                        }
                        let mut o = off;
                        for (i, f) in sd.fields.iter().enumerate() {
                            let e = self.op(format!("extractvalue {} {}, {}", tstr, x, i));
                            self.ser(&f.ty, &e, ptr, o)?;
                            o += words(tt, &f.ty)?;
                        }
                        Ok(())
                    }
                    TypeDecl::Enum(ed) => {
                        // 비활성 payload 는 구성상 0 (EnumCtor/역직렬화가 zeroinitializer 에서 시작)
                        let tag = self.op(format!("extractvalue {} {}, 0", tstr, x));
                        self.wr(ptr, off, &tag);
                        let mut o = off + 1;
                        let mut idx = 1usize;
                        for v in &ed.variants {
                            for f in &v.fields {
                                let e = self.op(format!("extractvalue {} {}, {}", tstr, x, idx));
                                self.ser(&f.ty, &e, ptr, o)?;
                                o += words(tt, &f.ty)?;
                                idx += 1;
                            }
                        }
                        Ok(())
                    }
                }
            }
        }
    }
}

pub fn abi_of(f: &Function, tt: &TypeTable) -> R<String> {
    let n = mangle(&f.name);
    let mut ext: Vec<String> = Vec::new();
    let mut pre: Vec<String> = Vec::new();
    let mut args: Vec<String> = Vec::new();
    let mut w = Words::new(tt);
    for p in &f.params {
        let q = mangle(&p.name);
        if is_user_type(&p.ty) {
            ext.push(format!("ptr %a.{}", q));
            let x = w.de(&p.ty, &format!("%a.{}", q), 0)?;
            args.push(format!("{} {}", lty(&p.ty), x));
            pre.extend(w.lines.drain(..));
        } else if p.ty == "i64" {
            ext.push(format!("i64 %a.{}", q));
            args.push(format!("i64 %a.{}", q));
        } else if p.ty == "bool" {
            ext.push(format!("i64 %a.{}", q));
            pre.push(format!("%c.{} = icmp ne i64 %a.{}, 0", q, q));
            args.push(format!("i1 %c.{}", q));
        } else if p.ty == "array" {
            ext.push(format!("ptr %a.{}.a", q));
            ext.push(format!("i64 %a.{}.n", q));
            args.push(format!("ptr %a.{}.a", q));
            args.push(format!("i64 %a.{}.n", q));
        } else {
            ext.push(format!("i64 %a.{}.t", q));
            ext.push(format!("i64 %a.{}.v", q));
            pre.push(format!("%c.{}.t = icmp ne i64 %a.{}.t, 0", q, q));
            pre.push(format!("%c.{}.g1 = insertvalue {} undef, i1 %c.{}.t, 0", q, OPT, q));
            pre.push(format!("%c.{}.g = insertvalue {} %c.{}.g1, i64 %a.{}.v, 1", q, OPT, q, q));
            args.push(format!("{} %c.{}.g", OPT, q));
        }
    }
    let rt = f.ret.as_str();
    let entry = format!("@{}__pruv_entry", n);
    let argl = args.join(", ");
    let mut body: Vec<String> = pre.iter().map(|x| format!("  {}", x)).collect();
    let ret: &str;
    if rt == "array" {
        ext.push("ptr %out".to_string());
        body.push(format!("  %r = call {} {}({})", lty(rt), entry, argl));
        body.push(format!("  %x0 = extractvalue {} %r, 0", lty(rt)));
        body.push(format!("  %x1 = extractvalue {} %r, 1", lty(rt)));
        body.push("  %o0 = getelementptr inbounds { ptr, i64 }, ptr %out, i32 0, i32 0".to_string());
        body.push("  %o1 = getelementptr inbounds { ptr, i64 }, ptr %out, i32 0, i32 1".to_string());
        body.push("  store ptr %x0, ptr %o0".to_string());
        body.push("  store i64 %x1, ptr %o1".to_string());
        body.push("  ret void".to_string());
        ret = "void";
    } else if rt == "option" || rt == "result" {
        // { i64, i64 } 값 반환(macOS arm64 / SysV x86-64 에서 레지스터 두 개)
        body.push(format!("  %r = call {} {}({})", lty(rt), entry, argl));
        body.push(format!("  %x0 = extractvalue {} %r, 0", lty(rt)));
        body.push(format!("  %x1 = extractvalue {} %r, 1", lty(rt)));
        body.push("  %x0z = zext i1 %x0 to i64".to_string());
        body.push("  %t0 = insertvalue { i64, i64 } undef, i64 %x0z, 0".to_string());
        body.push("  %t1 = insertvalue { i64, i64 } %t0, i64 %x1, 1".to_string());
        body.push("  ret { i64, i64 } %t1".to_string());
        ret = "{ i64, i64 }";
    } else if is_user_type(rt) {
        ext.push("ptr %out".to_string());
        body.push(format!("  %r = call {} {}({})", lty(rt), entry, argl));
        w.ser(rt, "%r", "%out", 0)?;
        for x in &w.lines {
            body.push(format!("  {}", x));
        }
        body.push("  ret void".to_string());
        ret = "void";
    } else if rt == "unit" {
        body.push(format!("  call void {}({})", entry, argl));
        body.push("  ret void".to_string());
        ret = "void";
    } else if rt == "bool" {
        body.push(format!("  %r = call i1 {}({})", entry, argl));
        body.push("  %rz = zext i1 %r to i64".to_string());
        body.push("  ret i64 %rz".to_string());
        ret = "i64";
    } else {
        body.push(format!("  %r = call i64 {}({})", entry, argl));
        body.push("  ret i64 %r".to_string());
        ret = "i64";
    }
    Ok(format!("define {} @pruv_abi_{}({}) {{\nentry:\n{}\n}}\n", ret, n, ext.join(", "), body.join("\n")))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn abi_i64_bool() {
        let tt = TypeTable::new(&[]);
        let f = Function {
            line: 1,
            col: 1,
            name: "f".into(),
            params: vec![Param { name: "x".into(), ty: "i64".into() }, Param { name: "b".into(), ty: "bool".into() }],
            ret: "bool".into(),
            effects: vec![],
            requires: vec![],
            ensures: vec![],
            body: vec![],
        };
        assert_eq!(
            abi_of(&f, &tt).unwrap(),
            "define i64 @pruv_abi_f(i64 %a.x, i64 %a.b) {\nentry:\n  %c.b = icmp ne i64 %a.b, 0\n  %r = call i1 @f__pruv_entry(i64 %a.x, i1 %c.b)\n  %rz = zext i1 %r to i64\n  ret i64 %rz\n}\n"
        );
    }
}
