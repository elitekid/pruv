fn main() {
    println!("{}", sol::probe_empty(0));
    println!("{}", sol::probe_empty(i64::MAX));
    println!("{}", sol::extreme(0));
    println!("{}", sol::extreme(i64::MAX));
    println!("{}", sol::extreme(-i64::MAX));
    println!("{}", sol::extreme(1));
    println!("{}", sol::extreme(-1));
}
