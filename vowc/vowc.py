"""vowc: Vow compiler CLI.  python vowc/vowc.py in.vow -o out.rs [--no-verify]"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vast import VowError  # noqa: E402
from vparser import parse  # noqa: E402
from check import check  # noqa: E402
from codegen import gen_rust  # noqa: E402


def compile_file(path, out, verify=True):
    src = open(path).read()
    prog = parse(src)
    check(prog)
    if verify:
        from verify import verify_program
        errs = verify_program(prog)
        if errs:
            return errs
    with open(out, "w") as fh:
        fh.write(gen_rust(prog))
    return []


def main(argv):
    if len(argv) < 4 or argv[2] != "-o":
        print("usage: vowc.py in.vow -o out.rs [--no-verify]")
        return 2
    try:
        errs = compile_file(argv[1], argv[3], "--no-verify" not in argv)
    except VowError as e:
        errs = [e]
    if errs:
        for e in errs:
            print(e.to_json())
        return 1
    print(json.dumps({"ok": True}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
