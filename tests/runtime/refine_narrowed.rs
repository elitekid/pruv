fn main() {
    // an unrefined i64 narrowed by `if` reaches the refined parameter
    println!("{}", sol::f(50));
    println!("{}", sol::f(200));
    println!("{}", sol::f(-5));
}
