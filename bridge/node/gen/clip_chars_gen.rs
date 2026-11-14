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
fn pruv_m_f_1_4_next__pruv_body(s: &str, i: i64) -> i64 {
    let mut j: i64 = (i + 1i64);
    while ((j < (s.len() as i64)) && (!pruv_str_boundary(s, j))) {
        j = (j + 1i64);
    }
    return j;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn clip_chars__pruv_body(s: &str, chars: i64) -> ::std::string::String {
    let n: i64 = (s.len() as i64);
    let mut i: i64 = 0i64;
    let mut u: i64 = 0i64;
    let mut end: i64 = n;
    while (i < n) {
        let j: i64 = pruv_m_f_1_4_next__pruv_body(s, i);
        let mut w: i64 = 1i64;
        if ((j - i) == 4i64) {
            w = 2i64;
        }
        if ((u + w) > chars) {
            end = i;
            i = n;
        } else {
            u = (u + w);
            i = j;
        }
    }
    return { let pruv_s: &str = s; let pruv_lo: i64 = 0i64; let pruv_hi: i64 = end; ::std::string::String::from(unsafe { pruv_s.get_unchecked((pruv_lo as usize)..(pruv_hi as usize)) }) };
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
#[inline]
pub fn clip_chars(s: &str, chars: i64) -> ::std::string::String {
    let mut pruv_budget: i64 = 1_073_741_824;
    if !(((s.len() as i128) <= 100000000000i128)) { panic!("{}", "pruv: requires violated: crate::clip_chars: (len(s) <= 100000000000)"); }
    if !(((0i128 <= (chars as i128)) && ((chars as i128) <= 100000000000i128))) { panic!("{}", "pruv: requires violated: crate::clip_chars: ((0 <= chars) && (chars <= 100000000000))"); }
    clip_chars__pruv_body(s, chars)
}

