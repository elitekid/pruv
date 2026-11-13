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
fn pruv_m_f_1_11_label_units__pruv_body(col: i64) -> i64 {
    let mut n: i64 = col;
    let mut c: i64 = 1i64;
    while (n > 0i64) {
        n = ((n - 1i64) / 26i64);
        c = (c + 1i64);
    }
    return c;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_10_head_units__pruv_body(row_no: i64) -> i64 {
    let mut c: i64 = 5i64;
    let mut p: i64 = 10i64;
    while ((p <= row_no) && (c < 20i64)) {
        p = (p * 10i64);
        c = (c + 1i64);
    }
    return c;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_8_row_into__pruv_body(s: &str, ends: &[i64], hl: i64, max: i64, out: &mut [i64]) -> i64 {
    let lim: i64 = (max - hl);
    let mut im: i64 = ((max - hl) - 12i64);
    if (im < 100i64) {
        im = 100i64;
    }
    let mut n: i64 = 0i64;
    let mut active: i64 = 0i64;
    let mut tu: i64 = 0i64;
    let mut h: i64 = 0i64;
    let mut nseg: i64 = 0i64;
    let mut col1: i64 = 0i64;
    let mut prev: i64 = 0i64;
    let mut st: i64 = 0i64;
    let mut j: i64 = 0i64;
    while (j < (ends.len() as i64)) {
        let e: i64 = (unsafe { *ends.get_unchecked((j) as usize) });
        if ((e < st) || (e > (s.len() as i64))) {
            return (-1i64);
        }
        if ((!pruv_str_boundary(s, st)) || (!pruv_str_boundary(s, e))) {
            return (-1i64);
        }
        let col: i64 = (j + 1i64);
        let lu: i64 = pruv_m_f_1_11_label_units__pruv_body(col);
        let b: i64 = pruv_m_f_1_8_trim_end__pruv_body(s, st, e);
        let mut a: i64 = pruv_m_f_1_10_trim_start__pruv_body(s, st, b);
        let mut rest: i64 = pruv_m_f_1_5_units__pruv_body(s, a, b);
        while (a < b) {
            let mut pe: i64 = b;
            let mut na: i64 = b;
            if (rest > im) {
                let c: i64 = pruv_m_f_1_3_cut__pruv_body(s, a, b, im);
                pe = pruv_m_f_1_8_trim_end__pruv_body(s, a, c);
                na = pruv_m_f_1_10_trim_start__pruv_body(s, c, b);
            }
            let pu: i64 = pruv_m_f_1_5_units__pruv_body(s, a, pe);
            let mut lab: i64 = 0i64;
            if (active == 1i64) {
                if ((prev != col) && (col != (prev + 1i64))) {
                    lab = col;
                }
            } else {
                if (col != 1i64) {
                    lab = col;
                }
            }
            let mut su: i64 = pu;
            if (lab > 0i64) {
                su = (pu + lu);
            }
            if ((active == 1i64) && (((tu + su) + 3i64) > lim)) {
                if ((h + 2i64) < (out.len() as i64)) {
                    { let pruv_i: i64 = h; let pruv_x: i64 = col1; unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
                    { let pruv_i: i64 = (h + 1i64); let pruv_x: i64 = prev; unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
                    { let pruv_i: i64 = (h + 2i64); let pruv_x: i64 = nseg; unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
                }
                active = 0i64;
                lab = 0i64;
                if (col != 1i64) {
                    lab = col;
                }
                su = pu;
                if (lab > 0i64) {
                    su = (pu + lu);
                }
            }
            if (active == 0i64) {
                h = n;
                n = (n + 3i64);
                nseg = 0i64;
                col1 = col;
                tu = su;
                active = 1i64;
            } else {
                tu = ((tu + 3i64) + su);
            }
            if ((n + 2i64) < (out.len() as i64)) {
                { let pruv_i: i64 = n; let pruv_x: i64 = lab; unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
                { let pruv_i: i64 = (n + 1i64); let pruv_x: i64 = a; unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
                { let pruv_i: i64 = (n + 2i64); let pruv_x: i64 = pe; unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
            }
            n = (n + 3i64);
            nseg = (nseg + 1i64);
            prev = col;
            rest = (rest - pruv_m_f_1_5_units__pruv_body(s, a, na));
            if (rest < 0i64) {
                rest = 0i64;
            }
            a = na;
        }
        st = (e + 1i64);
        j = (j + 1i64);
    }
    if (active == 1i64) {
        if ((h + 2i64) < (out.len() as i64)) {
            { let pruv_i: i64 = h; let pruv_x: i64 = col1; unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
            { let pruv_i: i64 = (h + 1i64); let pruv_x: i64 = prev; unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
            { let pruv_i: i64 = (h + 2i64); let pruv_x: i64 = nseg; unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
        }
    }
    return n;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn row_bounds__pruv_body(s: &str, ends: &[i64], row_no: i64, max: i64) -> ::std::vec::Vec<i64> {
    let hl: i64 = pruv_m_f_1_10_head_units__pruv_body(row_no);
    let mut none: ::std::vec::Vec<i64> = { let pruv_n: i64 = 0i64; let pruv_v: i64 = 0i64; vec![pruv_v; pruv_n as usize] };
    let k: i64 = pruv_m_f_1_8_row_into__pruv_body(s, ends, hl, max, &mut none);
    if (k < 0i64) {
        let bad: ::std::vec::Vec<i64> = { let pruv_n: i64 = 1i64; let pruv_v: i64 = (-1i64); vec![pruv_v; pruv_n as usize] };
        return bad;
    }
    let mut out: ::std::vec::Vec<i64> = { let pruv_n: i64 = k; let pruv_v: i64 = 0i64; vec![pruv_v; pruv_n as usize] };
    let filled: i64 = pruv_m_f_1_8_row_into__pruv_body(s, ends, hl, max, &mut out);
    return out;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
#[inline]
pub fn row_bounds(s: &str, ends: &[i64], row_no: i64, max: i64) -> ::std::vec::Vec<i64> {
    let mut pruv_budget: i64 = 1_073_741_824;
    if !(((1i128 <= (max as i128)) && ((max as i128) <= 1099511627776i128))) { panic!("{}", "pruv: requires violated: crate::row_bounds: ((1 <= max) && (max <= 1099511627776))"); }
    if !(((1i128 <= (row_no as i128)) && ((row_no as i128) <= 1000000000000000i128))) { panic!("{}", "pruv: requires violated: crate::row_bounds: ((1 <= row_no) && (row_no <= 1000000000000000))"); }
    if !(((s.len() as i128) <= 180000000000i128)) { panic!("{}", "pruv: requires violated: crate::row_bounds: (len(s) <= 180000000000)"); }
    row_bounds__pruv_body(s, ends, row_no, max)
}

