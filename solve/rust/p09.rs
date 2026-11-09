pub fn dot(a: &[i64], b: &[i64]) -> Result<i64, i64> {
    if a.len() != b.len() {
        return Err(1);
    }
    Ok(a.iter().zip(b.iter()).map(|(&x, &y)| x * y).sum())
}
