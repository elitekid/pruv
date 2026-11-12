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
