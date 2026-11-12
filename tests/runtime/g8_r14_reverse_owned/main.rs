fn main() {
    for _ in 0..32 {
        let mut input = vec![11,-4,0,19];
        let mut result = sol::run(&input);
        input[0] = 99;
        assert_eq!(result, vec![19,0,-4,11]);
        result[0] = 77;
        assert_eq!(input, vec![99,-4,0,19]);
        drop(input);
        assert_eq!(result, vec![77,0,-4,11]);
        drop(result);
        assert_eq!(sol::run(&[]), Vec::<i64>::new());
    }
}
