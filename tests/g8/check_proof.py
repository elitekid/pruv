"""A1 proof isolation and per-compile bundle verification, in a disposable package."""
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
# A bound present in both sum bodies' invariants but absent from the public contract.
CLIENT = """mod std;
pub fn f(a: [i64]) -> ()
 requires len(a) <= 1000000
 requires forall k in 0..len(a): -1000000000 <= a[k] && a[k] <= 1000000000
{
 let s: i64 = crate::std::sum_i64(a);
 assert s <= 1000000000 * len(a);
}
"""


def main(work):
    work = Path(work) / "g8_proof_bundle"
    package = work / "distribution"
    shutil.copytree(ROOT / "pruvc", package / "pruvc", ignore=shutil.ignore_patterns("__pycache__"))
    (package / "stdlib").mkdir()
    bundle = package / "stdlib/std.pruv"
    source = (ROOT / "stdlib/std.pruv").read_text()
    bundle.write_text(source)
    app = work / "app"
    app.mkdir()
    root = app / "root.pruv"
    root.write_text("mod std;\n")
    out = work / "out"
    sys.path.insert(0, str(package / "pruvc"))
    from pruvc import compile_file
    import verify
    from modules import load_program
    from check import check
    from vparser import parse
    # Both implementations keep the exact approved public headers.
    sys.path.insert(0, str(ROOT / "tests/g8"))
    from check_bundle import canonical

    def compile(backend="rust", verified=True):
        errors = compile_file(str(root), str(out), verify=verified, backend=backend)
        assert out.exists() == (not errors), "artifact disagrees with compile result"
        if out.exists():
            out.unlink()
        return errors

    def success(errors, backend="rust"):
        assert not errors, [vars(e) for e in errors]

    # Time only ordinary verification of the import-only program in one compile.
    ordinary_verify = verify.verify_program
    durations = []

    def timed(program, *args, **kwargs):
        assert len(program.functions) == 12
        start = time.perf_counter()
        errors = ordinary_verify(program, *args, **kwargs)
        durations.append(time.perf_counter() - start)
        return errors

    verify.verify_program = timed
    try:
        success(compile())
    finally:
        verify.verify_program = ordinary_verify
    assert len(durations) == 1
    print("bundle: 12 bodies, inference disabled, %.6f seconds" % durations[0])
    for text in alias_roots(app, bundle):
        root.write_text(text)
        success(compile())
    root.write_text("mod std;\n")

    # The unused last function must be re-proved even after a prior successful compile,
    # and on the next fresh compile in the same process (no persistent success cache).
    broken = source.replace("ensures len(result) == len(a)", "ensures len(result) == len(a) + 1")
    assert broken != source
    bundle.write_text(broken)
    for backend in ("rust", "llvm"):
        for _ in range(2):
            errors = compile(backend)
            assert errors and all(e.stage == "verify" for e in errors), [vars(e) for e in errors]
            assert any(e.code == "ensures" and e.file == "@std/std.pruv" for e in errors)
    # No-verify must skip SMT for both a false user assertion and the broken bundle.
    root.write_text("mod std;\npub fn f() -> () { assert false; }\n")
    def forbidden(*args, **kwargs):
        raise AssertionError("--no-verify entered SMT verification")
    verify.verify_program = forbidden
    try:
        for backend in ("rust", "llvm"):
            success(compile(backend, verified=False), backend)
    finally:
        verify.verify_program = ordinary_verify

    # Unknown also fails with its original bundled-resource diagnostic.
    from vast import PruvError
    def unknown(program, *args, **kwargs):
        return [PruvError("verify", 1, 1, "verify_unknown", "solver unknown", "",
                          file="@std/std.pruv")]
    verify.verify_program = unknown
    try:
        for backend in ("rust", "llvm"):
            errors = compile(backend)
            assert [(e.stage, e.code, e.file) for e in errors] == [
                ("verify", "verify_unknown", "@std/std.pruv")]
    finally:
        verify.verify_program = ordinary_verify

    # Move the increment before the addition: a distinct implementation, same headers.
    alternative = source.replace("s = s + a[i];\n    i = i + 1;",
                                 "i = i + 1;\n    s = s + a[i - 1];")
    assert source != alternative
    assert canonical(parse(source)) == canonical(parse(alternative))
    # This bound is available in both sum bodies' invariants but absent from the
    # public contract. One-step aggregate unfolding cannot supply general induction.
    observations = []
    for implementation in (source, alternative):
        bundle.write_text(implementation)
        root.write_text("mod std;\n")
        for backend in ("rust", "llvm"):
            success(compile(backend), backend)
        root.write_text(CLIENT)
        program = load_program(str(root))
        check(program)
        # Capture the caller's actual proof inputs, not just matching diagnostics.
        original_prove = verify.FnVerifier.prove
        facts = []
        def capture(self, state, guards, obligation, node, *args, **kwargs):
            if self.f.file == "root.pruv":
                facts.append(([p.sexpr() for p in state.pc],
                              [g.sexpr() for g in guards], obligation.sexpr()))
            return original_prove(self, state, guards, obligation, node, *args, **kwargs)
        verify.FnVerifier.prove = capture
        try:
            errors = ordinary_verify(program)
        finally:
            verify.FnVerifier.prove = original_prove
        assert errors and all(e.file == "root.pruv" and e.code == "assert" for e in errors), [vars(e) for e in errors]
        observations.append(facts)
        for backend in ("rust", "llvm"):
            errors = compile(backend)
            assert errors and all(e.stage == "verify" and e.file == "root.pruv" and e.code == "assert"
                                  for e in errors), [vars(e) for e in errors]
    assert observations[0] and observations[0] == observations[1], "body leaked into caller obligations/facts"
    print("unused false ensures: 4 rejections; no-verify: 2; unknown: 2; alternative bodies: 4 proofs; isolated callers: 4 backend rejections, 2 trace captures")


def alias_roots(app, target):
    """A module file that is a link to the bundle is a separate module, never a std alias (both import orders)."""
    mirror = app / "mirror.pruv"
    if mirror.is_symlink() or mirror.exists():
        mirror.unlink()
    mirror.symlink_to(target)
    for text in ("mod std;\nmod mirror;\n", "mod mirror;\nmod std;\n"):
        yield text
    mirror.unlink()


def rs_main(work, binary):
    """The same cases against pruvc-rs: the bundle is embedded, so each variant is a patched binary copy."""
    import json
    import subprocess
    work = Path(work) / "g8_proof_bundle_rs"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    source = (ROOT / "stdlib/std.pruv").read_bytes()
    image = Path(binary).read_bytes()
    assert image.count(source) == 1, "embedded bundle not found exactly once"

    def variant(name, text):
        # Same length keeps every offset in the binary valid.
        assert len(text) == len(source) and text != source
        path = work / name
        path.write_bytes(image.replace(source, text))
        path.chmod(0o755)
        if sys.platform == "darwin":
            subprocess.run(["codesign", "-f", "-s", "-", str(path)], check=True, capture_output=True)
        return path

    exe = work / "pruvc"
    shutil.copy2(binary, exe)
    app = work / "app"
    app.mkdir()
    root = app / "root.pruv"
    out = work / "out"

    def compile(exe, backend="rust", verified=True):
        argv = [str(exe), str(root), "-o", str(out), "--backend", backend] + ([] if verified else ["--no-verify"])
        c = subprocess.run(argv, capture_output=True, text=True, timeout=300)
        assert out.exists() == (c.returncode == 0), (c.returncode, c.stdout, c.stderr)
        if c.returncode == 0:
            out.unlink()
            return None
        ds = [json.loads(l) for l in (c.stdout + c.stderr).splitlines() if l.startswith("{")]
        assert ds, (c.stdout, c.stderr)
        return ds

    def success(ds, backend="llvm"):
        assert ds is None, ds

    root.write_text("mod std;\n")
    for backend in ("rust", "llvm"):
        success(compile(exe, backend), backend)
    aliases = 0
    for text in alias_roots(app, ROOT / "stdlib/std.pruv"):
        root.write_text(text)
        success(compile(exe), "rust")
        aliases += 1

    broken = variant("pruvc_broken", source.replace(b"ensures len(result) == len(a)",
                                                    b"ensures len(result) != len(a)"))
    root.write_text("mod std;\n")
    for backend in ("rust", "llvm"):
        for _ in range(2):
            ds = compile(broken, backend)
            assert all(d["stage"] == "verify" for d in ds), ds
            assert any(d["code"] == "ensures" and d["file"] == "@std/std.pruv" for d in ds), ds
    root.write_text("mod std;\npub fn f() -> () { assert false; }\n")
    for backend in ("rust", "llvm"):
        success(compile(broken, backend, verified=False), backend)

    # Same distinct sum body as the Python check, with the indentation trimmed to keep the length.
    alternative = variant("pruvc_alternative", source.replace(b"s = s + a[i];\n    i = i + 1;",
                                                              b"i = i + 1;\ns = s + a[i - 1];"))
    observations = []
    for implementation in (exe, alternative):
        root.write_text("mod std;\n")
        for backend in ("rust", "llvm"):
            success(compile(implementation, backend), backend)
        root.write_text(CLIENT)
        ds = compile(implementation)
        assert all(d["file"] == "root.pruv" and d["code"] == "assert" for d in ds), ds
        observations.append([{k: v for k, v in d.items() if k != "counterexample"} for d in ds])
    assert observations[0] == observations[1], observations
    print("rs: alias orders: %d; unused false ensures: 4 rejections; no-verify: 2; alternative bodies: 4 proofs; "
          "isolated callers: 2 rejections" % aliases)


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[2] == "--rs":
        rs_main(sys.argv[1], sys.argv[3])
    else:
        main(sys.argv[1])
