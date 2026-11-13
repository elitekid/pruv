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
fn under__pruv_body(path: &str, root: &str, sep: i64) -> bool {
    let lr: i64 = (root.len() as i64);
    if (lr > (path.len() as i64)) {
        return false;
    }
    let mut i: i64 = 0i64;
    while (i < lr) {
        if (((unsafe { *path.as_bytes().get_unchecked((i) as usize) }) as i64) != ((unsafe { *root.as_bytes().get_unchecked((i) as usize) }) as i64)) {
            return false;
        }
        i = (i + 1i64);
    }
    if (lr == (path.len() as i64)) {
        return true;
    }
    if ((lr > 0i64) && (((unsafe { *root.as_bytes().get_unchecked(((lr - 1i64)) as usize) }) as i64) == sep)) {
        return true;
    }
    return (((unsafe { *path.as_bytes().get_unchecked((lr) as usize) }) as i64) == sep);
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
#[inline]
pub fn under(path: &str, root: &str, sep: i64) -> bool {
    let mut pruv_budget: i64 = 1_073_741_824;
    if !((((((path.len() as i128) <= 1000000000000i128) && ((root.len() as i128) <= 1000000000000i128)) && (0i128 <= (sep as i128))) && ((sep as i128) <= 127i128))) { panic!("{}", "pruv: requires violated: crate::under: ((((len(path) <= 1000000000000) && (len(root) <= 1000000000000)) && (0 <= sep)) && (sep <= 127))"); }
    under__pruv_body(path, root, sep)
}

