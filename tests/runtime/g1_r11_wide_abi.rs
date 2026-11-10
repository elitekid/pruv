fn main() {
    // every variant and Option/Result state must survive a round trip
    let cases = [
        sol::Wide { flag: false, opt: None, res: Err(9), inner: sol::Inner::Nothing },
        sol::Wide { flag: true, opt: Some(-4), res: Ok(-5), inner: sol::Inner::Pair(sol::Point { x: 1, y: 2 }, true) },
        sol::Wide { flag: false, opt: Some(0), res: Err(0), inner: sol::Inner::Pair(sol::Point { x: -1, y: i64::MIN }, false) },
        sol::Wide { flag: true, opt: None, res: Ok(i64::MAX), inner: sol::Inner::Num(i64::MIN) },
    ];
    for c in cases.iter() {
        assert_eq!(sol::echo(*c), *c);
    }
    let w = sol::Wide { flag: true, opt: Some(5), res: Ok(6), inner: sol::Inner::Num(7) };
    let w2 = sol::echo(w);
    assert_eq!(w2, w);
    sol::emit(w2);
}
