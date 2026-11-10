fn main() {
    // default budget (2^30): 2 * 540_000_000 > 2^30, each alone < 2^30
    println!("{}", sol::f(540000000));
}
