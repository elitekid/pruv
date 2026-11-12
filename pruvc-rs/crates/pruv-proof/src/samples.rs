//! Builders that hand-port the obligations verify.py would produce for the 6 sample .pruv files (`samples/`).
//!
//! Since there is no parser, each builder follows verify.py's evaluation order (`run` → `exec` → `loop` → `ensures_ok`)
//! and calls `FnVerifier` pieces. That order determines `s.k` (the number in names) and the lemma accumulation order.
//! Positions (line, col) are based on the `samples/*.pruv` source and equal the node positions verify.py passes to `prove`:
//! Binary is the operator token, Index is `[`, Call is the name, a statement is its first token, invariant/decreases/requires are the top-level node of the expression.
//!
//! Assumptions (also noted in the README):
//! - The havoc variable order uses the 0A sorting (by name) from SPEC §6. Python iterated a set, but it was decided to sort in 0A.
//! - Each sample starts with a fresh context and `_MODEL_SEQ=0` (assuming the Python adapter uses a new process per file).

use serde_json::Value;

use crate::model::{reset_model_seq, Model, Prelude, Ty, TypeDecl};
use crate::obligation::{trace_json, Trace};
use crate::symbolic::{Arith, Arr, FnVerifier, State, Val};
use crate::sys::{Ast, Z3};

type SampleFn = fn(&Z3, &Prelude, &mut Trace);

/// (name, builder). The source is `samples/{name}.pruv`.
pub const SAMPLES: &[(&str, SampleFn)] = &[
    ("s1_sum_loop", s1_sum_loop),
    ("s2_agg_max_count", s2_agg_max_count),
    ("s3_option_result", s3_option_result),
    ("s4_struct_enum", s4_struct_enum),
    ("s5_nested_quant", s5_nested_quant),
    ("s6_alloc_loop", s6_alloc_loop),
];

pub fn sample_names() -> Vec<&'static str> {
    SAMPLES.iter().map(|(n, _)| *n).collect()
}

/// Runs one sample in a fresh context and builds the trace JSON. None if the name is unknown.
pub fn run_sample(name: &str) -> Option<Value> {
    let (_, build) = SAMPLES.iter().find(|(n, _)| *n == name)?;
    reset_model_seq();
    let z = Z3::new();
    let pre = Prelude::new(&z);
    let mut trace = Trace::default();
    build(&z, &pre, &mut trace);
    Some(trace_json(name, &trace, &crate::z3_full_version()))
}

fn int_of(st: &State, name: &str) -> Ast {
    st.env.get(name).ast().clone()
}

/// `0 <= i && i <= n` (And(IntVal(0) <= i, i <= n))
fn inv_range(z: &Z3, i: &Ast, n: &Ast) -> Ast {
    z.and(&[z.int(0).le(i), i.le(n)])
}

/// `sum(k in 0..hi: k)` — Quant evaluation: lo/hi are already evaluated → `s.k += 1`, body `k`, aggregate.
fn sum_k(v: &mut FnVerifier, hi: &Ast) -> Ast {
    let lo = v.z.int(0);
    let k = v.quant_enter("k");
    let body = k.clone();
    v.quant_exit();
    v.aggregate("sum", &k, &lo, hi, &body)
}

// =============================================================================================
// s1_sum_loop: tri — sum aggregate + lemmas retry (first attempt sat → lemmas unsat), while-loop havoc (Int)
// =============================================================================================
fn s1_sum_loop(z: &Z3, pre: &Prelude, trace: &mut Trace) {
    let model = Model::new(z, pre, &[]);
    let mut v = FnVerifier::new(z, pre, &model, trace, "tri");

    // run(): parameter n → `n!1`
    let mut st = v.init_params(&[("n", Ty::I64)]);
    let n = int_of(&st, "n");
    // requires n >= 0 && n <= 1_000   (no partial operations → no domain queries)
    st.pc.push(z.and(&[n.ge_l(0), n.le_l(1000)]));

    // let mut s: i64 = 0;  let mut i: i64 = 0;
    st.env.set("s", Val::Int(z.int(0)));
    st.env.set("i", Val::Int(z.int(0)));

    // ---- while (7,3): loop() ----
    // Entry: evaluate each invariant and prove invariant_entry
    let i0 = int_of(&st, "i");
    let s0 = int_of(&st, "s");
    let ob = inv_range(z, &i0, &n);
    v.prove(&st, &[], &ob, (8, 22), "invariant_entry", None);
    let app = sum_k(&mut v, &i0);
    let ob = s0.eq(&app); // s == sum(k in 0..i: k)
    v.prove(&st, &[], &ob, (9, 17), "invariant_entry", None);

    // names = assigned(body) = {i, s} (sorted)
    let mut b = v.havoc(&st, &["i", "s"]); // i!3, s!4
    let (bi, bs) = (int_of(&b, "i"), int_of(&b, "s"));
    b.pc.push(inv_range(z, &bi, &n));
    let app = sum_k(&mut v, &bi);
    b.pc.push(bs.eq(&app));
    b.pc.push(bi.lt(&n)); // condition i < n
    let d0 = n.sub(&bi); // decreases n - i (code=False: no obligation)
    v.prove(&b, &[], &d0.ge_i(0), (10, 17), "decreases_nonneg", None);

    // Body: s = s + i;  i = i + 1;
    let mut e = b.fork(None);
    let (s_old, i_old) = (int_of(&e, "s"), int_of(&e, "i"));
    let res = v.ev_arith(&e, &[], Arith::Add, &s_old, &i_old, (12, 11));
    e.env.set("s", Val::Int(res));
    let mut e = e.fork(None);
    let i_old = int_of(&e, "i");
    let one = z.int(1);
    let res = v.ev_arith(&e, &[], Arith::Add, &i_old, &one, (13, 11));
    e.env.set("i", Val::Int(res));

    // End of body: invariant preserved
    let (ei, es) = (int_of(&e, "i"), int_of(&e, "s"));
    let ob = inv_range(z, &ei, &n);
    v.prove(&e, &[], &ob, (8, 22), "invariant_preserved", None);
    let app = sum_k(&mut v, &ei);
    let ob = es.eq(&app);
    v.prove(&e, &[], &ob, (9, 17), "invariant_preserved", None);
    let dn = n.sub(&ei);
    v.prove(&e, &[], &dn.lt(&d0), (10, 17), "decreases_decrease", None);

    // After the loop
    let mut a = v.havoc(&st, &["i", "s"]); // i!7, s!8
    let (ai, asv) = (int_of(&a, "i"), int_of(&a, "s"));
    a.pc.push(inv_range(z, &ai, &n));
    let app = sum_k(&mut v, &ai);
    a.pc.push(asv.eq(&app));
    a.pc.push(ai.lt(&n).not());

    // return s;  (15,3) → ensures_ok: result == sum(k in 0..n: k)
    let r = a.fork(None);
    let rv = int_of(&r, "s");
    let env = v.ensures_env(&r, Some(Val::Int(rv)));
    let result = env.get("result").ast().clone();
    let hi = env.get("n").ast().clone();
    let app = sum_k(&mut v, &hi);
    v.prove(&r, &[], &result.eq(&app), (15, 3), "ensures", None);
}

// =============================================================================================
// s2_agg_max_count: bounds — max/count/min aggregates, contract_domain of max/min, lemmas retry (unsat/sat)
// =============================================================================================
fn s2_agg_max_count(z: &Z3, pre: &Prelude, trace: &mut Trace) {
    let model = Model::new(z, pre, &[]);
    let mut v = FnVerifier::new(z, pre, &model, trace, "bounds");

    let mut st = v.init_params(&[("n", Ty::I64)]); // n!1
    let n = int_of(&st, "n");
    st.pc.push(z.and(&[n.ge_l(1), n.le_l(100)])); // requires n >= 1 && n <= 100

    // return n;  (7,3)
    let st = st.fork(None);
    let rv = int_of(&st, "n");
    let env = v.ensures_env(&st, Some(Val::Int(rv)));
    let n = env.get("n").ast().clone();
    let node = (7, 3);
    let mut prev: Vec<Ast> = Vec::new();

    // ensures max(k in 0..n: k) >= 0
    {
        // check_dom: dom(Quant max) = [lo < hi] (+ k incremented via the `!dk` constant), no body domain
        let lo = z.int(0);
        let d = lo.lt(&n);
        v.bump_k();
        if let Some(d) = v.check_dom_one(&st, &prev, Some(d), node, "contract_domain") {
            prev.push(d);
        }
        let k = v.quant_enter("k");
        let body = k.clone();
        v.quant_exit();
        let app = v.aggregate("max", &k, &lo, &n, &body);
        let ob = app.ge_l(0);
        v.prove(&st, &[], &ob, node, "ensures", None);
        prev.push(ob);
    }
    // ensures count(k in 0..n: k >= 0) <= n   (no domain queries)
    {
        let lo = z.int(0);
        let k = v.quant_enter("k");
        let body = k.ge_l(0);
        v.quant_exit();
        let app = v.aggregate("count", &k, &lo, &n, &body);
        let ob = app.le(&n);
        v.prove(&st, &[], &ob, node, "ensures", None);
        prev.push(ob);
    }
    // ensures min(k in 0..n: k) >= 1   (counterexample sample: if n = 1 then min = 0)
    {
        let lo = z.int(0);
        let d = lo.lt(&n);
        v.bump_k();
        if let Some(d) = v.check_dom_one(&st, &prev, Some(d), node, "contract_domain") {
            prev.push(d);
        }
        let k = v.quant_enter("k");
        let body = k.clone();
        v.quant_exit();
        let app = v.aggregate("min", &k, &lo, &n, &body);
        let ob = app.ge_l(1);
        v.prove(&st, &[], &ob, node, "ensures", None);
    }
}

// =============================================================================================
// s3_option_result: Opt/Res Datatype — constructors, recognizers, accessors (match), mix of proofs/counterexamples
// =============================================================================================
fn s3_option_result(z: &Z3, pre: &Prelude, trace: &mut Trace) {
    let model = Model::new(z, pre, &[]);

    // ---- fn safe_div(a, b) -> Result<i64> ----
    {
        let mut v = FnVerifier::new(z, pre, &model, trace, "safe_div");
        let mut st = v.init_params(&[("a", Ty::I64), ("b", Ty::I64)]); // a!1, b!2
        let (a, b) = (int_of(&st, "a"), int_of(&st, "b"));
        st.pc.push(z.and(&[a.ge_l(0), a.le_l(1_000_000)]));
        st.pc.push(z.and(&[b.ge_l(0), b.le_l(1_000_000)]));

        // if b == 0 { return Err(1); }
        let st = st.fork(None);
        let c = b.eq(&z.int(0));
        {
            let t = st.fork(Some(c.clone())).fork(None); // then block, Return forks again
            let val = pre.err(&z.int(1));
            safe_div_ensures(&mut v, pre, &t, val, (7, 5));
        }
        // return Ok(a / b);   else path
        let r = st.fork(Some(c.not())).fork(None);
        let q = v.ev_div(&r, &[], false, &a, &b, (9, 15));
        let val = pre.ok(&q);
        safe_div_ensures(&mut v, pre, &r, val, (9, 3));
    }

    // ---- fn first_pos(x, y) -> Option<i64> ----
    {
        let mut v = FnVerifier::new(z, pre, &model, trace, "first_pos");
        let st = v.init_params(&[("x", Ty::I64), ("y", Ty::I64)]);
        let (x, y) = (int_of(&st, "x"), int_of(&st, "y"));
        let c = x.gt_l(0);
        // if x > 0 { return Some(x); }
        let t = st.fork(Some(c.clone())).fork(None);
        first_pos_ensures(&mut v, pre, &t, pre.some(&x), (16, 5));
        // return Some(y);
        let r = st.fork(Some(c.not())).fork(None);
        first_pos_ensures(&mut v, pre, &r, pre.some(&y), (18, 3));
    }

    // ---- fn unwrap_or(o, d) -> i64 ----
    {
        let mut v = FnVerifier::new(z, pre, &model, trace, "unwrap_or");
        let st = v.init_params(&[("o", Ty::Opt), ("d", Ty::I64)]); // o!1, d!2
        let o = st.env.get("o").ast().clone();
        // match o { Some(x) => { return x; }  None => { return d; } }
        let st = st.fork(None);
        {
            // arm Some(x): cond = is_some(o), binder x = sval(o), wf(I64, x)
            let val = pre.sval(&o);
            let mut b = st.fork(Some(pre.is_some(&o)));
            b.env.set("x", Val::Int(val));
            let xv = b.env.get("x").ast().clone();
            if let Some(w) = v.wf(&Ty::I64, &xv) {
                b.pc.push(w);
            }
            let r = b.fork(None);
            let rv = int_of(&r, "x");
            unwrap_or_ensures(&mut v, pre, &r, rv, (25, 18));
        }
        {
            // arm None: cond = is_none(o)
            let b = st.fork(Some(pre.is_none(&o)));
            let r = b.fork(None);
            let rv = int_of(&r, "d");
            unwrap_or_ensures(&mut v, pre, &r, rv, (26, 15));
        }
    }
}

/// ensures is_ok(result) ==> b > 0
fn safe_div_ensures(v: &mut FnVerifier, pre: &Prelude, st: &State, result: Ast, node: (u64, u32)) {
    let env = v.ensures_env(st, Some(Val::Dt(result, Ty::Res)));
    let (res, b) = (env.get("result").ast().clone(), env.get("b").ast().clone());
    let ob = pre.is_ok(&res).implies(&b.gt_l(0));
    v.prove(st, &[], &ob, node, "ensures", None);
}

/// ensures is_some(result) ==> x > 0
fn first_pos_ensures(v: &mut FnVerifier, pre: &Prelude, st: &State, result: Ast, node: (u64, u32)) {
    let env = v.ensures_env(st, Some(Val::Dt(result, Ty::Opt)));
    let (res, x) = (env.get("result").ast().clone(), env.get("x").ast().clone());
    let ob = pre.is_some(&res).implies(&x.gt_l(0));
    v.prove(st, &[], &ob, node, "ensures", None);
}

/// ensures !is_some(o) ==> result == d
fn unwrap_or_ensures(v: &mut FnVerifier, pre: &Prelude, st: &State, result: Ast, node: (u64, u32)) {
    let env = v.ensures_env(st, Some(Val::Int(result)));
    let (res, o, d) = (
        env.get("result").ast().clone(),
        env.get("o").ast().clone(),
        env.get("d").ast().clone(),
    );
    let ob = pre.is_some(&o).not().implies(&res.eq(&d));
    v.prove(st, &[], &ob, node, "ensures", None);
}

// =============================================================================================
// s4_struct_enum: user struct/enum Datatypes (m1t0!Point, m1t1!Shape), variant_domain, match arms,
//                 field assignment (rebuild), set values of loop havoc (`q!h{k}`)
// =============================================================================================
fn s4_struct_enum(z: &Z3, pre: &Prelude, trace: &mut Trace) {
    let point = Ty::User("Point".to_string());
    let shape = Ty::User("Shape".to_string());
    let no_fields: &[(&str, Ty)] = &[];
    let circle_fields: &[(&str, Ty)] = &[("r", Ty::I64)];
    let rect_fields: &[(&str, Ty)] = &[("p", point.clone()), ("w", Ty::I64)];
    let decls = vec![
        TypeDecl::new_struct("Point", &[("x", Ty::I64), ("y", Ty::I64)]),
        TypeDecl::new_enum(
            "Shape",
            &[("Empty", no_fields), ("Circle", circle_fields), ("Rect", rect_fields)],
        ),
    ];
    let model = Model::new(z, pre, &decls);

    // ---- fn area(s: Shape) -> i64 ----
    {
        let mut v = FnVerifier::new(z, pre, &model, trace, "area");
        let mut st = v.init_params(&[("s", shape.clone())]); // s!1
        let s = st.env.get("s").ast().clone();
        let circle = model.variant("Shape", "Circle");
        let rec_c = circle.rec.apply1(&s);
        let acc_r = circle.accs[0].apply1(&s);

        // requires is_variant(s, Shape::Circle) ==> (vf >= 0 && vf <= 1_000)   node = `==>` (13,41)
        //   D = Implies(rec, And(rec, Implies(vf >= 0, rec)))   (dom(.., "variant"); see the README for the domain analysis)
        let ge0 = acc_r.ge_l(0);
        let le1000 = acc_r.le_l(1000);
        let d = rec_c.implies(&z.and(&[rec_c.clone(), ge0.implies(&rec_c)]));
        v.check_dom_one(&st, &[], Some(d.clone()), (13, 41), "variant_domain");
        st.pc.push(d); // dom(r, "variant") into pc
        st.pc.push(rec_c.implies(&z.and(&[ge0.clone(), le1000]))); // value

        // match s { ... }
        let st = st.fork(None);
        // arm Shape::Empty
        {
            let empty = model.variant("Shape", "Empty");
            let b = st.fork(Some(empty.rec.apply1(&s)));
            let r = b.fork(None);
            let env = v.ensures_env(&r, Some(Val::Int(z.int(0))));
            let ob = env.get("result").ast().ge_l(0);
            v.prove(&r, &[], &ob, (17, 23), "ensures", None);
        }
        // arm Shape::Circle(r)
        {
            let mut b = st.fork(Some(rec_c.clone()));
            b.env.set("r", Val::Int(acc_r.clone()));
            let rv = int_of(&b, "r");
            if let Some(w) = v.wf(&Ty::I64, &rv) {
                b.pc.push(w);
            }
            let r2 = b.fork(None);
            let rr = int_of(&r2, "r");
            let res = v.ev_arith(&r2, &[], Arith::Add, &rr, &z.int(1), (18, 36));
            let env = v.ensures_env(&r2, Some(Val::Int(res)));
            let ob = env.get("result").ast().ge_l(0);
            v.prove(&r2, &[], &ob, (18, 27), "ensures", None);
        }
        // arm Shape::Rect(p, w)
        {
            let rect = model.variant("Shape", "Rect");
            let mut b = st.fork(Some(rect.rec.apply1(&s)));
            b.env.set("p", Val::Dt(rect.accs[0].apply1(&s), point.clone()));
            let pv = b.env.get("p").ast().clone();
            if let Some(w) = v.wf(&point, &pv) {
                b.pc.push(w);
            }
            b.env.set("w", Val::Int(rect.accs[1].apply1(&s)));
            let wv = int_of(&b, "w");
            if let Some(w) = v.wf(&Ty::I64, &wv) {
                b.pc.push(w);
            }
            let r2 = b.fork(None);
            let rv = int_of(&r2, "w");
            let env = v.ensures_env(&r2, Some(Val::Int(rv)));
            let ob = env.get("result").ast().ge_l(0);
            v.prove(&r2, &[], &ob, (19, 28), "ensures", None); // counterexample sample
        }
    }

    // ---- fn walk(p: Point, n: i64) -> Point ----
    {
        let mut v = FnVerifier::new(z, pre, &model, trace, "walk");
        let mut st = v.init_params(&[("p", point.clone()), ("n", Ty::I64)]); // p!1, n!2
        let (p, n) = (int_of(&st, "p"), int_of(&st, "n"));
        st.pc.push(z.and(&[n.ge_l(0), n.le_l(1000)])); // requires n >= 0 && n <= 1_000
        let sf = model.struct_fns("Point");
        let (acc_x, acc_y) = (&sf.accs[0], &sf.accs[1]);

        // let mut q: Point = p;  let mut i: i64 = 0;
        st.env.set("q", Val::Dt(p.clone(), point.clone()));
        st.env.set("i", Val::Int(z.int(0)));

        // ---- while (29,3) ----
        // Entry
let i0 = int_of(&st, "i");
        v.prove(&st, &[], &inv_range(z, &i0, &n), (30, 22), "invariant_entry", None);
        let q0 = int_of(&st, "q");
        let ob = acc_y.apply1(&q0).eq(&acc_y.apply1(&p)); // q.y == p.y
        v.prove(&st, &[], &ob, (31, 19), "invariant_entry", None);

        // havoc for the body: i → `i!3` (Int), q → `q!h3` (set value; the name uses the value of k before incrementing)
        let mut b = v.havoc(&st, &["i", "q"]);
        let (bi, bq) = (int_of(&b, "i"), int_of(&b, "q"));
        b.pc.push(inv_range(z, &bi, &n));
        b.pc.push(acc_y.apply1(&bq).eq(&acc_y.apply1(&p)));
        b.pc.push(bi.lt(&n));
        let d0 = n.sub(&bi);
        v.prove(&b, &[], &d0.ge_i(0), (32, 17), "decreases_nonneg", None);

        // q.x = q.x + 1;
        let mut e = b.fork(None);
        let qcur = int_of(&e, "q");
        let xq = acc_x.apply1(&qcur);
        let res = v.ev_arith(&e, &[], Arith::Add, &xq, &z.int(1), (34, 15)); // counterexample (overflow)
        v.field_assign(&mut e, "q", &["x"], &res);
        // i = i + 1;
        let mut e = e.fork(None);
        let ie = int_of(&e, "i");
        let res = v.ev_arith(&e, &[], Arith::Add, &ie, &z.int(1), (35, 11));
        e.env.set("i", Val::Int(res));

        // Preserved
        let (ei, eq) = (int_of(&e, "i"), int_of(&e, "q"));
        v.prove(&e, &[], &inv_range(z, &ei, &n), (30, 22), "invariant_preserved", None);
        let ob = acc_y.apply1(&eq).eq(&acc_y.apply1(&p));
        v.prove(&e, &[], &ob, (31, 19), "invariant_preserved", None);
        v.prove(&e, &[], &n.sub(&ei).lt(&d0), (32, 17), "decreases_decrease", None);

        // After the loop
        let mut a = v.havoc(&st, &["i", "q"]);
        let (ai, aq) = (int_of(&a, "i"), int_of(&a, "q"));
        a.pc.push(inv_range(z, &ai, &n));
        a.pc.push(acc_y.apply1(&aq).eq(&acc_y.apply1(&p)));
        a.pc.push(ai.lt(&n).not());

        // return q;  (37,3) → ensures result.y == p.y
        let r = a.fork(None);
        let rq = int_of(&r, "q");
        let env = v.ensures_env(&r, Some(Val::Dt(rq, point.clone())));
        let res = env.get("result").ast().clone();
        let p_env = env.get("p").ast().clone();
        let ob = acc_y.apply1(&res).eq(&acc_y.apply1(&p_env));
        v.prove(&r, &[], &ob, (37, 3), "ensures", None);
    }
}

// =============================================================================================
// s5_nested_quant: nested forall/exists + aggregates inside quantifiers (outer variables, patterns=[app]) + quantifiers in requires
// =============================================================================================
fn s5_nested_quant(z: &Z3, pre: &Prelude, trace: &mut Trace) {
    let model = Model::new(z, pre, &[]);
    let mut v = FnVerifier::new(z, pre, &model, trace, "grid");
    let mut st = v.init_params(&[("n", Ty::I64)]); // n!1
    let n = int_of(&st, "n");
    st.pc.push(z.and(&[n.ge_l(0), n.le_l(100)])); // requires n >= 0 && n <= 100

    // requires forall i in 0..n: i >= 0 && i < n
    {
        let lo = z.int(0);
        let k = v.quant_enter("i"); // i!q2
        let body = z.and(&[k.ge_l(0), k.lt(&n)]);
        v.quant_exit();
        let f = v.forall_q(&k, &lo, &n, &body);
        st.pc.push(f);
    }

    // return n;  (8,3)
    let st = st.fork(None);
    let rv = int_of(&st, "n");
    let env = v.ensures_env(&st, Some(Val::Int(rv)));
    let n = env.get("n").ast().clone();
    let node = (8, 3);

    // ensures forall i in 0..n: forall j in i + 1..n: i < j
    {
        let lo = z.int(0);
        let ki = v.quant_enter("i");
        let lo2 = ki.add_i(1); // lo/hi are evaluated before `s.k += 1`
        let kj = v.quant_enter("j");
        let body2 = ki.lt(&kj);
        v.quant_exit();
        let inner = v.forall_q(&kj, &lo2, &n, &body2);
        v.quant_exit();
        let ob = v.forall_q(&ki, &lo, &n, &inner);
        v.prove(&st, &[], &ob, node, "ensures", None);
    }
    // ensures exists i in 0..n + 1: i == n
    {
        let lo = z.int(0);
        let hi = n.add_i(1);
        let k = v.quant_enter("i");
        let body = k.eq(&n);
        v.quant_exit();
        let ob = v.exists_q(&k, &lo, &hi, &body);
        v.prove(&st, &[], &ob, node, "ensures", None);
    }
    // ensures forall i in 0..n: count(j in 0..i: j < i) <= i
    {
        let lo = z.int(0);
        let ki = v.quant_enter("i");
        let lo2 = z.int(0);
        let kj = v.quant_enter("j");
        let body_c = kj.lt(&ki);
        v.quant_exit();
        // At the aggregate call, qstack = [i] → outer = [i], hi=i is bound → quantified lemma ForAll([i], .., patterns=[app])
        let app = v.aggregate("count", &kj, &lo2, &ki, &body_c);
        let body = app.le(&ki);
        v.quant_exit();
        let ob = v.forall_q(&ki, &lo, &n, &body);
        v.prove(&st, &[], &ob, node, "ensures", None);
    }
}

// =============================================================================================
// s6_alloc_loop: array parameters/returns, alloc, arrays in loop havoc (`out!k`, `out!k.len`), index_oob counterexample
// =============================================================================================
struct FillPos {
    alloc: (u64, u32),
    inv1: (u64, u32),
    inv2: (u64, u32),
    dec: (u64, u32),
    index_assign: (u64, u32),
    index_add: Option<(u64, u32)>,
    i_add: (u64, u32),
    ret: (u64, u32),
}

fn s6_alloc_loop(z: &Z3, pre: &Prelude, trace: &mut Trace) {
    let model = Model::new(z, pre, &[]);
    // fill: requires n >= 0 && n <= 1_000, ensures len(result) == n
    build_fill(
        z,
        pre,
        &model,
        trace,
        "fill",
        0,
        true,
        &FillPos {
            alloc: (5, 24),
            inv1: (8, 22),
            inv2: (9, 24),
            dec: (10, 17),
            index_assign: (12, 5),
            index_add: None,
            i_add: (13, 11),
            ret: (15, 3),
        },
    );
    // fill_bad: out[i + 1] = i (index_oob counterexample), requires n >= 1, no ensures
    build_fill(
        z,
        pre,
        &model,
        trace,
        "fill_bad",
        1,
        false,
        &FillPos {
            alloc: (21, 24),
            inv1: (24, 22),
            inv2: (25, 24),
            dec: (26, 17),
            index_assign: (28, 5),
            index_add: Some((28, 11)),
            i_add: (29, 11),
            ret: (31, 3),
        },
    );
}

#[allow(clippy::too_many_arguments)]
fn build_fill(
    z: &Z3,
    pre: &Prelude,
    model: &Model,
    trace: &mut Trace,
    fname: &str,
    n_lo: i64,
    with_ensures: bool,
    pos: &FillPos,
) {
    let mut v = FnVerifier::new(z, pre, model, trace, fname);
    let mut st = v.init_params(&[("n", Ty::I64)]); // n!1
    let n = int_of(&st, "n");
    // requires n >= {n_lo} && n <= 1_000
    st.pc.push(z.and(&[n.ge_l(n_lo), n.le_l(1000)]));

    // let mut out: [i64] = alloc(n, 0);  → obligation alloc_negative, then `s.k += 1`
    let arr = v.ev_alloc(&st, &[], &n, &z.int(0), pos.alloc);
    st.env.set("out", Val::Arr(Arr::new(arr.a, arr.n, "out".to_string(), arr.elem)));
    st.env.set("i", Val::Int(z.int(0)));

    let len_eq_n = |st: &State| -> Ast {
        // len(out) == n  (len(out) = Arr.n)
        st.env.get("out").arr().n.eq(&n)
    };

    // Entry
    let i0 = int_of(&st, "i");
    v.prove(&st, &[], &inv_range(z, &i0, &n), pos.inv1, "invariant_entry", None);
    v.prove(&st, &[], &len_eq_n(&st), pos.inv2, "invariant_entry", None);

    // havoc: sorted names [i, out] → i!3, out!4(+ out!4.len)
    let mut b = v.havoc(&st, &["i", "out"]);
    let bi = int_of(&b, "i");
    b.pc.push(inv_range(z, &bi, &n));
    b.pc.push(len_eq_n(&b));
    b.pc.push(bi.lt(&n));
    let d0 = n.sub(&bi);
    v.prove(&b, &[], &d0.ge_i(0), pos.dec, "decreases_nonneg", None);

    // Body: out[i] = i;  (fill_bad: out[i + 1] = i;)   i = i + 1;
    let mut e = b.fork(None);
    let ie = int_of(&e, "i");
    let idx = match pos.index_add {
        Some(p) => v.ev_arith(&e, &[], Arith::Add, &ie, &z.int(1), p),
        None => ie.clone(),
    };
    let val = ie.clone();
    v.index_assign(&mut e, "out", &idx, &val, pos.index_assign);
    let mut e = e.fork(None);
    let ie = int_of(&e, "i");
    let res = v.ev_arith(&e, &[], Arith::Add, &ie, &z.int(1), pos.i_add);
    e.env.set("i", Val::Int(res));

    // Preserved
    let ei = int_of(&e, "i");
    v.prove(&e, &[], &inv_range(z, &ei, &n), pos.inv1, "invariant_preserved", None);
    v.prove(&e, &[], &len_eq_n(&e), pos.inv2, "invariant_preserved", None);
    v.prove(&e, &[], &n.sub(&ei).lt(&d0), pos.dec, "decreases_decrease", None);

    // After the loop (i!5, out!6)
    let mut a = v.havoc(&st, &["i", "out"]);
    let ai = int_of(&a, "i");
    a.pc.push(inv_range(z, &ai, &n));
    a.pc.push(len_eq_n(&a));
    a.pc.push(ai.lt(&n).not());

    // return out;  → ensures_ok (only fill has `len(result) == n`)
    let r = a.fork(None);
    let out_val = r.env.get("out").clone();
    let env = v.ensures_env(&r, Some(out_val));
    if with_ensures {
        let len_res = env.get("result").arr().n.clone();
        let n_env = env.get("n").ast().clone();
        v.prove(&r, &[], &len_res.eq(&n_env), pos.ret, "ensures", None);
    }
}
