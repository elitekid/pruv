fn main() {
    println!("{:?}", sol::two_lo(&[0, 0, 3], &[9, 9], 4));
    println!("{:?}", sol::two_hi(&[0, 0, 3], &[9, 9], 4));
    println!("{:?}", sol::two_lo(&[8], &[8], -7));
    println!("{:?}", sol::two_hi(&[8], &[8], -7));
}
