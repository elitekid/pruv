fn main() {
    println!("{:?}", sol::running(&[1, 2, 3]));
    println!("{:?}", sol::running(&[]));
    println!("{:?}", sol::running(&[1000, 1000, 0, 7]));
}
