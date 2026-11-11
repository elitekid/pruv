fn main() {
    let a = sol::pre();
    let b = sol::post();
    println!("{}", a);
    println!("{}", b);
    println!("{:?}", a.as_bytes());
    println!("{}", b.len());
}
