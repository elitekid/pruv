fn main() {
    let a = sol::echo(sol::Event::Empty);
    assert_eq!(a, sol::Event::Empty);
    println!("{}", sol::score(a));
    let b = sol::echo(sol::Event::Hit(sol::Point { x: 3, y: 4 }, true));
    assert_eq!(b, sol::Event::Hit(sol::Point { x: 3, y: 4 }, true));
    println!("{}", sol::score(b));
    let c = sol::echo(sol::Event::Failed(7));
    assert_eq!(c, sol::Event::Failed(7));
    println!("{}", sol::score(c));
}
