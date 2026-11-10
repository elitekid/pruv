//! Python `open(path).read()` 흉내: 실패하면 Python 예외의 str(e) 문장을 돌려준다.
//! (CLI·시험 바이너리가 읽기·해독 실패를 Python 판처럼 internal_error 로 보고하는 데 쓴다.)
//! 개행 정규화는 parse 가 한다. 해독 오류 위치는 파일 앞에서부터 센 바이트 위치다(Python 이 파일 전체를
//! 한 번에 읽을 때와 같다; 8192바이트 너머·CRLF 섞임도 확인됨, RESULTS 18절).

use crate::pyrepr::repr_str;

/// UTF-8 엄격 해독 실패를 Python `UnicodeDecodeError` 문장으로.
pub fn utf8_error_message(bytes: &[u8], e: &std::str::Utf8Error) -> String {
    let start = e.valid_up_to();
    let (end, reason) = match e.error_len() {
        None => (bytes.len(), "unexpected end of data"),
        Some(n) => {
            let b = bytes[start];
            // 시작 바이트가 될 수 없는 값(이어지는 바이트·C0/C1·F5 이상)이면 invalid start byte
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

/// 파일 읽기 실패를 Python `OSError` 문장(`[Errno N] 설명: 'path'`)으로.
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

/// 읽기 + 엄격 UTF-8 해독. 실패하면 Python str(e) 와 같은 문장.
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
