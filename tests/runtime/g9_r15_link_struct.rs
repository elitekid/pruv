fn main() {
    println!("{}", sol::chain3_len());
    println!("{}", sol::chain3_head());
    println!("{}", sol::chain3_last());
    println!("{}", sol::grown_len(5));
    println!("{}", sol::grown_len(0));
    println!("{}", sol::grown_last(5));
    println!("{}", sol::grown_len(100));
}
