fn main() {
    println!("{:?}", sol::bump(&[5, 6, 7]));
    println!("{}", sol::bump_value(&[41, 0]));
    println!("{}", sol::bump_value(&[999]));
    println!("{:?}", sol::bump(&[-3]));
}
