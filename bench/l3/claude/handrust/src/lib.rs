//! Hand-written plain-Rust Claude JSONL "window" import (speed baseline against the Pruv version).
//! Target: the same packet as `oracle.py::window_packet(data, cut_before)`.
//!
//! Approach: one pass over byte slices, `serde_json::from_slice::<Value>` per line (features
//! `arbitrary_precision` for raw number text such as "-0" / "1e999", `unbounded_depth` for the depth fallback).
//! Handled so the packet still equals the oracle (slow path, only after serde rejected a line):
//!   * lone surrogate escapes ("\ud800", "\udc00", "\ud83dA"): rewritten to "�" in a scratch copy, then
//!     parsed again (the oracle maps lone surrogates in values to U+FFFD).
//!   * container depth exactly 128: serde's limit rejects 128 nested containers, the oracle accepts them. The
//!     fallback scans the nesting depth (string aware); > 128 -> line ignored, == 128 -> parsed without the limit.
//!   * duplicate keys: serde's map keeps the last one, like the oracle; an earlier deeper value still counts for depth.
//!
//! Known remaining differences (none expected on real transcripts):
//!   1. With `arbitrary_precision`, a JSON object whose only key is "$serde_json::private::Number" is read by serde
//!      as a number (or rejected) instead of an object. The oracle sees a plain object.
//!   2. Keys containing lone surrogates are rewritten too, so two distinct such keys collapse into one
//!      (only matters for keys the import never looks up, so it is invisible in the packet).
//!   3. The depth fallback relies on serde reporting "recursion limit exceeded" in its error text.
//!   4. The oracle decodes the 8 KiB drop prefix with Python's replacement decoder, this uses `from_utf8_lossy`;
//!      both replace by maximal subparts and the replacement char matches no pattern, so results are the same.

use serde_json::{Map, Value};
use std::borrow::Cow;
use std::collections::VecDeque;

const WINDOW: usize = 8_388_608;
const LINE: usize = 1_048_576;
const DROP: usize = 8192;
const LIM: usize = 32768;
const TOTAL: usize = 2_097_152;
const MAXTURNS: usize = 200;
const SYNTHETIC: &str = "<synthetic>";
const SAFE: i64 = 9_007_199_254_740_991;
const MIN_MS: i64 = -62_167_219_200_000;
const MAX_MS: i64 = 253_402_300_799_999;

type Stamp = Option<[u8; 24]>;

// ---------------- ECMAScript whitespace and text helpers ----------------
fn is_es_ws(c: char) -> bool {
    matches!(
        c,
        '\t' | '\n' | '\u{b}' | '\u{c}' | '\r' | ' ' | '\u{a0}' | '\u{1680}' | '\u{2000}'..='\u{200a}'
            | '\u{2028}' | '\u{2029}' | '\u{202f}' | '\u{205f}' | '\u{3000}' | '\u{feff}'
    )
}

fn es_trim(s: &str) -> &str {
    s.trim_matches(is_es_ws)
}

/// Whitespace runs -> one space, trim, then cut to `mx` UTF-16 units on a scalar boundary.
fn one_line(s: &str, mx: usize) -> String {
    let mut out = String::new();
    let mut pending = false;
    let mut u = 0usize;
    for c in s.chars() {
        if is_es_ws(c) {
            pending = true;
            continue;
        }
        if pending && !out.is_empty() {
            if u + 1 > mx {
                break;
            }
            out.push(' ');
            u += 1;
        }
        pending = false;
        let w = c.len_utf16();
        if u + w > mx {
            break;
        }
        out.push(c);
        u += w;
    }
    out
}

/// Longest prefix length <= mx that ends on a scalar boundary of valid UTF-8 `raw`.
fn clip_len(raw: &[u8], mx: usize) -> usize {
    if raw.len() <= mx {
        return raw.len();
    }
    let mut k = mx;
    while k > 0 && (raw[k] & 0xC0) == 0x80 {
        k -= 1;
    }
    k
}

// ---------------- timestamps ----------------
fn is_leap(y: u32) -> bool {
    y % 4 == 0 && (y % 100 != 0 || y % 400 == 0)
}

fn mdays(y: u32, m: u32) -> u32 {
    match m {
        2 => {
            if is_leap(y) {
                29
            } else {
                28
            }
        }
        4 | 6 | 9 | 11 => 30,
        _ => 31,
    }
}

fn canon(s: &[u8]) -> bool {
    if s.len() != 24 {
        return false;
    }
    for (i, &c) in s.iter().enumerate() {
        let ok = match i {
            4 | 7 => c == b'-',
            10 => c == b'T',
            13 | 16 => c == b':',
            19 => c == b'.',
            23 => c == b'Z',
            _ => c.is_ascii_digit(),
        };
        if !ok {
            return false;
        }
    }
    let n = |a: usize, l: usize| -> u32 { s[a..a + l].iter().fold(0u32, |x, &c| x * 10 + (c - b'0') as u32) };
    let (y, mo, d, h, mi, sec) = (n(0, 4), n(5, 2), n(8, 2), n(11, 2), n(14, 2), n(17, 2));
    (1..=12).contains(&mo) && d >= 1 && d <= mdays(y, mo) && h <= 23 && mi <= 59 && sec <= 59
}

fn put_digits(o: &mut [u8; 24], at: usize, n: usize, mut v: i64) {
    for k in (0..n).rev() {
        o[at + k] = b'0' + (v % 10) as u8;
        v /= 10;
    }
}

/// `ms` within [MIN_MS, MAX_MS] -> "YYYY-MM-DDTHH:MM:SS.mmmZ".
fn format_iso(ms: i64) -> [u8; 24] {
    let days = ms.div_euclid(86_400_000);
    let rem = ms.rem_euclid(86_400_000);
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z - era * 146_097;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let y = yoe + era * 400 + if m <= 2 { 1 } else { 0 };
    let secs = rem / 1000;
    let mut o = *b"0000-00-00T00:00:00.000Z";
    put_digits(&mut o, 0, 4, y);
    put_digits(&mut o, 5, 2, m);
    put_digits(&mut o, 8, 2, d);
    put_digits(&mut o, 11, 2, secs / 3600);
    put_digits(&mut o, 14, 2, secs % 3600 / 60);
    put_digits(&mut o, 17, 2, secs % 60);
    put_digits(&mut o, 20, 3, rem % 1000);
    o
}

fn iso_of_int(v: i64) -> Stamp {
    let ms = if v < 100_000_000_000 { v * 1000 } else { v };
    if (MIN_MS..=MAX_MS).contains(&ms) {
        Some(format_iso(ms))
    } else {
        None
    }
}

fn iso_number(text: &str) -> Stamp {
    if text.bytes().any(|c| matches!(c, b'.' | b'e' | b'E')) {
        return None;
    }
    if text.trim_start_matches('-').len() > 17 {
        return None;
    }
    let n: i64 = text.parse().ok()?;
    if n.abs() > SAFE {
        return None;
    }
    iso_of_int(n)
}

fn iso_str(s: &str) -> Stamp {
    let t = es_trim(s);
    if !t.is_empty() && t.bytes().all(|c| c.is_ascii_digit()) {
        let digits = t.trim_start_matches('0');
        if digits.len() > 16 {
            return None;
        }
        let n: i64 = if digits.is_empty() { 0 } else { digits.parse().ok()? };
        if n > SAFE {
            return None;
        }
        return iso_of_int(n);
    }
    if s.len() == 24 && canon(s.as_bytes()) {
        let mut o = [0u8; 24];
        o.copy_from_slice(s.as_bytes());
        return Some(o);
    }
    None
}

fn iso(v: Option<&Value>) -> Stamp {
    match v? {
        Value::Number(n) => iso_number(&n.to_string()),
        Value::String(s) => iso_str(s),
        _ => None,
    }
}

// ---------------- oversized-line probe (the oracle's o_dropped regexes) ----------------
/// Byte length of the ECMAScript whitespace character at `i` (0 if none).
fn ws_len(b: &[u8], i: usize) -> usize {
    match b.get(i) {
        Some(0x09..=0x0D) | Some(0x20) => 1,
        Some(0xC2) => (b.get(i + 1) == Some(&0xA0)) as usize * 2,
        Some(0xE1) => (b.get(i + 1) == Some(&0x9A) && b.get(i + 2) == Some(&0x80)) as usize * 3,
        Some(0xE2) => match (b.get(i + 1), b.get(i + 2)) {
            (Some(0x80), Some(0x80..=0x8A)) | (Some(0x80), Some(0xA8)) | (Some(0x80), Some(0xA9)) => 3,
            (Some(0x80), Some(0xAF)) | (Some(0x81), Some(0x9F)) => 3,
            _ => 0,
        },
        Some(0xE3) => (b.get(i + 1) == Some(&0x80) && b.get(i + 2) == Some(&0x80)) as usize * 3,
        Some(0xEF) => (b.get(i + 1) == Some(&0xBB) && b.get(i + 2) == Some(&0xBF)) as usize * 3,
        _ => 0,
    }
}

fn skip_ws(b: &[u8], mut i: usize) -> usize {
    loop {
        let n = ws_len(b, i);
        if n == 0 {
            return i;
        }
        i += n;
    }
}

fn find(hay: &[u8], needle: &[u8], from: usize) -> Option<usize> {
    if from >= hay.len() {
        return None;
    }
    let first = needle[0];
    let mut i = from;
    while i + needle.len() <= hay.len() {
        match hay[i..hay.len() - needle.len() + 1].iter().position(|&c| c == first) {
            None => return None,
            Some(p) => {
                i += p;
                if &hay[i..i + needle.len()] == needle {
                    return Some(i);
                }
                i += 1;
            }
        }
    }
    None
}

/// key WS* ':' WS* val, anywhere.
fn key_colon_val(b: &[u8], key: &[u8], val: &[u8]) -> bool {
    let mut from = 0;
    while let Some(p) = find(b, key, from) {
        let mut i = skip_ws(b, p + key.len());
        if b.get(i) == Some(&b':') {
            i = skip_ws(b, i + 1);
            if b[i..].starts_with(val) {
                return true;
            }
        }
        from = p + 1;
    }
    false
}

/// "content" WS* : WS* [ WS* { [^{}]* "type" WS* : WS* "tool_result"
fn has_tool_result(b: &[u8]) -> bool {
    let key = b"\"content\"";
    let mut from = 0;
    while let Some(p) = find(b, key, from) {
        from = p + 1;
        let mut i = skip_ws(b, p + key.len());
        if b.get(i) != Some(&b':') {
            continue;
        }
        i = skip_ws(b, i + 1);
        if b.get(i) != Some(&b'[') {
            continue;
        }
        i = skip_ws(b, i + 1);
        if b.get(i) != Some(&b'{') {
            continue;
        }
        i += 1;
        let end = b[i..].iter().position(|&c| c == b'{' || c == b'}').map_or(b.len(), |x| i + x);
        if key_colon_val(&b[i..end], b"\"type\"", b"\"tool_result\"") {
            return true;
        }
    }
    false
}

fn dropped_user(head: &[u8]) -> bool {
    let s = String::from_utf8_lossy(head);
    let b = s.as_bytes();
    key_colon_val(b, b"\"type\"", b"\"user\"")
        && !(has_tool_result(b)
            || key_colon_val(b, b"\"isMeta\"", b"true")
            || key_colon_val(b, b"\"isSidechain\"", b"true"))
}

// ---------------- line parsing with serde_json and the slow-path fallbacks ----------------
fn hex4(b: &[u8]) -> Option<u32> {
    if b.len() < 4 {
        return None;
    }
    let mut n = 0u32;
    for &c in &b[..4] {
        n = n * 16 + (c as char).to_digit(16)?;
    }
    Some(n)
}

/// Copies `src` into `out`, turning lone surrogate escapes into "�". Returns whether anything changed.
fn rewrite_lone_surrogates(src: &[u8], out: &mut Vec<u8>) -> bool {
    let mut changed = false;
    let mut in_str = false;
    let mut i = 0;
    out.reserve(src.len());
    while i < src.len() {
        let c = src[i];
        if !in_str {
            if c == b'"' {
                in_str = true;
            }
            out.push(c);
            i += 1;
            continue;
        }
        match c {
            b'"' => {
                in_str = false;
                out.push(c);
                i += 1;
            }
            b'\\' => {
                if src.get(i + 1) == Some(&b'u') {
                    if let Some(n) = hex4(&src[i + 2..]) {
                        if (0xD800..0xDC00).contains(&n) {
                            let pair = src.get(i + 6) == Some(&b'\\')
                                && src.get(i + 7) == Some(&b'u')
                                && matches!(src.get(i + 8..).and_then(hex4), Some(m) if (0xDC00..0xE000).contains(&m));
                            if pair {
                                out.extend_from_slice(&src[i..i + 12]);
                                i += 12;
                            } else {
                                out.extend_from_slice(b"\\ufffd");
                                changed = true;
                                i += 6;
                            }
                        } else if (0xDC00..0xE000).contains(&n) {
                            out.extend_from_slice(b"\\ufffd");
                            changed = true;
                            i += 6;
                        } else {
                            out.extend_from_slice(&src[i..i + 6]);
                            i += 6;
                        }
                        continue;
                    }
                }
                out.push(c);
                if let Some(&d) = src.get(i + 1) {
                    out.push(d);
                }
                i += 2;
            }
            _ => {
                out.push(c);
                i += 1;
            }
        }
    }
    changed
}

/// Container nesting deeper than `limit` (string aware; exact for valid JSON).
fn deeper_than(src: &[u8], limit: usize) -> bool {
    let (mut d, mut in_str, mut esc) = (0usize, false, false);
    for &c in src {
        if in_str {
            if esc {
                esc = false;
            } else if c == b'\\' {
                esc = true;
            } else if c == b'"' {
                in_str = false;
            }
        } else {
            match c {
                b'"' => in_str = true,
                b'{' | b'[' => {
                    d += 1;
                    if d > limit {
                        return true;
                    }
                }
                b'}' | b']' => d = d.saturating_sub(1),
                _ => {}
            }
        }
    }
    false
}

/// serde's recursion limit rejects 128 nested containers; the oracle allows exactly 128.
fn parse_deep(src: &[u8], err: &serde_json::Error) -> Option<Value> {
    if !err.to_string().contains("recursion limit") || deeper_than(src, 128) {
        return None;
    }
    let mut de = serde_json::Deserializer::from_slice(src);
    de.disable_recursion_limit();
    let mut it = de.into_iter::<Value>();
    let v = it.next()?.ok()?;
    if it.next().is_some() {
        return None;
    }
    Some(v)
}

fn parse_slow(line: &[u8], first_err: serde_json::Error, scratch: &mut Vec<u8>) -> Option<Value> {
    scratch.clear();
    if line.windows(2).any(|w| w == b"\\u") && rewrite_lone_surrogates(line, scratch) {
        let src = &scratch[..];
        return match serde_json::from_slice::<Value>(src) {
            Ok(v) => Some(v),
            Err(e) => parse_deep(src, &e),
        };
    }
    parse_deep(line, &first_err)
}

fn parse_line(line: &[u8], scratch: &mut Vec<u8>) -> Option<Map<String, Value>> {
    match line.iter().find(|&&b| !matches!(b, b' ' | b'\t' | b'\n' | b'\r')) {
        Some(&b'{') => {}
        _ => return None,
    }
    let v = match serde_json::from_slice::<Value>(line) {
        Ok(v) => v,
        Err(e) => parse_slow(line, e, scratch)?,
    };
    match v {
        Value::Object(m) => Some(m),
        _ => None,
    }
}

// ---------------- entry classification ----------------
fn get_str<'a>(m: &'a Map<String, Value>, k: &str) -> Option<&'a str> {
    match m.get(k) {
        Some(Value::String(s)) => Some(s.as_str()),
        _ => None,
    }
}

fn is_true(m: &Map<String, Value>, k: &str) -> bool {
    matches!(m.get(k), Some(Value::Bool(true)))
}

fn task_origin(e: &Map<String, Value>) -> bool {
    matches!(e.get("origin"), Some(Value::Object(o)) if get_str(o, "kind") == Some("task-notification"))
}

fn is_human_text(e: &Map<String, Value>, text: &str) -> bool {
    let t = es_trim(text);
    if t.is_empty() {
        return false;
    }
    if t == "[Request interrupted by user]" || t == "[Request interrupted by user for tool use]" {
        return false;
    }
    !(t.starts_with("<task-notification>")
        && t.ends_with("</task-notification>")
        && t.chars().count() >= 39
        && task_origin(e))
}

fn human_text<'a>(e: &'a Map<String, Value>) -> Option<Cow<'a, str>> {
    if get_str(e, "type") != Some("user") || is_true(e, "isMeta") || is_true(e, "isSidechain") {
        return None;
    }
    let content = match e.get("message") {
        Some(Value::Object(m)) => m.get("content"),
        _ => None,
    };
    match content {
        Some(Value::String(s)) => {
            if is_human_text(e, s) {
                Some(Cow::Borrowed(s.as_str()))
            } else {
                None
            }
        }
        Some(Value::Array(blocks)) => {
            let mut first: Option<&str> = None;
            let mut joined = String::new();
            let mut count = 0usize;
            for b in blocks {
                let Value::Object(o) = b else { continue };
                match get_str(o, "type") {
                    Some("tool_result") => return None,
                    Some("text") => {
                        if let Some(Value::String(t)) = o.get("text") {
                            match count {
                                0 => first = Some(t.as_str()),
                                1 => {
                                    joined.push_str(first.unwrap_or(""));
                                    joined.push_str("\n\n");
                                    joined.push_str(t);
                                }
                                _ => {
                                    joined.push_str("\n\n");
                                    joined.push_str(t);
                                }
                            }
                            count += 1;
                        }
                    }
                    _ => {}
                }
            }
            let text = match count {
                0 => return None,
                1 => Cow::Borrowed(first.unwrap_or("")),
                _ => Cow::Owned(joined),
            };
            if is_human_text(e, &text) {
                Some(text)
            } else {
                None
            }
        }
        _ => None,
    }
}

/// First of `keys` holding a string that is not blank.
fn pick<'a>(e: &'a Map<String, Value>, k1: &str, k2: &str) -> Option<&'a str> {
    for k in [k1, k2] {
        if let Some(s) = get_str(e, k) {
            if !es_trim(s).is_empty() {
                return Some(s);
            }
        }
    }
    None
}

// ---------------- turn collector ----------------
struct Draft {
    prompt: Vec<u8>,
    reply: Vec<u8>,
    used: usize,
    tools: i64,
    created: Stamp,
    completed: Stamp,
    clipped: bool,
}

struct Collector {
    drafts: VecDeque<Draft>, // only the newest MAXTURNS can ever be kept
    begun: usize,
    active: bool,
    lost: bool,
}

impl Collector {
    fn new() -> Self {
        Collector { drafts: VecDeque::new(), begun: 0, active: false, lost: false }
    }

    fn begin(&mut self, prompt: &str, created: Stamp) {
        let raw = prompt.as_bytes();
        let mut d = if self.drafts.len() >= MAXTURNS {
            let mut d = self.drafts.pop_front().unwrap();
            d.prompt.clear();
            d.reply.clear();
            d
        } else {
            Draft {
                prompt: Vec::new(),
                reply: Vec::new(),
                used: 0,
                tools: 0,
                created: None,
                completed: None,
                clipped: false,
            }
        };
        d.prompt.extend_from_slice(&raw[..clip_len(raw, LIM)]);
        d.used = 0;
        d.tools = 0;
        d.created = created;
        d.completed = None;
        d.clipped = raw.len() > LIM || self.lost;
        self.lost = false;
        self.active = true;
        self.begun += 1;
        self.drafts.push_back(d);
    }

    fn skip_user(&mut self) {
        self.active = false;
        self.lost = true;
    }

    fn answer(&mut self, text: &str, at: Stamp) {
        if !self.active {
            return;
        }
        let Some(d) = self.drafts.back_mut() else { return };
        if at.is_some() {
            d.completed = at;
        }
        let raw = text.as_bytes();
        if raw.is_empty() || d.used >= LIM {
            return;
        }
        let sep = if d.reply.is_empty() { 0 } else { 2 };
        let room = LIM - d.used;
        if sep + raw.len() <= room {
            d.reply.extend_from_slice(&b"\n\n"[..sep]);
            d.reply.extend_from_slice(raw);
            d.used += sep + raw.len();
        } else {
            if room <= sep {
                d.reply.extend_from_slice(&b"\n\n"[..room]);
            } else {
                let k = clip_len(raw, room - sep);
                d.reply.extend_from_slice(&b"\n\n"[..sep]);
                d.reply.extend_from_slice(&raw[..k]);
            }
            d.used = LIM;
            d.clipped = true;
        }
    }

    fn tool(&mut self) {
        if self.active {
            if let Some(d) = self.drafts.back_mut() {
                d.tools += 1;
            }
        }
    }

    /// Number of newest drafts kept (<= MAXTURNS, <= TOTAL bytes).
    fn kept(&self) -> usize {
        let (mut n, mut total) = (0usize, 0usize);
        for d in self.drafts.iter().rev() {
            if n >= MAXTURNS {
                break;
            }
            let size = d.prompt.len() + d.reply.len();
            if total + size > TOTAL {
                break;
            }
            total += size;
            n += 1;
        }
        n
    }
}

#[derive(Default)]
struct State {
    rank: u8,
    title: String,
    model: Vec<u8>,
}

fn consume(e: &Map<String, Value>, col: &mut Collector, st: &mut State) {
    let ty = get_str(e, "type");
    let (rank, key) = match ty {
        Some("custom-title") => (3u8, "customTitle"),
        Some("ai-title") => (2, "aiTitle"),
        Some("summary") => (1, "summary"),
        _ => (0, ""),
    };
    if rank > 0 && rank >= st.rank {
        if let Some(t) = pick(e, key, "title") {
            st.rank = rank;
            st.title.clear();
            st.title.push_str(t);
        }
    }
    if let Some(prompt) = human_text(e) {
        col.begin(&prompt, iso(e.get("timestamp")));
        return;
    }
    if ty != Some("assistant") || is_true(e, "isSidechain") {
        return;
    }
    let msg = match e.get("message") {
        Some(Value::Object(m)) => Some(m),
        _ => None,
    };
    let model = msg.and_then(|m| get_str(m, "model"));
    if model == Some(SYNTHETIC) && !is_true(e, "isApiErrorMessage") {
        return;
    }
    if let Some(m) = model {
        if !m.is_empty() && m != SYNTHETIC {
            st.model.clear();
            st.model.extend_from_slice(m.as_bytes());
        }
    }
    match msg.and_then(|m| m.get("content")) {
        Some(Value::String(s)) => col.answer(s, iso(e.get("timestamp"))),
        Some(Value::Array(blocks)) => {
            let at = iso(e.get("timestamp"));
            for b in blocks {
                let Value::Object(o) = b else { continue };
                match get_str(o, "type") {
                    Some("text") => {
                        if let Some(Value::String(t)) = o.get("text") {
                            col.answer(t, at);
                        }
                    }
                    Some("tool_use") => col.tool(),
                    _ => {}
                }
            }
        }
        _ => {}
    }
}

// ---------------- packet ----------------
fn put(text: &mut Vec<u8>, b: &[u8]) -> [i64; 2] {
    let start = text.len() as i64;
    text.extend_from_slice(b);
    [start, b.len() as i64]
}

pub fn window_packet(data: &[u8], cut_before: i64) -> Vec<i64> {
    if data.len() > WINDOW {
        return vec![1, 0];
    }
    let cut = cut_before != 0;
    let mut col = Collector::new();
    let mut st = State::default();
    let mut scratch: Vec<u8> = Vec::new();

    let mut pos = 0usize;
    if cut {
        pos = match data.iter().position(|&b| b == b'\n') {
            Some(i) => i + 1,
            None => data.len(),
        };
    }
    while pos < data.len() {
        let rest = &data[pos..];
        match rest.iter().position(|&b| b == b'\n') {
            None => {
                if rest.len() > LINE && dropped_user(&rest[..DROP]) {
                    col.skip_user();
                }
                break;
            }
            Some(i) => {
                let raw = &rest[..i];
                if raw.len() > LINE {
                    if dropped_user(&raw[..DROP]) {
                        col.skip_user();
                    }
                } else {
                    let line = if raw.last() == Some(&b'\r') { &raw[..raw.len() - 1] } else { raw };
                    if let Some(e) = parse_line(line, &mut scratch) {
                        consume(&e, &mut col, &mut st);
                    }
                }
                pos += i + 1;
            }
        }
    }

    let n = col.kept();
    let trimmed = n < col.begun;
    let title = if st.rank > 0 { one_line(&st.title, 120) } else { String::new() };

    let mut text: Vec<u8> = Vec::new();
    let title_ref = if title.is_empty() { [-1, 0] } else { put(&mut text, title.as_bytes()) };
    let model_ref = if st.model.is_empty() { [-1, 0] } else { put(&mut text, &st.model) };
    let mut turns: Vec<i64> = Vec::with_capacity(n * 10);
    for d in col.drafts.iter().skip(col.drafts.len() - n) {
        turns.extend_from_slice(&put(&mut text, &d.prompt));
        turns.extend_from_slice(&put(&mut text, &d.reply));
        for s in [&d.created, &d.completed] {
            match s {
                Some(b) => turns.extend_from_slice(&put(&mut text, b)),
                None => turns.extend_from_slice(&[-1, 0]),
            }
        }
        turns.push(d.tools);
        turns.push(d.clipped as i64);
    }

    let mut out: Vec<i64> = Vec::with_capacity(18 + turns.len() + text.len());
    out.extend_from_slice(&[0, 14, turns.len() as i64, text.len() as i64]);
    out.extend_from_slice(&[1, 2, (cut || trimmed) as i64, n as i64]);
    out.extend_from_slice(&title_ref);
    out.extend_from_slice(&[-1, 0, -1, 0, -1, 0]);
    out.extend_from_slice(&model_ref);
    out.extend_from_slice(&turns);
    out.extend(text.iter().map(|&b| b as i64));
    out
}
