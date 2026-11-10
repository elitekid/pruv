//! 사용법: pruv-trace-dump FILE
//! 파일 하나를 받아(입력마다 새 프로세스: `_MODEL_SEQ` 가 0 에서 시작) 한 줄을 stdout 에 쓴다.
//! 출력은 Python `diff_py_adapter.trace_result(path, True)` 를 `json.dumps(sort_keys=True, ensure_ascii=False)` 한 것과
//! 바이트 동일해야 한다:
//!   {"errors":[...], "obligations":[{"attempts":[{"lemmas","result","smt2"}],"code","col","fn","line","seq"[,"skipped"]}],
//!    "schema":"pruv-trace-v1", "timeout_ms":N}
//! parse/check 오류면 errors 에 그 오류 하나, obligations 는 빈 목록이고 timeout_ms 는 없다.
//! 증명기 내부 실패는 errors 에 `internal_error` 하나(그때까지 기록한 obligations 와 timeout_ms 는 남는다).
//! 해독 실패는 `{"adapter_error": "decode"}`.

use std::io::Write;

use pruv_core::pyjson::{dumps_sorted, Json};
use pruv_proof::obligation::{adapter_obligations_json, Trace};
use pruv_proof::symbolic::TIMEOUT_MS;
use pruv_proof::verify_program;

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

fn output(errors: Vec<Json>, trace: &Trace, timeout: Option<u32>) -> String {
    let mut kv = vec![
        ("schema".to_string(), Json::str("pruv-trace-v1")),
        ("errors".to_string(), Json::Arr(errors)),
        ("obligations".to_string(), adapter_obligations_json(trace)),
    ];
    if let Some(t) = timeout {
        kv.push(("timeout_ms".to_string(), Json::int(t as i64)));
    }
    dumps_sorted(&Json::Obj(kv))
}

fn run(path: &std::ffi::OsStr) -> String {
    // 어댑터 trace_result 처럼 읽기·해독 실패도 internal_error(Python 예외 문장)로 낸다(감사 필수 1).
    let src = match pruv_core::pyio::read_source(std::path::Path::new(path)) {
        Ok(s) => s,
        Err(msg) => return output(vec![internal_err(&msg)], &Trace::adapter(), None),
    };
    let mut errors: Vec<Json> = Vec::new();
    let mut trace = Trace::adapter();
    let mut timeout: Option<u32> = None;
    match pruv_core::parse(&src) {
        Err(e) => errors.push(e.to_json_value()),
        Ok(mut prog) => match pruv_core::check::check(&mut prog) {
            Err(e) => errors.push(e.to_json_value()),
            Ok(tt) => {
                timeout = Some(TIMEOUT_MS);
                match verify_program(&prog, &tt, Some(&mut trace)) {
                    Ok(errs) => errors.extend(errs.iter().map(|e| e.to_json_value())),
                    Err(msg) => errors.push(internal_err(&msg)),
                }
            }
        },
    }
    output(errors, &trace, timeout)
}

fn main() {
    let args: Vec<std::ffi::OsString> = std::env::args_os().skip(1).collect();
    if args.len() != 1 {
        eprintln!("usage: pruv-trace-dump FILE");
        std::process::exit(2);
    }
    let path = args[0].clone();
    // 깊게 중첩된 입력을 위해 1GB 스택 스레드에서 돌린다(파서·검사기·기호 실행이 모두 재귀).
    let handle = std::thread::Builder::new().stack_size(1 << 30).spawn(move || run(&path));
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
