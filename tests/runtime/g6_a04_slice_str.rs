fn main() {
    println!("{}", sol::score(&[1, 2, 3], "héllo"));
    println!("{}", sol::score(&[10], "abc"));
    println!("{}", sol::score(&[], ""));
    println!("{}", sol::score(&[1000, 1000], "日本"));
}
