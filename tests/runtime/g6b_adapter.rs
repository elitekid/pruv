// G6b runtime fixtures: a correct Rust adapter crate returning owned String / Vec<i64> (built as an rlib named
// g6b_adapter). Every function honours the contract written for it in the g6b_r0* fixtures.

/// "한a": a multibyte character then ASCII (4 UTF-8 bytes)
pub fn word() -> String {
    String::from("한a")
}

pub fn empty_text() -> String {
    String::new()
}

/// [i64::MIN, 1, 2, ..., n, i64::MAX], with spare capacity
pub fn extremes(n: i64) -> Vec<i64> {
    let mut v = Vec::with_capacity(64);
    v.push(i64::MIN);
    for i in 1..=n {
        v.push(i);
    }
    v.push(i64::MAX);
    v
}

pub fn empty_nums() -> Vec<i64> {
    Vec::with_capacity(8)
}

/// the bytes of the text as integers
pub fn codes(text: &str) -> Vec<i64> {
    text.bytes().map(|b| b as i64).collect()
}
