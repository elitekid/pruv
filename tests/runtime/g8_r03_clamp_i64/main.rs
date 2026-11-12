fn main() {
    assert_eq!(sol::run(i64::MIN, -4, 9), -4); assert_eq!(sol::run(i64::MAX, -4, 9), 9); assert_eq!(sol::run(3, -4, 9), 3); assert_eq!(sol::run(0, 7, 7), 7); assert_eq!(sol::run(i64::MIN, i64::MIN, i64::MAX), i64::MIN);
}
