pub fn prefix_sums(a: &[i64]) -> Vec<i64> {
    let mut out = vec![0i64; a.len() + 1];
    for i in 0..a.len() { out[i + 1] = out[i] + a[i]; }
    out
}
