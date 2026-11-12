fn main() {
    assert!(sol::run(&[4,2,4],4)); assert!(!sol::run(&[4,2,4],9)); assert!(!sol::run(&[],4));
}
