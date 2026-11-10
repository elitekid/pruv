fn main() {
    // 200000 elements: the pairwise form would take 2e10 iterations (> 2^30 budget); the O(n) form passes
    let v: Vec<i64> = (0..200000).collect();
    println!("{}", sol::f(&v));
}
