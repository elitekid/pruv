use l3_claude_handrust::window_packet;
use std::{env, fs, hint::black_box, time::Instant};

fn main() {
    let a: Vec<String> = env::args().collect();
    if a.len() < 3 {
        eprintln!("usage: {} <input> window | dump <flag>", a[0]);
        std::process::exit(2);
    }
    let data = fs::read(&a[1]).unwrap();
    match a[2].as_str() {
        "window" => {
            for i in 0..6 {
                let start = Instant::now();
                let out = black_box(window_packet(black_box(&data), 0));
                let ms = start.elapsed().as_secs_f64() * 1000.0;
                println!("{} {} {} {}", if i == 0 { "warm" } else { "run" }, ms, out.len(), out[0]);
            }
        }
        "dump" => {
            let flag: i64 = a.get(3).map_or(0, |s| s.parse().unwrap());
            let out = window_packet(&data, flag);
            let line: Vec<String> = out.iter().map(|x| x.to_string()).collect();
            println!("{}", line.join(","));
        }
        _ => {
            eprintln!("unknown op");
            std::process::exit(2);
        }
    }
}
