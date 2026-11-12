fn main() {
    if let Some(mode) = std::env::args().nth(1) {
        match mode.as_str() {
            "0" => { sol::run(0, 9, 2); },
            _ => panic!("unknown case"),
        }
        return;
    }
    assert_eq!(sol::run(i64::MIN, -4, 9), -4); assert_eq!(sol::run(i64::MAX, -4, 9), 9); assert_eq!(sol::run(3, -4, 9), 3); assert_eq!(sol::run(0, 7, 7), 7); assert_eq!(sol::run(i64::MIN, i64::MIN, i64::MAX), i64::MIN);
    for mode in 0..1 {
        let out = std::process::Command::new(std::env::current_exe().unwrap()).arg(mode.to_string()).output().unwrap();
        assert_eq!(out.status.code(), Some(101));
        assert!(String::from_utf8_lossy(&out.stderr).contains("pruv: requires violated: crate::std::clamp_i64"));
    }
}
