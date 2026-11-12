#!/usr/bin/env python3
"""Regenerate (or with --check, verify) bridge/node/gen/*_gen.rs from bench/l0/*.pruv.

Uses the Python reference compiler. If verification fails, the compiler's exit
code is returned and nothing is overwritten: the bridge must not be built.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
GEN = Path(__file__).resolve().parent / "gen"
NAMES = ["clip_bytes", "host_within"]


def main() -> int:
    check = "--check" in sys.argv[1:]
    stale = []
    with tempfile.TemporaryDirectory() as tmp:
        for name in NAMES:
            out = Path(tmp) / f"{name}_gen.rs"
            src = ROOT / "bench" / "l0" / f"{name}.pruv"
            r = subprocess.run(
                [sys.executable, str(ROOT / "pruvc" / "pruvc.py"), str(src), "-o", str(out)],
                cwd=str(ROOT),
            )
            if r.returncode != 0:
                print(f"compile failed for {name}", file=sys.stderr)
                return r.returncode
            dest = GEN / f"{name}_gen.rs"
            new = out.read_bytes()
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
