target datalayout = "e-m:w-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-f80:128-n8:16:32:64-S128"
target triple = "x86_64-pc-windows-msvc"

@.str.0 = private unnamed_addr constant [22 x i8] c"division by zero in /\00"
@.str.1 = private unnamed_addr constant [19 x i8] c"i128 overflow in /\00"
@.str.2 = private unnamed_addr constant [22 x i8] c"division by zero in %\00"
@.str.3 = private unnamed_addr constant [19 x i8] c"i128 overflow in %\00"
@.str.4 = private unnamed_addr constant [22 x i8] c"pruv_g3_f_4_same_1_ob\00"
@.str.5 = private unnamed_addr constant [9 x i8] c"(a == b)\00"
@.str.6 = private unnamed_addr constant [22 x i8] c"pruv_g3_f_4_same_1_rb\00"
@.str.7 = private unnamed_addr constant [9 x i8] c"same_opt\00"
@.str.8 = private unnamed_addr constant [9 x i8] c"same_res\00"

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

define internal { i1, i1 } @pruv_g3_f_4_same_1_ob__pruv_body({ i1, i1 } %p.a, { i1, i1 } %p.b) {
entry:
  br label %start
start:
  ret { i1, i1 } %p.a
}

define internal { i1, i1 } @pruv_g3_f_4_same_1_ob__pruv_entry({ i1, i1 } %p.a, { i1, i1 } %p.b) {
entry:
  %req.budget = alloca i64
  br label %start
start:
  %t1 = extractvalue { i1, i1 } %p.a, 0
  %t2 = insertvalue { i1, i1 } zeroinitializer, i1 %t1, 0
  %t3 = extractvalue { i1, i1 } %p.a, 1
  %t4 = insertvalue { i1, i1 } %t2, i1 %t3, 1
  %t5 = extractvalue { i1, i1 } %p.b, 0
  %t6 = insertvalue { i1, i1 } zeroinitializer, i1 %t5, 0
  %t7 = extractvalue { i1, i1 } %p.b, 1
  %t8 = insertvalue { i1, i1 } %t6, i1 %t7, 1
  store i64 1073741824, ptr %req.budget
  %t9 = extractvalue { i1, i1 } %t4, 0
  %t10 = extractvalue { i1, i1 } %t8, 0
  %t11 = icmp eq i1 %t9, %t10
  %t12 = extractvalue { i1, i1 } %t4, 1
  %t13 = extractvalue { i1, i1 } %t8, 1
  %t14 = icmp eq i1 %t12, %t13
  %t15 = xor i1 %t9, true
  %t16 = or i1 %t15, %t14
  %t17 = and i1 %t11, %t16
  br i1 %t17, label %ok.1, label %fail.2
fail.2:
  call void @pruv_panic_requires(ptr @.str.4, ptr @.str.5)
  unreachable
ok.1:
  %t18 = call { i1, i1 } @pruv_g3_f_4_same_1_ob__pruv_body({ i1, i1 } %p.a, { i1, i1 } %p.b)
  ret { i1, i1 } %t18
}

define internal { i1, i1, i64 } @pruv_g3_f_4_same_1_rb__pruv_body({ i1, i1, i64 } %p.a, { i1, i1, i64 } %p.b) {
entry:
  br label %start
start:
  ret { i1, i1, i64 } %p.a
}

define internal { i1, i1, i64 } @pruv_g3_f_4_same_1_rb__pruv_entry({ i1, i1, i64 } %p.a, { i1, i1, i64 } %p.b) {
entry:
  %req.budget = alloca i64
  br label %start
start:
  %t1 = extractvalue { i1, i1, i64 } %p.a, 0
  %t2 = insertvalue { i1, i1, i128 } zeroinitializer, i1 %t1, 0
  %t3 = extractvalue { i1, i1, i64 } %p.a, 1
  %t4 = insertvalue { i1, i1, i128 } %t2, i1 %t3, 1
  %t5 = extractvalue { i1, i1, i64 } %p.a, 2
  %t6 = sext i64 %t5 to i128
  %t7 = insertvalue { i1, i1, i128 } %t4, i128 %t6, 2
  %t8 = extractvalue { i1, i1, i64 } %p.b, 0
  %t9 = insertvalue { i1, i1, i128 } zeroinitializer, i1 %t8, 0
  %t10 = extractvalue { i1, i1, i64 } %p.b, 1
  %t11 = insertvalue { i1, i1, i128 } %t9, i1 %t10, 1
  %t12 = extractvalue { i1, i1, i64 } %p.b, 2
  %t13 = sext i64 %t12 to i128
  %t14 = insertvalue { i1, i1, i128 } %t11, i128 %t13, 2
  store i64 1073741824, ptr %req.budget
  %t15 = extractvalue { i1, i1, i128 } %t7, 0
  %t16 = extractvalue { i1, i1, i128 } %t14, 0
  %t17 = icmp eq i1 %t15, %t16
  %t18 = extractvalue { i1, i1, i128 } %t7, 1
  %t19 = extractvalue { i1, i1, i128 } %t14, 1
  %t20 = icmp eq i1 %t18, %t19
  %t21 = xor i1 %t15, true
  %t22 = extractvalue { i1, i1, i128 } %t7, 2
  %t23 = extractvalue { i1, i1, i128 } %t14, 2
  %t24 = icmp eq i128 %t22, %t23
  %t25 = and i1 %t15, %t20
  %t26 = and i1 %t21, %t24
  %t27 = or i1 %t25, %t26
  %t28 = and i1 %t17, %t27
  br i1 %t28, label %ok.1, label %fail.2
fail.2:
  call void @pruv_panic_requires(ptr @.str.6, ptr @.str.5)
  unreachable
ok.1:
  %t29 = call { i1, i1, i64 } @pruv_g3_f_4_same_1_rb__pruv_body({ i1, i1, i64 } %p.a, { i1, i1, i64 } %p.b)
  ret { i1, i1, i64 } %t29
}

define internal { i1, i1 } @same_opt__pruv_body({ i1, i1 } %p.a, { i1, i1 } %p.b) {
entry:
  br label %start
start:
  %t1 = call { i1, i1 } @pruv_g3_f_4_same_1_ob__pruv_body({ i1, i1 } %p.a, { i1, i1 } %p.b)
  ret { i1, i1 } %t1
}

define internal { i1, i1 } @same_opt__pruv_entry({ i1, i1 } %p.a, { i1, i1 } %p.b) {
entry:
  %req.budget = alloca i64
  br label %start
start:
  %t1 = extractvalue { i1, i1 } %p.a, 0
  %t2 = insertvalue { i1, i1 } zeroinitializer, i1 %t1, 0
  %t3 = extractvalue { i1, i1 } %p.a, 1
  %t4 = insertvalue { i1, i1 } %t2, i1 %t3, 1
  %t5 = extractvalue { i1, i1 } %p.b, 0
  %t6 = insertvalue { i1, i1 } zeroinitializer, i1 %t5, 0
  %t7 = extractvalue { i1, i1 } %p.b, 1
  %t8 = insertvalue { i1, i1 } %t6, i1 %t7, 1
  store i64 1073741824, ptr %req.budget
  %t9 = extractvalue { i1, i1 } %t4, 0
  %t10 = extractvalue { i1, i1 } %t8, 0
  %t11 = icmp eq i1 %t9, %t10
  %t12 = extractvalue { i1, i1 } %t4, 1
  %t13 = extractvalue { i1, i1 } %t8, 1
  %t14 = icmp eq i1 %t12, %t13
  %t15 = xor i1 %t9, true
  %t16 = or i1 %t15, %t14
  %t17 = and i1 %t11, %t16
  br i1 %t17, label %ok.1, label %fail.2
fail.2:
  call void @pruv_panic_requires(ptr @.str.7, ptr @.str.5)
  unreachable
ok.1:
  %t18 = call { i1, i1 } @same_opt__pruv_body({ i1, i1 } %p.a, { i1, i1 } %p.b)
  ret { i1, i1 } %t18
}

define void @pruv_abi_same_opt(ptr %a.a, ptr %a.b, ptr %out) {
entry:
  %w.1 = getelementptr inbounds i64, ptr %a.a, i64 0
  %w.2 = load i64, ptr %w.1
  %w.3 = icmp ne i64 %w.2, 0
  %w.4 = getelementptr inbounds i64, ptr %a.a, i64 1
  %w.5 = load i64, ptr %w.4
  %w.6 = icmp ne i64 %w.5, 0
  %w.7 = and i1 %w.3, %w.6
  %w.8 = insertvalue { i1, i1 } zeroinitializer, i1 %w.3, 0
  %w.9 = insertvalue { i1, i1 } %w.8, i1 %w.7, 1
  %w.10 = getelementptr inbounds i64, ptr %a.b, i64 0
  %w.11 = load i64, ptr %w.10
  %w.12 = icmp ne i64 %w.11, 0
  %w.13 = getelementptr inbounds i64, ptr %a.b, i64 1
  %w.14 = load i64, ptr %w.13
  %w.15 = icmp ne i64 %w.14, 0
  %w.16 = and i1 %w.12, %w.15
  %w.17 = insertvalue { i1, i1 } zeroinitializer, i1 %w.12, 0
  %w.18 = insertvalue { i1, i1 } %w.17, i1 %w.16, 1
  %r = call { i1, i1 } @same_opt__pruv_entry({ i1, i1 } %w.9, { i1, i1 } %w.18)
  %w.19 = extractvalue { i1, i1 } %r, 0
  %w.20 = zext i1 %w.19 to i64
  %w.21 = getelementptr inbounds i64, ptr %out, i64 0
  store i64 %w.20, ptr %w.21
  %w.22 = extractvalue { i1, i1 } %r, 1
  %w.23 = and i1 %w.19, %w.22
  %w.24 = zext i1 %w.23 to i64
  %w.25 = getelementptr inbounds i64, ptr %out, i64 1
  store i64 %w.24, ptr %w.25
  ret void
}

define internal { i1, i1, i64 } @same_res__pruv_body({ i1, i1, i64 } %p.a, { i1, i1, i64 } %p.b) {
entry:
  br label %start
start:
  %t1 = call { i1, i1, i64 } @pruv_g3_f_4_same_1_rb__pruv_body({ i1, i1, i64 } %p.a, { i1, i1, i64 } %p.b)
  ret { i1, i1, i64 } %t1
}

define internal { i1, i1, i64 } @same_res__pruv_entry({ i1, i1, i64 } %p.a, { i1, i1, i64 } %p.b) {
entry:
  %req.budget = alloca i64
  br label %start
start:
  %t1 = extractvalue { i1, i1, i64 } %p.a, 0
  %t2 = insertvalue { i1, i1, i128 } zeroinitializer, i1 %t1, 0
  %t3 = extractvalue { i1, i1, i64 } %p.a, 1
  %t4 = insertvalue { i1, i1, i128 } %t2, i1 %t3, 1
  %t5 = extractvalue { i1, i1, i64 } %p.a, 2
  %t6 = sext i64 %t5 to i128
  %t7 = insertvalue { i1, i1, i128 } %t4, i128 %t6, 2
  %t8 = extractvalue { i1, i1, i64 } %p.b, 0
  %t9 = insertvalue { i1, i1, i128 } zeroinitializer, i1 %t8, 0
  %t10 = extractvalue { i1, i1, i64 } %p.b, 1
  %t11 = insertvalue { i1, i1, i128 } %t9, i1 %t10, 1
  %t12 = extractvalue { i1, i1, i64 } %p.b, 2
  %t13 = sext i64 %t12 to i128
  %t14 = insertvalue { i1, i1, i128 } %t11, i128 %t13, 2
  store i64 1073741824, ptr %req.budget
  %t15 = extractvalue { i1, i1, i128 } %t7, 0
  %t16 = extractvalue { i1, i1, i128 } %t14, 0
  %t17 = icmp eq i1 %t15, %t16
  %t18 = extractvalue { i1, i1, i128 } %t7, 1
  %t19 = extractvalue { i1, i1, i128 } %t14, 1
  %t20 = icmp eq i1 %t18, %t19
  %t21 = xor i1 %t15, true
  %t22 = extractvalue { i1, i1, i128 } %t7, 2
  %t23 = extractvalue { i1, i1, i128 } %t14, 2
  %t24 = icmp eq i128 %t22, %t23
  %t25 = and i1 %t15, %t20
  %t26 = and i1 %t21, %t24
  %t27 = or i1 %t25, %t26
  %t28 = and i1 %t17, %t27
  br i1 %t28, label %ok.1, label %fail.2
fail.2:
  call void @pruv_panic_requires(ptr @.str.8, ptr @.str.5)
  unreachable
ok.1:
  %t29 = call { i1, i1, i64 } @same_res__pruv_body({ i1, i1, i64 } %p.a, { i1, i1, i64 } %p.b)
  ret { i1, i1, i64 } %t29
}

define void @pruv_abi_same_res(ptr %a.a, ptr %a.b, ptr %out) {
entry:
  %w.1 = getelementptr inbounds i64, ptr %a.a, i64 0
  %w.2 = load i64, ptr %w.1
  %w.3 = icmp ne i64 %w.2, 0
  %w.4 = getelementptr inbounds i64, ptr %a.a, i64 1
  %w.5 = load i64, ptr %w.4
  %w.6 = icmp ne i64 %w.5, 0
  %w.7 = and i1 %w.3, %w.6
  %w.8 = insertvalue { i1, i1, i64 } zeroinitializer, i1 %w.3, 0
  %w.9 = insertvalue { i1, i1, i64 } %w.8, i1 %w.7, 1
  %w.10 = getelementptr inbounds i64, ptr %a.a, i64 2
  %w.11 = load i64, ptr %w.10
  %w.12 = xor i1 %w.3, true
  %w.13 = select i1 %w.12, i64 %w.11, i64 0
  %w.14 = insertvalue { i1, i1, i64 } %w.9, i64 %w.13, 2
  %w.15 = getelementptr inbounds i64, ptr %a.b, i64 0
  %w.16 = load i64, ptr %w.15
  %w.17 = icmp ne i64 %w.16, 0
  %w.18 = getelementptr inbounds i64, ptr %a.b, i64 1
  %w.19 = load i64, ptr %w.18
  %w.20 = icmp ne i64 %w.19, 0
  %w.21 = and i1 %w.17, %w.20
  %w.22 = insertvalue { i1, i1, i64 } zeroinitializer, i1 %w.17, 0
  %w.23 = insertvalue { i1, i1, i64 } %w.22, i1 %w.21, 1
  %w.24 = getelementptr inbounds i64, ptr %a.b, i64 2
  %w.25 = load i64, ptr %w.24
  %w.26 = xor i1 %w.17, true
  %w.27 = select i1 %w.26, i64 %w.25, i64 0
  %w.28 = insertvalue { i1, i1, i64 } %w.23, i64 %w.27, 2
  %r = call { i1, i1, i64 } @same_res__pruv_entry({ i1, i1, i64 } %w.14, { i1, i1, i64 } %w.28)
  %w.29 = extractvalue { i1, i1, i64 } %r, 0
  %w.30 = zext i1 %w.29 to i64
  %w.31 = getelementptr inbounds i64, ptr %out, i64 0
  store i64 %w.30, ptr %w.31
  %w.32 = extractvalue { i1, i1, i64 } %r, 1
  %w.33 = and i1 %w.29, %w.32
  %w.34 = zext i1 %w.33 to i64
  %w.35 = getelementptr inbounds i64, ptr %out, i64 1
  store i64 %w.34, ptr %w.35
  %w.36 = extractvalue { i1, i1, i64 } %r, 2
  %w.37 = xor i1 %w.29, true
  %w.38 = select i1 %w.37, i64 %w.36, i64 0
  %w.39 = getelementptr inbounds i64, ptr %out, i64 2
  store i64 %w.38, ptr %w.39
  ret void
}
