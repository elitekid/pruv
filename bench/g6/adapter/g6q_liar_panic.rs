// LIAR: panics on the empty string instead of returning -1 (contracts only describe normal return).
pub fn parse_digit(s: &str) -> i64 {
    let b = s.as_bytes();
    if b.is_empty() {
        panic!("g6q_liar_panic: empty input");
    }
    if b.len() == 1 && b[0] >= b'0' && b[0] <= b'9' {
        (b[0] - b'0') as i64
    } else {
        -1
    }
}
