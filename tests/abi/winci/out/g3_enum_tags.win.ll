target datalayout = "e-m:w-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-f80:128-n8:16:32:64-S128"
target triple = "x86_64-pc-windows-msvc"

@.str.0 = private unnamed_addr constant [22 x i8] c"division by zero in /\00"
@.str.1 = private unnamed_addr constant [19 x i8] c"i128 overflow in /\00"
@.str.2 = private unnamed_addr constant [22 x i8] c"division by zero in %\00"
@.str.3 = private unnamed_addr constant [19 x i8] c"i128 overflow in %\00"
@.str.4 = private unnamed_addr constant [10 x i8] c"left_bool\00"
@.str.5 = private unnamed_addr constant [28 x i8] c"is_variant(c, Choice::Left)\00"
@.str.6 = private unnamed_addr constant [30 x i8] c"enum pruv_g3_t_6_Choice_2_b_i\00"

%pruv_t_pruv_g3_t_6_Choice_2_b_i = type { i64, i1, i64 }
%pruv_c_pruv_g3_t_6_Choice_2_b_i = type { i64, i1, i128 }

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
declare void @pruv_panic_repr(i64, ptr) noreturn cold nounwind

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

define internal i1 @left_bool__pruv_body(%pruv_t_pruv_g3_t_6_Choice_2_b_i %p.c) {
entry:
  br label %start
start:
  %t1 = extractvalue %pruv_t_pruv_g3_t_6_Choice_2_b_i %p.c, 0
  switch i64 %t1, label %matchdef.3 [ i64 0, label %armLeft.1 i64 1, label %armRight.2 ]
matchdef.3:
  unreachable
armLeft.1:
  %t2 = extractvalue %pruv_t_pruv_g3_t_6_Choice_2_b_i %p.c, 1
  ret i1 %t2
armRight.2:
  %t3 = extractvalue %pruv_t_pruv_g3_t_6_Choice_2_b_i %p.c, 2
  ret i1 false
}

define internal i1 @left_bool__pruv_entry(%pruv_t_pruv_g3_t_6_Choice_2_b_i %p.c) {
entry:
  %req.budget = alloca i64
  br label %start
start:
  %t1 = extractvalue %pruv_t_pruv_g3_t_6_Choice_2_b_i %p.c, 0
  %t2 = insertvalue %pruv_c_pruv_g3_t_6_Choice_2_b_i zeroinitializer, i64 %t1, 0
  switch i64 %t1, label %cvend.1 [ i64 0, label %cvv.2 i64 1, label %cvv.3 ]
cvv.2:
  %t3 = extractvalue %pruv_t_pruv_g3_t_6_Choice_2_b_i %p.c, 1
  %t4 = insertvalue %pruv_c_pruv_g3_t_6_Choice_2_b_i %t2, i1 %t3, 1
  br label %cvend.1
cvv.3:
  %t5 = extractvalue %pruv_t_pruv_g3_t_6_Choice_2_b_i %p.c, 2
  %t6 = sext i64 %t5 to i128
  %t7 = insertvalue %pruv_c_pruv_g3_t_6_Choice_2_b_i %t2, i128 %t6, 2
  br label %cvend.1
cvend.1:
  %t8 = phi %pruv_c_pruv_g3_t_6_Choice_2_b_i [ %t2, %start ], [ %t4, %cvv.2 ], [ %t7, %cvv.3 ]
  store i64 1073741824, ptr %req.budget
  %t9 = extractvalue %pruv_c_pruv_g3_t_6_Choice_2_b_i %t8, 0
  %t10 = icmp eq i64 %t9, 0
  br i1 %t10, label %ok.4, label %fail.5
fail.5:
  call void @pruv_panic_requires(ptr @.str.4, ptr @.str.5)
  unreachable
ok.4:
  %t11 = call i1 @left_bool__pruv_body(%pruv_t_pruv_g3_t_6_Choice_2_b_i %p.c)
  ret i1 %t11
}

define i64 @pruv_abi_left_bool(ptr %a.c) {
entry:
  %w.1 = getelementptr inbounds i64, ptr %a.c, i64 0
  %w.2 = load i64, ptr %w.1
  %w.3 = icmp ult i64 %w.2, 2
  %w.4 = insertvalue %pruv_t_pruv_g3_t_6_Choice_2_b_i zeroinitializer, i64 %w.2, 0
  %w.5 = icmp eq i64 %w.2, 0
  %w.6 = getelementptr inbounds i64, ptr %a.c, i64 1
  %w.7 = load i64, ptr %w.6
  %w.8 = icmp ne i64 %w.7, 0
  %w.9 = and i1 %w.5, %w.8
  %w.10 = insertvalue %pruv_t_pruv_g3_t_6_Choice_2_b_i %w.4, i1 %w.9, 1
  %w.11 = icmp eq i64 %w.2, 1
  %w.12 = getelementptr inbounds i64, ptr %a.c, i64 2
  %w.13 = load i64, ptr %w.12
  %w.14 = select i1 %w.11, i64 %w.13, i64 0
  %w.15 = insertvalue %pruv_t_pruv_g3_t_6_Choice_2_b_i %w.10, i64 %w.14, 2
  br i1 %w.3, label %enum.ok0, label %enum.bad0
enum.bad0:
  call void @pruv_panic_repr(i64 %w.2, ptr @.str.6)
  unreachable
enum.ok0:
  %r = call i1 @left_bool__pruv_entry(%pruv_t_pruv_g3_t_6_Choice_2_b_i %w.15)
  %rz = zext i1 %r to i64
  ret i64 %rz
}

define internal i1 @is_left__pruv_body(%pruv_t_pruv_g3_t_6_Choice_2_b_i %p.c) {
entry:
  br label %start
start:
  %t1 = extractvalue %pruv_t_pruv_g3_t_6_Choice_2_b_i %p.c, 0
  switch i64 %t1, label %matchdef.3 [ i64 0, label %armLeft.1 i64 1, label %armRight.2 ]
matchdef.3:
  unreachable
armLeft.1:
  %t2 = extractvalue %pruv_t_pruv_g3_t_6_Choice_2_b_i %p.c, 1
  ret i1 true
armRight.2:
  %t3 = extractvalue %pruv_t_pruv_g3_t_6_Choice_2_b_i %p.c, 2
  ret i1 false
}

define internal i1 @is_left__pruv_entry(%pruv_t_pruv_g3_t_6_Choice_2_b_i %p.c) {
entry:
  br label %start
start:
  %t1 = call i1 @is_left__pruv_body(%pruv_t_pruv_g3_t_6_Choice_2_b_i %p.c)
  ret i1 %t1
}

define i64 @pruv_abi_is_left(ptr %a.c) {
entry:
  %w.1 = getelementptr inbounds i64, ptr %a.c, i64 0
  %w.2 = load i64, ptr %w.1
  %w.3 = icmp ult i64 %w.2, 2
  %w.4 = insertvalue %pruv_t_pruv_g3_t_6_Choice_2_b_i zeroinitializer, i64 %w.2, 0
  %w.5 = icmp eq i64 %w.2, 0
  %w.6 = getelementptr inbounds i64, ptr %a.c, i64 1
  %w.7 = load i64, ptr %w.6
  %w.8 = icmp ne i64 %w.7, 0
  %w.9 = and i1 %w.5, %w.8
  %w.10 = insertvalue %pruv_t_pruv_g3_t_6_Choice_2_b_i %w.4, i1 %w.9, 1
  %w.11 = icmp eq i64 %w.2, 1
  %w.12 = getelementptr inbounds i64, ptr %a.c, i64 2
  %w.13 = load i64, ptr %w.12
  %w.14 = select i1 %w.11, i64 %w.13, i64 0
  %w.15 = insertvalue %pruv_t_pruv_g3_t_6_Choice_2_b_i %w.10, i64 %w.14, 2
  br i1 %w.3, label %enum.ok0, label %enum.bad0
enum.bad0:
  call void @pruv_panic_repr(i64 %w.2, ptr @.str.6)
  unreachable
enum.ok0:
  %r = call i1 @is_left__pruv_entry(%pruv_t_pruv_g3_t_6_Choice_2_b_i %w.15)
  %rz = zext i1 %r to i64
  ret i64 %rz
}

define internal i1 @opt_is_left__pruv_body({ i1, %pruv_t_pruv_g3_t_6_Choice_2_b_i } %p.o) {
entry:
  br label %start
start:
  %t1 = extractvalue { i1, %pruv_t_pruv_g3_t_6_Choice_2_b_i } %p.o, 0
  br i1 %t1, label %armT.1, label %armF.2
armT.1:
  %t2 = extractvalue { i1, %pruv_t_pruv_g3_t_6_Choice_2_b_i } %p.o, 1
  %t3 = call i1 @is_left__pruv_body(%pruv_t_pruv_g3_t_6_Choice_2_b_i %t2)
  ret i1 %t3
armF.2:
  ret i1 false
}

define internal i1 @opt_is_left__pruv_entry({ i1, %pruv_t_pruv_g3_t_6_Choice_2_b_i } %p.o) {
entry:
  br label %start
start:
  %t1 = call i1 @opt_is_left__pruv_body({ i1, %pruv_t_pruv_g3_t_6_Choice_2_b_i } %p.o)
  ret i1 %t1
}

define i64 @pruv_abi_opt_is_left(ptr %a.o) {
entry:
  %w.1 = getelementptr inbounds i64, ptr %a.o, i64 0
  %w.2 = load i64, ptr %w.1
  %w.3 = icmp ne i64 %w.2, 0
  %w.4 = getelementptr inbounds i64, ptr %a.o, i64 1
  %w.5 = load i64, ptr %w.4
  %w.6 = icmp ult i64 %w.5, 2
  %w.7 = xor i1 %w.3, true
  %w.8 = or i1 %w.7, %w.6
  %w.9 = select i1 %w.3, i64 %w.5, i64 0
  %w.10 = insertvalue %pruv_t_pruv_g3_t_6_Choice_2_b_i zeroinitializer, i64 %w.9, 0
  %w.11 = icmp eq i64 %w.5, 0
  %w.12 = and i1 %w.3, %w.11
  %w.13 = getelementptr inbounds i64, ptr %a.o, i64 2
  %w.14 = load i64, ptr %w.13
  %w.15 = icmp ne i64 %w.14, 0
  %w.16 = and i1 %w.12, %w.15
  %w.17 = insertvalue %pruv_t_pruv_g3_t_6_Choice_2_b_i %w.10, i1 %w.16, 1
  %w.18 = icmp eq i64 %w.5, 1
  %w.19 = and i1 %w.3, %w.18
  %w.20 = getelementptr inbounds i64, ptr %a.o, i64 3
  %w.21 = load i64, ptr %w.20
  %w.22 = select i1 %w.19, i64 %w.21, i64 0
  %w.23 = insertvalue %pruv_t_pruv_g3_t_6_Choice_2_b_i %w.17, i64 %w.22, 2
  %w.24 = insertvalue { i1, %pruv_t_pruv_g3_t_6_Choice_2_b_i } zeroinitializer, i1 %w.3, 0
  %w.25 = insertvalue { i1, %pruv_t_pruv_g3_t_6_Choice_2_b_i } %w.24, %pruv_t_pruv_g3_t_6_Choice_2_b_i %w.23, 1
  br i1 %w.8, label %enum.ok0, label %enum.bad0
enum.bad0:
  call void @pruv_panic_repr(i64 %w.5, ptr @.str.6)
  unreachable
enum.ok0:
  %r = call i1 @opt_is_left__pruv_entry({ i1, %pruv_t_pruv_g3_t_6_Choice_2_b_i } %w.25)
  %rz = zext i1 %r to i64
  ret i64 %rz
}
