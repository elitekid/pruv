fn main() {
    println!("{}", sol::clamp(5, 0, 10));
    println!("{}", sol::clamp(-4, 0, 10));
    println!("{}", sol::clamp(99, 0, 10));
    println!("{}", sol::spread(3, 10));
    println!("{}", sol::spread(10, 3));
    println!("{}", sol::spread(4, 4));
}
