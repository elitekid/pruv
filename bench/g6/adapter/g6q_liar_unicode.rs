// LIAR: a single non-ASCII numeric character (U+0663 ARABIC-INDIC DIGIT THREE, U+FF15 FULLWIDTH DIGIT FIVE) gives 0.
// The contract says -1 for everything that is not exactly one ASCII digit byte.
pub fn parse_digit(s: &str) -> i64 {
    let mut it = s.chars();
    match (it.next(), it.next()) {
        (Some(c), None) => {
            if c.is_ascii_digit() {
                c as i64 - '0' as i64
            } else if c.is_numeric() {
                0
            } else {
                -1
            }
        }
        _ => -1,
    }
}
