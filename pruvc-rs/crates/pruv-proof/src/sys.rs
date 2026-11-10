//! z3-sys 위의 작은 래퍼. 이 프로젝트의 unsafe 는 전부 여기에 있다.
//!
//! 호출 순서·인자는 z3py(`z3.py`)가 하는 C API 호출을 그대로 따른다. SMT 텍스트를 Python 과 글자 단위로
//! 맞추기 위해서다. z3py 와 맞춘 지점(확신 낮은 것은 README/최종 보고에 별도 표기):
//! - `Z3_set_ast_print_mode(ctx, SMTLIB2_COMPLIANT)` (z3py `Context.__init__`)
//! - 양화: 항상 `Z3_mk_quantifier_const_ex(weight=1, qid="", skid="")` (z3py `_mk_quantifier`)
//! - 패턴: 항(term) 하나짜리 `Z3_mk_pattern` (z3py `_to_pattern` → `MultiPattern`)
//! - Datatype: `Z3_mk_constructor(name, "is-"+name, ...)` + `Z3_mk_datatypes` (z3py `CreateDatatypes`)
//! - 산술: `+ - *` 는 인자 2개짜리 `Z3_mk_add/sub/mul`, `!=` 는 `Z3_mk_distinct`(Python `__ne__`)
//! - 솔버: `Z3_mk_solver`, 타임아웃은 `Z3_params_set_uint("timeout", ms)` 후 `Z3_solver_set_params`
//!
//! # 공통 안전 근거 (각 unsafe 블록의 `SAFETY:` 가 번호로 인용)
//! - **S1 컨텍스트 소유**: `Z3`(= `Rc<Ctx>`)는 모든 핸들(`Ast`/`Sort`/`FuncDecl`/`Solver`)이 복제본을 들고 있어
//!   raw 포인터가 쓰이는 동안 `Z3_del_context` 가 불리지 않는다. 핸들은 `Rc` 때문에 `!Send` 라 한 스레드 전용.
//! - **S2 논-rc 컨텍스트**: `Z3_mk_context`(rc 아님)로 만든다. 이 컨텍스트에서 Ast/Sort/FuncDecl/Symbol/Pattern 은
//!   `Z3_solver_pop` 으로 범위를 내리지 않는 한 컨텍스트가 삭제될 때까지 유효하다. 우리는 push/pop 을 쓰지 않는다.
//!   따라서 Ast 에 inc_ref/dec_ref 를 하지 않는다(해야 하는 것은 solver/params/constructor 뿐, S5).
//! - **S3 배열 인자**: 길이·포인터는 호출 동안만 빌려 쓰는 슬라이스/Vec 에서 나오고, z3 는 호출 안에서 복사한다.
//! - **S4 문자열**: 넘기는 `CString` 은 호출이 끝날 때까지 산다. 돌려받는 `*const c_char` 는 같은 컨텍스트의 다음
//!   API 호출 전까지만 유효하므로 즉시 `String` 으로 복사한다.
//! - **S5 ref-counted 객체**: solver/params 는 생성 직후 `inc_ref`, `Drop`(또는 사용 직후)에서 `dec_ref`.
//!   constructor/constructor_list 는 `Z3_mk_datatypes` 직후 `del_*` 로 해제한다.
//! - **S6 반환 포인터**: z3-sys 가 `Option<NonNull>` 로 돌려주든 raw 포인터로 돌려주든 `nn()` 이 null 을 패닉으로
//!   바꾸고 같은 모양의 non-null 타입으로 돌려준다(버전 차이를 한 곳에 가둔다).
//!
//! 메인이 실제 빌드에서 z3-sys 0.22 계열 시그니처와 어긋나는 곳은 이 파일만 고치면 된다.

use std::collections::HashSet;
use std::ffi::{CStr, CString};
use std::os::raw::{c_char, c_uint};
use std::ptr::{self, NonNull};
use std::rc::Rc;

use z3_sys as z;

// ---------------------------------------------------------------------------------------------
// z3-sys 버전 차이 흡수: 반환 포인터 정규화 (S6)
// ---------------------------------------------------------------------------------------------

/// `Option<NonNull<T>>`/`NonNull<T>`/`*mut T`/`Option<*mut T>` 를 같은 non-null 모양으로 정규화.
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

// `as u32/i32` 로 읽어 z3-sys 가 enum 으로 내든 정수 별칭으로 내든 같게 동작한다.
const K_APP: u32 = 1; // Z3_APP_AST
const K_QUANTIFIER: u32 = 3; // Z3_QUANTIFIER_AST
const LBOOL_TRUE: i32 = 1;
const LBOOL_FALSE: i32 = -1;

unsafe fn take_string(p: *const c_char) -> String {
    // SAFETY: S4 — 호출자가 방금 받은 z3 문자열 포인터이며 즉시 복사한다.
    unsafe { CStr::from_ptr(p).to_string_lossy().into_owned() }
}

// ---------------------------------------------------------------------------------------------
// 컨텍스트
// ---------------------------------------------------------------------------------------------

struct Ctx {
    raw: RawCtx,
}
impl Drop for Ctx {
    fn drop(&mut self) {
        // SAFETY: S1 — 마지막 `Z3` 복제본이 사라질 때만 불리므로 이 컨텍스트를 쓰는 핸들은 이미 없다.
        unsafe { z::Z3_del_context(self.raw) }
    }
}

/// 컨텍스트 핸들. 복제는 `Rc` 복제. Python 의 `main_ctx()` 에 해당(프로세스당 하나일 필요는 없고 표본마다 새로 만든다).
#[derive(Clone)]
pub struct Z3(Rc<Ctx>);

/// solver 판정.
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

/// z3 오류 처리기: 오류 코드와 메시지를 stderr 에 쓰고 abort (종료 코드 1 로 위장하지 않는다).
extern "C" fn on_z3_error(c: RawCtx, e: z::ErrorCode) {
    use std::io::Write;
    // SAFETY: S4 — z3 가 방금 이 컨텍스트에 대해 돌려준 오류 메시지를 즉시 복사한다.
    let msg = unsafe { take_string(z::Z3_get_error_msg(c, e)) };
    let _ = writeln!(std::io::stderr(), "pruv: z3 error {:?}: {}", e as i32, msg);
    std::process::abort();
}

/// libz3 전체 버전 문자열 (`Z3_get_full_version`).
pub fn full_version() -> String {
    // SAFETY: S4 — 인자 없는 정적 문자열 getter; 즉시 복사.
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
            debug_assert!(Rc::ptr_eq(&self.z.0, &o.z.0), "AST 가 서로 다른 컨텍스트에 속함");
            // SAFETY: S1 S2 — 두 AST 는 같은 컨텍스트에서 만들어졌고(위 debug_assert) 컨텍스트 삭제 전까지 유효.
            unsafe { self.z.wrap(nn(z::$f(self.z.raw(), self.raw, o.raw))) }
        }
    };
}
macro_rules! nary_ast {
    ($name:ident, $f:ident) => {
        pub fn $name(&self, args: &[Ast]) -> Ast {
            let raw: Vec<RawAst> = args.iter().map(|a| a.raw).collect();
            // SAFETY: S1 S2 S3 — raw 는 이 호출 동안만 빌려 쓰는 Vec, 원소 AST 는 이 컨텍스트 소속.
            unsafe { self.wrap(nn(z::$f(self.raw(), raw.len() as c_uint, raw.as_ptr()))) }
        }
    };
}

impl Z3 {
    /// z3py `Context()` 에 대응: 논-rc 컨텍스트 + SMT-LIB2 출력 모드.
    pub fn new() -> Z3 {
        // SAFETY: S2 — config 는 컨텍스트 생성 직후 삭제한다. 출력 모드는 z3-sys enum 값을 그대로 넘긴다.
        unsafe {
            let cfg = nn(z::Z3_mk_config());
            let raw = nn(z::Z3_mk_context(cfg));
            z::Z3_del_config(cfg);
            // z3 기본 오류 처리기는 stdout 에 쓰고 exit(1) 해서 '언어 거부'(종료 코드 1)와 구별되지 않는다.
            // 가정: z3-sys 0.14.1 의 `Z3_error_handler` = `Option<unsafe extern "C" fn(Z3_context, ErrorCode)>`
            // (오류 코드 enum 이름은 z3-sys 의 `ErrorCode`; 맞지 않으면 on_z3_error 서명만 고친다).
            z::Z3_set_error_handler(raw, Some(on_z3_error));
            // z3py Context(): Z3_set_ast_print_mode(ctx, Z3_PRINT_SMTLIB2_COMPLIANT) (값 2).
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
        // SAFETY: S1 S4 — cs 는 이 문장 끝까지 산다; z3 는 문자열을 복사해 심볼 테이블에 넣는다.
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
    pub fn array_sort(&self, dom: &Sort, range: &Sort) -> Sort {
        // SAFETY: S1 S2 — dom/range 는 같은 컨텍스트의 sort.
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
    /// z3py `z3.IntVal(v)`: 십진 문자열 numeral.
    pub fn int(&self, v: i64) -> Ast {
        let cs = CString::new(v.to_string()).expect("digits only");
        let s = self.int_sort();
        // SAFETY: S1 S2 S4.
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
    /// z3py `ForAll(vs, body, patterns=...)`. 변수 0개면 body 그대로(z3py 와 같음).
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
        // SAFETY: S1 S2 S3 — 변수는 상수 AST(`Z3_to_app` 은 같은 포인터의 app 뷰); 패턴/배열은 호출 동안만 빌림.
        unsafe {
            let apps: Vec<RawApp> = bound.iter().map(|b| nn(z::Z3_to_app(c, b.raw))).collect();
            let pats: Vec<RawPattern> = patterns
                .iter()
                .map(|p| {
                    let term = [p.raw];
                    nn(z::Z3_mk_pattern(c, 1, term.as_ptr()))
                })
                .collect();
            // z3py: qid=skid="" → `Z3_mk_string_symbol("")` 는 null 기호를 돌려주고 그대로 넘긴다.
            // z3-sys 0.14.1 은 이 두 인자를 NonNull 로 묶어 null 을 못 넘기므로 같은 C 함수를
            // null 허용 서명으로 따로 선언해 부른다(아래 `raw_quant`). 나머지 인자 형은 z3-sys 와 같다.
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
    /// z3py `CreateDatatypes(d1, d2, ...)`: 한 번의 `Z3_mk_datatypes` 로 여러 sort 를 함께 만든다.
    pub fn create_datatypes(&self, specs: &[DtSpec]) -> Vec<DtSort> {
        let c = self.raw();
        let mut all_cons: Vec<RawConstructor> = Vec::new();
        let mut lists = Vec::new();
        for spec in specs {
            let mut cons: Vec<RawConstructor> = Vec::new();
            for ct in &spec.ctors {
                let name = self.sym(&ct.name);
                let rec = self.sym(&format!("is-{}", ct.name)); // z3py: declare(name) → recognizer "is-name"
                let fnames: Vec<RawSymbol> = ct.fields.iter().map(|(n, _)| self.sym(n)).collect();
                let sorts: Vec<Option<RawSort>> = ct.fields.iter().map(|(_, s)| Some(s.raw)).collect();
                let mut refs: Vec<c_uint> = vec![0; ct.fields.len()];
                // SAFETY: S1 S2 S3 S5 — 필드 sort 는 모두 이미 만들어진 sort(재귀 참조 없음 → refs 는 0);
                // 만든 constructor 는 아래에서 모두 del 한다.
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
            // SAFETY: S1 S3 S5 — cons 는 이 호출 동안 유효; list 는 아래에서 del.
            let list = unsafe { nn(z::Z3_mk_constructor_list(c, cons.len() as c_uint, cons.as_ptr())) };
            lists.push(list);
            all_cons.extend(cons);
        }
        let names: Vec<RawSymbol> = specs.iter().map(|s| self.sym(&s.name)).collect();
        // 출력 배열은 None 으로 초기화해 두고(미초기화 메모리를 읽지 않는다) 호출 뒤 원소마다 nn() 으로 검사한다.
        // `Option<RawSort>` 와 `RawSort` 의 배치가 같아야 아래 캐스트가 유효하다(NonNull 류의 niche).
        const _: () = assert!(core::mem::size_of::<Option<RawSort>>() == core::mem::size_of::<RawSort>());
        let mut out: Vec<Option<RawSort>> = vec![None; specs.len()];
        // SAFETY: S1 S3 S5 — names/lists 는 specs.len() 개, `Z3_mk_datatypes` 는 sorts 출력 배열 specs.len() 개를
        // 채운다(실패하면 z3 오류 처리기가 abort). 호출 뒤에만 del 한다. 채워지지 않은 원소는 nn() 이 패닉으로 잡는다.
        // Z3_mk_constructor_list/Z3_mk_constructor 는 출력 배열이 없고 반환값을 이미 nn() 으로 검사한다.
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
        // z3py 가 CreateDatatypes 뒤에 하는 것과 같은 조회: constructor(j), recognizer(j), accessor(j, k).
        let mut result = Vec::new();
        for (spec, sort) in specs.iter().zip(sorts) {
            let mut ctors = Vec::new();
            for (j, ct) in spec.ctors.iter().enumerate() {
                // SAFETY: S1 S2 — sort 는 방금 만든 datatype sort, 인덱스는 spec 범위 안.
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

    /// z3py `z3.Function(name, *sorts)` (마지막이 치역).
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
}

impl FuncDecl {
    pub fn new(z: &Z3, name: &str, domain: &[Sort], range: &Sort) -> FuncDecl {
        z.func_decl(name, domain, range)
    }
    pub fn name(&self) -> &str {
        &self.name
    }
    /// 적용 `f(args...)` (`Z3_mk_app`). 인자 0개면 상수.
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

    /// z3py 비교 `l OP r` (두 쪽 모두 z3 식). Python 규칙: 오른쪽 형이 왼쪽 형의 하위 클래스면
    /// 반사 메서드가 먼저 불린다. z3py 에서 IntNumRef(수 리터럴)는 ArithRef 의 하위 클래스이므로
    /// `x >= IntVal(0)` 은 `IntVal(0).__le__(x)` = `(<= 0 x)` 가 된다. 수 리터럴 판정은 AST 종류
    /// NUMERAL(z3py `_to_expr_ref` 가 IntNumRef 를 고르는 기준)로 한다. 파이썬 int 와의 비교는 `*_i`.
    fn reflect(&self, o: &Ast) -> bool {
        o.is_numeral() && !self.is_numeral()
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

    // Python 의 `x + 1`, `x >= 0` 처럼 정수 리터럴이 오른쪽에 오는 경우(IntVal 로 승격).
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
    pub fn gt_i(&self, v: i64) -> Ast {
        self.raw_gt(&self.z.int(v))
    }
    pub fn ge_i(&self, v: i64) -> Ast {
        self.raw_ge(&self.z.int(v))
    }

    // 소스 정수 리터럴(verify.py ev 의 IntVal)과의 비교: 반사 규칙을 따른다.
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
    /// z3py `a.eq(b)` (구조적 동일).
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
    /// 리터럴 `true` 인가(`z3.is_true`).
    pub fn is_true(&self) -> bool {
        // SAFETY: S1 — bool 값이 아닌 AST 에는 L_UNDEF 를 돌려준다.
        (unsafe { z::Z3_get_bool_value(self.z.raw(), self.raw) }) as i32 == LBOOL_TRUE
    }
    /// 리터럴 `false` 인가.
    pub fn is_false(&self) -> bool {
        // SAFETY: S1.
        (unsafe { z::Z3_get_bool_value(self.z.raw(), self.raw) }) as i32 == LBOOL_FALSE
    }
    fn num_args(&self) -> u32 {
        // SAFETY: S1 S2 — 호출자가 kind()==APP 를 확인한 뒤에만 부른다.
        unsafe {
            let app = nn(z::Z3_to_app(self.z.raw(), self.raw));
            z::Z3_get_app_num_args(self.z.raw(), app) as u32
        }
    }
    fn arg(&self, i: u32) -> Ast {
        // SAFETY: S1 S2 — kind()==APP 이고 i < num_args().
        unsafe {
            let app = nn(z::Z3_to_app(self.z.raw(), self.raw));
            self.z.wrap(nn(z::Z3_get_app_arg(self.z.raw(), app, i as c_uint)))
        }
    }
    fn body(&self) -> Ast {
        // SAFETY: S1 S2 — kind()==QUANTIFIER.
        unsafe { self.z.wrap(nn(z::Z3_get_quantifier_body(self.z.raw(), self.raw))) }
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

    /// verify.py `_occurs(t, c)`: 상수 `c` 가 `self` 안에 나타나는가(양화 본문까지 따라감).
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
// Datatype 사양/결과
// ---------------------------------------------------------------------------------------------

pub struct DtCtorSpec {
    pub name: String,
    /// (필드(접근자) 이름, 필드 sort)
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
        let key = z.sym("timeout");
        let c = z.raw();
        // SAFETY: S1 S5 — solver/params 는 생성 직후 inc_ref, params 는 set 직후 dec_ref, solver 는 Drop 에서 dec_ref.
        unsafe {
            let s = nn(z::Z3_mk_solver(c));
            z::Z3_solver_inc_ref(c, s);
            let p = nn(z::Z3_mk_params(c));
            z::Z3_params_inc_ref(c, p);
            z::Z3_params_set_uint(c, p, key, timeout_ms as c_uint);
            z::Z3_solver_set_params(c, s, p);
            z::Z3_params_dec_ref(c, p);
            Solver { z: z.clone(), raw: s }
        }
    }
    pub fn add(&mut self, a: &Ast) {
        // SAFETY: S1 S2 — a 는 같은 컨텍스트의 Bool 식.
        unsafe { z::Z3_solver_assert(self.z.raw(), self.raw, a.raw) }
    }
    /// z3py `Solver.sexpr()` (`Z3_solver_to_string`).
    pub fn to_smt2(&self) -> String {
        // SAFETY: S1 S4.
        unsafe { take_string(z::Z3_solver_to_string(self.z.raw(), self.raw)) }
    }
    pub fn check(&mut self) -> Sat {
        // SAFETY: S1 — `as i32` 로 lbool 을 읽는다(enum/정수 별칭 모두 가능).
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
        // SAFETY: S1 S5 — new() 의 inc_ref 와 짝.
        unsafe { z::Z3_solver_dec_ref(self.z.raw(), self.raw) }
    }
}

/// null 기호를 허용하는 `Z3_mk_quantifier_const_ex` 선언(z3 C API 는 qid/skid 에 null 을 허용한다).
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

// 위 별도 extern 의 반환형 `Option<Z3_ast>` 가 포인터 크기(niche)임을 컴파일 때 확인한다.
const _: () = assert!(core::mem::size_of::<Option<z3_sys::Z3_ast>>() == core::mem::size_of::<usize>());
