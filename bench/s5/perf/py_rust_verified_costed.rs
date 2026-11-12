#[allow(dead_code)]
#[cold]
#[inline(never)]
fn pruv_ud(what: &str) -> ! { panic!("pruv: requires undefined: {}", what) }
#[allow(dead_code)]
#[inline]
fn pruv_cidx(a: &[i64], i: i128) -> i128 { if i >= 0 && i < (a.len() as i128) { a[i as usize] as i128 } else { pruv_ud("array index out of range") } }
#[allow(dead_code)]
#[inline]
fn pruv_cadd(a: i128, b: i128) -> i128 { a.checked_add(b).unwrap_or_else(|| pruv_ud("i128 overflow in +")) }
#[allow(dead_code)]
#[inline]
fn pruv_csub(a: i128, b: i128) -> i128 { a.checked_sub(b).unwrap_or_else(|| pruv_ud("i128 overflow in -")) }
#[allow(dead_code)]
#[inline]
fn pruv_cmul(a: i128, b: i128) -> i128 { a.checked_mul(b).unwrap_or_else(|| pruv_ud("i128 overflow in *")) }
#[allow(dead_code)]
#[inline]
fn pruv_cneg(a: i128) -> i128 { a.checked_neg().unwrap_or_else(|| pruv_ud("i128 overflow in unary -")) }
#[allow(dead_code)]
#[inline]
fn pruv_cdiv(a: i128, b: i128) -> i128 { if b == 0 { pruv_ud("division by zero in /") } a.checked_div_euclid(b).unwrap_or_else(|| pruv_ud("i128 overflow in /")) }
#[allow(dead_code)]
#[inline]
fn pruv_crem(a: i128, b: i128) -> i128 { if b == 0 { pruv_ud("division by zero in %") } a.checked_rem_euclid(b).unwrap_or_else(|| pruv_ud("i128 overflow in %")) }

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn step__pruv_body(x: i64) -> i64 {
    return (((x * 251i64) + 17i64) % 65521i64);
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
#[inline]
pub fn step(x: i64) -> i64 {
    let mut pruv_budget: i64 = 1_073_741_824;
    if !(((0i128 <= (x as i128)) && ((x as i128) < 65521i128))) { panic!("{}", "pruv: requires violated: step: ((0 <= x) && (x < 65521))"); }
    step__pruv_body(x)
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn mix__pruv_body(n: i64, seed: i64) -> i64 {
    let mut x: i64 = seed;
    let mut i: i64 = 0i64;
    while (i < n) {
        let mut j: i64 = 0i64;
        while (j < 32i64) {
            x = step__pruv_body(x);
            j = (j + 1i64);
        }
        i = (i + 1i64);
    }
    return x;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
#[inline]
pub fn mix(n: i64, seed: i64) -> i64 {
    let mut pruv_budget: i64 = 1_073_741_824;
    if !(((0i128 <= (n as i128)) && ((n as i128) <= 1000000i128))) { panic!("{}", "pruv: requires violated: mix: ((0 <= n) && (n <= 1000000))"); }
    if !(((0i128 <= (seed as i128)) && ((seed as i128) < 65521i128))) { panic!("{}", "pruv: requires violated: mix: ((0 <= seed) && (seed < 65521))"); }
    mix__pruv_body(n, seed)
}

