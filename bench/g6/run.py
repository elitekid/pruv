# -*- coding: utf-8 -*-
"""G6 (Rust calls, standard collections) grader for the four independent-use problems of bench/g6/PROBLEMS.md.

  python bench/g6/run.py <solutions_dir> [out.json] [--compiler py|rs|both] [--backend rust|llvm|both]
                         [--no-verify] [--foreign-checks requires|all|off] [--adapter FILE.rs] [qNN ...]

Defaults: both compilers, both backends (4 configurations), out = bench/g6/results/<dir name>.json.
Per problem and configuration: status ok|wrong|pruv_error|missing|timeout|compile_error, tests_passed/total.
The expected results are computed here in Python (the reference semantics of PROBLEMS.md), embedded as Rust expressions
in a generated test program, and compared (Debug text) with what the compiled public wrappers return.
q04 needs the adapter crate: it is built once as an rlib named g6q_adapter (rustc --crate-type rlib), passed to pruvc as
`--rust-extern g6q_adapter=RLIB` and to the final rustc as `--extern g6q_adapter=RLIB`. LLVM builds compile the generated
bindings (which contain the Rust shim) with rustc together with the clang-built object and runtime object.
`--adapter` replaces the adapter source (used for the lying variants of mutate_ops.py).
Importable API (used by mutate_ops.py): PROBLEMS, tests, build_rlib, build_and_run, grade_one, compile_pruv."""
import importlib.util
import json
import os
import random
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


G2 = _load("g2_run", os.path.join(ROOT, "bench", "g2", "run.py"))   # compile_pruv, build_llvm_objects, RUSTC
compile_pruv = G2.compile_pruv

PROBLEMS = ["q01", "q02", "q03", "q04"]
EXTERN_NAME = "g6q_adapter"
ADAPTER_SRC = os.path.join(HERE, "adapter", "g6q_adapter.rs")
NEEDS_EXTERN = ("q04",)
REQUIRED_TOKENS = {"q01": ["vec_push"], "q02": ["map_insert", "map_get"], "q03": ["string_push_str", "string_to_str"],
                   "q04": ["trusted rust fn parse_digit", "::g6q_adapter::parse_digit"]}
MIN, MAX = -9223372036854775808, 9223372036854775807
IV = [MIN, -1, 0, 1, 2, 7, MAX]


# ------------------------------------------------------------------ values as Rust expressions
def rs_str(v):
    out = []
    for ch in v:
        o = ord(ch)
        if 32 <= o < 127 and ch not in '"\\':
            out.append(ch)
        else:
            out.append("\\u{%x}" % o)
    return '"' + "".join(out) + '"'


def lit(kind, v):
    """Rust expression of a value; kinds: i (i64), b (bool), s (str), ai ([i64])."""
    if kind == "i":
        return "i64::MIN" if v == MIN else "i64::MAX" if v == MAX else "(%di64)" % v
    if kind == "b":
        return "true" if v else "false"
    if kind == "s":
        return rs_str(v)
    if kind == "ai":
        if not v:
            return "&Vec::<i64>::new()"
        return "&vec![%s]" % ", ".join(lit("i", x) for x in v)
    raise ValueError(kind)


# ------------------------------------------------------------------ reference semantics (PROBLEMS.md)
def ref_count_in_range(a, lo, hi):
    return sum(1 for x in a if lo <= x <= hi)


def ref_running_total(a):
    return sum(a)


def ref_count_value(a, q):
    return sum(1 for x in a if x == q)


def ref_join_pair(a, b, sep):
    return a + sep + b


def ref_joined_len3(a, b, c, sep):
    return len((a + sep + b + sep + c).encode("utf-8"))


DIGITS = "0123456789"


def is_d(s):
    return len(s.encode("utf-8")) == 1 and s in DIGITS


def ref_digit_or(s, d):
    return int(s) if is_d(s) else d


def ref_add_digits(a, b):
    return int(a) + int(b) if is_d(a) and is_d(b) else -1


def tests():
    """{pid: [(fn, [(kind, value)], (kind, expected))]}"""
    rnd = random.Random(2027)
    t = {p: [] for p in PROBLEMS}
    # q01
    ranges = [(0, 1), (-1, 7), (2, 2), (5, 3), (MIN, MAX), (MIN, -1), (1, MAX), (7, 7), (-5, 5)]
    arrs = [[], [0], [1], [MIN], [MAX], [0, 1, 0, 1], [5, 3, 9, -1, 7, 7, 2], [2, 2, 2]]
    for _ in range(10):
        arrs.append([rnd.choice(IV + [3, 5, -5, 9]) for _ in range(rnd.randint(4, 9))])
    arrs.append([rnd.randint(-10, 20) for _ in range(40)])
    arrs.append([rnd.randint(-1000, 1000) for _ in range(120)])
    for a in arrs:
        for lo, hi in ranges:
            t["q01"].append(("count_in_range", [("ai", a), ("i", lo), ("i", hi)], ("i", ref_count_in_range(a, lo, hi))))
    sums = [[], [0], [1000], [1, 2, 3], [7, 0, 1000, 3], [0] * 5, [1000] * 40, [1000] * 1000]
    for _ in range(12):
        sums.append([rnd.randint(0, 1000) for _ in range(rnd.randint(1, 9))])
    sums.append([rnd.randint(0, 1000) for _ in range(40)])
    for a in sums:
        t["q01"].append(("running_total", [("ai", a)], ("i", ref_running_total(a))))
    # q02
    arrs2 = [[], [0], [1, 1, 1], [MIN, MAX, MIN], [0, 1, 0], [2, 2, 1, 2, 0]]
    for _ in range(10):
        arrs2.append([rnd.choice(IV + [3]) for _ in range(rnd.randint(4, 9))])
    arrs2.append([rnd.choice([0, 1, 2, MAX]) for _ in range(40)])
    arrs2.append([i % 7 for i in range(2000)])
    for a in arrs2:
        for q in [0, 1, 2, 3, MIN, MAX, -1, 7]:
            n = ref_count_value(a, q)
            t["q02"].append(("count_value", [("ai", a), ("i", q)], ("i", n)))
            t["q02"].append(("seen", [("ai", a), ("i", q)], ("b", n > 0)))
    # q03
    pieces = ["", "a", "é", "한글", "\U0001F600", "ab,c", "x\ny\0"]
    seps = ["", ",", " — ", "→", "\U0001F600\U0001F600"]
    for a in pieces:
        for b in pieces:
            for sep in seps:
                t["q03"].append(("join_pair", [("s", a), ("s", b), ("s", sep)], ("s", ref_join_pair(a, b, sep))))
    for _ in range(40):
        a, b, c = rnd.choice(pieces), rnd.choice(pieces), rnd.choice(pieces)
        sep = rnd.choice(seps)
        t["q03"].append(("joined_len3", [("s", a), ("s", b), ("s", c), ("s", sep)], ("i", ref_joined_len3(a, b, c, sep))))
    # q04
    strs = ["0", "1", "5", "9", "a", "", "12", " 5", "5 ", "/", ":", "-", "٣", "５", "\U0001F600", "00"]
    for s in strs:
        t["q04"].append(("is_digit", [("s", s)], ("b", is_d(s))))
        for d in [-7, 0, 100, MIN, MAX]:
            t["q04"].append(("digit_or", [("s", s), ("i", d)], ("i", ref_digit_or(s, d))))
    pairs = ["0", "9", "5", "a", "", "12", "٣"]
    for a in pairs:
        for b in pairs:
            t["q04"].append(("add_digits", [("s", a), ("s", b)], ("i", ref_add_digits(a, b))))
    return t


# ------------------------------------------------------------------ Rust test program
TEMPLATE = r'''
#![allow(dead_code, unused_imports, unused_parens)]
#[path = "@SOL@"] mod sol;
struct St { passed: usize, total: usize, first: Option<String>, panics: usize, first_panic: Option<String> }
fn fail(st: &mut St, m: String) { if st.first.is_none() { st.first = Some(m); } }
fn pmsg(e: Box<dyn std::any::Any + Send>) -> String {
    e.downcast_ref::<String>().cloned().or_else(|| e.downcast_ref::<&str>().map(|s| s.to_string())).unwrap_or_default()
}
fn chk(st: &mut St, name: &str, f: &dyn Fn() -> String, want: &str) {
    st.total += 1;
    match std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| f())) {
        Ok(got) if got == want => st.passed += 1,
        Ok(got) => fail(st, format!("{} want {:.120} got {:.120}", name, want, got)),
        Err(e) => {
            let m = pmsg(e);
            st.panics += 1;
            if st.first_panic.is_none() { st.first_panic = Some(m.clone()); }
            fail(st, format!("{} want {:.120} got PANIC {:.120}", name, want, m));
        }
    }
}
fn main() {
    std::panic::set_hook(Box::new(|_| {}));
    let mut st = St { passed: 0, total: 0, first: None, panics: 0, first_panic: None };
@CHECKS@
    println!("TESTS {} {}", st.passed, st.total);
    println!("PANICS {}", st.panics);
    if let Some(m) = st.first_panic { println!("PANIC {}", m.replace('\n', " ")); }
    if let Some(m) = st.first { println!("FIRST {}", m.replace('\n', " ")); }
}
'''


def render(pid):
    lines = []
    for fn, args, (ek, ev) in tests()[pid]:
        call = "sol::%s(%s)" % (fn, ", ".join(lit(k, v) for k, v in args))
        lines.append('    chk(&mut st, "%s", &|| format!("{:?}", %s), &format!("{:?}", %s));' % (fn, call, lit(ek, ev)))
    return "\n".join(lines)


def build_rlib(src, workdir, name=EXTERN_NAME):
    """rustc --crate-type rlib --crate-name NAME src -> (rlib path, None) or (None, error text)."""
    if not os.path.isdir(workdir):
        os.makedirs(workdir)
    rlib = os.path.join(workdir, "lib%s.rlib" % name)
    c = subprocess.run([G2.RUSTC, "-O", "--edition", "2021", "--crate-type", "rlib", "--crate-name", name,
                        os.path.abspath(src), "-o", rlib], capture_output=True, encoding="utf-8", errors="replace")
    if c.returncode != 0:
        return None, c.stderr[-1500:]
    return rlib, None


def build_and_run(sol_path, pid, workdir, llvm_path=None, rlib=None, opt="-O"):
    """Build the generated Rust (and the LLVM objects when llvm_path is given), run the tests of problem pid.
    rlib: the adapter rlib (--extern g6q_adapter=RLIB) for problems that call it."""
    src = TEMPLATE.replace("@SOL@", sol_path).replace("@CHECKS@", render(pid))
    main = os.path.join(workdir, pid + "_main.rs")
    exe = os.path.join(workdir, pid + "_bin")
    with open(main, "w", encoding="utf-8") as f:
        f.write(src)
    extra = []
    if llvm_path:
        extra, err = G2.build_llvm_objects(os.path.abspath(llvm_path), pid, workdir)
        if err:
            return {"status": "compile_error", "compile_error": err[:2000]}
    if rlib:
        extra = extra + ["--extern", "%s=%s" % (EXTERN_NAME, rlib)]
    opts = ["-C", "opt-level=0"] if opt == "-O0" else ["-O"]
    c = subprocess.run([G2.RUSTC] + opts + ["--edition", "2021", main, "-o", exe] + extra,
                       capture_output=True, encoding="utf-8", errors="replace")
    if c.returncode != 0:
        return {"status": "compile_error", "compile_error": c.stderr[:2000]}
    try:
        r = subprocess.run([exe], capture_output=True, encoding="utf-8", errors="replace", timeout=120)
    except subprocess.TimeoutExpired:
        return {"status": "timeout"}
    out = {"status": "ok"}
    for line in r.stdout.splitlines():
        p = line.split(" ", 1)
        if p[0] == "TESTS":
            a, b = p[1].split()
            out["tests_passed"], out["tests_total"] = int(a), int(b)
        elif p[0] == "PANICS":
            out["panics"] = int(p[1])
        elif p[0] == "PANIC":
            out["first_panic"] = p[1][:300]
        elif p[0] == "FIRST":
            out["first_failure"] = p[1][:400]
    if out.get("tests_passed") != out.get("tests_total") or "tests_passed" not in out:
        out["status"] = "wrong"
    if r.returncode != 0:
        out["status"] = "wrong"        # on LLVM a foreign panic / failed boundary check ends the process with exit 101
        out["exit_code"] = r.returncode
        out["stderr"] = r.stderr[-300:]
        if "pruv: foreign" in r.stderr and "first_panic" not in out:
            out["first_panic"] = r.stderr.strip().splitlines()[-1][:300] if r.stderr.strip() else "pruv: foreign"
    return out


def grade_one(src, pid, compiler, backend, flags, work, rlib=None):
    """Compile solution file `src` for problem pid in one configuration and run its tests. Result dict with status."""
    wd = tempfile.mkdtemp(prefix="%s_%s_%s_" % (compiler, backend, pid), dir=work)
    xflags = ["--rust-extern", "%s=%s" % (EXTERN_NAME, rlib)] if rlib else []
    c = compile_pruv(compiler, src, wd, backend, list(flags) + xflags)
    if c["rc"] != 0:
        r = {"status": "pruv_error", "pruv_errors": c["errors"]}
        if not c["errors"]:
            r["stderr"] = c["stderr"]
        return r
    return build_and_run(c["rs"], pid, wd, llvm_path=c["ll"], rlib=rlib)


def grade(sdir, compiler, backend, flags, only, rlib, work):
    res = {}
    for pid in PROBLEMS:
        if only and pid not in only:
            continue
        src = os.path.join(sdir, pid + ".pruv")
        if not os.path.exists(src):
            res[pid] = {"status": "missing"}
            continue
        if pid in NEEDS_EXTERN and not rlib:
            res[pid] = {"status": "compile_error", "compile_error": "adapter rlib missing"}
            continue
        r = grade_one(src, pid, compiler, backend, flags, work, rlib if pid in NEEDS_EXTERN else None)
        if r["status"] == "ok":
            text = open(src, encoding="utf-8").read()
            lacking = [tok for tok in REQUIRED_TOKENS[pid] if tok not in text]
            if lacking:
                r["status"] = "wrong"
                r["first_failure"] = "required construct missing: " + ", ".join(lacking)
        res[pid] = r
    return res


USAGE = ("usage: run.py <solutions_dir> [out.json] [--compiler py|rs|both] [--backend rust|llvm|both] "
         "[--no-verify] [--foreign-checks requires|all|off] [--adapter FILE.rs] [qNN ...]")


def main():
    args = sys.argv[1:]
    opt = {"--compiler": "both", "--backend": "both", "--foreign-checks": "", "--adapter": ADAPTER_SRC}
    for o in opt:
        if o in args:
            i = args.index(o)
            opt[o] = args[i + 1] if i + 1 < len(args) else ""
            del args[i:i + 2]
    flags = [f for f in ("--no-verify",) if f in args]
    if opt["--foreign-checks"]:
        flags += ["--foreign-checks", opt["--foreign-checks"]]
    only = [a for a in args if a in PROBLEMS]
    args = [a for a in args if not a.startswith("--") and a not in PROBLEMS]
    if (not args or opt["--compiler"] not in ("py", "rs", "both") or opt["--backend"] not in ("rust", "llvm", "both")
            or opt["--foreign-checks"] not in ("", "requires", "all", "off")):
        print(USAGE)
        sys.exit(2)
    sdir = os.path.abspath(args[0])
    outp = args[1] if len(args) > 1 else os.path.join(HERE, "results", os.path.basename(sdir.rstrip("/")) + ".json")
    compilers = ["py", "rs"] if opt["--compiler"] == "both" else [opt["--compiler"]]
    backends = ["rust", "llvm"] if opt["--backend"] == "both" else [opt["--backend"]]
    work = tempfile.mkdtemp(prefix="pruvg6_")
    rlib = None
    if not only or any(p in NEEDS_EXTERN for p in only):
        rlib, err = build_rlib(opt["--adapter"], os.path.join(work, "adapter"))
        if err:
            print("adapter build failed:\n" + err)
    results = {}
    for c in compilers:
        for b in backends:
            results["%s-%s" % (c, b)] = grade(sdir, c, b, flags, only, rlib, work)
    od = os.path.dirname(os.path.abspath(outp))
    if not os.path.isdir(od):
        os.makedirs(od)
    with open(outp, "w", encoding="utf-8") as f:
        json.dump({"solutions": sdir, "flags": flags, "adapter": os.path.abspath(opt["--adapter"]), "results": results},
                  f, indent=1, ensure_ascii=False)
    bad = 0
    print("%-9s %-4s %-13s %-9s %s" % ("config", "id", "status", "tests", "note"))
    for cfg, res in results.items():
        for pid, r in res.items():
            note = ""
            if r["status"] == "pruv_error" and r.get("pruv_errors"):
                e = r["pruv_errors"][0]
                note = "%s %s" % (e.get("stage", ""), e.get("code", ""))
            elif r.get("first_failure"):
                note = r["first_failure"][:80]
            elif r.get("compile_error"):
                note = r["compile_error"][:80].replace("\n", " ")
            print("%-9s %-4s %-13s %-9s %s" % (cfg, pid, r["status"],
                                                "%s/%s" % (r.get("tests_passed", "-"), r.get("tests_total", "-")), note))
            bad += r["status"] != "ok"
    total = sum(len(r) for r in results.values())
    print("G6 grader: %d/%d problem runs ok" % (total - bad, total))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
