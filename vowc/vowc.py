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
--contract-budget N  internal/test-only (overrides the per-entry requires iteration
                 budget, default 2^30; not part of the language spec).
--also-llvm LL RS  internal/test-only (used by bench/fuzz/run.py; not part of the language
                 spec). Rust backend only: in the same single parse+check+verify run, also
                 write the LLVM IR to LL and its Rust bindings to RS. OUT, LL, RS must be
                 pairwise distinct. Verification failure -> no file is written.
                 All texts are generated before any file is written, so a generator error
                 (exit 3) leaves no output from this call.

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


def compile_file(path, out, verify=True, trust_callers=False, backend="rust", rust_bindings=None,
                 budget=None, also_llvm=None):
    if budget is None:
        budget = 1 << 30
    assert 1 <= budget <= 2 ** 62
    if also_llvm and backend != "rust":
        raise ValueError("also_llvm requires backend='rust'")
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
        ir, bindings = gen_llvm(prog, verified=verify, trust_callers=trust_callers, budget=budget)
        with open(out, "w") as fh:
            fh.write(ir)
        with open(rust_bindings or default_bindings_path(out), "w") as fh:
            fh.write(bindings)
    else:
        # generate every text first; write files only after all generators succeeded
        # (gen_rust / gen_llvm do not mutate prog, so they share it)
        rs_text = gen_rust(prog, verified=verify, trust_callers=trust_callers, budget=budget)
        llvm_texts = None
        if also_llvm:
            from llvmgen import gen_llvm
            llvm_texts = gen_llvm(prog, verified=verify, trust_callers=trust_callers, budget=budget)
        with open(out, "w") as fh:
            fh.write(rs_text)
        if llvm_texts is not None:
            with open(also_llvm[0], "w") as fh:
                fh.write(llvm_texts[0])
            with open(also_llvm[1], "w") as fh:
                fh.write(llvm_texts[1])
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
    ap.add_argument("--contract-budget", dest="budget", type=int, default=None,
                    help=argparse.SUPPRESS)
    ap.add_argument("--also-llvm", dest="also_llvm", nargs=2, metavar=("LL", "RS"), default=None,
                    help=argparse.SUPPRESS)
    a = ap.parse_args(argv[1:])
    if a.also_llvm is not None:
        if a.backend != "rust":
            ap.error("--also-llvm requires --backend rust")
        paths = [os.path.abspath(p) for p in [a.out] + a.also_llvm]
        if len(set(paths)) != 3:
            ap.error("-o, --also-llvm LL and RS paths must be pairwise distinct")
    if a.budget is not None and not 1 <= a.budget <= 2 ** 62:
        ap.error("--contract-budget must be in 1..2**62")
    if a.rust_bindings is not None and a.backend != "llvm":
        ap.error("--rust-bindings requires --backend llvm")
    bindings = a.rust_bindings
    if a.backend == "llvm":
        if bindings is None:
            bindings = default_bindings_path(a.out)
        if os.path.abspath(bindings) == os.path.abspath(a.out):
            ap.error("--rust-bindings path must differ from -o path")
    try:
        errs = compile_file(a.input, a.out, not a.no_verify, a.trust_callers, a.backend, bindings,
                          a.budget, tuple(a.also_llvm) if a.also_llvm else None)
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
