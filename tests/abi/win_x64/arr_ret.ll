; Windows x64 표본: 배열 반환은 기존 '마지막 명시 out 포인터 + void' 유지. 숨은 sret 없음.
; out 은 { ptr, i64 } (포인터, 길이) 를 받는다. 본문은 입력 슬라이스를 그대로 돌려준다.
target datalayout = "e-m:w-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-f80:128-n8:16:32:64-S128"
target triple = "x86_64-pc-windows-msvc"

define internal { ptr, i64 } @arr__pruv_entry(ptr %a.v.a, i64 %a.v.n) #0 {
entry:
  %s = insertvalue { ptr, i64 } undef, ptr %a.v.a, 0
  %r = insertvalue { ptr, i64 } %s, i64 %a.v.n, 1
  ret { ptr, i64 } %r
}

define void @pruv_abi_arr(ptr %a.v.a, i64 %a.v.n, ptr %out) {
entry:
  %r = call { ptr, i64 } @arr__pruv_entry(ptr %a.v.a, i64 %a.v.n)
  %x0 = extractvalue { ptr, i64 } %r, 0
  %x1 = extractvalue { ptr, i64 } %r, 1
  %o0 = getelementptr inbounds { ptr, i64 }, ptr %out, i32 0, i32 0
  %o1 = getelementptr inbounds { ptr, i64 }, ptr %out, i32 0, i32 1
  store ptr %x0, ptr %o0
  store i64 %x1, ptr %o1
  ret void
}

attributes #0 = { noinline }
