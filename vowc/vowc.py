"""vowc: Vow compiler CLI.

  python vowc/vowc.py in.vow -o OUT [--no-verify] [--trust-callers]
                      [--backend rust|llvm] [--rust-bindings PATH]

--no-verify      skip the proof; emit safe code (checked indexing/arithmetic)
--trust-callers  public entry points skip the run-time `requires` check (benchmarking)
--backend        rust (default): OUT is Rust source.
                 llvm: OUT is textual LLVM IR (.ll); Rust bindings are written to
                 --rust-bindings PATH (default: OUT with the extension changed to .rs;
                 it is a usage error if that equals OUT).
--rust-bindings  llvm backend only; giving it with the rust backend is a usage error.

Language errors: JSON lines on stdout, exit 1.  Success: {"ok": true}, exit 0.
Usage errors: usage text, exit 2.
Internal compiler errors (any non-VowError exception): one JSON line with
stage "internal", code "internal_error" on stdout, exit 3.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vast import VowError  # noqa: E402
from vparser import parse  # noqa: E402
from check import check  # noqa: E402
from codegen import gen_rust  # noqa: E402

USAGE = ("usage: vowc.py in.vow -o OUT [--no-verify] [--trust-callers] "
         "[--backend rust|llvm] [--rust-bindings PATH]")


def default_bindings_path(out):
    return os.path.splitext(out)[0] + ".rs"


def compile_file(path, out, verify=True, trust_callers=False, backend="rust", rust_bindings=None):
    src = open(path).read()
    prog = parse(src)
    check(prog)
    if verify:
        from verify import verify_program
        errs = verify_program(prog)
        if errs:
            return errs
    if backend == "llvm":
        from llvmgen import gen_llvm  # lazy: only the llvm backend needs it
        ir, bindings = gen_llvm(prog, verified=verify, trust_callers=trust_callers)
        with open(out, "w") as fh:
            fh.write(ir)
        with open(rust_bindings or default_bindings_path(out), "w") as fh:
            fh.write(bindings)
    else:
        with open(out, "w") as fh:
            fh.write(gen_rust(prog, verified=verify, trust_callers=trust_callers))
    return []


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        print(USAGE)
        print("vowc.py: error: " + message, file=sys.stderr)
        sys.exit(2)


def main(argv):
    ap = _Parser(prog="vowc.py", usage=USAGE, add_help=False)
    ap.add_argument("input")
    ap.add_argument("-o", dest="out", required=True)
    ap.add_argument("--no-verify", action="store_true")
    ap.add_argument("--trust-callers", action="store_true")
    ap.add_argument("--backend", choices=["rust", "llvm"], default="rust")
    ap.add_argument("--rust-bindings", default=None)
    a = ap.parse_args(argv[1:])
    if a.rust_bindings is not None and a.backend != "llvm":
        ap.error("--rust-bindings requires --backend llvm")
    bindings = a.rust_bindings
    if a.backend == "llvm":
        if bindings is None:
            bindings = default_bindings_path(a.out)
        if os.path.abspath(bindings) == os.path.abspath(a.out):
            ap.error("--rust-bindings path must differ from -o path")
    try:
        errs = compile_file(a.input, a.out, not a.no_verify, a.trust_callers, a.backend, bindings)
    except VowError as e:
        errs = [e]
    except Exception as e:  # compiler-internal failure, not a language error
        print(json.dumps({"stage": "internal", "line": 0, "col": 0,
                          "code": "internal_error", "message": str(e), "fix": ""}))
        return 3
    if errs:
        for e in errs:
            print(e.to_json())
        return 1
    print(json.dumps({"ok": True}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
