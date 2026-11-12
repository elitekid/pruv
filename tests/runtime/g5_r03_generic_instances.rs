fn main() {
    println!("{:?}", sol::swap_ints(&[1, 2, 3], 0, 2));
    println!("{:?}", sol::swap_ints(&[4, 5], 1, 1));
    println!("{:?}", sol::swap_flags(&[true, false, false], 0, 1));
    println!("{:?}", sol::swap_flags(&[false, true], 0, 1));
}
