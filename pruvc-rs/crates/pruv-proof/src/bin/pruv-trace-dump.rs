//! Usage: pruv-trace-dump [--infer] [--no-verify] [--trust-callers] [--contract-budget N] FILE
//! (any other "--" option or a wrong FILE count exits with code 2). options is {"infer","no_verify"}.
//! `--no-verify`: do not run verification (obligations [], no timeout_ms). --trust-callers and --contract-budget do not affect proofs.
//! `--infer`: options {"infer":true}, and a top-level "inference" (array of per-loop report records; [] even on read/parse/check errors) is added.
//! Takes one file (a new process per input: `_MODEL_SEQ` starts at 0) and writes one line to stdout.
//! The output must be byte-identical to the Python `diff_py_adapter.trace_result(path, True)` passed through `json.dumps(sort_keys=True, ensure_ascii=False)`:
//!   {"errors":[...], "obligations":[{"attempts":[{"lemmas","reason_unknown","result","rlimit","seed","smt2","status","timeout_ms"}],
//!    "cand","code","col","fn","line","phase","round","seq"[,"skipped"]}],
//!    "options":{"infer":false}, "schema":"pruv-trace-v2", "timeout_ms":N}
//! On a parse/check error, errors holds that single error, obligations is an empty list and timeout_ms is absent (options is always present).
//! An internal prover failure puts a single `internal_error` in errors (obligations recorded so far and timeout_ms are kept).
//! Read/decode failures yield internal_error like the adapter (Python exception sentence, pruv_core::pyio).

use std::io::Write;

use pruv_core::pyjson::{dumps_sorted, Json};
use pruv_proof::obligation::{adapter_obligations_json, Trace};
use pruv_proof::symbolic::TIMEOUT_MS;
use pruv_proof::{verify_program_opts, VerifyOptions};

/// The adapter's `internal_err(e)`.
fn internal_err(msg: &str) -> Json {
    Json::Obj(vec![
        ("stage".to_string(), Json::str("internal")),
        ("line".to_string(), Json::int(0)),
        ("col".to_string(), Json::int(0)),
        ("code".to_string(), Json::str("internal_error")),
        ("message".to_string(), Json::str(msg)),
        ("fix".to_string(), Json::str("")),
    ])
}

/// infer: only with `--infer` is a top-level `inference` (report record array) emitted (adapter: present as `[]` even on read/parse/check errors).
fn output(
    errors: Vec<Json>,
    trace: &Trace,
    timeout: Option<u32>,
    infer: bool,
    no_verify: bool,
    inference: Vec<Json>,
) -> String {
    let mut kv = vec![
        ("schema".to_string(), Json::str("pruv-trace-v2")),
        (
            "options".to_string(),
            Json::Obj(vec![
                ("infer".to_string(), Json::Bool(infer)),
                ("no_verify".to_string(), Json::Bool(no_verify)),
            ]),
        ),
        ("errors".to_string(), Json::Arr(errors)),
        ("obligations".to_string(), adapter_obligations_json(trace)),
    ];
    if let Some(t) = timeout {
        kv.push(("timeout_ms".to_string(), Json::int(t as i64)));
    }
    if infer {
        kv.push(("inference".to_string(), Json::Arr(inference)));
    }
    dumps_sorted(&Json::Obj(kv))
}

/// G9 A0: the adapter's guard right after the check (verify on -> stage "verify" / layer "verifier"; else the rust backend).
fn g9_guard(prog: &pruv_core::ast::Program, no_verify: bool) -> Option<pruv_core::diagnostic::PruvError> {
    if no_verify {
        pruv_core::typeinfo::g9_unimplemented_error(prog, "codegen", "rust codegen layer")
    } else {
        pruv_core::typeinfo::g9_unimplemented_error(prog, "verify", "verifier")
    }
}

fn run(path: &std::ffi::OsStr, infer: bool, no_verify: bool) -> String {
    // Like the adapter's trace_result, read/decode failures are also reported as internal_error (Python exception sentence) (audit must-fix 1).
    let src = match pruv_core::pyio::read_source(std::path::Path::new(path)) {
        Ok(s) => s,
        Err(msg) => return output(vec![internal_err(&msg)], &Trace::adapter(), None, infer, no_verify, Vec::new()),
    };
    let mut errors: Vec<Json> = Vec::new();
    let mut trace = Trace::adapter();
    let mut timeout: Option<u32> = None;
    let mut report: Vec<Json> = Vec::new();
    match pruv_core::parse(&src) {
        Err(e) => errors.push(e.to_json_value()),
        Ok(mut prog) => match pruv_core::check::check(&mut prog) {
            Err(e) => errors.push(e.to_json_value()),
            // G9 A0: same guard as pruvc compile_file (the rust backend is the default code generator here): the
            // error is the only entry, no obligations, no timeout_ms.
            Ok(_) if g9_guard(&prog, no_verify).is_some() => {
                if let Some(e) = g9_guard(&prog, no_verify) {
                    errors.push(e.to_json_value());
                }
            }
            // --no-verify: do not run verification (obligations [], no timeout_ms).
            Ok(_) if no_verify => {}
            Ok(tt) => {
                timeout = Some(TIMEOUT_MS);
                let opts = VerifyOptions { infer };
                let rep = if infer { Some(&mut report) } else { None };
                match verify_program_opts(&prog, &tt, Some(&mut trace), &opts, rep) {
                    Ok(errs) => errors.extend(errs.iter().map(|e| e.to_json_value())),
                    Err(msg) => errors.push(internal_err(&msg)),
                }
            }
        },
    }
    output(errors, &trace, timeout, infer, no_verify, report)
}

fn main() {
    let args: Vec<std::ffi::OsString> = std::env::args_os().skip(1).collect();
    // Separate options (starting with "--") from FILE. Known option: --infer.
    let mut files: Vec<std::ffi::OsString> = Vec::new();
    let mut unknown: Vec<String> = Vec::new();
    let mut infer = false;
    let mut no_verify = false;
    let mut args = args.into_iter();
    while let Some(a) = args.next() {
        let s = a.to_string_lossy().into_owned();
        if s == "--infer" {
            infer = true;
        } else if s == "--no-verify" {
            no_verify = true;
        } else if s == "--trust-callers" {
            // No effect on proofs: just accept it.
        } else if s == "--contract-budget" {
            // Takes one value (no effect on proofs). A missing value is a usage error.
            if args.next().is_none() {
                eprintln!("pruv-trace-dump: --contract-budget needs a value");
                std::process::exit(2);
            }
        } else if a.to_string_lossy().starts_with("--") {
            unknown.push(a.to_string_lossy().into_owned());
        } else {
            files.push(a);
        }
    }
    if !unknown.is_empty() {
        eprintln!("pruv-trace-dump: unknown option(s): {}", unknown.join(" "));
        std::process::exit(2);
    }
    if files.len() != 1 {
        eprintln!("usage: pruv-trace-dump [OPTIONS] FILE");
        std::process::exit(2);
    }
    let path = files.remove(0);
    // Run on a 1GB-stack thread for deeply nested input (parser, checker and symbolic execution are all recursive).
    let handle = std::thread::Builder::new().stack_size(1 << 30).spawn(move || run(&path, infer, no_verify));
    // A panic or thread-creation failure exits with a nonzero code so the differential tool counts it as rs_crash.
    let line = match handle.map(|h| h.join()) {
        Ok(Ok(s)) => s,
        _ => {
            eprintln!("pruv-trace-dump: internal failure");
            std::process::exit(3);
        }
    };
    let stdout = std::io::stdout();
    let mut lock = stdout.lock();
    if lock.write_all(line.as_bytes()).is_err() || lock.write_all(b"\n").is_err() || lock.flush().is_err() {
        std::process::exit(1);
    }
}
