#!/bin/sh
# 실행 파일의 동적 의존이 개발 머신/빌드 폴더/외부 libz3·libLLVM 에 묶여 있으면 실패한다.
#
# 사용: sh ci/m3/check_deps.sh EXE [EXE ...]
# 환경: CHECK_DEPS_BUILD_DIR  빌드 폴더 절대 경로(기본: 현재 폴더). 이 경로가 의존 목록에 나오면 실패.
# 종료 코드: 0 통과, 1 금지 항목 발견, 2 사용법·도구 오류.
#
# macOS 는 `otool -L`, Linux 는 `ldd` 를 쓴다. otool 의 첫 줄은 파일 자신의 경로이므로 건너뛴다
# (실행 파일이 빌드 폴더 안에 있어도 오탐하지 않게).

set -u

if [ "$#" -lt 1 ]; then
    echo "usage: $0 EXE [EXE ...]" >&2
    exit 2
fi

build_dir=${CHECK_DEPS_BUILD_DIR:-$(pwd)}

case "$(uname -s)" in
    Darwin)
        list_deps() { otool -L "$1" 2>&1 | sed 1d; }
        tool=otool
        ;;
    Linux)
        list_deps() { ldd "$1" 2>&1; }
        tool=ldd
        ;;
    *)
        echo "check_deps: unsupported OS $(uname -s)" >&2
        exit 2
        ;;
esac

if ! command -v "$tool" >/dev/null 2>&1; then
    echo "check_deps: $tool not found" >&2
    exit 2
fi

status=0
for exe in "$@"; do
    if [ ! -f "$exe" ]; then
        echo "check_deps: no such file: $exe" >&2
        status=2
        continue
    fi
    deps=$(list_deps "$exe")
    # 도구 자체가 실패한 경우(Mach-O/ELF 아님 등)는 금지 목록과 따로 취급한다.
    case "$deps" in
        *"not a Mach-O"*|*"not a dynamic executable"*|*"is not an object file"*|*"No such file"*)
            echo "check_deps: $tool could not read $exe:" >&2
            echo "$deps" >&2
            status=2
            continue
            ;;
    esac

    bad=""
    for pat in "/opt/homebrew" "/usr/local/Cellar" "/usr/local/opt" "/usr/local/lib" "$build_dir" "libz3" "libLLVM" "libzstd" "@rpath/"; do
        [ -n "$pat" ] || continue
        hit=$(printf '%s\n' "$deps" | grep -F -e "$pat")
        if [ -n "$hit" ]; then
            bad="$bad
[$pat]
$hit"
        fi
    done

    # Linux: ldd 가 'not found' 로 표시한 의존은 해석되지 않는 라이브러리이므로 실패.
    if [ "$tool" = ldd ]; then
        nf=$(printf '%s\n' "$deps" | grep -F -e "not found")
        if [ -n "$nf" ]; then
            bad="$bad
[not found]
$nf"
        fi
    fi

    if [ -n "$bad" ]; then
        echo "FAIL $exe: forbidden dependency$bad" >&2
        [ "$status" -eq 2 ] || status=1
    else
        echo "OK   $exe"
    fi
done
exit "$status"
