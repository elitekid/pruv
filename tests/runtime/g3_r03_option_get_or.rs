fn main() {
    println!("{}", sol::get_or_int(Some(4), 0));
    println!("{}", sol::get_or_int(None, 9));
    println!("{}", sol::get_or_bool(Some(false), true));
    println!("{}", sol::get_or_bool(None, true));
    println!("{:?}", sol::wrap_bool(true));
    println!("{:?}", sol::none_bool());
}
