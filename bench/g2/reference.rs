// Trusted reference implementations for the G2 problems (no external crates).

pub fn clamp_bytes(a: &[i64]) -> Vec<u8> {
    a.iter().map(|&x| x.max(0).min(255) as u8).collect()
}

pub fn ascii_mask(a: &[u8]) -> Vec<u8> {
    a.iter().map(|&x| if x < 128 { x } else { 63 }).collect()
}

pub fn add_sat(a: &[u8], d: i64) -> Vec<u8> {
    a.iter().map(|&x| (x as i64 + d).max(0).min(255) as u8).collect()
}

pub fn longest_true_run(a: &[bool]) -> i64 {
    let mut best: i64 = 0;
    let mut cur: i64 = 0;
    for &b in a {
        if b {
            cur += 1;
            if cur > best {
                best = cur;
            }
        } else {
            cur = 0;
        }
    }
    best
}

pub fn count_chars(s: &str) -> i64 {
    s.chars().count() as i64
}

pub fn prefix_chars(s: &str, k: i64) -> String {
    s.chars().take(k as usize).collect()
}
