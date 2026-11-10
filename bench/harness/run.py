"""Benchmark harness.  python run.py <solutions_dir> <out.json> [--pruv]
--pruv: compile pNN.pruv with pruvc first (pruv errors -> status pruv_error)."""
import json, os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
RUSTC = shutil.which("rustc") or os.path.expanduser("~/.cargo/bin/rustc")
sys.path.append(os.path.join(ROOT, "tests"))
import compiler_driver as CD  # noqa: E402

DRIVER = None  # compiler_driver.Driver; set by main() or by an importer such as bench/mutate.py (None -> rs)


def get_driver():
    global DRIVER
    if DRIVER is None:
        DRIVER = CD.default_driver()
    return DRIVER

E = "1_000_000_000"
# name: (fn, gen(rng, n) -> tuple expr, call template with F, perf body with F (uses input t))
P = {
 "p01": ("sum_array", "(r.arr(n, -%s, %s),)" % (E, E), "F(&t.0)", None),
 "p02": ("max_element", "(r.arr(n, -%s, %s),)" % (E, E), "F(&t.0)", None),
 "p03": ("is_sorted", "({ let mut v = r.arr(n, -%s, %s); if r.next() %% 2 == 0 { v.sort(); } v },)" % (E, E), "F(&t.0)", None),
 "p04": ("binary_search", "({ let mut v = r.arr(n, -20, 20); if n > 1000 { v = r.arr(n, -%s, %s); } v.sort(); v }, r.range(-22, 22))" % (E, E),
         "F(&t.0, t.1)",
         "{ let mut acc = 0i64; let mut q = Lcg(7); for _ in 0..1_000_000 { let x = q.range(-%s, %s); if let Some(i) = F(black_box(&t.0), x) { acc = acc.wrapping_add(i); } } acc }" % (E, E)),
 "p05": ("prefix_sums", "(r.arr(n, -%s, %s),)" % (E, E), "F(&t.0)", None),
 "p06": ("max_subarray", "(r.arr(n.max(1), -%s, %s),)" % (E, E), "F(&t.0)", None),
 "p07": ("count_less", "(r.arr(n, -%s, %s), r.range(-%s, %s))" % (E, E, E, E), "F(&t.0, t.1)", None),
 "p08": ("reverse", "(r.arr(n, -%s, %s),)" % (E, E), "F(&t.0)", None),
 "p09": ("dot", "{ let m = if r.next() % 5 == 0 { n + 1 } else { n }; (r.arr(n, -1_000_000, 1_000_000), r.arr(m, -1_000_000, 1_000_000)) }",
         "F(&t.0, &t.1)", None),
 "p10": ("gcd", "(r.range(0, 1_000_000_000_000) / (1 + r.next() as i64 % 1000) * (1 + r.next() as i64 % 3), r.range(0, 1_000_000_000_000))",
         "F(t.0, t.1)",
         "{ let mut acc = 0i64; let mut q = Lcg(9); for _ in 0..1_000_000 { let a = q.range(0, 1_000_000_000_000); let b = q.range(0, 1_000_000_000_000); acc = acc.wrapping_add(F(black_box(a), black_box(b))); } acc }"),
}

EDGE = {  # extra hand-written inputs (Rust tuple exprs)
 "p01": ["(vec![],)", "(vec![%s; 1000],)" % E, "(vec![-%s; 1000],)" % E],
 "p02": ["(vec![],)", "(vec![-%s],)" % E, "(vec![5, 5, 5],)"],
 "p03": ["(vec![],)", "(vec![1],)", "(vec![2, 2, 2],)", "(vec![1, 3, 2],)", "(vec![-%s, %s],)" % (E, E)],
 "p04": ["(vec![], 1)", "(vec![1], 1)", "(vec![1], 0)", "(vec![2, 2, 2, 2], 2)", "(vec![1, 2, 2, 2, 3], 2)", "(vec![1, 3], 2)", "(vec![1, 3], 4)"],
 "p05": ["(vec![],)", "(vec![%s; 1000],)" % E],
 "p06": ["(vec![-5],)", "(vec![-3, -1, -2],)", "(vec![%s; 1000],)" % E, "(vec![-%s; 1000],)" % E, "(vec![2, -1, 2],)"],
 "p07": ["(vec![], 0)", "(vec![1, 1, 1], 1)", "(vec![-%s], %s)" % (E, E)],
 "p08": ["(vec![],)", "(vec![1],)"],
 "p09": ["(vec![], vec![])", "(vec![1], vec![])", "(vec![1_000_000; 1000], vec![-1_000_000; 1000])"],
 "p10": ["(0, 0)", "(0, 5)", "(5, 0)", "(1_000_000_000_000, 999_999_999_989)", "(12, 18)"],
}

PGEN = {"p03": "({ let mut v = r.arr(n, -%s, %s); v.sort(); v },)" % (E, E)}

TEMPLATE = r'''
#![allow(dead_code, unused_imports)]
#[path = "%(sol)s"] mod sol;
#[path = "%(ref)s"] mod reference;
use std::hint::black_box;
use std::time::Instant;
struct Lcg(u64);
impl Lcg {
    fn next(&mut self) -> u64 { self.0 = self.0.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407); self.0 >> 17 }
    fn range(&mut self, lo: i64, hi: i64) -> i64 { lo + (self.next() %% ((hi - lo + 1) as u64)) as i64 }
    fn arr(&mut self, n: usize, lo: i64, hi: i64) -> Vec<i64> { (0..n).map(|_| self.range(lo, hi)).collect() }
}
fn check<T: std::fmt::Debug>(t: &T, f: &dyn Fn(&T) -> String, g: &dyn Fn(&T) -> String) -> Option<String> {
    let want = g(t);
    match std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| f(t))) {
        Ok(got) if got == want => None,
        Ok(got) => Some(format!("input {:.200} want {} got {}", format!("{:?}", t), want, got)),
        Err(_) => Some(format!("input {:.200} PANIC", format!("{:?}", t))),
    }
}
fn median(mut v: Vec<u128>) -> u128 { v.sort(); v[v.len() / 2] }
fn main() {
    std::panic::set_hook(Box::new(|_| {}));
    let mut r = Lcg(12345);
    let mut inputs = Vec::new();
    %(edges)s
    for _ in 0..300 { let n = r.range(0, 50) as usize; inputs.push(%(gen)s); }
    let mut passed = 0; let mut first: Option<String> = None;
    for t in &inputs {
        match check(t, &|t| format!("{:?}", %(call_sol)s), &|t| format!("{:?}", %(call_ref)s)) {
            None => passed += 1,
            Some(m) => if first.is_none() { first = Some(m) },
        }
    }
    println!("TESTS {} {}", passed, inputs.len());
    if let Some(m) = first { println!("FIRST {}", m.replace('\n', " ")); }
    if passed != inputs.len() { return; }
    let n = 1_000_000usize; let mut r = Lcg(777);
    let t = %(pgen)s;
    let (mut ts, mut tr) = (Vec::new(), Vec::new());
    let (mut cs, mut cr) = (String::new(), String::new());
    for _ in 0..21 {
        let s0 = Instant::now(); let a = %(perf_sol)s; ts.push(s0.elapsed().as_nanos()); cs = format!("{:?}", black_box(a)).len().to_string();
        let s0 = Instant::now(); let b = %(perf_ref)s; tr.push(s0.elapsed().as_nanos()); cr = format!("{:?}", black_box(b)).len().to_string();
        let _ = (&cs, &cr);
    }
    println!("PERF {} {}", median(ts), median(tr));
}
'''


CLANG = shutil.which("clang") or "/usr/bin/clang"


def build_llvm_objects(llvm_path, stem, workdir):
    """Compile gen .ll and runtime.c into objects inside workdir.
    Returns (link_args, error_text); error_text is None on success."""
    gen_o = os.path.join(workdir, stem + "_gen.o")
    rt_o = os.path.join(workdir, stem + "_rt.o")
    import platform
    cpu = "-mcpu=native" if platform.machine().lower() in ("arm64", "aarch64") else "-march=native"
    c = subprocess.run([CLANG, "-O2", cpu, "-Wno-override-module", "-c", llvm_path, "-o", gen_o],
                       capture_output=True, text=True)
    if c.returncode != 0:
        return [], "clang (gen.ll): " + c.stderr[-1500:]
    c = subprocess.run([CLANG, "-O2", cpu, "-std=c11", "-DPRUV_RUST_ALLOCATOR", "-c",
                        os.path.join(ROOT, "pruvc/runtime.c"), "-o", rt_o],
                       capture_output=True, text=True)
    if c.returncode != 0:
        return [], "clang (runtime.c): " + c.stderr[-1500:]
    return ["-C", "link-arg=" + gen_o, "-C", "link-arg=" + rt_o], None


def build_and_run(sol_path, pid, workdir, noperf=False, llvm_path=None):
    fn, gen, call, perf = P[pid]
    edges = "\n    ".join("inputs.push(%s);" % e for e in EDGE[pid])
    perf = perf or call.replace("t.", "black_box(&t).")
    src = TEMPLATE % {
        "sol": sol_path, "ref": os.path.join(HERE, "reference.rs"), "edges": edges, "gen": gen, "pgen": PGEN.get(pid, gen),
        "call_sol": call.replace("F", "sol::" + fn), "call_ref": call.replace("F", "reference::" + fn),
        "perf_sol": perf.replace("F(", "sol::%s(" % fn), "perf_ref": perf.replace("F(", "reference::%s(" % fn),
    }
    if noperf:
        src = src.replace("    if passed != inputs.len() { return; }", "    return;")
    main = os.path.join(workdir, pid + "_main.rs")
    exe = os.path.join(workdir, pid + "_bin")
    open(main, "w").write(src)
    extra = []
    if llvm_path:
        extra, err = build_llvm_objects(os.path.abspath(llvm_path), pid, workdir)
        if err:
            return {"status": "compile_error", "compile_error": err[:2000]}
    c = subprocess.run([RUSTC, "-O", "--edition", "2021", "-C", "target-cpu=native", main, "-o", exe] + extra,
                       capture_output=True, text=True)
    if c.returncode != 0:
        return {"status": "compile_error", "compile_error": c.stderr[:2000]}
    try:
        r = subprocess.run([exe], capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return {"status": "timeout"}
    out = {"status": "ok"}
    for line in r.stdout.splitlines():
        p = line.split(" ", 1)
        if p[0] == "TESTS":
            a, b = p[1].split(); out["tests_passed"], out["tests_total"] = int(a), int(b)
        elif p[0] == "FIRST":
            out["first_failure"] = p[1][:400]
        elif p[0] == "PERF":
            a, b = p[1].split(); out["sol_ns"], out["ref_ns"] = int(a), int(b)
    if out.get("tests_passed") != out.get("tests_total") or "tests_passed" not in out:
        out["status"] = "wrong"
    if r.returncode != 0:
        out["status"] = "wrong"
        out["exit_code"] = r.returncode
        out["stderr"] = r.stderr[-300:]
    elif not noperf and out["status"] == "ok" and "sol_ns" not in out:
        out["status"] = "wrong"
    return out


def main():
    global DRIVER
    DRIVER = CD.from_argv(sys.argv)  # --compiler py|rs / --compiler-path PATH, removed from sys.argv
    sdir, outp = os.path.abspath(sys.argv[1]), sys.argv[2]
    pruv = "--pruv" in sys.argv
    backend = "rust"
    if "--backend" in sys.argv:
        bi = sys.argv.index("--backend")
        backend = sys.argv[bi + 1] if bi + 1 < len(sys.argv) else ""
        if backend not in ("rust", "llvm"):
            print("usage: run.py <solutions_dir> <out.json> [--pruv] [--backend rust|llvm] [--no-verify] [--trust-callers] [--compiler py|rs] [--compiler-path PATH] [pNN ...]")
            sys.exit(2)
        if backend == "llvm" and not pruv:
            print("--backend llvm requires --pruv")
            sys.exit(2)
    llvm = backend == "llvm"
    only = [a for a in sys.argv[3:] if a.startswith("p")]
    res = {}
    work = tempfile.mkdtemp(prefix="pruvbench_")
    for pid in sorted(P):
        if only and pid not in only:
            continue
        src = os.path.join(sdir, pid + (".pruv" if pruv else ".rs"))
        if not os.path.exists(src):
            res[pid] = {"status": "missing"}; continue
        if pruv:
            rs = os.path.join(work, pid + "_gen.rs")
            flags = [f for f in ("--no-verify", "--trust-callers") if f in sys.argv]
            ll = None
            drv = get_driver()
            if llvm:
                ll = os.path.join(work, pid + "_gen.ll")
                cmd = drv.argv(src, ll, ["--rust-bindings", rs] + flags, "llvm")
            else:
                cmd = drv.argv(src, rs, flags, "rust")
            c = drv.run(cmd, timeout=None)  # same as before: no timeout
            if c.returncode != 0:
                res[pid] = {"status": "pruv_error", "pruv_errors": [json.loads(l) for l in c.stdout.splitlines() if l.startswith("{")]}
                if c.kind == "crash":  # exit 3 / signal / spawn failure: not a language rejection
                    res[pid]["compiler_crash"] = {"exit": c.returncode, "stderr": c.stderr[-300:]}
                continue
            src = rs
        res[pid] = build_and_run(src, pid, work, llvm_path=ll if pruv else None)
    json.dump(res, open(outp, "w"), indent=1, ensure_ascii=False)
    print("%-4s %-13s %-9s %12s %12s" % ("id", "status", "tests", "sol_ms", "ref_ms"))
    for pid, r in res.items():
        t = "%s/%s" % (r.get("tests_passed", "-"), r.get("tests_total", "-"))
        f = lambda k: "%.3f" % (r[k] / 1e6) if k in r else "-"
        print("%-4s %-13s %-9s %12s %12s" % (pid, r["status"], t, f("sol_ns"), f("ref_ns")))


if __name__ == "__main__":
    main()
