fn main() {
    println!("{}", sol::index_or(&[4, 5, 6, 5], 5, -1));
    println!("{}", sol::index_or(&[4, 5, 6, 5], 9, -1));
    println!("{}", sol::index_or(&[], 1, -7));
    println!("{}", sol::index_or(&[8], 8, -7));
}
