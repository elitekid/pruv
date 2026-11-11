//! 컴파일 파이프라인. Python `compile_file` 순서 그대로:
//! 읽기 → parse → check → (verify) → 출력 종류별 생성 → 모든 텍스트가 만들어진 뒤에야 파일 쓰기.

use crate::cli::{Args, Kind};
use pruv_core::ast::Program;
use pruv_core::diagnostic::PruvError;
use pruvc::link::{self, RuntimeChoice};
use pruvc::runtime::{self, Variant};
use pruvc::target::Target;
use std::io::Write;
use std::path::Path;

/// exe 의 C 진입 shim. `main__pruv_entry` 는 llvmgen::entry_of 가 내는 `define internal void` (인자 없는 unit main).
const MAIN_SHIM: &str = "define i32 @main() {\n  call void @main__pruv_entry()\n  ret i32 0\n}\n";

enum Fail {
    /// 언어·증명 오류(각각 한 줄, exit 1).
    Lang(Vec<PruvError>),
    /// 새 빌드 진단(stage link/codegen, exit 1). 둘째는 stderr 에 남길 원문.
    Build(PruvError, Option<String>),
    /// 내부 오류(exit 3).
    Internal(String),
}

fn out_line(s: &str) {
    let stdout = std::io::stdout();
    let mut l = stdout.lock();
    let _ = l.write_all(s.as_bytes());
    let _ = l.write_all(b"\n");
    let _ = l.flush();
}

/// Python `json.dumps` 기본값(ensure_ascii=True)과 같은 문자열 이스케이프.
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

/// 내부 오류 JSON 한 줄(Python 과 같은 키 순서·구분자).
pub fn internal_json(msg: &str) -> String {
    let mut s = String::from("{\"stage\": \"internal\", \"line\": 0, \"col\": 0, \"code\": \"internal_error\", \"message\": ");
    push_ascii_json_str(&mut s, msg);
    s.push_str(", \"fix\": \"\"}");
    s
}

/// 파이프라인을 돌려 종료 코드를 돌려준다.
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

// 실패 문장은 Python open(path, "w") 의 OSError 와 같게(감사 필수 1).
fn write_text(path: &str, text: &str) -> Result<(), Fail> {
    std::fs::write(path, text).map_err(|e| Fail::Internal(pruv_core::pyio::io_error_message(Path::new(path), &e)))
}

fn generate(a: &Args, prog: &Program) -> Result<(String, String), Fail> {
    // 6단계: Windows x64 대상이면 외부 wrapper 를 처음부터 대상 ABI(sret)로, 그 밖은 기존(Python 과 바이트 동일) 출력.
    // --target 이 없으면 호스트 대상(설계 3절 "기본 호스트"). Windows 호스트의 ll 도 sret 형태여야 한다(6단계 감사 필수).
    let host = pruvc::target::Target::host().ok();
    let windows = match (&a.target, &host) {
        (Some(t), _) => t.is_windows(),
        (None, Some(h)) => h.is_windows(),
        (None, None) => false,
    };
    let abi = if windows { pruv_core::abi::AbiTarget::WinX64 } else { pruv_core::abi::AbiTarget::SysV };
    pruv_core::llvmgen::gen_llvm_for(prog, a.verify, a.trust_callers, a.budget, abi).map_err(Fail::Internal)
}

fn need_target(a: &Args) -> Result<&Target, Fail> {
    a.target.as_ref().ok_or_else(|| Fail::Internal("target was not resolved".to_string()))
}

/// compile_ir_to_object 의 오류: 대상·방출 문제는 codegen 진단(exit 1), IR 자체 결함은 내부 오류.
fn codegen_fail(e: pruvc::Error) -> Fail {
    match e.code {
        "llvm_target" | "llvm_emit" | "target_mismatch" | "unsupported" | "unsupported_target" => {
            Fail::Build(PruvError::new("codegen", 0, 0, e.code, e.message, ""), None)
        }
        _ => Fail::Internal(e.to_string()),
    }
}

/// link::link 의 오류를 설계 3절의 link 진단으로.
fn link_fail(e: pruvc::Error) -> Fail {
    match e.code {
        "io" | "no_main" | "invalid_argument" | "object_read" | "llvm_error" => Fail::Internal(e.to_string()),
        "link_spawn" => Fail::Build(PruvError::new("link", 0, 0, "linker_missing", e.message, ""), None),
        "link_failed" => {
            // 진단에는 원인 한 줄(링커의 error/ld: 줄, 경고 제외, 없으면 첫 줄), 링커 원문은 stderr 로(감사 권고)
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

/// exe 진입점: `fn main() -> ()` 이고 매개변수가 없어야 한다.
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

/// 대상이 호스트가 아니거나 그 대상의 내장 런타임이 없으면 target_runtime_missing.
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
    // 읽기 실패·UTF-8 해독 실패는 내부 오류(Python open().read() 와 같은 취급)
    let src = pruv_core::pyio::read_source(Path::new(&a.input)).map_err(Fail::Internal)?;
    // 깊이 한도 초과는 파서가 stage "internal" 로 알린다(Python RecursionError 처럼 exit 3).
    let mut prog = pruv_core::parse(&src).map_err(|e| if e.stage == "internal" { Fail::Internal(e.message) } else { Fail::Lang(vec![e]) })?;
    let tt = pruv_core::check::check(&mut prog).map_err(|e| Fail::Lang(vec![e]))?;
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
            // 내부 오류(Err)면 Python 은 예외로 아무것도 찍지 않는다. Ok 일 때만(검증 오류가 있어도) 기록을 남긴다.
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
    } else if a.infer && a.show_inferred {
        eprintln!("{{\"status\": \"skipped_no_verify\"}}");
    }
    // G2: verify 뒤에도, 아직 코드 생성 층이 없는 배열 타입은 거부.
    // A4·A5: [u8]·[bool] 은 모든 길(rust·llvm·ll·obj·exe·also_llvm)에서 허용.
    let g2_err = pruv_core::typeinfo::g2_unimplemented_error(&prog, "codegen", None, &["array_u8", "array_bool"], None); // G2 A5
    if let Some(e) = g2_err {
        return Err(Fail::Lang(vec![e]));
    }
    match a.kind {
        // 7단계: Rust 소스 뒷단. Python compile_file 처럼 모든 텍스트(rs, 그리고 --also-llvm 이면 ll·바인딩)를
        // 먼저 만들고 나서 파일을 쓴다(생성기 오류면 아무 파일도 쓰지 않음). 쓰는 순서: OUT, LL, RS.
        Kind::Rs => {
            let rs_text = pruv_core::codegen::gen_rust(&prog, a.verify, a.trust_callers, a.budget).map_err(Fail::Internal)?;
            let llvm_texts = match &a.also_llvm {
                Some(_) => Some(generate(a, &prog)?),
                None => None,
            };
            write_text(&a.out, &rs_text)?;
            if let (Some((ll, rs)), Some((ir, bindings))) = (&a.also_llvm, llvm_texts) {
                write_text(ll, &ir)?;
                write_text(rs, &bindings)?;
            }
            Ok(())
        }
        Kind::Ll => {
            let (ir, bindings) = generate(a, &prog)?;
            // Python 과 같은 순서: IR 먼저, 바인딩 다음
            write_text(&a.out, &ir)?;
            match &a.bindings {
                Some(b) => write_text(b, &bindings),
                None => Err(Fail::Internal("missing bindings path".to_string())),
            }
        }
        Kind::Obj => {
            let target = need_target(a)?;
            let (ir, bindings) = generate(a, &prog)?;
            // 객체는 임시 폴더에 만들어 성공했을 때만 -o 로 옮긴다(실패 시 기존 파일을 건드리지 않음)
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
            let (mut ir, _) = generate(a, &prog)?;
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
