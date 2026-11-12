//! pruv-proof: a crate porting the z3 layer of the Python `pruvc/verify.py`.
//!
//! Layout (same structure as verify.py):
//! - `sys`        : a small wrapper over z3-sys. **unsafe lives only in this module** (see `deny` below).
//! - `model`      : `Opt`/`Res` Datatype, user struct/enum `Model`, `_MODEL_SEQ`
//! - `symbolic`   : `State`/`Arr`/`FnVerifier`: fresh, wf, havoc, aggregate lemmas, expression `ev`, domain `dom`, statement `exec`, `run`
//! - `obligation` : `prove` (pc → guard → (lemmas) → Not(ob), timeout 8000ms, seen key), counterexample `cex`/`fmt_val`, trace
//! - `samples`    : builders hand-porting the obligations of the 6 sample .pruv files (0B prototype; used by `pruv-proof-spike`)
//!
//! The public entry point is [`verify_program`]. For the same input, the SMT-LIB text passed to z3 per obligation, the verdicts and the error JSON
//! must be byte-identical to Python (SPEC §6).
//!
//! Why use sys directly instead of the high-level `z3` crate: the SMT text must match z3py character for character
//! (SPEC §6), and the high-level crate may differ from z3py in quantifier weight/qid, how Datatypes are created, etc.
//! The `z3` dependency is kept only to pull in z3-sys/z3-src via `vendored`.
#![deny(unsafe_code)]

#[allow(unsafe_code)]
pub mod sys;

pub mod infer;
pub mod model;
pub mod obligation;
pub mod samples;
pub mod symbolic;

use pruv_core::ast::Program;
use pruv_core::diagnostic::PruvError;
use pruv_core::typeinfo::TypeTable;

use crate::model::{decls_from_ast, next_seq, Model, Prelude};
use crate::obligation::Trace;
use crate::symbolic::FnVerifier;
use crate::sys::Z3;

/// Full version string of the running libz3 (counterpart of Python `z3.get_full_version()`).
pub fn z3_full_version() -> String {
    sys::full_version()
}

/// verify.py `verify_program(prog)` (line 864). Returns the proof errors of a program that passed checking, in function/obligation order.
///
/// - Python creates one `Model` for the whole program (incrementing `_MODEL_SEQ` once) shared by all functions. Here
///   the sequence number is taken once, and for each function the `Model` is rebuilt in a fresh z3 context with the same number (the expression text is identical).
/// - `tt` is unused: Python also builds a fresh `TypeTable(prog)` inside `Model(prog)` (the same table the checker built).
/// - `rec`: adapter trace recording (`Trace::adapter()`). If None, nothing is recorded.
/// - A Python exception (internal failure) becomes `Err(message)` — errors gathered so far are discarded (Python likewise returns no value on an exception).
pub fn verify_program(prog: &Program, tt: &TypeTable, rec: Option<&mut Trace>) -> Result<Vec<PruvError>, String> {
    verify_program_opts(prog, tt, rec, &VerifyOptions { infer: false }, None)
}

/// STAGE1 B2 options.
#[derive(Clone, Copy, Debug, Default)]
pub struct VerifyOptions {
    /// `--infer`: per function, run template Houdini invariant inference (infer.rs) and verify together with the surviving candidates.
    pub infer: bool,
}

/// verify.py `verify_program(prog, rec, infer, report)`. `infer=false` keeps the existing path unchanged.
/// If `report` is Some, per-loop report records (docs/STAGE1_B_INFER.md §5) are pushed in function order, then loop number order
/// (after finishing each function: even if a later function fails internally, earlier functions' records remain).
/// In inference mode a fresh z3 context (+Prelude, Model with the same seq) is created per function, per search round and per final verification.
pub fn verify_program_opts(
    prog: &Program,
    _tt: &TypeTable,
    rec: Option<&mut Trace>,
    opts: &VerifyOptions,
    mut report: Option<&mut Vec<pruv_core::pyjson::Json>>,
) -> Result<Vec<PruvError>, String> {
    if let Some(e) = pruv_core::typeinfo::s5_unimplemented_error(prog) { return Ok(vec![e]); }
    // G3 A2: the verifier handles generics (no guard here); the code generators and the driver still reject them.
    // The structured `[T]` is never a G2 hit (the plain `[i64]` is not either), so "array" needs no skip entry.
    if let Some(e) = pruv_core::typeinfo::g2_unimplemented_error(prog, "verify", None, &["array_u8", "array_bool", "str"], None) { return Ok(vec![e]); } // G2 B1
    let mut local = Trace::off();
    let trace: &mut Trace = match rec {
        Some(t) => t,
        None => &mut local,
    };
    let decls = decls_from_ast(&prog.types);
    let seq = next_seq();
    {
        // Python builds the Model first regardless of the function count: a model construction failure occurs even with no functions.
        let z = Z3::new();
        let pre = Prelude::new(&z);
        Model::for_program(&z, &pre, &decls, prog, seq)?;
    }
    let mut errors: Vec<PruvError> = Vec::new();
    if opts.infer {
        for f in &prog.functions {
            let res = infer::infer_function(prog, f, &decls, seq, &mut *trace)?;
            let before = errors.len();
            if res.status == infer::InferStatus::Timeout {
                errors.push(PruvError {
                    stage: "verify".to_string(),
                    line: f.line,
                    col: f.col,
                    code: "inference_timeout".to_string(),
                    message: format!(
                        "invariant inference for {} hit the time safety limit (5 s per function, 500 ms per query)",
                        f.name
                    ),
                    fix: "write the loop invariants explicitly, or compile without --infer".to_string(),
                    counterexample: None,
                });
            } else {
                let z = Z3::new();
                let pre = Prelude::new(&z);
                let model = Model::for_program(&z, &pre, &decls, prog, seq)?;
                let mut fv = FnVerifier::for_function(&z, &pre, &model, &mut *trace, prog, f);
                fv.set_extra(res.extra());
                fv.run()?;
                errors.append(&mut fv.errors);
            }
            if let Some(rep) = report.as_mut() {
                rep.extend(res.records(errors.len() - before));
            }
        }
        return Ok(errors);
    }
    for f in &prog.functions {
        // A fresh context per function (a non-rc context never frees ASTs, so it is dropped wholesale when the function ends).
        // Counterexample model values may differ from Python (the SMT text and verdicts are the same). Suspected cause: z3py uses an rc context, so AST ids are reused
        // and the chosen model differs (switching to one context per program left the counterexample difference unchanged, RESULTS §18).
        let z = Z3::new();
        let pre = Prelude::new(&z);
        let model = Model::for_program(&z, &pre, &decls, prog, seq)?;
        let mut fv = FnVerifier::for_function(&z, &pre, &model, &mut *trace, prog, f);
        fv.run()?;
        errors.append(&mut fv.errors);
    }
    Ok(errors)
}
