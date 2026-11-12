fn main() {
    assert_eq!(sol::run(&[i64::MIN]),i64::MIN); assert_eq!(sol::run(&[-9,-2,-8,-2]),-2); assert_eq!(sol::run(&[i64::MIN,i64::MAX]),i64::MAX);
}
