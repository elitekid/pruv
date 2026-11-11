target datalayout = "e-m:w-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-f80:128-n8:16:32:64-S128"
target triple = "x86_64-pc-windows-msvc"


%pruv_t_pruv_g3_t_4_Pair_2_b_i = type { i1, i64 }
%pruv_t_pruv_g3_t_4_Pair_2_i_b = type { i64, i1 }
%pruv_c_pruv_g3_t_4_Pair_2_b_i = type { i1, i128 }
%pruv_c_pruv_g3_t_4_Pair_2_i_b = type { i128, i1 }

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

define internal %pruv_t_pruv_g3_t_4_Pair_2_b_i @pruv_g3_f_4_make_2_b_i__pruv_body(i1 %p.a, i64 %p.b) {
entry:
  br label %start
start:
  %t1 = insertvalue %pruv_t_pruv_g3_t_4_Pair_2_b_i zeroinitializer, i1 %p.a, 0
  %t2 = insertvalue %pruv_t_pruv_g3_t_4_Pair_2_b_i %t1, i64 %p.b, 1
  ret %pruv_t_pruv_g3_t_4_Pair_2_b_i %t2
}

define internal %pruv_t_pruv_g3_t_4_Pair_2_b_i @pruv_g3_f_4_make_2_b_i__pruv_entry(i1 %p.a, i64 %p.b) {
entry:
  br label %start
start:
  %t1 = call %pruv_t_pruv_g3_t_4_Pair_2_b_i @pruv_g3_f_4_make_2_b_i__pruv_body(i1 %p.a, i64 %p.b)
  ret %pruv_t_pruv_g3_t_4_Pair_2_b_i %t1
}

define internal %pruv_t_pruv_g3_t_4_Pair_2_i_b @pruv_g3_f_4_make_2_i_b__pruv_body(i64 %p.a, i1 %p.b) {
entry:
  br label %start
start:
  %t1 = insertvalue %pruv_t_pruv_g3_t_4_Pair_2_i_b zeroinitializer, i64 %p.a, 0
  %t2 = insertvalue %pruv_t_pruv_g3_t_4_Pair_2_i_b %t1, i1 %p.b, 1
  ret %pruv_t_pruv_g3_t_4_Pair_2_i_b %t2
}

define internal %pruv_t_pruv_g3_t_4_Pair_2_i_b @pruv_g3_f_4_make_2_i_b__pruv_entry(i64 %p.a, i1 %p.b) {
entry:
  br label %start
start:
  %t1 = call %pruv_t_pruv_g3_t_4_Pair_2_i_b @pruv_g3_f_4_make_2_i_b__pruv_body(i64 %p.a, i1 %p.b)
  ret %pruv_t_pruv_g3_t_4_Pair_2_i_b %t1
}

define internal %pruv_t_pruv_g3_t_4_Pair_2_b_i @pruv_g3_f_4_swap_2_i_b__pruv_body(%pruv_t_pruv_g3_t_4_Pair_2_i_b %p.p) {
entry:
  br label %start
start:
  %t1 = extractvalue %pruv_t_pruv_g3_t_4_Pair_2_i_b %p.p, 1
  %t2 = extractvalue %pruv_t_pruv_g3_t_4_Pair_2_i_b %p.p, 0
  %t3 = call %pruv_t_pruv_g3_t_4_Pair_2_b_i @pruv_g3_f_4_make_2_b_i__pruv_body(i1 %t1, i64 %t2)
  ret %pruv_t_pruv_g3_t_4_Pair_2_b_i %t3
}

define internal %pruv_t_pruv_g3_t_4_Pair_2_b_i @pruv_g3_f_4_swap_2_i_b__pruv_entry(%pruv_t_pruv_g3_t_4_Pair_2_i_b %p.p) {
entry:
  br label %start
start:
  %t1 = call %pruv_t_pruv_g3_t_4_Pair_2_b_i @pruv_g3_f_4_swap_2_i_b__pruv_body(%pruv_t_pruv_g3_t_4_Pair_2_i_b %p.p)
  ret %pruv_t_pruv_g3_t_4_Pair_2_b_i %t1
}

define internal %pruv_t_pruv_g3_t_4_Pair_2_i_b @build__pruv_body(i64 %p.a, i1 %p.b) {
entry:
  br label %start
start:
  %t1 = call %pruv_t_pruv_g3_t_4_Pair_2_i_b @pruv_g3_f_4_make_2_i_b__pruv_body(i64 %p.a, i1 %p.b)
  ret %pruv_t_pruv_g3_t_4_Pair_2_i_b %t1
}

define internal %pruv_t_pruv_g3_t_4_Pair_2_i_b @build__pruv_entry(i64 %p.a, i1 %p.b) {
entry:
  br label %start
start:
  %t1 = call %pruv_t_pruv_g3_t_4_Pair_2_i_b @build__pruv_body(i64 %p.a, i1 %p.b)
  ret %pruv_t_pruv_g3_t_4_Pair_2_i_b %t1
}

define void @pruv_abi_build(i64 %a.a, i64 %a.b, ptr %out) {
entry:
  %c.b = icmp ne i64 %a.b, 0
  %r = call %pruv_t_pruv_g3_t_4_Pair_2_i_b @build__pruv_entry(i64 %a.a, i1 %c.b)
  %w.1 = extractvalue %pruv_t_pruv_g3_t_4_Pair_2_i_b %r, 0
  %w.2 = getelementptr inbounds i64, ptr %out, i64 0
  store i64 %w.1, ptr %w.2
  %w.3 = extractvalue %pruv_t_pruv_g3_t_4_Pair_2_i_b %r, 1
  %w.4 = zext i1 %w.3 to i64
  %w.5 = getelementptr inbounds i64, ptr %out, i64 1
  store i64 %w.4, ptr %w.5
  ret void
}

define internal %pruv_t_pruv_g3_t_4_Pair_2_b_i @swap_ib__pruv_body(%pruv_t_pruv_g3_t_4_Pair_2_i_b %p.p) {
entry:
  br label %start
start:
  %t1 = call %pruv_t_pruv_g3_t_4_Pair_2_b_i @pruv_g3_f_4_swap_2_i_b__pruv_body(%pruv_t_pruv_g3_t_4_Pair_2_i_b %p.p)
  ret %pruv_t_pruv_g3_t_4_Pair_2_b_i %t1
}

define internal %pruv_t_pruv_g3_t_4_Pair_2_b_i @swap_ib__pruv_entry(%pruv_t_pruv_g3_t_4_Pair_2_i_b %p.p) {
entry:
  br label %start
start:
  %t1 = call %pruv_t_pruv_g3_t_4_Pair_2_b_i @swap_ib__pruv_body(%pruv_t_pruv_g3_t_4_Pair_2_i_b %p.p)
  ret %pruv_t_pruv_g3_t_4_Pair_2_b_i %t1
}

define void @pruv_abi_swap_ib(ptr %a.p, ptr %out) {
entry:
  %w.1 = getelementptr inbounds i64, ptr %a.p, i64 0
  %w.2 = load i64, ptr %w.1
  %w.3 = insertvalue %pruv_t_pruv_g3_t_4_Pair_2_i_b zeroinitializer, i64 %w.2, 0
  %w.4 = getelementptr inbounds i64, ptr %a.p, i64 1
  %w.5 = load i64, ptr %w.4
  %w.6 = icmp ne i64 %w.5, 0
  %w.7 = insertvalue %pruv_t_pruv_g3_t_4_Pair_2_i_b %w.3, i1 %w.6, 1
  %r = call %pruv_t_pruv_g3_t_4_Pair_2_b_i @swap_ib__pruv_entry(%pruv_t_pruv_g3_t_4_Pair_2_i_b %w.7)
  %w.8 = extractvalue %pruv_t_pruv_g3_t_4_Pair_2_b_i %r, 0
  %w.9 = zext i1 %w.8 to i64
  %w.10 = getelementptr inbounds i64, ptr %out, i64 0
  store i64 %w.9, ptr %w.10
  %w.11 = extractvalue %pruv_t_pruv_g3_t_4_Pair_2_b_i %r, 1
  %w.12 = getelementptr inbounds i64, ptr %out, i64 1
  store i64 %w.11, ptr %w.12
  ret void
}
