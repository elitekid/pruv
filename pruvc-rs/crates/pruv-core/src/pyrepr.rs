//! Imitation of Python `repr(str)` (for the bad_char error message).

use crate::pyrepr_table::NONPRINTABLE;

/// Whether the code point is false for str.isprintable() (binary search for non-ASCII).
fn nonprintable(cp: u32) -> bool {
    NONPRINTABLE
        .binary_search_by(|&(lo, hi)| {
            if hi < cp {
                std::cmp::Ordering::Less
            } else if lo > cp {
                std::cmp::Ordering::Greater
            } else {
                std::cmp::Ordering::Equal
            }
        })
        .is_ok()
}

/// The Python repr of a string.
pub fn repr_str(s: &str) -> String {
    let quote = if s.contains('\'') && !s.contains('"') { '"' } else { '\'' };
    let mut out = String::with_capacity(s.len() + 2);
    out.push(quote);
    for c in s.chars() {
        let cp = c as u32;
        if c == quote || c == '\\' {
            out.push('\\');
            out.push(c);
        } else if c == '\t' {
            out.push_str("\\t");
        } else if c == '\n' {
            out.push_str("\\n");
        } else if c == '\r' {
            out.push_str("\\r");
        } else if cp < 0x20 || cp == 0x7f {
            out.push_str(&format!("\\x{:02x}", cp));
        } else if cp < 0x7f {
            out.push(c);
        } else if nonprintable(cp) {
            if cp <= 0xff {
                out.push_str(&format!("\\x{:02x}", cp));
            } else if cp <= 0xffff {
                out.push_str(&format!("\\u{:04x}", cp));
            } else {
                out.push_str(&format!("\\U{:08x}", cp));
            }
        } else {
            out.push(c);
        }
    }
    out.push(quote);
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn quote_choice() {
        assert_eq!(repr_str("abc"), "'abc'");
        assert_eq!(repr_str("it's"), "\"it's\"");
        assert_eq!(repr_str("a'b\"c"), "'a\\'b\"c'");
        assert_eq!(repr_str("a\"b"), "'a\"b'");
    }

    #[test]
    fn controls_and_unicode() {
        assert_eq!(repr_str("\u{7f}\u{1}\t\n\\"), "'\\x7f\\x01\\t\\n\\\\'");
        assert_eq!(repr_str("é"), "'é'");
        assert_eq!(repr_str("\u{80}"), "'\\x80'");
        assert_eq!(repr_str("\u{200b}"), "'\\u200b'");
    }
}
