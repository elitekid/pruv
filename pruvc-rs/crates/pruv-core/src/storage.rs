//! Deterministic post-mono array storage analysis, matching storage.py.
//! Entries use stable keys. Node lookup requires the original unmoved AST;
//! cloned or synthesized nodes must use layout_key or parameter.
use crate::ast::*;
use crate::gtype::key_is_collection;
use crate::emit_common::is_spec_fn;
use std::collections::{HashMap, HashSet};

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub enum StorageKey {
    Param(String, usize), Result(String), Binding(String, usize), Expr(String, usize),
}
#[derive(Debug, Default)]
pub struct StoragePlan {
    pub entries: Vec<(StorageKey, &'static str)>,
    layouts: HashMap<StorageKey, &'static str>,
    objects: HashMap<(&'static str, usize), StorageKey>,
    params: HashMap<(String, String), StorageKey>,
}
impl StoragePlan {
    pub fn layout_of<T>(&self, node: &T) -> &'static str {
        self.objects.get(&(std::any::type_name::<T>(), node as *const T as usize)).map_or("i64", |k| self.layout_key(k))
    }
    pub fn contains_node<T>(&self, node: &T) -> bool {
        self.objects.contains_key(&(std::any::type_name::<T>(), node as *const T as usize))
    }
    pub fn layout_key(&self, key: &StorageKey) -> &'static str {
        self.layouts.get(key).copied().unwrap_or("i64")
    }
    pub fn parameter(&self, function: &str, name: &str) -> &'static str {
        self.params.get(&(function.into(), name.into())).map_or("i64", |k| self.layout_key(k))
    }
}
pub fn range_layout(lo: i128, hi: i128) -> &'static str {
    for (bits, u, i) in [(8, "u8", "i8"), (16, "u16", "i16"), (32, "u32", "i32")] {
        if lo >= 0 && hi < 1i128 << bits { return u; }
        if lo < 0 && -(1i128 << (bits - 1)) <= lo && hi < 1i128 << (bits - 1) { return i; }
    }
    "i64"
}
pub fn elem_size(layout: &str) -> usize { layout[1..].parse::<usize>().expect("storage width") / 8 }
pub fn alignment(layout: &str) -> usize { elem_size(layout) }

type Slot = Option<usize>;
type Scope = HashMap<String, Slot>;
struct Analysis {
    out: StoragePlan, keys: Vec<StorageKey>, lookup: HashMap<StorageKey, usize>,
    parent: Vec<usize>, bounds: Vec<Option<(i128, i128)>>, pinned: Vec<bool>,
    verified: bool, functions: HashSet<String>, function: String, sn: usize, en: usize,
}
impl Analysis {
    fn node<T>(&mut self, key: StorageKey, obj: &T, refine: Option<&Refinement>, declaration: bool, pin: bool) -> usize {
        let b = refine.filter(|r| r.base == "i64").and_then(|r| {
            Some((r.lo.as_ref()?.parse().ok()?, r.hi.as_ref()?.parse().ok()?))
        });
        let n = self.keys.len();
        self.keys.push(key.clone()); self.parent.push(n); self.lookup.insert(key.clone(), n);
        self.bounds.push(b); self.pinned.push(pin || !self.verified || (declaration && b.is_none()));
        self.out.objects.insert((std::any::type_name::<T>(), obj as *const T as usize), key);
        n
    }
    fn root(&mut self, mut i: usize) -> usize {
        while self.parent[i] != i { self.parent[i] = self.parent[self.parent[i]]; i = self.parent[i]; } i
    }
    fn pin(&mut self, n: Slot) { if let Some(n) = n { self.pinned[n] = true; } }
    fn join(&mut self, a: Slot, b: Slot) {
        if let (Some(a), Some(b)) = (a,b) {
            let a = self.root(a); let b = self.root(b); self.parent[a.max(b)] = a.min(b);
        } else { self.pin(a); self.pin(b); }
    }
    fn expr(&mut self, e: &Expr, scope: &Scope) -> Slot {
        let number = self.en; self.en += 1;
        let n = if expr_ty(e).as_deref() == Some("array") {
            Some(self.node(StorageKey::Expr(self.function.clone(), number), e, None, false, false))
        } else { None };
        let children: Vec<Slot> = crate::refine::kids(e).into_iter().map(|c| self.expr(c, scope)).collect();
        match e {
            Expr::Var(x) => { if n.is_some() { self.join(n, scope.get(&x.name).copied().flatten()); } }
            Expr::Move(x) => { if n.is_some() { self.join(n, scope.get(&x.name).copied().flatten()); } }
            Expr::InoutArg(_) => { self.pin(children[0]); if n.is_some() { self.join(n, children[0]); } }
            Expr::Call(x) => match x.name.as_str() {
                "copy" | "truncate" | "old" => { if n.is_some() { self.join(n, children[0]); } }
                "alloc" => {},
                name if self.functions.contains(name) => {
                    for (j, c) in children.iter().enumerate() { if c.is_some() {
                        self.join(*c, self.lookup.get(&StorageKey::Param(name.into(), j)).copied());
                    } }
                    if n.is_some() { self.join(n, self.lookup.get(&StorageKey::Result(name.into())).copied()); }
                }
                "len" => {},
                _ => { self.pin(n); for c in children { self.pin(c); } }
            },
            Expr::Index(_) | Expr::Quant(_) | Expr::Unary(_) | Expr::IntLit(_) | Expr::BoolLit(_) | Expr::StrLit(_) => self.pin(n),
            _ => { self.pin(n); for c in children { self.pin(c); } }
        }
        n
    }
    fn block(&mut self, stmts: &[Stmt], outer: &Scope) {
        let mut scope = outer.clone();
        for st in stmts {
            let number = self.sn; self.sn += 1;
            match st {
                Stmt::Let(x) => {
                    let n = if x.ty == "array" { Some(self.node(StorageKey::Binding(self.function.clone(), number), x, x.refine.as_ref(), true, false)) } else { None };
                    let v = self.expr(&x.value, &scope);
                    if n.is_some() || v.is_some() { self.join(n,v); }
                    scope.insert(x.name.clone(), n);
                }
                Stmt::Assign(x) => {
                    let v = self.expr(&x.value, &scope); let n = scope.get(&x.name).copied().flatten();
                    if n.is_some() || v.is_some() { self.join(n,v); }
                }
                Stmt::Return(x) => { if let Some(e) = &x.value {
                    let v = self.expr(e, &scope); if v.is_some() { self.join(v, self.lookup.get(&StorageKey::Result(self.function.clone())).copied()); }
                } }
                Stmt::IndexAssign(x) => {
                    if let Some(n) = scope.get(&x.name).copied().flatten() { self.out.objects.insert((std::any::type_name::<IndexAssign>(), x as *const IndexAssign as usize), self.keys[n].clone()); }
                    self.expr(&x.index, &scope); self.expr(&x.value, &scope);
                }
                Stmt::If(x) => { self.expr(&x.cond, &scope); self.block(&x.then, &scope); self.block(&x.els, &scope); }
                Stmt::While(x) => { self.expr(&x.cond, &scope); for inv in &x.invariants { self.expr(inv, &scope); } self.expr(&x.decreases, &scope); self.block(&x.body, &scope); }
                Stmt::Assert(x) => { self.expr(&x.cond, &scope); }
                Stmt::ExprStmt(x) => { self.expr(&x.expr, &scope); }
                Stmt::FieldAssign(x) => { let v = self.expr(&x.value, &scope); self.pin(v); }
                Stmt::Par(x) => { for c in &x.calls { self.expr(c, &scope); } }
                Stmt::Match(x) => { self.expr(&x.scrutinee, &scope); for arm in &x.arms {
                    let mut inner = scope.clone(); for name in &arm.binders { inner.insert(name.clone(), None); } self.block(&arm.body, &inner);
                } }
            }
        }
    }
}
pub fn plan_storage(prog: &Program, verified: bool) -> StoragePlan {
    let mut a = Analysis { out: StoragePlan::default(), keys: vec![], lookup: HashMap::new(), parent: vec![], bounds: vec![], pinned: vec![], verified,
        functions: prog.functions.iter().map(|f| f.name.clone()).collect(), function: String::new(), sn: 0, en: 0 };
    let extended = |t: &str| prog.g9.as_ref().map_or(false, |g| g.extended.iter().any(|x| x == t));
    for (i, f) in prog.functions.iter().enumerate() {
        let private = is_spec_fn(&f.name) || f.params.iter().any(|p| key_is_collection(&p.ty) || extended(&p.ty) || p.mode_pos.is_some()) || key_is_collection(&f.ret) || extended(&f.ret);
        let host = prog.explicit.as_ref().map_or(!private, |e| e.fns[i].host_entry);
        for (j,p) in f.params.iter().enumerate() { if p.ty == "array" {
            let key = StorageKey::Param(f.name.clone(), j);
            a.node(key.clone(), p, p.refine.as_ref(), true, host || p.mode_pos.is_some() || f.foreign.is_some());
            a.out.params.insert((f.name.clone(), p.name.clone()), key);
        } }
        if f.ret == "array" { a.node(StorageKey::Result(f.name.clone()), f, f.ret_refine.as_ref(), true, host || f.foreign.is_some()); }
    }
    for f in &prog.functions {
        a.function = f.name.clone(); a.sn = 0; a.en = 0;
        let env: Scope = f.params.iter().enumerate().map(|(j,p)| (p.name.clone(), a.lookup.get(&StorageKey::Param(f.name.clone(), j)).copied())).collect();
        for e in &f.requires { a.expr(e, &env); }
        let mut renv = env.clone(); renv.insert("result".into(), a.lookup.get(&StorageKey::Result(f.name.clone())).copied());
        for e in &f.ensures { a.expr(e, &renv); }
        a.block(&f.body, &env);
    }
    let mut ranges: HashMap<usize, (i128,i128)> = HashMap::new(); let mut pins = HashSet::new();
    for i in 0..a.keys.len() {
        let r = a.root(i); if a.pinned[i] { pins.insert(r); }
        if let Some((lo,hi)) = a.bounds[i] { ranges.entry(r).and_modify(|b| { b.0 = b.0.min(lo); b.1 = b.1.max(hi); }).or_insert((lo,hi)); }
    }
    for i in 0..a.keys.len() {
        let r = a.root(i); let width = if pins.contains(&r) { "i64" } else { ranges.get(&r).map_or("i64", |&(lo,hi)| range_layout(lo,hi)) };
        a.out.entries.push((a.keys[i].clone(), width)); a.out.layouts.insert(a.keys[i].clone(), width);
    }
    a.out
}

fn expr_ty(e: &Expr) -> &Option<String> {
    match e {
        Expr::Spent(x) => &x.ty,
        Expr::IntLit(x) => &x.ty,
        Expr::BoolLit(x) => &x.ty,
        Expr::StrLit(x) => &x.ty,
        Expr::Var(x) => &x.ty,
        Expr::Unary(x) => &x.ty,
        Expr::Binary(x) => &x.ty,
        Expr::Call(x) => &x.ty,
        Expr::Index(x) => &x.ty,
        Expr::Ctor(x) => &x.ty,
        Expr::Quant(x) => &x.ty,
        Expr::StructLit(x) => &x.ty,
        Expr::EnumCtor(x) => &x.ty,
        Expr::FieldAccess(x) => &x.ty,
        Expr::IsVariant(x) => &x.ty,
        Expr::VariantField(x) => &x.ty,
        Expr::Move(x) => &x.ty,
        Expr::InoutArg(x) => &x.ty,
    }
}

