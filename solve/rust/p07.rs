pub fn count_less(a: &[i64], x: i64) -> i64 {
    a.iter().map(|&v| (v < x) as i64).sum()
}
