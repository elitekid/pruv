# samples

## main_i128.ll

Entry-point IR that does an i128 multiplication, signed division, and remainder (for a positive a and a negative -a), with `@main` printing the results.
a = 2^64 + 5, b = 10. Each line is the result i128 as `upper-64-bits lower-64-bits` (both unsigned decimal numbers).

```
pruvc-ir-tool obj samples/main_i128.ll -o /tmp/m.o
pruvc-ir-tool undef /tmp/m.o          # depending on the target, __multi3 / __divti3 / __modti3 may appear
pruvc-ir-tool link /tmp/m.o -o /tmp/m --runtime none
/tmp/m
```

Expected output (computed by hand; not confirmed by running it):

```
10 50
0 1844674407370955162
0 1
18446744073709551615 16602069666338596454
18446744073709551615 18446744073709551615
```

- `a*10 = 10·2^64 + 50`
- `a/10 = 1844674407370955162`, `a%10 = 1`
- `(-a)/10 = -1844674407370955162` (truncated toward 0), `(-a)%10 = -1` — shown as the complement with respect to 2^128

Exit code 0. No runtime object is needed, so it is linked with `--runtime none` (only libc's printf is used).
