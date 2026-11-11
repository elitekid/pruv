target datalayout = "e-m:w-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-f80:128-n8:16:32:64-S128"
target triple = "x86_64-pc-windows-msvc"

@.str.0 = private unnamed_addr constant [30 x i8] c"enum pruv_g3_t_6_Choice_2_b_i\00"
@.str.1 = private unnamed_addr constant [31 x i8] c"enum pruv_g3_t_6_Choice_2_b_ob\00"

%pruv_t_pruv_g3_t_6_Choice_2_b_i = type { i64, i1, i64 }
%pruv_t_pruv_g3_t_6_Choice_2_b_ob = type { i64, i1, { i1, i1 } }
%pruv_t_pruv_g3_t_6_Choice_2_ob_b = type { i64, { i1, i1 }, i1 }
%pruv_c_pruv_g3_t_6_Choice_2_b_i = type { i64, i1, i128 }
%pruv_c_pruv_g3_t_6_Choice_2_b_ob = type { i64, i1, { i1, i1 } }
%pruv_c_pruv_g3_t_6_Choice_2_ob_b = type { i64, { i1, i1 }, i1 }

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

define internal %pruv_t_pruv_g3_t_6_Choice_2_b_i @choice_id__pruv_body(%pruv_t_pruv_g3_t_6_Choice_2_b_i %p.c) {
entry:
  br label %start
start:
  ret %pruv_t_pruv_g3_t_6_Choice_2_b_i %p.c
}

define internal %pruv_t_pruv_g3_t_6_Choice_2_b_i @choice_id__pruv_entry(%pruv_t_pruv_g3_t_6_Choice_2_b_i %p.c) {
entry:
  br label %start
start:
  %t1 = call %pruv_t_pruv_g3_t_6_Choice_2_b_i @choice_id__pruv_body(%pruv_t_pruv_g3_t_6_Choice_2_b_i %p.c)
  ret %pruv_t_pruv_g3_t_6_Choice_2_b_i %t1
}

define void @pruv_abi_choice_id(ptr %a.c, ptr %out) {
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
  call void @pruv_panic_repr(i64 %w.2, ptr @.str.0)
  unreachable
enum.ok0:
  %r = call %pruv_t_pruv_g3_t_6_Choice_2_b_i @choice_id__pruv_entry(%pruv_t_pruv_g3_t_6_Choice_2_b_i %w.15)
  %w.16 = extractvalue %pruv_t_pruv_g3_t_6_Choice_2_b_i %r, 0
  %w.17 = getelementptr inbounds i64, ptr %out, i64 0
  store i64 %w.16, ptr %w.17
  %w.18 = icmp eq i64 %w.16, 0
  %w.19 = extractvalue %pruv_t_pruv_g3_t_6_Choice_2_b_i %r, 1
  %w.20 = and i1 %w.18, %w.19
  %w.21 = zext i1 %w.20 to i64
  %w.22 = getelementptr inbounds i64, ptr %out, i64 1
  store i64 %w.21, ptr %w.22
  %w.23 = icmp eq i64 %w.16, 1
  %w.24 = extractvalue %pruv_t_pruv_g3_t_6_Choice_2_b_i %r, 2
  %w.25 = select i1 %w.23, i64 %w.24, i64 0
  %w.26 = getelementptr inbounds i64, ptr %out, i64 2
  store i64 %w.25, ptr %w.26
  ret void
}

define internal %pruv_t_pruv_g3_t_6_Choice_2_ob_b @choice_flip__pruv_body(%pruv_t_pruv_g3_t_6_Choice_2_b_ob %p.c) {
entry:
  br label %start
start:
  %t1 = extractvalue %pruv_t_pruv_g3_t_6_Choice_2_b_ob %p.c, 0
  switch i64 %t1, label %matchdef.3 [ i64 0, label %armLeft.1 i64 1, label %armRight.2 ]
matchdef.3:
  unreachable
armLeft.1:
  %t2 = extractvalue %pruv_t_pruv_g3_t_6_Choice_2_b_ob %p.c, 1
  %t3 = insertvalue %pruv_t_pruv_g3_t_6_Choice_2_ob_b zeroinitializer, i64 1, 0
  %t4 = insertvalue %pruv_t_pruv_g3_t_6_Choice_2_ob_b %t3, i1 %t2, 2
  ret %pruv_t_pruv_g3_t_6_Choice_2_ob_b %t4
armRight.2:
  %t5 = extractvalue %pruv_t_pruv_g3_t_6_Choice_2_b_ob %p.c, 2
  %t6 = insertvalue %pruv_t_pruv_g3_t_6_Choice_2_ob_b zeroinitializer, i64 0, 0
  %t7 = insertvalue %pruv_t_pruv_g3_t_6_Choice_2_ob_b %t6, { i1, i1 } %t5, 1
  ret %pruv_t_pruv_g3_t_6_Choice_2_ob_b %t7
}

define internal %pruv_t_pruv_g3_t_6_Choice_2_ob_b @choice_flip__pruv_entry(%pruv_t_pruv_g3_t_6_Choice_2_b_ob %p.c) {
entry:
  br label %start
start:
  %t1 = call %pruv_t_pruv_g3_t_6_Choice_2_ob_b @choice_flip__pruv_body(%pruv_t_pruv_g3_t_6_Choice_2_b_ob %p.c)
  ret %pruv_t_pruv_g3_t_6_Choice_2_ob_b %t1
}

define void @pruv_abi_choice_flip(ptr %a.c, ptr %out) {
entry:
  %w.1 = getelementptr inbounds i64, ptr %a.c, i64 0
  %w.2 = load i64, ptr %w.1
  %w.3 = icmp ult i64 %w.2, 2
  %w.4 = insertvalue %pruv_t_pruv_g3_t_6_Choice_2_b_ob zeroinitializer, i64 %w.2, 0
  %w.5 = icmp eq i64 %w.2, 0
  %w.6 = getelementptr inbounds i64, ptr %a.c, i64 1
  %w.7 = load i64, ptr %w.6
  %w.8 = icmp ne i64 %w.7, 0
  %w.9 = and i1 %w.5, %w.8
  %w.10 = insertvalue %pruv_t_pruv_g3_t_6_Choice_2_b_ob %w.4, i1 %w.9, 1
  %w.11 = icmp eq i64 %w.2, 1
  %w.12 = getelementptr inbounds i64, ptr %a.c, i64 2
  %w.13 = load i64, ptr %w.12
  %w.14 = icmp ne i64 %w.13, 0
  %w.15 = and i1 %w.11, %w.14
  %w.16 = getelementptr inbounds i64, ptr %a.c, i64 3
  %w.17 = load i64, ptr %w.16
  %w.18 = icmp ne i64 %w.17, 0
  %w.19 = and i1 %w.15, %w.18
  %w.20 = insertvalue { i1, i1 } zeroinitializer, i1 %w.15, 0
  %w.21 = insertvalue { i1, i1 } %w.20, i1 %w.19, 1
  %w.22 = insertvalue %pruv_t_pruv_g3_t_6_Choice_2_b_ob %w.10, { i1, i1 } %w.21, 2
  br i1 %w.3, label %enum.ok0, label %enum.bad0
enum.bad0:
  call void @pruv_panic_repr(i64 %w.2, ptr @.str.1)
  unreachable
enum.ok0:
  %r = call %pruv_t_pruv_g3_t_6_Choice_2_ob_b @choice_flip__pruv_entry(%pruv_t_pruv_g3_t_6_Choice_2_b_ob %w.22)
  %w.23 = extractvalue %pruv_t_pruv_g3_t_6_Choice_2_ob_b %r, 0
  %w.24 = getelementptr inbounds i64, ptr %out, i64 0
  store i64 %w.23, ptr %w.24
  %w.25 = icmp eq i64 %w.23, 0
  %w.26 = extractvalue %pruv_t_pruv_g3_t_6_Choice_2_ob_b %r, 1
  %w.27 = extractvalue { i1, i1 } %w.26, 0
  %w.28 = and i1 %w.25, %w.27
  %w.29 = zext i1 %w.28 to i64
  %w.30 = getelementptr inbounds i64, ptr %out, i64 1
  store i64 %w.29, ptr %w.30
  %w.31 = extractvalue { i1, i1 } %w.26, 1
  %w.32 = and i1 %w.28, %w.31
  %w.33 = zext i1 %w.32 to i64
  %w.34 = getelementptr inbounds i64, ptr %out, i64 2
  store i64 %w.33, ptr %w.34
  %w.35 = icmp eq i64 %w.23, 1
  %w.36 = extractvalue %pruv_t_pruv_g3_t_6_Choice_2_ob_b %r, 2
  %w.37 = and i1 %w.35, %w.36
  %w.38 = zext i1 %w.37 to i64
  %w.39 = getelementptr inbounds i64, ptr %out, i64 3
  store i64 %w.38, ptr %w.39
  ret void
}
