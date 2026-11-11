/* Windows CI: a C caller (clang, x86_64-pc-windows-msvc) calls the sret wrapper in args_0_1_5.win.obj directly.
 * Returning a 16-byte struct lowers to a hidden sret under the C ABI, so the values only match
 * if our wrapper signature agrees with it. */
#include <stdint.h>
#include <stdio.h>

typedef struct { int64_t tag, value; } PruvTagged;

PruvTagged pruv_abi_f0(void);
PruvTagged pruv_abi_f1(int64_t);
PruvTagged pruv_abi_f5(int64_t, int64_t, int64_t, int64_t, int64_t);

static int bad = 0;

static void check(const char *name, PruvTagged got, int64_t tag, int64_t value) {
    int ok = got.tag == tag && got.value == value;
    printf("%s = (%lld, %lld) %s\n", name, (long long)got.tag, (long long)got.value, ok ? "ok" : "MISMATCH");
    if (!ok) bad = 1;
}

int main(void) {
    check("f0()", pruv_abi_f0(), 0, 0);
    check("f1(7)", pruv_abi_f1(7), 1, 7);
    check("f1(-3)", pruv_abi_f1(-3), 0, 0);
    check("f5(1,2,3,4,5)", pruv_abi_f5(1, 2, 3, 4, 5), 1, 15);
    check("f5(-1,-2,-3,-4,-5)", pruv_abi_f5(-1, -2, -3, -4, -5), 0, 0);
    check("f5(1e6 x5)", pruv_abi_f5(1000000, 1000000, 1000000, 1000000, 1000000), 1, 5000000);
    for (int64_t i = 0; i < 100000; i++) {
        PruvTagged t = pruv_abi_f1(i - 50000);
        int64_t v = i - 50000;
        if (v > 0 ? !(t.tag == 1 && t.value == v) : !(t.tag == 0 && t.value == 0)) { bad = 1; break; }
    }
    puts(bad ? "C FAIL" : "C OK");
    return bad;
}
