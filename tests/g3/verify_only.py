#!/usr/bin/env python3
"""G3 A2: parse + check + verify one .pruv with the Python verifier and stop before code generation.

    python tests/g3/verify_only.py [--infer] FILE

Prints one JSON line per verification error (like pruvc), or {"ok": true}. Exit 0 = the program type-checks and
every obligation (generic definitions included) is proved; exit 1 = a language error; exit 3 = internal failure.
The code generators still reject generics (G3 A2), so a positive generic example cannot go through `pruvc`;
tests/run_all.py runs the tests/g3/proof/*.pruv group through this script.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "pruvc"))

from vast import PruvError   # noqa: E402
from vparser import parse    # noqa: E402
from check import check      # noqa: E402


def main(argv):
    args = [a for a in argv[1:] if a != "--infer"]
    infer = "--infer" in argv[1:]
    if len(args) != 1:
        print("usage: verify_only.py [--infer] FILE", file=sys.stderr)
        return 2
    try:
        with open(args[0], encoding="utf-8") as fh:
            src = fh.read()
        prog = parse(src)
        check(prog)
        from verify import verify_program
        errs = verify_program(prog, infer=infer)
    except PruvError as e:
        errs = [e]
    except Exception as e:   # compiler-internal failure
        print(json.dumps({"stage": "internal", "code": "internal_error", "message": str(e)}))
        return 3
    for e in errs:
        print(e.to_json())
    if errs:
        return 1
    print(json.dumps({"ok": True}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
