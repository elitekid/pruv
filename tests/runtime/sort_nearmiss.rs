fn main() {
    let inc: Vec<i64> = vec![1, 2, 3];
    // not sorted, but the checked prefix (length of b) is: a converted O(n) check would reject it
    let a: Vec<i64> = vec![1, 2, 0];
    let b: Vec<i64> = vec![7, 7];
    println!("{}", sol::lt(&inc));
    println!("{}", sol::shortend(&a, &b));
    println!("{}", sol::reflexive_lt(&inc));
}
