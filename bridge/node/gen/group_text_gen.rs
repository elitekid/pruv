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
fn pruv_m_f_1_5_is_ws__pruv_body(s: &str, i: i64) -> bool {
    let b: i64 = ((unsafe { *s.as_bytes().get_unchecked((i) as usize) }) as i64);
    if (((9i64 <= b) && (b <= 13i64)) || (b == 32i64)) {
        return true;
    }
    if ((b == 194i64) && ((i + 1i64) < (s.len() as i64))) {
        return (((unsafe { *s.as_bytes().get_unchecked(((i + 1i64)) as usize) }) as i64) == 160i64);
    }
    if ((i + 2i64) >= (s.len() as i64)) {
        return false;
    }
    let c: i64 = ((unsafe { *s.as_bytes().get_unchecked(((i + 1i64)) as usize) }) as i64);
    let d: i64 = ((unsafe { *s.as_bytes().get_unchecked(((i + 2i64)) as usize) }) as i64);
    if (b == 225i64) {
        return ((c == 154i64) && (d == 128i64));
    }
    if ((b == 226i64) && (c == 128i64)) {
        return (((((128i64 <= d) && (d <= 138i64)) || (d == 168i64)) || (d == 169i64)) || (d == 175i64));
    }
    if ((b == 226i64) && (c == 129i64)) {
        return (d == 159i64);
    }
    if (b == 227i64) {
        return ((c == 128i64) && (d == 128i64));
    }
    if (b == 239i64) {
        return ((c == 187i64) && (d == 191i64));
    }
    return false;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_5_width__pruv_body(s: &str, i: i64) -> i64 {
    if (((unsafe { *s.as_bytes().get_unchecked((i) as usize) }) as i64) >= 240i64) {
        return 2i64;
    }
    return 1i64;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_4_next__pruv_body(s: &str, i: i64) -> i64 {
    let mut j: i64 = (i + 1i64);
    while ((j < (s.len() as i64)) && (!pruv_str_boundary(s, j))) {
        j = (j + 1i64);
    }
    return j;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_4_prev__pruv_body(s: &str, j: i64) -> i64 {
    let mut i: i64 = (j - 1i64);
    while ((i > 0i64) && (!pruv_str_boundary(s, i))) {
        i = (i - 1i64);
    }
    return i;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_10_trim_start__pruv_body(s: &str, a: i64, b: i64) -> i64 {
    let mut i: i64 = a;
    while ((i < b) && pruv_m_f_1_5_is_ws__pruv_body(s, i)) {
        i = pruv_m_f_1_4_next__pruv_body(s, i);
    }
    return i;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_8_trim_end__pruv_body(s: &str, a: i64, b: i64) -> i64 {
    let mut j: i64 = b;
    let mut go: i64 = 1i64;
    while ((go == 1i64) && (j > a)) {
        let p: i64 = pruv_m_f_1_4_prev__pruv_body(s, j);
        if pruv_m_f_1_5_is_ws__pruv_body(s, p) {
            j = p;
        } else {
            go = 0i64;
        }
    }
    return j;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_5_units__pruv_body(s: &str, a: i64, b: i64) -> i64 {
    let mut i: i64 = a;
    let mut u: i64 = 0i64;
    while (i < b) {
        u = (u + pruv_m_f_1_5_width__pruv_body(s, i));
        i = pruv_m_f_1_4_next__pruv_body(s, i);
    }
    return u;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_3_cut__pruv_body(s: &str, a: i64, b: i64, max: i64) -> i64 {
    let mut i: i64 = a;
    let mut u: i64 = 0i64;
    let mut nl: i64 = (-1i64);
    let mut nlu: i64 = 0i64;
    let mut sp: i64 = (-1i64);
    let mut spu: i64 = 0i64;
    let mut at: i64 = b;
    let mut go: i64 = 1i64;
    while ((go == 1i64) && (i < b)) {
        let c: i64 = ((unsafe { *s.as_bytes().get_unchecked((i) as usize) }) as i64);
        if ((i > a) && (c == 10i64)) {
            nl = i;
            nlu = u;
        }
        if ((i > a) && (c == 32i64)) {
            sp = i;
            spu = u;
        }
        let w: i64 = pruv_m_f_1_5_width__pruv_body(s, i);
        if ((u + w) > max) {
            at = i;
            go = 0i64;
        } else {
            u = (u + w);
            i = pruv_m_f_1_4_next__pruv_body(s, i);
        }
    }
    if ((nl >= 0i64) && ((2i64 * nlu) >= max)) {
        return nl;
    }
    if ((sp >= 0i64) && ((2i64 * spu) >= max)) {
        return sp;
    }
    return at;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_10_split_item__pruv_body(s: &str, a0: i64, b0: i64, max: i64, j: i64, out: &mut [i64], k0: i64) -> i64 {
    let b: i64 = pruv_m_f_1_8_trim_end__pruv_body(s, a0, b0);
    let mut a: i64 = pruv_m_f_1_10_trim_start__pruv_body(s, a0, b);
    let mut rest: i64 = pruv_m_f_1_5_units__pruv_body(s, a, b);
    let mut k: i64 = k0;
    while ((a < b) && (rest > max)) {
        let c: i64 = pruv_m_f_1_3_cut__pruv_body(s, a, b, max);
        let e: i64 = pruv_m_f_1_8_trim_end__pruv_body(s, a, c);
        if (((4i64 * k) + 3i64) < (out.len() as i64)) {
            { let pruv_i: i64 = (4i64 * k); let pruv_x: i64 = j; unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
            { let pruv_i: i64 = ((4i64 * k) + 1i64); let pruv_x: i64 = j; unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
            { let pruv_i: i64 = ((4i64 * k) + 2i64); let pruv_x: i64 = a; unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
            { let pruv_i: i64 = ((4i64 * k) + 3i64); let pruv_x: i64 = e; unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
        }
        k = (k + 1i64);
        let n: i64 = pruv_m_f_1_10_trim_start__pruv_body(s, c, b);
        rest = (rest - pruv_m_f_1_5_units__pruv_body(s, a, n));
        if (rest < 0i64) {
            rest = 0i64;
        }
        a = n;
    }
    if (a < b) {
        if (((4i64 * k) + 3i64) < (out.len() as i64)) {
            { let pruv_i: i64 = (4i64 * k); let pruv_x: i64 = j; unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
            { let pruv_i: i64 = ((4i64 * k) + 1i64); let pruv_x: i64 = j; unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
            { let pruv_i: i64 = ((4i64 * k) + 2i64); let pruv_x: i64 = a; unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
            { let pruv_i: i64 = ((4i64 * k) + 3i64); let pruv_x: i64 = b; unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
        }
        k = (k + 1i64);
    }
    return k;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_5_flush__pruv_body(s: &str, gs: i64, ge: i64, f: i64, t: i64, out: &mut [i64], k: i64) -> i64 {
    let b: i64 = pruv_m_f_1_8_trim_end__pruv_body(s, gs, ge);
    let a: i64 = pruv_m_f_1_10_trim_start__pruv_body(s, gs, b);
    if (a < b) {
        if (((4i64 * k) + 3i64) < (out.len() as i64)) {
            { let pruv_i: i64 = (4i64 * k); let pruv_x: i64 = f; unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
            { let pruv_i: i64 = ((4i64 * k) + 1i64); let pruv_x: i64 = t; unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
            { let pruv_i: i64 = ((4i64 * k) + 2i64); let pruv_x: i64 = a; unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
            { let pruv_i: i64 = ((4i64 * k) + 3i64); let pruv_x: i64 = b; unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
        }
        return (k + 1i64);
    }
    return k;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_10_group_into__pruv_body(s: &str, ends: &[i64], max: i64, out: &mut [i64]) -> i64 {
    let mut k: i64 = 0i64;
    let mut st: i64 = 0i64;
    let mut active: i64 = 0i64;
    let mut gs: i64 = 0i64;
    let mut ge: i64 = 0i64;
    let mut f: i64 = 0i64;
    let mut t: i64 = 0i64;
    let mut size: i64 = 0i64;
    let mut j: i64 = 0i64;
    while (j < (ends.len() as i64)) {
        let e: i64 = (unsafe { *ends.get_unchecked((j) as usize) });
        if ((e < st) || (e > (s.len() as i64))) {
            return (-1i64);
        }
        if ((!pruv_str_boundary(s, st)) || (!pruv_str_boundary(s, e))) {
            return (-1i64);
        }
        let u: i64 = pruv_m_f_1_5_units__pruv_body(s, st, e);
        if (u > max) {
            if (active == 1i64) {
                k = pruv_m_f_1_5_flush__pruv_body(s, gs, ge, f, t, &mut *out, k);
            }
            active = 0i64;
            size = 0i64;
            k = pruv_m_f_1_10_split_item__pruv_body(s, st, e, max, j, &mut *out, k);
        } else {
            if ((active == 1i64) && (((size + u) + 1i64) > max)) {
                k = pruv_m_f_1_5_flush__pruv_body(s, gs, ge, f, t, &mut *out, k);
                active = 0i64;
                size = 0i64;
            }
            if (active == 0i64) {
                gs = st;
                f = j;
                active = 1i64;
            }
            t = j;
            ge = e;
            size = ((size + u) + 1i64);
        }
        st = (e + 1i64);
        j = (j + 1i64);
    }
    if (active == 1i64) {
        k = pruv_m_f_1_5_flush__pruv_body(s, gs, ge, f, t, &mut *out, k);
    }
    return k;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn group_bounds__pruv_body(s: &str, ends: &[i64], max: i64) -> ::std::vec::Vec<i64> {
    let mut none: ::std::vec::Vec<i64> = { let pruv_n: i64 = 0i64; let pruv_v: i64 = 0i64; vec![pruv_v; pruv_n as usize] };
    let k: i64 = pruv_m_f_1_10_group_into__pruv_body(s, ends, max, &mut none);
    if (k < 0i64) {
        let bad: ::std::vec::Vec<i64> = { let pruv_n: i64 = 1i64; let pruv_v: i64 = (-1i64); vec![pruv_v; pruv_n as usize] };
        return bad;
    }
    let mut out: ::std::vec::Vec<i64> = { let pruv_n: i64 = (4i64 * k); let pruv_v: i64 = 0i64; vec![pruv_v; pruv_n as usize] };
    let filled: i64 = pruv_m_f_1_10_group_into__pruv_body(s, ends, max, &mut out);
    return out;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
#[inline]
pub fn group_bounds(s: &str, ends: &[i64], max: i64) -> ::std::vec::Vec<i64> {
    let mut pruv_budget: i64 = 1_073_741_824;
    if !(((2i128 <= (max as i128)) && ((max as i128) <= 1099511627776i128))) { panic!("{}", "pruv: requires violated: crate::group_bounds: ((2 <= max) && (max <= 1099511627776))"); }
    if !(((s.len() as i128) <= 250000000000i128)) { panic!("{}", "pruv: requires violated: crate::group_bounds: (len(s) <= 250000000000)"); }
    group_bounds__pruv_body(s, ends, max)
}

