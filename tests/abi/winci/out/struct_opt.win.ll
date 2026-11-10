target datalayout = "e-m:w-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-f80:128-n8:16:32:64-S128"
target triple = "x86_64-pc-windows-msvc"

@.str.0 = private unnamed_addr constant [22 x i8] c"division by zero in /\00"
@.str.1 = private unnamed_addr constant [19 x i8] c"i128 overflow in /\00"
@.str.2 = private unnamed_addr constant [22 x i8] c"division by zero in %\00"
@.str.3 = private unnamed_addr constant [19 x i8] c"i128 overflow in %\00"
@.str.4 = private unnamed_addr constant [5 x i8] c"bump\00"
@.str.5 = private unnamed_addr constant [26 x i8] c"((d >= 0) && (d <= 1000))\00"
@.str.6 = private unnamed_addr constant [30 x i8] c"((c.n >= 0) && (c.n <= 1000))\00"

%pruv_t_Cell = type { { i1, i64 }, i64 }
%pruv_c_Cell = type { { i1, i128 }, i128 }

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

define internal %pruv_t_Cell @bump__pruv_body(%pruv_t_Cell %p.c, i64 %p.d) {
entry:
  %l0.q.a = alloca %pruv_t_Cell
  br label %start
start:
  store %pruv_t_Cell %p.c, ptr %l0.q.a
  %t1 = load %pruv_t_Cell, ptr %l0.q.a
  %t2 = extractvalue %pruv_t_Cell %t1, 1
  %t3 = add nsw i64 %t2, %p.d
  %t4 = load %pruv_t_Cell, ptr %l0.q.a
  %t5 = insertvalue %pruv_t_Cell %t4, i64 %t3, 1
  store %pruv_t_Cell %t5, ptr %l0.q.a
  %t6 = load %pruv_t_Cell, ptr %l0.q.a
  ret %pruv_t_Cell %t6
}

define internal %pruv_t_Cell @bump__pruv_entry(%pruv_t_Cell %p.c, i64 %p.d) {
entry:
  %req.budget = alloca i64
  br label %start
start:
  %t1 = extractvalue %pruv_t_Cell %p.c, 0
  %t2 = extractvalue { i1, i64 } %t1, 0
  %t3 = extractvalue { i1, i64 } %t1, 1
  %t4 = sext i64 %t3 to i128
  %t5 = insertvalue { i1, i128 } undef, i1 %t2, 0
  %t6 = insertvalue { i1, i128 } %t5, i128 %t4, 1
  %t7 = insertvalue %pruv_c_Cell zeroinitializer, { i1, i128 } %t6, 0
  %t8 = extractvalue %pruv_t_Cell %p.c, 1
  %t9 = sext i64 %t8 to i128
  %t10 = insertvalue %pruv_c_Cell %t7, i128 %t9, 1
  %t11 = sext i64 %p.d to i128
  store i64 1073741824, ptr %req.budget
  %t12 = icmp sge i128 %t11, 0
  br i1 %t12, label %rhs.1, label %endsc.2
rhs.1:
  %t13 = icmp sle i128 %t11, 1000
  br label %endsc.2
endsc.2:
  %t14 = phi i1 [ false, %start ], [ %t13, %rhs.1 ]
  br i1 %t14, label %ok.3, label %fail.4
fail.4:
  call void @pruv_panic_requires(ptr @.str.4, ptr @.str.5)
  unreachable
ok.3:
  %t15 = extractvalue %pruv_c_Cell %t10, 1
  %t16 = icmp sge i128 %t15, 0
  br i1 %t16, label %rhs.5, label %endsc.6
rhs.5:
  %t17 = extractvalue %pruv_c_Cell %t10, 1
  %t18 = icmp sle i128 %t17, 1000
  br label %endsc.6
endsc.6:
  %t19 = phi i1 [ false, %ok.3 ], [ %t18, %rhs.5 ]
  br i1 %t19, label %ok.7, label %fail.8
fail.8:
  call void @pruv_panic_requires(ptr @.str.4, ptr @.str.6)
  unreachable
ok.7:
  %t20 = call %pruv_t_Cell @bump__pruv_body(%pruv_t_Cell %p.c, i64 %p.d)
  ret %pruv_t_Cell %t20
}

define void @pruv_abi_bump(ptr %a.c, i64 %a.d, ptr %out) {
entry:
  %w.1 = getelementptr inbounds i64, ptr %a.c, i64 0
  %w.2 = load i64, ptr %w.1
  %w.3 = icmp ne i64 %w.2, 0
  %w.4 = getelementptr inbounds i64, ptr %a.c, i64 1
  %w.5 = load i64, ptr %w.4
  %w.6 = insertvalue { i1, i64 } undef, i1 %w.3, 0
  %w.7 = insertvalue { i1, i64 } %w.6, i64 %w.5, 1
  %w.8 = insertvalue %pruv_t_Cell zeroinitializer, { i1, i64 } %w.7, 0
  %w.9 = getelementptr inbounds i64, ptr %a.c, i64 2
  %w.10 = load i64, ptr %w.9
  %w.11 = insertvalue %pruv_t_Cell %w.8, i64 %w.10, 1
  %r = call %pruv_t_Cell @bump__pruv_entry(%pruv_t_Cell %w.11, i64 %a.d)
  %w.12 = extractvalue %pruv_t_Cell %r, 0
  %w.13 = extractvalue { i1, i64 } %w.12, 0
  %w.14 = extractvalue { i1, i64 } %w.12, 1
  %w.15 = select i1 %w.13, i64 %w.14, i64 0
  %w.16 = zext i1 %w.13 to i64
  %w.17 = getelementptr inbounds i64, ptr %out, i64 0
  store i64 %w.16, ptr %w.17
  %w.18 = getelementptr inbounds i64, ptr %out, i64 1
  store i64 %w.15, ptr %w.18
  %w.19 = extractvalue %pruv_t_Cell %r, 1
  %w.20 = getelementptr inbounds i64, ptr %out, i64 2
  store i64 %w.19, ptr %w.20
  ret void
}
