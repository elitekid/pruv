use std::hint::black_box;
use std::time::Instant;
fn native(path: &str) -> i64 {
    use std::io::Read;
    let mut file = match std::fs::File::open(path) { Ok(f) => f, Err(_) => return -1 };
    let mut data = Vec::new();
    if file.read_to_end(&mut data).is_err() || data.len() > 10_000_000 { return -1; }
    data.iter().map(|b| *b as i64).sum()
}
fn main() {
    let args: Vec<String> = std::env::args().collect();
    let path = &args[1];
    let repeat: usize = args[2].parse().unwrap();
    let data: Vec<u8> = (0..10_000_000usize).map(|i| ((i * 37 + 11) % 256) as u8).collect();
    std::fs::write(path, &data).unwrap();
    let expected: i64 = data.iter().map(|b| *b as i64).sum();
    drop(data);
    assert_eq!(native(path), expected);
    assert_eq!(sol::checksum(path), expected);
    let mut pruv = Vec::new();
    let mut rust = Vec::new();
    for round in 0..repeat {
        // Alternate order to reduce cache/order bias; timings exclude file creation.
        for side in if round % 2 == 0 { [0, 1] } else { [1, 0] } {
            let start = Instant::now();
            let got = if side == 0 { sol::checksum(black_box(path)) } else { native(black_box(path)) };
            let elapsed = start.elapsed().as_nanos();
            assert_eq!(black_box(got), expected);
            if side == 0 { pruv.push(elapsed); } else { rust.push(elapsed); }
        }
    }
    println!("{{\"bytes\":10000000,\"checksum\":{},\"pruv_ns\":{:?},\"rust_ns\":{:?}}}", expected, pruv, rust);
}
