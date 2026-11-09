pub fn max_element(a: &[i64]) -> Option<i64> {
    if a.is_empty() { return None; }
    let mut m = a[0];
    for &v in &a[1..] { if v > m { m = v; } }
    Some(m)
}
