//! 작은 JSON 값과 Python `json.dumps(..., ensure_ascii=False)` 와 바이트 동일한 출력기.
//! 구분자는 ", " 와 ": ", 들여쓰기 없음.

#[derive(Debug, Clone, PartialEq)]
pub enum Json {
    Null,
    Bool(bool),
    /// 수는 원문 그대로 보관한다.
    Num(String),
    Str(String),
    Arr(Vec<Json>),
    /// 삽입 순서를 가진 객체.
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

/// 삽입 순서대로 출력.
pub fn dumps(v: &Json) -> String {
    let mut out = String::new();
    write_value(&mut out, v, false);
    out
}

/// sort_keys=True: 모든 중첩 객체의 키를 코드 포인트(=UTF-8 바이트) 순으로 정렬.
pub fn dumps_sorted(v: &Json) -> String {
    let mut out = String::new();
    write_value(&mut out, v, true);
    out
}

/// 문자열 이스케이프(ensure_ascii=False 규칙).
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
