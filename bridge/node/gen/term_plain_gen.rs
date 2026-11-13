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
fn pack__pruv_body(a: i64, skip: bool, e: i64) -> i64 {
    let mut s: i64 = a;
    if skip {
        s = (a + 6i64);
    }
    return ((s * 4i64) + e);
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]
#[inline]
pub fn pack(a: i64, skip: bool, e: i64) -> i64 {
    let mut pruv_budget: i64 = 1_073_741_824;
    if !(((((0i128 <= (a as i128)) && ((a as i128) < 6i128)) && (0i128 <= (e as i128))) && ((e as i128) < 3i128))) { panic!("{}", "pruv: requires violated: pack: ((((0 <= a) && (a < 6)) && (0 <= e)) && (e < 3))"); }
    pack__pruv_body(a, skip, e)
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]
fn emit__pruv_body(skip: bool, c: i64) -> i64 {
    if (skip && (c == 10i64)) {
        return pack__pruv_body(0i64, false, 0i64);
    }
    if (c == 13i64) {
        return pack__pruv_body(0i64, true, 2i64);
    }
    return pack__pruv_body(0i64, false, 1i64);
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]
#[inline]
pub fn emit(skip: bool, c: i64) -> i64 {
    let mut pruv_budget: i64 = 1_073_741_824;
    if !(((0i128 <= (c as i128)) && ((c as i128) <= 256i128))) { panic!("{}", "pruv: requires violated: emit: ((0 <= c) && (c <= 256))"); }
    emit__pruv_body(skip, c)
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]
fn trans__pruv_body(st: i64, c: i64) -> i64 {
    let skip: bool = (st >= 6i64);
    let mut a: i64 = (st % 6i64);
    if (a == 5i64) {
        if (c == 92i64) {
            return pack__pruv_body(0i64, skip, 0i64);
        }
        a = 4i64;
    }
    if ((a == 1i64) || (a == 2i64)) {
        if ((32i64 <= c) && (c <= 47i64)) {
            return pack__pruv_body(2i64, skip, 0i64);
        }
        if (a == 1i64) {
            if (c == 91i64) {
                return pack__pruv_body(3i64, skip, 0i64);
            }
            if (((((c == 93i64) || (c == 80i64)) || (c == 88i64)) || (c == 94i64)) || (c == 95i64)) {
                return pack__pruv_body(4i64, skip, 0i64);
            }
        }
        if ((48i64 <= c) && (c <= 126i64)) {
            return pack__pruv_body(0i64, skip, 0i64);
        }
        a = 0i64;
    }
    if (a == 3i64) {
        if ((64i64 <= c) && (c <= 126i64)) {
            return pack__pruv_body(0i64, skip, 0i64);
        }
        return pack__pruv_body(3i64, skip, 0i64);
    }
    if (a == 4i64) {
        if ((c == 7i64) || (c == 156i64)) {
            return pack__pruv_body(0i64, skip, 0i64);
        }
        if (c == 27i64) {
            return pack__pruv_body(5i64, skip, 0i64);
        }
        return pack__pruv_body(4i64, skip, 0i64);
    }
    if (c == 27i64) {
        return pack__pruv_body(1i64, skip, 0i64);
    }
    if (c == 155i64) {
        return pack__pruv_body(3i64, skip, 0i64);
    }
    if (((((c == 157i64) || (c == 144i64)) || (c == 159i64)) || (c == 158i64)) || (c == 152i64)) {
        return pack__pruv_body(4i64, skip, 0i64);
    }
    if (((c == 9i64) || (c == 10i64)) || (c == 13i64)) {
        return emit__pruv_body(skip, c);
    }
    if (((c < 32i64) || (c == 127i64)) || ((128i64 <= c) && (c <= 159i64))) {
        return pack__pruv_body(0i64, skip, 0i64);
    }
    return emit__pruv_body(skip, c);
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]
#[inline]
pub fn trans(st: i64, c: i64) -> i64 {
    let mut pruv_budget: i64 = 1_073_741_824;
    if !(((((0i128 <= (st as i128)) && ((st as i128) < 12i128)) && (0i128 <= (c as i128))) && ((c as i128) <= 256i128))) { panic!("{}", "pruv: requires violated: trans: ((((0 <= st) && (st < 12)) && (0 <= c)) && (c <= 256))"); }
    trans__pruv_body(st, c)
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]
fn class__pruv_body(s: &str, i: i64) -> i64 {
    let b: i64 = ((unsafe { *s.as_bytes().get_unchecked((i) as usize) }) as i64);
    if (b < 128i64) {
        return b;
    }
    if ((b == 194i64) && ((i + 1i64) < (s.len() as i64))) {
        if (((unsafe { *s.as_bytes().get_unchecked(((i + 1i64)) as usize) }) as i64) < 160i64) {
            return ((unsafe { *s.as_bytes().get_unchecked(((i + 1i64)) as usize) }) as i64);
        }
    }
    return 256i64;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]
#[inline]
pub fn class(s: &str, i: i64) -> i64 {
    let mut pruv_budget: i64 = 1_073_741_824;
    if !(((0i128 <= (i as i128)) && ((i as i128) < (s.len() as i128)))) { panic!("{}", "pruv: requires violated: class: ((0 <= i) && (i < len(s)))"); }
    class__pruv_body(s, i)
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]
fn next__pruv_body(s: &str, i: i64) -> i64 {
    let mut j: i64 = (i + 1i64);
    while ((j < (s.len() as i64)) && (!pruv_str_boundary(s, j))) {
        j = (j + 1i64);
    }
    return j;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]
#[inline]
pub fn next(s: &str, i: i64) -> i64 {
    let mut pruv_budget: i64 = 1_073_741_824;
    if !(((0i128 <= (i as i128)) && ((i as i128) < (s.len() as i128)))) { panic!("{}", "pruv: requires violated: next: ((0 <= i) && (i < len(s)))"); }
    next__pruv_body(s, i)
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]
fn term_plain__pruv_body(state: i64, data: &str) -> ::std::string::String {
    let mut st: i64 = state;
    let mut out: ::std::string::String = pruv_g6_string_new();
    let mut i: i64 = 0i64;
    while (i < (data.len() as i64)) {
        let j: i64 = next__pruv_body(data, i);
        let t: i64 = trans__pruv_body(st, class__pruv_body(data, i));
        st = (t / 4i64);
        let e: i64 = (t % 4i64);
        if (e == 1i64) {
            let piece: ::std::string::String = { let pruv_s: &str = data; let pruv_lo: i64 = i; let pruv_hi: i64 = j; ::std::string::String::from(unsafe { pruv_s.get_unchecked((pruv_lo as usize)..(pruv_hi as usize)) }) };
            out = pruv_g6_string_push_str(out, &piece);
        }
        if (e == 2i64) {
            out = pruv_g6_string_push_str(out, &::std::string::String::from("\u{a}"));
        }
        i = j;
    }
    return pruv_g6_string_to_str(&out);
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]
#[inline]
pub fn term_plain(state: i64, data: &str) -> ::std::string::String {
    let mut pruv_budget: i64 = 1_073_741_824;
    if !(((0i128 <= (state as i128)) && ((state as i128) < 12i128))) { panic!("{}", "pruv: requires violated: term_plain: ((0 <= state) && (state < 12))"); }
    if !(((data.len() as i128) <= 1000000000000i128)) { panic!("{}", "pruv: requires violated: term_plain: (len(data) <= 1000000000000)"); }
    term_plain__pruv_body(state, data)
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]
fn term_state__pruv_body(state: i64, data: &str) -> i64 {
    let mut st: i64 = state;
    let mut i: i64 = 0i64;
    while (i < (data.len() as i64)) {
        st = (trans__pruv_body(st, class__pruv_body(data, i)) / 4i64);
        i = next__pruv_body(data, i);
    }
    return st;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]
#[inline]
pub fn term_state(state: i64, data: &str) -> i64 {
    let mut pruv_budget: i64 = 1_073_741_824;
    if !(((0i128 <= (state as i128)) && ((state as i128) < 12i128))) { panic!("{}", "pruv: requires violated: term_state: ((0 <= state) && (state < 12))"); }
    if !(((data.len() as i128) <= 1000000000000i128)) { panic!("{}", "pruv: requires violated: term_state: (len(data) <= 1000000000000)"); }
    term_state__pruv_body(state, data)
}

