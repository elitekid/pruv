fn main() {
    // Distinct child results must survive even though both functions are named min_i64.
    for (x, want) in [(-20, 0), (0, 0), (5, -2), (99, -4),
                      (i64::MIN, 0), (i64::MAX, -4)] {
        assert_eq!(sol::run(x), want);
    }
}
