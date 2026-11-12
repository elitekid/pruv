fn main() {
 for pick in 0..3 {
  let actual = sol::run(pick);
  assert_eq!(actual, sol::sequential(pick));
  println!("{:?}", actual);
 }
}
