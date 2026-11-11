# -*- coding: utf-8 -*-
"""G3 (generics) grader for the four independent-use problems of bench/g3/PROBLEMS.md.

  python bench/g3/run.py <solutions_dir> [out.json] [--compiler py|rs|both] [--backend rust|llvm|both]
                         [--no-verify] [qNN ...]

Defaults: both compilers, both backends (4 configurations), out = bench/g3/results/<dir name>.json.
Per problem and configuration: status ok|wrong|pruv_error|missing|timeout|compile_error, tests_passed/total.
The expected results are computed here in Python (the reference semantics of PROBLEMS.md), embedded as literals in a
generated Rust test program, and compared with the Debug text of what the compiled wrappers return.
Importable API (used by mutate_ops.py): PROBLEMS, tests, build_and_run, compile_pruv."""
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
MIN, MAX = -9223372036854775808, 9223372036854775807
IV = [MIN, -1, 0, 1, 2, 7, MAX]
BV = [False, True]


# ------------------------------------------------------------------ values: Rust literal and Debug text
def lit(kind, v):
    if kind == "i":
        return "i64::MIN" if v == MIN else "i64::MAX" if v == MAX else "(%di64)" % v
    if kind == "b":
        return "true" if v else "false"
    el = "i" if kind == "ai" else "b"
    ty = "i64" if el == "i" else "bool"
    if not v:
        return "&Vec::<%s>::new()" % ty
    return "&vec![%s]" % ", ".join(lit(el, x) for x in v)


def dbg(kind, v):
    if kind == "i":
        return str(v)
    if kind == "b":
        return "true" if v else "false"
    return "[" + ", ".join(dbg(kind[1], x) for x in v) + "]"


def arrays(el, rnd):
    """Arrays of length 0..=3 over two values, 12 random arrays of length 4..=9, one of length 40."""
    vals = [0, 1] if el == "i" else [False, True]
    out = [[]]
    for n in (1, 2, 3):
        out += [[vals[(m >> k) & 1] for k in range(n)] for m in range(2 ** n)]
    pool = IV if el == "i" else BV
    out += [[rnd.choice(pool) for _ in range(rnd.randint(4, 9))] for _ in range(12)]
    out.append([rnd.choice(pool) for _ in range(40)])
    return out


def tests():
    """{pid: ([(fn, [(kind, value)], (kind, expected))], [probe fn, [(kind, value)]])}"""
    rnd = random.Random(2026)
    t = {p: ([], []) for p in PROBLEMS}
    q1 = t["q01"][0]
    for a in IV:
        for b in BV:
            q1.append(("swap_ib_first", [("i", a), ("b", b)], ("b", b)))
            q1.append(("swap_ib_second", [("i", a), ("b", b)], ("i", a)))
            q1.append(("swap_bi_first", [("b", b), ("i", a)], ("i", a)))
            q1.append(("swap_bi_second", [("b", b), ("i", a)], ("b", b)))
        for b in IV:
            q1.append(("swap_ii_first", [("i", a), ("i", b)], ("i", b)))
    for a in BV:
        for b in BV:
            q1.append(("swap_bb_first", [("b", a), ("b", b)], ("b", b)))
    q2 = t["q02"][0]
    for h in BV:
        for v in IV:
            for d in IV:
                q2.append(("get_or_int", [("b", h), ("i", v), ("i", d)], ("i", v if h else d)))
        for v in BV:
            for d in BV:
                q2.append(("get_or_bool", [("b", h), ("b", v), ("b", d)], ("b", v if h else d)))
    for a in arrays("i", rnd):
        if a:
            t["q03"][0].append(("head_int", [("ai", a)], ("i", a[0])))
        t["q04"][0].append(("copy_int", [("ai", a)], ("ai", list(a))))
    for a in arrays("b", rnd):
        if a:
            t["q03"][0].append(("head_bool", [("ab", a)], ("b", a[0])))
        t["q04"][0].append(("copy_bool", [("ab", a)], ("ab", list(a))))
    t["q03"][1].extend([("head_int", [("ai", [])]), ("head_bool", [("ab", [])])])
    return t


# ------------------------------------------------------------------ Rust test program
TEMPLATE = r'''
#![allow(dead_code, unused_imports, unused_parens)]
#[path = "@SOL@"] mod sol;
struct St { passed: usize, total: usize, first: Option<String> }
fn fail(st: &mut St, m: String) { if st.first.is_none() { st.first = Some(m); } }
fn chk(st: &mut St, name: &str, f: &dyn Fn() -> String, want: &str) {
    st.total += 1;
    match std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| f())) {
        Ok(got) if got == want => st.passed += 1,
        Ok(got) => fail(st, format!("{} want {:.120} got {:.120}", name, want, got)),
        Err(_) => fail(st, format!("{} want {:.120} got PANIC", name, want)),
    }
}
fn prb(st: &mut St, name: &str, f: &dyn Fn() -> String) {
    st.total += 1;
    match std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| f())) {
        Err(e) => {
            let m = e.downcast_ref::<String>().cloned().or_else(|| e.downcast_ref::<&str>().map(|s| s.to_string())).unwrap_or_default();
            if m.contains("requires violated") { st.passed += 1 } else { fail(st, format!("{} probe: wrong panic {:.80}", name, m)) }
        }
        Ok(got) => fail(st, format!("{} probe: no panic, got {:.80}", name, got)),
    }
}
fn main() {
    std::panic::set_hook(Box::new(|_| {}));
    let mut st = St { passed: 0, total: 0, first: None };
@CHECKS@
    println!("TESTS {} {}", st.passed, st.total);
    if let Some(m) = st.first { println!("FIRST {}", m.replace('\n', " ")); }
}
'''


def render(pid, probes):
    cases, probe_cases = tests()[pid]
    lines = []
    for fn, args, (ek, ev) in cases:
        call = "sol::%s(%s)" % (fn, ", ".join(lit(k, v) for k, v in args))
        lines.append('    chk(&mut st, "%s", &|| format!("{:?}", %s), "%s");' % (fn, call, dbg(ek, ev)))
    if probes:
        for fn, args in probe_cases:
            call = "sol::%s(%s)" % (fn, ", ".join(lit(k, v) for k, v in args))
            lines.append('    prb(&mut st, "%s", &|| format!("{:?}", %s));' % (fn, call))
    return "\n".join(lines)


def build_and_run(sol_path, pid, workdir, llvm_path=None, probes=None, opt="-O"):
    """Build the generated Rust (and the LLVM objects when llvm_path is given), run the tests of problem pid.
    probes: run the requires-violation probes (default: only on the Rust backend, the LLVM runtime aborts)."""
    if probes is None:
        probes = llvm_path is None
    src = TEMPLATE.replace("@SOL@", sol_path).replace("@CHECKS@", render(pid, probes))
    main = os.path.join(workdir, pid + "_main.rs")
    exe = os.path.join(workdir, pid + "_bin")
    with open(main, "w", encoding="utf-8") as f:
        f.write(src)
    extra = []
    if llvm_path:
        extra, err = G2.build_llvm_objects(os.path.abspath(llvm_path), pid, workdir)
        if err:
            return {"status": "compile_error", "compile_error": err[:2000]}
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
        elif p[0] == "FIRST":
            out["first_failure"] = p[1][:400]
    if out.get("tests_passed") != out.get("tests_total") or "tests_passed" not in out:
        out["status"] = "wrong"
    if r.returncode != 0:
        out["status"] = "wrong"
        out["exit_code"] = r.returncode
        out["stderr"] = r.stderr[-300:]
    return out


def grade(sdir, compiler, backend, flags, only):
    work = tempfile.mkdtemp(prefix="pruvg3_")
    res = {}
    for pid in PROBLEMS:
        if only and pid not in only:
            continue
        src = os.path.join(sdir, pid + ".pruv")
        if not os.path.exists(src):
            res[pid] = {"status": "missing"}
            continue
        wd = os.path.join(work, "%s_%s_%s" % (compiler, backend, pid))
        os.makedirs(wd)
        c = compile_pruv(compiler, src, wd, backend, flags)
        if c["rc"] != 0:
            res[pid] = {"status": "pruv_error", "pruv_errors": c["errors"]}
            if not c["errors"]:
                res[pid]["stderr"] = c["stderr"]
            continue
        res[pid] = build_and_run(c["rs"], pid, wd, llvm_path=c["ll"])
    return res


USAGE = ("usage: run.py <solutions_dir> [out.json] [--compiler py|rs|both] [--backend rust|llvm|both] "
         "[--no-verify] [qNN ...]")


def main():
    args = sys.argv[1:]
    opt = {"--compiler": "both", "--backend": "both"}
    for o in opt:
        if o in args:
            i = args.index(o)
            opt[o] = args[i + 1] if i + 1 < len(args) else ""
            del args[i:i + 2]
    flags = [f for f in ("--no-verify",) if f in args]
    only = [a for a in args if a in PROBLEMS]
    args = [a for a in args if not a.startswith("--") and a not in PROBLEMS]
    if (not args or opt["--compiler"] not in ("py", "rs", "both") or opt["--backend"] not in ("rust", "llvm", "both")):
        print(USAGE)
        sys.exit(2)
    sdir = os.path.abspath(args[0])
    outp = args[1] if len(args) > 1 else os.path.join(HERE, "results", os.path.basename(sdir.rstrip("/")) + ".json")
    compilers = ["py", "rs"] if opt["--compiler"] == "both" else [opt["--compiler"]]
    backends = ["rust", "llvm"] if opt["--backend"] == "both" else [opt["--backend"]]
    results = {}
    for c in compilers:
        for b in backends:
            results["%s-%s" % (c, b)] = grade(sdir, c, b, flags, only)
    od = os.path.dirname(os.path.abspath(outp))
    if not os.path.isdir(od):
        os.makedirs(od)
    with open(outp, "w", encoding="utf-8") as f:
        json.dump({"solutions": sdir, "flags": flags, "results": results}, f, indent=1, ensure_ascii=False)
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
    print("G3 grader: %d/%d problem runs ok" % (sum(len(r) for r in results.values()) - bad,
                                                sum(len(r) for r in results.values())))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
