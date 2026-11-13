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
pub fn space(c: i64) -> bool {
    return ((c == 32i64) || ((9i64 <= c) && (c <= 13i64)));
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn start__pruv_body(s: &str) -> i64 {
    let mut i: i64 = 0i64;
    while (i < (s.len() as i64)) {
        if (!space(((unsafe { *s.as_bytes().get_unchecked((i) as usize) }) as i64))) {
            return i;
        }
        i = (i + 1i64);
    }
    return i;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
#[inline]
pub fn start(s: &str) -> i64 {
    let mut pruv_budget: i64 = 1_073_741_824;
    if !(((s.len() as i128) <= 4096i128)) { panic!("{}", "pruv: requires violated: start: (len(s) <= 4096)"); }
    start__pruv_body(s)
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn end__pruv_body(s: &str) -> i64 {
    let mut i: i64 = (s.len() as i64);
    while (i > 0i64) {
        if (!space(((unsafe { *s.as_bytes().get_unchecked(((i - 1i64)) as usize) }) as i64))) {
            return i;
        }
        i = (i - 1i64);
    }
    return i;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
#[inline]
pub fn end(s: &str) -> i64 {
    let mut pruv_budget: i64 = 1_073_741_824;
    if !(((s.len() as i128) <= 4096i128)) { panic!("{}", "pruv: requires violated: end: (len(s) <= 4096)"); }
    end__pruv_body(s)
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn digits__pruv_body(s: &str, lo: i64, hi: i64) -> i64 {
    let mut i: i64 = lo;
    while (i < hi) {
        if ((((unsafe { *s.as_bytes().get_unchecked((i) as usize) }) as i64) < 48i64) || (((unsafe { *s.as_bytes().get_unchecked((i) as usize) }) as i64) > 57i64)) {
            return i;
        }
        i = (i + 1i64);
    }
    return i;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
#[inline]
pub fn digits(s: &str, lo: i64, hi: i64) -> i64 {
    let mut pruv_budget: i64 = 1_073_741_824;
    if !(((((0i128 <= (lo as i128)) && ((lo as i128) <= (hi as i128))) && ((hi as i128) <= (s.len() as i128))) && ((s.len() as i128) <= 4096i128))) { panic!("{}", "pruv: requires violated: digits: ((((0 <= lo) && (lo <= hi)) && (hi <= len(s))) && (len(s) <= 4096))"); }
    digits__pruv_body(s, lo, hi)
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn valid__pruv_body(s: &str) -> bool {
    let mut i: i64 = start__pruv_body(s);
    let hi: i64 = end__pruv_body(s);
    if (i >= hi) {
        return false;
    }
    let mut part: i64 = 0i64;
    while (part < 3i64) {
        let j: i64 = digits__pruv_body(s, i, hi);
        if (j == i) {
            return false;
        }
        if (part == 2i64) {
            return (j == hi);
        }
        if (j == hi) {
            return false;
        }
        if (((unsafe { *s.as_bytes().get_unchecked((j) as usize) }) as i64) != 46i64) {
            return false;
        }
        i = (j + 1i64);
        part = (part + 1i64);
    }
    return false;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
#[inline]
pub fn valid(s: &str) -> bool {
    let mut pruv_budget: i64 = 1_073_741_824;
    if !(((s.len() as i128) <= 4096i128)) { panic!("{}", "pruv: requires violated: valid: (len(s) <= 4096)"); }
    valid__pruv_body(s)
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn significant__pruv_body(s: &str, lo: i64, hi: i64) -> i64 {
    let mut i: i64 = lo;
    while (i < hi) {
        if (((unsafe { *s.as_bytes().get_unchecked((i) as usize) }) as i64) != 48i64) {
            return i;
        }
        i = (i + 1i64);
    }
    return i;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
#[inline]
pub fn significant(s: &str, lo: i64, hi: i64) -> i64 {
    let mut pruv_budget: i64 = 1_073_741_824;
    if !(((((0i128 <= (lo as i128)) && ((lo as i128) <= (hi as i128))) && ((hi as i128) <= (s.len() as i128))) && ((s.len() as i128) <= 4096i128))) { panic!("{}", "pruv: requires violated: significant: ((((0 <= lo) && (lo <= hi)) && (hi <= len(s))) && (len(s) <= 4096))"); }
    significant__pruv_body(s, lo, hi)
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn version_at_least__pruv_body(a: &str, b: &str) -> bool {
    if ((!valid__pruv_body(a)) || (!valid__pruv_body(b))) {
        return false;
    }
    let mut i: i64 = start__pruv_body(a);
    let mut j: i64 = start__pruv_body(b);
    let mut part: i64 = 0i64;
    while (part < 3i64) {
        let ai: i64 = digits__pruv_body(a, i, (a.len() as i64));
        let bj: i64 = digits__pruv_body(b, j, (b.len() as i64));
        i = significant__pruv_body(a, i, ai);
        j = significant__pruv_body(b, j, bj);
        if ((ai - i) != (bj - j)) {
            return ((ai - i) > (bj - j));
        }
        while (i < ai) {
            if (((unsafe { *a.as_bytes().get_unchecked((i) as usize) }) as i64) != ((unsafe { *b.as_bytes().get_unchecked((j) as usize) }) as i64)) {
                return (((unsafe { *a.as_bytes().get_unchecked((i) as usize) }) as i64) > ((unsafe { *b.as_bytes().get_unchecked((j) as usize) }) as i64));
            }
            i = (i + 1i64);
            j = (j + 1i64);
        }
        if (i < (a.len() as i64)) {
            i = (i + 1i64);
        }
        if (j < (b.len() as i64)) {
            j = (j + 1i64);
        }
        part = (part + 1i64);
    }
    return true;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
#[inline]
pub fn version_at_least(a: &str, b: &str) -> bool {
    let mut pruv_budget: i64 = 1_073_741_824;
    if !((((a.len() as i128) <= 4096i128) && ((b.len() as i128) <= 4096i128))) { panic!("{}", "pruv: requires violated: version_at_least: ((len(a) <= 4096) && (len(b) <= 4096))"); }
    version_at_least__pruv_body(a, b)
}

