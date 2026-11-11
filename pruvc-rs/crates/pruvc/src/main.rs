//! pruvc: the Pruv compiler CLI (Rust implementation). Runs cli -> driver on a 1GB-stack thread and ends with the exit code.

mod cli;
mod driver;

use std::io::Write;

fn run(argv: Vec<String>) -> i32 {
    match cli::parse(&argv) {
        Ok(args) => driver::run(&args),
        Err(msg) => cli::usage_error(&msg),
    }
}

/// Extracts the message from a thread panic payload.
fn panic_message(p: &(dyn std::any::Any + Send)) -> String {
    if let Some(s) = p.downcast_ref::<&str>() {
        (*s).to_string()
    } else if let Some(s) = p.downcast_ref::<String>() {
        s.clone()
    } else {
        "panic".to_string()
    }
}

fn internal(msg: &str) -> i32 {
    println!("{}", driver::internal_json(msg));
    3
}

fn main() {
    let mut argv: Vec<String> = Vec::new();
    for a in std::env::args_os().skip(1) {
        match a.into_string() {
            Ok(s) => argv.push(s),
            Err(_) => {
                let code = cli::usage_error("argument is not valid UTF-8");
                std::process::exit(code);
            }
        }
    }
    // Run on a large-stack thread for deeply nested input.
    let code = match std::thread::Builder::new().stack_size(1 << 30).spawn(move || run(argv)) {
        Ok(h) => match h.join() {
            Ok(c) => c,
            Err(p) => internal(&panic_message(p.as_ref())),
        },
        Err(e) => internal(&format!("cannot start worker thread: {e}")),
    };
    let _ = std::io::stdout().flush();
    std::process::exit(code);
}
