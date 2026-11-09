pub fn reverse(a: &[i64]) -> Vec<i64> {
    let n = a.len();
    let mut out = vec![0i64; n];
    for i in 0..n { out[i] = a[n - 1 - i]; }
    out
}
