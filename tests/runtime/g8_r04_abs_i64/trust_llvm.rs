fn main() {
    if let Some(mode) = std::env::args().nth(1) {
        match mode.as_str() {
            "0" => { sol::run(i64::MIN); },
            _ => panic!("unknown case"),
        }
        return;
    }
    assert_eq!(sol::run(i64::MIN + 1), i64::MAX); assert_eq!(sol::run(i64::MAX), i64::MAX); assert_eq!(sol::run(0), 0); assert_eq!(sol::run(-7), 7);
    for mode in 0..1 {
        let out = std::process::Command::new(std::env::current_exe().unwrap()).arg(mode.to_string()).output().unwrap();
        assert_eq!(out.status.code(), Some(101));
        assert!(String::from_utf8_lossy(&out.stderr).contains("pruv: requires violated: crate::std::abs_i64"));
    }
}
