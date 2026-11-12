fn main() {
    for _ in 0..32 {
        for (a, x, expected) in [
            (vec![], 0, None), (vec![7], 7, Some(0)),
            (vec![3,2,2,3,9], 3, Some(1)),
            (vec![3,2,2,3,9], 2, Some(2)),
            (vec![1,1,1], 1, Some(0)),
            (vec![i64::MIN,0,i64::MAX], i64::MIN, Some(2)),
            (vec![1,2,3], 9, None),
        ] {
            let original = a.clone();
            assert_eq!(sol::run(&a, x), expected);
            assert_eq!(a, original);
        }
    }
}
