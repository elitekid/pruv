fn main() {
    assert_eq!(sol::run(i64::MIN, -4, 9), -4); assert_eq!(sol::run(i64::MAX, -4, 9), 9); assert_eq!(sol::run(3, -4, 9), 3); assert_eq!(sol::run(0, 7, 7), 7); assert_eq!(sol::run(i64::MIN, i64::MIN, i64::MAX), i64::MIN);
    let panic = std::panic::catch_unwind(|| { sol::run(0, 9, 2); }).expect_err("internal requires must fail");
    let msg = panic.downcast_ref::<String>().map(String::as_str).or_else(|| panic.downcast_ref::<&str>().copied()).unwrap();
    assert!(msg.contains("pruv: requires violated: crate::std::clamp_i64"), "{msg}");
}
