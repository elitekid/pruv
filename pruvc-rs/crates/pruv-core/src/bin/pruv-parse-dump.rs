//! Usage: pruv-parse-dump FILE...
//! Writes exactly one line (UTF-8, ending with \n) per file to stdout, in order.
//! Each line is flushed immediately: even if one file overflows the stack and the process aborts, the lines of earlier files remain.

use std::io::Write;

fn work(files: Vec<std::ffi::OsString>) -> bool {
    let stdout = std::io::stdout();
    let mut lock = stdout.lock();
    for f in files {
        // G4: through the module loader (an explicit-mode root also reads its declared module files)
        let line = pruv_core::dump::parse_dump_path(std::path::Path::new(&f));
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
    // Run on a large-stack thread for deeply nested input (the public parse has no depth limit, so the caller provides the stack).
    let handle = std::thread::Builder::new().stack_size(1 << 30).spawn(move || work(files));
    match handle.map(|h| h.join()) {
        Ok(Ok(true)) => {}
        _ => {
            eprintln!("pruv-parse-dump: internal failure");
            std::process::exit(1);
        }
    }
}
