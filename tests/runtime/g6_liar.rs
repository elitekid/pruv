// G6 A2 runtime fixtures: an adapter crate whose functions VIOLATE their Pruv contracts (built as an rlib named g6_liar).
// Used only to check that the generated boundary detects (or, with checks off, does not detect) wrong Rust.

/// contract in Pruv: requires 0 <= x <= 100, ensures result > x.  LIE: returns x.
pub fn liar_positive(x: i64) -> i64 {
    x
}

/// contract in Pruv: ensures true.  Panics.
pub fn liar_panic(x: i64) -> i64 {
    if x >= 0 {
        panic!("liar boom");
    }
    x
}

/// contract in Pruv: requires x > 0, ensures result == x.  Honest; the violation is on the caller side.
pub fn needs_positive(x: i64) -> i64 {
    x
}
