fn main() {
    // each call 600 < budget 1000, total 1200 > 1000: the budget resets per call
    println!("{}", sol::f(600));
    println!("{}", sol::f(600));
}
