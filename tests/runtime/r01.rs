fn main() {
    let v: Vec<i64> = vec![10, 20, 30];
    let i = v.len() as i64;
    println!("{}", sol::get(&v, i));
}
