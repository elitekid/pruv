#!/bin/sh
# Fails if an executable's dynamic dependencies are tied to the development machine, the build directory, or an external libz3/libLLVM.
#
# Usage: sh ci/m3/check_deps.sh EXE [EXE ...]
# Env:   CHECK_DEPS_BUILD_DIR  absolute path of the build directory (default: current directory). Fails if this path appears in the dependency list.
# Exit codes: 0 pass, 1 forbidden entry found, 2 usage or tool error.
#
# macOS uses `otool -L`, Linux uses `ldd`. The first line of otool output is the file's own path, so it is skipped
# (to avoid false positives when the executable lives inside the build directory).

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
    # A failure of the tool itself (not Mach-O/ELF, etc.) is handled separately from the forbidden list.
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

    # Linux: a dependency that ldd marks 'not found' is an unresolved library, so it fails.
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
