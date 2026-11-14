//! A small wrapper over z3-sys. All of this project's unsafe code lives here.
//!
//! Call order and arguments follow exactly the C API calls z3py (`z3.py`) makes, so that the SMT text
//! matches Python character for character. Points matched to z3py (low-confidence ones are flagged separately in the README/final report):
//! - `Z3_set_ast_print_mode(ctx, SMTLIB2_COMPLIANT)` (z3py `Context.__init__`)
//! - Quantifiers: always `Z3_mk_quantifier_const_ex(weight=1, qid="", skid="")` (z3py `_mk_quantifier`)
//! - Patterns: a single-term `Z3_mk_pattern` (z3py `_to_pattern` → `MultiPattern`)
//! - Datatype: `Z3_mk_constructor(name, "is-"+name, ...)` + `Z3_mk_datatypes` (z3py `CreateDatatypes`)
//! - Arithmetic: `+ - *` are two-argument `Z3_mk_add/sub/mul`, `!=` is `Z3_mk_distinct` (Python `__ne__`)
//! - Bit-vectors (P2): `Int2BV` → `Z3_mk_int2bv(ctx, bits, a)`, `BV2Int` → `Z3_mk_bv2int(ctx, a, is_signed)`, `& | ^` → `Z3_mk_bvand/bvor/bvxor`, `<<` / `LShR` → `Z3_mk_bvshl/bvlshr`
//! - Solver: `Z3_mk_solver`; the timeout is `Z3_params_set_uint("timeout", ms)` followed by `Z3_solver_set_params`
//!
//! # Common safety rationale (cited by number from each unsafe block's `SAFETY:`)
//! - **S1 context ownership**: `Z3` (= `Rc<Ctx>`) is held as a clone by every handle (`Ast`/`Sort`/`FuncDecl`/`Solver`),
//!   so `Z3_del_context` is not called while raw pointers are in use. Handles are `!Send` because of `Rc`, so they are single-thread only.
//! - **S2 non-rc context**: created with `Z3_mk_context` (not rc). In this context Ast/Sort/FuncDecl/Symbol/Pattern stay
//!   valid until the context is deleted, unless scopes are popped with `Z3_solver_pop`. We do not use push/pop.
//!   Hence we do not inc_ref/dec_ref Asts (only solver/params/constructor need it, S5).
//! - **S3 array arguments**: lengths and pointers come from slices/Vecs borrowed only for the duration of the call, and z3 copies within the call.
//! - **S4 strings**: the `CString` we pass lives until the call ends. A returned `*const c_char` is valid only until the next
//!   API call on the same context, so it is copied into a `String` immediately.
//! - **S5 ref-counted objects**: solver/params get `inc_ref` right after creation and `dec_ref` in `Drop` (or right after use).
//!   constructor/constructor_list are released with `del_*` right after `Z3_mk_datatypes`.
//! - **S6 returned pointers**: whether z3-sys returns `Option<NonNull>` or a raw pointer, `nn()` turns null into a panic
//!   and returns a non-null type of the same shape (confining version differences to one place).
//!
//! Wherever the real build disagrees with the z3-sys 0.22-series signatures, only this file needs fixing (by the main branch).

use std::collections::HashSet;
use std::ffi::{CStr, CString};
use std::os::raw::{c_char, c_uint};
use std::ptr::{self, NonNull};
use std::rc::Rc;

use z3_sys as z;

// ---------------------------------------------------------------------------------------------
// Absorbing z3-sys version differences: normalizing returned pointers (S6)
// ---------------------------------------------------------------------------------------------

/// `Option<NonNull<T>>`/`NonNull<T>`/`*mut T`/`Option<*mut T>` are normalized to the same non-null shape.
pub trait MaybePtr {
    type Inner;
    #[track_caller]
    fn nn(self) -> Self::Inner;
}
impl<T> MaybePtr for *mut T {
    type Inner = *mut T;
    #[track_caller]
    fn nn(self) -> *mut T {
        assert!(!self.is_null(), "z3 returned a null pointer");
        self
    }
}
impl<T> MaybePtr for NonNull<T> {
    type Inner = NonNull<T>;
    #[track_caller]
    fn nn(self) -> NonNull<T> {
        self
    }
}
impl<T> MaybePtr for Option<NonNull<T>> {
    type Inner = NonNull<T>;
    #[track_caller]
    fn nn(self) -> NonNull<T> {
        self.expect("z3 returned a null pointer")
    }
}
impl<T> MaybePtr for Option<*mut T> {
    type Inner = *mut T;
    #[track_caller]
    fn nn(self) -> *mut T {
        let p = self.expect("z3 returned a null pointer");
        assert!(!p.is_null(), "z3 returned a null pointer");
        p
    }
}
#[inline]
#[track_caller]
fn nn<T: MaybePtr>(t: T) -> T::Inner {
    t.nn()
}

type RawCtx = z::Z3_context;
type RawAst = z::Z3_ast;
type RawSort = z::Z3_sort;
type RawFuncDecl = z::Z3_func_decl;
type RawSymbol = z::Z3_symbol;
type RawPattern = z::Z3_pattern;
type RawApp = z::Z3_app;
type RawSolver = z::Z3_solver;
type RawConstructor = z::Z3_constructor;

// Read via `as u32/i32`, so it behaves the same whether z3-sys exposes an enum or an integer alias.
const K_APP: u32 = 1; // Z3_APP_AST
const K_QUANTIFIER: u32 = 3; // Z3_QUANTIFIER_AST
const LBOOL_TRUE: i32 = 1;
const LBOOL_FALSE: i32 = -1;

unsafe fn take_string(p: *const c_char) -> String {
    // SAFETY: S4 — a z3 string pointer the caller has just received; it is copied immediately.
    unsafe { CStr::from_ptr(p).to_string_lossy().into_owned() }
}

// ---------------------------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------------------------

struct Ctx {
    raw: RawCtx,
}
impl Drop for Ctx {
    fn drop(&mut self) {
        // SAFETY: S1 — called only when the last `Z3` clone disappears, so no handle using this context remains.
        unsafe { z::Z3_del_context(self.raw) }
    }
}

/// Context handle. Cloning is an `Rc` clone. Corresponds to Python's `main_ctx()` (need not be one per process; a new one is made per sample).
#[derive(Clone)]
pub struct Z3(Rc<Ctx>);

/// Solver verdict.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Sat {
    Sat,
    Unsat,
    Unknown,
}
impl Sat {
    pub fn as_str(self) -> &'static str {
        match self {
            Sat::Sat => "sat",
            Sat::Unsat => "unsat",
            Sat::Unknown => "unknown",
        }
    }
}

/// z3 error handler: writes the error code and message to stderr and aborts (does not masquerade as exit code 1).
extern "C" fn on_z3_error(c: RawCtx, e: z::ErrorCode) {
    use std::io::Write;
    // SAFETY: S4 — copies immediately the error message z3 has just returned for this context.
    let msg = unsafe { take_string(z::Z3_get_error_msg(c, e)) };
    let _ = writeln!(std::io::stderr(), "pruv: z3 error {:?}: {}", e as i32, msg);
    std::process::abort();
}

/// Full libz3 version string (`Z3_get_full_version`).
pub fn full_version() -> String {
    // SAFETY: S4 — a static string getter with no arguments; copied immediately.
    unsafe { take_string(z::Z3_get_full_version()) }
}

#[derive(Clone)]
pub struct Sort {
    z: Z3,
    raw: RawSort,
}

#[derive(Clone)]
pub struct Ast {
    z: Z3,
    raw: RawAst,
}

#[derive(Clone)]
pub struct FuncDecl {
    z: Z3,
    raw: RawFuncDecl,
    name: String,
}

macro_rules! bin_ast {
    ($name:ident, $f:ident) => {
        pub fn $name(&self, o: &Ast) -> Ast {
            debug_assert!(Rc::ptr_eq(&self.z.0, &o.z.0), "ASTs belong to different contexts");
            // SAFETY: S1 S2 — both ASTs were made in the same context (debug_assert above) and stay valid until the context is deleted.
            unsafe { self.z.wrap(nn(z::$f(self.z.raw(), self.raw, o.raw))) }
        }
    };
}
macro_rules! nary_ast {
    ($name:ident, $f:ident) => {
        pub fn $name(&self, args: &[Ast]) -> Ast {
            let raw: Vec<RawAst> = args.iter().map(|a| a.raw).collect();
            // SAFETY: S1 S2 S3 — raw is a Vec borrowed only for this call; the element ASTs belong to this context.
            unsafe { self.wrap(nn(z::$f(self.raw(), raw.len() as c_uint, raw.as_ptr()))) }
        }
    };
}

impl Z3 {
    /// Counterpart of z3py `Context()`: non-rc context + SMT-LIB2 output mode.
    pub fn new() -> Z3 {
        // SAFETY: S2 — the config is deleted right after the context is created. The output mode passes the z3-sys enum value as is.
        unsafe {
            let cfg = nn(z::Z3_mk_config());
            let raw = nn(z::Z3_mk_context(cfg));
            z::Z3_del_config(cfg);
            // z3's default error handler writes to stdout and calls exit(1), which is indistinguishable from a 'language rejection' (exit code 1).
            // Assumption: z3-sys 0.14.1's `Z3_error_handler` = `Option<unsafe extern "C" fn(Z3_context, ErrorCode)>`
            // (the error code enum is z3-sys's `ErrorCode`; if that does not match, only fix the on_z3_error signature).
            z::Z3_set_error_handler(raw, Some(on_z3_error));
            // z3py Context(): Z3_set_ast_print_mode(ctx, Z3_PRINT_SMTLIB2_COMPLIANT) (value 2).
            z::Z3_set_ast_print_mode(raw, z::AstPrintMode::Smtlib2Compliant);
            Z3(Rc::new(Ctx { raw }))
        }
    }

    fn raw(&self) -> RawCtx {
        self.0.raw
    }
    fn wrap(&self, raw: RawAst) -> Ast {
        Ast { z: self.clone(), raw }
    }

    fn sym(&self, name: &str) -> RawSymbol {
        let cs = CString::new(name).expect("symbol name has no NUL");
        // SAFETY: S1 S4 — cs lives until the end of this statement; z3 copies the string into the symbol table.
        unsafe { nn(z::Z3_mk_string_symbol(self.raw(), cs.as_ptr())) }
    }

    // ---- sorts ----
    pub fn int_sort(&self) -> Sort {
        // SAFETY: S1 S2.
        Sort { z: self.clone(), raw: unsafe { nn(z::Z3_mk_int_sort(self.raw())) } }
    }
    pub fn bool_sort(&self) -> Sort {
        // SAFETY: S1 S2.
        Sort { z: self.clone(), raw: unsafe { nn(z::Z3_mk_bool_sort(self.raw())) } }
    }
    /// z3py `z3.DeclareSort(name)`: an uninterpreted sort (the same name gives the same sort).
    pub fn declare_sort(&self, name: &str) -> Sort {
        let s = self.sym(name);
        // SAFETY: S1 S2 — the symbol was made in this context.
        Sort { z: self.clone(), raw: unsafe { nn(z::Z3_mk_uninterpreted_sort(self.raw(), s)) } }
    }
    pub fn array_sort(&self, dom: &Sort, range: &Sort) -> Sort {
        // SAFETY: S1 S2 — dom/range are sorts of the same context.
        Sort { z: self.clone(), raw: unsafe { nn(z::Z3_mk_array_sort(self.raw(), dom.raw, range.raw)) } }
    }

    // ---- constants ----
    /// z3py `z3.Const(name, sort)`.
    pub fn constant(&self, name: &str, sort: &Sort) -> Ast {
        let s = self.sym(name);
        // SAFETY: S1 S2.
        unsafe { self.wrap(nn(z::Z3_mk_const(self.raw(), s, sort.raw))) }
    }
    pub fn int_const(&self, name: &str) -> Ast {
        self.constant(name, &self.int_sort())
    }
    pub fn bool_const(&self, name: &str) -> Ast {
        self.constant(name, &self.bool_sort())
    }
    /// z3py `z3.IntVal(v)`: decimal-string numeral.
    pub fn int(&self, v: i64) -> Ast {
        let cs = CString::new(v.to_string()).expect("digits only");
        let s = self.int_sort();
        // SAFETY: S1 S2 S4.
        unsafe { self.wrap(nn(z::Z3_mk_numeral(self.raw(), cs.as_ptr(), s.raw))) }
    }
    /// z3py `z3.IntVal(str)`: decimal-string numeral (arbitrary length). The caller supplies a normalized digit string.
    pub fn int_str(&self, v: &str) -> Ast {
        let cs = CString::new(v).unwrap_or_default();
        let s = self.int_sort();
        // SAFETY: S1 S2 S4 — a digit string (no NUL); for an empty string the z3 error handler aborts.
        unsafe { self.wrap(nn(z::Z3_mk_numeral(self.raw(), cs.as_ptr(), s.raw))) }
    }
    pub fn bool_val(&self, v: bool) -> Ast {
        // SAFETY: S1 S2.
        unsafe {
            if v {
                self.wrap(nn(z::Z3_mk_true(self.raw())))
            } else {
                self.wrap(nn(z::Z3_mk_false(self.raw())))
            }
        }
    }
    /// z3py `z3.K(dom, v)`.
    pub fn const_array(&self, dom: &Sort, v: &Ast) -> Ast {
        // SAFETY: S1 S2.
        unsafe { self.wrap(nn(z::Z3_mk_const_array(self.raw(), dom.raw, v.raw))) }
    }

    // ---- connectives / arithmetic (n-ary) ----
    nary_ast!(and, Z3_mk_and);
    nary_ast!(or, Z3_mk_or);
    nary_ast!(add_n, Z3_mk_add);
    nary_ast!(sub_n, Z3_mk_sub);
    nary_ast!(mul_n, Z3_mk_mul);
    nary_ast!(distinct, Z3_mk_distinct);

    /// z3py `z3.If(c, a, b)`.
    pub fn ite(&self, c: &Ast, a: &Ast, b: &Ast) -> Ast {
        // SAFETY: S1 S2.
        unsafe { self.wrap(nn(z::Z3_mk_ite(self.raw(), c.raw, a.raw, b.raw))) }
    }

    // ---- quantifiers ----
    /// z3py `ForAll(vs, body, patterns=...)`. With 0 variables, body as is (same as z3py).
    pub fn forall(&self, bound: &[Ast], body: &Ast, patterns: &[Ast]) -> Ast {
        self.quantifier(true, bound, body, patterns)
    }
    /// z3py `Exists(vs, body, patterns=...)`.
    pub fn exists(&self, bound: &[Ast], body: &Ast, patterns: &[Ast]) -> Ast {
        self.quantifier(false, bound, body, patterns)
    }
    fn quantifier(&self, is_forall: bool, bound: &[Ast], body: &Ast, patterns: &[Ast]) -> Ast {
        if bound.is_empty() {
            return body.clone();
        }
        let c = self.raw();
        // SAFETY: S1 S2 S3 — variables are constant ASTs (`Z3_to_app` is an app view of the same pointer); patterns/arrays are borrowed only for the call.
        unsafe {
            let apps: Vec<RawApp> = bound.iter().map(|b| nn(z::Z3_to_app(c, b.raw))).collect();
            let pats: Vec<RawPattern> = patterns
                .iter()
                .map(|p| {
                    let term = [p.raw];
                    nn(z::Z3_mk_pattern(c, 1, term.as_ptr()))
                })
                .collect();
            // z3py: qid=skid="" → `Z3_mk_string_symbol("")` returns a null symbol, which is passed through as is.
            // z3-sys 0.14.1 wraps these two arguments in NonNull and cannot pass null, so the same C function is
            // declared separately with a null-permitting signature and called (`raw_quant` below). The other argument types are the same as z3-sys.
            self.wrap(nn(raw_quant::Z3_mk_quantifier_const_ex(
                c,
                is_forall,
                1,
                ptr::null_mut(),
                ptr::null_mut(),
                apps.len() as c_uint,
                apps.as_ptr(),
                pats.len() as c_uint,
                pats.as_ptr(),
                0,
                ptr::null(),
                body.raw,
            )))
        }
    }

    // ---- datatypes ----
    /// z3py `CreateDatatypes(d1, d2, ...)`: creates several sorts together with a single `Z3_mk_datatypes`.
    pub fn create_datatypes(&self, specs: &[DtSpec]) -> Vec<DtSort> {
        self.create_datatypes_refs(specs, &[])
    }

    /// z3py `CreateDatatypes(d1, d2, ...)` with datatype references (G9 A1, simultaneous recursive declaration).
    /// `refs[i][j][k] = Some(m)`: field k of constructor j of datatype i has the datatype number m of this very call as its
    /// sort (z3py: a field whose type is a `Datatype` object of the list gives `sorts[k] = None, refs[k] = list index`);
    /// the sort stored in `fields` is then ignored. A missing (or shorter) `refs` means "no references" everywhere.
    pub fn create_datatypes_refs(&self, specs: &[DtSpec], refs_spec: &[Vec<Vec<Option<usize>>>]) -> Vec<DtSort> {
        let c = self.raw();
        let mut all_cons: Vec<RawConstructor> = Vec::new();
        let mut lists = Vec::new();
        for (si, spec) in specs.iter().enumerate() {
            let mut cons: Vec<RawConstructor> = Vec::new();
            for (ci, ct) in spec.ctors.iter().enumerate() {
                let name = self.sym(&ct.name);
                let rec = self.sym(&format!("is-{}", ct.name)); // z3py: declare(name) → recognizer "is-name"
                let fnames: Vec<RawSymbol> = ct.fields.iter().map(|(n, _)| self.sym(n)).collect();
                let field_ref = |k: usize| -> Option<usize> {
                    refs_spec.get(si).and_then(|a| a.get(ci)).and_then(|b| b.get(k)).copied().flatten()
                };
                let sorts: Vec<Option<RawSort>> = ct
                    .fields
                    .iter()
                    .enumerate()
                    .map(|(k, (_, s))| if field_ref(k).is_some() { None } else { Some(s.raw) })
                    .collect();
                let mut refs: Vec<c_uint> = (0..ct.fields.len()).map(|k| field_ref(k).unwrap_or(0) as c_uint).collect();
                // SAFETY: S1 S2 S3 S5 — field sorts are already-created sorts (refs 0) or null with a datatype index
                // of this call (z3 resolves it inside Z3_mk_datatypes); every constructor made is del'd below.
                let con = unsafe {
                    nn(z::Z3_mk_constructor(
                        c,
                        name,
                        rec,
                        ct.fields.len() as c_uint,
                        fnames.as_ptr(),
                        sorts.as_ptr(),
                        refs.as_mut_ptr(),
                    ))
                };
                cons.push(con);
            }
            // SAFETY: S1 S3 S5 — cons is valid for this call; the list is del'd below.
            let list = unsafe { nn(z::Z3_mk_constructor_list(c, cons.len() as c_uint, cons.as_ptr())) };
            lists.push(list);
            all_cons.extend(cons);
        }
        let names: Vec<RawSymbol> = specs.iter().map(|s| self.sym(&s.name)).collect();
        // The output array is initialized to None (so uninitialized memory is never read), and each element is checked with nn() after the call.
        // The cast below is valid only if `Option<RawSort>` and `RawSort` have the same layout (NonNull-style niche).
        const _: () = assert!(core::mem::size_of::<Option<RawSort>>() == core::mem::size_of::<RawSort>());
        let mut out: Vec<Option<RawSort>> = vec![None; specs.len()];
        // SAFETY: S1 S3 S5 — names/lists have specs.len() entries, and `Z3_mk_datatypes` fills the sorts output array of specs.len()
        // entries (on failure the z3 error handler aborts). del happens only after the call. Unfilled elements are caught by nn() as a panic.
        // Z3_mk_constructor_list/Z3_mk_constructor have no output array and their return values are already checked with nn().
        let sorts: Vec<Sort> = unsafe {
            z::Z3_mk_datatypes(
                c,
                specs.len() as c_uint,
                names.as_ptr(),
                out.as_mut_ptr() as *mut RawSort,
                lists.as_mut_ptr(),
            );
            for l in lists {
                z::Z3_del_constructor_list(c, l);
            }
            for con in all_cons {
                z::Z3_del_constructor(c, con);
            }
            out.iter().map(|m| Sort { z: self.clone(), raw: nn(*m) }).collect()
        };
        // The same lookups z3py does after CreateDatatypes:constructor(j), recognizer(j), accessor(j, k).
        let mut result = Vec::new();
        for (spec, sort) in specs.iter().zip(sorts) {
            let mut ctors = Vec::new();
            for (j, ct) in spec.ctors.iter().enumerate() {
                // SAFETY: S1 S2 — sort is the datatype sort just created; the index is within the spec range.
                let (con, rec, accs) = unsafe {
                    let con = nn(z::Z3_get_datatype_sort_constructor(c, sort.raw, j as c_uint));
                    let rec = nn(z::Z3_get_datatype_sort_recognizer(c, sort.raw, j as c_uint));
                    let accs: Vec<RawFuncDecl> = (0..ct.fields.len())
                        .map(|k| {
                            nn(z::Z3_get_datatype_sort_constructor_accessor(c, sort.raw, j as c_uint, k as c_uint))
                        })
                        .collect();
                    (con, rec, accs)
                };
                ctors.push(DtCtor {
                    ctor: FuncDecl { z: self.clone(), raw: con, name: ct.name.clone() },
                    rec: FuncDecl { z: self.clone(), raw: rec, name: format!("is-{}", ct.name) },
                    accs: accs
                        .into_iter()
                        .zip(ct.fields.iter())
                        .map(|(raw, (fname, _))| FuncDecl { z: self.clone(), raw, name: fname.clone() })
                        .collect(),
                });
            }
            result.push(DtSort { sort, ctors });
        }
        result
    }

    /// z3py `z3.Function(name, *sorts)` (the last is the range).
    pub fn func_decl(&self, name: &str, domain: &[Sort], range: &Sort) -> FuncDecl {
        let s = self.sym(name);
        let dom: Vec<RawSort> = domain.iter().map(|d| d.raw).collect();
        // SAFETY: S1 S2 S3.
        let raw = unsafe { nn(z::Z3_mk_func_decl(self.raw(), s, dom.len() as c_uint, dom.as_ptr(), range.raw)) };
        FuncDecl { z: self.clone(), raw, name: name.to_string() }
    }
}

impl Default for Z3 {
    fn default() -> Self {
        Z3::new()
    }
}

impl Sort {
    pub fn sexpr(&self) -> String {
        // SAFETY: S1 S4.
        unsafe { take_string(z::Z3_sort_to_string(self.z.raw(), self.raw)) }
    }
    /// Value of `Z3_get_sort_kind` (BOOL=1, INT=2, ARRAY=5, DATATYPE=6).
    pub fn kind_id(&self) -> u32 {
        // SAFETY: S1.
        unsafe { z::Z3_get_sort_kind(self.z.raw(), self.raw) as u32 }
    }
    pub fn is_int(&self) -> bool {
        self.kind_id() == 2
    }
    pub fn is_bool(&self) -> bool {
        self.kind_id() == 1
    }
    /// z3py `sort.name()`: the symbol string.
    pub fn name(&self) -> String {
        let c = self.z.raw();
        // SAFETY: S1 S2 S4 — the sort's name symbol is valid for the context lifetime and the string is copied immediately.
        unsafe {
            let sym = nn(z::Z3_get_sort_name(c, self.raw));
            take_string(z::Z3_get_symbol_string(c, sym))
        }
    }
}

impl FuncDecl {
    pub fn new(z: &Z3, name: &str, domain: &[Sort], range: &Sort) -> FuncDecl {
        z.func_decl(name, domain, range)
    }
    pub fn name(&self) -> &str {
        &self.name
    }
    /// Application `f(args...)` (`Z3_mk_app`). A constant if there are 0 arguments.
    pub fn apply(&self, args: &[Ast]) -> Ast {
        let raw: Vec<RawAst> = args.iter().map(|a| a.raw).collect();
        // SAFETY: S1 S2 S3.
        unsafe { self.z.wrap(nn(z::Z3_mk_app(self.z.raw(), self.raw, raw.len() as c_uint, raw.as_ptr()))) }
    }
    pub fn apply1(&self, a: &Ast) -> Ast {
        self.apply(std::slice::from_ref(a))
    }
}

impl Ast {
    bin_ast!(raw_eq, Z3_mk_eq);
    bin_ast!(raw_lt, Z3_mk_lt);
    bin_ast!(raw_le, Z3_mk_le);
    bin_ast!(raw_gt, Z3_mk_gt);
    bin_ast!(raw_ge, Z3_mk_ge);

    /// z3py comparison `l OP r` (both sides are z3 expressions). Python rule: if the right operand's type is a subclass of the left's,
    /// the reflected method is called first. In z3py IntNumRef (a numeric literal) is a subclass of ArithRef, so
    /// `x >= IntVal(0)` becomes `IntVal(0).__le__(x)` = `(<= 0 x)`. Numeric literals are detected by AST kind
    /// NUMERAL (the criterion by which z3py `_to_expr_ref` picks IntNumRef). Comparison with a Python int is `*_i`.
    // Generalization: a Python comparison operator calls the right operand's reflected method first when the right operand's type is a proper subclass of the left's.
    // The pairs used here are two: ArithRef⊃IntNumRef (numeric literal) and BoolRef⊃QuantifierRef (quantified expression).
    // Example: `BoolVal(False) == ForAll(..)` is `(= forall false)`.
    fn reflect(&self, o: &Ast) -> bool {
        (o.is_numeral() && !self.is_numeral())
            || (o.is_quantifier() && !self.is_quantifier() && self.sort().is_bool())
    }
    pub fn is_quantifier(&self) -> bool {
        self.kind() == 3 // Z3_QUANTIFIER_AST
    }
    pub fn eq(&self, o: &Ast) -> Ast {
        if self.reflect(o) { o.raw_eq(self) } else { self.raw_eq(o) }
    }
    pub fn lt(&self, o: &Ast) -> Ast {
        if self.reflect(o) { o.raw_gt(self) } else { self.raw_lt(o) }
    }
    pub fn le(&self, o: &Ast) -> Ast {
        if self.reflect(o) { o.raw_ge(self) } else { self.raw_le(o) }
    }
    pub fn gt(&self, o: &Ast) -> Ast {
        if self.reflect(o) { o.raw_lt(self) } else { self.raw_gt(o) }
    }
    pub fn ge(&self, o: &Ast) -> Ast {
        if self.reflect(o) { o.raw_le(self) } else { self.raw_ge(o) }
    }
    pub fn is_numeral(&self) -> bool {
        self.kind() == 0 // Z3_NUMERAL_AST
    }
    bin_ast!(implies, Z3_mk_implies);
    bin_ast!(div, Z3_mk_div);
    bin_ast!(modulo, Z3_mk_mod);
    bin_ast!(select, Z3_mk_select);
    // P2: z3py `a & b`, `a | b`, `a ^ b` on bit-vectors (`BitVecRef.__and__` etc.: one two-argument call each).
    bin_ast!(bvand, Z3_mk_bvand);
    bin_ast!(bvor, Z3_mk_bvor);
    bin_ast!(bvxor, Z3_mk_bvxor);
    // P2 batch 2: z3py `a << b` (`BitVecRef.__lshift__` → bvshl) and `LShR(a, b)` (logical right shift → bvlshr).
    // Each expands through `bin_ast!`, whose unsafe block carries the SAFETY comment (S1 S2, same-context debug_assert).
    bin_ast!(bvshl, Z3_mk_bvshl);
    bin_ast!(bvlshr, Z3_mk_bvlshr);

    /// z3py `Int2BV(self, bits)`: `Z3_mk_int2bv(ctx, bits, a)`.
    pub fn int2bv(&self, bits: u32) -> Ast {
        // SAFETY: S1 S2 — self is an Int expression of this context.
        unsafe { self.z.wrap(nn(z::Z3_mk_int2bv(self.z.raw(), bits as c_uint, self.raw))) }
    }
    /// z3py `BV2Int(self, is_signed)`: `Z3_mk_bv2int(ctx, a, is_signed)` (z3py default is unsigned).
    pub fn bv2int(&self, is_signed: bool) -> Ast {
        // SAFETY: S1 S2 — self is a bit-vector expression of this context.
        unsafe { self.z.wrap(nn(z::Z3_mk_bv2int(self.z.raw(), self.raw, is_signed))) }
    }

    /// Python `a != b` → `Z3_mk_distinct(a, b)`.
    pub fn ne(&self, o: &Ast) -> Ast {
        if self.reflect(o) {
            return self.z.distinct(&[o.clone(), self.clone()]);
        }
        self.z.distinct(&[self.clone(), o.clone()])
    }
    pub fn add(&self, o: &Ast) -> Ast {
        self.z.add_n(&[self.clone(), o.clone()])
    }
    pub fn sub(&self, o: &Ast) -> Ast {
        self.z.sub_n(&[self.clone(), o.clone()])
    }
    pub fn mul(&self, o: &Ast) -> Ast {
        self.z.mul_n(&[self.clone(), o.clone()])
    }
    pub fn neg(&self) -> Ast {
        // SAFETY: S1 S2.
        unsafe { self.z.wrap(nn(z::Z3_mk_unary_minus(self.z.raw(), self.raw))) }
    }
    pub fn not(&self) -> Ast {
        // SAFETY: S1 S2.
        unsafe { self.z.wrap(nn(z::Z3_mk_not(self.z.raw(), self.raw))) }
    }
    pub fn store(&self, i: &Ast, v: &Ast) -> Ast {
        // SAFETY: S1 S2.
        unsafe { self.z.wrap(nn(z::Z3_mk_store(self.z.raw(), self.raw, i.raw, v.raw))) }
    }

    // Cases like Python's `x + 1`, `x >= 0` where an integer literal is on the right (promoted to IntVal).
    pub fn add_i(&self, v: i64) -> Ast {
        self.add(&self.z.int(v))
    }
    pub fn sub_i(&self, v: i64) -> Ast {
        self.sub(&self.z.int(v))
    }
    pub fn lt_i(&self, v: i64) -> Ast {
        self.raw_lt(&self.z.int(v))
    }
    pub fn le_i(&self, v: i64) -> Ast {
        self.raw_le(&self.z.int(v))
    }
    /// Python `x != 0` (integer literal, no reflection):`Z3_mk_distinct(x, IntVal(v))`.
    pub fn ne_i(&self, v: i64) -> Ast {
        self.z.distinct(&[self.clone(), self.z.int(v)])
    }
    pub fn gt_i(&self, v: i64) -> Ast {
        self.raw_gt(&self.z.int(v))
    }
    pub fn ge_i(&self, v: i64) -> Ast {
        self.raw_ge(&self.z.int(v))
    }

    // Comparison with a source integer literal (IntVal in verify.py ev): follows the reflection rule.
    pub fn eq_l(&self, v: i64) -> Ast { self.eq(&self.z.int(v)) }
    pub fn lt_l(&self, v: i64) -> Ast { self.lt(&self.z.int(v)) }
    pub fn le_l(&self, v: i64) -> Ast { self.le(&self.z.int(v)) }
    pub fn gt_l(&self, v: i64) -> Ast { self.gt(&self.z.int(v)) }
    pub fn ge_l(&self, v: i64) -> Ast { self.ge(&self.z.int(v)) }

    /// z3py `ast.sexpr()` (`Z3_ast_to_string`).
    pub fn sexpr(&self) -> String {
        // SAFETY: S1 S4.
        unsafe { take_string(z::Z3_ast_to_string(self.z.raw(), self.raw)) }
    }
    pub fn id(&self) -> u32 {
        // SAFETY: S1.
        unsafe { z::Z3_get_ast_id(self.z.raw(), self.raw) as u32 }
    }
    fn kind(&self) -> u32 {
        // SAFETY: S1.
        unsafe { z::Z3_get_ast_kind(self.z.raw(), self.raw) as u32 }
    }
    /// z3py `a.eq(b)` (structural identity).
    pub fn same(&self, o: &Ast) -> bool {
        // SAFETY: S1.
        unsafe { z::Z3_is_eq_ast(self.z.raw(), self.raw, o.raw) }
    }
    pub fn sort(&self) -> Sort {
        // SAFETY: S1 S2.
        Sort { z: self.z.clone(), raw: unsafe { nn(z::Z3_get_sort(self.z.raw(), self.raw)) } }
    }
    pub fn simplify(&self) -> Ast {
        // SAFETY: S1 S2.
        unsafe { self.z.wrap(nn(z::Z3_simplify(self.z.raw(), self.raw))) }
    }
    /// Is this the literal `true` (`z3.is_true`)?
    pub fn is_true(&self) -> bool {
        // SAFETY: S1 — for an AST that is not a bool value, L_UNDEF is returned.
        (unsafe { z::Z3_get_bool_value(self.z.raw(), self.raw) }) as i32 == LBOOL_TRUE
    }
    /// Is this the literal `false`?
    pub fn is_false(&self) -> bool {
        // SAFETY: S1.
        (unsafe { z::Z3_get_bool_value(self.z.raw(), self.raw) }) as i32 == LBOOL_FALSE
    }
    fn num_args(&self) -> u32 {
        // SAFETY: S1 S2 — called only after the caller has confirmed kind()==APP.
        unsafe {
            let app = nn(z::Z3_to_app(self.z.raw(), self.raw));
            z::Z3_get_app_num_args(self.z.raw(), app) as u32
        }
    }
    fn arg(&self, i: u32) -> Ast {
        // SAFETY: S1 S2 — kind()==APP and i < num_args().
        unsafe {
            let app = nn(z::Z3_to_app(self.z.raw(), self.raw));
            self.z.wrap(nn(z::Z3_get_app_arg(self.z.raw(), app, i as c_uint)))
        }
    }
    fn body(&self) -> Ast {
        // SAFETY: S1 S2 — kind()==QUANTIFIER.
        unsafe { self.z.wrap(nn(z::Z3_get_quantifier_body(self.z.raw(), self.raw))) }
    }

    /// z3py `z3.is_app`: kind APP or NUMERAL.
    pub fn is_app(&self) -> bool {
        let k = self.kind();
        k == 0 || k == K_APP
    }
    /// z3py `children()` (APP only; numeric literals and quantifiers give an empty list).
    pub fn children(&self) -> Vec<Ast> {
        if self.kind() != K_APP {
            return Vec::new();
        }
        (0..self.num_args()).map(|i| self.arg(i)).collect()
    }
    /// z3py `v.decl().name()` (APP only).
    pub fn decl_name(&self) -> Option<String> {
        if self.kind() != K_APP {
            return None;
        }
        let c = self.z.raw();
        // SAFETY: S1 S2 S4 — after confirming kind()==APP; the string is copied immediately.
        unsafe {
            let app = nn(z::Z3_to_app(c, self.raw));
            let d = nn(z::Z3_get_app_decl(c, app));
            let sym = nn(z::Z3_get_decl_name(c, d));
            Some(take_string(z::Z3_get_symbol_string(c, sym)))
        }
    }
    /// Decimal string of a numeric literal (the value z3py `as_long()` reads, arbitrary length). None if not a numeric literal.
    pub fn numeral_string(&self) -> Option<String> {
        if self.kind() != 0 {
            return None;
        }
        // SAFETY: S1 S4 — after confirming kind NUMERAL; the string is copied immediately.
        Some(unsafe { take_string(z::Z3_get_numeral_string(self.z.raw(), self.raw)) })
    }

    /// z3py `z3.substitute(t, (from_i, to_i)...)`.
    pub fn substitute(&self, from: &[Ast], to: &[Ast]) -> Ast {
        assert_eq!(from.len(), to.len());
        let f: Vec<RawAst> = from.iter().map(|a| a.raw).collect();
        let t: Vec<RawAst> = to.iter().map(|a| a.raw).collect();
        // SAFETY: S1 S2 S3.
        unsafe {
            self.z.wrap(nn(z::Z3_substitute(self.z.raw(), self.raw, f.len() as c_uint, f.as_ptr(), t.as_ptr())))
        }
    }

    /// verify.py `_occurs(t, c)`: does constant `c` occur within `self` (descending into quantifier bodies)?
    pub fn occurs(&self, c: &Ast) -> bool {
        let mut seen: HashSet<u32> = HashSet::new();
        let mut todo: Vec<Ast> = vec![self.clone()];
        while let Some(n) = todo.pop() {
            if !seen.insert(n.id()) {
                continue;
            }
            match n.kind() {
                K_APP => {
                    let na = n.num_args();
                    if na == 0 && n.same(c) {
                        return true;
                    }
                    for i in 0..na {
                        todo.push(n.arg(i));
                    }
                }
                K_QUANTIFIER => todo.push(n.body()),
                _ => {}
            }
        }
        false
    }
}

// ---------------------------------------------------------------------------------------------
// Datatype spec/result
// ---------------------------------------------------------------------------------------------

pub struct DtCtorSpec {
    pub name: String,
    /// (field (accessor) name, field sort)
    pub fields: Vec<(String, Sort)>,
}
pub struct DtSpec {
    pub name: String,
    pub ctors: Vec<DtCtorSpec>,
}
pub struct DtCtor {
    pub ctor: FuncDecl,
    pub rec: FuncDecl,
    pub accs: Vec<FuncDecl>,
}
pub struct DtSort {
    pub sort: Sort,
    pub ctors: Vec<DtCtor>,
}

// ---------------------------------------------------------------------------------------------
// Solver
// ---------------------------------------------------------------------------------------------

pub struct Solver {
    z: Z3,
    raw: RawSolver,
}

impl Solver {
    /// z3py `s = Solver(); s.set("timeout", ms)`.
    pub fn new(z: &Z3, timeout_ms: u32) -> Solver {
        Solver::with_options(z, timeout_ms, None, None)
    }

    /// z3py `s.set("timeout", t)`, (if present) `s.set("rlimit", r)`, (if present) `s.set("random_seed", s)`, in this order.
    pub fn with_options(z: &Z3, timeout_ms: u32, rlimit: Option<u32>, seed: Option<u32>) -> Solver {
        let key = z.sym("timeout");
        let rkey = rlimit.map(|_| z.sym("rlimit"));
        let skey = seed.map(|_| z.sym("random_seed"));
        let c = z.raw();
        // SAFETY: S1 S5 — solver/params get inc_ref right after creation, params get dec_ref right after set, and the solver gets dec_ref in Drop.
        // The symbols (key/rkey/skey) were made in the same context (S1).
        unsafe {
            let s = nn(z::Z3_mk_solver(c));
            z::Z3_solver_inc_ref(c, s);
            let p = nn(z::Z3_mk_params(c));
            z::Z3_params_inc_ref(c, p);
            z::Z3_params_set_uint(c, p, key, timeout_ms as c_uint);
            if let (Some(k), Some(r)) = (rkey, rlimit) {
                z::Z3_params_set_uint(c, p, k, r as c_uint);
            }
            if let (Some(k), Some(sd)) = (skey, seed) {
                z::Z3_params_set_uint(c, p, k, sd as c_uint);
            }
            z::Z3_solver_set_params(c, s, p);
            z::Z3_params_dec_ref(c, p);
            Solver { z: z.clone(), raw: s }
        }
    }
    pub fn add(&mut self, a: &Ast) {
        // SAFETY: S1 S2 — a is a Bool expression of the same context.
        unsafe { z::Z3_solver_assert(self.z.raw(), self.raw, a.raw) }
    }
    /// z3py `Solver.sexpr()` (`Z3_solver_to_string`).
    pub fn to_smt2(&self) -> String {
        // SAFETY: S1 S4.
        unsafe { take_string(z::Z3_solver_to_string(self.z.raw(), self.raw)) }
    }
    /// z3py `Solver.model()`: call only when the preceding check was sat (otherwise the z3 error handler aborts).
    pub fn model(&self) -> ZModel {
        let c = self.z.raw();
        // SAFETY: S1 S5 — the model gets inc_ref right after creation and dec_ref in `ZModel`'s Drop.
        unsafe {
            let m = nn(z::Z3_solver_get_model(c, self.raw));
            z::Z3_model_inc_ref(c, m);
            ZModel { z: self.z.clone(), raw: m }
        }
    }
    /// z3py `Solver.reason_unknown()`.
    pub fn reason_unknown(&self) -> String {
        // SAFETY: S1 S4.
        unsafe { take_string(z::Z3_solver_get_reason_unknown(self.z.raw(), self.raw)) }
    }
    pub fn check(&mut self) -> Sat {
        // SAFETY: S1 — reads the lbool via `as i32` (works for both enum and integer alias).
        let r = unsafe { z::Z3_solver_check(self.z.raw(), self.raw) } as i32;
        match r {
            LBOOL_TRUE => Sat::Sat,
            LBOOL_FALSE => Sat::Unsat,
            _ => Sat::Unknown,
        }
    }
}
impl Drop for Solver {
    fn drop(&mut self) {
        // SAFETY: S1 S5 — pairs with the inc_ref in new().
        unsafe { z::Z3_solver_dec_ref(self.z.raw(), self.raw) }
    }
}

type RawModel = z::Z3_model;

/// z3 model (z3py `ModelRef`).
pub struct ZModel {
    z: Z3,
    raw: RawModel,
}

impl ZModel {
    /// z3py `m.eval(a, model_completion=True)`. None if evaluation fails (z3py raises an exception).
    pub fn eval(&self, a: &Ast) -> Option<Ast> {
        let c = self.z.raw();
        // The output slot is initialized to None (NonNull niche: `Option<RawAst>` and `RawAst` have the same size — see the const assertion below).
        let mut out: Option<RawAst> = None;
        // SAFETY: S1 S2 — the model and expression belong to this context; the output slot is a local valid for this call and z3 fills it.
        let ok = unsafe {
            z::Z3_model_eval(c, self.raw, a.raw, true, &mut out as *mut Option<RawAst> as *mut RawAst)
        };
        if !ok {
            return None;
        }
        out.map(|raw| Ast { z: self.z.clone(), raw })
    }
}
impl Drop for ZModel {
    fn drop(&mut self) {
        // SAFETY: S1 S5 — pairs with the inc_ref in `Solver::model`.
        unsafe { z::Z3_model_dec_ref(self.z.raw(), self.raw) }
    }
}
const _: () = assert!(core::mem::size_of::<Option<RawAst>>() == core::mem::size_of::<RawAst>());

/// Declaration of `Z3_mk_quantifier_const_ex` that permits null symbols (the z3 C API allows null for qid/skid).
#[allow(clashing_extern_declarations, non_snake_case)]
mod raw_quant {
    use z3_sys as z;
    extern "C" {
        pub fn Z3_mk_quantifier_const_ex(
            c: z::Z3_context,
            is_forall: bool,
            weight: ::core::ffi::c_uint,
            quantifier_id: *mut z::_Z3_symbol,
            skolem_id: *mut z::_Z3_symbol,
            num_bound: ::core::ffi::c_uint,
            bound: *const z::Z3_app,
            num_patterns: ::core::ffi::c_uint,
            patterns: *const z::Z3_pattern,
            num_no_patterns: ::core::ffi::c_uint,
            no_patterns: *const z::Z3_ast,
            body: z::Z3_ast,
        ) -> Option<z::Z3_ast>;
    }
}

// Verify at compile time that the return type `Option<Z3_ast>` of the separate extern above is pointer-sized (niche).
const _: () = assert!(core::mem::size_of::<Option<z3_sys::Z3_ast>>() == core::mem::size_of::<usize>());
