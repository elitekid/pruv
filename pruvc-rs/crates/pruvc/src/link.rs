//! System link driver discovery and invocation (no shell; argv only).

use crate::runtime::{self, Variant};
use crate::target::Target;
use crate::{llvm, Error, Result};
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::OnceLock;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RuntimeChoice {
    Malloc,
    MallocCount,
    None,
}

/// Linker driver: PRUVC_LINKER (executable path, not a shell string) first,
/// then macOS `xcrun --find cc` (fallback `cc`), Linux `cc`. Windows: unsupported for now.
pub fn find_linker(target: &Target) -> Result<PathBuf> {
    // Windows is unimplemented regardless of PRUVC_LINKER: check it first.
    if target.is_windows() {
        return Err(Error::new("unsupported", "linking for Windows is not implemented yet"));
    }
    if let Some(v) = std::env::var_os("PRUVC_LINKER") {
        if !v.is_empty() {
            return Ok(PathBuf::from(v));
        }
    }
    if target.is_macos() {
        if let Some(p) = xcrun_cc() {
            return Ok(p.clone());
        }
    }
    Ok(PathBuf::from("cc"))
}

/// `xcrun --find cc`, computed once per process.
fn xcrun_cc() -> Option<&'static PathBuf> {
    static CC: OnceLock<Option<PathBuf>> = OnceLock::new();
    CC.get_or_init(|| {
        let o = Command::new("xcrun").args(["--find", "cc"]).output().ok()?;
        let s = String::from_utf8_lossy(&o.stdout).trim().to_string();
        if o.status.success() && !s.is_empty() {
            Some(PathBuf::from(s))
        } else {
            None
        }
    })
    .as_ref()
}

/// `xcrun --sdk macosx --show-sdk-path`, computed once per process.
fn xcrun_sdk() -> Option<&'static PathBuf> {
    static SDK: OnceLock<Option<PathBuf>> = OnceLock::new();
    SDK.get_or_init(|| {
        let o = Command::new("xcrun").args(["--sdk", "macosx", "--show-sdk-path"]).output().ok()?;
        let s = String::from_utf8_lossy(&o.stdout).trim().to_string();
        if o.status.success() && !s.is_empty() {
            Some(PathBuf::from(s))
        } else {
            None
        }
    })
    .as_ref()
}

/// SDK for the link: PRUVC_SYSROOT first; on macOS without SDKROOT, `xcrun --sdk macosx --show-sdk-path`
/// (a bare `cc` outside an Xcode-configured shell cannot find libSystem otherwise).
fn sysroot(target: &Target) -> Option<PathBuf> {
    if let Some(v) = std::env::var_os("PRUVC_SYSROOT") {
        if !v.is_empty() {
            return Some(PathBuf::from(v));
        }
    }
    if !target.is_macos() || std::env::var_os("SDKROOT").map_or(false, |v| !v.is_empty()) {
        return None;
    }
    xcrun_sdk().cloned()
}

/// Link `objs` (plus the embedded runtime unless `None`) into `exe`.
/// At least one input must define `main`.
pub fn link(objs: &[PathBuf], exe: &Path, target: &Target, rt: RuntimeChoice) -> Result<()> {
    if objs.is_empty() {
        return Err(Error::new("invalid_argument", "no input objects"));
    }
    if !target.is_host() {
        return Err(Error::new(
            "unsupported",
            format!("cannot link for non-host target {} (cross linking not implemented)", target.public),
        ));
    }

    let mut has_main = false;
    for o in objs {
        let bytes = std::fs::read(o).map_err(|e| Error::new("io", format!("{}: {e}", o.display())))?;
        let syms = llvm::defined_symbols(&bytes, &o.to_string_lossy())?;
        if syms.iter().any(|s| s == "main" || s == "_main") {
            has_main = true;
        }
    }
    if !has_main {
        return Err(Error::new("no_main", "no input object defines main"));
    }

    let linker = find_linker(target)?;
    // Runtime object lives in a private temp dir removed when `tmp` drops.
    let tmp = tempfile::tempdir().map_err(|e| Error::new("io", format!("tempdir: {e}")))?;
    let mut args: Vec<std::ffi::OsString> = objs.iter().map(|p| p.as_os_str().to_owned()).collect();
    match rt {
        RuntimeChoice::None => {}
        RuntimeChoice::Malloc | RuntimeChoice::MallocCount => {
            let bytes = runtime::object(target, Variant::Malloc, rt == RuntimeChoice::MallocCount)?;
            let p = tmp.path().join("pruv_runtime.o");
            std::fs::write(&p, bytes).map_err(|e| Error::new("io", format!("{}: {e}", p.display())))?;
            args.push(p.into_os_string());
        }
    }
    if let Some(sdk) = sysroot(target) {
        if target.is_macos() {
            args.push("-isysroot".into());
            args.push(sdk.into_os_string());
        } else {
            // Linux (gcc/clang driver): --sysroot=PATH as a single argument.
            let mut a = std::ffi::OsString::from("--sysroot=");
            a.push(sdk.as_os_str());
            args.push(a);
        }
    }
    args.push("-o".into());
    args.push(exe.as_os_str().to_owned());

    let out = Command::new(&linker)
        .args(&args)
        .output()
        .map_err(|e| Error::new("link_spawn", format!("{}: {e}", linker.display())))?;
    if !out.status.success() {
        return Err(Error::new(
            "link_failed",
            format!("{} exited with {}\n{}", linker.display(), out.status, String::from_utf8_lossy(&out.stderr)),
        ));
    }
    Ok(())
}
