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
fn pruv_m_f_1_6_ws_len__pruv_body(s: &str, i: i64) -> i64 {
    let b: i64 = ((unsafe { *s.as_bytes().get_unchecked((i) as usize) }) as i64);
    if (((9i64 <= b) && (b <= 13i64)) || (b == 32i64)) {
        return 1i64;
    }
    if (b == 194i64) {
        if ((i + 1i64) < (s.len() as i64)) {
            if (((unsafe { *s.as_bytes().get_unchecked(((i + 1i64)) as usize) }) as i64) == 160i64) {
                return 2i64;
            }
        }
        return 0i64;
    }
    if ((i + 2i64) >= (s.len() as i64)) {
        return 0i64;
    }
    let c: i64 = ((unsafe { *s.as_bytes().get_unchecked(((i + 1i64)) as usize) }) as i64);
    let d: i64 = ((unsafe { *s.as_bytes().get_unchecked(((i + 2i64)) as usize) }) as i64);
    if (((b == 225i64) && (c == 154i64)) && (d == 128i64)) {
        return 3i64;
    }
    if ((b == 226i64) && (c == 128i64)) {
        if (((((128i64 <= d) && (d <= 138i64)) || (d == 168i64)) || (d == 169i64)) || (d == 175i64)) {
            return 3i64;
        }
    }
    if (((b == 226i64) && (c == 129i64)) && (d == 159i64)) {
        return 3i64;
    }
    if (((b == 227i64) && (c == 128i64)) && (d == 128i64)) {
        return 3i64;
    }
    if (((b == 239i64) && (c == 187i64)) && (d == 191i64)) {
        return 3i64;
    }
    return 0i64;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_5_ws_cp(c: i64) -> bool {
    if (((((9i64 <= c) && (c <= 13i64)) || (c == 32i64)) || (c == 160i64)) || (c == 5760i64)) {
        return true;
    }
    if (((((8192i64 <= c) && (c <= 8202i64)) || (c == 8232i64)) || (c == 8233i64)) || (c == 8239i64)) {
        return true;
    }
    return (((c == 8287i64) || (c == 12288i64)) || (c == 65279i64));
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_4_clen__pruv_body(s: &str, i: i64, b: i64) -> i64 {
    let x: i64 = ((unsafe { *s.as_bytes().get_unchecked((i) as usize) }) as i64);
    let mut l: i64 = 1i64;
    if (x >= 192i64) {
        l = 2i64;
    }
    if (x >= 224i64) {
        l = 3i64;
    }
    if (x >= 240i64) {
        l = 4i64;
    }
    if ((i + l) > b) {
        l = (b - i);
    }
    return l;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_5_cp_at__pruv_body(s: &str, i: i64, l: i64) -> i64 {
    let x: i64 = ((unsafe { *s.as_bytes().get_unchecked((i) as usize) }) as i64);
    if (l == 1i64) {
        return x;
    }
    let mut v: i64 = (x % 32i64);
    if (l == 3i64) {
        v = (x % 16i64);
    }
    if (l == 4i64) {
        v = (x % 8i64);
    }
    let mut k: i64 = 1i64;
    while (k < l) {
        let y: i64 = ((unsafe { *s.as_bytes().get_unchecked(((i + k)) as usize) }) as i64);
        v = (((v * 64i64) + (y % 64i64)) % 2097152i64);
        k = (k + 1i64);
    }
    return v;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_5_lower(x: i64) -> i64 {
    if ((65i64 <= x) && (x <= 90i64)) {
        return (x + 32i64);
    }
    return x;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_6_is_cls(x: i64, cls: i64) -> bool {
    let digit: bool = ((48i64 <= x) && (x <= 57i64));
    let letter: bool = (((65i64 <= x) && (x <= 90i64)) || ((97i64 <= x) && (x <= 122i64)));
    if (cls == 0i64) {
        return ((digit || ((65i64 <= x) && (x <= 70i64))) || ((97i64 <= x) && (x <= 102i64)));
    }
    if (cls == 1i64) {
        return digit;
    }
    if (cls == 2i64) {
        return letter;
    }
    if (cls == 3i64) {
        return (digit || letter);
    }
    if (cls == 4i64) {
        return (((((digit || letter) || (x == 95i64)) || (x == 58i64)) || (x == 46i64)) || (x == 45i64));
    }
    return ((letter || (x == 95i64)) || (x == 58i64));
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_7_run_cls__pruv_body(s: &str, k: i64, b: i64, cls: i64) -> i64 {
    let mut i: i64 = k;
    while ((i < b) && pruv_m_f_1_6_is_cls(((unsafe { *s.as_bytes().get_unchecked((i) as usize) }) as i64), cls)) {
        i = (i + 1i64);
    }
    return i;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_7_skip_ws__pruv_body(s: &str, k: i64, b: i64) -> i64 {
    let mut i: i64 = k;
    let mut go: i64 = 1i64;
    while ((go == 1i64) && (i < b)) {
        let l: i64 = pruv_m_f_1_6_ws_len__pruv_body(s, i);
        if (l == 0i64) {
            go = 0i64;
        } else {
            i = (i + l);
            if (i > b) {
                i = b;
            }
        }
    }
    return i;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_7_word_is__pruv_body(s: &str, a: i64, b: i64, w: &str) -> bool {
    if ((b - a) != (w.len() as i64)) {
        return false;
    }
    let mut k: i64 = 0i64;
    while (k < (w.len() as i64)) {
        let x: i64 = ((unsafe { *s.as_bytes().get_unchecked(((a + k)) as usize) }) as i64);
        let y: i64 = ((unsafe { *w.as_bytes().get_unchecked((k) as usize) }) as i64);
        if (pruv_m_f_1_5_lower(x) != y) {
            return false;
        }
        k = (k + 1i64);
    }
    return true;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_7_ent_end__pruv_body(s: &str, i: i64, b: i64) -> i64 {
    let j: i64 = (i + 1i64);
    if (j >= b) {
        return (-1i64);
    }
    if (((unsafe { *s.as_bytes().get_unchecked((j) as usize) }) as i64) == 35i64) {
        if ((j + 1i64) >= b) {
            return (-1i64);
        }
        let y: i64 = ((unsafe { *s.as_bytes().get_unchecked(((j + 1i64)) as usize) }) as i64);
        if ((y == 120i64) || (y == 88i64)) {
            let h: i64 = pruv_m_f_1_7_run_cls__pruv_body(s, (j + 2i64), b, 0i64);
            if ((h > (j + 2i64)) && (h < b)) {
                if (((unsafe { *s.as_bytes().get_unchecked((h) as usize) }) as i64) == 59i64) {
                    return (h + 1i64);
                }
            }
            return (-1i64);
        }
        let d: i64 = pruv_m_f_1_7_run_cls__pruv_body(s, (j + 1i64), b, 1i64);
        if ((d > (j + 1i64)) && (d < b)) {
            if (((unsafe { *s.as_bytes().get_unchecked((d) as usize) }) as i64) == 59i64) {
                return (d + 1i64);
            }
        }
        return (-1i64);
    }
    let l: i64 = pruv_m_f_1_7_run_cls__pruv_body(s, j, b, 2i64);
    if ((l > j) && (l < b)) {
        if (((unsafe { *s.as_bytes().get_unchecked((l) as usize) }) as i64) == 59i64) {
            return (l + 1i64);
        }
    }
    return (-1i64);
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_8_ent_code__pruv_body(s: &str, i: i64, e: i64) -> i64 {
    if (((unsafe { *s.as_bytes().get_unchecked(((i + 1i64)) as usize) }) as i64) == 35i64) {
        let mut k: i64 = (i + 2i64);
        let mut base: i64 = 10i64;
        let y: i64 = ((unsafe { *s.as_bytes().get_unchecked(((i + 2i64)) as usize) }) as i64);
        if (((y == 120i64) || (y == 88i64)) && ((i + 3i64) < e)) {
            base = 16i64;
            k = (i + 3i64);
        }
        let mut v: i64 = 0i64;
        while (k < (e - 1i64)) {
            let x: i64 = ((unsafe { *s.as_bytes().get_unchecked((k) as usize) }) as i64);
            let mut dv: i64 = 0i64;
            if ((48i64 <= x) && (x <= 57i64)) {
                dv = (x - 48i64);
            }
            if ((65i64 <= x) && (x <= 70i64)) {
                dv = (x - 55i64);
            }
            if ((97i64 <= x) && (x <= 102i64)) {
                dv = (x - 87i64);
            }
            v = ((v * base) + dv);
            if (v > 1114112i64) {
                v = 1114112i64;
            }
            k = (k + 1i64);
        }
        if ((v == 0i64) || (v > 1114111i64)) {
            return 1114112i64;
        }
        return v;
    }
    let a: i64 = (i + 1i64);
    let b: i64 = (e - 1i64);
    if pruv_m_f_1_7_word_is__pruv_body(s, a, b, &::std::string::String::from("amp")) {
        return 38i64;
    }
    if pruv_m_f_1_7_word_is__pruv_body(s, a, b, &::std::string::String::from("lt")) {
        return 60i64;
    }
    if pruv_m_f_1_7_word_is__pruv_body(s, a, b, &::std::string::String::from("gt")) {
        return 62i64;
    }
    if pruv_m_f_1_7_word_is__pruv_body(s, a, b, &::std::string::String::from("quot")) {
        return 34i64;
    }
    if pruv_m_f_1_7_word_is__pruv_body(s, a, b, &::std::string::String::from("apos")) {
        return 39i64;
    }
    if pruv_m_f_1_7_word_is__pruv_body(s, a, b, &::std::string::String::from("nbsp")) {
        return 32i64;
    }
    if pruv_m_f_1_7_word_is__pruv_body(s, a, b, &::std::string::String::from("constructor")) {
        return 1114113i64;
    }
    return (-1i64);
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_3_put__pruv_body(out: &mut [i64], p: i64, v: i64) -> i64 {
    if (p < (out.len() as i64)) {
        { let pruv_i: i64 = p; let pruv_x: i64 = v; unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
    }
    if (p < 1125899906842624i64) {
        return (p + 1i64);
    }
    return p;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_3_set(out: &mut [i64], at: i64, v: i64) {
    if ((0i64 <= at) && (at < (out.len() as i64))) {
        { let pruv_i: i64 = at; let pruv_x: i64 = v; unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
    }
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_11_decode_into__pruv_body(s: &str, a: i64, b: i64, out: &mut [i64], p: i64) -> i64 {
    let ctor: ::std::string::String = ::std::string::String::from("function Object() { [native code] }");
    let mut i: i64 = a;
    let mut q: i64 = p;
    while (i < b) {
        let mut nx: i64 = (-1i64);
        if (((unsafe { *s.as_bytes().get_unchecked((i) as usize) }) as i64) == 38i64) {
            let e: i64 = pruv_m_f_1_7_ent_end__pruv_body(s, i, b);
            if (e > i) {
                let c: i64 = pruv_m_f_1_8_ent_code__pruv_body(s, i, e);
                if (c >= 0i64) {
                    if (c == 1114113i64) {
                        let mut k: i64 = 0i64;
                        while (k < (ctor.len() as i64)) {
                            q = pruv_m_f_1_3_put__pruv_body(&mut *out, q, ((unsafe { *ctor.as_bytes().get_unchecked((k) as usize) }) as i64));
                            k = (k + 1i64);
                        }
                    } else {
                        if (c != 1114112i64) {
                            q = pruv_m_f_1_3_put__pruv_body(&mut *out, q, c);
                        }
                    }
                    nx = e;
                }
            }
        }
        if (nx < 0i64) {
            let l: i64 = pruv_m_f_1_4_clen__pruv_body(s, i, b);
            q = pruv_m_f_1_3_put__pruv_body(&mut *out, q, pruv_m_f_1_5_cp_at__pruv_body(s, i, l));
            nx = (i + l);
        }
        i = nx;
    }
    return q;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_13_decoded_blank__pruv_body(s: &str, a: i64, b: i64) -> bool {
    let mut i: i64 = a;
    while (i < b) {
        let mut nx: i64 = (-1i64);
        if (((unsafe { *s.as_bytes().get_unchecked((i) as usize) }) as i64) == 38i64) {
            let e: i64 = pruv_m_f_1_7_ent_end__pruv_body(s, i, b);
            if (e > i) {
                let c: i64 = pruv_m_f_1_8_ent_code__pruv_body(s, i, e);
                if (c == 1114113i64) {
                    return false;
                }
                if ((c >= 0i64) && (c != 1114112i64)) {
                    if (!pruv_m_f_1_5_ws_cp(c)) {
                        return false;
                    }
                }
                if (c >= 0i64) {
                    nx = e;
                }
            }
        }
        if (nx < 0i64) {
            let l: i64 = pruv_m_f_1_6_ws_len__pruv_body(s, i);
            if (l == 0i64) {
                return false;
            }
            nx = (i + l);
            if (nx > b) {
                nx = b;
            }
        }
        i = nx;
    }
    return true;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_8_text_rec__pruv_body(s: &str, a: i64, b: i64, par: i64, out: &mut [i64], p: i64) -> i64 {
    if (par == (-1i64)) {
        if pruv_m_f_1_13_decoded_blank__pruv_body(s, a, b) {
            return p;
        }
    }
    let mut q: i64 = pruv_m_f_1_3_put__pruv_body(&mut *out, p, 0i64);
    q = pruv_m_f_1_3_put__pruv_body(&mut *out, q, par);
    q = pruv_m_f_1_3_put__pruv_body(&mut *out, q, 0i64);
    let st: i64 = q;
    q = pruv_m_f_1_11_decode_into__pruv_body(s, a, b, &mut *out, q);
    pruv_m_f_1_3_set(&mut *out, (st - 1i64), (q - st));
    return q;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_10_find_angle__pruv_body(s: &str, k: i64) -> i64 {
    let mut i: i64 = k;
    while (i < (s.len() as i64)) {
        let x: i64 = ((unsafe { *s.as_bytes().get_unchecked((i) as usize) }) as i64);
        if ((x == 60i64) || (x == 62i64)) {
            return i;
        }
        i = (i + 1i64);
    }
    return (-1i64);
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_10_find_close__pruv_body(s: &str, k: i64) -> i64 {
    let mut i: i64 = k;
    while ((i + 3i64) <= (s.len() as i64)) {
        if (((((unsafe { *s.as_bytes().get_unchecked((i) as usize) }) as i64) == 45i64) && (((unsafe { *s.as_bytes().get_unchecked(((i + 1i64)) as usize) }) as i64) == 45i64)) && (((unsafe { *s.as_bytes().get_unchecked(((i + 2i64)) as usize) }) as i64) == 62i64)) {
            return i;
        }
        i = (i + 1i64);
    }
    return (-1i64);
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_10_find_quote__pruv_body(s: &str, k: i64, b: i64) -> i64 {
    let mut i: i64 = k;
    while (i < b) {
        let x: i64 = ((unsafe { *s.as_bytes().get_unchecked((i) as usize) }) as i64);
        if (x == 34i64) {
            return i;
        }
        i = (i + 1i64);
    }
    return (-1i64);
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_10_last_solid__pruv_body(s: &str, w: i64, r: i64) -> i64 {
    let mut k: i64 = w;
    let mut q: i64 = w;
    while (k < r) {
        let l: i64 = pruv_m_f_1_6_ws_len__pruv_body(s, k);
        if (l > 0i64) {
            k = (k + l);
            if (k > r) {
                k = r;
            }
        } else {
            k = (k + pruv_m_f_1_4_clen__pruv_body(s, k, r));
            q = k;
        }
    }
    return q;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_8_tag_info__pruv_body(s: &str, i: i64) -> ::std::vec::Vec<i64> {
    let n: i64 = (s.len() as i64);
    let mut r: ::std::vec::Vec<i64> = { let pruv_n: i64 = 6i64; let pruv_v: i64 = 0i64; vec![pruv_v; pruv_n as usize] };
    { let pruv_i: i64 = 0i64; let pruv_x: i64 = (-1i64); unsafe { *r.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
    let mut ns: i64 = (i + 1i64);
    let mut cl: i64 = 0i64;
    if (ns < n) {
        if (((unsafe { *s.as_bytes().get_unchecked((ns) as usize) }) as i64) == 47i64) {
            ns = (ns + 1i64);
            cl = 1i64;
        }
    }
    if (ns >= n) {
        return r;
    }
    if (!pruv_m_f_1_6_is_cls(((unsafe { *s.as_bytes().get_unchecked((ns) as usize) }) as i64), 2i64)) {
        return r;
    }
    let ne: i64 = pruv_m_f_1_7_run_cls__pruv_body(s, (ns + 1i64), n, 3i64);
    if (ne >= n) {
        return r;
    }
    let mut end: i64 = (-1i64);
    let mut q: i64 = ne;
    let mut sc: i64 = 0i64;
    if (pruv_m_f_1_6_ws_len__pruv_body(s, ne) == 0i64) {
        if (((unsafe { *s.as_bytes().get_unchecked((ne) as usize) }) as i64) == 62i64) {
            end = (ne + 1i64);
        } else {
            if ((((unsafe { *s.as_bytes().get_unchecked((ne) as usize) }) as i64) == 47i64) && ((ne + 1i64) < n)) {
                if (((unsafe { *s.as_bytes().get_unchecked(((ne + 1i64)) as usize) }) as i64) == 62i64) {
                    end = (ne + 2i64);
                    sc = 1i64;
                }
            }
        }
    } else {
        let w: i64 = pruv_m_f_1_7_skip_ws__pruv_body(s, ne, n);
        let e: i64 = pruv_m_f_1_10_find_angle__pruv_body(s, w);
        if (e >= 0i64) {
            if (((unsafe { *s.as_bytes().get_unchecked((e) as usize) }) as i64) == 62i64) {
                let mut rr: i64 = e;
                if ((e - 1i64) >= w) {
                    if (((unsafe { *s.as_bytes().get_unchecked(((e - 1i64)) as usize) }) as i64) == 47i64) {
                        rr = (e - 1i64);
                        sc = 1i64;
                    }
                }
                q = pruv_m_f_1_10_last_solid__pruv_body(s, w, rr);
                end = (e + 1i64);
            }
        }
    }
    if (end < 0i64) {
        return r;
    }
    { let pruv_i: i64 = 0i64; let pruv_x: i64 = end; unsafe { *r.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
    { let pruv_i: i64 = 1i64; let pruv_x: i64 = cl; unsafe { *r.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
    { let pruv_i: i64 = 2i64; let pruv_x: i64 = ns; unsafe { *r.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
    { let pruv_i: i64 = 3i64; let pruv_x: i64 = ne; unsafe { *r.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
    { let pruv_i: i64 = 4i64; let pruv_x: i64 = q; unsafe { *r.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
    { let pruv_i: i64 = 5i64; let pruv_x: i64 = sc; unsafe { *r.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
    return r;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_6_wanted__pruv_body(s: &str, a: i64, b: i64, which: i64) -> bool {
    if (which == 0i64) {
        return pruv_m_f_1_7_word_is__pruv_body(s, a, b, &::std::string::String::from("href"));
    }
    if (which == 1i64) {
        return pruv_m_f_1_7_word_is__pruv_body(s, a, b, &::std::string::String::from("colspan"));
    }
    return pruv_m_f_1_7_word_is__pruv_body(s, a, b, &::std::string::String::from("rowspan"));
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_9_last_attr__pruv_body(s: &str, a: i64, q: i64, which: i64) -> i64 {
    let mut k: i64 = a;
    let mut res: i64 = (-1i64);
    let mut nq: i64 = (q + 1i64);
    while (k < q) {
        let mut nx: i64 = (k + 1i64);
        if pruv_m_f_1_6_is_cls(((unsafe { *s.as_bytes().get_unchecked((k) as usize) }) as i64), 5i64) {
            let ke: i64 = pruv_m_f_1_7_run_cls__pruv_body(s, (k + 1i64), q, 4i64);
            nx = ke;
            let m: i64 = pruv_m_f_1_7_skip_ws__pruv_body(s, ke, q);
            if (m < q) {
                if (((unsafe { *s.as_bytes().get_unchecked((m) as usize) }) as i64) == 61i64) {
                    let m2: i64 = pruv_m_f_1_7_skip_ws__pruv_body(s, (m + 1i64), q);
                    if (m2 < q) {
                        if (((unsafe { *s.as_bytes().get_unchecked((m2) as usize) }) as i64) == 34i64) {
                            let vs: i64 = (m2 + 1i64);
                            if (vs < nq) {
                                let c: i64 = pruv_m_f_1_10_find_quote__pruv_body(s, vs, q);
                                if (c >= 0i64) {
                                    if pruv_m_f_1_6_wanted__pruv_body(s, k, ke, which) {
                                        res = vs;
                                    }
                                    nx = (c + 1i64);
                                } else {
                                    nq = vs;
                                }
                            }
                        }
                    }
                }
            }
        }
        k = nx;
    }
    return res;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_8_elem_rec__pruv_body(s: &str, ns: i64, ne: i64, q: i64, par: i64, out: &mut [i64], p: i64) -> i64 {
    let mut r: i64 = pruv_m_f_1_3_put__pruv_body(&mut *out, p, 1i64);
    r = pruv_m_f_1_3_put__pruv_body(&mut *out, r, par);
    r = pruv_m_f_1_3_put__pruv_body(&mut *out, r, (ne - ns));
    let mut k: i64 = ns;
    while (k < ne) {
        r = pruv_m_f_1_3_put__pruv_body(&mut *out, r, pruv_m_f_1_5_lower(((unsafe { *s.as_bytes().get_unchecked((k) as usize) }) as i64)));
        k = (k + 1i64);
    }
    let mut which: i64 = 0i64;
    while (which < 3i64) {
        let vs: i64 = pruv_m_f_1_9_last_attr__pruv_body(s, ne, q, which);
        if (vs < 0i64) {
            r = pruv_m_f_1_3_put__pruv_body(&mut *out, r, (-1i64));
        } else {
            let mut ve: i64 = pruv_m_f_1_10_find_quote__pruv_body(s, vs, q);
            if (ve < 0i64) {
                ve = vs;
            }
            r = pruv_m_f_1_3_put__pruv_body(&mut *out, r, 0i64);
            let st: i64 = r;
            r = pruv_m_f_1_11_decode_into__pruv_body(s, vs, ve, &mut *out, r);
            pruv_m_f_1_3_set(&mut *out, (st - 1i64), (r - st));
        }
        which = (which + 1i64);
    }
    return r;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_9_same_name(s: &str, a1: i64, b1: i64, a2: i64, b2: i64) -> bool {
    if ((((((a1 < 0i64) || (b1 < a1)) || (b1 > (s.len() as i64))) || (a2 < 0i64)) || (b2 < a2)) || (b2 > (s.len() as i64))) {
        return false;
    }
    if ((b1 - a1) != (b2 - a2)) {
        return false;
    }
    let mut k: i64 = 0i64;
    while (k < (b1 - a1)) {
        let x: i64 = ((unsafe { *s.as_bytes().get_unchecked(((a1 + k)) as usize) }) as i64);
        let y: i64 = ((unsafe { *s.as_bytes().get_unchecked(((a2 + k)) as usize) }) as i64);
        if (pruv_m_f_1_5_lower(x) != pruv_m_f_1_5_lower(y)) {
            return false;
        }
        k = (k + 1i64);
    }
    return true;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_8_close_to__pruv_body(s: &str, stk: &[i64], d: i64, a: i64, b: i64) -> i64 {
    let mut k: i64 = d;
    while (k > 0i64) {
        if pruv_m_f_1_9_same_name(s, (unsafe { *stk.get_unchecked((((3i64 * k) - 2i64)) as usize) }), (unsafe { *stk.get_unchecked((((3i64 * k) - 1i64)) as usize) }), a, b) {
            return (k - 1i64);
        }
        k = (k - 1i64);
    }
    return d;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_7_is_void__pruv_body(s: &str, a: i64, b: i64) -> bool {
    return ((pruv_m_f_1_7_word_is__pruv_body(s, a, b, &::std::string::String::from("br")) || pruv_m_f_1_7_word_is__pruv_body(s, a, b, &::std::string::String::from("img"))) || pruv_m_f_1_7_word_is__pruv_body(s, a, b, &::std::string::String::from("hr")));
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_10_parse_into(s: &str, out: &mut [i64], stk: &mut [i64]) -> i64 {
    let n: i64 = (s.len() as i64);
    let mut i: i64 = 0i64;
    let mut p: i64 = 0i64;
    let mut d: i64 = 0i64;
    let mut ne: i64 = 0i64;
    let mut noclose: i64 = (n + 1i64);
    while (i < n) {
        let mut par: i64 = (-1i64);
        if (d > 0i64) {
            par = (unsafe { *stk.get_unchecked((((3i64 * d) - 3i64)) as usize) });
        }
        if (((unsafe { *s.as_bytes().get_unchecked((i) as usize) }) as i64) != 60i64) {
            let mut t: i64 = (i + 1i64);
            while ((t < n) && (((unsafe { *s.as_bytes().get_unchecked((t) as usize) }) as i64) != 60i64)) {
                t = (t + 1i64);
            }
            p = pruv_m_f_1_8_text_rec__pruv_body(s, i, t, par, &mut *out, p);
            i = t;
        } else {
            let mut done: i64 = 0i64;
            if ((i + 3i64) < n) {
                if (((((unsafe { *s.as_bytes().get_unchecked(((i + 1i64)) as usize) }) as i64) == 33i64) && (((unsafe { *s.as_bytes().get_unchecked(((i + 2i64)) as usize) }) as i64) == 45i64)) && (((unsafe { *s.as_bytes().get_unchecked(((i + 3i64)) as usize) }) as i64) == 45i64)) {
                    if ((i + 4i64) < noclose) {
                        let c: i64 = pruv_m_f_1_10_find_close__pruv_body(s, (i + 4i64));
                        if (c >= 0i64) {
                            i = (c + 3i64);
                            done = 1i64;
                        } else {
                            noclose = (i + 4i64);
                        }
                    }
                }
            }
            if (done == 0i64) {
                let r: ::std::vec::Vec<i64> = pruv_m_f_1_8_tag_info__pruv_body(s, i);
                if ((unsafe { *r.get_unchecked((0i64) as usize) }) < 0i64) {
                    p = pruv_m_f_1_8_text_rec__pruv_body(s, i, (i + 1i64), par, &mut *out, p);
                    i = (i + 1i64);
                } else {
                    if ((unsafe { *r.get_unchecked((1i64) as usize) }) == 1i64) {
                        d = pruv_m_f_1_8_close_to__pruv_body(s, &*stk, d, (unsafe { *r.get_unchecked((2i64) as usize) }), (unsafe { *r.get_unchecked((3i64) as usize) }));
                    } else {
                        p = pruv_m_f_1_8_elem_rec__pruv_body(s, (unsafe { *r.get_unchecked((2i64) as usize) }), (unsafe { *r.get_unchecked((3i64) as usize) }), (unsafe { *r.get_unchecked((4i64) as usize) }), par, &mut *out, p);
                        let me: i64 = ne;
                        if (ne < 1125899906842624i64) {
                            ne = (ne + 1i64);
                        }
                        if (((unsafe { *r.get_unchecked((5i64) as usize) }) == 0i64) && (!pruv_m_f_1_7_is_void__pruv_body(s, (unsafe { *r.get_unchecked((2i64) as usize) }), (unsafe { *r.get_unchecked((3i64) as usize) })))) {
                            if (((3i64 * d) + 2i64) < (stk.len() as i64)) {
                                { let pruv_i: i64 = (3i64 * d); let pruv_x: i64 = me; unsafe { *stk.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
                                { let pruv_i: i64 = ((3i64 * d) + 1i64); let pruv_x: i64 = (unsafe { *r.get_unchecked((2i64) as usize) }); unsafe { *stk.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
                                { let pruv_i: i64 = ((3i64 * d) + 2i64); let pruv_x: i64 = (unsafe { *r.get_unchecked((3i64) as usize) }); unsafe { *stk.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
                                d = (d + 1i64);
                            }
                        }
                    }
                    i = (unsafe { *r.get_unchecked((0i64) as usize) });
                }
            }
        }
    }
    return p;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn parse_html__pruv_body(s: &str) -> ::std::vec::Vec<i64> {
    let n: i64 = (s.len() as i64);
    let mut lts: i64 = 0i64;
    let mut i: i64 = 0i64;
    while (i < n) {
        if (((unsafe { *s.as_bytes().get_unchecked((i) as usize) }) as i64) == 60i64) {
            lts = (lts + 1i64);
        }
        i = (i + 1i64);
    }
    let mut stk: ::std::vec::Vec<i64> = { let pruv_n: i64 = ((3i64 * lts) + 3i64); let pruv_v: i64 = 0i64; vec![pruv_v; pruv_n as usize] };
    let mut none: ::std::vec::Vec<i64> = { let pruv_n: i64 = 0i64; let pruv_v: i64 = 0i64; vec![pruv_v; pruv_n as usize] };
    let k: i64 = pruv_m_f_1_10_parse_into(s, &mut none, &mut stk);
    if (k > 1099511627776i64) {
        let bad: ::std::vec::Vec<i64> = { let pruv_n: i64 = 1i64; let pruv_v: i64 = (-1i64); vec![pruv_v; pruv_n as usize] };
        return bad;
    }
    let mut out: ::std::vec::Vec<i64> = { let pruv_n: i64 = k; let pruv_v: i64 = 0i64; vec![pruv_v; pruv_n as usize] };
    let f: i64 = pruv_m_f_1_10_parse_into(s, &mut out, &mut stk);
    return out;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
#[inline]
pub fn parse_html(s: &str) -> ::std::vec::Vec<i64> {
    let mut pruv_budget: i64 = 1_073_741_824;
    if !(((s.len() as i128) <= 274877906944i128)) { panic!("{}", "pruv: requires violated: crate::parse_html: (len(s) <= 274877906944)"); }
    parse_html__pruv_body(s)
}

