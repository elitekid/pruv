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
fn index_terms__pruv_body(tok: &[i64], vocab: i64) -> ::std::vec::Vec<i64> {
    let n: i64 = (tok.len() as i64);
    let mut cnt: ::std::vec::Vec<i64> = { let pruv_n: i64 = vocab; let pruv_v: i64 = 0i64; vec![pruv_v; pruv_n as usize] };
    let mut at: ::std::vec::Vec<i64> = { let pruv_n: i64 = n; let pruv_v: i64 = 0i64; vec![pruv_v; pruv_n as usize] };
    let mut m: i64 = 0i64;
    let mut i: i64 = 0i64;
    while (i < n) {
        let t: i64 = (unsafe { *tok.get_unchecked((i) as usize) });
        if ((unsafe { *cnt.get_unchecked((t) as usize) }) == 0i64) {
            { let pruv_i: i64 = m; let pruv_x: i64 = i; unsafe { *at.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
            m = (m + 1i64);
        }
        { let pruv_i: i64 = t; let pruv_x: i64 = ((unsafe { *cnt.get_unchecked((t) as usize) }) + 1i64); unsafe { *cnt.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
        i = (i + 1i64);
    }
    let mut out: ::std::vec::Vec<i64> = { let pruv_n: i64 = (1i64 + (2i64 * m)); let pruv_v: i64 = 0i64; vec![pruv_v; pruv_n as usize] };
    { let pruv_i: i64 = 0i64; let pruv_x: i64 = m; unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
    let mut p: i64 = 0i64;
    while (p < m) {
        let t: i64 = (unsafe { *tok.get_unchecked(((unsafe { *at.get_unchecked((p) as usize) })) as usize) });
        { let pruv_i: i64 = (1i64 + (2i64 * p)); let pruv_x: i64 = t; unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
        { let pruv_i: i64 = (2i64 + (2i64 * p)); let pruv_x: i64 = (unsafe { *cnt.get_unchecked((t) as usize) }); unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
        p = (p + 1i64);
    }
    return out;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
#[inline]
pub fn index_terms(tok: &[i64], vocab: i64) -> ::std::vec::Vec<i64> {
    let mut pruv_budget: i64 = 1_073_741_824;
    if !(((1i128 <= (vocab as i128)) && ((vocab as i128) <= 10000000i128))) { panic!("{}", "pruv: requires violated: crate::index_terms: ((1 <= vocab) && (vocab <= 10000000))"); }
    if !(((tok.len() as i128) <= 10000000i128)) { panic!("{}", "pruv: requires violated: crate::index_terms: (len(tok) <= 10000000)"); }
    if !({ let pruv_lo1: i128 = 0i128; let pruv_hi1: i128 = (tok.len() as i128); let mut pruv_k1: i128 = pruv_lo1; let mut pruv_r1 = true; while pruv_k1 < pruv_hi1 { pruv_budget -= 1; if pruv_budget < 0 { pruv_ud("contract iteration budget exceeded"); } let k: i128 = pruv_k1; if !(((0i128 <= pruv_cidx(tok, k)) && (pruv_cidx(tok, k) < (vocab as i128)))) { pruv_r1 = false; break; } pruv_k1 += 1; } pruv_r1 }) { panic!("{}", "pruv: requires violated: crate::index_terms: forall k in 0..len(tok): ((0 <= tok[k]) && (tok[k] < vocab))"); }
    index_terms__pruv_body(tok, vocab)
}

