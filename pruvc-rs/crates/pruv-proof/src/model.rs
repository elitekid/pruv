//! verify.py 10~70줄: `Opt`/`Res` Datatype(모듈 수준)와 프로그램별 `Model`(사용자 struct/enum, G1).
//!
//! 이름 규칙(글자 단위로 verify.py 와 같아야 한다):
//! - `Opt`: `some(sval: Int)`, `none`; `Res`: `ok(oval: Int)`, `err(eval: Int)`. 둘은 한 번의 `CreateDatatypes` 로 함께 만든다.
//! - 사용자 타입 i 번째(TypeTable 의존 순서)는 tag = `m{SEQ}t{i}!`.
//!   struct: datatype 이름 = 생성자 이름 = `tag+Name`, 접근자 = `tag+Name+"."+field`.
//!   enum: datatype = `tag+Name`, 변형 생성자 = `tag+Name+"::"+Variant`, 접근자 = 생성자 이름 + `"."+field`.
//! - SEQ(`_MODEL_SEQ`)는 프로세스(여기서는 스레드)에서 `Model` 을 만들 때마다 1 씩 증가한다. Python 은 프로그램마다
//!   Model 하나를 만들므로 `verify_program` 은 `next_seq()` 를 한 번만 부르고 함수마다 컨텍스트가 다르더라도
//!   같은 번호로 `Model::with_seq` 를 부른다.

use std::cell::Cell;
use std::collections::HashMap;

use pruv_core::ast as past;

use crate::sys::{Ast, DtCtor, DtCtorSpec, DtSort, DtSpec, FuncDecl, Sort, Z3};

thread_local! {
    static MODEL_SEQ: Cell<u32> = const { Cell::new(0) };
}

/// 표본마다 Python 새 프로세스와 같게 0 에서 다시 시작하고 싶을 때(spike 바이너리가 표본 앞에서 부른다).
pub fn reset_model_seq() {
    MODEL_SEQ.with(|c| c.set(0));
}

/// `_MODEL_SEQ[0] += 1` 뒤의 값.
pub fn next_seq() -> u32 {
    MODEL_SEQ.with(|c| {
        c.set(c.get() + 1);
        c.get()
    })
}

/// 배열 원소 저장 타입(G2). 내부 이름 대응은 pruv_core::typeinfo 한 곳.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum Elem {
    I64,
    U8,
    Bool,
}

impl Elem {
    /// 원소 타입 이름("i64"/"u8"/"bool").
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

/// Pruv 타입(vast.Type). 사용자 타입은 이름 하나.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Ty {
    I64,
    Bool,
    Unit,
    Array(Elem),
    Opt,
    Res,
    User(String),
}

impl Ty {
    /// 파서/검사기의 타입 이름 문자열 → `Ty`.
    pub fn from_name(n: &str) -> Ty {
        match n {
            "i64" => Ty::I64,
            "bool" => Ty::Bool,
            "unit" => Ty::Unit,
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
            Ty::Array(e) => pruv_core::typeinfo::array_of_elem_name(e.name()).unwrap(),
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

/// pruv-core 의 선언 → 이 크레이트의 선언(선언 순서 유지).
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
// Opt / Res (verify.py 10~12줄)
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
// Model (verify.py 17~62줄)
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
    /// TypeTable.order: 의존 우선, 선언 순서 안정.
    pub order: Vec<TypeDecl>,
    sorts: HashMap<String, Sort>,
    structs: HashMap<String, StructFns>,
    enums: HashMap<String, Vec<(String, VariantFns)>>,
    /// `by_sort`: z3 정렬 이름 → Pruv 타입(Opt/Res/사용자).
    by_sort: HashMap<String, Ty>,
    opt_sort: Sort,
    res_sort: Sort,
    int_sort: Sort,
    bool_sort: Sort,
}

/// typeinfo.py `_deps`: 선언된 사용자 타입 필드 의존(중복 없이 첫 등장 순서).
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

/// typeinfo.py `_build_order`: 방문 표시를 먼저 하고 의존을 먼저 방문한 뒤 자신을 추가.
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
    /// `Model(prog)`: 순번을 새로 올린다(시제품·표본용).
    pub fn new(z: &Z3, pre: &Prelude, decls: &[TypeDecl]) -> Model {
        match Model::with_seq(z, pre, decls, next_seq()) {
            Ok(m) => m,
            Err(e) => panic!("Model::new: {e}"),
        }
    }

    /// 순번을 호출자가 정한 `Model(prog)`. `decls` 는 프로그램 선언 순서(같은 이름이 반복되면 첫 선언만 쓴다).
    /// 필드 타입이 정렬을 갖지 못하면(Python `KeyError`) `Err("'이름'")`.
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

    /// `Model.sort_of`(Python 은 정렬이 없으면 `KeyError(이름)`).
    pub fn try_sort_of(&self, ty: &Ty) -> Result<Sort, String> {
        match ty {
            Ty::I64 => Ok(self.int_sort.clone()),
            Ty::Bool => Ok(self.bool_sort.clone()),
            Ty::Opt => Ok(self.opt_sort.clone()),
            Ty::Res => Ok(self.res_sort.clone()),
            Ty::User(n) => self.sorts.get(n).cloned().ok_or_else(|| format!("'{}'", n)),
            Ty::Unit | Ty::Array(_) => Err(format!("'{}'", ty.name())),
        }
    }

    /// 시제품용(패닉). 새 경로는 `try_sort_of`.
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
    /// `Model.is_user(ty)`: 사용자 정렬이 있는 타입인가.
    pub fn is_user(&self, ty: &Ty) -> bool {
        matches!(ty, Ty::User(n) if self.sorts.contains_key(n))
    }
    /// `Model.type_of(v)`: datatype 값의 정렬 이름으로 Pruv 타입을 찾는다(없으면 None).
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
    /// 열거형의 변형 함수들(선언 순서).
    pub fn enum_variants(&self, enum_name: &str) -> Option<&[(String, VariantFns)]> {
        self.enums.get(enum_name).map(|v| v.as_slice())
    }
    /// 열거형 변형의 선언.
    pub fn variant_decl(&self, enum_name: &str, variant: &str) -> Option<&VariantDecl> {
        match &self.decl_opt(enum_name)?.kind {
            TypeKind::Enum(vs) => vs.iter().find(|v| v.name == variant),
            TypeKind::Struct(_) => None,
        }
    }
    /// 열거형 변형 안의 필드 위치.
    pub fn variant_field_index(&self, enum_name: &str, variant: &str, field: &str) -> Option<usize> {
        self.variant_decl(enum_name, variant)?.fields.iter().position(|f| f.name == field)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn array_type_names_round_trip() {
        for n in ["array", "array_u8", "array_bool"] {
            let t = Ty::from_name(n);
            assert_eq!(t.name(), n);
            assert!(t.is_array());
        }
        assert_eq!(Ty::from_name("u8"), Ty::User("u8".to_string()));
    }
}
