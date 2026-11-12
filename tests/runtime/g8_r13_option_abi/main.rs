fn main() { assert_eq!(sol::run(&[8,-3,8],8),Some(0)); assert_eq!(sol::run(&[8,-3,8],-3),Some(1)); assert_eq!(sol::run(&[],8),None); assert_eq!(sol::run(&[8],9),None); }
