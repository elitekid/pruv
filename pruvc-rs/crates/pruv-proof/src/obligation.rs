//! verify.py `prove` (254~290행)와 의무 trace.
//!
//! `prove` 의 흐름을 그대로 옮긴다:
//! 1. `seen` 키 `(line, col, code[, key_extra])` 가 있으면 아무것도 하지 않는다(질의 없음, 기록 없음).
//! 2. `run(false)`: 새 Solver(timeout 8000ms)에 pc → guard → `Not(ob)` 순서로 assert 하고 check.
//! 3. unsat 이면 끝(`seen` 에 넣지 않는다).
//! 4. 아니고 `lemmas` 가 비어 있지 않으면 `run(true)`: pc → guard → lemmas → `Not(ob)`.
//!    unsat 이면 끝(seen 에 넣지 않는다).
//! 5. 그 밖에는 `seen` 에 키를 넣는다(Python 은 여기서 PruvError 를 만든다; 시제품은 오류 문구를 만들지 않는다).
//!
//! 각 시도의 SMT-LIB 는 `(set-option :timeout 8000)\n` + `Solver::to_smt2()` 이며 **check 전에** 뽑는다
//! (Python 쪽 adapter 도 `sol.sexpr()` 를 check 전에 호출하도록 맞춰야 한다).

use serde_json::{json, Value};

use crate::sys::{Ast, Sat, Solver};
use crate::symbolic::{FnVerifier, Pos, State, TIMEOUT_MS};

#[derive(Clone, Debug)]
pub struct Attempt {
    pub lemmas: bool,
    pub smt2: String,
    pub result: Sat,
}

#[derive(Clone, Debug)]
pub struct Obligation {
    /// 표본 전체에서 1부터, `prove` 가 시도를 기록한 순서.
    pub seq: u32,
    pub fn_name: String,
    pub line: u32,
    pub col: u32,
    pub code: String,
    pub attempts: Vec<Attempt>,
}

#[derive(Default, Debug)]
pub struct Trace {
    pub obligations: Vec<Obligation>,
}

impl<'a> FnVerifier<'a> {
    /// verify.py `prove(st, g, ob, node, code, what, key_extra)`. `what`(오류 문구)은 trace 에 쓰이지 않아 생략.
    pub fn prove(&mut self, st: &State, g: &[Ast], ob: &Ast, node: Pos, code: &str, key_extra: Option<&str>) {
        let key = (node.0, node.1, code.to_string(), key_extra.map(|s| s.to_string()));
        if self.seen.contains(&key) {
            return;
        }
        let mut attempts: Vec<Attempt> = Vec::new();
        let r = self.run_attempt(st, g, ob, false, &mut attempts);
        if r != Sat::Unsat {
            let mut last = r;
            if !self.lemmas.is_empty() {
                last = self.run_attempt(st, g, ob, true, &mut attempts);
            }
            if last != Sat::Unsat {
                self.seen.insert(key);
            }
        }
        let seq = self.trace.obligations.len() as u32 + 1;
        self.trace.obligations.push(Obligation {
            seq,
            fn_name: self.fname.clone(),
            line: node.0,
            col: node.1,
            code: code.to_string(),
            attempts,
        });
    }

    /// verify.py 내부 `run(with_lemmas)` (258~269행).
    fn run_attempt(&self, st: &State, g: &[Ast], ob: &Ast, with_lemmas: bool, out: &mut Vec<Attempt>) -> Sat {
        let mut sol = Solver::new(&self.z, TIMEOUT_MS);
        for p in &st.pc {
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
        let smt2 = format!("(set-option :timeout {})\n{}", TIMEOUT_MS, sol.to_smt2());
        let result = sol.check();
        out.push(Attempt { lemmas: with_lemmas, smt2, result });
        result
    }
}

/// 출력 JSON: `{"sample","obligations":[{"seq","fn","line","col","code","attempts":[{"lemmas","smt2","result"}]}],"z3_version"}`.
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
