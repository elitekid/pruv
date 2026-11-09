pub fn is_sorted(a: &[i64]) -> bool {
    for i in 1..a.len() { if a[i - 1] > a[i] { return false; } }
    true
}
