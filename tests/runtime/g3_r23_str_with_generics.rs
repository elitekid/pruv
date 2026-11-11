fn main() {
    println!("{}", sol::length("héllo"));
    let p = sol::pair_len("héllo");
    println!("{} {}", p.first, p.second);
    println!("{}", sol::cut_len("héllo", 0, 3));
    println!("{}", sol::cut_len("héllo", 1, 3));
    println!("{}", sol::id_int(8));
}
