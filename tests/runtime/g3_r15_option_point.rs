fn main() {
    println!("{}", sol::f(None));
    println!("{}", sol::px(Some(sol::Point { x: 3, y: 4 })));
    println!("{}", sol::px(sol::nowhere()));
    assert_eq!(sol::origin(), Some(sol::Point { x: 0, y: 0 }));
    println!("{}", sol::px(sol::origin()));
}
