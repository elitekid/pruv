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
 *
 * v2 (u8 arrays, G2 A4): pruv_alloc_u8(len, value), pruv_copy_v2(src, len, size,
 * align) and pruv_free_v2(data, len, size, align) handle element sizes 1, 4, 8
 * (size == align). In -DPRUV_RUST_ALLOCATOR mode they call the extern v2 host
 * helpers pruv_host_alloc_v2 / pruv_host_alloc_zeroed_v2 / pruv_host_free_v2 and
 * the runtime defines the no-op marker pruv_runtime_rust_allocator_v2, which
 * the bindings reference; a v1 runtime with v2 bindings, or v1 bindings with
 * this runtime, fails to link. The v1 helpers and marker are unchanged.
 * pruv_panic_elem(v, range) prints
 *   pruv: element out of range: <v> (<range>)
 * and exits 101 like the other panics.
 * pruv_panic_repr(v, what) (G2 A5) prints
 *   pruv: invalid representation: <v> (<what>)
 * and exits 101; pruv_check_bool(data, len) (G2 A5) calls it for the first byte
 * of a [bool] array that is not 0 or 1 (raw ABI entry check).
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
void *pruv_alloc_u8(int64_t len, int64_t value);
void *pruv_copy_v2(const void *src, int64_t len, int64_t size, int64_t align);
void pruv_free_v2(void *data, int64_t len, int64_t size, int64_t align);
_Noreturn void pruv_panic_elem(int64_t v, const char *range);
_Noreturn void pruv_panic_repr(int64_t v, const char *what);

#ifdef PRUV_RUST_ALLOCATOR
extern int64_t *pruv_host_alloc(int64_t len);
extern void pruv_host_free(int64_t *data, int64_t len);
extern int64_t *pruv_host_alloc_zeroed(int64_t len);
extern void pruv_host_flush(void);
void pruv_runtime_rust_allocator_v1(void) {}
extern void *pruv_host_alloc_v2(int64_t len, int64_t size, int64_t align);
extern void *pruv_host_alloc_zeroed_v2(int64_t len, int64_t size, int64_t align);
extern void pruv_host_free_v2(void *data, int64_t len, int64_t size, int64_t align);
void pruv_runtime_rust_allocator_v2(void) {}
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

_Noreturn void pruv_panic_elem(int64_t v, const char *range) {
    PRUV_HOST_FLUSH();
    fflush(stdout);
    fprintf(stderr, "pruv: element out of range: %" PRId64 " (%s)\n", v, range);
    exit(101);
}

/* G2 A5 */
_Noreturn void pruv_panic_repr(int64_t v, const char *what) {
    PRUV_HOST_FLUSH();
    fflush(stdout);
    fprintf(stderr, "pruv: invalid representation: %" PRId64 " (%s)\n", v, what);
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

#define PRUV_MAX_LEN ((uint64_t)1 << 40)

static int pruv_layout_ok(int64_t size, int64_t align) {
    return (size == 1 && align == 1) || (size == 4 && align == 4) || (size == 8 && align == 8);
}

static void *pruv_raw_alloc_v2(int64_t len, int64_t size, int64_t align, int zeroed) {
    /* len > 0 here; every check comes before the multiplication */
    if (!pruv_layout_ok(size, align)) pruv_panic_arith("invalid element layout");
    if ((uint64_t)len > PRUV_MAX_LEN) pruv_panic_arith("allocation failed");
    if ((uint64_t)len > (uint64_t)SIZE_MAX / (uint64_t)size) pruv_panic_arith("allocation failed");
#ifdef PRUV_RUST_ALLOCATOR
    void *p = zeroed ? pruv_host_alloc_zeroed_v2(len, size, align) : pruv_host_alloc_v2(len, size, align);
#else
    void *p = zeroed ? calloc((size_t)len, (size_t)size) : malloc((size_t)len * (size_t)size);
#endif
    if (!p) pruv_panic_arith("allocation failed");
#ifdef PRUV_COUNT_ALLOCS
    pruv_n_allocs++;
#endif
    return p;
}

void *pruv_alloc_u8(int64_t len, int64_t value) {
    /* value is already in 0..=255: proved (proof mode) or checked by the caller (safe mode) */
    if (len <= 0) return NULL;
    if (value == 0) return pruv_raw_alloc_v2(len, 1, 1, 1);
    uint8_t *p = (uint8_t *)pruv_raw_alloc_v2(len, 1, 1, 0);
    memset(p, (int)(uint8_t)value, (size_t)len);
    return p;
}

void *pruv_copy_v2(const void *src, int64_t len, int64_t size, int64_t align) {
    if (len <= 0) return NULL;
    void *p = pruv_raw_alloc_v2(len, size, align, 0);
    memcpy(p, src, (size_t)len * (size_t)size);
    return p;
}

void pruv_free_v2(void *data, int64_t len, int64_t size, int64_t align) {
#ifdef PRUV_COUNT_ALLOCS
    if (data) pruv_n_frees++;
#endif
    if (!data || len <= 0) return;
#ifdef PRUV_RUST_ALLOCATOR
    pruv_host_free_v2(data, len, size, align);
#else
    (void)len;
    (void)size;
    (void)align;
    free(data);
#endif
}

/* G2 A5 */
void pruv_check_bool(const uint8_t *data, int64_t len) {
    if (data == NULL || len <= 0)
        return;
    for (int64_t k = 0; k < len; k++)
        if (data[k] > 1)
            pruv_panic_repr((int64_t)data[k], "bool 0..=1");
}

void pruv_print_i64(int64_t v) {
    printf("%" PRId64 "\n", v);
    fflush(stdout);
}

void pruv_print_bool(int64_t v) {
    fputs(v ? "true\n" : "false\n", stdout);
    fflush(stdout);
}
