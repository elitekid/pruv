target datalayout = "e-m:w-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-f80:128-n8:16:32:64-S128"
target triple = "x86_64-pc-windows-msvc"

@.str.0 = private unnamed_addr constant [22 x i8] c"division by zero in /\00"
@.str.1 = private unnamed_addr constant [19 x i8] c"i128 overflow in /\00"
@.str.2 = private unnamed_addr constant [22 x i8] c"division by zero in %\00"
@.str.3 = private unnamed_addr constant [19 x i8] c"i128 overflow in %\00"
@.str.4 = private unnamed_addr constant [22 x i8] c"pruv_g3_f_5_first_1_b\00"
@.str.5 = private unnamed_addr constant [13 x i8] c"(len(a) > 0)\00"
@.str.6 = private unnamed_addr constant [11 x i8] c"first_bool\00"
@.str.7 = private unnamed_addr constant [21 x i8] c"pruv_g3_f_4_fill_1_b\00"
@.str.8 = private unnamed_addr constant [25 x i8] c"((0 <= n) && (n <= 100))\00"
@.str.9 = private unnamed_addr constant [10 x i8] c"fill_bool\00"

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
declare noalias ptr @pruv_alloc_u8(i64, i64) nounwind
declare noalias ptr @pruv_copy_v2(ptr nocapture readonly, i64, i64, i64) nounwind
declare void @pruv_free_v2(ptr nocapture, i64, i64, i64) nounwind
declare void @pruv_panic_elem(i64, ptr) noreturn cold nounwind
declare void @pruv_check_bool(ptr nocapture readonly, i64) nounwind

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

define internal i1 @pruv_g3_f_5_first_1_b__pruv_body(ptr noalias nocapture readonly %p.a.a, i64 %p.a.n) {
entry:
  br label %start
start:
  %t1 = getelementptr inbounds i8, ptr %p.a.a, i64 0
  %t2 = load i8, ptr %t1
  %t3 = icmp ne i8 %t2, 0
  ret i1 %t3
}

define internal i1 @pruv_g3_f_5_first_1_b__pruv_entry(ptr noalias nocapture readonly %p.a.a, i64 %p.a.n) {
entry:
  %req.budget = alloca i64
  br label %start
start:
  store i64 1073741824, ptr %req.budget
  %t1 = zext i64 %p.a.n to i128
  %t2 = icmp sgt i128 %t1, 0
  br i1 %t2, label %ok.1, label %fail.2
fail.2:
  call void @pruv_panic_requires(ptr @.str.4, ptr @.str.5)
  unreachable
ok.1:
  %t3 = call i1 @pruv_g3_f_5_first_1_b__pruv_body(ptr %p.a.a, i64 %p.a.n)
  ret i1 %t3
}

define internal i1 @first_bool__pruv_body(ptr noalias nocapture readonly %p.a.a, i64 %p.a.n) {
entry:
  br label %start
start:
  %t1 = call i1 @pruv_g3_f_5_first_1_b__pruv_body(ptr %p.a.a, i64 %p.a.n)
  ret i1 %t1
}

define internal i1 @first_bool__pruv_entry(ptr noalias nocapture readonly %p.a.a, i64 %p.a.n) {
entry:
  %req.budget = alloca i64
  br label %start
start:
  store i64 1073741824, ptr %req.budget
  %t1 = zext i64 %p.a.n to i128
  %t2 = icmp sgt i128 %t1, 0
  br i1 %t2, label %ok.1, label %fail.2
fail.2:
  call void @pruv_panic_requires(ptr @.str.6, ptr @.str.5)
  unreachable
ok.1:
  %t3 = call i1 @first_bool__pruv_body(ptr %p.a.a, i64 %p.a.n)
  ret i1 %t3
}

define i64 @pruv_abi_first_bool(ptr %a.a.a, i64 %a.a.n) {
entry:
  call void @pruv_check_bool(ptr %a.a.a, i64 %a.a.n)
  %r = call i1 @first_bool__pruv_entry(ptr %a.a.a, i64 %a.a.n)
  %rz = zext i1 %r to i64
  ret i64 %rz
}

define i64 @pruv_abi_first_bool__typed(ptr %a.a.a, i64 %a.a.n) {
entry:
  %r = call i1 @first_bool__pruv_entry(ptr %a.a.a, i64 %a.a.n)
  %rz = zext i1 %r to i64
  ret i64 %rz
}

define internal { i1, i1 } @head_opt__pruv_body(ptr noalias nocapture readonly %p.a.a, i64 %p.a.n) {
entry:
  br label %start
start:
  %t1 = icmp sgt i64 %p.a.n, 0
  br i1 %t1, label %then.1, label %endif.2
then.1:
  %t2 = getelementptr inbounds i8, ptr %p.a.a, i64 0
  %t3 = load i8, ptr %t2
  %t4 = icmp ne i8 %t3, 0
  %t5 = insertvalue { i1, i1 } zeroinitializer, i1 true, 0
  %t6 = insertvalue { i1, i1 } %t5, i1 %t4, 1
  ret { i1, i1 } %t6
endif.2:
  ret { i1, i1 } zeroinitializer
}

define internal { i1, i1 } @head_opt__pruv_entry(ptr noalias nocapture readonly %p.a.a, i64 %p.a.n) {
entry:
  br label %start
start:
  %t1 = call { i1, i1 } @head_opt__pruv_body(ptr %p.a.a, i64 %p.a.n)
  ret { i1, i1 } %t1
}

define void @pruv_abi_head_opt(ptr %a.a.a, i64 %a.a.n, ptr %out) {
entry:
  call void @pruv_check_bool(ptr %a.a.a, i64 %a.a.n)
  %r = call { i1, i1 } @head_opt__pruv_entry(ptr %a.a.a, i64 %a.a.n)
  %w.1 = extractvalue { i1, i1 } %r, 0
  %w.2 = zext i1 %w.1 to i64
  %w.3 = getelementptr inbounds i64, ptr %out, i64 0
  store i64 %w.2, ptr %w.3
  %w.4 = extractvalue { i1, i1 } %r, 1
  %w.5 = and i1 %w.1, %w.4
  %w.6 = zext i1 %w.5 to i64
  %w.7 = getelementptr inbounds i64, ptr %out, i64 1
  store i64 %w.6, ptr %w.7
  ret void
}

define void @pruv_abi_head_opt__typed(ptr %a.a.a, i64 %a.a.n, ptr %out) {
entry:
  %r = call { i1, i1 } @head_opt__pruv_entry(ptr %a.a.a, i64 %a.a.n)
  %w.1 = extractvalue { i1, i1 } %r, 0
  %w.2 = zext i1 %w.1 to i64
  %w.3 = getelementptr inbounds i64, ptr %out, i64 0
  store i64 %w.2, ptr %w.3
  %w.4 = extractvalue { i1, i1 } %r, 1
  %w.5 = and i1 %w.1, %w.4
  %w.6 = zext i1 %w.5 to i64
  %w.7 = getelementptr inbounds i64, ptr %out, i64 1
  store i64 %w.6, ptr %w.7
  ret void
}

define internal { ptr, i64 } @pruv_g3_f_4_fill_1_b__pruv_body(i64 %p.n, i1 %p.v) {
entry:
  %l0.out.a = alloca ptr
  %l0.out.b = alloca i64
  %l1.i.a = alloca i64
  br label %start
start:
  %t1 = zext i1 %p.v to i64
  %t2 = call ptr @pruv_alloc_u8(i64 %p.n, i64 %t1)
  store ptr %t2, ptr %l0.out.a
  store i64 %p.n, ptr %l0.out.b
  store i64 0, ptr %l1.i.a
  br label %wcond.1
wcond.1:
  %t3 = load i64, ptr %l1.i.a
  %t4 = icmp slt i64 %t3, %p.n
  br i1 %t4, label %wbody.2, label %wend.3
wbody.2:
  %t5 = load i64, ptr %l1.i.a
  %t6 = load ptr, ptr %l0.out.a
  %t7 = load i64, ptr %l0.out.b
  %t8 = getelementptr inbounds i8, ptr %t6, i64 %t5
  %t9 = zext i1 %p.v to i8
  store i8 %t9, ptr %t8
  %t10 = load i64, ptr %l1.i.a
  %t11 = add nsw i64 %t10, 1
  store i64 %t11, ptr %l1.i.a
  br label %wcond.1
wend.3:
  %t12 = load ptr, ptr %l0.out.a
  %t13 = load i64, ptr %l0.out.b
  store ptr null, ptr %l0.out.a
  store i64 0, ptr %l0.out.b
  %t14 = load ptr, ptr %l0.out.a
  %t15 = load i64, ptr %l0.out.b
  call void @pruv_free_v2(ptr %t14, i64 %t15, i64 1, i64 1)
  %t16 = insertvalue { ptr, i64 } undef, ptr %t12, 0
  %t17 = insertvalue { ptr, i64 } %t16, i64 %t13, 1
  ret { ptr, i64 } %t17
}

define internal { ptr, i64 } @pruv_g3_f_4_fill_1_b__pruv_entry(i64 %p.n, i1 %p.v) {
entry:
  %req.budget = alloca i64
  br label %start
start:
  %t1 = sext i64 %p.n to i128
  store i64 1073741824, ptr %req.budget
  %t2 = icmp sle i128 0, %t1
  br i1 %t2, label %rhs.1, label %endsc.2
rhs.1:
  %t3 = icmp sle i128 %t1, 100
  br label %endsc.2
endsc.2:
  %t4 = phi i1 [ false, %start ], [ %t3, %rhs.1 ]
  br i1 %t4, label %ok.3, label %fail.4
fail.4:
  call void @pruv_panic_requires(ptr @.str.7, ptr @.str.8)
  unreachable
ok.3:
  %t5 = call { ptr, i64 } @pruv_g3_f_4_fill_1_b__pruv_body(i64 %p.n, i1 %p.v)
  ret { ptr, i64 } %t5
}

define internal { ptr, i64 } @fill_bool__pruv_body(i64 %p.n, i1 %p.v) {
entry:
  %l0.out.a = alloca ptr
  %l0.out.b = alloca i64
  br label %start
start:
  %t1 = call { ptr, i64 } @pruv_g3_f_4_fill_1_b__pruv_body(i64 %p.n, i1 %p.v)
  %t2 = extractvalue { ptr, i64 } %t1, 0
  %t3 = extractvalue { ptr, i64 } %t1, 1
  store ptr %t2, ptr %l0.out.a
  store i64 %t3, ptr %l0.out.b
  %t4 = load ptr, ptr %l0.out.a
  %t5 = load i64, ptr %l0.out.b
  store ptr null, ptr %l0.out.a
  store i64 0, ptr %l0.out.b
  %t6 = load ptr, ptr %l0.out.a
  %t7 = load i64, ptr %l0.out.b
  call void @pruv_free_v2(ptr %t6, i64 %t7, i64 1, i64 1)
  %t8 = insertvalue { ptr, i64 } undef, ptr %t4, 0
  %t9 = insertvalue { ptr, i64 } %t8, i64 %t5, 1
  ret { ptr, i64 } %t9
}

define internal { ptr, i64 } @fill_bool__pruv_entry(i64 %p.n, i1 %p.v) {
entry:
  %req.budget = alloca i64
  br label %start
start:
  %t1 = sext i64 %p.n to i128
  store i64 1073741824, ptr %req.budget
  %t2 = icmp sle i128 0, %t1
  br i1 %t2, label %rhs.1, label %endsc.2
rhs.1:
  %t3 = icmp sle i128 %t1, 100
  br label %endsc.2
endsc.2:
  %t4 = phi i1 [ false, %start ], [ %t3, %rhs.1 ]
  br i1 %t4, label %ok.3, label %fail.4
fail.4:
  call void @pruv_panic_requires(ptr @.str.9, ptr @.str.8)
  unreachable
ok.3:
  %t5 = call { ptr, i64 } @fill_bool__pruv_body(i64 %p.n, i1 %p.v)
  ret { ptr, i64 } %t5
}

define void @pruv_abi_fill_bool(i64 %a.n, i64 %a.v, ptr %out) {
entry:
  %c.v = icmp ne i64 %a.v, 0
  %r = call { ptr, i64 } @fill_bool__pruv_entry(i64 %a.n, i1 %c.v)
  %x0 = extractvalue { ptr, i64 } %r, 0
  %x1 = extractvalue { ptr, i64 } %r, 1
  %o0 = getelementptr inbounds { ptr, i64 }, ptr %out, i32 0, i32 0
  %o1 = getelementptr inbounds { ptr, i64 }, ptr %out, i32 0, i32 1
  store ptr %x0, ptr %o0
  store i64 %x1, ptr %o1
  ret void
}
