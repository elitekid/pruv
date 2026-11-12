use std::panic::catch_unwind;

fn text(p: Box<dyn std::any::Any + Send>) -> String {
    if let Some(s) = p.downcast_ref::<String>() {
        s.clone()
    } else if let Some(s) = p.downcast_ref::<&str>() {
        s.to_string()
    } else {
        "unknown panic".to_string()
    }
}

fn main() {
    std::panic::set_hook(Box::new(|_| {}));
    println!("{:?}", sol::write_i64(&[1, 2, 3], 2, 8));
    println!("{}", text(catch_unwind(|| sol::write_i64(&[1, 2, 3], 3, 8)).err().unwrap()));
    println!("{}", text(catch_unwind(|| sol::write_i64(&[1, 2, 3], -1, 8)).err().unwrap()));
    println!("{:?}", sol::write_u8(&[1u8, 2], 1, 255));
    println!("{}", text(catch_unwind(|| sol::write_u8(&[1u8, 2], 0, 300)).err().unwrap()));
    println!("{}", text(catch_unwind(|| sol::write_u8(&[1u8, 2], 0, -1)).err().unwrap()));
    println!("{}", text(catch_unwind(|| sol::write_u8(&[1u8, 2], 5, 300)).err().unwrap()));
}
