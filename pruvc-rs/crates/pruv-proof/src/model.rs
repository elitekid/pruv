//! verify.py lines 10-70: the `Opt`/`Res` Datatypes (module level) and the per-program `Model` (user struct/enum, G1).
//!
//! Naming rules (must match verify.py character for character):
//! - `Opt`: `some(sval: Int)`, `none`; `Res`: `ok(oval: Int)`, `err(eval: Int)`. Both are created together with a single `CreateDatatypes`.
//! - The i-th user type (in TypeTable dependency order) has tag = `m{SEQ}t{i}!`.
//!   struct: datatype name = constructor name = `tag+Name`, accessor = `tag+Name+"."+field`.
//!   enum: datatype = `tag+Name`, variant constructor = `tag+Name+"::"+Variant`, accessor = constructor name + `"."+field`.
//! - SEQ (`_MODEL_SEQ`) increases by 1 each time a `Model` is created in the process (here, the thread). Python creates
//!   one Model per program, so `verify_program` calls `next_seq()` only once and, even though each function has a different context,
//!   calls `Model::with_seq` with the same number.

use std::cell::Cell;
use std::collections::HashMap;

use pruv_core::ast as past;

use crate::sys::{Ast, DtCtor, DtCtorSpec, DtSort, DtSpec, FuncDecl, Sort, Z3};

thread_local! {
    static MODEL_SEQ: Cell<u32> = const { Cell::new(0) };
}

/// For restarting from 0 per sample, like a fresh Python process (the spike binary calls this before each sample).
pub fn reset_model_seq() {
    MODEL_SEQ.with(|c| c.set(0));
}

/// The value after `_MODEL_SEQ[0] += 1`.
pub fn next_seq() -> u32 {
    MODEL_SEQ.with(|c| {
        c.set(c.get() + 1);
        c.get()
    })
}

/// Array element storage type (G2). The internal name mapping lives in one place, pruv_core::typeinfo.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum Elem {
    I64,
    U8,
    Bool,
}

impl Elem {
    /// Element type name ("i64"/"u8"/"bool").
    pub fn name(self) -> &'static str {
        match self {
            Elem::I64 => "i64",
            Elem::U8 => "u8",
            Elem::Bool => "bool",
        }
    }
    pub fn from_name(n: &str) -> Option<Elem> {
        match n {
            "i64" => Some(Elem::I64),
            "u8" => Some(Elem::U8),
            "bool" => Some(Elem::Bool),
            _ => None,
        }
    }
}

/// Pruv type (vast.Type). A user type is a single name.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Ty {
    I64,
    Bool,
    Unit,
    Array(Elem),
    Str,
    Opt,
    Res,
    User(String),
}

impl Ty {
    /// The parser/checker's type name string → `Ty`.
    pub fn from_name(n: &str) -> Ty {
        match n {
            "i64" => Ty::I64,
            "bool" => Ty::Bool,
            "unit" => Ty::Unit,
            "str" => Ty::Str,
            "option" => Ty::Opt,
            "result" => Ty::Res,
            other => {
                if let Some(e) = pruv_core::typeinfo::array_elem_name(other).and_then(Elem::from_name) {
                    Ty::Array(e)
                } else {
                    Ty::User(other.to_string())
                }
            }
        }
    }
    /// vast `Type.name`.
    pub fn name(&self) -> &str {
        match self {
            Ty::I64 => "i64",
            Ty::Bool => "bool",
            Ty::Unit => "unit",
            Ty::Array(e) => pruv_core::typeinfo::array_of_elem_name(e.name()).expect("every Elem name has an array type name"),
            Ty::Str => "str",
            Ty::Opt => "option",
            Ty::Res => "result",
            Ty::User(n) => n,
        }
    }
    pub fn is_array(&self) -> bool {
        matches!(self, Ty::Array(_))
    }
    pub fn array_elem(&self) -> Option<Elem> {
        match self {
            Ty::Array(e) => Some(*e),
            _ => None,
        }
    }
    pub fn array_of(e: Elem) -> Ty {
        Ty::Array(e)
    }
}

#[derive(Clone, Debug)]
pub struct FieldDecl {
    pub name: String,
    pub ty: Ty,
}
#[derive(Clone, Debug)]
pub struct VariantDecl {
    pub name: String,
    pub fields: Vec<FieldDecl>,
}
#[derive(Clone, Debug)]
pub enum TypeKind {
    Struct(Vec<FieldDecl>),
    Enum(Vec<VariantDecl>),
}
#[derive(Clone, Debug)]
pub struct TypeDecl {
    pub name: String,
    pub kind: TypeKind,
}

fn fields_of(fs: &[(&str, Ty)]) -> Vec<FieldDecl> {
    fs.iter().map(|(n, t)| FieldDecl { name: (*n).to_string(), ty: t.clone() }).collect()
}

fn conv_fields(fs: &[past::FieldDecl]) -> Vec<FieldDecl> {
    fs.iter().map(|f| FieldDecl { name: f.name.clone(), ty: Ty::from_name(&f.ty) }).collect()
}

/// pruv-core's declarations → this crate's declarations (declaration order preserved).
pub fn decls_from_ast(types: &[past::TypeDecl]) -> Vec<TypeDecl> {
    types
        .iter()
        .map(|d| match d {
            past::TypeDecl::Struct(s) => {
                TypeDecl { name: s.name.clone(), kind: TypeKind::Struct(conv_fields(&s.fields)) }
            }
            past::TypeDecl::Enum(e) => TypeDecl {
                name: e.name.clone(),
                kind: TypeKind::Enum(
                    e.variants
                        .iter()
                        .map(|v| VariantDecl { name: v.name.clone(), fields: conv_fields(&v.fields) })
                        .collect(),
                ),
            },
        })
        .collect()
}

impl TypeDecl {
    pub fn new_struct(name: &str, fields: &[(&str, Ty)]) -> TypeDecl {
        TypeDecl { name: name.to_string(), kind: TypeKind::Struct(fields_of(fields)) }
    }
    pub fn new_enum(name: &str, variants: &[(&str, &[(&str, Ty)])]) -> TypeDecl {
        TypeDecl {
            name: name.to_string(),
            kind: TypeKind::Enum(
                variants
                    .iter()
                    .map(|(vn, fs)| VariantDecl { name: (*vn).to_string(), fields: fields_of(fs) })
                    .collect(),
            ),
        }
    }
    /// typeinfo.py `_all_fields`.
    fn all_fields(&self) -> Vec<&FieldDecl> {
        match &self.kind {
            TypeKind::Struct(fs) => fs.iter().collect(),
            TypeKind::Enum(vs) => vs.iter().flat_map(|v| v.fields.iter()).collect(),
        }
    }
}

// ---------------------------------------------------------------------------------------------
// Opt / Res (verify.py lines 10-12)
// ---------------------------------------------------------------------------------------------

pub struct Prelude {
    pub opt: DtSort,
    pub res: DtSort,
}

impl Prelude {
    pub fn new(z: &Z3) -> Prelude {
        let int = z.int_sort();
        let ctor = |name: &str, fields: Vec<(&str, Sort)>| DtCtorSpec {
            name: name.to_string(),
            fields: fields.into_iter().map(|(n, s)| (n.to_string(), s)).collect(),
        };
        let specs = vec![
            DtSpec {
                name: "Opt".to_string(),
                ctors: vec![ctor("some", vec![("sval", int.clone())]), ctor("none", vec![])],
            },
            DtSpec {
                name: "Res".to_string(),
                ctors: vec![ctor("ok", vec![("oval", int.clone())]), ctor("err", vec![("eval", int)])],
            },
        ];
        let mut v = z.create_datatypes(&specs);
        let res = v.pop().expect("Res");
        let opt = v.pop().expect("Opt");
        Prelude { opt, res }
    }

    pub fn some(&self, v: &Ast) -> Ast {
        self.opt.ctors[0].ctor.apply1(v)
    }
    pub fn none(&self) -> Ast {
        self.opt.ctors[1].ctor.apply(&[])
    }
    pub fn is_some(&self, v: &Ast) -> Ast {
        self.opt.ctors[0].rec.apply1(v)
    }
    pub fn is_none(&self, v: &Ast) -> Ast {
        self.opt.ctors[1].rec.apply1(v)
    }
    pub fn sval(&self, v: &Ast) -> Ast {
        self.opt.ctors[0].accs[0].apply1(v)
    }
    pub fn ok(&self, v: &Ast) -> Ast {
        self.res.ctors[0].ctor.apply1(v)
    }
    pub fn err(&self, v: &Ast) -> Ast {
        self.res.ctors[1].ctor.apply1(v)
    }
    pub fn is_ok(&self, v: &Ast) -> Ast {
        self.res.ctors[0].rec.apply1(v)
    }
    pub fn is_err(&self, v: &Ast) -> Ast {
        self.res.ctors[1].rec.apply1(v)
    }
    pub fn oval(&self, v: &Ast) -> Ast {
        self.res.ctors[0].accs[0].apply1(v)
    }
    pub fn eval(&self, v: &Ast) -> Ast {
        self.res.ctors[1].accs[0].apply1(v)
    }
}

// ---------------------------------------------------------------------------------------------
// Model (verify.py lines 17-62)
// ---------------------------------------------------------------------------------------------

pub struct StructFns {
    pub ctor: FuncDecl,
    pub accs: Vec<FuncDecl>,
}
pub struct VariantFns {
    pub ctor: FuncDecl,
    pub rec: FuncDecl,
    pub accs: Vec<FuncDecl>,
}

pub struct Model {
    /// TypeTable.order: dependencies first, stable in declaration order.
    pub order: Vec<TypeDecl>,
    sorts: HashMap<String, Sort>,
    structs: HashMap<String, StructFns>,
    enums: HashMap<String, Vec<(String, VariantFns)>>,
    /// `by_sort`: z3 sort name → Pruv type (Opt/Res/user).
    by_sort: HashMap<String, Ty>,
    opt_sort: Sort,
    res_sort: Sort,
    int_sort: Sort,
    bool_sort: Sort,
}

/// typeinfo.py `_deps`: field dependencies on declared user types (no duplicates, first-appearance order).
fn deps(d: &TypeDecl, uniq: &[TypeDecl]) -> Vec<usize> {
    let mut out: Vec<usize> = Vec::new();
    for f in d.all_fields() {
        if let Ty::User(n) = &f.ty {
            if let Some(i) = uniq.iter().position(|u| &u.name == n) {
                if !out.contains(&i) {
                    out.push(i);
                }
            }
        }
    }
    out
}

/// typeinfo.py `_build_order`: mark as visited first, visit dependencies first, then append itself.
fn visit(i: usize, uniq: &[TypeDecl], seen: &mut [bool], order: &mut Vec<usize>) {
    if seen[i] {
        return;
    }
    seen[i] = true;
    for d in deps(&uniq[i], uniq) {
        visit(d, uniq, seen, order);
    }
    order.push(i);
}

impl Model {
    /// `Model(prog)`: bumps the sequence number anew (for the prototype and samples).
    pub fn new(z: &Z3, pre: &Prelude, decls: &[TypeDecl]) -> Model {
        match Model::with_seq(z, pre, decls, next_seq()) {
            Ok(m) => m,
            Err(e) => panic!("Model::new: {e}"),
        }
    }

    /// `Model(prog)` with a caller-chosen sequence number. `decls` is the program declaration order (if a name repeats, only the first declaration is used).
    /// If a field type has no sort (Python `KeyError`), `Err("'name'")`.
    pub fn with_seq(z: &Z3, pre: &Prelude, decls: &[TypeDecl], seq: u32) -> Result<Model, String> {
        let mut uniq: Vec<TypeDecl> = Vec::new();
        for d in decls {
            if !uniq.iter().any(|u| u.name == d.name) {
                uniq.push(d.clone());
            }
        }
        let mut seen = vec![false; uniq.len()];
        let mut idx_order: Vec<usize> = Vec::new();
        for i in 0..uniq.len() {
            visit(i, &uniq, &mut seen, &mut idx_order);
        }
        let order: Vec<TypeDecl> = idx_order.iter().map(|&i| uniq[i].clone()).collect();

        let pre_tag = format!("m{}", seq);

        let mut by_sort: HashMap<String, Ty> = HashMap::new();
        by_sort.insert(pre.opt.sort.name(), Ty::Opt);
        by_sort.insert(pre.res.sort.name(), Ty::Res);

        let mut m = Model {
            order: Vec::new(),
            sorts: HashMap::new(),
            structs: HashMap::new(),
            enums: HashMap::new(),
            by_sort,
            opt_sort: pre.opt.sort.clone(),
            res_sort: pre.res.sort.clone(),
            int_sort: z.int_sort(),
            bool_sort: z.bool_sort(),
        };
        for (idx, d) in order.iter().enumerate() {
            let tag = format!("{}t{}!", pre_tag, idx);
            match &d.kind {
                TypeKind::Struct(fields) => {
                    let cn = format!("{}{}", tag, d.name);
                    let mut fs: Vec<(String, Sort)> = Vec::new();
                    for fd in fields {
                        fs.push((format!("{}.{}", cn, fd.name), m.try_sort_of(&fd.ty)?));
                    }
                    let spec = DtSpec { name: cn.clone(), ctors: vec![DtCtorSpec { name: cn.clone(), fields: fs }] };
                    let mut dt = z.create_datatypes(&[spec]);
                    let DtSort { sort, mut ctors } = dt.pop().ok_or("datatype")?;
                    if ctors.is_empty() {
                        return Err("datatype".to_string());
                    }
                    let DtCtor { ctor, accs, .. } = ctors.remove(0);
                    m.by_sort.insert(sort.name(), Ty::User(d.name.clone()));
                    m.structs.insert(d.name.clone(), StructFns { ctor, accs });
                    m.sorts.insert(d.name.clone(), sort);
                }
                TypeKind::Enum(variants) => {
                    let dn = format!("{}{}", tag, d.name);
                    let mut specs: Vec<DtCtorSpec> = Vec::new();
                    for v in variants {
                        let cn = format!("{}{}::{}", tag, d.name, v.name);
                        let mut fs: Vec<(String, Sort)> = Vec::new();
                        for fd in &v.fields {
                            fs.push((format!("{}.{}", cn, fd.name), m.try_sort_of(&fd.ty)?));
                        }
                        specs.push(DtCtorSpec { name: cn, fields: fs });
                    }
                    let mut dt = z.create_datatypes(&[DtSpec { name: dn, ctors: specs }]);
                    let DtSort { sort, ctors } = dt.pop().ok_or("datatype")?;
                    let fns: Vec<(String, VariantFns)> = variants
                        .iter()
                        .zip(ctors)
                        .map(|(v, c)| (v.name.clone(), VariantFns { ctor: c.ctor, rec: c.rec, accs: c.accs }))
                        .collect();
                    m.by_sort.insert(sort.name(), Ty::User(d.name.clone()));
                    m.enums.insert(d.name.clone(), fns);
                    m.sorts.insert(d.name.clone(), sort);
                }
            }
        }
        m.order = order;
        Ok(m)
    }

    /// `Model.sort_of` (Python raises `KeyError(name)` when there is no sort).
    pub fn try_sort_of(&self, ty: &Ty) -> Result<Sort, String> {
        match ty {
            Ty::I64 => Ok(self.int_sort.clone()),
            Ty::Bool => Ok(self.bool_sort.clone()),
            Ty::Opt => Ok(self.opt_sort.clone()),
            Ty::Res => Ok(self.res_sort.clone()),
            Ty::User(n) => self.sorts.get(n).cloned().ok_or_else(|| format!("'{}'", n)),
            Ty::Unit | Ty::Array(_) | Ty::Str => Err(format!("'{}'", ty.name())),
        }
    }

    /// For the prototype (panics). The new path uses `try_sort_of`.
    pub fn sort_of(&self, ty: &Ty) -> Sort {
        match self.try_sort_of(ty) {
            Ok(s) => s,
            Err(e) => panic!("sort_of: {e}"),
        }
    }

    pub fn sort(&self, name: &str) -> &Sort {
        &self.sorts[name]
    }
    pub fn sort_opt(&self, name: &str) -> Option<&Sort> {
        self.sorts.get(name)
    }
    /// `Model.is_user(ty)`: is this a type that has a user sort?
    pub fn is_user(&self, ty: &Ty) -> bool {
        matches!(ty, Ty::User(n) if self.sorts.contains_key(n))
    }
    /// `Model.type_of(v)`: finds the Pruv type from the sort name of a datatype value (None if absent).
    pub fn type_of(&self, v: &Ast) -> Option<Ty> {
        self.by_sort.get(&v.sort().name()).cloned()
    }

    pub fn decl(&self, name: &str) -> &TypeDecl {
        self.order.iter().find(|d| d.name == name).unwrap_or_else(|| panic!("unknown type {name}"))
    }
    pub fn decl_opt(&self, name: &str) -> Option<&TypeDecl> {
        self.order.iter().find(|d| d.name == name)
    }
    pub fn struct_fns(&self, name: &str) -> &StructFns {
        &self.structs[name]
    }
    pub fn struct_fns_opt(&self, name: &str) -> Option<&StructFns> {
        self.structs.get(name)
    }
    pub fn struct_fields(&self, name: &str) -> &[FieldDecl] {
        match &self.decl(name).kind {
            TypeKind::Struct(fs) => fs,
            TypeKind::Enum(_) => panic!("{name} is an enum"),
        }
    }
    pub fn struct_fields_opt(&self, name: &str) -> Option<&[FieldDecl]> {
        match &self.decl_opt(name)?.kind {
            TypeKind::Struct(fs) => Some(fs),
            TypeKind::Enum(_) => None,
        }
    }
    pub fn field_index(&self, struct_name: &str, field: &str) -> usize {
        self.struct_fields(struct_name)
            .iter()
            .position(|f| f.name == field)
            .unwrap_or_else(|| panic!("no field {field}"))
    }
    pub fn field_index_opt(&self, struct_name: &str, field: &str) -> Option<usize> {
        self.struct_fields_opt(struct_name)?.iter().position(|f| f.name == field)
    }
    pub fn variant(&self, enum_name: &str, variant: &str) -> &VariantFns {
        &self.enums[enum_name].iter().find(|(n, _)| n == variant).unwrap_or_else(|| panic!("no variant {variant}")).1
    }
    pub fn variant_opt(&self, enum_name: &str, variant: &str) -> Option<&VariantFns> {
        self.enums.get(enum_name)?.iter().find(|(n, _)| n == variant).map(|(_, f)| f)
    }
    /// The variant functions of an enum (declaration order).
    pub fn enum_variants(&self, enum_name: &str) -> Option<&[(String, VariantFns)]> {
        self.enums.get(enum_name).map(|v| v.as_slice())
    }
    /// The declaration of an enum variant.
    pub fn variant_decl(&self, enum_name: &str, variant: &str) -> Option<&VariantDecl> {
        match &self.decl_opt(enum_name)?.kind {
            TypeKind::Enum(vs) => vs.iter().find(|v| v.name == variant),
            TypeKind::Struct(_) => None,
        }
    }
    /// Position of a field within an enum variant.
    pub fn variant_field_index(&self, enum_name: &str, variant: &str, field: &str) -> Option<usize> {
        self.variant_decl(enum_name, variant)?.fields.iter().position(|f| f.name == field)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn array_type_names_round_trip() {
        for e in [Elem::I64, Elem::U8, Elem::Bool] {
            let n = pruv_core::typeinfo::array_of_elem_name(e.name()).expect("array name for every Elem");
            let t = Ty::from_name(n);
            assert_eq!(t, Ty::Array(e));
            assert_eq!(t.name(), n);
            assert!(t.is_array());
        }
        assert_eq!(Ty::from_name("u8"), Ty::User("u8".to_string()));
        assert_eq!(Ty::from_name("str"), Ty::Str);
        assert_eq!(Ty::Str.name(), "str");
    }
}
