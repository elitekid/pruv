use std::{hint::black_box, time::Instant};
fn mix(a: &mut [i64]) {
 for v in a {
  assert!(*v >= 0);
  let mut x = *v % 65521;
  for _ in 0..32 { let y = x.checked_mul(251).unwrap().checked_add(17).unwrap(); assert!(y >= 0); x = y % 65521; }
  *v = x;
 }
}
fn main() {
 let args: Vec<String> = std::env::args().collect();
 let n: usize = args[1].parse().unwrap();
 let repeat: usize = args[2].parse().unwrap();
 let source: Vec<i64> = (0..n).map(|i| (i % 65521) as i64).collect();
 let mut expected = source.clone(); mix(&mut expected);
 for iteration in 0..repeat+2 {
  for offset in 0..4 {
   let variant = (offset + iteration) % 4;
   let start = Instant::now();
   let mut a = source.clone(); let mut b = source.clone();
   let kernel = Instant::now();
   match variant {
    0 => sol::bench_parallel(black_box(&mut a), black_box(&mut b)),
    1 => sol::bench_sequential(black_box(&mut a), black_box(&mut b)),
    2 => { mix(black_box(&mut a)); mix(black_box(&mut b)); },
    _ => std::thread::scope(|s| { let h1 = s.spawn(|| mix(black_box(&mut a))); let h2 = s.spawn(|| mix(black_box(&mut b))); h1.join().unwrap(); h2.join().unwrap(); }),
   }
   let kernel_ns = kernel.elapsed().as_nanos();
   let inclusive_ns = start.elapsed().as_nanos();
   assert_eq!(a, expected); assert_eq!(b, expected);
   let checksum: i64 = black_box(&a).iter().chain(black_box(&b)).sum();
   if iteration >= 2 { println!("{} {} {} {}", variant, kernel_ns, inclusive_ns, checksum); }
  }
 }
}
