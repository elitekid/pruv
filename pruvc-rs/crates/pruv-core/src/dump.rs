//! Serializes the AST to Json in the adapter schema pruv-ast-v1.
//! Integers, line and col are decimal strings, bool is a JSON bool, None is null, Type is its name string.

use crate::ast::*;
use crate::diagnostic::plain_line;
use crate::gtype::{format_type, is_g3_key, GType};
use crate::modules::{load_program, G4, LoadError};
use crate::parser::parse_source;
use crate::pyjson::{dumps_sorted, Json};

fn js(s: &str) -> Json {
    Json::Str(s.to_string())
}

/// A type string of the AST: a legacy name is printed as it always was; a structured (G3) type with the shared
/// source formatting (`Pair<i64, bool>`, `[T]`, `Option<bool>`), like the Python adapter.
fn tys(s: &str) -> Json {
    if is_g3_key(s) {
        js(&format_type(&GType::from_key(s)))
    } else {
        js(s)
    }
}

/// A structured type of the AST (type argument, recorded instantiation, enum_ty): spelled exactly like `tys` spells its key.
fn gty(g: &GType) -> Json {
    if g.owner.is_some() || !g.args.is_empty() {
        js(&format_type(g))
    } else {
        js(&g.name)
    }
}

fn ty(t: &Ty) -> Json {
    match t {
        Some(s) => tys(s),
        None => Json::Null,
    }
}

type Fields = Vec<(&'static str, Json)>;

/// The declared type parameters of a fn/struct/enum, only when it is generic.
fn tparams_extra(f: &mut Fields, tps: &[TParam]) {
    if tps.is_empty() {
        return;
    }
    let items: Vec<Json> = tps
        .iter()
        .map(|t| {
            node(
                "TypeParam",
                Some((t.line, t.col)),
                vec![
                    ("name", js(&t.name)),
                    ("bound", match &t.bound {
                        Some(b) => js(b),
                        None => Json::Null,
                    }),
                ],
            )
        })
        .collect();
    f.push(("tparams", Json::Arr(items)));
}

/// The explicit type arguments of a call/literal/constructor and, once checked, the instantiation the checker recorded.
fn targs_extra(f: &mut Fields, targs: &Option<Vec<GType>>, inst: &Option<Inst>) {
    let targs = match targs {
        Some(k) => k,
        None => return,
    };
    f.push(("targs", Json::Arr(targs.iter().map(gty).collect())));
    if let Some(inst) = inst {
        let subst: Vec<Json> = inst
            .subst
            .iter()
            .map(|(owner, index, t)| {
                Json::Obj(vec![
                    ("index".to_string(), Json::Str(index.to_string())),
                    ("owner".to_string(), js(owner)),
                    ("type".to_string(), gty(t)),
                ])
            })
            .collect();
        f.push((
            "inst",
            Json::Obj(vec![
                ("args".to_string(), Json::Arr(inst.args.iter().map(gty).collect())),
                ("decl".to_string(), js(&inst.decl)),
                ("subst".to_string(), Json::Arr(subst)),
            ]),
        ));
    }
}

/// IsVariant / VariantField: the complete instantiated enum type of the scrutinee, only when it has type arguments.
fn enum_ty_extra(f: &mut Fields, enum_ty: &Option<GType>) {
    if let Some(t) = enum_ty {
        if !t.args.is_empty() {
            f.push(("enum_ty", gty(t)));
        }
    }
}

fn strs(v: &[String]) -> Json {
    Json::Arr(v.iter().map(|s| js(s)).collect())
}

fn list<T>(v: &[T], f: fn(&T) -> Json) -> Json {
    Json::Arr(v.iter().map(f).collect())
}

/// One node: kind, (line, col), fields.
fn node(kind: &str, lc: Option<(i64, i64)>, fields: Vec<(&str, Json)>) -> Json {
    let mut kv: Vec<(String, Json)> = vec![("kind".to_string(), js(kind))];
    if let Some((l, c)) = lc {
        kv.push(("line".to_string(), Json::Str(plain_line(l).to_string()))); // G4: no file tag in the dump
        kv.push(("col".to_string(), Json::Str(c.to_string())));
    }
    // Like a Python dict, the same key is overwritten: in the adapter's ser(), Quant.kind ("forall" etc.)
    // overwriting the node name "Quant" is baked into the reference snapshot (pruv-ast-v1).
    for (k, v) in fields {
        match kv.iter_mut().find(|(kk, _)| kk == k) {
            Some(slot) => slot.1 = v,
            None => kv.push((k.to_string(), v)),
        }
    }
    Json::Obj(kv)
}

fn bx(e: &Expr) -> Json {
    expr(e)
}

pub fn expr(e: &Expr) -> Json {
    match e {
        Expr::Spent(x) => node("Spent", Some((x.line, x.col)), vec![("ty", ty(&x.ty))]),
        Expr::Move(x) => node("Move", Some((x.line, x.col)), vec![("name", js(&x.name)), ("ty", ty(&x.ty))]),
        Expr::IntLit(x) => node("IntLit", Some((x.line, x.col)), vec![("value", js(&x.value)), ("ty", ty(&x.ty))]),
        Expr::BoolLit(x) => node("BoolLit", Some((x.line, x.col)), vec![("value", Json::Bool(x.value)), ("ty", ty(&x.ty))]),
        Expr::StrLit(x) => {
            let hex: String = x.value.iter().map(|b| format!("{:02x}", b)).collect();
            node("StrLit", Some((x.line, x.col)), vec![("value", Json::Str(hex)), ("ty", ty(&x.ty))])
        }
        Expr::Var(x) => node("Var", Some((x.line, x.col)), vec![("name", js(&x.name)), ("ty", ty(&x.ty))]),
        Expr::Unary(x) => node(
            "Unary",
            Some((x.line, x.col)),
            vec![("op", js(&x.op)), ("operand", bx(&x.operand)), ("ty", ty(&x.ty))],
        ),
        Expr::Binary(x) => node(
            "Binary",
            Some((x.line, x.col)),
            vec![("op", js(&x.op)), ("left", bx(&x.left)), ("right", bx(&x.right)), ("ty", ty(&x.ty))],
        ),
        Expr::Call(x) => {
            let mut f: Fields = vec![("name", js(&x.name)), ("args", list(&x.args, expr)), ("ty", ty(&x.ty))];
            targs_extra(&mut f, &x.targs, &x.inst);
            if let Some((pname, index)) = &x.old {
                // G5 A0, written only when present (check dump): the resolved old(a) operand and its parameter position
                f.push((
                    "old",
                    Json::Obj(vec![
                        ("param".to_string(), js(pname)),
                        ("index".to_string(), Json::Str(index.to_string())),
                    ]),
                ));
            }
            node("Call", Some((x.line, x.col)), f)
        }
        Expr::InoutArg(x) => node("InoutArg", Some((x.line, x.col)), vec![("expr", bx(&x.expr)), ("ty", ty(&x.ty))]),
        Expr::Index(x) => node(
            "Index",
            Some((x.line, x.col)),
            vec![("array", bx(&x.array)), ("index", bx(&x.index)), ("ty", ty(&x.ty))],
        ),
        Expr::Ctor(x) => {
            let mut f: Fields = vec![
                ("name", js(&x.name)),
                ("arg", match &x.arg {
                    Some(a) => bx(a),
                    None => Json::Null,
                }),
                ("ty", ty(&x.ty)),
            ];
            targs_extra(&mut f, &x.targs, &x.inst);
            node("Ctor", Some((x.line, x.col)), f)
        }
        Expr::Quant(x) => node(
            "Quant",
            Some((x.line, x.col)),
            vec![
                ("kind", js(&x.kind)),
                ("var", js(&x.var)),
                ("lo", bx(&x.lo)),
                ("hi", bx(&x.hi)),
                ("body", bx(&x.body)),
                ("ty", ty(&x.ty)),
            ],
        ),
        Expr::StructLit(x) => {
            let mut f: Fields =
                vec![("name", js(&x.name)), ("fields", list(&x.fields, field_init)), ("ty", ty(&x.ty))];
            targs_extra(&mut f, &x.targs, &x.inst);
            node("StructLit", Some((x.line, x.col)), f)
        }
        Expr::EnumCtor(x) => {
            let mut f: Fields = vec![
                ("enum_name", js(&x.enum_name)),
                ("variant", js(&x.variant)),
                ("args", list(&x.args, expr)),
                ("ty", ty(&x.ty)),
            ];
            targs_extra(&mut f, &x.targs, &x.inst);
            node("EnumCtor", Some((x.line, x.col)), f)
        }
        Expr::FieldAccess(x) => node(
            "FieldAccess",
            Some((x.line, x.col)),
            vec![("base", bx(&x.base)), ("field", js(&x.field)), ("ty", ty(&x.ty))],
        ),
        Expr::IsVariant(x) => {
            let mut f: Fields = vec![
                ("value", bx(&x.value)),
                ("enum_name", js(&x.enum_name)),
                ("variant", js(&x.variant)),
                ("ty", ty(&x.ty)),
            ];
            enum_ty_extra(&mut f, &x.enum_ty);
            node("IsVariant", Some((x.line, x.col)), f)
        }
        Expr::VariantField(x) => {
            let mut f: Fields = vec![
                ("value", bx(&x.value)),
                ("enum_name", js(&x.enum_name)),
                ("variant", js(&x.variant)),
                ("field", js(&x.field)),
                ("ty", ty(&x.ty)),
            ];
            enum_ty_extra(&mut f, &x.enum_ty);
            node("VariantField", Some((x.line, x.col)), f)
        }
    }
}

fn field_init(f: &FieldInit) -> Json {
    node("FieldInit", Some((f.line, f.col)), vec![("name", js(&f.name)), ("value", expr(&f.value))])
}

fn field_decl(f: &FieldDecl) -> Json {
    node("FieldDecl", Some((f.line, f.col)), vec![("name", js(&f.name)), ("type", tys(&f.ty))])
}

fn variant_decl(v: &VariantDecl) -> Json {
    node("VariantDecl", Some((v.line, v.col)), vec![("name", js(&v.name)), ("fields", list(&v.fields, field_decl))])
}

fn type_decl(d: &TypeDecl) -> Json {
    match d {
        TypeDecl::Struct(s) => {
            let mut f: Fields = vec![("name", js(&s.name)), ("fields", list(&s.fields, field_decl))];
            tparams_extra(&mut f, &s.tparams);
            node("StructDecl", Some((s.line, s.col)), f)
        }
        TypeDecl::Enum(e) => {
            let mut f: Fields = vec![("name", js(&e.name)), ("variants", list(&e.variants, variant_decl))];
            tparams_extra(&mut f, &e.tparams);
            node("EnumDecl", Some((e.line, e.col)), f)
        }
    }
}

fn match_arm(a: &MatchArm) -> Json {
    node(
        "MatchArm",
        Some((a.line, a.col)),
        vec![
            ("enum_name", match &a.enum_name {
                Some(s) => js(s),
                None => Json::Null,
            }),
            ("ctor", js(&a.ctor)),
            ("binders", strs(&a.binders)),
            ("body", list(&a.body, stmt)),
        ],
    )
}

pub fn stmt(s: &Stmt) -> Json {
    match s {
        Stmt::Let(x) => {
            let mut f = vec![("name", js(&x.name)), ("mutable", Json::Bool(x.mutable)), ("type", tys(&x.ty)), ("value", expr(&x.value))];
            if let Some(r) = &x.refine {
                f.push(("refine", refinement(r)));
            }
            node("Let", Some((x.line, x.col)), f)
        }
        Stmt::Assign(x) => node("Assign", Some((x.line, x.col)), vec![("name", js(&x.name)), ("value", expr(&x.value))]),
        Stmt::IndexAssign(x) => {
            let mut f = vec![("name", js(&x.name)), ("index", expr(&x.index)), ("value", expr(&x.value))];
            if let Some((lo, hi, what)) = &x.elem_refine {
                f.push(("elem_refine", Json::Arr(vec![js(lo), js(hi), js(what)])));
            }
            node("IndexAssign", Some((x.line, x.col)), f)
        }
        Stmt::If(x) => if_node(x),
        Stmt::While(x) => node(
            "While",
            Some((x.line, x.col)),
            vec![
                ("cond", expr(&x.cond)),
                ("invariants", list(&x.invariants, expr)),
                ("decreases", expr(&x.decreases)),
                ("body", list(&x.body, stmt)),
            ],
        ),
        Stmt::Return(x) => node(
            "Return",
            Some((x.line, x.col)),
            vec![("value", match &x.value {
                Some(v) => expr(v),
                None => Json::Null,
            })],
        ),
        Stmt::Assert(x) => {
            let mut f = vec![("cond", expr(&x.cond))];
            if let Some(c) = &x.origin_code {
                f.push(("origin_code", js(c)));
            }
            if let Some(w) = &x.origin_what {
                f.push(("origin_what", js(w)));
            }
            node("Assert", Some((x.line, x.col)), f)
        }
        Stmt::Par(x) => node("Par", Some((x.line, x.col)), vec![("calls", list(&x.calls, expr))]),
        Stmt::ExprStmt(x) => node("ExprStmt", Some((x.line, x.col)), vec![("expr", expr(&x.expr))]),
        Stmt::FieldAssign(x) => node(
            "FieldAssign",
            Some((x.line, x.col)),
            vec![("name", js(&x.name)), ("fields", strs(&x.fields)), ("value", expr(&x.value))],
        ),
        Stmt::Match(x) => node(
            "Match",
            Some((x.line, x.col)),
            vec![("scrutinee", expr(&x.scrutinee)), ("arms", list(&x.arms, match_arm))],
        ),
    }
}

fn if_node(x: &If) -> Json {
    node(
        "If",
        Some((x.line, x.col)),
        vec![("cond", expr(&x.cond)), ("then", list(&x.then, stmt)), ("els", list(&x.els, stmt))],
    )
}

/// Integer string or null (null when the value is None).
fn opt_num(v: &Option<String>) -> Json {
    match v {
        Some(s) => js(s),
        None => Json::Null,
    }
}

/// Refinement node. Field shape ("scalar"|"array"). The node name kind is "Refinement".
fn refinement(r: &Refinement) -> Json {
    node(
        "Refinement",
        Some((r.line, r.col)),
        vec![
            ("shape", js(&r.shape)),
            ("base", js(&r.base)),
            ("lo", opt_num(&r.lo)),
            ("hi", opt_num(&r.hi)),
            ("maxlen", opt_num(&r.maxlen)),
        ],
    )
}

fn param(p: &Param) -> Json {
    let mut f = vec![("name", js(&p.name)), ("type", tys(&p.ty))];
    if let Some(r) = &p.refine {
        f.push(("refine", refinement(r)));
    }
    if p.take {
        f.push(("take", Json::Bool(true))); // G6 A0, written only when present
    }
    if p.mode_pos.is_some() {
        f.push(("mode", js("inout"))); // G5 A0, written only when present
    }
    node("Param", None, f)
}

fn function(f: &Function) -> Json {
    let mut fields = vec![
        ("name", js(&f.name)),
        ("params", list(&f.params, param)),
        ("ret", tys(&f.ret)),
        ("effects", strs(&f.effects)),
        ("requires", list(&f.requires, expr)),
        ("ensures", list(&f.ensures, expr)),
        ("body", list(&f.body, stmt)),
    ];
    if let Some(r) = &f.ret_refine {
        fields.push(("ret_refine", refinement(r)));
    }
    tparams_extra(&mut fields, &f.tparams);
    if let Some(fo) = &f.foreign {
        // G6 A0, written only when present: {"path", "line", "col"} of the path string token (line/col are decimal strings)
        fields.push((
            "foreign",
            Json::Obj(vec![
                ("path".to_string(), js(&fo.path)),
                ("line".to_string(), Json::Str(plain_line(fo.line).to_string())),
                ("col".to_string(), Json::Str(fo.col.to_string())),
            ]),
        ));
    }
    if let Some(d) = &f.cost { fields.push(("cost", expr(d))); }
    if let Some(d) = &f.decreases {
        fields.push(("decreases", expr(d))); // G9 A0, written only when present
    }
    node("Function", Some((f.line, f.col)), fields)
}

pub fn program(p: &Program) -> Json {
    node(
        "Program",
        None,
        vec![("functions", list(&p.functions, function)), ("types", list(&p.types, type_decl))],
    )
}

fn push_kv(j: &mut Json, k: &str, v: Json) {
    if let Json::Obj(kv) = j {
        kv.push((k.to_string(), v));
    }
}

/// G4 A0, explicit mode only (diff_py_adapter `_g4_extras`): module, file, pub (only when public), src_name (only when the
/// resolved name differs), host_entry (functions, only when true).
fn g4_item_extras(j: &mut Json, g4: &G4, m: &crate::modules::ItemMeta, name: &str, is_fn: bool) {
    let module = &g4.modules[m.module];
    push_kv(j, "module", Json::Arr(module.path.iter().map(|s| js(s)).collect()));
    push_kv(j, "file", js(&module.file));
    if m.is_pub {
        push_kv(j, "pub", Json::Bool(true));
    }
    if m.src_name != name {
        push_kv(j, "src_name", js(&m.src_name));
    }
    if is_fn && m.host_entry {
        push_kv(j, "host_entry", Json::Bool(true));
    }
}

/// `program` plus the explicit-mode data: per-item extras and the Program "modules" list (root-first depth-first order).
pub fn program_g4(p: &Program, g4: Option<&G4>) -> Json {
    let g4 = match g4 {
        None => return program(p),
        Some(g) => g,
    };
    let mut fns: Vec<Json> = Vec::new();
    for (i, f) in p.functions.iter().enumerate() {
        let mut j = function(f);
        g4_item_extras(&mut j, g4, &g4.fn_meta[i], &f.name, true);
        fns.push(j);
    }
    let mut tys: Vec<Json> = Vec::new();
    for (i, d) in p.types.iter().enumerate() {
        let mut j = type_decl(d);
        g4_item_extras(&mut j, g4, &g4.ty_meta[i], d.name(), false);
        tys.push(j);
    }
    let mut top = node("Program", None, vec![("functions", Json::Arr(fns)), ("types", Json::Arr(tys))]);
    let mods: Vec<Json> = g4
        .modules
        .iter()
        .map(|m| {
            let decls: Vec<Json> = m
                .mods
                .iter()
                .map(|md| node("ModDecl", Some((md.line, md.col)), vec![("name", js(&md.name))]))
                .collect();
            Json::Obj(vec![
                ("path".to_string(), Json::Arr(m.path.iter().map(|s| js(s)).collect())),
                ("file".to_string(), js(&m.file)),
                ("mods".to_string(), Json::Arr(decls)),
            ])
        })
        .collect();
    push_kv(&mut top, "modules", Json::Arr(mods));
    top
}

fn adapter_error(kind: &str) -> String {
    dumps_sorted(&Json::Obj(vec![("adapter_error".to_string(), js(kind))]))
}

/// One root file (through the module loader: its declared child files are read too) -> one parse output line.
pub fn parse_dump_path(path: &std::path::Path) -> String {
    let top = match load_program(path) {
        Err(LoadError::Io(_)) => return adapter_error("io"),
        Err(LoadError::Decode(_)) => return adapter_error("decode"),
        Err(LoadError::Lang(e)) => Json::Obj(vec![
            ("schema".to_string(), js(crate::SCHEMA_AST)),
            ("error".to_string(), e.to_json_value()),
        ]),
        Ok(l) => Json::Obj(vec![
            ("schema".to_string(), js(crate::SCHEMA_AST)),
            ("program".to_string(), program_g4(&l.prog, l.g4.as_ref())),
        ]),
    };
    dumps_sorted(&top)
}

/// One root file -> one parse+check output line (G4: explicit mode resolves names first and adds the top-level "g4").
pub fn check_dump_path(path: &std::path::Path, externs: &[String]) -> String {
    let err_top = |e: crate::diagnostic::PruvError| {
        Json::Obj(vec![
            ("schema".to_string(), js(crate::SCHEMA_AST)),
            ("error".to_string(), e.to_json_value()),
        ])
    };
    let top = match load_program(path) {
        Err(LoadError::Io(_)) => return adapter_error("io"),
        Err(LoadError::Decode(_)) => return adapter_error("decode"),
        Err(LoadError::Lang(e)) => err_top(e),
        Ok(mut l) => {
            let res = match l.g4.as_mut() {
                Some(g4) => crate::check::check_explicit(&mut l.prog, g4, externs),
                None => crate::check::check_with_externs(&mut l.prog, externs),
            };
            match res {
                Err(e) => err_top(e),
                Ok(tt) => {
                    let mut kv = vec![
                        ("schema".to_string(), js(crate::SCHEMA_AST)),
                        ("program".to_string(), program_g4(&l.prog, l.g4.as_ref())),
                        ("type_table".to_string(), type_table_json(&tt)),
                    ];
                    if let Some(g4) = &l.g4 {
                        kv.push((
                            "g4".to_string(),
                            Json::Obj(vec![
                                ("entries".to_string(), strs(&g4.entries)),
                                (
                                    "main".to_string(),
                                    match &g4.main {
                                        Some(m) => js(m),
                                        None => Json::Null,
                                    },
                                ),
                            ]),
                        ));
                    }
                    Json::Obj(kv)
                }
            }
        }
    };
    dumps_sorted(&top)
}

/// One file's bytes -> one output line (without the newline).
pub fn parse_dump_line(src_bytes: &[u8]) -> String {
    let src = match std::str::from_utf8(src_bytes) {
        Ok(s) => s,
        Err(_) => return dumps_sorted(&Json::Obj(vec![("adapter_error".to_string(), js("decode"))])),
    };
    let top = match parse_source(src) {
        Ok(p) => Json::Obj(vec![
            ("schema".to_string(), js(crate::SCHEMA_AST)),
            ("program".to_string(), program(&p)),
        ]),
        Err(e) => Json::Obj(vec![
            ("schema".to_string(), js(crate::SCHEMA_AST)),
            ("error".to_string(), e.to_json_value()),
        ]),
    };
    dumps_sorted(&top)
}

/// Type table ->{"order": [...], "entries": [{"deps","kind","name"}...]} (Python type_table_json).
fn type_table_json(tt: &crate::typeinfo::TypeTable) -> Json {
    let mut entries = Vec::new();
    let mut order = Vec::new();
    for d in tt.ordered() {
        let kind = match d {
            TypeDecl::Struct(_) => "struct",
            TypeDecl::Enum(_) => "enum",
        };
        order.push(js(d.name()));
        entries.push(Json::Obj(vec![
            ("name".to_string(), js(d.name())),
            ("kind".to_string(), js(kind)),
            ("deps".to_string(), strs(&tt.deps(d))),
        ]));
    }
    let mut top = vec![("order".to_string(), Json::Arr(order)), ("entries".to_string(), Json::Arr(entries))];
    if let Some(g) = &tt.g9 {
        // G9 A0, only when the program has a G9 feature
        let lists = |v: &Vec<Vec<String>>| Json::Arr(v.iter().map(|x| strs(x)).collect());
        top.push((
            "g9".to_string(),
            Json::Obj(vec![
                ("type_sccs".to_string(), lists(&g.type_sccs)),
                ("boxed".to_string(), strs(&g.boxed)),
                ("extended".to_string(), strs(&g.extended)),
                ("fn_sccs".to_string(), lists(&g.fn_sccs)),
            ]),
        ));
    }
    Json::Obj(top)
}

/// One file's bytes -> one parse+check result line (without the newline). On success, the program with ty filled in and the type_table.
pub fn check_dump_line(src_bytes: &[u8]) -> String {
    check_dump_line_with(src_bytes, &[])
}

/// `check_dump_line` with the crate names of --rust-extern (G6: the adapter's `check --rust-extern NAME=PATH`, only NAME is used).
pub fn check_dump_line_with(src_bytes: &[u8], externs: &[String]) -> String {
    let src = match std::str::from_utf8(src_bytes) {
        Ok(s) => s,
        Err(_) => return dumps_sorted(&Json::Obj(vec![("adapter_error".to_string(), js("decode"))])),
    };
    let err_top = |e: crate::diagnostic::PruvError| {
        Json::Obj(vec![
            ("schema".to_string(), js(crate::SCHEMA_AST)),
            ("error".to_string(), e.to_json_value()),
        ])
    };
    let top = match parse_source(src) {
        Err(e) => err_top(e),
        Ok(mut p) => match crate::check::check_with_externs(&mut p, externs) {
            Err(e) => err_top(e),
            Ok(tt) => Json::Obj(vec![
                ("schema".to_string(), js(crate::SCHEMA_AST)),
                ("program".to_string(), program(&p)),
                ("type_table".to_string(), type_table_json(&tt)),
            ]),
        },
    };
    dumps_sorted(&top)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn check_line_decode_error() {
        assert_eq!(check_dump_line(&[0xff]), r#"{"adapter_error": "decode"}"#);
    }

    #[test]
    fn error_line_is_number() {
        let s = parse_dump_line(b"fn f() -> i64 {\n return 1 }");
        assert_eq!(
            s,
            r#"{"error": {"code": "syntax", "col": 11, "fix": "insert ';'", "line": 2, "message": "expected ';' but found '}'", "stage": "parse"}, "schema": "pruv-ast-v1"}"#
        );
    }

    #[test]
    fn decode_error() {
        assert_eq!(parse_dump_line(&[0xff, 0xfe]), r#"{"adapter_error": "decode"}"#);
    }

    #[test]
    fn empty_program() {
        assert_eq!(
            parse_dump_line(b""),
            r#"{"program": {"functions": [], "kind": "Program", "types": []}, "schema": "pruv-ast-v1"}"#
        );
    }
}
