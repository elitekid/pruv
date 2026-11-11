fn main() {
    println!("{}", sol::branchy(true, 5));
    println!("{}", sol::branchy(false, 5));
    println!("{}", sol::maybe_moved(true));
    println!("{}", sol::maybe_moved(false));
}
