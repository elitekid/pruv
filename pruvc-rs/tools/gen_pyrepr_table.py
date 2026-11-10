#!/usr/bin/env python3
"""pruv-core/src/pyrepr_table.rs 생성기. 개발 Python(.venv, 3.9.6, Unicode 13.0)의 str.isprintable 기준.
Python repr(str) 이 \\x/\\u/\\U 로 바꾸는 문자 범위를 그대로 옮겨 parse 오류 문장(bad_char)을 바이트 동일하게 맞춘다.
    .venv/bin/python pruvc-rs/tools/gen_pyrepr_table.py > pruvc-rs/crates/pruv-core/src/pyrepr_table.rs
"""
import sys
import unicodedata

ranges = []
start = None
for cp in range(0x110000):
    np = not chr(cp).isprintable()
    if np and start is None:
        start = cp
    elif not np and start is not None:
        ranges.append((start, cp - 1)); start = None
if start is not None:
    ranges.append((start, 0x10FFFF))
out = ["//! 생성 파일: pruvc-rs/tools/gen_pyrepr_table.py (Python %s, Unicode %s). 손으로 고치지 않는다."
       % (sys.version.split()[0], unicodedata.unidata_version),
       "//! Python str.isprintable() 이 거짓인 코드 포인트 범위(닫힌 구간, 오름차순).",
       "",
       "pub const NONPRINTABLE: &[(u32, u32)] = &["]
for a, b in ranges:
    out.append("    (0x%X, 0x%X)," % (a, b))
out.append("];")
sys.stdout.write("\n".join(out) + "\n")
