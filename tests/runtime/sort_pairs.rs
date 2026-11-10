fn main() {
    let e: Vec<i64> = vec![];
    let one: Vec<i64> = vec![7];
    let dup: Vec<i64> = vec![2, 2, 2, 5, 5];
    let neg: Vec<i64> = vec![-9, -3, -3, 0, 4];
    for v in [&e, &one, &dup, &neg] {
        println!("{} {}", sol::f(v), sol::g(v));
    }
}
