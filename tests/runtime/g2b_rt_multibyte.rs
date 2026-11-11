fn main() {
    let s = "안녕😀";
    println!("{}", sol::han() == s);
    println!("{}", sol::han().len());
    let mut bad = 0;
    for i in -1..=11i64 {
        if sol::bnd(s, i) != s.is_char_boundary(i as usize) {
            bad += 1;
        }
    }
    println!("{}", bad);
    for (lo, hi) in [(0i64, 3i64), (3, 6), (6, 10), (0, 10), (6, 6), (10, 10), (0, 0)] {
        let t = sol::cutb(s, lo, hi);
        println!("{}", t == &s[lo as usize..hi as usize]);
    }
    println!("{}", sol::pick() == "녕");
}
