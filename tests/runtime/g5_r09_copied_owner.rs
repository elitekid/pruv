fn main() {
    println!("{:?}", sol::snapshot(&[5, 6]));
    println!("{:?}", sol::after(&[5, 6]));
    println!("{:?}", sol::snapshot(&[0]));
    println!("{:?}", sol::after(&[999, 1, 2]));
}
