use std::{hint::black_box, time::Instant};
fn main() {
 let args: Vec<String> = std::env::args().collect();
 let n: i64 = args[1].parse().unwrap();
 let reps: usize = args[2].parse().unwrap();
 let mut expected = 7i64;
 for _ in 0..n*32 { expected = (expected*251+17)%65521; }
 for k in 0..reps+2 {
  let start = Instant::now();
  let got = black_box(sol::mix(black_box(n), black_box(7)));
  let elapsed = start.elapsed().as_nanos();
  assert_eq!(got, expected);
  if k >= 2 { println!("{} {}", elapsed, got); }
 }
}
