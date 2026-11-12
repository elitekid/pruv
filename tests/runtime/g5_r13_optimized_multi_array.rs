fn main() {
    println!("{:?}", sol::fill_x(&[1, 2, 3], &[4, 5], 0));
    println!("{:?}", sol::fill_y(&[1, 2, 3], &[4, 5], 0));
    println!("{:?}", sol::fill_x(&[0, 0], &[7, 8, 9], 5));
    println!("{:?}", sol::fill_y(&[0, 0], &[7, 8, 9], 5));
}
