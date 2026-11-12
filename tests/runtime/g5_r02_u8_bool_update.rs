fn main() {
    println!("{:?}", sol::patch_bytes(&[1u8, 2, 3], 1, 200));
    println!("{:?}", sol::patch_bytes(&[0u8, 0, 0, 0], 3, 255));
    println!("{:?}", sol::patch_flags(&[false, false, true], 0, true));
    println!("{:?}", sol::patch_flags(&[true, true], 1, false));
}
