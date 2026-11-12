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

define internal i64 @step__pruv_body(i64 %p.x) {
entry:
  br label %start
start:
  %t1 = call { i64, i1 } @llvm.smul.with.overflow.i64(i64 %p.x, i64 251)
  %t2 = extractvalue { i64, i1 } %t1, 0
  %t3 = extractvalue { i64, i1 } %t1, 1
  br i1 %t3, label %fail.2, label %ok.1
fail.2:
  call void @pruv_panic_arith(ptr @.str.4)
  unreachable
ok.1:
  %t4 = call { i64, i1 } @llvm.sadd.with.overflow.i64(i64 %t2, i64 17)
  %t5 = extractvalue { i64, i1 } %t4, 0
  %t6 = extractvalue { i64, i1 } %t4, 1
  br i1 %t6, label %fail.4, label %ok.3
fail.4:
  call void @pruv_panic_arith(ptr @.str.5)
  unreachable
ok.3:
  %t7 = icmp sgt i64 65521, 0
  %t8 = icmp sge i64 %t5, 0
  %t9 = and i1 %t7, %t8
  br i1 %t9, label %ok.5, label %fail.6
fail.6:
  call void @pruv_panic_arith(ptr @.str.6)
  unreachable
ok.5:
  %t10 = urem i64 %t5, 65521
  ret i64 %t10
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

define internal i64 @mix__pruv_body(i64 %p.n, i64 %p.seed) {
entry:
  %l0.x.a = alloca i64
  %l1.i.a = alloca i64
  %l2.j.a = alloca i64
  br label %start
start:
  store i64 %p.seed, ptr %l0.x.a
  store i64 0, ptr %l1.i.a
  br label %wcond.1
wcond.1:
  %t1 = load i64, ptr %l1.i.a
  %t2 = icmp slt i64 %t1, %p.n
  br i1 %t2, label %wbody.2, label %wend.3
wbody.2:
  store i64 0, ptr %l2.j.a
  br label %wcond.4
wcond.4:
  %t3 = load i64, ptr %l2.j.a
  %t4 = icmp slt i64 %t3, 32
  br i1 %t4, label %wbody.5, label %wend.6
wbody.5:
  %t5 = load i64, ptr %l0.x.a
  %t6 = call i64 @step__pruv_entry(i64 %t5)
  store i64 %t6, ptr %l0.x.a
  %t7 = load i64, ptr %l2.j.a
  %t8 = call { i64, i1 } @llvm.sadd.with.overflow.i64(i64 %t7, i64 1)
  %t9 = extractvalue { i64, i1 } %t8, 0
  %t10 = extractvalue { i64, i1 } %t8, 1
  br i1 %t10, label %fail.8, label %ok.7
fail.8:
  call void @pruv_panic_arith(ptr @.str.5)
  unreachable
ok.7:
  store i64 %t9, ptr %l2.j.a
  br label %wcond.4
wend.6:
  %t11 = load i64, ptr %l1.i.a
  %t12 = call { i64, i1 } @llvm.sadd.with.overflow.i64(i64 %t11, i64 1)
  %t13 = extractvalue { i64, i1 } %t12, 0
  %t14 = extractvalue { i64, i1 } %t12, 1
  br i1 %t14, label %fail.10, label %ok.9
fail.10:
  call void @pruv_panic_arith(ptr @.str.5)
  unreachable
ok.9:
  store i64 %t13, ptr %l1.i.a
  br label %wcond.1
wend.3:
  %t15 = load i64, ptr %l0.x.a
  ret i64 %t15
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
