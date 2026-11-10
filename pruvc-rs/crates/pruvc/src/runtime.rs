//! Runtime objects built by build.rs from pruvc/runtime.c and embedded here.
//! They are compiled for the cargo TARGET only; other targets are
//! `target_runtime_missing`. Empty objects mean "variant not built" (MSVC count).

use crate::target::Target;
use crate::{Error, Result};

static RT_MALLOC: &[u8] = include_bytes!(concat!(env!("OUT_DIR"), "/rt_malloc.o"));
static RT_MALLOC_COUNT: &[u8] = include_bytes!(concat!(env!("OUT_DIR"), "/rt_malloc_count.o"));
static RT_RUST: &[u8] = include_bytes!(concat!(env!("OUT_DIR"), "/rt_rust.o"));
static RT_RUST_COUNT: &[u8] = include_bytes!(concat!(env!("OUT_DIR"), "/rt_rust_count.o"));

/// Cargo TARGET the embedded objects were compiled for.
pub const EMBEDDED_TARGET: &str = env!("PRUVC_RT_TARGET");

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Variant {
    Malloc,
    Rust,
}

impl Variant {
    pub fn parse(s: &str) -> Option<Variant> {
        match s {
            "malloc" => Some(Variant::Malloc),
            "rust" => Some(Variant::Rust),
            _ => None,
        }
    }
    fn name(self) -> &'static str {
        match self {
            Variant::Malloc => "malloc",
            Variant::Rust => "rust",
        }
    }
}

/// Targets whose runtime is embedded (public names).
pub fn available_targets() -> Vec<&'static str> {
    crate::target::host_public().into_iter().filter(|t| *t == EMBEDDED_TARGET).collect()
}

/// Embedded object bytes for (target, variant, count-allocs).
pub fn object(target: &Target, variant: Variant, count: bool) -> Result<&'static [u8]> {
    let have = if target.public == EMBEDDED_TARGET { Some(()) } else { None };
    let bytes: &'static [u8] = match (variant, count) {
        (Variant::Malloc, false) => RT_MALLOC,
        (Variant::Malloc, true) => RT_MALLOC_COUNT,
        (Variant::Rust, false) => RT_RUST,
        (Variant::Rust, true) => RT_RUST_COUNT,
    };
    if have.is_none() || bytes.is_empty() {
        return Err(Error::new(
            "target_runtime_missing",
            format!(
                "no embedded runtime for target {} variant {}{} (embedded: {})",
                target.public,
                variant.name(),
                if count { "+count" } else { "" },
                EMBEDDED_TARGET
            ),
        ));
    }
    Ok(bytes)
}
