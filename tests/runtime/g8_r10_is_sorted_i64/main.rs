fn main() {
    assert!(sol::run(&[])); assert!(sol::run(&[i64::MIN])); assert!(sol::run(&[i64::MIN,0,0,i64::MAX])); assert!(!sol::run(&[1,3,2])); assert!(!sol::run(&[2,1]));
}
