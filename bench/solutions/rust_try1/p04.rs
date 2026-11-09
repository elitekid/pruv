pub fn binary_search(a: &[i64], x: i64) -> Option<i64> {
    let (mut lo, mut hi) = (0usize, a.len());
    while lo < hi {
        let mid = lo + (hi - lo) / 2;
        if a[mid] < x { lo = mid + 1; } else { hi = mid; }
    }
    if lo < a.len() && a[lo] == x { Some(lo as i64) } else { None }
}
