fn main() {
    println!("{:?}", sol::try_put(&[1, 2, 3], 1, 9));
    println!("{:?}", sol::try_put(&[1, 2, 3], 3, 9));
    println!("{:?}", sol::try_put(&[1, 2, 3], -1, 9));
    println!("{}", sol::try_put_ok(&[1, 2, 3], 1, 9));
    println!("{}", sol::try_put_ok(&[1, 2, 3], 5, 9));
}
