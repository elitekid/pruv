//! Node-API bridge exposing verified Pruv functions to Node and Electron.
//!
//! JS strings are converted to UTF-8 by Node-API; lone surrogates become
//! U+FFFD. All byte limits below count UTF-8 bytes, not UTF-16 code units.
//!
//! Each wrapper checks the Pruv `requires` clause and throws a JS exception
//! instead of letting the generated code panic.

use napi_derive::napi;

#[path = "../gen/clip_bytes_gen.rs"]
#[allow(dead_code, clippy::all)]
mod clip_bytes_gen;

#[path = "../gen/host_within_gen.rs"]
#[allow(dead_code, clippy::all)]
mod host_within_gen;

#[path = "../gen/version_at_least_gen.rs"]
#[allow(dead_code, clippy::all)]
mod version_at_least_gen;

#[path = "../gen/col_letters_gen.rs"]
#[allow(dead_code, clippy::all)]
mod col_letters_gen;

#[napi(js_name = "versionAtLeast")]
pub fn version_at_least(a: String, b: String) -> napi::Result<bool> {
    if a.len() > 4096 || b.len() > 4096 {
        return Err(napi::Error::new(napi::Status::InvalidArg,
            "versionAtLeast: a and b must be at most 4096 UTF-8 bytes each"));
    }
    Ok(version_at_least_gen::version_at_least(&a, &b))
}

#[napi(js_name = "colLetters")]
pub fn col_letters(col: f64) -> napi::Result<String> {
    if !col.is_finite() || col.fract() != 0.0 || !(0.0..=1_000_000_000_000_000.0).contains(&col) {
        return Err(napi::Error::new(napi::Status::InvalidArg,
            "colLetters: col must be an integer in 0..=1000000000000000"));
    }
    Ok(col_letters_gen::col_letters(col as i64))
}

#[napi(js_name = "clipBytes")]
pub fn clip_bytes(text: String, max: i64) -> napi::Result<String> {
    if !(0..=1_000_000).contains(&max) {
        return Err(napi::Error::new(
            napi::Status::InvalidArg,
            "clipBytes: max must be in 0..=1000000",
        ));
    }
    if text.len() > 1_000_000 {
        return Err(napi::Error::new(
            napi::Status::InvalidArg,
            "clipBytes: text must be at most 1000000 UTF-8 bytes",
        ));
    }
    Ok(clip_bytes_gen::clip_bytes(&text, max))
}

#[napi(js_name = "hostWithin")]
pub fn host_within(host: String, site: String) -> napi::Result<bool> {
    if host.len() > 4096 || site.len() > 4096 {
        return Err(napi::Error::new(
            napi::Status::InvalidArg,
            "hostWithin: host and site must be at most 4096 UTF-8 bytes each",
        ));
    }
    Ok(host_within_gen::host_within(&host, &site))
}
