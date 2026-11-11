target datalayout = "e-m:w-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-f80:128-n8:16:32:64-S128"
target triple = "x86_64-pc-windows-msvc"

@.str.0 = private unnamed_addr constant [22 x i8] c"division by zero in /\00"
@.str.1 = private unnamed_addr constant [19 x i8] c"i128 overflow in /\00"
@.str.2 = private unnamed_addr constant [22 x i8] c"division by zero in %\00"
@.str.3 = private unnamed_addr constant [19 x i8] c"i128 overflow in %\00"
@.str.4 = private unnamed_addr constant [10 x i8] c"count_opt\00"
@.str.5 = private unnamed_addr constant [20 x i8] c"(len(a) <= 1000000)\00"

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

define internal { i1, i64 } @count_opt__pruv_body(ptr noalias nocapture readonly %p.a.a, i64 %p.a.n) {
entry:
  %l0.c.a = alloca i64
  %l1.i.a = alloca i64
  br label %start
start:
  store i64 0, ptr %l0.c.a
  store i64 0, ptr %l1.i.a
  br label %wcond.1
wcond.1:
  %t1 = load i64, ptr %l1.i.a
  %t2 = icmp slt i64 %t1, %p.a.n
  br i1 %t2, label %wbody.2, label %wend.3
wbody.2:
  %t3 = load i64, ptr %l1.i.a
  %t4 = getelementptr inbounds i8, ptr %p.a.a, i64 %t3
  %t5 = load i8, ptr %t4
  %t6 = icmp ne i8 %t5, 0
  br i1 %t6, label %then.4, label %endif.5
then.4:
  %t7 = load i64, ptr %l0.c.a
  %t8 = add nsw i64 %t7, 1
  store i64 %t8, ptr %l0.c.a
  br label %endif.5
endif.5:
  %t9 = load i64, ptr %l1.i.a
  %t10 = add nsw i64 %t9, 1
  store i64 %t10, ptr %l1.i.a
  br label %wcond.1
wend.3:
  %t11 = load i64, ptr %l0.c.a
  %t12 = icmp sgt i64 %t11, 0
  br i1 %t12, label %then.6, label %endif.7
then.6:
  %t13 = load i64, ptr %l0.c.a
  %t14 = insertvalue { i1, i64 } undef, i1 true, 0
  %t15 = insertvalue { i1, i64 } %t14, i64 %t13, 1
  ret { i1, i64 } %t15
endif.7:
  %t16 = insertvalue { i1, i64 } undef, i1 false, 0
  %t17 = insertvalue { i1, i64 } %t16, i64 0, 1
  ret { i1, i64 } %t17
}

define internal { i1, i64 } @count_opt__pruv_entry(ptr noalias nocapture readonly %p.a.a, i64 %p.a.n) {
entry:
  %req.budget = alloca i64
  br label %start
start:
  store i64 1073741824, ptr %req.budget
  %t1 = zext i64 %p.a.n to i128
  %t2 = icmp sle i128 %t1, 1000000
  br i1 %t2, label %ok.1, label %fail.2
fail.2:
  call void @pruv_panic_requires(ptr @.str.4, ptr @.str.5)
  unreachable
ok.1:
  %t3 = call { i1, i64 } @count_opt__pruv_body(ptr %p.a.a, i64 %p.a.n)
  ret { i1, i64 } %t3
}

define void @pruv_abi_count_opt(ptr sret({ i64, i64 }) align 8 %sret, ptr %a.a.a, i64 %a.a.n) {
entry:
  call void @pruv_check_bool(ptr %a.a.a, i64 %a.a.n)
  %r = call { i1, i64 } @count_opt__pruv_entry(ptr %a.a.a, i64 %a.a.n)
  %x0 = extractvalue { i1, i64 } %r, 0
  %x1 = extractvalue { i1, i64 } %r, 1
  %x0z = zext i1 %x0 to i64
  %sl0 = getelementptr inbounds { i64, i64 }, ptr %sret, i32 0, i32 0
  %sl1 = getelementptr inbounds { i64, i64 }, ptr %sret, i32 0, i32 1
  store i64 %x0z, ptr %sl0, align 8
  store i64 %x1, ptr %sl1, align 8
  ret void
}

define void @pruv_abi_count_opt__typed(ptr sret({ i64, i64 }) align 8 %sret, ptr %a.a.a, i64 %a.a.n) {
entry:
  %r = call { i1, i64 } @count_opt__pruv_entry(ptr %a.a.a, i64 %a.a.n)
  %x0 = extractvalue { i1, i64 } %r, 0
  %x1 = extractvalue { i1, i64 } %r, 1
  %x0z = zext i1 %x0 to i64
  %sl0 = getelementptr inbounds { i64, i64 }, ptr %sret, i32 0, i32 0
  %sl1 = getelementptr inbounds { i64, i64 }, ptr %sret, i32 0, i32 1
  store i64 %x0z, ptr %sl0, align 8
  store i64 %x1, ptr %sl1, align 8
  ret void
}
