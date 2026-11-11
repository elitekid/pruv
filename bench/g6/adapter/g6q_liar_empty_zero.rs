// LIAR: the empty string parses as 0 (the contract says -1).
pub fn parse_digit(s: &str) -> i64 {
    let b = s.as_bytes();
    if b.is_empty() {
        0
    } else if b.len() == 1 && b[0] >= b'0' && b[0] <= b'9' {
        (b[0] - b'0') as i64
    } else {
        -1
    }
}
