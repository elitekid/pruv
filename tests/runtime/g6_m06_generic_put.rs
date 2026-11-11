fn main() {
    println!("{}", sol::int_roundtrip(8, 80));
    println!("{}", sol::int_roundtrip(-8, -80));
    println!("{}", sol::flag_roundtrip(true, true));
    println!("{}", sol::flag_roundtrip(false, false));
    println!("{}", sol::other_key_missing(1, 2));
}
