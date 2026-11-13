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
fn pruv_m_f_1_2_hv(b: i64) -> i64 {
    if ((48i64 <= b) && (b <= 57i64)) {
        return (b - 48i64);
    }
    if ((97i64 <= b) && (b <= 102i64)) {
        return (b - 87i64);
    }
    return 0i64;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]
fn pruv_m_f_1_5_word8__pruv_body(s: &str, at: i64) -> i64 {
    return ((((((((pruv_m_f_1_2_hv(((unsafe { *s.as_bytes().get_unchecked((at) as usize) }) as i64)) * 268435456i64) + (pruv_m_f_1_2_hv(((unsafe { *s.as_bytes().get_unchecked(((at + 1i64)) as usize) }) as i64)) * 16777216i64)) + (pruv_m_f_1_2_hv(((unsafe { *s.as_bytes().get_unchecked(((at + 2i64)) as usize) }) as i64)) * 1048576i64)) + (pruv_m_f_1_2_hv(((unsafe { *s.as_bytes().get_unchecked(((at + 3i64)) as usize) }) as i64)) * 65536i64)) + (pruv_m_f_1_2_hv(((unsafe { *s.as_bytes().get_unchecked(((at + 4i64)) as usize) }) as i64)) * 4096i64)) + (pruv_m_f_1_2_hv(((unsafe { *s.as_bytes().get_unchecked(((at + 5i64)) as usize) }) as i64)) * 256i64)) + (pruv_m_f_1_2_hv(((unsafe { *s.as_bytes().get_unchecked(((at + 6i64)) as usize) }) as i64)) * 16i64)) + pruv_m_f_1_2_hv(((unsafe { *s.as_bytes().get_unchecked(((at + 7i64)) as usize) }) as i64)));
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]
fn pruv_m_f_1_6_kconst__pruv_body(t: i64) -> i64 {
    let k: ::std::string::String = ::std::string::String::from("428a2f9871374491b5c0fbcfe9b5dba53956c25b59f111f1923f82a4ab1c5ed5d807aa9812835b01243185be550c7dc372be5d7480deb1fe9bdc06a7c19bf174e49b69c1efbe47860fc19dc6240ca1cc2de92c6f4a7484aa5cb0a9dc76f988da983e5152a831c66db00327c8bf597fc7c6e00bf3d5a7914706ca63511429296727b70a852e1b21384d2c6dfc53380d13650a7354766a0abb81c2c92e92722c85a2bfe8a1a81a664bc24b8b70c76c51a3d192e819d6990624f40e3585106aa07019a4c1161e376c082748774c34b0bcb5391c0cb34ed8aa4a5b9cca4f682e6ff3748f82ee78a5636f84c878148cc7020890befffaa4506cebbef9a3f7c67178f2");
    return pruv_m_f_1_5_word8__pruv_body(&k, (8i64 * t));
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]
fn pruv_m_f_1_4_bits__pruv_body(x: i64, y: i64, z: i64, mode: i64) -> i64 {
    let mut a: i64 = x;
    let mut b: i64 = y;
    let mut c: i64 = z;
    let mut r: i64 = 0i64;
    let mut p: i64 = 1i64;
    while (p < 4294967296i64) {
        let i: i64 = (a % 2i64);
        let j: i64 = (b % 2i64);
        let k: i64 = (c % 2i64);
        let mut v: i64 = 0i64;
        if (mode == 0i64) {
            v = (((i + j) + k) % 2i64);
        } else {
            if (mode == 1i64) {
                if (i == 1i64) {
                    v = j;
                } else {
                    v = k;
                }
            } else {
                if (((i + j) + k) >= 2i64) {
                    v = 1i64;
                }
            }
        }
        r = (r + (v * p));
        p = (p * 2i64);
        a = (a / 2i64);
        b = (b / 2i64);
        c = (c / 2i64);
    }
    return (r % 4294967296i64);
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]
fn pruv_m_f_1_4_big0__pruv_body(x: i64) -> i64 {
    let r2: i64 = (((x / 4i64) + ((x % 4i64) * 1073741824i64)) % 4294967296i64);
    let r13: i64 = (((x / 8192i64) + ((x % 8192i64) * 524288i64)) % 4294967296i64);
    let r22: i64 = (((x / 4194304i64) + ((x % 4194304i64) * 1024i64)) % 4294967296i64);
    return pruv_m_f_1_4_bits__pruv_body(r2, r13, r22, 0i64);
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]
fn pruv_m_f_1_4_big1__pruv_body(x: i64) -> i64 {
    let r6: i64 = (((x / 64i64) + ((x % 64i64) * 67108864i64)) % 4294967296i64);
    let r11: i64 = (((x / 2048i64) + ((x % 2048i64) * 2097152i64)) % 4294967296i64);
    let r25: i64 = (((x / 33554432i64) + ((x % 33554432i64) * 128i64)) % 4294967296i64);
    return pruv_m_f_1_4_bits__pruv_body(r6, r11, r25, 0i64);
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]
fn pruv_m_f_1_6_small0__pruv_body(x: i64) -> i64 {
    let r7: i64 = (((x / 128i64) + ((x % 128i64) * 33554432i64)) % 4294967296i64);
    let r18: i64 = (((x / 262144i64) + ((x % 262144i64) * 16384i64)) % 4294967296i64);
    return pruv_m_f_1_4_bits__pruv_body(r7, r18, (x / 8i64), 0i64);
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]
fn pruv_m_f_1_6_small1__pruv_body(x: i64) -> i64 {
    let r17: i64 = (((x / 131072i64) + ((x % 131072i64) * 32768i64)) % 4294967296i64);
    let r19: i64 = (((x / 524288i64) + ((x % 524288i64) * 8192i64)) % 4294967296i64);
    return pruv_m_f_1_4_bits__pruv_body(r17, r19, (x / 1024i64), 0i64);
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]
fn pruv_m_f_1_8_msg_byte__pruv_body(s: &str, i: i64, total: i64) -> i64 {
    let n: i64 = (s.len() as i64);
    if (i < n) {
        let b: i64 = ((unsafe { *s.as_bytes().get_unchecked((i) as usize) }) as i64);
        if ((b < 0i64) || (b > 255i64)) {
            return 0i64;
        }
        return b;
    }
    if (i == n) {
        return 128i64;
    }
    let j: i64 = (i - (total - 8i64));
    let bitlen: i64 = (8i64 * n);
    if (j == 4i64) {
        return ((bitlen / 16777216i64) % 256i64);
    }
    if (j == 5i64) {
        return ((bitlen / 65536i64) % 256i64);
    }
    if (j == 6i64) {
        return ((bitlen / 256i64) % 256i64);
    }
    if (j == 7i64) {
        return (bitlen % 256i64);
    }
    return 0i64;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]
fn pruv_m_f_1_4_hex8__pruv_body(x: i64) -> ::std::string::String {
    let hex: ::std::string::String = ::std::string::String::from("0123456789abcdef");
    let mut o: ::std::string::String = pruv_g6_string_new();
    let mut v: i64 = x;
    let mut k: i64 = 0i64;
    while (k < 8i64) {
        let d: i64 = (v / 268435456i64);
        o = pruv_g6_string_push_str(o, &{ let pruv_s: &str = &hex; let pruv_lo: i64 = d; let pruv_hi: i64 = (d + 1i64); ::std::string::String::from(unsafe { pruv_s.get_unchecked((pruv_lo as usize)..(pruv_hi as usize)) }) });
        v = ((v % 268435456i64) * 16i64);
        k = (k + 1i64);
    }
    return pruv_g6_string_to_str(&o);
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]
fn sha256_hex__pruv_body(s: &str) -> ::std::string::String {
    let total: i64 = (((((s.len() as i64) + 8i64) / 64i64) + 1i64) * 64i64);
    let mut h0: i64 = 1779033703i64;
    let mut h1: i64 = 3144134277i64;
    let mut h2: i64 = 1013904242i64;
    let mut h3: i64 = 2773480762i64;
    let mut h4: i64 = 1359893119i64;
    let mut h5: i64 = 2600822924i64;
    let mut h6: i64 = 528734635i64;
    let mut h7: i64 = 1541459225i64;
    let mut w: ::std::vec::Vec<i64> = { let pruv_n: i64 = 64i64; let pruv_v: i64 = 0i64; vec![pruv_v; pruv_n as usize] };
    let mut base: i64 = 0i64;
    while (base < total) {
        let mut t: i64 = 0i64;
        while (t < 64i64) {
            if (t < 16i64) {
                let at: i64 = (base + (4i64 * t));
                { let pruv_i: i64 = t; let pruv_x: i64 = ((((pruv_m_f_1_8_msg_byte__pruv_body(s, at, total) * 16777216i64) + (pruv_m_f_1_8_msg_byte__pruv_body(s, (at + 1i64), total) * 65536i64)) + (pruv_m_f_1_8_msg_byte__pruv_body(s, (at + 2i64), total) * 256i64)) + pruv_m_f_1_8_msg_byte__pruv_body(s, (at + 3i64), total)); unsafe { *w.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
            } else {
                { let pruv_i: i64 = t; let pruv_x: i64 = ((((pruv_m_f_1_6_small1__pruv_body((unsafe { *w.get_unchecked(((t - 2i64)) as usize) })) + (unsafe { *w.get_unchecked(((t - 7i64)) as usize) })) + pruv_m_f_1_6_small0__pruv_body((unsafe { *w.get_unchecked(((t - 15i64)) as usize) }))) + (unsafe { *w.get_unchecked(((t - 16i64)) as usize) })) % 4294967296i64); unsafe { *w.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
            }
            t = (t + 1i64);
        }
        let mut a: i64 = h0;
        let mut b: i64 = h1;
        let mut c: i64 = h2;
        let mut d: i64 = h3;
        let mut e: i64 = h4;
        let mut f: i64 = h5;
        let mut g: i64 = h6;
        let mut h: i64 = h7;
        t = 0i64;
        while (t < 64i64) {
            let t1: i64 = (((((h + pruv_m_f_1_4_big1__pruv_body(e)) + pruv_m_f_1_4_bits__pruv_body(e, f, g, 1i64)) + pruv_m_f_1_6_kconst__pruv_body(t)) + (unsafe { *w.get_unchecked((t) as usize) })) % 4294967296i64);
            let t2: i64 = ((pruv_m_f_1_4_big0__pruv_body(a) + pruv_m_f_1_4_bits__pruv_body(a, b, c, 2i64)) % 4294967296i64);
            h = g;
            g = f;
            f = e;
            e = ((d + t1) % 4294967296i64);
            d = c;
            c = b;
            b = a;
            a = ((t1 + t2) % 4294967296i64);
            t = (t + 1i64);
        }
        h0 = ((h0 + a) % 4294967296i64);
        h1 = ((h1 + b) % 4294967296i64);
        h2 = ((h2 + c) % 4294967296i64);
        h3 = ((h3 + d) % 4294967296i64);
        h4 = ((h4 + e) % 4294967296i64);
        h5 = ((h5 + f) % 4294967296i64);
        h6 = ((h6 + g) % 4294967296i64);
        h7 = ((h7 + h) % 4294967296i64);
        base = (base + 64i64);
    }
    let mut out: ::std::string::String = pruv_g6_string_new();
    out = pruv_g6_string_push_str(out, &pruv_m_f_1_4_hex8__pruv_body(h0));
    out = pruv_g6_string_push_str(out, &pruv_m_f_1_4_hex8__pruv_body(h1));
    out = pruv_g6_string_push_str(out, &pruv_m_f_1_4_hex8__pruv_body(h2));
    out = pruv_g6_string_push_str(out, &pruv_m_f_1_4_hex8__pruv_body(h3));
    out = pruv_g6_string_push_str(out, &pruv_m_f_1_4_hex8__pruv_body(h4));
    out = pruv_g6_string_push_str(out, &pruv_m_f_1_4_hex8__pruv_body(h5));
    out = pruv_g6_string_push_str(out, &pruv_m_f_1_4_hex8__pruv_body(h6));
    out = pruv_g6_string_push_str(out, &pruv_m_f_1_4_hex8__pruv_body(h7));
    return pruv_g6_string_to_str(&out);
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]
#[inline]
pub fn sha256_hex(s: &str) -> ::std::string::String {
    let mut pruv_budget: i64 = 1_073_741_824;
    if !(((s.len() as i128) <= 536870912i128)) { panic!("{}", "pruv: requires violated: crate::sha256_hex: (len(s) <= 536870912)"); }
    sha256_hex__pruv_body(s)
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]
fn extract_version_of__pruv_body(source: &str, kind: &str, variant: &str) -> ::std::string::String {
    let mut m: ::std::string::String = pruv_g6_string_new();
    m = pruv_g6_string_push_str(m, source);
    m = pruv_g6_string_push_str(m, &::std::string::String::from("\u{a}"));
    m = pruv_g6_string_push_str(m, kind);
    m = pruv_g6_string_push_str(m, &::std::string::String::from("\u{a}"));
    m = pruv_g6_string_push_str(m, variant);
    m = pruv_g6_string_push_str(m, &::std::string::String::from("\u{a}"));
    m = pruv_g6_string_push_str(m, &::std::string::String::from("rev2;pdfjs6.3.289;tesseract7.0.0;kor+eng 4.0.0_best_int;mammoth1.13.0;rxl9.3.10;papaparse5.7.0;chunk1500;scan100"));
    return sha256_hex__pruv_body(&pruv_g6_string_to_str(&m));
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]
#[inline]
pub fn extract_version_of(source: &str, kind: &str, variant: &str) -> ::std::string::String {
    let mut pruv_budget: i64 = 1_073_741_824;
    if !(((((source.len() as i128) <= 134217728i128) && ((kind.len() as i128) <= 134217728i128)) && ((variant.len() as i128) <= 134217728i128))) { panic!("{}", "pruv: requires violated: crate::extract_version_of: (((len(source) <= 134217728) && (len(kind) <= 134217728)) && (len(variant) <= 134217728))"); }
    extract_version_of__pruv_body(source, kind, variant)
}

