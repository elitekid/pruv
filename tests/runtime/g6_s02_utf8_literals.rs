fn main() {
    println!("{}", sol::utf8_len());
    for i in [0i64, 1, 2, 3, 5, 6, 7, 8, 9, 10, 11] {
        println!("{}", sol::utf8_byte(i));
    }
}
