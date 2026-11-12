use sol::pruv_m_t_2_1_a_5_Point as PointA;
use sol::pruv_m_t_2_1_b_5_Point as PointB;

fn main() {
    println!("{}", sol::sum_a(PointA { x: 3, y: 4 }));
    println!("{}", sol::sum_b(PointB { on: true, p: 1, q: 2, r: 3 }));
    println!("{}", sol::sum_b(PointB { on: false, p: 1, q: 2, r: 3 }));
    println!("{}", sol::mix(5));
}
