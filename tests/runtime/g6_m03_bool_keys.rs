fn main() {
    println!("{}", sol::bool_lookup(true));
    println!("{}", sol::bool_lookup(false));
    println!("{}", sol::bool_size());
    println!("{}", sol::flag_roundtrip(true, false));
    println!("{}", sol::flag_roundtrip(false, true));
}
