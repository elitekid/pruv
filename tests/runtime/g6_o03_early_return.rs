fn main() {
    println!("{}", sol::early(true));
    println!("{}", sol::early(false));
    println!("{}", sol::early_default(0, 9));
    println!("{}", sol::early_default(1, 9));
}
