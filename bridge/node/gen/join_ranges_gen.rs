#[allow(dead_code)]
#[inline]
fn pruv_str_boundary(a: &str, i: i64) -> bool { i >= 0 && (i as u64) <= (a.len() as u64) && a.is_char_boundary(i as usize) }

::std::thread_local! { static PRUV_CTX: ::std::cell::Cell<&'static str> = ::std::cell::Cell::new(""); }
#[allow(dead_code)]
struct PruvCtx;
impl ::std::ops::Drop for PruvCtx { fn drop(&mut self) { PRUV_CTX.with(|c| c.set("")); } }
#[allow(dead_code)]
fn pruv_ctx(name: &'static str) -> PruvCtx { PRUV_CTX.with(|c| c.set(name)); PruvCtx }
#[allow(dead_code)]
#[cold]
#[inline(never)]
fn pruv_ud(what: &str) -> ! {
    let c: &'static str = PRUV_CTX.with(|c| c.get());
    if c.is_empty() { panic!("pruv: requires undefined: {}", what) } else { panic!("pruv: foreign contract undefined: {}: {}", c, what) }
}
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

#[allow(dead_code)]
#[cold]
#[inline(never)]
fn pruv_g6_req(name: &str, what: &str) -> ! { panic!("pruv: foreign requires violated: {}: {}", name, what) }
#[allow(dead_code)]
#[cold]
#[inline(never)]
fn pruv_g6_ens(name: &str, what: &str) -> ! { panic!("pruv: foreign ensures violated: {}: {}", name, what) }
#[allow(dead_code)]
#[cold]
#[inline(never)]
fn pruv_g6_repr(what: &str) -> ! { panic!("pruv: invalid representation: {}", what) }
#[allow(dead_code)]
#[inline]
fn pruv_g6_charge(budget: &mut i64, n: usize) { let n: i64 = if n > (i64::MAX as usize) { i64::MAX } else { n as i64 }; *budget = budget.saturating_sub(n); if *budget < 0 { pruv_ud("budget") } }

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]
fn pruv_g6_string_new() -> ::std::string::String {
    let pruv_g = pruv_ctx("string_new");
    let pruv_r: ::std::string::String = ::std::string::String::new();
    pruv_r
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]
fn pruv_g6_string_push_str(mut s: ::std::string::String, text: &str) -> ::std::string::String {
    let pruv_g = pruv_ctx("string_push_str");
    if !((s.len() as u64) + (text.len() as u64) <= (1u64 << 40)) { pruv_g6_req("string_push_str", "len(s) + len(text) <= 2^40"); }
    s.push_str(text);
    s
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]
fn pruv_g6_string_to_str(s: &::std::string::String) -> ::std::string::String {
    let pruv_g = pruv_ctx("string_to_str");
    let pruv_r: ::std::string::String = s.clone();
    pruv_r
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]
fn pruv_m_f_1_5_width__pruv_body(s: &str, i: i64) -> i64 {
    if (((unsafe { *s.as_bytes().get_unchecked((i) as usize) }) as i64) >= 240i64) {
        return 2i64;
    }
    return 1i64;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]
fn pruv_m_f_1_4_next__pruv_body(s: &str, i: i64) -> i64 {
    let mut j: i64 = (i + 1i64);
    while ((j < (s.len() as i64)) && (!pruv_str_boundary(s, j))) {
        j = (j + 1i64);
    }
    return j;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]
fn pruv_m_f_1_5_units__pruv_body(s: &str, a: i64, b: i64) -> i64 {
    let mut i: i64 = a;
    let mut u: i64 = 0i64;
    while (i < b) {
        let w: i64 = pruv_m_f_1_5_width__pruv_body(s, i);
        let j: i64 = pruv_m_f_1_4_next__pruv_body(s, i);
        if ((j - i) > (3i64 * w)) {
            u = (u + (j - i));
        } else {
            u = (u + w);
        }
        i = j;
    }
    return u;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]
fn join_ranges__pruv_body(text: &str, ends: &[i64]) -> ::std::string::String {
    let mut full: ::std::string::String = pruv_g6_string_new();
    let mut kept: ::std::string::String = pruv_g6_string_new();
    let mut full_u: i64 = 0i64;
    let mut kept_u: i64 = 0i64;
    let mut over: bool = false;
    let mut stopped: bool = false;
    let mut st: i64 = 0i64;
    let mut i: i64 = 0i64;
    while ((i < (ends.len() as i64)) && ((!over) || (!stopped))) {
        let mut e: i64 = (unsafe { *ends.get_unchecked((i) as usize) });
        if (((e < st) || (e > (text.len() as i64))) || (!pruv_str_boundary(text, e))) {
            e = st;
        }
        let u: i64 = pruv_m_f_1_5_units__pruv_body(text, st, e);
        if (!over) {
            let mut nu: i64 = (full_u + u);
            if (i > 0i64) {
                nu = (nu + 2i64);
            }
            if (nu > 400i64) {
                over = true;
            } else {
                if (i > 0i64) {
                    full = pruv_g6_string_push_str(full, &::std::string::String::from(", "));
                }
                full = pruv_g6_string_push_str(full, &{ let pruv_s: &str = text; let pruv_lo: i64 = st; let pruv_hi: i64 = e; ::std::string::String::from(unsafe { pruv_s.get_unchecked((pruv_lo as usize)..(pruv_hi as usize)) }) });
                full_u = nu;
            }
        }
        if (!stopped) {
            let mut ku: i64 = (kept_u + u);
            if ((kept.len() as i64) > 0i64) {
                ku = (ku + 2i64);
            }
            if ((ku + 3i64) > 400i64) {
                stopped = true;
            } else {
                if ((kept.len() as i64) > 0i64) {
                    kept = pruv_g6_string_push_str(kept, &::std::string::String::from(", "));
                }
                kept = pruv_g6_string_push_str(kept, &{ let pruv_s: &str = text; let pruv_lo: i64 = st; let pruv_hi: i64 = e; ::std::string::String::from(unsafe { pruv_s.get_unchecked((pruv_lo as usize)..(pruv_hi as usize)) }) });
                kept_u = ku;
            }
        }
        st = e;
        i = (i + 1i64);
    }
    if (!over) {
        return pruv_g6_string_to_str(&full);
    }
    kept = pruv_g6_string_push_str(kept, &::std::string::String::from(", \u{2026}"));
    return pruv_g6_string_to_str(&kept);
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]
#[inline]
pub fn join_ranges(text: &str, ends: &[i64]) -> ::std::string::String {
    let mut pruv_budget: i64 = 1_073_741_824;
    if !(((text.len() as i128) <= 1000000000000i128)) { panic!("{}", "pruv: requires violated: crate::join_ranges: (len(text) <= 1000000000000)"); }
    if !({ let pruv_lo1: i128 = 0i128; let pruv_hi1: i128 = (ends.len() as i128); let mut pruv_k1: i128 = pruv_lo1; let mut pruv_r1 = true; while pruv_k1 < pruv_hi1 { pruv_budget -= 1; if pruv_budget < 0 { pruv_ud("contract iteration budget exceeded"); } let k: i128 = pruv_k1; if !((((0i128 <= pruv_cidx(ends, k)) && (pruv_cidx(ends, k) <= (text.len() as i128))) && pruv_cboundary(text, pruv_cidx(ends, k)))) { pruv_r1 = false; break; } pruv_k1 += 1; } pruv_r1 }) { panic!("{}", "pruv: requires violated: crate::join_ranges: forall k in 0..len(ends): (((0 <= ends[k]) && (ends[k] <= len(text))) && is_char_boundary(text, ends[k]))"); }
    if !({ let pruv_lo2: i128 = 0i128; let pruv_hi2: i128 = (ends.len() as i128); let mut pruv_k2: i128 = pruv_lo2; let mut pruv_r2 = true; while pruv_k2 < pruv_hi2 { pruv_budget -= 1; if pruv_budget < 0 { pruv_ud("contract iteration budget exceeded"); } let k: i128 = pruv_k2; if !(((pruv_cadd(k, 1i128) >= (ends.len() as i128)) || (pruv_cidx(ends, k) <= pruv_cidx(ends, pruv_cadd(k, 1i128))))) { pruv_r2 = false; break; } pruv_k2 += 1; } pruv_r2 }) { panic!("{}", "pruv: requires violated: crate::join_ranges: forall k in 0..len(ends): (((k + 1) >= len(ends)) || (ends[k] <= ends[(k + 1)]))"); }
    if !((((ends.len() as i128) == 0i128) || (pruv_cidx(ends, pruv_csub((ends.len() as i128), 1i128)) == (text.len() as i128)))) { panic!("{}", "pruv: requires violated: crate::join_ranges: ((len(ends) == 0) || (ends[(len(ends) - 1)] == len(text)))"); }
    join_ranges__pruv_body(text, ends)
}

