"""pruvc: Pruv compiler CLI.

  python pruvc/pruvc.py in.pruv -o OUT [--no-verify] [--trust-callers]
                      [--backend rust|llvm] [--rust-bindings PATH] [--infer [--show-inferred]]

--no-verify      skip the proof; emit safe code (checked indexing/arithmetic)
--infer          STAGE1 B2: infer loop invariants from fixed templates (Houdini) and use the surviving
                 ones as extra invariants in the proof (docs/STAGE1_B_INFER.md). Off by default; without it
                 the proof and its solver queries are unchanged. Generated code is unchanged.
--show-inferred  with --infer only (otherwise a usage error): one JSON line per loop on stderr (fn, loop,
                 line, col, status, invariants, generated, capped, kept, dropped, rounds, queries).
                 With --no-verify the single line {"status": "skipped_no_verify"}.
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
Internal compiler errors (any non-PruvError exception): one JSON line with
stage "internal", code "internal_error" on stdout, exit 3.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vast import PruvError  # noqa: E402
from vparser import parse  # noqa: E402
from check import check  # noqa: E402
from codegen import gen_rust  # noqa: E402
from typeinfo import g2_unimplemented_error, g3_unimplemented_error  # noqa: E402

USAGE = ("usage: pruvc.py in.pruv -o OUT [--no-verify] [--trust-callers] "
         "[--backend rust|llvm] [--rust-bindings PATH] [--infer [--show-inferred]]")


def default_bindings_path(out):
    return os.path.splitext(out)[0] + ".rs"


def compile_file(path, out, verify=True, trust_callers=False, backend="rust", rust_bindings=None,
                 budget=None, also_llvm=None, infer=False, show_inferred=False):
    if budget is None:
        budget = 1 << 30
    assert 1 <= budget <= 2 ** 62
    if also_llvm and backend != "rust":
        raise ValueError("also_llvm requires backend='rust'")
    src = open(path, encoding="utf-8").read()
    prog = parse(src)
    check(prog)
    # G3 A1 staging guard: the verifier and both code generators do not support generics yet; reject explicitly
    # (also with --no-verify) instead of crashing. Removed when the later G3 batches land.
    g3err = g3_unimplemented_error(prog, "codegen")
    if g3err is not None:
        return [g3err]
    if verify:
        from verify import verify_program
        if infer:
            report = [] if show_inferred else None
            errs = verify_program(prog, infer=True, report=report)
            for rec in report or []:
                print(json.dumps(rec, sort_keys=True, ensure_ascii=False), file=sys.stderr)
        else:
            errs = verify_program(prog)
        if errs:
            return errs
    elif infer and show_inferred:
        print(json.dumps({"status": "skipped_no_verify"}, sort_keys=True, ensure_ascii=False), file=sys.stderr)
    # G2: runs after verify too; array types that have no code-generation layer yet are rejected.
    # [u8] (A3·A4), [bool] (A5) and str (B2) are implemented by every back end.
    g2err = g2_unimplemented_error(prog, "codegen", skip=("array_u8", "array_bool", "str"))  # G2 B2
    if g2err is not None:
        return [g2err]
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
        print("pruvc.py: error: " + message, file=sys.stderr)
        sys.exit(2)


def main(argv):
    ap = _Parser(prog="pruvc.py", usage=USAGE, add_help=False)
    ap.add_argument("input")
    ap.add_argument("-o", dest="out", required=True)
    ap.add_argument("--no-verify", action="store_true")
    ap.add_argument("--trust-callers", action="store_true")
    ap.add_argument("--backend", choices=["rust", "llvm"], default="rust")
    ap.add_argument("--rust-bindings", default=None)
    ap.add_argument("--infer", action="store_true")
    ap.add_argument("--show-inferred", dest="show_inferred", action="store_true")
    ap.add_argument("--contract-budget", dest="budget", type=int, default=None,
                    help=argparse.SUPPRESS)
    ap.add_argument("--also-llvm", dest="also_llvm", nargs=2, metavar=("LL", "RS"), default=None,
                    help=argparse.SUPPRESS)
    a = ap.parse_args(argv[1:])
    if a.show_inferred and not a.infer:
        ap.error("--show-inferred requires --infer")
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
                          a.budget, tuple(a.also_llvm) if a.also_llvm else None,
                          infer=a.infer, show_inferred=a.show_inferred)
    except PruvError as e:
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
