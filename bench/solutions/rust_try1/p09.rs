pub fn dot(a: &[i64], b: &[i64]) -> Result<i64, i64> {
    if a.len() != b.len() { return Err(1); }
    let mut s = 0i64;
    for i in 0..a.len() { s += a[i] * b[i]; }
    Ok(s)
}
