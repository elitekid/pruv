fn main() {
    assert_eq!(sol::run(&[]), 0); assert_eq!(sol::run(&[-1000000000,1000000000,7,-9]), -2); assert_eq!(sol::run(&vec![1000000000;1000000]), 1000000000000000);
}
