fn main() {
    assert_eq!(sol::run(i64::MIN + 1), i64::MAX); assert_eq!(sol::run(i64::MAX), i64::MAX); assert_eq!(sol::run(0), 0); assert_eq!(sol::run(-7), 7);
    let panic = std::panic::catch_unwind(|| { sol::run(i64::MIN); }).expect_err("internal requires must fail");
    let msg = panic.downcast_ref::<String>().map(String::as_str).or_else(|| panic.downcast_ref::<&str>().copied()).unwrap();
    assert!(msg.contains("pruv: requires violated: crate::std::abs_i64"), "{msg}");
}
