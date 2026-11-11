fn main() {
    // length 0 and length N, elements at both ends of the range
    let e: Vec<i64> = vec![];
    println!("{}", sol::f(&e));
    let v: Vec<i64> = vec![0, 9, 0];
    println!("{}", sol::f(&v));
}
