; i128 mul / sdiv / srem with a C-visible @main (LLVM 22 opaque-pointer syntax).
; No triple or datalayout on purpose: pruvc-ir-tool supplies the target's.
; The operations are in noinline external functions so O2 cannot fold them away
; and the i128 compiler-rt helpers (__multi3, __divti3, __modti3) stay as calls
; on targets that lack native 128-bit instructions.

@fmt = private unnamed_addr constant [11 x i8] c"%llu %llu\0A\00"

declare i32 @printf(ptr, ...)

define i128 @mul128(i128 %a, i128 %b) noinline {
entry:
  %r = mul i128 %a, %b
  ret i128 %r
}

define i128 @sdiv128(i128 %a, i128 %b) noinline {
entry:
  %r = sdiv i128 %a, %b
  ret i128 %r
}

define i128 @srem128(i128 %a, i128 %b) noinline {
entry:
  %r = srem i128 %a, %b
  ret i128 %r
}

; prints "<high 64 bits> <low 64 bits>" of an i128, both unsigned
define void @show(i128 %v) noinline {
entry:
  %lo = trunc i128 %v to i64
  %sh = lshr i128 %v, 64
  %hi = trunc i128 %sh to i64
  %c = call i32 (ptr, ...) @printf(ptr @fmt, i64 %hi, i64 %lo)
  ret void
}

define i32 @main() {
entry:
  ; a = 2^64 + 5, b = 10
  %a = add i128 18446744073709551616, 5
  %na = sub i128 0, %a
  %m = call i128 @mul128(i128 %a, i128 10)
  call void @show(i128 %m)
  %d = call i128 @sdiv128(i128 %a, i128 10)
  call void @show(i128 %d)
  %r = call i128 @srem128(i128 %a, i128 10)
  call void @show(i128 %r)
  %dn = call i128 @sdiv128(i128 %na, i128 10)
  call void @show(i128 %dn)
  %rn = call i128 @srem128(i128 %na, i128 10)
  call void @show(i128 %rn)
  ret i32 0
}
