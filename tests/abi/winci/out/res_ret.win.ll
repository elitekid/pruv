target datalayout = "e-m:w-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-f80:128-n8:16:32:64-S128"
target triple = "x86_64-pc-windows-msvc"

@.str.0 = private unnamed_addr constant [22 x i8] c"division by zero in /\00"
@.str.1 = private unnamed_addr constant [19 x i8] c"i128 overflow in /\00"
@.str.2 = private unnamed_addr constant [22 x i8] c"division by zero in %\00"
@.str.3 = private unnamed_addr constant [19 x i8] c"i128 overflow in %\00"
@.str.4 = private unnamed_addr constant [8 x i8] c"get_res\00"
@.str.5 = private unnamed_addr constant [29 x i8] c"((a >= 0) && (a <= 1000000))\00"
@.str.6 = private unnamed_addr constant [29 x i8] c"((b >= 0) && (b <= 1000000))\00"

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

define internal { i1, i64 } @get_res__pruv_body(i64 %p.a, i64 %p.b) {
entry:
  br label %start
start:
  %t1 = icmp eq i64 %p.b, 0
  br i1 %t1, label %then.1, label %endif.2
then.1:
  %t2 = insertvalue { i1, i64 } undef, i1 false, 0
  %t3 = insertvalue { i1, i64 } %t2, i64 1, 1
  ret { i1, i64 } %t3
endif.2:
  %t4 = udiv i64 %p.a, %p.b
  %t5 = insertvalue { i1, i64 } undef, i1 true, 0
  %t6 = insertvalue { i1, i64 } %t5, i64 %t4, 1
  ret { i1, i64 } %t6
}

define internal { i1, i64 } @get_res__pruv_entry(i64 %p.a, i64 %p.b) {
entry:
  %req.budget = alloca i64
  br label %start
start:
  %t1 = sext i64 %p.a to i128
  %t2 = sext i64 %p.b to i128
  store i64 1073741824, ptr %req.budget
  %t3 = icmp sge i128 %t1, 0
  br i1 %t3, label %rhs.1, label %endsc.2
rhs.1:
  %t4 = icmp sle i128 %t1, 1000000
  br label %endsc.2
endsc.2:
  %t5 = phi i1 [ false, %start ], [ %t4, %rhs.1 ]
  br i1 %t5, label %ok.3, label %fail.4
fail.4:
  call void @pruv_panic_requires(ptr @.str.4, ptr @.str.5)
  unreachable
ok.3:
  %t6 = icmp sge i128 %t2, 0
  br i1 %t6, label %rhs.5, label %endsc.6
rhs.5:
  %t7 = icmp sle i128 %t2, 1000000
  br label %endsc.6
endsc.6:
  %t8 = phi i1 [ false, %ok.3 ], [ %t7, %rhs.5 ]
  br i1 %t8, label %ok.7, label %fail.8
fail.8:
  call void @pruv_panic_requires(ptr @.str.4, ptr @.str.6)
  unreachable
ok.7:
  %t9 = call { i1, i64 } @get_res__pruv_body(i64 %p.a, i64 %p.b)
  ret { i1, i64 } %t9
}

define void @pruv_abi_get_res(ptr sret({ i64, i64 }) align 8 %sret, i64 %a.a, i64 %a.b) {
entry:
  %r = call { i1, i64 } @get_res__pruv_entry(i64 %a.a, i64 %a.b)
  %x0 = extractvalue { i1, i64 } %r, 0
  %x1 = extractvalue { i1, i64 } %r, 1
  %x0z = zext i1 %x0 to i64
  %sl0 = getelementptr inbounds { i64, i64 }, ptr %sret, i32 0, i32 0
  %sl1 = getelementptr inbounds { i64, i64 }, ptr %sret, i32 0, i32 1
  store i64 %x0z, ptr %sl0, align 8
  store i64 %x1, ptr %sl1, align 8
  ret void
}
