target datalayout = "e-m:w-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-f80:128-n8:16:32:64-S128"
target triple = "x86_64-pc-windows-msvc"

@.str.0 = private unnamed_addr constant [22 x i8] c"division by zero in /\00"
@.str.1 = private unnamed_addr constant [19 x i8] c"i128 overflow in /\00"
@.str.2 = private unnamed_addr constant [22 x i8] c"division by zero in %\00"
@.str.3 = private unnamed_addr constant [19 x i8] c"i128 overflow in %\00"
@.str.4 = private unnamed_addr constant [10 x i8] c"make_slot\00"
@.str.5 = private unnamed_addr constant [36 x i8] c"((x >= -1000000) && (x <= 1000000))\00"

%pruv_t_Slot = type { { i1, i64 }, i64 }
%pruv_c_Slot = type { { i1, i128 }, i128 }

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

define internal %pruv_t_Slot @make_slot__pruv_body(i64 %p.x) {
entry:
  br label %start
start:
  %t1 = icmp sgt i64 %p.x, 0
  br i1 %t1, label %then.1, label %endif.2
then.1:
  %t2 = insertvalue { i1, i64 } undef, i1 true, 0
  %t3 = insertvalue { i1, i64 } %t2, i64 %p.x, 1
  %t4 = insertvalue %pruv_t_Slot zeroinitializer, { i1, i64 } %t3, 0
  %t5 = insertvalue %pruv_t_Slot %t4, i64 %p.x, 1
  ret %pruv_t_Slot %t5
endif.2:
  %t6 = insertvalue { i1, i64 } undef, i1 false, 0
  %t7 = insertvalue { i1, i64 } %t6, i64 0, 1
  %t8 = insertvalue %pruv_t_Slot zeroinitializer, { i1, i64 } %t7, 0
  %t9 = insertvalue %pruv_t_Slot %t8, i64 %p.x, 1
  ret %pruv_t_Slot %t9
}

define internal %pruv_t_Slot @make_slot__pruv_entry(i64 %p.x) {
entry:
  %req.budget = alloca i64
  br label %start
start:
  %t1 = sext i64 %p.x to i128
  store i64 1073741824, ptr %req.budget
  %t2 = icmp sge i128 %t1, -1000000
  br i1 %t2, label %rhs.1, label %endsc.2
rhs.1:
  %t3 = icmp sle i128 %t1, 1000000
  br label %endsc.2
endsc.2:
  %t4 = phi i1 [ false, %start ], [ %t3, %rhs.1 ]
  br i1 %t4, label %ok.3, label %fail.4
fail.4:
  call void @pruv_panic_requires(ptr @.str.4, ptr @.str.5)
  unreachable
ok.3:
  %t5 = call %pruv_t_Slot @make_slot__pruv_body(i64 %p.x)
  ret %pruv_t_Slot %t5
}

define void @pruv_abi_make_slot(i64 %a.x, ptr %out) {
entry:
  %r = call %pruv_t_Slot @make_slot__pruv_entry(i64 %a.x)
  %w.1 = extractvalue %pruv_t_Slot %r, 0
  %w.2 = extractvalue { i1, i64 } %w.1, 0
  %w.3 = extractvalue { i1, i64 } %w.1, 1
  %w.4 = select i1 %w.2, i64 %w.3, i64 0
  %w.5 = zext i1 %w.2 to i64
  %w.6 = getelementptr inbounds i64, ptr %out, i64 0
  store i64 %w.5, ptr %w.6
  %w.7 = getelementptr inbounds i64, ptr %out, i64 1
  store i64 %w.4, ptr %w.7
  %w.8 = extractvalue %pruv_t_Slot %r, 1
  %w.9 = getelementptr inbounds i64, ptr %out, i64 2
  store i64 %w.8, ptr %w.9
  ret void
}

define internal { i1, i64 } @slot_opt__pruv_body(%pruv_t_Slot %p.s) {
entry:
  br label %start
start:
  %t1 = extractvalue %pruv_t_Slot %p.s, 0
  %t2 = extractvalue { i1, i64 } %t1, 0
  %t3 = extractvalue { i1, i64 } %t1, 1
  br i1 %t2, label %armT.1, label %armF.2
armT.1:
  %t4 = insertvalue { i1, i64 } undef, i1 true, 0
  %t5 = insertvalue { i1, i64 } %t4, i64 %t3, 1
  ret { i1, i64 } %t5
armF.2:
  %t6 = insertvalue { i1, i64 } undef, i1 false, 0
  %t7 = insertvalue { i1, i64 } %t6, i64 0, 1
  ret { i1, i64 } %t7
}

define internal { i1, i64 } @slot_opt__pruv_entry(%pruv_t_Slot %p.s) {
entry:
  br label %start
start:
  %t1 = call { i1, i64 } @slot_opt__pruv_body(%pruv_t_Slot %p.s)
  ret { i1, i64 } %t1
}

define void @pruv_abi_slot_opt(ptr sret({ i64, i64 }) align 8 %sret, ptr %a.s) {
entry:
  %w.1 = getelementptr inbounds i64, ptr %a.s, i64 0
  %w.2 = load i64, ptr %w.1
  %w.3 = icmp ne i64 %w.2, 0
  %w.4 = getelementptr inbounds i64, ptr %a.s, i64 1
  %w.5 = load i64, ptr %w.4
  %w.6 = insertvalue { i1, i64 } undef, i1 %w.3, 0
  %w.7 = insertvalue { i1, i64 } %w.6, i64 %w.5, 1
  %w.8 = insertvalue %pruv_t_Slot zeroinitializer, { i1, i64 } %w.7, 0
  %w.9 = getelementptr inbounds i64, ptr %a.s, i64 2
  %w.10 = load i64, ptr %w.9
  %w.11 = insertvalue %pruv_t_Slot %w.8, i64 %w.10, 1
  %r = call { i1, i64 } @slot_opt__pruv_entry(%pruv_t_Slot %w.11)
  %x0 = extractvalue { i1, i64 } %r, 0
  %x1 = extractvalue { i1, i64 } %r, 1
  %x0z = zext i1 %x0 to i64
  %sl0 = getelementptr inbounds { i64, i64 }, ptr %sret, i32 0, i32 0
  %sl1 = getelementptr inbounds { i64, i64 }, ptr %sret, i32 0, i32 1
  store i64 %x0z, ptr %sl0, align 8
  store i64 %x1, ptr %sl1, align 8
  ret void
}
