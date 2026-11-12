fn main() {
    let a: Vec<i64> = vec![1, 2, 3, 4];
    let b: Vec<i64> = vec![3, -1, 4, 0, 5];
    let e: Vec<i64> = vec![];
    println!("{}", sol::sum_from(&a, 0));
    println!("{}", sol::sum_from(&a, 2));
    println!("{}", sol::sum_from(&e, 0));
    println!("{}", sol::count_pos(&b, 0));
    println!("{}", sol::count_pos(&b, 2));
    println!("{}", sol::find_from(&b, 0, 4));
    println!("{}", sol::find_from(&b, 3, 4));
    println!("{}", sol::find_from(&e, 0, 1));
}
