"""G1 (structs/enums) grader.
python bench/g1/run.py <solutions_dir> <out.json> [--backend rust|llvm] [--no-verify] [--trust-callers] [gNN ...]
Solutions are gNN.pruv files compiled with pruvc (--pruv is accepted and ignored: Pruv is the only input kind).
Per problem: status ok|wrong|pruv_error|missing|timeout (|compile_error), tests_passed/total, pruv_errors."""
import json, os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
RUSTC = shutil.which("rustc") or os.path.expanduser("~/.cargo/bin/rustc")
PY = os.path.join(ROOT, ".venv/bin/python")
PRUVC = os.path.join(ROOT, "pruvc/pruvc.py")
CLANG = shutil.which("clang") or "/usr/bin/clang"

E = "1_000_000_000"
RECT = "M::Rect { lo: M::Point { x: %(t)s.0, y: %(t)s.1 }, hi: M::Point { x: %(t)s.2, y: %(t)s.3 } }"

# name: (fn, gen expr (uses r, n), call template (uses t, M::))
P = {
 "g01": ("overlap_area",
         "{ let lim = if r.next() %% 3 == 0 { %s } else { 20 }; (r.rect(lim), r.rect(lim)) }" % E,
         "M::overlap_area(%s, %s)" % (RECT % {"t": "t.0"}, RECT % {"t": "t.1"})),
 "g02": ("apply",
         "{ let k = r.range(0, 3); let v = if k == 1 { r.range(-1000, 1000) } else if k == 0 { r.range(-%s, %s) } else { 0 }; "
         "let big = r.next() %% 2 == 0; (if big { r.range(-%s, %s) } else { r.range(-10, 10) }, r.range(0, %s), k, v) }" % (E, E, E, E, E),
         "M::apply(M::Acc { value: t.0, steps: t.1 }, match t.2 { 0 => M::Op::Add(t.3), 1 => M::Op::Mul(t.3), 2 => M::Op::Neg, _ => M::Op::Clear })"),
 "g03": ("stats",
         "({ let (lo, hi) = if r.next() %% 2 == 0 { (-%s, %s) } else { (-5, 5) }; r.arr(n, lo, hi) },)" % (E, E),
         "M::stats(&t.0)"),
 "g04": ("measure",
         "{ let hi = if r.next() % 2 == 0 { 1_000_000 } else { 10 }; (r.range(0, 2), r.range(0, hi), r.range(0, hi), r.range(0, hi), r.range(0, hi)) }",
         "M::measure(match t.0 { 0 => M::Shape::Circle(t.1), 1 => M::Shape::Rect(t.1, t.2), _ => M::Shape::Tri(t.1, t.2, t.3, t.4) })"),
 "g05": ("first_negative",
         "({ let mut v = r.arr(n, 0, %s); if n > 0 && r.next() %% 3 != 0 { for _ in 0..(1 + r.next() %% 3) { let i = r.range(0, n as i64 - 1) as usize; v[i] = r.range(-%s, -1); } } v },)" % (E, E),
         "M::first_negative(&t.0)"),
}

EDGE = {  # extra hand-written inputs (Rust exprs, same type as gen)
 "g01": ["((0, 0, 5, 5), (5, 0, 10, 5))", "((0, 0, 5, 5), (6, 6, 9, 9))", "((0, 0, 5, 5), (1, 1, 2, 2))",
         "((0, 0, 0, 5), (0, 0, 0, 5))", "((-%s, -%s, %s, %s), (-%s, -%s, %s, %s))" % ((E,) * 8),
         "((-%s, -%s, 0, 0), (0, 0, %s, %s))" % ((E,) * 4), "((-%s, -%s, %s, %s), (-1, -1, 1, 1))" % ((E,) * 4),
         "((0, 0, 10, 10), (5, 5, 15, 15))", "((0, 0, 10, 10), (10, 10, 20, 20))"],
 "g02": ["(%s, 0, 0, %s)" % (E, E), "(-%s, 0, 0, -%s)" % (E, E), "(%s, 5, 1, 1000)" % E, "(-%s, 5, 1, 1000)" % E,
         "(-%s, 5, 1, -1000)" % E, "(%s, 1_000_000_000, 2, 0)" % E, "(-%s, 0, 2, 0)" % E, "(7, 3, 3, 0)", "(0, 0, 1, 0)",
         "(0, 0, 0, 0)"],
 "g03": ["(vec![],)", "(vec![5],)", "(vec![-%s],)" % E, "(vec![3, 3, 3],)", "(vec![%s; 1000],)" % E,
         "(vec![-%s; 1000],)" % E, "(vec![1, -1, 2, -2, 0],)", "(vec![0],)"],
 "g04": ["(0, 0, 0, 0, 0)", "(0, 1_000_000, 0, 0, 0)", "(1, 1_000_000, 1_000_000, 0, 0)", "(2, 0, 0, 0, 0)",
         "(2, 1_000_000, 1_000_000, 1_000_000, 1_000_000)", "(2, 1, 1, 3, 3)", "(2, 1, 1, 1, 1)", "(1, 0, 5, 0, 0)"],
 "g05": ["(vec![],)", "(vec![-1],)", "(vec![0],)", "(vec![0, 0, -%s],)" % E, "(vec![-1, -2, -3],)",
         "(vec![%s; 1000],)" % E, "(vec![1, 2, 3, 4, -5, -6],)"],
}

TEMPLATE = r'''
#![allow(dead_code, unused_imports)]
#[path = "@SOL@"] mod sol;
#[path = "@REF@"] mod reference;
struct Lcg(u64);
impl Lcg {
    fn next(&mut self) -> u64 { self.0 = self.0.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407); self.0 >> 17 }
    fn range(&mut self, lo: i64, hi: i64) -> i64 { lo + (self.next() % ((hi - lo + 1) as u64)) as i64 }
    fn arr(&mut self, n: usize, lo: i64, hi: i64) -> Vec<i64> { (0..n).map(|_| self.range(lo, hi)).collect() }
    fn rect(&mut self, lim: i64) -> (i64, i64, i64, i64) {
        let a = self.range(-lim, lim); let b = self.range(-lim, lim);
        let c = self.range(-lim, lim); let d = self.range(-lim, lim);
        (a.min(b), c.min(d), a.max(b), c.max(d))
    }
}
fn check<T: std::fmt::Debug>(t: &T, f: &dyn Fn(&T) -> String, g: &dyn Fn(&T) -> String) -> Option<String> {
    let want = g(t);
    match std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| f(t))) {
        Ok(got) if got == want => None,
        Ok(got) => Some(format!("input {:.200} want {} got {}", format!("{:?}", t), want, got)),
        Err(_) => Some(format!("input {:.200} want {} got PANIC", format!("{:?}", t), want)),
    }
}
fn main() {
    std::panic::set_hook(Box::new(|_| {}));
    let mut r = Lcg(12345);
    let mut inputs = Vec::new();
    @EDGES@
    for _ in 0..300 { let n = r.range(0, 50) as usize; inputs.push(@GEN@); }
    let mut passed = 0; let mut first: Option<String> = None;
    for t in &inputs {
        match check(t, &|t| format!("{:?}", @CALL_SOL@), &|t| format!("{:?}", @CALL_REF@)) {
            None => passed += 1,
            Some(m) => if first.is_none() { first = Some(m) },
        }
    }
    println!("TESTS {} {}", passed, inputs.len());
    if let Some(m) = first { println!("FIRST {}", m.replace('\n', " ")); }
}
'''


def build_llvm_objects(llvm_path, stem, workdir):
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


def build_and_run(sol_path, pid, workdir, llvm_path=None):
    fn, gen, call = P[pid]
    edges = "\n    ".join("inputs.push(%s);" % e for e in EDGE[pid])
    src = (TEMPLATE.replace("@SOL@", sol_path).replace("@REF@", os.path.join(HERE, "reference.rs"))
           .replace("@EDGES@", edges).replace("@GEN@", gen)
           .replace("@CALL_SOL@", call.replace("M::", "sol::"))
           .replace("@CALL_REF@", call.replace("M::", "reference::")))
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
    if out.get("tests_passed") != out.get("tests_total") or "tests_passed" not in out:
        out["status"] = "wrong"
    if r.returncode != 0:
        out["status"] = "wrong"
        out["exit_code"] = r.returncode
        out["stderr"] = r.stderr[-300:]
    return out


USAGE = "usage: run.py <solutions_dir> <out.json> [--backend rust|llvm] [--no-verify] [--trust-callers] [gNN ...]"


def main():
    args = sys.argv[1:]
    backend = "rust"
    if "--backend" in args:
        bi = args.index("--backend")
        backend = args[bi + 1] if bi + 1 < len(args) else ""
        if backend not in ("rust", "llvm"):
            print(USAGE); sys.exit(2)
        del args[bi:bi + 2]
    flags = [f for f in ("--no-verify", "--trust-callers") if f in args]
    args = [a for a in args if not a.startswith("--")]
    if len(args) < 2:
        print(USAGE); sys.exit(2)
    sdir, outp = os.path.abspath(args[0]), args[1]
    only = [a for a in args[2:] if a in P]
    llvm = backend == "llvm"
    res = {}
    work = tempfile.mkdtemp(prefix="pruvg1_")
    for pid in sorted(P):
        if only and pid not in only:
            continue
        src = os.path.join(sdir, pid + ".pruv")
        if not os.path.exists(src):
            res[pid] = {"status": "missing"}; continue
        rs = os.path.join(work, pid + "_gen.rs")
        ll = None
        if llvm:
            ll = os.path.join(work, pid + "_gen.ll")
            cmd = [PY, PRUVC, src, "-o", ll, "--backend", "llvm", "--rust-bindings", rs] + flags
        else:
            cmd = [PY, PRUVC, src, "-o", rs] + flags
        c = subprocess.run(cmd, capture_output=True, text=True)
        if c.returncode != 0:
            errs = []
            for l in c.stdout.splitlines():
                if l.startswith("{"):
                    try:
                        errs.append(json.loads(l))
                    except ValueError:
                        errs.append({"raw": l})
            res[pid] = {"status": "pruv_error", "pruv_errors": errs}
            if not errs:
                res[pid]["stderr"] = (c.stdout + c.stderr)[-500:]
            continue
        res[pid] = build_and_run(rs, pid, work, llvm_path=ll)
    json.dump(res, open(outp, "w"), indent=1, ensure_ascii=False)
    print("%-4s %-13s %-9s %s" % ("id", "status", "tests", "note"))
    for pid, r in res.items():
        t = "%s/%s" % (r.get("tests_passed", "-"), r.get("tests_total", "-"))
        note = ""
        if r["status"] == "pruv_error" and r.get("pruv_errors"):
            e = r["pruv_errors"][0]
            note = "%s %s" % (e.get("stage", ""), e.get("code", ""))
        elif r.get("first_failure"):
            note = r["first_failure"][:80]
        print("%-4s %-13s %-9s %s" % (pid, r["status"], t, note))


if __name__ == "__main__":
    main()
