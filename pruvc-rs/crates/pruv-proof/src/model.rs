//! verify.py 10~70줄: `Opt`/`Res` Datatype(모듈 수준)와 프로그램별 `Model`(사용자 struct/enum, G1).
//!
//! 이름 규칙(글자 단위로 verify.py 와 같아야 한다):
//! - `Opt`: `some(sval: Int)`, `none`; `Res`: `ok(oval: Int)`, `err(eval: Int)`. 둘은 한 번의 `CreateDatatypes` 로 함께 만든다.
//! - 사용자 타입 i 번째(TypeTable 의존 순서)는 tag = `m{SEQ}t{i}!`.
//!   struct: datatype 이름 = 생성자 이름 = `tag+Name`, 접근자 = `tag+Name+"."+field`.
//!   enum: datatype = `tag+Name`, 변형 생성자 = `tag+Name+"::"+Variant`, 접근자 = 생성자 이름 + `"."+field`.
//! - SEQ(`_MODEL_SEQ`)는 프로세스(여기서는 스레드)에서 `Model::new` 를 부를 때마다 1 씩 증가한다.

use std::cell::Cell;
use std::collections::HashMap;

use crate::sys::{Ast, DtCtor, DtCtorSpec, DtSort, DtSpec, FuncDecl, Sort, Z3};

thread_local! {
    static MODEL_SEQ: Cell<u32> = const { Cell::new(0) };
}

/// 표본마다 Python 새 프로세스와 같게 0 에서 다시 시작하고 싶을 때(spike 바이너리가 표본 앞에서 부른다).
pub fn reset_model_seq() {
    MODEL_SEQ.with(|c| c.set(0));
}

/// Pruv 타입(vast.Type). 사용자 타입은 이름 하나.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Ty {
    I64,
    Bool,
    Unit,
    Array,
    Opt,
    Res,
    User(String),
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
    /// `Model(prog)`. `decls` 는 프로그램 선언 순서(같은 이름이 반복되면 첫 선언만 쓴다).
    pub fn new(z: &Z3, pre: &Prelude, decls: &[TypeDecl]) -> Model {
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

        let seq = MODEL_SEQ.with(|c| {
            c.set(c.get() + 1);
            c.get()
        });
        let pre_tag = format!("m{}", seq);

        let mut m = Model {
            order: Vec::new(),
            sorts: HashMap::new(),
            structs: HashMap::new(),
            enums: HashMap::new(),
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
                    let spec = DtSpec {
                        name: cn.clone(),
                        ctors: vec![DtCtorSpec {
                            name: cn.clone(),
                            fields: fields
                                .iter()
                                .map(|fd| (format!("{}.{}", cn, fd.name), m.sort_of(&fd.ty)))
                                .collect(),
                        }],
                    };
                    let mut dt = z.create_datatypes(&[spec]);
                    let DtSort { sort, mut ctors } = dt.pop().expect("datatype");
                    let DtCtor { ctor, accs, .. } = ctors.remove(0);
                    m.structs.insert(d.name.clone(), StructFns { ctor, accs });
                    m.sorts.insert(d.name.clone(), sort);
                }
                TypeKind::Enum(variants) => {
                    let dn = format!("{}{}", tag, d.name);
                    let ctors: Vec<DtCtorSpec> = variants
                        .iter()
                        .map(|v| {
                            let cn = format!("{}{}::{}", tag, d.name, v.name);
                            DtCtorSpec {
                                name: cn.clone(),
                                fields: v
                                    .fields
                                    .iter()
                                    .map(|fd| (format!("{}.{}", cn, fd.name), m.sort_of(&fd.ty)))
                                    .collect(),
                            }
                        })
                        .collect();
                    let mut dt = z.create_datatypes(&[DtSpec { name: dn, ctors }]);
                    let DtSort { sort, ctors } = dt.pop().expect("datatype");
                    let fns: Vec<(String, VariantFns)> = variants
                        .iter()
                        .zip(ctors)
                        .map(|(v, c)| (v.name.clone(), VariantFns { ctor: c.ctor, rec: c.rec, accs: c.accs }))
                        .collect();
                    m.enums.insert(d.name.clone(), fns);
                    m.sorts.insert(d.name.clone(), sort);
                }
            }
        }
        m.order = order;
        m
    }

    /// `Model.sort_of`.
    pub fn sort_of(&self, ty: &Ty) -> Sort {
        match ty {
            Ty::I64 => self.int_sort.clone(),
            Ty::Bool => self.bool_sort.clone(),
            Ty::Opt => self.opt_sort.clone(),
            Ty::Res => self.res_sort.clone(),
            Ty::User(n) => self.sorts[n].clone(),
            Ty::Unit | Ty::Array => panic!("sort_of: {:?}", ty),
        }
    }

    pub fn sort(&self, name: &str) -> &Sort {
        &self.sorts[name]
    }
    pub fn decl(&self, name: &str) -> &TypeDecl {
        self.order.iter().find(|d| d.name == name).unwrap_or_else(|| panic!("unknown type {name}"))
    }
    pub fn struct_fns(&self, name: &str) -> &StructFns {
        &self.structs[name]
    }
    pub fn struct_fields(&self, name: &str) -> &[FieldDecl] {
        match &self.decl(name).kind {
            TypeKind::Struct(fs) => fs,
            TypeKind::Enum(_) => panic!("{name} is an enum"),
        }
    }
    pub fn field_index(&self, struct_name: &str, field: &str) -> usize {
        self.struct_fields(struct_name)
            .iter()
            .position(|f| f.name == field)
            .unwrap_or_else(|| panic!("no field {field}"))
    }
    pub fn variant(&self, enum_name: &str, variant: &str) -> &VariantFns {
        &self.enums[enum_name].iter().find(|(n, _)| n == variant).unwrap_or_else(|| panic!("no variant {variant}")).1
    }
}
