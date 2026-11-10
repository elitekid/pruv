fn main() {
    // budget 1000: 500 + 500 = 1000 is allowed exactly; 501 + 501 = 1002 exceeds
    println!("{}", sol::f(500));
    println!("{}", sol::f(501));
}
