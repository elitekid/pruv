/* Windows x64 C ABI 기준. check_abi.py 가 이 파일을
 *   clang --target=x86_64-pc-windows-msvc -O0 -S -emit-llvm
 * 으로 IR 로 만들어, 아래 두 종류의 서명을 우리 .ll 표본과 비교한다.
 *   - pruv_abi_*      : extern 선언을 부르는 호출자 (IR 의 declare 서명 = 호출 규약)
 *   - ref_pruv_abi_*  : 같은 서명을 C 로 정의한 기준 구현 (IR 의 define 서명)
 * 기대: 16바이트 구조체 반환은 `void @f(ptr sret(%struct.PruvTagged) align 8, ...)`.
 */
#include <stdint.h>

typedef struct { int64_t tag, payload; } PruvTagged;
typedef struct { const int64_t *ptr; int64_t len; } PruvArr;

PruvTagged pruv_abi_get_opt(int64_t);
PruvTagged pruv_abi_get_res(int64_t);
PruvTagged pruv_abi_f0(void);
PruvTagged pruv_abi_f1(int64_t);
PruvTagged pruv_abi_f5(int64_t, int64_t, int64_t, int64_t, int64_t);
void pruv_abi_arr(const int64_t *v, int64_t n, PruvArr *out);
void pruv_abi_bump(const int64_t *p, int64_t d, int64_t *out);

/* 호출자: 선언이 IR 에 남도록 실제로 호출한다. */
int64_t ref_caller(const int64_t *v, int64_t n) {
    int64_t acc = 0;
    PruvTagged t;
    t = pruv_abi_get_opt(n);              acc += t.tag + t.payload;
    t = pruv_abi_get_res(n);              acc += t.tag + t.payload;
    t = pruv_abi_f0();                    acc += t.tag + t.payload;
    t = pruv_abi_f1(n);                   acc += t.tag + t.payload;
    t = pruv_abi_f5(n, n, n, n, n);       acc += t.tag + t.payload;
    PruvArr a;
    pruv_abi_arr(v, n, &a);               acc += a.len;
    int64_t out[3];
    pruv_abi_bump(v, n, out);             acc += out[0];
    return acc;
}

/* 기준 구현: 서명만 중요하다. */
PruvTagged ref_pruv_abi_get_opt(int64_t x) { PruvTagged t = { x > 0, x > 0 ? x : 0 }; return t; }
PruvTagged ref_pruv_abi_get_res(int64_t x) { PruvTagged t = { x >= 0, x >= 0 ? x : -x }; return t; }
PruvTagged ref_pruv_abi_f0(void) { PruvTagged t = { 0, 0 }; return t; }
PruvTagged ref_pruv_abi_f1(int64_t a) { PruvTagged t = { a > 0, a > 0 ? a : 0 }; return t; }
PruvTagged ref_pruv_abi_f5(int64_t a, int64_t b, int64_t c, int64_t d, int64_t e) {
    int64_t s = a + b + c + d + e;
    PruvTagged t = { s > 0, s > 0 ? s : 0 };
    return t;
}
void ref_pruv_abi_arr(const int64_t *v, int64_t n, PruvArr *out) { out->ptr = v; out->len = n; }
void ref_pruv_abi_bump(const int64_t *p, int64_t d, int64_t *out) {
    out[0] = p[0] + d; out[1] = p[1]; out[2] = p[2];
}
