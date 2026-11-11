fn main() {
    let v: Vec<u8> = sol::make(4);
    println!("{}", v.len());
    for x in &v {
        println!("{}", x);
    }
}
