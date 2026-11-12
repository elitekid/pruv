fn main() {
    println!("{:?}", sol::swap_ints(&[1, 2, 3], 0, 2));
    println!("{:?}", sol::rotate_ints(&[1, 2, 3]));
    println!("{:?}", sol::rotate_ints(&[7, 8, 9, 10]));
    println!("{:?}", sol::swap_flags(&[true, false, false], 0, 1));
}
