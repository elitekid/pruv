//! verify.py `prove`/`cex`/`fmt_val` (254~338행)와 의무 trace.
//!
//! `prove` 의 흐름을 그대로 옮긴다:
//! 1. `seen` 키 `(line, col, code[, key_extra])` 가 있으면 질의 없이 끝낸다(어댑터 trace 는 `skipped` 항목을 남긴다).
//! 2. `run(false)`: 새 Solver(timeout 8000ms)에 pc → guard → `Not(ob)` 순서로 assert 하고 check.
//! 3. unsat 이면 끝(`seen` 에 넣지 않는다).
//! 4. 아니고 `lemmas` 가 비어 있지 않으면: 첫 시도가 sat 이면 반례(relaxed)를 뽑고, `run(true)`
//!    (pc → guard → lemmas → `Not(ob)`). unsat 이면 끝(seen 에 넣지 않는다).
//! 5. 그 밖에는 `seen` 에 키를 넣고 오류를 만든다: sat(또는 relaxed 있음)이면 `cannot prove`+반례,
//!    아니면 `verify_unknown`.
//!
//! 각 시도의 SMT-LIB 는 `(set-option :timeout 8000)\n` + `Solver::to_smt2()` 이며 **check 전에** 뽑는다.

use pruv_core::diagnostic::PruvError;
use pruv_core::pyjson::Json;
use serde_json::{json, Value};

use crate::symbolic::{Env, FnVerifier, Pos, State, Val, TIMEOUT_MS};
use crate::sys::{Ast, Sat, Solver, ZModel};

#[derive(Clone, Debug)]
pub struct Attempt {
    pub lemmas: bool,
    pub smt2: String,
    pub result: Sat,
}

#[derive(Clone, Debug)]
pub struct Obligation {
    /// 시제품 형식: 표본 전체에서 1부터. 어댑터 형식: 0부터(`len(rec.obligations)`).
    pub seq: u32,
    pub fn_name: String,
    pub line: u32,
    pub col: u32,
    pub code: String,
    pub attempts: Vec<Attempt>,
    /// 어댑터 형식에서 `key in fv.seen` 이라 질의 없이 지나간 의무.
    pub skipped: bool,
}

#[derive(Debug)]
pub struct Trace {
    pub obligations: Vec<Obligation>,
    /// true: 어댑터 `pruv-trace-v1` 규칙(seq 0부터, skipped 항목 기록, 진입 때 항목 생성).
    pub adapter: bool,
    /// false: 기록하지 않는다(SMT 텍스트도 만들지 않는다).
    pub record: bool,
}

impl Default for Trace {
    /// 시제품 형식(1부터, skipped 는 기록하지 않음).
    fn default() -> Self {
        Trace { obligations: Vec::new(), adapter: false, record: true }
    }
}

impl Trace {
    /// `diff_py_adapter.trace_result` 와 같은 기록.
    pub fn adapter() -> Trace {
        Trace { obligations: Vec::new(), adapter: true, record: true }
    }
    /// 기록 없음(verify_program 에 trace 를 주지 않을 때).
    pub fn off() -> Trace {
        Trace { obligations: Vec::new(), adapter: true, record: false }
    }

    /// `prove` 진입: 항목을 만들고 위치를 돌려준다(기록하지 않으면 None).
    pub(crate) fn begin(&mut self, fname: &str, node: Pos, code: &str, skipped: bool) -> Option<usize> {
        if !self.record || (skipped && !self.adapter) {
            return None;
        }
        let base = if self.adapter { 0 } else { 1 };
        let seq = self.obligations.len() as u32 + base;
        self.obligations.push(Obligation {
            seq,
            fn_name: fname.to_string(),
            line: node.0,
            col: node.1,
            code: code.to_string(),
            attempts: Vec::new(),
            skipped,
        });
        Some(self.obligations.len() - 1)
    }

    pub(crate) fn attempt(&mut self, idx: Option<usize>, a: Attempt) {
        if let Some(i) = idx {
            if let Some(o) = self.obligations.get_mut(i) {
                o.attempts.push(a);
            }
        }
    }
}

/// verify.py 의 `FIX` 표(172행).
fn fix_for(code: &str) -> &'static str {
    match code {
        "index_oob" => "add a requires/invariant/if that bounds the index, e.g. `invariant 0 <= i && i <= len(a)`",
        "overflow" => "bound the operands with requires (element ranges, len(a) <= N) and loop invariants on accumulators",
        "div" => "prove divisor > 0 and dividend >= 0 (add an if or requires)",
        "alloc_negative" => "prove 0 <= length <= 2^40",
        "call_requires" => "make the callee's requires hold before the call",
        "ensures" => "fix the code, or strengthen loop invariants so the postcondition follows",
        "assert" => "strengthen invariants or fix the code",
        "invariant_entry" => "the invariant must hold before the first iteration; check initial values",
        "invariant_preserved" => "the invariant must hold again after one body iteration; add facts it depends on as more invariants",
        "decreases_nonneg" => "the decreases expression must be >= 0 whenever the loop condition holds; add an invariant",
        "decreases_decrease" => "the decreases expression must strictly decrease each iteration",
        "variant_domain" => "guard the lookup so it is only reached for that variant, e.g. `is_variant(e, E::V) && variant_field(e, E::V, f) > 0` or `!is_variant(e, E::V) || ...`",
        "contract_domain" => "guard the partial operation earlier in the same contract or in an earlier clause: index range, divisor != 0, is_some/is_ok before some_val/ok_val/err_val, lo < hi before max/min",
        _ => "",
    }
}

/// z3py 가 모델 값 `str(v)` 로 찍는 꼴(수 리터럴, True/False, 접두 응용 `f(a, b)`).
fn py_str(v: &Ast) -> String {
    if let Some(n) = v.numeral_string() {
        return n;
    }
    if v.sort().is_bool() {
        if v.is_true() {
            return "True".to_string();
        }
        if v.is_false() {
            return "False".to_string();
        }
    }
    match v.decl_name() {
        Some(name) => {
            let kids = v.children();
            if kids.is_empty() {
                name
            } else {
                format!("{}({})", name, kids.iter().map(py_str).collect::<Vec<_>>().join(", "))
            }
        }
        None => v.sexpr(),
    }
}

/// `min(max(n, 0), 8)` (n 은 임의 길이 십진 문자열).
fn clamp8(n: &str) -> usize {
    if n.starts_with('-') {
        return 0;
    }
    match n.parse::<u64>() {
        Ok(v) => v.min(8) as usize,
        Err(_) => 8,
    }
}

/// `dict(relaxed, _note=...)`: 있으면 자리를 유지한 채 값만 교체, 없으면 끝에 추가.
fn set_key(kv: &mut Vec<(String, Json)>, key: &str, v: Json) {
    if let Some(e) = kv.iter_mut().find(|(k, _)| k == key) {
        e.1 = v;
    } else {
        kv.push((key.to_string(), v));
    }
}

impl<'a> FnVerifier<'a> {
    /// 시제품 경로: 오류 문구(`what`)는 비워 둔다.
    pub fn prove(&mut self, st: &State, g: &[Ast], ob: &Ast, node: Pos, code: &str, key_extra: Option<&str>) {
        self.prove_core(&st.env, &st.pc, g, ob, node, code, "", key_extra);
    }

    /// verify.py `prove(st, g, ob, node, code, what, key_extra)` (254행). 상태는 (env, pc) 로 받는다.
    #[allow(clippy::too_many_arguments)]
    pub(crate) fn prove_core(
        &mut self,
        senv: &Env,
        pc: &[Ast],
        g: &[Ast],
        ob: &Ast,
        node: Pos,
        code: &str,
        what: &str,
        key_extra: Option<&str>,
    ) {
        let key = (node.0, node.1, code.to_string(), key_extra.map(|s| s.to_string()));
        let skipped = self.seen.contains(&key);
        let idx = self.trace.begin(&self.fname, node, code, skipped);
        if skipped {
            return;
        }
        // 먼저 집계 보조정리 없이: 가정이 적으므로 여기서 unsat 이면 건전한 증명이고,
        // 보조정리가 필요 없는 많은 의무에서 양화 보조정리를 뺀다
        let (mut sol, mut r) = self.run_attempt(pc, g, ob, false, idx);
        if r == Sat::Unsat {
            return;
        }
        let mut relaxed: Option<Vec<(String, Json)>> = None;
        if !self.lemmas.is_empty() {
            if r == Sat::Sat {
                relaxed = Some(self.cex(&sol.model(), senv));
            }
            let (s2, r2) = self.run_attempt(pc, g, ob, true, idx);
            sol = s2;
            r = r2;
            if r == Sat::Unsat {
                return;
            }
        }
        self.seen.insert(key);
        let fix = fix_for(code).to_string();
        let (code2, msg, cex) = if r == Sat::Sat || relaxed.is_some() {
            let cex = if r == Sat::Sat {
                self.cex(&sol.model(), senv)
            } else {
                let mut m = relaxed.unwrap_or_default();
                let note = format!(
                    "counterexample ignores aggregate (sum/count/max/min) definitions; retry with them: {}",
                    sol.reason_unknown()
                );
                set_key(&mut m, "_note", Json::Str(note));
                m
            };
            (code.to_string(), format!("cannot prove {} in {}", what, self.fname), Some(Json::Obj(cex)))
        } else {
            (
                "verify_unknown".to_string(),
                format!("solver gave up proving {} in {} ({})", what, self.fname, sol.reason_unknown()),
                None,
            )
        };
        self.errors.push(PruvError {
            stage: "verify".to_string(),
            line: node.0 as i64,
            col: node.1 as i64,
            code: code2,
            message: msg,
            fix,
            counterexample: cex,
        });
    }

    /// verify.py 내부 `run(with_lemmas)` (258~269행): (solver, 판정).
    fn run_attempt(&mut self, pc: &[Ast], g: &[Ast], ob: &Ast, with_lemmas: bool, idx: Option<usize>) -> (Solver, Sat) {
        let mut sol = Solver::new(&self.z, TIMEOUT_MS);
        for p in pc {
            sol.add(p);
        }
        for p in g {
            sol.add(p);
        }
        if with_lemmas {
            for p in &self.lemmas {
                sol.add(p);
            }
        }
        sol.add(&ob.not());
        let smt2 = if self.trace.record {
            format!("(set-option :timeout {})\n{}", TIMEOUT_MS, sol.to_smt2())
        } else {
            String::new()
        };
        let result = sol.check();
        self.trace.attempt(idx, Attempt { lemmas: with_lemmas, smt2, result });
        (sol, result)
    }

    /// verify.py `cex` (292행): 상태의 변수마다 모델 값. 평가에 실패한 변수는 건너뛴다(Python `except: pass`).
    fn cex(&self, m: &ZModel, senv: &Env) -> Vec<(String, Json)> {
        let mut out: Vec<(String, Json)> = Vec::new();
        for (name, v) in &senv.0 {
            if let Some(j) = self.cex_one(m, v) {
                set_key(&mut out, name, j);
            }
        }
        out
    }

    fn cex_one(&self, m: &ZModel, v: &Val) -> Option<Json> {
        match v {
            Val::Arr(a) => {
                let n = m.eval(&a.n)?.numeral_string()?;
                let cnt = clamp8(&n);
                let mut els: Vec<Json> = Vec::new();
                for i in 0..cnt {
                    let sel = a.a.select(&self.z.int(i as i64));
                    els.push(Json::Num(m.eval(&sel)?.numeral_string()?));
                }
                Some(Json::Obj(vec![("len".to_string(), Json::Num(n)), ("first".to_string(), Json::Arr(els))]))
            }
            Val::Int(a) => Some(Json::Num(m.eval(a)?.numeral_string()?)),
            Val::Bool(a) => Some(Json::Bool(m.eval(a)?.is_true())),
            Val::Dt(a, _) => Some(Json::Str(self.fmt_val(&m.eval(a)?))),
            Val::Unit => None,
        }
    }

    /// verify.py `fmt_val` (310행): z3 모델 값 → 한 줄 Pruv 문법(사용자 struct/enum); 모르는 모양은 z3py 의 `str()`.
    pub(crate) fn fmt_val(&self, v: &Ast) -> String {
        if v.sort().is_int() && v.is_numeral() {
            if let Some(n) = v.numeral_string() {
                return n;
            }
        }
        if v.sort().is_bool() {
            return if v.is_true() { "true" } else { "false" }.to_string();
        }
        let model = self.model;
        let tyname = match model.type_of(v) {
            Some(crate::model::Ty::User(n)) if model.sort_opt(&n).is_some() => n,
            _ => return py_str(v),
        };
        if !v.is_app() {
            return py_str(v);
        }
        let dn = v.decl_name().unwrap_or_default();
        let kids: Vec<String> = v.children().iter().map(|c| self.fmt_val(c)).collect();
        if let Some(sf) = model.struct_fns_opt(&tyname) {
            if let Some(fields) = model.struct_fields_opt(&tyname) {
                if sf.ctor.name() == dn && fields.len() == kids.len() {
                    if kids.is_empty() {
                        return tyname;
                    }
                    let parts: Vec<String> =
                        fields.iter().zip(kids.iter()).map(|(fd, k)| format!("{}: {}", fd.name, k)).collect();
                    return format!("{} {{ {} }}", tyname, parts.join(", "));
                }
            }
        } else if let Some(vars) = model.enum_variants(&tyname) {
            for (vn, vf) in vars {
                if vf.ctor.name() == dn {
                    if kids.is_empty() {
                        return format!("{}::{}", tyname, vn);
                    }
                    return format!("{}::{}({})", tyname, vn, kids.join(", "));
                }
            }
        }
        py_str(v)
    }
}

/// 시제품 출력 JSON: `{"sample","obligations":[{"seq","fn","line","col","code","attempts":[{"lemmas","smt2","result"}]}],"z3_version"}`.
pub fn trace_json(sample: &str, trace: &Trace, z3_version: &str) -> Value {
    let obligations: Vec<Value> = trace
        .obligations
        .iter()
        .map(|o| {
            let attempts: Vec<Value> = o
                .attempts
                .iter()
                .map(|a| json!({ "lemmas": a.lemmas, "smt2": a.smt2, "result": a.result.as_str() }))
                .collect();
            json!({
                "seq": o.seq,
                "fn": o.fn_name,
                "line": o.line,
                "col": o.col,
                "code": o.code,
                "attempts": attempts,
            })
        })
        .collect();
    json!({ "sample": sample, "obligations": obligations, "z3_version": z3_version })
}

/// 어댑터 `pruv-trace-v1` 의 `obligations` 배열(키 정렬은 `dumps_sorted` 가 한다).
pub fn adapter_obligations_json(trace: &Trace) -> Json {
    let items: Vec<Json> = trace
        .obligations
        .iter()
        .map(|o| {
            let attempts: Vec<Json> = o
                .attempts
                .iter()
                .map(|a| {
                    Json::Obj(vec![
                        ("lemmas".to_string(), Json::Bool(a.lemmas)),
                        ("smt2".to_string(), Json::Str(a.smt2.clone())),
                        ("result".to_string(), Json::str(a.result.as_str())),
                    ])
                })
                .collect();
            let mut kv = vec![
                ("seq".to_string(), Json::int(o.seq as i64)),
                ("fn".to_string(), Json::Str(o.fn_name.clone())),
                ("line".to_string(), Json::int(o.line as i64)),
                ("col".to_string(), Json::int(o.col as i64)),
                ("code".to_string(), Json::Str(o.code.clone())),
                ("attempts".to_string(), Json::Arr(attempts)),
            ];
            if o.skipped {
                kv.push(("skipped".to_string(), Json::Bool(true)));
            }
            Json::Obj(kv)
        })
        .collect();
    Json::Arr(items)
}
