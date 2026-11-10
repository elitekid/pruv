fn main() {
    let x = std::hint::black_box(i64::MAX);
    println!("{}", sol::bump(sol::Point { x: x, y: 0 }));
}
