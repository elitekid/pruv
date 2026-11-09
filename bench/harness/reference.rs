// Trusted reference implementations (idiomatic Rust, iterator style).
#![allow(dead_code)]
pub fn sum_array(a: &[i64]) -> i64 { a.iter().sum() }
pub fn max_element(a: &[i64]) -> Option<i64> { a.iter().copied().max() }
pub fn is_sorted(a: &[i64]) -> bool { a.windows(2).all(|w| w[0] <= w[1]) }
pub fn binary_search(a: &[i64], x: i64) -> Option<i64> {
    let i = a.partition_point(|&v| v < x);
    if i < a.len() && a[i] == x { Some(i as i64) } else { None }
}
pub fn prefix_sums(a: &[i64]) -> Vec<i64> {
    let mut out = Vec::with_capacity(a.len() + 1);
    let mut s = 0; out.push(0);
    for &v in a { s += v; out.push(s); }
    out
}
pub fn max_subarray(a: &[i64]) -> i64 {
    let mut best = a[0]; let mut cur = a[0];
    for &v in &a[1..] { cur = v.max(cur + v); best = best.max(cur); }
    best
}
pub fn count_less(a: &[i64], x: i64) -> i64 { a.iter().filter(|&&v| v < x).count() as i64 }
pub fn reverse(a: &[i64]) -> Vec<i64> { a.iter().rev().copied().collect() }
pub fn dot(a: &[i64], b: &[i64]) -> Result<i64, i64> {
    if a.len() != b.len() { return Err(1); }
    Ok(a.iter().zip(b).map(|(x, y)| x * y).sum())
}
pub fn gcd(mut a: i64, mut b: i64) -> i64 { while b != 0 { let t = a % b; a = b; b = t; } a }
