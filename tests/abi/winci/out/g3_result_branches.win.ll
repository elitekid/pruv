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

define internal { i1, i1, i64 } @res_bool__pruv_body({ i1, i1, i64 } %p.r) {
entry:
  br label %start
start:
  ret { i1, i1, i64 } %p.r
}

define internal { i1, i1, i64 } @res_bool__pruv_entry({ i1, i1, i64 } %p.r) {
entry:
  br label %start
start:
  %t1 = call { i1, i1, i64 } @res_bool__pruv_body({ i1, i1, i64 } %p.r)
  ret { i1, i1, i64 } %t1
}

define void @pruv_abi_res_bool(ptr %a.r, ptr %out) {
entry:
  %w.1 = getelementptr inbounds i64, ptr %a.r, i64 0
  %w.2 = load i64, ptr %w.1
  %w.3 = icmp ne i64 %w.2, 0
  %w.4 = getelementptr inbounds i64, ptr %a.r, i64 1
  %w.5 = load i64, ptr %w.4
  %w.6 = icmp ne i64 %w.5, 0
  %w.7 = and i1 %w.3, %w.6
  %w.8 = insertvalue { i1, i1, i64 } zeroinitializer, i1 %w.3, 0
  %w.9 = insertvalue { i1, i1, i64 } %w.8, i1 %w.7, 1
  %w.10 = getelementptr inbounds i64, ptr %a.r, i64 2
  %w.11 = load i64, ptr %w.10
  %w.12 = xor i1 %w.3, true
  %w.13 = select i1 %w.12, i64 %w.11, i64 0
  %w.14 = insertvalue { i1, i1, i64 } %w.9, i64 %w.13, 2
  %r = call { i1, i1, i64 } @res_bool__pruv_entry({ i1, i1, i64 } %w.14)
  %w.15 = extractvalue { i1, i1, i64 } %r, 0
  %w.16 = zext i1 %w.15 to i64
  %w.17 = getelementptr inbounds i64, ptr %out, i64 0
  store i64 %w.16, ptr %w.17
  %w.18 = extractvalue { i1, i1, i64 } %r, 1
  %w.19 = and i1 %w.15, %w.18
  %w.20 = zext i1 %w.19 to i64
  %w.21 = getelementptr inbounds i64, ptr %out, i64 1
  store i64 %w.20, ptr %w.21
  %w.22 = extractvalue { i1, i1, i64 } %r, 2
  %w.23 = xor i1 %w.15, true
  %w.24 = select i1 %w.23, i64 %w.22, i64 0
  %w.25 = getelementptr inbounds i64, ptr %out, i64 2
  store i64 %w.24, ptr %w.25
  ret void
}

define internal { i1, i1, i64 } @ok_bool__pruv_body(i1 %p.b) {
entry:
  br label %start
start:
  %t1 = insertvalue { i1, i1, i64 } zeroinitializer, i1 true, 0
  %t2 = insertvalue { i1, i1, i64 } %t1, i1 %p.b, 1
  ret { i1, i1, i64 } %t2
}

define internal { i1, i1, i64 } @ok_bool__pruv_entry(i1 %p.b) {
entry:
  br label %start
start:
  %t1 = call { i1, i1, i64 } @ok_bool__pruv_body(i1 %p.b)
  ret { i1, i1, i64 } %t1
}

define void @pruv_abi_ok_bool(i64 %a.b, ptr %out) {
entry:
  %c.b = icmp ne i64 %a.b, 0
  %r = call { i1, i1, i64 } @ok_bool__pruv_entry(i1 %c.b)
  %w.1 = extractvalue { i1, i1, i64 } %r, 0
  %w.2 = zext i1 %w.1 to i64
  %w.3 = getelementptr inbounds i64, ptr %out, i64 0
  store i64 %w.2, ptr %w.3
  %w.4 = extractvalue { i1, i1, i64 } %r, 1
  %w.5 = and i1 %w.1, %w.4
  %w.6 = zext i1 %w.5 to i64
  %w.7 = getelementptr inbounds i64, ptr %out, i64 1
  store i64 %w.6, ptr %w.7
  %w.8 = extractvalue { i1, i1, i64 } %r, 2
  %w.9 = xor i1 %w.1, true
  %w.10 = select i1 %w.9, i64 %w.8, i64 0
  %w.11 = getelementptr inbounds i64, ptr %out, i64 2
  store i64 %w.10, ptr %w.11
  ret void
}

define internal { i1, i1, i64 } @err_bool__pruv_body(i64 %p.c) {
entry:
  br label %start
start:
  %t1 = insertvalue { i1, i1, i64 } zeroinitializer, i64 %p.c, 2
  ret { i1, i1, i64 } %t1
}

define internal { i1, i1, i64 } @err_bool__pruv_entry(i64 %p.c) {
entry:
  br label %start
start:
  %t1 = call { i1, i1, i64 } @err_bool__pruv_body(i64 %p.c)
  ret { i1, i1, i64 } %t1
}

define void @pruv_abi_err_bool(i64 %a.c, ptr %out) {
entry:
  %r = call { i1, i1, i64 } @err_bool__pruv_entry(i64 %a.c)
  %w.1 = extractvalue { i1, i1, i64 } %r, 0
  %w.2 = zext i1 %w.1 to i64
  %w.3 = getelementptr inbounds i64, ptr %out, i64 0
  store i64 %w.2, ptr %w.3
  %w.4 = extractvalue { i1, i1, i64 } %r, 1
  %w.5 = and i1 %w.1, %w.4
  %w.6 = zext i1 %w.5 to i64
  %w.7 = getelementptr inbounds i64, ptr %out, i64 1
  store i64 %w.6, ptr %w.7
  %w.8 = extractvalue { i1, i1, i64 } %r, 2
  %w.9 = xor i1 %w.1, true
  %w.10 = select i1 %w.9, i64 %w.8, i64 0
  %w.11 = getelementptr inbounds i64, ptr %out, i64 2
  store i64 %w.10, ptr %w.11
  ret void
}

define internal i64 @code_of__pruv_body({ i1, i1, i64 } %p.r) {
entry:
  br label %start
start:
  %t1 = extractvalue { i1, i1, i64 } %p.r, 0
  br i1 %t1, label %armT.1, label %armF.2
armT.1:
  %t2 = extractvalue { i1, i1, i64 } %p.r, 1
  ret i64 0
armF.2:
  %t3 = extractvalue { i1, i1, i64 } %p.r, 2
  ret i64 %t3
}

define internal i64 @code_of__pruv_entry({ i1, i1, i64 } %p.r) {
entry:
  br label %start
start:
  %t1 = call i64 @code_of__pruv_body({ i1, i1, i64 } %p.r)
  ret i64 %t1
}

define i64 @pruv_abi_code_of(ptr %a.r) {
entry:
  %w.1 = getelementptr inbounds i64, ptr %a.r, i64 0
  %w.2 = load i64, ptr %w.1
  %w.3 = icmp ne i64 %w.2, 0
  %w.4 = getelementptr inbounds i64, ptr %a.r, i64 1
  %w.5 = load i64, ptr %w.4
  %w.6 = icmp ne i64 %w.5, 0
  %w.7 = and i1 %w.3, %w.6
  %w.8 = insertvalue { i1, i1, i64 } zeroinitializer, i1 %w.3, 0
  %w.9 = insertvalue { i1, i1, i64 } %w.8, i1 %w.7, 1
  %w.10 = getelementptr inbounds i64, ptr %a.r, i64 2
  %w.11 = load i64, ptr %w.10
  %w.12 = xor i1 %w.3, true
  %w.13 = select i1 %w.12, i64 %w.11, i64 0
  %w.14 = insertvalue { i1, i1, i64 } %w.9, i64 %w.13, 2
  %r = call i64 @code_of__pruv_entry({ i1, i1, i64 } %w.14)
  ret i64 %r
}

define internal { i1, %pruv_t_Point, i64 } @res_point__pruv_body({ i1, %pruv_t_Point, i64 } %p.r) {
entry:
  br label %start
start:
  ret { i1, %pruv_t_Point, i64 } %p.r
}

define internal { i1, %pruv_t_Point, i64 } @res_point__pruv_entry({ i1, %pruv_t_Point, i64 } %p.r) {
entry:
  br label %start
start:
  %t1 = call { i1, %pruv_t_Point, i64 } @res_point__pruv_body({ i1, %pruv_t_Point, i64 } %p.r)
  ret { i1, %pruv_t_Point, i64 } %t1
}

define void @pruv_abi_res_point(ptr %a.r, ptr %out) {
entry:
  %w.1 = getelementptr inbounds i64, ptr %a.r, i64 0
  %w.2 = load i64, ptr %w.1
  %w.3 = icmp ne i64 %w.2, 0
  %w.4 = getelementptr inbounds i64, ptr %a.r, i64 1
  %w.5 = load i64, ptr %w.4
  %w.6 = select i1 %w.3, i64 %w.5, i64 0
  %w.7 = insertvalue %pruv_t_Point zeroinitializer, i64 %w.6, 0
  %w.8 = getelementptr inbounds i64, ptr %a.r, i64 2
  %w.9 = load i64, ptr %w.8
  %w.10 = select i1 %w.3, i64 %w.9, i64 0
  %w.11 = insertvalue %pruv_t_Point %w.7, i64 %w.10, 1
  %w.12 = insertvalue { i1, %pruv_t_Point, i64 } zeroinitializer, i1 %w.3, 0
  %w.13 = insertvalue { i1, %pruv_t_Point, i64 } %w.12, %pruv_t_Point %w.11, 1
  %w.14 = getelementptr inbounds i64, ptr %a.r, i64 3
  %w.15 = load i64, ptr %w.14
  %w.16 = xor i1 %w.3, true
  %w.17 = select i1 %w.16, i64 %w.15, i64 0
  %w.18 = insertvalue { i1, %pruv_t_Point, i64 } %w.13, i64 %w.17, 2
  %r = call { i1, %pruv_t_Point, i64 } @res_point__pruv_entry({ i1, %pruv_t_Point, i64 } %w.18)
  %w.19 = extractvalue { i1, %pruv_t_Point, i64 } %r, 0
  %w.20 = zext i1 %w.19 to i64
  %w.21 = getelementptr inbounds i64, ptr %out, i64 0
  store i64 %w.20, ptr %w.21
  %w.22 = extractvalue { i1, %pruv_t_Point, i64 } %r, 1
  %w.23 = extractvalue %pruv_t_Point %w.22, 0
  %w.24 = select i1 %w.19, i64 %w.23, i64 0
  %w.25 = getelementptr inbounds i64, ptr %out, i64 1
  store i64 %w.24, ptr %w.25
  %w.26 = extractvalue %pruv_t_Point %w.22, 1
  %w.27 = select i1 %w.19, i64 %w.26, i64 0
  %w.28 = getelementptr inbounds i64, ptr %out, i64 2
  store i64 %w.27, ptr %w.28
  %w.29 = extractvalue { i1, %pruv_t_Point, i64 } %r, 2
  %w.30 = xor i1 %w.19, true
  %w.31 = select i1 %w.30, i64 %w.29, i64 0
  %w.32 = getelementptr inbounds i64, ptr %out, i64 3
  store i64 %w.31, ptr %w.32
  ret void
}
