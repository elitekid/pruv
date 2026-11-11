fn main() {
    println!("{}", sol::get_int(&[1, 2], 1));
    println!("{}", sol::get_bool(&[true], 0));
    println!("{}", sol::get_bool(&[true, false], 5));
    println!("unreachable");
}
