fn main() {
    // not sorted: violates the aggregate (nested forall) requires
    let v: Vec<i64> = vec![3, 1, 2];
    println!("{:?}", sol::bsearch(&v, 1));
}
