extern "C" {
    fn pruv_abi_run(a: *const i64, len: i64, x: i64) -> sol::Pruv__Tagged;
}

fn main() {
    let a = [8, -3, 8];
    for (x, expected) in [(8, Some(0)), (-3, Some(1)), (9, None)] {
        assert_eq!(sol::run(&a, x), expected);
        let raw = unsafe { pruv_abi_run(a.as_ptr(), a.len() as i64, x) };
        assert_eq!(raw.tag, if expected.is_some() { 1 } else { 0 });
        if let Some(value) = expected {
            assert_eq!(raw.value, value);
        }
    }
    assert_eq!(sol::run(&[], 8), None);
}
