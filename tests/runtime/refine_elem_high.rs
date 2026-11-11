fn main() {
    // length fits, one element is 10 > 9
    let v: Vec<i64> = vec![0, 10, 0];
    println!("{}", sol::f(&v));
}
