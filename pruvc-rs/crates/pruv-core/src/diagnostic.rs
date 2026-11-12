//! Error format (vast.PruvError). line/col are 1-based, in Unicode characters.

use crate::pyjson::{dumps, Json};
use std::sync::Mutex;

// ---------- G4 A0: source files of an explicit-mode program ----------
// Python tags every AST node with its `file`. Here the file is carried in the line number of the node instead: the
// lexer of module file number k (the root is 1, k = position in the module list + 1) starts counting at
// `1 + (k << 32)`. A legacy program has tag 0 everywhere, so its line numbers are the plain ones. Everything that prints
// a line goes through `plain_line`; `PruvError::to_json_value` also emits `"file"` for a tagged line.
pub const LINE_MASK: i64 = 0xFFFF_FFFF;

/// The line number without the file tag.
pub fn plain_line(l: i64) -> i64 {
    if l < 0 {
        l
    } else {
        l & LINE_MASK
    }
}

/// The file tag of a line number (0 = no file: legacy mode or a synthetic position).
pub fn line_tag(l: i64) -> usize {
    if l < 0 {
        0
    } else {
        (l >> 32) as usize
    }
}

/// `line` (plain or tagged) carrying the file tag `tag`.
pub fn tagged_line(line: i64, tag: usize) -> i64 {
    plain_line(line) | ((tag as i64) << 32)
}

static FILES: Mutex<Vec<String>> = Mutex::new(Vec::new());

/// Registers the file names of the program being compiled (index = tag - 1); the empty list for a legacy program.
pub fn set_files(files: Vec<String>) {
    let mut g = FILES.lock().unwrap_or_else(|e| e.into_inner());
    *g = files;
}

/// The file name of a tag, if registered.
pub fn file_of_tag(tag: usize) -> Option<String> {
    if tag == 0 {
        return None;
    }
    let g = FILES.lock().unwrap_or_else(|e| e.into_inner());
    g.get(tag - 1).cloned()
}

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

    /// Insertion order stage,line,col,code,message,fix[,file][,counterexample]; line/col are JSON numbers.
    /// G4: a tagged line number (explicit mode) prints as its plain line and adds `file` after `fix`.
    pub fn to_json_value(&self) -> Json {
        let tag = line_tag(self.line);
        let file = file_of_tag(tag);
        let mut kv = vec![
            ("stage".to_string(), Json::Str(self.stage.clone())),
            ("line".to_string(), Json::int(plain_line(self.line))),
            ("col".to_string(), Json::int(self.col)),
            ("code".to_string(), Json::Str(self.code.clone())),
            ("message".to_string(), Json::Str(self.message.clone())),
            ("fix".to_string(), Json::Str(self.fix.clone())),
        ];
        if let Some(f) = file {
            kv.push(("file".to_string(), Json::Str(f)));
        }
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
