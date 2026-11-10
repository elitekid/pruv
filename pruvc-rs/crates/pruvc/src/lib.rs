//! pruvc: LLVM object / link / embedded-runtime layer (shared by the `pruvc`
//! CLI and the dev-only `pruvc-ir-tool`).

pub mod link;
pub mod llvm;
pub mod runtime;
pub mod target;

use std::fmt;

/// Error with a stable machine code (e.g. `target_runtime_missing`) and text.
#[derive(Debug, Clone)]
pub struct Error {
    pub code: &'static str,
    pub message: String,
}

impl Error {
    pub fn new(code: &'static str, message: impl Into<String>) -> Self {
        Error { code, message: message.into() }
    }
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}: {}", self.code, self.message)
    }
}

impl std::error::Error for Error {}

pub type Result<T> = std::result::Result<T, Error>;
