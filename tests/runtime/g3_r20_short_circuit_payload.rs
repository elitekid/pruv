fn main() {
    println!("{}", sol::is_some_eq(Some(true), true));
    println!("{}", sol::is_some_eq(None, true));
    println!("{}", sol::is_some_eq(Some(false), true));
    println!("{}", sol::expect_bool(Some(true), true));
    println!("{}", sol::expect_bool(None, true));
    println!("unreachable");
}
