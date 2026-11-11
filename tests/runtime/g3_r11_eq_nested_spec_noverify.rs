fn main() {
    let a = sol::pruv_g3_t_4_Pair_2_ob_ri { first: None, second: Err(1) };
    let r = sol::loose_same(a, a);
    println!("{:?} {:?}", r.first, r.second);
    let b = sol::pruv_g3_t_4_Pair_2_ob_ri { first: None, second: Err(2) };
    sol::loose_same(a, b);
}
