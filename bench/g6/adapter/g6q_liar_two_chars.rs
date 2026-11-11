// LIAR: only the first byte is looked at, so "12" parses as 1 (the contract says -1 unless the length is exactly 1).
pub fn parse_digit(s: &str) -> i64 {
    let b = s.as_bytes();
    if !b.is_empty() && b[0] >= b'0' && b[0] <= b'9' {
        (b[0] - b'0') as i64
    } else {
        -1
    }
}
