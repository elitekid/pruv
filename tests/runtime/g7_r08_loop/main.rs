fn main() {
 let actual = sol::run();
 let mut sequential = vec![0; 3];
 for i in 0..3 { sequential[0] = i; }
 assert_eq!(actual, sequential);
 println!("{:?}", actual);
}
