target datalayout = "e-m:w-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-f80:128-n8:16:32:64-S128"
target triple = "x86_64-pc-windows-msvc"

@.str.0 = private unnamed_addr constant [22 x i8] c"division by zero in /\00"
@.str.1 = private unnamed_addr constant [19 x i8] c"i128 overflow in /\00"
@.str.2 = private unnamed_addr constant [22 x i8] c"division by zero in %\00"
@.str.3 = private unnamed_addr constant [19 x i8] c"i128 overflow in %\00"
@.str.4 = private unnamed_addr constant [4 x i8] c"cut\00"
@.str.5 = private unnamed_addr constant [28 x i8] c"((0 <= i) && (i <= len(s)))\00"
@.str.6 = private unnamed_addr constant [23 x i8] c"is_char_boundary(s, i)\00"

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
declare i32 @pruv_str_boundary(ptr nocapture readonly, i64, i64) nounwind willreturn memory(argmem: read)
declare noalias ptr @pruv_substr(ptr nocapture readonly, i64, i64, i64) nounwind
declare void @pruv_check_utf8(ptr nocapture readonly, i64) nounwind

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

define internal { ptr, i64 } @cut__pruv_body(ptr noalias nocapture readonly %p.s.a, i64 %p.s.n, i64 %p.i) {
entry:
  %l0.c.a = alloca ptr
  %l0.c.b = alloca i64
  %l1.d.a = alloca ptr
  %l1.d.b = alloca i64
  br label %start
start:
  %t1 = call ptr @pruv_copy_v2(ptr %p.s.a, i64 %p.s.n, i64 1, i64 1)
  store ptr %t1, ptr %l0.c.a
  store i64 %p.s.n, ptr %l0.c.b
  %t2 = load ptr, ptr %l0.c.a
  %t3 = load i64, ptr %l0.c.b
  %t4 = sub i64 %p.i, 0
  %t5 = getelementptr inbounds i8, ptr %t2, i64 0
  %t6 = call ptr @pruv_copy_v2(ptr %t5, i64 %t4, i64 1, i64 1)
  store ptr %t6, ptr %l1.d.a
  store i64 %t4, ptr %l1.d.b
  %t7 = load ptr, ptr %l1.d.a
  %t8 = load i64, ptr %l1.d.b
  store ptr null, ptr %l1.d.a
  store i64 0, ptr %l1.d.b
  %t9 = load ptr, ptr %l1.d.a
  %t10 = load i64, ptr %l1.d.b
  call void @pruv_free_v2(ptr %t9, i64 %t10, i64 1, i64 1)
  %t11 = load ptr, ptr %l0.c.a
  %t12 = load i64, ptr %l0.c.b
  call void @pruv_free_v2(ptr %t11, i64 %t12, i64 1, i64 1)
  %t13 = insertvalue { ptr, i64 } undef, ptr %t7, 0
  %t14 = insertvalue { ptr, i64 } %t13, i64 %t8, 1
  ret { ptr, i64 } %t14
}

define internal { ptr, i64 } @cut__pruv_entry(ptr noalias nocapture readonly %p.s.a, i64 %p.s.n, i64 %p.i) {
entry:
  %req.budget = alloca i64
  br label %start
start:
  %t1 = sext i64 %p.i to i128
  store i64 1073741824, ptr %req.budget
  %t2 = icmp sle i128 0, %t1
  br i1 %t2, label %rhs.1, label %endsc.2
rhs.1:
  %t3 = zext i64 %p.s.n to i128
  %t4 = icmp sle i128 %t1, %t3
  br label %endsc.2
endsc.2:
  %t5 = phi i1 [ false, %start ], [ %t4, %rhs.1 ]
  br i1 %t5, label %ok.3, label %fail.4
fail.4:
  call void @pruv_panic_requires(ptr @.str.4, ptr @.str.5)
  unreachable
ok.3:
  %t6 = zext i64 %p.s.n to i128
  %t7 = icmp ule i128 %t1, %t6
  %t8 = trunc i128 %t1 to i64
  %t9 = select i1 %t7, i64 %t8, i64 -1
  %t10 = call i32 @pruv_str_boundary(ptr %p.s.a, i64 %p.s.n, i64 %t9)
  %t11 = icmp ne i32 %t10, 0
  br i1 %t11, label %ok.5, label %fail.6
fail.6:
  call void @pruv_panic_requires(ptr @.str.4, ptr @.str.6)
  unreachable
ok.5:
  %t12 = call { ptr, i64 } @cut__pruv_body(ptr %p.s.a, i64 %p.s.n, i64 %p.i)
  ret { ptr, i64 } %t12
}

define void @pruv_abi_cut(ptr %a.s.a, i64 %a.s.n, i64 %a.i, ptr %out) {
entry:
  call void @pruv_check_utf8(ptr %a.s.a, i64 %a.s.n)
  %r = call { ptr, i64 } @cut__pruv_entry(ptr %a.s.a, i64 %a.s.n, i64 %a.i)
  %x0 = extractvalue { ptr, i64 } %r, 0
  %x1 = extractvalue { ptr, i64 } %r, 1
  %o0 = getelementptr inbounds { ptr, i64 }, ptr %out, i32 0, i32 0
  %o1 = getelementptr inbounds { ptr, i64 }, ptr %out, i32 0, i32 1
  store ptr %x0, ptr %o0
  store i64 %x1, ptr %o1
  ret void
}

define void @pruv_abi_cut__typed(ptr %a.s.a, i64 %a.s.n, i64 %a.i, ptr %out) {
entry:
  %r = call { ptr, i64 } @cut__pruv_entry(ptr %a.s.a, i64 %a.s.n, i64 %a.i)
  %x0 = extractvalue { ptr, i64 } %r, 0
  %x1 = extractvalue { ptr, i64 } %r, 1
  %o0 = getelementptr inbounds { ptr, i64 }, ptr %out, i32 0, i32 0
  %o1 = getelementptr inbounds { ptr, i64 }, ptr %out, i32 0, i32 1
  store ptr %x0, ptr %o0
  store i64 %x1, ptr %o1
  ret void
}
