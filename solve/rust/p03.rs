pub fn is_sorted(a: &[i64]) -> bool {
    a.windows(2).all(|w| w[0] <= w[1])
}
