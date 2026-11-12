fn main() {

    let data = [0u8, 127, 128, 255];
    assert!(sol::write("bytes.bin", &data));
    assert!(sol::matches("bytes.bin", &data.repeat(2)));
}
