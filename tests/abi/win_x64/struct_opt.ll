; Windows x64 표본: 사용자 구조체(내부에 Option 필드). sret 없음.
; struct Pair { a: i64, o: Option<i64> } 는 i64 word 3개(a, tag, payload)로 직렬화된다.
; 입력은 word 배열 포인터, 출력은 마지막 명시 out 포인터. 크기가 16바이트 이하여도 예외 없음.
; bump(p, d) = Pair { a: p.a + d, o: p.o }
target datalayout = "e-m:w-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-f80:128-n8:16:32:64-S128"
target triple = "x86_64-pc-windows-msvc"

define internal { i64, { i1, i64 } } @bump__pruv_entry({ i64, { i1, i64 } } %a.p, i64 %a.d) #0 {
entry:
  %a = extractvalue { i64, { i1, i64 } } %a.p, 0
  %o = extractvalue { i64, { i1, i64 } } %a.p, 1
  %a2 = add i64 %a, %a.d
  %s = insertvalue { i64, { i1, i64 } } undef, i64 %a2, 0
  %r = insertvalue { i64, { i1, i64 } } %s, { i1, i64 } %o, 1
  ret { i64, { i1, i64 } } %r
}

define void @pruv_abi_bump(ptr %a.p, i64 %a.d, ptr %out) {
entry:
  %w0 = getelementptr inbounds i64, ptr %a.p, i64 0
  %w1 = getelementptr inbounds i64, ptr %a.p, i64 1
  %w2 = getelementptr inbounds i64, ptr %a.p, i64 2
  %v0 = load i64, ptr %w0, align 8
  %v1 = load i64, ptr %w1, align 8
  %v2 = load i64, ptr %w2, align 8
  %t = icmp ne i64 %v1, 0
  %g0 = insertvalue { i1, i64 } undef, i1 %t, 0
  %g1 = insertvalue { i1, i64 } %g0, i64 %v2, 1
  %p0 = insertvalue { i64, { i1, i64 } } undef, i64 %v0, 0
  %p1 = insertvalue { i64, { i1, i64 } } %p0, { i1, i64 } %g1, 1
  %r = call { i64, { i1, i64 } } @bump__pruv_entry({ i64, { i1, i64 } } %p1, i64 %a.d)
  %ra = extractvalue { i64, { i1, i64 } } %r, 0
  %ro = extractvalue { i64, { i1, i64 } } %r, 1
  %rt = extractvalue { i1, i64 } %ro, 0
  %rv = extractvalue { i1, i64 } %ro, 1
  %rtz = zext i1 %rt to i64
  %o0 = getelementptr inbounds i64, ptr %out, i64 0
  %o1 = getelementptr inbounds i64, ptr %out, i64 1
  %o2 = getelementptr inbounds i64, ptr %out, i64 2
  store i64 %ra, ptr %o0, align 8
  store i64 %rtz, ptr %o1, align 8
  store i64 %rv, ptr %o2, align 8
  ret void
}

attributes #0 = { noinline }
