/// Representation conversion only: invalid UTF-8 returns an empty String.
pub fn utf8_to_string(data: &[u8]) -> String {
    std::str::from_utf8(data).map(str::to_owned).unwrap_or_default()
}
