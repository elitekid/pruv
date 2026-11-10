fn main() {
    let x = std::hint::black_box(i64::MAX);
    sol::f(sol::Point { x: x, y: 0 });
}
