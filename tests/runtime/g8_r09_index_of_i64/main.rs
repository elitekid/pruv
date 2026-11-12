fn main() {
    assert_eq!(sol::run(&[4,2,4],4),Some(0)); assert_eq!(sol::run(&[9,2,2],2),Some(1)); assert_eq!(sol::run(&[4,2,4],9),None); assert_eq!(sol::run(&[],4),None);
}
