target datalayout = "e-m:w-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-f80:128-n8:16:32:64-S128"
target triple = "x86_64-pc-windows-msvc"


%pruv_t_Marker = type {}
%pruv_t_pruv_g3_t_6_Holder_1_n6_Marker_0 = type { %pruv_t_Marker }
%pruv_c_Marker = type {}
%pruv_c_pruv_g3_t_6_Holder_1_n6_Marker_0 = type { %pruv_c_Marker }

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

define internal %pruv_t_Marker @marker_id__pruv_body(%pruv_t_Marker %p.m) {
entry:
  br label %start
start:
  ret %pruv_t_Marker %p.m
}

define internal %pruv_t_Marker @marker_id__pruv_entry(%pruv_t_Marker %p.m) {
entry:
  br label %start
start:
  %t1 = call %pruv_t_Marker @marker_id__pruv_body(%pruv_t_Marker %p.m)
  ret %pruv_t_Marker %t1
}

define void @pruv_abi_marker_id(ptr %a.m, ptr %out) {
entry:
  %r = call %pruv_t_Marker @marker_id__pruv_entry(%pruv_t_Marker zeroinitializer)
  %w.1 = getelementptr inbounds i64, ptr %out, i64 0
  store i64 0, ptr %w.1
  ret void
}

define internal %pruv_t_pruv_g3_t_6_Holder_1_n6_Marker_0 @hold_marker__pruv_body(%pruv_t_Marker %p.m) {
entry:
  br label %start
start:
  %t1 = insertvalue %pruv_t_pruv_g3_t_6_Holder_1_n6_Marker_0 zeroinitializer, %pruv_t_Marker %p.m, 0
  ret %pruv_t_pruv_g3_t_6_Holder_1_n6_Marker_0 %t1
}

define internal %pruv_t_pruv_g3_t_6_Holder_1_n6_Marker_0 @hold_marker__pruv_entry(%pruv_t_Marker %p.m) {
entry:
  br label %start
start:
  %t1 = call %pruv_t_pruv_g3_t_6_Holder_1_n6_Marker_0 @hold_marker__pruv_body(%pruv_t_Marker %p.m)
  ret %pruv_t_pruv_g3_t_6_Holder_1_n6_Marker_0 %t1
}

define void @pruv_abi_hold_marker(ptr %a.m, ptr %out) {
entry:
  %r = call %pruv_t_pruv_g3_t_6_Holder_1_n6_Marker_0 @hold_marker__pruv_entry(%pruv_t_Marker zeroinitializer)
  %w.1 = extractvalue %pruv_t_pruv_g3_t_6_Holder_1_n6_Marker_0 %r, 0
  %w.2 = getelementptr inbounds i64, ptr %out, i64 0
  store i64 0, ptr %w.2
  ret void
}

define internal { i1, %pruv_t_Marker } @some_marker__pruv_body(%pruv_t_Marker %p.m) {
entry:
  br label %start
start:
  %t1 = insertvalue { i1, %pruv_t_Marker } zeroinitializer, i1 true, 0
  %t2 = insertvalue { i1, %pruv_t_Marker } %t1, %pruv_t_Marker %p.m, 1
  ret { i1, %pruv_t_Marker } %t2
}

define internal { i1, %pruv_t_Marker } @some_marker__pruv_entry(%pruv_t_Marker %p.m) {
entry:
  br label %start
start:
  %t1 = call { i1, %pruv_t_Marker } @some_marker__pruv_body(%pruv_t_Marker %p.m)
  ret { i1, %pruv_t_Marker } %t1
}

define void @pruv_abi_some_marker(ptr %a.m, ptr %out) {
entry:
  %r = call { i1, %pruv_t_Marker } @some_marker__pruv_entry(%pruv_t_Marker zeroinitializer)
  %w.1 = extractvalue { i1, %pruv_t_Marker } %r, 0
  %w.2 = zext i1 %w.1 to i64
  %w.3 = getelementptr inbounds i64, ptr %out, i64 0
  store i64 %w.2, ptr %w.3
  %w.4 = extractvalue { i1, %pruv_t_Marker } %r, 1
  %w.5 = getelementptr inbounds i64, ptr %out, i64 1
  store i64 0, ptr %w.5
  ret void
}

define internal { i1, %pruv_t_Marker } @no_marker__pruv_body() {
entry:
  br label %start
start:
  ret { i1, %pruv_t_Marker } zeroinitializer
}

define internal { i1, %pruv_t_Marker } @no_marker__pruv_entry() {
entry:
  br label %start
start:
  %t1 = call { i1, %pruv_t_Marker } @no_marker__pruv_body()
  ret { i1, %pruv_t_Marker } %t1
}

define void @pruv_abi_no_marker(ptr %out) {
entry:
  %r = call { i1, %pruv_t_Marker } @no_marker__pruv_entry()
  %w.1 = extractvalue { i1, %pruv_t_Marker } %r, 0
  %w.2 = zext i1 %w.1 to i64
  %w.3 = getelementptr inbounds i64, ptr %out, i64 0
  store i64 %w.2, ptr %w.3
  %w.4 = extractvalue { i1, %pruv_t_Marker } %r, 1
  %w.5 = getelementptr inbounds i64, ptr %out, i64 1
  store i64 0, ptr %w.5
  ret void
}
