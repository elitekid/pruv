//! verify.py 의 기호 실행 부품: `Arr`, `State`, `FnVerifier`(fresh, wf, rebuild, havoc, 집계, 양화 조각, ev 조각).
//!
//! 이 시제품에는 파서·AST 가 없으므로 `ev`/`exec` 전체가 아니라 표본 빌더가 부르는 "조각"만 있다.
//! 각 조각은 verify.py 의 해당 분기를 그대로 옮겼고 주석에 줄 번호를 단다. 호출 순서(= `s.k` 증가 순서,
//! 보조정리가 쌓이는 순서)는 빌더가 verify.py 의 평가 순서대로 부른다.

use std::collections::HashSet;

use crate::model::{Model, Prelude, Ty, TypeKind};
use crate::obligation::Trace;
use crate::sys::{Ast, FuncDecl, Sort, Z3};

/// (line, col), 1부터.
pub type Pos = (u32, u32);

/// verify.py 7행.
pub const MAX_LEN: i64 = 1 << 40;
/// verify.py 8행.
pub const TIMEOUT_MS: u32 = 8000;

/// verify.py `in_range` (168행).
pub fn in_range(z: &Z3, x: &Ast) -> Ast {
    z.and(&[x.raw_ge(&z.int(i64::MIN)), x.raw_le(&z.int(i64::MAX))])
}

/// verify.py `_conj` (72행): None 은 건너뛰고, 하나면 그대로, 둘 이상이면 And.
pub fn conj(z: &Z3, xs: Vec<Option<Ast>>) -> Option<Ast> {
    let xs: Vec<Ast> = xs.into_iter().flatten().collect();
    match xs.len() {
        0 => None,
        1 => Some(xs[0].clone()),
        _ => Some(z.and(&xs)),
    }
}

/// verify.py `_imp` (79행).
pub fn imp(c: &Ast, d: Option<Ast>) -> Option<Ast> {
    d.map(|d| c.implies(&d))
}

#[derive(Clone)]
pub struct Arr {
    pub a: Ast,
    pub n: Ast,
    pub name: String,
}

/// 환경 값. verify.py 는 z3 식의 sort 로 Int/Bool/Datatype 을 구분하지만 여기서는 태그로 든다.
#[derive(Clone)]
pub enum Val {
    Int(Ast),
    Bool(Ast),
    /// Opt/Res/사용자 struct·enum 값과 그 Pruv 타입(= `Model.type_of`).
    Dt(Ast, Ty),
    Arr(Arr),
}

impl Val {
    pub fn ast(&self) -> &Ast {
        match self {
            Val::Int(a) | Val::Bool(a) | Val::Dt(a, _) => a,
            Val::Arr(_) => panic!("array value has no single ast"),
        }
    }
    pub fn arr(&self) -> &Arr {
        match self {
            Val::Arr(a) => a,
            _ => panic!("not an array"),
        }
    }
}

/// 삽입 순서를 유지하는 환경(Python dict).
#[derive(Clone, Default)]
pub struct Env(pub Vec<(String, Val)>);

impl Env {
    pub fn get(&self, name: &str) -> &Val {
        self.try_get(name).unwrap_or_else(|| panic!("unbound variable {name}"))
    }
    pub fn try_get(&self, name: &str) -> Option<&Val> {
        self.0.iter().find(|(k, _)| k == name).map(|(_, v)| v)
    }
    /// dict 대입: 이미 있으면 자리를 유지한 채 값만 교체.
    pub fn set(&mut self, name: &str, v: Val) {
        if let Some(e) = self.0.iter_mut().find(|(k, _)| k == name) {
            e.1 = v;
        } else {
            self.0.push((name.to_string(), v));
        }
    }
}

#[derive(Clone)]
pub struct State {
    pub env: Env,
    pub pc: Vec<Ast>,
}

impl State {
    /// verify.py `State.fork` (146행).
    pub fn fork(&self, extra: Option<Ast>) -> State {
        let mut pc = self.pc.clone();
        if let Some(e) = extra {
            pc.push(e);
        }
        State { env: self.env.clone(), pc }
    }
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Arith {
    Add,
    Sub,
    Mul,
}

/// verify.py `FnVerifier`(189행). 함수마다 하나, `k`/`seen`/`aggs`/`lemmas` 는 함수 단위.
pub struct FnVerifier<'a> {
    pub z: Z3,
    pub prelude: &'a Prelude,
    pub model: &'a Model,
    pub trace: &'a mut Trace,
    pub fname: String,
    /// `s.k`
    pub k: u32,
    pub(crate) seen: HashSet<(u32, u32, String, Option<String>)>,
    pub qstack: Vec<Ast>,
    /// `s.aggs`: (kind, Tc.sexpr(), len(outer)) → F. 삽입 순서 유지(F 이름에 `len(aggs)` 가 들어간다).
    pub(crate) aggs: Vec<((String, String, usize), FuncDecl)>,
    pub lemmas: Vec<Ast>,
    /// `lemma_keys` 의 `(kind, F)` 항목
    pub(crate) lemma_fn_keys: HashSet<(String, String)>,
    /// `lemma_keys` 의 `L.sexpr()` 항목
    pub(crate) lemma_text_keys: HashSet<String>,
    /// `s.params`
    pub params: Env,
}

impl<'a> FnVerifier<'a> {
    pub fn new(z: &Z3, prelude: &'a Prelude, model: &'a Model, trace: &'a mut Trace, fname: &str) -> Self {
        FnVerifier {
            z: z.clone(),
            prelude,
            model,
            trace,
            fname: fname.to_string(),
            k: 0,
            seen: HashSet::new(),
            qstack: Vec::new(),
            aggs: Vec::new(),
            lemmas: Vec::new(),
            lemma_fn_keys: HashSet::new(),
            lemma_text_keys: HashSet::new(),
            params: Env::default(),
        }
    }

    // ---------- fresh (201행) ----------
    /// `fresh(base, ty)`: k 를 먼저 올린 뒤 이름 `base!k`; 배열 길이는 `base!k.len`.
    pub fn fresh(&mut self, base: &str, ty: &Ty) -> Val {
        self.k += 1;
        let n = format!("{}!{}", base, self.k);
        let z = &self.z;
        match ty {
            Ty::I64 => Val::Int(z.int_const(&n)),
            Ty::Bool => Val::Bool(z.bool_const(&n)),
            Ty::Opt => Val::Dt(z.constant(&n, &self.prelude.opt.sort), ty.clone()),
            Ty::Res => Val::Dt(z.constant(&n, &self.prelude.res.sort), ty.clone()),
            Ty::Array => {
                let int = z.int_sort();
                let arr_sort = z.array_sort(&int, &int);
                Val::Arr(Arr {
                    a: z.constant(&n, &arr_sort),
                    n: z.int_const(&format!("{}.len", n)),
                    name: base.to_string(),
                })
            }
            Ty::User(name) => Val::Dt(z.constant(&n, self.model.sort(name)), ty.clone()),
            Ty::Unit => panic!("fresh: unit"),
        }
    }
    pub fn fresh_int(&mut self, base: &str) -> Ast {
        self.fresh(base, &Ty::I64).ast().clone()
    }

    /// dom() 의 Quant 분기가 만드는 `!dk` 상수는 쓰이지 않아도 `s.k += 1` 은 일어난다(499행).
    pub fn bump_k(&mut self) {
        self.k += 1;
    }

    // ---------- value domain (219행) ----------
    /// `wf(ty, v)`: 활성 leaf 가 전부 i64. 자명하면 None.
    pub fn wf(&self, ty: &Ty, v: &Ast) -> Option<Ast> {
        let z = &self.z;
        let p = self.prelude;
        match ty {
            Ty::I64 => Some(in_range(z, v)),
            Ty::Opt => Some(p.is_some(v).implies(&in_range(z, &p.sval(v)))),
            Ty::Res => Some(z.and(&[
                p.is_ok(v).implies(&in_range(z, &p.oval(v))),
                p.is_err(v).implies(&in_range(z, &p.eval(v))),
            ])),
            Ty::User(name) => match &self.model.decl(name).kind {
                TypeKind::Struct(fields) => {
                    let accs = &self.model.struct_fns(name).accs;
                    conj(z, fields.iter().zip(accs).map(|(fd, acc)| self.wf(&fd.ty, &acc.apply1(v))).collect())
                }
                TypeKind::Enum(variants) => {
                    let mut parts: Vec<Option<Ast>> = Vec::new();
                    for vd in variants {
                        let vf = self.model.variant(name, &vd.name);
                        let w = conj(
                            z,
                            vd.fields.iter().zip(&vf.accs).map(|(fd, acc)| self.wf(&fd.ty, &acc.apply1(v))).collect(),
                        );
                        if let Some(w) = w {
                            parts.push(Some(vf.rec.apply1(v).implies(&w)));
                        }
                    }
                    conj(z, parts)
                }
            },
            Ty::Bool | Ty::Unit | Ty::Array => None,
        }
    }

    /// `rebuild(ty, cur, path, new)` (242행): struct 값 `cur` 의 필드 경로를 `new` 로 바꾼 값.
    pub fn rebuild(&self, ty: &Ty, cur: &Ast, path: &[&str], new: &Ast) -> Ast {
        if path.is_empty() {
            return new.clone();
        }
        let Ty::User(name) = ty else { panic!("rebuild on non-struct") };
        let i = self.model.field_index(name, path[0]);
        let sf = self.model.struct_fns(name);
        let fields = self.model.struct_fields(name);
        let mut vals: Vec<Ast> = sf.accs.iter().map(|a| a.apply1(cur)).collect();
        let sub = self.rebuild(&fields[i].ty, &vals[i], &path[1..], new);
        vals[i] = sub;
        sf.ctor.apply(&vals)
    }

    // ---------- run() 앞부분 (835행) ----------
    /// 매개변수마다 `fresh`, 배열은 `0 <= len <= MAX_LEN`, 그 밖은 `wf` 를 pc 에 넣는다. `self.params` 도 채운다.
    pub fn init_params(&mut self, params: &[(&str, Ty)]) -> State {
        let mut env = Env::default();
        let mut pc: Vec<Ast> = Vec::new();
        for (name, ty) in params {
            let v = self.fresh(name, ty);
            match &v {
                Val::Arr(a) => pc.push(self.z.and(&[a.n.ge_i(0), a.n.le_i(MAX_LEN)])),
                other => {
                    if let Some(w) = self.wf(ty, other.ast()) {
                        pc.push(w);
                    }
                }
            }
            env.set(name, v);
        }
        self.params = env.clone();
        State { env, pc }
    }

    /// `ensures_ok` 앞부분(647행): 현재 env 위에 매개변수 원래 값을 덮고 `result` 를 넣는다.
    pub fn ensures_env(&self, st: &State, result: Option<Val>) -> Env {
        let mut env = st.env.clone();
        for (n, v) in &self.params.0 {
            env.set(n, v.clone());
        }
        if let Some(r) = result {
            env.set("result", r);
        }
        env
    }

    // ---------- ev 조각 (code=True) ----------
    /// `assume(st, g, fact)` (340행).
    pub fn assume(&self, st: &mut State, g: &[Ast], fact: Ast) {
        if g.is_empty() {
            st.pc.push(fact);
        } else {
            st.pc.push(self.z.and(g).implies(&fact));
        }
    }

    /// Binary `+ - *` (361~385행): 결과를 만들고 `in_range(res)` 의무(code "overflow").
    pub fn ev_arith(&mut self, st: &State, g: &[Ast], op: Arith, l: &Ast, r: &Ast, node: Pos) -> Ast {
        let res = match op {
            Arith::Add => l.add(r),
            Arith::Sub => l.sub(r),
            Arith::Mul => l.mul(r),
        };
        let ob = in_range(&self.z, &res);
        self.prove(st, g, &ob, node, "overflow", None);
        res
    }

    /// Binary `/ %` (373~376행): 의무 `r > 0 && l >= 0` (code "div").
    pub fn ev_div(&mut self, st: &State, g: &[Ast], is_mod: bool, l: &Ast, r: &Ast, node: Pos) -> Ast {
        let ob = self.z.and(&[r.gt_i(0), l.ge_i(0)]);
        self.prove(st, g, &ob, node, "div", None);
        if is_mod {
            l.modulo(r)
        } else {
            l.div(r)
        }
    }

    /// Unary `-` (358~360행).
    pub fn ev_neg(&mut self, st: &State, g: &[Ast], v: &Ast, node: Pos) -> Ast {
        let ob = in_range(&self.z, &v.neg());
        self.prove(st, g, &ob, node, "overflow", None);
        v.neg()
    }

    /// Index (386~395행): 의무 `0 <= i < n` (code "index_oob"), 읽은 값의 `in_range` 를 pc 에 가정.
    pub fn ev_index(&mut self, st: &mut State, g: &[Ast], arr: &Arr, i: &Ast, node: Pos) -> Ast {
        let ob = self.z.and(&[i.ge_i(0), i.lt(&arr.n)]);
        self.prove(st, g, &ob, node, "index_oob", None);
        let v = arr.a.select(i);
        let w = in_range(&self.z, &v);
        self.assume(st, g, w);
        v
    }

    /// Call `alloc(n, init)` (609~613행). `args` = [n, init]. 의무 "alloc_negative" 뒤 `s.k += 1`.
    pub fn ev_alloc(&mut self, st: &State, g: &[Ast], n: &Ast, init: &Ast, node: Pos) -> Arr {
        let ob = self.z.and(&[n.ge_i(0), n.le_i(MAX_LEN)]);
        self.prove(st, g, &ob, node, "alloc_negative", None);
        self.k += 1;
        Arr { a: self.z.const_array(&self.z.int_sort(), init), n: n.clone(), name: "alloc".to_string() }
    }

    // ---------- exec 조각 (st 는 호출자가 이미 fork 한 상태) ----------
    /// IndexAssign (718~725행): 의무 `0 <= i < arr.n`("index_oob", node = 문장) 뒤 `Store`.
    pub fn index_assign(&mut self, st: &mut State, name: &str, i: &Ast, v: &Ast, node: Pos) {
        let arr = st.env.get(name).arr().clone();
        let ob = self.z.and(&[i.ge_i(0), i.lt(&arr.n)]);
        self.prove(st, &[], &ob, node, "index_oob", None);
        st.env.set(name, Val::Arr(Arr { a: arr.a.store(i, v), n: arr.n.clone(), name: name.to_string() }));
    }

    /// FieldAssign (761~766행): 오른쪽 값 `v` 는 호출자가 먼저 계산한다.
    pub fn field_assign(&mut self, st: &mut State, name: &str, path: &[&str], v: &Ast) {
        let Val::Dt(root, ty) = st.env.get(name).clone() else { panic!("field assign on non-struct") };
        let new = self.rebuild(&ty, &root, path, v);
        st.env.set(name, Val::Dt(new, ty));
    }

    /// check_dom 한 건 (524~543행): 정의역 `d` 가 None 이거나 `simplify(d)` 가 true 면 질의 없음,
    /// 아니면 `prove(.., code)` 하고 d 를 돌려준다(돌려준 것이 호출자의 `prev` 로 간다).
    pub fn check_dom_one(&mut self, st: &State, g: &[Ast], d: Option<Ast>, node: Pos, code: &str) -> Option<Ast> {
        let d = d?;
        if d.simplify().is_true() {
            return None;
        }
        self.prove(st, g, &d, node, code, None);
        Some(d)
    }

    // ---------- havoc (684행) ----------
    /// `names` 는 순서와 상관없이 받고, 안에서 이름순(바이트 순 = 코드포인트 순, Python `sorted`)으로 정렬해
    /// 순회한다(SPEC 6절의 0A 정렬을 API 에 넣음; fresh 이름의 `k` 증가 순서가 Python 과 같아진다).
    pub fn havoc(&mut self, st: &State, names: &[&str]) -> State {
        let mut h = st.fork(None);
        let mut sorted: Vec<&str> = names.to_vec();
        sorted.sort();
        for n in &sorted {
            let Some(old) = h.env.try_get(n).cloned() else { continue };
            match old {
                Val::Arr(_) => {
                    let Val::Arr(nv) = self.fresh(n, &Ty::Array) else { unreachable!() };
                    h.pc.push(self.z.and(&[nv.n.ge_i(0), nv.n.le_i(MAX_LEN)]));
                    h.env.set(n, Val::Arr(nv));
                }
                Val::Int(_) => {
                    let nv = self.fresh_int(n);
                    h.pc.push(in_range(&self.z, &nv));
                    h.env.set(n, Val::Int(nv));
                }
                Val::Bool(_) => {
                    let nv = self.fresh(n, &Ty::Bool);
                    h.env.set(n, nv);
                }
                Val::Dt(old_ast, ty) => {
                    // 집합값: `name!h{k}` 에서 k 는 증가 전 값을 쓰고 그 뒤에 올린다(701~702행).
                    let nv = self.z.constant(&format!("{}!h{}", n, self.k), &old_ast.sort());
                    self.k += 1;
                    h.env.set(n, Val::Dt(nv.clone(), ty.clone()));
                    if let Some(w) = self.wf(&ty, &nv) {
                        h.pc.push(w);
                    }
                }
            }
        }
        h
    }

    // ---------- 양화 조각 (401~417행) ----------
    /// Quant 평가 중간: lo/hi 를 먼저 평가한 뒤 `s.k += 1`, 상수 `var!q{k}`, qstack push. 본문 평가 뒤 `quant_exit`.
    pub fn quant_enter(&mut self, var: &str) -> Ast {
        self.k += 1;
        let k = self.z.int_const(&format!("{}!q{}", var, self.k));
        self.qstack.push(k.clone());
        k
    }
    pub fn quant_exit(&mut self) {
        self.qstack.pop();
    }
    /// `ForAll([k], Implies(And(k >= lo, k < hi), body))` — patterns 없음.
    pub fn forall_q(&self, k: &Ast, lo: &Ast, hi: &Ast, body: &Ast) -> Ast {
        let rng = self.z.and(&[k.ge(lo), k.lt(hi)]);
        self.z.forall(std::slice::from_ref(k), &rng.implies(body), &[])
    }
    /// `Exists([k], And(And(k >= lo, k < hi), body))`.
    pub fn exists_q(&self, k: &Ast, lo: &Ast, hi: &Ast, body: &Ast) -> Ast {
        let rng = self.z.and(&[k.ge(lo), k.lt(hi)]);
        self.z.exists(std::slice::from_ref(k), &self.z.and(&[rng, body.clone()]), &[])
    }

    // ---------- 집계 + 보조정리 (545~602행) ----------
    /// sum/count/max/min over lo<=k<hi 를 미해석 함수 `F(lo, hi, *outer)` 와 펼침 보조정리로 옮긴다.
    /// 호출 시점에 `qstack` 에는 이 집계의 자기 변수 `k` 가 이미 빠져 있어야 한다(`quant_exit` 뒤).
    pub fn aggregate(&mut self, kind: &str, k: &Ast, lo: &Ast, hi: &Ast, t: &Ast) -> Ast {
        let z = self.z.clone();
        let outer: Vec<Ast> = self.qstack.iter().filter(|c| t.occurs(c)).cloned().collect();
        let k0 = z.int_const("agg!k");
        let ps: Vec<Ast> = (0..outer.len()).map(|i| z.int_const(&format!("agg!p{}", i))).collect();

        let mut from = vec![k.clone()];
        let mut to = vec![k0.clone()];
        for (o, p) in outer.iter().zip(ps.iter()) {
            from.push(o.clone());
            to.push(p.clone());
        }
        let tc = t.substitute(&from, &to);
        let key = (kind.to_string(), tc.sexpr(), outer.len());

        let existing = self.aggs.iter().find(|(kk, _)| *kk == key).map(|(_, f)| f.clone());
        let f = match existing {
            Some(f) => f,
            None => {
                let int = z.int_sort();
                let dom: Vec<Sort> = (0..2 + outer.len()).map(|_| int.clone()).collect();
                let f = FuncDecl::new(&z, &format!("agg!{}{}", kind, self.aggs.len()), &dom, &int);
                self.aggs.push((key.clone(), f.clone()));
                f
            }
        };

        let body_at = |x: &Ast| -> Ast {
            let mut from = vec![k0.clone()];
            let mut to = vec![x.clone()];
            for (p, o) in ps.iter().zip(outer.iter()) {
                from.push(p.clone());
                to.push(o.clone());
            }
            tc.substitute(&from, &to)
        };
        let val = |x: &Ast| -> Ast {
            let b = body_at(x);
            if kind == "count" {
                z.ite(&b, &z.int(1), &z.int(0))
            } else {
                b
            }
        };
        // 더 작은 범위의 집계에 원소 x 를 붙인 값. `empty`: 작은 범위가 비어 있음.
        let comb = |smaller: &Ast, x: &Ast, empty: &Ast| -> Ast {
            if kind == "sum" || kind == "count" {
                z.ite(empty, &z.int(0), smaller).add(&val(x))
            } else {
                let better = if kind == "max" { smaller.ge(&val(x)) } else { smaller.le(&val(x)) };
                z.ite(empty, &val(x), &z.ite(&better, smaller, &val(x)))
            }
        };
        let fa = |a: &Ast, b: &Ast| -> Ast {
            let mut args = vec![a.clone(), b.clone()];
            args.extend(outer.iter().cloned());
            f.apply(&args)
        };

        let fk = (kind.to_string(), f.name().to_string());
        if !self.lemma_fn_keys.contains(&fk) {
            // 빈 범위: sum/count 는 0 (새 항을 만들지 않으므로 matching loop 없음)
            self.lemma_fn_keys.insert(fk);
            if kind == "sum" || kind == "count" {
                let x = z.int_const("agg!x");
                let y = z.int_const("agg!y");
                let os: Vec<Ast> = (0..outer.len()).map(|i| z.int_const(&format!("agg!o{}", i))).collect();
                let mut args = vec![x.clone(), y.clone()];
                args.extend(os.iter().cloned());
                let fapp = f.apply(&args);
                let mut bound = vec![x.clone(), y.clone()];
                bound.extend(os.iter().cloned());
                let body = y.le(&x).implies(&fapp.raw_eq(&z.int(0)));
                self.lemmas.push(z.forall(&bound, &body, &[fapp.clone()]));
            }
        }

        let app = fa(lo, hi);
        let mut facts: Vec<Ast> = Vec::new();
        if kind == "count" {
            facts.push(lo.lt(hi).implies(&z.and(&[app.ge_i(0), app.le(&hi.sub(lo))])));
        }
        let bound_lo = self.qstack.iter().any(|c| lo.occurs(c));
        let bound_hi = self.qstack.iter().any(|c| hi.occurs(c));
        // 끝을 하나만 옮겨 펼친다: 양화된 보조정리가 자기 출력에 다시 매치되지 않게.
        if !bound_hi {
            let hm1 = hi.sub_i(1);
            facts.push(lo.lt(hi).implies(&app.eq(&comb(&fa(lo, &hm1), &hm1, &hm1.le(lo)))));
            facts.push(lo.le(hi).implies(&fa(lo, &hi.add_i(1)).eq(&comb(&app, hi, &hi.le(lo)))));
        }
        if !bound_lo {
            let lp1 = lo.add_i(1);
            facts.push(lo.lt(hi).implies(&app.eq(&comb(&fa(&lp1, hi), lo, &hi.le(&lp1)))));
            let lm1 = lo.sub_i(1);
            facts.push(lo.le(hi).implies(&fa(&lm1, hi).eq(&comb(&app, &lm1, &hi.le(lo)))));
        }
        if !facts.is_empty() {
            let mut l = z.and(&facts);
            let bs: Vec<Ast> = self
                .qstack
                .iter()
                .filter(|c| outer.iter().any(|o| c.same(o)) || lo.occurs(c) || hi.occurs(c))
                .cloned()
                .collect();
            if !bs.is_empty() {
                l = z.forall(&bs, &l, std::slice::from_ref(&app));
            }
            let lk = l.sexpr();
            if self.lemma_text_keys.insert(lk) {
                self.lemmas.push(l);
            }
        }
        app
    }
}
