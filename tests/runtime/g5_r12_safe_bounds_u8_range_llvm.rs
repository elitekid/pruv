// llvm host driver of g5_r12: a llvm safe failure ends the process (exit 101, message on stderr), so every failing case
// runs in a child process (this executable re-run with the case number) and the parent prints the child's message.
// The printed lines are the same as those of the Rust driver g5_r12_safe_bounds_u8_range.rs.
use std::process::Command;

fn case(n: u32) {
    match n {
        1 => println!("{:?}", sol::write_i64(&[1, 2, 3], 2, 8)),
        2 => println!("{:?}", sol::write_i64(&[1, 2, 3], 3, 8)),
        3 => println!("{:?}", sol::write_i64(&[1, 2, 3], -1, 8)),
        4 => println!("{:?}", sol::write_u8(&[1u8, 2], 1, 255)),
        5 => println!("{:?}", sol::write_u8(&[1u8, 2], 0, 300)),
        6 => println!("{:?}", sol::write_u8(&[1u8, 2], 0, -1)),
        _ => println!("{:?}", sol::write_u8(&[1u8, 2], 5, 300)),
    }
}

fn main() {
    if let Some(a) = std::env::args().nth(1) {
        case(a.parse().unwrap());
        return;
    }
    let me = std::env::current_exe().unwrap();
    for n in 1..=7u32 {
        let out = Command::new(&me).arg(n.to_string()).output().unwrap();
        if out.status.success() {
            print!("{}", String::from_utf8_lossy(&out.stdout));
        } else {
            println!("{}", String::from_utf8_lossy(&out.stderr).trim_end());
        }
    }
}
