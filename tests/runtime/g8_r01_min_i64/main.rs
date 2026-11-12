fn main() {
    assert_eq!(sol::run(i64::MIN, i64::MAX), i64::MIN); assert_eq!(sol::run(7, 7), 7); assert_eq!(sol::run(9, -3), -3);
}
