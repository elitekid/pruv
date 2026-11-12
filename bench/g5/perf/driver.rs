// G5 perf host driver, shared by both programs and both back ends. bench/g5/perf.py prepends
//   #![allow(dead_code, unused_imports)]
//   #[path = "<generated>"] mod sol;
// (like tests/run_all.py runtime_job) and links the llvm objects when the llvm back end is measured.
// Usage: driver [N=1000000] [REPS=10] [INNER=20]
// Per repetition: rev_once (setup included), rev_n(a, 0) (setup alone), rev_n(a, INNER) (setup + INNER reversals).
// Every output is checked against an independently computed order-sensitive checksum (exit 3 on mismatch), which also
// keeps the calls alive. A counting global allocator sees every allocation: Rust-side Vecs and, because the llvm
// runtime is built with -DPRUV_RUST_ALLOCATOR, the llvm arrays too.
use std::alloc::{GlobalAlloc, Layout, System};
use std::hint::black_box;
use std::sync::atomic::{AtomicU64, Ordering::Relaxed};
use std::time::Instant;

struct Counting;
static ALLOCS: AtomicU64 = AtomicU64::new(0);
static FREES: AtomicU64 = AtomicU64::new(0);
static BYTES: AtomicU64 = AtomicU64::new(0);

unsafe impl GlobalAlloc for Counting {
    unsafe fn alloc(&self, l: Layout) -> *mut u8 {
        ALLOCS.fetch_add(1, Relaxed);
        BYTES.fetch_add(l.size() as u64, Relaxed);
        System.alloc(l)
    }
    unsafe fn alloc_zeroed(&self, l: Layout) -> *mut u8 {
        ALLOCS.fetch_add(1, Relaxed);
        BYTES.fetch_add(l.size() as u64, Relaxed);
        System.alloc_zeroed(l)
    }
    unsafe fn dealloc(&self, p: *mut u8, l: Layout) {
        FREES.fetch_add(1, Relaxed);
        System.dealloc(p, l)
    }
    unsafe fn realloc(&self, p: *mut u8, l: Layout, new_size: usize) -> *mut u8 {
        ALLOCS.fetch_add(1, Relaxed);
        FREES.fetch_add(1, Relaxed);
        BYTES.fetch_add(new_size as u64, Relaxed);
        System.realloc(p, l, new_size)
    }
}

#[global_allocator]
static GLOBAL: Counting = Counting;

fn snap() -> (u64, u64, u64) {
    (ALLOCS.load(Relaxed), FREES.load(Relaxed), BYTES.load(Relaxed))
}

fn cks(v: &[i64]) -> u64 {
    let mut h: u64 = 0xcbf29ce484222325;
    for (i, x) in v.iter().enumerate() {
        h = (h ^ (*x as u64)).wrapping_mul(0x100000001b3) ^ (i as u64);
    }
    h
}

fn arg(i: usize, d: usize) -> usize {
    std::env::args().nth(i).and_then(|s| s.parse().ok()).unwrap_or(d)
}

fn join(v: &[u64]) -> String {
    v.iter().map(|x| x.to_string()).collect::<Vec<_>>().join(",")
}

fn main() {
    let n = arg(1, 1_000_000);
    let reps = arg(2, 10);
    let inner = arg(3, 20);
    let mut x: u64 = 0x9E3779B97F4A7C15;
    let input: Vec<i64> = (0..n)
        .map(|_| {
            x = x.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
            (x ^ (x >> 29)) as i64
        })
        .collect();
    let rev_in: Vec<i64> = input.iter().rev().cloned().collect();
    let want_id = cks(&input);
    let want_rev = cks(&rev_in);
    let want_many = if inner % 2 == 0 { want_id } else { want_rev };
    drop(rev_in);

    // warm-up (not recorded): page-faults the input and the code
    let w = sol::rev_once(black_box(&input));
    if cks(&w) != want_rev {
        eprintln!("checksum mismatch (warm-up rev_once)");
        std::process::exit(3);
    }
    drop(w);

    let (mut t_once, mut t_zero, mut t_many) = (Vec::new(), Vec::new(), Vec::new());
    let (mut a_once, mut a_zero, mut a_many) = (Vec::new(), Vec::new(), Vec::new());
    let (mut b_once, mut b_zero, mut b_many) = (Vec::new(), Vec::new(), Vec::new());
    let (mut f_once, mut f_zero, mut f_many) = (Vec::new(), Vec::new(), Vec::new());
    for _ in 0..reps {
        let s0 = snap();
        let t = Instant::now();
        let o1 = sol::rev_once(black_box(&input));
        let d1 = t.elapsed().as_nanos() as u64;
        let s1 = snap();
        let o1 = black_box(o1);
        let ok1 = cks(&o1) == want_rev;
        drop(o1);

        let s2 = snap();
        let t = Instant::now();
        let o2 = sol::rev_n(black_box(&input), 0);
        let d2 = t.elapsed().as_nanos() as u64;
        let s3 = snap();
        let o2 = black_box(o2);
        let ok2 = cks(&o2) == want_id;
        drop(o2);

        let s4 = snap();
        let t = Instant::now();
        let o3 = sol::rev_n(black_box(&input), inner as i64);
        let d3 = t.elapsed().as_nanos() as u64;
        let s5 = snap();
        let o3 = black_box(o3);
        let ok3 = cks(&o3) == want_many;
        drop(o3);

        if !(ok1 && ok2 && ok3) {
            eprintln!("checksum mismatch (once {} zero {} many {})", ok1, ok2, ok3);
            std::process::exit(3);
        }
        t_once.push(d1);
        t_zero.push(d2);
        t_many.push(d3);
        a_once.push(s1.0 - s0.0);
        f_once.push(s1.1 - s0.1);
        b_once.push(s1.2 - s0.2);
        a_zero.push(s3.0 - s2.0);
        f_zero.push(s3.1 - s2.1);
        b_zero.push(s3.2 - s2.2);
        a_many.push(s5.0 - s4.0);
        f_many.push(s5.1 - s4.1);
        b_many.push(s5.2 - s4.2);
    }
    println!(
        "{{\"n\":{},\"reps\":{},\"inner\":{},\"ok\":true,\"checksum_id\":{},\"checksum_rev\":{},\
\"once_ns\":[{}],\"zero_ns\":[{}],\"many_ns\":[{}],\
\"once_allocs\":[{}],\"zero_allocs\":[{}],\"many_allocs\":[{}],\
\"once_frees\":[{}],\"zero_frees\":[{}],\"many_frees\":[{}],\
\"once_bytes\":[{}],\"zero_bytes\":[{}],\"many_bytes\":[{}]}}",
        n, reps, inner, want_id, want_rev,
        join(&t_once), join(&t_zero), join(&t_many),
        join(&a_once), join(&a_zero), join(&a_many),
        join(&f_once), join(&f_zero), join(&f_many),
        join(&b_once), join(&b_zero), join(&b_many)
    );
}
