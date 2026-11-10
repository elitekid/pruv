//! `pruv-proof-spike SAMPLE_NAME` | `--all` | `--list`
//!
//! 표본의 의무 trace 를 JSON 으로 출력한다(형식은 samples.rs/obligation.rs 문서 참고).
//! `--all` 은 표본마다 JSON 한 줄(JSON Lines). 표본마다 새 z3 컨텍스트와 `_MODEL_SEQ=0` 에서 시작한다.

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
