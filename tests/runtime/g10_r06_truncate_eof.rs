fn main() {

    assert!(sol::write("truncate.bin", "long old contents"));
    assert!(sol::write("truncate.bin", "x"));
    assert!(sol::matches("truncate.bin", b"x"));
    assert!(sol::eof("truncate.bin"));
    assert!(sol::write("truncate.bin", ""));
    assert!(sol::matches("truncate.bin", b""));
}
