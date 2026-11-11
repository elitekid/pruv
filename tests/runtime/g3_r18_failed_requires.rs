fn main() {
    println!("{}", sol::at_int(&[5, 6], 1));
    println!("{}", sol::at_bool(&[true, false], 0));
    println!("{}", sol::at_bool(&[true], 3));
    println!("unreachable");
}
