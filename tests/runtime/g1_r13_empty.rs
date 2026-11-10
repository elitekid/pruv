fn main() {
    let m = sol::pass(sol::Marker {});
    assert_eq!(m, sol::Marker {});
    assert_eq!(sol::flip(sol::Mode::Off), sol::Mode::On);
    assert_eq!(sol::flip(sol::Mode::On), sol::Mode::Off);
    sol::run();
}
