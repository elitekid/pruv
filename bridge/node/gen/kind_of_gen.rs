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
fn pruv_m_f_1_8_ext_from(name: &str) -> i64 {
    let mut base: i64 = 0i64;
    let mut dot: i64 = (-1i64);
    let mut i: i64 = 0i64;
    while (i < (name.len() as i64)) {
        let c: i64 = ((unsafe { *name.as_bytes().get_unchecked((i) as usize) }) as i64);
        if ((c == 47i64) || (c == 92i64)) {
            base = (i + 1i64);
            dot = (-1i64);
        } else {
            if (c == 46i64) {
                dot = i;
            }
        }
        i = (i + 1i64);
    }
    if (dot > base) {
        return (dot + 1i64);
    }
    return (-1i64);
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_8_units_to__pruv_body(name: &str, end: i64) -> i64 {
    let mut n: i64 = 0i64;
    let mut i: i64 = 0i64;
    while (i < end) {
        let c: i64 = ((unsafe { *name.as_bytes().get_unchecked((i) as usize) }) as i64);
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
fn extension_at__pruv_body(name: &str) -> i64 {
    let at: i64 = pruv_m_f_1_8_ext_from(name);
    if (at < 0i64) {
        return (-1i64);
    }
    return pruv_m_f_1_8_units_to__pruv_body(name, at);
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
#[inline]
pub fn extension_at(name: &str) -> i64 {
    let mut pruv_budget: i64 = 1_073_741_824;
    if !(((name.len() as i128) <= 1000000000000i128)) { panic!("{}", "pruv: requires violated: crate::extension_at: (len(name) <= 1000000000000)"); }
    extension_at__pruv_body(name)
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_4_word(w: &str) -> i64 {
    let mut k: i64 = 0i64;
    let mut cap: i64 = 1i64;
    let mut i: i64 = 0i64;
    while (i < (w.len() as i64)) {
        if (cap > 594467302491009i64) {
            return (-2i64);
        }
        let c: i64 = ((unsafe { *w.as_bytes().get_unchecked((i) as usize) }) as i64);
        k = (((k * 129i64) + (c % 128i64)) + 1i64);
        cap = (cap * 129i64);
        i = (i + 1i64);
    }
    return k;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_7_ext_key__pruv_body(name: &str, at: i64) -> i64 {
    let mut k: i64 = 0i64;
    let mut cap: i64 = 1i64;
    let mut i: i64 = at;
    while (i < (name.len() as i64)) {
        if (cap > 594467302491009i64) {
            return (-1i64);
        }
        let c: i64 = ((unsafe { *name.as_bytes().get_unchecked((i) as usize) }) as i64);
        let mut lc: i64 = c;
        if (c < 128i64) {
            if ((65i64 <= c) && (c <= 90i64)) {
                lc = (c + 32i64);
            }
            i = (i + 1i64);
        } else {
            if ((((c == 226i64) && ((i + 2i64) < (name.len() as i64))) && (((unsafe { *name.as_bytes().get_unchecked(((i + 1i64)) as usize) }) as i64) == 132i64)) && (((unsafe { *name.as_bytes().get_unchecked(((i + 2i64)) as usize) }) as i64) == 170i64)) {
                lc = 107i64;
                i = (i + 3i64);
            } else {
                return (-1i64);
            }
        }
        k = (((k * 129i64) + lc) + 1i64);
        cap = (cap * 129i64);
    }
    return k;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_8_is_image(k: i64) -> bool {
    return ((((((((k == pruv_m_f_1_4_word(&::std::string::String::from("png"))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("jpg")))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("jpeg")))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("webp")))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("gif")))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("bmp")))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("tif")))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("tiff"))));
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_7_is_text(k: i64) -> bool {
    return ((((((((((((((((((((((((((((((((((((((((((((((k == pruv_m_f_1_4_word(&::std::string::String::from("txt"))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("md")))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("markdown")))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("log")))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("json")))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("jsonl")))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("yaml")))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("yml")))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("xml")))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("html")))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("htm")))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("css")))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("ini")))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("toml")))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("cfg")))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("conf")))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("env")))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("rst")))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("tex")))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("srt")))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("vtt")))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("js")))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("mjs")))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("cjs")))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("ts")))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("tsx")))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("jsx")))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("py")))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("rb")))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("go")))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("rs")))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("java")))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("kt")))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("swift")))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("c")))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("h")))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("cc")))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("cpp")))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("hpp")))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("cs")))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("php")))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("sh")))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("bat")))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("ps1")))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("sql")))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("svg"))));
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn pruv_m_f_1_14_is_unsupported(k: i64) -> bool {
    return (((((((((((((((k == pruv_m_f_1_4_word(&::std::string::String::from("pptx"))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("ppt")))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("hwp")))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("hwpx")))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("doc")))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("xls")))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("odt")))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("ods")))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("odp")))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("rtf")))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("pages")))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("numbers")))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("key")))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("zip")))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("epub"))));
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
fn kind_of__pruv_body(name: &str) -> i64 {
    let at: i64 = pruv_m_f_1_8_ext_from(name);
    if (at < 0i64) {
        return 0i64;
    }
    let k: i64 = pruv_m_f_1_7_ext_key__pruv_body(name, at);
    if (k < 0i64) {
        return 0i64;
    }
    if (k == pruv_m_f_1_4_word(&::std::string::String::from("pdf"))) {
        return 1i64;
    }
    if (k == pruv_m_f_1_4_word(&::std::string::String::from("docx"))) {
        return 2i64;
    }
    if (k == pruv_m_f_1_4_word(&::std::string::String::from("xlsx"))) {
        return 3i64;
    }
    if ((k == pruv_m_f_1_4_word(&::std::string::String::from("csv"))) || (k == pruv_m_f_1_4_word(&::std::string::String::from("tsv")))) {
        return 4i64;
    }
    if pruv_m_f_1_8_is_image(k) {
        return 5i64;
    }
    if pruv_m_f_1_7_is_text(k) {
        return 6i64;
    }
    if pruv_m_f_1_14_is_unsupported(k) {
        return 7i64;
    }
    return 0i64;
}

#[allow(unused_mut, unused_variables, unused_parens, non_snake_case, non_camel_case_types, dead_code, unreachable_code, unreachable_patterns, unconditional_panic, arithmetic_overflow)]
#[inline]
pub fn kind_of(name: &str) -> i64 {
    let mut pruv_budget: i64 = 1_073_741_824;
    if !(((name.len() as i128) <= 1000000000000i128)) { panic!("{}", "pruv: requires violated: crate::kind_of: (len(name) <= 1000000000000)"); }
    kind_of__pruv_body(name)
}

