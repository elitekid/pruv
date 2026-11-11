fn main() {
    println!("{}", sol::unwrap_bool(Ok(false), true));
    println!("{}", sol::unwrap_bool(Err(2), true));
    println!("{:?}", sol::fail_bool(3));
    println!("{:?}", sol::ok_bool(true));
    println!("{:?}", sol::fail_int(5));
}
