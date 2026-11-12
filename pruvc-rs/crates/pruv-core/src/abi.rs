//! IR text for the external word form (pruv_abi_*): a port of llvmgen.py's Words class and abi_of (lines 1124-1288).
//! docs/M2_G1_SPEC.md §5 W(T).

use crate::ast::*;
use crate::llvmgen::{g_arg, is_agg, is_gopt, is_new_app, lty, mangle, st, words, Mod, R, OPT};
use crate::typeinfo::{is_array_name, is_user_type, TypeTable};
use std::collections::HashMap;

pub struct Words<'a> {
    tt: &'a TypeTable,
    pub lines: Vec<String>,
    pub n: usize,
    /// G3: (valid i1, raw tag word, type name) of every enum ordinal that must be rejected if invalid
    pub checks: Vec<(String, String, String)>,
    /// caches: storage type text per type key, "is or contains a G3 application" per type key
    stm: HashMap<String, String>,
    hn: HashMap<String, bool>,
}

impl<'a> Words<'a> {
    pub fn new(tt: &'a TypeTable) -> Words<'a> {
        Words { tt, lines: Vec::new(), n: 0, checks: Vec::new(), stm: HashMap::new(), hn: HashMap::new() }
    }

    /// st(ty, false), cached per type key
    fn s_of(&mut self, ty: &str) -> String {
        if let Some(r) = self.stm.get(ty) {
            return r.clone();
        }
        let r = if is_gopt(ty) {
            let x = self.s_of(g_arg(ty));
            if ty.starts_with("option<") {
                format!("{{ i1, {} }}", x)
            } else {
                format!("{{ i1, {}, i64 }}", x)
            }
        } else {
            st(ty, false)
        };
        self.stm.insert(ty.to_string(), r.clone());
        r
    }

    /// Whether ty is, or contains by value, a G3 application (its words follow the G3 rules).
    fn has_new(&mut self, ty: &str) -> bool {
        if let Some(&r) = self.hn.get(ty) {
            return r;
        }
        let tt = self.tt;
        let r = if is_new_app(ty) {
            true
        } else if !is_user_type(ty) {
            false
        } else {
            let mut found = false;
            match tt.decl(ty) {
                Some(TypeDecl::Struct(sd)) => {
                    for f in &sd.fields {
                        if self.has_new(&f.ty) {
                            found = true;
                            break;
                        }
                    }
                }
                Some(TypeDecl::Enum(ed)) => {
                    'outer: for v in &ed.variants {
                        for f in &v.fields {
                            if self.has_new(&f.ty) {
                                found = true;
                                break 'outer;
                            }
                        }
                    }
                }
                None => {}
            }
            found
        };
        self.hn.insert(ty.to_string(), r);
        r
    }

    /// Whether any field of the variant is (or contains) a G3 application.
    fn variant_has_new(&mut self, v: &VariantDecl) -> bool {
        for f in &v.fields {
            if self.has_new(&f.ty) {
                return true;
            }
        }
        false
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

    /// Reads a value of type ty from the words at ptr[off..]; returns the SSA name of type st(ty).
    /// `act` is None ("true") or an i1 telling whether this legacy value is active: it only matters for a G3
    /// application reached through legacy structs/enums, whose ordinal check happens only when its whole path is
    /// active (an inactive one reads zero).
    pub fn de(&mut self, ty: &str, ptr: &str, off: usize, act: Option<&str>) -> R<String> {
        let tt = self.tt;
        if is_new_app(ty) {
            // G3 application (new Option/Result, generated generic instance) and everything below it
            return self.de_new(ty, ptr, off, act);
        }
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
                    let x = self.de(&f.ty, ptr, o, act)?;
                    let fs = self.s_of(&f.ty);
                    acc = self.op(format!("insertvalue {} {}, {} {}, {}", tstr, acc, fs, x, i));
                    o += words(tt, &f.ty)?;
                }
                Ok(acc)
            }
            TypeDecl::Enum(ed) => {
                let tag = self.rd(ptr, off);
                acc = self.op(format!("insertvalue {} zeroinitializer, i64 {}, 0", tstr, tag));
                let mut o = off + 1;
                let mut idx = 1usize;
                for (k, v) in ed.variants.iter().enumerate() {
                    let mut ak: Option<String> = act.map(|s| s.to_string());
                    if self.variant_has_new(v) {
                        // only then is the activity of this payload observable
                        let mut a = self.op(format!("icmp eq i64 {}, {}", tag, k));
                        if let Some(outer) = act {
                            a = self.op(format!("and i1 {}, {}", outer, a));
                        }
                        ak = Some(a);
                    }
                    for f in &v.fields {
                        let x = self.de(&f.ty, ptr, o, ak.as_deref())?;
                        let fs = self.s_of(&f.ty);
                        acc = self.op(format!("insertvalue {} {}, {} {}, {}", tstr, acc, fs, x, idx));
                        o += words(tt, &f.ty)?;
                        idx += 1;
                    }
                }
                Ok(acc)
            }
        }
    }

    /// G3 reading of a value of type ty from the words at ptr[off..]. `act` is None ("true") or an i1 SSA name telling
    /// whether this value is semantically active: inactive words are read as zero, bool/tag words normalize by
    /// nonzero-to-true, and the ordinal of every active nominal enum must be < the variant count (recorded in
    /// `checks`; the wrapper rejects before requires/body).
    pub fn de_new(&mut self, ty: &str, ptr: &str, off: usize, act: Option<&str>) -> R<String> {
        let tt = self.tt;
        let on = act.is_some();
        if ty == "i64" {
            let w = self.rd(ptr, off);
            return Ok(match act {
                Some(a) => self.op(format!("select i1 {}, i64 {}, i64 0", a, w)),
                None => w,
            });
        }
        if ty == "bool" {
            let w = self.rd(ptr, off);
            let c = self.op(format!("icmp ne i64 {}, 0", w));
            return Ok(match act {
                Some(a) => self.op(format!("and i1 {}, {}", a, c)),
                None => c,
            });
        }
        if is_gopt(ty) {
            let x = g_arg(ty).to_string();
            let tstr = self.s_of(ty);
            let w = self.rd(ptr, off);
            let mut t = self.op(format!("icmp ne i64 {}, 0", w));
            if let Some(a) = act {
                t = self.op(format!("and i1 {}, {}", a, t));
            }
            let xv = self.de_new(&x, ptr, off + 1, Some(&t))?;
            let mut acc = self.op(format!("insertvalue {} zeroinitializer, i1 {}, 0", tstr, t));
            let xs = self.s_of(&x);
            acc = self.op(format!("insertvalue {} {}, {} {}, 1", tstr, acc, xs, xv));
            if ty.starts_with("result<") {
                let ew = self.rd(ptr, off + 1 + words(tt, &x)?);
                let mut ea = self.op(format!("xor i1 {}, true", t));
                if let Some(a) = act {
                    ea = self.op(format!("and i1 {}, {}", a, ea));
                }
                let e = self.op(format!("select i1 {}, i64 {}, i64 0", ea, ew));
                acc = self.op(format!("insertvalue {} {}, i64 {}, 2", tstr, acc, e));
            }
            return Ok(acc);
        }
        if ty == "option" || ty == "result" {
            // legacy Option<i64>/Result<i64> nested in a G3 value
            let w = self.rd(ptr, off);
            let mut t = self.op(format!("icmp ne i64 {}, 0", w));
            if let Some(a) = act {
                t = self.op(format!("and i1 {}, {}", a, t));
            }
            let mut p = self.rd(ptr, off + 1);
            let pa: Option<String> = if ty == "option" { Some(t.clone()) } else { act.map(|s| s.to_string()) };
            if let Some(pa) = pa {
                p = self.op(format!("select i1 {}, i64 {}, i64 0", pa, p));
            }
            let a = self.op(format!("insertvalue {} undef, i1 {}, 0", OPT, t));
            return Ok(self.op(format!("insertvalue {} {}, i64 {}, 1", OPT, a, p)));
        }
        let d = tt.decl(ty).ok_or_else(|| format!("'{}'", ty))?;
        let tstr = st(ty, false);
        let mut acc = "zeroinitializer".to_string();
        match d {
            TypeDecl::Struct(sd) => {
                let mut o = off;
                for (i, f) in sd.fields.iter().enumerate() {
                    let x = self.de_new(&f.ty, ptr, o, act)?;
                    let fs = self.s_of(&f.ty);
                    acc = self.op(format!("insertvalue {} {}, {} {}, {}", tstr, acc, fs, x, i));
                    o += words(tt, &f.ty)?;
                }
                Ok(acc)
            }
            TypeDecl::Enum(ed) => {
                let w = self.rd(ptr, off);
                let mut ok = self.op(format!("icmp ult i64 {}, {}", w, ed.variants.len()));
                if let Some(a) = act {
                    let na = self.op(format!("xor i1 {}, true", a));
                    ok = self.op(format!("or i1 {}, {}", na, ok));
                }
                // G4: source-qualified type identity in explicit mode (Python `getattr(d, "disp", ty.name)`)
                self.checks.push((ok, w.clone(), crate::emit_common::type_disp(ty)));
                let tag = match act {
                    Some(a) if on => self.op(format!("select i1 {}, i64 {}, i64 0", a, w)),
                    _ => w.clone(),
                };
                acc = self.op(format!("insertvalue {} zeroinitializer, i64 {}, 0", tstr, tag));
                let mut o = off + 1;
                let mut idx = 1usize;
                for (k, v) in ed.variants.iter().enumerate() {
                    let mut ak: Option<String> = None;
                    if !v.fields.is_empty() {
                        let mut a = self.op(format!("icmp eq i64 {}, {}", w, k));
                        if let Some(outer) = act {
                            a = self.op(format!("and i1 {}, {}", outer, a));
                        }
                        ak = Some(a);
                    }
                    for f in &v.fields {
                        let x = self.de_new(&f.ty, ptr, o, ak.as_deref())?;
                        let fs = self.s_of(&f.ty);
                        acc = self.op(format!("insertvalue {} {}, {} {}, {}", tstr, acc, fs, x, idx));
                        o += words(tt, &f.ty)?;
                        idx += 1;
                    }
                }
                Ok(acc)
            }
        }
    }

    /// G3 writing of the SSA value x (of type st(ty)) as words to ptr[off..]. `act` is None ("true") or an i1 telling
    /// whether this value is semantically active. Every inactive word is written explicitly as zero (a legacy-ABI
    /// value may carry dirty inactive storage), propagating the activity recursively: an Option payload is active when
    /// the tag is set, a Result error word when it is not, an enum payload when the tag selects its variant.
    pub fn ser_new(&mut self, ty: &str, x: &str, ptr: &str, off: usize, act: Option<&str>) -> R<()> {
        let tt = self.tt;
        if ty == "i64" {
            let v = match act {
                Some(a) => self.op(format!("select i1 {}, i64 {}, i64 0", a, x)),
                None => x.to_string(),
            };
            self.wr(ptr, off, &v);
            return Ok(());
        }
        if ty == "bool" {
            let b = match act {
                Some(a) => self.op(format!("and i1 {}, {}", a, x)),
                None => x.to_string(),
            };
            let z = self.op(format!("zext i1 {} to i64", b));
            self.wr(ptr, off, &z);
            return Ok(());
        }
        if is_gopt(ty) {
            // tag word, payload words, (Result) error word
            let xt = g_arg(ty).to_string();
            let tstr = self.s_of(ty);
            let mut t = self.op(format!("extractvalue {} {}, 0", tstr, x));
            if let Some(a) = act {
                t = self.op(format!("and i1 {}, {}", a, t));
            }
            let z = self.op(format!("zext i1 {} to i64", t));
            self.wr(ptr, off, &z);
            let p = self.op(format!("extractvalue {} {}, 1", tstr, x));
            self.ser_new(&xt, &p, ptr, off + 1, Some(&t))?;
            if ty.starts_with("result<") {
                let e = self.op(format!("extractvalue {} {}, 2", tstr, x));
                let mut ea = self.op(format!("xor i1 {}, true", t));
                if let Some(a) = act {
                    ea = self.op(format!("and i1 {}, {}", a, ea));
                }
                let e2 = self.op(format!("select i1 {}, i64 {}, i64 0", ea, e));
                self.wr(ptr, off + 1 + words(tt, &xt)?, &e2);
            }
            return Ok(());
        }
        if ty == "option" || ty == "result" {
            // legacy Option<i64>/Result<i64> nested in a G3 value
            let mut t = self.op(format!("extractvalue {} {}, 0", OPT, x));
            let mut p = self.op(format!("extractvalue {} {}, 1", OPT, x));
            if let Some(a) = act {
                t = self.op(format!("and i1 {}, {}", a, t));
            }
            let pa: Option<String> = if ty == "option" { Some(t.clone()) } else { act.map(|s| s.to_string()) };
            if let Some(pa) = pa {
                p = self.op(format!("select i1 {}, i64 {}, i64 0", pa, p));
            }
            let z = self.op(format!("zext i1 {} to i64", t));
            self.wr(ptr, off, &z);
            self.wr(ptr, off + 1, &p);
            return Ok(());
        }
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
                    self.ser_new(&f.ty, &e, ptr, o, act)?;
                    o += words(tt, &f.ty)?;
                }
                Ok(())
            }
            TypeDecl::Enum(ed) => {
                let tag = self.op(format!("extractvalue {} {}, 0", tstr, x));
                let tw = match act {
                    Some(a) => self.op(format!("select i1 {}, i64 {}, i64 0", a, tag)),
                    None => tag.clone(),
                };
                self.wr(ptr, off, &tw);
                let mut o = off + 1;
                let mut idx = 1usize;
                for (k, v) in ed.variants.iter().enumerate() {
                    let mut ak: Option<String> = None;
                    if !v.fields.is_empty() {
                        let mut a = self.op(format!("icmp eq i64 {}, {}", tag, k));
                        if let Some(outer) = act {
                            a = self.op(format!("and i1 {}, {}", outer, a));
                        }
                        ak = Some(a);
                    }
                    for f in &v.fields {
                        let e = self.op(format!("extractvalue {} {}, {}", tstr, x, idx));
                        self.ser_new(&f.ty, &e, ptr, o, ak.as_deref())?;
                        o += words(tt, &f.ty)?;
                        idx += 1;
                    }
                }
                Ok(())
            }
        }
    }

    /// Writes the SSA value x (of type st(ty)) as words to ptr[off..]. A purely legacy value is written as it is (the
    /// legacy ABI output stays byte-identical); a G3 application and everything nested in it goes through ser_new,
    /// also when it hangs below a legacy struct/enum (`act`: whether that legacy value is active).
    pub fn ser(&mut self, ty: &str, x: &str, ptr: &str, off: usize, act: Option<&str>) -> R<()> {
        let tt = self.tt;
        if is_new_app(ty) {
            return self.ser_new(ty, x, ptr, off, act);
        }
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
                    // The payload of None is serialized as 0
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
                            self.ser(&f.ty, &e, ptr, o, act)?;
                            o += words(tt, &f.ty)?;
                        }
                        Ok(())
                    }
                    TypeDecl::Enum(ed) => {
                        // legacy words are written as they are; only a G3 application below has its inactivity made explicit
                        let tag = self.op(format!("extractvalue {} {}, 0", tstr, x));
                        self.wr(ptr, off, &tag);
                        let mut o = off + 1;
                        let mut idx = 1usize;
                        for (k, v) in ed.variants.iter().enumerate() {
                            let mut ak: Option<String> = act.map(|s| s.to_string());
                            if self.variant_has_new(v) {
                                let mut a = self.op(format!("icmp eq i64 {}, {}", tag, k));
                                if let Some(outer) = act {
                                    a = self.op(format!("and i1 {}, {}", outer, a));
                                }
                                ak = Some(a);
                            }
                            for f in &v.fields {
                                let e = self.op(format!("extractvalue {} {}, {}", tstr, x, idx));
                                self.ser(&f.ty, &e, ptr, o, ak.as_deref())?;
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

/// The C ABI target the wrapper follows. SysV = macOS arm64/x64 and Linux x64 (existing output).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum AbiTarget {
    SysV,
    WinX64,
}

pub fn abi_of(f: &Function, tt: &TypeTable, target: AbiTarget, m: &mut Mod) -> R<String> {
    abi_of_target(f, tt, target, m, "entry")
}

/// Python `abi_of(f, tt, m, target)`: `callee` is the internal function the wrapper calls, `entry` (checked, legacy) or
/// `body` (G4 explicit mode when the host boundary needs no requires check). The representation checks run in every mode.
pub fn abi_of_target(f: &Function, tt: &TypeTable, target: AbiTarget, m: &mut Mod, callee: &str) -> R<String> {
    // G5 A3: defensive, an inout function is never host-visible
    if crate::llvmgen::has_inout(f) || crate::llvmgen::is_internal_fn(f, tt) {
        return Err(format!("llvmgen: {} has no host ABI wrapper (inout or extended signature)", f.name));
    }
    let n = mangle(&f.name);
    let mut ext: Vec<String> = Vec::new();
    let mut pre: Vec<String> = Vec::new();
    let mut args: Vec<String> = Vec::new();
    let mut w = Words::new(tt);
    for p in &f.params {
        let q = mangle(&p.name);
        if is_array_name(&p.ty) || p.ty == "str" {
            ext.push(format!("ptr %a.{}.a", q));
            ext.push(format!("i64 %a.{}.n", q));
            args.push(format!("ptr %a.{}.a", q));
            args.push(format!("i64 %a.{}.n", q));
            if p.ty == "array_bool" {
                // G2 A5: at the raw entry, first check that every byte is 0/1
                pre.push(format!("call void @pruv_check_bool(ptr %a.{}.a, i64 %a.{}.n)", q, q));
            }
            if p.ty == "str" {
                // G2 B2: at the raw entry, first check that the byte sequence is valid UTF-8
                pre.push(format!("call void @pruv_check_utf8(ptr %a.{}.a, i64 %a.{}.n)", q, q));
            }
        } else if is_agg(&p.ty) {
            ext.push(format!("ptr %a.{}", q));
            let x = w.de(&p.ty, &format!("%a.{}", q), 0, None)?;
            args.push(format!("{} {}", lty(&p.ty), x));
            pre.extend(w.lines.drain(..));
        } else if p.ty == "i64" {
            ext.push(format!("i64 %a.{}", q));
            args.push(format!("i64 %a.{}", q));
        } else if p.ty == "bool" {
            ext.push(format!("i64 %a.{}", q));
            pre.push(format!("%c.{} = icmp ne i64 %a.{}, 0", q, q));
            args.push(format!("i1 %c.{}", q));
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
    let entry = format!("@{}__pruv_{}", n, callee);
    let argl = args.join(", ");
    let mut body: Vec<String> = pre.iter().map(|x| format!("  {}", x)).collect();
    for (k, (okv, wv, tname)) in w.checks.iter().enumerate() {
        // G3: an invalid nominal enum ordinal is rejected here, before the entry (requires) and the body run
        let msg = m.string(&format!("enum {}", tname));
        m.uses_repr = true;
        body.push(format!("  br i1 {}, label %enum.ok{}, label %enum.bad{}", okv, k, k));
        body.push(format!("enum.bad{}:", k));
        body.push(format!("  call void @pruv_panic_repr(i64 {}, ptr {})", wv, msg));
        body.push("  unreachable".to_string());
        body.push(format!("enum.ok{}:", k));
    }
    let ret: &str;
    if is_array_name(rt) || rt == "str" {
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
    } else if (rt == "option" || rt == "result") && target == AbiTarget::WinX64 {
        // Windows x64: a 16-byte aggregate is returned through a hidden sret pointer (first parameter)
        ext.insert(0, "ptr sret({ i64, i64 }) align 8 %sret".to_string());
        body.push(format!("  %r = call {} {}({})", lty(rt), entry, argl));
        body.push(format!("  %x0 = extractvalue {} %r, 0", lty(rt)));
        body.push(format!("  %x1 = extractvalue {} %r, 1", lty(rt)));
        body.push("  %x0z = zext i1 %x0 to i64".to_string());
        body.push("  %sl0 = getelementptr inbounds { i64, i64 }, ptr %sret, i32 0, i32 0".to_string());
        body.push("  %sl1 = getelementptr inbounds { i64, i64 }, ptr %sret, i32 0, i32 1".to_string());
        body.push("  store i64 %x0z, ptr %sl0, align 8".to_string());
        body.push("  store i64 %x1, ptr %sl1, align 8".to_string());
        body.push("  ret void".to_string());
        ret = "void";
    } else if rt == "option" || rt == "result" {
        // Returns a { i64, i64 } value (two registers on macOS arm64 / SysV x86-64)
        body.push(format!("  %r = call {} {}({})", lty(rt), entry, argl));
        body.push(format!("  %x0 = extractvalue {} %r, 0", lty(rt)));
        body.push(format!("  %x1 = extractvalue {} %r, 1", lty(rt)));
        body.push("  %x0z = zext i1 %x0 to i64".to_string());
        body.push("  %t0 = insertvalue { i64, i64 } undef, i64 %x0z, 0".to_string());
        body.push("  %t1 = insertvalue { i64, i64 } %t0, i64 %x1, 1".to_string());
        body.push("  ret { i64, i64 } %t1".to_string());
        ret = "{ i64, i64 }";
    } else if is_agg(rt) {
        ext.push("ptr %out".to_string());
        body.push(format!("  %r = call {} {}({})", lty(rt), entry, argl));
        w.ser(rt, "%r", "%out", 0, None)?;
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
    let mut out = format!("define {} @pruv_abi_{}({}) {{\nentry:\n{}\n}}\n", ret, n, ext.join(", "), body.join("\n"));
    if f.params.iter().any(|p| p.ty == "array_bool" || p.ty == "str") {
        // G2 A5: the typed Rust binding passes a type-valid &[bool] through this entry, which has no byte check
        // G2 B2: the same for &str (the valid-UTF-8 check line is omitted)
        let tb: Vec<&str> = body
            .iter()
            .map(|x| x.as_str())
            .filter(|x| !x.starts_with("  call void @pruv_check_bool(") && !x.starts_with("  call void @pruv_check_utf8("))
            .collect();
        out.push_str(&format!("\ndefine {} @pruv_abi_{}__typed({}) {{\nentry:\n{}\n}}\n", ret, n, ext.join(", "), tb.join("\n")));
    }
    Ok(out)
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
            params: vec![
                Param { name: "x".into(), ty: "i64".into(), refine: None, take: false, mode_pos: None },
                Param { name: "b".into(), ty: "bool".into(), refine: None, take: false, mode_pos: None },
            ],
            ret: "bool".into(),
            effects: vec![],
            requires: vec![],
            ensures: vec![],
            body: vec![],
            ret_refine: None,
            tparams: vec![],
            foreign: None,
            cost: None, decreases: None,
        };
        assert_eq!(
            abi_of(&f, &tt, AbiTarget::SysV, &mut Mod::new()).unwrap(),
            "define i64 @pruv_abi_f(i64 %a.x, i64 %a.b) {\nentry:\n  %c.b = icmp ne i64 %a.b, 0\n  %r = call i1 @f__pruv_entry(i64 %a.x, i1 %c.b)\n  %rz = zext i1 %r to i64\n  ret i64 %rz\n}\n"
        );
        // i64/bool returns are independent of the target
        assert_eq!(
            abi_of(&f, &tt, AbiTarget::WinX64, &mut Mod::new()).unwrap(),
            abi_of(&f, &tt, AbiTarget::SysV, &mut Mod::new()).unwrap()
        );
    }

    fn opt_fn() -> Function {
        Function {
            line: 1,
            col: 1,
            name: "f".into(),
            params: vec![Param { name: "x".into(), ty: "i64".into(), refine: None, take: false, mode_pos: None }],
            ret: "option".into(),
            effects: vec![],
            requires: vec![],
            ensures: vec![],
            body: vec![],
            ret_refine: None,
            tparams: vec![],
            foreign: None,
            cost: None, decreases: None,
        }
    }

    #[test]
    fn abi_option_sysv() {
        let tt = TypeTable::new(&[]);
        assert_eq!(
            abi_of(&opt_fn(), &tt, AbiTarget::SysV, &mut Mod::new()).unwrap(),
            "define { i64, i64 } @pruv_abi_f(i64 %a.x) {\nentry:\n  %r = call { i1, i64 } @f__pruv_entry(i64 %a.x)\n  %x0 = extractvalue { i1, i64 } %r, 0\n  %x1 = extractvalue { i1, i64 } %r, 1\n  %x0z = zext i1 %x0 to i64\n  %t0 = insertvalue { i64, i64 } undef, i64 %x0z, 0\n  %t1 = insertvalue { i64, i64 } %t0, i64 %x1, 1\n  ret { i64, i64 } %t1\n}\n"
        );
    }

    #[test]
    fn abi_option_win_sret() {
        let tt = TypeTable::new(&[]);
        let t = abi_of(&opt_fn(), &tt, AbiTarget::WinX64, &mut Mod::new()).unwrap();
        assert!(t.starts_with("define void @pruv_abi_f(ptr sret({ i64, i64 }) align 8 %sret, i64 %a.x) {\nentry:\n"));
        assert!(t.contains("  store i64 %x0z, ptr %sl0, align 8\n  store i64 %x1, ptr %sl1, align 8\n  ret void\n}\n"));
    }
}
