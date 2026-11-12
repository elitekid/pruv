fn main() {
    if let Some(mode) = std::env::args().nth(1) {
        match mode.as_str() {
            "0" => { sol::run(&[1000000001]); },
            "1" => { sol::run(&vec![0;1000001]); },
            _ => panic!("unknown case"),
        }
        return;
    }
    assert_eq!(sol::run(&[]), 0); assert_eq!(sol::run(&[-1000000000,1000000000,7,-9]), -2); assert_eq!(sol::run(&vec![1000000000;1000000]), 1000000000000000);
    for mode in 0..2 {
        let out = std::process::Command::new(std::env::current_exe().unwrap()).arg(mode.to_string()).output().unwrap();
        assert_eq!(out.status.code(), Some(101));
        assert!(String::from_utf8_lossy(&out.stderr).contains("pruv: requires violated: crate::std::sum_i64"));
    }
}
