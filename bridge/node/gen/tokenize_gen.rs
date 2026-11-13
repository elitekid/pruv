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
fn pruv_m_f_1_12_cased_before__pruv_body(u: &[i64], i: i64) -> bool {
    let mut j: i64 = (i - 1i64);
    let mut r: i64 = 2i64;
    while ((j >= 0i64) && (r == 2i64)) {
        r = pruv_m_f_1_2_ct((unsafe { *u.get_unchecked((j) as usize) }));
        j = (j - 1i64);
    }
    return (r == 1i64);
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_11_cased_after__pruv_body(u: &[i64], i: i64, m: i64) -> bool {
    let mut j: i64 = (i + 1i64);
    let mut r: i64 = 2i64;
    while ((j < m) && (r == 2i64)) {
        r = pruv_m_f_1_2_ct((unsafe { *u.get_unchecked((j) as usize) }));
        j = (j + 1i64);
    }
    return (r == 1i64);
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_4_push__pruv_body(w: &[i64], a: i64, b: i64, out: &mut [i64], q0: i64) -> i64 {
    let mut q: i64 = pruv_m_f_1_3_put__pruv_body(&mut *out, q0, (b - a));
    let mut k: i64 = a;
    while (k < b) {
        q = pruv_m_f_1_3_put__pruv_body(&mut *out, q, (unsafe { *w.get_unchecked((k) as usize) }));
        k = (k + 1i64);
    }
    return q;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_7_run_end__pruv_body(w: &[i64], a: i64, b: i64, k: i64) -> i64 {
    let mut e: i64 = (a + 1i64);
    while ((e < b) && (pruv_m_f_1_2_wc((unsafe { *w.get_unchecked((e) as usize) })) == k)) {
        e = (e + 1i64);
    }
    return e;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_4_word__pruv_body(w: &[i64], a: i64, b: i64, out: &mut [i64], q: &mut [i64]) {
    let mut p: i64 = (unsafe { *q.get_unchecked((0i64) as usize) });
    let mut cnt: i64 = (unsafe { *q.get_unchecked((1i64) as usize) });
    let mut r: i64 = a;
    while (r < b) {
        let k: i64 = pruv_m_f_1_2_wc((unsafe { *w.get_unchecked((r) as usize) }));
        let e: i64 = pruv_m_f_1_7_run_end__pruv_body(w, r, b, k);
        if (((k != 2i64) || ((unsafe { *w.get_unchecked((r) as usize) }) > 65535i64)) || ((e - r) == 1i64)) {
            p = pruv_m_f_1_4_push__pruv_body(w, r, e, &mut *out, p);
            if (cnt < 1125899906842624i64) {
                cnt = (cnt + 1i64);
            }
        } else {
            if (((e - r) >= 3i64) && ((e - r) <= 8i64)) {
                p = pruv_m_f_1_4_push__pruv_body(w, r, e, &mut *out, p);
                if (cnt < 1125899906842624i64) {
                    cnt = (cnt + 1i64);
                }
            }
            let mut j: i64 = r;
            while ((j + 1i64) < e) {
                p = pruv_m_f_1_4_push__pruv_body(w, j, (j + 2i64), &mut *out, p);
                if (cnt < 1125899906842624i64) {
                    cnt = (cnt + 1i64);
                }
                j = (j + 1i64);
            }
        }
        r = e;
    }
    { let pruv_i: i64 = 0i64; let pruv_x: i64 = p; unsafe { *q.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
    { let pruv_i: i64 = 1i64; let pruv_x: i64 = cnt; unsafe { *q.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_4_emit__pruv_body(w: &[i64], m: i64, out: &mut [i64]) -> i64 {
    let mut q: ::std::vec::Vec<i64> = { let pruv_n: i64 = 2i64; let pruv_v: i64 = 0i64; vec![pruv_v; pruv_n as usize] };
    { let pruv_i: i64 = 0i64; let pruv_x: i64 = 1i64; unsafe { *q.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
    let mut i: i64 = 0i64;
    while (i < m) {
        if (pruv_m_f_1_2_wc((unsafe { *w.get_unchecked((i) as usize) })) == 0i64) {
            i = (i + 1i64);
        } else {
            let mut e: i64 = (i + 1i64);
            while ((e < m) && (pruv_m_f_1_2_wc((unsafe { *w.get_unchecked((e) as usize) })) != 0i64)) {
                e = (e + 1i64);
            }
            pruv_m_f_1_4_word__pruv_body(w, i, e, &mut *out, &mut q);
            i = e;
        }
    }
    pruv_m_f_1_3_set(&mut *out, 0i64, (unsafe { *q.get_unchecked((1i64) as usize) }));
    return (unsafe { *q.get_unchecked((0i64) as usize) });
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn tokenize__pruv_body(s: &str) -> ::std::vec::Vec<i64> {
    let n: i64 = (s.len() as i64);
    let mut u: ::std::vec::Vec<i64> = { let pruv_n: i64 = (n + 1i64); let pruv_v: i64 = 0i64; vec![pruv_v; pruv_n as usize] };
    let mut nu: i64 = 0i64;
    let mut i: i64 = 0i64;
    while (i < n) {
        let l: i64 = pruv_m_f_1_4_clen__pruv_body(s, i, n);
        { let pruv_i: i64 = nu; let pruv_x: i64 = pruv_m_f_1_5_cp_at__pruv_body(s, i, l); unsafe { *u.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
        nu = (nu + 1i64);
        i = (i + l);
    }
    let mut w: ::std::vec::Vec<i64> = { let pruv_n: i64 = ((2i64 * nu) + 1i64); let pruv_v: i64 = 0i64; vec![pruv_v; pruv_n as usize] };
    let mut m: i64 = 0i64;
    let mut k: i64 = 0i64;
    while (k < nu) {
        let c: i64 = (unsafe { *u.get_unchecked((k) as usize) });
        if (c == 304i64) {
            { let pruv_i: i64 = m; let pruv_x: i64 = 105i64; unsafe { *w.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
            { let pruv_i: i64 = (m + 1i64); let pruv_x: i64 = 775i64; unsafe { *w.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
            m = (m + 2i64);
        } else {
            if (c == 931i64) {
                { let pruv_i: i64 = m; let pruv_x: i64 = 963i64; unsafe { *w.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
                if (pruv_m_f_1_12_cased_before__pruv_body(&u, k) && (!pruv_m_f_1_11_cased_after__pruv_body(&u, k, nu))) {
                    { let pruv_i: i64 = m; let pruv_x: i64 = 962i64; unsafe { *w.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
                }
            } else {
                { let pruv_i: i64 = m; let pruv_x: i64 = pruv_m_f_1_3_lw1(c); unsafe { *w.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
            }
            m = (m + 1i64);
        }
        k = (k + 1i64);
    }
    let mut none: ::std::vec::Vec<i64> = { let pruv_n: i64 = 0i64; let pruv_v: i64 = 0i64; vec![pruv_v; pruv_n as usize] };
    let t: i64 = pruv_m_f_1_4_emit__pruv_body(&w, m, &mut none);
    if (t > 1099511627776i64) {
        let bad: ::std::vec::Vec<i64> = { let pruv_n: i64 = 1i64; let pruv_v: i64 = (-1i64); vec![pruv_v; pruv_n as usize] };
        return bad;
    }
    let mut out: ::std::vec::Vec<i64> = { let pruv_n: i64 = t; let pruv_v: i64 = 0i64; vec![pruv_v; pruv_n as usize] };
    let f: i64 = pruv_m_f_1_4_emit__pruv_body(&w, m, &mut out);
    return out;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
#[inline]
pub fn tokenize(s: &str) -> ::std::vec::Vec<i64> {
    let mut pruv_budget: i64 = 1_073_741_824;
    if !(((s.len() as i128) <= 274877906944i128)) { panic!("{}", "pruv: requires violated: crate::tokenize: (len(s) <= 274877906944)"); }
    tokenize__pruv_body(s)
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_2_wc(c: i64) -> i64 {
    if (c < 44032i64) {
        if (c < 4702i64) {
            if (c < 2833i64) {
                if (c < 2085i64) {
                    if (c < 1015i64) {
                        if (c < 722i64) {
                            if (c < 182i64) {
                                if (c < 123i64) {
                                    if (c < 65i64) {
                                        if (c < 48i64) {
                                            return 0i64;
                                        }
                                        if (c < 58i64) {
                                            return 1i64;
                                        }
                                        return 0i64;
                                    }
                                    if (c < 91i64) {
                                        return 1i64;
                                    }
                                    if (c < 97i64) {
                                        return 0i64;
                                    }
                                    return 1i64;
                                }
                                if (c < 178i64) {
                                    if (c < 170i64) {
                                        return 0i64;
                                    }
                                    if (c < 171i64) {
                                        return 1i64;
                                    }
                                    return 0i64;
                                }
                                if (c < 180i64) {
                                    return 1i64;
                                }
                                if (c < 181i64) {
                                    return 0i64;
                                }
                                return 1i64;
                            }
                            if (c < 215i64) {
                                if (c < 188i64) {
                                    if (c < 185i64) {
                                        return 0i64;
                                    }
                                    if (c < 187i64) {
                                        return 1i64;
                                    }
                                    return 0i64;
                                }
                                if (c < 191i64) {
                                    return 1i64;
                                }
                                if (c < 192i64) {
                                    return 0i64;
                                }
                                return 1i64;
                            }
                            if (c < 248i64) {
                                if (c < 216i64) {
                                    return 0i64;
                                }
                                if (c < 247i64) {
                                    return 1i64;
                                }
                                return 0i64;
                            }
                            if (c < 706i64) {
                                return 1i64;
                            }
                            if (c < 710i64) {
                                return 0i64;
                            }
                            return 1i64;
                        }
                        if (c < 894i64) {
                            if (c < 751i64) {
                                if (c < 748i64) {
                                    if (c < 736i64) {
                                        return 0i64;
                                    }
                                    if (c < 741i64) {
                                        return 1i64;
                                    }
                                    return 0i64;
                                }
                                if (c < 749i64) {
                                    return 1i64;
                                }
                                if (c < 750i64) {
                                    return 0i64;
                                }
                                return 1i64;
                            }
                            if (c < 886i64) {
                                if (c < 880i64) {
                                    return 0i64;
                                }
                                if (c < 885i64) {
                                    return 1i64;
                                }
                                return 0i64;
                            }
                            if (c < 888i64) {
                                return 1i64;
                            }
                            if (c < 890i64) {
                                return 0i64;
                            }
                            return 1i64;
                        }
                        if (c < 907i64) {
                            if (c < 902i64) {
                                if (c < 895i64) {
                                    return 0i64;
                                }
                                if (c < 896i64) {
                                    return 1i64;
                                }
                                return 0i64;
                            }
                            if (c < 903i64) {
                                return 1i64;
                            }
                            if (c < 904i64) {
                                return 0i64;
                            }
                            return 1i64;
                        }
                        if (c < 910i64) {
                            if (c < 908i64) {
                                return 0i64;
                            }
                            if (c < 909i64) {
                                return 1i64;
                            }
                            return 0i64;
                        }
                        if (c < 931i64) {
                            if (c < 930i64) {
                                return 1i64;
                            }
                            return 0i64;
                        }
                        if (c < 1014i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 1765i64) {
                        if (c < 1519i64) {
                            if (c < 1369i64) {
                                if (c < 1328i64) {
                                    if (c < 1154i64) {
                                        return 1i64;
                                    }
                                    if (c < 1162i64) {
                                        return 0i64;
                                    }
                                    return 1i64;
                                }
                                if (c < 1329i64) {
                                    return 0i64;
                                }
                                if (c < 1367i64) {
                                    return 1i64;
                                }
                                return 0i64;
                            }
                            if (c < 1417i64) {
                                if (c < 1370i64) {
                                    return 1i64;
                                }
                                if (c < 1376i64) {
                                    return 0i64;
                                }
                                return 1i64;
                            }
                            if (c < 1488i64) {
                                return 0i64;
                            }
                            if (c < 1515i64) {
                                return 1i64;
                            }
                            return 0i64;
                        }
                        if (c < 1646i64) {
                            if (c < 1611i64) {
                                if (c < 1523i64) {
                                    return 1i64;
                                }
                                if (c < 1568i64) {
                                    return 0i64;
                                }
                                return 1i64;
                            }
                            if (c < 1632i64) {
                                return 0i64;
                            }
                            if (c < 1642i64) {
                                return 1i64;
                            }
                            return 0i64;
                        }
                        if (c < 1748i64) {
                            if (c < 1648i64) {
                                return 1i64;
                            }
                            if (c < 1649i64) {
                                return 0i64;
                            }
                            return 1i64;
                        }
                        if (c < 1749i64) {
                            return 0i64;
                        }
                        if (c < 1750i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 1969i64) {
                        if (c < 1808i64) {
                            if (c < 1789i64) {
                                if (c < 1767i64) {
                                    return 1i64;
                                }
                                if (c < 1774i64) {
                                    return 0i64;
                                }
                                return 1i64;
                            }
                            if (c < 1791i64) {
                                return 0i64;
                            }
                            if (c < 1792i64) {
                                return 1i64;
                            }
                            return 0i64;
                        }
                        if (c < 1840i64) {
                            if (c < 1809i64) {
                                return 1i64;
                            }
                            if (c < 1810i64) {
                                return 0i64;
                            }
                            return 1i64;
                        }
                        if (c < 1869i64) {
                            return 0i64;
                        }
                        if (c < 1958i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 2042i64) {
                        if (c < 2027i64) {
                            if (c < 1970i64) {
                                return 1i64;
                            }
                            if (c < 1984i64) {
                                return 0i64;
                            }
                            return 1i64;
                        }
                        if (c < 2036i64) {
                            return 0i64;
                        }
                        if (c < 2038i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 2070i64) {
                        if (c < 2043i64) {
                            return 1i64;
                        }
                        if (c < 2048i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 2075i64) {
                        if (c < 2074i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 2084i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 2556i64) {
                    if (c < 2433i64) {
                        if (c < 2250i64) {
                            if (c < 2155i64) {
                                if (c < 2112i64) {
                                    if (c < 2088i64) {
                                        return 0i64;
                                    }
                                    if (c < 2089i64) {
                                        return 1i64;
                                    }
                                    return 0i64;
                                }
                                if (c < 2137i64) {
                                    return 1i64;
                                }
                                if (c < 2144i64) {
                                    return 0i64;
                                }
                                return 1i64;
                            }
                            if (c < 2185i64) {
                                if (c < 2160i64) {
                                    return 0i64;
                                }
                                if (c < 2184i64) {
                                    return 1i64;
                                }
                                return 0i64;
                            }
                            if (c < 2192i64) {
                                return 1i64;
                            }
                            if (c < 2208i64) {
                                return 0i64;
                            }
                            return 1i64;
                        }
                        if (c < 2385i64) {
                            if (c < 2365i64) {
                                if (c < 2308i64) {
                                    return 0i64;
                                }
                                if (c < 2362i64) {
                                    return 1i64;
                                }
                                return 0i64;
                            }
                            if (c < 2366i64) {
                                return 1i64;
                            }
                            if (c < 2384i64) {
                                return 0i64;
                            }
                            return 1i64;
                        }
                        if (c < 2406i64) {
                            if (c < 2392i64) {
                                return 0i64;
                            }
                            if (c < 2402i64) {
                                return 1i64;
                            }
                            return 0i64;
                        }
                        if (c < 2416i64) {
                            return 1i64;
                        }
                        if (c < 2417i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 2490i64) {
                        if (c < 2473i64) {
                            if (c < 2447i64) {
                                if (c < 2437i64) {
                                    return 0i64;
                                }
                                if (c < 2445i64) {
                                    return 1i64;
                                }
                                return 0i64;
                            }
                            if (c < 2449i64) {
                                return 1i64;
                            }
                            if (c < 2451i64) {
                                return 0i64;
                            }
                            return 1i64;
                        }
                        if (c < 2482i64) {
                            if (c < 2474i64) {
                                return 0i64;
                            }
                            if (c < 2481i64) {
                                return 1i64;
                            }
                            return 0i64;
                        }
                        if (c < 2483i64) {
                            return 1i64;
                        }
                        if (c < 2486i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 2526i64) {
                        if (c < 2510i64) {
                            if (c < 2493i64) {
                                return 0i64;
                            }
                            if (c < 2494i64) {
                                return 1i64;
                            }
                            return 0i64;
                        }
                        if (c < 2511i64) {
                            return 1i64;
                        }
                        if (c < 2524i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 2534i64) {
                        if (c < 2527i64) {
                            return 0i64;
                        }
                        if (c < 2530i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 2548i64) {
                        if (c < 2546i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 2554i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 2693i64) {
                    if (c < 2613i64) {
                        if (c < 2579i64) {
                            if (c < 2571i64) {
                                if (c < 2557i64) {
                                    return 1i64;
                                }
                                if (c < 2565i64) {
                                    return 0i64;
                                }
                                return 1i64;
                            }
                            if (c < 2575i64) {
                                return 0i64;
                            }
                            if (c < 2577i64) {
                                return 1i64;
                            }
                            return 0i64;
                        }
                        if (c < 2609i64) {
                            if (c < 2601i64) {
                                return 1i64;
                            }
                            if (c < 2602i64) {
                                return 0i64;
                            }
                            return 1i64;
                        }
                        if (c < 2610i64) {
                            return 0i64;
                        }
                        if (c < 2612i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 2654i64) {
                        if (c < 2618i64) {
                            if (c < 2615i64) {
                                return 1i64;
                            }
                            if (c < 2616i64) {
                                return 0i64;
                            }
                            return 1i64;
                        }
                        if (c < 2649i64) {
                            return 0i64;
                        }
                        if (c < 2653i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 2672i64) {
                        if (c < 2655i64) {
                            return 1i64;
                        }
                        if (c < 2662i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 2674i64) {
                        return 0i64;
                    }
                    if (c < 2677i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 2749i64) {
                    if (c < 2730i64) {
                        if (c < 2706i64) {
                            if (c < 2702i64) {
                                return 1i64;
                            }
                            if (c < 2703i64) {
                                return 0i64;
                            }
                            return 1i64;
                        }
                        if (c < 2707i64) {
                            return 0i64;
                        }
                        if (c < 2729i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 2740i64) {
                        if (c < 2737i64) {
                            return 1i64;
                        }
                        if (c < 2738i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 2741i64) {
                        return 0i64;
                    }
                    if (c < 2746i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 2790i64) {
                    if (c < 2769i64) {
                        if (c < 2750i64) {
                            return 1i64;
                        }
                        if (c < 2768i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 2784i64) {
                        return 0i64;
                    }
                    if (c < 2786i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 2810i64) {
                    if (c < 2800i64) {
                        return 1i64;
                    }
                    if (c < 2809i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 2829i64) {
                    if (c < 2821i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 2831i64) {
                    return 0i64;
                }
                return 1i64;
            }
            if (c < 3426i64) {
                if (c < 3114i64) {
                    if (c < 2961i64) {
                        if (c < 2910i64) {
                            if (c < 2868i64) {
                                if (c < 2858i64) {
                                    if (c < 2835i64) {
                                        return 0i64;
                                    }
                                    if (c < 2857i64) {
                                        return 1i64;
                                    }
                                    return 0i64;
                                }
                                if (c < 2865i64) {
                                    return 1i64;
                                }
                                if (c < 2866i64) {
                                    return 0i64;
                                }
                                return 1i64;
                            }
                            if (c < 2877i64) {
                                if (c < 2869i64) {
                                    return 0i64;
                                }
                                if (c < 2874i64) {
                                    return 1i64;
                                }
                                return 0i64;
                            }
                            if (c < 2878i64) {
                                return 1i64;
                            }
                            if (c < 2908i64) {
                                return 0i64;
                            }
                            return 1i64;
                        }
                        if (c < 2936i64) {
                            if (c < 2918i64) {
                                if (c < 2911i64) {
                                    return 0i64;
                                }
                                if (c < 2914i64) {
                                    return 1i64;
                                }
                                return 0i64;
                            }
                            if (c < 2928i64) {
                                return 1i64;
                            }
                            if (c < 2929i64) {
                                return 0i64;
                            }
                            return 1i64;
                        }
                        if (c < 2949i64) {
                            if (c < 2947i64) {
                                return 0i64;
                            }
                            if (c < 2948i64) {
                                return 1i64;
                            }
                            return 0i64;
                        }
                        if (c < 2955i64) {
                            return 1i64;
                        }
                        if (c < 2958i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 2987i64) {
                        if (c < 2973i64) {
                            if (c < 2969i64) {
                                if (c < 2962i64) {
                                    return 0i64;
                                }
                                if (c < 2966i64) {
                                    return 1i64;
                                }
                                return 0i64;
                            }
                            if (c < 2971i64) {
                                return 1i64;
                            }
                            if (c < 2972i64) {
                                return 0i64;
                            }
                            return 1i64;
                        }
                        if (c < 2979i64) {
                            if (c < 2974i64) {
                                return 0i64;
                            }
                            if (c < 2976i64) {
                                return 1i64;
                            }
                            return 0i64;
                        }
                        if (c < 2981i64) {
                            return 1i64;
                        }
                        if (c < 2984i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 3059i64) {
                        if (c < 3024i64) {
                            if (c < 2990i64) {
                                return 0i64;
                            }
                            if (c < 3002i64) {
                                return 1i64;
                            }
                            return 0i64;
                        }
                        if (c < 3025i64) {
                            return 1i64;
                        }
                        if (c < 3046i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 3086i64) {
                        if (c < 3077i64) {
                            return 0i64;
                        }
                        if (c < 3085i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 3090i64) {
                        if (c < 3089i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 3113i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 3253i64) {
                    if (c < 3192i64) {
                        if (c < 3164i64) {
                            if (c < 3134i64) {
                                if (c < 3130i64) {
                                    return 1i64;
                                }
                                if (c < 3133i64) {
                                    return 0i64;
                                }
                                return 1i64;
                            }
                            if (c < 3160i64) {
                                return 0i64;
                            }
                            if (c < 3163i64) {
                                return 1i64;
                            }
                            return 0i64;
                        }
                        if (c < 3170i64) {
                            if (c < 3166i64) {
                                return 1i64;
                            }
                            if (c < 3168i64) {
                                return 0i64;
                            }
                            return 1i64;
                        }
                        if (c < 3174i64) {
                            return 0i64;
                        }
                        if (c < 3184i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 3214i64) {
                        if (c < 3201i64) {
                            if (c < 3199i64) {
                                return 1i64;
                            }
                            if (c < 3200i64) {
                                return 0i64;
                            }
                            return 1i64;
                        }
                        if (c < 3205i64) {
                            return 0i64;
                        }
                        if (c < 3213i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 3241i64) {
                        if (c < 3217i64) {
                            return 1i64;
                        }
                        if (c < 3218i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 3242i64) {
                        return 0i64;
                    }
                    if (c < 3252i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 3332i64) {
                    if (c < 3296i64) {
                        if (c < 3262i64) {
                            if (c < 3258i64) {
                                return 1i64;
                            }
                            if (c < 3261i64) {
                                return 0i64;
                            }
                            return 1i64;
                        }
                        if (c < 3292i64) {
                            return 0i64;
                        }
                        if (c < 3295i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 3312i64) {
                        if (c < 3298i64) {
                            return 1i64;
                        }
                        if (c < 3302i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 3313i64) {
                        return 0i64;
                    }
                    if (c < 3315i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 3389i64) {
                    if (c < 3345i64) {
                        if (c < 3341i64) {
                            return 1i64;
                        }
                        if (c < 3342i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 3346i64) {
                        return 0i64;
                    }
                    if (c < 3387i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 3407i64) {
                    if (c < 3390i64) {
                        return 1i64;
                    }
                    if (c < 3406i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 3415i64) {
                    if (c < 3412i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 3416i64) {
                    return 0i64;
                }
                return 1i64;
            }
            if (c < 3840i64) {
                if (c < 3674i64) {
                    if (c < 3518i64) {
                        if (c < 3479i64) {
                            if (c < 3450i64) {
                                if (c < 3430i64) {
                                    return 0i64;
                                }
                                if (c < 3449i64) {
                                    return 1i64;
                                }
                                return 0i64;
                            }
                            if (c < 3456i64) {
                                return 1i64;
                            }
                            if (c < 3461i64) {
                                return 0i64;
                            }
                            return 1i64;
                        }
                        if (c < 3507i64) {
                            if (c < 3482i64) {
                                return 0i64;
                            }
                            if (c < 3506i64) {
                                return 1i64;
                            }
                            return 0i64;
                        }
                        if (c < 3516i64) {
                            return 1i64;
                        }
                        if (c < 3517i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 3633i64) {
                        if (c < 3558i64) {
                            if (c < 3520i64) {
                                return 0i64;
                            }
                            if (c < 3527i64) {
                                return 1i64;
                            }
                            return 0i64;
                        }
                        if (c < 3568i64) {
                            return 1i64;
                        }
                        if (c < 3585i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 3648i64) {
                        if (c < 3634i64) {
                            return 0i64;
                        }
                        if (c < 3636i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 3655i64) {
                        return 1i64;
                    }
                    if (c < 3664i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 3761i64) {
                    if (c < 3723i64) {
                        if (c < 3716i64) {
                            if (c < 3713i64) {
                                return 0i64;
                            }
                            if (c < 3715i64) {
                                return 1i64;
                            }
                            return 0i64;
                        }
                        if (c < 3717i64) {
                            return 1i64;
                        }
                        if (c < 3718i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 3749i64) {
                        if (c < 3724i64) {
                            return 0i64;
                        }
                        if (c < 3748i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 3750i64) {
                        return 1i64;
                    }
                    if (c < 3751i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 3781i64) {
                    if (c < 3773i64) {
                        if (c < 3762i64) {
                            return 0i64;
                        }
                        if (c < 3764i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 3774i64) {
                        return 1i64;
                    }
                    if (c < 3776i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 3792i64) {
                    if (c < 3782i64) {
                        return 0i64;
                    }
                    if (c < 3783i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 3804i64) {
                    if (c < 3802i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 3808i64) {
                    return 1i64;
                }
                return 0i64;
            }
            if (c < 4213i64) {
                if (c < 4159i64) {
                    if (c < 3913i64) {
                        if (c < 3892i64) {
                            if (c < 3841i64) {
                                return 1i64;
                            }
                            if (c < 3872i64) {
                                return 0i64;
                            }
                            return 1i64;
                        }
                        if (c < 3904i64) {
                            return 0i64;
                        }
                        if (c < 3912i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 3981i64) {
                        if (c < 3949i64) {
                            return 1i64;
                        }
                        if (c < 3976i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 4096i64) {
                        return 0i64;
                    }
                    if (c < 4139i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 4193i64) {
                    if (c < 4182i64) {
                        if (c < 4170i64) {
                            return 1i64;
                        }
                        if (c < 4176i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 4186i64) {
                        return 0i64;
                    }
                    if (c < 4190i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 4199i64) {
                    if (c < 4194i64) {
                        return 1i64;
                    }
                    if (c < 4197i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 4206i64) {
                    return 0i64;
                }
                if (c < 4209i64) {
                    return 1i64;
                }
                return 0i64;
            }
            if (c < 4304i64) {
                if (c < 4256i64) {
                    if (c < 4239i64) {
                        if (c < 4226i64) {
                            return 1i64;
                        }
                        if (c < 4238i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 4240i64) {
                        return 0i64;
                    }
                    if (c < 4250i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 4296i64) {
                    if (c < 4294i64) {
                        return 1i64;
                    }
                    if (c < 4295i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 4301i64) {
                    return 0i64;
                }
                if (c < 4302i64) {
                    return 1i64;
                }
                return 0i64;
            }
            if (c < 4682i64) {
                if (c < 4352i64) {
                    if (c < 4347i64) {
                        return 1i64;
                    }
                    if (c < 4348i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 4608i64) {
                    return 2i64;
                }
                if (c < 4681i64) {
                    return 1i64;
                }
                return 0i64;
            }
            if (c < 4695i64) {
                if (c < 4686i64) {
                    return 1i64;
                }
                if (c < 4688i64) {
                    return 0i64;
                }
                return 1i64;
            }
            if (c < 4697i64) {
                if (c < 4696i64) {
                    return 0i64;
                }
                return 1i64;
            }
            if (c < 4698i64) {
                return 0i64;
            }
            return 1i64;
        }
        if (c < 8522i64) {
            if (c < 6989i64) {
                if (c < 5998i64) {
                    if (c < 4989i64) {
                        if (c < 4801i64) {
                            if (c < 4785i64) {
                                if (c < 4746i64) {
                                    if (c < 4704i64) {
                                        return 0i64;
                                    }
                                    if (c < 4745i64) {
                                        return 1i64;
                                    }
                                    return 0i64;
                                }
                                if (c < 4750i64) {
                                    return 1i64;
                                }
                                if (c < 4752i64) {
                                    return 0i64;
                                }
                                return 1i64;
                            }
                            if (c < 4792i64) {
                                if (c < 4786i64) {
                                    return 0i64;
                                }
                                if (c < 4790i64) {
                                    return 1i64;
                                }
                                return 0i64;
                            }
                            if (c < 4799i64) {
                                return 1i64;
                            }
                            if (c < 4800i64) {
                                return 0i64;
                            }
                            return 1i64;
                        }
                        if (c < 4881i64) {
                            if (c < 4808i64) {
                                if (c < 4802i64) {
                                    return 0i64;
                                }
                                if (c < 4806i64) {
                                    return 1i64;
                                }
                                return 0i64;
                            }
                            if (c < 4823i64) {
                                return 1i64;
                            }
                            if (c < 4824i64) {
                                return 0i64;
                            }
                            return 1i64;
                        }
                        if (c < 4888i64) {
                            if (c < 4882i64) {
                                return 0i64;
                            }
                            if (c < 4886i64) {
                                return 1i64;
                            }
                            return 0i64;
                        }
                        if (c < 4955i64) {
                            return 1i64;
                        }
                        if (c < 4969i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 5787i64) {
                        if (c < 5118i64) {
                            if (c < 5024i64) {
                                if (c < 4992i64) {
                                    return 0i64;
                                }
                                if (c < 5008i64) {
                                    return 1i64;
                                }
                                return 0i64;
                            }
                            if (c < 5110i64) {
                                return 1i64;
                            }
                            if (c < 5112i64) {
                                return 0i64;
                            }
                            return 1i64;
                        }
                        if (c < 5743i64) {
                            if (c < 5121i64) {
                                return 0i64;
                            }
                            if (c < 5741i64) {
                                return 1i64;
                            }
                            return 0i64;
                        }
                        if (c < 5760i64) {
                            return 1i64;
                        }
                        if (c < 5761i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 5906i64) {
                        if (c < 5870i64) {
                            if (c < 5792i64) {
                                return 0i64;
                            }
                            if (c < 5867i64) {
                                return 1i64;
                            }
                            return 0i64;
                        }
                        if (c < 5881i64) {
                            return 1i64;
                        }
                        if (c < 5888i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 5952i64) {
                        if (c < 5919i64) {
                            return 0i64;
                        }
                        if (c < 5938i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 5984i64) {
                        if (c < 5970i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 5997i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 6400i64) {
                    if (c < 6160i64) {
                        if (c < 6108i64) {
                            if (c < 6068i64) {
                                if (c < 6001i64) {
                                    return 1i64;
                                }
                                if (c < 6016i64) {
                                    return 0i64;
                                }
                                return 1i64;
                            }
                            if (c < 6103i64) {
                                return 0i64;
                            }
                            if (c < 6104i64) {
                                return 1i64;
                            }
                            return 0i64;
                        }
                        if (c < 6122i64) {
                            if (c < 6109i64) {
                                return 1i64;
                            }
                            if (c < 6112i64) {
                                return 0i64;
                            }
                            return 1i64;
                        }
                        if (c < 6128i64) {
                            return 0i64;
                        }
                        if (c < 6138i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 6279i64) {
                        if (c < 6265i64) {
                            if (c < 6170i64) {
                                return 1i64;
                            }
                            if (c < 6176i64) {
                                return 0i64;
                            }
                            return 1i64;
                        }
                        if (c < 6272i64) {
                            return 0i64;
                        }
                        if (c < 6277i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 6315i64) {
                        if (c < 6313i64) {
                            return 1i64;
                        }
                        if (c < 6314i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 6320i64) {
                        return 0i64;
                    }
                    if (c < 6390i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 6656i64) {
                    if (c < 6528i64) {
                        if (c < 6510i64) {
                            if (c < 6431i64) {
                                return 1i64;
                            }
                            if (c < 6470i64) {
                                return 0i64;
                            }
                            return 1i64;
                        }
                        if (c < 6512i64) {
                            return 0i64;
                        }
                        if (c < 6517i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 6602i64) {
                        if (c < 6572i64) {
                            return 1i64;
                        }
                        if (c < 6576i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 6608i64) {
                        return 0i64;
                    }
                    if (c < 6619i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 6800i64) {
                    if (c < 6741i64) {
                        if (c < 6679i64) {
                            return 1i64;
                        }
                        if (c < 6688i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 6784i64) {
                        return 0i64;
                    }
                    if (c < 6794i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 6824i64) {
                    if (c < 6810i64) {
                        return 1i64;
                    }
                    if (c < 6823i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 6964i64) {
                    if (c < 6917i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 6981i64) {
                    return 0i64;
                }
                return 1i64;
            }
            if (c < 8118i64) {
                if (c < 7415i64) {
                    if (c < 7294i64) {
                        if (c < 7142i64) {
                            if (c < 7043i64) {
                                if (c < 6992i64) {
                                    return 0i64;
                                }
                                if (c < 7002i64) {
                                    return 1i64;
                                }
                                return 0i64;
                            }
                            if (c < 7073i64) {
                                return 1i64;
                            }
                            if (c < 7086i64) {
                                return 0i64;
                            }
                            return 1i64;
                        }
                        if (c < 7232i64) {
                            if (c < 7168i64) {
                                return 0i64;
                            }
                            if (c < 7204i64) {
                                return 1i64;
                            }
                            return 0i64;
                        }
                        if (c < 7242i64) {
                            return 1i64;
                        }
                        if (c < 7245i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 7360i64) {
                        if (c < 7312i64) {
                            if (c < 7296i64) {
                                return 0i64;
                            }
                            if (c < 7307i64) {
                                return 1i64;
                            }
                            return 0i64;
                        }
                        if (c < 7355i64) {
                            return 1i64;
                        }
                        if (c < 7357i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 7406i64) {
                        if (c < 7401i64) {
                            return 0i64;
                        }
                        if (c < 7405i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 7412i64) {
                        return 1i64;
                    }
                    if (c < 7413i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 8014i64) {
                    if (c < 7958i64) {
                        if (c < 7424i64) {
                            if (c < 7418i64) {
                                return 0i64;
                            }
                            if (c < 7419i64) {
                                return 1i64;
                            }
                            return 0i64;
                        }
                        if (c < 7616i64) {
                            return 1i64;
                        }
                        if (c < 7680i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 7968i64) {
                        if (c < 7960i64) {
                            return 0i64;
                        }
                        if (c < 7966i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 8006i64) {
                        return 1i64;
                    }
                    if (c < 8008i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 8028i64) {
                    if (c < 8025i64) {
                        if (c < 8016i64) {
                            return 0i64;
                        }
                        if (c < 8024i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 8026i64) {
                        return 1i64;
                    }
                    if (c < 8027i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 8031i64) {
                    if (c < 8029i64) {
                        return 0i64;
                    }
                    if (c < 8030i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 8064i64) {
                    if (c < 8062i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 8117i64) {
                    return 1i64;
                }
                return 0i64;
            }
            if (c < 8336i64) {
                if (c < 8160i64) {
                    if (c < 8134i64) {
                        if (c < 8127i64) {
                            if (c < 8125i64) {
                                return 1i64;
                            }
                            if (c < 8126i64) {
                                return 0i64;
                            }
                            return 1i64;
                        }
                        if (c < 8130i64) {
                            return 0i64;
                        }
                        if (c < 8133i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 8148i64) {
                        if (c < 8141i64) {
                            return 1i64;
                        }
                        if (c < 8144i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 8150i64) {
                        return 0i64;
                    }
                    if (c < 8156i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 8304i64) {
                    if (c < 8181i64) {
                        if (c < 8173i64) {
                            return 1i64;
                        }
                        if (c < 8178i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 8182i64) {
                        return 0i64;
                    }
                    if (c < 8189i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 8314i64) {
                    if (c < 8306i64) {
                        return 1i64;
                    }
                    if (c < 8308i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 8319i64) {
                    return 0i64;
                }
                if (c < 8330i64) {
                    return 1i64;
                }
                return 0i64;
            }
            if (c < 8484i64) {
                if (c < 8458i64) {
                    if (c < 8451i64) {
                        if (c < 8349i64) {
                            return 1i64;
                        }
                        if (c < 8450i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 8455i64) {
                        return 0i64;
                    }
                    if (c < 8456i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 8470i64) {
                    if (c < 8468i64) {
                        return 1i64;
                    }
                    if (c < 8469i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 8473i64) {
                    return 0i64;
                }
                if (c < 8478i64) {
                    return 1i64;
                }
                return 0i64;
            }
            if (c < 8490i64) {
                if (c < 8487i64) {
                    if (c < 8485i64) {
                        return 1i64;
                    }
                    if (c < 8486i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 8488i64) {
                    return 0i64;
                }
                if (c < 8489i64) {
                    return 1i64;
                }
                return 0i64;
            }
            if (c < 8506i64) {
                if (c < 8494i64) {
                    return 1i64;
                }
                if (c < 8495i64) {
                    return 0i64;
                }
                return 1i64;
            }
            if (c < 8512i64) {
                if (c < 8508i64) {
                    return 0i64;
                }
                return 1i64;
            }
            if (c < 8517i64) {
                return 0i64;
            }
            return 1i64;
        }
        if (c < 42512i64) {
            if (c < 12293i64) {
                if (c < 11566i64) {
                    if (c < 11493i64) {
                        if (c < 9372i64) {
                            if (c < 8528i64) {
                                if (c < 8526i64) {
                                    return 0i64;
                                }
                                if (c < 8527i64) {
                                    return 1i64;
                                }
                                return 0i64;
                            }
                            if (c < 8586i64) {
                                return 1i64;
                            }
                            if (c < 9312i64) {
                                return 0i64;
                            }
                            return 1i64;
                        }
                        if (c < 10102i64) {
                            if (c < 9450i64) {
                                return 0i64;
                            }
                            if (c < 9472i64) {
                                return 1i64;
                            }
                            return 0i64;
                        }
                        if (c < 10132i64) {
                            return 1i64;
                        }
                        if (c < 11264i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 11518i64) {
                        if (c < 11506i64) {
                            if (c < 11499i64) {
                                return 0i64;
                            }
                            if (c < 11503i64) {
                                return 1i64;
                            }
                            return 0i64;
                        }
                        if (c < 11508i64) {
                            return 1i64;
                        }
                        if (c < 11517i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 11559i64) {
                        if (c < 11520i64) {
                            return 0i64;
                        }
                        if (c < 11558i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 11560i64) {
                        return 1i64;
                    }
                    if (c < 11565i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 11703i64) {
                    if (c < 11671i64) {
                        if (c < 11631i64) {
                            if (c < 11568i64) {
                                return 0i64;
                            }
                            if (c < 11624i64) {
                                return 1i64;
                            }
                            return 0i64;
                        }
                        if (c < 11632i64) {
                            return 1i64;
                        }
                        if (c < 11648i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 11688i64) {
                        if (c < 11680i64) {
                            return 0i64;
                        }
                        if (c < 11687i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 11695i64) {
                        return 1i64;
                    }
                    if (c < 11696i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 11727i64) {
                    if (c < 11712i64) {
                        if (c < 11704i64) {
                            return 0i64;
                        }
                        if (c < 11711i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 11719i64) {
                        return 1i64;
                    }
                    if (c < 11720i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 11736i64) {
                    if (c < 11728i64) {
                        return 0i64;
                    }
                    if (c < 11735i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 11823i64) {
                    if (c < 11743i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 11824i64) {
                    return 1i64;
                }
                return 0i64;
            }
            if (c < 12690i64) {
                if (c < 12439i64) {
                    if (c < 12337i64) {
                        if (c < 12296i64) {
                            if (c < 12294i64) {
                                return 2i64;
                            }
                            if (c < 12295i64) {
                                return 1i64;
                            }
                            return 2i64;
                        }
                        if (c < 12321i64) {
                            return 0i64;
                        }
                        if (c < 12330i64) {
                            return 2i64;
                        }
                        return 0i64;
                    }
                    if (c < 12348i64) {
                        if (c < 12342i64) {
                            return 1i64;
                        }
                        if (c < 12344i64) {
                            return 0i64;
                        }
                        return 2i64;
                    }
                    if (c < 12349i64) {
                        return 1i64;
                    }
                    if (c < 12353i64) {
                        return 0i64;
                    }
                    return 2i64;
                }
                if (c < 12541i64) {
                    if (c < 12449i64) {
                        if (c < 12445i64) {
                            return 0i64;
                        }
                        if (c < 12448i64) {
                            return 2i64;
                        }
                        return 0i64;
                    }
                    if (c < 12539i64) {
                        return 2i64;
                    }
                    if (c < 12540i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 12592i64) {
                    if (c < 12544i64) {
                        return 2i64;
                    }
                    if (c < 12549i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 12593i64) {
                    return 0i64;
                }
                if (c < 12687i64) {
                    return 2i64;
                }
                return 0i64;
            }
            if (c < 12928i64) {
                if (c < 12832i64) {
                    if (c < 12736i64) {
                        if (c < 12694i64) {
                            return 1i64;
                        }
                        if (c < 12704i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 12784i64) {
                        return 0i64;
                    }
                    if (c < 12800i64) {
                        return 2i64;
                    }
                    return 0i64;
                }
                if (c < 12880i64) {
                    if (c < 12842i64) {
                        return 1i64;
                    }
                    if (c < 12872i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 12881i64) {
                    return 0i64;
                }
                if (c < 12896i64) {
                    return 1i64;
                }
                return 0i64;
            }
            if (c < 19968i64) {
                if (c < 12992i64) {
                    if (c < 12938i64) {
                        return 1i64;
                    }
                    if (c < 12977i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 13312i64) {
                    return 0i64;
                }
                if (c < 19904i64) {
                    return 2i64;
                }
                return 0i64;
            }
            if (c < 42192i64) {
                if (c < 40960i64) {
                    return 2i64;
                }
                if (c < 42125i64) {
                    return 1i64;
                }
                return 0i64;
            }
            if (c < 42240i64) {
                if (c < 42238i64) {
                    return 1i64;
                }
                return 0i64;
            }
            if (c < 42509i64) {
                return 1i64;
            }
            return 0i64;
        }
        if (c < 43519i64) {
            if (c < 43072i64) {
                if (c < 42891i64) {
                    if (c < 42656i64) {
                        if (c < 42607i64) {
                            if (c < 42540i64) {
                                return 1i64;
                            }
                            if (c < 42560i64) {
                                return 0i64;
                            }
                            return 1i64;
                        }
                        if (c < 42623i64) {
                            return 0i64;
                        }
                        if (c < 42654i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 42784i64) {
                        if (c < 42736i64) {
                            return 1i64;
                        }
                        if (c < 42775i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 42786i64) {
                        return 0i64;
                    }
                    if (c < 42889i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 43015i64) {
                    if (c < 43010i64) {
                        if (c < 42973i64) {
                            return 1i64;
                        }
                        if (c < 42993i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 43011i64) {
                        return 0i64;
                    }
                    if (c < 43014i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 43043i64) {
                    if (c < 43019i64) {
                        return 1i64;
                    }
                    if (c < 43020i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 43056i64) {
                    return 0i64;
                }
                if (c < 43062i64) {
                    return 1i64;
                }
                return 0i64;
            }
            if (c < 43264i64) {
                if (c < 43250i64) {
                    if (c < 43188i64) {
                        if (c < 43124i64) {
                            return 1i64;
                        }
                        if (c < 43138i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 43216i64) {
                        return 0i64;
                    }
                    if (c < 43226i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 43260i64) {
                    if (c < 43256i64) {
                        return 1i64;
                    }
                    if (c < 43259i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 43261i64) {
                    return 0i64;
                }
                if (c < 43263i64) {
                    return 1i64;
                }
                return 0i64;
            }
            if (c < 43396i64) {
                if (c < 43335i64) {
                    if (c < 43302i64) {
                        return 1i64;
                    }
                    if (c < 43312i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 43360i64) {
                    return 0i64;
                }
                if (c < 43389i64) {
                    return 2i64;
                }
                return 0i64;
            }
            if (c < 43482i64) {
                if (c < 43443i64) {
                    return 1i64;
                }
                if (c < 43471i64) {
                    return 0i64;
                }
                return 1i64;
            }
            if (c < 43493i64) {
                if (c < 43488i64) {
                    return 0i64;
                }
                return 1i64;
            }
            if (c < 43494i64) {
                return 0i64;
            }
            return 1i64;
        }
        if (c < 43715i64) {
            if (c < 43643i64) {
                if (c < 43596i64) {
                    if (c < 43584i64) {
                        if (c < 43520i64) {
                            return 0i64;
                        }
                        if (c < 43561i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 43587i64) {
                        return 1i64;
                    }
                    if (c < 43588i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 43616i64) {
                    if (c < 43600i64) {
                        return 0i64;
                    }
                    if (c < 43610i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 43639i64) {
                    return 1i64;
                }
                if (c < 43642i64) {
                    return 0i64;
                }
                return 1i64;
            }
            if (c < 43703i64) {
                if (c < 43697i64) {
                    if (c < 43646i64) {
                        return 0i64;
                    }
                    if (c < 43696i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 43698i64) {
                    return 1i64;
                }
                if (c < 43701i64) {
                    return 0i64;
                }
                return 1i64;
            }
            if (c < 43712i64) {
                if (c < 43705i64) {
                    return 0i64;
                }
                if (c < 43710i64) {
                    return 1i64;
                }
                return 0i64;
            }
            if (c < 43713i64) {
                return 1i64;
            }
            if (c < 43714i64) {
                return 0i64;
            }
            return 1i64;
        }
        if (c < 43799i64) {
            if (c < 43765i64) {
                if (c < 43744i64) {
                    if (c < 43739i64) {
                        return 0i64;
                    }
                    if (c < 43742i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 43755i64) {
                    return 1i64;
                }
                if (c < 43762i64) {
                    return 0i64;
                }
                return 1i64;
            }
            if (c < 43785i64) {
                if (c < 43777i64) {
                    return 0i64;
                }
                if (c < 43783i64) {
                    return 1i64;
                }
                return 0i64;
            }
            if (c < 43791i64) {
                return 1i64;
            }
            if (c < 43793i64) {
                return 0i64;
            }
            return 1i64;
        }
        if (c < 43867i64) {
            if (c < 43816i64) {
                if (c < 43808i64) {
                    return 0i64;
                }
                if (c < 43815i64) {
                    return 1i64;
                }
                return 0i64;
            }
            if (c < 43823i64) {
                return 1i64;
            }
            if (c < 43824i64) {
                return 0i64;
            }
            return 1i64;
        }
        if (c < 43888i64) {
            if (c < 43868i64) {
                return 0i64;
            }
            if (c < 43882i64) {
                return 1i64;
            }
            return 0i64;
        }
        if (c < 44016i64) {
            if (c < 44003i64) {
                return 1i64;
            }
            return 0i64;
        }
        if (c < 44026i64) {
            return 1i64;
        }
        return 0i64;
    }
    if (c < 72161i64) {
        if (c < 68352i64) {
            if (c < 66504i64) {
                if (c < 65392i64) {
                    if (c < 64320i64) {
                        if (c < 64275i64) {
                            if (c < 63744i64) {
                                if (c < 55239i64) {
                                    if (c < 55204i64) {
                                        return 2i64;
                                    }
                                    if (c < 55216i64) {
                                        return 0i64;
                                    }
                                    return 2i64;
                                }
                                if (c < 55243i64) {
                                    return 0i64;
                                }
                                if (c < 55292i64) {
                                    return 2i64;
                                }
                                return 0i64;
                            }
                            if (c < 64218i64) {
                                if (c < 64110i64) {
                                    return 2i64;
                                }
                                if (c < 64112i64) {
                                    return 0i64;
                                }
                                return 2i64;
                            }
                            if (c < 64256i64) {
                                return 0i64;
                            }
                            if (c < 64263i64) {
                                return 1i64;
                            }
                            return 0i64;
                        }
                        if (c < 64298i64) {
                            if (c < 64286i64) {
                                if (c < 64280i64) {
                                    return 1i64;
                                }
                                if (c < 64285i64) {
                                    return 0i64;
                                }
                                return 1i64;
                            }
                            if (c < 64287i64) {
                                return 0i64;
                            }
                            if (c < 64297i64) {
                                return 1i64;
                            }
                            return 0i64;
                        }
                        if (c < 64317i64) {
                            if (c < 64311i64) {
                                return 1i64;
                            }
                            if (c < 64312i64) {
                                return 0i64;
                            }
                            return 1i64;
                        }
                        if (c < 64318i64) {
                            return 0i64;
                        }
                        if (c < 64319i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 65008i64) {
                        if (c < 64467i64) {
                            if (c < 64325i64) {
                                if (c < 64322i64) {
                                    return 1i64;
                                }
                                if (c < 64323i64) {
                                    return 0i64;
                                }
                                return 1i64;
                            }
                            if (c < 64326i64) {
                                return 0i64;
                            }
                            if (c < 64434i64) {
                                return 1i64;
                            }
                            return 0i64;
                        }
                        if (c < 64912i64) {
                            if (c < 64830i64) {
                                return 1i64;
                            }
                            if (c < 64848i64) {
                                return 0i64;
                            }
                            return 1i64;
                        }
                        if (c < 64914i64) {
                            return 0i64;
                        }
                        if (c < 64968i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 65296i64) {
                        if (c < 65141i64) {
                            if (c < 65020i64) {
                                return 1i64;
                            }
                            if (c < 65136i64) {
                                return 0i64;
                            }
                            return 1i64;
                        }
                        if (c < 65142i64) {
                            return 0i64;
                        }
                        if (c < 65277i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 65339i64) {
                        if (c < 65306i64) {
                            return 1i64;
                        }
                        if (c < 65313i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 65371i64) {
                        if (c < 65345i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 65382i64) {
                        return 0i64;
                    }
                    return 2i64;
                }
                if (c < 65630i64) {
                    if (c < 65501i64) {
                        if (c < 65480i64) {
                            if (c < 65440i64) {
                                if (c < 65393i64) {
                                    return 1i64;
                                }
                                if (c < 65438i64) {
                                    return 2i64;
                                }
                                return 1i64;
                            }
                            if (c < 65471i64) {
                                return 2i64;
                            }
                            if (c < 65474i64) {
                                return 0i64;
                            }
                            return 2i64;
                        }
                        if (c < 65490i64) {
                            if (c < 65482i64) {
                                return 0i64;
                            }
                            if (c < 65488i64) {
                                return 2i64;
                            }
                            return 0i64;
                        }
                        if (c < 65496i64) {
                            return 2i64;
                        }
                        if (c < 65498i64) {
                            return 0i64;
                        }
                        return 2i64;
                    }
                    if (c < 65595i64) {
                        if (c < 65549i64) {
                            if (c < 65536i64) {
                                return 0i64;
                            }
                            if (c < 65548i64) {
                                return 1i64;
                            }
                            return 0i64;
                        }
                        if (c < 65575i64) {
                            return 1i64;
                        }
                        if (c < 65576i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 65599i64) {
                        if (c < 65596i64) {
                            return 0i64;
                        }
                        if (c < 65598i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 65614i64) {
                        return 1i64;
                    }
                    if (c < 65616i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 66257i64) {
                    if (c < 65913i64) {
                        if (c < 65799i64) {
                            if (c < 65664i64) {
                                return 0i64;
                            }
                            if (c < 65787i64) {
                                return 1i64;
                            }
                            return 0i64;
                        }
                        if (c < 65844i64) {
                            return 1i64;
                        }
                        if (c < 65856i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 66176i64) {
                        if (c < 65930i64) {
                            return 0i64;
                        }
                        if (c < 65932i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 66205i64) {
                        return 1i64;
                    }
                    if (c < 66208i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 66379i64) {
                    if (c < 66304i64) {
                        if (c < 66273i64) {
                            return 0i64;
                        }
                        if (c < 66300i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 66340i64) {
                        return 1i64;
                    }
                    if (c < 66349i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 66432i64) {
                    if (c < 66384i64) {
                        return 0i64;
                    }
                    if (c < 66422i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 66464i64) {
                    if (c < 66462i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 66500i64) {
                    return 1i64;
                }
                return 0i64;
            }
            if (c < 67593i64) {
                if (c < 66967i64) {
                    if (c < 66816i64) {
                        if (c < 66720i64) {
                            if (c < 66518i64) {
                                if (c < 66512i64) {
                                    return 1i64;
                                }
                                if (c < 66513i64) {
                                    return 0i64;
                                }
                                return 1i64;
                            }
                            if (c < 66560i64) {
                                return 0i64;
                            }
                            if (c < 66718i64) {
                                return 1i64;
                            }
                            return 0i64;
                        }
                        if (c < 66772i64) {
                            if (c < 66730i64) {
                                return 1i64;
                            }
                            if (c < 66736i64) {
                                return 0i64;
                            }
                            return 1i64;
                        }
                        if (c < 66776i64) {
                            return 0i64;
                        }
                        if (c < 66812i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 66940i64) {
                        if (c < 66916i64) {
                            if (c < 66856i64) {
                                return 1i64;
                            }
                            if (c < 66864i64) {
                                return 0i64;
                            }
                            return 1i64;
                        }
                        if (c < 66928i64) {
                            return 0i64;
                        }
                        if (c < 66939i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 66963i64) {
                        if (c < 66955i64) {
                            return 1i64;
                        }
                        if (c < 66956i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 66964i64) {
                        return 0i64;
                    }
                    if (c < 66966i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 67392i64) {
                    if (c < 67003i64) {
                        if (c < 66994i64) {
                            if (c < 66978i64) {
                                return 1i64;
                            }
                            if (c < 66979i64) {
                                return 0i64;
                            }
                            return 1i64;
                        }
                        if (c < 66995i64) {
                            return 0i64;
                        }
                        if (c < 67002i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 67060i64) {
                        if (c < 67005i64) {
                            return 1i64;
                        }
                        if (c < 67008i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 67072i64) {
                        return 0i64;
                    }
                    if (c < 67383i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 67463i64) {
                    if (c < 67432i64) {
                        if (c < 67414i64) {
                            return 1i64;
                        }
                        if (c < 67424i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 67456i64) {
                        return 0i64;
                    }
                    if (c < 67462i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 67515i64) {
                    if (c < 67505i64) {
                        return 1i64;
                    }
                    if (c < 67506i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 67590i64) {
                    if (c < 67584i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 67592i64) {
                    return 0i64;
                }
                return 1i64;
            }
            if (c < 67930i64) {
                if (c < 67743i64) {
                    if (c < 67645i64) {
                        if (c < 67639i64) {
                            if (c < 67594i64) {
                                return 0i64;
                            }
                            if (c < 67638i64) {
                                return 1i64;
                            }
                            return 0i64;
                        }
                        if (c < 67641i64) {
                            return 1i64;
                        }
                        if (c < 67644i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 67672i64) {
                        if (c < 67647i64) {
                            return 0i64;
                        }
                        if (c < 67670i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 67703i64) {
                        return 1i64;
                    }
                    if (c < 67705i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 67830i64) {
                    if (c < 67808i64) {
                        if (c < 67751i64) {
                            return 0i64;
                        }
                        if (c < 67760i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 67827i64) {
                        return 1i64;
                    }
                    if (c < 67828i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 67872i64) {
                    if (c < 67835i64) {
                        return 0i64;
                    }
                    if (c < 67868i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 67898i64) {
                    return 1i64;
                }
                if (c < 67904i64) {
                    return 0i64;
                }
                return 1i64;
            }
            if (c < 68150i64) {
                if (c < 68097i64) {
                    if (c < 68028i64) {
                        if (c < 67968i64) {
                            return 0i64;
                        }
                        if (c < 68024i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 68048i64) {
                        return 1i64;
                    }
                    if (c < 68050i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 68117i64) {
                    if (c < 68112i64) {
                        return 0i64;
                    }
                    if (c < 68116i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 68120i64) {
                    return 1i64;
                }
                if (c < 68121i64) {
                    return 0i64;
                }
                return 1i64;
            }
            if (c < 68256i64) {
                if (c < 68192i64) {
                    if (c < 68160i64) {
                        return 0i64;
                    }
                    if (c < 68169i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 68223i64) {
                    return 1i64;
                }
                if (c < 68224i64) {
                    return 0i64;
                }
                return 1i64;
            }
            if (c < 68297i64) {
                if (c < 68288i64) {
                    return 0i64;
                }
                if (c < 68296i64) {
                    return 1i64;
                }
                return 0i64;
            }
            if (c < 68331i64) {
                if (c < 68325i64) {
                    return 1i64;
                }
                return 0i64;
            }
            if (c < 68336i64) {
                return 1i64;
            }
            return 0i64;
        }
        if (c < 70384i64) {
            if (c < 69747i64) {
                if (c < 69216i64) {
                    if (c < 68736i64) {
                        if (c < 68472i64) {
                            if (c < 68438i64) {
                                if (c < 68406i64) {
                                    return 1i64;
                                }
                                if (c < 68416i64) {
                                    return 0i64;
                                }
                                return 1i64;
                            }
                            if (c < 68440i64) {
                                return 0i64;
                            }
                            if (c < 68467i64) {
                                return 1i64;
                            }
                            return 0i64;
                        }
                        if (c < 68528i64) {
                            if (c < 68498i64) {
                                return 1i64;
                            }
                            if (c < 68521i64) {
                                return 0i64;
                            }
                            return 1i64;
                        }
                        if (c < 68608i64) {
                            return 0i64;
                        }
                        if (c < 68681i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 68912i64) {
                        if (c < 68851i64) {
                            if (c < 68787i64) {
                                return 1i64;
                            }
                            if (c < 68800i64) {
                                return 0i64;
                            }
                            return 1i64;
                        }
                        if (c < 68858i64) {
                            return 0i64;
                        }
                        if (c < 68900i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 68966i64) {
                        if (c < 68922i64) {
                            return 1i64;
                        }
                        if (c < 68928i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 68975i64) {
                        return 0i64;
                    }
                    if (c < 68998i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 69457i64) {
                    if (c < 69314i64) {
                        if (c < 69290i64) {
                            if (c < 69247i64) {
                                return 1i64;
                            }
                            if (c < 69248i64) {
                                return 0i64;
                            }
                            return 1i64;
                        }
                        if (c < 69296i64) {
                            return 0i64;
                        }
                        if (c < 69298i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 69416i64) {
                        if (c < 69320i64) {
                            return 1i64;
                        }
                        if (c < 69376i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 69424i64) {
                        return 0i64;
                    }
                    if (c < 69446i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 69600i64) {
                    if (c < 69506i64) {
                        if (c < 69461i64) {
                            return 1i64;
                        }
                        if (c < 69488i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 69552i64) {
                        return 0i64;
                    }
                    if (c < 69580i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 69688i64) {
                    if (c < 69623i64) {
                        return 1i64;
                    }
                    if (c < 69635i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 69744i64) {
                    if (c < 69714i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 69745i64) {
                    return 0i64;
                }
                return 1i64;
            }
            if (c < 70085i64) {
                if (c < 69952i64) {
                    if (c < 69865i64) {
                        if (c < 69763i64) {
                            if (c < 69749i64) {
                                return 0i64;
                            }
                            if (c < 69750i64) {
                                return 1i64;
                            }
                            return 0i64;
                        }
                        if (c < 69808i64) {
                            return 1i64;
                        }
                        if (c < 69840i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 69891i64) {
                        if (c < 69872i64) {
                            return 0i64;
                        }
                        if (c < 69882i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 69927i64) {
                        return 1i64;
                    }
                    if (c < 69942i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 70003i64) {
                    if (c < 69959i64) {
                        if (c < 69956i64) {
                            return 0i64;
                        }
                        if (c < 69957i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 69960i64) {
                        return 1i64;
                    }
                    if (c < 69968i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 70019i64) {
                    if (c < 70006i64) {
                        return 0i64;
                    }
                    if (c < 70007i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 70067i64) {
                    return 1i64;
                }
                if (c < 70081i64) {
                    return 0i64;
                }
                return 1i64;
            }
            if (c < 70209i64) {
                if (c < 70133i64) {
                    if (c < 70108i64) {
                        if (c < 70096i64) {
                            return 0i64;
                        }
                        if (c < 70107i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 70109i64) {
                        return 1i64;
                    }
                    if (c < 70113i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 70163i64) {
                    if (c < 70144i64) {
                        return 0i64;
                    }
                    if (c < 70162i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 70188i64) {
                    return 1i64;
                }
                if (c < 70207i64) {
                    return 0i64;
                }
                return 1i64;
            }
            if (c < 70286i64) {
                if (c < 70280i64) {
                    if (c < 70272i64) {
                        return 0i64;
                    }
                    if (c < 70279i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 70281i64) {
                    return 1i64;
                }
                if (c < 70282i64) {
                    return 0i64;
                }
                return 1i64;
            }
            if (c < 70303i64) {
                if (c < 70287i64) {
                    return 0i64;
                }
                if (c < 70302i64) {
                    return 1i64;
                }
                return 0i64;
            }
            if (c < 70320i64) {
                if (c < 70313i64) {
                    return 1i64;
                }
                return 0i64;
            }
            if (c < 70367i64) {
                return 1i64;
            }
            return 0i64;
        }
        if (c < 70874i64) {
            if (c < 70542i64) {
                if (c < 70453i64) {
                    if (c < 70419i64) {
                        if (c < 70413i64) {
                            if (c < 70394i64) {
                                return 1i64;
                            }
                            if (c < 70405i64) {
                                return 0i64;
                            }
                            return 1i64;
                        }
                        if (c < 70415i64) {
                            return 0i64;
                        }
                        if (c < 70417i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 70449i64) {
                        if (c < 70441i64) {
                            return 1i64;
                        }
                        if (c < 70442i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 70450i64) {
                        return 0i64;
                    }
                    if (c < 70452i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 70493i64) {
                    if (c < 70462i64) {
                        if (c < 70458i64) {
                            return 1i64;
                        }
                        if (c < 70461i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 70480i64) {
                        return 0i64;
                    }
                    if (c < 70481i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 70538i64) {
                    if (c < 70498i64) {
                        return 1i64;
                    }
                    if (c < 70528i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 70539i64) {
                    return 0i64;
                }
                if (c < 70540i64) {
                    return 1i64;
                }
                return 0i64;
            }
            if (c < 70727i64) {
                if (c < 70609i64) {
                    if (c < 70582i64) {
                        if (c < 70543i64) {
                            return 1i64;
                        }
                        if (c < 70544i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 70583i64) {
                        return 0i64;
                    }
                    if (c < 70584i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 70612i64) {
                    if (c < 70610i64) {
                        return 1i64;
                    }
                    if (c < 70611i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 70656i64) {
                    return 0i64;
                }
                if (c < 70709i64) {
                    return 1i64;
                }
                return 0i64;
            }
            if (c < 70784i64) {
                if (c < 70746i64) {
                    if (c < 70731i64) {
                        return 1i64;
                    }
                    if (c < 70736i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 70751i64) {
                    return 0i64;
                }
                if (c < 70754i64) {
                    return 1i64;
                }
                return 0i64;
            }
            if (c < 70854i64) {
                if (c < 70832i64) {
                    return 1i64;
                }
                if (c < 70852i64) {
                    return 0i64;
                }
                return 1i64;
            }
            if (c < 70856i64) {
                if (c < 70855i64) {
                    return 0i64;
                }
                return 1i64;
            }
            if (c < 70864i64) {
                return 0i64;
            }
            return 1i64;
        }
        if (c < 71495i64) {
            if (c < 71339i64) {
                if (c < 71216i64) {
                    if (c < 71128i64) {
                        if (c < 71040i64) {
                            return 0i64;
                        }
                        if (c < 71087i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 71132i64) {
                        return 1i64;
                    }
                    if (c < 71168i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 71248i64) {
                    if (c < 71236i64) {
                        return 0i64;
                    }
                    if (c < 71237i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 71258i64) {
                    return 1i64;
                }
                if (c < 71296i64) {
                    return 0i64;
                }
                return 1i64;
            }
            if (c < 71396i64) {
                if (c < 71360i64) {
                    if (c < 71352i64) {
                        return 0i64;
                    }
                    if (c < 71353i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 71370i64) {
                    return 1i64;
                }
                if (c < 71376i64) {
                    return 0i64;
                }
                return 1i64;
            }
            if (c < 71472i64) {
                if (c < 71424i64) {
                    return 0i64;
                }
                if (c < 71451i64) {
                    return 1i64;
                }
                return 0i64;
            }
            if (c < 71484i64) {
                return 1i64;
            }
            if (c < 71488i64) {
                return 0i64;
            }
            return 1i64;
        }
        if (c < 71959i64) {
            if (c < 71943i64) {
                if (c < 71840i64) {
                    if (c < 71680i64) {
                        return 0i64;
                    }
                    if (c < 71724i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 71923i64) {
                    return 1i64;
                }
                if (c < 71935i64) {
                    return 0i64;
                }
                return 1i64;
            }
            if (c < 71948i64) {
                if (c < 71945i64) {
                    return 0i64;
                }
                if (c < 71946i64) {
                    return 1i64;
                }
                return 0i64;
            }
            if (c < 71956i64) {
                return 1i64;
            }
            if (c < 71957i64) {
                return 0i64;
            }
            return 1i64;
        }
        if (c < 72002i64) {
            if (c < 71999i64) {
                if (c < 71960i64) {
                    return 0i64;
                }
                if (c < 71984i64) {
                    return 1i64;
                }
                return 0i64;
            }
            if (c < 72000i64) {
                return 1i64;
            }
            if (c < 72001i64) {
                return 0i64;
            }
            return 1i64;
        }
        if (c < 72096i64) {
            if (c < 72016i64) {
                return 0i64;
            }
            if (c < 72026i64) {
                return 1i64;
            }
            return 0i64;
        }
        if (c < 72106i64) {
            if (c < 72104i64) {
                return 1i64;
            }
            return 0i64;
        }
        if (c < 72145i64) {
            return 1i64;
        }
        return 0i64;
    }
    if (c < 120071i64) {
        if (c < 92864i64) {
            if (c < 73113i64) {
                if (c < 72714i64) {
                    if (c < 72284i64) {
                        if (c < 72203i64) {
                            if (c < 72164i64) {
                                if (c < 72162i64) {
                                    return 1i64;
                                }
                                if (c < 72163i64) {
                                    return 0i64;
                                }
                                return 1i64;
                            }
                            if (c < 72192i64) {
                                return 0i64;
                            }
                            if (c < 72193i64) {
                                return 1i64;
                            }
                            return 0i64;
                        }
                        if (c < 72251i64) {
                            if (c < 72243i64) {
                                return 1i64;
                            }
                            if (c < 72250i64) {
                                return 0i64;
                            }
                            return 1i64;
                        }
                        if (c < 72272i64) {
                            return 0i64;
                        }
                        if (c < 72273i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 72640i64) {
                        if (c < 72350i64) {
                            if (c < 72330i64) {
                                return 1i64;
                            }
                            if (c < 72349i64) {
                                return 0i64;
                            }
                            return 1i64;
                        }
                        if (c < 72368i64) {
                            return 0i64;
                        }
                        if (c < 72441i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 72698i64) {
                        if (c < 72673i64) {
                            return 1i64;
                        }
                        if (c < 72688i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 72704i64) {
                        return 0i64;
                    }
                    if (c < 72713i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 72971i64) {
                    if (c < 72818i64) {
                        if (c < 72769i64) {
                            if (c < 72751i64) {
                                return 1i64;
                            }
                            if (c < 72768i64) {
                                return 0i64;
                            }
                            return 1i64;
                        }
                        if (c < 72784i64) {
                            return 0i64;
                        }
                        if (c < 72813i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 72967i64) {
                        if (c < 72848i64) {
                            return 1i64;
                        }
                        if (c < 72960i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 72968i64) {
                        return 0i64;
                    }
                    if (c < 72970i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 73056i64) {
                    if (c < 73031i64) {
                        if (c < 73009i64) {
                            return 1i64;
                        }
                        if (c < 73030i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 73040i64) {
                        return 0i64;
                    }
                    if (c < 73050i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 73065i64) {
                    if (c < 73062i64) {
                        return 1i64;
                    }
                    if (c < 73063i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 73098i64) {
                    if (c < 73066i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 73112i64) {
                    return 0i64;
                }
                return 1i64;
            }
            if (c < 74863i64) {
                if (c < 73489i64) {
                    if (c < 73194i64) {
                        if (c < 73136i64) {
                            if (c < 73120i64) {
                                return 0i64;
                            }
                            if (c < 73130i64) {
                                return 1i64;
                            }
                            return 0i64;
                        }
                        if (c < 73180i64) {
                            return 1i64;
                        }
                        if (c < 73184i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 73474i64) {
                        if (c < 73440i64) {
                            return 0i64;
                        }
                        if (c < 73459i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 73475i64) {
                        return 1i64;
                    }
                    if (c < 73476i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 73649i64) {
                    if (c < 73552i64) {
                        if (c < 73490i64) {
                            return 0i64;
                        }
                        if (c < 73524i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 73562i64) {
                        return 1i64;
                    }
                    if (c < 73648i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 73728i64) {
                    if (c < 73664i64) {
                        return 0i64;
                    }
                    if (c < 73685i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 74650i64) {
                    return 1i64;
                }
                if (c < 74752i64) {
                    return 0i64;
                }
                return 1i64;
            }
            if (c < 83527i64) {
                if (c < 78896i64) {
                    if (c < 77712i64) {
                        if (c < 74880i64) {
                            return 0i64;
                        }
                        if (c < 75076i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 77809i64) {
                        return 1i64;
                    }
                    if (c < 77824i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 78944i64) {
                    if (c < 78913i64) {
                        return 0i64;
                    }
                    if (c < 78919i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 82939i64) {
                    return 1i64;
                }
                if (c < 82944i64) {
                    return 0i64;
                }
                return 1i64;
            }
            if (c < 92729i64) {
                if (c < 90416i64) {
                    if (c < 90368i64) {
                        return 0i64;
                    }
                    if (c < 90398i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 90426i64) {
                    return 1i64;
                }
                if (c < 92160i64) {
                    return 0i64;
                }
                return 1i64;
            }
            if (c < 92768i64) {
                if (c < 92736i64) {
                    return 0i64;
                }
                if (c < 92767i64) {
                    return 1i64;
                }
                return 0i64;
            }
            if (c < 92784i64) {
                if (c < 92778i64) {
                    return 1i64;
                }
                return 0i64;
            }
            if (c < 92863i64) {
                return 1i64;
            }
            return 0i64;
        }
        if (c < 110591i64) {
            if (c < 93883i64) {
                if (c < 93027i64) {
                    if (c < 92992i64) {
                        if (c < 92910i64) {
                            if (c < 92874i64) {
                                return 1i64;
                            }
                            if (c < 92880i64) {
                                return 0i64;
                            }
                            return 1i64;
                        }
                        if (c < 92928i64) {
                            return 0i64;
                        }
                        if (c < 92976i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 93018i64) {
                        if (c < 92996i64) {
                            return 1i64;
                        }
                        if (c < 93008i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 93019i64) {
                        return 0i64;
                    }
                    if (c < 93026i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 93552i64) {
                    if (c < 93072i64) {
                        if (c < 93048i64) {
                            return 1i64;
                        }
                        if (c < 93053i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 93504i64) {
                        return 0i64;
                    }
                    if (c < 93549i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 93847i64) {
                    if (c < 93562i64) {
                        return 1i64;
                    }
                    if (c < 93760i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 93856i64) {
                    return 0i64;
                }
                if (c < 93881i64) {
                    return 1i64;
                }
                return 0i64;
            }
            if (c < 94194i64) {
                if (c < 94099i64) {
                    if (c < 94027i64) {
                        if (c < 93908i64) {
                            return 1i64;
                        }
                        if (c < 93952i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 94032i64) {
                        return 0i64;
                    }
                    if (c < 94033i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 94178i64) {
                    if (c < 94112i64) {
                        return 1i64;
                    }
                    if (c < 94176i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 94179i64) {
                    return 0i64;
                }
                if (c < 94180i64) {
                    return 2i64;
                }
                return 0i64;
            }
            if (c < 101760i64) {
                if (c < 101590i64) {
                    if (c < 94199i64) {
                        return 2i64;
                    }
                    if (c < 94208i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 101631i64) {
                    return 0i64;
                }
                if (c < 101663i64) {
                    return 1i64;
                }
                return 0i64;
            }
            if (c < 110580i64) {
                if (c < 101875i64) {
                    return 1i64;
                }
                if (c < 110576i64) {
                    return 0i64;
                }
                return 2i64;
            }
            if (c < 110588i64) {
                if (c < 110581i64) {
                    return 0i64;
                }
                return 2i64;
            }
            if (c < 110589i64) {
                return 0i64;
            }
            return 2i64;
        }
        if (c < 119508i64) {
            if (c < 111356i64) {
                if (c < 110931i64) {
                    if (c < 110898i64) {
                        if (c < 110592i64) {
                            return 0i64;
                        }
                        if (c < 110883i64) {
                            return 2i64;
                        }
                        return 0i64;
                    }
                    if (c < 110899i64) {
                        return 2i64;
                    }
                    if (c < 110928i64) {
                        return 0i64;
                    }
                    return 2i64;
                }
                if (c < 110948i64) {
                    if (c < 110933i64) {
                        return 0i64;
                    }
                    if (c < 110934i64) {
                        return 2i64;
                    }
                    return 0i64;
                }
                if (c < 110952i64) {
                    return 2i64;
                }
                if (c < 110960i64) {
                    return 0i64;
                }
                return 1i64;
            }
            if (c < 113801i64) {
                if (c < 113776i64) {
                    if (c < 113664i64) {
                        return 0i64;
                    }
                    if (c < 113771i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 113789i64) {
                    return 1i64;
                }
                if (c < 113792i64) {
                    return 0i64;
                }
                return 1i64;
            }
            if (c < 118000i64) {
                if (c < 113808i64) {
                    return 0i64;
                }
                if (c < 113818i64) {
                    return 1i64;
                }
                return 0i64;
            }
            if (c < 118010i64) {
                return 1i64;
            }
            if (c < 119488i64) {
                return 0i64;
            }
            return 1i64;
        }
        if (c < 119971i64) {
            if (c < 119893i64) {
                if (c < 119648i64) {
                    if (c < 119520i64) {
                        return 0i64;
                    }
                    if (c < 119540i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 119673i64) {
                    return 1i64;
                }
                if (c < 119808i64) {
                    return 0i64;
                }
                return 1i64;
            }
            if (c < 119966i64) {
                if (c < 119894i64) {
                    return 0i64;
                }
                if (c < 119965i64) {
                    return 1i64;
                }
                return 0i64;
            }
            if (c < 119968i64) {
                return 1i64;
            }
            if (c < 119970i64) {
                return 0i64;
            }
            return 1i64;
        }
        if (c < 119994i64) {
            if (c < 119977i64) {
                if (c < 119973i64) {
                    return 0i64;
                }
                if (c < 119975i64) {
                    return 1i64;
                }
                return 0i64;
            }
            if (c < 119981i64) {
                return 1i64;
            }
            if (c < 119982i64) {
                return 0i64;
            }
            return 1i64;
        }
        if (c < 119997i64) {
            if (c < 119995i64) {
                return 0i64;
            }
            if (c < 119996i64) {
                return 1i64;
            }
            return 0i64;
        }
        if (c < 120005i64) {
            if (c < 120004i64) {
                return 1i64;
            }
            return 0i64;
        }
        if (c < 120070i64) {
            return 1i64;
        }
        return 0i64;
    }
    if (c < 125264i64) {
        if (c < 123181i64) {
            if (c < 120572i64) {
                if (c < 120134i64) {
                    if (c < 120094i64) {
                        if (c < 120085i64) {
                            if (c < 120075i64) {
                                return 1i64;
                            }
                            if (c < 120077i64) {
                                return 0i64;
                            }
                            return 1i64;
                        }
                        if (c < 120086i64) {
                            return 0i64;
                        }
                        if (c < 120093i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 120127i64) {
                        if (c < 120122i64) {
                            return 1i64;
                        }
                        if (c < 120123i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 120128i64) {
                        return 0i64;
                    }
                    if (c < 120133i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 120488i64) {
                    if (c < 120145i64) {
                        if (c < 120135i64) {
                            return 1i64;
                        }
                        if (c < 120138i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 120146i64) {
                        return 0i64;
                    }
                    if (c < 120486i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 120539i64) {
                    if (c < 120513i64) {
                        return 1i64;
                    }
                    if (c < 120514i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 120540i64) {
                    return 0i64;
                }
                if (c < 120571i64) {
                    return 1i64;
                }
                return 0i64;
            }
            if (c < 120746i64) {
                if (c < 120656i64) {
                    if (c < 120629i64) {
                        if (c < 120597i64) {
                            return 1i64;
                        }
                        if (c < 120598i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 120630i64) {
                        return 0i64;
                    }
                    if (c < 120655i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 120713i64) {
                    if (c < 120687i64) {
                        return 1i64;
                    }
                    if (c < 120688i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 120714i64) {
                    return 0i64;
                }
                if (c < 120745i64) {
                    return 1i64;
                }
                return 0i64;
            }
            if (c < 122624i64) {
                if (c < 120780i64) {
                    if (c < 120771i64) {
                        return 1i64;
                    }
                    if (c < 120772i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 120782i64) {
                    return 0i64;
                }
                if (c < 120832i64) {
                    return 1i64;
                }
                return 0i64;
            }
            if (c < 122667i64) {
                if (c < 122655i64) {
                    return 1i64;
                }
                if (c < 122661i64) {
                    return 0i64;
                }
                return 1i64;
            }
            if (c < 122990i64) {
                if (c < 122928i64) {
                    return 0i64;
                }
                return 1i64;
            }
            if (c < 123136i64) {
                return 0i64;
            }
            return 1i64;
        }
        if (c < 124643i64) {
            if (c < 123642i64) {
                if (c < 123215i64) {
                    if (c < 123200i64) {
                        if (c < 123191i64) {
                            return 0i64;
                        }
                        if (c < 123198i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 123210i64) {
                        return 1i64;
                    }
                    if (c < 123214i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 123584i64) {
                    if (c < 123536i64) {
                        return 0i64;
                    }
                    if (c < 123566i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 123628i64) {
                    return 1i64;
                }
                if (c < 123632i64) {
                    return 0i64;
                }
                return 1i64;
            }
            if (c < 124398i64) {
                if (c < 124144i64) {
                    if (c < 124112i64) {
                        return 0i64;
                    }
                    if (c < 124140i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 124154i64) {
                    return 1i64;
                }
                if (c < 124368i64) {
                    return 0i64;
                }
                return 1i64;
            }
            if (c < 124608i64) {
                if (c < 124400i64) {
                    return 0i64;
                }
                if (c < 124411i64) {
                    return 1i64;
                }
                return 0i64;
            }
            if (c < 124639i64) {
                return 1i64;
            }
            if (c < 124640i64) {
                return 0i64;
            }
            return 1i64;
        }
        if (c < 124908i64) {
            if (c < 124661i64) {
                if (c < 124647i64) {
                    if (c < 124644i64) {
                        return 0i64;
                    }
                    if (c < 124646i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 124654i64) {
                    return 1i64;
                }
                if (c < 124656i64) {
                    return 0i64;
                }
                return 1i64;
            }
            if (c < 124896i64) {
                if (c < 124670i64) {
                    return 0i64;
                }
                if (c < 124672i64) {
                    return 1i64;
                }
                return 0i64;
            }
            if (c < 124903i64) {
                return 1i64;
            }
            if (c < 124904i64) {
                return 0i64;
            }
            return 1i64;
        }
        if (c < 125125i64) {
            if (c < 124912i64) {
                if (c < 124909i64) {
                    return 0i64;
                }
                if (c < 124911i64) {
                    return 1i64;
                }
                return 0i64;
            }
            if (c < 124927i64) {
                return 1i64;
            }
            if (c < 124928i64) {
                return 0i64;
            }
            return 1i64;
        }
        if (c < 125184i64) {
            if (c < 125127i64) {
                return 0i64;
            }
            if (c < 125136i64) {
                return 1i64;
            }
            return 0i64;
        }
        if (c < 125259i64) {
            if (c < 125252i64) {
                return 1i64;
            }
            return 0i64;
        }
        if (c < 125260i64) {
            return 1i64;
        }
        return 0i64;
    }
    if (c < 126556i64) {
        if (c < 126516i64) {
            if (c < 126464i64) {
                if (c < 126129i64) {
                    if (c < 126124i64) {
                        if (c < 125274i64) {
                            return 1i64;
                        }
                        if (c < 126065i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 126125i64) {
                        return 0i64;
                    }
                    if (c < 126128i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 126254i64) {
                    if (c < 126133i64) {
                        return 1i64;
                    }
                    if (c < 126209i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 126255i64) {
                    return 0i64;
                }
                if (c < 126270i64) {
                    return 1i64;
                }
                return 0i64;
            }
            if (c < 126500i64) {
                if (c < 126496i64) {
                    if (c < 126468i64) {
                        return 1i64;
                    }
                    if (c < 126469i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 126497i64) {
                    return 0i64;
                }
                if (c < 126499i64) {
                    return 1i64;
                }
                return 0i64;
            }
            if (c < 126504i64) {
                if (c < 126501i64) {
                    return 1i64;
                }
                if (c < 126503i64) {
                    return 0i64;
                }
                return 1i64;
            }
            if (c < 126505i64) {
                return 0i64;
            }
            if (c < 126515i64) {
                return 1i64;
            }
            return 0i64;
        }
        if (c < 126539i64) {
            if (c < 126530i64) {
                if (c < 126522i64) {
                    if (c < 126520i64) {
                        return 1i64;
                    }
                    if (c < 126521i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 126523i64) {
                    return 0i64;
                }
                if (c < 126524i64) {
                    return 1i64;
                }
                return 0i64;
            }
            if (c < 126536i64) {
                if (c < 126531i64) {
                    return 1i64;
                }
                if (c < 126535i64) {
                    return 0i64;
                }
                return 1i64;
            }
            if (c < 126537i64) {
                return 0i64;
            }
            if (c < 126538i64) {
                return 1i64;
            }
            return 0i64;
        }
        if (c < 126548i64) {
            if (c < 126544i64) {
                if (c < 126540i64) {
                    return 1i64;
                }
                if (c < 126541i64) {
                    return 0i64;
                }
                return 1i64;
            }
            if (c < 126545i64) {
                return 0i64;
            }
            if (c < 126547i64) {
                return 1i64;
            }
            return 0i64;
        }
        if (c < 126552i64) {
            if (c < 126549i64) {
                return 1i64;
            }
            if (c < 126551i64) {
                return 0i64;
            }
            return 1i64;
        }
        if (c < 126554i64) {
            if (c < 126553i64) {
                return 0i64;
            }
            return 1i64;
        }
        if (c < 126555i64) {
            return 0i64;
        }
        return 1i64;
    }
    if (c < 126628i64) {
        if (c < 126579i64) {
            if (c < 126563i64) {
                if (c < 126559i64) {
                    if (c < 126557i64) {
                        return 0i64;
                    }
                    if (c < 126558i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 126560i64) {
                    return 1i64;
                }
                if (c < 126561i64) {
                    return 0i64;
                }
                return 1i64;
            }
            if (c < 126567i64) {
                if (c < 126564i64) {
                    return 0i64;
                }
                if (c < 126565i64) {
                    return 1i64;
                }
                return 0i64;
            }
            if (c < 126571i64) {
                return 1i64;
            }
            if (c < 126572i64) {
                return 0i64;
            }
            return 1i64;
        }
        if (c < 126591i64) {
            if (c < 126585i64) {
                if (c < 126580i64) {
                    return 0i64;
                }
                if (c < 126584i64) {
                    return 1i64;
                }
                return 0i64;
            }
            if (c < 126589i64) {
                return 1i64;
            }
            if (c < 126590i64) {
                return 0i64;
            }
            return 1i64;
        }
        if (c < 126603i64) {
            if (c < 126592i64) {
                return 0i64;
            }
            if (c < 126602i64) {
                return 1i64;
            }
            return 0i64;
        }
        if (c < 126620i64) {
            return 1i64;
        }
        if (c < 126625i64) {
            return 0i64;
        }
        return 1i64;
    }
    if (c < 178206i64) {
        if (c < 127245i64) {
            if (c < 126635i64) {
                if (c < 126629i64) {
                    return 0i64;
                }
                if (c < 126634i64) {
                    return 1i64;
                }
                return 0i64;
            }
            if (c < 126652i64) {
                return 1i64;
            }
            if (c < 127232i64) {
                return 0i64;
            }
            return 1i64;
        }
        if (c < 131072i64) {
            if (c < 130032i64) {
                return 0i64;
            }
            if (c < 130042i64) {
                return 1i64;
            }
            return 0i64;
        }
        if (c < 173792i64) {
            return 2i64;
        }
        if (c < 173824i64) {
            return 0i64;
        }
        return 2i64;
    }
    if (c < 192094i64) {
        if (c < 183984i64) {
            if (c < 178208i64) {
                return 0i64;
            }
            if (c < 183982i64) {
                return 2i64;
            }
            return 0i64;
        }
        if (c < 191457i64) {
            return 2i64;
        }
        if (c < 191472i64) {
            return 0i64;
        }
        return 2i64;
    }
    if (c < 196608i64) {
        if (c < 194560i64) {
            return 0i64;
        }
        if (c < 195102i64) {
            return 2i64;
        }
        return 0i64;
    }
    if (c < 201552i64) {
        if (c < 201547i64) {
            return 2i64;
        }
        return 0i64;
    }
    if (c < 210042i64) {
        return 2i64;
    }
    return 0i64;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_2_ct(c: i64) -> i64 {
    if (c < 42786i64) {
        if (c < 4193i64) {
            if (c < 2501i64) {
                if (c < 1470i64) {
                    if (c < 452i64) {
                        if (c < 173i64) {
                            if (c < 94i64) {
                                if (c < 47i64) {
                                    if (c < 40i64) {
                                        if (c < 39i64) {
                                            return 0i64;
                                        }
                                        return 2i64;
                                    }
                                    if (c < 46i64) {
                                        return 0i64;
                                    }
                                    return 2i64;
                                }
                                if (c < 59i64) {
                                    if (c < 58i64) {
                                        return 0i64;
                                    }
                                    return 2i64;
                                }
                                if (c < 65i64) {
                                    return 0i64;
                                }
                                if (c < 91i64) {
                                    return 1i64;
                                }
                                return 0i64;
                            }
                            if (c < 123i64) {
                                if (c < 96i64) {
                                    if (c < 95i64) {
                                        return 2i64;
                                    }
                                    return 0i64;
                                }
                                if (c < 97i64) {
                                    return 2i64;
                                }
                                return 1i64;
                            }
                            if (c < 169i64) {
                                if (c < 168i64) {
                                    return 0i64;
                                }
                                return 2i64;
                            }
                            if (c < 170i64) {
                                return 0i64;
                            }
                            if (c < 171i64) {
                                return 1i64;
                            }
                            return 0i64;
                        }
                        if (c < 186i64) {
                            if (c < 180i64) {
                                if (c < 175i64) {
                                    if (c < 174i64) {
                                        return 2i64;
                                    }
                                    return 0i64;
                                }
                                if (c < 176i64) {
                                    return 2i64;
                                }
                                return 0i64;
                            }
                            if (c < 182i64) {
                                if (c < 181i64) {
                                    return 2i64;
                                }
                                return 1i64;
                            }
                            if (c < 183i64) {
                                return 0i64;
                            }
                            if (c < 185i64) {
                                return 2i64;
                            }
                            return 0i64;
                        }
                        if (c < 247i64) {
                            if (c < 192i64) {
                                if (c < 187i64) {
                                    return 1i64;
                                }
                                return 0i64;
                            }
                            if (c < 215i64) {
                                return 1i64;
                            }
                            if (c < 216i64) {
                                return 0i64;
                            }
                            return 1i64;
                        }
                        if (c < 443i64) {
                            if (c < 248i64) {
                                return 0i64;
                            }
                            return 1i64;
                        }
                        if (c < 444i64) {
                            return 0i64;
                        }
                        if (c < 448i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 908i64) {
                        if (c < 891i64) {
                            if (c < 880i64) {
                                if (c < 662i64) {
                                    if (c < 660i64) {
                                        return 1i64;
                                    }
                                    return 0i64;
                                }
                                if (c < 688i64) {
                                    return 1i64;
                                }
                                return 2i64;
                            }
                            if (c < 886i64) {
                                if (c < 884i64) {
                                    return 1i64;
                                }
                                return 2i64;
                            }
                            if (c < 888i64) {
                                return 1i64;
                            }
                            if (c < 890i64) {
                                return 0i64;
                            }
                            return 2i64;
                        }
                        if (c < 900i64) {
                            if (c < 895i64) {
                                if (c < 894i64) {
                                    return 1i64;
                                }
                                return 0i64;
                            }
                            if (c < 896i64) {
                                return 1i64;
                            }
                            return 0i64;
                        }
                        if (c < 903i64) {
                            if (c < 902i64) {
                                return 2i64;
                            }
                            return 1i64;
                        }
                        if (c < 904i64) {
                            return 2i64;
                        }
                        if (c < 907i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 1162i64) {
                        if (c < 931i64) {
                            if (c < 910i64) {
                                if (c < 909i64) {
                                    return 1i64;
                                }
                                return 0i64;
                            }
                            if (c < 930i64) {
                                return 1i64;
                            }
                            return 0i64;
                        }
                        if (c < 1015i64) {
                            if (c < 1014i64) {
                                return 1i64;
                            }
                            return 0i64;
                        }
                        if (c < 1154i64) {
                            return 1i64;
                        }
                        if (c < 1155i64) {
                            return 0i64;
                        }
                        return 2i64;
                    }
                    if (c < 1370i64) {
                        if (c < 1329i64) {
                            if (c < 1328i64) {
                                return 1i64;
                            }
                            return 0i64;
                        }
                        if (c < 1367i64) {
                            return 1i64;
                        }
                        if (c < 1369i64) {
                            return 0i64;
                        }
                        return 2i64;
                    }
                    if (c < 1376i64) {
                        if (c < 1375i64) {
                            return 0i64;
                        }
                        return 2i64;
                    }
                    if (c < 1417i64) {
                        return 1i64;
                    }
                    if (c < 1425i64) {
                        return 0i64;
                    }
                    return 2i64;
                }
                if (c < 2027i64) {
                    if (c < 1601i64) {
                        if (c < 1524i64) {
                            if (c < 1475i64) {
                                if (c < 1472i64) {
                                    if (c < 1471i64) {
                                        return 0i64;
                                    }
                                    return 2i64;
                                }
                                if (c < 1473i64) {
                                    return 0i64;
                                }
                                return 2i64;
                            }
                            if (c < 1478i64) {
                                if (c < 1476i64) {
                                    return 0i64;
                                }
                                return 2i64;
                            }
                            if (c < 1479i64) {
                                return 0i64;
                            }
                            if (c < 1480i64) {
                                return 2i64;
                            }
                            return 0i64;
                        }
                        if (c < 1552i64) {
                            if (c < 1536i64) {
                                if (c < 1525i64) {
                                    return 2i64;
                                }
                                return 0i64;
                            }
                            if (c < 1542i64) {
                                return 2i64;
                            }
                            return 0i64;
                        }
                        if (c < 1564i64) {
                            if (c < 1563i64) {
                                return 2i64;
                            }
                            return 0i64;
                        }
                        if (c < 1565i64) {
                            return 2i64;
                        }
                        if (c < 1600i64) {
                            return 0i64;
                        }
                        return 2i64;
                    }
                    if (c < 1770i64) {
                        if (c < 1649i64) {
                            if (c < 1632i64) {
                                if (c < 1611i64) {
                                    return 0i64;
                                }
                                return 2i64;
                            }
                            if (c < 1648i64) {
                                return 0i64;
                            }
                            return 2i64;
                        }
                        if (c < 1758i64) {
                            if (c < 1750i64) {
                                return 0i64;
                            }
                            return 2i64;
                        }
                        if (c < 1759i64) {
                            return 0i64;
                        }
                        if (c < 1769i64) {
                            return 2i64;
                        }
                        return 0i64;
                    }
                    if (c < 1810i64) {
                        if (c < 1807i64) {
                            if (c < 1774i64) {
                                return 2i64;
                            }
                            return 0i64;
                        }
                        if (c < 1808i64) {
                            return 2i64;
                        }
                        if (c < 1809i64) {
                            return 0i64;
                        }
                        return 2i64;
                    }
                    if (c < 1867i64) {
                        if (c < 1840i64) {
                            return 0i64;
                        }
                        return 2i64;
                    }
                    if (c < 1958i64) {
                        return 0i64;
                    }
                    if (c < 1969i64) {
                        return 2i64;
                    }
                    return 0i64;
                }
                if (c < 2362i64) {
                    if (c < 2140i64) {
                        if (c < 2045i64) {
                            if (c < 2042i64) {
                                if (c < 2038i64) {
                                    return 2i64;
                                }
                                return 0i64;
                            }
                            if (c < 2043i64) {
                                return 2i64;
                            }
                            return 0i64;
                        }
                        if (c < 2070i64) {
                            if (c < 2046i64) {
                                return 2i64;
                            }
                            return 0i64;
                        }
                        if (c < 2094i64) {
                            return 2i64;
                        }
                        if (c < 2137i64) {
                            return 0i64;
                        }
                        return 2i64;
                    }
                    if (c < 2194i64) {
                        if (c < 2185i64) {
                            if (c < 2184i64) {
                                return 0i64;
                            }
                            return 2i64;
                        }
                        if (c < 2192i64) {
                            return 0i64;
                        }
                        return 2i64;
                    }
                    if (c < 2208i64) {
                        if (c < 2199i64) {
                            return 0i64;
                        }
                        return 2i64;
                    }
                    if (c < 2249i64) {
                        return 0i64;
                    }
                    if (c < 2307i64) {
                        return 2i64;
                    }
                    return 0i64;
                }
                if (c < 2392i64) {
                    if (c < 2369i64) {
                        if (c < 2364i64) {
                            if (c < 2363i64) {
                                return 2i64;
                            }
                            return 0i64;
                        }
                        if (c < 2365i64) {
                            return 2i64;
                        }
                        return 0i64;
                    }
                    if (c < 2381i64) {
                        if (c < 2377i64) {
                            return 2i64;
                        }
                        return 0i64;
                    }
                    if (c < 2382i64) {
                        return 2i64;
                    }
                    if (c < 2385i64) {
                        return 0i64;
                    }
                    return 2i64;
                }
                if (c < 2433i64) {
                    if (c < 2404i64) {
                        if (c < 2402i64) {
                            return 0i64;
                        }
                        return 2i64;
                    }
                    if (c < 2417i64) {
                        return 0i64;
                    }
                    if (c < 2418i64) {
                        return 2i64;
                    }
                    return 0i64;
                }
                if (c < 2492i64) {
                    if (c < 2434i64) {
                        return 2i64;
                    }
                    return 0i64;
                }
                if (c < 2493i64) {
                    return 2i64;
                }
                if (c < 2497i64) {
                    return 0i64;
                }
                return 2i64;
            }
            if (c < 3202i64) {
                if (c < 2817i64) {
                    if (c < 2642i64) {
                        if (c < 2620i64) {
                            if (c < 2532i64) {
                                if (c < 2510i64) {
                                    if (c < 2509i64) {
                                        return 0i64;
                                    }
                                    return 2i64;
                                }
                                if (c < 2530i64) {
                                    return 0i64;
                                }
                                return 2i64;
                            }
                            if (c < 2559i64) {
                                if (c < 2558i64) {
                                    return 0i64;
                                }
                                return 2i64;
                            }
                            if (c < 2561i64) {
                                return 0i64;
                            }
                            if (c < 2563i64) {
                                return 2i64;
                            }
                            return 0i64;
                        }
                        if (c < 2631i64) {
                            if (c < 2625i64) {
                                if (c < 2621i64) {
                                    return 2i64;
                                }
                                return 0i64;
                            }
                            if (c < 2627i64) {
                                return 2i64;
                            }
                            return 0i64;
                        }
                        if (c < 2635i64) {
                            if (c < 2633i64) {
                                return 2i64;
                            }
                            return 0i64;
                        }
                        if (c < 2638i64) {
                            return 2i64;
                        }
                        if (c < 2641i64) {
                            return 0i64;
                        }
                        return 2i64;
                    }
                    if (c < 2753i64) {
                        if (c < 2678i64) {
                            if (c < 2674i64) {
                                if (c < 2672i64) {
                                    return 0i64;
                                }
                                return 2i64;
                            }
                            if (c < 2677i64) {
                                return 0i64;
                            }
                            return 2i64;
                        }
                        if (c < 2691i64) {
                            if (c < 2689i64) {
                                return 0i64;
                            }
                            return 2i64;
                        }
                        if (c < 2748i64) {
                            return 0i64;
                        }
                        if (c < 2749i64) {
                            return 2i64;
                        }
                        return 0i64;
                    }
                    if (c < 2766i64) {
                        if (c < 2759i64) {
                            if (c < 2758i64) {
                                return 2i64;
                            }
                            return 0i64;
                        }
                        if (c < 2761i64) {
                            return 2i64;
                        }
                        if (c < 2765i64) {
                            return 0i64;
                        }
                        return 2i64;
                    }
                    if (c < 2788i64) {
                        if (c < 2786i64) {
                            return 0i64;
                        }
                        return 2i64;
                    }
                    if (c < 2810i64) {
                        return 0i64;
                    }
                    if (c < 2816i64) {
                        return 2i64;
                    }
                    return 0i64;
                }
                if (c < 3021i64) {
                    if (c < 2894i64) {
                        if (c < 2879i64) {
                            if (c < 2876i64) {
                                if (c < 2818i64) {
                                    return 2i64;
                                }
                                return 0i64;
                            }
                            if (c < 2877i64) {
                                return 2i64;
                            }
                            return 0i64;
                        }
                        if (c < 2881i64) {
                            if (c < 2880i64) {
                                return 2i64;
                            }
                            return 0i64;
                        }
                        if (c < 2885i64) {
                            return 2i64;
                        }
                        if (c < 2893i64) {
                            return 0i64;
                        }
                        return 2i64;
                    }
                    if (c < 2916i64) {
                        if (c < 2903i64) {
                            if (c < 2901i64) {
                                return 0i64;
                            }
                            return 2i64;
                        }
                        if (c < 2914i64) {
                            return 0i64;
                        }
                        return 2i64;
                    }
                    if (c < 2947i64) {
                        if (c < 2946i64) {
                            return 0i64;
                        }
                        return 2i64;
                    }
                    if (c < 3008i64) {
                        return 0i64;
                    }
                    if (c < 3009i64) {
                        return 2i64;
                    }
                    return 0i64;
                }
                if (c < 3137i64) {
                    if (c < 3076i64) {
                        if (c < 3072i64) {
                            if (c < 3022i64) {
                                return 2i64;
                            }
                            return 0i64;
                        }
                        if (c < 3073i64) {
                            return 2i64;
                        }
                        return 0i64;
                    }
                    if (c < 3132i64) {
                        if (c < 3077i64) {
                            return 2i64;
                        }
                        return 0i64;
                    }
                    if (c < 3133i64) {
                        return 2i64;
                    }
                    if (c < 3134i64) {
                        return 0i64;
                    }
                    return 2i64;
                }
                if (c < 3157i64) {
                    if (c < 3145i64) {
                        if (c < 3142i64) {
                            return 0i64;
                        }
                        return 2i64;
                    }
                    if (c < 3146i64) {
                        return 0i64;
                    }
                    if (c < 3150i64) {
                        return 2i64;
                    }
                    return 0i64;
                }
                if (c < 3170i64) {
                    if (c < 3159i64) {
                        return 2i64;
                    }
                    return 0i64;
                }
                if (c < 3172i64) {
                    return 2i64;
                }
                if (c < 3201i64) {
                    return 0i64;
                }
                return 2i64;
            }
            if (c < 3764i64) {
                if (c < 3406i64) {
                    if (c < 3298i64) {
                        if (c < 3264i64) {
                            if (c < 3261i64) {
                                if (c < 3260i64) {
                                    return 0i64;
                                }
                                return 2i64;
                            }
                            if (c < 3263i64) {
                                return 0i64;
                            }
                            return 2i64;
                        }
                        if (c < 3271i64) {
                            if (c < 3270i64) {
                                return 0i64;
                            }
                            return 2i64;
                        }
                        if (c < 3276i64) {
                            return 0i64;
                        }
                        if (c < 3278i64) {
                            return 2i64;
                        }
                        return 0i64;
                    }
                    if (c < 3387i64) {
                        if (c < 3328i64) {
                            if (c < 3300i64) {
                                return 2i64;
                            }
                            return 0i64;
                        }
                        if (c < 3330i64) {
                            return 2i64;
                        }
                        return 0i64;
                    }
                    if (c < 3393i64) {
                        if (c < 3389i64) {
                            return 2i64;
                        }
                        return 0i64;
                    }
                    if (c < 3397i64) {
                        return 2i64;
                    }
                    if (c < 3405i64) {
                        return 0i64;
                    }
                    return 2i64;
                }
                if (c < 3542i64) {
                    if (c < 3458i64) {
                        if (c < 3428i64) {
                            if (c < 3426i64) {
                                return 0i64;
                            }
                            return 2i64;
                        }
                        if (c < 3457i64) {
                            return 0i64;
                        }
                        return 2i64;
                    }
                    if (c < 3531i64) {
                        if (c < 3530i64) {
                            return 0i64;
                        }
                        return 2i64;
                    }
                    if (c < 3538i64) {
                        return 0i64;
                    }
                    if (c < 3541i64) {
                        return 2i64;
                    }
                    return 0i64;
                }
                if (c < 3643i64) {
                    if (c < 3633i64) {
                        if (c < 3543i64) {
                            return 2i64;
                        }
                        return 0i64;
                    }
                    if (c < 3634i64) {
                        return 2i64;
                    }
                    if (c < 3636i64) {
                        return 0i64;
                    }
                    return 2i64;
                }
                if (c < 3663i64) {
                    if (c < 3654i64) {
                        return 0i64;
                    }
                    return 2i64;
                }
                if (c < 3761i64) {
                    return 0i64;
                }
                if (c < 3762i64) {
                    return 2i64;
                }
                return 0i64;
            }
            if (c < 3974i64) {
                if (c < 3894i64) {
                    if (c < 3784i64) {
                        if (c < 3782i64) {
                            if (c < 3773i64) {
                                return 2i64;
                            }
                            return 0i64;
                        }
                        if (c < 3783i64) {
                            return 2i64;
                        }
                        return 0i64;
                    }
                    if (c < 3864i64) {
                        if (c < 3791i64) {
                            return 2i64;
                        }
                        return 0i64;
                    }
                    if (c < 3866i64) {
                        return 2i64;
                    }
                    if (c < 3893i64) {
                        return 0i64;
                    }
                    return 2i64;
                }
                if (c < 3898i64) {
                    if (c < 3896i64) {
                        if (c < 3895i64) {
                            return 0i64;
                        }
                        return 2i64;
                    }
                    if (c < 3897i64) {
                        return 0i64;
                    }
                    return 2i64;
                }
                if (c < 3967i64) {
                    if (c < 3953i64) {
                        return 0i64;
                    }
                    return 2i64;
                }
                if (c < 3968i64) {
                    return 0i64;
                }
                if (c < 3973i64) {
                    return 2i64;
                }
                return 0i64;
            }
            if (c < 4145i64) {
                if (c < 3993i64) {
                    if (c < 3981i64) {
                        if (c < 3976i64) {
                            return 2i64;
                        }
                        return 0i64;
                    }
                    if (c < 3992i64) {
                        return 2i64;
                    }
                    return 0i64;
                }
                if (c < 4038i64) {
                    if (c < 4029i64) {
                        return 2i64;
                    }
                    return 0i64;
                }
                if (c < 4039i64) {
                    return 2i64;
                }
                if (c < 4141i64) {
                    return 0i64;
                }
                return 2i64;
            }
            if (c < 4157i64) {
                if (c < 4152i64) {
                    if (c < 4146i64) {
                        return 0i64;
                    }
                    return 2i64;
                }
                if (c < 4153i64) {
                    return 0i64;
                }
                if (c < 4155i64) {
                    return 2i64;
                }
                return 0i64;
            }
            if (c < 4184i64) {
                if (c < 4159i64) {
                    return 2i64;
                }
                return 0i64;
            }
            if (c < 4186i64) {
                return 2i64;
            }
            if (c < 4190i64) {
                return 0i64;
            }
            return 2i64;
        }
        if (c < 7960i64) {
            if (c < 6754i64) {
                if (c < 6070i64) {
                    if (c < 4347i64) {
                        if (c < 4253i64) {
                            if (c < 4227i64) {
                                if (c < 4213i64) {
                                    if (c < 4209i64) {
                                        return 0i64;
                                    }
                                    return 2i64;
                                }
                                if (c < 4226i64) {
                                    return 0i64;
                                }
                                return 2i64;
                            }
                            if (c < 4231i64) {
                                if (c < 4229i64) {
                                    return 0i64;
                                }
                                return 2i64;
                            }
                            if (c < 4237i64) {
                                return 0i64;
                            }
                            if (c < 4238i64) {
                                return 2i64;
                            }
                            return 0i64;
                        }
                        if (c < 4295i64) {
                            if (c < 4256i64) {
                                if (c < 4254i64) {
                                    return 2i64;
                                }
                                return 0i64;
                            }
                            if (c < 4294i64) {
                                return 1i64;
                            }
                            return 0i64;
                        }
                        if (c < 4301i64) {
                            if (c < 4296i64) {
                                return 1i64;
                            }
                            return 0i64;
                        }
                        if (c < 4302i64) {
                            return 1i64;
                        }
                        if (c < 4304i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 5118i64) {
                        if (c < 4957i64) {
                            if (c < 4349i64) {
                                if (c < 4348i64) {
                                    return 0i64;
                                }
                                return 2i64;
                            }
                            if (c < 4352i64) {
                                return 1i64;
                            }
                            return 0i64;
                        }
                        if (c < 5024i64) {
                            if (c < 4960i64) {
                                return 2i64;
                            }
                            return 0i64;
                        }
                        if (c < 5110i64) {
                            return 1i64;
                        }
                        if (c < 5112i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 5970i64) {
                        if (c < 5909i64) {
                            if (c < 5906i64) {
                                return 0i64;
                            }
                            return 2i64;
                        }
                        if (c < 5938i64) {
                            return 0i64;
                        }
                        if (c < 5940i64) {
                            return 2i64;
                        }
                        return 0i64;
                    }
                    if (c < 6002i64) {
                        if (c < 5972i64) {
                            return 2i64;
                        }
                        return 0i64;
                    }
                    if (c < 6004i64) {
                        return 2i64;
                    }
                    if (c < 6068i64) {
                        return 0i64;
                    }
                    return 2i64;
                }
                if (c < 6314i64) {
                    if (c < 6109i64) {
                        if (c < 6087i64) {
                            if (c < 6078i64) {
                                if (c < 6071i64) {
                                    return 0i64;
                                }
                                return 2i64;
                            }
                            if (c < 6086i64) {
                                return 0i64;
                            }
                            return 2i64;
                        }
                        if (c < 6100i64) {
                            if (c < 6089i64) {
                                return 0i64;
                            }
                            return 2i64;
                        }
                        if (c < 6103i64) {
                            return 0i64;
                        }
                        if (c < 6104i64) {
                            return 2i64;
                        }
                        return 0i64;
                    }
                    if (c < 6211i64) {
                        if (c < 6155i64) {
                            if (c < 6110i64) {
                                return 2i64;
                            }
                            return 0i64;
                        }
                        if (c < 6160i64) {
                            return 2i64;
                        }
                        return 0i64;
                    }
                    if (c < 6277i64) {
                        if (c < 6212i64) {
                            return 2i64;
                        }
                        return 0i64;
                    }
                    if (c < 6279i64) {
                        return 2i64;
                    }
                    if (c < 6313i64) {
                        return 0i64;
                    }
                    return 2i64;
                }
                if (c < 6679i64) {
                    if (c < 6441i64) {
                        if (c < 6435i64) {
                            if (c < 6432i64) {
                                return 0i64;
                            }
                            return 2i64;
                        }
                        if (c < 6439i64) {
                            return 0i64;
                        }
                        return 2i64;
                    }
                    if (c < 6451i64) {
                        if (c < 6450i64) {
                            return 0i64;
                        }
                        return 2i64;
                    }
                    if (c < 6457i64) {
                        return 0i64;
                    }
                    if (c < 6460i64) {
                        return 2i64;
                    }
                    return 0i64;
                }
                if (c < 6743i64) {
                    if (c < 6683i64) {
                        if (c < 6681i64) {
                            return 2i64;
                        }
                        return 0i64;
                    }
                    if (c < 6684i64) {
                        return 2i64;
                    }
                    if (c < 6742i64) {
                        return 0i64;
                    }
                    return 2i64;
                }
                if (c < 6751i64) {
                    if (c < 6744i64) {
                        return 0i64;
                    }
                    return 2i64;
                }
                if (c < 6752i64) {
                    return 0i64;
                }
                if (c < 6753i64) {
                    return 2i64;
                }
                return 0i64;
            }
            if (c < 7146i64) {
                if (c < 6966i64) {
                    if (c < 6824i64) {
                        if (c < 6771i64) {
                            if (c < 6757i64) {
                                if (c < 6755i64) {
                                    return 2i64;
                                }
                                return 0i64;
                            }
                            if (c < 6765i64) {
                                return 2i64;
                            }
                            return 0i64;
                        }
                        if (c < 6783i64) {
                            if (c < 6781i64) {
                                return 2i64;
                            }
                            return 0i64;
                        }
                        if (c < 6784i64) {
                            return 2i64;
                        }
                        if (c < 6823i64) {
                            return 0i64;
                        }
                        return 2i64;
                    }
                    if (c < 6892i64) {
                        if (c < 6878i64) {
                            if (c < 6832i64) {
                                return 0i64;
                            }
                            return 2i64;
                        }
                        if (c < 6880i64) {
                            return 0i64;
                        }
                        return 2i64;
                    }
                    if (c < 6916i64) {
                        if (c < 6912i64) {
                            return 0i64;
                        }
                        return 2i64;
                    }
                    if (c < 6964i64) {
                        return 0i64;
                    }
                    if (c < 6965i64) {
                        return 2i64;
                    }
                    return 0i64;
                }
                if (c < 7042i64) {
                    if (c < 6978i64) {
                        if (c < 6972i64) {
                            if (c < 6971i64) {
                                return 2i64;
                            }
                            return 0i64;
                        }
                        if (c < 6973i64) {
                            return 2i64;
                        }
                        return 0i64;
                    }
                    if (c < 7019i64) {
                        if (c < 6979i64) {
                            return 2i64;
                        }
                        return 0i64;
                    }
                    if (c < 7028i64) {
                        return 2i64;
                    }
                    if (c < 7040i64) {
                        return 0i64;
                    }
                    return 2i64;
                }
                if (c < 7083i64) {
                    if (c < 7078i64) {
                        if (c < 7074i64) {
                            return 0i64;
                        }
                        return 2i64;
                    }
                    if (c < 7080i64) {
                        return 0i64;
                    }
                    if (c < 7082i64) {
                        return 2i64;
                    }
                    return 0i64;
                }
                if (c < 7142i64) {
                    if (c < 7086i64) {
                        return 2i64;
                    }
                    return 0i64;
                }
                if (c < 7143i64) {
                    return 2i64;
                }
                if (c < 7144i64) {
                    return 0i64;
                }
                return 2i64;
            }
            if (c < 7379i64) {
                if (c < 7288i64) {
                    if (c < 7154i64) {
                        if (c < 7150i64) {
                            if (c < 7149i64) {
                                return 0i64;
                            }
                            return 2i64;
                        }
                        if (c < 7151i64) {
                            return 0i64;
                        }
                        return 2i64;
                    }
                    if (c < 7220i64) {
                        if (c < 7212i64) {
                            return 0i64;
                        }
                        return 2i64;
                    }
                    if (c < 7222i64) {
                        return 0i64;
                    }
                    if (c < 7224i64) {
                        return 2i64;
                    }
                    return 0i64;
                }
                if (c < 7312i64) {
                    if (c < 7296i64) {
                        if (c < 7294i64) {
                            return 2i64;
                        }
                        return 0i64;
                    }
                    if (c < 7307i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 7357i64) {
                    if (c < 7355i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 7360i64) {
                    return 1i64;
                }
                if (c < 7376i64) {
                    return 0i64;
                }
                return 2i64;
            }
            if (c < 7416i64) {
                if (c < 7401i64) {
                    if (c < 7393i64) {
                        if (c < 7380i64) {
                            return 0i64;
                        }
                        return 2i64;
                    }
                    if (c < 7394i64) {
                        return 0i64;
                    }
                    return 2i64;
                }
                if (c < 7406i64) {
                    if (c < 7405i64) {
                        return 0i64;
                    }
                    return 2i64;
                }
                if (c < 7412i64) {
                    return 0i64;
                }
                if (c < 7413i64) {
                    return 2i64;
                }
                return 0i64;
            }
            if (c < 7544i64) {
                if (c < 7424i64) {
                    if (c < 7418i64) {
                        return 2i64;
                    }
                    return 0i64;
                }
                if (c < 7468i64) {
                    return 1i64;
                }
                if (c < 7531i64) {
                    return 2i64;
                }
                return 1i64;
            }
            if (c < 7579i64) {
                if (c < 7545i64) {
                    return 2i64;
                }
                return 1i64;
            }
            if (c < 7680i64) {
                return 2i64;
            }
            if (c < 7958i64) {
                return 1i64;
            }
            return 0i64;
        }
        if (c < 8487i64) {
            if (c < 8189i64) {
                if (c < 8118i64) {
                    if (c < 8026i64) {
                        if (c < 8008i64) {
                            if (c < 7968i64) {
                                if (c < 7966i64) {
                                    return 1i64;
                                }
                                return 0i64;
                            }
                            if (c < 8006i64) {
                                return 1i64;
                            }
                            return 0i64;
                        }
                        if (c < 8016i64) {
                            if (c < 8014i64) {
                                return 1i64;
                            }
                            return 0i64;
                        }
                        if (c < 8024i64) {
                            return 1i64;
                        }
                        if (c < 8025i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 8030i64) {
                        if (c < 8028i64) {
                            if (c < 8027i64) {
                                return 0i64;
                            }
                            return 1i64;
                        }
                        if (c < 8029i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 8062i64) {
                        if (c < 8031i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 8064i64) {
                        return 0i64;
                    }
                    if (c < 8117i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 8148i64) {
                    if (c < 8130i64) {
                        if (c < 8126i64) {
                            if (c < 8125i64) {
                                return 1i64;
                            }
                            return 2i64;
                        }
                        if (c < 8127i64) {
                            return 1i64;
                        }
                        return 2i64;
                    }
                    if (c < 8134i64) {
                        if (c < 8133i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 8141i64) {
                        return 1i64;
                    }
                    if (c < 8144i64) {
                        return 2i64;
                    }
                    return 1i64;
                }
                if (c < 8173i64) {
                    if (c < 8156i64) {
                        if (c < 8150i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 8157i64) {
                        return 0i64;
                    }
                    if (c < 8160i64) {
                        return 2i64;
                    }
                    return 1i64;
                }
                if (c < 8178i64) {
                    if (c < 8176i64) {
                        return 2i64;
                    }
                    return 0i64;
                }
                if (c < 8181i64) {
                    return 1i64;
                }
                if (c < 8182i64) {
                    return 0i64;
                }
                return 1i64;
            }
            if (c < 8319i64) {
                if (c < 8232i64) {
                    if (c < 8216i64) {
                        if (c < 8203i64) {
                            if (c < 8191i64) {
                                return 2i64;
                            }
                            return 0i64;
                        }
                        if (c < 8208i64) {
                            return 2i64;
                        }
                        return 0i64;
                    }
                    if (c < 8228i64) {
                        if (c < 8218i64) {
                            return 2i64;
                        }
                        return 0i64;
                    }
                    if (c < 8229i64) {
                        return 2i64;
                    }
                    if (c < 8231i64) {
                        return 0i64;
                    }
                    return 2i64;
                }
                if (c < 8293i64) {
                    if (c < 8239i64) {
                        if (c < 8234i64) {
                            return 0i64;
                        }
                        return 2i64;
                    }
                    if (c < 8288i64) {
                        return 0i64;
                    }
                    return 2i64;
                }
                if (c < 8304i64) {
                    if (c < 8294i64) {
                        return 0i64;
                    }
                    return 2i64;
                }
                if (c < 8305i64) {
                    return 0i64;
                }
                if (c < 8306i64) {
                    return 2i64;
                }
                return 0i64;
            }
            if (c < 8456i64) {
                if (c < 8400i64) {
                    if (c < 8336i64) {
                        if (c < 8320i64) {
                            return 2i64;
                        }
                        return 0i64;
                    }
                    if (c < 8349i64) {
                        return 2i64;
                    }
                    return 0i64;
                }
                if (c < 8450i64) {
                    if (c < 8433i64) {
                        return 2i64;
                    }
                    return 0i64;
                }
                if (c < 8451i64) {
                    return 1i64;
                }
                if (c < 8455i64) {
                    return 0i64;
                }
                return 1i64;
            }
            if (c < 8473i64) {
                if (c < 8468i64) {
                    if (c < 8458i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 8469i64) {
                    return 0i64;
                }
                if (c < 8470i64) {
                    return 1i64;
                }
                return 0i64;
            }
            if (c < 8484i64) {
                if (c < 8478i64) {
                    return 1i64;
                }
                return 0i64;
            }
            if (c < 8485i64) {
                return 1i64;
            }
            if (c < 8486i64) {
                return 0i64;
            }
            return 1i64;
        }
        if (c < 11647i64) {
            if (c < 8581i64) {
                if (c < 8508i64) {
                    if (c < 8494i64) {
                        if (c < 8489i64) {
                            if (c < 8488i64) {
                                return 0i64;
                            }
                            return 1i64;
                        }
                        if (c < 8490i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 8501i64) {
                        if (c < 8495i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 8505i64) {
                        return 0i64;
                    }
                    if (c < 8506i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 8526i64) {
                    if (c < 8517i64) {
                        if (c < 8512i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 8522i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 8544i64) {
                    if (c < 8527i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 8576i64) {
                    return 1i64;
                }
                if (c < 8579i64) {
                    return 0i64;
                }
                return 1i64;
            }
            if (c < 11506i64) {
                if (c < 11388i64) {
                    if (c < 9450i64) {
                        if (c < 9398i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 11264i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 11493i64) {
                    if (c < 11390i64) {
                        return 2i64;
                    }
                    return 1i64;
                }
                if (c < 11499i64) {
                    return 0i64;
                }
                if (c < 11503i64) {
                    return 1i64;
                }
                return 2i64;
            }
            if (c < 11560i64) {
                if (c < 11520i64) {
                    if (c < 11508i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 11558i64) {
                    return 1i64;
                }
                if (c < 11559i64) {
                    return 0i64;
                }
                return 1i64;
            }
            if (c < 11566i64) {
                if (c < 11565i64) {
                    return 0i64;
                }
                return 1i64;
            }
            if (c < 11631i64) {
                return 0i64;
            }
            if (c < 11632i64) {
                return 2i64;
            }
            return 0i64;
        }
        if (c < 40981i64) {
            if (c < 12334i64) {
                if (c < 11823i64) {
                    if (c < 11744i64) {
                        if (c < 11648i64) {
                            return 2i64;
                        }
                        return 0i64;
                    }
                    if (c < 11776i64) {
                        return 2i64;
                    }
                    return 0i64;
                }
                if (c < 12293i64) {
                    if (c < 11824i64) {
                        return 2i64;
                    }
                    return 0i64;
                }
                if (c < 12294i64) {
                    return 2i64;
                }
                if (c < 12330i64) {
                    return 0i64;
                }
                return 2i64;
            }
            if (c < 12348i64) {
                if (c < 12342i64) {
                    if (c < 12337i64) {
                        return 0i64;
                    }
                    return 2i64;
                }
                if (c < 12347i64) {
                    return 0i64;
                }
                return 2i64;
            }
            if (c < 12447i64) {
                if (c < 12441i64) {
                    return 0i64;
                }
                return 2i64;
            }
            if (c < 12540i64) {
                return 0i64;
            }
            if (c < 12543i64) {
                return 2i64;
            }
            return 0i64;
        }
        if (c < 42611i64) {
            if (c < 42508i64) {
                if (c < 42232i64) {
                    if (c < 40982i64) {
                        return 2i64;
                    }
                    return 0i64;
                }
                if (c < 42238i64) {
                    return 2i64;
                }
                return 0i64;
            }
            if (c < 42560i64) {
                if (c < 42509i64) {
                    return 2i64;
                }
                return 0i64;
            }
            if (c < 42606i64) {
                return 1i64;
            }
            if (c < 42607i64) {
                return 0i64;
            }
            return 2i64;
        }
        if (c < 42652i64) {
            if (c < 42622i64) {
                if (c < 42612i64) {
                    return 0i64;
                }
                return 2i64;
            }
            if (c < 42623i64) {
                return 0i64;
            }
            if (c < 42624i64) {
                return 2i64;
            }
            return 1i64;
        }
        if (c < 42736i64) {
            if (c < 42656i64) {
                return 2i64;
            }
            return 0i64;
        }
        if (c < 42738i64) {
            return 2i64;
        }
        if (c < 42752i64) {
            return 0i64;
        }
        return 2i64;
    }
    if (c < 71134i64) {
        if (c < 66956i64) {
            if (c < 43763i64) {
                if (c < 43444i64) {
                    if (c < 43019i64) {
                        if (c < 42997i64) {
                            if (c < 42891i64) {
                                if (c < 42865i64) {
                                    if (c < 42864i64) {
                                        return 1i64;
                                    }
                                    return 2i64;
                                }
                                if (c < 42888i64) {
                                    return 1i64;
                                }
                                return 2i64;
                            }
                            if (c < 42896i64) {
                                if (c < 42895i64) {
                                    return 1i64;
                                }
                                return 0i64;
                            }
                            if (c < 42973i64) {
                                return 1i64;
                            }
                            if (c < 42993i64) {
                                return 0i64;
                            }
                            return 2i64;
                        }
                        if (c < 43003i64) {
                            if (c < 43000i64) {
                                if (c < 42999i64) {
                                    return 1i64;
                                }
                                return 0i64;
                            }
                            if (c < 43002i64) {
                                return 2i64;
                            }
                            return 1i64;
                        }
                        if (c < 43011i64) {
                            if (c < 43010i64) {
                                return 0i64;
                            }
                            return 2i64;
                        }
                        if (c < 43014i64) {
                            return 0i64;
                        }
                        if (c < 43015i64) {
                            return 2i64;
                        }
                        return 0i64;
                    }
                    if (c < 43250i64) {
                        if (c < 43052i64) {
                            if (c < 43045i64) {
                                if (c < 43020i64) {
                                    return 2i64;
                                }
                                return 0i64;
                            }
                            if (c < 43047i64) {
                                return 2i64;
                            }
                            return 0i64;
                        }
                        if (c < 43204i64) {
                            if (c < 43053i64) {
                                return 2i64;
                            }
                            return 0i64;
                        }
                        if (c < 43206i64) {
                            return 2i64;
                        }
                        if (c < 43232i64) {
                            return 0i64;
                        }
                        return 2i64;
                    }
                    if (c < 43335i64) {
                        if (c < 43264i64) {
                            if (c < 43263i64) {
                                return 0i64;
                            }
                            return 2i64;
                        }
                        if (c < 43302i64) {
                            return 0i64;
                        }
                        if (c < 43310i64) {
                            return 2i64;
                        }
                        return 0i64;
                    }
                    if (c < 43392i64) {
                        if (c < 43346i64) {
                            return 2i64;
                        }
                        return 0i64;
                    }
                    if (c < 43395i64) {
                        return 2i64;
                    }
                    if (c < 43443i64) {
                        return 0i64;
                    }
                    return 2i64;
                }
                if (c < 43597i64) {
                    if (c < 43561i64) {
                        if (c < 43454i64) {
                            if (c < 43450i64) {
                                if (c < 43446i64) {
                                    return 0i64;
                                }
                                return 2i64;
                            }
                            if (c < 43452i64) {
                                return 0i64;
                            }
                            return 2i64;
                        }
                        if (c < 43472i64) {
                            if (c < 43471i64) {
                                return 0i64;
                            }
                            return 2i64;
                        }
                        if (c < 43493i64) {
                            return 0i64;
                        }
                        if (c < 43495i64) {
                            return 2i64;
                        }
                        return 0i64;
                    }
                    if (c < 43573i64) {
                        if (c < 43569i64) {
                            if (c < 43567i64) {
                                return 2i64;
                            }
                            return 0i64;
                        }
                        if (c < 43571i64) {
                            return 2i64;
                        }
                        return 0i64;
                    }
                    if (c < 43587i64) {
                        if (c < 43575i64) {
                            return 2i64;
                        }
                        return 0i64;
                    }
                    if (c < 43588i64) {
                        return 2i64;
                    }
                    if (c < 43596i64) {
                        return 0i64;
                    }
                    return 2i64;
                }
                if (c < 43703i64) {
                    if (c < 43645i64) {
                        if (c < 43633i64) {
                            if (c < 43632i64) {
                                return 0i64;
                            }
                            return 2i64;
                        }
                        if (c < 43644i64) {
                            return 0i64;
                        }
                        return 2i64;
                    }
                    if (c < 43697i64) {
                        if (c < 43696i64) {
                            return 0i64;
                        }
                        return 2i64;
                    }
                    if (c < 43698i64) {
                        return 0i64;
                    }
                    if (c < 43701i64) {
                        return 2i64;
                    }
                    return 0i64;
                }
                if (c < 43714i64) {
                    if (c < 43710i64) {
                        if (c < 43705i64) {
                            return 2i64;
                        }
                        return 0i64;
                    }
                    if (c < 43712i64) {
                        return 2i64;
                    }
                    if (c < 43713i64) {
                        return 0i64;
                    }
                    return 2i64;
                }
                if (c < 43742i64) {
                    if (c < 43741i64) {
                        return 0i64;
                    }
                    return 2i64;
                }
                if (c < 43756i64) {
                    return 0i64;
                }
                if (c < 43758i64) {
                    return 2i64;
                }
                return 0i64;
            }
            if (c < 65287i64) {
                if (c < 64263i64) {
                    if (c < 43888i64) {
                        if (c < 43824i64) {
                            if (c < 43766i64) {
                                if (c < 43765i64) {
                                    return 2i64;
                                }
                                return 0i64;
                            }
                            if (c < 43767i64) {
                                return 2i64;
                            }
                            return 0i64;
                        }
                        if (c < 43872i64) {
                            if (c < 43867i64) {
                                return 1i64;
                            }
                            return 2i64;
                        }
                        if (c < 43881i64) {
                            return 1i64;
                        }
                        if (c < 43884i64) {
                            return 2i64;
                        }
                        return 0i64;
                    }
                    if (c < 44008i64) {
                        if (c < 44005i64) {
                            if (c < 43968i64) {
                                return 1i64;
                            }
                            return 0i64;
                        }
                        if (c < 44006i64) {
                            return 2i64;
                        }
                        return 0i64;
                    }
                    if (c < 44013i64) {
                        if (c < 44009i64) {
                            return 2i64;
                        }
                        return 0i64;
                    }
                    if (c < 44014i64) {
                        return 2i64;
                    }
                    if (c < 64256i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 65043i64) {
                    if (c < 64287i64) {
                        if (c < 64280i64) {
                            if (c < 64275i64) {
                                return 0i64;
                            }
                            return 1i64;
                        }
                        if (c < 64286i64) {
                            return 0i64;
                        }
                        return 2i64;
                    }
                    if (c < 64451i64) {
                        if (c < 64434i64) {
                            return 0i64;
                        }
                        return 2i64;
                    }
                    if (c < 65024i64) {
                        return 0i64;
                    }
                    if (c < 65040i64) {
                        return 2i64;
                    }
                    return 0i64;
                }
                if (c < 65107i64) {
                    if (c < 65056i64) {
                        if (c < 65044i64) {
                            return 2i64;
                        }
                        return 0i64;
                    }
                    if (c < 65072i64) {
                        return 2i64;
                    }
                    if (c < 65106i64) {
                        return 0i64;
                    }
                    return 2i64;
                }
                if (c < 65110i64) {
                    if (c < 65109i64) {
                        return 0i64;
                    }
                    return 2i64;
                }
                if (c < 65279i64) {
                    return 0i64;
                }
                if (c < 65280i64) {
                    return 2i64;
                }
                return 0i64;
            }
            if (c < 65508i64) {
                if (c < 65343i64) {
                    if (c < 65306i64) {
                        if (c < 65294i64) {
                            if (c < 65288i64) {
                                return 2i64;
                            }
                            return 0i64;
                        }
                        if (c < 65295i64) {
                            return 2i64;
                        }
                        return 0i64;
                    }
                    if (c < 65313i64) {
                        if (c < 65307i64) {
                            return 2i64;
                        }
                        return 0i64;
                    }
                    if (c < 65339i64) {
                        return 1i64;
                    }
                    if (c < 65342i64) {
                        return 0i64;
                    }
                    return 2i64;
                }
                if (c < 65392i64) {
                    if (c < 65345i64) {
                        if (c < 65344i64) {
                            return 0i64;
                        }
                        return 2i64;
                    }
                    if (c < 65371i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 65438i64) {
                    if (c < 65393i64) {
                        return 2i64;
                    }
                    return 0i64;
                }
                if (c < 65440i64) {
                    return 2i64;
                }
                if (c < 65507i64) {
                    return 0i64;
                }
                return 2i64;
            }
            if (c < 66560i64) {
                if (c < 66046i64) {
                    if (c < 65532i64) {
                        if (c < 65529i64) {
                            return 0i64;
                        }
                        return 2i64;
                    }
                    if (c < 66045i64) {
                        return 0i64;
                    }
                    return 2i64;
                }
                if (c < 66273i64) {
                    if (c < 66272i64) {
                        return 0i64;
                    }
                    return 2i64;
                }
                if (c < 66422i64) {
                    return 0i64;
                }
                if (c < 66427i64) {
                    return 2i64;
                }
                return 0i64;
            }
            if (c < 66812i64) {
                if (c < 66736i64) {
                    if (c < 66640i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 66772i64) {
                    return 1i64;
                }
                if (c < 66776i64) {
                    return 0i64;
                }
                return 1i64;
            }
            if (c < 66939i64) {
                if (c < 66928i64) {
                    return 0i64;
                }
                return 1i64;
            }
            if (c < 66940i64) {
                return 0i64;
            }
            if (c < 66955i64) {
                return 1i64;
            }
            return 0i64;
        }
        if (c < 69838i64) {
            if (c < 68943i64) {
                if (c < 68097i64) {
                    if (c < 67002i64) {
                        if (c < 66967i64) {
                            if (c < 66964i64) {
                                if (c < 66963i64) {
                                    return 1i64;
                                }
                                return 0i64;
                            }
                            if (c < 66966i64) {
                                return 1i64;
                            }
                            return 0i64;
                        }
                        if (c < 66979i64) {
                            if (c < 66978i64) {
                                return 1i64;
                            }
                            return 0i64;
                        }
                        if (c < 66994i64) {
                            return 1i64;
                        }
                        if (c < 66995i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 67462i64) {
                        if (c < 67005i64) {
                            if (c < 67003i64) {
                                return 0i64;
                            }
                            return 1i64;
                        }
                        if (c < 67456i64) {
                            return 0i64;
                        }
                        return 2i64;
                    }
                    if (c < 67505i64) {
                        if (c < 67463i64) {
                            return 0i64;
                        }
                        return 2i64;
                    }
                    if (c < 67506i64) {
                        return 0i64;
                    }
                    if (c < 67515i64) {
                        return 2i64;
                    }
                    return 0i64;
                }
                if (c < 68160i64) {
                    if (c < 68108i64) {
                        if (c < 68101i64) {
                            if (c < 68100i64) {
                                return 2i64;
                            }
                            return 0i64;
                        }
                        if (c < 68103i64) {
                            return 2i64;
                        }
                        return 0i64;
                    }
                    if (c < 68152i64) {
                        if (c < 68112i64) {
                            return 2i64;
                        }
                        return 0i64;
                    }
                    if (c < 68155i64) {
                        return 2i64;
                    }
                    if (c < 68159i64) {
                        return 0i64;
                    }
                    return 2i64;
                }
                if (c < 68800i64) {
                    if (c < 68327i64) {
                        if (c < 68325i64) {
                            return 0i64;
                        }
                        return 2i64;
                    }
                    if (c < 68736i64) {
                        return 0i64;
                    }
                    if (c < 68787i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 68900i64) {
                    if (c < 68851i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 68904i64) {
                    return 2i64;
                }
                if (c < 68942i64) {
                    return 0i64;
                }
                return 2i64;
            }
            if (c < 69633i64) {
                if (c < 69293i64) {
                    if (c < 68974i64) {
                        if (c < 68966i64) {
                            if (c < 68944i64) {
                                return 0i64;
                            }
                            return 1i64;
                        }
                        if (c < 68969i64) {
                            return 0i64;
                        }
                        return 2i64;
                    }
                    if (c < 68976i64) {
                        if (c < 68975i64) {
                            return 0i64;
                        }
                        return 2i64;
                    }
                    if (c < 68998i64) {
                        return 1i64;
                    }
                    if (c < 69291i64) {
                        return 0i64;
                    }
                    return 2i64;
                }
                if (c < 69376i64) {
                    if (c < 69318i64) {
                        if (c < 69317i64) {
                            return 0i64;
                        }
                        return 2i64;
                    }
                    if (c < 69370i64) {
                        return 0i64;
                    }
                    return 2i64;
                }
                if (c < 69457i64) {
                    if (c < 69446i64) {
                        return 0i64;
                    }
                    return 2i64;
                }
                if (c < 69506i64) {
                    return 0i64;
                }
                if (c < 69510i64) {
                    return 2i64;
                }
                return 0i64;
            }
            if (c < 69762i64) {
                if (c < 69744i64) {
                    if (c < 69688i64) {
                        if (c < 69634i64) {
                            return 2i64;
                        }
                        return 0i64;
                    }
                    if (c < 69703i64) {
                        return 2i64;
                    }
                    return 0i64;
                }
                if (c < 69747i64) {
                    if (c < 69745i64) {
                        return 2i64;
                    }
                    return 0i64;
                }
                if (c < 69749i64) {
                    return 2i64;
                }
                if (c < 69759i64) {
                    return 0i64;
                }
                return 2i64;
            }
            if (c < 69821i64) {
                if (c < 69815i64) {
                    if (c < 69811i64) {
                        return 0i64;
                    }
                    return 2i64;
                }
                if (c < 69817i64) {
                    return 0i64;
                }
                if (c < 69819i64) {
                    return 2i64;
                }
                return 0i64;
            }
            if (c < 69826i64) {
                if (c < 69822i64) {
                    return 2i64;
                }
                return 0i64;
            }
            if (c < 69827i64) {
                return 2i64;
            }
            if (c < 69837i64) {
                return 0i64;
            }
            return 2i64;
        }
        if (c < 70502i64) {
            if (c < 70194i64) {
                if (c < 70016i64) {
                    if (c < 69932i64) {
                        if (c < 69891i64) {
                            if (c < 69888i64) {
                                return 0i64;
                            }
                            return 2i64;
                        }
                        if (c < 69927i64) {
                            return 0i64;
                        }
                        return 2i64;
                    }
                    if (c < 69941i64) {
                        if (c < 69933i64) {
                            return 0i64;
                        }
                        return 2i64;
                    }
                    if (c < 70003i64) {
                        return 0i64;
                    }
                    if (c < 70004i64) {
                        return 2i64;
                    }
                    return 0i64;
                }
                if (c < 70089i64) {
                    if (c < 70070i64) {
                        if (c < 70018i64) {
                            return 2i64;
                        }
                        return 0i64;
                    }
                    if (c < 70079i64) {
                        return 2i64;
                    }
                    return 0i64;
                }
                if (c < 70095i64) {
                    if (c < 70093i64) {
                        return 2i64;
                    }
                    return 0i64;
                }
                if (c < 70096i64) {
                    return 2i64;
                }
                if (c < 70191i64) {
                    return 0i64;
                }
                return 2i64;
            }
            if (c < 70367i64) {
                if (c < 70200i64) {
                    if (c < 70197i64) {
                        if (c < 70196i64) {
                            return 0i64;
                        }
                        return 2i64;
                    }
                    if (c < 70198i64) {
                        return 0i64;
                    }
                    return 2i64;
                }
                if (c < 70207i64) {
                    if (c < 70206i64) {
                        return 0i64;
                    }
                    return 2i64;
                }
                if (c < 70209i64) {
                    return 0i64;
                }
                if (c < 70210i64) {
                    return 2i64;
                }
                return 0i64;
            }
            if (c < 70402i64) {
                if (c < 70371i64) {
                    if (c < 70368i64) {
                        return 2i64;
                    }
                    return 0i64;
                }
                if (c < 70379i64) {
                    return 2i64;
                }
                if (c < 70400i64) {
                    return 0i64;
                }
                return 2i64;
            }
            if (c < 70461i64) {
                if (c < 70459i64) {
                    return 0i64;
                }
                return 2i64;
            }
            if (c < 70464i64) {
                return 0i64;
            }
            if (c < 70465i64) {
                return 2i64;
            }
            return 0i64;
        }
        if (c < 70726i64) {
            if (c < 70609i64) {
                if (c < 70587i64) {
                    if (c < 70512i64) {
                        if (c < 70509i64) {
                            return 2i64;
                        }
                        return 0i64;
                    }
                    if (c < 70517i64) {
                        return 2i64;
                    }
                    return 0i64;
                }
                if (c < 70606i64) {
                    if (c < 70593i64) {
                        return 2i64;
                    }
                    return 0i64;
                }
                if (c < 70607i64) {
                    return 2i64;
                }
                if (c < 70608i64) {
                    return 0i64;
                }
                return 2i64;
            }
            if (c < 70627i64) {
                if (c < 70611i64) {
                    if (c < 70610i64) {
                        return 0i64;
                    }
                    return 2i64;
                }
                if (c < 70625i64) {
                    return 0i64;
                }
                return 2i64;
            }
            if (c < 70720i64) {
                if (c < 70712i64) {
                    return 0i64;
                }
                return 2i64;
            }
            if (c < 70722i64) {
                return 0i64;
            }
            if (c < 70725i64) {
                return 2i64;
            }
            return 0i64;
        }
        if (c < 70849i64) {
            if (c < 70835i64) {
                if (c < 70750i64) {
                    if (c < 70727i64) {
                        return 2i64;
                    }
                    return 0i64;
                }
                if (c < 70751i64) {
                    return 2i64;
                }
                return 0i64;
            }
            if (c < 70842i64) {
                if (c < 70841i64) {
                    return 2i64;
                }
                return 0i64;
            }
            if (c < 70843i64) {
                return 2i64;
            }
            if (c < 70847i64) {
                return 0i64;
            }
            return 2i64;
        }
        if (c < 71100i64) {
            if (c < 70852i64) {
                if (c < 70850i64) {
                    return 0i64;
                }
                return 2i64;
            }
            if (c < 71090i64) {
                return 0i64;
            }
            if (c < 71094i64) {
                return 2i64;
            }
            return 0i64;
        }
        if (c < 71103i64) {
            if (c < 71102i64) {
                return 2i64;
            }
            return 0i64;
        }
        if (c < 71105i64) {
            return 2i64;
        }
        if (c < 71132i64) {
            return 0i64;
        }
        return 2i64;
    }
    if (c < 113823i64) {
        if (c < 72884i64) {
            if (c < 72154i64) {
                if (c < 71456i64) {
                    if (c < 71341i64) {
                        if (c < 71230i64) {
                            if (c < 71227i64) {
                                if (c < 71219i64) {
                                    return 0i64;
                                }
                                return 2i64;
                            }
                            if (c < 71229i64) {
                                return 0i64;
                            }
                            return 2i64;
                        }
                        if (c < 71233i64) {
                            if (c < 71231i64) {
                                return 0i64;
                            }
                            return 2i64;
                        }
                        if (c < 71339i64) {
                            return 0i64;
                        }
                        if (c < 71340i64) {
                            return 2i64;
                        }
                        return 0i64;
                    }
                    if (c < 71351i64) {
                        if (c < 71344i64) {
                            if (c < 71342i64) {
                                return 2i64;
                            }
                            return 0i64;
                        }
                        if (c < 71350i64) {
                            return 2i64;
                        }
                        return 0i64;
                    }
                    if (c < 71453i64) {
                        if (c < 71352i64) {
                            return 2i64;
                        }
                        return 0i64;
                    }
                    if (c < 71454i64) {
                        return 2i64;
                    }
                    if (c < 71455i64) {
                        return 0i64;
                    }
                    return 2i64;
                }
                if (c < 71840i64) {
                    if (c < 71468i64) {
                        if (c < 71462i64) {
                            if (c < 71458i64) {
                                return 0i64;
                            }
                            return 2i64;
                        }
                        if (c < 71463i64) {
                            return 0i64;
                        }
                        return 2i64;
                    }
                    if (c < 71736i64) {
                        if (c < 71727i64) {
                            return 0i64;
                        }
                        return 2i64;
                    }
                    if (c < 71737i64) {
                        return 0i64;
                    }
                    if (c < 71739i64) {
                        return 2i64;
                    }
                    return 0i64;
                }
                if (c < 71999i64) {
                    if (c < 71995i64) {
                        if (c < 71904i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 71997i64) {
                        return 2i64;
                    }
                    if (c < 71998i64) {
                        return 0i64;
                    }
                    return 2i64;
                }
                if (c < 72004i64) {
                    if (c < 72003i64) {
                        return 0i64;
                    }
                    return 2i64;
                }
                if (c < 72148i64) {
                    return 0i64;
                }
                if (c < 72152i64) {
                    return 2i64;
                }
                return 0i64;
            }
            if (c < 72344i64) {
                if (c < 72255i64) {
                    if (c < 72193i64) {
                        if (c < 72160i64) {
                            if (c < 72156i64) {
                                return 2i64;
                            }
                            return 0i64;
                        }
                        if (c < 72161i64) {
                            return 2i64;
                        }
                        return 0i64;
                    }
                    if (c < 72243i64) {
                        if (c < 72203i64) {
                            return 2i64;
                        }
                        return 0i64;
                    }
                    if (c < 72249i64) {
                        return 2i64;
                    }
                    if (c < 72251i64) {
                        return 0i64;
                    }
                    return 2i64;
                }
                if (c < 72279i64) {
                    if (c < 72264i64) {
                        if (c < 72263i64) {
                            return 0i64;
                        }
                        return 2i64;
                    }
                    if (c < 72273i64) {
                        return 0i64;
                    }
                    return 2i64;
                }
                if (c < 72284i64) {
                    if (c < 72281i64) {
                        return 0i64;
                    }
                    return 2i64;
                }
                if (c < 72330i64) {
                    return 0i64;
                }
                if (c < 72343i64) {
                    return 2i64;
                }
                return 0i64;
            }
            if (c < 72759i64) {
                if (c < 72546i64) {
                    if (c < 72544i64) {
                        if (c < 72346i64) {
                            return 2i64;
                        }
                        return 0i64;
                    }
                    if (c < 72545i64) {
                        return 2i64;
                    }
                    return 0i64;
                }
                if (c < 72550i64) {
                    if (c < 72549i64) {
                        return 2i64;
                    }
                    return 0i64;
                }
                if (c < 72551i64) {
                    return 2i64;
                }
                if (c < 72752i64) {
                    return 0i64;
                }
                return 2i64;
            }
            if (c < 72850i64) {
                if (c < 72766i64) {
                    if (c < 72760i64) {
                        return 0i64;
                    }
                    return 2i64;
                }
                if (c < 72767i64) {
                    return 0i64;
                }
                if (c < 72768i64) {
                    return 2i64;
                }
                return 0i64;
            }
            if (c < 72874i64) {
                if (c < 72872i64) {
                    return 2i64;
                }
                return 0i64;
            }
            if (c < 72881i64) {
                return 2i64;
            }
            if (c < 72882i64) {
                return 0i64;
            }
            return 2i64;
        }
        if (c < 90398i64) {
            if (c < 73112i64) {
                if (c < 73023i64) {
                    if (c < 73015i64) {
                        if (c < 72887i64) {
                            if (c < 72885i64) {
                                return 0i64;
                            }
                            return 2i64;
                        }
                        if (c < 73009i64) {
                            return 0i64;
                        }
                        return 2i64;
                    }
                    if (c < 73019i64) {
                        if (c < 73018i64) {
                            return 0i64;
                        }
                        return 2i64;
                    }
                    if (c < 73020i64) {
                        return 0i64;
                    }
                    if (c < 73022i64) {
                        return 2i64;
                    }
                    return 0i64;
                }
                if (c < 73104i64) {
                    if (c < 73031i64) {
                        if (c < 73030i64) {
                            return 2i64;
                        }
                        return 0i64;
                    }
                    if (c < 73032i64) {
                        return 2i64;
                    }
                    return 0i64;
                }
                if (c < 73109i64) {
                    if (c < 73106i64) {
                        return 2i64;
                    }
                    return 0i64;
                }
                if (c < 73110i64) {
                    return 2i64;
                }
                if (c < 73111i64) {
                    return 0i64;
                }
                return 2i64;
            }
            if (c < 73536i64) {
                if (c < 73461i64) {
                    if (c < 73178i64) {
                        if (c < 73177i64) {
                            return 0i64;
                        }
                        return 2i64;
                    }
                    if (c < 73459i64) {
                        return 0i64;
                    }
                    return 2i64;
                }
                if (c < 73474i64) {
                    if (c < 73472i64) {
                        return 0i64;
                    }
                    return 2i64;
                }
                if (c < 73526i64) {
                    return 0i64;
                }
                if (c < 73531i64) {
                    return 2i64;
                }
                return 0i64;
            }
            if (c < 73563i64) {
                if (c < 73538i64) {
                    if (c < 73537i64) {
                        return 2i64;
                    }
                    return 0i64;
                }
                if (c < 73539i64) {
                    return 2i64;
                }
                if (c < 73562i64) {
                    return 0i64;
                }
                return 2i64;
            }
            if (c < 78913i64) {
                if (c < 78896i64) {
                    return 0i64;
                }
                return 2i64;
            }
            if (c < 78919i64) {
                return 0i64;
            }
            if (c < 78934i64) {
                return 2i64;
            }
            return 0i64;
        }
        if (c < 93883i64) {
            if (c < 92996i64) {
                if (c < 92912i64) {
                    if (c < 90413i64) {
                        if (c < 90410i64) {
                            return 2i64;
                        }
                        return 0i64;
                    }
                    if (c < 90416i64) {
                        return 2i64;
                    }
                    return 0i64;
                }
                if (c < 92976i64) {
                    if (c < 92917i64) {
                        return 2i64;
                    }
                    return 0i64;
                }
                if (c < 92983i64) {
                    return 2i64;
                }
                if (c < 92992i64) {
                    return 0i64;
                }
                return 2i64;
            }
            if (c < 93549i64) {
                if (c < 93507i64) {
                    if (c < 93504i64) {
                        return 0i64;
                    }
                    return 2i64;
                }
                if (c < 93547i64) {
                    return 0i64;
                }
                return 2i64;
            }
            if (c < 93824i64) {
                if (c < 93760i64) {
                    return 0i64;
                }
                return 1i64;
            }
            if (c < 93856i64) {
                return 0i64;
            }
            if (c < 93881i64) {
                return 1i64;
            }
            return 0i64;
        }
        if (c < 94181i64) {
            if (c < 94095i64) {
                if (c < 94031i64) {
                    if (c < 93908i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 94032i64) {
                    return 2i64;
                }
                return 0i64;
            }
            if (c < 94176i64) {
                if (c < 94112i64) {
                    return 2i64;
                }
                return 0i64;
            }
            if (c < 94178i64) {
                return 2i64;
            }
            if (c < 94179i64) {
                return 0i64;
            }
            return 2i64;
        }
        if (c < 110581i64) {
            if (c < 94196i64) {
                if (c < 94194i64) {
                    return 0i64;
                }
                return 2i64;
            }
            if (c < 110576i64) {
                return 0i64;
            }
            if (c < 110580i64) {
                return 2i64;
            }
            return 0i64;
        }
        if (c < 110589i64) {
            if (c < 110588i64) {
                return 2i64;
            }
            return 0i64;
        }
        if (c < 110591i64) {
            return 2i64;
        }
        if (c < 113821i64) {
            return 0i64;
        }
        return 2i64;
    }
    if (c < 120771i64) {
        if (c < 120071i64) {
            if (c < 119893i64) {
                if (c < 119155i64) {
                    if (c < 118574i64) {
                        if (c < 113828i64) {
                            if (c < 113824i64) {
                                return 0i64;
                            }
                            return 2i64;
                        }
                        if (c < 118528i64) {
                            return 0i64;
                        }
                        return 2i64;
                    }
                    if (c < 118599i64) {
                        if (c < 118576i64) {
                            return 0i64;
                        }
                        return 2i64;
                    }
                    if (c < 119143i64) {
                        return 0i64;
                    }
                    if (c < 119146i64) {
                        return 2i64;
                    }
                    return 0i64;
                }
                if (c < 119210i64) {
                    if (c < 119173i64) {
                        if (c < 119171i64) {
                            return 2i64;
                        }
                        return 0i64;
                    }
                    if (c < 119180i64) {
                        return 2i64;
                    }
                    return 0i64;
                }
                if (c < 119362i64) {
                    if (c < 119214i64) {
                        return 2i64;
                    }
                    return 0i64;
                }
                if (c < 119365i64) {
                    return 2i64;
                }
                if (c < 119808i64) {
                    return 0i64;
                }
                return 1i64;
            }
            if (c < 119977i64) {
                if (c < 119968i64) {
                    if (c < 119965i64) {
                        if (c < 119894i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 119966i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 119971i64) {
                    if (c < 119970i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 119973i64) {
                    return 0i64;
                }
                if (c < 119975i64) {
                    return 1i64;
                }
                return 0i64;
            }
            if (c < 119996i64) {
                if (c < 119982i64) {
                    if (c < 119981i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 119994i64) {
                    return 1i64;
                }
                if (c < 119995i64) {
                    return 0i64;
                }
                return 1i64;
            }
            if (c < 120004i64) {
                if (c < 119997i64) {
                    return 0i64;
                }
                return 1i64;
            }
            if (c < 120005i64) {
                return 0i64;
            }
            if (c < 120070i64) {
                return 1i64;
            }
            return 0i64;
        }
        if (c < 120488i64) {
            if (c < 120127i64) {
                if (c < 120086i64) {
                    if (c < 120077i64) {
                        if (c < 120075i64) {
                            return 1i64;
                        }
                        return 0i64;
                    }
                    if (c < 120085i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 120094i64) {
                    if (c < 120093i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 120122i64) {
                    return 1i64;
                }
                if (c < 120123i64) {
                    return 0i64;
                }
                return 1i64;
            }
            if (c < 120135i64) {
                if (c < 120133i64) {
                    if (c < 120128i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 120134i64) {
                    return 0i64;
                }
                return 1i64;
            }
            if (c < 120145i64) {
                if (c < 120138i64) {
                    return 0i64;
                }
                return 1i64;
            }
            if (c < 120146i64) {
                return 0i64;
            }
            if (c < 120486i64) {
                return 1i64;
            }
            return 0i64;
        }
        if (c < 120629i64) {
            if (c < 120540i64) {
                if (c < 120514i64) {
                    if (c < 120513i64) {
                        return 1i64;
                    }
                    return 0i64;
                }
                if (c < 120539i64) {
                    return 1i64;
                }
                return 0i64;
            }
            if (c < 120572i64) {
                if (c < 120571i64) {
                    return 1i64;
                }
                return 0i64;
            }
            if (c < 120597i64) {
                return 1i64;
            }
            if (c < 120598i64) {
                return 0i64;
            }
            return 1i64;
        }
        if (c < 120688i64) {
            if (c < 120655i64) {
                if (c < 120630i64) {
                    return 0i64;
                }
                return 1i64;
            }
            if (c < 120656i64) {
                return 0i64;
            }
            if (c < 120687i64) {
                return 1i64;
            }
            return 0i64;
        }
        if (c < 120714i64) {
            if (c < 120713i64) {
                return 1i64;
            }
            return 0i64;
        }
        if (c < 120745i64) {
            return 1i64;
        }
        if (c < 120746i64) {
            return 0i64;
        }
        return 1i64;
    }
    if (c < 123566i64) {
        if (c < 122655i64) {
            if (c < 121476i64) {
                if (c < 121399i64) {
                    if (c < 120780i64) {
                        if (c < 120772i64) {
                            return 0i64;
                        }
                        return 1i64;
                    }
                    if (c < 121344i64) {
                        return 0i64;
                    }
                    return 2i64;
                }
                if (c < 121453i64) {
                    if (c < 121403i64) {
                        return 0i64;
                    }
                    return 2i64;
                }
                if (c < 121461i64) {
                    return 0i64;
                }
                if (c < 121462i64) {
                    return 2i64;
                }
                return 0i64;
            }
            if (c < 121505i64) {
                if (c < 121499i64) {
                    if (c < 121477i64) {
                        return 2i64;
                    }
                    return 0i64;
                }
                if (c < 121504i64) {
                    return 2i64;
                }
                return 0i64;
            }
            if (c < 122624i64) {
                if (c < 121520i64) {
                    return 2i64;
                }
                return 0i64;
            }
            if (c < 122634i64) {
                return 1i64;
            }
            if (c < 122635i64) {
                return 0i64;
            }
            return 1i64;
        }
        if (c < 122915i64) {
            if (c < 122887i64) {
                if (c < 122667i64) {
                    if (c < 122661i64) {
                        return 0i64;
                    }
                    return 1i64;
                }
                if (c < 122880i64) {
                    return 0i64;
                }
                return 2i64;
            }
            if (c < 122905i64) {
                if (c < 122888i64) {
                    return 0i64;
                }
                return 2i64;
            }
            if (c < 122907i64) {
                return 0i64;
            }
            if (c < 122914i64) {
                return 2i64;
            }
            return 0i64;
        }
        if (c < 122990i64) {
            if (c < 122918i64) {
                if (c < 122917i64) {
                    return 2i64;
                }
                return 0i64;
            }
            if (c < 122923i64) {
                return 2i64;
            }
            if (c < 122928i64) {
                return 0i64;
            }
            return 2i64;
        }
        if (c < 123024i64) {
            if (c < 123023i64) {
                return 0i64;
            }
            return 2i64;
        }
        if (c < 123184i64) {
            return 0i64;
        }
        if (c < 123198i64) {
            return 2i64;
        }
        return 0i64;
    }
    if (c < 125136i64) {
        if (c < 124644i64) {
            if (c < 124139i64) {
                if (c < 123628i64) {
                    if (c < 123567i64) {
                        return 2i64;
                    }
                    return 0i64;
                }
                if (c < 123632i64) {
                    return 2i64;
                }
                return 0i64;
            }
            if (c < 124398i64) {
                if (c < 124144i64) {
                    return 2i64;
                }
                return 0i64;
            }
            if (c < 124400i64) {
                return 2i64;
            }
            if (c < 124643i64) {
                return 0i64;
            }
            return 2i64;
        }
        if (c < 124656i64) {
            if (c < 124647i64) {
                if (c < 124646i64) {
                    return 0i64;
                }
                return 2i64;
            }
            if (c < 124654i64) {
                return 0i64;
            }
            return 2i64;
        }
        if (c < 124662i64) {
            if (c < 124661i64) {
                return 0i64;
            }
            return 2i64;
        }
        if (c < 124671i64) {
            return 0i64;
        }
        if (c < 124672i64) {
            return 2i64;
        }
        return 0i64;
    }
    if (c < 127344i64) {
        if (c < 125260i64) {
            if (c < 125184i64) {
                if (c < 125143i64) {
                    return 2i64;
                }
                return 0i64;
            }
            if (c < 125252i64) {
                return 1i64;
            }
            return 2i64;
        }
        if (c < 127306i64) {
            if (c < 127280i64) {
                return 0i64;
            }
            return 1i64;
        }
        if (c < 127312i64) {
            return 0i64;
        }
        if (c < 127338i64) {
            return 1i64;
        }
        return 0i64;
    }
    if (c < 917506i64) {
        if (c < 127995i64) {
            if (c < 127370i64) {
                return 1i64;
            }
            return 0i64;
        }
        if (c < 128000i64) {
            return 2i64;
        }
        if (c < 917505i64) {
            return 0i64;
        }
        return 2i64;
    }
    if (c < 917632i64) {
        if (c < 917536i64) {
            return 0i64;
        }
        return 2i64;
    }
    if (c < 917760i64) {
        return 0i64;
    }
    if (c < 918000i64) {
        return 2i64;
    }
    return 0i64;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_3_lw1(c: i64) -> i64 {
    if (c < 7360i64) {
        if (c < 544i64) {
            if (c < 412i64) {
                if (c < 386i64) {
                    if (c < 305i64) {
                        if (c < 215i64) {
                            if (c < 91i64) {
                                if (c < 65i64) {
                                    return c;
                                }
                                return (c + 32i64);
                            }
                            if (c < 192i64) {
                                return c;
                            }
                            return (c + 32i64);
                        }
                        if (c < 223i64) {
                            if (c < 216i64) {
                                return c;
                            }
                            return (c + 32i64);
                        }
                        if (c < 256i64) {
                            return c;
                        }
                        if (c < 304i64) {
                            if (((c - 256i64) % 2i64) == 0i64) {
                                return (c + 1i64);
                            }
                            return c;
                        }
                        return (c - 199i64);
                    }
                    if (c < 330i64) {
                        if (c < 311i64) {
                            if (c < 306i64) {
                                return c;
                            }
                            if (((c - 306i64) % 2i64) == 0i64) {
                                return (c + 1i64);
                            }
                            return c;
                        }
                        if (c < 313i64) {
                            return c;
                        }
                        if (c < 328i64) {
                            if (((c - 313i64) % 2i64) == 0i64) {
                                return (c + 1i64);
                            }
                            return c;
                        }
                        return c;
                    }
                    if (c < 377i64) {
                        if (c < 376i64) {
                            if (((c - 330i64) % 2i64) == 0i64) {
                                return (c + 1i64);
                            }
                            return c;
                        }
                        return (c - 121i64);
                    }
                    if (c < 382i64) {
                        if (((c - 377i64) % 2i64) == 0i64) {
                            return (c + 1i64);
                        }
                        return c;
                    }
                    if (c < 385i64) {
                        return c;
                    }
                    return (c + 210i64);
                }
                if (c < 400i64) {
                    if (c < 393i64) {
                        if (c < 391i64) {
                            if (c < 390i64) {
                                if (((c - 386i64) % 2i64) == 0i64) {
                                    return (c + 1i64);
                                }
                                return c;
                            }
                            return (c + 206i64);
                        }
                        if (c < 392i64) {
                            return (c + 1i64);
                        }
                        return c;
                    }
                    if (c < 396i64) {
                        if (c < 395i64) {
                            return (c + 205i64);
                        }
                        return (c + 1i64);
                    }
                    if (c < 398i64) {
                        return c;
                    }
                    if (c < 399i64) {
                        return (c + 79i64);
                    }
                    return (c + 202i64);
                }
                if (c < 405i64) {
                    if (c < 402i64) {
                        if (c < 401i64) {
                            return (c + 203i64);
                        }
                        return (c + 1i64);
                    }
                    if (c < 403i64) {
                        return c;
                    }
                    if (c < 404i64) {
                        return (c + 205i64);
                    }
                    return (c + 207i64);
                }
                if (c < 407i64) {
                    if (c < 406i64) {
                        return c;
                    }
                    return (c + 211i64);
                }
                if (c < 408i64) {
                    return (c + 209i64);
                }
                if (c < 409i64) {
                    return (c + 1i64);
                }
                return c;
            }
            if (c < 441i64) {
                if (c < 426i64) {
                    if (c < 416i64) {
                        if (c < 414i64) {
                            if (c < 413i64) {
                                return (c + 211i64);
                            }
                            return (c + 213i64);
                        }
                        if (c < 415i64) {
                            return c;
                        }
                        return (c + 214i64);
                    }
                    if (c < 423i64) {
                        if (c < 422i64) {
                            if (((c - 416i64) % 2i64) == 0i64) {
                                return (c + 1i64);
                            }
                            return c;
                        }
                        return (c + 218i64);
                    }
                    if (c < 424i64) {
                        return (c + 1i64);
                    }
                    if (c < 425i64) {
                        return c;
                    }
                    return (c + 218i64);
                }
                if (c < 432i64) {
                    if (c < 429i64) {
                        if (c < 428i64) {
                            return c;
                        }
                        return (c + 1i64);
                    }
                    if (c < 430i64) {
                        return c;
                    }
                    if (c < 431i64) {
                        return (c + 218i64);
                    }
                    return (c + 1i64);
                }
                if (c < 435i64) {
                    if (c < 433i64) {
                        return c;
                    }
                    return (c + 217i64);
                }
                if (c < 439i64) {
                    if (((c - 435i64) % 2i64) == 0i64) {
                        return (c + 1i64);
                    }
                    return c;
                }
                if (c < 440i64) {
                    return (c + 219i64);
                }
                return (c + 1i64);
            }
            if (c < 458i64) {
                if (c < 453i64) {
                    if (c < 445i64) {
                        if (c < 444i64) {
                            return c;
                        }
                        return (c + 1i64);
                    }
                    if (c < 452i64) {
                        return c;
                    }
                    return (c + 2i64);
                }
                if (c < 455i64) {
                    if (c < 454i64) {
                        return (c + 1i64);
                    }
                    return c;
                }
                if (c < 456i64) {
                    return (c + 2i64);
                }
                if (c < 457i64) {
                    return (c + 1i64);
                }
                return c;
            }
            if (c < 497i64) {
                if (c < 476i64) {
                    if (c < 459i64) {
                        return (c + 2i64);
                    }
                    if (((c - 459i64) % 2i64) == 0i64) {
                        return (c + 1i64);
                    }
                    return c;
                }
                if (c < 478i64) {
                    return c;
                }
                if (c < 495i64) {
                    if (((c - 478i64) % 2i64) == 0i64) {
                        return (c + 1i64);
                    }
                    return c;
                }
                return c;
            }
            if (c < 502i64) {
                if (c < 498i64) {
                    return (c + 2i64);
                }
                if (((c - 498i64) % 2i64) == 0i64) {
                    return (c + 1i64);
                }
                return c;
            }
            if (c < 503i64) {
                return (c - 97i64);
            }
            if (c < 504i64) {
                return (c - 56i64);
            }
            if (((c - 504i64) % 2i64) == 0i64) {
                return (c + 1i64);
            }
            return c;
        }
        if (c < 976i64) {
            if (c < 882i64) {
                if (c < 575i64) {
                    if (c < 570i64) {
                        if (c < 546i64) {
                            if (c < 545i64) {
                                return (c - 130i64);
                            }
                            return c;
                        }
                        if (c < 563i64) {
                            if (((c - 546i64) % 2i64) == 0i64) {
                                return (c + 1i64);
                            }
                            return c;
                        }
                        return c;
                    }
                    if (c < 572i64) {
                        if (c < 571i64) {
                            return (c + 10795i64);
                        }
                        return (c + 1i64);
                    }
                    if (c < 573i64) {
                        return c;
                    }
                    if (c < 574i64) {
                        return (c - 163i64);
                    }
                    return (c + 10792i64);
                }
                if (c < 581i64) {
                    if (c < 578i64) {
                        if (c < 577i64) {
                            return c;
                        }
                        return (c + 1i64);
                    }
                    if (c < 579i64) {
                        return c;
                    }
                    if (c < 580i64) {
                        return (c - 195i64);
                    }
                    return (c + 69i64);
                }
                if (c < 591i64) {
                    if (c < 582i64) {
                        return (c + 71i64);
                    }
                    if (((c - 582i64) % 2i64) == 0i64) {
                        return (c + 1i64);
                    }
                    return c;
                }
                if (c < 880i64) {
                    return c;
                }
                if (c < 881i64) {
                    return (c + 1i64);
                }
                return c;
            }
            if (c < 907i64) {
                if (c < 895i64) {
                    if (c < 886i64) {
                        if (c < 883i64) {
                            return (c + 1i64);
                        }
                        return c;
                    }
                    if (c < 887i64) {
                        return (c + 1i64);
                    }
                    return c;
                }
                if (c < 902i64) {
                    if (c < 896i64) {
                        return (c + 116i64);
                    }
                    return c;
                }
                if (c < 903i64) {
                    return (c + 38i64);
                }
                if (c < 904i64) {
                    return c;
                }
                return (c + 37i64);
            }
            if (c < 913i64) {
                if (c < 909i64) {
                    if (c < 908i64) {
                        return c;
                    }
                    return (c + 64i64);
                }
                if (c < 910i64) {
                    return c;
                }
                if (c < 912i64) {
                    return (c + 63i64);
                }
                return c;
            }
            if (c < 931i64) {
                if (c < 930i64) {
                    return (c + 32i64);
                }
                return c;
            }
            if (c < 940i64) {
                return (c + 32i64);
            }
            if (c < 975i64) {
                return c;
            }
            return (c + 8i64);
        }
        if (c < 1230i64) {
            if (c < 1019i64) {
                if (c < 1013i64) {
                    if (c < 1007i64) {
                        if (c < 984i64) {
                            return c;
                        }
                        if (((c - 984i64) % 2i64) == 0i64) {
                            return (c + 1i64);
                        }
                        return c;
                    }
                    if (c < 1012i64) {
                        return c;
                    }
                    return (c - 60i64);
                }
                if (c < 1016i64) {
                    if (c < 1015i64) {
                        return c;
                    }
                    return (c + 1i64);
                }
                if (c < 1017i64) {
                    return c;
                }
                if (c < 1018i64) {
                    return (c - 7i64);
                }
                return (c + 1i64);
            }
            if (c < 1120i64) {
                if (c < 1024i64) {
                    if (c < 1021i64) {
                        return c;
                    }
                    return (c - 130i64);
                }
                if (c < 1040i64) {
                    return (c + 80i64);
                }
                if (c < 1072i64) {
                    return (c + 32i64);
                }
                return c;
            }
            if (c < 1162i64) {
                if (c < 1153i64) {
                    if (((c - 1120i64) % 2i64) == 0i64) {
                        return (c + 1i64);
                    }
                    return c;
                }
                return c;
            }
            if (c < 1216i64) {
                if (((c - 1162i64) % 2i64) == 0i64) {
                    return (c + 1i64);
                }
                return c;
            }
            if (c < 1217i64) {
                return (c + 15i64);
            }
            if (((c - 1217i64) % 2i64) == 0i64) {
                return (c + 1i64);
            }
            return c;
        }
        if (c < 4301i64) {
            if (c < 1367i64) {
                if (c < 1327i64) {
                    if (c < 1232i64) {
                        return c;
                    }
                    if (((c - 1232i64) % 2i64) == 0i64) {
                        return (c + 1i64);
                    }
                    return c;
                }
                if (c < 1329i64) {
                    return c;
                }
                return (c + 48i64);
            }
            if (c < 4294i64) {
                if (c < 4256i64) {
                    return c;
                }
                return (c + 7264i64);
            }
            if (c < 4295i64) {
                return c;
            }
            if (c < 4296i64) {
                return (c + 7264i64);
            }
            return c;
        }
        if (c < 7305i64) {
            if (c < 5024i64) {
                if (c < 4302i64) {
                    return (c + 7264i64);
                }
                return c;
            }
            if (c < 5104i64) {
                return (c + 38864i64);
            }
            if (c < 5110i64) {
                return (c + 8i64);
            }
            return c;
        }
        if (c < 7312i64) {
            if (c < 7306i64) {
                return (c + 1i64);
            }
            return c;
        }
        if (c < 7355i64) {
            return (c - 3008i64);
        }
        if (c < 7357i64) {
            return c;
        }
        return (c - 3008i64);
    }
    if (c < 11390i64) {
        if (c < 8170i64) {
            if (c < 8040i64) {
                if (c < 7960i64) {
                    if (c < 7839i64) {
                        if (c < 7829i64) {
                            if (c < 7680i64) {
                                return c;
                            }
                            if (((c - 7680i64) % 2i64) == 0i64) {
                                return (c + 1i64);
                            }
                            return c;
                        }
                        if (c < 7838i64) {
                            return c;
                        }
                        return (c - 7615i64);
                    }
                    if (c < 7935i64) {
                        if (c < 7840i64) {
                            return c;
                        }
                        if (((c - 7840i64) % 2i64) == 0i64) {
                            return (c + 1i64);
                        }
                        return c;
                    }
                    if (c < 7944i64) {
                        return c;
                    }
                    if (c < 7952i64) {
                        return (c - 8i64);
                    }
                    return c;
                }
                if (c < 8000i64) {
                    if (c < 7976i64) {
                        if (c < 7966i64) {
                            return (c - 8i64);
                        }
                        return c;
                    }
                    if (c < 7984i64) {
                        return (c - 8i64);
                    }
                    if (c < 7992i64) {
                        return c;
                    }
                    return (c - 8i64);
                }
                if (c < 8014i64) {
                    if (c < 8008i64) {
                        return c;
                    }
                    return (c - 8i64);
                }
                if (c < 8025i64) {
                    return c;
                }
                if (c < 8032i64) {
                    if (((c - 8025i64) % 2i64) == 0i64) {
                        return (c - 8i64);
                    }
                    return c;
                }
                return c;
            }
            if (c < 8122i64) {
                if (c < 8088i64) {
                    if (c < 8072i64) {
                        if (c < 8048i64) {
                            return (c - 8i64);
                        }
                        return c;
                    }
                    if (c < 8080i64) {
                        return (c - 8i64);
                    }
                    return c;
                }
                if (c < 8104i64) {
                    if (c < 8096i64) {
                        return (c - 8i64);
                    }
                    return c;
                }
                if (c < 8112i64) {
                    return (c - 8i64);
                }
                if (c < 8120i64) {
                    return c;
                }
                return (c - 8i64);
            }
            if (c < 8141i64) {
                if (c < 8125i64) {
                    if (c < 8124i64) {
                        return (c - 74i64);
                    }
                    return (c - 9i64);
                }
                if (c < 8136i64) {
                    return c;
                }
                if (c < 8140i64) {
                    return (c - 86i64);
                }
                return (c - 9i64);
            }
            if (c < 8154i64) {
                if (c < 8152i64) {
                    return c;
                }
                return (c - 8i64);
            }
            if (c < 8156i64) {
                return (c - 100i64);
            }
            if (c < 8168i64) {
                return c;
            }
            return (c - 8i64);
        }
        if (c < 9424i64) {
            if (c < 8490i64) {
                if (c < 8186i64) {
                    if (c < 8173i64) {
                        if (c < 8172i64) {
                            return (c - 112i64);
                        }
                        return (c - 7i64);
                    }
                    if (c < 8184i64) {
                        return c;
                    }
                    return (c - 128i64);
                }
                if (c < 8189i64) {
                    if (c < 8188i64) {
                        return (c - 126i64);
                    }
                    return (c - 9i64);
                }
                if (c < 8486i64) {
                    return c;
                }
                if (c < 8487i64) {
                    return (c - 7517i64);
                }
                return c;
            }
            if (c < 8544i64) {
                if (c < 8492i64) {
                    if (c < 8491i64) {
                        return (c - 8383i64);
                    }
                    return (c - 8262i64);
                }
                if (c < 8498i64) {
                    return c;
                }
                if (c < 8499i64) {
                    return (c + 28i64);
                }
                return c;
            }
            if (c < 8579i64) {
                if (c < 8560i64) {
                    return (c + 16i64);
                }
                return c;
            }
            if (c < 8580i64) {
                return (c + 1i64);
            }
            if (c < 9398i64) {
                return c;
            }
            return (c + 26i64);
        }
        if (c < 11367i64) {
            if (c < 11361i64) {
                if (c < 11312i64) {
                    if (c < 11264i64) {
                        return c;
                    }
                    return (c + 48i64);
                }
                if (c < 11360i64) {
                    return c;
                }
                return (c + 1i64);
            }
            if (c < 11363i64) {
                if (c < 11362i64) {
                    return c;
                }
                return (c - 10743i64);
            }
            if (c < 11364i64) {
                return (c - 3814i64);
            }
            if (c < 11365i64) {
                return (c - 10727i64);
            }
            return c;
        }
        if (c < 11377i64) {
            if (c < 11374i64) {
                if (c < 11373i64) {
                    if (((c - 11367i64) % 2i64) == 0i64) {
                        return (c + 1i64);
                    }
                    return c;
                }
                return (c - 10780i64);
            }
            if (c < 11375i64) {
                return (c - 10749i64);
            }
            if (c < 11376i64) {
                return (c - 10783i64);
            }
            return (c - 10782i64);
        }
        if (c < 11379i64) {
            if (c < 11378i64) {
                return c;
            }
            return (c + 1i64);
        }
        if (c < 11381i64) {
            return c;
        }
        if (c < 11382i64) {
            return (c + 1i64);
        }
        return c;
    }
    if (c < 42930i64) {
        if (c < 42878i64) {
            if (c < 42560i64) {
                if (c < 11500i64) {
                    if (c < 11491i64) {
                        if (c < 11392i64) {
                            return (c - 10815i64);
                        }
                        if (((c - 11392i64) % 2i64) == 0i64) {
                            return (c + 1i64);
                        }
                        return c;
                    }
                    if (c < 11499i64) {
                        return c;
                    }
                    return (c + 1i64);
                }
                if (c < 11502i64) {
                    if (c < 11501i64) {
                        return c;
                    }
                    return (c + 1i64);
                }
                if (c < 11506i64) {
                    return c;
                }
                if (c < 11507i64) {
                    return (c + 1i64);
                }
                return c;
            }
            if (c < 42799i64) {
                if (c < 42624i64) {
                    if (c < 42605i64) {
                        if (((c - 42560i64) % 2i64) == 0i64) {
                            return (c + 1i64);
                        }
                        return c;
                    }
                    return c;
                }
                if (c < 42651i64) {
                    if (((c - 42624i64) % 2i64) == 0i64) {
                        return (c + 1i64);
                    }
                    return c;
                }
                if (c < 42786i64) {
                    return c;
                }
                if (((c - 42786i64) % 2i64) == 0i64) {
                    return (c + 1i64);
                }
                return c;
            }
            if (c < 42863i64) {
                if (c < 42802i64) {
                    return c;
                }
                if (((c - 42802i64) % 2i64) == 0i64) {
                    return (c + 1i64);
                }
                return c;
            }
            if (c < 42873i64) {
                return c;
            }
            if (c < 42877i64) {
                if (((c - 42873i64) % 2i64) == 0i64) {
                    return (c + 1i64);
                }
                return c;
            }
            return (c - 35332i64);
        }
        if (c < 42899i64) {
            if (c < 42893i64) {
                if (c < 42891i64) {
                    if (c < 42887i64) {
                        if (((c - 42878i64) % 2i64) == 0i64) {
                            return (c + 1i64);
                        }
                        return c;
                    }
                    return c;
                }
                if (c < 42892i64) {
                    return (c + 1i64);
                }
                return c;
            }
            if (c < 42896i64) {
                if (c < 42894i64) {
                    return (c - 42280i64);
                }
                return c;
            }
            if (c < 42897i64) {
                return (c + 1i64);
            }
            if (c < 42898i64) {
                return c;
            }
            return (c + 1i64);
        }
        if (c < 42925i64) {
            if (c < 42922i64) {
                if (c < 42902i64) {
                    return c;
                }
                if (((c - 42902i64) % 2i64) == 0i64) {
                    return (c + 1i64);
                }
                return c;
            }
            if (c < 42923i64) {
                return (c - 42308i64);
            }
            if (c < 42924i64) {
                return (c - 42319i64);
            }
            return (c - 42315i64);
        }
        if (c < 42927i64) {
            if (c < 42926i64) {
                return (c - 42305i64);
            }
            return (c - 42308i64);
        }
        if (c < 42928i64) {
            return c;
        }
        if (c < 42929i64) {
            return (c - 42258i64);
        }
        return (c - 42282i64);
    }
    if (c < 66928i64) {
        if (c < 42972i64) {
            if (c < 42949i64) {
                if (c < 42932i64) {
                    if (c < 42931i64) {
                        return (c - 42261i64);
                    }
                    return (c + 928i64);
                }
                if (c < 42948i64) {
                    if (((c - 42932i64) % 2i64) == 0i64) {
                        return (c + 1i64);
                    }
                    return c;
                }
                return (c - 48i64);
            }
            if (c < 42951i64) {
                if (c < 42950i64) {
                    return (c - 42307i64);
                }
                return (c - 35384i64);
            }
            if (c < 42955i64) {
                if (((c - 42951i64) % 2i64) == 0i64) {
                    return (c + 1i64);
                }
                return c;
            }
            if (c < 42956i64) {
                return (c - 42343i64);
            }
            if (((c - 42956i64) % 2i64) == 0i64) {
                return (c + 1i64);
            }
            return c;
        }
        if (c < 65339i64) {
            if (c < 42997i64) {
                if (c < 42973i64) {
                    return (c - 42561i64);
                }
                return c;
            }
            if (c < 42998i64) {
                return (c + 1i64);
            }
            if (c < 65313i64) {
                return c;
            }
            return (c + 32i64);
        }
        if (c < 66600i64) {
            if (c < 66560i64) {
                return c;
            }
            return (c + 40i64);
        }
        if (c < 66736i64) {
            return c;
        }
        if (c < 66772i64) {
            return (c + 40i64);
        }
        return c;
    }
    if (c < 68944i64) {
        if (c < 66963i64) {
            if (c < 66940i64) {
                if (c < 66939i64) {
                    return (c + 39i64);
                }
                return c;
            }
            if (c < 66955i64) {
                return (c + 39i64);
            }
            if (c < 66956i64) {
                return c;
            }
            return (c + 39i64);
        }
        if (c < 66966i64) {
            if (c < 66964i64) {
                return c;
            }
            return (c + 39i64);
        }
        if (c < 68736i64) {
            return c;
        }
        if (c < 68787i64) {
            return (c + 64i64);
        }
        return c;
    }
    if (c < 93792i64) {
        if (c < 71840i64) {
            if (c < 68966i64) {
                return (c + 32i64);
            }
            return c;
        }
        if (c < 71872i64) {
            return (c + 32i64);
        }
        if (c < 93760i64) {
            return c;
        }
        return (c + 32i64);
    }
    if (c < 93881i64) {
        if (c < 93856i64) {
            return c;
        }
        return (c + 27i64);
    }
    if (c < 125184i64) {
        return c;
    }
    if (c < 125218i64) {
        return (c + 34i64);
    }
    return c;
}

