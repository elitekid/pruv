# -*- coding: utf-8 -*-
"""G5 (inout parameters) grader for the two problems of bench/g5/PROBLEMS.md.

  python bench/g5/run.py <solutions_dir> [out.json] [--compiler py|rs|both] [--backend rust|llvm|both]
                         [--no-verify] [qNN ...]

<solutions_dir> holds one project directory per problem (<solutions_dir>/q01/root.pruv, ...). The compiler is started
on <project>/root.pruv; child modules are loaded by the compiler from the declared `mod` files.

Defaults: both compilers, both backends (4 configurations), out = bench/g5/results/<dir name>.json.
Per problem and configuration: status ok|wrong|pruv_error|missing|timeout|compile_error, tests_passed/total.
The expected results are computed here in Python (the reference semantics of PROBLEMS.md), embedded as text in a
generated Rust test program, and compared (Debug text) with what the compiled root host entries return.
Before compiling, the project structure (module files) and the root entry contracts are checked against
ENTRY_CONTRACTS (a mismatch is a pruv_error with the message "contract changed"); after a successful run the required
constructs of each problem are checked.

Importable API (used by mutate_ops.py): PROBLEMS, FILES, tests, grade_one, build_and_run, compile_pruv, ENTRY_CONTRACTS,
CONTRACT_CHECKS (empty: the G5 contracts are exact, so there is no contract-weak class)."""
import importlib.util
import json
import os
import random
import re
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

PROBLEMS = ["q01", "q02"]
MIN, MAX = -9223372036854775808, 9223372036854775807

# files of each project (paths relative to the project directory); the first one is the root
FILES = {
    "q01": ["root.pruv"],
    "q02": ["root.pruv", "xform.pruv"],
}

# `mod` declarations the grader requires: (file, module name)
MOD_DECLS = {
    "q01": [],
    "q02": [("root.pruv", "xform")],
}

# root entry -> signature text and requires/ensures lines exactly as in PROBLEMS.md
ENTRY_CONTRACTS = {
    "q01": {
        "add_sat": ["pub fn add_sat(a: [u8], lo: i64, hi: i64, c: i64) -> [u8] ! alloc",
                    "requires 0 <= lo && lo <= hi && hi <= len(a) && 0 <= c && c <= 255",
                    "ensures len(result) == len(a)",
                    "ensures forall k in 0..len(a): (lo <= k && k < hi && a[k] + c <= 255) ==> result[k] == a[k] + c",
                    "ensures forall k in 0..len(a): (lo <= k && k < hi && a[k] + c > 255) ==> result[k] == 255",
                    "ensures forall k in 0..len(a): (k < lo || k >= hi) ==> result[k] == a[k]"],
        "add_wrap": ["pub fn add_wrap(a: [u8], lo: i64, hi: i64, c: i64) -> [u8] ! alloc",
                     "requires 0 <= lo && lo <= hi && hi <= len(a) && 0 <= c && c <= 255",
                     "ensures len(result) == len(a)",
                     "ensures forall k in 0..len(a): (lo <= k && k < hi) ==> result[k] == (a[k] + c) % 256",
                     "ensures forall k in 0..len(a): (k < lo || k >= hi) ==> result[k] == a[k]"],
        "fill_bytes": ["pub fn fill_bytes(a: [u8], lo: i64, hi: i64, v: i64) -> [u8] ! alloc",
                       "requires 0 <= lo && lo <= hi && hi <= len(a) && 0 <= v && v <= 255",
                       "ensures len(result) == len(a)",
                       "ensures forall k in 0..len(a): (lo <= k && k < hi) ==> result[k] == v",
                       "ensures forall k in 0..len(a): (k < lo || k >= hi) ==> result[k] == a[k]"],
    },
    "q02": {
        "reverse_window": ["pub fn reverse_window(a: [i64], lo: i64, hi: i64) -> [i64] ! alloc",
                           "requires 0 <= lo && lo <= hi + 1 && hi < len(a)",
                           "ensures len(result) == len(a)",
                           "ensures forall k in 0..len(a): (lo <= k && k <= hi) ==> result[k] == a[lo + hi - k]",
                           "ensures forall k in 0..len(a): (k < lo || k > hi) ==> result[k] == a[k]"],
        "reverse_all": ["pub fn reverse_all(a: [i64]) -> [i64] ! alloc",
                        "ensures len(result) == len(a)",
                        "ensures forall k in 0..len(a): result[k] == a[len(a) - 1 - k]"],
        "shift_tail": ["pub fn shift_tail(a: [i64], i: i64, d: i64) -> [i64] ! alloc",
                       "requires 0 <= i && i <= len(a) && -1000 <= d && d <= 1000",
                       "requires forall k in 0..len(a): -1000000 <= a[k] && a[k] <= 1000000",
                       "ensures len(result) == len(a)",
                       "ensures forall k in 0..len(a): k >= i ==> result[k] == a[k] + d",
                       "ensures forall k in 0..len(a): k < i ==> result[k] == a[k]"],
    },
}


def norm(s):
    return re.sub(r"\s+", " ", s).strip()


def strip_comments(text):
    return re.sub(r"//[^\n]*", "", text)


def entry_header(text, name):
    """Normalized text from `pub fn name(` up to the body brace, or None."""
    t = strip_comments(text)
    m = re.search(r"\bpub\s+fn\s+%s\s*\(" % re.escape(name), t)
    if not m:
        return None
    body = t[m.start():]
    end = body.find("{")
    return norm(body if end < 0 else body[:end])


def check_contracts(root_text, pid):
    """None when every root entry of pid has exactly its signature and contract lines, in order and
    whitespace-normalized, and the root has no other `pub fn` (except `main`); else a message."""
    t = strip_comments(root_text)
    for name, lines in ENTRY_CONTRACTS[pid].items():
        head = entry_header(root_text, name)
        if head is None:
            if re.search(r"\bfn\s+%s\s*\(" % re.escape(name), t):
                return "contract changed: entry %s is not `pub`" % name
            return "contract changed: entry %s not found" % name
        if head != norm(" ".join(lines)):
            return "contract changed: %s differs from the fixed signature and contract" % name
    extra = [n for n in re.findall(r"\bpub\s+fn\s+(\w+)", t) if n not in ENTRY_CONTRACTS[pid] and n != "main"]
    if extra:
        return "contract changed: extra public root function %s" % extra[0]
    return None


def read_project(sdir):
    """{relative path: text} of the .pruv files of the project directory."""
    out = {}
    for dp, _dn, fns in os.walk(sdir):
        for fn in fns:
            if fn.endswith(".pruv"):
                p = os.path.join(dp, fn)
                with open(p, encoding="utf-8") as f:
                    out[os.path.relpath(p, sdir).replace(os.sep, "/")] = f.read()
    return out


def check_structure(files, pid):
    """None when the project has its module files and `mod` declarations, else a message."""
    for rel in FILES[pid]:
        if rel not in files:
            return "structure changed: file %s is missing" % rel
    for rel, mod in MOD_DECLS[pid]:
        if not re.search(r"^\s*mod\s+%s\s*;" % re.escape(mod), strip_comments(files[rel]), re.M):
            return "structure changed: %s does not declare `mod %s;`" % (rel, mod)
    return None


def has_recursive_inout_call(text):
    """True when some `fn f(inout ...)` calls `f(inout ...)` anywhere in its own body (any brace depth)."""
    for m in re.finditer(r"\bfn\s+(\w+)\s*\(\s*inout\b", text):
        start = text.find("{", m.end())
        if start < 0:
            continue
        depth, i = 0, start
        while i < len(text):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        if re.search(r"\b%s\s*\(\s*inout\b" % re.escape(m.group(1)), text[start:i]):
            return True
    return False


def check_constructs(files, pid):
    """List of missing required constructs (PROBLEMS.md 'Structure required by the grader')."""
    lack = []
    root = strip_comments(files.get("root.pruv", ""))
    if pid == "q01":
        if not re.search(r"^fn\s+\w+\s*\(\s*inout\s+\w+\s*:\s*\[u8\]", root, re.M):
            lack.append("private inout [u8] helper in root.pruv")
        if len(re.findall(r"\(\s*inout\s+\w+", root)) < 4:
            lack.append("at least four inout calls in root.pruv")
        if "old(" not in root:
            lack.append("old(...) in an inout helper contract")
        if "copy(" not in root:
            lack.append("copy(...) in the host wrappers")
        if re.search(r"\bpub\s+fn\s+\w+\s*\(\s*inout\b", root):
            lack.append("no pub fn may take inout")
    elif pid == "q02":
        x = strip_comments(files.get("xform.pruv", ""))
        if not re.search(r"^pub\s+fn\s+\w+\s*\(\s*inout\s+\w+\s*:\s*\[i64\]", x, re.M):
            lack.append("pub fn with an inout [i64] parameter in xform.pruv")
        if len(re.findall(r"\bdecreases\b", x)) < 2:
            lack.append("at least two `decreases` clauses in xform.pruv")
        if not has_recursive_inout_call(x):
            lack.append("a recursive inout call in xform.pruv")
        if "old(" not in x:
            lack.append("old(...) in xform.pruv contracts")
        if "crate::xform::" not in root:
            lack.append("root reaches xform by crate::xform:: paths")
        if "copy(" not in root:
            lack.append("copy(...) in the host wrappers")
    return lack


# ------------------------------------------------------------------ reference semantics (PROBLEMS.md)
def ref_add_sat(a, lo, hi, c):
    return [min(255, x + c) if lo <= k < hi else x for k, x in enumerate(a)]


def ref_add_wrap(a, lo, hi, c):
    return [(x + c) % 256 if lo <= k < hi else x for k, x in enumerate(a)]


def ref_fill_bytes(a, lo, hi, v):
    return [v if lo <= k < hi else x for k, x in enumerate(a)]


def ref_reverse_window(a, lo, hi):
    return [a[lo + hi - k] if lo <= k <= hi else x for k, x in enumerate(a)]


def ref_reverse_all(a):
    return list(reversed(a))


def ref_shift_tail(a, i, d):
    return [x + d if k >= i else x for k, x in enumerate(a)]


def dbg(kind, v):
    """Rust Debug text of an expected value (kinds: au [u8], ai [i64])."""
    return "[" + ", ".join(str(x) for x in v) + "]"


def tests():
    """{pid: [(fn, [(kind, value)], (kind, expected))]}; kinds: i (i64), au ([u8]), ai ([i64])."""
    rnd = random.Random(2057)
    t = {p: [] for p in PROBLEMS}
    # q01
    bv = [0, 1, 100, 127, 128, 200, 250, 254, 255]
    arrs = [[], [0], [255], [128], [1, 2, 3], [250, 251, 252, 253, 254, 255], [255, 255, 255, 0, 0, 0],
            [0, 255, 0, 255, 0, 255, 0]]
    for _ in range(6):
        arrs.append([rnd.choice(bv) for _ in range(rnd.randint(4, 12))])
    arrs.append([(i * 37) % 256 for i in range(300)])
    for a in arrs:
        n = len(a)
        wins = sorted({(0, 0), (0, n), (n, n), (1, n) if n >= 1 else (0, 0), (0, n // 2), (n // 2, n),
                       (1, n - 1) if n >= 2 else (0, 0), (n // 3, 2 * n // 3)})
        for lo, hi in wins:
            for c in (0, 1, 100, 255):
                t["q01"].append(("add_sat", [("au", a), ("i", lo), ("i", hi), ("i", c)],
                                 ("au", ref_add_sat(a, lo, hi, c))))
                t["q01"].append(("add_wrap", [("au", a), ("i", lo), ("i", hi), ("i", c)],
                                 ("au", ref_add_wrap(a, lo, hi, c))))
            for v in (0, 77, 255):
                t["q01"].append(("fill_bytes", [("au", a), ("i", lo), ("i", hi), ("i", v)],
                                 ("au", ref_fill_bytes(a, lo, hi, v))))
    # q02
    big = [MIN, MAX, 0, -1, 1, 7, MIN + 1, MAX - 1]
    rarrs = [[], [5], [1, 2], [1, 2, 3], [10, 20, 30, 40], [3, 1, 4, 1, 5, 9, 2, 6], big,
             [rnd.choice(big) for _ in range(9)], list(range(40)), [(i * 7919) % 1001 - 500 for i in range(500)]]
    for a in rarrs:
        n = len(a)
        wins = {(0, n - 1), (0, -1), (n, n - 1), (n // 2, n - 1), (0, n // 2)}
        if n >= 1:
            wins |= {(0, 0), (n - 1, n - 1)}
        if n >= 3:
            wins |= {(1, n - 2)}
        for lo, hi in sorted(wins):
            if 0 <= lo <= hi + 1 and hi < n:
                t["q02"].append(("reverse_window", [("ai", a), ("i", lo), ("i", hi)],
                                 ("ai", ref_reverse_window(a, lo, hi))))
        t["q02"].append(("reverse_all", [("ai", a)], ("ai", ref_reverse_all(a))))
    sarrs = [[], [0], [-1000000], [1000000], [1, 2, 3], [999999, -999999, 5, 1000000, -1000000],
             [rnd.randint(-1000000, 1000000) for _ in range(9)], [(i * 7919) % 2001 - 1000 for i in range(500)]]
    for a in sarrs:
        n = len(a)
        for i in sorted({0, n // 2, n}):
            for d in (-1000, 0, 7, 1000):
                t["q02"].append(("shift_tail", [("ai", a), ("i", i), ("i", d)], ("ai", ref_shift_tail(a, i, d))))
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
    std::panic::set_hook(Box::new(|i| {
        let m = i.payload().downcast_ref::<String>().cloned()
            .or_else(|| i.payload().downcast_ref::<&str>().map(|s| s.to_string())).unwrap_or_default();
        eprintln!("{}", m.replace('\n', " "));
    }));
    let mut st = St { passed: 0, total: 0, first: None, panics: 0, first_panic: None };
@ARRAYS@
@CHECKS@
    println!("TESTS {} {}", st.passed, st.total);
    println!("PANICS {}", st.panics);
    if let Some(m) = st.first_panic { println!("PANIC {}", m.replace('\n', " ")); }
    if let Some(m) = st.first { println!("FIRST {}", m.replace('\n', " ")); }
}
'''

# G5 contracts state the full meaning (exact content and frame), so there is no "contract-weak" class: every wrong
# result violates a stated ensures. Kept as an (empty) importable name for the shape of bench/g4/run.py.
CONTRACT_CHECKS = {}


def rs_i(v):
    return "i64::MIN" if v == MIN else "i64::MAX" if v == MAX else "(%di64)" % v


def render(pid):
    """(array let-bindings, check lines). Every distinct array is bound once and passed by reference."""
    names = {}
    lets = []

    def arr(kind, v):
        key = (kind, tuple(v))
        if key not in names:
            names[key] = "a%d" % len(names)
            if kind == "au":
                body = ", ".join("%du8" % x for x in v)
                lets.append("    let %s: Vec<u8> = vec![%s];" % (names[key], body))
            else:
                body = ", ".join(rs_i(x) for x in v)
                lets.append("    let %s: Vec<i64> = vec![%s];" % (names[key], body))
        return "&" + names[key]

    lines = []
    for fn, args, (ek, ev) in tests()[pid]:
        cs = ", ".join(arr(k, v) if k in ("au", "ai") else rs_i(v) for k, v in args)
        lines.append('    chk(&mut st, "%s", &|| format!("{:?}", sol::%s(%s)), "%s");' % (fn, fn, cs, dbg(ek, ev)))
    return "\n".join(lets), "\n".join(lines)


def build_and_run(sol_path, pid, workdir, llvm_path=None, opt="-O", timeout=120, contracts=False):
    """Build the generated Rust (and the LLVM objects when llvm_path is given), run the tests of problem pid.
    `contracts` is accepted for the shape of bench/g4/run.py and must be False."""
    arrays, checks = render(pid)
    src = TEMPLATE.replace("@SOL@", sol_path).replace("@ARRAYS@", arrays).replace("@CHECKS@", checks)
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
        r = subprocess.run([exe], capture_output=True, encoding="utf-8", errors="replace", timeout=timeout)
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
        out["status"] = "wrong"        # crash (stack overflow, abort) or panic that ends the process
        out["exit_code"] = r.returncode
        out["stderr"] = r.stderr[-300:]
    return out


def grade_one(sdir, pid, compiler, backend, flags, work, timeout=120, contracts=False):
    """Compile project directory `sdir` (with root.pruv) for problem pid in one configuration and run its tests.
    Result dict with status."""
    files = read_project(sdir)
    msg = check_structure(files, pid) or check_contracts(files.get("root.pruv", ""), pid)
    if msg:
        code = "structure_changed" if msg.startswith("structure") else "contract_changed"
        return {"status": "pruv_error", "rc": 1, "pruv_errors": [{"stage": "grader", "code": code, "message": msg}]}
    wd = tempfile.mkdtemp(prefix="%s_%s_%s_" % (compiler, backend, pid), dir=work)
    c = compile_pruv(compiler, os.path.join(sdir, "root.pruv"), wd, backend, list(flags))
    if c["rc"] != 0:
        r = {"status": "pruv_error", "rc": c["rc"], "pruv_errors": c["errors"]}
        if not c["errors"]:
            r["stderr"] = c["stderr"]
        return r
    return build_and_run(c["rs"], pid, wd, llvm_path=c["ll"], timeout=timeout)


def grade(sdir, compiler, backend, flags, only, work):
    res = {}
    for pid in PROBLEMS:
        if only and pid not in only:
            continue
        src = os.path.join(sdir, pid)
        if not os.path.exists(os.path.join(src, "root.pruv")):
            res[pid] = {"status": "missing"}
            continue
        r = grade_one(src, pid, compiler, backend, flags, work)
        if r["status"] == "ok":
            lacking = check_constructs(read_project(src), pid)
            if lacking:
                r["status"] = "wrong"
                r["first_failure"] = "required construct missing: " + ", ".join(lacking)
        res[pid] = r
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
    ok_opts = opt["--compiler"] in ("py", "rs", "both") and opt["--backend"] in ("rust", "llvm", "both")
    if not ok_opts or not args:
        print(USAGE)
        sys.exit(2)
    compilers = ["py", "rs"] if opt["--compiler"] == "both" else [opt["--compiler"]]
    backends = ["rust", "llvm"] if opt["--backend"] == "both" else [opt["--backend"]]
    sdir = os.path.abspath(args[0])
    outp = args[1] if len(args) > 1 else os.path.join(HERE, "results", os.path.basename(sdir.rstrip("/")) + ".json")
    work = tempfile.mkdtemp(prefix="pruvg5_")
    results = {}
    for c in compilers:
        for b in backends:
            results["%s-%s" % (c, b)] = grade(sdir, c, b, flags, only, work)
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
                note = "%s %s %s" % (e.get("stage", ""), e.get("code", ""), e.get("message", "")[:60])
            elif r.get("first_failure"):
                note = r["first_failure"][:80]
            elif r.get("compile_error"):
                note = r["compile_error"][:80].replace("\n", " ")
            print("%-9s %-4s %-13s %-9s %s" % (cfg, pid, r["status"],
                                                "%s/%s" % (r.get("tests_passed", "-"), r.get("tests_total", "-")), note))
            bad += r["status"] != "ok"
    total = sum(len(r) for r in results.values())
    print("G5 grader: %d/%d problem runs ok (work dir %s)" % (total - bad, total, work))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
