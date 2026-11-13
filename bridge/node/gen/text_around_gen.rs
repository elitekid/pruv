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
fn pruv_m_f_1_9_whole_end__pruv_body(b: &[u8], s: i64, e: i64) -> i64 {
    let mut back: i64 = 0i64;
    let mut stop: i64 = 0i64;
    let mut k: i64 = 0i64;
    while (k < 4i64) {
        if ((stop == 0i64) && (((e - 1i64) - k) >= s)) {
            let x: i64 = ((unsafe { *b.get_unchecked((((e - 1i64) - k)) as usize) }) as i64);
            if ((x >= 128i64) && (x < 192i64)) {
                back = (k + 1i64);
            } else {
                stop = 1i64;
            }
        } else {
            stop = 1i64;
        }
        k = (k + 1i64);
    }
    let lead_at: i64 = ((e - 1i64) - back);
    if (lead_at >= s) {
        let lead: i64 = ((unsafe { *b.get_unchecked((lead_at) as usize) }) as i64);
        if (lead >= 192i64) {
            let mut need: i64 = 2i64;
            if (lead >= 224i64) {
                need = 3i64;
            }
            if (lead >= 240i64) {
                need = 4i64;
            }
            if ((back + 1i64) < need) {
                return lead_at;
            }
        }
    }
    return e;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_13_first_newline__pruv_body(b: &[u8], s: i64, e: i64) -> i64 {
    let mut i: i64 = s;
    while (i < e) {
        let x: i64 = ((unsafe { *b.get_unchecked((i) as usize) }) as i64);
        if (x == 10i64) {
            return i;
        }
        i = (i + 1i64);
    }
    return (-1i64);
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_12_last_newline__pruv_body(b: &[u8], s: i64, e: i64) -> i64 {
    let mut i: i64 = e;
    while (i > s) {
        let x: i64 = ((unsafe { *b.get_unchecked(((i - 1i64)) as usize) }) as i64);
        if (x == 10i64) {
            return (i - 1i64);
        }
        i = (i - 1i64);
    }
    return (-1i64);
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_14_count_newlines__pruv_body(b: &[u8], s: i64, e: i64) -> i64 {
    let mut c: i64 = 0i64;
    let mut i: i64 = s;
    while (i < e) {
        let x: i64 = ((unsafe { *b.get_unchecked((i) as usize) }) as i64);
        if (x == 10i64) {
            c = (c + 1i64);
        }
        i = (i + 1i64);
    }
    return c;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_13_after_newline__pruv_body(b: &[u8], k: i64) -> i64 {
    let n: i64 = (b.len() as i64);
    let mut c: i64 = 0i64;
    let mut i: i64 = 0i64;
    while (i < n) {
        let x: i64 = ((unsafe { *b.get_unchecked((i) as usize) }) as i64);
        if (x == 10i64) {
            c = (c + 1i64);
            if (c == k) {
                return (i + 1i64);
            }
        }
        i = (i + 1i64);
    }
    return (-1i64);
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn around_plan__pruv_body(buf: &[u8], target: i64, before: i64, after: i64, max_bytes: i64) -> ::std::vec::Vec<i64> {
    let n: i64 = (buf.len() as i64);
    let mut from: i64 = (target - before);
    if (from < 1i64) {
        from = 1i64;
    }
    let to: i64 = (target + after);
    let newlines: i64 = pruv_m_f_1_14_count_newlines__pruv_body(buf, 0i64, n);
    let mut last: i64 = 0i64;
    if (n > 0i64) {
        last = ((unsafe { *buf.get_unchecked(((n - 1i64)) as usize) }) as i64);
    }
    let mut total: i64 = 0i64;
    if (n > 0i64) {
        total = (newlines + 1i64);
        if (last == 10i64) {
            total = newlines;
        }
    }
    let mut start_offset: i64 = 0i64;
    if (from > 1i64) {
        start_offset = pruv_m_f_1_13_after_newline__pruv_body(buf, (from - 1i64));
    }
    if (((total == 0i64) || (from > total)) || (start_offset < 0i64)) {
        let mut past: ::std::vec::Vec<i64> = { let pruv_n: i64 = 2i64; let pruv_v: i64 = 0i64; vec![pruv_v; pruv_n as usize] };
        { let pruv_i: i64 = 1i64; let pruv_x: i64 = total; unsafe { *past.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
        return past;
    }
    let mut shown: i64 = target;
    if (total < shown) {
        shown = total;
    }
    let mut target_start: i64 = 0i64;
    if (target > 1i64) {
        target_start = pruv_m_f_1_13_after_newline__pruv_body(buf, (target - 1i64));
    }
    let mut target_end: i64 = pruv_m_f_1_13_after_newline__pruv_body(buf, target);
    if ((target_start < 0i64) || (target > total)) {
        let lastnl: i64 = pruv_m_f_1_12_last_newline__pruv_body(buf, 0i64, n);
        target_start = (lastnl + 1i64);
        if ((last == 10i64) && (lastnl >= 0i64)) {
            target_start = (pruv_m_f_1_12_last_newline__pruv_body(buf, 0i64, lastnl) + 1i64);
        }
    }
    if ((target_end < 0i64) || (target > total)) {
        target_end = n;
    }
    let mut end: i64 = pruv_m_f_1_13_after_newline__pruv_body(buf, to);
    if (end < 0i64) {
        end = n;
    }
    if ((start_offset > target_start) || (target_start > target_end)) {
        let odd: ::std::vec::Vec<i64> = { let pruv_n: i64 = 1i64; let pruv_v: i64 = (-2i64); vec![pruv_v; pruv_n as usize] };
        return odd;
    }
    return pruv_m_f_1_6_window__pruv_body(buf, start_offset, target_start, target_end, end, max_bytes, total, shown);
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
#[inline]
pub fn around_plan(buf: &[u8], target: i64, before: i64, after: i64, max_bytes: i64) -> ::std::vec::Vec<i64> {
    let mut pruv_budget: i64 = 1_073_741_824;
    if !(((buf.len() as i128) <= 1099511627776i128)) { panic!("{}", "pruv: requires violated: crate::around_plan: (len(buf) <= 1099511627776)"); }
    if !(((1i128 <= (target as i128)) && ((target as i128) <= 1000000000000000i128))) { panic!("{}", "pruv: requires violated: crate::around_plan: ((1 <= target) && (target <= 1000000000000000))"); }
    if !(((0i128 <= (before as i128)) && ((before as i128) <= 1000000000000000i128))) { panic!("{}", "pruv: requires violated: crate::around_plan: ((0 <= before) && (before <= 1000000000000000))"); }
    if !(((0i128 <= (after as i128)) && ((after as i128) <= 1000000000000000i128))) { panic!("{}", "pruv: requires violated: crate::around_plan: ((0 <= after) && (after <= 1000000000000000))"); }
    if !(((0i128 <= (max_bytes as i128)) && ((max_bytes as i128) <= 1099511627776i128))) { panic!("{}", "pruv: requires violated: crate::around_plan: ((0 <= max_bytes) && (max_bytes <= 1099511627776))"); }
    around_plan__pruv_body(buf, target, before, after, max_bytes)
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_6_window__pruv_body(buf: &[u8], start_offset: i64, target_start: i64, target_end: i64, end: i64, max_bytes: i64, total: i64, shown: i64) -> ::std::vec::Vec<i64> {
    let target_bytes: i64 = (target_end - target_start);
    let mut cut: i64 = 0i64;
    let mut target_len: i64 = target_bytes;
    if (target_bytes > max_bytes) {
        cut = 1i64;
        target_len = max_bytes;
    }
    let before_need: i64 = (target_start - start_offset);
    let mut after_need: i64 = (end - target_end);
    if (after_need < 0i64) {
        after_need = 0i64;
    }
    let budgets: ::std::vec::Vec<i64> = pruv_m_f_1_12_split_budget__pruv_body((max_bytes - target_len), before_need, after_need);
    let before_len: i64 = (unsafe { *budgets.get_unchecked((0i64) as usize) });
    let after_len: i64 = (unsafe { *budgets.get_unchecked((1i64) as usize) });
    let mut truncated: i64 = cut;
    let mut b_start: i64 = (target_start - before_len);
    if (before_len < before_need) {
        let edge: i64 = ((unsafe { *buf.get_unchecked(((b_start - 1i64)) as usize) }) as i64);
        if (edge != 10i64) {
            let found: i64 = pruv_m_f_1_13_first_newline__pruv_body(buf, b_start, target_start);
            if (found >= 0i64) {
                b_start = (found + 1i64);
            } else {
                b_start = target_start;
            }
        }
        truncated = 1i64;
    }
    let mut a_end: i64 = (target_end + after_len);
    if (after_len < after_need) {
        let found: i64 = pruv_m_f_1_12_last_newline__pruv_body(buf, target_end, a_end);
        if (found >= 0i64) {
            a_end = (found + 1i64);
        } else {
            a_end = target_end;
        }
        truncated = 1i64;
    }
    let mut t_end: i64 = (target_start + target_len);
    if (cut == 1i64) {
        t_end = pruv_m_f_1_9_whole_end__pruv_body(buf, target_start, t_end);
    }
    let lines: i64 = pruv_m_f_1_14_count_newlines__pruv_body(buf, b_start, target_start);
    let mut out: ::std::vec::Vec<i64> = { let pruv_n: i64 = 12i64; let pruv_v: i64 = 0i64; vec![pruv_v; pruv_n as usize] };
    { let pruv_i: i64 = 0i64; let pruv_x: i64 = 1i64; unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
    { let pruv_i: i64 = 1i64; let pruv_x: i64 = total; unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
    { let pruv_i: i64 = 2i64; let pruv_x: i64 = shown; unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
    { let pruv_i: i64 = 3i64; let pruv_x: i64 = b_start; unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
    { let pruv_i: i64 = 4i64; let pruv_x: i64 = target_start; unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
    { let pruv_i: i64 = 5i64; let pruv_x: i64 = target_start; unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
    { let pruv_i: i64 = 6i64; let pruv_x: i64 = t_end; unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
    { let pruv_i: i64 = 7i64; let pruv_x: i64 = target_end; unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
    { let pruv_i: i64 = 8i64; let pruv_x: i64 = a_end; unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
    { let pruv_i: i64 = 9i64; let pruv_x: i64 = lines; unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
    { let pruv_i: i64 = 10i64; let pruv_x: i64 = truncated; unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
    { let pruv_i: i64 = 11i64; let pruv_x: i64 = cut; unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
    return out;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_12_split_budget__pruv_body(rest: i64, before_need: i64, after_need: i64) -> ::std::vec::Vec<i64> {
    let mut before_budget: i64 = (rest / 2i64);
    let mut after_budget: i64 = (rest - before_budget);
    if (before_need < before_budget) {
        after_budget = ((after_budget + before_budget) - before_need);
    } else {
        if (after_need < after_budget) {
            before_budget = ((before_budget + after_budget) - after_need);
        }
    }
    let mut out: ::std::vec::Vec<i64> = { let pruv_n: i64 = 2i64; let pruv_v: i64 = 0i64; vec![pruv_v; pruv_n as usize] };
    { let pruv_i: i64 = 0i64; let pruv_x: i64 = before_need; unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
    if (before_budget < before_need) {
        { let pruv_i: i64 = 0i64; let pruv_x: i64 = before_budget; unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
    }
    { let pruv_i: i64 = 1i64; let pruv_x: i64 = after_need; unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
    if (after_budget < after_need) {
        { let pruv_i: i64 = 1i64; let pruv_x: i64 = after_budget; unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
    }
    return out;
}

