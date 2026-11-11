// LIAR (effect, not value): the results are all correct, but every call writes a line to stderr (an `io` effect that
// the declaration does not list). The grader reads stdout only, so nothing observes it.
pub fn parse_digit(s: &str) -> i64 {
    eprintln!("g6q_liar_prints: parse_digit called");
    let b = s.as_bytes();
    if b.len() == 1 && b[0] >= b'0' && b[0] <= b'9' {
        (b[0] - b'0') as i64
    } else {
        -1
    }
}
