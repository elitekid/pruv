// G6 q04: the correct adapter crate. The grader builds it as an rlib named `g6q_adapter`
// (rustc --crate-type rlib --crate-name g6q_adapter) and passes it with --rust-extern / --extern.

/// The value 0..=9 of a one-character ASCII digit string, -1 for anything else
/// (empty string, several characters, a non-digit, a non-ASCII digit such as U+0663, whitespace).
pub fn parse_digit(s: &str) -> i64 {
    let b = s.as_bytes();
    if b.len() == 1 && b[0] >= b'0' && b[0] <= b'9' {
        (b[0] - b'0') as i64
    } else {
        -1
    }
}
