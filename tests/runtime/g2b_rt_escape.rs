fn main() {
    let s = sol::esc();
    println!("{}", s.len());
    for b in s.as_bytes() {
        println!("{}", b);
    }
    println!("{}", sol::byte(5));
}
