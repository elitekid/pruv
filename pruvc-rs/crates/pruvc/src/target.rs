//! Public target triples and their explicit LLVM triple mapping, plus -mcpu.

use crate::{Error, Result};

/// (public triple, LLVM triple). Only these four are accepted.
const TABLE: [(&str, &str); 4] = [
    ("aarch64-apple-darwin", "aarch64-apple-macosx11.0.0"),
    ("x86_64-unknown-linux-gnu", "x86_64-unknown-linux-gnu"),
    ("x86_64-pc-windows-msvc", "x86_64-pc-windows-msvc"),
    ("x86_64-apple-darwin", "x86_64-apple-macosx10.15.0"),
];

#[derive(Debug, Clone)]
pub struct Target {
    /// One of the four public names.
    pub public: &'static str,
    /// Triple handed to LLVM.
    pub llvm_triple: String,
}

/// Public name of the machine this binary was built for (None if not one of the four).
pub fn host_public() -> Option<&'static str> {
    if cfg!(all(target_arch = "aarch64", target_os = "macos")) {
        Some("aarch64-apple-darwin")
    } else if cfg!(all(target_arch = "x86_64", target_os = "macos")) {
        Some("x86_64-apple-darwin")
    } else if cfg!(all(target_arch = "x86_64", target_os = "linux", target_env = "gnu")) {
        Some("x86_64-unknown-linux-gnu")
    } else if cfg!(all(target_arch = "x86_64", target_os = "windows", target_env = "msvc")) {
        Some("x86_64-pc-windows-msvc")
    } else {
        None
    }
}

impl Target {
    /// Explicit target from the table.
    pub fn parse(name: &str) -> Result<Target> {
        for (public, llvm) in TABLE {
            if public == name {
                return Ok(Target { public, llvm_triple: llvm.to_string() });
            }
        }
        Err(Error::new(
            "unsupported_target",
            format!(
                "unknown target '{}' (allowed: {})",
                name,
                TABLE.iter().map(|t| t.0).collect::<Vec<_>>().join(", ")
            ),
        ))
    }

    /// No --target: the host. Pick one of the four public targets from cfg!(target_arch/os/env)
    /// and use the TABLE's llvm_triple (not LLVMGetDefaultTargetTriple, which varies by LLVM build).
    pub fn host() -> Result<Target> {
        let public = host_public()
            .ok_or_else(|| Error::new("unsupported_target", "host is not one of the four public targets"))?;
        Target::parse(public)
    }

    pub fn is_host(&self) -> bool {
        host_public() == Some(self.public)
    }

    pub fn is_windows(&self) -> bool {
        self.public.contains("windows")
    }

    pub fn is_macos(&self) -> bool {
        self.public.ends_with("apple-darwin")
    }
}

/// (arch, os family) of a triple, normalised so arm64≡aarch64 and darwin≡macosx.
fn family(triple: &str) -> (String, String) {
    let parts: Vec<&str> = triple.split('-').collect();
    let arch = match parts.first().copied().unwrap_or("") {
        "arm64" => "aarch64".to_string(),
        "amd64" | "x86-64" => "x86_64".to_string(),
        a => a.to_string(),
    };
    let mut os = String::new();
    for p in parts.iter().skip(1) {
        let base = p.trim_end_matches(|c: char| c.is_ascii_digit() || c == '.');
        let fam = match base {
            "macosx" | "darwin" | "macos" => "macos",
            "linux" => "linux",
            "windows" | "win32" => "windows",
            _ => continue,
        };
        os = fam.to_string();
        break;
    }
    (arch, os)
}

/// ABI/environment component of a triple (gnu, musl, msvc, ...), if it names one.
fn env_of(triple: &str) -> Option<String> {
    for p in triple.split('-').skip(2) {
        let base = p.trim_end_matches(|c: char| c.is_ascii_digit() || c == '.');
        if matches!(base, "gnu" | "musl" | "msvc" | "android" | "gnueabi" | "gnueabihf" | "musleabi"
            | "musleabihf" | "gnux32" | "itanium" | "cygnus" | "macho" | "elf" | "coff")
        {
            return Some(base.to_string());
        }
    }
    None
}

/// Whether an input module's triple is the same target as `want` (version suffixes ignored).
/// If both name an environment (gnu/msvc/musl...), they must be equal.
pub fn triples_compatible(have: &str, want: &str) -> bool {
    if family(have) != family(want) {
        return false;
    }
    match (env_of(have), env_of(want)) {
        (Some(a), Some(b)) => a == b,
        _ => true,
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Cpu {
    Generic,
    Native,
    Named(String),
}

impl Cpu {
    /// Parse the value of `-mcpu=`.
    pub fn parse(v: &str) -> Cpu {
        match v {
            "generic" => Cpu::Generic,
            "native" => Cpu::Native,
            n => Cpu::Named(n.to_string()),
        }
    }

    /// (cpu name, feature string) for LLVMCreateTargetMachine.
    pub fn resolve(&self, target: &Target) -> Result<(String, String)> {
        match self {
            Cpu::Generic => Ok(("generic".into(), String::new())),
            Cpu::Named(n) => Ok((n.clone(), String::new())),
            Cpu::Native => {
                if !target.is_host() {
                    return Err(Error::new("unsupported", "-mcpu=native is only valid for the host target"));
                }
                Ok((crate::llvm::host_cpu_name(), crate::llvm::host_cpu_features()))
            }
        }
    }
}
