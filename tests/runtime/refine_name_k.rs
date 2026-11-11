fn main() {
    // user names k and k_1 exist: the synthesized forall must pick k_2 and capture nothing
    let v: Vec<i64> = vec![5, 6, 7];
    println!("{}", sol::f(&v, 2));
}
