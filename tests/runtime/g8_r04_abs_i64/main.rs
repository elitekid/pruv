fn main() {
    assert_eq!(sol::run(i64::MIN + 1), i64::MAX); assert_eq!(sol::run(i64::MAX), i64::MAX); assert_eq!(sol::run(0), 0); assert_eq!(sol::run(-7), 7);
}
