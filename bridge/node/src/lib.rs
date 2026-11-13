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

#[path = "../gen/encode_png_gen.rs"]
#[allow(dead_code, clippy::all)]
mod encode_png_gen;

#[path = "../gen/split_text_gen.rs"]
#[allow(dead_code, clippy::all)]
mod split_text_gen;

#[path = "../gen/group_text_gen.rs"]
#[allow(dead_code, clippy::all)]
mod group_text_gen;

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

/// Downsampled PNG scanlines (filter byte 0 + samples per row) for encodePng.
#[napi(object)]
pub struct PngScanlines {
    pub width: f64,
    pub height: f64,
    pub raw: napi::bindgen_prelude::Buffer,
}

const PNG_DIM_MAX: f64 = 1_099_511_627_776.0; // 2^40
const PNG_MAX_PIXELS: f64 = 68_719_476_736.0; // 2^36: scanlines stay at most 4 * 2^36 bytes

fn png_int(name: &str, v: f64, hi: f64) -> napi::Result<i64> {
    if !v.is_finite() || v.fract() != 0.0 || v < 1.0 || v > hi {
        return Err(napi::Error::new(napi::Status::InvalidArg,
            format!("pngScanlines: {name} must be an integer in 1..={hi}")));
    }
    Ok(v as i64)
}

/// The pixel part of Lair encodePng: null where TS returns null (no pixels after downsampling).
/// width, height >= 1 with width * height <= 2^40, kind 1..=3, maxPixels 1..=2^36 (integers).
#[napi(js_name = "pngScanlines")]
pub fn png_scanlines(
    data: napi::bindgen_prelude::Uint8Array,
    width: f64,
    height: f64,
    kind: f64,
    max_pixels: f64,
) -> napi::Result<Option<PngScanlines>> {
    let w = png_int("width", width, PNG_DIM_MAX)?;
    let h = png_int("height", height, PNG_DIM_MAX)?;
    if (w as i128) * (h as i128) > PNG_DIM_MAX as i128 {
        return Err(napi::Error::new(napi::Status::InvalidArg,
            "pngScanlines: width * height must be at most 1099511627776"));
    }
    let k = png_int("kind", kind, 3.0)?;
    let mx = png_int("maxPixels", max_pixels, PNG_MAX_PIXELS)?;
    let raw = encode_png_gen::png_scanlines(&data, w, h, k, mx);
    if raw.is_empty() {
        return Ok(None);
    }
    let step = encode_png_gen::png_step(w, h, mx);
    Ok(Some(PngScanlines { width: (w / step) as f64, height: (h / step) as f64, raw: raw.into() }))
}

/// Lair splitText: pieces of at most `max` UTF-16 code units, cut at the last newline, else the last
/// space, at or after max / 2, else at max (never inside a surrogate pair), each trimmed of JS
/// whitespace. Pruv returns the byte ranges; this slices them. `max` is an integer in 2..=2^40
/// (TS can loop forever below 2).
#[napi(js_name = "splitText")]
pub fn split_text(text: String, max: f64) -> napi::Result<Vec<String>> {
    if !max.is_finite() || max.fract() != 0.0 || !(2.0..=1_099_511_627_776.0).contains(&max) {
        return Err(napi::Error::new(napi::Status::InvalidArg,
            "splitText: max must be an integer in 2..=1099511627776"));
    }
    if text.len() as u64 > 500_000_000_000 {
        return Err(napi::Error::new(napi::Status::InvalidArg,
            "splitText: text must be at most 500000000000 UTF-8 bytes"));
    }
    let r = split_text_gen::split_bounds(&text, max as i64);
    Ok(r.chunks(2).map(|p| text[p[0] as usize..p[1] as usize].to_string()).collect())
}

#[napi(object)]
pub struct GroupPiece {
    /// Index (0-based) of the first and last item in the piece.
    pub from: f64,
    pub to: f64,
    pub text: String,
}

/// Lair groupNumbered (behind chunkLines and chunkBlocks): gather items from the top into pieces of at
/// most `max` UTF-16 units (each item counts its length + 1), an item longer than `max` split alone by
/// splitText. Pruv returns item indexes and byte ranges into the items joined with '\n'.
#[napi(js_name = "groupTexts")]
pub fn group_texts(texts: Vec<String>, max: f64) -> napi::Result<Vec<GroupPiece>> {
    if !max.is_finite() || max.fract() != 0.0 || !(2.0..=1_099_511_627_776.0).contains(&max) {
        return Err(napi::Error::new(napi::Status::InvalidArg,
            "groupTexts: max must be an integer in 2..=1099511627776"));
    }
    let joined = texts.join("\n");
    if joined.len() as u64 > 250_000_000_000 {
        return Err(napi::Error::new(napi::Status::InvalidArg,
            "groupTexts: texts joined with newlines must be at most 250000000000 UTF-8 bytes"));
    }
    let mut ends = Vec::with_capacity(texts.len());
    let mut at = 0usize;
    for (k, t) in texts.iter().enumerate() {
        at += usize::from(k > 0) + t.len();
        ends.push(at as i64);
    }
    let r = group_text_gen::group_bounds(&joined, &ends, max as i64);
    if r.len() % 4 != 0 {
        return Err(napi::Error::new(napi::Status::GenericFailure, "groupTexts: malformed item ends"));
    }
    Ok(r.chunks(4).map(|p| GroupPiece {
        from: p[0] as f64,
        to: p[1] as f64,
        text: joined[p[2] as usize..p[3] as usize].to_string(),
    }).collect())
}
