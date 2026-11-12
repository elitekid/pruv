//! verify.py lines 10-300: the `Opt`/`Res` Datatypes (module level) and the per-program `Model` (user struct/enum, G1; G3 A2 generic
//! instances and abstract sorts).
//!
//! Naming rules (must match verify.py character for character):
//! - `Opt`: `some(sval: Int)`, `none`; `Res`: `ok(oval: Int)`, `err(eval: Int)`. Both are created together with a single `CreateDatatypes`.
//! - The i-th user type (in TypeTable dependency order, generic declarations included in the count) has tag = `m{SEQ}t{i}!`.
//!   struct: datatype name = constructor name = `tag+Name`, accessor = `tag+Name+"."+field`.
//!   enum: datatype = `tag+Name`, variant constructor = `tag+Name+"::"+Variant`, accessor = constructor name + `"."+field`.
//!   Generic declarations get no datatype of their own.
//! - G3 A2 instances (Option<X>, Result<X>, D<..>) are built lazily, one datatype per complete structural type, named
//!   `m{SEQ}g{N}!` + format_type(ty); N counts the instances of the whole program in order of first construction (Python keeps one
//!   Model for all functions, so the number is kept in a per-SEQ registry that outlives the per-function Rust `Model`).
//!   Option<X>: `tag+Some(tag+Some.val)`, `tag+None`; Result<X>: `tag+Ok(tag+Ok.val)`, `tag+Err(tag+Err.val: Int)`;
//!   struct/enum as for non-generic ones, with the tag above.
//! - A type parameter of a function is the uninterpreted sort `g3!<function declaration index>!T<i>`.
//! - SEQ (`_MODEL_SEQ`) increases by 1 each time a `Model` is created in the process (here, the thread). Python creates
//!   one Model per program, so `verify_program` calls `next_seq()` only once and, even though each function has a different context,
//!   calls `Model::with_seq` with the same number.

use std::cell::{Cell, RefCell};
use std::collections::{HashMap, HashSet};

use pruv_core::ast as past;
use pruv_core::gtype::{self, GType};

use crate::sys::{Ast, DtCtor, DtCtorSpec, DtSort, DtSpec, FuncDecl, Sort, Z3};

thread_local! {
    static MODEL_SEQ: Cell<u32> = const { Cell::new(0) };
    /// seq -> instance types in order of first construction (the position + 1 is the number N in `m{SEQ}g{N}!`).
    static GREG: RefCell<HashMap<u32, Vec<GType>>> = RefCell::new(HashMap::new());
}

/// For restarting from 0 per sample, like a fresh Python process (the spike binary calls this before each sample).
pub fn reset_model_seq() {
    MODEL_SEQ.with(|c| c.set(0));
    GREG.with(|g| g.borrow_mut().clear());
}

/// The value after `_MODEL_SEQ[0] += 1`.
pub fn next_seq() -> u32 {
    let n = MODEL_SEQ.with(|c| {
        c.set(c.get() + 1);
        c.get()
    });
    GREG.with(|g| {
        g.borrow_mut().remove(&n);
    });
    n
}

/// The number `N` of an instance type (assigned at its first construction, `s.gcount += 1`).
fn greg_number(seq: u32, ty: &GType) -> usize {
    GREG.with(|g| {
        let mut g = g.borrow_mut();
        let v = g.entry(seq).or_default();
        match v.iter().position(|t| t == ty) {
            Some(i) => i + 1,
            None => {
                v.push(ty.clone());
                v.len()
            }
        }
    })
}

/// Array element storage type (G2; `Abs` = an element of abstract sort, G3 A2). The internal name mapping lives in one place, pruv_core::typeinfo.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum Elem {
    I64,
    U8,
    Bool,
    /// G3: an element whose type is a type parameter (the parameter itself is kept in `Arr.ety`).
    Abs,
}

impl Elem {
    /// Element type name ("i64"/"u8"/"bool").
    pub fn name(self) -> &'static str {
        match self {
            Elem::I64 => "i64",
            Elem::U8 => "u8",
            Elem::Bool => "bool",
            Elem::Abs => "abs",
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

/// Pruv type (vast.Type). A user type is a single name; G3 types keep their structure in a `GType`.
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
    /// A bound type parameter (G3).
    Param(GType),
    /// `[T]`: an array of an abstract element type (G3); the payload is the element type.
    GArray(GType),
    /// Option<X> / Result<X> with X other than i64, or a generic declaration applied to arguments (G3).
    Inst(GType),
}

impl Ty {
    /// The parser/checker's type name string (a legacy plain name or a G3 type key) → `Ty`.
    pub fn from_name(n: &str) -> Ty {
        if gtype::is_g3_key(n) {
            if let Ok(g) = GType::try_from_key(n) {
                return Ty::from_gtype(&g);
            }
        }
        Ty::from_plain(n)
    }
    fn from_plain(n: &str) -> Ty {
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
    /// A structured type → `Ty` (legacy forms come back as the legacy variants).
    pub fn from_gtype(g: &GType) -> Ty {
        if g.owner.is_some() {
            return Ty::Param(g.clone());
        }
        if g.args.is_empty() {
            return Ty::from_plain(&g.name);
        }
        if g.name == "array" {
            return Ty::GArray(g.args[0].clone());
        }
        Ty::Inst(g.clone())
    }
    /// The structured type of this `Ty`.
    pub fn to_gtype(&self) -> GType {
        match self {
            Ty::I64 => GType::i64(),
            Ty::Bool => GType::bool(),
            Ty::Unit => GType::unit(),
            Ty::Str => GType::str(),
            Ty::Opt => GType::option(),
            Ty::Res => GType::result(),
            Ty::Array(Elem::U8) => GType::array_u8(),
            Ty::Array(Elem::Bool) => GType::array_bool(),
            Ty::Array(_) => GType::array(),
            Ty::User(n) => GType::new(n, Vec::new()),
            Ty::Param(g) | Ty::Inst(g) => g.clone(),
            Ty::GArray(e) => GType::new("array", vec![e.clone()]),
        }
    }
    /// vast `Type.name`.
    pub fn name(&self) -> &str {
        match self {
            Ty::I64 => "i64",
            Ty::Bool => "bool",
            Ty::Unit => "unit",
            Ty::Array(e) => pruv_core::typeinfo::array_of_elem_name(e.name()).unwrap_or("array"),
            Ty::Str => "str",
            Ty::Opt => "option",
            Ty::Res => "result",
            Ty::User(n) => n,
            Ty::Param(g) | Ty::Inst(g) => &g.name,
            Ty::GArray(_) => "array",
        }
    }
    pub fn is_array(&self) -> bool {
        matches!(self, Ty::Array(_) | Ty::GArray(_))
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
    /// The type arguments of a structured type (empty otherwise).
    pub fn args(&self) -> &[GType] {
        match self {
            Ty::Inst(g) => &g.args,
            _ => &[],
        }
    }
    /// G6 A1: the owned collection kind of this type (verify.py `ty.owner is None and ty.name in _COLL`).
    /// `Vec<T>` / `HashMap<K, V>` are `Ty::Inst` (they always carry arguments); `String` has no arguments and
    /// comes out of `from_plain` as `Ty::User("string")`.
    pub fn coll(&self) -> Option<Coll> {
        match self {
            Ty::Inst(g) if g.owner.is_none() && g.name == "vec" && g.args.len() == 1 => Some(Coll::Vec(g.args[0].clone())),
            Ty::Inst(g) if g.owner.is_none() && g.name == "hashmap" && g.args.len() == 2 => {
                Some(Coll::Map(g.args[0].clone(), g.args[1].clone()))
            }
            Ty::User(n) if n == "string" => Some(Coll::Str),
            _ => None,
        }
    }
}

/// G6 A1: Vec<T> (element type), HashMap<K, V>, String.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Coll {
    Vec(GType),
    Map(GType, GType),
    Str,
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
    /// Number of type parameters (0 = not generic).
    pub tparams: usize,
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
            past::TypeDecl::Struct(s) => TypeDecl {
                name: s.name.clone(),
                kind: TypeKind::Struct(conv_fields(&s.fields)),
                tparams: s.tparams.len(),
            },
            past::TypeDecl::Enum(e) => TypeDecl {
                name: e.name.clone(),
                kind: TypeKind::Enum(
                    e.variants
                        .iter()
                        .map(|v| VariantDecl { name: v.name.clone(), fields: conv_fields(&v.fields) })
                        .collect(),
                ),
                tparams: e.tparams.len(),
            },
        })
        .collect()
}

impl TypeDecl {
    pub fn new_struct(name: &str, fields: &[(&str, Ty)]) -> TypeDecl {
        TypeDecl { name: name.to_string(), kind: TypeKind::Struct(fields_of(fields)), tparams: 0 }
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
            tparams: 0,
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

/// verify.py `_OptOps`: the z3 operations of one Option datatype (the legacy `Opt`, or a G3 instance Option<X>).
#[derive(Clone)]
pub struct OptOps {
    pub some: FuncDecl,
    pub none: Ast,
    pub is_some: FuncDecl,
    pub is_none: FuncDecl,
    pub sval: FuncDecl,
}

/// verify.py `_ResOps`: the z3 operations of one Result datatype (the legacy `Res`, or a G3 instance Result<X>).
#[derive(Clone)]
pub struct ResOps {
    pub ok: FuncDecl,
    pub err: FuncDecl,
    pub is_ok: FuncDecl,
    pub is_err: FuncDecl,
    pub oval: FuncDecl,
    pub eval: FuncDecl,
}

impl OptOps {
    fn legacy(p: &Prelude) -> OptOps {
        OptOps {
            some: p.opt.ctors[0].ctor.clone(),
            none: p.none(),
            is_some: p.opt.ctors[0].rec.clone(),
            is_none: p.opt.ctors[1].rec.clone(),
            sval: p.opt.ctors[0].accs[0].clone(),
        }
    }
}

impl ResOps {
    fn legacy(p: &Prelude) -> ResOps {
        ResOps {
            ok: p.res.ctors[0].ctor.clone(),
            err: p.res.ctors[1].ctor.clone(),
            is_ok: p.res.ctors[0].rec.clone(),
            is_err: p.res.ctors[1].rec.clone(),
            oval: p.res.ctors[0].accs[0].clone(),
            eval: p.res.ctors[1].accs[0].clone(),
        }
    }
}

// ---------------------------------------------------------------------------------------------
// Model (verify.py lines 137-298)
// ---------------------------------------------------------------------------------------------

#[derive(Clone)]
pub struct StructFns {
    pub ctor: FuncDecl,
    pub accs: Vec<FuncDecl>,
}
#[derive(Clone)]
pub struct VariantFns {
    pub ctor: FuncDecl,
    pub rec: FuncDecl,
    pub accs: Vec<FuncDecl>,
}

/// Struct or enum (`TypeTable.is_struct` / `is_enum`).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum NomKind {
    Struct,
    Enum,
}

/// The lazily built part of the Model (G3 A2): instances and abstract sorts of one z3 context.
#[derive(Default)]
struct GState {
    ginst: HashMap<GType, Sort>,
    gopt: HashMap<GType, OptOps>,
    gres: HashMap<GType, ResOps>,
    gstruct: HashMap<GType, StructFns>,
    genum: HashMap<GType, Vec<(String, VariantFns)>>,
    /// (owner, index) -> uninterpreted sort of a function type parameter
    abstract_: HashMap<(String, usize), Sort>,
    /// sort name -> type-parameter spelling (counterexample rendering)
    abs_name: HashMap<String, String>,
    /// constructor name of a generic Option/Result instance -> source name
    short: HashMap<String, &'static str>,
}

/// G9 A1: the buffer-field datatype `Buf(len: Int, arr: Array(Int, elem sort))` of one element sort (verify.py `Model.bufs` entry
/// `(sort, constructor, length accessor, array accessor)`).
#[derive(Clone)]
pub struct BufFns {
    pub sort: Sort,
    pub ctor: FuncDecl,
    pub len: FuncDecl,
    pub arr: FuncDecl,
}

pub struct Model {
    z: Z3,
    /// TypeTable.order: dependencies first, stable in declaration order (generic declarations included).
    pub order: Vec<TypeDecl>,
    sorts: HashMap<String, Sort>,
    structs: HashMap<String, StructFns>,
    enums: HashMap<String, Vec<(String, VariantFns)>>,
    /// `by_sort`: z3 sort name → Pruv type (Opt/Res/user/instances).
    by_sort: RefCell<HashMap<String, Ty>>,
    opt_sort: Sort,
    res_sort: Sort,
    int_sort: Sort,
    bool_sort: Sort,
    opt_ops: OptOps,
    res_ops: ResOps,
    seq: u32,
    pre_tag: String,
    /// function name -> declaration index (the later one wins if names repeat)
    fn_index: HashMap<String, usize>,
    g: RefCell<GState>,
    /// G3: `wf_trivial` cache per instance type.
    wf_triv: RefCell<HashMap<GType, bool>>,
    /// G9 A1 (verify.py `s.g9`): the program carries G9 metadata (a G9 feature is present).
    g9: bool,
    /// recursive type name -> member names of its SCC (declaration order)
    scc_of: HashMap<String, Vec<String>>,
    /// names of non-generic types that are recursive or (transitively) contain a recursive type
    recrel: HashSet<String>,
    /// `false` = "int" (i64/u8/str elements), `true` = "bool": buffer datatypes built lazily
    bufs: RefCell<HashMap<bool, BufFns>>,
    buf_names: RefCell<HashSet<String>>,
    /// lazily declared uninterpreted `size!<Name>` / `wf!<Name>` functions
    size_f: RefCell<HashMap<String, FuncDecl>>,
    wf_f: RefCell<HashMap<String, FuncDecl>>,
}

/// typeinfo.py `_deps` as names: field dependencies on declared user types (no duplicates, first-appearance order).
fn dep_names(d: &TypeDecl, decls: &[TypeDecl]) -> Vec<String> {
    let mut out: Vec<String> = Vec::new();
    for f in d.all_fields() {
        for n in gtype::dependencies(&f.ty.to_gtype()) {
            if decls.iter().any(|u| u.name == n) && !out.contains(&n) {
                out.push(n);
            }
        }
    }
    out
}

/// typeinfo.py `_deps`: field dependencies on declared user types (no duplicates, first-appearance order),
/// a nominal reference anywhere inside a field type (nested arguments included) is an edge.
fn deps(d: &TypeDecl, uniq: &[TypeDecl]) -> Vec<usize> {
    let mut out: Vec<usize> = Vec::new();
    for f in d.all_fields() {
        for n in gtype::dependencies(&f.ty.to_gtype()) {
            if let Some(i) = uniq.iter().position(|u| u.name == n) {
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

fn nokey(n: &str) -> String {
    format!("'{}'", n)
}

impl Model {
    /// `Model(prog)`: bumps the sequence number anew (for the prototype and samples).
    pub fn new(z: &Z3, pre: &Prelude, decls: &[TypeDecl]) -> Model {
        match Model::with_seq(z, pre, decls, next_seq()) {
            Ok(m) => m,
            Err(e) => panic!("Model::new: {e}"),
        }
    }

    /// `Model(prog)` with a caller-chosen sequence number and no function names (no abstract sorts can be named).
    pub fn with_seq(z: &Z3, pre: &Prelude, decls: &[TypeDecl], seq: u32) -> Result<Model, String> {
        Model::with_seq_fns(z, pre, decls, &[], seq)
    }

    /// `Model(prog)` of a checked program: `fns` = the function names in declaration order (abstract sorts are named by index).
    pub fn for_program(z: &Z3, pre: &Prelude, decls: &[TypeDecl], prog: &past::Program, seq: u32) -> Result<Model, String> {
        let fns: Vec<String> = prog.functions.iter().map(|f| f.name.clone()).collect();
        Model::with_seq_g9(z, pre, decls, &fns, prog.g9.as_ref(), seq)
    }

    /// `Model(prog)` with a caller-chosen sequence number. `decls` is the program declaration order (if a name repeats, only the first declaration is used).
    /// If a field type has no sort (Python `KeyError`), `Err("'name'")`.
    pub fn with_seq_fns(z: &Z3, pre: &Prelude, decls: &[TypeDecl], fns: &[String], seq: u32) -> Result<Model, String> {
        Model::with_seq_g9(z, pre, decls, fns, None, seq)
    }

    /// `Model(prog)` with the G9 A1 metadata (`prog.g9`, None for a program without a G9 feature).
    pub fn with_seq_g9(
        z: &Z3,
        pre: &Prelude,
        decls: &[TypeDecl],
        fns: &[String],
        meta: Option<&past::G9Meta>,
        seq: u32,
    ) -> Result<Model, String> {
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

        let mut fn_index: HashMap<String, usize> = HashMap::new();
        for (i, n) in fns.iter().enumerate() {
            fn_index.insert(n.clone(), i);
        }

        let mut m = Model {
            z: z.clone(),
            // the declarations are visible from the start: a generic instance built while the first types are created needs them
            order: order.clone(),
            sorts: HashMap::new(),
            structs: HashMap::new(),
            enums: HashMap::new(),
            by_sort: RefCell::new(by_sort),
            opt_sort: pre.opt.sort.clone(),
            res_sort: pre.res.sort.clone(),
            int_sort: z.int_sort(),
            bool_sort: z.bool_sort(),
            opt_ops: OptOps::legacy(pre),
            res_ops: ResOps::legacy(pre),
            seq,
            pre_tag: pre_tag.clone(),
            fn_index,
            g: RefCell::new(GState::default()),
            wf_triv: RefCell::new(HashMap::new()),
            g9: meta.is_some(),
            scc_of: HashMap::new(),
            recrel: HashSet::new(),
            bufs: RefCell::new(HashMap::new()),
            buf_names: RefCell::new(HashSet::new()),
            size_f: RefCell::new(HashMap::new()),
            wf_f: RefCell::new(HashMap::new()),
        };
        // G9 A1: recursive type SCCs and the types that (transitively) contain one
        if let Some(meta) = meta {
            for names in &meta.type_sccs {
                let mut keyed: Vec<(usize, String)> = Vec::new();
                for n in names {
                    let i = uniq.iter().position(|u| u.name == *n).ok_or_else(|| nokey(n))?;
                    keyed.push((i, n.clone()));
                }
                keyed.sort_by_key(|(i, _)| *i); // stable, like Python `sorted(key=pindex)`
                let mem: Vec<String> = keyed.into_iter().map(|(_, n)| n).collect();
                for n in &mem {
                    m.scc_of.insert(n.clone(), mem.clone());
                }
            }
            m.recrel = m.scc_of.keys().cloned().collect();
            let mut changed = !m.recrel.is_empty();
            while changed {
                changed = false;
                for d in &uniq {
                    if !m.recrel.contains(&d.name)
                        && d.tparams == 0
                        && dep_names(d, &uniq).iter().any(|n| m.recrel.contains(n))
                    {
                        m.recrel.insert(d.name.clone());
                        changed = true;
                    }
                }
            }
        }
        let idx_of: HashMap<String, usize> = order.iter().enumerate().map(|(i, d)| (d.name.clone(), i)).collect();
        let mut done: HashSet<String> = HashSet::new();
        for d in &order {
            m.build(&d.name, &idx_of, &mut done)?;
        }
        Ok(m)
    }

    /// verify.py `Model._build`: create the datatype of `name` (its whole recursive SCC at once), dependencies first.
    /// For a program without recursive types this visits the declarations in `order` exactly like the old loop.
    fn build(&mut self, name: &str, idx_of: &HashMap<String, usize>, done: &mut HashSet<String>) -> Result<(), String> {
        if done.contains(name) {
            return Ok(());
        }
        let d = self.decl_opt(name).ok_or_else(|| nokey(name))?.clone();
        let group: Vec<String> = match self.scc_of.get(name) {
            Some(g) if !g.is_empty() => g.clone(),
            _ => vec![name.to_string()],
        };
        for n in &group {
            done.insert(n.clone());
        }
        if d.tparams > 0 {
            return Ok(()); // generic declarations are instantiated lazily
        }
        let mut members: Vec<TypeDecl> = Vec::new();
        for n in &group {
            members.push(self.decl_opt(n).ok_or_else(|| nokey(n))?.clone());
        }
        for mdecl in &members {
            for dep in dep_names(mdecl, &self.order) {
                if !group.contains(&dep) {
                    self.build(&dep, idx_of, done)?;
                }
            }
        }
        self.make_group(&members, idx_of)
    }

    /// The sort of a field type while the datatypes of `gnames` are under construction: a member type is a datatype
    /// reference (`Some(index in the group)`; the returned sort is then an ignored placeholder), anything else its sort.
    fn group_field_sort(&self, ft: &Ty, gnames: &[String]) -> Result<(Sort, Option<usize>), String> {
        if let Ty::User(n) = ft {
            if let Some(i) = gnames.iter().position(|g| g == n) {
                return Ok((self.int_sort.clone(), Some(i)));
            }
        }
        Ok((self.try_sort_of(ft)?, None))
    }

    /// verify.py `Model._make_group`: one simultaneous `CreateDatatypes` for the members of an SCC (a single member for an
    /// ordinary type: the same call as the old per-type construction).
    fn make_group(&mut self, members: &[TypeDecl], idx_of: &HashMap<String, usize>) -> Result<(), String> {
        let gnames: Vec<String> = members.iter().map(|d| d.name.clone()).collect();
        let mut specs: Vec<DtSpec> = Vec::new();
        let mut refs: Vec<Vec<Vec<Option<usize>>>> = Vec::new();
        for d in members {
            let idx = *idx_of.get(&d.name).ok_or_else(|| nokey(&d.name))?;
            let tag = format!("{}t{}!", self.pre_tag, idx);
            let mut ctor_specs: Vec<DtCtorSpec> = Vec::new();
            let mut ctor_refs: Vec<Vec<Option<usize>>> = Vec::new();
            let dtname: String;
            match &d.kind {
                TypeKind::Struct(fields) => {
                    let cn = format!("{}{}", tag, d.name);
                    let mut fs: Vec<(String, Sort)> = Vec::new();
                    let mut rf: Vec<Option<usize>> = Vec::new();
                    for fd in fields {
                        let (s, r) = self.group_field_sort(&fd.ty, &gnames)?;
                        fs.push((format!("{}.{}", cn, fd.name), s));
                        rf.push(r);
                    }
                    dtname = cn.clone();
                    ctor_specs.push(DtCtorSpec { name: cn, fields: fs });
                    ctor_refs.push(rf);
                }
                TypeKind::Enum(variants) => {
                    dtname = format!("{}{}", tag, d.name);
                    for v in variants {
                        let cn = format!("{}{}::{}", tag, d.name, v.name);
                        let mut fs: Vec<(String, Sort)> = Vec::new();
                        let mut rf: Vec<Option<usize>> = Vec::new();
                        for fd in &v.fields {
                            let (s, r) = self.group_field_sort(&fd.ty, &gnames)?;
                            fs.push((format!("{}.{}", cn, fd.name), s));
                            rf.push(r);
                        }
                        ctor_specs.push(DtCtorSpec { name: cn, fields: fs });
                        ctor_refs.push(rf);
                    }
                }
            }
            specs.push(DtSpec { name: dtname, ctors: ctor_specs });
            refs.push(ctor_refs);
        }
        let out = self.z.create_datatypes_refs(&specs, &refs);
        for (d, dt) in members.iter().zip(out) {
            let DtSort { sort, mut ctors } = dt;
            match &d.kind {
                TypeKind::Struct(_) => {
                    if ctors.is_empty() {
                        return Err("datatype".to_string());
                    }
                    let DtCtor { ctor, accs, .. } = ctors.remove(0);
                    self.structs.insert(d.name.clone(), StructFns { ctor, accs });
                }
                TypeKind::Enum(variants) => {
                    let fns: Vec<(String, VariantFns)> = variants
                        .iter()
                        .zip(ctors)
                        .map(|(v, c)| (v.name.clone(), VariantFns { ctor: c.ctor, rec: c.rec, accs: c.accs }))
                        .collect();
                    self.enums.insert(d.name.clone(), fns);
                }
            }
            self.by_sort.borrow_mut().insert(sort.name(), Ty::User(d.name.clone()));
            self.sorts.insert(d.name.clone(), sort);
        }
        Ok(())
    }

    // ---------- G9 A1: buffer fields ----------

    /// verify.py `Model.is_buf`: a `[i64]` / `[u8]` / `[bool]` / `str` field type (never a G3 `[T]`).
    pub fn is_buf(ty: &Ty) -> bool {
        matches!(ty, Ty::Array(_) | Ty::Str)
    }

    /// verify.py `Model.buf_elem`.
    pub fn buf_elem(ty: &Ty) -> Elem {
        match ty {
            Ty::Array(Elem::Bool) => Elem::Bool,
            Ty::Array(Elem::U8) | Ty::Str => Elem::U8,
            _ => Elem::I64,
        }
    }

    /// verify.py `Model.bufsort` (the whole `bufs` entry): datatype Buf(len: Int, arr: Array(Int, elem sort)); one per element
    /// sort (Int for i64/u8/str, Bool).
    pub fn buf_entry(&self, ty: &Ty) -> Result<BufFns, String> {
        let key = matches!(ty, Ty::Array(Elem::Bool));
        if let Some(e) = self.bufs.borrow().get(&key) {
            return Ok(e.clone());
        }
        let tag = format!("{}buf!{}", self.pre_tag, if key { "bool" } else { "int" });
        let esort = if key { self.bool_sort.clone() } else { self.int_sort.clone() };
        let arr_sort = self.z.array_sort(&self.int_sort, &esort);
        let spec = DtSpec {
            name: tag.clone(),
            ctors: vec![DtCtorSpec {
                name: format!("{}.mk", tag),
                fields: vec![(format!("{}.len", tag), self.int_sort.clone()), (format!("{}.arr", tag), arr_sort)],
            }],
        };
        let mut dt = self.z.create_datatypes(&[spec]);
        let DtSort { sort, mut ctors } = dt.pop().ok_or("datatype")?;
        if ctors.is_empty() {
            return Err("datatype".to_string());
        }
        let DtCtor { ctor, accs, .. } = ctors.remove(0);
        if accs.len() < 2 {
            return Err("datatype".to_string());
        }
        let ent = BufFns { sort: sort.clone(), ctor, len: accs[0].clone(), arr: accs[1].clone() };
        self.bufs.borrow_mut().insert(key, ent.clone());
        self.buf_names.borrow_mut().insert(sort.name());
        Ok(ent)
    }

    /// verify.py `Model.bufsort`.
    pub fn bufsort(&self, ty: &Ty) -> Result<Sort, String> {
        Ok(self.buf_entry(ty)?.sort)
    }

    /// Is `name` the name of a buffer datatype sort (verify.py `sname in s.model.buf_names`)?
    pub fn is_buf_sort_name(&self, name: &str) -> bool {
        self.buf_names.borrow().contains(name)
    }

    /// The `(array, length)` of a stored buffer field value `term` of field type `fty` (what verify.py `Model.field_get` wraps
    /// in `mk_arr(arr(term), len(term), ..)`). The array accessor is applied first, like the Python argument order.
    pub fn buf_parts(&self, fty: &Ty, term: &Ast) -> Result<(Ast, Ast), String> {
        let ent = self.buf_entry(fty)?;
        let a = ent.arr.apply1(term);
        let n = ent.len.apply1(term);
        Ok((a, n))
    }

    /// verify.py `Model.field_put` for an array value `(a, n)` stored into a buffer field of type `fty`: `Buf(n, a)`.
    pub fn buf_put(&self, fty: &Ty, n: &Ast, a: &Ast) -> Result<Ast, String> {
        let ent = self.buf_entry(fty)?;
        Ok(ent.ctor.apply(&[n.clone(), a.clone()]))
    }

    // ---------- G9 A1: structural size and well-formedness of recursive values ----------

    /// verify.py `s.g9`.
    pub fn is_g9(&self) -> bool {
        self.g9
    }

    /// Does the (non-generic) type name belong to a recursive type SCC (`name in s.scc_of`)?
    pub fn in_scc(&self, name: &str) -> bool {
        self.scc_of.contains_key(name)
    }

    /// verify.py `Model.rel`.
    pub fn rel(&self, ty: &Ty) -> bool {
        matches!(ty, Ty::User(n) if self.recrel.contains(n))
    }

    /// verify.py `Model.rel_nominal`: a plain non-generic user struct/enum type.
    pub fn rel_nominal(&self, ty: &Ty) -> bool {
        matches!(ty, Ty::User(n) if self.decl_opt(n).map_or(false, |d| d.tparams == 0))
    }

    /// verify.py `Model.size_fn`: size_D as an uninterpreted z3 function (all members of the SCC of D are declared first).
    pub fn size_fn(&self, name: &str) -> Result<FuncDecl, String> {
        if let Some(f) = self.size_f.borrow().get(name) {
            return Ok(f.clone());
        }
        let group: Vec<String> = match self.scc_of.get(name) {
            Some(g) if !g.is_empty() => g.clone(),
            _ => vec![name.to_string()],
        };
        for n in &group {
            let s = self.sorts.get(n).cloned().ok_or_else(|| nokey(n))?;
            let f = self.z.func_decl(&format!("{}size!{}", self.pre_tag, n), &[s], &self.int_sort);
            self.size_f.borrow_mut().insert(n.clone(), f);
        }
        self.size_f.borrow().get(name).cloned().ok_or_else(|| nokey(name))
    }

    /// verify.py `Model.weight`: size weight of a field value `t` of type `fty` (None = always 0): nominal values count their
    /// own size, Some/Ok payloads count their payload, everything else is 0.
    pub fn weight(&self, fty: &Ty, t: &Ast) -> Result<Option<Ast>, String> {
        let early = matches!(fty, Ty::Param(_) | Ty::I64 | Ty::Bool | Ty::Opt | Ty::Res);
        if early || Model::is_buf(fty) || fty.coll().is_some() {
            return Ok(None);
        }
        if let Ty::Inst(g) = fty {
            if g.name == "option" {
                let o = self.opt(Some(fty))?;
                let w = self.weight(&Ty::from_gtype(&g.args[0]), &o.sval.apply1(t))?;
                return Ok(w.map(|w| self.z.ite(&o.is_some.apply1(t), &w, &self.z.int(0))));
            }
            if g.name == "result" {
                let o = self.res(Some(fty))?;
                let w = self.weight(&Ty::from_gtype(&g.args[0]), &o.oval.apply1(t))?;
                return Ok(w.map(|w| self.z.ite(&o.is_ok.apply1(t), &w, &self.z.int(0))));
            }
        }
        if self.nominal_kind(fty).is_some() {
            if let Ty::User(n) = fty {
                return Ok(Some(self.size_fn(n)?.apply1(t)));
            }
            // an admitted acyclic G3 application: internal helper traversal
            return Ok(Some(self.size_value(fty, t)?));
        }
        Ok(None)
    }

    /// verify.py `Model.size_sum`.
    pub fn size_sum(&self, ty: &Ty, variant: Option<&str>, accs: &[FuncDecl], t: &Ast) -> Result<Ast, String> {
        let mut total = self.z.int(1);
        for ((_fd, fty), acc) in self.fields_of(ty, variant)?.iter().zip(accs.iter()) {
            let term = acc.apply1(t);
            if Model::is_buf(fty) {
                // field_get makes an Arr view (weight None): only the buffer sort is (idempotently) ensured
                self.buf_entry(fty)?;
                continue;
            }
            if let Some(w) = self.weight(fty, &term)? {
                total = total.add(&w);
            }
        }
        Ok(total)
    }

    /// verify.py `Model.size_value`: one step of size: 1 + the weights of the active constructor's fields.
    pub fn size_value(&self, ty: &Ty, t: &Ast) -> Result<Ast, String> {
        if self.nominal_kind(ty) == Some(NomKind::Struct) {
            let accs = self.struct_info(ty)?.accs;
            return self.size_sum(ty, None, &accs, t);
        }
        let infos = self.enum_info(ty)?;
        let mut body: Option<Ast> = None;
        for vn in self.variant_names(ty).iter().rev() {
            let vf = infos.iter().find(|(n, _)| n == vn).map(|(_, f)| f.clone()).ok_or_else(|| nokey(vn))?;
            let val = self.size_sum(ty, Some(vn), &vf.accs, t)?;
            body = Some(match body {
                None => val,
                Some(b) => self.z.ite(&vf.rec.apply1(t), &val, &b),
            });
        }
        body.ok_or_else(|| "size of an enum without variants".to_string())
    }

    /// verify.py `Model.wf_fn`: wf_D (recursive types only) as an uninterpreted z3 function over the SCC of D.
    pub fn wf_fn(&self, name: &str) -> Result<FuncDecl, String> {
        if let Some(f) = self.wf_f.borrow().get(name) {
            return Ok(f.clone());
        }
        let group: Vec<String> = self.scc_of.get(name).cloned().ok_or_else(|| nokey(name))?;
        for n in &group {
            let s = self.sorts.get(n).cloned().ok_or_else(|| nokey(n))?;
            let f = self.z.func_decl(&format!("{}wf!{}", self.pre_tag, n), &[s], &self.bool_sort);
            self.wf_f.borrow_mut().insert(n.clone(), f);
        }
        self.wf_f.borrow().get(name).cloned().ok_or_else(|| nokey(name))
    }

    // ---------- G3 A2: abstract sorts and generic datatype instances ----------

    /// Fresh uninterpreted sort `g3!<function-declaration-index>!T<i>` of a function type parameter.
    pub fn abstract_sort(&self, g: &GType) -> Sort {
        let owner = g.owner.clone().unwrap_or_default();
        let key = (owner.clone(), g.index);
        if let Some(s) = self.g.borrow().abstract_.get(&key) {
            return s.clone();
        }
        let fname = owner.strip_prefix("fn:").unwrap_or(&owner).to_string();
        let first = match self.fn_index.get(&fname) {
            Some(i) => i.to_string(),
            None => fname.clone(),
        };
        let name = format!("g3!{}!T{}", first, g.index);
        let s = self.z.declare_sort(&name);
        let mut st = self.g.borrow_mut();
        st.abstract_.insert(key, s.clone());
        st.abs_name.insert(name, g.name.clone());
        s
    }

    /// The spelling of the type parameter whose abstract sort is called `sort_name`.
    pub fn abs_name_of(&self, sort_name: &str) -> Option<String> {
        self.g.borrow().abs_name.get(sort_name).cloned()
    }

    /// The source name (`Some`, `None`, `Ok`, `Err`) of a constructor of a generic Option/Result instance.
    pub fn short_of(&self, ctor_name: &str) -> Option<&'static str> {
        self.g.borrow().short.get(ctor_name).copied()
    }

    /// `[(FieldDecl, field type)]` with the type arguments of `ty` substituted into the declared field types.
    pub fn fields_of(&self, ty: &Ty, variant: Option<&str>) -> Result<Vec<(FieldDecl, Ty)>, String> {
        let name = ty.name();
        let d = self.decl_opt(name).ok_or_else(|| nokey(name))?;
        let flds: &[FieldDecl] = match &d.kind {
            TypeKind::Struct(fs) => fs,
            TypeKind::Enum(vs) => {
                let v = variant.ok_or_else(|| format!("enum {} needs a variant", name))?;
                match vs.iter().find(|x| x.name == v) {
                    Some(x) => &x.fields,
                    None => return Err(format!("'{}::{}'", name, v)),
                }
            }
        };
        if d.tparams == 0 {
            return Ok(flds.iter().map(|fd| (fd.clone(), fd.ty.clone())).collect());
        }
        let m = gtype::bind_args(&gtype::decl_owner(name), d.tparams, ty.args()).map_err(|e| e.to_string())?;
        Ok(flds.iter().map(|fd| (fd.clone(), Ty::from_gtype(&gtype::substitute(&fd.ty.to_gtype(), &m)))).collect())
    }

    /// datatype of Option<X> / Result<X> / D<X..>, built once per complete structural type
    fn instance(&self, g: &GType) -> Result<Sort, String> {
        if let Some(s) = self.g.borrow().ginst.get(g) {
            return Ok(s.clone());
        }
        let n = greg_number(self.seq, g);
        let tag = format!("{}g{}!", self.pre_tag, n);
        let dtname = format!("{}{}", tag, gtype::format_type(g));
        let ty = Ty::from_gtype(g);
        let sort: Sort;
        if g.name == "option" {
            let ps = self.try_sort_of(&Ty::from_gtype(&g.args[0]))?;
            let spec = DtSpec {
                name: dtname,
                ctors: vec![
                    DtCtorSpec { name: format!("{}Some", tag), fields: vec![(format!("{}Some.val", tag), ps)] },
                    DtCtorSpec { name: format!("{}None", tag), fields: Vec::new() },
                ],
            };
            let mut dt = self.z.create_datatypes(&[spec]);
            let DtSort { sort: s, ctors } = dt.pop().ok_or("datatype")?;
            sort = s;
            self.g.borrow_mut().gopt.insert(
                g.clone(),
                OptOps {
                    some: ctors[0].ctor.clone(),
                    none: ctors[1].ctor.apply(&[]),
                    is_some: ctors[0].rec.clone(),
                    is_none: ctors[1].rec.clone(),
                    sval: ctors[0].accs[0].clone(),
                },
            );
            let mut st = self.g.borrow_mut();
            st.short.insert(format!("{}Some", tag), "Some");
            st.short.insert(format!("{}None", tag), "None");
        } else if g.name == "result" {
            let ps = self.try_sort_of(&Ty::from_gtype(&g.args[0]))?;
            let spec = DtSpec {
                name: dtname,
                ctors: vec![
                    DtCtorSpec { name: format!("{}Ok", tag), fields: vec![(format!("{}Ok.val", tag), ps)] },
                    DtCtorSpec {
                        name: format!("{}Err", tag),
                        fields: vec![(format!("{}Err.val", tag), self.int_sort.clone())],
                    },
                ],
            };
            let mut dt = self.z.create_datatypes(&[spec]);
            let DtSort { sort: s, ctors } = dt.pop().ok_or("datatype")?;
            sort = s;
            self.g.borrow_mut().gres.insert(
                g.clone(),
                ResOps {
                    ok: ctors[0].ctor.clone(),
                    err: ctors[1].ctor.clone(),
                    is_ok: ctors[0].rec.clone(),
                    is_err: ctors[1].rec.clone(),
                    oval: ctors[0].accs[0].clone(),
                    eval: ctors[1].accs[0].clone(),
                },
            );
            let mut st = self.g.borrow_mut();
            st.short.insert(format!("{}Ok", tag), "Ok");
            st.short.insert(format!("{}Err", tag), "Err");
        } else {
            let d = self.decl_opt(&g.name).ok_or_else(|| nokey(&g.name))?;
            match &d.kind {
                TypeKind::Struct(_) => {
                    let mut fl: Vec<(String, Sort)> = Vec::new();
                    for (fd, ft) in self.fields_of(&ty, None)? {
                        fl.push((format!("{}{}.{}", tag, d.name, fd.name), self.try_sort_of(&ft)?));
                    }
                    let nf = fl.len();
                    let cn = format!("{}{}", tag, d.name);
                    let spec = DtSpec { name: dtname, ctors: vec![DtCtorSpec { name: cn, fields: fl }] };
                    let mut dt = self.z.create_datatypes(&[spec]);
                    let DtSort { sort: s, mut ctors } = dt.pop().ok_or("datatype")?;
                    if ctors.is_empty() {
                        return Err("datatype".to_string());
                    }
                    let DtCtor { ctor, accs, .. } = ctors.remove(0);
                    debug_assert_eq!(accs.len(), nf);
                    sort = s;
                    self.g.borrow_mut().gstruct.insert(g.clone(), StructFns { ctor, accs });
                }
                TypeKind::Enum(variants) => {
                    let mut specs: Vec<DtCtorSpec> = Vec::new();
                    for v in variants {
                        let cn = format!("{}{}::{}", tag, d.name, v.name);
                        let mut fs: Vec<(String, Sort)> = Vec::new();
                        for (fd, ft) in self.fields_of(&ty, Some(&v.name))? {
                            fs.push((format!("{}.{}", cn, fd.name), self.try_sort_of(&ft)?));
                        }
                        specs.push(DtCtorSpec { name: cn, fields: fs });
                    }
                    let mut dt = self.z.create_datatypes(&[DtSpec { name: dtname, ctors: specs }]);
                    let DtSort { sort: s, ctors } = dt.pop().ok_or("datatype")?;
                    sort = s;
                    let fns: Vec<(String, VariantFns)> = variants
                        .iter()
                        .zip(ctors)
                        .map(|(v, c)| (v.name.clone(), VariantFns { ctor: c.ctor, rec: c.rec, accs: c.accs }))
                        .collect();
                    self.g.borrow_mut().genum.insert(g.clone(), fns);
                }
            }
        }
        self.g.borrow_mut().ginst.insert(g.clone(), sort.clone());
        self.by_sort.borrow_mut().insert(sort.name(), ty);
        Ok(sort)
    }

    /// Operations of the Option datatype of `ty` (None / `Option<i64>` = the legacy one).
    pub fn opt(&self, ty: Option<&Ty>) -> Result<OptOps, String> {
        match ty {
            None | Some(Ty::Opt) => Ok(self.opt_ops.clone()),
            Some(Ty::Inst(g)) if g.name == "option" => {
                self.instance(g)?;
                self.g.borrow().gopt.get(g).cloned().ok_or_else(|| nokey("option"))
            }
            Some(t) => Err(nokey(t.name())),
        }
    }

    /// Operations of the Result datatype of `ty` (None / `Result<i64>` = the legacy one).
    pub fn res(&self, ty: Option<&Ty>) -> Result<ResOps, String> {
        match ty {
            None | Some(Ty::Res) => Ok(self.res_ops.clone()),
            Some(Ty::Inst(g)) if g.name == "result" => {
                self.instance(g)?;
                self.g.borrow().gres.get(g).cloned().ok_or_else(|| nokey("result"))
            }
            Some(t) => Err(nokey(t.name())),
        }
    }

    /// `(constructor, [accessor per field])` of a struct type.
    pub fn struct_info(&self, ty: &Ty) -> Result<StructFns, String> {
        match ty {
            Ty::User(n) => self.structs.get(n).cloned().ok_or_else(|| nokey(n)),
            Ty::Inst(g) => {
                self.instance(g)?;
                self.g.borrow().gstruct.get(g).cloned().ok_or_else(|| nokey(&g.name))
            }
            other => Err(nokey(other.name())),
        }
    }

    /// `{variant: (constructor, recognizer, [accessor per field])}` of an enum type, in declaration order.
    pub fn enum_info(&self, ty: &Ty) -> Result<Vec<(String, VariantFns)>, String> {
        match ty {
            Ty::User(n) => self.enums.get(n).cloned().ok_or_else(|| nokey(n)),
            Ty::Inst(g) => {
                self.instance(g)?;
                self.g.borrow().genum.get(g).cloned().ok_or_else(|| nokey(&g.name))
            }
            other => Err(nokey(other.name())),
        }
    }

    /// One variant of an enum type.
    pub fn variant_fns(&self, ty: &Ty, variant: &str) -> Result<VariantFns, String> {
        let all = self.enum_info(ty)?;
        match all.into_iter().find(|(n, _)| n == variant) {
            Some((_, f)) => Ok(f),
            None => Err(nokey(variant)),
        }
    }

    /// `TypeTable.is_struct` / `is_enum`: struct, enum, or None (no such user declaration).
    pub fn nominal_kind(&self, ty: &Ty) -> Option<NomKind> {
        if !matches!(ty, Ty::User(_) | Ty::Inst(_)) {
            return None;
        }
        match &self.decl_opt(ty.name())?.kind {
            TypeKind::Struct(_) => Some(NomKind::Struct),
            TypeKind::Enum(_) => Some(NomKind::Enum),
        }
    }

    /// G3 (verify.py `Model.wf_trivial`): true when `wf(ty, v)` is None for every v (no i64 leaf and no Result
    /// error code inside). Cached per instance type, so the check is linear in the size of the type.
    pub fn wf_trivial(&self, ty: &Ty) -> Result<bool, String> {
        let key = match ty {
            Ty::Inst(g) => Some(g.clone()),
            _ => None,
        };
        if let Some(k) = &key {
            if let Some(r) = self.wf_triv.borrow().get(k) {
                return Ok(*r);
            }
        }
        let r = match ty {
            Ty::I64 | Ty::Opt | Ty::Res => false,
            Ty::Param(_) => true,
            Ty::Inst(g) if g.name == "result" => false,
            Ty::Inst(g) if g.name == "option" => self.wf_trivial(&Ty::from_gtype(&g.args[0]))?,
            // G9 A1: a recursive type has the wf_D definition (never trivially true here)
            Ty::User(n) if self.scc_of.contains_key(n) => false,
            Ty::User(_) | Ty::Inst(_) => match self.nominal_kind(ty) {
                Some(NomKind::Struct) => {
                    let mut all = true;
                    for (_, ft) in self.fields_of(ty, None)? {
                        if !self.wf_trivial(&ft)? {
                            all = false;
                            break;
                        }
                    }
                    all
                }
                Some(NomKind::Enum) => {
                    let mut all = true;
                    'outer: for vn in self.variant_names(ty) {
                        for (_, ft) in self.fields_of(ty, Some(&vn))? {
                            if !self.wf_trivial(&ft)? {
                                all = false;
                                break 'outer;
                            }
                        }
                    }
                    all
                }
                None => true,
            },
            _ => true,
        };
        if let Some(k) = key {
            self.wf_triv.borrow_mut().insert(k, r);
        }
        Ok(r)
    }

    /// The variant names of an enum type, in declaration order (empty for anything else).
    pub fn variant_names(&self, ty: &Ty) -> Vec<String> {
        match self.decl_opt(ty.name()).map(|d| &d.kind) {
            Some(TypeKind::Enum(vs)) => vs.iter().map(|v| v.name.clone()).collect(),
            _ => Vec::new(),
        }
    }

    /// `TypeTable.field_index(ty, name, variant)`.
    pub fn field_index_of(&self, ty: &Ty, field: &str, variant: Option<&str>) -> Result<usize, String> {
        let fs = self.fields_of(ty, variant)?;
        fs.iter().position(|(fd, _)| fd.name == field).ok_or_else(|| nokey(field))
    }

    /// `Model.try_sort_of` (Python `sort_of` raises `KeyError(name)` when there is no sort).
    pub fn try_sort_of(&self, ty: &Ty) -> Result<Sort, String> {
        match ty {
            Ty::I64 => Ok(self.int_sort.clone()),
            Ty::Bool => Ok(self.bool_sort.clone()),
            // G9 A1: a buffer field of a struct/enum (checked before the Opt/Res cases, like verify.py sort_of)
            Ty::Array(_) | Ty::Str => self.bufsort(ty),
            Ty::Opt => Ok(self.opt_sort.clone()),
            Ty::Res => Ok(self.res_sort.clone()),
            Ty::Param(g) => Ok(self.abstract_sort(g)),
            Ty::User(n) => self.sorts.get(n).cloned().ok_or_else(|| nokey(n)),
            Ty::Inst(g) => self.instance(g),
            Ty::Unit | Ty::GArray(_) => Err(nokey(ty.name())),
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
    /// `Model.is_user(ty)`: is this a user struct/enum type (generic applications included)?
    pub fn is_user(&self, ty: &Ty) -> bool {
        matches!(ty, Ty::User(_) | Ty::Inst(_)) && self.decl_opt(ty.name()).is_some()
    }
    /// `Model.type_of(v)`: finds the Pruv type from the sort name of a datatype value (None if absent).
    pub fn type_of(&self, v: &Ast) -> Option<Ty> {
        self.by_sort.borrow().get(&v.sort().name()).cloned()
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
    /// The variant functions of a non-generic enum (declaration order).
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

    #[test]
    fn structured_types_round_trip() {
        let g = gtype::mk_option(GType::bool());
        let t = Ty::from_name(&g.to_key());
        assert_eq!(t, Ty::Inst(g.clone()));
        assert_eq!(t.to_gtype(), g);
        assert_eq!(Ty::from_gtype(&GType::option()), Ty::Opt);
        let p = gtype::mk_param("fn:f", 0, "T");
        assert_eq!(Ty::from_name(&gtype::mk_array(p.clone()).to_key()), Ty::GArray(p));
    }
}
