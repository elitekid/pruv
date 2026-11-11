/* Windows x64 C ABI reference. check_abi.py compiles this file to IR with
 *   clang --target=x86_64-pc-windows-msvc -O0 -S -emit-llvm
 * and cross-checks the two kinds of signatures below against our .ll samples.
 *   - pruv_abi_*      : callers of the extern declarations (IR declare signature = calling convention)
 *   - ref_pruv_abi_*  : reference implementations defining the same signatures in C (IR define signature)
 * Expected: a 16-byte struct return is `void @f(ptr sret(%struct.PruvTagged) align 8, ...)`.
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

/* Caller: actually calls each function so the declarations remain in the IR. */
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

/* Reference implementations: only the signatures matter. */
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
