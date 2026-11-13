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
fn pruv_cidx_u8(a: &[u8], i: i128) -> i128 { if i >= 0 && i < (a.len() as i128) { a[i as usize] as i128 } else { pruv_ud("array index out of range") } }

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
fn utf8_lossy(data: &[u8], from: i64) -> ::std::string::String {
    let pruv_g = pruv_ctx("utf8_lossy");
    let mut pruv_budget: i64 = 1_073_741_824;
    if !(((0i128 <= (from as i128)) && ((from as i128) <= (data.len() as i128)))) { pruv_g6_req("utf8_lossy", "((0 <= from) && (from <= len(data)))"); }
    let result: ::std::string::String = match ::std::panic::catch_unwind(::std::panic::AssertUnwindSafe(|| ::pruv_decode::utf8_lossy(data, from))) {
        Ok(pruv_r) => pruv_r,
        Err(_) => panic!("pruv: foreign panic: utf8_lossy"),
    };
    if (result.len() as u128) > (1u128 << 40) { pruv_g6_repr("utf8_lossy: result length"); }
    result
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]
fn pruv_g6_string_to_str(s: &::std::string::String) -> ::std::string::String {
    let pruv_g = pruv_ctx("string_to_str");
    let pruv_r: ::std::string::String = s.clone();
    pruv_r
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]
fn utf16(data: &[u8], from: i64, big: bool) -> ::std::string::String {
    let pruv_g = pruv_ctx("utf16");
    let mut pruv_budget: i64 = 1_073_741_824;
    if !(((0i128 <= (from as i128)) && ((from as i128) <= (data.len() as i128)))) { pruv_g6_req("utf16", "((0 <= from) && (from <= len(data)))"); }
    let result: ::std::string::String = match ::std::panic::catch_unwind(::std::panic::AssertUnwindSafe(|| ::pruv_decode::utf16(data, from, big))) {
        Ok(pruv_r) => pruv_r,
        Err(_) => panic!("pruv: foreign panic: utf16"),
    };
    if (result.len() as u128) > (1u128 << 40) { pruv_g6_repr("utf16: result length"); }
    result
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]
fn utf8_copy(data: &[u8]) -> ::std::string::String {
    let pruv_g = pruv_ctx("utf8_copy");
    let mut pruv_budget: i64 = 1_073_741_824;
    let result: ::std::string::String = match ::std::panic::catch_unwind(::std::panic::AssertUnwindSafe(|| ::pruv_decode::utf8_copy(data))) {
        Ok(pruv_r) => pruv_r,
        Err(_) => panic!("pruv: foreign panic: utf8_copy"),
    };
    if (result.len() as u128) > (1u128 << 40) { pruv_g6_repr("utf8_copy: result length"); }
    result
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]
fn euc_kr(data: &[u8]) -> ::std::string::String {
    let pruv_g = pruv_ctx("euc_kr");
    let mut pruv_budget: i64 = 1_073_741_824;
    let result: ::std::string::String = match ::std::panic::catch_unwind(::std::panic::AssertUnwindSafe(|| ::pruv_decode::euc_kr(data))) {
        Ok(pruv_r) => pruv_r,
        Err(_) => panic!("pruv: foreign panic: euc_kr"),
    };
    if (result.len() as u128) > (1u128 << 40) { pruv_g6_repr("euc_kr: result length"); }
    result
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]
fn utf8_ok__pruv_body(a: &[u8]) -> bool {
    let mut i: i64 = 0i64;
    while (i < (a.len() as i64)) {
        let b: i64 = ((unsafe { *a.get_unchecked((i) as usize) }) as i64);
        if (b <= 127i64) {
            i = (i + 1i64);
        } else {
            let mut need: i64 = 0i64;
            let mut lo: i64 = 128i64;
            let mut hi: i64 = 191i64;
            if ((194i64 <= b) && (b <= 223i64)) {
                need = 1i64;
            }
            if ((224i64 <= b) && (b <= 239i64)) {
                need = 2i64;
                if (b == 224i64) {
                    lo = 160i64;
                }
                if (b == 237i64) {
                    hi = 159i64;
                }
            }
            if ((240i64 <= b) && (b <= 244i64)) {
                need = 3i64;
                if (b == 240i64) {
                    lo = 144i64;
                }
                if (b == 244i64) {
                    hi = 143i64;
                }
            }
            if (need == 0i64) {
                return false;
            }
            if ((i + need) >= (a.len() as i64)) {
                return false;
            }
            let c: i64 = ((unsafe { *a.get_unchecked(((i + 1i64)) as usize) }) as i64);
            if ((c < lo) || (c > hi)) {
                return false;
            }
            let mut k: i64 = 2i64;
            while (k <= need) {
                let d: i64 = ((unsafe { *a.get_unchecked(((i + k)) as usize) }) as i64);
                if ((d < 128i64) || (d > 191i64)) {
                    return false;
                }
                k = (k + 1i64);
            }
            i = ((i + need) + 1i64);
        }
    }
    return true;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]
#[inline]
pub fn utf8_ok(a: &[u8]) -> bool {
    let mut pruv_budget: i64 = 1_073_741_824;
    if !(((a.len() as i128) <= 1000000000000i128)) { panic!("{}", "pruv: requires violated: utf8_ok: (len(a) <= 1000000000000)"); }
    utf8_ok__pruv_body(a)
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]
fn decode_kind__pruv_body(data: &[u8]) -> i64 {
    if (((((data.len() as i64) >= 3i64) && (((unsafe { *data.get_unchecked((0i64) as usize) }) as i64) == 239i64)) && (((unsafe { *data.get_unchecked((1i64) as usize) }) as i64) == 187i64)) && (((unsafe { *data.get_unchecked((2i64) as usize) }) as i64) == 191i64)) {
        return 0i64;
    }
    if ((((data.len() as i64) >= 2i64) && (((unsafe { *data.get_unchecked((0i64) as usize) }) as i64) == 255i64)) && (((unsafe { *data.get_unchecked((1i64) as usize) }) as i64) == 254i64)) {
        return 1i64;
    }
    if ((((data.len() as i64) >= 2i64) && (((unsafe { *data.get_unchecked((0i64) as usize) }) as i64) == 254i64)) && (((unsafe { *data.get_unchecked((1i64) as usize) }) as i64) == 255i64)) {
        return 2i64;
    }
    if utf8_ok__pruv_body(data) {
        return 3i64;
    }
    return 4i64;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]
#[inline]
pub fn decode_kind(data: &[u8]) -> i64 {
    let mut pruv_budget: i64 = 1_073_741_824;
    if !(((data.len() as i128) <= 1000000000000i128)) { panic!("{}", "pruv: requires violated: decode_kind: (len(data) <= 1000000000000)"); }
    decode_kind__pruv_body(data)
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]
fn decode_text__pruv_body(data: &[u8]) -> ::std::string::String {
    let k: i64 = decode_kind__pruv_body(data);
    if (k == 0i64) {
        let s: ::std::string::String = utf8_lossy(data, 3i64);
        return pruv_g6_string_to_str(&s);
    }
    if ((k == 1i64) || (k == 2i64)) {
        let s: ::std::string::String = utf16(data, 2i64, (k == 2i64));
        return pruv_g6_string_to_str(&s);
    }
    if (k == 3i64) {
        let s: ::std::string::String = utf8_copy(data);
        return pruv_g6_string_to_str(&s);
    }
    let s: ::std::string::String = euc_kr(data);
    return pruv_g6_string_to_str(&s);
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]
#[inline]
pub fn decode_text(data: &[u8]) -> ::std::string::String {
    let mut pruv_budget: i64 = 1_073_741_824;
    if !(((data.len() as i128) <= 1000000000000i128)) { panic!("{}", "pruv: requires violated: decode_text: (len(data) <= 1000000000000)"); }
    decode_text__pruv_body(data)
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]
fn looks_binary__pruv_body(data: &[u8]) -> bool {
    let mut i: i64 = 0i64;
    while ((i < (data.len() as i64)) && (i < 8192i64)) {
        if (((unsafe { *data.get_unchecked((i) as usize) }) as i64) == 0i64) {
            return true;
        }
        i = (i + 1i64);
    }
    return false;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]
#[inline]
pub fn looks_binary(data: &[u8]) -> bool {
    let mut pruv_budget: i64 = 1_073_741_824;
    if !(((data.len() as i128) <= 1000000000000i128)) { panic!("{}", "pruv: requires violated: looks_binary: (len(data) <= 1000000000000)"); }
    looks_binary__pruv_body(data)
}

