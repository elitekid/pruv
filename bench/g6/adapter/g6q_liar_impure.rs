// LIAR (effect, not value): the results are all correct, but the function keeps hidden global state (a call counter).
// The declaration claims no effect, so this violates the effect-honesty obligation. No test or runtime check sees it.
use std::sync::atomic::{AtomicUsize, Ordering};

static CALLS: AtomicUsize = AtomicUsize::new(0);

pub fn calls() -> usize {
    CALLS.load(Ordering::SeqCst)
}

pub fn parse_digit(s: &str) -> i64 {
    CALLS.fetch_add(1, Ordering::SeqCst);
    let b = s.as_bytes();
    if b.len() == 1 && b[0] >= b'0' && b[0] <= b'9' {
        (b[0] - b'0') as i64
    } else {
        -1
    }
}
