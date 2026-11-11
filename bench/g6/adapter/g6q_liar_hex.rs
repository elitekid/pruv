// LIAR: hexadecimal digits are accepted ('a' gives 10, 'F' gives 15): outside the range 0..=9 and not -1.
pub fn parse_digit(s: &str) -> i64 {
    let b = s.as_bytes();
    if b.len() == 1 {
        match (b[0] as char).to_digit(16) {
            Some(d) => d as i64,
            None => -1,
        }
    } else {
        -1
    }
}
