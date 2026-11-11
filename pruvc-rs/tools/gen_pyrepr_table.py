#!/usr/bin/env python3
"""Generator for pruv-core/src/pyrepr_table.rs, based on str.isprintable of the development Python (.venv, 3.9.6, Unicode 13.0).
It copies the character ranges that Python repr(str) rewrites as \\x/\\u/\\U so the parse error message (bad_char) is byte-identical.
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
out = ["//! Generated file: pruvc-rs/tools/gen_pyrepr_table.py (Python %s, Unicode %s). Do not edit by hand."
       % (sys.version.split()[0], unicodedata.unidata_version),
       "//! Code point ranges for which Python str.isprintable() is false (closed intervals, ascending).",
       "",
       "pub const NONPRINTABLE: &[(u32, u32)] = &["]
for a, b in ranges:
    out.append("    (0x%X, 0x%X)," % (a, b))
out.append("];")
sys.stdout.write("\n".join(out) + "\n")
