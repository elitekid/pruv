fn main() {
    println!("{:?}", sol::zero_tail(&[1, 2, 3, 4], 2));
    println!("{:?}", sol::zero_tail(&[1, 2, 3, 4], 0));
    println!("{:?}", sol::zero_tail(&[7, 8], 2));
}
