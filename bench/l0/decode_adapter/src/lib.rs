//! Trusted adapters behind bench/l0/decode_bytes.pruv. Each function keeps the contract written
//! on its `trusted rust fn` declaration; the decoders are encoding_rs, which implements the same
//! WHATWG Encoding Standard as TextDecoder.
use encoding_rs::{EUC_KR, UTF_16BE, UTF_16LE, UTF_8};

/// Lossy UTF-8 of data[from..]; a further UTF-8 BOM there is removed (TextDecoder default).
/// Every input byte gives at most one U+FFFD, so the output is at most 3 bytes per input byte.
pub fn utf8_lossy(data: &[u8], from: i64) -> String {
    let (text, _) = UTF_8.decode_with_bom_removal(&data[from as usize..]);
    text.into_owned()
}

/// UTF-16 (little or big endian) of data[from..]; a further BOM of that byte order is removed.
/// Two input bytes give at most 3 output bytes, and an odd last byte gives one U+FFFD.
pub fn utf16(data: &[u8], from: i64, big: bool) -> String {
    let encoding = if big { UTF_16BE } else { UTF_16LE };
    let (text, _) = encoding.decode_with_bom_removal(&data[from as usize..]);
    text.into_owned()
}

/// EUC-KR (WHATWG, i.e. CP949) with no BOM handling, as TextDecoder('euc-kr') does.
pub fn euc_kr(data: &[u8]) -> String {
    let (text, _) = EUC_KR.decode_without_bom_handling(data);
    text.into_owned()
}

/// The bytes as a String when they are valid UTF-8, otherwise empty.
pub fn utf8_copy(data: &[u8]) -> String {
    std::str::from_utf8(data).map(str::to_owned).unwrap_or_default()
}
