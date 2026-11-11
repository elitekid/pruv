fn main() {
    let p = sol::build(7, true);
    assert_eq!(p, sol::pruv_g3_t_4_Pair_2_i_b { first: 7, second: true });
    let q = sol::swap_ib(p);
    assert_eq!(q, sol::pruv_g3_t_4_Pair_2_b_i { first: true, second: 7 });
    println!("{} {}", q.first, q.second);
    let r = sol::reset_first(p);
    println!("{} {}", r.first, r.second);
}
