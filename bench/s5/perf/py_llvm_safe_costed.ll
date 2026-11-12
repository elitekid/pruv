@.str.0 = private unnamed_addr constant [22 x i8] c"division by zero in /\00"
@.str.1 = private unnamed_addr constant [19 x i8] c"i128 overflow in /\00"
@.str.2 = private unnamed_addr constant [22 x i8] c"division by zero in %\00"
@.str.3 = private unnamed_addr constant [19 x i8] c"i128 overflow in %\00"
@.str.4 = private unnamed_addr constant [14 x i8] c"overflow in *\00"
@.str.5 = private unnamed_addr constant [14 x i8] c"overflow in +\00"
@.str.6 = private unnamed_addr constant [60 x i8] c"division outside domain: need divisor > 0 and dividend >= 0\00"
@.str.7 = private unnamed_addr constant [5 x i8] c"step\00"
@.str.8 = private unnamed_addr constant [26 x i8] c"((0 <= x) && (x < 65521))\00"
@.str.9 = private unnamed_addr constant [4 x i8] c"mix\00"
@.str.10 = private unnamed_addr constant [29 x i8] c"((0 <= n) && (n <= 1000000))\00"
@.str.11 = private unnamed_addr constant [32 x i8] c"((0 <= seed) && (seed < 65521))\00"
@.str.12 = private unnamed_addr constant [19 x i8] c"i128 overflow in *\00"

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

define internal i128 @step__pruv_cost(i64 %p.x) {
entry:
  %req.budget = alloca i64
  br label %start
start:
  %t1 = sext i64 %p.x to i128
  store i64 1073741824, ptr %req.budget
  %t2 = icmp sle i128 0, %t1
  br i1 %t2, label %rhs.1, label %endsc.2
rhs.1:
  %t3 = icmp slt i128 %t1, 65521
  br label %endsc.2
endsc.2:
  %t4 = phi i1 [ false, %start ], [ %t3, %rhs.1 ]
  br i1 %t4, label %ok.3, label %fail.4
fail.4:
  call void @pruv_panic_requires(ptr @.str.7, ptr @.str.8)
  unreachable
ok.3:
  ret i128 0
}

define internal i64 @step__pruv_body(i64 %p.x) {
entry:
  %cost.spent = alloca i128
  br label %start
start:
  %t1 = call i128 @step__pruv_cost(i64 %p.x)
  store i128 0, ptr %cost.spent
  %t2 = call { i64, i1 } @llvm.smul.with.overflow.i64(i64 %p.x, i64 251)
  %t3 = extractvalue { i64, i1 } %t2, 0
  %t4 = extractvalue { i64, i1 } %t2, 1
  br i1 %t4, label %fail.2, label %ok.1
fail.2:
  call void @pruv_panic_arith(ptr @.str.4)
  unreachable
ok.1:
  %t5 = call { i64, i1 } @llvm.sadd.with.overflow.i64(i64 %t3, i64 17)
  %t6 = extractvalue { i64, i1 } %t5, 0
  %t7 = extractvalue { i64, i1 } %t5, 1
  br i1 %t7, label %fail.4, label %ok.3
fail.4:
  call void @pruv_panic_arith(ptr @.str.5)
  unreachable
ok.3:
  %t8 = icmp sgt i64 65521, 0
  %t9 = icmp sge i64 %t6, 0
  %t10 = and i1 %t8, %t9
  br i1 %t10, label %ok.5, label %fail.6
fail.6:
  call void @pruv_panic_arith(ptr @.str.6)
  unreachable
ok.5:
  %t11 = urem i64 %t6, 65521
  %t12 = icmp slt i128 %t1, 0
  %t13 = load i128, ptr %cost.spent
  %t14 = icmp ugt i128 %t13, %t1
  %t15 = or i1 %t12, %t14
  br i1 %t15, label %fail.8, label %ok.7
fail.8:
  call void @pruv_panic_cost()
  unreachable
ok.7:
  ret i64 %t11
}

define internal i64 @step__pruv_entry(i64 %p.x) {
entry:
  %req.budget = alloca i64
  br label %start
start:
  %t1 = sext i64 %p.x to i128
  store i64 1073741824, ptr %req.budget
  %t2 = icmp sle i128 0, %t1
  br i1 %t2, label %rhs.1, label %endsc.2
rhs.1:
  %t3 = icmp slt i128 %t1, 65521
  br label %endsc.2
endsc.2:
  %t4 = phi i1 [ false, %start ], [ %t3, %rhs.1 ]
  br i1 %t4, label %ok.3, label %fail.4
fail.4:
  call void @pruv_panic_requires(ptr @.str.7, ptr @.str.8)
  unreachable
ok.3:
  %t5 = call i64 @step__pruv_body(i64 %p.x)
  ret i64 %t5
}

define i64 @pruv_abi_step(i64 %a.x) {
entry:
  %r = call i64 @step__pruv_entry(i64 %a.x)
  ret i64 %r
}

define internal i128 @mix__pruv_cost(i64 %p.n, i64 %p.seed) {
entry:
  %req.budget = alloca i64
  br label %start
start:
  %t1 = sext i64 %p.n to i128
  %t2 = sext i64 %p.seed to i128
  store i64 1073741824, ptr %req.budget
  %t3 = icmp sle i128 0, %t1
  br i1 %t3, label %rhs.1, label %endsc.2
rhs.1:
  %t4 = icmp sle i128 %t1, 1000000
  br label %endsc.2
endsc.2:
  %t5 = phi i1 [ false, %start ], [ %t4, %rhs.1 ]
  br i1 %t5, label %ok.3, label %fail.4
fail.4:
  call void @pruv_panic_requires(ptr @.str.9, ptr @.str.10)
  unreachable
ok.3:
  %t6 = icmp sle i128 0, %t2
  br i1 %t6, label %rhs.5, label %endsc.6
rhs.5:
  %t7 = icmp slt i128 %t2, 65521
  br label %endsc.6
endsc.6:
  %t8 = phi i1 [ false, %ok.3 ], [ %t7, %rhs.5 ]
  br i1 %t8, label %ok.7, label %fail.8
fail.8:
  call void @pruv_panic_requires(ptr @.str.9, ptr @.str.11)
  unreachable
ok.7:
  %t9 = call { i128, i1 } @llvm.smul.with.overflow.i128(i128 65, i128 %t1)
  %t10 = extractvalue { i128, i1 } %t9, 0
  %t11 = extractvalue { i128, i1 } %t9, 1
  br i1 %t11, label %fail.10, label %ok.9
fail.10:
  call void @pruv_panic_undefined(ptr @.str.12)
  unreachable
ok.9:
  ret i128 %t10
}

define internal i64 @mix__pruv_body(i64 %p.n, i64 %p.seed) {
entry:
  %cost.spent = alloca i128
  %l0.x.a = alloca i64
  %l1.i.a = alloca i64
  %l2.j.a = alloca i64
  br label %start
start:
  %t1 = call i128 @mix__pruv_cost(i64 %p.n, i64 %p.seed)
  store i128 0, ptr %cost.spent
  store i64 %p.seed, ptr %l0.x.a
  store i64 0, ptr %l1.i.a
  br label %wcond.1
wcond.1:
  %t2 = load i64, ptr %l1.i.a
  %t3 = icmp slt i64 %t2, %p.n
  br i1 %t3, label %wbody.2, label %wend.3
wbody.2:
  %t4 = load i128, ptr %cost.spent
  %t5 = call { i128, i1 } @llvm.uadd.with.overflow.i128(i128 %t4, i128 1)
  %t6 = extractvalue { i128, i1 } %t5, 0
  %t7 = extractvalue { i128, i1 } %t5, 1
  br i1 %t7, label %fail.5, label %ok.4
fail.5:
  call void @pruv_panic_cost()
  unreachable
ok.4:
  store i128 %t6, ptr %cost.spent
  store i64 0, ptr %l2.j.a
  br label %wcond.6
wcond.6:
  %t8 = load i64, ptr %l2.j.a
  %t9 = icmp slt i64 %t8, 32
  br i1 %t9, label %wbody.7, label %wend.8
wbody.7:
  %t10 = load i128, ptr %cost.spent
  %t11 = call { i128, i1 } @llvm.uadd.with.overflow.i128(i128 %t10, i128 1)
  %t12 = extractvalue { i128, i1 } %t11, 0
  %t13 = extractvalue { i128, i1 } %t11, 1
  br i1 %t13, label %fail.10, label %ok.9
fail.10:
  call void @pruv_panic_cost()
  unreachable
ok.9:
  store i128 %t12, ptr %cost.spent
  %t14 = load i64, ptr %l0.x.a
  %t15 = call i128 @step__pruv_cost(i64 %t14)
  %t16 = icmp slt i128 %t15, 0
  br i1 %t16, label %fail.12, label %ok.11
fail.12:
  call void @pruv_panic_cost()
  unreachable
ok.11:
  %t17 = add i128 %t15, 1
  %t18 = load i128, ptr %cost.spent
  %t19 = call { i128, i1 } @llvm.uadd.with.overflow.i128(i128 %t18, i128 %t17)
  %t20 = extractvalue { i128, i1 } %t19, 0
  %t21 = extractvalue { i128, i1 } %t19, 1
  br i1 %t21, label %fail.14, label %ok.13
fail.14:
  call void @pruv_panic_cost()
  unreachable
ok.13:
  store i128 %t20, ptr %cost.spent
  %t22 = call i64 @step__pruv_entry(i64 %t14)
  store i64 %t22, ptr %l0.x.a
  %t23 = load i64, ptr %l2.j.a
  %t24 = call { i64, i1 } @llvm.sadd.with.overflow.i64(i64 %t23, i64 1)
  %t25 = extractvalue { i64, i1 } %t24, 0
  %t26 = extractvalue { i64, i1 } %t24, 1
  br i1 %t26, label %fail.16, label %ok.15
fail.16:
  call void @pruv_panic_arith(ptr @.str.5)
  unreachable
ok.15:
  store i64 %t25, ptr %l2.j.a
  br label %wcond.6
wend.8:
  %t27 = load i64, ptr %l1.i.a
  %t28 = call { i64, i1 } @llvm.sadd.with.overflow.i64(i64 %t27, i64 1)
  %t29 = extractvalue { i64, i1 } %t28, 0
  %t30 = extractvalue { i64, i1 } %t28, 1
  br i1 %t30, label %fail.18, label %ok.17
fail.18:
  call void @pruv_panic_arith(ptr @.str.5)
  unreachable
ok.17:
  store i64 %t29, ptr %l1.i.a
  br label %wcond.1
wend.3:
  %t31 = load i64, ptr %l0.x.a
  %t32 = icmp slt i128 %t1, 0
  %t33 = load i128, ptr %cost.spent
  %t34 = icmp ugt i128 %t33, %t1
  %t35 = or i1 %t32, %t34
  br i1 %t35, label %fail.20, label %ok.19
fail.20:
  call void @pruv_panic_cost()
  unreachable
ok.19:
  ret i64 %t31
}

define internal i64 @mix__pruv_entry(i64 %p.n, i64 %p.seed) {
entry:
  %req.budget = alloca i64
  br label %start
start:
  %t1 = sext i64 %p.n to i128
  %t2 = sext i64 %p.seed to i128
  store i64 1073741824, ptr %req.budget
  %t3 = icmp sle i128 0, %t1
  br i1 %t3, label %rhs.1, label %endsc.2
rhs.1:
  %t4 = icmp sle i128 %t1, 1000000
  br label %endsc.2
endsc.2:
  %t5 = phi i1 [ false, %start ], [ %t4, %rhs.1 ]
  br i1 %t5, label %ok.3, label %fail.4
fail.4:
  call void @pruv_panic_requires(ptr @.str.9, ptr @.str.10)
  unreachable
ok.3:
  %t6 = icmp sle i128 0, %t2
  br i1 %t6, label %rhs.5, label %endsc.6
rhs.5:
  %t7 = icmp slt i128 %t2, 65521
  br label %endsc.6
endsc.6:
  %t8 = phi i1 [ false, %ok.3 ], [ %t7, %rhs.5 ]
  br i1 %t8, label %ok.7, label %fail.8
fail.8:
  call void @pruv_panic_requires(ptr @.str.9, ptr @.str.11)
  unreachable
ok.7:
  %t9 = call i64 @mix__pruv_body(i64 %p.n, i64 %p.seed)
  ret i64 %t9
}

define i64 @pruv_abi_mix(i64 %a.n, i64 %a.seed) {
entry:
  %r = call i64 @mix__pruv_entry(i64 %a.n, i64 %a.seed)
  ret i64 %r
}
declare void @pruv_panic_cost() noreturn cold nounwind
declare { i128, i1 } @llvm.uadd.with.overflow.i128(i128, i128)
