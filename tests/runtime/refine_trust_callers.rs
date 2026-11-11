fn main() {
    // --trust-callers skips the synthesized entry checks too: both violations go through
    println!("{}", sol::f(101));
    let v: Vec<i64> = vec![1, 2, 30, 4, 5];
    println!("{}", sol::g(&v));
}
