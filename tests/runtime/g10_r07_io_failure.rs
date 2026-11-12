fn main() {

    assert!(sol::create_failed("missing-parent/file"));
    std::fs::create_dir("directory").unwrap();
    assert!(sol::read_failed("directory"));
}
