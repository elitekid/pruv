pub fn sum_array(a: &[i64]) -> i64 {
    let mut s = 0i64;
    for &v in a { s += v; }
    s
}
