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
fn png_step__pruv_body(width: i64, height: i64, max_pixels: i64) -> i64 {
    let wh: i64 = (width * height);
    if (wh <= max_pixels) {
        return 1i64;
    }
    let q: i64 = (((wh + max_pixels) - 1i64) / max_pixels);
    let mut s: i64 = 1i64;
    while ((s < 1048577i64) && ((s * s) < q)) {
        s = (s + 1i64);
    }
    return s;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
#[inline]
pub fn png_step(width: i64, height: i64, max_pixels: i64) -> i64 {
    let mut pruv_budget: i64 = 1_073_741_824;
    if !(((((1i128 <= (width as i128)) && (1i128 <= (height as i128))) && ((width as i128) <= 1099511627776i128)) && ((height as i128) <= 1099511627776i128))) { panic!("{}", "pruv: requires violated: crate::png_step: ((((1 <= width) && (1 <= height)) && (width <= 1099511627776)) && (height <= 1099511627776))"); }
    if !((pruv_cmul((width as i128), (height as i128)) <= 1099511627776i128)) { panic!("{}", "pruv: requires violated: crate::png_step: ((width * height) <= 1099511627776)"); }
    if !(((1i128 <= (max_pixels as i128)) && ((max_pixels as i128) <= 1099511627776i128))) { panic!("{}", "pruv: requires violated: crate::png_step: ((1 <= max_pixels) && (max_pixels <= 1099511627776))"); }
    png_step__pruv_body(width, height, max_pixels)
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_6_bit_at__pruv_body(b: i64, bit: i64) -> i64 {
    let mut v: i64 = b;
    let mut k: i64 = (7i64 - bit);
    while (k > 0i64) {
        v = (v / 2i64);
        k = (k - 1i64);
    }
    return (v % 2i64);
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_5_blend__pruv_body(c: i64, a: i64) -> i64 {
    let n: i64 = ((c * a) + (255i64 * (255i64 - a)));
    return (((2i64 * n) + 255i64) / 510i64);
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_8_png_fill__pruv_body(data: &[u8], width: i64, kind: i64, step: i64, out_w: i64, raw: &mut [u8]) -> i64 {
    let mut ch: i64 = 3i64;
    if (kind == 1i64) {
        ch = 1i64;
    }
    let row_bytes: i64 = (1i64 + (out_w * ch));
    let n: i64 = (data.len() as i64);
    let bit_row: i64 = ((width + 7i64) / 8i64);
    let mut base: i64 = 0i64;
    let mut row: i64 = 0i64;
    let mut white: i64 = 0i64;
    while ((row + row_bytes) <= (raw.len() as i64)) {
        { let pruv_i: i64 = row; let pruv_x: i64 = 0i64; unsafe { *raw.get_unchecked_mut(pruv_i as usize) = pruv_x as u8; } }
        let mut at: i64 = (row + 1i64);
        let mut sx: i64 = 0i64;
        while (((sx + step) <= ((width + step) - 1i64)) && ((at + ch) <= (row + row_bytes))) {
            if (kind == 1i64) {
                let from: i64 = (base + (sx / 8i64));
                let mut bit: i64 = 0i64;
                if (from < n) {
                    bit = pruv_m_f_1_6_bit_at__pruv_body(((unsafe { *data.get_unchecked((from) as usize) }) as i64), (sx % 8i64));
                }
                { let pruv_i: i64 = at; let pruv_x: i64 = (255i64 * bit); unsafe { *raw.get_unchecked_mut(pruv_i as usize) = pruv_x as u8; } }
                white = (white + bit);
            } else {
                if (kind == 2i64) {
                    let from: i64 = ((base + sx) * 3i64);
                    let mut c0: i64 = 0i64;
                    let mut c1: i64 = 0i64;
                    let mut c2: i64 = 0i64;
                    if (from < n) {
                        c0 = ((unsafe { *data.get_unchecked((from) as usize) }) as i64);
                    }
                    if ((from + 1i64) < n) {
                        c1 = ((unsafe { *data.get_unchecked(((from + 1i64)) as usize) }) as i64);
                    }
                    if ((from + 2i64) < n) {
                        c2 = ((unsafe { *data.get_unchecked(((from + 2i64)) as usize) }) as i64);
                    }
                    { let pruv_i: i64 = at; let pruv_x: i64 = c0; unsafe { *raw.get_unchecked_mut(pruv_i as usize) = pruv_x as u8; } }
                    { let pruv_i: i64 = (at + 1i64); let pruv_x: i64 = c1; unsafe { *raw.get_unchecked_mut(pruv_i as usize) = pruv_x as u8; } }
                    { let pruv_i: i64 = (at + 2i64); let pruv_x: i64 = c2; unsafe { *raw.get_unchecked_mut(pruv_i as usize) = pruv_x as u8; } }
                } else {
                    let from: i64 = ((base + sx) * 4i64);
                    let mut c0: i64 = 0i64;
                    let mut c1: i64 = 0i64;
                    let mut c2: i64 = 0i64;
                    if ((from + 3i64) < n) {
                        let a: i64 = ((unsafe { *data.get_unchecked(((from + 3i64)) as usize) }) as i64);
                        c0 = pruv_m_f_1_5_blend__pruv_body(((unsafe { *data.get_unchecked((from) as usize) }) as i64), a);
                        c1 = pruv_m_f_1_5_blend__pruv_body(((unsafe { *data.get_unchecked(((from + 1i64)) as usize) }) as i64), a);
                        c2 = pruv_m_f_1_5_blend__pruv_body(((unsafe { *data.get_unchecked(((from + 2i64)) as usize) }) as i64), a);
                    }
                    { let pruv_i: i64 = at; let pruv_x: i64 = c0; unsafe { *raw.get_unchecked_mut(pruv_i as usize) = pruv_x as u8; } }
                    { let pruv_i: i64 = (at + 1i64); let pruv_x: i64 = c1; unsafe { *raw.get_unchecked_mut(pruv_i as usize) = pruv_x as u8; } }
                    { let pruv_i: i64 = (at + 2i64); let pruv_x: i64 = c2; unsafe { *raw.get_unchecked_mut(pruv_i as usize) = pruv_x as u8; } }
                }
            }
            at = (at + ch);
            sx = (sx + step);
        }
        row = (row + row_bytes);
        let mut j: i64 = 0i64;
        while (j < step) {
            if (kind == 1i64) {
                base = (base + bit_row);
            } else {
                base = (base + width);
            }
            if (base > n) {
                base = (n + 1i64);
            }
            j = (j + 1i64);
        }
    }
    return white;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_10_png_invert__pruv_body(raw: &mut [u8], out_w: i64) {
    let row_bytes: i64 = (1i64 + out_w);
    let mut row: i64 = 0i64;
    while ((row + row_bytes) <= (raw.len() as i64)) {
        let mut at: i64 = (row + 1i64);
        while (at < (row + row_bytes)) {
            let v: i64 = ((unsafe { *raw.get_unchecked((at) as usize) }) as i64);
            { let pruv_i: i64 = at; let pruv_x: i64 = (255i64 - v); unsafe { *raw.get_unchecked_mut(pruv_i as usize) = pruv_x as u8; } }
            at = (at + 1i64);
        }
        row = (row + row_bytes);
    }
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn png_scanlines__pruv_body(data: &[u8], width: i64, height: i64, kind: i64, max_pixels: i64) -> ::std::vec::Vec<u8> {
    let step: i64 = png_step__pruv_body(width, height, max_pixels);
    let out_w: i64 = (width / step);
    let out_h: i64 = (height / step);
    if ((out_w < 1i64) || (out_h < 1i64)) {
        return { let pruv_n: i64 = 0i64; let pruv_v: i64 = 0i64; vec![pruv_v as u8; pruv_n as usize] };
    }
    let mut ch: i64 = 3i64;
    if (kind == 1i64) {
        ch = 1i64;
    }
    let row_bytes: i64 = (1i64 + (out_w * ch));
    if (out_h > (1099511627776i64 / row_bytes)) {
        return { let pruv_n: i64 = 0i64; let pruv_v: i64 = 0i64; vec![pruv_v as u8; pruv_n as usize] };
    }
    let mut raw: ::std::vec::Vec<u8> = { let pruv_n: i64 = (row_bytes * out_h); let pruv_v: i64 = 0i64; vec![pruv_v as u8; pruv_n as usize] };
    let white: i64 = pruv_m_f_1_8_png_fill__pruv_body(data, width, kind, step, out_w, &mut raw);
    if ((kind == 1i64) && ((2i64 * white) < (out_w * out_h))) {
        pruv_m_f_1_10_png_invert__pruv_body(&mut raw, out_w);
    }
    return raw;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
#[inline]
pub fn png_scanlines(data: &[u8], width: i64, height: i64, kind: i64, max_pixels: i64) -> ::std::vec::Vec<u8> {
    let mut pruv_budget: i64 = 1_073_741_824;
    if !(((((1i128 <= (width as i128)) && (1i128 <= (height as i128))) && ((width as i128) <= 1099511627776i128)) && ((height as i128) <= 1099511627776i128))) { panic!("{}", "pruv: requires violated: crate::png_scanlines: ((((1 <= width) && (1 <= height)) && (width <= 1099511627776)) && (height <= 1099511627776))"); }
    if !((pruv_cmul((width as i128), (height as i128)) <= 1099511627776i128)) { panic!("{}", "pruv: requires violated: crate::png_scanlines: ((width * height) <= 1099511627776)"); }
    if !(((1i128 <= (max_pixels as i128)) && ((max_pixels as i128) <= 1099511627776i128))) { panic!("{}", "pruv: requires violated: crate::png_scanlines: ((1 <= max_pixels) && (max_pixels <= 1099511627776))"); }
    if !(((1i128 <= (kind as i128)) && ((kind as i128) <= 3i128))) { panic!("{}", "pruv: requires violated: crate::png_scanlines: ((1 <= kind) && (kind <= 3))"); }
    png_scanlines__pruv_body(data, width, height, kind, max_pixels)
}

