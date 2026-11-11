//! Checks that the full port (`verify_program`) yields, on the 6 samples, the same obligation sequence, SMT-LIB and verdicts
//! as the 0B prototype (hand-written builder, confirmed to match the Python implementation in SMT text and verdicts). Verdicts may depend on the time limit, but the samples are small.

use pruv_proof::model::reset_model_seq;
use pruv_proof::obligation::Trace;
use pruv_proof::samples::{run_sample, sample_names};
use pruv_proof::verify_program;

fn full_trace(name: &str) -> Trace {
    let path = format!("{}/samples/{}.pruv", env!("CARGO_MANIFEST_DIR"), name);
    let src = std::fs::read_to_string(&path).expect("sample file");
    let mut prog = pruv_core::parse(&src).expect("parse");
    let tt = pruv_core::check::check(&mut prog).expect("check");
    reset_model_seq();
    let mut trace = Trace::adapter();
    verify_program(&prog, &tt, Some(&mut trace)).expect("verify");
    trace
}

#[test]
fn full_port_matches_spike_on_samples() {
    for name in sample_names() {
        let spike = run_sample(name).expect("sample");
        let spike_obs = spike["obligations"].as_array().expect("obligations");
        let trace = full_trace(name);
        // the prototype does not record skipped entries (key already failed, so no query)
        let mine: Vec<_> = trace.obligations.iter().filter(|o| !o.skipped).collect();
        assert_eq!(spike_obs.len(), mine.len(), "{name}: obligation count");
        for (i, (a, b)) in spike_obs.iter().zip(mine.iter()).enumerate() {
            let at = format!("{name} #{i}");
            assert_eq!(a["fn"].as_str(), Some(b.fn_name.as_str()), "{at}: fn");
            assert_eq!(a["line"].as_u64(), Some(b.line as u64), "{at}: line");
            assert_eq!(a["col"].as_u64(), Some(b.col as u64), "{at}: col");
            assert_eq!(a["code"].as_str(), Some(b.code.as_str()), "{at}: code");
            let attempts = a["attempts"].as_array().expect("attempts");
            assert_eq!(attempts.len(), b.attempts.len(), "{at}: attempts");
            for (x, y) in attempts.iter().zip(b.attempts.iter()) {
                assert_eq!(x["lemmas"].as_bool(), Some(y.lemmas), "{at}: lemmas flag");
                assert_eq!(x["smt2"].as_str(), Some(y.smt2.as_str()), "{at}: smt2");
                assert_eq!(x["result"].as_str(), Some(y.result.as_str()), "{at}: result");
            }
        }
    }
}

#[test]
fn adapter_trace_numbers_from_zero() {
    let trace = full_trace("s1_sum_loop");
    assert!(!trace.obligations.is_empty());
    for (i, o) in trace.obligations.iter().enumerate() {
        assert_eq!(o.seq as usize, i);
        if o.skipped {
            assert!(o.attempts.is_empty());
        }
    }
}
