fn main() {
    let s = sol::lift_bool(false).unwrap();
    println!("{} {}", s.first, s.second);
    let r = sol::lift_pair(1, true).unwrap();
    println!("{} {} {} {}", r.first.first, r.first.second, r.second.first, r.second.second);
}
