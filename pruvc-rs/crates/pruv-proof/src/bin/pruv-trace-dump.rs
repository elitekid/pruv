//! 사용법: pruv-trace-dump [--infer] [--no-verify] [--trust-callers] [--contract-budget N] FILE
//! (그 밖의 "--" 옵션·FILE 개수 오류는 종료 코드 2). options 는 {"infer","no_verify"}.
//! `--no-verify`: 검증을 돌리지 않는다(obligations [], timeout_ms 없음). --trust-callers·--contract-budget 은 증명에 영향 없다.
//! `--infer`: options {"infer":true}, 최상위 "inference"(루프별 보고 레코드 배열; 읽기·parse·check 오류여도 [])가 더해진다.
//! 파일 하나를 받아(입력마다 새 프로세스: `_MODEL_SEQ` 가 0 에서 시작) 한 줄을 stdout 에 쓴다.
//! 출력은 Python `diff_py_adapter.trace_result(path, True)` 를 `json.dumps(sort_keys=True, ensure_ascii=False)` 한 것과
//! 바이트 동일해야 한다:
//!   {"errors":[...], "obligations":[{"attempts":[{"lemmas","reason_unknown","result","rlimit","seed","smt2","status","timeout_ms"}],
//!    "cand","code","col","fn","line","phase","round","seq"[,"skipped"]}],
//!    "options":{"infer":false}, "schema":"pruv-trace-v2", "timeout_ms":N}
//! parse/check 오류면 errors 에 그 오류 하나, obligations 는 빈 목록이고 timeout_ms 는 없다(options 는 항상 있다).
//! 증명기 내부 실패는 errors 에 `internal_error` 하나(그때까지 기록한 obligations 와 timeout_ms 는 남는다).
//! 읽기·해독 실패는 어댑터처럼 internal_error(Python 예외 문장, pruv_core::pyio).

use std::io::Write;

use pruv_core::pyjson::{dumps_sorted, Json};
use pruv_proof::obligation::{adapter_obligations_json, Trace};
use pruv_proof::symbolic::TIMEOUT_MS;
use pruv_proof::{verify_program_opts, VerifyOptions};

/// 어댑터 `internal_err(e)`.
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

/// infer: `--infer` 일 때만 최상위 `inference`(보고 레코드 배열)를 낸다(어댑터: 읽기·parse·check 오류여도 `[]` 로 있다).
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

fn run(path: &std::ffi::OsStr, infer: bool, no_verify: bool) -> String {
    // 어댑터 trace_result 처럼 읽기·해독 실패도 internal_error(Python 예외 문장)로 낸다(감사 필수 1).
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
            // --no-verify: 검증을 돌리지 않는다(obligations [], timeout_ms 없음).
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
    // 옵션("--" 로 시작)과 FILE 을 가른다. 알려진 옵션: --infer.
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
            // 증명에 영향 없음: 받기만 한다.
        } else if s == "--contract-budget" {
            // 값 하나를 받는다(증명에 영향 없음). 값이 없으면 사용법 오류.
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
    // 깊게 중첩된 입력을 위해 1GB 스택 스레드에서 돌린다(파서·검사기·기호 실행이 모두 재귀).
    let handle = std::thread::Builder::new().stack_size(1 << 30).spawn(move || run(&path, infer, no_verify));
    // 패닉·스레드 생성 실패는 차분 도구가 rs_crash 로 세도록 0 이 아닌 종료 코드로 끝낸다.
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
