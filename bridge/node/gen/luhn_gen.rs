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
fn pruv_m_f_1_10_luhn_value__pruv_body(u: i64, dbl: bool) -> i64 {
    let mut v: i64 = (u - 48i64);
    if dbl {
        v = (v * 2i64);
        if (v > 9i64) {
            v = (v - 9i64);
        }
    }
    return v;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn luhn__pruv_body(s: &str) -> bool {
    let n: i64 = (s.len() as i64);
    let mut i: i64 = 0i64;
    let mut k: i64 = 0i64;
    let mut even: i64 = 0i64;
    let mut odd: i64 = 0i64;
    while (i < n) {
        let x: i64 = ((unsafe { *s.as_bytes().get_unchecked((i) as usize) }) as i64);
        if (x < 128i64) {
            even = (even + pruv_m_f_1_10_luhn_value__pruv_body(x, ((k % 2i64) == 0i64)));
            odd = (odd + pruv_m_f_1_10_luhn_value__pruv_body(x, ((k % 2i64) == 1i64)));
            k = (k + 1i64);
            i = (i + 1i64);
        } else {
            if ((x < 224i64) && ((i + 1i64) < n)) {
                let u: i64 = (((x % 32i64) * 64i64) + (((unsafe { *s.as_bytes().get_unchecked(((i + 1i64)) as usize) }) as i64) % 64i64));
                even = (even + pruv_m_f_1_10_luhn_value__pruv_body(u, ((k % 2i64) == 0i64)));
                odd = (odd + pruv_m_f_1_10_luhn_value__pruv_body(u, ((k % 2i64) == 1i64)));
                k = (k + 1i64);
                i = (i + 2i64);
            } else {
                if ((x < 240i64) && ((i + 2i64) < n)) {
                    let u: i64 = ((((x % 16i64) * 4096i64) + ((((unsafe { *s.as_bytes().get_unchecked(((i + 1i64)) as usize) }) as i64) % 64i64) * 64i64)) + (((unsafe { *s.as_bytes().get_unchecked(((i + 2i64)) as usize) }) as i64) % 64i64));
                    even = (even + pruv_m_f_1_10_luhn_value__pruv_body(u, ((k % 2i64) == 0i64)));
                    odd = (odd + pruv_m_f_1_10_luhn_value__pruv_body(u, ((k % 2i64) == 1i64)));
                    k = (k + 1i64);
                    i = (i + 3i64);
                } else {
                    if ((x >= 240i64) && ((i + 3i64) < n)) {
                        let c: i64 = ((((((x % 8i64) * 262144i64) + ((((unsafe { *s.as_bytes().get_unchecked(((i + 1i64)) as usize) }) as i64) % 64i64) * 4096i64)) + ((((unsafe { *s.as_bytes().get_unchecked(((i + 2i64)) as usize) }) as i64) % 64i64) * 64i64)) + (((unsafe { *s.as_bytes().get_unchecked(((i + 3i64)) as usize) }) as i64) % 64i64)) - 65536i64);
                        let mut hi: i64 = 55296i64;
                        let mut lo: i64 = 56320i64;
                        if ((0i64 <= c) && (c < 1048576i64)) {
                            hi = (55296i64 + (c / 1024i64));
                            lo = (56320i64 + (c % 1024i64));
                        }
                        even = (even + pruv_m_f_1_10_luhn_value__pruv_body(hi, ((k % 2i64) == 0i64)));
                        odd = (odd + pruv_m_f_1_10_luhn_value__pruv_body(hi, ((k % 2i64) == 1i64)));
                        even = (even + pruv_m_f_1_10_luhn_value__pruv_body(lo, ((k % 2i64) == 1i64)));
                        odd = (odd + pruv_m_f_1_10_luhn_value__pruv_body(lo, ((k % 2i64) == 0i64)));
                        k = (k + 2i64);
                        i = (i + 4i64);
                    } else {
                        i = n;
                    }
                }
            }
        }
    }
    let mut sum: i64 = odd;
    if ((k % 2i64) == 0i64) {
        sum = even;
    }
    if (sum < 0i64) {
        sum = (-sum);
    }
    return ((sum % 10i64) == 0i64);
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
#[inline]
pub fn luhn(s: &str) -> bool {
    let mut pruv_budget: i64 = 1_073_741_824;
    if !(((s.len() as i128) <= 10000000000i128)) { panic!("{}", "pruv: requires violated: crate::luhn: (len(s) <= 10000000000)"); }
    luhn__pruv_body(s)
}

