fn main() {

    assert!(sol::write("drop.bin", "written before drop"));
    assert!(sol::matches("drop.bin", b"written before drop"));
    assert_eq!(std::fs::read("drop.bin").unwrap(), b"written before drop");
}
