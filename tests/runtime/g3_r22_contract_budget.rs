fn main() {
    println!("{}", sol::first_same_int(&vec![4i64; 10]));
    println!("{}", sol::first_same_int(&vec![9i64; 400]));
    println!("{}", sol::first_same_bool(&vec![true; 50]));
    println!("{}", sol::first_same_int(&vec![1i64; 1500]));
    println!("unreachable");
}
