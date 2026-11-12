fn main() {
    println!("{}", sol::new_root(0));
    println!("{}", sol::new_root(1));
    println!("{}", sol::new_left_root(1));
    println!("{}", sol::new_root(3));
    println!("{}", sol::tag_len(1));
    println!("{}", sol::tag_len(2));
    println!("{}", sol::orig_root());
    println!("{}", sol::orig_tag_len());
}
