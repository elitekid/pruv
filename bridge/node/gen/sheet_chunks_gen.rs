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
fn pruv_m_f_1_11_col_letters__pruv_body(col: i64) -> ::std::string::String {
    if (col == 0i64) {
        return ::std::string::String::from("");
    }
    let prefix: ::std::string::String = pruv_m_f_1_11_col_letters__pruv_body(((col - 1i64) / 26i64));
    let alphabet: ::std::string::String = ::std::string::String::from("ABCDEFGHIJKLMNOPQRSTUVWXYZ");
    let digit: i64 = ((col - 1i64) % 26i64);
    let letter: ::std::string::String = { let pruv_s: &str = &alphabet; let pruv_lo: i64 = digit; let pruv_hi: i64 = (digit + 1i64); ::std::string::String::from(unsafe { pruv_s.get_unchecked((pruv_lo as usize)..(pruv_hi as usize)) }) };
    let mut out: ::std::string::String = pruv_g6_string_new();
    out = pruv_g6_string_push_str(out, &prefix);
    out = pruv_g6_string_push_str(out, &letter);
    return pruv_g6_string_to_str(&out);
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
fn range_of__pruv_body(row1: i64, row2: i64, col1: i64, col2: i64) -> ::std::string::String {
    let mut out: ::std::string::String = pruv_g6_string_new();
    out = pruv_g6_string_push_str(out, &pruv_m_f_1_11_col_letters__pruv_body(col1));
    out = pruv_g6_string_push_str(out, &pruv_m_f_1_6_digits__pruv_body(row1));
    if ((row1 != row2) || (col1 != col2)) {
        out = pruv_g6_string_push_str(out, &::std::string::String::from(":"));
        out = pruv_g6_string_push_str(out, &pruv_m_f_1_11_col_letters__pruv_body(col2));
        out = pruv_g6_string_push_str(out, &pruv_m_f_1_6_digits__pruv_body(row2));
    }
    return pruv_g6_string_to_str(&out);
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]
#[inline]
pub fn range_of(row1: i64, row2: i64, col1: i64, col2: i64) -> ::std::string::String {
    let mut pruv_budget: i64 = 1_073_741_824;
    if !(((((1i128 <= (row1 as i128)) && ((row1 as i128) <= 1000000000000000i128)) && (1i128 <= (row2 as i128))) && ((row2 as i128) <= 1000000000000000i128))) { panic!("{}", "pruv: requires violated: crate::range_of: ((((1 <= row1) && (row1 <= 1000000000000000)) && (1 <= row2)) && (row2 <= 1000000000000000))"); }
    if !(((((1i128 <= (col1 as i128)) && ((col1 as i128) <= 1000000000000000i128)) && (1i128 <= (col2 as i128))) && ((col2 as i128) <= 1000000000000000i128))) { panic!("{}", "pruv: requires violated: crate::range_of: ((((1 <= col1) && (col1 <= 1000000000000000)) && (1 <= col2)) && (col2 <= 1000000000000000))"); }
    range_of__pruv_body(row1, row2, col1, col2)
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]
fn pruv_m_f_1_3_put__pruv_body(out: &mut [i64], k: i64, f: i64, t: i64, r1: i64, r2: i64, c1: i64, c2: i64) -> i64 {
    if (((6i64 * k) + 5i64) < (out.len() as i64)) {
        { let pruv_i: i64 = (6i64 * k); let pruv_x: i64 = f; unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
        { let pruv_i: i64 = ((6i64 * k) + 1i64); let pruv_x: i64 = t; unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
        { let pruv_i: i64 = ((6i64 * k) + 2i64); let pruv_x: i64 = r1; unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
        { let pruv_i: i64 = ((6i64 * k) + 3i64); let pruv_x: i64 = r2; unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
        { let pruv_i: i64 = ((6i64 * k) + 4i64); let pruv_x: i64 = c1; unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
        { let pruv_i: i64 = ((6i64 * k) + 5i64); let pruv_x: i64 = c2; unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
    }
    return (k + 1i64);
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]
fn pruv_m_f_1_11_chunks_into__pruv_body(rows: &[i64], col1s: &[i64], col2s: &[i64], lens: &[i64], header: i64, max: i64, out: &mut [i64]) -> i64 {
    let n: i64 = (rows.len() as i64);
    if ((((col1s.len() as i64) != n) || ((col2s.len() as i64) != n)) || ((lens.len() as i64) != n)) {
        return (-1i64);
    }
    let mut k: i64 = 0i64;
    let mut active: i64 = 0i64;
    let mut f: i64 = 0i64;
    let mut last: i64 = 0i64;
    let mut r1: i64 = 0i64;
    let mut r2: i64 = 0i64;
    let mut c1: i64 = 0i64;
    let mut c2: i64 = 0i64;
    let mut size: i64 = header;
    let mut j: i64 = 0i64;
    while (j < n) {
        let row: i64 = (unsafe { *rows.get_unchecked((j) as usize) });
        let a: i64 = (unsafe { *col1s.get_unchecked((j) as usize) });
        let b: i64 = (unsafe { *col2s.get_unchecked((j) as usize) });
        let u: i64 = (unsafe { *lens.get_unchecked((j) as usize) });
        if ((((row < 1i64) || (row > 1000000000000000i64)) || (a < 1i64)) || (a > 1000000000000000i64)) {
            return (-1i64);
        }
        if ((((b < 1i64) || (b > 1000000000000000i64)) || (u < 0i64)) || (u > 1099511627776i64)) {
            return (-1i64);
        }
        if ((active == 1i64) && ((((size + u) + 1i64) > max) || ((row - last) > 50i64))) {
            k = pruv_m_f_1_3_put__pruv_body(&mut *out, k, f, (j - 1i64), r1, r2, c1, c2);
            active = 0i64;
            size = header;
        }
        if (active == 0i64) {
            f = j;
            r1 = row;
            r2 = row;
            c1 = a;
            c2 = b;
            active = 1i64;
        } else {
            if (row < r1) {
                r1 = row;
            }
            if (row > r2) {
                r2 = row;
            }
            if (a < c1) {
                c1 = a;
            }
            if (b > c2) {
                c2 = b;
            }
        }
        last = row;
        size = ((size + u) + 1i64);
        j = (j + 1i64);
    }
    if (active == 1i64) {
        k = pruv_m_f_1_3_put__pruv_body(&mut *out, k, f, (n - 1i64), r1, r2, c1, c2);
    }
    return k;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]
fn sheet_groups__pruv_body(rows: &[i64], col1s: &[i64], col2s: &[i64], lens: &[i64], header: i64, max: i64) -> ::std::vec::Vec<i64> {
    let mut none: ::std::vec::Vec<i64> = { let pruv_n: i64 = 0i64; let pruv_v: i64 = 0i64; vec![pruv_v; pruv_n as usize] };
    let k: i64 = pruv_m_f_1_11_chunks_into__pruv_body(rows, col1s, col2s, lens, header, max, &mut none);
    if (k < 0i64) {
        let bad: ::std::vec::Vec<i64> = { let pruv_n: i64 = 1i64; let pruv_v: i64 = (-1i64); vec![pruv_v; pruv_n as usize] };
        return bad;
    }
    let mut out: ::std::vec::Vec<i64> = { let pruv_n: i64 = (6i64 * k); let pruv_v: i64 = 0i64; vec![pruv_v; pruv_n as usize] };
    let filled: i64 = pruv_m_f_1_11_chunks_into__pruv_body(rows, col1s, col2s, lens, header, max, &mut out);
    return out;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]
#[inline]
pub fn sheet_groups(rows: &[i64], col1s: &[i64], col2s: &[i64], lens: &[i64], header: i64, max: i64) -> ::std::vec::Vec<i64> {
    let mut pruv_budget: i64 = 1_073_741_824;
    if !(((0i128 <= (header as i128)) && ((header as i128) <= 1099511627776i128))) { panic!("{}", "pruv: requires violated: crate::sheet_groups: ((0 <= header) && (header <= 1099511627776))"); }
    if !(((1i128 <= (max as i128)) && ((max as i128) <= 1099511627776i128))) { panic!("{}", "pruv: requires violated: crate::sheet_groups: ((1 <= max) && (max <= 1099511627776))"); }
    if !(((rows.len() as i128) <= 100000000000i128)) { panic!("{}", "pruv: requires violated: crate::sheet_groups: (len(rows) <= 100000000000)"); }
    sheet_groups__pruv_body(rows, col1s, col2s, lens, header, max)
}

