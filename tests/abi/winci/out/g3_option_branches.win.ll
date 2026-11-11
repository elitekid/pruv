target datalayout = "e-m:w-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-f80:128-n8:16:32:64-S128"
target triple = "x86_64-pc-windows-msvc"


%pruv_t_Point = type { i64, i64 }
%pruv_c_Point = type { i128, i128 }

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

define internal { i1, i1 } @opt_bool__pruv_body({ i1, i1 } %p.x) {
entry:
  br label %start
start:
  ret { i1, i1 } %p.x
}

define internal { i1, i1 } @opt_bool__pruv_entry({ i1, i1 } %p.x) {
entry:
  br label %start
start:
  %t1 = call { i1, i1 } @opt_bool__pruv_body({ i1, i1 } %p.x)
  ret { i1, i1 } %t1
}

define void @pruv_abi_opt_bool(ptr %a.x, ptr %out) {
entry:
  %w.1 = getelementptr inbounds i64, ptr %a.x, i64 0
  %w.2 = load i64, ptr %w.1
  %w.3 = icmp ne i64 %w.2, 0
  %w.4 = getelementptr inbounds i64, ptr %a.x, i64 1
  %w.5 = load i64, ptr %w.4
  %w.6 = icmp ne i64 %w.5, 0
  %w.7 = and i1 %w.3, %w.6
  %w.8 = insertvalue { i1, i1 } zeroinitializer, i1 %w.3, 0
  %w.9 = insertvalue { i1, i1 } %w.8, i1 %w.7, 1
  %r = call { i1, i1 } @opt_bool__pruv_entry({ i1, i1 } %w.9)
  %w.10 = extractvalue { i1, i1 } %r, 0
  %w.11 = zext i1 %w.10 to i64
  %w.12 = getelementptr inbounds i64, ptr %out, i64 0
  store i64 %w.11, ptr %w.12
  %w.13 = extractvalue { i1, i1 } %r, 1
  %w.14 = and i1 %w.10, %w.13
  %w.15 = zext i1 %w.14 to i64
  %w.16 = getelementptr inbounds i64, ptr %out, i64 1
  store i64 %w.15, ptr %w.16
  ret void
}

define internal { i1, i1 } @some_bool__pruv_body(i1 %p.b) {
entry:
  br label %start
start:
  %t1 = insertvalue { i1, i1 } zeroinitializer, i1 true, 0
  %t2 = insertvalue { i1, i1 } %t1, i1 %p.b, 1
  ret { i1, i1 } %t2
}

define internal { i1, i1 } @some_bool__pruv_entry(i1 %p.b) {
entry:
  br label %start
start:
  %t1 = call { i1, i1 } @some_bool__pruv_body(i1 %p.b)
  ret { i1, i1 } %t1
}

define void @pruv_abi_some_bool(i64 %a.b, ptr %out) {
entry:
  %c.b = icmp ne i64 %a.b, 0
  %r = call { i1, i1 } @some_bool__pruv_entry(i1 %c.b)
  %w.1 = extractvalue { i1, i1 } %r, 0
  %w.2 = zext i1 %w.1 to i64
  %w.3 = getelementptr inbounds i64, ptr %out, i64 0
  store i64 %w.2, ptr %w.3
  %w.4 = extractvalue { i1, i1 } %r, 1
  %w.5 = and i1 %w.1, %w.4
  %w.6 = zext i1 %w.5 to i64
  %w.7 = getelementptr inbounds i64, ptr %out, i64 1
  store i64 %w.6, ptr %w.7
  ret void
}

define internal { i1, i1 } @none_bool__pruv_body() {
entry:
  br label %start
start:
  ret { i1, i1 } zeroinitializer
}

define internal { i1, i1 } @none_bool__pruv_entry() {
entry:
  br label %start
start:
  %t1 = call { i1, i1 } @none_bool__pruv_body()
  ret { i1, i1 } %t1
}

define void @pruv_abi_none_bool(ptr %out) {
entry:
  %r = call { i1, i1 } @none_bool__pruv_entry()
  %w.1 = extractvalue { i1, i1 } %r, 0
  %w.2 = zext i1 %w.1 to i64
  %w.3 = getelementptr inbounds i64, ptr %out, i64 0
  store i64 %w.2, ptr %w.3
  %w.4 = extractvalue { i1, i1 } %r, 1
  %w.5 = and i1 %w.1, %w.4
  %w.6 = zext i1 %w.5 to i64
  %w.7 = getelementptr inbounds i64, ptr %out, i64 1
  store i64 %w.6, ptr %w.7
  ret void
}

define internal i1 @flag__pruv_body({ i1, i1 } %p.o) {
entry:
  br label %start
start:
  %t1 = extractvalue { i1, i1 } %p.o, 0
  br i1 %t1, label %armT.1, label %armF.2
armT.1:
  %t2 = extractvalue { i1, i1 } %p.o, 1
  ret i1 %t2
armF.2:
  ret i1 false
}

define internal i1 @flag__pruv_entry({ i1, i1 } %p.o) {
entry:
  br label %start
start:
  %t1 = call i1 @flag__pruv_body({ i1, i1 } %p.o)
  ret i1 %t1
}

define i64 @pruv_abi_flag(ptr %a.o) {
entry:
  %w.1 = getelementptr inbounds i64, ptr %a.o, i64 0
  %w.2 = load i64, ptr %w.1
  %w.3 = icmp ne i64 %w.2, 0
  %w.4 = getelementptr inbounds i64, ptr %a.o, i64 1
  %w.5 = load i64, ptr %w.4
  %w.6 = icmp ne i64 %w.5, 0
  %w.7 = and i1 %w.3, %w.6
  %w.8 = insertvalue { i1, i1 } zeroinitializer, i1 %w.3, 0
  %w.9 = insertvalue { i1, i1 } %w.8, i1 %w.7, 1
  %r = call i1 @flag__pruv_entry({ i1, i1 } %w.9)
  %rz = zext i1 %r to i64
  ret i64 %rz
}

define internal { i1, %pruv_t_Point } @opt_point__pruv_body({ i1, %pruv_t_Point } %p.o) {
entry:
  br label %start
start:
  ret { i1, %pruv_t_Point } %p.o
}

define internal { i1, %pruv_t_Point } @opt_point__pruv_entry({ i1, %pruv_t_Point } %p.o) {
entry:
  br label %start
start:
  %t1 = call { i1, %pruv_t_Point } @opt_point__pruv_body({ i1, %pruv_t_Point } %p.o)
  ret { i1, %pruv_t_Point } %t1
}

define void @pruv_abi_opt_point(ptr %a.o, ptr %out) {
entry:
  %w.1 = getelementptr inbounds i64, ptr %a.o, i64 0
  %w.2 = load i64, ptr %w.1
  %w.3 = icmp ne i64 %w.2, 0
  %w.4 = getelementptr inbounds i64, ptr %a.o, i64 1
  %w.5 = load i64, ptr %w.4
  %w.6 = select i1 %w.3, i64 %w.5, i64 0
  %w.7 = insertvalue %pruv_t_Point zeroinitializer, i64 %w.6, 0
  %w.8 = getelementptr inbounds i64, ptr %a.o, i64 2
  %w.9 = load i64, ptr %w.8
  %w.10 = select i1 %w.3, i64 %w.9, i64 0
  %w.11 = insertvalue %pruv_t_Point %w.7, i64 %w.10, 1
  %w.12 = insertvalue { i1, %pruv_t_Point } zeroinitializer, i1 %w.3, 0
  %w.13 = insertvalue { i1, %pruv_t_Point } %w.12, %pruv_t_Point %w.11, 1
  %r = call { i1, %pruv_t_Point } @opt_point__pruv_entry({ i1, %pruv_t_Point } %w.13)
  %w.14 = extractvalue { i1, %pruv_t_Point } %r, 0
  %w.15 = zext i1 %w.14 to i64
  %w.16 = getelementptr inbounds i64, ptr %out, i64 0
  store i64 %w.15, ptr %w.16
  %w.17 = extractvalue { i1, %pruv_t_Point } %r, 1
  %w.18 = extractvalue %pruv_t_Point %w.17, 0
  %w.19 = select i1 %w.14, i64 %w.18, i64 0
  %w.20 = getelementptr inbounds i64, ptr %out, i64 1
  store i64 %w.19, ptr %w.20
  %w.21 = extractvalue %pruv_t_Point %w.17, 1
  %w.22 = select i1 %w.14, i64 %w.21, i64 0
  %w.23 = getelementptr inbounds i64, ptr %out, i64 2
  store i64 %w.22, ptr %w.23
  ret void
}

define internal { i1, { i1, i64 } } @opt_res__pruv_body({ i1, { i1, i64 } } %p.o) {
entry:
  br label %start
start:
  ret { i1, { i1, i64 } } %p.o
}

define internal { i1, { i1, i64 } } @opt_res__pruv_entry({ i1, { i1, i64 } } %p.o) {
entry:
  br label %start
start:
  %t1 = call { i1, { i1, i64 } } @opt_res__pruv_body({ i1, { i1, i64 } } %p.o)
  ret { i1, { i1, i64 } } %t1
}

define void @pruv_abi_opt_res(ptr %a.o, ptr %out) {
entry:
  %w.1 = getelementptr inbounds i64, ptr %a.o, i64 0
  %w.2 = load i64, ptr %w.1
  %w.3 = icmp ne i64 %w.2, 0
  %w.4 = getelementptr inbounds i64, ptr %a.o, i64 1
  %w.5 = load i64, ptr %w.4
  %w.6 = icmp ne i64 %w.5, 0
  %w.7 = and i1 %w.3, %w.6
  %w.8 = getelementptr inbounds i64, ptr %a.o, i64 2
  %w.9 = load i64, ptr %w.8
  %w.10 = select i1 %w.3, i64 %w.9, i64 0
  %w.11 = insertvalue { i1, i64 } undef, i1 %w.7, 0
  %w.12 = insertvalue { i1, i64 } %w.11, i64 %w.10, 1
  %w.13 = insertvalue { i1, { i1, i64 } } zeroinitializer, i1 %w.3, 0
  %w.14 = insertvalue { i1, { i1, i64 } } %w.13, { i1, i64 } %w.12, 1
  %r = call { i1, { i1, i64 } } @opt_res__pruv_entry({ i1, { i1, i64 } } %w.14)
  %w.15 = extractvalue { i1, { i1, i64 } } %r, 0
  %w.16 = zext i1 %w.15 to i64
  %w.17 = getelementptr inbounds i64, ptr %out, i64 0
  store i64 %w.16, ptr %w.17
  %w.18 = extractvalue { i1, { i1, i64 } } %r, 1
  %w.19 = extractvalue { i1, i64 } %w.18, 0
  %w.20 = extractvalue { i1, i64 } %w.18, 1
  %w.21 = and i1 %w.15, %w.19
  %w.22 = select i1 %w.15, i64 %w.20, i64 0
  %w.23 = zext i1 %w.21 to i64
  %w.24 = getelementptr inbounds i64, ptr %out, i64 1
  store i64 %w.23, ptr %w.24
  %w.25 = getelementptr inbounds i64, ptr %out, i64 2
  store i64 %w.22, ptr %w.25
  ret void
}
