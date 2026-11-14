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
fn text_lines__pruv_body(s: &str, chars: i64) -> ::std::vec::Vec<i64> {
    let n: i64 = (s.len() as i64);
    let mut i: i64 = 0i64;
    let mut a: i64 = 0i64;
    let mut lu: i64 = 0i64;
    let mut count: i64 = 0i64;
    let mut keep: i64 = (-1i64);
    let mut used: i64 = 0i64;
    while (i < n) {
        let x: i64 = ((unsafe { *s.as_bytes().get_unchecked((i) as usize) }) as i64);
        if (x == 10i64) {
            let mut w: i64 = lu;
            if ((i > a) && (((unsafe { *s.as_bytes().get_unchecked(((i - 1i64)) as usize) }) as i64) == 13i64)) {
                w = (w - 1i64);
            }
            if (keep == (-1i64)) {
                used = ((used + w) + 1i64);
                if (used > chars) {
                    keep = count;
                }
            }
            count = (count + 1i64);
            a = (i + 1i64);
            lu = 0i64;
        } else {
            if ((x < 128i64) || ((192i64 <= x) && (x < 240i64))) {
                lu = (lu + 1i64);
            } else {
                if (x >= 240i64) {
                    lu = (lu + 2i64);
                }
            }
        }
        i = (i + 1i64);
    }
    let mut b: i64 = n;
    let mut w: i64 = lu;
    if ((n > a) && (((unsafe { *s.as_bytes().get_unchecked(((n - 1i64)) as usize) }) as i64) == 13i64)) {
        b = (n - 1i64);
        w = (lu - 1i64);
    }
    if (b > a) {
        if (keep == (-1i64)) {
            used = ((used + w) + 1i64);
            if (used > chars) {
                keep = count;
            }
        }
        count = (count + 1i64);
    }
    if (keep == (-1i64)) {
        keep = count;
    }
    let mut out: ::std::vec::Vec<i64> = { let pruv_n: i64 = 2i64; let pruv_v: i64 = 0i64; vec![pruv_v; pruv_n as usize] };
    { let pruv_i: i64 = 0i64; let pruv_x: i64 = count; unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
    { let pruv_i: i64 = 1i64; let pruv_x: i64 = keep; unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
    return out;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
#[inline]
pub fn text_lines(s: &str, chars: i64) -> ::std::vec::Vec<i64> {
    let mut pruv_budget: i64 = 1_073_741_824;
    if !(((s.len() as i128) <= 500000000000i128)) { panic!("{}", "pruv: requires violated: crate::text_lines: (len(s) <= 500000000000)"); }
    if !((((-1000000000000000i128) <= (chars as i128)) && ((chars as i128) <= 1000000000000000i128))) { panic!("{}", "pruv: requires violated: crate::text_lines: ((-1000000000000000 <= chars) && (chars <= 1000000000000000))"); }
    text_lines__pruv_body(s, chars)
}

