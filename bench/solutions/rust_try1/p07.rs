pub fn count_less(a: &[i64], x: i64) -> i64 {
    let mut c = 0i64;
    for &v in a { if v < x { c += 1; } }
    c
}
