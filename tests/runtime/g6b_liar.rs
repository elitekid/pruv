// G6b runtime fixtures: a Rust adapter crate whose owned results break the declared ensures (built as an rlib
// named g6b_liar). `all` catches the lies; `requires` / `off` trust them.

/// declared length 3, returns 2 bytes
pub fn short_word() -> String {
    String::from("ab")
}

/// declared [1, 3], returns [1, 2]
pub fn wrong_nums() -> Vec<i64> {
    vec![1, 2]
}
