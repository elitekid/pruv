fn main() {
    for k in 0..5 {
        println!("{}", sol::shape_of(k));
    }
    println!("{}", sol::sample_left());
    println!("{}", sol::sample_right());
    println!("{}", sol::leaf_left());
}
