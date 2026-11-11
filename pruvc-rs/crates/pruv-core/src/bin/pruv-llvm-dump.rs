//! Usage: pruv-llvm-dump [--no-verify] [--trust-callers] [--budget N] FILE...
//! Writes exactly one line (UTF-8, ending with \n) per file to stdout, in order.
//! After parse+check (the verifier is not run), the gen_llvm result is emitted as {"bindings", "ir"}, and errors as {"error"|"internal"|"adapter_error"}.
//! Each line is flushed immediately: even if one file overflows the stack and aborts, the lines of earlier files remain.

use pruv_core::pyjson::{dumps_sorted, Json};
use std::io::Write;

struct Opts {
    verified: bool,
    trust_callers: bool,
    budget: u64,
    target: pruv_core::abi::AbiTarget,
    files: Vec<std::ffi::OsString>,
}

fn obj1(k: &str, v: Json) -> String {
    dumps_sorted(&Json::Obj(vec![(k.to_string(), v)]))
}

fn line_for(bytes: &[u8], o: &Opts) -> String {
    let src = match std::str::from_utf8(bytes) {
        Ok(s) => s,
        Err(_) => return obj1("adapter_error", Json::str("decode")),
    };
    let mut prog = match pruv_core::parse(src) {
        Ok(p) => p,
        Err(e) => return obj1("error", e.to_json_value()),
    };
    if let Err(e) = pruv_core::check::check(&mut prog) {
        return obj1("error", e.to_json_value());
    }
    // like Python gen_llvm: a generic program is specialized first (a specialization limit is a diagnostic)
    match pruv_core::llvmgen::gen_llvm_any(&prog, o.verified, o.trust_callers, o.budget, o.target) {
        Ok((ir, bindings)) => dumps_sorted(&Json::Obj(vec![
            ("ir".to_string(), Json::Str(ir)),
            ("bindings".to_string(), Json::Str(bindings)),
        ])),
        Err(pruv_core::codegen::GenError::Diag(e)) => obj1("error", e.to_json_value()),
        Err(pruv_core::codegen::GenError::Msg(msg)) => obj1("internal", Json::Str(msg)),
    }
}

fn work(o: Opts) -> bool {
    let stdout = std::io::stdout();
    let mut lock = stdout.lock();
    for f in &o.files {
        let line = match std::fs::read(f) {
            Ok(bytes) => line_for(&bytes, &o),
            Err(_) => obj1("adapter_error", Json::str("io")),
        };
        if lock.write_all(line.as_bytes()).is_err() || lock.write_all(b"\n").is_err() || lock.flush().is_err() {
            return false;
        }
    }
    true
}

fn usage() -> ! {
    eprintln!("usage: pruv-llvm-dump [--no-verify] [--trust-callers] [--budget N] [--target TRIPLE] FILE...");
    std::process::exit(2);
}

fn main() {
    let mut o = Opts {
        verified: true,
        trust_callers: false,
        budget: 1 << 30,
        target: pruv_core::abi::AbiTarget::SysV,
        files: Vec::new(),
    };
    let mut it = std::env::args_os().skip(1);
    while let Some(a) = it.next() {
        match a.to_str() {
            Some("--no-verify") => o.verified = false,
            Some("--trust-callers") => o.trust_callers = true,
            Some("--budget") => match it.next().and_then(|v| v.to_str().and_then(|s| s.parse::<u64>().ok())) {
                Some(n) => o.budget = n,
                None => usage(),
            },
            Some("--target") => match it.next().as_ref().and_then(|v| v.to_str()) {
                Some("x86_64-pc-windows-msvc") => o.target = pruv_core::abi::AbiTarget::WinX64,
                Some("aarch64-apple-darwin") | Some("x86_64-apple-darwin") | Some("x86_64-unknown-linux-gnu") => {
                    o.target = pruv_core::abi::AbiTarget::SysV
                }
                _ => usage(),
            },
            _ => o.files.push(a),
        }
    }
    if o.files.is_empty() {
        usage();
    }
    // Run on a large-stack thread for deeply nested input.
    let handle = std::thread::Builder::new().stack_size(1 << 30).spawn(move || work(o));
    match handle.map(|h| h.join()) {
        Ok(Ok(true)) => {}
        _ => {
            eprintln!("pruv-llvm-dump: internal failure");
            std::process::exit(1);
        }
    }
}
