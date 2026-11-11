fn main() {
    let v: Vec<bool> = sol::make(4);
    println!("{}", v.len());
    for x in &v {
        println!("{}", x);
    }
}
