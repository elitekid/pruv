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
fn pruv_cidx_u8(a: &[u8], i: i128) -> i128 { if i >= 0 && i < (a.len() as i128) { a[i as usize] as i128 } else { pruv_ud("array index out of range") } }

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn u16le__pruv_body(b: &[u8], at: i64) -> i64 {
    let x0: i64 = ((unsafe { *b.get_unchecked((at) as usize) }) as i64);
    let x1: i64 = ((unsafe { *b.get_unchecked(((at + 1i64)) as usize) }) as i64);
    return (x0 + (256i64 * x1));
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
#[inline]
pub fn u16le(b: &[u8], at: i64) -> i64 {
    let mut pruv_budget: i64 = 1_073_741_824;
    if !(((0i128 <= (at as i128)) && (pruv_cadd((at as i128), 2i128) <= (b.len() as i128)))) { panic!("{}", "pruv: requires violated: u16le: ((0 <= at) && ((at + 2) <= len(b)))"); }
    u16le__pruv_body(b, at)
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn u32le__pruv_body(b: &[u8], at: i64) -> i64 {
    let x0: i64 = ((unsafe { *b.get_unchecked((at) as usize) }) as i64);
    let x1: i64 = ((unsafe { *b.get_unchecked(((at + 1i64)) as usize) }) as i64);
    let x2: i64 = ((unsafe { *b.get_unchecked(((at + 2i64)) as usize) }) as i64);
    let x3: i64 = ((unsafe { *b.get_unchecked(((at + 3i64)) as usize) }) as i64);
    return (((x0 + (256i64 * x1)) + (65536i64 * x2)) + (16777216i64 * x3));
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
#[inline]
pub fn u32le(b: &[u8], at: i64) -> i64 {
    let mut pruv_budget: i64 = 1_073_741_824;
    if !(((0i128 <= (at as i128)) && (pruv_cadd((at as i128), 4i128) <= (b.len() as i128)))) { panic!("{}", "pruv: requires violated: u32le: ((0 <= at) && ((at + 4) <= len(b)))"); }
    u32le__pruv_body(b, at)
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn find_eocd__pruv_body(buf: &[u8]) -> i64 {
    let n: i64 = (buf.len() as i64);
    let mut min: i64 = ((n - 65535i64) - 22i64);
    if (min < 0i64) {
        min = 0i64;
    }
    let mut i: i64 = (n - 22i64);
    while (i >= min) {
        if (u32le__pruv_body(buf, i) == 101010256i64) {
            return i;
        }
        i = (i - 1i64);
    }
    return (-1i64);
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
#[inline]
pub fn find_eocd(buf: &[u8]) -> i64 {
    let mut pruv_budget: i64 = 1_073_741_824;
    if !(((buf.len() as i128) <= 1000000000000i128)) { panic!("{}", "pruv: requires violated: find_eocd: (len(buf) <= 1000000000000)"); }
    find_eocd__pruv_body(buf)
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn zip_uncompressed_total__pruv_body(buf: &[u8]) -> i64 {
    let n: i64 = (buf.len() as i64);
    let eocd: i64 = find_eocd__pruv_body(buf);
    if (eocd < 0i64) {
        return (-1i64);
    }
    let count: i64 = u16le__pruv_body(buf, (eocd + 10i64));
    let mut at: i64 = u32le__pruv_body(buf, (eocd + 16i64));
    if ((count == 65535i64) || (at == 4294967295i64)) {
        return (-2i64);
    }
    let mut total: i64 = 0i64;
    let mut k: i64 = 0i64;
    while (k < count) {
        if ((at + 46i64) > n) {
            return (-1i64);
        }
        if (u32le__pruv_body(buf, at) != 33639248i64) {
            return (-1i64);
        }
        let size: i64 = u32le__pruv_body(buf, (at + 24i64));
        if (size == 4294967295i64) {
            return (-2i64);
        }
        total = (total + size);
        at = ((((at + 46i64) + u16le__pruv_body(buf, (at + 28i64))) + u16le__pruv_body(buf, (at + 30i64))) + u16le__pruv_body(buf, (at + 32i64)));
        k = (k + 1i64);
    }
    return total;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
#[inline]
pub fn zip_uncompressed_total(buf: &[u8]) -> i64 {
    let mut pruv_budget: i64 = 1_073_741_824;
    if !(((buf.len() as i128) <= 1000000000000i128)) { panic!("{}", "pruv: requires violated: zip_uncompressed_total: (len(buf) <= 1000000000000)"); }
    zip_uncompressed_total__pruv_body(buf)
}

