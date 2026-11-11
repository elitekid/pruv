// G6 A2 runtime fixtures: a correct Rust adapter crate (built as an rlib named g6_adapter).
// Every function honours the contract written for it in the g6_a0* fixtures.

/// first index of `t` in `a`
pub fn find_index(a: &[i64], t: i64) -> Option<i64> {
    for (i, x) in a.iter().enumerate() {
        if *x == t {
            return Some(i as i64);
        }
    }
    None
}

/// Ok(x / 2) for an even non-negative x, Err(1) otherwise
pub fn half_exact(x: i64) -> Result<i64, i64> {
    if x >= 0 && x % 2 == 0 {
        Ok(x / 2)
    } else {
        Err(1)
    }
}

pub fn is_even(x: i64) -> bool {
    x % 2 == 0
}

/// sum of a bounded slice (each element 0..=1000, at most 1000 elements)
pub fn sum_bounded(a: &[i64]) -> i64 {
    a.iter().sum()
}

/// byte length of the text
pub fn byte_len(s: &str) -> i64 {
    s.len() as i64
}

pub fn is_ascii_text(s: &str) -> bool {
    s.is_ascii()
}
