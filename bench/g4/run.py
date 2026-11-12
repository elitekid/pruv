# -*- coding: utf-8 -*-
"""G4 (modules, visibility, host entries) grader for the two problems of bench/g4/PROBLEMS.md.

  python bench/g4/run.py <solutions_dir> [out.json] [--compiler py|rs|both] [--backend rust|llvm|both]
                         [--no-verify] [qNN ...]
  python bench/g4/run.py --scale [out.json] [--compiler py|rs|both] [--backend rust|llvm|both] [--repeat N] [--keep]

<solutions_dir> holds one project directory per problem (<solutions_dir>/q01/root.pruv, ...). The compiler is started
on <project>/root.pruv; child modules are loaded by the compiler from the declared `mod` files.

Defaults: both compilers, both backends (4 configurations), out = bench/g4/results/<dir name>.json.
Per problem and configuration: status ok|wrong|pruv_error|missing|timeout|compile_error, tests_passed/total.
The expected results are computed here in Python (the reference semantics of PROBLEMS.md), embedded as text in a
generated Rust test program, and compared (Debug text) with what the compiled root host entries return.
Before compiling, the project structure (declared module files) and the root entry contracts are checked against
ENTRY_CONTRACTS (a mismatch is a pruv_error with the message "contract changed"); after a successful run the required
constructs of each problem are checked.

--scale writes a deterministic 100-module fixture (root + 99 modules) to a temporary directory and measures the
whole-program compile time of both compilers with proofs and with --no-verify, printing a table. Every compile is a
cold whole-program compile; nothing here measures or claims incremental behaviour.

Importable API (used by mutate_ops.py): PROBLEMS, FILES, tests, grade_one, build_and_run, compile_pruv, ENTRY_CONTRACTS,
CONTRACT_CHECKS, write_scale_fixture."""
import importlib.util
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import time
from functools import lru_cache

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
    "q01": ["root.pruv", "store.pruv", "store/check.pruv"],
    "q02": ["root.pruv", "tree.pruv", "tree/shape.pruv"],
}

# `mod` declarations the grader requires: (file, module name)
MOD_DECLS = {
    "q01": [("root.pruv", "store"), ("store.pruv", "check")],
    "q02": [("root.pruv", "tree"), ("tree.pruv", "shape")],
}

# root entry -> signature text and requires/ensures lines exactly as in PROBLEMS.md
ENTRY_CONTRACTS = {
    "q01": {
        "find_first": ["pub fn find_first(a: [i64], q: i64) -> i64",
                       "requires len(a) <= 1000",
                       "ensures result == 0 - 1 || (0 <= result && result < len(a))",
                       "ensures result >= 0 ==> a[result] == q && (forall k in 0..result: a[k] != q)",
                       "ensures result < 0 ==> (forall k in 0..len(a): a[k] != q)"],
        "sum_range": ["pub fn sum_range(a: [i64], lo: i64, hi: i64) -> i64",
                      "requires len(a) <= 1000",
                      "requires forall k in 0..len(a): -1000000 <= a[k] && a[k] <= 1000000",
                      "ensures (0 <= lo && lo <= hi && hi <= len(a)) ==> result == sum(k in lo..hi: a[k])",
                      "ensures !(0 <= lo && lo <= hi && hi <= len(a)) ==> result == 0 - 1"],
        "insert_get": ["pub fn insert_get(a: [i64], i: i64, v: i64, j: i64) -> i64 ! alloc",
                       "requires len(a) <= 1000",
                       "ensures (0 <= i && i <= len(a) && 0 <= j && j <= len(a)) ==> ((j < i ==> result == a[j]) "
                       "&& (j == i ==> result == v) && (j > i ==> result == a[j - 1]))",
                       "ensures !(0 <= i && i <= len(a) && 0 <= j && j <= len(a)) ==> result == 0 - 1"],
    },
    "q02": {
        "node_total": ["pub fn node_total(n: i64) -> i64 ! alloc",
                       "requires 0 <= n && n <= 1000",
                       "ensures result == n"],
        "leaf_total": ["pub fn leaf_total(n: i64) -> i64 ! alloc",
                       "requires 0 <= n && n <= 1000",
                       "ensures result == n + 1"],
        "tree_height": ["pub fn tree_height(n: i64) -> i64 ! alloc",
                        "requires 0 <= n && n <= 1000",
                        "ensures 0 <= result && result <= 2 * n + 1"],
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
    whitespace-normalized, with nothing added, removed or rewritten between `pub fn` and the body brace, and the root has
    no other `pub fn` (except `main`); else a message."""
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
    """{relative path: text} of the files of the project directory that exist (FILES order is not used)."""
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


def check_constructs(files, pid):
    """List of missing required constructs (PROBLEMS.md 'Structure required by the grader')."""
    lack = []
    root = strip_comments(files.get("root.pruv", ""))
    if pid == "q01":
        store = strip_comments(files.get("store.pruv", ""))
        check = strip_comments(files.get("store/check.pruv", ""))
        if not re.search(r"^fn\s+\w+", store, re.M):
            lack.append("private helper function in store.pruv")
        if not re.search(r"^pub\s+fn\s+\w+", store, re.M):
            lack.append("pub fn in store.pruv")
        if not re.search(r"^pub\s+fn\s+\w+", check, re.M):
            lack.append("pub fn in store/check.pruv")
        if "crate::store::" not in root:
            lack.append("root reaches store by crate::store:: paths")
    elif pid == "q02":
        tree = strip_comments(files.get("tree.pruv", ""))
        shape = strip_comments(files.get("tree/shape.pruv", ""))
        if "enum Tree" not in norm(tree):
            lack.append("enum Tree in tree.pruv")
        if len(re.findall(r"decreases size\(", tree)) < 3:
            lack.append("at least three `decreases size(` clauses in tree.pruv")
        if not re.search(r"\bmatch\b", tree):
            lack.append("match in tree.pruv")
        if not re.search(r"^pub\s+fn\s+\w+", shape, re.M):
            lack.append("pub fn in tree/shape.pruv")
        if "crate::tree::" not in root:
            lack.append("root reaches tree by crate::tree:: paths")
        if re.search(r"\benum\b", root):
            lack.append("no enum in root.pruv")
    return lack


# ------------------------------------------------------------------ reference semantics (PROBLEMS.md)
def ref_find_first(a, q):
    for i, x in enumerate(a):
        if x == q:
            return i
    return -1


def ref_sum_range(a, lo, hi):
    if 0 <= lo <= hi <= len(a):
        return sum(a[lo:hi])
    return -1


def ref_insert_get(a, i, v, j):
    n = len(a)
    if not (0 <= i <= n and 0 <= j <= n):
        return -1
    return (a[:i] + [v] + a[i:])[j]


@lru_cache(maxsize=None)
def ref_height(n):
    """Height of the balanced tree of the range of n integers (mid = lo + (hi - lo) / 2)."""
    if n == 0:
        return 0
    left = n // 2
    return 1 + max(ref_height(left), ref_height(n - left - 1))


def dbg(kind, v):
    """Rust Debug text of an i64 / bool result."""
    if kind == "b":
        return "true" if v else "false"
    return str(v)


def tests():
    """{pid: [(fn, [(kind, value)], (kind, expected))]}; kinds: i (i64), b (bool), ai ([i64])."""
    rnd = random.Random(2031)
    t = {p: [] for p in PROBLEMS}
    iv = [-1000000, -1, 0, 1, 2, 7, 1000000]
    # q01
    arrs = [[]] + [[v] for v in iv] + [[3, 3, 3], [5, 3, 9, 3], [1, 2, 3, 4, 5], [0, 1, 0, 1], [7, 7, 0]]
    for _ in range(8):
        arrs.append([rnd.choice(iv) for _ in range(rnd.randint(2, 9))])
    arrs.append([rnd.choice(iv + [3, 5, 6]) for _ in range(40)])
    arrs.append([i % 7 - 3 for i in range(1000)])
    for a in arrs:
        n = len(a)
        for q in [0, 1, 2, 6, -1, 7, 1000000, -1000000, MIN, MAX]:
            t["q01"].append(("find_first", [("ai", a), ("i", q)], ("i", ref_find_first(a, q))))
        ranges = [(0, 0), (0, n), (1, n), (n // 2, n), (n, n), (-1, 0), (0, n + 1), (n + 1, n + 1), (2, 1),
                  (MIN, 0), (0, MAX)]
        for lo, hi in ranges:
            t["q01"].append(("sum_range", [("ai", a), ("i", lo), ("i", hi)], ("i", ref_sum_range(a, lo, hi))))
        vs = [42, MIN, MAX] if n <= 9 else [42]
        for i in sorted({0, n // 2, n, -1, n + 1}):
            for j in sorted({0, i, i + 1, n, n + 1, -1}):
                for v in vs:
                    t["q01"].append(("insert_get", [("ai", a), ("i", i), ("i", v), ("i", j)],
                                     ("i", ref_insert_get(a, i, v, j))))
    # q02
    ns = list(range(10)) + [15, 16, 17, 31, 32, 100, 127, 128, 500, 999, 1000]
    ns += [rnd.randint(0, 1000) for _ in range(10)]
    for n in ns:
        t["q02"].append(("node_total", [("i", n)], ("i", n)))
        t["q02"].append(("leaf_total", [("i", n)], ("i", n + 1)))
        t["q02"].append(("tree_height", [("i", n)], ("i", ref_height(n))))
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


def rs_i(v):
    return "i64::MIN" if v == MIN else "i64::MAX" if v == MAX else "(%di64)" % v


# Rust forms of the stated entry ensures (ENTRY_CONTRACTS) for entries whose contracts do not state the full meaning
# (PROBLEMS.md q02 tree_height). Used only by the mutation test to tell a contract-violating mutant from one that keeps
# the stated contracts but computes other results (contract-weak). Scalar argument k of an entry is `xk`, an array
# argument is `vk` (&[i64]); `r` is the result. Every entry of a problem listed here needs a check.
CONTRACT_CHECKS = {
    "q02": {
        "node_total": "r == x0",
        "leaf_total": "r == x0 + 1",
        "tree_height": "r >= 0 && r <= 2 * x0 + 1",
    },
}


def render(pid, contracts=False):
    """(array let-bindings, check lines). Every distinct array is bound once and passed by reference.
    contracts=True renders checks that hold when the result satisfies the stated entry ensures (expected "true")."""
    names = {}
    lets = []

    def arr(v):
        key = tuple(v)
        if key not in names:
            names[key] = "a%d" % len(names)
            body = ", ".join(rs_i(x) for x in v)
            lets.append("    let %s: Vec<i64> = vec![%s];" % (names[key], body))
        return "&" + names[key]

    lines = []
    for fn, args, (ek, ev) in tests()[pid]:
        if contracts:
            binds, cs = [], []
            for idx, (k, v) in enumerate(args):
                if k == "ai":
                    binds.append("let v%d: &[i64] = %s;" % (idx, arr(v)))
                    cs.append("v%d" % idx)
                else:
                    binds.append("let x%d: i64 = %s;" % (idx, rs_i(v)))
                    cs.append("x%d" % idx)
            lines.append('    chk(&mut st, "%s contract", &|| { %s let r: i64 = sol::%s(%s); format!("{}", %s) }, "true");'
                         % (fn, " ".join(binds), fn, ", ".join(cs), CONTRACT_CHECKS[pid][fn]))
        else:
            cs = ", ".join(arr(v) if k == "ai" else rs_i(v) for k, v in args)
            lines.append('    chk(&mut st, "%s", &|| format!("{:?}", sol::%s(%s)), "%s");'
                         % (fn, fn, cs, dbg(ek, ev)))
    return "\n".join(lets), "\n".join(lines)


def build_and_run(sol_path, pid, workdir, llvm_path=None, opt="-O", timeout=120, contracts=False):
    """Build the generated Rust (and the LLVM objects when llvm_path is given), run the tests of problem pid.
    contracts=True checks the stated entry ensures instead of the exact results (CONTRACT_CHECKS)."""
    arrays, checks = render(pid, contracts)
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
    return build_and_run(c["rs"], pid, wd, llvm_path=c["ll"], timeout=timeout, contracts=contracts)


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


# ------------------------------------------------------------------ 100-module scale fixture
SCALE_MODULES = 99      # plus the root: 100 files


def _scale_children(k, total):
    return [c for c in (3 * k + 1, 3 * k + 2, 3 * k + 3) if c <= total]


def _scale_path(k):
    """Module names from the root to module k (module k's parent is (k - 1) // 3; the root is 0)."""
    parts = []
    while k > 0:
        parts.append("m%d" % k)
        k = (k - 1) // 3
    return list(reversed(parts))


def write_scale_fixture(dst, total=SCALE_MODULES):
    """Write the deterministic fixture to directory dst and return {"root", "modules", "files", "lines", "n", "e"}.

    The modules form a ternary tree: module k declares the modules 3k+1..3k+3 (those <= total) and lives in
    m<..>/m<k>.pruv. Every module has a private helper `bump` and a public `step(x)` that calls bump and the `step` of
    every child by absolute paths; its contract is exact: `result == N * x + E` with N and E computed here. The root has
    the host entry `run` that calls the `step` of modules 1..3. No randomness: the same call writes the same bytes."""
    ne = {}
    for k in range(total, 0, -1):       # children have larger numbers than their parent
        kids = _scale_children(k, total)
        ne[k] = (1 + sum(ne[c][0] for c in kids), 1 + sum(ne[c][1] for c in kids))
    files = {}
    for k in range(1, total + 1):
        path = _scale_path(k)
        kids = _scale_children(k, total)
        lines = ["// module crate::%s of the bench/g4 scale fixture (generated, deterministic)" % "::".join(path)]
        lines += ["mod m%d;" % c for c in kids]
        if kids:
            lines.append("")
        lines += ["// private helper: only this module can call it",
                  "fn bump(x: i64) -> i64",
                  "  requires 0 <= x && x <= 1000",
                  "  ensures result == x + 1",
                  "{",
                  "  return x + 1;",
                  "}",
                  "",
                  "pub fn step(x: i64) -> i64",
                  "  requires 0 <= x && x <= 1000",
                  "  ensures result == %d * x + %d" % ne[k],
                  "{",
                  "  let s0: i64 = bump(x);"]
        names = ["s0"]
        for c in kids:
            lines.append("  let s%d: i64 = crate::%s::step(x);" % (c, "::".join(_scale_path(c))))
            names.append("s%d" % c)
        lines += ["  return %s;" % " + ".join(names), "}"]
        files["/".join(path) + ".pruv"] = "\n".join(lines) + "\n"
    kids0 = _scale_children(0, total)
    n0, e0 = sum(ne[c][0] for c in kids0), sum(ne[c][1] for c in kids0)
    lines = ["// root of the bench/g4 scale fixture (generated, deterministic): %d modules in a ternary tree" % total]
    lines += ["mod m%d;" % c for c in kids0]
    lines += ["",
              "pub fn run(x: i64) -> i64",
              "  requires 0 <= x && x <= 1000",
              "  ensures result == %d * x + %d" % (n0, e0),
              "{"]
    names = []
    for c in kids0:
        lines.append("  let s%d: i64 = crate::m%d::step(x);" % (c, c))
        names.append("s%d" % c)
    lines += ["  return %s;" % " + ".join(names), "}"]
    files["root.pruv"] = "\n".join(lines) + "\n"
    n_lines = 0
    for rel, text in sorted(files.items()):
        p = os.path.join(dst, rel)
        if not os.path.isdir(os.path.dirname(p)):
            os.makedirs(os.path.dirname(p))
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        n_lines += text.count("\n")
    return {"root": os.path.join(dst, "root.pruv"), "modules": total, "files": len(files), "lines": n_lines,
            "n": n0, "e": e0}


def run_scale(compilers, backends, repeat, outp, keep):
    d = tempfile.mkdtemp(prefix="pruvg4_scale_")
    info = write_scale_fixture(os.path.join(d, "proj"))
    out = os.path.join(d, "out")
    os.makedirs(out)
    rows = []
    for comp in compilers:
        for backend in backends:
            for mode, flags in (("proof", []), ("no-verify", ["--no-verify"])):
                times, rc, note = [], 0, ""
                for _ in range(repeat):
                    wd = tempfile.mkdtemp(prefix="%s_%s_" % (comp, backend), dir=out)
                    t0 = time.perf_counter()
                    c = compile_pruv(comp, info["root"], wd, backend, flags)
                    times.append(time.perf_counter() - t0)
                    if c["rc"] != 0:
                        rc = c["rc"]
                        e = c["errors"][0] if c["errors"] else {}
                        note = "%s %s %s" % (e.get("stage", ""), e.get("code", ""), (e.get("message") or c["stderr"])[:60])
                        break
                rows.append({"compiler": comp, "backend": backend, "mode": mode, "rc": rc, "runs": len(times),
                             "min_s": round(min(times), 3), "median_s": round(sorted(times)[len(times) // 2], 3),
                             "note": note.strip()})
    od = os.path.dirname(os.path.abspath(outp))
    if not os.path.isdir(od):
        os.makedirs(od)
    with open(outp, "w", encoding="utf-8") as f:
        json.dump({"fixture": {k: v for k, v in info.items() if k != "root"}, "repeat": repeat,
                   "note": "cold whole-program compiles; no incremental claim", "rows": rows}, f, indent=1)
    print("G4 scale fixture: %d modules + root, %d files, %d lines (%s)" % (info["modules"], info["files"],
                                                                         info["lines"], d))
    print("%-4s %-5s %-10s %-3s %8s %8s  %s" % ("comp", "back", "mode", "rc", "min s", "median s", "note"))
    for r in rows:
        print("%-4s %-5s %-10s %-3d %8.3f %8.3f  %s" % (r["compiler"], r["backend"], r["mode"], r["rc"], r["min_s"],
                                                       r["median_s"], r["note"]))
    print("wrote %s" % outp)
    if not keep:
        import shutil
        shutil.rmtree(d, ignore_errors=True)
    else:
        print("kept %s" % d)
    sys.exit(1 if any(r["rc"] != 0 for r in rows) else 0)


USAGE = ("usage: run.py <solutions_dir> [out.json] [--compiler py|rs|both] [--backend rust|llvm|both] "
         "[--no-verify] [qNN ...]\n"
         "       run.py --scale [out.json] [--compiler py|rs|both] [--backend rust|llvm|both] [--repeat N] [--keep]")


def main():
    args = sys.argv[1:]
    opt = {"--compiler": "both", "--backend": "both", "--repeat": "1"}
    for o in opt:
        if o in args:
            i = args.index(o)
            opt[o] = args[i + 1] if i + 1 < len(args) else ""
            del args[i:i + 2]
    flags = [f for f in ("--no-verify",) if f in args]
    scale = "--scale" in args
    keep = "--keep" in args
    only = [a for a in args if a in PROBLEMS]
    args = [a for a in args if not a.startswith("--") and a not in PROBLEMS]
    ok_opts = (opt["--compiler"] in ("py", "rs", "both") and opt["--backend"] in ("rust", "llvm", "both")
               and opt["--repeat"].isdigit() and int(opt["--repeat"]) >= 1)
    if not ok_opts or (not scale and not args) or (scale and flags):
        print(USAGE)
        sys.exit(2)
    compilers = ["py", "rs"] if opt["--compiler"] == "both" else [opt["--compiler"]]
    backends = ["rust", "llvm"] if opt["--backend"] == "both" else [opt["--backend"]]
    if scale:
        outp = args[0] if args else os.path.join(HERE, "results", "scale.json")
        run_scale(compilers, backends, int(opt["--repeat"]), outp, keep)
        return
    sdir = os.path.abspath(args[0])
    outp = args[1] if len(args) > 1 else os.path.join(HERE, "results", os.path.basename(sdir.rstrip("/")) + ".json")
    work = tempfile.mkdtemp(prefix="pruvg4_")
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
    print("G4 grader: %d/%d problem runs ok (work dir %s)" % (total - bad, total, work))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
