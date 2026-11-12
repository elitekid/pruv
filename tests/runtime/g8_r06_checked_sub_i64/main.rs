fn main() {
    for (a,b,want) in [(i64::MIN,1,None),(i64::MIN+1,1,Some(i64::MIN)),(i64::MAX,-1,None),(i64::MAX-1,-1,Some(i64::MAX)),(0,i64::MIN,None),(-1,i64::MIN,Some(i64::MAX)),(i64::MIN,i64::MIN,Some(0)),(i64::MAX,0,Some(i64::MAX))] { assert_eq!(sol::run(a,b),want); }
}
