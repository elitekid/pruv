//! Node-API bridge exposing verified Pruv functions to Node and Electron.
//!
//! JS strings are converted to UTF-8 by Node-API; lone surrogates become
//! U+FFFD. All byte limits below count UTF-8 bytes, not UTF-16 code units.
//!
//! Each wrapper checks the Pruv `requires` clause and throws a JS exception
//! instead of letting the generated code panic.

use napi_derive::napi;

#[path = "../gen/number_ranges_gen.rs"]
#[allow(dead_code, clippy::all)]
mod number_ranges_gen;

#[path = "../gen/cut_cell_gen.rs"]
#[allow(dead_code, clippy::all)]
mod cut_cell_gen;

#[path = "../gen/sheet_range_gen.rs"]
#[allow(dead_code, clippy::all)]
mod sheet_range_gen;

#[path = "../gen/page_ranges_gen.rs"]
#[allow(dead_code, clippy::all)]
mod page_ranges_gen;

#[path = "../gen/grouped_number_gen.rs"]
#[allow(dead_code, clippy::all)]
mod grouped_number_gen;

#[path = "../gen/doc_labels_gen.rs"]
#[allow(dead_code, clippy::all)]
mod doc_labels_gen;

#[path = "../gen/join_ranges_gen.rs"]
#[allow(dead_code, clippy::all)]
mod join_ranges_gen;

#[path = "../gen/kind_of_gen.rs"]
#[allow(dead_code, clippy::all)]
mod kind_of_gen;

#[path = "../gen/clip_sheet_gen.rs"]
#[allow(dead_code, clippy::all)]
mod clip_sheet_gen;

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

#[path = "../gen/image_shrink_gen.rs"]
#[allow(dead_code, clippy::all)]
mod image_shrink_gen;

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

/// Lair readOrientation: the EXIF orientation (1..=8) from the first APP1 Exif segment of a JPEG,
/// 1 when there is none or it is malformed. At most 2^40 bytes.
#[napi(js_name = "jpegOrientation")]
pub fn jpeg_orientation(bytes: napi::bindgen_prelude::Uint8Array) -> napi::Result<i64> {
    if bytes.len() as u64 > 1_099_511_627_776 {
        return Err(napi::Error::new(napi::Status::InvalidArg,
            "jpegOrientation: data must be at most 1099511627776 bytes"));
    }
    Ok(image_shrink_gen::jpeg_orientation(&bytes))
}

/// Upright, shrunk RGBA pixels (alpha 255).
#[napi(object)]
pub struct ShrunkPixels {
    pub width: f64,
    pub height: f64,
    pub data: napi::bindgen_prelude::Buffer,
}

fn shrink_int(name: &str, v: f64, hi: f64) -> napi::Result<i64> {
    if !v.is_finite() || v.fract() != 0.0 || v < 1.0 || v > hi {
        return Err(napi::Error::new(napi::Status::InvalidArg,
            format!("shrinkPixels: {name} must be an integer in 1..={hi}")));
    }
    Ok(v as i64)
}

/// The pixel part of Lair shrinkJpeg between jpeg-js decode and encode: long side cut to 2000 by box
/// averaging, then the EXIF orientation applied. null where TS returns undefined (long side at most
/// 2000 and orientation 1). width, height 1..=65535 (every JPEG), orientation 1..=8, data 4 * w * h bytes.
#[napi(js_name = "shrinkPixels")]
pub fn shrink_pixels(
    data: napi::bindgen_prelude::Uint8Array,
    width: f64,
    height: f64,
    orientation: f64,
) -> napi::Result<Option<ShrunkPixels>> {
    let w = shrink_int("width", width, 65535.0)?;
    let h = shrink_int("height", height, 65535.0)?;
    let o = shrink_int("orientation", orientation, 8.0)?;
    if data.len() as u64 != 4 * (w as u64) * (h as u64) {
        return Err(napi::Error::new(napi::Status::InvalidArg,
            "shrinkPixels: data must be 4 * width * height bytes"));
    }
    let out = image_shrink_gen::shrink_pixels(&data, w, h, o);
    if out.is_empty() {
        return Ok(None);
    }
    let (mut sw, mut sh) = (image_shrink_gen::shrink_width(w, h), image_shrink_gen::shrink_height(w, h));
    if o >= 5 {
        std::mem::swap(&mut sw, &mut sh);
    }
    Ok(Some(ShrunkPixels { width: sw as f64, height: sh as f64, data: out.into() }))
}

/// Lair numberRanges: "3-5, 8", cut at a range boundary with ", …" past 400 characters.
#[napi(js_name = "numberRanges")]
pub fn number_ranges(numbers: Vec<f64>) -> napi::Result<String> {
    let mut v = Vec::with_capacity(numbers.len());
    for n in numbers {
        if !n.is_finite() || n.fract() != 0.0 || !(-1e15..=1e15).contains(&n) {
            return Err(napi::Error::new(napi::Status::InvalidArg,
                "numberRanges: numbers must be integers in -1000000000000000..=1000000000000000"));
        }
        v.push(n as i64);
    }
    Ok(number_ranges_gen::number_ranges(&v))
}

/// Lair joinRangeParts: the parts joined with ", "; past 400 UTF-16 units cut at a part boundary and
/// followed by ", …". Pruv gets the concatenated parts and the byte end of every part. A lone surrogate
/// reaches Pruv as U+FFFD (one unit either way, so the length rule is unchanged).
#[napi(js_name = "joinRangeParts")]
pub fn join_range_parts(parts: Vec<String>) -> napi::Result<String> {
    let total: u64 = parts.iter().map(|p| p.len() as u64).sum();
    if total > 1_000_000_000_000 {
        return Err(napi::Error::new(napi::Status::InvalidArg,
            "joinRangeParts: parts must be at most 1000000000000 UTF-8 bytes in total"));
    }
    let text = parts.concat();
    let mut ends = Vec::with_capacity(parts.len());
    let mut at = 0usize;
    for p in &parts {
        at += p.len();
        ends.push(at as i64);
    }
    Ok(join_ranges_gen::join_ranges(&text, &ends))
}

/// The sheetWindow cell cut in Lair: a text longer than 200 UTF-16 units becomes its first 200 units and
/// "…". When unit 200 is the first half of a surrogate pair the result has U+FFFD there (TS keeps a lone
/// high surrogate, which is U+FFFD once encoded as UTF-8). A lone surrogate in the input reaches Pruv as
/// U+FFFD (one unit either way).
#[napi(js_name = "cutCell")]
pub fn cut_cell(text: String) -> napi::Result<String> {
    if text.len() as u64 > 1_000_000_000_000 {
        return Err(napi::Error::new(napi::Status::InvalidArg,
            "cutCell: text must be at most 1000000000000 UTF-8 bytes"));
    }
    Ok(cut_cell_gen::cut_cell(&text))
}

fn range_int(name: &str, v: f64, lo: f64, hi: f64) -> napi::Result<i64> {
    if !v.is_finite() || v.fract() != 0.0 || v < lo || v > hi {
        return Err(napi::Error::new(napi::Status::InvalidArg,
            format!("sheetRange: {name} must be an integer in {lo}..={hi}")));
    }
    Ok(v as i64)
}

/// The window arithmetic of Lair sheetWindow: [row, col, rowCount, colCount] for a sheet of
/// totalRows x totalCols and the request fields row, col, rows, cols (undefined or null takes the
/// default: 1, 1, 200, 50). The window is proved inside the sheet and the counts within 0..=500 / 0..=100.
#[napi(js_name = "sheetRange")]
pub fn sheet_range(total_rows: f64, total_cols: f64, row: Option<f64>, col: Option<f64>, rows: Option<f64>,
                   cols: Option<f64>) -> napi::Result<Vec<f64>> {
    const SAFE: f64 = 9007199254740991.0;
    let tr = range_int("totalRows", total_rows, 0.0, 1e12)?;
    let tc = range_int("totalCols", total_cols, 0.0, 1e12)?;
    let mut given = 0i64;
    let mut v = [0i64; 4];
    for (k, (name, f)) in [("row", row), ("col", col), ("rows", rows), ("cols", cols)].into_iter().enumerate() {
        if let Some(x) = f {
            v[k] = range_int(name, x, -SAFE, SAFE)?;
            given |= 1 << k;
        }
    }
    let r = sheet_range_gen::sheet_range(tr, tc, v[0], v[1], v[2], v[3], given);
    Ok(r.iter().map(|&x| x as f64).collect())
}

/// Lair rangeText (src/documents/pdf.ts): page numbers as "3~5쪽, 8쪽", no length cap.
#[napi(js_name = "pageRanges")]
pub fn page_ranges(pages: Vec<f64>) -> napi::Result<String> {
    if pages.len() > 10_000_000 {
        return Err(napi::Error::new(napi::Status::InvalidArg,
            "pageRanges: at most 10000000 pages"));
    }
    let mut v = Vec::with_capacity(pages.len());
    for n in pages {
        if !n.is_finite() || n.fract() != 0.0 || !(-1e15..=1e15).contains(&n) {
            return Err(napi::Error::new(napi::Status::InvalidArg,
                "pageRanges: pages must be integers in -1000000000000000..=1000000000000000"));
        }
        v.push(n as i64);
    }
    Ok(page_ranges_gen::page_ranges(&v))
}

/// Lair groupedNumber (src/documents/context.ts): an integer as toLocaleString('en-US'), e.g. "1,000,000".
#[napi(js_name = "groupedNumber")]
pub fn grouped_number(value: f64) -> napi::Result<String> {
    // -0 is refused: toLocaleString gives "-0" there, which no i64 carries.
    if !value.is_finite() || value.fract() != 0.0 || !(-1e15..=1e15).contains(&value)
        || (value == 0.0 && value.is_sign_negative()) {
        return Err(napi::Error::new(napi::Status::InvalidArg,
            "groupedNumber: value must be an integer in -1000000000000000..=1000000000000000 (not -0)"));
    }
    Ok(grouped_number_gen::grouped_number(value as i64))
}

/// Lair csvName: the file name after the last '/' or '\', without its extension; "표" if nothing is left.
#[napi(js_name = "csvName")]
pub fn csv_name(name: String) -> String {
    doc_labels_gen::csv_name(&name)
}

fn count_max(name: &str, max: f64) -> napi::Result<i64> {
    if !max.is_finite() || max.fract() != 0.0 || !(0.0..=1e9).contains(&max) {
        return Err(napi::Error::new(napi::Status::InvalidArg,
            format!("{name}: max must be an integer in 0..=1000000000")));
    }
    Ok(max as i64)
}

/// Lair countList's list text: the first max items as "3 (2), 5 (1)".
#[napi(js_name = "countListText")]
pub fn count_list_text(pages: Vec<f64>, counts: Vec<f64>, max: f64) -> napi::Result<String> {
    if pages.len() != counts.len() {
        return Err(napi::Error::new(napi::Status::InvalidArg,
            "countListText: pages and counts must have the same length"));
    }
    let max = count_max("countListText", max)?;
    let mut p = Vec::with_capacity(pages.len());
    let mut c = Vec::with_capacity(counts.len());
    for (a, b) in pages.into_iter().zip(counts) {
        for x in [a, b] {
            if !x.is_finite() || x.fract() != 0.0 || !(-1e15..=1e15).contains(&x) {
                return Err(napi::Error::new(napi::Status::InvalidArg,
                    "countListText: pages and counts must be integers in -1000000000000000..=1000000000000000"));
            }
        }
        p.push(a as i64);
        c.push(b as i64);
    }
    Ok(doc_labels_gen::count_list(&p, &c, max))
}

/// Lair countList's more: max(0, n - max) for n items.
#[napi(js_name = "countListMore")]
pub fn count_list_more(n: f64, max: f64) -> napi::Result<f64> {
    if !n.is_finite() || n.fract() != 0.0 || !(0.0..=1e12).contains(&n) {
        return Err(napi::Error::new(napi::Status::InvalidArg,
            "countListMore: n must be an integer in 0..=1000000000000"));
    }
    let max = count_max("countListMore", max)?;
    Ok(doc_labels_gen::count_list_more(n as i64, max) as f64)
}

fn sheet_int(name: &str, v: f64, lo: f64, hi: f64) -> napi::Result<i64> {
    if !v.is_finite() || v.fract() != 0.0 || v < lo || v > hi {
        return Err(napi::Error::new(napi::Status::InvalidArg,
            format!("clipSheetCell: {name} must be an integer in {lo}..={hi}")));
    }
    Ok(v as i64)
}

/// Lair renderClipSheet's blank 1560 x 920 RGBA board (dark grey).
#[napi(js_name = "clipSheetBackground")]
pub fn clip_sheet_background() -> napi::bindgen_prelude::Buffer {
    clip_sheet_gen::clip_sheet_background().into()
}

/// One cell of Lair renderClipSheet drawn onto a copy of `sheet`: the picture box-fitted to
/// out_w x out_h and centred in the 768 x 432 cell, the label strip and the number box.
/// sheet 5740800 bytes, index 0..=3, width/height 1..=65535, data 4 * width * height bytes,
/// out_w 1..=768, out_h 1..=432, label at most 1000000 and number at most 4096 UTF-8 bytes.
#[napi(js_name = "clipSheetCell")]
#[allow(clippy::too_many_arguments)]
pub fn clip_sheet_cell(
    sheet: napi::bindgen_prelude::Uint8Array,
    index: f64,
    data: napi::bindgen_prelude::Uint8Array,
    width: f64,
    height: f64,
    out_w: f64,
    out_h: f64,
    label: String,
    number: String,
) -> napi::Result<napi::bindgen_prelude::Buffer> {
    if sheet.len() != 5740800 {
        return Err(napi::Error::new(napi::Status::InvalidArg,
            "clipSheetCell: sheet must be 5740800 bytes"));
    }
    let i = sheet_int("index", index, 0.0, 3.0)?;
    let w = sheet_int("width", width, 1.0, 65535.0)?;
    let h = sheet_int("height", height, 1.0, 65535.0)?;
    let ow = sheet_int("out_w", out_w, 1.0, 768.0)?;
    let oh = sheet_int("out_h", out_h, 1.0, 432.0)?;
    if data.len() as u64 != 4 * (w as u64) * (h as u64) {
        return Err(napi::Error::new(napi::Status::InvalidArg,
            "clipSheetCell: data must be 4 * width * height bytes"));
    }
    if label.len() > 1000000 {
        return Err(napi::Error::new(napi::Status::InvalidArg,
            "clipSheetCell: label must be at most 1000000 UTF-8 bytes"));
    }
    if number.len() > 4096 {
        return Err(napi::Error::new(napi::Status::InvalidArg,
            "clipSheetCell: number must be at most 4096 UTF-8 bytes"));
    }
    Ok(clip_sheet_gen::clip_sheet_cell(&sheet, i, &data, w, h, ow, oh, &label, &number).into())
}

const NAME_MAX: usize = 1_000_000_000_000;

fn name_ok(func: &str, name: &str) -> napi::Result<()> {
    if name.len() > NAME_MAX {
        return Err(napi::Error::new(napi::Status::InvalidArg,
            format!("{func}: name must be at most 1000000000000 UTF-8 bytes")));
    }
    Ok(())
}

/// Lair kindOf as a code: 0 unknown, 1 pdf, 2 docx, 3 xlsx, 4 csv, 5 image, 6 text, 7 unsupported.
#[napi(js_name = "kindCode")]
pub fn kind_code(name: String) -> napi::Result<i64> {
    name_ok("kindCode", &name)?;
    Ok(kind_of_gen::kind_of(&name))
}

/// UTF-16 index where Lair extensionOf's text starts, or -1 when it is empty.
#[napi(js_name = "extensionAt")]
pub fn extension_at(name: String) -> napi::Result<i64> {
    name_ok("extensionAt", &name)?;
    Ok(kind_of_gen::extension_at(&name))
}

#[path = "../gen/row_pieces_gen.rs"]
#[allow(dead_code, clippy::all)]
mod row_pieces_gen;

#[napi(object)]
pub struct RowPiece {
    pub row: f64,
    /// First and last column (1-based) whose text is in the piece.
    pub col1: f64,
    pub col2: f64,
    pub text: String,
}

/// Lair rowPieces (behind extractSheets) on the cellText of every cell: "행 {rowNo}: " followed by the
/// non-empty cells joined with " | ", a cell labelled "{letters}=" unless it continues the previous or
/// next column (column 1 is never labelled at the start of a piece), each piece at most `max` UTF-16
/// units of text after the head, a long cell split by splitText first. Pruv returns columns and byte
/// ranges into the texts joined with '\n'; only the head and the column letters are formatted here.
#[napi(js_name = "rowTextPieces")]
pub fn row_text_pieces(texts: Vec<String>, row_no: f64, max: f64) -> napi::Result<Vec<RowPiece>> {
    if !row_no.is_finite() || row_no.fract() != 0.0 || !(1.0..=1_000_000_000_000_000.0).contains(&row_no) {
        return Err(napi::Error::new(napi::Status::InvalidArg,
            "rowTextPieces: rowNo must be an integer in 1..=1000000000000000"));
    }
    if !max.is_finite() || max.fract() != 0.0 || !(1.0..=1_099_511_627_776.0).contains(&max) {
        return Err(napi::Error::new(napi::Status::InvalidArg,
            "rowTextPieces: max must be an integer in 1..=1099511627776"));
    }
    let joined = texts.join("\n");
    if joined.len() as u64 > 180_000_000_000 {
        return Err(napi::Error::new(napi::Status::InvalidArg,
            "rowTextPieces: texts joined with newlines must be at most 180000000000 UTF-8 bytes"));
    }
    let mut ends = Vec::with_capacity(texts.len());
    let mut at = 0usize;
    for (k, t) in texts.iter().enumerate() {
        at += usize::from(k > 0) + t.len();
        ends.push(at as i64);
    }
    let row = row_no as i64;
    let r = row_pieces_gen::row_bounds(&joined, &ends, row, max as i64);
    if r.first() == Some(&-1) {
        return Err(napi::Error::new(napi::Status::GenericFailure, "rowTextPieces: malformed item ends"));
    }
    let head = format!("행 {row}: ");
    let mut out = Vec::new();
    let mut k = 0usize;
    while k + 3 <= r.len() {
        let nseg = r[k + 2] as usize;
        let mut text = head.clone();
        for q in 0..nseg {
            let p = &r[k + 3 + 3 * q..k + 6 + 3 * q];
            if q > 0 {
                text.push_str(" | ");
            }
            if p[0] > 0 {
                text.push_str(&col_letters_gen::col_letters(p[0]));
                text.push('=');
            }
            text.push_str(&joined[p[1] as usize..p[2] as usize]);
        }
        out.push(RowPiece { row: row_no, col1: r[k] as f64, col2: r[k + 1] as f64, text });
        k += 3 + 3 * nseg;
    }
    Ok(out)
}

#[path = "../gen/sheet_chunks_gen.rs"]
#[allow(dead_code, clippy::all)]
mod sheet_chunks_gen;

#[napi(object)]
pub struct SheetChunk {
    /// The A1 range of the chunk: "B3" for one cell, else "A1:C9".
    pub range: String,
    pub row1: f64,
    pub row2: f64,
    pub col1: f64,
    pub col2: f64,
    pub text: String,
}

fn cell_int(func: &str, name: &str, v: f64) -> napi::Result<i64> {
    if !v.is_finite() || v.fract() != 0.0 || !(1.0..=1_000_000_000_000_000.0).contains(&v) {
        return Err(napi::Error::new(napi::Status::InvalidArg,
            format!("{func}: {name} must be an integer in 1..=1000000000000000")));
    }
    Ok(v as i64)
}

/// Lair rangeOf.
#[napi(js_name = "cellRange")]
pub fn cell_range(row1: f64, row2: f64, col1: f64, col2: f64) -> napi::Result<String> {
    let f = "cellRange";
    Ok(sheet_chunks_gen::range_of(cell_int(f, "row1", row1)?, cell_int(f, "row2", row2)?,
        cell_int(f, "col1", col1)?, cell_int(f, "col2", col2)?).to_string())
}

/// The extractSheets grouping of one sheet's row pieces (in order): a piece starts a new chunk when the
/// open chunk is nonempty and either "[시트: {name}]\n" plus the pieces joined with '\n' would pass `max`
/// UTF-16 units or the piece row is more than 50 rows after the last one. Pruv decides the groups, their
/// row and column bounds and the range text; only the texts are joined here.
#[napi(js_name = "sheetChunks")]
pub fn sheet_chunks(name: String, pieces: Vec<RowPiece>, max: f64) -> napi::Result<Vec<SheetChunk>> {
    let f = "sheetChunks";
    if !max.is_finite() || max.fract() != 0.0 || !(1.0..=1_099_511_627_776.0).contains(&max) {
        return Err(napi::Error::new(napi::Status::InvalidArg, "sheetChunks: max must be an integer in 1..=1099511627776"));
    }
    let header = format!("[시트: {name}]\n");
    let header_len = header.encode_utf16().count() as i64;
    if header_len > 1_099_511_627_776 || pieces.len() as u64 > 100_000_000_000 {
        return Err(napi::Error::new(napi::Status::InvalidArg,
            "sheetChunks: the header must be at most 1099511627776 UTF-16 units and the pieces at most 100000000000"));
    }
    let (mut rows, mut col1s, mut col2s, mut lens) = (Vec::new(), Vec::new(), Vec::new(), Vec::new());
    for p in &pieces {
        rows.push(cell_int(f, "piece.row", p.row)?);
        col1s.push(cell_int(f, "piece.col1", p.col1)?);
        col2s.push(cell_int(f, "piece.col2", p.col2)?);
        lens.push(p.text.encode_utf16().count() as i64);
    }
    let r = sheet_chunks_gen::sheet_groups(&rows, &col1s, &col2s, &lens, header_len, max as i64);
    if r.first() == Some(&-1) {
        return Err(napi::Error::new(napi::Status::GenericFailure, "sheetChunks: malformed pieces"));
    }
    Ok(r.chunks(6).map(|g| {
        let mut text = header.clone();
        for (q, p) in pieces[g[0] as usize..=g[1] as usize].iter().enumerate() {
            if q > 0 {
                text.push('\n');
            }
            text.push_str(&p.text);
        }
        SheetChunk { range: sheet_chunks_gen::range_of(g[2], g[3], g[4], g[5]).to_string(),
            row1: g[2] as f64, row2: g[3] as f64, col1: g[4] as f64, col2: g[5] as f64, text }
    }).collect())
}

#[path = "../gen/text_around_gen.rs"]
#[allow(dead_code, clippy::all)]
mod text_around_gen;

/// The Pruv around_plan record of Lair textAround for the bytes of a whole file: [0, totalLines] when the
/// first shown line is past the end, else [1, totalLines, shown target, beforeStart, beforeEnd, targetStart,
/// targetEnd, afterStart, afterEnd, newlines before, truncated, target cut] (byte offsets into `data`).
#[napi(js_name = "textAroundPlan")]
pub fn text_around_plan(data: napi::bindgen_prelude::Uint8Array, line: f64, before: f64, after: f64, max_bytes: f64)
    -> napi::Result<Vec<f64>> {
    let f = "textAroundPlan";
    let int = |name: &str, v: f64, lo: f64, hi: f64| -> napi::Result<i64> {
        if !v.is_finite() || v.fract() != 0.0 || !(lo..=hi).contains(&v) {
            return Err(napi::Error::new(napi::Status::InvalidArg,
                format!("{f}: {name} must be an integer in {lo}..={hi}")));
        }
        Ok(v as i64)
    };
    let line = int("line", line, 1.0, 1e15)?;
    let before = int("before", before, 0.0, 1e15)?;
    let after = int("after", after, 0.0, 1e15)?;
    let max_bytes = int("maxBytes", max_bytes, 0.0, 1_099_511_627_776.0)?;
    if data.len() as u64 > 1_099_511_627_776 {
        return Err(napi::Error::new(napi::Status::InvalidArg, "textAroundPlan: data must be at most 1099511627776 bytes"));
    }
    let r = text_around_gen::around_plan(&data, line, before, after, max_bytes);
    if r.first() == Some(&-2) {
        return Err(napi::Error::new(napi::Status::GenericFailure, "textAroundPlan: unexpected line offsets"));
    }
    Ok(r.iter().map(|&x| x as f64).collect())
}

#[path = "../gen/parse_html_gen.rs"]
#[allow(dead_code, clippy::all)]
mod parse_html_gen;

/// The Pruv parse_html record list of Lair parseHtml (docx.ts) for `html`: per node in document order a text
/// record [0, parent, n, code points] or an element record [1, parent, n, lowercase tag code points, then
/// for href, colspan and rowspan -1 or m followed by the decoded value code points]. parent is the element
/// number (elements count from 0 in creation order) or -1 for the top level.
#[napi(js_name = "parseHtmlRecords")]
pub fn parse_html_records(html: String) -> napi::Result<Vec<f64>> {
    if html.len() as u64 > 274_877_906_944 {
        return Err(napi::Error::new(napi::Status::InvalidArg, "parseHtmlRecords: html must be at most 274877906944 UTF-8 bytes"));
    }
    let r = parse_html_gen::parse_html(&html);
    if r.len() == 1 && r[0] == -1 {
        return Err(napi::Error::new(napi::Status::GenericFailure, "parseHtmlRecords: output passes 1099511627776 slots"));
    }
    Ok(r.iter().map(|&x| x as f64).collect())
}

#[path = "../gen/docx_parts_gen.rs"]
#[allow(dead_code, clippy::all)]
mod docx_parts_gen;

/// Lair docxParts (docx.ts) past its parse for `html`: [len(rec), the parse_html record list, the <img\b
/// count, then the docx_parts list: nblocks, per block (kind 0 p / 1 h / 2 li / 3 tr, element number, n,
/// text code points), hlen, preview HTML code points].
#[napi(js_name = "docxPartsRecords")]
pub fn docx_parts_records(html: String) -> napi::Result<Vec<f64>> {
    if html.len() as u64 > 274_877_906_944 {
        return Err(napi::Error::new(napi::Status::InvalidArg, "docxPartsRecords: html must be at most 274877906944 UTF-8 bytes"));
    }
    let rec = parse_html_gen::parse_html(&html);
    if rec.len() == 1 && rec[0] == -1 {
        return Err(napi::Error::new(napi::Status::GenericFailure, "docxPartsRecords: output passes 1099511627776 slots"));
    }
    let parts = docx_parts_gen::docx_parts(&rec);
    if parts.len() == 1 && parts[0] == -1 {
        return Err(napi::Error::new(napi::Status::GenericFailure, "docxPartsRecords: record list passes 68719476736 slots"));
    }
    let mut out = Vec::with_capacity(rec.len() + parts.len() + 2);
    out.push(rec.len() as f64);
    out.extend(rec.iter().map(|&x| x as f64));
    out.push(docx_parts_gen::img_count(&html) as f64);
    out.extend(parts.iter().map(|&x| x as f64));
    Ok(out)
}

#[path = "../gen/tokenize_gen.rs"]
#[allow(dead_code, clippy::all)]
mod tokenize_gen;

/// The Pruv token list of Lair tokenize (search.ts) for `text`: [token count, then per token: n, n code
/// points]. Unicode 17.0 (ICU 78.2) lowercase, letters, numbers and scripts.
#[napi(js_name = "tokenizeRecords")]
pub fn tokenize_records(text: String) -> napi::Result<Vec<f64>> {
    if text.len() as u64 > 274_877_906_944 {
        return Err(napi::Error::new(napi::Status::InvalidArg, "tokenizeRecords: text must be at most 274877906944 UTF-8 bytes"));
    }
    let r = tokenize_gen::tokenize(&text);
    if r.len() == 1 && r[0] == -1 {
        return Err(napi::Error::new(napi::Status::GenericFailure, "tokenizeRecords: output passes 1099511627776 slots"));
    }
    Ok(r.iter().map(|&x| x as f64).collect())
}
