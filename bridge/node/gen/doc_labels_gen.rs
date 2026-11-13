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
fn pruv_m_f_1_6_digits__pruv_body(n: i64) -> ::std::string::String {
    let ten: ::std::string::String = ::std::string::String::from("0123456789");
    let mut out: ::std::string::String = pruv_g6_string_new();
    let mut p: i64 = 1000000000000000i64;
    let mut k: i64 = 0i64;
    while (k < 16i64) {
        if (p > 0i64) {
            let d: i64 = ((n / p) % 10i64);
            if ((((out.len() as i64) > 0i64) || (d != 0i64)) || (p == 1i64)) {
                out = pruv_g6_string_push_str(out, &{ let pruv_s: &str = &ten; let pruv_lo: i64 = d; let pruv_hi: i64 = (d + 1i64); ::std::string::String::from(unsafe { pruv_s.get_unchecked((pruv_lo as usize)..(pruv_hi as usize)) }) });
            }
        }
        p = (p / 10i64);
        k = (k + 1i64);
    }
    return pruv_g6_string_to_str(&out);
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]
fn pruv_m_f_1_3_num__pruv_body(n: i64) -> ::std::string::String {
    let mut out: ::std::string::String = pruv_g6_string_new();
    if (n < 0i64) {
        out = pruv_g6_string_push_str(out, &::std::string::String::from("-"));
        out = pruv_g6_string_push_str(out, &pruv_m_f_1_6_digits__pruv_body((-n)));
    } else {
        out = pruv_g6_string_push_str(out, &pruv_m_f_1_6_digits__pruv_body(n));
    }
    return pruv_g6_string_to_str(&out);
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]
fn csv_name__pruv_body(name: &str) -> ::std::string::String {
    let mut base: i64 = 0i64;
    let mut dot: i64 = (-1i64);
    let mut i: i64 = 0i64;
    while (i < (name.len() as i64)) {
        let c: i64 = ((unsafe { *name.as_bytes().get_unchecked((i) as usize) }) as i64);
        if ((c == 47i64) || (c == 92i64)) {
            base = (i + 1i64);
            dot = (-1i64);
        } else {
            if (c == 46i64) {
                dot = i;
            }
        }
        i = (i + 1i64);
    }
    let mut end: i64 = (name.len() as i64);
    if ((dot >= 0i64) && ((dot + 1i64) < (name.len() as i64))) {
        end = dot;
    }
    if (((base < end) && pruv_str_boundary(name, base)) && pruv_str_boundary(name, end)) {
        return { let pruv_s: &str = name; let pruv_lo: i64 = base; let pruv_hi: i64 = end; ::std::string::String::from(unsafe { pruv_s.get_unchecked((pruv_lo as usize)..(pruv_hi as usize)) }) };
    }
    return ::std::string::String::from("\u{d45c}");
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]
#[inline]
pub fn csv_name(name: &str) -> ::std::string::String {
    let mut pruv_budget: i64 = 1_073_741_824;
    if !(((name.len() as i128) <= 1000000000000i128)) { panic!("{}", "pruv: requires violated: crate::csv_name: (len(name) <= 1000000000000)"); }
    csv_name__pruv_body(name)
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]
fn count_list__pruv_body(pages: &[i64], counts: &[i64], max: i64) -> ::std::string::String {
    let mut out: ::std::string::String = pruv_g6_string_new();
    let mut i: i64 = 0i64;
    while ((i < (pages.len() as i64)) && (i < max)) {
        if (i > 0i64) {
            out = pruv_g6_string_push_str(out, &::std::string::String::from(", "));
        }
        out = pruv_g6_string_push_str(out, &pruv_m_f_1_3_num__pruv_body((unsafe { *pages.get_unchecked((i) as usize) })));
        out = pruv_g6_string_push_str(out, &::std::string::String::from(" ("));
        out = pruv_g6_string_push_str(out, &pruv_m_f_1_3_num__pruv_body((unsafe { *counts.get_unchecked((i) as usize) })));
        out = pruv_g6_string_push_str(out, &::std::string::String::from(")"));
        i = (i + 1i64);
    }
    return pruv_g6_string_to_str(&out);
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]
#[inline]
pub fn count_list(pages: &[i64], counts: &[i64], max: i64) -> ::std::string::String {
    let mut pruv_budget: i64 = 1_073_741_824;
    if !(((pages.len() as i128) == (counts.len() as i128))) { panic!("{}", "pruv: requires violated: crate::count_list: (len(pages) == len(counts))"); }
    if !({ let pruv_lo1: i128 = 0i128; let pruv_hi1: i128 = (pages.len() as i128); let mut pruv_k1: i128 = pruv_lo1; let mut pruv_r1 = true; while pruv_k1 < pruv_hi1 { pruv_budget -= 1; if pruv_budget < 0 { pruv_ud("contract iteration budget exceeded"); } let k: i128 = pruv_k1; if !((((-1000000000000000i128) <= pruv_cidx(pages, k)) && (pruv_cidx(pages, k) <= 1000000000000000i128))) { pruv_r1 = false; break; } pruv_k1 += 1; } pruv_r1 }) { panic!("{}", "pruv: requires violated: crate::count_list: forall k in 0..len(pages): ((-1000000000000000 <= pages[k]) && (pages[k] <= 1000000000000000))"); }
    if !({ let pruv_lo2: i128 = 0i128; let pruv_hi2: i128 = (counts.len() as i128); let mut pruv_k2: i128 = pruv_lo2; let mut pruv_r2 = true; while pruv_k2 < pruv_hi2 { pruv_budget -= 1; if pruv_budget < 0 { pruv_ud("contract iteration budget exceeded"); } let k: i128 = pruv_k2; if !((((-1000000000000000i128) <= pruv_cidx(counts, k)) && (pruv_cidx(counts, k) <= 1000000000000000i128))) { pruv_r2 = false; break; } pruv_k2 += 1; } pruv_r2 }) { panic!("{}", "pruv: requires violated: crate::count_list: forall k in 0..len(counts): ((-1000000000000000 <= counts[k]) && (counts[k] <= 1000000000000000))"); }
    if !(((0i128 <= (max as i128)) && ((max as i128) <= 1000000000i128))) { panic!("{}", "pruv: requires violated: crate::count_list: ((0 <= max) && (max <= 1000000000))"); }
    count_list__pruv_body(pages, counts, max)
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]
fn count_list_more__pruv_body(n: i64, max: i64) -> i64 {
    if (n > max) {
        return (n - max);
    }
    return 0i64;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]
#[inline]
pub fn count_list_more(n: i64, max: i64) -> i64 {
    let mut pruv_budget: i64 = 1_073_741_824;
    if !(((0i128 <= (n as i128)) && ((n as i128) <= 1000000000000i128))) { panic!("{}", "pruv: requires violated: crate::count_list_more: ((0 <= n) && (n <= 1000000000000))"); }
    if !(((0i128 <= (max as i128)) && ((max as i128) <= 1000000000i128))) { panic!("{}", "pruv: requires violated: crate::count_list_more: ((0 <= max) && (max <= 1000000000))"); }
    count_list_more__pruv_body(n, max)
}

