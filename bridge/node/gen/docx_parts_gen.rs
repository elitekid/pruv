#[allow(dead_code)]
#[inline]
fn pruv_str_boundary(a: &str, i: i64) -> bool { i >= 0 && (i as u64) <= (a.len() as u64) && a.is_char_boundary(i as usize) }

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_1_g(a: &[i64], i: i64) -> i64 {
    if ((0i64 <= i) && (i < (a.len() as i64))) {
        return (unsafe { *a.get_unchecked((i) as usize) });
    }
    return (-1i64);
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_2_sv(a: &mut [i64], i: i64, v: i64) {
    if ((0i64 <= i) && (i < (a.len() as i64))) {
        { let pruv_i: i64 = i; let pruv_x: i64 = v; unsafe { *a.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
    }
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_2_wr(out: &mut [i64], p: i64, v: i64) -> i64 {
    if ((0i64 <= p) && (p < (out.len() as i64))) {
        { let pruv_i: i64 = p; let pruv_x: i64 = v; unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
    }
    if (p < 0i64) {
        return 0i64;
    }
    if (p < 1125899906842624i64) {
        return (p + 1i64);
    }
    return 1125899906842624i64;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_2_nf(t: &[i64], i: i64, f: i64) -> i64 {
    if ((((0i64 <= i) && (i <= 1099511627776i64)) && (0i64 <= f)) && (f <= 9i64)) {
        return pruv_m_f_1_1_g(t, ((10i64 * i) + f));
    }
    return (-1i64);
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_4_nset(t: &mut [i64], i: i64, f: i64, v: i64) {
    if ((((0i64 <= i) && (i <= 1099511627776i64)) && (0i64 <= f)) && (f <= 9i64)) {
        pruv_m_f_1_2_sv(&mut *t, ((10i64 * i) + f), v);
    }
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_3_dws(c: i64) -> bool {
    if (((((9i64 <= c) && (c <= 13i64)) || (c == 32i64)) || (c == 160i64)) || (c == 5760i64)) {
        return true;
    }
    if (((((8192i64 <= c) && (c <= 8202i64)) || (c == 8232i64)) || (c == 8233i64)) || (c == 8239i64)) {
        return true;
    }
    return (((c == 8287i64) || (c == 12288i64)) || (c == 65279i64));
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_5_is_sp(c: i64) -> bool {
    return (((((c == 32i64) || (c == 9i64)) || (c == 11i64)) || (c == 12i64)) || (c == 13i64));
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_4_lowc(x: i64) -> i64 {
    if ((65i64 <= x) && (x <= 90i64)) {
        return (x + 32i64);
    }
    return x;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_5_wordc(x: i64) -> bool {
    return (((((48i64 <= x) && (x <= 57i64)) || ((65i64 <= x) && (x <= 90i64))) || ((97i64 <= x) && (x <= 122i64))) || (x == 95i64));
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_6_tag_eq(rec: &[i64], a: i64, n: i64, w: &str) -> bool {
    if (((n != (w.len() as i64)) || (a < 0i64)) || (a > 1099511627776i64)) {
        return false;
    }
    let mut k: i64 = 0i64;
    while (k < n) {
        let y: i64 = ((unsafe { *w.as_bytes().get_unchecked((k) as usize) }) as i64);
        if (pruv_m_f_1_1_g(rec, (a + k)) != y) {
            return false;
        }
        k = (k + 1i64);
    }
    return true;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_8_classify(rec: &[i64], a: i64, n: i64) -> i64 {
    if pruv_m_f_1_6_tag_eq(rec, a, n, &::std::string::String::from("p")) {
        return 1i64;
    }
    if ((pruv_m_f_1_6_tag_eq(rec, a, n, &::std::string::String::from("h1")) || pruv_m_f_1_6_tag_eq(rec, a, n, &::std::string::String::from("h2"))) || pruv_m_f_1_6_tag_eq(rec, a, n, &::std::string::String::from("h3"))) {
        return 2i64;
    }
    if ((pruv_m_f_1_6_tag_eq(rec, a, n, &::std::string::String::from("h4")) || pruv_m_f_1_6_tag_eq(rec, a, n, &::std::string::String::from("h5"))) || pruv_m_f_1_6_tag_eq(rec, a, n, &::std::string::String::from("h6"))) {
        return 2i64;
    }
    if (pruv_m_f_1_6_tag_eq(rec, a, n, &::std::string::String::from("ul")) || pruv_m_f_1_6_tag_eq(rec, a, n, &::std::string::String::from("ol"))) {
        return 3i64;
    }
    if pruv_m_f_1_6_tag_eq(rec, a, n, &::std::string::String::from("li")) {
        return 4i64;
    }
    if pruv_m_f_1_6_tag_eq(rec, a, n, &::std::string::String::from("table")) {
        return 5i64;
    }
    if ((pruv_m_f_1_6_tag_eq(rec, a, n, &::std::string::String::from("thead")) || pruv_m_f_1_6_tag_eq(rec, a, n, &::std::string::String::from("tbody"))) || pruv_m_f_1_6_tag_eq(rec, a, n, &::std::string::String::from("tfoot"))) {
        return 6i64;
    }
    if pruv_m_f_1_6_tag_eq(rec, a, n, &::std::string::String::from("tr")) {
        return 7i64;
    }
    if (pruv_m_f_1_6_tag_eq(rec, a, n, &::std::string::String::from("td")) || pruv_m_f_1_6_tag_eq(rec, a, n, &::std::string::String::from("th"))) {
        return 8i64;
    }
    if ((pruv_m_f_1_6_tag_eq(rec, a, n, &::std::string::String::from("strong")) || pruv_m_f_1_6_tag_eq(rec, a, n, &::std::string::String::from("em"))) || pruv_m_f_1_6_tag_eq(rec, a, n, &::std::string::String::from("u"))) {
        return 9i64;
    }
    if (pruv_m_f_1_6_tag_eq(rec, a, n, &::std::string::String::from("sup")) || pruv_m_f_1_6_tag_eq(rec, a, n, &::std::string::String::from("sub"))) {
        return 9i64;
    }
    if pruv_m_f_1_6_tag_eq(rec, a, n, &::std::string::String::from("br")) {
        return 10i64;
    }
    if pruv_m_f_1_6_tag_eq(rec, a, n, &::std::string::String::from("img")) {
        return 11i64;
    }
    if pruv_m_f_1_6_tag_eq(rec, a, n, &::std::string::String::from("a")) {
        return 12i64;
    }
    if (pruv_m_f_1_6_tag_eq(rec, a, n, &::std::string::String::from("script")) || pruv_m_f_1_6_tag_eq(rec, a, n, &::std::string::String::from("style"))) {
        return 13i64;
    }
    if pruv_m_f_1_6_tag_eq(rec, a, n, &::std::string::String::from("div")) {
        return 14i64;
    }
    return 0i64;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_6_cps_ok__pruv_body(rec: &[i64], a: i64, b: i64) -> bool {
    let mut k: i64 = a;
    while (k < b) {
        let c: i64 = (unsafe { *rec.get_unchecked((k) as usize) });
        if ((c < 0i64) || (c > 1114111i64)) {
            return false;
        }
        k = (k + 1i64);
    }
    return true;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_8_rec_next__pruv_body(rec: &[i64], p: i64, e: i64) -> i64 {
    let l: i64 = (rec.len() as i64);
    if ((p + 3i64) > l) {
        return (-1i64);
    }
    let kind: i64 = (unsafe { *rec.get_unchecked((p) as usize) });
    let par: i64 = (unsafe { *rec.get_unchecked(((p + 1i64)) as usize) });
    let n: i64 = (unsafe { *rec.get_unchecked(((p + 2i64)) as usize) });
    if ((kind != 0i64) && (kind != 1i64)) {
        return (-1i64);
    }
    if ((par < (-1i64)) || (par >= e)) {
        return (-1i64);
    }
    if ((n < 0i64) || (n > ((l - p) - 3i64))) {
        return (-1i64);
    }
    let mut q: i64 = (p + 3i64);
    if (!pruv_m_f_1_6_cps_ok__pruv_body(rec, q, (q + n))) {
        return (-1i64);
    }
    q = (q + n);
    if (kind == 1i64) {
        let mut w: i64 = 0i64;
        while (w < 3i64) {
            if (q >= l) {
                return (-1i64);
            }
            let m: i64 = (unsafe { *rec.get_unchecked((q) as usize) });
            if ((m < (-1i64)) || (m > ((l - q) - 1i64))) {
                return (-1i64);
            }
            q = (q + 1i64);
            if (m > 0i64) {
                if (!pruv_m_f_1_6_cps_ok__pruv_body(rec, q, (q + m))) {
                    return (-1i64);
                }
                q = (q + m);
            }
            w = (w + 1i64);
        }
    }
    return q;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_9_copy_text(rec: &[i64], a: i64, n: i64, buf: &mut [i64], q0: i64) -> i64 {
    let mut q: i64 = pruv_m_f_1_2_wr(&mut *buf, (-1i64), 0i64);
    q = q0;
    if ((q < 0i64) || (q > 1125899906842624i64)) {
        q = 0i64;
    }
    if ((((a < 0i64) || (a > 1099511627776i64)) || (n < 0i64)) || (n > 1099511627776i64)) {
        return q;
    }
    let mut k: i64 = 0i64;
    while (k < n) {
        q = pruv_m_f_1_2_wr(&mut *buf, q, pruv_m_f_1_1_g(rec, (a + k)));
        k = (k + 1i64);
    }
    return q;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_11_inline_text(rec: &[i64], t: &[i64], el: i64, skip: i64, buf: &mut [i64], ik: &mut [i64]) -> i64 {
    let mut cur: i64 = 0i64;
    let mut d: i64 = 1i64;
    pruv_m_f_1_2_sv(&mut *ik, 0i64, pruv_m_f_1_2_nf(t, el, 5i64));
    pruv_m_f_1_2_sv(&mut *ik, 1i64, 0i64);
    let mut fuel: i64 = ((t.len() as i64) + 10i64);
    while ((d > 0i64) && (fuel > 0i64)) {
        fuel = (fuel - 1i64);
        let c: i64 = pruv_m_f_1_1_g(&*ik, ((2i64 * d) - 2i64));
        if (c < 0i64) {
            d = (d - 1i64);
        } else {
            pruv_m_f_1_2_sv(&mut *ik, ((2i64 * d) - 2i64), pruv_m_f_1_2_nf(t, c, 6i64));
            let kd: i64 = pruv_m_f_1_2_nf(t, c, 0i64);
            if (kd == 0i64) {
                cur = pruv_m_f_1_9_copy_text(rec, pruv_m_f_1_2_nf(t, c, 2i64), pruv_m_f_1_2_nf(t, c, 3i64), &mut *buf, cur);
            } else {
                if (kd == 1i64) {
                    let tg: i64 = pruv_m_f_1_2_nf(t, c, 1i64);
                    if ((skip == 1i64) && (tg == 3i64)) {
                        cur = cur;
                    } else {
                        if (tg == 10i64) {
                            cur = pruv_m_f_1_2_wr(&mut *buf, cur, 10i64);
                        } else {
                            if (tg == 11i64) {
                                cur = pruv_m_f_1_2_wr(&mut *buf, cur, 91i64);
                                cur = pruv_m_f_1_2_wr(&mut *buf, cur, 44536i64);
                                cur = pruv_m_f_1_2_wr(&mut *buf, cur, 47548i64);
                                cur = pruv_m_f_1_2_wr(&mut *buf, cur, 93i64);
                            } else {
                                if (((tg == 1i64) || (tg == 14i64)) || (tg == 4i64)) {
                                    let st: i64 = pruv_m_f_1_1_g(&*ik, ((2i64 * d) - 1i64));
                                    if ((cur > st) && (pruv_m_f_1_1_g(&*buf, (cur - 1i64)) != 10i64)) {
                                        cur = pruv_m_f_1_2_wr(&mut *buf, cur, 32i64);
                                    }
                                }
                                if ((((2i64 * d) + 1i64) < (ik.len() as i64)) && (d < 1099511627776i64)) {
                                    pruv_m_f_1_2_sv(&mut *ik, (2i64 * d), pruv_m_f_1_2_nf(t, c, 5i64));
                                    pruv_m_f_1_2_sv(&mut *ik, ((2i64 * d) + 1i64), cur);
                                    d = (d + 1i64);
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    return cur;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_8_collapse(src: &[i64], b: i64, cell: i64, out: &mut [i64], q0: i64) -> i64 {
    let mut q: i64 = pruv_m_f_1_2_wr(&mut *out, (-1i64), 0i64);
    q = q0;
    if ((q < 0i64) || (q > 1125899906842624i64)) {
        q = 0i64;
    }
    let mut bb: i64 = b;
    if (bb > (src.len() as i64)) {
        bb = (src.len() as i64);
    }
    if (bb < 0i64) {
        bb = 0i64;
    }
    let mut f: i64 = 0i64;
    while ((f < bb) && pruv_m_f_1_3_dws((unsafe { *src.get_unchecked((f) as usize) }))) {
        f = (f + 1i64);
    }
    let mut l: i64 = bb;
    while ((l > f) && pruv_m_f_1_3_dws((unsafe { *src.get_unchecked(((l - 1i64)) as usize) }))) {
        l = (l - 1i64);
    }
    let mut i: i64 = f;
    let mut nl: i64 = 0i64;
    while (i < l) {
        let c: i64 = (unsafe { *src.get_unchecked((i) as usize) });
        if pruv_m_f_1_5_is_sp(c) {
            let mut j: i64 = (i + 1i64);
            while ((j < l) && pruv_m_f_1_5_is_sp((unsafe { *src.get_unchecked((j) as usize) }))) {
                j = (j + 1i64);
            }
            if ((pruv_m_f_1_1_g(src, (i - 1i64)) != 10i64) && (pruv_m_f_1_1_g(src, j) != 10i64)) {
                q = pruv_m_f_1_2_wr(&mut *out, q, 32i64);
                nl = 0i64;
            }
            i = j;
        } else {
            if (c == 10i64) {
                if (cell == 0i64) {
                    q = pruv_m_f_1_2_wr(&mut *out, q, 10i64);
                } else {
                    if (nl == 0i64) {
                        q = pruv_m_f_1_2_wr(&mut *out, q, 32i64);
                    }
                    nl = 1i64;
                }
                i = (i + 1i64);
            } else {
                q = pruv_m_f_1_2_wr(&mut *out, q, c);
                nl = 0i64;
                i = (i + 1i64);
            }
        }
    }
    return q;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_8_row_text(rec: &[i64], t: &[i64], tr: i64, tmp: &mut [i64], row: &mut [i64], ik: &mut [i64]) -> i64 {
    let mut rq: i64 = 0i64;
    let mut cells: i64 = 0i64;
    let mut c: i64 = pruv_m_f_1_2_nf(t, tr, 5i64);
    let mut fuel: i64 = (t.len() as i64);
    while ((c >= 0i64) && (fuel > 0i64)) {
        fuel = (fuel - 1i64);
        if ((pruv_m_f_1_2_nf(t, c, 0i64) == 1i64) && (pruv_m_f_1_2_nf(t, c, 1i64) == 8i64)) {
            if (cells > 0i64) {
                rq = pruv_m_f_1_2_wr(&mut *row, rq, 32i64);
                rq = pruv_m_f_1_2_wr(&mut *row, rq, 124i64);
                rq = pruv_m_f_1_2_wr(&mut *row, rq, 32i64);
            }
            let e: i64 = pruv_m_f_1_11_inline_text(rec, t, c, 0i64, &mut *tmp, &mut *ik);
            rq = pruv_m_f_1_8_collapse(&*tmp, e, 1i64, &mut *row, rq);
            cells = 1i64;
        }
        c = pruv_m_f_1_2_nf(t, c, 6i64);
    }
    if ((rq > 0i64) && ((rq % 3i64) == 0i64)) {
        let mut k: i64 = 0i64;
        let mut seps: i64 = 1i64;
        while (k < rq) {
            if (((pruv_m_f_1_1_g(&*row, k) != 32i64) || (pruv_m_f_1_1_g(&*row, (k + 1i64)) != 124i64)) || (pruv_m_f_1_1_g(&*row, (k + 2i64)) != 32i64)) {
                seps = 0i64;
            }
            k = (k + 3i64);
        }
        if (seps == 1i64) {
            rq = 0i64;
        }
    }
    return rq;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_9_add_block(t: &mut [i64], root: i64, c: i64, kind: i64, src: &[i64], b: i64, out: &mut [i64], q0: i64) -> i64 {
    let mut q: i64 = pruv_m_f_1_2_wr(&mut *out, (-1i64), 0i64);
    q = q0;
    if ((q < 0i64) || (q > 1125899906842624i64)) {
        q = 0i64;
    }
    let h: i64 = q;
    q = pruv_m_f_1_2_wr(&mut *out, q, kind);
    q = pruv_m_f_1_2_wr(&mut *out, q, pruv_m_f_1_2_nf(&*t, c, 8i64));
    q = pruv_m_f_1_2_wr(&mut *out, q, 0i64);
    let st: i64 = q;
    q = pruv_m_f_1_8_collapse(src, b, 0i64, &mut *out, q);
    if (q == st) {
        return h;
    }
    pruv_m_f_1_2_sv(&mut *out, (st - 1i64), (q - st));
    let mut cnt: i64 = pruv_m_f_1_2_nf(&*t, root, 9i64);
    if (cnt < 0i64) {
        cnt = 0i64;
    }
    if (cnt < 1125899906842624i64) {
        cnt = (cnt + 1i64);
    }
    pruv_m_f_1_4_nset(&mut *t, root, 9i64, cnt);
    pruv_m_f_1_4_nset(&mut *t, c, 9i64, cnt);
    return q;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_7_collect(rec: &[i64], root: i64, t: &mut [i64], tmp: &mut [i64], row: &mut [i64], sk: &mut [i64], ik: &mut [i64], out: &mut [i64], q0: i64) -> i64 {
    let mut q: i64 = pruv_m_f_1_2_wr(&mut *out, (-1i64), 0i64);
    q = q0;
    if ((q < 0i64) || (q > 1125899906842624i64)) {
        q = 0i64;
    }
    let mut d: i64 = 1i64;
    pruv_m_f_1_2_sv(&mut *sk, 0i64, 0i64);
    pruv_m_f_1_2_sv(&mut *sk, 1i64, pruv_m_f_1_2_nf(&*t, root, 5i64));
    let mut fuel: i64 = ((t.len() as i64) + 10i64);
    while ((d > 0i64) && (fuel > 0i64)) {
        fuel = (fuel - 1i64);
        let ty: i64 = pruv_m_f_1_1_g(&*sk, ((2i64 * d) - 2i64));
        let c: i64 = pruv_m_f_1_1_g(&*sk, ((2i64 * d) - 1i64));
        if (c < 0i64) {
            d = (d - 1i64);
        } else {
            pruv_m_f_1_2_sv(&mut *sk, ((2i64 * d) - 1i64), pruv_m_f_1_2_nf(&*t, c, 6i64));
            if (pruv_m_f_1_2_nf(&*t, c, 0i64) == 1i64) {
                let tg: i64 = pruv_m_f_1_2_nf(&*t, c, 1i64);
                let mut visit: i64 = 0i64;
                let mut push: i64 = (-1i64);
                if (ty == 0i64) {
                    visit = 1i64;
                } else {
                    if (ty == 1i64) {
                        if (tg == 4i64) {
                            let e: i64 = pruv_m_f_1_11_inline_text(rec, &*t, c, 1i64, &mut *tmp, &mut *ik);
                            q = pruv_m_f_1_9_add_block(&mut *t, root, c, 2i64, &*tmp, e, &mut *out, q);
                            push = 2i64;
                        } else {
                            visit = 1i64;
                        }
                    } else {
                        if (ty == 2i64) {
                            if (tg == 3i64) {
                                visit = 1i64;
                            }
                        } else {
                            if (tg == 7i64) {
                                let e: i64 = pruv_m_f_1_8_row_text(rec, &*t, c, &mut *tmp, &mut *row, &mut *ik);
                                q = pruv_m_f_1_9_add_block(&mut *t, root, c, 3i64, &*row, e, &mut *out, q);
                            } else {
                                if (tg == 6i64) {
                                    push = 3i64;
                                }
                            }
                        }
                    }
                }
                if (visit == 1i64) {
                    if ((tg == 1i64) || (tg == 2i64)) {
                        let e: i64 = pruv_m_f_1_11_inline_text(rec, &*t, c, 0i64, &mut *tmp, &mut *ik);
                        q = pruv_m_f_1_9_add_block(&mut *t, root, c, (tg - 1i64), &*tmp, e, &mut *out, q);
                    } else {
                        if (tg == 3i64) {
                            push = 1i64;
                        } else {
                            if (tg == 5i64) {
                                push = 3i64;
                            } else {
                                push = 0i64;
                            }
                        }
                    }
                }
                if (((push >= 0i64) && (((2i64 * d) + 1i64) < (sk.len() as i64))) && (d < 1099511627776i64)) {
                    pruv_m_f_1_2_sv(&mut *sk, (2i64 * d), push);
                    pruv_m_f_1_2_sv(&mut *sk, ((2i64 * d) + 1i64), pruv_m_f_1_2_nf(&*t, c, 5i64));
                    d = (d + 1i64);
                }
            }
        }
    }
    return q;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_7_put_str(out: &mut [i64], q0: i64, s: &str) -> i64 {
    let mut q: i64 = pruv_m_f_1_2_wr(&mut *out, (-1i64), 0i64);
    q = q0;
    if ((q < 0i64) || (q > 1125899906842624i64)) {
        q = 0i64;
    }
    let mut k: i64 = 0i64;
    while (k < (s.len() as i64)) {
        q = pruv_m_f_1_2_wr(&mut *out, q, ((unsafe { *s.as_bytes().get_unchecked((k) as usize) }) as i64));
        k = (k + 1i64);
    }
    return q;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_7_put_num__pruv_body(out: &mut [i64], q0: i64, v: i64) -> i64 {
    let mut q: i64 = pruv_m_f_1_2_wr(&mut *out, (-1i64), 0i64);
    q = q0;
    if ((q < 0i64) || (q > 1125899906842624i64)) {
        q = 0i64;
    }
    let mut p: i64 = 1i64;
    while (p <= (v / 10i64)) {
        p = (p * 10i64);
    }
    while (p > 0i64) {
        q = pruv_m_f_1_2_wr(&mut *out, q, (48i64 + ((v / p) % 10i64)));
        p = (p / 10i64);
    }
    return q;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_7_attr_at(rec: &[i64], t: &[i64], c: i64, which: i64) -> i64 {
    let mut k: i64 = pruv_m_f_1_2_nf(t, c, 4i64);
    if ((k < 0i64) || (k > 1099511627776i64)) {
        return (-1i64);
    }
    let mut w: i64 = 0i64;
    while ((w < which) && (w < 3i64)) {
        let m: i64 = pruv_m_f_1_1_g(rec, k);
        if ((m < (-1i64)) || (m > 1099511627776i64)) {
            return (-1i64);
        }
        k = (k + 1i64);
        if (m > 0i64) {
            k = (k + m);
        }
        w = (w + 1i64);
    }
    return k;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_8_esc_text(rec: &[i64], a: i64, n: i64, attr: i64, out: &mut [i64], q0: i64) -> i64 {
    let mut q: i64 = pruv_m_f_1_2_wr(&mut *out, (-1i64), 0i64);
    q = q0;
    if ((q < 0i64) || (q > 1125899906842624i64)) {
        q = 0i64;
    }
    if ((((a < 0i64) || (a > 1099511627776i64)) || (n < 0i64)) || (n > 1099511627776i64)) {
        return q;
    }
    let mut k: i64 = 0i64;
    while (k < n) {
        let c: i64 = pruv_m_f_1_1_g(rec, (a + k));
        if (c == 38i64) {
            q = pruv_m_f_1_7_put_str(&mut *out, q, &::std::string::String::from("&amp;"));
        } else {
            if (c == 60i64) {
                q = pruv_m_f_1_7_put_str(&mut *out, q, &::std::string::String::from("&lt;"));
            } else {
                if (c == 62i64) {
                    q = pruv_m_f_1_7_put_str(&mut *out, q, &::std::string::String::from("&gt;"));
                } else {
                    if ((c == 34i64) && (attr == 1i64)) {
                        q = pruv_m_f_1_7_put_str(&mut *out, q, &::std::string::String::from("&quot;"));
                    } else {
                        q = pruv_m_f_1_2_wr(&mut *out, q, c);
                    }
                }
            }
        }
        k = (k + 1i64);
    }
    return q;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_8_open_tag(rec: &[i64], t: &[i64], c: i64, bn: i64, spans: i64, out: &mut [i64], q0: i64) -> i64 {
    let mut q: i64 = pruv_m_f_1_2_wr(&mut *out, q0, 60i64);
    q = pruv_m_f_1_9_copy_text(rec, pruv_m_f_1_2_nf(t, c, 2i64), pruv_m_f_1_2_nf(t, c, 3i64), &mut *out, q);
    if ((bn > 0i64) && (bn <= 1125899906842624i64)) {
        q = pruv_m_f_1_7_put_str(&mut *out, q, &::std::string::String::from(" data-block=\u{22}"));
        q = pruv_m_f_1_7_put_num__pruv_body(&mut *out, q, bn);
        q = pruv_m_f_1_2_wr(&mut *out, q, 34i64);
    }
    if (spans == 1i64) {
        let mut w: i64 = 1i64;
        while (w <= 2i64) {
            let k: i64 = pruv_m_f_1_7_attr_at(rec, t, c, w);
            let m: i64 = pruv_m_f_1_1_g(rec, k);
            if ((m >= 1i64) && (m <= 3i64)) {
                let mut digits: i64 = 1i64;
                let mut j: i64 = 1i64;
                while (j <= m) {
                    let x: i64 = pruv_m_f_1_1_g(rec, (k + j));
                    if ((x < 48i64) || (x > 57i64)) {
                        digits = 0i64;
                    }
                    j = (j + 1i64);
                }
                if (digits == 1i64) {
                    if (w == 1i64) {
                        q = pruv_m_f_1_7_put_str(&mut *out, q, &::std::string::String::from(" colspan=\u{22}"));
                    } else {
                        q = pruv_m_f_1_7_put_str(&mut *out, q, &::std::string::String::from(" rowspan=\u{22}"));
                    }
                    q = pruv_m_f_1_9_copy_text(rec, (k + 1i64), m, &mut *out, q);
                    q = pruv_m_f_1_2_wr(&mut *out, q, 34i64);
                }
            }
            w = (w + 1i64);
        }
    }
    return pruv_m_f_1_2_wr(&mut *out, q, 62i64);
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_9_close_tag(rec: &[i64], t: &[i64], c: i64, out: &mut [i64], q0: i64) -> i64 {
    let mut q: i64 = pruv_m_f_1_2_wr(&mut *out, q0, 60i64);
    q = pruv_m_f_1_2_wr(&mut *out, q, 47i64);
    q = pruv_m_f_1_9_copy_text(rec, pruv_m_f_1_2_nf(t, c, 2i64), pruv_m_f_1_2_nf(t, c, 3i64), &mut *out, q);
    return pruv_m_f_1_2_wr(&mut *out, q, 62i64);
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_10_https_href(rec: &[i64], t: &[i64], c: i64) -> bool {
    let k: i64 = pruv_m_f_1_7_attr_at(rec, t, c, 0i64);
    let m: i64 = pruv_m_f_1_1_g(rec, k);
    if (((m < 8i64) || (k < 0i64)) || (k > 3298534883328i64)) {
        return false;
    }
    let w: ::std::string::String = ::std::string::String::from("https://");
    let mut j: i64 = 0i64;
    while (j < 8i64) {
        let y: i64 = ((unsafe { *w.as_bytes().get_unchecked((j) as usize) }) as i64);
        if (pruv_m_f_1_4_lowc(pruv_m_f_1_1_g(rec, ((k + 1i64) + j))) != y) {
            return false;
        }
        j = (j + 1i64);
    }
    return true;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_6_render(rec: &[i64], root: i64, t: &[i64], sk: &mut [i64], out: &mut [i64], q0: i64) -> i64 {
    let mut q: i64 = pruv_m_f_1_2_wr(&mut *out, (-1i64), 0i64);
    q = q0;
    if ((q < 0i64) || (q > 1125899906842624i64)) {
        q = 0i64;
    }
    let mut d: i64 = 1i64;
    pruv_m_f_1_2_sv(&mut *sk, 0i64, root);
    pruv_m_f_1_2_sv(&mut *sk, 1i64, pruv_m_f_1_2_nf(t, root, 5i64));
    pruv_m_f_1_2_sv(&mut *sk, 2i64, 2i64);
    pruv_m_f_1_2_sv(&mut *sk, 3i64, 0i64);
    pruv_m_f_1_2_sv(&mut *sk, 4i64, 0i64);
    let mut fuel: i64 = ((2i64 * (t.len() as i64)) + 10i64);
    while ((d > 0i64) && (fuel > 0i64)) {
        fuel = (fuel - 1i64);
        let b: i64 = ((5i64 * d) - 5i64);
        let nd: i64 = pruv_m_f_1_1_g(&*sk, b);
        let c: i64 = pruv_m_f_1_1_g(&*sk, (b + 1i64));
        let ph: i64 = pruv_m_f_1_1_g(&*sk, (b + 2i64));
        let ic: i64 = pruv_m_f_1_1_g(&*sk, (b + 3i64));
        if (c < 0i64) {
            if (ph == 0i64) {
                pruv_m_f_1_2_sv(&mut *sk, (b + 1i64), pruv_m_f_1_2_nf(t, nd, 5i64));
                pruv_m_f_1_2_sv(&mut *sk, (b + 2i64), 1i64);
            } else {
                if (pruv_m_f_1_1_g(&*sk, (b + 4i64)) == 1i64) {
                    q = pruv_m_f_1_9_close_tag(rec, t, nd, &mut *out, q);
                }
                d = (d - 1i64);
            }
        } else {
            pruv_m_f_1_2_sv(&mut *sk, (b + 1i64), pruv_m_f_1_2_nf(t, c, 6i64));
            let kd: i64 = pruv_m_f_1_2_nf(t, c, 0i64);
            if (kd == 0i64) {
                if (ph != 1i64) {
                    q = pruv_m_f_1_8_esc_text(rec, pruv_m_f_1_2_nf(t, c, 2i64), pruv_m_f_1_2_nf(t, c, 3i64), 0i64, &mut *out, q);
                }
            } else {
                if (kd == 1i64) {
                    let tg: i64 = pruv_m_f_1_2_nf(t, c, 1i64);
                    let mut go: i64 = 1i64;
                    if ((ph == 0i64) && (tg == 3i64)) {
                        go = 0i64;
                    }
                    if ((ph == 1i64) && (tg != 3i64)) {
                        go = 0i64;
                    }
                    if (tg == 13i64) {
                        go = 0i64;
                    }
                    if (go == 1i64) {
                        let bn: i64 = pruv_m_f_1_2_nf(t, c, 9i64);
                        let mut push: i64 = 1i64;
                        let mut nph: i64 = 2i64;
                        let mut nic: i64 = ic;
                        let mut ncl: i64 = 1i64;
                        if ((tg == 1i64) || (tg == 2i64)) {
                            if ((bn > 0i64) || (ic == 1i64)) {
                                q = pruv_m_f_1_8_open_tag(rec, t, c, bn, 0i64, &mut *out, q);
                            } else {
                                push = 0i64;
                            }
                        } else {
                            if (tg == 4i64) {
                                nic = 0i64;
                                if (bn > 0i64) {
                                    q = pruv_m_f_1_8_open_tag(rec, t, c, bn, 0i64, &mut *out, q);
                                    nph = 0i64;
                                } else {
                                    nph = 1i64;
                                    ncl = 0i64;
                                }
                            } else {
                                if (tg == 7i64) {
                                    q = pruv_m_f_1_8_open_tag(rec, t, c, bn, 0i64, &mut *out, q);
                                } else {
                                    if ((((tg == 3i64) || (tg == 5i64)) || (tg == 6i64)) || (tg == 9i64)) {
                                        q = pruv_m_f_1_8_open_tag(rec, t, c, 0i64, 0i64, &mut *out, q);
                                    } else {
                                        if (tg == 8i64) {
                                            q = pruv_m_f_1_8_open_tag(rec, t, c, 0i64, 1i64, &mut *out, q);
                                            nic = 1i64;
                                        } else {
                                            if (tg == 10i64) {
                                                q = pruv_m_f_1_7_put_str(&mut *out, q, &::std::string::String::from("<br>"));
                                                push = 0i64;
                                            } else {
                                                if (tg == 11i64) {
                                                    q = pruv_m_f_1_2_wr(&mut *out, q, 91i64);
                                                    q = pruv_m_f_1_2_wr(&mut *out, q, 44536i64);
                                                    q = pruv_m_f_1_2_wr(&mut *out, q, 47548i64);
                                                    q = pruv_m_f_1_2_wr(&mut *out, q, 93i64);
                                                    push = 0i64;
                                                } else {
                                                    if (tg == 12i64) {
                                                        if pruv_m_f_1_10_https_href(rec, t, c) {
                                                            let k: i64 = pruv_m_f_1_7_attr_at(rec, t, c, 0i64);
                                                            q = pruv_m_f_1_7_put_str(&mut *out, q, &::std::string::String::from("<a href=\u{22}"));
                                                            q = pruv_m_f_1_8_esc_text(rec, (k + 1i64), pruv_m_f_1_1_g(rec, k), 1i64, &mut *out, q);
                                                            q = pruv_m_f_1_7_put_str(&mut *out, q, &::std::string::String::from("\u{22} rel=\u{22}noopener noreferrer\u{22}>"));
                                                        } else {
                                                            ncl = 0i64;
                                                        }
                                                    } else {
                                                        ncl = 0i64;
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                        if (((push == 1i64) && (((5i64 * d) + 4i64) < (sk.len() as i64))) && (d < 1099511627776i64)) {
                            pruv_m_f_1_2_sv(&mut *sk, (5i64 * d), c);
                            pruv_m_f_1_2_sv(&mut *sk, ((5i64 * d) + 1i64), pruv_m_f_1_2_nf(t, c, 5i64));
                            pruv_m_f_1_2_sv(&mut *sk, ((5i64 * d) + 2i64), nph);
                            pruv_m_f_1_2_sv(&mut *sk, ((5i64 * d) + 3i64), nic);
                            pruv_m_f_1_2_sv(&mut *sk, ((5i64 * d) + 4i64), ncl);
                            d = (d + 1i64);
                        }
                    }
                }
            }
        }
    }
    return q;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_4_walk(rec: &[i64], root: i64, t: &mut [i64], tmp: &mut [i64], row: &mut [i64], sk: &mut [i64], ik: &mut [i64], out: &mut [i64]) -> i64 {
    pruv_m_f_1_4_nset(&mut *t, root, 9i64, 0i64);
    let mut q: i64 = pruv_m_f_1_2_wr(&mut *out, 0i64, 0i64);
    q = pruv_m_f_1_7_collect(rec, root, &mut *t, &mut *tmp, &mut *row, &mut *sk, &mut *ik, &mut *out, q);
    pruv_m_f_1_2_sv(&mut *out, 0i64, pruv_m_f_1_2_nf(&*t, root, 9i64));
    let hs: i64 = pruv_m_f_1_2_wr(&mut *out, q, 0i64);
    let he: i64 = pruv_m_f_1_6_render(rec, root, &*t, &mut *sk, &mut *out, hs);
    pruv_m_f_1_2_sv(&mut *out, (hs - 1i64), (he - hs));
    return he;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
pub fn docx_parts(rec: &[i64]) -> ::std::vec::Vec<i64> {
    let l: i64 = (rec.len() as i64);
    if (l > 68719476736i64) {
        let bad: ::std::vec::Vec<i64> = { let pruv_n: i64 = 1i64; let pruv_v: i64 = (-1i64); vec![pruv_v; pruv_n as usize] };
        return bad;
    }
    let mut p: i64 = 0i64;
    let mut m: i64 = 0i64;
    let mut e: i64 = 0i64;
    let mut ok: i64 = 1i64;
    while ((ok == 1i64) && (p < l)) {
        let nxt: i64 = pruv_m_f_1_8_rec_next__pruv_body(rec, p, e);
        if (nxt < 0i64) {
            ok = 0i64;
        } else {
            if ((unsafe { *rec.get_unchecked((p) as usize) }) == 1i64) {
                e = (e + 1i64);
            }
            m = (m + 1i64);
            p = nxt;
        }
    }
    if (ok == 0i64) {
        let bad: ::std::vec::Vec<i64> = { let pruv_n: i64 = 1i64; let pruv_v: i64 = (-1i64); vec![pruv_v; pruv_n as usize] };
        return bad;
    }
    let mut t: ::std::vec::Vec<i64> = { let pruv_n: i64 = ((10i64 * m) + 10i64); let pruv_v: i64 = (-1i64); vec![pruv_v; pruv_n as usize] };
    let mut eln: ::std::vec::Vec<i64> = { let pruv_n: i64 = (e + 1i64); let pruv_v: i64 = (-1i64); vec![pruv_v; pruv_n as usize] };
    p = 0i64;
    let mut i: i64 = 0i64;
    let mut en: i64 = 0i64;
    while (p < l) {
        let nxt: i64 = pruv_m_f_1_8_rec_next__pruv_body(rec, p, en);
        if (((nxt < 0i64) || ((unsafe { *rec.get_unchecked(((p + 2i64)) as usize) }) < 0i64)) || ((unsafe { *rec.get_unchecked(((p + 2i64)) as usize) }) > l)) {
            p = l;
        } else {
            let kind: i64 = (unsafe { *rec.get_unchecked((p) as usize) });
            let par: i64 = (unsafe { *rec.get_unchecked(((p + 1i64)) as usize) });
            let n: i64 = (unsafe { *rec.get_unchecked(((p + 2i64)) as usize) });
            let mut pn: i64 = m;
            if (par >= 0i64) {
                pn = pruv_m_f_1_1_g(&eln, par);
            }
            pruv_m_f_1_4_nset(&mut t, i, 0i64, kind);
            pruv_m_f_1_4_nset(&mut t, i, 2i64, (p + 3i64));
            pruv_m_f_1_4_nset(&mut t, i, 3i64, n);
            if (kind == 1i64) {
                pruv_m_f_1_4_nset(&mut t, i, 1i64, pruv_m_f_1_8_classify(rec, (p + 3i64), n));
                pruv_m_f_1_4_nset(&mut t, i, 4i64, ((p + 3i64) + n));
                pruv_m_f_1_4_nset(&mut t, i, 8i64, en);
                pruv_m_f_1_2_sv(&mut eln, en, i);
                en = (en + 1i64);
            }
            let lc: i64 = pruv_m_f_1_2_nf(&t, pn, 7i64);
            if (lc < 0i64) {
                pruv_m_f_1_4_nset(&mut t, pn, 5i64, i);
            } else {
                pruv_m_f_1_4_nset(&mut t, lc, 6i64, i);
            }
            pruv_m_f_1_4_nset(&mut t, pn, 7i64, i);
            i = (i + 1i64);
            p = nxt;
        }
    }
    let s: i64 = ((l + (8i64 * m)) + 8i64);
    let mut tmp: ::std::vec::Vec<i64> = { let pruv_n: i64 = s; let pruv_v: i64 = 0i64; vec![pruv_v; pruv_n as usize] };
    let mut row: ::std::vec::Vec<i64> = { let pruv_n: i64 = s; let pruv_v: i64 = 0i64; vec![pruv_v; pruv_n as usize] };
    let mut sk: ::std::vec::Vec<i64> = { let pruv_n: i64 = ((5i64 * m) + 10i64); let pruv_v: i64 = 0i64; vec![pruv_v; pruv_n as usize] };
    let mut ik: ::std::vec::Vec<i64> = { let pruv_n: i64 = ((2i64 * m) + 4i64); let pruv_v: i64 = 0i64; vec![pruv_v; pruv_n as usize] };
    let mut none: ::std::vec::Vec<i64> = { let pruv_n: i64 = 0i64; let pruv_v: i64 = 0i64; vec![pruv_v; pruv_n as usize] };
    let k: i64 = pruv_m_f_1_4_walk(rec, m, &mut t, &mut tmp, &mut row, &mut sk, &mut ik, &mut none);
    if (k > 1099511627776i64) {
        let bad: ::std::vec::Vec<i64> = { let pruv_n: i64 = 1i64; let pruv_v: i64 = (-1i64); vec![pruv_v; pruv_n as usize] };
        return bad;
    }
    let mut out: ::std::vec::Vec<i64> = { let pruv_n: i64 = k; let pruv_v: i64 = 0i64; vec![pruv_v; pruv_n as usize] };
    let f: i64 = pruv_m_f_1_4_walk(rec, m, &mut t, &mut tmp, &mut row, &mut sk, &mut ik, &mut out);
    return out;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
pub fn img_count(s: &str) -> i64 {
    let n: i64 = (s.len() as i64);
    let mut c: i64 = 0i64;
    let mut i: i64 = 0i64;
    while ((i + 4i64) <= n) {
        if ((((((unsafe { *s.as_bytes().get_unchecked((i) as usize) }) as i64) == 60i64) && (pruv_m_f_1_4_lowc(((unsafe { *s.as_bytes().get_unchecked(((i + 1i64)) as usize) }) as i64)) == 105i64)) && (pruv_m_f_1_4_lowc(((unsafe { *s.as_bytes().get_unchecked(((i + 2i64)) as usize) }) as i64)) == 109i64)) && (pruv_m_f_1_4_lowc(((unsafe { *s.as_bytes().get_unchecked(((i + 3i64)) as usize) }) as i64)) == 103i64)) {
            let mut hit: bool = true;
            if ((i + 4i64) < n) {
                if pruv_m_f_1_5_wordc(((unsafe { *s.as_bytes().get_unchecked(((i + 4i64)) as usize) }) as i64)) {
                    hit = false;
                }
            }
            if hit {
                c = (c + 1i64);
            }
        }
        i = (i + 1i64);
    }
    return c;
}

