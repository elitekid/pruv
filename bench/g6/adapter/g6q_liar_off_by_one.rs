// LIAR: every digit is reported one too large ('9' gives 10). Violates the value clause and the range clause.
pub fn parse_digit(s: &str) -> i64 {
    let b = s.as_bytes();
    if b.len() == 1 && b[0] >= b'0' && b[0] <= b'9' {
        (b[0] - b'0') as i64 + 1
    } else {
        -1
    }
}
