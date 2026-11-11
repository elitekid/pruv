fn main() {
    let a = sol::pruv_g3_t_4_Pair_2_ob_ri { first: Some(true), second: Ok(3) };
    let r = sol::same_nested(a, a);
    println!("{:?} {:?}", r.first, r.second);
    let b = sol::pruv_g3_t_4_Pair_2_ob_ri { first: Some(true), second: Err(3) };
    sol::same_nested(a, b);
}
