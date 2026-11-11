//! Usage: pruv-check-dump [--rust-extern NAME=PATH]... FILE...
//! Writes exactly one line (UTF-8, ending with \n) per file to stdout, in order (the parse+check result).
//! Each line is flushed immediately: even if one file overflows the stack and the process aborts, the lines of earlier files remain.
//! --rust-extern (G6, like `diff_py_adapter.py check --rust-extern`): repeatable; only NAME (the part before `=`) is used.

use std::io::Write;

fn work(files: Vec<std::ffi::OsString>, externs: Vec<String>) -> bool {
    let stdout = std::io::stdout();
    let mut lock = stdout.lock();
    for f in files {
        let line = match std::fs::read(&f) {
            Ok(bytes) => pruv_core::dump::check_dump_line_with(&bytes, &externs),
            Err(_) => r#"{"adapter_error": "io"}"#.to_string(),
        };
        if lock.write_all(line.as_bytes()).is_err() || lock.write_all(b"\n").is_err() || lock.flush().is_err() {
            return false;
        }
    }
    true
}

fn main() {
    let mut files: Vec<std::ffi::OsString> = Vec::new();
    let mut externs: Vec<String> = Vec::new();
    let mut args = std::env::args_os().skip(1);
    while let Some(a) = args.next() {
        if a == "--rust-extern" {
            match args.next() {
                Some(v) => externs.push(v.to_string_lossy().split('=').next().unwrap_or("").to_string()),
                None => {
                    eprintln!("usage: pruv-check-dump [--rust-extern NAME=PATH]... FILE...");
                    std::process::exit(2);
                }
            }
        } else if let Some(v) = a.to_str().and_then(|s| s.strip_prefix("--rust-extern=")) {
            externs.push(v.split('=').next().unwrap_or("").to_string());
        } else {
            files.push(a);
        }
    }
    if files.is_empty() {
        eprintln!("usage: pruv-check-dump [--rust-extern NAME=PATH]... FILE...");
        std::process::exit(2);
    }
    // Run on a large-stack thread for deeply nested input (the checker is recursive too, so the caller provides the stack).
    let handle = std::thread::Builder::new().stack_size(1 << 30).spawn(move || work(files, externs));
    match handle.map(|h| h.join()) {
        Ok(Ok(true)) => {}
        _ => {
            eprintln!("pruv-check-dump: internal failure");
            std::process::exit(1);
        }
    }
}
