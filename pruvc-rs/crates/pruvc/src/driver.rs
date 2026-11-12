//! Compile pipeline, in exactly the order of Python `compile_file`:
//! read -> parse -> check -> (verify) -> generation per output kind -> files are written only after all the text has been produced.

use crate::cli::{Args, Kind};
use pruv_core::ast::Program;
use pruv_core::diagnostic::PruvError;
use pruvc::link::{self, RuntimeChoice};
use pruvc::runtime::{self, Variant};
use pruvc::target::Target;
use std::io::Write;
use std::path::Path;

/// The C entry shim of exe. `main__pruv_entry` is the `define internal void` emitted by llvmgen::entry_of (a unit main with no arguments).
const MAIN_SHIM: &str = "define i32 @main() {\n  call void @main__pruv_entry()\n  ret i32 0\n}\n";

enum Fail {
    /// Language and proof errors (one line each, exit 1).
    Lang(Vec<PruvError>),
    /// New build diagnostics (stage link/codegen, exit 1). The second is the raw text to leave on stderr.
    Build(PruvError, Option<String>),
    /// Internal error (exit 3).
    Internal(String),
}

fn out_line(s: &str) {
    let stdout = std::io::stdout();
    let mut l = stdout.lock();
    let _ = l.write_all(s.as_bytes());
    let _ = l.write_all(b"\n");
    let _ = l.flush();
}

/// String escaping identical to the Python `json.dumps` default (ensure_ascii=True).
fn push_ascii_json_str(out: &mut String, s: &str) {
    out.push('"');
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{8}' => out.push_str("\\b"),
            '\u{c}' => out.push_str("\\f"),
            c if c >= ' ' && c <= '~' => out.push(c),
            c => {
                let mut buf = [0u16; 2];
                for u in c.encode_utf16(&mut buf) {
                    out.push_str(&format!("\\u{:04x}", u));
                }
            }
        }
    }
    out.push('"');
}

/// One internal-error JSON line (same key order and separators as Python).
pub fn internal_json(msg: &str) -> String {
    let mut s = String::from("{\"stage\": \"internal\", \"line\": 0, \"col\": 0, \"code\": \"internal_error\", \"message\": ");
    push_ascii_json_str(&mut s, msg);
    s.push_str(", \"fix\": \"\"}");
    s
}

/// Runs the pipeline and returns the exit code.
pub fn run(a: &Args) -> i32 {
    match compile(a) {
        Ok(()) => {
            out_line("{\"ok\": true}");
            0
        }
        Err(Fail::Lang(errs)) => {
            for e in &errs {
                out_line(&e.to_cli_json());
            }
            1
        }
        Err(Fail::Build(e, raw)) => {
            if let Some(t) = raw {
                eprintln!("{}", t.trim_end());
            }
            out_line(&e.to_cli_json());
            1
        }
        Err(Fail::Internal(m)) => {
            out_line(&internal_json(&m));
            3
        }
    }
}

// The failure message matches the OSError of Python open(path, "w") (audit must-fix 1).
fn write_text(path: &str, text: &str) -> Result<(), Fail> {
    std::fs::write(path, text).map_err(|e| Fail::Internal(pruv_core::pyio::io_error_message(Path::new(path), &e)))
}

fn generate(a: &Args, prog: &Program) -> Result<(String, String), Fail> {
    // Stage 6: for a Windows x64 target the external wrapper uses the target ABI (sret) from the start; otherwise the existing output (byte-identical to Python).
    // Without --target the host target is used (design §3 "default host"). The ll of a Windows host must also be in sret form (stage 6 audit must-fix).
    let host = pruvc::target::Target::host().ok();
    let windows = match (&a.target, &host) {
        (Some(t), _) => t.is_windows(),
        (None, Some(h)) => h.is_windows(),
        (None, None) => false,
    };
    let abi = if windows { pruv_core::abi::AbiTarget::WinX64 } else { pruv_core::abi::AbiTarget::SysV };
    // `prog` is the CONCRETE program (the specialization plan of a generic program, see `compile`).
    // G6 A3: foreign_checks reaches the shim helpers; a G6 construct outside G6_SPEC 13.1 is a codegen/unsupported_type
    // diagnostic (nothing is written), like Python's PruvError from gen_llvm.
    pruv_core::llvmgen::gen_llvm_concrete_ex(prog, a.verify, a.trust_callers, a.budget, abi, &a.foreign_checks).map_err(|e| match e {
        pruv_core::codegen::GenError::Diag(p) => Fail::Lang(vec![p]),
        pruv_core::codegen::GenError::Msg(m) => Fail::Internal(m),
    })
}

/// G6_SPEC 13.1: `--emit exe|obj` of a G6 program needs the Rust host build (the shim lives in the generated bindings).
fn foreign_target_error(prog: &Program) -> Option<PruvError> {
    pruv_core::foreign::first_g6_use(prog)?;
    Some(PruvError::new(
        "codegen",
        0,
        0,
        "foreign_target",
        "a G6 program on the LLVM backend needs the Rust host build (generated bindings compiled by rustc)",
        "emit LLVM IR and Rust bindings (--backend llvm --rust-bindings PATH) and compile the bindings with rustc",
    ))
}

fn need_target(a: &Args) -> Result<&Target, Fail> {
    a.target.as_ref().ok_or_else(|| Fail::Internal("target was not resolved".to_string()))
}

/// Errors of compile_ir_to_object: target and emission problems become a codegen diagnostic (exit 1), defects in the IR itself become an internal error.
fn codegen_fail(e: pruvc::Error) -> Fail {
    match e.code {
        "llvm_target" | "llvm_emit" | "target_mismatch" | "unsupported" | "unsupported_target" => {
            Fail::Build(PruvError::new("codegen", 0, 0, e.code, e.message, ""), None)
        }
        _ => Fail::Internal(e.to_string()),
    }
}

/// Turns an error of link::link into the link diagnostic of design §3.
fn link_fail(e: pruvc::Error) -> Fail {
    match e.code {
        "io" | "no_main" | "invalid_argument" | "object_read" | "llvm_error" => Fail::Internal(e.to_string()),
        "link_spawn" => Fail::Build(PruvError::new("link", 0, 0, "linker_missing", e.message, ""), None),
        "link_failed" => {
            // The diagnostic gets one cause line (the linker's error/ld: line, warnings excluded, the first line if none); the raw linker text goes to stderr (audit recommendation)
            let first = e
                .message
                .lines()
                .find(|l| !l.contains("warning") && (l.contains("error") || l.trim_start().starts_with("ld:")))
                .or_else(|| e.message.lines().next())
                .unwrap_or("")
                .to_string();
            Fail::Build(PruvError::new("link", 0, 0, "link_failed", first, ""), Some(e.message))
        }
        code => Fail::Build(PruvError::new("link", 0, 0, code, e.message, ""), None),
    }
}

/// The exe entry point: must be `fn main() -> ()` with no parameters.
fn check_entry(prog: &Program) -> Result<(), Fail> {
    let m = prog.functions.iter().find(|f| f.name == "main");
    if m.map_or(false, |f| f.params.is_empty() && f.ret == "unit") {
        return Ok(());
    }
    let (line, col) = m.map_or((0, 0), |f| (f.line, f.col));
    Err(Fail::Build(
        PruvError::new(
            "link",
            line,
            col,
            "exe_entry",
            "--emit exe needs `fn main() -> ()` without parameters",
            "add `fn main() -> () ! io { ... }`",
        ),
        None,
    ))
}

/// target_runtime_missing if the target is not the host or has no built-in runtime.
fn check_runtime(target: &Target) -> Result<(), Fail> {
    let msg = if !target.is_host() {
        Some(format!(
            "cannot build an executable for non-host target {} (this build embeds the runtime for {} only)",
            target.public,
            runtime::EMBEDDED_TARGET
        ))
    } else {
        runtime::object(target, Variant::Malloc, false).err().map(|e| e.message)
    };
    match msg {
        None => Ok(()),
        Some(m) => Err(Fail::Build(PruvError::new("link", 0, 0, "target_runtime_missing", m, ""), None)),
    }
}

fn compile(a: &Args) -> Result<(), Fail> {
    // A read failure or UTF-8 decode failure is an internal error (handled like Python open().read())
    let src = pruv_core::pyio::read_source(Path::new(&a.input)).map_err(Fail::Internal)?;
    // Exceeding the depth limit is reported by the parser as stage "internal" (exit 3, like Python RecursionError).
    let mut prog = pruv_core::parse(&src).map_err(|e| if e.stage == "internal" { Fail::Internal(e.message) } else { Fail::Lang(vec![e]) })?;
    let tt = pruv_core::check::check_with_externs(&mut prog, &a.rust_extern).map_err(|e| Fail::Lang(vec![e]))?;
    // G9 A3: both back ends lower G9 programs; the G9 staging guard is gone from the driver.
    // G6: the Rust source backend lowers foreign calls and collections (A2); the LLVM backend (and --also-llvm) lowers
    // the G6_SPEC 13.1 subset (A3) and rejects everything else with codegen/unsupported_type inside the LLVM generator
    // (after verification, so verification errors win; same as Python compile_file). The native paths (--emit obj|exe),
    // which Python does not have, cannot link the Rust shim: codegen/foreign_target (G6_SPEC 13.1). With --no-verify
    // that check fires right after the check; otherwise after verification.
    let g6_native = matches!(a.kind, Kind::Obj | Kind::Exe);
    if !a.verify && g6_native {
        if let Some(e) = foreign_target_error(&prog) {
            return Err(Fail::Lang(vec![e]));
        }
    }
    if a.verify {
        let errs = if a.infer {
            let opts = pruv_proof::VerifyOptions { infer: true };
            let mut report: Vec<pruv_core::pyjson::Json> = Vec::new();
            let r = pruv_proof::verify_program_opts(
                &prog,
                &tt,
                None,
                &opts,
                if a.show_inferred { Some(&mut report) } else { None },
            );
            // On an internal error (Err), Python prints nothing because of the exception. The record is left only when Ok (even if there is a verification error).
            let errs = r.map_err(Fail::Internal)?;
            for rec in &report {
                eprintln!("{}", pruv_core::pyjson::dumps_sorted(rec));
            }
            errs
        } else {
            pruv_proof::verify_program(&prog, &tt, None).map_err(Fail::Internal)?
        };
        if !errs.is_empty() {
            return Err(Fail::Lang(errs));
        }
        if g6_native {
            if let Some(e) = foreign_target_error(&prog) {
                return Err(Fail::Lang(vec![e]));
            }
        }
    } else if a.infer && a.show_inferred {
        eprintln!("{{\"status\": \"skipped_no_verify\"}}");
    }
    // G3 A3/A4 (same place as in Python compile_file): every backend (rust, llvm, also --also-llvm) specializes generic
    // programs through the shared plan (mono.rs) and generates from the concrete program.
    let mut plan_prog: Option<Program> = None;
    if pruv_core::typeinfo::first_g3_use(&prog).is_some() {
        match pruv_core::mono::specialize(&prog) {
            Ok(plan) => plan_prog = Some(plan.program),
            Err(pruv_core::mono::MonoError::Limit(e)) => return Err(Fail::Lang(vec![e])), // no output at all
            Err(pruv_core::mono::MonoError::Internal(m)) => return Err(Fail::Internal(m)),
        }
    }
    let gprog: &Program = plan_prog.as_ref().unwrap_or(&prog);
    // G2: even after verify, reject array types that do not yet have a code-generation layer.
    // A4, A5: [u8] and [bool] are allowed on every path (rust, llvm, ll, obj, exe, also_llvm).
    let g2_err = pruv_core::typeinfo::g2_unimplemented_error(gprog, "codegen", None, &["array_u8", "array_bool", "str"], None); // G2 B2
    if let Some(e) = g2_err {
        return Err(Fail::Lang(vec![e]));
    }
    match a.kind {
        // Stage 7: the Rust-source backend. Like Python compile_file, all the text (rs, and with --also-llvm also ll and bindings)
        // is produced first and only then are files written (on a generator error no file is written). Write order: OUT, LL, RS.
        Kind::Rs => {
            let (rs_text, manifest) = pruv_core::codegen::gen_rust_concrete_ex(
                gprog,
                a.verify,
                a.trust_callers,
                a.budget,
                &a.foreign_checks,
                &a.rust_extern_specs,
            )
            .map_err(|e| match e {
                // G9 A2: a runtime requires the Rust backend cannot lower yet is a diagnostic (Python PruvError)
                pruv_core::codegen::GenError::Diag(p) => Fail::Lang(vec![p]),
                pruv_core::codegen::GenError::Msg(m) => Fail::Internal(m),
            })?;
            let llvm_texts = match &a.also_llvm {
                Some(_) => Some(generate(a, gprog)?),
                None => None,
            };
            write_text(&a.out, &rs_text)?;
            if let Some(m) = &manifest {
                // G6_SPEC 12.4: <out>.foreign.json, only for a program that uses G6
                write_text(&format!("{}.foreign.json", a.out), m)?;
            }
            if let (Some((ll, rs)), Some((ir, bindings))) = (&a.also_llvm, llvm_texts) {
                write_text(ll, &ir)?;
                write_text(rs, &bindings)?;
            }
            Ok(())
        }
        Kind::Ll => {
            let (ir, bindings) = generate(a, gprog)?;
            // Same order as Python: IR first, then the bindings
            write_text(&a.out, &ir)?;
            match &a.bindings {
                Some(b) => write_text(b, &bindings),
                None => Err(Fail::Internal("missing bindings path".to_string())),
            }
        }
        Kind::Obj => {
            let target = need_target(a)?;
            let (ir, bindings) = generate(a, gprog)?;
            // The object is built in a temporary folder and moved to -o only on success (an existing file is not touched on failure)
            let tmp = tempfile::tempdir().map_err(|e| Fail::Internal(format!("tempdir: {e}")))?;
            let obj = tmp.path().join("out.o");
            pruvc::llvm::compile_ir_to_object(ir.as_bytes(), &a.input, target, &a.cpu, &obj).map_err(codegen_fail)?;
            std::fs::copy(&obj, &a.out).map_err(|e| Fail::Internal(pruv_core::pyio::io_error_message(Path::new(&a.out), &e)))?;
            match &a.bindings {
                Some(b) => write_text(b, &bindings),
                None => Ok(()),
            }
        }
        Kind::Exe => {
            let target = need_target(a)?;
            check_entry(&prog)?;
            check_runtime(target)?;
            let (mut ir, _) = generate(a, gprog)?;
            if !ir.ends_with('\n') {
                ir.push('\n');
            }
            ir.push('\n');
            ir.push_str(MAIN_SHIM);
            let tmp = tempfile::tempdir().map_err(|e| Fail::Internal(format!("tempdir: {e}")))?;
            let obj = tmp.path().join("prog.o");
            pruvc::llvm::compile_ir_to_object(ir.as_bytes(), &a.input, target, &a.cpu, &obj).map_err(codegen_fail)?;
            link::link(&[obj], Path::new(&a.out), target, RuntimeChoice::Malloc).map_err(link_fail)
        }
    }
}
