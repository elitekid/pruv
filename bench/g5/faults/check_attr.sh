#!/bin/sh
# direct expected-attribute check: the inout pointer of swap_at must be `ptr noalias nocapture %p.a.a` (no readonly)
set -e
.venv/bin/python pruvc/pruvc.py examples/g5_reverse.pruv -o "${TMPDIR:-/tmp}/g5_rev.ll" --backend llvm --rust-bindings "${TMPDIR:-/tmp}/g5_rev_b.rs" >/dev/null
grep -E '^define .*swap_at' "${TMPDIR:-/tmp}/g5_rev.ll"
if grep -E '^define .*swap_at.*readonly %p\.a\.a' "${TMPDIR:-/tmp}/g5_rev.ll" >/dev/null; then echo "FAIL readonly on inout pointer"; exit 1; fi
grep -E '^define .*swap_at.*ptr noalias nocapture %p\.a\.a' "${TMPDIR:-/tmp}/g5_rev.ll" >/dev/null && echo "PASS inout pointer is mutable"
