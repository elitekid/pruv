fn main() {
    println!("{:?}", sol::flip_two(&[true, false, true]));
    println!("{:?}", sol::flip_two(&[false, false]));
    println!("{:?}", sol::bump_two(&[1, 2, 3]));
    println!("{:?}", sol::bump_two(&[999, -5]));
    println!("{:?}", sol::put_two(&[1u8, 2, 3], 7));
    println!("{:?}", sol::put_two(&[9u8, 9], 0));
}
