fn main() {
    let z = sol::z_last(true).unwrap();
    println!("{} {}", z.first, z.second);
    let a = sol::a_first(5).unwrap();
    println!("{} {}", a.first, a.second);
    let m = sol::m_mixed(5, true);
    println!("{} {:?}", m.first, m.second);
}
