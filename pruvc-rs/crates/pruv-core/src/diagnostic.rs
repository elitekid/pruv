//! Error format (vast.PruvError). line/col are 1-based, in Unicode characters.

use crate::pyjson::{dumps, Json};

#[derive(Debug, Clone, PartialEq)]
pub struct PruvError {
    pub stage: String,
    pub line: i64,
    pub col: i64,
    pub code: String,
    pub message: String,
    pub fix: String,
    pub counterexample: Option<Json>,
}

impl PruvError {
    pub fn new(stage: &str, line: i64, col: i64, code: &str, message: impl Into<String>, fix: impl Into<String>) -> PruvError {
        PruvError {
            stage: stage.to_string(),
            line,
            col,
            code: code.to_string(),
            message: message.into(),
            fix: fix.into(),
            counterexample: None,
        }
    }

    /// Insertion order stage,line,col,code,message,fix[,counterexample]; line/col are JSON numbers.
    pub fn to_json_value(&self) -> Json {
        let mut kv = vec![
            ("stage".to_string(), Json::Str(self.stage.clone())),
            ("line".to_string(), Json::int(self.line)),
            ("col".to_string(), Json::int(self.col)),
            ("code".to_string(), Json::Str(self.code.clone())),
            ("message".to_string(), Json::Str(self.message.clone())),
            ("fix".to_string(), Json::Str(self.fix.clone())),
        ];
        if let Some(c) = &self.counterexample {
            kv.push(("counterexample".to_string(), c.clone()));
        }
        Json::Obj(kv)
    }

    /// One line identical to Python `json.dumps(d, ensure_ascii=False)`.
    pub fn to_cli_json(&self) -> String {
        dumps(&self.to_json_value())
    }
}

impl std::fmt::Display for PruvError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.message)
    }
}

impl std::error::Error for PruvError {}
