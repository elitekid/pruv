#[allow(dead_code)]
#[inline]
fn pruv_str_boundary(a: &str, i: i64) -> bool { i >= 0 && (i as u64) <= (a.len() as u64) && a.is_char_boundary(i as usize) }

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

#[allow(dead_code)]
#[inline]
fn pruv_cidx_str(a: &str, i: i128) -> i128 { if i >= 0 && i < (a.len() as i128) { a.as_bytes()[i as usize] as i128 } else { pruv_ud("array index out of range") } }
#[allow(dead_code)]
#[inline]
fn pruv_cboundary(a: &str, i: i128) -> bool { i >= 0 && i <= (a.len() as i128) && a.is_char_boundary(i as usize) }

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_5_alnum(x: i64) -> bool {
    return ((((48i64 <= x) && (x <= 57i64)) || ((65i64 <= x) && (x <= 90i64))) || ((97i64 <= x) && (x <= 122i64)));
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn valid_thread__pruv_body(s: &str) -> bool {
    let n: i64 = (s.len() as i64);
    if ((n < 1i64) || (n > 128i64)) {
        return false;
    }
    if (!pruv_m_f_1_5_alnum(((unsafe { *s.as_bytes().get_unchecked((0i64) as usize) }) as i64))) {
        return false;
    }
    let mut i: i64 = 1i64;
    let mut ok: bool = true;
    while (i < n) {
        let x: i64 = ((unsafe { *s.as_bytes().get_unchecked((i) as usize) }) as i64);
        if (!((pruv_m_f_1_5_alnum(x) || (x == 95i64)) || (x == 45i64))) {
            ok = false;
        }
        i = (i + 1i64);
    }
    return ok;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
#[inline]
pub fn valid_thread(s: &str) -> bool {
    let mut pruv_budget: i64 = 1_073_741_824;
    if !(((s.len() as i128) <= 100000000000i128)) { panic!("{}", "pruv: requires violated: crate::valid_thread: (len(s) <= 100000000000)"); }
    valid_thread__pruv_body(s)
}

