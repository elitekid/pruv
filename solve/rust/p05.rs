pub fn prefix_sums(a: &[i64]) -> Vec<i64> {
    let mut out = Vec::with_capacity(a.len() + 1);
    let mut s: i64 = 0;
    out.push(0);
    for &v in a {
        s += v;
        out.push(s);
    }
    out
}
