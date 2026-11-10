fn main() {
    // x * 4 = 1.6e19 exceeds i64::MAX; contract arithmetic is i128
    println!("{}", sol::f(4000000000000000000));
}
