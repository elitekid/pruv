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
fn note_pairs__pruv_body(n0: i64, has: i64, pre: &[i64], keys: &[i64]) -> ::std::vec::Vec<i64> {
    let m: i64 = (keys.len() as i64);
    let p: i64 = (pre.len() as i64);
    let mut on: i64 = has;
    let mut w: i64 = 0i64;
    let mut j: i64 = 0i64;
    while (j < m) {
        if (((unsafe { *keys.get_unchecked((j) as usize) }) > 0i64) && (on == 0i64)) {
            on = 1i64;
            w = j;
        }
        j = (j + 1i64);
    }
    if (on == 0i64) {
        let none: ::std::vec::Vec<i64> = { let pruv_n: i64 = 1i64; let pruv_v: i64 = 0i64; vec![pruv_v; pruv_n as usize] };
        return none;
    }
    let mut base: i64 = n0;
    if ((p > n0) || (m == 0i64)) {
        base = p;
    }
    let mut out: ::std::vec::Vec<i64> = { let pruv_n: i64 = ((1i64 + base) + m); let pruv_v: i64 = 0i64; vec![pruv_v; pruv_n as usize] };
    { let pruv_i: i64 = 0i64; let pruv_x: i64 = 1i64; unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
    let mut i: i64 = 0i64;
    while (i < p) {
        { let pruv_i: i64 = (1i64 + i); let pruv_x: i64 = (unsafe { *pre.get_unchecked((i) as usize) }); unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
        i = (i + 1i64);
    }
    let mut k: i64 = 0i64;
    while (k < m) {
        { let pruv_i: i64 = ((1i64 + base) + k); let pruv_x: i64 = (unsafe { *keys.get_unchecked((k) as usize) }); unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
        k = (k + 1i64);
    }
    return out;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
#[inline]
pub fn note_pairs(n0: i64, has: i64, pre: &[i64], keys: &[i64]) -> ::std::vec::Vec<i64> {
    let mut pruv_budget: i64 = 1_073_741_824;
    if !(((0i128 <= (n0 as i128)) && ((n0 as i128) <= 10000000i128))) { panic!("{}", "pruv: requires violated: crate::note_pairs: ((0 <= n0) && (n0 <= 10000000))"); }
    if !((((has as i128) == 0i128) || ((has as i128) == 1i128))) { panic!("{}", "pruv: requires violated: crate::note_pairs: ((has == 0) || (has == 1))"); }
    if !(((pre.len() as i128) <= 10000000i128)) { panic!("{}", "pruv: requires violated: crate::note_pairs: (len(pre) <= 10000000)"); }
    if !((((has as i128) == 1i128) || ((pre.len() as i128) == 0i128))) { panic!("{}", "pruv: requires violated: crate::note_pairs: ((has == 1) || (len(pre) == 0))"); }
    if !(((keys.len() as i128) <= 10000000i128)) { panic!("{}", "pruv: requires violated: crate::note_pairs: (len(keys) <= 10000000)"); }
    if !({ let pruv_lo1: i128 = 0i128; let pruv_hi1: i128 = (pre.len() as i128); let mut pruv_k1: i128 = pruv_lo1; let mut pruv_r1 = true; while pruv_k1 < pruv_hi1 { pruv_budget -= 1; if pruv_budget < 0 { pruv_ud("contract iteration budget exceeded"); } let i: i128 = pruv_k1; if !(((0i128 <= pruv_cidx(pre, i)) && (pruv_cidx(pre, i) <= 1000000000i128))) { pruv_r1 = false; break; } pruv_k1 += 1; } pruv_r1 }) { panic!("{}", "pruv: requires violated: crate::note_pairs: forall i in 0..len(pre): ((0 <= pre[i]) && (pre[i] <= 1000000000))"); }
    if !({ let pruv_lo2: i128 = 0i128; let pruv_hi2: i128 = (keys.len() as i128); let mut pruv_k2: i128 = pruv_lo2; let mut pruv_r2 = true; while pruv_k2 < pruv_hi2 { pruv_budget -= 1; if pruv_budget < 0 { pruv_ud("contract iteration budget exceeded"); } let j: i128 = pruv_k2; if !(((0i128 <= pruv_cidx(keys, j)) && (pruv_cidx(keys, j) <= 1000000000i128))) { pruv_r2 = false; break; } pruv_k2 += 1; } pruv_r2 }) { panic!("{}", "pruv: requires violated: crate::note_pairs: forall j in 0..len(keys): ((0 <= keys[j]) && (keys[j] <= 1000000000))"); }
    note_pairs__pruv_body(n0, has, pre, keys)
}

