fn main() {
    println!("{}", sol::id_int(7));
    println!("{}", sol::id_bool(true));
    println!("{:?}", sol::id_opt(Some(false)));
    println!("{:?}", sol::id_opt(None));
    let p = sol::id_pair(3, false);
    println!("{} {}", p.first, p.second);
    println!("{}", sol::id_int(-2));
    println!("{}", sol::id_bool(false));
}
