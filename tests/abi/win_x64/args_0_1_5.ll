; Windows x64 sret 표본: 인자 0·1·5개. 모두 Option 반환(sret).
; Windows x64 는 정수 인자 레지스터가 4개(RCX,RDX,R8,R9)이고 숨은 sret 가 RCX 를 차지하므로
; f0 은 sret 만, f1 은 sret+1, f5 는 사용자 인자 3개가 레지스터, 2개가 스택으로 간다.
; 합이 0 보다 크면 Some(합).
target datalayout = "e-m:w-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-f80:128-n8:16:32:64-S128"
target triple = "x86_64-pc-windows-msvc"

define internal { i1, i64 } @f0__pruv_entry() #0 {
entry:
  ret { i1, i64 } { i1 false, i64 0 }
}

define internal { i1, i64 } @f1__pruv_entry(i64 %a.a) #0 {
entry:
  %c = icmp sgt i64 %a.a, 0
  %p = select i1 %c, i64 %a.a, i64 0
  %s = insertvalue { i1, i64 } undef, i1 %c, 0
  %r = insertvalue { i1, i64 } %s, i64 %p, 1
  ret { i1, i64 } %r
}

define internal { i1, i64 } @f5__pruv_entry(i64 %a.a, i64 %a.b, i64 %a.c, i64 %a.d, i64 %a.e) #0 {
entry:
  %s1 = add i64 %a.a, %a.b
  %s2 = add i64 %s1, %a.c
  %s3 = add i64 %s2, %a.d
  %s4 = add i64 %s3, %a.e
  %c = icmp sgt i64 %s4, 0
  %p = select i1 %c, i64 %s4, i64 0
  %s = insertvalue { i1, i64 } undef, i1 %c, 0
  %r = insertvalue { i1, i64 } %s, i64 %p, 1
  ret { i1, i64 } %r
}

define void @pruv_abi_f0(ptr sret({ i64, i64 }) align 8 %sret) {
entry:
  %r = call { i1, i64 } @f0__pruv_entry()
  %x0 = extractvalue { i1, i64 } %r, 0
  %x1 = extractvalue { i1, i64 } %r, 1
  %x0z = zext i1 %x0 to i64
  %o0 = getelementptr inbounds { i64, i64 }, ptr %sret, i32 0, i32 0
  %o1 = getelementptr inbounds { i64, i64 }, ptr %sret, i32 0, i32 1
  store i64 %x0z, ptr %o0, align 8
  store i64 %x1, ptr %o1, align 8
  ret void
}

define void @pruv_abi_f1(ptr sret({ i64, i64 }) align 8 %sret, i64 %a.a) {
entry:
  %r = call { i1, i64 } @f1__pruv_entry(i64 %a.a)
  %x0 = extractvalue { i1, i64 } %r, 0
  %x1 = extractvalue { i1, i64 } %r, 1
  %x0z = zext i1 %x0 to i64
  %o0 = getelementptr inbounds { i64, i64 }, ptr %sret, i32 0, i32 0
  %o1 = getelementptr inbounds { i64, i64 }, ptr %sret, i32 0, i32 1
  store i64 %x0z, ptr %o0, align 8
  store i64 %x1, ptr %o1, align 8
  ret void
}

define void @pruv_abi_f5(ptr sret({ i64, i64 }) align 8 %sret, i64 %a.a, i64 %a.b, i64 %a.c, i64 %a.d, i64 %a.e) {
entry:
  %r = call { i1, i64 } @f5__pruv_entry(i64 %a.a, i64 %a.b, i64 %a.c, i64 %a.d, i64 %a.e)
  %x0 = extractvalue { i1, i64 } %r, 0
  %x1 = extractvalue { i1, i64 } %r, 1
  %x0z = zext i1 %x0 to i64
  %o0 = getelementptr inbounds { i64, i64 }, ptr %sret, i32 0, i32 0
  %o1 = getelementptr inbounds { i64, i64 }, ptr %sret, i32 0, i32 1
  store i64 %x0z, ptr %o0, align 8
  store i64 %x1, ptr %o1, align 8
  ret void
}

attributes #0 = { noinline }
