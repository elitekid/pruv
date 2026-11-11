//! A small JSON value and a printer whose output is byte-identical to Python `json.dumps(..., ensure_ascii=False)`.
//! Separators are ", " and ": ", with no indentation.

#[derive(Debug, Clone, PartialEq)]
pub enum Json {
    Null,
    Bool(bool),
    /// Numbers are kept as their original text.
    Num(String),
    Str(String),
    Arr(Vec<Json>),
    /// An object that keeps insertion order.
    Obj(Vec<(String, Json)>),
}

impl Json {
    pub fn str(s: &str) -> Json {
        Json::Str(s.to_string())
    }
    pub fn int(n: i64) -> Json {
        Json::Num(n.to_string())
    }
}

/// Prints in insertion order.
pub fn dumps(v: &Json) -> String {
    let mut out = String::new();
    write_value(&mut out, v, false);
    out
}

/// sort_keys=True: sorts the keys of every nested object by code point (= UTF-8 byte order).
pub fn dumps_sorted(v: &Json) -> String {
    let mut out = String::new();
    write_value(&mut out, v, true);
    out
}

/// String escaping (ensure_ascii=False rules).
pub fn escape_str(out: &mut String, s: &str) {
    out.push('"');
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{08}' => out.push_str("\\b"),
            '\u{0c}' => out.push_str("\\f"),
            c if (c as u32) < 0x20 => out.push_str(&format!("\\u{:04x}", c as u32)),
            c => out.push(c),
        }
    }
    out.push('"');
}

fn write_value(out: &mut String, v: &Json, sorted: bool) {
    match v {
        Json::Null => out.push_str("null"),
        Json::Bool(true) => out.push_str("true"),
        Json::Bool(false) => out.push_str("false"),
        Json::Num(n) => out.push_str(n),
        Json::Str(s) => escape_str(out, s),
        Json::Arr(items) => {
            out.push('[');
            for (i, it) in items.iter().enumerate() {
                if i > 0 {
                    out.push_str(", ");
                }
                write_value(out, it, sorted);
            }
            out.push(']');
        }
        Json::Obj(kv) => {
            out.push('{');
            let mut refs: Vec<&(String, Json)> = kv.iter().collect();
            if sorted {
                refs.sort_by(|a, b| a.0.as_bytes().cmp(b.0.as_bytes()));
            }
            for (i, (k, val)) in refs.into_iter().map(|p| (&p.0, &p.1)).enumerate() {
                if i > 0 {
                    out.push_str(", ");
                }
                escape_str(out, k);
                out.push_str(": ");
                write_value(out, val, sorted);
            }
            out.push('}');
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn escapes() {
        let s = Json::Str("a\"b\\c\n\r\t\u{8}\u{c}\u{1}\u{1f}\u{7f}é".to_string());
        assert_eq!(
            dumps(&s),
            "\"a\\\"b\\\\c\\n\\r\\t\\b\\f\\u0001\\u001f\u{7f}é\""
        );
    }

    #[test]
    fn sorted_and_empty() {
        let v = Json::Obj(vec![
            ("b".into(), Json::Arr(vec![])),
            ("a".into(), Json::Obj(vec![("z".into(), Json::Null), ("y".into(), Json::Bool(true))])),
            ("c".into(), Json::Obj(vec![])),
        ]);
        assert_eq!(dumps(&v), r#"{"b": [], "a": {"z": null, "y": true}, "c": {}}"#);
        assert_eq!(dumps_sorted(&v), r#"{"a": {"y": true, "z": null}, "b": [], "c": {}}"#);
    }
}
