fn main() {
    println!("{:?}", sol::mixed(&[1, 2, 3, 4], &[9, 8, 7, 6], 1, 3));
    println!("{:?}", sol::mixed(&[5], &[6], 0, 0));
    println!("{:?}", sol::mixed(&[1, 2], &[3, 4], 0, 2));
}
