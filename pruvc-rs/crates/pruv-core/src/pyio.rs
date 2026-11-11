//! Imitation of Python `open(path).read()`: on failure, returns the str(e) message of the Python exception.
//! (Used by the CLI and test binaries to report read/decode failures as internal_error, like the Python implementation.)
//! Newline normalization is done by parse. The decode-error position is the byte position counted from the start of the file (the same as when Python
//! reads the whole file at once; also confirmed beyond 8192 bytes and with mixed CRLF, RESULTS §18).

use crate::pyrepr::repr_str;

/// A strict UTF-8 decode failure as a Python `UnicodeDecodeError` message.
pub fn utf8_error_message(bytes: &[u8], e: &std::str::Utf8Error) -> String {
    let start = e.valid_up_to();
    let (end, reason) = match e.error_len() {
        None => (bytes.len(), "unexpected end of data"),
        Some(n) => {
            let b = bytes[start];
            // A value that cannot be a start byte (a continuation byte, C0/C1, F5 or above) gives invalid start byte
            let bad_start = (0x80..=0xC1).contains(&b) || b >= 0xF5;
            (start + n, if n == 1 && bad_start { "invalid start byte" } else { "invalid continuation byte" })
        }
    };
    if end - start == 1 {
        format!("'utf-8' codec can't decode byte 0x{:02x} in position {}: {}", bytes[start], start, reason)
    } else {
        format!("'utf-8' codec can't decode bytes in position {}-{}: {}", start, end - 1, reason)
    }
}

/// A file read failure as a Python `OSError` message (`[Errno N] description: 'path'`).
pub fn io_error_message(path: &std::path::Path, e: &std::io::Error) -> String {
    let shown = repr_str(&path.to_string_lossy());
    match e.raw_os_error() {
        Some(code) => {
            let text = e.to_string();
            let desc = match text.rfind(" (os error ") {
                Some(i) => text[..i].to_string(),
                None => text,
            };
            format!("[Errno {}] {}: {}", code, desc, shown)
        }
        None => format!("{}: {}", e, shown),
    }
}

/// Read plus strict UTF-8 decoding. On failure, the same message as Python's str(e).
pub fn read_source(path: &std::path::Path) -> Result<String, String> {
    let bytes = std::fs::read(path).map_err(|e| io_error_message(path, &e))?;
    match std::str::from_utf8(&bytes) {
        Ok(_) => Ok(String::from_utf8(bytes).unwrap_or_default()),
        Err(e) => Err(utf8_error_message(&bytes, &e)),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn msg(b: &[u8]) -> String {
        utf8_error_message(b, &std::str::from_utf8(b).unwrap_err())
    }

    #[test]
    fn decode_messages() {
        assert_eq!(msg(b"ab\xff"), "'utf-8' codec can't decode byte 0xff in position 2: invalid start byte");
        assert_eq!(msg(b"\xe2\x28"), "'utf-8' codec can't decode byte 0xe2 in position 0: invalid continuation byte");
        assert_eq!(msg(b"\xe2\x82\x28"), "'utf-8' codec can't decode bytes in position 0-1: invalid continuation byte");
        assert_eq!(msg(b"x\xe2\x82"), "'utf-8' codec can't decode bytes in position 1-2: unexpected end of data");
        assert_eq!(msg(b"\xc0\x80"), "'utf-8' codec can't decode byte 0xc0 in position 0: invalid start byte");
        assert_eq!(msg(b"\xed\xa0\x80"), "'utf-8' codec can't decode byte 0xed in position 0: invalid continuation byte");
        assert_eq!(msg(b"\xf4\x90\x80\x80"), "'utf-8' codec can't decode byte 0xf4 in position 0: invalid continuation byte");
    }
}
