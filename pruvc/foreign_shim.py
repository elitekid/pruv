"""G6 A3 (docs/G6_SPEC.md section 13): the Rust shim of the LLVM bridge.

build_shim() returns the text of `mod pruv_g6_shim { .. }`, which gen_bindings() appends to the generated Rust host
bindings of a G6 program.  The module contains
  * the contract/G6 preludes the helpers need (the same texts the Rust source backend emits),
  * the bridge runtime: live-box counter (PRUV_G6_COUNT atexit report), catch_unwind guard (fflush(NULL) +
    exit(101)), checked conversions (bool, handle, borrowed slice, str),
  * exactly the A2 boundary helpers the program uses (texts produced by a codegen.Gen / ForeignGen created for the
    same program and check mode, so the checks and messages are identical to the Rust source backend),
  * one `#[no_mangle] pub extern "C"` adapter per helper, named `pruv_g6_v1_<helper name>`, one
    `pruv_g6_v1_drop__<C>` and `pruv_g6_v1_len__<C>` per collection type <C>, `pruv_g6_v1_string_bytes` (only when
    string_to_str is used; it replaces the A2 clone helper by a borrowed view) and
    `#[no_mangle] pub static pruv_g6_bridge_v1: u8 = 1;`.
<C> is the G3 structural encoding of the collection type: vec__i, vec__b, hashmap__i__b, string.

Bridge representations (section 13.2): i64 as i64; bool as i64 0/1 (anything else -> `pruv: invalid representation:
bool`); a collection handle as an opaque pointer to a Box of the concrete Rust collection; a borrowed array/str as
(ptr, i64 len); Option<i64|bool> results through (ptr tag_out, ptr val_out).  Consuming updates return the same
pointer (File updates consume the old box and return a fresh box).  The helper-name part of a symbol is the full A2 helper name (`pruv_g6_vec_push__i` ->
`pruv_g6_v1_pruv_g6_vec_push__i`, `trusted rust fn min2` -> `pruv_g6_v1_min2`).
"""
from vast import *
from typeinfo import encode, is_collection, uses_array_type, uses_str
from codegen import (Gen, rty, CONTRACT_PRELUDE_G6, CONTRACT_PRELUDE_U8, CONTRACT_PRELUDE_BOOL,
                     CONTRACT_PRELUDE_STR, G6_PRELUDE, FILE_PRELUDE)
from foreign import CATALOG, CATALOG_CONTRACT_ONLY, FILE_OBSERVERS

PREFIX = "pruv_g6_v1_"
BRIDGE_SYM = "pruv_g6_bridge_v1"
STRING_BYTES_SYM = PREFIX + "string_bytes"
STRING_TO_STR = "pruv_g6_string_to_str"       # A2 helper name replaced by the borrowed view string_bytes


def helper_name(op, src):
    """the A2 helper name of a catalog instance (ForeignGen.catalog_helper)"""
    return "pruv_g6_" + op + "".join("__" + encode(t) for t in src)


def adapter_sym(helper):
    return PREFIX + helper


def cname(t):
    """<C>: G3 encoding of a collection type"""
    if t.name == "vec":
        return "vec__" + encode(t.args[0])
    if t.name == "hashmap":
        return "hashmap__%s__%s" % (encode(t.args[0]), encode(t.args[1]))
    return "File" if t.name == "file" else "string"


def drop_sym(t):
    return "%sdrop__%s" % (PREFIX, cname(t))


def len_sym(t):
    return "%slen__%s" % (PREFIX, cname(t))


def inst_types(e):
    """(low, src) type arguments of a catalog call as codegen.catalog_call computes them"""
    low = tuple(e.inst["args"]) if e.inst else ()
    src = tuple(e.inst.get("src_args", low)) if e.inst else ()
    if not src and low:
        src = low
    return low, src


# ---------------------------------------------------------------------------
# program scan
# ---------------------------------------------------------------------------
def _walk(node, fn):
    if isinstance(node, (list, tuple)):
        for x in node:
            _walk(x, fn)
        return
    if not hasattr(node, "__dataclass_fields__") or isinstance(node, Type):
        return
    fn(node)
    for fname in node.__dataclass_fields__:
        _walk(getattr(node, fname), fn)


def collect(prog):
    """(cats, colls, trusted): cats: helper name -> (op, low types); colls: <C> -> collection Type (sorted by the
    caller); trusted: name -> Function of the trusted declarations called from a body"""
    cats, colls, trusted = {}, {}, {}
    fmap = {}
    for f in prog.functions:
        fmap.setdefault(f.name, f)

    def add(t):
        if t is not None and is_collection(t):
            colls.setdefault(cname(t), t)

    def visit(n):
        if isinstance(n, Let):
            add(n.type)
        ty = getattr(n, "ty", None)
        if ty is not None:
            add(ty)
        if isinstance(n, Call):
            if n.name in CATALOG and n.name not in CATALOG_CONTRACT_ONLY:
                low, src = inst_types(n)
                cats.setdefault(helper_name(n.name, src), (n.name, low))
                if n.name == "file_byte":
                    cats.setdefault(helper_name("file_size", ()), ("file_size", ()))
            else:
                f = fmap.get(n.name)
                if f is not None and f.foreign is not None:
                    trusted.setdefault(n.name, f)

    for f in prog.functions:
        if f.foreign is not None:
            continue
        for p in f.params:
            add(p.type)
        add(f.ret)
        _walk(f.body, visit)
        def contract_visit(n):
            if isinstance(n, Call) and n.name in FILE_OBSERVERS:
                visit(n)
        _walk(f.requires, contract_visit)
        _walk(f.ensures, contract_visit)
    return cats, colls, trusted


# ---------------------------------------------------------------------------
# bridge runtime text
# ---------------------------------------------------------------------------
BRIDGE_RUNTIME = """\
mod pruv_g6_c {
    extern "C" {
        pub fn fflush(stream: *mut ::std::ffi::c_void) -> i32;
        pub fn atexit(cb: extern "C" fn()) -> i32;
    }
}
type PruvH = *mut ::std::ffi::c_void;
#[no_mangle]
pub static pruv_g6_bridge_v1: u8 = 1;
static PRUV_G6_LIVE: ::std::sync::atomic::AtomicI64 = ::std::sync::atomic::AtomicI64::new(0);
static PRUV_G6_ONCE: ::std::sync::Once = ::std::sync::Once::new();
extern "C" fn pruv_g6_report() {
    let n: i64 = PRUV_G6_LIVE.load(::std::sync::atomic::Ordering::SeqCst);
    let _ = ::std::io::Write::write_fmt(&mut ::std::io::stderr(), format_args!("pruv-g6-live: {}\\n", n));
}
fn pruv_g6_register() {
    PRUV_G6_ONCE.call_once(|| {
        if ::std::env::var("PRUV_G6_COUNT").map(|v| v == "1").unwrap_or(false) {
            unsafe { pruv_g6_c::atexit(pruv_g6_report); }
        }
    });
}
fn pruv_g6_guard<R, F: FnOnce() -> R>(f: F) -> R {
    match ::std::panic::catch_unwind(::std::panic::AssertUnwindSafe(f)) {
        Ok(r) => r,
        Err(_) => {
            unsafe { pruv_g6_c::fflush(::std::ptr::null_mut()); }
            ::std::process::exit(101)
        }
    }
}
fn pruv_g6_b(x: i64) -> bool { match x { 0 => false, 1 => true, _ => pruv_g6_repr("bool") } }
fn pruv_g6_new<T>(v: T) -> PruvH {
    pruv_g6_register();
    PRUV_G6_LIVE.fetch_add(1, ::std::sync::atomic::Ordering::SeqCst);
    ::std::boxed::Box::into_raw(::std::boxed::Box::new(v)) as PruvH
}
fn pruv_g6_ref<'a, T>(h: PruvH) -> &'a T {
    if h.is_null() { pruv_g6_repr("null handle") }
    unsafe { &*(h as *const T) }
}
fn pruv_g6_upd<T: Default, F: FnOnce(T) -> T>(h: PruvH, f: F) -> PruvH {
    if h.is_null() { pruv_g6_repr("null handle") }
    unsafe {
        let p: *mut T = h as *mut T;
        let old: T = ::std::mem::take(&mut *p);
        let new: T = f(old);
        *p = new;
    }
    h
}
fn pruv_g6_free<T>(h: PruvH) {
    if h.is_null() { return; }
    unsafe { drop(::std::boxed::Box::from_raw(h as *mut T)); }
    PRUV_G6_LIVE.fetch_sub(1, ::std::sync::atomic::Ordering::SeqCst);
}
fn pruv_g6_nlen(n: i64) -> usize { if n < 0 || n > (1i64 << 40) { pruv_g6_repr("length") } n as usize }
fn pruv_g6_slice<'a, T>(p: *const T, n: i64) -> &'a [T] {
    let n: usize = pruv_g6_nlen(n);
    if n == 0 { return &[]; }
    if p.is_null() { pruv_g6_repr("NULL data") }
    if (p as usize) % ::std::mem::align_of::<T>() != 0 { pruv_g6_repr("alignment") }
    unsafe { ::std::slice::from_raw_parts(p, n) }
}
fn pruv_g6_bools<'a>(p: *const u8, n: i64) -> &'a [bool] {
    let s: &[u8] = pruv_g6_slice::<u8>(p, n);
    for b in s.iter() { if *b > 1 { pruv_g6_repr("bool") } }
    unsafe { ::std::slice::from_raw_parts(s.as_ptr() as *const bool, s.len()) }
}
fn pruv_g6_str<'a>(p: *const u8, n: i64) -> &'a str {
    match ::std::str::from_utf8(pruv_g6_slice::<u8>(p, n)) { Ok(s) => s, Err(_) => pruv_g6_repr("utf-8") }
}
fn pruv_g6_out(p: *mut i64) -> *mut i64 { if p.is_null() { pruv_g6_repr("null output") } p }
"""

MOD_ALLOW = ("#[allow(dead_code, unused_imports, unused_variables, unused_mut, unused_parens, unused_unsafe, "
             "non_snake_case, non_camel_case_types, non_upper_case_globals, improper_ctypes_definitions, "
             "unreachable_code, unconditional_panic, arithmetic_overflow, unused_assignments, unused_comparisons)]")


# ---------------------------------------------------------------------------
# adapters
# ---------------------------------------------------------------------------
def _cin(t, x):
    return x if t == I64 else "pruv_g6_b(%s)" % x


def _cout(t, x):
    return x if t == I64 else "(%s) as i64" % x


def _fn(sym, params, ret, body):
    return '#[no_mangle]\npub extern "C" fn %s(%s)%s {\n    %s\n}\n' % (
        sym, params, "" if ret is None else " -> " + ret, body)


def _cat_adapter(helper, op, low):
    S = adapter_sym(helper)
    if op.startswith("file_"):
        return _file_adapter(S, helper, op)
    if op in ("vec_new", "vec_push", "vec_get"):
        T = low[0]
        C = rty(Type("vec", (T,)))
    elif op in ("map_new", "map_get", "map_insert"):
        K, V = low[0], low[1]
        C = rty(Type("hashmap", (K, V)))
    else:
        C = rty(Type("string"))
    if op in ("vec_new", "map_new", "string_new"):
        return _fn(S, "", "PruvH", "pruv_g6_guard(|| pruv_g6_new::<%s>(%s()))" % (C, helper))
    if op == "vec_push":
        return _fn(S, "v: PruvH, x: i64", "PruvH",
                   "pruv_g6_guard(|| { let pruv_x: %s = %s; pruv_g6_upd::<%s, _>(v, |pruv_o| %s(pruv_o, pruv_x)) })" % (
                       rty(T), _cin(T, "x"), C, helper))
    if op == "vec_get":
        return _fn(S, "v: PruvH, i: i64", "i64",
                   "pruv_g6_guard(|| { let pruv_r: %s = %s(pruv_g6_ref::<%s>(v), i); %s })" % (
                       rty(T), helper, C, _cout(T, "pruv_r")))
    if op == "map_get":
        return _fn(S, "m: PruvH, k: i64, tag: *mut i64, val: *mut i64", None,
                   "pruv_g6_guard(|| { let pruv_k: %s = %s; let pruv_r: ::std::option::Option<%s> = %s(pruv_g6_ref::<%s>(m), pruv_k); "
                   "let pruv_t: *mut i64 = pruv_g6_out(tag); let pruv_v: *mut i64 = pruv_g6_out(val); "
                   "unsafe { match pruv_r { ::std::option::Option::Some(pruv_x) => { *pruv_t = 1; *pruv_v = %s; } "
                   "::std::option::Option::None => { *pruv_t = 0; *pruv_v = 0; } } } })" % (
                       rty(K), _cin(K, "k"), rty(V), helper, C, _cout(V, "pruv_x")))
    if op == "map_insert":
        return _fn(S, "m: PruvH, k: i64, v: i64", "PruvH",
                   "pruv_g6_guard(|| { let pruv_k: %s = %s; let pruv_v: %s = %s; "
                   "pruv_g6_upd::<%s, _>(m, |pruv_o| %s(pruv_o, pruv_k, pruv_v)) })" % (
                       rty(K), _cin(K, "k"), rty(V), _cin(V, "v"), C, helper))
    if op == "string_push_str":
        return _fn(S, "s: PruvH, p: *const u8, n: i64", "PruvH",
                   "pruv_g6_guard(|| { let pruv_t: &str = pruv_g6_str(p, n); "
                   "pruv_g6_upd::<%s, _>(s, |pruv_o| %s(pruv_o, pruv_t)) })" % (C, helper))
    if op == "string_byte":
        return _fn(S, "s: PruvH, i: i64", "i64", "pruv_g6_guard(|| %s(pruv_g6_ref::<%s>(s), i))" % (helper, C))
    raise Exception("foreign_shim: no adapter for catalog operation %s" % op)


def _file_adapter(sym, helper, op):
    if op in ("file_open_read", "file_create"):
        return _fn(sym, "p: *const u8, n: i64", "PruvH",
                   "pruv_g6_guard(|| pruv_g6_new(%s(pruv_g6_str(p, n))))" % helper)
    params, arg = "h: PruvH", ""
    if op == "file_byte":
        params += ", i: i64"
        arg = ", i"
    if op in ("file_ok", "file_readable", "file_writable", "file_size", "file_byte"):
        return _fn(sym, params, "i64",
                   "pruv_g6_guard(|| %s(pruv_g6_ref::<pruv_File>(h)%s) as i64)" % (helper, arg))
    body = ""
    if op in ("file_write_str", "file_write_bytes"):
        params += ", p: *const u8, n: i64"
        arg = ", pruv_data"
        conv = "pruv_g6_str(p, n)" if op == "file_write_str" else "pruv_g6_slice::<u8>(p, n)"
        body += "let pruv_data = %s; " % conv
    # Consume the box before the A2 helper; File has no Default placeholder.
    body += ('if h.is_null() { pruv_g6_repr("null handle") } '
             "let f: pruv_File = unsafe { *::std::boxed::Box::from_raw(h as *mut pruv_File) }; "
             "PRUV_G6_LIVE.fetch_sub(1, ::std::sync::atomic::Ordering::SeqCst); ")
    call = "%s(f%s)" % (helper, arg)
    body += call + " as i64" if op == "file_close" else "pruv_g6_new(%s)" % call
    return _fn(sym, params, "i64" if op == "file_close" else "PruvH", "pruv_g6_guard(|| { %s })" % body)


def _trusted_adapter(f):
    params, args = [], []
    for i, p in enumerate(f.params):
        t = p.type
        if t == I64:
            params.append("a%d: i64" % i)
            args.append("a%d" % i)
        elif t == BOOL:
            params.append("a%d: i64" % i)
            args.append("pruv_g6_b(a%d)" % i)
        elif t == STR:
            params += ["a%d: *const u8" % i, "n%d: i64" % i]
            args.append("pruv_g6_str(a%d, n%d)" % (i, i))
        elif t == ARRAY:
            params += ["a%d: *const i64" % i, "n%d: i64" % i]
            args.append("pruv_g6_slice::<i64>(a%d, n%d)" % (i, i))
        elif t == ARRAY_U8:
            params += ["a%d: *const u8" % i, "n%d: i64" % i]
            args.append("pruv_g6_slice::<u8>(a%d, n%d)" % (i, i))
        elif t == ARRAY_BOOL:
            params += ["a%d: *const u8" % i, "n%d: i64" % i]
            args.append("pruv_g6_bools(a%d, n%d)" % (i, i))
        else:
            raise Exception("foreign_shim: unsupported trusted parameter type %r" % (t,))
    call = "%s(%s)" % (f.name, ", ".join(args))
    S = adapter_sym(f.name)
    if is_collection(f.ret):   # G6b: the helper checked the result; box it once, even when empty
        return _fn(S, ", ".join(params), "PruvH", "pruv_g6_guard(|| pruv_g6_new(%s))" % call)
    if f.ret == UNIT:
        return _fn(S, ", ".join(params), None, "pruv_g6_guard(|| { %s; })" % call)
    if f.ret == BOOL:
        return _fn(S, ", ".join(params), "i64", "pruv_g6_guard(|| { let pruv_r: bool = %s; pruv_r as i64 })" % call)
    return _fn(S, ", ".join(params), "i64", "pruv_g6_guard(|| %s)" % call)


def _coll_adapters(t):
    C = rty(t)
    if t.name == "file":
        return _fn(drop_sym(t), "h: PruvH", None, "pruv_g6_guard(|| pruv_g6_free::<pruv_File>(h))")
    return (_fn(len_sym(t), "h: PruvH", "i64", "pruv_g6_guard(|| pruv_g6_ref::<%s>(h).len() as i64)" % C) +
            _fn(drop_sym(t), "h: PruvH", None, "pruv_g6_guard(|| pruv_g6_free::<%s>(h))" % C))


def _string_bytes_adapter():
    return _fn(STRING_BYTES_SYM, "h: PruvH, data: *mut *const u8, len: *mut i64", None,
               "pruv_g6_guard(|| { let pruv_s: &::std::string::String = pruv_g6_ref::<::std::string::String>(h); "
               "if data.is_null() || len.is_null() { pruv_g6_repr(\"null output\") } "
               "unsafe { *data = pruv_s.as_ptr(); *len = pruv_s.len() as i64; } })")


# ---------------------------------------------------------------------------
# the module
# ---------------------------------------------------------------------------
def build_shim(prog, verified=True, trust_callers=False, budget=1 << 30, foreign_checks="requires"):
    """text of `mod pruv_g6_shim` for the (concrete) program prog; deterministic"""
    cats, colls, trusted = collect(prog)
    # helper discovery: exactly the A2 helpers (same texts, same mode and budget).  The entry checks of the Rust
    # source backend are not emitted here (trust=True): the LLVM entries evaluate requires themselves.
    g = Gen(prog, verified, True, budget, foreign_checks)
    for f in prog.functions:
        g.fn(f)
    for op, low in cats.values():
        if op in FILE_OBSERVERS:
            g.fg.catalog_helper(op, low, low)
    items = g.fg.items
    out = [MOD_ALLOW, "mod pruv_g6_shim {"]
    if g.g10:
        out.append(FILE_PRELUDE)
    out.append(CONTRACT_PRELUDE_G6)
    if uses_array_type(prog, "array_u8") or g.g10:
        out.append(CONTRACT_PRELUDE_U8)
    if uses_array_type(prog, "array_bool"):
        out.append(CONTRACT_PRELUDE_BOOL)
    if uses_str(prog) or uses_array_type(prog, "string"):   # G6b: a String result indexed in an ensures
        out.append(CONTRACT_PRELUDE_STR)
    out.append(G6_PRELUDE)
    out.append(BRIDGE_RUNTIME)
    adapters = []
    for name, text in items.items():
        if name in cats and cats[name][0] == "string_to_str":
            continue        # replaced by the borrowed view pruv_g6_v1_string_bytes
        if name not in cats and name not in trusted:
            continue        # contract scans (map_updated) are not used by the LLVM entries
        out.append(text)
        if name in cats:
            adapters.append(_cat_adapter(name, cats[name][0], cats[name][1]))
        else:
            adapters.append(_trusted_adapter(trusted[name]))
    for helper in cats:
        if cats[helper][0] == "string_to_str":
            adapters.append(_string_bytes_adapter())
            break
    for key in sorted(colls):
        adapters.append(_coll_adapters(colls[key]))
    out.extend(adapters)
    out.append("}")
    return "\n".join(out) + "\n"
