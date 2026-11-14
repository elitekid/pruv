// Single-threaded binarytrees-rust-1 with a contiguous preorder arena.
// Each i64 slot is a node: left = root + 1, right = arena[root], leaf = -1.
fn build(a: &mut [i64], root: usize, span: usize) {
    if span >= 3 {
        let half = (span - 1) / 2;
        let right = root + 1 + half;
        a[root] = right as i64;
        if half >= 3 {
            build(a, root + 1, half);
            build(a, right, half);
        }
    }
}
fn tree(depth: i64) -> Vec<i64> {
    let count = (1usize << (depth + 1)) - 1;
    let mut a = vec![-1; count];
    build(&mut a, 0, count);
    a
}
fn check(a: &[i64], root: usize, span: usize) -> i64 {
    if span < 3 { return 1; }
    let half = (span - 1) / 2;
    1 + check(a, root + 1, half) + check(a, a[root] as usize, half)
}
pub fn bench(_data: &[u8], n: i64) -> Vec<i64> {
    let mut out = Vec::with_capacity(((n - 4) / 2 + 3) as usize);
    {
        let stretch = tree(n + 1);
        out.push(check(&stretch, 0, stretch.len()));
    }
    let long = tree(n);
    for d in (4..=n).step_by(2) {
        let iterations = 1i64 << (n - d + 4);
        let mut sum = 0;
        for _ in 0..iterations {
            let a = tree(d);
            sum += check(&a, 0, a.len());
        }
        out.push(sum);
    }
    out.push(check(&long, 0, long.len()));
    out
}
