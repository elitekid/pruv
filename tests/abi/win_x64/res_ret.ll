; Windows x64 sret 표본: Result 반환 (내부 꼴은 Option 과 같은 {i1,i64})
; x >= 0 이면 Ok(x) (tag=1), 아니면 Err(-x) (tag=0). 쓰는 tag 의 의미는 llvmgen.py 규칙을 따른다고 가정.
target datalayout = "e-m:w-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-f80:128-n8:16:32:64-S128"
target triple = "x86_64-pc-windows-msvc"

define internal { i1, i64 } @get_res__pruv_entry(i64 %a.x) #0 {
entry:
  %ok = icmp sge i64 %a.x, 0
  %neg = sub i64 0, %a.x
  %p = select i1 %ok, i64 %a.x, i64 %neg
  %s = insertvalue { i1, i64 } undef, i1 %ok, 0
  %r = insertvalue { i1, i64 } %s, i64 %p, 1
  ret { i1, i64 } %r
}

define void @pruv_abi_get_res(ptr sret({ i64, i64 }) align 8 %sret, i64 %a.x) {
entry:
  %r = call { i1, i64 } @get_res__pruv_entry(i64 %a.x)
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
