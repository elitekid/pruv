// llvm backend driver (run_all uses main_llvm.rs instead of main.rs when it exists): the valid values go through the typed
// bindings, the invalid representations through the raw `pruv_abi_*` symbols. Each bad call panics (exit 101), so it runs in a
// child process (this executable with an argument) and the parent checks its exit code and stderr.
use std::process::Command;

extern "C" {
    fn pruv_abi_count_true(a: *const u8, n: i64) -> i64;
    fn pruv_abi_first_len(s: *const u8, n: i64) -> i64;
}

fn child(mode: &str) -> (Option<i32>, String) {
    let o = Command::new(std::env::current_exe().unwrap()).arg(mode).output().unwrap();
    (o.status.code(), String::from_utf8_lossy(&o.stderr).to_string())
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() > 1 {
        let r = match args[1].as_str() {
            "bool" => unsafe { pruv_abi_count_true([1u8, 2u8, 1u8].as_ptr(), 3) },
            "bool_first" => unsafe { pruv_abi_count_true([0u8, 2u8].as_ptr(), 2) },
            "utf8" => unsafe { pruv_abi_first_len([0x68u8, 0xFFu8, 0x69u8].as_ptr(), 3) },
            _ => -1,
        };
        println!("{}", r);
        return;
    }
    println!("{}", sol::count_true(&[true, false, true]));
    println!("{}", sol::first_len("héllo"));
    let (c, e) = child("bool");
    println!("bool {} {}", c == Some(101), e.contains("pruv: invalid representation: 2 (bool 0..=1)"));
    let (c, e) = child("bool_first");
    println!("bool_first {} {} {}", c == Some(101), e.contains("pruv: invalid representation: 2 (bool 0..=1)"),
             !e.contains("requires violated"));
    let (c, e) = child("utf8");
    println!("utf8 {} {}", c == Some(101), e.contains("pruv: invalid representation: 1 (str UTF-8, byte offset)"));
}
