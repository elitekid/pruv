fn main() {
    assert_eq!(sol::run(i64::MIN, i64::MAX), i64::MAX); assert_eq!(sol::run(-7, -7), -7); assert_eq!(sol::run(-3, -9), -3);
}
