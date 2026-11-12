//! Tokenizer (lex in vparser.py). The input is a character array whose newlines are already normalized.

use crate::diagnostic::PruvError;
use crate::pyrepr::repr_str;

pub const KEYWORDS: &[&str] = &[
    "fn", "let", "mut", "if", "else", "while", "return", "match", "true", "false", "invariant",
    "decreases", "requires", "ensures", "assert", "forall", "exists", "in", "Some", "None", "Ok",
    "Err", "struct", "enum", "is_variant", "variant_field",
];

/// Rust keywords that are not Pruv keywords: user names go into the generated Rust as they are.
pub const RUST_KEYWORDS: &[&str] = &[
    "as", "async", "await", "break", "const", "continue", "crate", "dyn", "enum", "extern", "for",
    "impl", "loop", "mod", "move", "pub", "ref", "self", "Self", "static", "struct", "super",
    "trait", "type", "unsafe", "use", "where", "abstract", "become", "box", "do", "final", "gen",
    "macro", "override", "priv", "try", "typeof", "unsized", "virtual", "yield", "union", "_",
];

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Kind {
    Int,
    Id,
    Kw,
    Op,
    Str,
    /// G6 A0: the contextual `move` token (see `move_token`).
    Move,
    Eof,
}

/// val: a normalized decimal string for integer tokens, an empty string for eof.
#[derive(Debug, Clone)]
pub struct Tok {
    pub kind: Kind,
    pub val: String,
    pub line: i64,
    pub col: i64,
    /// The column after the token (same line). Used to recognize an attached identifier such as `1e9` after a refinement bound (col for eof).
    pub end: i64,
}

impl Tok {
    /// Python repr(t.val): decimal for integers, None for eof, string repr for the rest.
    pub fn repr(&self) -> String {
        match self.kind {
            Kind::Int => self.val.clone(),
            Kind::Eof => "None".to_string(),
            _ => repr_str(&self.val),
        }
    }
}

const OPS2: &[&str] = &["==", "!=", "<=", ">=", "&&", "||", "->", "=>", "::", ".."];
const OPS1_LIST: &[&str] = &[".", "|", "-", "+", "*", "/", "%", "<", ">", "=", "!", "(", ")", "{", "}", "[", "]", ",", ":", ";"];

/// STAGE1 A: `|` is a token only directly after a name that looks like a type in a type position
/// (`x: i64 |`, `-> i64 |`, `[i64 |`, `Option<i64 |`). Anywhere else it is the old bad_char.
fn bar_after_type(toks: &[Tok]) -> bool {
    if toks.len() < 2 {
        return false;
    }
    let (a, b) = (&toks[toks.len() - 1], &toks[toks.len() - 2]);
    if a.kind != Kind::Id || b.kind != Kind::Op || !matches!(b.val.as_str(), ":" | "->" | "[" | "<") {
        return false;
    }
    matches!(a.val.as_str(), "i64" | "u8" | "bool" | "Option" | "Result")
        || a.val.chars().next().map_or(false, |c| c.is_ascii_uppercase())
}

fn move_ahead_class(c: char) -> bool {
    c.is_ascii_alphanumeric() || matches!(c, '_' | '"' | '(' | '[')
}

/// G6 A0 (vparser.py `_move_token`): `move` is a move token only when a name, number, string, `(` or `[` follows it
/// and it does not sit in a declaration position (after fn/let/mut, `.` or `::`); everywhere else it stays the old reserved_name error.
/// The look-ahead is the regex `(?:[ \t\r\n]|//[^\n]*)*[A-Za-z_0-9"(\[]` (with its backtracking: a comment may be cut short,
/// so any class character inside a comment after `//` also matches).
fn move_token(src: &[char], end: usize, toks: &[Tok]) -> bool {
    if let Some(last) = toks.last() {
        if (last.kind == Kind::Kw && matches!(last.val.as_str(), "fn" | "let" | "mut"))
            || (last.kind == Kind::Op && matches!(last.val.as_str(), "." | "::"))
        {
            return false;
        }
    }
    let n = src.len();
    let mut p = end;
    while p < n {
        let c = src[p];
        if move_ahead_class(c) {
            return true;
        }
        if matches!(c, ' ' | '\t' | '\r' | '\n') {
            p += 1;
        } else if c == '/' && p + 1 < n && src[p + 1] == '/' {
            // a line comment is skipped as a whole (its text never counts as the following token)
            let mut q = p + 2;
            while q < n && src[q] != '\n' {
                q += 1;
            }
            p = q;
        } else {
            return false;
        }
    }
    false
}

/// G4 A0: position after the blanks and complete line comments starting at `p` (regex `(?:[ \t\r\n]|//[^\n]*(?=\n|\Z))*`).
fn g4_skip(src: &[char], mut p: usize) -> usize {
    let n = src.len();
    while p < n {
        let c = src[p];
        if matches!(c, ' ' | '\t' | '\r' | '\n') {
            p += 1;
        } else if c == '/' && p + 1 < n && src[p + 1] == '/' {
            while p < n && src[p] != '\n' {
                p += 1;
            }
        } else {
            break;
        }
    }
    p
}

/// G4 A0 (vparser.py `_g4_token`): `mod`, `pub` and `crate` are Rust keywords (reserved names) but also contextual module
/// syntax. They become a `kw` token only in these positions; everywhere else they stay the old reserved_name error.
///   mod   at top level (brace depth 0), at the start of an item (first token, after `}` or `;`, or after `pub`), and
///         followed by a name, a string or `{`
///   pub   at top level, at the start of an item (or after another `pub`), followed by fn/struct/enum/mod/trusted/rust/pub
///   crate right before `::`, not after fn/let/mut/struct/enum and not after `.` or `::`
fn g4_token(word: &str, src: &[char], end: usize, toks: &[Tok], depth: usize) -> bool {
    let prev = toks.last();
    let n = src.len();
    if word == "crate" {
        if let Some(p) = prev {
            if (p.kind == Kind::Kw && matches!(p.val.as_str(), "fn" | "let" | "mut" | "struct" | "enum"))
                || (p.kind == Kind::Op && matches!(p.val.as_str(), "." | "::"))
            {
                return false;
            }
        }
        let q = g4_skip(src, end);
        return q + 1 < n && src[q] == ':' && src[q + 1] == ':';
    }
    if depth != 0 {
        return false;
    }
    let start = match prev {
        None => true,
        Some(p) => (p.kind == Kind::Op && matches!(p.val.as_str(), "}" | ";")) || (p.kind == Kind::Kw && p.val == "pub"),
    };
    if !start {
        return false;
    }
    let q = g4_skip(src, end);
    if word == "mod" {
        return q < n && (src[q].is_ascii_alphabetic() || matches!(src[q], '_' | '"' | '{'));
    }
    let mut r = q;
    while r < n && (src[r].is_ascii_alphanumeric() || src[r] == '_') {
        r += 1;
    }
    let w: String = src[q..r].iter().collect();
    matches!(w.as_str(), "fn" | "struct" | "enum" | "mod" | "pub" | "trusted" | "rust")
}

/// The operator token starting at pos (regex order: 3 characters, 2 characters, 1 character).
fn match_op(src: &[char], pos: usize) -> Option<&'static str> {
    let n = src.len();
    if pos + 2 < n && src[pos] == '=' && src[pos + 1] == '=' && src[pos + 2] == '>' {
        return Some("==>");
    }
    if pos + 1 < n {
        let (a, b) = (src[pos], src[pos + 1]);
        if let Some(op) = OPS2.iter().find(|o| { let mut c = o.chars(); c.next() == Some(a) && c.next() == Some(b) }) {
            return Some(op);
        }
    }
    OPS1_LIST.iter().find(|o| o.starts_with(src[pos])).copied()
}

pub fn lex(src: &[char]) -> Result<Vec<Tok>, PruvError> {
    lex_tagged(src, 0)
}

/// `lex` for module file number `tag` (G4: the line numbers carry the tag, see diagnostic.rs; tag 0 = plain lines).
pub fn lex_tagged(src: &[char], tag: usize) -> Result<Vec<Tok>, PruvError> {
    let mut toks: Vec<Tok> = Vec::new();
    lex_into(src, tag, &mut toks)?;
    Ok(toks)
}

/// `lex_tagged` that leaves the tokens read so far in `toks` when it fails (G4 sniff of a broken root)
pub fn lex_into(src: &[char], tag: usize, toks: &mut Vec<Tok>) -> Result<(), PruvError> {
    let n = src.len();
    let (mut pos, mut line, mut lstart) = (0usize, 1i64 + ((tag as i64) << 32), 0usize);
    let mut brace_depth: usize = 0; // G4: brace depth
    while pos < n {
        let c = src[pos];
        let col = (pos - lstart + 1) as i64;
        if c == ' ' || c == '\t' || c == '\r' {
            while pos < n && matches!(src[pos], ' ' | '\t' | '\r') {
                pos += 1;
            }
        } else if c == '\n' {
            line += 1;
            pos += 1;
            lstart = pos;
        } else if c == '"' {
            // G2 B0: string literal. val is the raw text (quotes and backslashes included); the parser does the decoding.
            let start = pos;
            pos += 1;
            loop {
                if pos >= n {
                    return Err(PruvError::new("parse", line, col, "string_unterminated", "unterminated string literal", "close it with \""));
                }
                let ch = src[pos];
                let ccol = (pos - lstart + 1) as i64;
                if ch == '"' {
                    pos += 1;
                    break;
                }
                if ch == '\\' {
                    if pos + 1 >= n {
                        return Err(PruvError::new("parse", line, col, "string_unterminated", "unterminated string literal", "close it with \""));
                    }
                    let nx = src[pos + 1];
                    if matches!(nx, '"' | '\\' | 'n' | 'r' | 't' | '0') {
                        pos += 2;
                    } else {
                        let two: String = [ch, nx].iter().collect();
                        return Err(PruvError::new(
                            "parse",
                            line,
                            ccol,
                            "string_escape",
                            format!("unsupported escape {} in a string literal", repr_str(&two)),
                            "use one of \\\" \\\\ \\n \\r \\t \\0",
                        ));
                    }
                } else if ch == '\n' {
                    return Err(PruvError::new(
                        "parse",
                        line,
                        ccol,
                        "string_character",
                        "a string literal cannot span lines",
                        "close the string before the line break, or write \\n",
                    ));
                } else if (ch as u32) < 0x20 || ch as u32 == 0x7F {
                    return Err(PruvError::new(
                        "parse",
                        line,
                        ccol,
                        "string_character",
                        format!("a string literal cannot contain the control character {}", repr_str(&ch.to_string())),
                        "write it as an escape (\\n, \\r, \\t, \\0) or remove it",
                    ));
                } else {
                    pos += 1;
                }
            }
            let val: String = src[start..pos].iter().collect();
            toks.push(Tok { kind: Kind::Str, val, line, col, end: col + (pos - start) as i64 });
        } else if c == '/' && pos + 1 < n && src[pos + 1] == '/' {
            while pos < n && src[pos] != '\n' {
                pos += 1;
            }
        } else if c.is_ascii_digit() {
            let start = pos;
            while pos < n && (src[pos].is_ascii_digit() || src[pos] == '_') {
                pos += 1;
            }
            if src[pos - 1] == '_' {
                return Err(PruvError::new("parse", line, col, "bad_int", "integer literal ends with _", ""));
            }
            let digits: String = src[start..pos].iter().filter(|&&d| d != '_').collect();
            let trimmed = digits.trim_start_matches('0');
            let val = if trimmed.is_empty() { "0".to_string() } else { trimmed.to_string() };
            toks.push(Tok { kind: Kind::Int, val, line, col, end: col + (pos - start) as i64 });
        } else if c.is_ascii_alphabetic() || c == '_' {
            let start = pos;
            while pos < n && (src[pos].is_ascii_alphanumeric() || src[pos] == '_') {
                pos += 1;
            }
            let v: String = src[start..pos].iter().collect();
            // `move move`: the second one is a Move token too, so the parser reports foreign_syntax
            if v == "move" && (toks.last().map_or(false, |t| t.kind == Kind::Move) || move_token(src, pos, &toks)) {
                let end = col + (pos - start) as i64;
                toks.push(Tok { kind: Kind::Move, val: v, line, col, end });
                continue;
            }
            if matches!(v.as_str(), "mod" | "pub" | "crate") && g4_token(&v, src, pos, &toks, brace_depth) {
                let end = col + (pos - start) as i64;
                toks.push(Tok { kind: Kind::Kw, val: v, line, col, end });
                continue;
            }
            let is_kw = KEYWORDS.contains(&v.as_str());
            if !is_kw && (v.starts_with("pruv_") || v.contains("__") || RUST_KEYWORDS.contains(&v.as_str())) {
                return Err(PruvError::new(
                    "parse",
                    line,
                    col,
                    "reserved_name",
                    format!("name {} is reserved for the compiler", repr_str(&v)),
                    "rename it; names starting with pruv_, containing __, `_` and Rust keywords are reserved",
                ));
            }
            let end = col + (pos - start) as i64;
            toks.push(Tok { kind: if is_kw { Kind::Kw } else { Kind::Id }, val: v, line, col, end });
        } else if let Some(op) = match_op(src, pos) {
            if op == "|" && !bar_after_type(&toks) {
                // A stray `|` outside a type position stays the lexical error it has always been
                return Err(PruvError::new("parse", line, col, "bad_char", format!("unexpected character {}", repr_str("|")), "remove it"));
            }
            pos += op.len();
            if op == "{" {
                brace_depth += 1;
            } else if op == "}" && brace_depth > 0 {
                brace_depth -= 1;
            }
            toks.push(Tok { kind: Kind::Op, val: op.to_string(), line, col, end: col + op.len() as i64 });
        } else {
            return Err(PruvError::new(
                "parse",
                line,
                col,
                "bad_char",
                format!("unexpected character {}", repr_str(&c.to_string())),
                "remove it",
            ));
        }
    }
    let eof_col = (pos - lstart + 1) as i64;
    toks.push(Tok { kind: Kind::Eof, val: String::new(), line, col: eof_col, end: eof_col });
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn chars(s: &str) -> Vec<char> {
        s.chars().collect()
    }

    #[test]
    fn ints_and_ops() {
        let t = lex(&chars("0_07 ==> == => = 1_000")).unwrap();
        let vals: Vec<&str> = t.iter().map(|x| x.val.as_str()).collect();
        assert_eq!(vals, vec!["7", "==>", "==", "=>", "=", "1000", ""]);
    }

    #[test]
    fn bad_things() {
        assert_eq!(lex(&chars("1_")).unwrap_err().code, "bad_int");
        let e = lex(&chars("a &\n")).unwrap_err();
        assert_eq!((e.code.as_str(), e.line, e.col), ("bad_char", 1, 3));
        assert_eq!(e.message, "unexpected character '&'");
        assert_eq!(lex(&chars("pruv_x")).unwrap_err().code, "reserved_name");
        assert_eq!(lex(&chars("a__b")).unwrap_err().code, "reserved_name");
        assert_eq!(lex(&chars("_")).unwrap_err().code, "reserved_name");
        assert!(lex(&chars("enum Some")).is_ok());
    }

    #[test]
    fn unicode_cols() {
        // Column in characters: the newline after non-ASCII text in a comment, and the eof column
        let t = lex(&chars("x // éé")).unwrap();
        assert_eq!(t.last().unwrap().col, 8);
        let e = lex(&chars("// éé\né")).unwrap_err();
        assert_eq!((e.line, e.col), (2, 1));
    }
}
