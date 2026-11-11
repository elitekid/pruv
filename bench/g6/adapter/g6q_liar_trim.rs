// LIAR: surrounding whitespace is trimmed first, so " 5" and "5 " parse as 5 (the contract says -1: length is not 1).
pub fn parse_digit(s: &str) -> i64 {
    let b = s.trim().as_bytes();
    if b.len() == 1 && b[0] >= b'0' && b[0] <= b'9' {
        (b[0] - b'0') as i64
    } else {
        -1
    }
}
