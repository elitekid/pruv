target datalayout = "e-m:w-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-f80:128-n8:16:32:64-S128"
target triple = "x86_64-pc-windows-msvc"


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

define internal { i1, i64 } @opt_max__pruv_body() {
entry:
  br label %start
start:
  %t1 = insertvalue { i1, i64 } undef, i1 true, 0
  %t2 = insertvalue { i1, i64 } %t1, i64 9223372036854775807, 1
  ret { i1, i64 } %t2
}

define internal { i1, i64 } @opt_max__pruv_entry() {
entry:
  br label %start
start:
  %t1 = call { i1, i64 } @opt_max__pruv_body()
  ret { i1, i64 } %t1
}

define void @pruv_abi_opt_max(ptr sret({ i64, i64 }) align 8 %sret) {
entry:
  %r = call { i1, i64 } @opt_max__pruv_entry()
  %x0 = extractvalue { i1, i64 } %r, 0
  %x1 = extractvalue { i1, i64 } %r, 1
  %x0z = zext i1 %x0 to i64
  %sl0 = getelementptr inbounds { i64, i64 }, ptr %sret, i32 0, i32 0
  %sl1 = getelementptr inbounds { i64, i64 }, ptr %sret, i32 0, i32 1
  store i64 %x0z, ptr %sl0, align 8
  store i64 %x1, ptr %sl1, align 8
  ret void
}

define internal { i1, i64 } @opt_min__pruv_body() {
entry:
  br label %start
start:
  %t1 = sub nsw i64 -9223372036854775807, 1
  %t2 = insertvalue { i1, i64 } undef, i1 true, 0
  %t3 = insertvalue { i1, i64 } %t2, i64 %t1, 1
  ret { i1, i64 } %t3
}

define internal { i1, i64 } @opt_min__pruv_entry() {
entry:
  br label %start
start:
  %t1 = call { i1, i64 } @opt_min__pruv_body()
  ret { i1, i64 } %t1
}

define void @pruv_abi_opt_min(ptr sret({ i64, i64 }) align 8 %sret) {
entry:
  %r = call { i1, i64 } @opt_min__pruv_entry()
  %x0 = extractvalue { i1, i64 } %r, 0
  %x1 = extractvalue { i1, i64 } %r, 1
  %x0z = zext i1 %x0 to i64
  %sl0 = getelementptr inbounds { i64, i64 }, ptr %sret, i32 0, i32 0
  %sl1 = getelementptr inbounds { i64, i64 }, ptr %sret, i32 0, i32 1
  store i64 %x0z, ptr %sl0, align 8
  store i64 %x1, ptr %sl1, align 8
  ret void
}
