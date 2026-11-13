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
fn pruv_m_f_1_3_u16__pruv_body(b: &[u8], i: i64, little: i64) -> i64 {
    if (little == 1i64) {
        return (((unsafe { *b.get_unchecked((i) as usize) }) as i64) + (256i64 * ((unsafe { *b.get_unchecked(((i + 1i64)) as usize) }) as i64)));
    }
    return ((256i64 * ((unsafe { *b.get_unchecked((i) as usize) }) as i64)) + ((unsafe { *b.get_unchecked(((i + 1i64)) as usize) }) as i64));
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_3_u32__pruv_body(b: &[u8], i: i64, little: i64) -> i64 {
    if (little == 1i64) {
        return (((((unsafe { *b.get_unchecked((i) as usize) }) as i64) + (256i64 * ((unsafe { *b.get_unchecked(((i + 1i64)) as usize) }) as i64))) + (65536i64 * ((unsafe { *b.get_unchecked(((i + 2i64)) as usize) }) as i64))) + (16777216i64 * ((unsafe { *b.get_unchecked(((i + 3i64)) as usize) }) as i64)));
    }
    return ((((16777216i64 * ((unsafe { *b.get_unchecked((i) as usize) }) as i64)) + (65536i64 * ((unsafe { *b.get_unchecked(((i + 1i64)) as usize) }) as i64))) + (256i64 * ((unsafe { *b.get_unchecked(((i + 2i64)) as usize) }) as i64))) + ((unsafe { *b.get_unchecked(((i + 3i64)) as usize) }) as i64));
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_21_orientation_from_tiff__pruv_body(b: &[u8], tiff: i64, end: i64) -> i64 {
    if ((tiff + 8i64) > end) {
        return 1i64;
    }
    let mut little: i64 = 0i64;
    if ((((unsafe { *b.get_unchecked((tiff) as usize) }) as i64) == 73i64) && (((unsafe { *b.get_unchecked(((tiff + 1i64)) as usize) }) as i64) == 73i64)) {
        little = 1i64;
    } else {
        if ((((unsafe { *b.get_unchecked((tiff) as usize) }) as i64) == 77i64) && (((unsafe { *b.get_unchecked(((tiff + 1i64)) as usize) }) as i64) == 77i64)) {
            little = 0i64;
        } else {
            return 1i64;
        }
    }
    if (pruv_m_f_1_3_u16__pruv_body(b, (tiff + 2i64), little) != 42i64) {
        return 1i64;
    }
    let ifd: i64 = (tiff + pruv_m_f_1_3_u32__pruv_body(b, (tiff + 4i64), little));
    if ((ifd + 2i64) > end) {
        return 1i64;
    }
    let count: i64 = pruv_m_f_1_3_u16__pruv_body(b, ifd, little);
    let mut i: i64 = 0i64;
    while (i < count) {
        let entry: i64 = ((ifd + 2i64) + (i * 12i64));
        if ((entry + 12i64) > end) {
            return 1i64;
        }
        if (pruv_m_f_1_3_u16__pruv_body(b, entry, little) == 274i64) {
            let value: i64 = pruv_m_f_1_3_u16__pruv_body(b, (entry + 8i64), little);
            if ((value >= 1i64) && (value <= 8i64)) {
                return value;
            }
            return 1i64;
        }
        i = (i + 1i64);
    }
    return 1i64;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn jpeg_orientation__pruv_body(b: &[u8]) -> i64 {
    let mut pos: i64 = 2i64;
    while ((pos + 4i64) <= (b.len() as i64)) {
        if (((unsafe { *b.get_unchecked((pos) as usize) }) as i64) != 255i64) {
            return 1i64;
        }
        let marker: i64 = ((unsafe { *b.get_unchecked(((pos + 1i64)) as usize) }) as i64);
        if (marker == 255i64) {
            pos = (pos + 1i64);
        } else {
            if (((marker == 216i64) || (marker == 1i64)) || ((marker >= 208i64) && (marker <= 215i64))) {
                pos = (pos + 2i64);
            } else {
                if ((marker == 218i64) || (marker == 217i64)) {
                    return 1i64;
                }
                let length: i64 = ((256i64 * ((unsafe { *b.get_unchecked(((pos + 2i64)) as usize) }) as i64)) + ((unsafe { *b.get_unchecked(((pos + 3i64)) as usize) }) as i64));
                if (length < 2i64) {
                    return 1i64;
                }
                let mut end: i64 = ((pos + 2i64) + length);
                if (end > (b.len() as i64)) {
                    end = (b.len() as i64);
                }
                if ((((((((marker == 225i64) && ((pos + 10i64) <= end)) && (((unsafe { *b.get_unchecked(((pos + 4i64)) as usize) }) as i64) == 69i64)) && (((unsafe { *b.get_unchecked(((pos + 5i64)) as usize) }) as i64) == 120i64)) && (((unsafe { *b.get_unchecked(((pos + 6i64)) as usize) }) as i64) == 105i64)) && (((unsafe { *b.get_unchecked(((pos + 7i64)) as usize) }) as i64) == 102i64)) && (((unsafe { *b.get_unchecked(((pos + 8i64)) as usize) }) as i64) == 0i64)) && (((unsafe { *b.get_unchecked(((pos + 9i64)) as usize) }) as i64) == 0i64)) {
                    return pruv_m_f_1_21_orientation_from_tiff__pruv_body(b, (pos + 10i64), end);
                }
                pos = ((pos + 2i64) + length);
            }
        }
    }
    return 1i64;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
#[inline]
pub fn jpeg_orientation(b: &[u8]) -> i64 {
    let mut pruv_budget: i64 = 1_073_741_824;
    if !(((b.len() as i128) <= 1099511627776i128)) { panic!("{}", "pruv: requires violated: crate::jpeg_orientation: (len(b) <= 1099511627776)"); }
    jpeg_orientation__pruv_body(b)
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_11_scaled_side__pruv_body(side: i64, long: i64) -> i64 {
    if (long <= 2000i64) {
        return side;
    }
    let mut v: i64 = (((4000i64 * side) + long) / (2i64 * long));
    if (v < 1i64) {
        v = 1i64;
    }
    if (v > 2000i64) {
        v = 2000i64;
    }
    return v;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_9_long_side__pruv_body(width: i64, height: i64) -> i64 {
    if (width >= height) {
        return width;
    }
    return height;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn shrink_width__pruv_body(width: i64, height: i64) -> i64 {
    return pruv_m_f_1_11_scaled_side__pruv_body(width, pruv_m_f_1_9_long_side__pruv_body(width, height));
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
#[inline]
pub fn shrink_width(width: i64, height: i64) -> i64 {
    let mut pruv_budget: i64 = 1_073_741_824;
    if !(((((1i128 <= (width as i128)) && ((width as i128) <= 65535i128)) && (1i128 <= (height as i128))) && ((height as i128) <= 65535i128))) { panic!("{}", "pruv: requires violated: crate::shrink_width: ((((1 <= width) && (width <= 65535)) && (1 <= height)) && (height <= 65535))"); }
    shrink_width__pruv_body(width, height)
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn shrink_height__pruv_body(width: i64, height: i64) -> i64 {
    return pruv_m_f_1_11_scaled_side__pruv_body(height, pruv_m_f_1_9_long_side__pruv_body(width, height));
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
#[inline]
pub fn shrink_height(width: i64, height: i64) -> i64 {
    let mut pruv_budget: i64 = 1_073_741_824;
    if !(((((1i128 <= (width as i128)) && ((width as i128) <= 65535i128)) && (1i128 <= (height as i128))) && ((height as i128) <= 65535i128))) { panic!("{}", "pruv: requires violated: crate::shrink_height: ((((1 <= width) && (width <= 65535)) && (1 <= height)) && (height <= 65535))"); }
    shrink_height__pruv_body(width, height)
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
fn pruv_m_f_1_10_box_shrink__pruv_body(data: &[u8], width: i64, height: i64, out_w: i64, out_h: i64, out: &mut [u8]) {
    let mut write: i64 = 0i64;
    let mut oy: i64 = 0i64;
    while (oy < out_h) {
        let y0: i64 = pruv_m_f_1_7_edge_lo__pruv_body(oy, height, out_h);
        let y1: i64 = pruv_m_f_1_7_edge_hi__pruv_body(oy, height, out_h, y0);
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
            if ((write + 3i64) < (out.len() as i64)) {
                { let pruv_i: i64 = write; let pruv_x: i64 = pruv_m_f_1_3_avg__pruv_body(r, n); unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x as u8; } }
                { let pruv_i: i64 = (write + 1i64); let pruv_x: i64 = pruv_m_f_1_3_avg__pruv_body(g, n); unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x as u8; } }
                { let pruv_i: i64 = (write + 2i64); let pruv_x: i64 = pruv_m_f_1_3_avg__pruv_body(b, n); unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x as u8; } }
                { let pruv_i: i64 = (write + 3i64); let pruv_x: i64 = 255i64; unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x as u8; } }
            }
            write = (write + 4i64);
            ox = (ox + 1i64);
        }
        oy = (oy + 1i64);
    }
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_6_orient__pruv_body(src: &[u8], width: i64, height: i64, orientation: i64, out: &mut [u8]) {
    let mut out_w: i64 = width;
    if (orientation >= 5i64) {
        out_w = height;
    }
    let mut y: i64 = 0i64;
    while (y < height) {
        let mut x: i64 = 0i64;
        while (x < width) {
            let mut dx: i64 = x;
            let mut dy: i64 = y;
            if (orientation == 2i64) {
                dx = ((width - 1i64) - x);
            } else {
                if (orientation == 3i64) {
                    dx = ((width - 1i64) - x);
                    dy = ((height - 1i64) - y);
                } else {
                    if (orientation == 4i64) {
                        dy = ((height - 1i64) - y);
                    } else {
                        if (orientation == 5i64) {
                            dx = y;
                            dy = x;
                        } else {
                            if (orientation == 6i64) {
                                dx = ((height - 1i64) - y);
                                dy = x;
                            } else {
                                if (orientation == 7i64) {
                                    dx = ((height - 1i64) - y);
                                    dy = ((width - 1i64) - x);
                                } else {
                                    dx = y;
                                    dy = ((width - 1i64) - x);
                                }
                            }
                        }
                    }
                }
            }
            let t: i64 = (((dy * out_w) + dx) * 4i64);
            let f: i64 = (((y * width) + x) * 4i64);
            if (((t + 3i64) < (out.len() as i64)) && ((f + 3i64) < (src.len() as i64))) {
                { let pruv_i: i64 = t; let pruv_x: i64 = ((unsafe { *src.get_unchecked((f) as usize) }) as i64); unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x as u8; } }
                { let pruv_i: i64 = (t + 1i64); let pruv_x: i64 = ((unsafe { *src.get_unchecked(((f + 1i64)) as usize) }) as i64); unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x as u8; } }
                { let pruv_i: i64 = (t + 2i64); let pruv_x: i64 = ((unsafe { *src.get_unchecked(((f + 2i64)) as usize) }) as i64); unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x as u8; } }
                { let pruv_i: i64 = (t + 3i64); let pruv_x: i64 = ((unsafe { *src.get_unchecked(((f + 3i64)) as usize) }) as i64); unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x as u8; } }
            }
            x = (x + 1i64);
        }
        y = (y + 1i64);
    }
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn shrink_pixels__pruv_body(data: &[u8], width: i64, height: i64, orientation: i64) -> ::std::vec::Vec<u8> {
    if ((pruv_m_f_1_9_long_side__pruv_body(width, height) <= 2000i64) && (orientation == 1i64)) {
        return { let pruv_n: i64 = 0i64; let pruv_v: i64 = 0i64; vec![pruv_v as u8; pruv_n as usize] };
    }
    let sw: i64 = shrink_width__pruv_body(width, height);
    let sh: i64 = shrink_height__pruv_body(width, height);
    let mut scaled: ::std::vec::Vec<u8> = { let pruv_n: i64 = ((4i64 * sw) * sh); let pruv_v: i64 = 0i64; vec![pruv_v as u8; pruv_n as usize] };
    pruv_m_f_1_10_box_shrink__pruv_body(data, width, height, sw, sh, &mut scaled);
    if (orientation == 1i64) {
        return scaled;
    }
    let mut out: ::std::vec::Vec<u8> = { let pruv_n: i64 = ((4i64 * sw) * sh); let pruv_v: i64 = 0i64; vec![pruv_v as u8; pruv_n as usize] };
    pruv_m_f_1_6_orient__pruv_body(&scaled, sw, sh, orientation, &mut out);
    return out;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
#[inline]
pub fn shrink_pixels(data: &[u8], width: i64, height: i64, orientation: i64) -> ::std::vec::Vec<u8> {
    let mut pruv_budget: i64 = 1_073_741_824;
    if !(((((1i128 <= (width as i128)) && ((width as i128) <= 65535i128)) && (1i128 <= (height as i128))) && ((height as i128) <= 65535i128))) { panic!("{}", "pruv: requires violated: crate::shrink_pixels: ((((1 <= width) && (width <= 65535)) && (1 <= height)) && (height <= 65535))"); }
    if !(((1i128 <= (orientation as i128)) && ((orientation as i128) <= 8i128))) { panic!("{}", "pruv: requires violated: crate::shrink_pixels: ((1 <= orientation) && (orientation <= 8))"); }
    shrink_pixels__pruv_body(data, width, height, orientation)
}

