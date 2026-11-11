fn main() {
    let a = sol::roundtrip("hello");
    println!("{} {}", a, a.len());
    let b = sol::roundtrip("héllo wörld");
    println!("{} {}", b, b.len());
    let c = sol::roundtrip("");
    println!("[{}] {}", c, c.len());
    println!("{}", sol::twice_len("日本"));
    println!("{}", sol::twice_len("ab"));
}
