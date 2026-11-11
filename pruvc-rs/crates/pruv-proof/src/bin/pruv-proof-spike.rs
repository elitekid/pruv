//! `pruv-proof-spike SAMPLE_NAME` | `--all` | `--list`
//!
//! Prints the sample's obligation trace as JSON (see the samples.rs/obligation.rs docs for the format).
//! `--all` emits one JSON line per sample (JSON Lines). Each sample starts with a fresh z3 context and `_MODEL_SEQ=0`.

use pruv_proof::samples::{run_sample, sample_names};

fn usage() -> ! {
    eprintln!("usage: pruv-proof-spike SAMPLE_NAME | --all | --list");
    eprintln!("samples: {}", sample_names().join(", "));
    std::process::exit(2);
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match args.as_slice() {
        [a] if a == "--list" => {
            for n in sample_names() {
                println!("{n}");
            }
        }
        [a] if a == "--all" => {
            for n in sample_names() {
                let v = run_sample(n).expect("listed sample exists");
                println!("{v}");
            }
        }
        [name] => match run_sample(name) {
            Some(v) => println!("{v}"),
            None => {
                eprintln!("unknown sample: {name}");
                usage();
            }
        },
        _ => usage(),
    }
}
