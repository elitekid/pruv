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

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_3_bit__pruv_body(given: i64, k: i64) -> i64 {
    let mut g: i64 = given;
    if (k >= 1i64) {
        g = (g / 2i64);
    }
    if (k >= 2i64) {
        g = (g / 2i64);
    }
    if (k >= 3i64) {
        g = (g / 2i64);
    }
    return (g % 2i64);
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn window_start__pruv_body(v: i64, present: i64) -> i64 {
    if (present == 0i64) {
        return 1i64;
    }
    if (v < 1i64) {
        return 1i64;
    }
    return v;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
#[inline]
pub fn window_start(v: i64, present: i64) -> i64 {
    let mut pruv_budget: i64 = 1_073_741_824;
    if !((((-9007199254740991i128) <= (v as i128)) && ((v as i128) <= 9007199254740991i128))) { panic!("{}", "pruv: requires violated: crate::window_start: ((-9007199254740991 <= v) && (v <= 9007199254740991))"); }
    window_start__pruv_body(v, present)
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn window_count__pruv_body(total: i64, start: i64, want: i64, present: i64, cap: i64, def: i64) -> i64 {
    let mut w: i64 = def;
    if (present != 0i64) {
        w = want;
    }
    if (w < 1i64) {
        w = 1i64;
    }
    if (w > cap) {
        w = cap;
    }
    let left: i64 = ((total - start) + 1i64);
    let mut n: i64 = w;
    if (left < n) {
        n = left;
    }
    if (n < 0i64) {
        n = 0i64;
    }
    return n;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
#[inline]
pub fn window_count(total: i64, start: i64, want: i64, present: i64, cap: i64, def: i64) -> i64 {
    let mut pruv_budget: i64 = 1_073_741_824;
    if !(((0i128 <= (total as i128)) && ((total as i128) <= 1000000000000i128))) { panic!("{}", "pruv: requires violated: crate::window_count: ((0 <= total) && (total <= 1000000000000))"); }
    if !(((1i128 <= (start as i128)) && ((start as i128) <= 9007199254740991i128))) { panic!("{}", "pruv: requires violated: crate::window_count: ((1 <= start) && (start <= 9007199254740991))"); }
    if !((((-9007199254740991i128) <= (want as i128)) && ((want as i128) <= 9007199254740991i128))) { panic!("{}", "pruv: requires violated: crate::window_count: ((-9007199254740991 <= want) && (want <= 9007199254740991))"); }
    if !((((1i128 <= (def as i128)) && ((def as i128) <= (cap as i128))) && ((cap as i128) <= 1000000i128))) { panic!("{}", "pruv: requires violated: crate::window_count: (((1 <= def) && (def <= cap)) && (cap <= 1000000))"); }
    window_count__pruv_body(total, start, want, present, cap, def)
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn sheet_range__pruv_body(total_rows: i64, total_cols: i64, row: i64, col: i64, rows: i64, cols: i64, given: i64) -> ::std::vec::Vec<i64> {
    let r: i64 = window_start__pruv_body(row, pruv_m_f_1_3_bit__pruv_body(given, 0i64));
    let c: i64 = window_start__pruv_body(col, pruv_m_f_1_3_bit__pruv_body(given, 1i64));
    let mut out: ::std::vec::Vec<i64> = { let pruv_n: i64 = 4i64; let pruv_v: i64 = 0i64; vec![pruv_v; pruv_n as usize] };
    { let pruv_i: i64 = 0i64; let pruv_x: i64 = r; unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
    { let pruv_i: i64 = 1i64; let pruv_x: i64 = c; unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
    { let pruv_i: i64 = 2i64; let pruv_x: i64 = window_count__pruv_body(total_rows, r, rows, pruv_m_f_1_3_bit__pruv_body(given, 2i64), 500i64, 200i64); unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
    { let pruv_i: i64 = 3i64; let pruv_x: i64 = window_count__pruv_body(total_cols, c, cols, pruv_m_f_1_3_bit__pruv_body(given, 3i64), 100i64, 50i64); unsafe { *out.get_unchecked_mut(pruv_i as usize) = pruv_x; } }
    return out;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
#[inline]
pub fn sheet_range(total_rows: i64, total_cols: i64, row: i64, col: i64, rows: i64, cols: i64, given: i64) -> ::std::vec::Vec<i64> {
    let mut pruv_budget: i64 = 1_073_741_824;
    if !(((0i128 <= (total_rows as i128)) && ((total_rows as i128) <= 1000000000000i128))) { panic!("{}", "pruv: requires violated: crate::sheet_range: ((0 <= total_rows) && (total_rows <= 1000000000000))"); }
    if !(((0i128 <= (total_cols as i128)) && ((total_cols as i128) <= 1000000000000i128))) { panic!("{}", "pruv: requires violated: crate::sheet_range: ((0 <= total_cols) && (total_cols <= 1000000000000))"); }
    if !((((-9007199254740991i128) <= (row as i128)) && ((row as i128) <= 9007199254740991i128))) { panic!("{}", "pruv: requires violated: crate::sheet_range: ((-9007199254740991 <= row) && (row <= 9007199254740991))"); }
    if !((((-9007199254740991i128) <= (col as i128)) && ((col as i128) <= 9007199254740991i128))) { panic!("{}", "pruv: requires violated: crate::sheet_range: ((-9007199254740991 <= col) && (col <= 9007199254740991))"); }
    if !((((-9007199254740991i128) <= (rows as i128)) && ((rows as i128) <= 9007199254740991i128))) { panic!("{}", "pruv: requires violated: crate::sheet_range: ((-9007199254740991 <= rows) && (rows <= 9007199254740991))"); }
    if !((((-9007199254740991i128) <= (cols as i128)) && ((cols as i128) <= 9007199254740991i128))) { panic!("{}", "pruv: requires violated: crate::sheet_range: ((-9007199254740991 <= cols) && (cols <= 9007199254740991))"); }
    if !(((0i128 <= (given as i128)) && ((given as i128) <= 15i128))) { panic!("{}", "pruv: requires violated: crate::sheet_range: ((0 <= given) && (given <= 15))"); }
    sheet_range__pruv_body(total_rows, total_cols, row, col, rows, cols, given)
}

