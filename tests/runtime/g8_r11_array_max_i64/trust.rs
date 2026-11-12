fn main() {
    assert_eq!(sol::run(&[i64::MIN]),i64::MIN); assert_eq!(sol::run(&[-9,-2,-8,-2]),-2); assert_eq!(sol::run(&[i64::MIN,i64::MAX]),i64::MAX);
    let panic = std::panic::catch_unwind(|| { sol::run(&[]); }).expect_err("internal requires must fail");
    let msg = panic.downcast_ref::<String>().map(String::as_str).or_else(|| panic.downcast_ref::<&str>().copied()).unwrap();
    assert!(msg.contains("pruv: requires violated: crate::std::array_max_i64"), "{msg}");
}
