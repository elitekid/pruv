/*
 * Pruv runtime support for the LLVM backend (pruvc --backend llvm). C11.
 *   clang -O2 -std=c11 -c runtime.c                      (malloc/free)
 *   clang -O2 -std=c11 -DPRUV_RUST_ALLOCATOR -c runtime.c (Rust allocator)
 *
 * Allocation modes:
 *   default              malloc/free.
 *   -DPRUV_RUST_ALLOCATOR arrays are allocated/freed by the Rust bindings via
 *                        extern pruv_host_alloc(len) / pruv_host_free(data, len)
 *                        (called only when len > 0), so a returned array can be
 *                        adopted by Rust Vec::from_raw_parts. This mode also
 *                        defines the no-op pruv_runtime_rust_allocator_v1, which
 *                        the bindings reference so that linking the wrong
 *                        runtime fails.
 * pruv_alloc(len, 0) does not run a fill loop: calloc(len, 8) by default, or
 * extern pruv_host_alloc_zeroed(len) in -DPRUV_RUST_ALLOCATOR mode.
 * Allocation failure or len*8 overflow: pruv_panic_arith("allocation failed").
 *
 * -DPRUV_COUNT_ALLOCS (testing; combinable with either mode): counts successful
 * allocations (len > 0) and pruv_free calls with a non-null pointer, and prints
 * "pruv-alloc-balance: <allocs> <frees>" to stderr at exit (an atexit handler
 * registered by a constructor, so the line appears even with no allocations).
 *
 * Message convention: every panic (in -DPRUV_RUST_ALLOCATOR mode first calls
 * extern pruv_host_flush(), which flushes Rust's stdout) does fflush(stdout),
 * writes the message plus a newline to stderr, then exit(101). Messages match
 * the Rust backend:
 *   pruv: index out of bounds: <i> (len <len>)
 *   pruv: arithmetic error: <detail>
 *   pruv: requires violated: <fn>: <expr>
 *   pruv: requires undefined: <detail>
 * print functions flush stdout after every call.
 */
#include <stdint.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int64_t *pruv_alloc(int64_t len, int64_t value);
int64_t *pruv_copy(const int64_t *src, int64_t len);
void pruv_free(int64_t *data, int64_t len);
void pruv_print_i64(int64_t v);
void pruv_print_bool(int64_t v);
_Noreturn void pruv_panic_oob(int64_t i, int64_t len);
_Noreturn void pruv_panic_arith(const char *detail);
_Noreturn void pruv_panic_requires(const char *fn, const char *expr);
_Noreturn void pruv_panic_undefined(const char *detail);

#ifdef PRUV_RUST_ALLOCATOR
extern int64_t *pruv_host_alloc(int64_t len);
extern void pruv_host_free(int64_t *data, int64_t len);
extern int64_t *pruv_host_alloc_zeroed(int64_t len);
extern void pruv_host_flush(void);
void pruv_runtime_rust_allocator_v1(void) {}
#define PRUV_HOST_FLUSH() pruv_host_flush()
#else
#define PRUV_HOST_FLUSH() ((void)0)
#endif

_Noreturn void pruv_panic_oob(int64_t i, int64_t len) {
    PRUV_HOST_FLUSH();
    fflush(stdout);
    fprintf(stderr, "pruv: index out of bounds: %" PRId64 " (len %" PRId64 ")\n", i, len);
    exit(101);
}

_Noreturn void pruv_panic_arith(const char *detail) {
    PRUV_HOST_FLUSH();
    fflush(stdout);
    fprintf(stderr, "pruv: arithmetic error: %s\n", detail);
    exit(101);
}

_Noreturn void pruv_panic_requires(const char *fn, const char *expr) {
    PRUV_HOST_FLUSH();
    fflush(stdout);
    fprintf(stderr, "pruv: requires violated: %s: %s\n", fn, expr);
    exit(101);
}

_Noreturn void pruv_panic_undefined(const char *detail) {
    PRUV_HOST_FLUSH();
    fflush(stdout);
    fprintf(stderr, "pruv: requires undefined: %s\n", detail);
    exit(101);
}

#ifdef PRUV_COUNT_ALLOCS
static long long pruv_n_allocs = 0;
static long long pruv_n_frees = 0;
static void pruv_report_balance(void) {
    fprintf(stderr, "pruv-alloc-balance: %lld %lld\n", pruv_n_allocs, pruv_n_frees);
}
/* registered at load time so the line is printed even with zero allocations */
__attribute__((constructor)) static void pruv_register_balance(void) {
    atexit(pruv_report_balance);
}
#endif

static int64_t *pruv_raw_alloc(int64_t len, int zeroed) {
    /* len > 0 here */
    if ((uint64_t)len > (uint64_t)INT64_MAX / 8u) pruv_panic_arith("allocation failed");
#ifdef PRUV_RUST_ALLOCATOR
    int64_t *p = zeroed ? pruv_host_alloc_zeroed(len) : pruv_host_alloc(len);
#else
    int64_t *p = zeroed ? (int64_t *)calloc((size_t)len, 8u)
                        : (int64_t *)malloc((size_t)len * 8u);
#endif
    if (!p) pruv_panic_arith("allocation failed");
#ifdef PRUV_COUNT_ALLOCS
    pruv_n_allocs++;
#endif
    return p;
}

int64_t *pruv_alloc(int64_t len, int64_t value) {
    if (len <= 0) return NULL;
    if (value == 0) return pruv_raw_alloc(len, 1);
    int64_t *p = pruv_raw_alloc(len, 0);
    for (int64_t k = 0; k < len; k++) p[k] = value;
    return p;
}

int64_t *pruv_copy(const int64_t *src, int64_t len) {
    if (len <= 0) return NULL;
    int64_t *p = pruv_raw_alloc(len, 0);
    memcpy(p, src, (size_t)len * 8u);
    return p;
}

void pruv_free(int64_t *data, int64_t len) {
#ifdef PRUV_COUNT_ALLOCS
    if (data) pruv_n_frees++;
#endif
    if (!data || len <= 0) return;
#ifdef PRUV_RUST_ALLOCATOR
    pruv_host_free(data, len);
#else
    (void)len;
    free(data);
#endif
}

void pruv_print_i64(int64_t v) {
    printf("%" PRId64 "\n", v);
    fflush(stdout);
}

void pruv_print_bool(int64_t v) {
    fputs(v ? "true\n" : "false\n", stdout);
    fflush(stdout);
}
