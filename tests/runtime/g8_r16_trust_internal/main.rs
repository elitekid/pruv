fn main() {
    if std::env::args().nth(1).is_some() { let _ = sol::run(i64::MIN); return; }
    assert_eq!(sol::run(-17),17);
    let out = std::process::Command::new(std::env::current_exe().unwrap()).arg("invalid").output().unwrap();
    assert_eq!(out.status.code(),Some(101));
    assert!(String::from_utf8_lossy(&out.stderr).contains("pruv: requires violated: crate::std::abs_i64"));
}
