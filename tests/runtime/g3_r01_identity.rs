fn main() {
    println!("{}", sol::id_int(-7));
    println!("{}", sol::id_bool(true));
    println!("{:?}", sol::id_opt(Some(false)));
    println!("{:?}", sol::id_opt(None));
    println!("{:?}", sol::id_res(Ok(true)));
    println!("{:?}", sol::id_res(Err(4)));
}
