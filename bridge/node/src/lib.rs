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

#[path = "../gen/term_plain_gen.rs"]
#[allow(dead_code, clippy::all)]
mod term_plain_gen;

#[path = "../gen/decode_bytes_gen.rs"]
#[allow(dead_code, clippy::all)]
mod decode_bytes_gen;

#[path = "../gen/zip_total_gen.rs"]
#[allow(dead_code, clippy::all)]
mod zip_total_gen;

fn term_args(name: &str, state: f64, data: &str) -> napi::Result<i64> {
    if !state.is_finite() || state.fract() != 0.0 || !(0.0..=11.0).contains(&state) {
        return Err(napi::Error::new(napi::Status::InvalidArg,
            format!("{name}: state must be an integer in 0..=11")));
    }
    if data.len() as u64 > 1_000_000_000_000 {
        return Err(napi::Error::new(napi::Status::InvalidArg,
            format!("{name}: data must be at most 1000000000000 UTF-8 bytes")));
    }
    Ok(state as i64)
}

/// Cleaned text of one chunk; feed the next chunk with `termState` of this one.
#[napi(js_name = "termPlain")]
pub fn term_plain(state: f64, data: String) -> napi::Result<String> {
    let st = term_args("termPlain", state, &data)?;
    Ok(term_plain_gen::term_plain(st, &data))
}

/// Streaming state after one chunk (0..=11).
#[napi(js_name = "termState")]
pub fn term_state(state: f64, data: String) -> napi::Result<i64> {
    let st = term_args("termState", state, &data)?;
    Ok(term_plain_gen::term_state(st, &data))
}

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

const DECODE_MAX: usize = 1_000_000_000_000;
// Index = decode_kind result: 0 UTF-8 BOM, 1 UTF-16LE BOM, 2 UTF-16BE BOM, 3 valid UTF-8, 4 EUC-KR.
const ENCODINGS: [&str; 5] = ["utf-8", "utf-16le", "utf-16be", "utf-8", "cp949"];

fn decode_input(name: &str, data: &[u8]) -> napi::Result<()> {
    if data.len() > DECODE_MAX {
        return Err(napi::Error::new(
            napi::Status::InvalidArg,
            format!("{name}: data must be at most 1000000000000 bytes"),
        ));
    }
    Ok(())
}

#[napi(object)]
pub struct Decoded {
    pub text: String,
    pub encoding: String,
}

/// Lair decodeBytes: BOM, then strict UTF-8, else EUC-KR (WHATWG decoders via encoding_rs).
#[napi(js_name = "decodeBytes")]
pub fn decode_bytes(data: napi::bindgen_prelude::Uint8Array) -> napi::Result<Decoded> {
    decode_input("decodeBytes", &data)?;
    let kind = decode_bytes_gen::decode_kind(&data);
    Ok(Decoded {
        text: decode_bytes_gen::decode_text(&data),
        encoding: ENCODINGS[kind as usize].to_string(),
    })
}

/// A NUL byte in the first 8 KiB.
#[napi(js_name = "looksBinary")]
pub fn looks_binary(data: napi::bindgen_prelude::Uint8Array) -> napi::Result<bool> {
    decode_input("looksBinary", &data)?;
    Ok(decode_bytes_gen::looks_binary(&data))
}

/// Lair zipUncompressedTotal: the uncompressed-size sum from the zip central directory, read before
/// inflating. null = not a zip or unreadable directory, Infinity = zip64-shaped (size unknown).
/// Totals are at most 65534 * (2^32 - 2) < 2^53, so the f64 is exact.
#[napi(js_name = "zipUncompressedTotal")]
pub fn zip_uncompressed_total(data: napi::bindgen_prelude::Uint8Array) -> napi::Result<Option<f64>> {
    decode_input("zipUncompressedTotal", &data)?;
    Ok(match zip_total_gen::zip_uncompressed_total(&data) {
        -1 => None,
        -2 => Some(f64::INFINITY),
        total => Some(total as f64),
    })
}
