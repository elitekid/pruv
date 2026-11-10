//! 사용법: pruv-parse-dump FILE...
//! 파일마다 정확히 한 줄(UTF-8, 끝에 \n)을 순서대로 stdout 에 쓴다.
//! 줄마다 바로 내보내 비운다: 한 파일이 스택을 넘쳐 프로세스가 중단돼도 앞 파일의 줄은 남는다.

use std::io::Write;

fn work(files: Vec<std::ffi::OsString>) -> bool {
    let stdout = std::io::stdout();
    let mut lock = stdout.lock();
    for f in files {
        let line = match std::fs::read(&f) {
            Ok(bytes) => pruv_core::dump::parse_dump_line(&bytes),
            Err(_) => r#"{"adapter_error": "io"}"#.to_string(),
        };
        if lock.write_all(line.as_bytes()).is_err() || lock.write_all(b"\n").is_err() || lock.flush().is_err() {
            return false;
        }
    }
    true
}

fn main() {
    let files: Vec<std::ffi::OsString> = std::env::args_os().skip(1).collect();
    if files.is_empty() {
        eprintln!("usage: pruv-parse-dump FILE...");
        std::process::exit(2);
    }
    // 깊게 중첩된 입력을 위해 큰 스택 스레드에서 돌린다(공개 parse 는 깊이 상한이 없어 호출자가 스택을 잡는다).
    let handle = std::thread::Builder::new().stack_size(1 << 30).spawn(move || work(files));
    match handle.map(|h| h.join()) {
        Ok(Ok(true)) => {}
        _ => {
            eprintln!("pruv-parse-dump: internal failure");
            std::process::exit(1);
        }
    }
}
