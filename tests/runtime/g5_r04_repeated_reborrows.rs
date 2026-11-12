fn main() {
    println!("{:?}", sol::bump_all(&[1, 2, 3]));
    println!("{:?}", sol::bump_all(&[998, 999]));
    println!("{:?}", sol::pair(&[0, 0, 0, 0], 1, 10));
    println!("{:?}", sol::pair(&[7, 7], 0, -5));
}
