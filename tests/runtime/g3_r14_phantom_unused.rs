fn main() {
    let t = sol::tag_bool(41);
    let u = sol::to_int(t);
    assert_eq!(u, sol::pruv_g3_t_3_Tag_1_i { id: 41 });
    println!("{} {}", t.id, u.id);
}
