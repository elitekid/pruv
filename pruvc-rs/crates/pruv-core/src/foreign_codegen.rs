//! G6 A2 (docs/G6_SPEC.md section 12; counterpart of pruvc/foreign_codegen.py): Rust-source boundary helpers for the
//! standard catalog and for `trusted rust fn` declarations, the three check modes, and the `<out>.foreign.json` manifest.
//!
//! ForeignGen is owned by a codegen Gen (only created for a program that uses G6). Helpers are private Rust functions
//! named `pruv_g6_<op>__<enc>[__<enc>]` (catalog instance; <enc> = gtype::encode of each concrete, un-lowered type
//! argument), `pruv_g6_map_updated__<enc>__<enc>` (contract scan) and `NAME` (the helper of `trusted rust fn NAME`),
//! and are emitted once each, in first-use order, in front of the Pruv functions.
//!
//! The trusted-helper body needs the contract generator (`Gen::c`), so it lives in codegen.rs; this module only owns the
//! item table, the text skeletons and the manifest.

use crate::ast::Program;
use crate::codegen::{fmt_underscore, ALLOW_G6};
use crate::emit_common::{rstr, rty_g, show, try_conv_g, try_cty_g};
use crate::gtype::{encode, format_type, mk_option, GType};
use crate::modules::safe_type_cow;
use std::collections::HashSet;

type R<T> = Result<T, String>;

fn budget_line(n: u64) -> String {
    format!("let mut pruv_budget: i64 = {};", fmt_underscore(n))
}

fn idx_err() -> String {
    "list index out of range".to_string()
}

pub struct ForeignGen {
    /// requires | all | off
    pub mode: String,
    /// requires checks are emitted (every mode but off)
    pub req: bool,
    /// ensures checks are emitted (mode all)
    pub ens: bool,
    budget: u64,
    /// helper name -> text (insertion order = first use)
    items: Vec<(String, String)>,
    /// manifest: executable catalog instances in first-use order: (op, type_args)
    catalog: Vec<(String, Vec<String>)>,
    /// trusted fn names called from an emitted function
    pub called: HashSet<String>,
    op: String,
}

impl ForeignGen {
    pub fn new(mode: &str, budget: u64) -> ForeignGen {
        ForeignGen {
            mode: mode.to_string(),
            req: mode != "off",
            ens: mode == "all",
            budget,
            items: Vec::new(),
            catalog: Vec::new(),
            called: HashSet::new(),
            op: String::new(),
        }
    }

    // ------------------------------------------------------------------ results
    pub fn helper_texts(&self) -> Vec<String> {
        self.items.iter().map(|(_, t)| t.clone()).collect()
    }

    /// G6 A3: (helper name, text) of every emitted helper, in first-use order
    pub fn items(&self) -> &[(String, String)] {
        &self.items
    }

    pub fn has_item(&self, name: &str) -> bool {
        self.items.iter().any(|(n, _)| n == name)
    }

    pub fn set_op(&mut self, op: &str) {
        self.op = op.to_string();
    }

    pub fn add_item(&mut self, name: &str, text: String) {
        self.items.push((name.to_string(), text));
    }

    pub fn manifest(&self, prog: &Program, externs: &[(String, String)]) -> String {
        let mut trusted: Vec<J> = Vec::new();
        for (fi, f) in prog.functions.iter().enumerate() {
            let info = match &f.foreign {
                Some(i) => i,
                None => continue,
            };
            // G4 A2: explicit mode lists the source-qualified identity (crate::m::f), never the encoded stem
            let disp: &str = match &prog.explicit {
                Some(x) => &x.fns[fi].disp,
                None => &f.name,
            };
            trusted.push(J::O(vec![
                ("name".to_string(), J::s(disp)),
                ("path".to_string(), J::s(&info.path)),
                ("line".to_string(), J::I(crate::diagnostic::plain_line(f.line))),
                ("col".to_string(), J::I(f.col)),
                ("effects".to_string(), J::A(f.effects.iter().map(|e| J::s(e)).collect())),
                ("requires".to_string(), J::A(f.requires.iter().map(|r| J::Str(show(r))).collect())),
                ("ensures".to_string(), J::A(f.ensures.iter().map(|x| J::Str(show(x))).collect())),
                ("reachable".to_string(), J::B(self.called.contains(&f.name))),
            ]));
        }
        let catalog: Vec<J> = self
            .catalog
            .iter()
            .map(|(op, targs)| {
                J::O(vec![
                    ("op".to_string(), J::s(op)),
                    ("type_args".to_string(), J::A(targs.iter().map(|t| J::s(t)).collect())),
                ])
            })
            .collect();
        let ext: Vec<J> = externs
            .iter()
            .map(|(n, p)| J::O(vec![("name".to_string(), J::s(n)), ("path".to_string(), J::s(p))]))
            .collect();
        let doc = J::O(vec![
            ("schema".to_string(), J::s("pruv-foreign-v1")),
            ("backend".to_string(), J::s("rust")),
            ("check_mode".to_string(), J::s(&self.mode)),
            ("rustc_checked".to_string(), J::B(false)),
            ("trusted".to_string(), J::A(trusted)),
            ("catalog".to_string(), J::A(catalog)),
            ("externs".to_string(), J::A(ext)),
        ]);
        let mut out = String::new();
        dump_json(&doc, 0, &mut out);
        out.push('\n');
        out
    }

    // ------------------------------------------------------------------ helper skeleton
    /// text of `fn name(params) -> ret { guard; budget; body }`; body: lines (already without indentation)
    fn fn_text(&self, name: &str, params: &str, ret: Option<&str>, body: &[String]) -> String {
        let mut l: Vec<String> = Vec::new();
        l.push(ALLOW_G6.to_string());
        let arrow = match ret {
            None => String::new(),
            Some(r) => format!(" -> {}", r),
        };
        l.push(format!("fn {}({}){} {{", name, params, arrow));
        if self.req {
            l.push(format!("    let pruv_g = pruv_ctx({});", rstr(&self.op)));
        }
        if self.ens {
            l.push(format!("    {}", budget_line(self.budget)));
        }
        for x in body {
            l.push(format!("    {}", x));
        }
        l.push("}".to_string());
        format!("{}\n", l.join("\n"))
    }

    /// the helper of a trusted fn: the guard and the budget are shared by requires and ensures of one call
    /// `disp`: the name the boundary guard reports (G4 A2: the source identity; the helper itself keeps its stem `name`)
    pub fn fn_trusted(&self, name: &str, params: &str, ret: Option<&str>, body: &[String], disp: &str) -> String {
        let mut l: Vec<String> = Vec::new();
        l.push(ALLOW_G6.to_string());
        let arrow = match ret {
            None => String::new(),
            Some(r) => format!(" -> {}", r),
        };
        l.push(format!("fn {}({}){} {{", name, params, arrow));
        if self.req {
            l.push(format!("    let pruv_g = pruv_ctx({});", rstr(disp)));
            l.push(format!("    {}", budget_line(self.budget)));
        }
        for x in body {
            l.push(format!("    {}", x));
        }
        l.push("}".to_string());
        format!("{}\n", l.join("\n"))
    }

    fn req_line(&self, cond: &str, text: &str) -> Vec<String> {
        if self.req {
            vec![format!("if !({}) {{ pruv_g6_req({}, {}); }}", cond, rstr(&self.op), rstr(text))]
        } else {
            Vec::new()
        }
    }

    fn ens_line(&self, cond: &str, text: &str) -> Vec<String> {
        if self.ens {
            vec![format!("if !({}) {{ pruv_g6_ens({}, {}); }}", cond, rstr(&self.op), rstr(text))]
        } else {
            Vec::new()
        }
    }

    /// snapshot of a consumed input (mode all): charge its elements, then an independent clone
    fn snap(&self, ty: &str, src: &str) -> Vec<String> {
        if !self.ens {
            return Vec::new();
        }
        vec![
            format!("pruv_g6_charge(&mut pruv_budget, {}.len());", src),
            format!("let pruv_snap: {} = {}.clone();", ty, src),
        ]
    }

    // ------------------------------------------------------------------ catalog
    pub fn catalog_helper(&mut self, op: &str, low: &[GType], src: &[GType]) -> R<String> {
        let src: &[GType] = if src.is_empty() && !low.is_empty() { low } else { src };
        let mut name = format!("pruv_g6_{}", op);
        for t in src {
            name.push_str("__");
            name.push_str(&encode(&safe_type_cow(t))?); // G4: nominal identities use their [0-9A-Za-z_] encoding
        }
        if !self.has_item(&name) {
            self.op = op.to_string();
            let text = self.catalog_text(op, &name, low)?;
            self.items.push((name.clone(), text));
            self.catalog.push((op.to_string(), src.iter().map(format_type).collect()));
        }
        Ok(name)
    }

    fn catalog_text(&self, op: &str, name: &str, low: &[GType]) -> R<String> {
        const STRING: &str = "::std::string::String";
        let g = |i: usize| low.get(i).ok_or_else(idx_err);
        match op {
            "vec_new" => {
                let t = rty_g(g(0)?, false);
                let v = rty_g(&GType::new("vec", vec![g(0)?.clone()]), false);
                let mut body = vec![format!("let pruv_r: {} = ::std::vec::Vec::<{}>::new();", v, t)];
                body.extend(self.ens_line("pruv_r.len() == 0", "len(result) == 0"));
                body.push("pruv_r".to_string());
                Ok(self.fn_text(name, "", Some(v.as_str()), &body))
            }
            "vec_push" => {
                let t = rty_g(g(0)?, false);
                let v = rty_g(&GType::new("vec", vec![g(0)?.clone()]), false);
                let mut body = self.req_line("(v.len() as u64) < (1u64 << 40)", "len(v) < 2^40");
                body.extend(self.snap(&v, "v"));
                body.push("v.push(x);".to_string());
                body.extend(self.ens_line("v.len() == pruv_snap.len() + 1", "len(result) == len(v) + 1"));
                if self.ens {
                    body.push("pruv_g6_charge(&mut pruv_budget, pruv_snap.len());".to_string());
                }
                body.extend(self.ens_line("v[..pruv_snap.len()] == pruv_snap[..]", "result[..len(v)] == v"));
                if self.ens {
                    body.push("pruv_g6_charge(&mut pruv_budget, 1);".to_string()); // one visited element (G6_SPEC 12.3)
                }
                body.extend(self.ens_line("v[pruv_snap.len()] == x", "result[len(v)] == x"));
                body.push("v".to_string());
                Ok(self.fn_text(name, &format!("mut v: {}, x: {}", v, t), Some(v.as_str()), &body))
            }
            "vec_get" => {
                let t = rty_g(g(0)?, false);
                let v = rty_g(&GType::new("vec", vec![g(0)?.clone()]), false);
                let mut body = self.req_line("i >= 0 && (i as u64) < (v.len() as u64)", "0 <= i && i < len(v)");
                body.push(
                    "let pruv_k: usize = if i >= 0 && (i as u64) < (v.len() as u64) { i as usize } else { pruv_g6_repr(\"index\") };"
                        .to_string(),
                );
                body.push(format!("let pruv_r: {} = v[pruv_k];", t));
                if self.ens {
                    body.push("pruv_g6_charge(&mut pruv_budget, 1);".to_string()); // one visited element (G6_SPEC 12.3)
                }
                body.extend(self.ens_line("v.get(pruv_k).copied() == Some(pruv_r)", "result == v[i]"));
                body.push("pruv_r".to_string());
                Ok(self.fn_text(name, &format!("v: &{}, i: i64", v), Some(t.as_str()), &body))
            }
            "map_new" => {
                let k = rty_g(g(0)?, false);
                let t = rty_g(g(1)?, false);
                let m = rty_g(&GType::new("hashmap", vec![g(0)?.clone(), g(1)?.clone()]), false);
                let mut body = vec![format!("let pruv_r: {} = ::std::collections::HashMap::<{}, {}>::new();", m, k, t)];
                body.extend(self.ens_line("pruv_r.len() == 0", "len(result) == 0"));
                body.push("pruv_r".to_string());
                Ok(self.fn_text(name, "", Some(m.as_str()), &body))
            }
            "map_get" => {
                let k = rty_g(g(0)?, false);
                let m = rty_g(&GType::new("hashmap", vec![g(0)?.clone(), g(1)?.clone()]), false);
                let opt = rty_g(&mk_option(g(1)?.clone()), false);
                let mut body = vec![format!("let pruv_r: {} = m.get(&k).copied();", opt)];
                if self.ens {
                    body.push("pruv_g6_charge(&mut pruv_budget, 1);".to_string()); // one visited element (G6_SPEC 12.3)
                }
                body.extend(self.ens_line(
                    "m.contains_key(&k) == pruv_r.is_some() && m.get(&k).copied() == pruv_r",
                    "result == map_lookup(m, k)",
                ));
                body.push("pruv_r".to_string());
                Ok(self.fn_text(name, &format!("m: &{}, k: {}", m, k), Some(opt.as_str()), &body))
            }
            "map_insert" => {
                let k = rty_g(g(0)?, false);
                let t = rty_g(g(1)?, false);
                let m = rty_g(&GType::new("hashmap", vec![g(0)?.clone(), g(1)?.clone()]), false);
                let mut body = self.req_line("m.contains_key(&k) || (m.len() as u64) < (1u64 << 40)", "k in m || len(m) < 2^40");
                body.extend(self.snap(&m, "m"));
                body.push("let _ = m.insert(k, v);".to_string());
                body.extend(self.ens_line(
                    "m.len() == pruv_snap.len() + (if pruv_snap.contains_key(&k) { 0 } else { 1 })",
                    "len(result) == len(m) + (k absent ? 1 : 0)",
                ));
                if self.ens {
                    body.push("pruv_g6_charge(&mut pruv_budget, 1);".to_string()); // one visited element (G6_SPEC 12.3)
                }
                body.extend(self.ens_line("m.get(&k) == Some(&v)", "result[k] == v"));
                if self.ens {
                    body.push("for (pruv_sk, pruv_sv) in pruv_snap.iter() {".to_string());
                    body.push("    pruv_g6_charge(&mut pruv_budget, 1);".to_string());
                    body.push(format!(
                        "    if *pruv_sk != k && m.get(pruv_sk) != Some(pruv_sv) {{ pruv_g6_ens({}, \"entries other than k are unchanged\"); }}",
                        rstr(op)
                    ));
                    body.push("}".to_string());
                }
                body.push("m".to_string());
                Ok(self.fn_text(name, &format!("mut m: {}, k: {}, v: {}", m, k, t), Some(m.as_str()), &body))
            }
            "string_new" => {
                let mut body = vec![format!("let pruv_r: {} = ::std::string::String::new();", STRING)];
                body.extend(self.ens_line("pruv_r.len() == 0", "len(result) == 0"));
                body.push("pruv_r".to_string());
                Ok(self.fn_text(name, "", Some(STRING), &body))
            }
            "string_push_str" => {
                let mut body =
                    self.req_line("(s.len() as u64) + (text.len() as u64) <= (1u64 << 40)", "len(s) + len(text) <= 2^40");
                body.extend(self.snap(STRING, "s"));
                body.push("s.push_str(text);".to_string());
                body.extend(self.ens_line("s.len() == pruv_snap.len() + text.len()", "len(result) == len(s) + len(text)"));
                if self.ens {
                    body.push("pruv_g6_charge(&mut pruv_budget, pruv_snap.len());".to_string());
                }
                body.extend(self.ens_line(
                    "s.as_bytes()[..pruv_snap.len()] == pruv_snap.as_bytes()[..]",
                    "result[..len(s)] == s",
                ));
                if self.ens {
                    body.push("pruv_g6_charge(&mut pruv_budget, text.len());".to_string());
                }
                body.extend(self.ens_line("s.as_bytes()[pruv_snap.len()..] == text.as_bytes()[..]", "result[len(s)..] == text"));
                body.push("s".to_string());
                Ok(self.fn_text(name, &format!("mut s: {}, text: &str", STRING), Some(STRING), &body))
            }
            "string_byte" => {
                let mut body = self.req_line("i >= 0 && (i as u64) < (s.len() as u64)", "0 <= i && i < len(s)");
                body.push(
                    "let pruv_k: usize = if i >= 0 && (i as u64) < (s.len() as u64) { i as usize } else { pruv_g6_repr(\"index\") };"
                        .to_string(),
                );
                body.push("let pruv_r: i64 = s.as_bytes()[pruv_k] as i64;".to_string());
                if self.ens {
                    body.push("pruv_g6_charge(&mut pruv_budget, 1);".to_string()); // one visited element (G6_SPEC 12.3)
                }
                body.extend(self.ens_line(
                    "s.as_bytes().get(pruv_k).map(|pruv_b| *pruv_b as i64) == Some(pruv_r)",
                    "result == s[i]",
                ));
                body.push("pruv_r".to_string());
                Ok(self.fn_text(name, &format!("s: &{}, i: i64", STRING), Some("i64"), &body))
            }
            "string_to_str" => {
                let mut body: Vec<String> = Vec::new();
                if self.ens {
                    body.push("pruv_g6_charge(&mut pruv_budget, s.len());".to_string());
                }
                body.push(format!("let pruv_r: {} = s.clone();", STRING));
                body.extend(self.ens_line("pruv_r.as_bytes() == s.as_bytes()", "bytes of result equal bytes of s"));
                body.push("pruv_r".to_string());
                Ok(self.fn_text(name, &format!("s: &{}", STRING), Some(STRING), &body))
            }
            other => Err(format!("codegen: unknown catalog operation {}", other)),
        }
    }

    // ------------------------------------------------------------------ contract-only scan (requires)
    pub fn map_updated_helper(&mut self, kt: &GType, vt: &GType, src: &[GType]) -> R<String> {
        let mut name = String::from("pruv_g6_map_updated");
        for t in src {
            name.push_str("__");
            name.push_str(&encode(&safe_type_cow(t))?); // G4: nominal identities use their [0-9A-Za-z_] encoding
        }
        if self.has_item(&name) {
            return Ok(name);
        }
        self.op = "map_updated".to_string();
        let m = rty_g(&GType::new("hashmap", vec![kt.clone(), vt.clone()]), false);
        let k = rty_g(kt, false);
        let keyconv = if *kt == GType::i64() { "i64::try_from(pruv_kk).ok()" } else { "Some(pruv_kk)" };
        let l: Vec<String> = vec![
            ALLOW_G6.to_string(),
            format!(
                "fn {}(pruv_after: &{}, pruv_before: &{}, pruv_kk: {}, pruv_vv: {}, pruv_budget: &mut i64) -> bool {{",
                name,
                m,
                m,
                try_cty_g(kt)?,
                try_cty_g(vt)?
            ),
            format!("    let pruv_nk: {} = match {} {{ Some(pruv_x) => pruv_x, None => return false }};", k, keyconv),
            "    let pruv_was: bool = pruv_before.contains_key(&pruv_nk);".to_string(),
            "    if pruv_after.len() != pruv_before.len() + (if pruv_was { 0 } else { 1 }) { return false; }".to_string(),
            format!(
                "    match pruv_after.get(&pruv_nk) {{ Some(pruv_a) => {{ if !({} == pruv_vv) {{ return false; }} }} None => {{ return false; }} }}",
                try_conv_g(vt, "(*pruv_a)")?
            ),
            "    for (pruv_bk, pruv_bv) in pruv_before.iter() {".to_string(),
            "        *pruv_budget -= 1; if *pruv_budget < 0 { pruv_ud(\"contract iteration budget exceeded\"); }".to_string(),
            "        if *pruv_bk != pruv_nk {".to_string(),
            format!(
                "            match pruv_after.get(pruv_bk) {{ Some(pruv_av) => {{ if !({} == {}) {{ return false; }} }} None => {{ return false; }} }}",
                try_conv_g(vt, "(*pruv_av)")?,
                try_conv_g(vt, "(*pruv_bv)")?
            ),
            "        }".to_string(),
            "    }".to_string(),
            "    true".to_string(),
            "}".to_string(),
        ];
        self.items.push((name.clone(), format!("{}\n", l.join("\n"))));
        self.catalog.push(("map_updated".to_string(), src.iter().map(format_type).collect()));
        Ok(name)
    }
}

// ---------------------------------------------------------------------- manifest JSON
// Python json.dumps(doc, sort_keys=True, indent=2, ensure_ascii=False)

enum J {
    Str(String),
    I(i64),
    B(bool),
    A(Vec<J>),
    O(Vec<(String, J)>),
}

impl J {
    fn s(x: &str) -> J {
        J::Str(x.to_string())
    }
}

fn json_str(out: &mut String, s: &str) {
    out.push('"');
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{8}' => out.push_str("\\b"),
            '\u{c}' => out.push_str("\\f"),
            c if (c as u32) < 0x20 => out.push_str(&format!("\\u{:04x}", c as u32)),
            c => out.push(c),
        }
    }
    out.push('"');
}

fn dump_json(j: &J, level: usize, out: &mut String) {
    match j {
        J::Str(s) => json_str(out, s),
        J::I(n) => out.push_str(&n.to_string()),
        J::B(b) => out.push_str(if *b { "true" } else { "false" }),
        J::A(xs) => {
            if xs.is_empty() {
                out.push_str("[]");
                return;
            }
            out.push_str("[\n");
            for (i, x) in xs.iter().enumerate() {
                if i > 0 {
                    out.push_str(",\n");
                }
                out.push_str(&"  ".repeat(level + 1));
                dump_json(x, level + 1, out);
            }
            out.push('\n');
            out.push_str(&"  ".repeat(level));
            out.push(']');
        }
        J::O(es) => {
            if es.is_empty() {
                out.push_str("{}");
                return;
            }
            let mut sorted: Vec<&(String, J)> = es.iter().collect();
            sorted.sort_by(|a, b| a.0.cmp(&b.0));
            out.push_str("{\n");
            for (i, (k, v)) in sorted.into_iter().map(|e| (&e.0, &e.1)).enumerate() {
                if i > 0 {
                    out.push_str(",\n");
                }
                out.push_str(&"  ".repeat(level + 1));
                json_str(out, k);
                out.push_str(": ");
                dump_json(v, level + 1, out);
            }
            out.push('\n');
            out.push_str(&"  ".repeat(level));
            out.push('}');
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn json_layout() {
        let doc = J::O(vec![
            ("b".to_string(), J::A(vec![])),
            ("a".to_string(), J::A(vec![J::s("x\"é"), J::B(true), J::I(3)])),
        ]);
        let mut out = String::new();
        dump_json(&doc, 0, &mut out);
        assert_eq!(out, "{\n  \"a\": [\n    \"x\\\"é\",\n    true,\n    3\n  ],\n  \"b\": []\n}");
    }
}
