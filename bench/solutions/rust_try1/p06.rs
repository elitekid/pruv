pub fn max_subarray(a: &[i64]) -> i64 {
    let mut best = a[0];
    let mut cur = 0i64;
    for &v in a {
        cur = (cur + v).max(v);
        best = best.max(cur);
    }
    best
}
