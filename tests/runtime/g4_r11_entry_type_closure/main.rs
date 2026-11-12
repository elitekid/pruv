use sol::pruv_m_t_2_5_outer_5_Crate as Crate;
use sol::pruv_m_t_3_5_outer_5_inner_3_Dim as Dim;
use sol::pruv_m_t_3_5_outer_5_inner_4_Mark as Mark;

fn main() {
    let c = Crate { base: Dim { w: 3, h: 4 }, height: 5, mark: Mark::Tag(9) };
    println!("{}", sol::total_of(c));
    let d = sol::make(1, 2, 3, 4);
    println!("{} {} {}", d.base.w, d.base.h, d.height);
    println!("{}", sol::mark_of(d));
    println!("{}", sol::mark_of(Crate { base: Dim { w: 0, h: 0 }, height: 0, mark: Mark::Plain }));
}
