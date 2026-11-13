#!/usr/bin/env python3
"""Regenerate (or with --check, verify) bridge/node/gen/*_gen.rs from bench/l0/*.pruv.

Uses both compilers and requires byte-identical output. If verification fails, the compiler's exit
code is returned and nothing is overwritten: the bridge must not be built.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
GEN = Path(__file__).resolve().parent / "gen"
NAMES = ["clip_bytes", "host_within", "version_at_least", "col_letters", "term_plain", "decode_bytes", "zip_total", "encode_png", "split_text", "group_text", "image_shrink", "number_ranges", "clip_sheet", "kind_of", "row_pieces", "sheet_chunks", "text_around", "parse_html", "docx_parts", "tokenize", "doc_labels", "join_ranges", "cut_cell", "sheet_range", "page_ranges", "grouped_number", "under_root"]
# Sources with trusted adapters need the adapter crate to verify against.
EXTERN = {"decode_bytes": "decode"}
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / 'bench' / 'l0'))
from run import build_decode_adapter, configure, WORK


def main() -> int:
    check = "--check" in sys.argv[1:]
    stale = []
    g2, _ = configure()
    flags = {"decode": build_decode_adapter()[0]}
    with tempfile.TemporaryDirectory(dir=WORK) as tmp:
        for name in NAMES:
            out = Path(tmp) / f"{name}_gen.rs"
            src = ROOT / "bench" / "l0" / f"{name}.pruv"
            extra = flags[EXTERN[name]] if name in EXTERN else []
            r = subprocess.run(
                g2.COMPILERS['py'] + [str(src), "-o", str(out)] + extra,
                cwd=str(ROOT),
            )
            if r.returncode != 0:
                print(f"compile failed for {name}", file=sys.stderr)
                return r.returncode
            dest = GEN / f"{name}_gen.rs"
            new = out.read_bytes()
            rs_out = Path(tmp) / f"{name}_rs.rs"
            r = subprocess.run(g2.COMPILERS['rs'] + [str(src), '-o', str(rs_out)] + extra, cwd=ROOT)
            if r.returncode:
                return r.returncode
            if rs_out.read_bytes() != new:
                print(f"compiler outputs differ: {name}", file=sys.stderr)
                return 1
            if check:
                if not dest.exists() or dest.read_bytes() != new:
                    stale.append(str(dest))
            else:
                dest.write_bytes(new)
                print(f"wrote {dest}")
    if stale:
        for s in stale:
            print(f"out of date: {s}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
