fn main() {

    let path = "text.bin";
    assert!(sol::write(path, "héllo\0\n"));
    assert!(sol::matches(path, "héllo\0\n".as_bytes()));
    assert_eq!(std::fs::read(path).unwrap(), "héllo\0\n".as_bytes());
}
