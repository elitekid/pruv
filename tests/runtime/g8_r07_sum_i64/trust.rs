fn main() {
    assert_eq!(sol::run(&[]), 0); assert_eq!(sol::run(&[-1000000000,1000000000,7,-9]), -2); assert_eq!(sol::run(&vec![1000000000;1000000]), 1000000000000000);
    let panic = std::panic::catch_unwind(|| { sol::run(&[1000000001]); }).expect_err("internal requires must fail");
    let msg = panic.downcast_ref::<String>().map(String::as_str).or_else(|| panic.downcast_ref::<&str>().copied()).unwrap();
    assert!(msg.contains("pruv: requires violated: crate::std::sum_i64"), "{msg}");
    let panic = std::panic::catch_unwind(|| { sol::run(&vec![0;1000001]); }).expect_err("internal requires must fail");
    let msg = panic.downcast_ref::<String>().map(String::as_str).or_else(|| panic.downcast_ref::<&str>().copied()).unwrap();
    assert!(msg.contains("pruv: requires violated: crate::std::sum_i64"), "{msg}");
}
