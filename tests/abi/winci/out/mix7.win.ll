target datalayout = "e-m:w-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-f80:128-n8:16:32:64-S128"
target triple = "x86_64-pc-windows-msvc"

@.str.0 = private unnamed_addr constant [22 x i8] c"division by zero in /\00"
@.str.1 = private unnamed_addr constant [19 x i8] c"i128 overflow in /\00"
@.str.2 = private unnamed_addr constant [22 x i8] c"division by zero in %\00"
@.str.3 = private unnamed_addr constant [19 x i8] c"i128 overflow in %\00"
@.str.4 = private unnamed_addr constant [4 x i8] c"mix\00"
@.str.5 = private unnamed_addr constant [36 x i8] c"((a >= -1000000) && (a <= 1000000))\00"
@.str.6 = private unnamed_addr constant [36 x i8] c"((b >= -1000000) && (b <= 1000000))\00"
@.str.7 = private unnamed_addr constant [36 x i8] c"((c >= -1000000) && (c <= 1000000))\00"
@.str.8 = private unnamed_addr constant [36 x i8] c"((d >= -1000000) && (d <= 1000000))\00"

declare noalias ptr @pruv_alloc(i64, i64) nounwind
declare noalias ptr @pruv_copy(ptr nocapture readonly, i64) nounwind
declare void @pruv_free(ptr nocapture, i64) nounwind
declare void @pruv_print_i64(i64) nounwind
declare void @pruv_print_bool(i64) nounwind
declare void @pruv_panic_oob(i64, i64) noreturn cold nounwind
declare void @pruv_panic_arith(ptr) noreturn cold nounwind
declare void @pruv_panic_requires(ptr, ptr) noreturn cold nounwind
declare void @pruv_panic_undefined(ptr) noreturn cold nounwind
declare { i64, i1 } @llvm.sadd.with.overflow.i64(i64, i64)
declare { i64, i1 } @llvm.ssub.with.overflow.i64(i64, i64)
declare { i64, i1 } @llvm.smul.with.overflow.i64(i64, i64)
declare { i128, i1 } @llvm.sadd.with.overflow.i128(i128, i128)
declare { i128, i1 } @llvm.ssub.with.overflow.i128(i128, i128)
declare { i128, i1 } @llvm.smul.with.overflow.i128(i128, i128)

define internal i128 @pruv_cdiv(i128 %a, i128 %b) {
entry:
  %z = icmp eq i128 %b, 0
  br i1 %z, label %dz, label %c1
dz:
  call void @pruv_panic_undefined(ptr @.str.0)
  unreachable
c1:
  %am = icmp eq i128 %a, -170141183460469231731687303715884105728
  %bm = icmp eq i128 %b, -1
  %ov = and i1 %am, %bm
  br i1 %ov, label %of, label %c2
of:
  call void @pruv_panic_undefined(ptr @.str.1)
  unreachable
c2:
  %q = sdiv i128 %a, %b
  %r = srem i128 %a, %b
  %neg = icmp slt i128 %r, 0
  %bp = icmp sgt i128 %b, 0
  %ra = add i128 %r, %b
  %rs = sub i128 %r, %b
  %r2 = select i1 %bp, i128 %ra, i128 %rs
  %rr = select i1 %neg, i128 %r2, i128 %r
  %qd = select i1 %bp, i128 -1, i128 1
  %q2 = add i128 %q, %qd
  %qq = select i1 %neg, i128 %q2, i128 %q
  ret i128 %qq
}

define internal i128 @pruv_crem(i128 %a, i128 %b) {
entry:
  %z = icmp eq i128 %b, 0
  br i1 %z, label %dz, label %c1
dz:
  call void @pruv_panic_undefined(ptr @.str.2)
  unreachable
c1:
  %am = icmp eq i128 %a, -170141183460469231731687303715884105728
  %bm = icmp eq i128 %b, -1
  %ov = and i1 %am, %bm
  br i1 %ov, label %of, label %c2
of:
  call void @pruv_panic_undefined(ptr @.str.3)
  unreachable
c2:
  %q = sdiv i128 %a, %b
  %r = srem i128 %a, %b
  %neg = icmp slt i128 %r, 0
  %bp = icmp sgt i128 %b, 0
  %ra = add i128 %r, %b
  %rs = sub i128 %r, %b
  %r2 = select i1 %bp, i128 %ra, i128 %rs
  %rr = select i1 %neg, i128 %r2, i128 %r
  %qd = select i1 %bp, i128 -1, i128 1
  %q2 = add i128 %q, %qd
  %qq = select i1 %neg, i128 %q2, i128 %q
  ret i128 %rr
}

define internal { i1, i64 } @mix__pruv_body(i64 %p.a, { i1, i64 } %p.o, i64 %p.b, i64 %p.c, i64 %p.d) {
entry:
  br label %start
start:
  %t1 = extractvalue { i1, i64 } %p.o, 0
  %t2 = extractvalue { i1, i64 } %p.o, 1
  br i1 %t1, label %armT.1, label %armF.2
armT.1:
  %t3 = insertvalue { i1, i64 } undef, i1 true, 0
  %t4 = insertvalue { i1, i64 } %t3, i64 %t2, 1
  ret { i1, i64 } %t4
armF.2:
  %t5 = add nsw i64 %p.a, %p.b
  %t6 = add nsw i64 %t5, %p.c
  %t7 = add nsw i64 %t6, %p.d
  %t8 = insertvalue { i1, i64 } undef, i1 false, 0
  %t9 = insertvalue { i1, i64 } %t8, i64 %t7, 1
  ret { i1, i64 } %t9
}

define internal { i1, i64 } @mix__pruv_entry(i64 %p.a, { i1, i64 } %p.o, i64 %p.b, i64 %p.c, i64 %p.d) {
entry:
  %req.budget = alloca i64
  br label %start
start:
  %t1 = sext i64 %p.a to i128
  %t2 = extractvalue { i1, i64 } %p.o, 0
  %t3 = extractvalue { i1, i64 } %p.o, 1
  %t4 = sext i64 %t3 to i128
  %t5 = sext i64 %p.b to i128
  %t6 = sext i64 %p.c to i128
  %t7 = sext i64 %p.d to i128
  store i64 1073741824, ptr %req.budget
  %t8 = icmp sge i128 %t1, -1000000
  br i1 %t8, label %rhs.1, label %endsc.2
rhs.1:
  %t9 = icmp sle i128 %t1, 1000000
  br label %endsc.2
endsc.2:
  %t10 = phi i1 [ false, %start ], [ %t9, %rhs.1 ]
  br i1 %t10, label %ok.3, label %fail.4
fail.4:
  call void @pruv_panic_requires(ptr @.str.4, ptr @.str.5)
  unreachable
ok.3:
  %t11 = icmp sge i128 %t5, -1000000
  br i1 %t11, label %rhs.5, label %endsc.6
rhs.5:
  %t12 = icmp sle i128 %t5, 1000000
  br label %endsc.6
endsc.6:
  %t13 = phi i1 [ false, %ok.3 ], [ %t12, %rhs.5 ]
  br i1 %t13, label %ok.7, label %fail.8
fail.8:
  call void @pruv_panic_requires(ptr @.str.4, ptr @.str.6)
  unreachable
ok.7:
  %t14 = icmp sge i128 %t6, -1000000
  br i1 %t14, label %rhs.9, label %endsc.10
rhs.9:
  %t15 = icmp sle i128 %t6, 1000000
  br label %endsc.10
endsc.10:
  %t16 = phi i1 [ false, %ok.7 ], [ %t15, %rhs.9 ]
  br i1 %t16, label %ok.11, label %fail.12
fail.12:
  call void @pruv_panic_requires(ptr @.str.4, ptr @.str.7)
  unreachable
ok.11:
  %t17 = icmp sge i128 %t7, -1000000
  br i1 %t17, label %rhs.13, label %endsc.14
rhs.13:
  %t18 = icmp sle i128 %t7, 1000000
  br label %endsc.14
endsc.14:
  %t19 = phi i1 [ false, %ok.11 ], [ %t18, %rhs.13 ]
  br i1 %t19, label %ok.15, label %fail.16
fail.16:
  call void @pruv_panic_requires(ptr @.str.4, ptr @.str.8)
  unreachable
ok.15:
  %t20 = call { i1, i64 } @mix__pruv_body(i64 %p.a, { i1, i64 } %p.o, i64 %p.b, i64 %p.c, i64 %p.d)
  ret { i1, i64 } %t20
}

define void @pruv_abi_mix(ptr sret({ i64, i64 }) align 8 %sret, i64 %a.a, i64 %a.o.t, i64 %a.o.v, i64 %a.b, i64 %a.c, i64 %a.d) {
entry:
  %c.o.t = icmp ne i64 %a.o.t, 0
  %c.o.g1 = insertvalue { i1, i64 } undef, i1 %c.o.t, 0
  %c.o.g = insertvalue { i1, i64 } %c.o.g1, i64 %a.o.v, 1
  %r = call { i1, i64 } @mix__pruv_entry(i64 %a.a, { i1, i64 } %c.o.g, i64 %a.b, i64 %a.c, i64 %a.d)
  %x0 = extractvalue { i1, i64 } %r, 0
  %x1 = extractvalue { i1, i64 } %r, 1
  %x0z = zext i1 %x0 to i64
  %sl0 = getelementptr inbounds { i64, i64 }, ptr %sret, i32 0, i32 0
  %sl1 = getelementptr inbounds { i64, i64 }, ptr %sret, i32 0, i32 1
  store i64 %x0z, ptr %sl0, align 8
  store i64 %x1, ptr %sl1, align 8
  ret void
}
