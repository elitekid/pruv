fn main() {
    type C = sol::pruv_g3_t_6_Choice_2_b_i;
    println!("{}", sol::left_bool(C::Left(false)));
    println!("{}", sol::left_true(C::Left(true)));
    println!("{}", sol::left_bool(C::Right(5)));
}
