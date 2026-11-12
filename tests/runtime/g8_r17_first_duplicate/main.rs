fn main() {
    for (a, expected) in [
        (vec![], None), (vec![7], None), (vec![3,2,2,3], Some(0)),
        (vec![9,2,3,2,3], Some(1)), (vec![1,1,1], Some(0)),
        (vec![i64::MIN,i64::MAX,i64::MIN], Some(0)),
        (vec![i64::MAX,i64::MIN], None),
    ] {
        let original = a.clone();
        assert_eq!(sol::first_duplicate(&a), expected);
        assert_eq!(a, original);
    }
    assert_eq!(sol::checked_total(i64::MAX, 1), None);
    assert_eq!(sol::checked_total(i64::MIN, -1), None);
    assert_eq!(sol::checked_total(i64::MAX - 1, 1), Some(i64::MAX));
    assert_eq!(sol::checked_total(i64::MIN + 1, -1), Some(i64::MIN));
}
