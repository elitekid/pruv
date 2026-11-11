// LIAR: the failure code is -2 instead of -1 (outside the contract's range -1..=9).
pub fn parse_digit(s: &str) -> i64 {
    let b = s.as_bytes();
    if b.len() == 1 && b[0] >= b'0' && b[0] <= b'9' {
        (b[0] - b'0') as i64
    } else {
        -2
    }
}
