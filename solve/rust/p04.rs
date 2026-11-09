pub fn binary_search(a: &[i64], x: i64) -> Option<i64> {
    let i = a.partition_point(|&v| v < x);
    if i < a.len() && a[i] == x {
        Some(i as i64)
    } else {
        None
    }
}
