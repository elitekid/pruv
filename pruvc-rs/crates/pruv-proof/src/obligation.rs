//! verify.py `prove`/`cex`/`fmt_val` (lines 254-338) and the obligation trace.
//!
//! This ports the flow of `prove` as is:
//! 1. If the `seen` key `(line, col, code[, key_extra])` is present, finish without a query (the adapter trace leaves a `skipped` entry).
//! 2. `run(false)`: in a new Solver (timeout 8000ms), assert pc → guard → `Not(ob)` in that order and check.
//! 3. If unsat, done (not added to `seen`).
//! 4. Otherwise, if `lemmas` is non-empty: if the first attempt was sat, extract the counterexample (relaxed), then `run(true)`
//!    (pc → guard → lemmas → `Not(ob)`). If unsat, done (not added to seen).
//! 5. Otherwise, add the key to `seen` and build the error: if sat (or relaxed is present), `cannot prove` + counterexample,
//!    else `verify_unknown`.
//!
//! Each attempt's SMT-LIB is `(set-option :timeout T)\n` + (if rlimit is set, `(set-option :rlimit R)\n`) +
//! (if seed is set, `(set-option :random_seed S)\n`) + `Solver::to_smt2()`, extracted **before check** (T defaults to 8000).
//!
//! trace v2 (adapter format): an obligation records `phase` ("verification"|"inference"), `round`, `cand` (null if absent), and (only when skipped) `skipped`;
//! an attempt records `status` (proved|not_proved|timeout|resource_unknown), `timeout_ms`, `rlimit`, `seed`, and `reason_unknown` (only when Unknown).
//! The prototype format (`trace_json`) is unchanged. Configuration lives in `FnVerifier.qcfg` (`QueryConfig`).

use pruv_core::diagnostic::PruvError;
use pruv_core::pyjson::Json;
use serde_json::{json, Value};

use crate::symbolic::{Env, FnVerifier, Pos, State, Val};
use crate::sys::{Ast, Sat, Solver, ZModel};

/// verify.py `query_status`: verdict + `reason_unknown` → status for recording.
pub fn query_status(result: Sat, reason: Option<&str>) -> &'static str {
    match result {
        Sat::Unsat => "proved",
        Sat::Sat => "not_proved",
        Sat::Unknown => match reason {
            Some("timeout") | Some("canceled") => "timeout",
            _ => "resource_unknown",
        },
    }
}

#[derive(Clone, Debug)]
pub struct Attempt {
    pub lemmas: bool,
    pub smt2: String,
    pub result: Sat,
    /// `query_status(result, reason_unknown)`
    pub status: String,
    pub timeout_ms: u32,
    pub rlimit: Option<u32>,
    pub seed: Option<u32>,
    /// `Some(sol.reason_unknown())` only when Unknown.
    pub reason_unknown: Option<String>,
}

#[derive(Clone, Debug)]
pub struct Obligation {
    /// Prototype format: from 1 across the whole sample. Adapter format: from 0 (`len(rec.obligations)`).
    pub seq: u32,
    pub fn_name: String,
    pub line: u32,
    pub col: u32,
    pub code: String,
    pub attempts: Vec<Attempt>,
    /// In the adapter format, an obligation that passed without a query because `key in fv.seen`.
    pub skipped: bool,
    /// "verification" | "inference"
    pub phase: String,
    pub round: Option<u32>,
    pub cand: Option<String>,
    /// G4 A1: the file of the obligation's node (explicit visibility mode only; None keeps the legacy key set).
    pub file: Option<String>,
}

#[derive(Debug)]
pub struct Trace {
    pub obligations: Vec<Obligation>,
    /// true: adapter `pruv-trace-v1` rules (seq from 0, skipped entries recorded, entry created on entry).
    pub adapter: bool,
    /// false: record nothing (SMT text is not produced either).
    pub record: bool,
}

impl Default for Trace {
    /// Prototype format (from 1, skipped is not recorded).
    fn default() -> Self {
        Trace { obligations: Vec::new(), adapter: false, record: true }
    }
}

impl Trace {
    /// The same recording as `diff_py_adapter.trace_result`.
    pub fn adapter() -> Trace {
        Trace { obligations: Vec::new(), adapter: true, record: true }
    }
    /// No recording (when no trace is given to verify_program).
    pub fn off() -> Trace {
        Trace { obligations: Vec::new(), adapter: true, record: false }
    }

    /// `prove` entry: creates the entry and returns its position (None if not recording).
    #[allow(clippy::too_many_arguments)]
    pub(crate) fn begin(
        &mut self,
        fname: &str,
        node: Pos,
        code: &str,
        skipped: bool,
        phase: &str,
        round: Option<u32>,
        cand: Option<String>,
        file: Option<String>,
    ) -> Option<usize> {
        if !self.record || (skipped && !self.adapter) {
            return None;
        }
        let base = if self.adapter { 0 } else { 1 };
        let seq = self.obligations.len() as u32 + base;
        self.obligations.push(Obligation {
            seq,
            fn_name: fname.to_string(),
            line: crate::symbolic::pos_line(node),
            col: node.1,
            code: code.to_string(),
            attempts: Vec::new(),
            skipped,
            phase: phase.to_string(),
            round,
            cand,
            file,
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

/// The `FIX` table of verify.py (line 172).
fn fix_for(code: &str) -> &'static str {
    match code {
        "index_oob" => "add a requires/invariant/if that bounds the index, e.g. `invariant 0 <= i && i <= len(a)`",
        "overflow" => "bound the operands with requires (element ranges, len(a) <= N) and loop invariants on accumulators",
        "div" => "prove divisor > 0 and dividend >= 0 (add an if or requires)",
        "shift_range" => "prove 0 <= shift count < 64 (add an if or requires)",
        "alloc_negative" => "prove 0 <= length <= 2^40",
        "call_requires" => "make the callee's requires hold before the call",
        "ensures" => "fix the code, or strengthen loop invariants so the postcondition follows",
        "assert" => "strengthen invariants or fix the code",
        "refinement_init" => "make the initial value satisfy the declared range/length, or widen the refinement; it is a proof obligation, not a run-time check",
        "refinement_assign" => "make the stored value satisfy the declared range, or widen the refinement; a loop that updates it needs invariants that imply the range",
        "invariant_entry" => "the invariant must hold before the first iteration; check initial values",
        "invariant_preserved" => "the invariant must hold again after one body iteration; add facts it depends on as more invariants",
        "decreases_nonneg" => "the decreases expression must be >= 0 whenever the loop condition holds; add an invariant",
        "decreases_decrease" => "the decreases expression must strictly decrease each iteration",
        "recursive_nonneg" => "the decreases measure must be >= 0 at function entry and at every recursive call; add a requires, or guard the call with an if/match",
        "recursive_decrease" => "the callee's measure must be strictly smaller than the caller's entry measure: recurse on a smaller argument (a child of a match binder, an index one closer to the end), or fix the measure",
        "variant_domain" => "guard the lookup so it is only reached for that variant, e.g. `is_variant(e, E::V) && variant_field(e, E::V, f) > 0` or `!is_variant(e, E::V) || ...`",
        "contract_domain" => "guard the partial operation earlier in the same contract or in an earlier clause: index range, divisor != 0, is_some/is_ok before some_val/ok_val/err_val, lo < hi before max/min",
        "elem_range" => "store or fill only values in 0..=255 into a [u8] array: bound the value with requires, an if, or a loop invariant",
        "string_slice_range" => "keep 0 <= lo <= hi <= len(s) for substr(s, lo, hi): bound lo and hi with requires, an if, or a loop invariant (a counterexample str may not be valid UTF-8)",
        "utf8_boundary" => "cut a str only at character boundaries: require or check is_char_boundary(s, lo) and is_char_boundary(s, hi) (a counterexample str may not be valid UTF-8)",
        _ => "",
    }
}

/// The form z3py prints for a model value via `str(v)` (numeric literal, True/False, prefix application `f(a, b)`).
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

/// `min(max(n, 0), 8)` (n is a decimal string of arbitrary length).
fn clamp8(n: &str) -> usize {
    if n.starts_with('-') {
        return 0;
    }
    match n.parse::<u64>() {
        Ok(v) => v.min(8) as usize,
        Err(_) => 8,
    }
}

/// One byte of a `str` field element in a counterexample (verify.py `_fmt_buf`): `chr(b)` for a printable ASCII byte other than
/// `"` and `\`, else `\x%02x` of `b & 255` (Python's unbounded two's complement for a negative or huge element). `s` is the
/// decimal text of the element.
fn byte_text(s: &str) -> String {
    if let Ok(b) = s.parse::<i64>() {
        if (32..127).contains(&b) {
            let c = b as u8 as char;
            if c != '"' && c != '\\' {
                return c.to_string();
            }
        }
    }
    let (neg, digits) = match s.strip_prefix('-') {
        Some(r) => (true, r),
        None => (false, s),
    };
    let mut r: u32 = 0;
    for ch in digits.chars() {
        if let Some(d) = ch.to_digit(10) {
            r = (r * 10 + d) % 256;
        }
    }
    let low = if neg { (256 - r) % 256 } else { r };
    format!("\\x{:02x}", low)
}

/// `dict(relaxed, _note=...)`: if present, replace only the value, keeping its position; otherwise append at the end.
fn set_key(kv: &mut Vec<(String, Json)>, key: &str, v: Json) {
    if let Some(e) = kv.iter_mut().find(|(k, _)| k == key) {
        e.1 = v;
    } else {
        kv.push((key.to_string(), v));
    }
}

impl<'a> FnVerifier<'a> {
    /// Prototype path: the error wording (`what`) is left empty.
    pub fn prove(&mut self, st: &State, g: &[Ast], ob: &Ast, node: Pos, code: &str, key_extra: Option<&str>) {
        self.prove_core(&st.env, &st.pc, g, ob, node, code, "", key_extra);
    }

    /// verify.py `prove(st, g, ob, node, code, what, key_extra)` (line 254). The state is taken as (env, pc).
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
        self.prove_core_cand(senv, pc, g, ob, node, code, what, key_extra, None);
    }

    /// `prove_core` + `cand` for recording.
    #[allow(clippy::too_many_arguments)]
    pub(crate) fn prove_core_cand(
        &mut self,
        senv: &Env,
        pc: &[Ast],
        g: &[Ast],
        ob: &Ast,
        node: Pos,
        code: &str,
        what: &str,
        key_extra: Option<&str>,
        cand: Option<&str>,
    ) {
        // STAGE1 B2: during search, only obligations of candidates that have not yet failed are examined (once the abort flag is set, nothing is examined).
        let probing = self.probe.is_some();
        if let Some(p) = &self.probe {
            if p.abort.is_some() || cand.is_none() || cand.map_or(false, |c| p.failed.contains_key(c)) {
                return;
            }
        }
        // The key uses the plain per-file line (Python's key has no file).
        let key = (crate::symbolic::pos_line(node), node.1, code.to_string(), key_extra.map(|s| s.to_string()));
        let skipped = if probing { false } else { self.seen.contains(&key) };
        let idx = self.trace.begin(
            &self.fname,
            node,
            code,
            skipped,
            &self.qcfg.phase,
            self.qcfg.round,
            cand.map(|s| s.to_string()),
            self.file_of(node),
        );
        if skipped {
            return;
        }
        if probing {
            self.probe_attempts(pc, g, ob, code, cand.unwrap_or(""), idx);
            return;
        }
        // First without the aggregate lemmas: assumptions are few, so unsat here is a sound proof,
        // and it drops the quantified lemmas for the many obligations that do not need them
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
            line: self.err_line(node), // G4 A1: carries the file tag; the JSON prints it untagged with `file`
            col: node.1 as i64,
            code: code2,
            message: msg,
            fix,
            counterexample: cex,
        });
    }

    /// verify.py `_probe_attempts`: search of a single candidate obligation. Same two stages as `prove` (without lemmas → if the first attempt is not unsat
    /// and lemmas exist, with them too). Before each attempt, the budget and wall clock are checked first (`Probe::tick`; if exceeded, mark abort and finish).
    /// If an attempt's result is unknown and the z3 reason is exactly "timeout" (the 500ms per-query wall-clock deadline), the whole function ends with a timeout (abort Timeout).
    /// Otherwise, if the last attempt is not proved (including other unknown wordings such as rlimit-exhausted canceled), only that candidate is left failed for this round (status as in query_status).
    /// The wall clock (`Probe::tick`) also stops the whole function.
    /// Python's z3.Z3Exception → status "error" branch is not ported: Rust's `Solver::check` does not throw exceptions.
    fn probe_attempts(&mut self, pc: &[Ast], g: &[Ast], ob: &Ast, code: &str, cand: &str, idx: Option<usize>) {
        let mut status = String::new();
        for with_lemmas in [false, true] {
            if with_lemmas && self.lemmas.is_empty() {
                break;
            }
            let ok = match self.probe.as_mut() {
                Some(p) => p.tick(),
                None => return,
            };
            if !ok {
                return;
            }
            let (sol, r) = self.run_attempt(pc, g, ob, with_lemmas, idx);
            let reason = if r == Sat::Unknown { Some(sol.reason_unknown()) } else { None };
            status = query_status(r, reason.as_deref()).to_string();
            if reason.as_deref() == Some("timeout") {
                if let Some(p) = self.probe.as_mut() {
                    p.abort = Some(crate::symbolic::ProbeAbort::Timeout);
                }
                return;
            }
            if r == Sat::Unsat {
                return;
            }
        }
        if let Some(p) = self.probe.as_mut() {
            p.failed.insert(cand.to_string(), (code.to_string(), status));
        }
    }

    /// verify.py inner `run(with_lemmas)` (lines 258-269): (solver, verdict).
    fn run_attempt(&mut self, pc: &[Ast], g: &[Ast], ob: &Ast, with_lemmas: bool, idx: Option<usize>) -> (Solver, Sat) {
        let q = &self.qcfg;
        let mut sol = Solver::with_options(&self.z, q.timeout_ms, q.rlimit, q.seed);
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
            let mut head = format!("(set-option :timeout {})\n", q.timeout_ms);
            if let Some(r) = q.rlimit {
                head.push_str(&format!("(set-option :rlimit {})\n", r));
            }
            if let Some(s) = q.seed {
                head.push_str(&format!("(set-option :random_seed {})\n", s));
            }
            format!("{}{}", head, sol.to_smt2())
        } else {
            String::new()
        };
        let result = sol.check();
        let reason = if result == Sat::Unknown { Some(sol.reason_unknown()) } else { None };
        let status = query_status(result, reason.as_deref()).to_string();
        let attempt = Attempt {
            lemmas: with_lemmas,
            smt2,
            result,
            status,
            timeout_ms: q.timeout_ms,
            rlimit: q.rlimit,
            seed: q.seed,
            reason_unknown: reason,
        };
        self.trace.attempt(idx, attempt);
        (sol, result)
    }

    /// verify.py `cex` (line 292): the model value for each variable of the state. Variables that fail to evaluate are skipped (Python `except: pass`).
    fn cex(&self, m: &ZModel, senv: &Env) -> Vec<(String, Json)> {
        // G3 A2 (4.7): the opaque ordinals are per counterexample
        self.opq.borrow_mut().clear();
        let mut out: Vec<(String, Json)> = Vec::new();
        for (name, v) in &senv.0 {
            if let Some(j) = self.cex_one(m, v) {
                set_key(&mut out, name, j);
            }
        }
        if let Some(cost) = &self.cost0 {
            if let Some(j) = self.cex_one(m, &Val::Int(cost.clone())) {
                set_key(&mut out, "C", j);
            }
        }
        out
    }

    fn cex_one(&self, m: &ZModel, v: &Val) -> Option<Json> {
        match v {
            Val::File(f) => Some(Json::Obj(vec![
                ("ok".into(), Json::Bool(m.eval(&f.ok)?.is_true())),
                ("readable".into(), Json::Bool(m.eval(&f.readable)?.is_true())),
                ("writable".into(), Json::Bool(m.eval(&f.writable)?.is_true())),
                ("size".into(), Json::Num(m.eval(&f.buf.n)?.numeral_string()?)),
            ])),
            Val::Arr(a) => {
                let n = m.eval(&a.n)?.numeral_string()?;
                let cnt = clamp8(&n);
                let mut els: Vec<Json> = Vec::new();
                for i in 0..cnt {
                    let sel = a.a.select(&self.z.int(i as i64));
                    // G2 A5: bool elements are JSON true/false; G3: abstract elements are opaque tokens
                    if a.elem == crate::model::Elem::Bool {
                        els.push(Json::Bool(m.eval(&sel)?.is_true()));
                    } else if a.elem == crate::model::Elem::Abs {
                        // G6 A1: only an element of a type-parameter type is an opaque token; any other datatype element
                        // (a Vec<Option<i64>>, ...) makes Python's `.as_long()` raise, so the variable is skipped
                        if a.ety.as_ref().map_or(true, |g| g.owner.is_none()) {
                            return None;
                        }
                        els.push(self.opaque_json(&m.eval(&sel)?));
                    } else {
                        els.push(Json::Num(m.eval(&sel)?.numeral_string()?));
                    }
                }
                Some(Json::Obj(vec![("len".to_string(), Json::Num(n)), ("first".to_string(), Json::Arr(els))]))
            }
            Val::Int(a) => Some(Json::Num(m.eval(a)?.numeral_string()?)),
            Val::Bool(a) => Some(Json::Bool(m.eval(a)?.is_true())),
            // G3: an abstract value is the opaque dict at the top (a string `T:opaque#N` only inside a datatype)
            Val::Dt(a, _) => {
                let mv = m.eval(a)?;
                if self.model.is_g9() {
                    // G9 A1: a program with a G9 feature takes the bounded printer; any other program the original one
                    let mut lim = 0usize;
                    Some(self.fmt_g9(m, &mv, false, &mut lim, 1, None))
                } else {
                    Some(self.fmt_val_j(&mv, false))
                }
            }
            // G6 A1: Python evaluates the Map object in the model and the exception skips the variable
            Val::Map(_) => None,
            Val::Unit => None,
        }
    }

    /// verify.py `opaque` (4.7): the token of an abstract model value `v`; ordinals are per abstract sort, in first-seen order
    /// of this counterexample, and equal model values share one. (type parameter spelling, "opaque#N")
    fn opaque(&self, v: &Ast) -> (String, String) {
        let sname = v.sort().name();
        let key = v.sexpr();
        let mut tab = self.opq.borrow_mut();
        let list = tab.entry(sname.clone()).or_default();
        let idx = match list.iter().position(|k| *k == key) {
            Some(i) => i,
            None => {
                list.push(key);
                list.len() - 1
            }
        };
        (self.model.abs_name_of(&sname).unwrap_or_default(), format!("opaque#{}", idx))
    }

    fn opaque_json(&self, v: &Ast) -> Json {
        let (tp, val) = self.opaque(v);
        Json::Obj(vec![("type_parameter".to_string(), Json::Str(tp)), ("value".to_string(), Json::Str(val))])
    }

    /// verify.py `fmt_val` (line 310): z3 model value → one-line Pruv syntax (user struct/enum); unknown shapes use z3py's `str()`.
    /// G3: an abstract value is its opaque token (a dict at the top, `T:opaque#N` inside a datatype).
    pub(crate) fn fmt_val_j(&self, v: &Ast, nested: bool) -> Json {
        let model = self.model;
        if v.sort().is_int() && v.is_numeral() {
            if let Some(n) = v.numeral_string() {
                return Json::Str(n);
            }
        }
        if v.sort().is_bool() {
            return Json::Str(if v.is_true() { "true" } else { "false" }.to_string());
        }
        if model.abs_name_of(&v.sort().name()).is_some() {
            if nested {
                let (tp, val) = self.opaque(v);
                return Json::Str(format!("{}:{}", tp, val));
            }
            return self.opaque_json(v);
        }
        let ty = match model.type_of(v) {
            Some(t) => t,
            None => return Json::Str(py_str(v)),
        };
        let kid_str = |c: &Ast| -> String {
            match self.fmt_val_j(c, true) {
                Json::Str(s) => s,
                _ => py_str(c),
            }
        };
        if let crate::model::Ty::Inst(g) = &ty {
            if (g.name == "option" || g.name == "result") && v.is_app() {
                let dn = v.decl_name().unwrap_or_default();
                let nm = model.short_of(&dn).map(|s| s.to_string()).unwrap_or(dn);
                let ks: Vec<String> = v.children().iter().map(|c| kid_str(c)).collect();
                return Json::Str(if ks.is_empty() { nm } else { format!("{}({})", nm, ks.join(", ")) });
            }
        }
        if !model.is_user(&ty) || !v.is_app() {
            return Json::Str(py_str(v));
        }
        let dn = v.decl_name().unwrap_or_default();
        let kids: Vec<String> = v.children().iter().map(|c| kid_str(c)).collect();
        let tyname = ty.name().to_string();
        match model.nominal_kind(&ty) {
            Some(crate::model::NomKind::Struct) => {
                if let (Ok(sf), Some(decl)) = (model.struct_info(&ty), model.decl_opt(&tyname)) {
                    if let crate::model::TypeKind::Struct(fields) = &decl.kind {
                        if sf.ctor.name() == dn && fields.len() == kids.len() {
                            if kids.is_empty() {
                                return Json::Str(tyname);
                            }
                            let parts: Vec<String> =
                                fields.iter().zip(kids.iter()).map(|(fd, k)| format!("{}: {}", fd.name, k)).collect();
                            return Json::Str(format!("{} {{ {} }}", tyname, parts.join(", ")));
                        }
                    }
                }
            }
            Some(crate::model::NomKind::Enum) => {
                if let Ok(vars) = model.enum_info(&ty) {
                    for (vn, vf) in vars {
                        if vf.ctor.name() == dn {
                            if kids.is_empty() {
                                return Json::Str(format!("{}::{}", tyname, vn));
                            }
                            return Json::Str(format!("{}::{}({})", tyname, vn, kids.join(", ")));
                        }
                    }
                }
            }
            None => {}
        }
        Json::Str(py_str(v))
    }

    /// verify.py `_fmt_buf`: a buffer field value Buf(len, arr): `[e0, e1, ...]` (first 8 elements) or `"bytes"` for a str field.
    /// Any failure (Python exception) is the caller's `str(v)`.
    fn fmt_buf(&self, m: &ZModel, v: &Ast, fty: Option<&crate::model::Ty>) -> Json {
        use crate::model::Ty;
        let fallback = || Json::Str(py_str(v));
        let kids = v.children();
        let (Some(n_ast), Some(arr)) = (kids.first(), kids.get(1)) else { return fallback() };
        let Some(n) = n_ast.numeral_string() else { return fallback() };
        let Some(fty) = fty else { return fallback() };
        let is_bool = matches!(fty, Ty::Array(crate::model::Elem::Bool));
        let is_str = matches!(fty, Ty::Str);
        // elements as (bool, decimal text)
        let mut els: Vec<(bool, String)> = Vec::new();
        for i in 0..clamp8(&n) {
            let sel = arr.select(&self.z.int(i as i64));
            let Some(x) = m.eval(&sel) else { return fallback() };
            if is_bool {
                els.push((x.is_true(), String::new()));
            } else {
                let Some(t) = x.numeral_string() else { return fallback() };
                els.push((false, t));
            }
        }
        let more = !n.starts_with('-') && n.parse::<u64>().map_or(true, |c| c > 8);
        if is_str {
            let body: String = els.iter().map(|(_, t)| byte_text(t)).collect();
            return Json::Str(format!("\"{}{}\"", body, if more { "..." } else { "" }));
        }
        let txt = els
            .iter()
            .map(|(b, t)| if is_bool { (if *b { "true" } else { "false" }).to_string() } else { t.clone() })
            .collect::<Vec<_>>()
            .join(", ");
        let tail = if more {
            if txt.is_empty() { "..." } else { ", ..." }
        } else {
            ""
        };
        Json::Str(format!("[{}{}]", txt, tail))
    }

    /// `fmt_g9` of a nested value (always a string).
    fn fmt_g9_s(&self, m: &ZModel, v: &Ast, lim: &mut usize, depth: usize, fty: Option<&crate::model::Ty>) -> String {
        match self.fmt_g9(m, v, true, lim, depth, fty) {
            Json::Str(s) => s,
            _ => py_str(v),
        }
    }

    /// verify.py `_fmt_g9`: the bounded counterexample printer of a program with a G9 feature (at most `CEX_MAX_NODES` nominal
    /// constructor nodes per value in preorder, nesting depth at most `CEX_MAX_DEPTH`; the cut parts print as `<truncated>`).
    /// `lim` is the node counter shared by one top-level value, `depth` starts at 1, `fty` is the declared type of a field value
    /// (needed to print a buffer field). A Python exception anywhere inside is `str(v)` of that level.
    pub(crate) fn fmt_g9(
        &self,
        m: &ZModel,
        v: &Ast,
        nested: bool,
        lim: &mut usize,
        depth: usize,
        fty: Option<&crate::model::Ty>,
    ) -> Json {
        use crate::model::{Ty, TypeKind};
        const CEX_MAX_NODES: usize = 64;
        const CEX_MAX_DEPTH: usize = 16;
        const CEX_TRUNCATED: &str = "<truncated>";
        let model = self.model;
        if v.sort().is_int() && v.is_numeral() {
            if let Some(n) = v.numeral_string() {
                return Json::Str(n);
            }
        }
        if v.sort().is_bool() {
            return Json::Str(if v.is_true() { "true" } else { "false" }.to_string());
        }
        let sname = v.sort().name();
        if model.is_buf_sort_name(&sname) {
            return self.fmt_buf(m, v, fty);
        }
        if model.abs_name_of(&sname).is_some() {
            if nested {
                let (tp, val) = self.opaque(v);
                return Json::Str(format!("{}:{}", tp, val));
            }
            return self.opaque_json(v);
        }
        let ty = match model.type_of(v) {
            Some(t) => t,
            None => return Json::Str(py_str(v)),
        };
        if let Ty::Inst(g) = &ty {
            if (g.name == "option" || g.name == "result") && v.is_app() {
                let dn = v.decl_name().unwrap_or_default();
                let nm = model.short_of(&dn).map(|s| s.to_string()).unwrap_or(dn);
                let ks: Vec<String> = v.children().iter().map(|c| self.fmt_g9_s(m, c, lim, depth, None)).collect();
                return Json::Str(if ks.is_empty() { nm } else { format!("{}({})", nm, ks.join(", ")) });
            }
        }
        if !model.is_user(&ty) || !v.is_app() {
            return Json::Str(py_str(v));
        }
        if *lim >= CEX_MAX_NODES || depth > CEX_MAX_DEPTH {
            return Json::Str(CEX_TRUNCATED.to_string());
        }
        *lim += 1;
        let dn = v.decl_name().unwrap_or_default();
        let tyname = ty.name().to_string();
        let Some(decl) = model.decl_opt(&tyname) else { return Json::Str(py_str(v)) };
        let kids = v.children();
        match &decl.kind {
            TypeKind::Struct(fields) => {
                let Ok(sf) = model.struct_info(&ty) else { return Json::Str(py_str(v)) };
                if sf.ctor.name() == dn && fields.len() == kids.len() {
                    if fields.is_empty() {
                        return Json::Str(tyname);
                    }
                    let mut parts: Vec<String> = Vec::new();
                    for (fd, c) in fields.iter().zip(kids.iter()) {
                        let k = self.fmt_g9_s(m, c, lim, depth + 1, Some(&fd.ty));
                        parts.push(format!("{}: {}", fd.name, k));
                    }
                    return Json::Str(format!("{} {{ {} }}", tyname, parts.join(", ")));
                }
            }
            TypeKind::Enum(variants) => {
                let Ok(infos) = model.enum_info(&ty) else { return Json::Str(py_str(v)) };
                for vd in variants {
                    let Some((_, vf)) = infos.iter().find(|(n, _)| *n == vd.name) else { return Json::Str(py_str(v)) };
                    if vf.ctor.name() == dn {
                        if vd.fields.is_empty() {
                            return Json::Str(format!("{}::{}", tyname, vd.name));
                        }
                        let mut ks: Vec<String> = Vec::new();
                        for (fd, c) in vd.fields.iter().zip(kids.iter()) {
                            ks.push(self.fmt_g9_s(m, c, lim, depth + 1, Some(&fd.ty)));
                        }
                        return Json::Str(format!("{}::{}({})", tyname, vd.name, ks.join(", ")));
                    }
                }
            }
        }
        Json::Str(py_str(v))
    }

    /// `fmt_val` of a value that is never an abstract top-level one (kept for callers that need the string form).
    #[allow(dead_code)]
    pub(crate) fn fmt_val(&self, v: &Ast) -> String {
        match self.fmt_val_j(v, true) {
            Json::Str(s) => s,
            _ => py_str(v),
        }
    }
}

/// Prototype output JSON:`{"sample","obligations":[{"seq","fn","line","col","code","attempts":[{"lemmas","smt2","result"}]}],"z3_version"}`.
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

fn opt_u32(v: Option<u32>) -> Json {
    match v {
        Some(n) => Json::int(n as i64),
        None => Json::Null,
    }
}

fn opt_str(v: &Option<String>) -> Json {
    match v {
        Some(s) => Json::Str(s.clone()),
        None => Json::Null,
    }
}

/// The `obligations` array of adapter `pruv-trace-v2` (key sorting is done by `dumps_sorted`).
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
                        ("status".to_string(), Json::str(&a.status)),
                        ("timeout_ms".to_string(), Json::int(a.timeout_ms as i64)),
                        ("rlimit".to_string(), opt_u32(a.rlimit)),
                        ("seed".to_string(), opt_u32(a.seed)),
                        ("reason_unknown".to_string(), opt_str(&a.reason_unknown)),
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
                ("phase".to_string(), Json::Str(o.phase.clone())),
                ("round".to_string(), opt_u32(o.round)),
                ("cand".to_string(), opt_str(&o.cand)),
            ];
            if o.skipped {
                kv.push(("skipped".to_string(), Json::Bool(true)));
            }
            // G4 A1: only in explicit mode (the output keys are sorted by dumps_sorted, like Python's sort_keys)
            if let Some(f) = &o.file {
                kv.push(("file".to_string(), Json::Str(f.clone())));
            }
            Json::Obj(kv)
        })
        .collect();
    Json::Arr(items)
}
