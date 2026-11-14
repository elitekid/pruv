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
fn pruv_m_f_1_5_space__pruv_body(s: &str, i: i64) -> i64 {
    let b: i64 = ((unsafe { *s.as_bytes().get_unchecked((i) as usize) }) as i64);
    if ((b == 10i64) || (b == 13i64)) {
        return 2i64;
    }
    if ((((b == 9i64) || (b == 11i64)) || (b == 12i64)) || (b == 32i64)) {
        return 1i64;
    }
    if ((i + 1i64) >= (s.len() as i64)) {
        return 0i64;
    }
    let c: i64 = ((unsafe { *s.as_bytes().get_unchecked(((i + 1i64)) as usize) }) as i64);
    if ((b == 194i64) && (c == 160i64)) {
        return 1i64;
    }
    if ((i + 2i64) >= (s.len() as i64)) {
        return 0i64;
    }
    let d: i64 = ((unsafe { *s.as_bytes().get_unchecked(((i + 2i64)) as usize) }) as i64);
    if (((b == 225i64) && (c == 154i64)) && (d == 128i64)) {
        return 1i64;
    }
    if (((b == 226i64) && (c == 128i64)) && (((((128i64 <= d) && (d <= 138i64)) || (d == 168i64)) || (d == 169i64)) || (d == 175i64))) {
        return 1i64;
    }
    if (((b == 226i64) && (c == 129i64)) && (d == 159i64)) {
        return 1i64;
    }
    if (((b == 227i64) && (c == 128i64)) && (d == 128i64)) {
        return 1i64;
    }
    if (((b == 239i64) && (c == 187i64)) && (d == 191i64)) {
        return 1i64;
    }
    return 0i64;
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
fn pruv_m_f_1_6_letter(b: i64) -> bool {
    return (((65i64 <= b) && (b <= 90i64)) || ((97i64 <= b) && (b <= 122i64)));
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]
fn pruv_m_f_1_4_word(b: i64) -> bool {
    return ((pruv_m_f_1_6_letter(b) || ((48i64 <= b) && (b <= 57i64))) || (b == 95i64));
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]
fn pruv_m_f_1_6_scheme(b: i64) -> bool {
    return ((((pruv_m_f_1_6_letter(b) || ((48i64 <= b) && (b <= 57i64))) || (b == 43i64)) || (b == 46i64)) || (b == 45i64));
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]
fn strip_user_info__pruv_body(text: &str) -> ::std::string::String {
    let mut out: ::std::string::String = pruv_g6_string_new();
    let mut last: i64 = 0i64;
    let mut i: i64 = 0i64;
    while (i < (text.len() as i64)) {
        let b: i64 = ((unsafe { *text.as_bytes().get_unchecked((i) as usize) }) as i64);
        let mut start: bool = pruv_m_f_1_6_letter(b);
        if (start && (i > 0i64)) {
            if pruv_m_f_1_4_word(((unsafe { *text.as_bytes().get_unchecked(((i - 1i64)) as usize) }) as i64)) {
                start = false;
            }
        }
        if start {
            let mut j: i64 = pruv_m_f_1_4_next__pruv_body(text, i);
            while ((j < (text.len() as i64)) && pruv_m_f_1_6_scheme(((unsafe { *text.as_bytes().get_unchecked((j) as usize) }) as i64))) {
                j = pruv_m_f_1_4_next__pruv_body(text, j);
            }
            let mut found: i64 = (-1i64);
            if ((j < (text.len() as i64)) && (((unsafe { *text.as_bytes().get_unchecked((j) as usize) }) as i64) == 58i64)) {
                let k0: i64 = pruv_m_f_1_4_next__pruv_body(text, j);
                if ((k0 < (text.len() as i64)) && (((unsafe { *text.as_bytes().get_unchecked((k0) as usize) }) as i64) == 47i64)) {
                    let k1: i64 = pruv_m_f_1_4_next__pruv_body(text, k0);
                    if ((k1 < (text.len() as i64)) && (((unsafe { *text.as_bytes().get_unchecked((k1) as usize) }) as i64) == 47i64)) {
                        let k2: i64 = pruv_m_f_1_4_next__pruv_body(text, k1);
                        let mut k: i64 = k2;
                        while (((k < (text.len() as i64)) && (((unsafe { *text.as_bytes().get_unchecked((k) as usize) }) as i64) != 47i64)) && (pruv_m_f_1_5_space__pruv_body(text, k) == 0i64)) {
                            let e: i64 = pruv_m_f_1_4_next__pruv_body(text, k);
                            if (((unsafe { *text.as_bytes().get_unchecked((k) as usize) }) as i64) == 64i64) {
                                found = e;
                            }
                            k = e;
                        }
                        if (found != (-1i64)) {
                            let piece: ::std::string::String = { let pruv_s: &str = text; let pruv_lo: i64 = last; let pruv_hi: i64 = k2; ::std::string::String::from(unsafe { pruv_s.get_unchecked((pruv_lo as usize)..(pruv_hi as usize)) }) };
                            out = pruv_g6_string_push_str(out, &piece);
                            last = found;
                        }
                    }
                }
            }
            if (found != (-1i64)) {
                i = found;
            } else {
                i = j;
            }
        } else {
            i = pruv_m_f_1_4_next__pruv_body(text, i);
        }
    }
    let rest: ::std::string::String = { let pruv_s: &str = text; let pruv_lo: i64 = last; let pruv_hi: i64 = (text.len() as i64); ::std::string::String::from(unsafe { pruv_s.get_unchecked((pruv_lo as usize)..(pruv_hi as usize)) }) };
    out = pruv_g6_string_push_str(out, &rest);
    return pruv_g6_string_to_str(&out);
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]
#[inline]
pub fn strip_user_info(text: &str) -> ::std::string::String {
    let mut pruv_budget: i64 = 1_073_741_824;
    if !(((text.len() as i128) <= 100000000000i128)) { panic!("{}", "pruv: requires violated: crate::strip_user_info: (len(text) <= 100000000000)"); }
    strip_user_info__pruv_body(text)
}

