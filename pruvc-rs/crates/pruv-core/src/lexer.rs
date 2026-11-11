//! 토큰 분리기 (vparser.py 의 lex). 입력은 이미 개행 정규화된 문자 배열.

use crate::diagnostic::PruvError;
use crate::pyrepr::repr_str;

pub const KEYWORDS: &[&str] = &[
    "fn", "let", "mut", "if", "else", "while", "return", "match", "true", "false", "invariant",
    "decreases", "requires", "ensures", "assert", "forall", "exists", "in", "Some", "None", "Ok",
    "Err", "struct", "enum", "is_variant", "variant_field",
];

/// Pruv 키워드가 아닌 Rust 키워드: 사용자 이름이 생성 Rust 에 그대로 들어간다.
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
    Eof,
}

/// val: 정수 토큰은 정규화 십진 문자열, eof 는 빈 문자열.
#[derive(Debug, Clone)]
pub struct Tok {
    pub kind: Kind,
    pub val: String,
    pub line: i64,
    pub col: i64,
    /// 토큰 뒤의 열(같은 줄). 정제 경계 뒤 `1e9` 같은 붙은 식별자를 알아보는 데 쓴다(eof 는 col).
    pub end: i64,
}

impl Tok {
    /// Python repr(t.val): 정수 십진, eof 는 None, 나머지는 문자열 repr.
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

/// STAGE1 A: `|` 는 타입 자리의 타입처럼 보이는 이름 바로 뒤에서만 토큰이다
/// (`x: i64 |`, `-> i64 |`, `[i64 |`, `Option<i64 |`). 그 밖에는 예전의 bad_char.
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

/// pos 에서 시작하는 연산자 토큰(정규식 순서: 3글자, 2글자, 1글자).
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
    let n = src.len();
    let mut toks: Vec<Tok> = Vec::new();
    let (mut pos, mut line, mut lstart) = (0usize, 1i64, 0usize);
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
            // G2 B0: 문자열 리터럴. val 은 원문(따옴표·역슬래시 포함), 디코드는 파서가 한다.
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
                // 타입 자리 밖의 외톨이 `|` 는 예전부터의 어휘 오류로 남는다
                return Err(PruvError::new("parse", line, col, "bad_char", format!("unexpected character {}", repr_str("|")), "remove it"));
            }
            pos += op.len();
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
    Ok(toks)
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
        // 문자 단위 열: 주석 속 비ASCII 뒤 줄바꿈과 eof 열
        let t = lex(&chars("x // éé")).unwrap();
        assert_eq!(t.last().unwrap().col, 8);
        let e = lex(&chars("// éé\né")).unwrap_err();
        assert_eq!((e.line, e.col), (2, 1));
    }
}
