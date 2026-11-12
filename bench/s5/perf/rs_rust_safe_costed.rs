#[allow(dead_code)]
#[cold]
#[inline(never)]
fn pruv_oob(i: i64, len: usize) -> ! { panic!("pruv: index out of bounds: {} (len {})", i, len) }
#[allow(dead_code)]
#[cold]
#[inline(never)]
fn pruv_ovf(what: &str) -> ! { panic!("pruv: arithmetic error: {}", what) }
#[allow(dead_code)]
#[inline]
fn pruv_idx(i: i64, len: usize) -> usize { if i >= 0 && (i as u64) < (len as u64) { i as usize } else { pruv_oob(i, len) } }
#[allow(dead_code)]
#[inline]
fn pruv_get(a: &[i64], i: i64) -> i64 { a[pruv_idx(i, a.len())] }
#[allow(dead_code)]
#[inline]
fn pruv_set(a: &mut [i64], i: i64, v: i64) { let k = pruv_idx(i, a.len()); a[k] = v; }
#[allow(dead_code)]
#[inline]
fn pruv_add(a: i64, b: i64) -> i64 { match a.checked_add(b) { Some(v) => v, None => pruv_ovf("overflow in +") } }
#[allow(dead_code)]
#[inline]
fn pruv_sub(a: i64, b: i64) -> i64 { match a.checked_sub(b) { Some(v) => v, None => pruv_ovf("overflow in -") } }
#[allow(dead_code)]
#[inline]
fn pruv_mul(a: i64, b: i64) -> i64 { match a.checked_mul(b) { Some(v) => v, None => pruv_ovf("overflow in *") } }
#[allow(dead_code)]
#[inline]
fn pruv_div(a: i64, b: i64) -> i64 { if b > 0 && a >= 0 { a / b } else { pruv_ovf("division outside domain: need divisor > 0 and dividend >= 0") } }
#[allow(dead_code)]
#[inline]
fn pruv_rem(a: i64, b: i64) -> i64 { if b > 0 && a >= 0 { a % b } else { pruv_ovf("division outside domain: need divisor > 0 and dividend >= 0") } }
#[allow(dead_code)]
#[inline]
fn pruv_neg(a: i64) -> i64 { match a.checked_neg() { Some(v) => v, None => pruv_ovf("overflow in unary -") } }
#[allow(dead_code)]
#[inline]
fn pruv_alloc(n: i64, v: i64) -> ::std::vec::Vec<i64> { if n < 0 || n > (1i64 << 40) { pruv_ovf("alloc length outside 0..2^40") } vec![v; n as usize] }

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
fn step__pruv_body(x: i64) -> i64 {
    let pruv_cost: i128 = step__pruv_cost(x);
    let mut pruv_spent: u128 = 0;
    let pruv_return = pruv_rem(pruv_add(pruv_mul(x, 251i64), 17i64), 65521i64);
    if pruv_cost < 0 || pruv_spent > pruv_cost as u128 { panic!("pruv: cost exceeded"); }
    return pruv_return;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn step__pruv_cost(x: i64) -> i128 {
    let mut pruv_budget: i64 = 1_073_741_824;
    if !(((0i128 <= (x as i128)) && ((x as i128) < 65521i128))) { panic!("{}", "pruv: requires violated: step: ((0 <= x) && (x < 65521))"); }
    0i128
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
#[inline]
pub fn step(x: i64) -> i64 {
    let mut pruv_budget: i64 = 1_073_741_824;
    if !(((0i128 <= (x as i128)) && ((x as i128) < 65521i128))) { panic!("{}", "pruv: requires violated: step: ((0 <= x) && (x < 65521))"); }
    step__pruv_body(x)
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn mix__pruv_body(n: i64, seed: i64) -> i64 {
    let pruv_cost: i128 = mix__pruv_cost(n, seed);
    let mut pruv_spent: u128 = 0;
    let mut x: i64 = seed;
    let mut i: i64 = 0i64;
    while (i < n) {
        pruv_spent = pruv_spent.checked_add(1).unwrap_or_else(|| panic!("pruv: cost exceeded"));
        let mut j: i64 = 0i64;
        while (j < 32i64) {
            pruv_spent = pruv_spent.checked_add(1).unwrap_or_else(|| panic!("pruv: cost exceeded"));
            x = { let pruv_cost_arg_0 = x; let pruv_units = step__pruv_cost(pruv_cost_arg_0); if pruv_units < 0 { panic!("pruv: cost exceeded"); } pruv_spent = pruv_spent.checked_add((pruv_units as u128).checked_add(1).unwrap_or_else(|| panic!("pruv: cost exceeded"))).unwrap_or_else(|| panic!("pruv: cost exceeded")); step(pruv_cost_arg_0) };
            j = pruv_add(j, 1i64);
        }
        i = pruv_add(i, 1i64);
    }
    let pruv_return = x;
    if pruv_cost < 0 || pruv_spent > pruv_cost as u128 { panic!("pruv: cost exceeded"); }
    return pruv_return;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn mix__pruv_cost(n: i64, seed: i64) -> i128 {
    let mut pruv_budget: i64 = 1_073_741_824;
    if !(((0i128 <= (n as i128)) && ((n as i128) <= 1000000i128))) { panic!("{}", "pruv: requires violated: mix: ((0 <= n) && (n <= 1000000))"); }
    if !(((0i128 <= (seed as i128)) && ((seed as i128) < 65521i128))) { panic!("{}", "pruv: requires violated: mix: ((0 <= seed) && (seed < 65521))"); }
    pruv_cmul(65i128, (n as i128))
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
#[inline]
pub fn mix(n: i64, seed: i64) -> i64 {
    let mut pruv_budget: i64 = 1_073_741_824;
    if !(((0i128 <= (n as i128)) && ((n as i128) <= 1000000i128))) { panic!("{}", "pruv: requires violated: mix: ((0 <= n) && (n <= 1000000))"); }
    if !(((0i128 <= (seed as i128)) && ((seed as i128) < 65521i128))) { panic!("{}", "pruv: requires violated: mix: ((0 <= seed) && (seed < 65521))"); }
    mix__pruv_body(n, seed)
}

