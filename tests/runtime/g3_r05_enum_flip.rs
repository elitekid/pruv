fn main() {
    let a = sol::flip_ib(sol::pruv_g3_t_6_Choice_2_i_b::Left(5));
    assert_eq!(a, sol::pruv_g3_t_6_Choice_2_b_i::Right(5));
    println!("{}", sol::tag(a));
    let b = sol::flip_ib(sol::pruv_g3_t_6_Choice_2_i_b::Right(true));
    assert_eq!(b, sol::pruv_g3_t_6_Choice_2_b_i::Left(true));
    println!("{}", sol::tag(b));
}
