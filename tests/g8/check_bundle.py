"""G8 A0 resource/surface checks, invoked only by run_all's g8_frontend group."""
import dataclasses
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pruvc"))
from vparser import parse
from modules import load_program


def canonical(value):
    if dataclasses.is_dataclass(value):
        return (type(value).__name__, {f.name: canonical(getattr(value, f.name))
                for f in dataclasses.fields(value) if f.name not in ("line", "col", "body")})
    if isinstance(value, (list, tuple)):
        return [canonical(v) for v in value]
    return value


def main(work):
    source = (ROOT / "stdlib/std.pruv").read_text()
    listing = (ROOT / "docs/G8_SPEC.md").read_text().split("## 4.")[1].split("```pruv\n")[1].split("```")[0]
    headers = listing.strip().split("\n\n")
    approved = parse("\n\n".join(h + "\n{}" for h in headers))
    actual = parse(source)
    assert len(actual.functions) == len(actual.items) == 12 and not actual.mods
    assert canonical(actual) == canonical(approved), "parsed public headers changed"
    for f, h in zip(actual.functions, headers):
        assert f.pub and f.body
        assert not f.tparams and f.cost is None and f.decreases is None
        assert h + "\n{" in source, "header text changed"
    assert not re.search(r"\b(trusted|rust|crate|mod)\b", source)

    work = Path(work) / "g8_resources"
    work.mkdir()
    package = work / "distribution"
    shutil.copytree(ROOT / "pruvc", package / "pruvc", ignore=shutil.ignore_patterns("__pycache__"))
    (package / "stdlib").mkdir()
    bundle = package / "stdlib/std.pruv"
    bundle.write_text(source)
    app = work / "app"
    app.mkdir()
    root = app / "root.pruv"
    root.write_text("mod std;\npub fn f() -> i64 { return 1; }\n")
    cwd = work / "unrelated"
    cwd.mkdir()

    def compile_with(compiler, src=root, backend="rust", flags=()):
        return subprocess.run([sys.executable, str(compiler), str(src), "-o", str(work / "out"),
                               "--backend", backend, *flags], cwd=cwd, text=True,
                              capture_output=True, timeout=60)

    def expect(stage, code, file, message=None):
        for backend in ("rust", "llvm"):
            c = compile_with(package / "pruvc/pruvc.py", backend=backend)
            ds = [json.loads(line) for line in c.stdout.splitlines() if line.startswith("{")]
            assert c.returncode == 1 and len(ds) == 1, c.stdout + c.stderr
            d = ds[0]
            assert (d["stage"], d["code"], d.get("file")) == (stage, code, file), d
            if message:
                assert d["message"] == message, d
            assert str(package) not in c.stdout
            assert not (work / "out").exists()

    expect("codegen", "unsupported_type", "root.pruv", "G8 std verification is not implemented yet")
    root.write_text("mod child;\nmod std;\nmod after;\n")
    (app / "child.pruv").write_text("pub fn f() -> () {}")
    (app / "after.pruv").write_text("pub fn f() -> () {}")
    loaded = load_program(str(root))
    assert [m.path for m in loaded.modules] == [(), ("child",), ("std",), ("after",)]
    assert loaded.modules[2].file == "@std/std.pruv"
    assert all(f.file == "@std/std.pruv" for f in loaded.modules[2].items)
    root.write_text("mod std;\npub fn f() -> i64 { return 1; }\n")
    bundle.unlink()
    expect("parse", "std_source", "root.pruv")
    bundle.mkdir()  # read failure, independent of permission bits/root privileges
    expect("parse", "std_source", "root.pruv")
    bundle.rmdir()
    bundle.write_bytes(b"\xff")
    expect("parse", "std_source", "root.pruv")
    for kind in ("file", "directory", "dangling"):
        local = app / "std.pruv"
        if kind == "file":
            local.write_text("invalid")
        elif kind == "directory":
            local.mkdir()
        else:
            local.symlink_to("missing")
        expect("parse", "std_module_conflict", "root.pruv")
        local.rmdir() if kind == "directory" else local.unlink()
    root.write_text("mod child;\nmod std;\n")
    (app / "child.pruv").write_text("mod std;\n")
    expect("parse", "std_import_location", "child.pruv")
    root.write_text("mod std;\n")
    bundle.write_text("pub fn broken(")
    c = compile_with(package / "pruvc/pruvc.py")
    d = json.loads(c.stdout.strip())
    assert c.returncode == 1 and d["stage"] == "parse" and d["code"] != "std_source"
    assert d["file"] == "@std/std.pruv", d
    bundle.write_text("pub fn broken() -> i64 { return true; }")
    c = compile_with(package / "pruvc/pruvc.py")
    d = json.loads(c.stdout.strip())
    assert c.returncode == 1 and d["stage"] == "type" and d["file"] == "@std/std.pruv", d
    # Missing std must not affect legacy or ordinary explicit modules.
    bundle.unlink()
    for program in ("fn f() -> i64 { return 1; }", "pub fn f() -> i64 { return 1; }"):
        root.write_text(program)
        for backend in ("rust", "llvm"):
            c = compile_with(package / "pruvc/pruvc.py", backend=backend, flags=("--no-verify",))
            assert c.returncode == 0, c.stdout + c.stderr
            (work / "out").unlink()
    # Frozen pre-G8 outputs cover legacy, explicit modules, and diagnostics.
    compatibility = ROOT / "tests/g8/compatibility.json"
    samples = {
        "legacy": "fn f(x: i64) -> i64 { return x; }",
        "modules": "mod child;\npub fn f(x: i64) -> i64 { return crate::child::f(x); }",
        "diagnostic": "fn f() -> i64 { return true; }",
    }
    (app / "child.pruv").write_text("pub fn f(x: i64) -> i64 { return x; }")
    expected = json.loads(compatibility.read_text())
    for name, program in samples.items():
        root.write_text(program)
        for backend in ("rust", "llvm"):
            for mode, flags in (("default", ()), ("safe", ("--no-verify",))):
                key = "/".join((name, backend, mode))

                def artifacts(compiler):
                    bindings = work / "bindings.rs"
                    output = work / "out"
                    for path in (bindings, output):
                        if path.exists():
                            path.unlink()
                    extra = ("--rust-bindings", str(bindings)) if backend == "llvm" else ()
                    c = compile_with(compiler, backend=backend, flags=flags + extra)
                    assert c.returncode == (1 if name == "diagnostic" else 0), c.stdout + c.stderr
                    return {"exit": c.returncode, "stdout": c.stdout, "stderr": c.stderr,
                            "output": hashlib.sha256(output.read_bytes()).hexdigest() if output.exists() else None,
                            "bindings": hashlib.sha256(bindings.read_bytes()).hexdigest() if bindings.exists() else None}

                got = artifacts(package / "pruvc/pruvc.py")
                assert got == expected[key], (key, got, expected[key])
    print("12 parsed/text headers; relocated cwd; missing/unreadable/UTF-8 resources; conflicts and labels: OK")


if __name__ == "__main__":
    main(sys.argv[1])
