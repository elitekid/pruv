fn main() {
    println!("{}", sol::pick_num(true, 3, 9));
    println!("{}", sol::pick_num(false, 3, 9));
    println!("{}", sol::pick_flag(true, false, true));
    println!("{}", sol::pick_flag(false, false, true));
    println!("{}", sol::pick_guard(0, 5, 6));
    println!("{}", sol::pick_guard(2, 5, 6));
}
