pub fn max_subarray(a: &[i64]) -> i64 {
    if a.is_empty() {
        return 0;
    }
    let mut cur = a[0];
    let mut best = a[0];
    for &v in &a[1..] {
        cur = if cur > 0 { cur + v } else { v };
        if cur > best {
            best = cur;
        }
    }
    best
}
