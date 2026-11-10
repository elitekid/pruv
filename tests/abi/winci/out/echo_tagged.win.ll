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

define internal { i1, i64 } @echo_opt__pruv_body({ i1, i64 } %p.o) {
entry:
  br label %start
start:
  %t1 = extractvalue { i1, i64 } %p.o, 0
  %t2 = extractvalue { i1, i64 } %p.o, 1
  br i1 %t1, label %armT.1, label %armF.2
armT.1:
  %t3 = insertvalue { i1, i64 } undef, i1 true, 0
  %t4 = insertvalue { i1, i64 } %t3, i64 %t2, 1
  ret { i1, i64 } %t4
armF.2:
  %t5 = insertvalue { i1, i64 } undef, i1 false, 0
  %t6 = insertvalue { i1, i64 } %t5, i64 0, 1
  ret { i1, i64 } %t6
}

define internal { i1, i64 } @echo_opt__pruv_entry({ i1, i64 } %p.o) {
entry:
  br label %start
start:
  %t1 = call { i1, i64 } @echo_opt__pruv_body({ i1, i64 } %p.o)
  ret { i1, i64 } %t1
}

define void @pruv_abi_echo_opt(ptr sret({ i64, i64 }) align 8 %sret, i64 %a.o.t, i64 %a.o.v) {
entry:
  %c.o.t = icmp ne i64 %a.o.t, 0
  %c.o.g1 = insertvalue { i1, i64 } undef, i1 %c.o.t, 0
  %c.o.g = insertvalue { i1, i64 } %c.o.g1, i64 %a.o.v, 1
  %r = call { i1, i64 } @echo_opt__pruv_entry({ i1, i64 } %c.o.g)
  %x0 = extractvalue { i1, i64 } %r, 0
  %x1 = extractvalue { i1, i64 } %r, 1
  %x0z = zext i1 %x0 to i64
  %sl0 = getelementptr inbounds { i64, i64 }, ptr %sret, i32 0, i32 0
  %sl1 = getelementptr inbounds { i64, i64 }, ptr %sret, i32 0, i32 1
  store i64 %x0z, ptr %sl0, align 8
  store i64 %x1, ptr %sl1, align 8
  ret void
}

define internal { i1, i64 } @echo_res__pruv_body({ i1, i64 } %p.r) {
entry:
  br label %start
start:
  %t1 = extractvalue { i1, i64 } %p.r, 0
  %t2 = extractvalue { i1, i64 } %p.r, 1
  br i1 %t1, label %armT.1, label %armF.2
armT.1:
  %t3 = insertvalue { i1, i64 } undef, i1 true, 0
  %t4 = insertvalue { i1, i64 } %t3, i64 %t2, 1
  ret { i1, i64 } %t4
armF.2:
  %t5 = insertvalue { i1, i64 } undef, i1 false, 0
  %t6 = insertvalue { i1, i64 } %t5, i64 %t2, 1
  ret { i1, i64 } %t6
}

define internal { i1, i64 } @echo_res__pruv_entry({ i1, i64 } %p.r) {
entry:
  br label %start
start:
  %t1 = call { i1, i64 } @echo_res__pruv_body({ i1, i64 } %p.r)
  ret { i1, i64 } %t1
}

define void @pruv_abi_echo_res(ptr sret({ i64, i64 }) align 8 %sret, i64 %a.r.t, i64 %a.r.v) {
entry:
  %c.r.t = icmp ne i64 %a.r.t, 0
  %c.r.g1 = insertvalue { i1, i64 } undef, i1 %c.r.t, 0
  %c.r.g = insertvalue { i1, i64 } %c.r.g1, i64 %a.r.v, 1
  %r = call { i1, i64 } @echo_res__pruv_entry({ i1, i64 } %c.r.g)
  %x0 = extractvalue { i1, i64 } %r, 0
  %x1 = extractvalue { i1, i64 } %r, 1
  %x0z = zext i1 %x0 to i64
  %sl0 = getelementptr inbounds { i64, i64 }, ptr %sret, i32 0, i32 0
  %sl1 = getelementptr inbounds { i64, i64 }, ptr %sret, i32 0, i32 1
  store i64 %x0z, ptr %sl0, align 8
  store i64 %x1, ptr %sl1, align 8
  ret void
}
