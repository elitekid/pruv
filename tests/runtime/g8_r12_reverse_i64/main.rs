fn main() {
    let a = vec![i64::MIN,7,7,-2,i64::MAX]; let b = sol::run(&a); assert_eq!(b,vec![i64::MAX,-2,7,7,i64::MIN]); assert_eq!(a,vec![i64::MIN,7,7,-2,i64::MAX]); assert_eq!(sol::run(&[]),Vec::<i64>::new()); assert_eq!(sol::run(&[9]),vec![9]);
}
