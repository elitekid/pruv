/* Windows CI: C 호출자 (clang, x86_64-pc-windows-msvc) 가 args_0_1_5.win.obj 의 sret wrapper 를 직접 부른다.
 * 16바이트 구조체 반환은 C ABI 상 숨은 sret 로 하강하므로, 우리 wrapper 서명과 맞아야 값이 맞는다. */
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
