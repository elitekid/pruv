//! DEV-TOOL ONLY (pruvc-ir-tool). Removed after the Python comparison ends.
//! Not part of the distributed CLI or the Rust generator path.
//!
//! For now only a signature check: legacy (Python-made) IR that defines an
//! external `pruv_abi_*` returning `{ i64, i64 }` cannot be lowered for
//! Windows x64 yet, so it is rejected as `unsupported`. Real lowering is a later bundle.

use crate::target::Target;
use crate::{Error, Result};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum InputAbi {
    Legacy,
    Target,
}

impl InputAbi {
    pub fn parse(s: &str) -> Option<InputAbi> {
        match s {
            "legacy" => Some(InputAbi::Legacy),
            "target" => Some(InputAbi::Target),
            _ => None,
        }
    }
}

/// Names of `define`d `@pruv_abi_*` functions whose return type is `{ i64, i64 }`.
pub fn tagged_return_abi_defs(ir: &str) -> Vec<String> {
    let mut out = Vec::new();
    for line in ir.lines() {
        let l = line.trim_start();
        if !l.starts_with("define ") {
            continue;
        }
        let Some(at) = l.find("@pruv_abi_") else { continue };
        let head: String = l[..at].chars().filter(|c| !c.is_whitespace()).collect();
        if head.contains("{i64,i64}") {
            let name: String = l[at + 1..].chars().take_while(|c| c.is_alphanumeric() || *c == '_').collect();
            out.push(name);
        }
    }
    out
}

/// Signature check before objectification.
pub fn check(ir: &[u8], abi: InputAbi, target: &Target) -> Result<()> {
    if abi == InputAbi::Legacy && target.is_windows() {
        let text = String::from_utf8_lossy(ir);
        let bad = tagged_return_abi_defs(&text);
        if !bad.is_empty() {
            return Err(Error::new(
                "unsupported",
                format!(
                    "legacy IR defines external functions returning {{i64,i64}} ({}); \
                     Windows x64 ABI lowering is not implemented yet",
                    bad.join(", ")
                ),
            ));
        }
    }
    Ok(())
}
