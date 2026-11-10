; Windows x64 sret 표본: Option 반환 (docs/M3_C4_SPEC.md 7절)
; 내부 body 는 {i1,i64} 를 반환하고, 외부 wrapper 는 처음부터 void + 첫 숨은 sret 로 출력한다.
; x > 0 이면 Some(x) (tag=1), 아니면 None (tag=0, payload=0).
target datalayout = "e-m:w-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-f80:128-n8:16:32:64-S128"
target triple = "x86_64-pc-windows-msvc"

define internal { i1, i64 } @get_opt__pruv_entry(i64 %a.x) #0 {
entry:
  %c = icmp sgt i64 %a.x, 0
  %p = select i1 %c, i64 %a.x, i64 0
  %s = insertvalue { i1, i64 } undef, i1 %c, 0
  %r = insertvalue { i1, i64 } %s, i64 %p, 1
  ret { i1, i64 } %r
}

define void @pruv_abi_get_opt(ptr sret({ i64, i64 }) align 8 %sret, i64 %a.x) {
entry:
  %r = call { i1, i64 } @get_opt__pruv_entry(i64 %a.x)
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
