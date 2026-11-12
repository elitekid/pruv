"""Inspect ordinary bundled bodies and atomic LLVM staging failures."""
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pruvc"))
from pruvc import compile_file
from vparser import parse


def main(work):
    work = Path(work) / "g8_codegen"
    work.mkdir()
    root = work / "root.pruv"
    root.write_text("mod std;\npub fn f(x: i64) -> i64 { return crate::std::min_i64(x, 0); }\n")
    names = [f.name for f in parse((ROOT / "stdlib/std.pruv").read_text()).functions]
    for verified, trust in ((True, False), (False, False), (False, True)):
        out = work / "out.rs"
        assert not compile_file(str(root), str(out), verify=verified, trust_callers=trust)
        text = out.read_text()
        for name in names:
            stem = "pruv_m_f_2_3_std_%d_%s" % (len(name), name)
            assert re.search(r"^fn " + stem + r"(?:__pruv_body)?\(", text, re.M), name
            assert not re.search(r"pub fn " + stem, text), name
            assert not re.search(r"pub use[^;]*\b" + stem + r"\b", text), name
        assert "#[no_mangle]" not in text
        assert "std::cmp::min" not in text and "std::cmp::max" not in text
        assert "ensures violated" not in text
        assert not (work / "out.rs.foreign.json").exists()
        reverse = text.split("fn pruv_m_f_2_3_std_11_reverse_i64(")[1]
        assert reverse.count("pruv_alloc(") + reverse.count("vec![") == 1
        assert ".clone()" not in reverse and ".to_vec()" not in reverse
        if not verified:
            for name in ("clamp_i64", "abs_i64", "sum_i64", "array_max_i64"):
                assert "pruv: requires violated: crate::std::" + name in text
        out.unlink()
        for backend, dual in (("llvm", None), ("rust", (str(work / "out.ll"), str(work / "bindings.rs")))):
            errors = compile_file(str(root), str(out), verify=verified, backend=backend,
                                  rust_bindings=str(work / "bindings.rs"), also_llvm=dual)
            assert len(errors) == 1 and (errors[0].stage, errors[0].code) == ("codegen", "unsupported_type")
            assert sorted(p.name for p in work.iterdir()) == ["root.pruv"]
    print("12 ordinary bodies x 3 modes; reverse allocation; private std; 6 atomic LLVM rejections: OK")


if __name__ == "__main__":
    main(sys.argv[1])
