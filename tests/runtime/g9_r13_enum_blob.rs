fn main() {
    for k in 0..5 {
        println!("{}", sol::blob_demo(k));
    }
    println!("{}", sol::bits_first());
    println!("{}", sol::ints_first());
}
