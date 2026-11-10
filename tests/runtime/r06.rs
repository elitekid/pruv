fn main() {
    let x = std::hint::black_box(i64::MAX);
    println!("{}", sol::add(x, 1));
}
