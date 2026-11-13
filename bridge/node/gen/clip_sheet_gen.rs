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
fn pruv_cidx_u8(a: &[u8], i: i128) -> i128 { if i >= 0 && i < (a.len() as i128) { a[i as usize] as i128 } else { pruv_ud("array index out of range") } }

#[allow(dead_code)]
#[inline]
fn pruv_cidx_str(a: &str, i: i128) -> i128 { if i >= 0 && i < (a.len() as i128) { a.as_bytes()[i as usize] as i128 } else { pruv_ud("array index out of range") } }
#[allow(dead_code)]
#[inline]
fn pruv_cboundary(a: &str, i: i128) -> bool { i >= 0 && i <= (a.len() as i128) && a.is_char_boundary(i as usize) }

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_11_sheet_bytes() -> i64 {
    return 5740800i64;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_3_put__pruv_body(s: &mut [u8], at: i64, r: i64, g: i64, b: i64) {
    if ((0i64 <= at) && (at < ((s.len() as i64) - 3i64))) {
        { let pruv_i: i64 = at; let pruv_x: i64 = r; unsafe { *s.get_unchecked_mut(pruv_i as usize) = pruv_x as u8; } }
        { let pruv_i: i64 = (at + 1i64); let pruv_x: i64 = g; unsafe { *s.get_unchecked_mut(pruv_i as usize) = pruv_x as u8; } }
        { let pruv_i: i64 = (at + 2i64); let pruv_x: i64 = b; unsafe { *s.get_unchecked_mut(pruv_i as usize) = pruv_x as u8; } }
        { let pruv_i: i64 = (at + 3i64); let pruv_x: i64 = 255i64; unsafe { *s.get_unchecked_mut(pruv_i as usize) = pruv_x as u8; } }
    }
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_9_fill_rect__pruv_body(s: &mut [u8], x: i64, y: i64, w: i64, h: i64, r: i64, g: i64, b: i64) {
    let mut row: i64 = y;
    while (row < (y + h)) {
        let mut at: i64 = (((row * 1560i64) + x) * 4i64);
        let mut col: i64 = 0i64;
        while (col < w) {
            pruv_m_f_1_3_put__pruv_body(&mut *s, at, r, g, b);
            at = (at + 4i64);
            col = (col + 1i64);
        }
        row = (row + 1i64);
    }
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_5_units(t: &str) -> i64 {
    let mut n: i64 = 0i64;
    let mut i: i64 = 0i64;
    while (i < (t.len() as i64)) {
        let c: i64 = ((unsafe { *t.as_bytes().get_unchecked((i) as usize) }) as i64);
        if ((c < 128i64) || (c >= 192i64)) {
            n = (n + 1i64);
        }
        if (c >= 240i64) {
            n = (n + 1i64);
        }
        i = (i + 1i64);
    }
    return n;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_5_glyph__pruv_body(c: i64, k: i64) -> i64 {
    if (c == 48i64) {
        if (k == 0i64) {
            return 14i64;
        }
        if (k == 1i64) {
            return 17i64;
        }
        if (k == 2i64) {
            return 19i64;
        }
        if (k == 3i64) {
            return 21i64;
        }
        if (k == 4i64) {
            return 25i64;
        }
        if (k == 5i64) {
            return 17i64;
        }
        return 14i64;
    }
    if (c == 49i64) {
        if (k == 0i64) {
            return 4i64;
        }
        if (k == 1i64) {
            return 12i64;
        }
        if (k == 6i64) {
            return 14i64;
        }
        return 4i64;
    }
    if (c == 50i64) {
        if (k == 0i64) {
            return 14i64;
        }
        if (k == 1i64) {
            return 17i64;
        }
        if (k == 2i64) {
            return 1i64;
        }
        if (k == 3i64) {
            return 2i64;
        }
        if (k == 4i64) {
            return 4i64;
        }
        if (k == 5i64) {
            return 8i64;
        }
        return 31i64;
    }
    if (c == 51i64) {
        if (k == 0i64) {
            return 30i64;
        }
        if (k == 3i64) {
            return 14i64;
        }
        if (k == 6i64) {
            return 30i64;
        }
        return 1i64;
    }
    if (c == 52i64) {
        if (k == 0i64) {
            return 2i64;
        }
        if (k == 1i64) {
            return 6i64;
        }
        if (k == 2i64) {
            return 10i64;
        }
        if (k == 3i64) {
            return 18i64;
        }
        if (k == 4i64) {
            return 31i64;
        }
        return 2i64;
    }
    if (c == 53i64) {
        if (k == 0i64) {
            return 31i64;
        }
        if (k == 1i64) {
            return 16i64;
        }
        if (k == 2i64) {
            return 30i64;
        }
        if (k == 5i64) {
            return 17i64;
        }
        if (k == 6i64) {
            return 14i64;
        }
        return 1i64;
    }
    if (c == 54i64) {
        if (k == 0i64) {
            return 6i64;
        }
        if (k == 1i64) {
            return 8i64;
        }
        if (k == 2i64) {
            return 16i64;
        }
        if (k == 3i64) {
            return 30i64;
        }
        if (k == 6i64) {
            return 14i64;
        }
        return 17i64;
    }
    if (c == 55i64) {
        if (k == 0i64) {
            return 31i64;
        }
        if (k == 1i64) {
            return 1i64;
        }
        if (k == 2i64) {
            return 2i64;
        }
        if (k == 3i64) {
            return 4i64;
        }
        return 8i64;
    }
    if (c == 56i64) {
        if (((k == 0i64) || (k == 3i64)) || (k == 6i64)) {
            return 14i64;
        }
        return 17i64;
    }
    if (c == 57i64) {
        if (k == 0i64) {
            return 14i64;
        }
        if (k == 3i64) {
            return 15i64;
        }
        if (k == 4i64) {
            return 1i64;
        }
        if (k == 5i64) {
            return 2i64;
        }
        if (k == 6i64) {
            return 12i64;
        }
        return 17i64;
    }
    if (c == 58i64) {
        if (((k == 0i64) || (k == 3i64)) || (k == 6i64)) {
            return 0i64;
        }
        return 4i64;
    }
    if (c == 46i64) {
        if ((k == 5i64) || (k == 6i64)) {
            return 12i64;
        }
        return 0i64;
    }
    return (-1i64);
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_9_draw_text__pruv_body(s: &mut [u8], x: i64, y: i64, t: &str) {
    let mut left: i64 = x;
    let mut i: i64 = 0i64;
    while (i < (t.len() as i64)) {
        let c: i64 = ((unsafe { *t.as_bytes().get_unchecked((i) as usize) }) as i64);
        if ((c < 128i64) || (c >= 192i64)) {
            if (pruv_m_f_1_5_glyph__pruv_body(c, 0i64) >= 0i64) {
                let mut row: i64 = 0i64;
                while (row < 7i64) {
                    let bits: i64 = pruv_m_f_1_5_glyph__pruv_body(c, row);
                    let mut col: i64 = 0i64;
                    while (col < 5i64) {
                        let mut p: i64 = 16i64;
                        if (col == 1i64) {
                            p = 8i64;
                        }
                        if (col == 2i64) {
                            p = 4i64;
                        }
                        if (col == 3i64) {
                            p = 2i64;
                        }
                        if (col == 4i64) {
                            p = 1i64;
                        }
                        if ((bits >= 0i64) && (((bits / p) % 2i64) == 1i64)) {
                            pruv_m_f_1_9_fill_rect__pruv_body(&mut *s, (left + (col * 2i64)), (y + (row * 2i64)), 2i64, 2i64, 255i64, 255i64, 255i64);
                        }
                        col = (col + 1i64);
                    }
                    row = (row + 1i64);
                }
            }
            left = (left + 12i64);
        }
        i = (i + 1i64);
    }
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_7_edge_lo__pruv_body(o: i64, size: i64, out: i64) -> i64 {
    let mut v: i64 = ((o * size) / out);
    if (v > (size - 1i64)) {
        v = (size - 1i64);
    }
    return v;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_7_edge_hi__pruv_body(o: i64, size: i64, out: i64, lo: i64) -> i64 {
    let mut v: i64 = (((o + 1i64) * size) / out);
    if (v < (lo + 1i64)) {
        v = (lo + 1i64);
    }
    if (v > size) {
        v = size;
    }
    return v;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_2_at__pruv_body(data: &[u8], i: i64) -> i64 {
    if (i < (data.len() as i64)) {
        return ((unsafe { *data.get_unchecked((i) as usize) }) as i64);
    }
    return 0i64;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_3_avg__pruv_body(s: i64, n: i64) -> i64 {
    let v: i64 = (((2i64 * s) + n) / (2i64 * n));
    if (v > 255i64) {
        return 255i64;
    }
    return v;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_11_draw_fitted__pruv_body(s: &mut [u8], data: &[u8], width: i64, height: i64, out_w: i64, out_h: i64, left: i64, top: i64) {
    let origin_x: i64 = (left + ((768i64 - out_w) / 2i64));
    let origin_y: i64 = (top + ((432i64 - out_h) / 2i64));
    let mut oy: i64 = 0i64;
    while (oy < out_h) {
        let y0: i64 = pruv_m_f_1_7_edge_lo__pruv_body(oy, height, out_h);
        let y1: i64 = pruv_m_f_1_7_edge_hi__pruv_body(oy, height, out_h, y0);
        let mut write: i64 = ((((origin_y + oy) * 1560i64) + origin_x) * 4i64);
        let mut ox: i64 = 0i64;
        while (ox < out_w) {
            let x0: i64 = pruv_m_f_1_7_edge_lo__pruv_body(ox, width, out_w);
            let x1: i64 = pruv_m_f_1_7_edge_hi__pruv_body(ox, width, out_w, x0);
            let mut r: i64 = 0i64;
            let mut g: i64 = 0i64;
            let mut b: i64 = 0i64;
            let mut y: i64 = y0;
            while (y < y1) {
                let mut read: i64 = (((y * width) + x0) * 4i64);
                let mut x: i64 = x0;
                while (x < x1) {
                    r = (r + pruv_m_f_1_2_at__pruv_body(data, read));
                    g = (g + pruv_m_f_1_2_at__pruv_body(data, (read + 1i64)));
                    b = (b + pruv_m_f_1_2_at__pruv_body(data, (read + 2i64)));
                    read = (read + 4i64);
                    x = (x + 1i64);
                }
                y = (y + 1i64);
            }
            let n: i64 = ((y1 - y0) * (x1 - x0));
            pruv_m_f_1_3_put__pruv_body(&mut *s, write, pruv_m_f_1_3_avg__pruv_body(r, n), pruv_m_f_1_3_avg__pruv_body(g, n), pruv_m_f_1_3_avg__pruv_body(b, n));
            write = (write + 4i64);
            ox = (ox + 1i64);
        }
        oy = (oy + 1i64);
    }
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
pub fn clip_sheet_background() -> ::std::vec::Vec<u8> {
    let mut s: ::std::vec::Vec<u8> = { let pruv_n: i64 = pruv_m_f_1_11_sheet_bytes(); let pruv_v: i64 = 0i64; vec![pruv_v as u8; pruv_n as usize] };
    pruv_m_f_1_9_fill_rect__pruv_body(&mut s, 0i64, 0i64, 1560i64, 920i64, 13i64, 17i64, 23i64);
    return s;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn clip_sheet_cell__pruv_body(sheet: &[u8], index: i64, data: &[u8], width: i64, height: i64, out_w: i64, out_h: i64, label: &str, number: &str) -> ::std::vec::Vec<u8> {
    let mut s: ::std::vec::Vec<u8> = sheet.to_vec();
    let mut left: i64 = 8i64;
    if ((index % 2i64) == 1i64) {
        left = 784i64;
    }
    let mut top: i64 = 8i64;
    if (index >= 2i64) {
        top = 468i64;
    }
    pruv_m_f_1_11_draw_fitted__pruv_body(&mut s, data, width, height, out_w, out_h, left, top);
    let strip_top: i64 = (top + 432i64);
    pruv_m_f_1_9_fill_rect__pruv_body(&mut s, left, strip_top, 768i64, 20i64, 0i64, 0i64, 0i64);
    pruv_m_f_1_9_draw_text__pruv_body(&mut s, ((left + 385i64) - (6i64 * pruv_m_f_1_5_units(label))), (strip_top + 3i64), label);
    pruv_m_f_1_9_fill_rect__pruv_body(&mut s, left, top, (((12i64 * pruv_m_f_1_5_units(number)) - 2i64) + 8i64), 22i64, 0i64, 0i64, 0i64);
    pruv_m_f_1_9_draw_text__pruv_body(&mut s, (left + 4i64), (top + 4i64), number);
    return s;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
#[inline]
pub fn clip_sheet_cell(sheet: &[u8], index: i64, data: &[u8], width: i64, height: i64, out_w: i64, out_h: i64, label: &str, number: &str) -> ::std::vec::Vec<u8> {
    let mut pruv_budget: i64 = 1_073_741_824;
    if !(((((sheet.len() as i128) == 5740800i128) && (0i128 <= (index as i128))) && ((index as i128) <= 3i128))) { panic!("{}", "pruv: requires violated: crate::clip_sheet_cell: (((len(sheet) == 5740800) && (0 <= index)) && (index <= 3))"); }
    if !(((((1i128 <= (width as i128)) && ((width as i128) <= 65535i128)) && (1i128 <= (height as i128))) && ((height as i128) <= 65535i128))) { panic!("{}", "pruv: requires violated: crate::clip_sheet_cell: ((((1 <= width) && (width <= 65535)) && (1 <= height)) && (height <= 65535))"); }
    if !(((((1i128 <= (out_w as i128)) && ((out_w as i128) <= 768i128)) && (1i128 <= (out_h as i128))) && ((out_h as i128) <= 432i128))) { panic!("{}", "pruv: requires violated: crate::clip_sheet_cell: ((((1 <= out_w) && (out_w <= 768)) && (1 <= out_h)) && (out_h <= 432))"); }
    if !((((label.len() as i128) <= 1000000i128) && ((number.len() as i128) <= 4096i128))) { panic!("{}", "pruv: requires violated: crate::clip_sheet_cell: ((len(label) <= 1000000) && (len(number) <= 4096))"); }
    clip_sheet_cell__pruv_body(sheet, index, data, width, height, out_w, out_h, label, number)
}

