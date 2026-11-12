# -*- coding: utf-8 -*-
"""G9 (recursion, recursive types, buffer fields) grader for the four problems of bench/g9/PROBLEMS.md.

  python bench/g9/run.py <solutions_dir> [out.json] [--compiler py|rs|both] [--backend rust|llvm|both]
                         [--no-verify] [qNN ...]

Defaults: both compilers, both backends (4 configurations), out = bench/g9/results/<dir name>.json.
Per problem and configuration: status ok|wrong|pruv_error|missing|timeout|compile_error, tests_passed/total.
The expected results are computed here in Python (the reference semantics of PROBLEMS.md), embedded as text in a
generated Rust test program, and compared (Debug text) with what the compiled public wrappers return.
Before compiling, the wrapper contracts are checked against WRAPPER_CONTRACTS (a mismatch is a pruv_error with the
message "contract changed"); after a successful run the required constructs of each problem are checked.
Importable API (used by mutate_ops.py): PROBLEMS, tests, grade_one, build_and_run, compile_pruv, WRAPPER_CONTRACTS."""
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

PROBLEMS = ["q01", "q02", "q03", "q04"]
MIN, MAX = -9223372036854775808, 9223372036854775807
IV = [MIN, -1, 0, 1, 2, 7, MAX]

# wrapper -> (signature text, [requires/ensures lines]) exactly as in PROBLEMS.md
WRAPPER_CONTRACTS = {
    "q01": {
        "find_first": ["fn find_first(a: [i64], q: i64) -> i64",
                       "requires len(a) <= 1000000",
                       "ensures result == 0 - 1 || (0 <= result && result < len(a))",
                       "ensures result >= 0 ==> a[result] == q && (forall k in 0..result: a[k] != q)",
                       "ensures result < 0 ==> (forall k in 0..len(a): a[k] != q)"],
        "all_below": ["fn all_below(a: [i64], t: i64) -> bool",
                      "requires len(a) <= 1000000",
                      "ensures result == (forall k in 0..len(a): a[k] < t)"],
    },
    "q02": {
        "node_count": ["fn node_count(a: [i64]) -> i64 ! alloc",
                       "requires len(a) <= 1000",
                       "ensures result == len(a)"],
        "empty_count": ["fn empty_count(a: [i64]) -> i64 ! alloc",
                        "requires len(a) <= 1000",
                        "ensures result == len(a) + 1"],
    },
    "q03": {
        "value_end": ["fn value_end(a: [i64], i: i64) -> i64",
                      "requires 0 <= i && i <= len(a) && len(a) <= 1000",
                      "ensures result == 0 - 1 || (i < result && result <= len(a))",
                      "ensures (i < len(a) && a[i] == 0) ==> result == i + 1",
                      "ensures (i == len(a) || (a[i] != 0 && a[i] != 1)) ==> result == 0 - 1"],
        "is_value": ["fn is_value(a: [i64]) -> bool",
                     "requires len(a) <= 1000",
                     "ensures result ==> len(a) >= 1",
                     "ensures (len(a) == 1 && a[0] == 0) ==> result",
                     "ensures (len(a) >= 1 && a[0] == 0 && len(a) != 1) ==> !result"],
    },
    "q04": {
        "bumped_first": ["fn bumped_first(a: [i64], d: i64) -> i64 ! alloc",
                         "requires 1 <= len(a) && len(a) <= 1000",
                         "requires -1000000000 <= a[0] && a[0] <= 1000000000",
                         "requires -1000000000 <= d && d <= 1000000000",
                         "ensures result == 2 * a[0] + d"],
        "swapped_lengths": ["fn swapped_lengths(a: [i64], b: [i64]) -> i64 ! alloc",
                            "requires len(a) <= 1000 && len(b) <= 1000",
                            "ensures result == 1000 * len(b) + len(a)"],
    },
}


def norm(s):
    return re.sub(r"\s+", " ", s).strip()


def strip_comments(text):
    return re.sub(r"//[^\n]*", "", text)


def wrapper_header(text, name):
    """Normalized text from `fn name(` up to the body brace, or None."""
    m = re.search(r"\bfn\s+%s\s*\(" % re.escape(name), strip_comments(text))
    if not m:
        return None
    body = strip_comments(text)[m.start():]
    end = body.find("{")
    return norm(body if end < 0 else body[:end])


def check_contracts(text, pid):
    """None when every wrapper of pid carries its signature and contract lines unchanged (whitespace-normalized) and
    has no extra `requires`; else a message."""
    for name, lines in WRAPPER_CONTRACTS[pid].items():
        head = wrapper_header(text, name)
        if head is None:
            return "contract changed: wrapper %s not found" % name
        for ln in lines:
            if norm(ln) not in head:
                return "contract changed: %s lacks `%s`" % (name, ln)
        want = sum(1 for ln in lines if ln.startswith("requires"))
        if len(re.findall(r"\brequires\b", head)) != want:
            return "contract changed: %s has a different number of requires" % name
    return None


def check_constructs(text, pid):
    """List of missing required constructs (PROBLEMS.md 'Required constructs')."""
    t = strip_comments(text)
    n = norm(t)
    lack = []
    if pid == "q01":
        if "decreases" not in t:
            lack.append("decreases")
        if re.search(r"\bwhile\b", t):
            lack.append("no `while` allowed")
    elif pid == "q02":
        if "enum Tree" not in n:
            lack.append("enum Tree")
        if "decreases size(" not in n:
            lack.append("decreases size(")
        if not re.search(r"\bmatch\b", t):
            lack.append("match")
    elif pid == "q03":
        if len(re.findall(r"\bdecreases\b", t)) < 2:
            lack.append("at least two decreases clauses")
    elif pid == "q04":
        for tok in ("struct Buf", "struct Pair", "assert p.left.data[0] == a[0];",
                    "assert len(p.left.data) == len(a);"):
            if tok not in n:
                lack.append(tok)
    return lack


# ------------------------------------------------------------------ reference semantics (PROBLEMS.md)
def ref_find_first(a, q):
    for i, x in enumerate(a):
        if x == q:
            return i
    return -1


def ref_all_below(a, t):
    return all(x < t for x in a)


def ref_node_count(a):
    return len(a)


def ref_empty_count(a):
    return len(a) + 1


def ref_value_end(a, i):
    """Token grammar: 0 atom, 1 open, 2 close. End position of the value starting at i, or -1."""
    if i >= len(a):
        return -1
    if a[i] == 0:
        return i + 1
    if a[i] != 1:
        return -1
    j = i + 1
    while True:
        if j >= len(a):
            return -1
        if a[j] == 2:
            return j + 1
        k = ref_value_end(a, j)
        if k < 0:
            return -1
        j = k


def ref_is_value(a):
    return ref_value_end(a, 0) == len(a)


def ref_bumped_first(a, d):
    return 2 * a[0] + d


def ref_swapped_lengths(a, b):
    return 1000 * len(b) + len(a)


def dbg(kind, v):
    """Rust Debug text of an i64 / bool result."""
    if kind == "b":
        return "true" if v else "false"
    return str(v)


def tests():
    """{pid: [(fn, [(kind, value)], (kind, expected))]}; kinds: i (i64), b (bool), ai ([i64])."""
    rnd = random.Random(2029)
    t = {p: [] for p in PROBLEMS}
    # q01
    arrs = [[]] + [[v] for v in IV] + [[1, 1, 1], [5, 3, 9, 3], [0, 1, 0, 1], [2, 2, 2, 1, 2], [7, 7, 0]]
    for _ in range(10):
        arrs.append([rnd.choice(IV) for _ in range(rnd.randint(4, 9))])
    arrs.append([rnd.choice(IV + [3, 5, 6]) for _ in range(40)])
    arrs.append([i % 7 for i in range(2000)])
    for a in arrs:
        for q in [0, 1, 2, 6, MIN, MAX, -1, 7]:
            t["q01"].append(("find_first", [("ai", a), ("i", q)], ("i", ref_find_first(a, q))))
            t["q01"].append(("all_below", [("ai", a), ("i", q)], ("b", ref_all_below(a, q))))
    # q02
    lens = [0, 1, 2, 3, 7, 8, 40, 1000] + [rnd.randint(0, 100) for _ in range(10)]
    for n in lens:
        a = [rnd.choice(IV) for _ in range(n)]
        t["q02"].append(("node_count", [("ai", a)], ("i", ref_node_count(a))))
        t["q02"].append(("empty_count", [("ai", a)], ("i", ref_empty_count(a))))
    # q03
    toks = [[], [0], [1, 2], [1, 0, 0, 2], [1, 1, 2, 0, 2], [2], [1], [1, 0], [1, 3, 2], [0, 0], [1, 0, 1, 2, 2, 0],
            [1, 1, 1, 2, 2, 2], [1, 2, 2], [3], [0, 2], [1, 0, 0], [1, 1, 0, 2], [1, 2, 1, 2], [1, 2, 0],
            [1, 1, 2, 2, 0], [1, 0, 1, 0, 2, 2], [-1], [1, -1, 2], [1, 1, 3, 2, 2]]
    for _ in range(15):
        toks.append([rnd.choice([0, 1, 2]) for _ in range(rnd.randint(1, 12))])
    toks.append([1] * 40 + [0] + [2] * 40)          # nested list of depth 40
    toks.append([1] + [0] * 500 + [2])              # flat list of 500 atoms
    for a in toks:
        for i in range(len(a) + 1):
            t["q03"].append(("value_end", [("ai", a), ("i", i)], ("i", ref_value_end(a, i))))
        t["q03"].append(("is_value", [("ai", a)], ("b", ref_is_value(a))))
    # q04
    firsts = [-1000000000, -1, 0, 1, 7, 1000000000]
    barrs = []
    for k in range(19):
        n = rnd.randint(1, 9)
        barrs.append([firsts[k % len(firsts)]] + [rnd.choice(IV) for _ in range(n - 1)])
    barrs.append([firsts[rnd.randrange(len(firsts))]] + [rnd.choice(IV) for _ in range(999)])
    for a in barrs:
        for d in [-1000000000, -3, 0, 5, 1000000000]:
            t["q04"].append(("bumped_first", [("ai", a), ("i", d)], ("i", ref_bumped_first(a, d))))
    sized = {n: [rnd.choice(IV) for _ in range(n)] for n in (0, 1, 2, 9, 1000)}
    for na in sized:
        for nb in sized:
            a, b = sized[na], sized[nb]
            t["q04"].append(("swapped_lengths", [("ai", a), ("ai", b)], ("i", ref_swapped_lengths(a, b))))
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


def render(pid):
    """(array let-bindings, check lines). Every distinct array is bound once and passed by reference."""
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
        cs = ", ".join(arr(v) if k == "ai" else rs_i(v) for k, v in args)
        lines.append('    chk(&mut st, "%s", &|| format!("{:?}", sol::%s(%s)), "%s");' % (fn, fn, cs, dbg(ek, ev)))
    return "\n".join(lets), "\n".join(lines)


# Rust forms of the stated wrapper ensures (WRAPPER_CONTRACTS) for problems whose contracts do not state the full
# meaning (PROBLEMS.md q03). Used only by the mutation test to tell a contract-violating mutant from one that keeps the
# stated contracts but computes other results (contract-weak). `a` is &[i64], `n` = a.len() as i64, `r` the result.
CONTRACT_CHECKS = {
    "q03": {
        "value_end": "(r == -1 || (i < r && r <= n)) && (!(i < n && a[i as usize] == 0) || r == i + 1)"
                     " && (!(i == n || (a[i as usize] != 0 && a[i as usize] != 1)) || r == -1)",
        "is_value": "(!r || n >= 1) && (!(n == 1 && a[0] == 0) || r) && (!(n >= 1 && a[0] == 0 && n != 1) || !r)",
    },
}


def render_contracts(pid):
    """Like render, but each check holds when the result satisfies the stated wrapper ensures (expected "true")."""
    arrays, _ = render(pid)
    names = {}
    for ln in arrays.splitlines():
        nm, body = ln.strip()[4:].split(": Vec<i64> = vec![", 1)
        names[body[:-2]] = nm
    lines = []
    for fn, args, _ in tests()[pid]:
        a = names[", ".join(rs_i(x) for x in args[0][1])]
        rest = [rs_i(v) for _, v in args[1:]]
        binds = "let a: &[i64] = &%s; let n = a.len() as i64; " % a
        if rest:
            binds += "let i: i64 = %s; " % rest[0]
        call = "sol::%s(%s)" % (fn, ", ".join(["a"] + (["i"] if rest else [])))
        lines.append('    chk(&mut st, "%s contract", &|| { %slet r = %s; format!("{}", %s) }, "true");'
                     % (fn, binds, call, CONTRACT_CHECKS[pid][fn]))
    return arrays, "\n".join(lines)


def build_and_run(sol_path, pid, workdir, llvm_path=None, opt="-O", timeout=120, contracts=False):
    """Build the generated Rust (and the LLVM objects when llvm_path is given), run the tests of problem pid.
    contracts=True checks the stated wrapper ensures instead of the exact results (CONTRACT_CHECKS)."""
    arrays, checks = render_contracts(pid) if contracts else render(pid)
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


def grade_one(src, pid, compiler, backend, flags, work, timeout=120, contracts=False):
    """Compile solution file `src` for problem pid in one configuration and run its tests. Result dict with status."""
    with open(src, encoding="utf-8") as f:
        msg = check_contracts(f.read(), pid)
    if msg:
        return {"status": "pruv_error", "rc": 1, "pruv_errors": [{"stage": "grader", "code": "contract_changed",
                                                                  "message": msg}]}
    wd = tempfile.mkdtemp(prefix="%s_%s_%s_" % (compiler, backend, pid), dir=work)
    c = compile_pruv(compiler, src, wd, backend, list(flags))
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
        src = os.path.join(sdir, pid + ".pruv")
        if not os.path.exists(src):
            res[pid] = {"status": "missing"}
            continue
        r = grade_one(src, pid, compiler, backend, flags, work)
        if r["status"] == "ok":
            with open(src, encoding="utf-8") as f:
                lacking = check_constructs(f.read(), pid)
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
    if not args or opt["--compiler"] not in ("py", "rs", "both") or opt["--backend"] not in ("rust", "llvm", "both"):
        print(USAGE)
        sys.exit(2)
    sdir = os.path.abspath(args[0])
    outp = args[1] if len(args) > 1 else os.path.join(HERE, "results", os.path.basename(sdir.rstrip("/")) + ".json")
    compilers = ["py", "rs"] if opt["--compiler"] == "both" else [opt["--compiler"]]
    backends = ["rust", "llvm"] if opt["--backend"] == "both" else [opt["--backend"]]
    work = tempfile.mkdtemp(prefix="pruvg9_")
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
    print("G9 grader: %d/%d problem runs ok (work dir %s)" % (total - bad, total, work))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
