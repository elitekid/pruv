"""Inspect std linkage/checks and compare every positive G8 root's LLVM artifacts."""
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pruvc"))
from pruvc import compile_file
from vparser import parse


def main(work, binary=None):
    work = Path(work) / "g8_llvm"
    work.mkdir()
    names = [f.name for f in parse((ROOT / "stdlib/std.pruv").read_text()).functions]
    inventory = json.loads((ROOT / "tests/g8/fixtures.json").read_text())
    roots = [e["root"] for key in ("frontend", "proof") for e in inventory[key]]
    roots += inventory["runtime"] + inventory["examples"]
    compared = 0
    for index, src in enumerate(roots):
        for mode, flags in (("verified", []), ("safe", ["--no-verify"]),
                            ("trust", ["--no-verify", "--trust-callers"])):
            # The unsafe-input runtime root deliberately cannot verify.
            if "g8_r16_" in src and mode == "verified":
                continue
            ll, bindings = work / "py.ll", work / "py.rs"
            errors = compile_file(str(ROOT / src), str(ll), backend="llvm",
                                  rust_bindings=str(bindings), verify=not flags,
                                  trust_callers="--trust-callers" in flags)
            assert not errors, (src, mode, [vars(e) for e in errors])
            text, bind = ll.read_text(), bindings.read_text()
            definitions = re.findall(r"^define ([^\n]+)", text, re.M)
            for name in names:
                stem = "pruv_m_f_2_3_std_%d_%s" % (len(name), name)
                own = [line for line in definitions if "@" + stem + "__" in line]
                assert own and all(line.startswith(("internal ", "private ")) for line in own), (src, name)
                assert stem not in bind, (src, name)
                if flags and name in ("clamp_i64", "abs_i64", "sum_i64", "array_max_i64"):
                    assert any("__pruv_entry(" in line for line in own), name
            exported = re.findall(r"^define (?!internal\b|private\b)[^\n@]*@([^ (]+)\(", text, re.M)
            root_names = [f.name for f in parse((ROOT / src).read_text()).functions if f.pub]
            assert sorted(exported) == sorted("pruv_abi_" + n for n in root_names), (src, exported)
            assert sorted(re.findall(r'    fn (pruv_abi_\w+)\(', bind)) == sorted(exported), src
            if flags:
                assert "call void @pruv_panic_oob(" in text
                assert "call void @pruv_panic_arith(" in text
                assert "call { i64, i1 } @llvm.sadd.with.overflow.i64" in text
            # The catalog coexistence fixture intentionally has a G6 foreign operation.
            if "/catalog/" not in src:
                assert "pruv_foreign" not in text and "pruv_foreign" not in bind, src
            if binary:
                rsll, rsbind = work / "rs.ll", work / "rs.rs"
                c = subprocess.run([binary, str(ROOT / src), "--backend", "llvm", "-o", str(rsll),
                                    "--rust-bindings", str(rsbind), *flags],
                                   capture_output=True, text=True, timeout=120)
                assert c.returncode == 0, (src, mode, c.stdout, c.stderr)
                assert ll.read_bytes() == rsll.read_bytes(), (src, mode, "IR mismatch")
                assert bindings.read_bytes() == rsbind.read_bytes(), (src, mode, "bindings mismatch")
                compared += 1
    print("%d roots: linkage, exports, safe checks; %d IR/binding pairs byte-equal" % (len(roots), compared))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[3] if len(sys.argv) == 4 and sys.argv[2] == "--rs" else None)
