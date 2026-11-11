# -*- coding: utf-8 -*-
"""G2 (u8/bool arrays, str) grader.
python bench/g2/run.py <solutions_dir> <out.json> [--backend rust|llvm] [--compiler py|rs] [--no-verify] [--trust-callers] [qNN ...]
Solutions are qNN.pruv files. Per problem: status ok|wrong|pruv_error|missing|timeout|compile_error,
tests_passed/total, pruv_errors.
Importable API (used by mutate_ops.py): P, compile_pruv, build_and_run."""
import json, os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
RUSTC = shutil.which("rustc") or os.path.expanduser("~/.cargo/bin/rustc")
PY = os.path.join(ROOT, ".venv/bin/python")
PRUVC = os.path.join(ROOT, "pruvc/pruvc.py")
PRUVC_RS = os.path.join(ROOT, "pruvc-rs/target/release/pruvc")
CLANG = shutil.which("clang") or "/usr/bin/clang"

COMPILERS = {"py": [PY, PRUVC], "rs": [PRUVC_RS]}

# name: (fn, gen expr (uses r, n), call template (uses t, M::))
P = {
    "q01": ("clamp_bytes",
            "({ let wide = r.next() % 3 == 0; (0..n).map(|_| if wide { r.range(-1000, 1000) } else { r.range(-300, 600) }).collect::<Vec<i64>>() },)",
            "M::clamp_bytes(&t.0)"),
    "q02": ("ascii_mask",
            "(r.bytes(n),)",
            "M::ascii_mask(&t.0)"),
    "q03": ("add_sat",
            "{ let a = r.bytes(n); let d = r.range(-255, 255); (a, d) }",
            "M::add_sat(&t.0, t.1)"),
    "q04": ("longest_true_run",
            "(r.bools(n),)",
            "M::longest_true_run(&t.0)"),
    "q05": ("count_chars",
            "(r.utf8(n),)",
            "M::count_chars(&t.0)"),
    "q06": ("prefix_chars",
            "{ let s = r.utf8(n); let k = r.range(0, n as i64 + 3); (s, k) }",
            "M::prefix_chars(&t.0, t.1)"),
}

EDGE = {  # extra hand-written inputs (Rust exprs, same type as gen)
    "q01": ["(vec![],)", "(vec![0],)", "(vec![i64::MIN],)", "(vec![i64::MAX],)",
            "(vec![i64::MIN, -1, 0, 1, 254, 255, 256, i64::MAX],)", "(vec![-1],)", "(vec![255],)", "(vec![256],)",
            "(vec![254, 255, 256],)", "(vec![-1, 0, 1],)"],
    "q02": ["(vec![],)", "(vec![0u8],)", "(vec![127u8],)", "(vec![128u8],)", "(vec![255u8],)",
            "(vec![0u8, 127, 128, 255],)", "(vec![126u8, 127, 128, 129],)", "(vec![63u8, 191, 192],)"],
    "q03": ["(vec![], 0)", "(vec![], 255)", "(vec![0u8], 0)", "(vec![0u8], 255)", "(vec![0u8], -255)",
            "(vec![255u8], 255)", "(vec![255u8], -255)", "(vec![255u8], 0)",
            "(vec![0u8, 1, 127, 128, 254, 255], 1)", "(vec![0u8, 1, 127, 128, 254, 255], -1)",
            "(vec![0u8, 255, 100], 255)", "(vec![0u8, 255, 100], -255)"],
    "q04": ["(vec![],)", "(vec![true],)", "(vec![false],)", "(vec![true; 10],)", "(vec![false; 10],)",
            "(vec![true, false, true, true],)", "(vec![true, true, false, true, true, true],)",
            "(vec![false, true, false, true, true, true, true],)", "(vec![true, true, true, false, true],)"],
    "q05": [r'(String::new(),)', r'("a".to_string(),)', r'("\u{e9}".to_string(),)', r'("\u{1F600}".to_string(),)',
            r'("a\u{0}b".to_string(),)', r'("\u{d55c}\u{ae00}".to_string(),)',
            r'("\u{7f}\u{80}\u{7ff}\u{800}\u{ffff}\u{10000}\u{10ffff}".to_string(),)',
            r'("abc".to_string(),)'],
    "q06": [r'(String::new(), 0)', r'(String::new(), 5)', r'("a".to_string(), 0)', r'("a".to_string(), 1)',
            r'("a\u{e9}b".to_string(), 2)', r'("abc".to_string(), 3)', r'("abc".to_string(), 10)',
            r'("\u{1F600}\u{1F600}\u{1F600}".to_string(), 1)', r'("\u{1F600}\u{1F600}\u{1F600}".to_string(), 2)',
            r'("a\u{1F600}b".to_string(), 2)', r'("\u{d55c}\u{ae00}".to_string(), 1)',
            r'("\u{d55c}\u{ae00}".to_string(), 2)', r'("\u{d55c}\u{ae00}".to_string(), 3)',
            r'("a\u{0}b".to_string(), 2)'],
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
    fn bytes(&mut self, n: usize) -> Vec<u8> { (0..n).map(|_| (self.next() % 256) as u8).collect() }
    fn bools(&mut self, n: usize) -> Vec<bool> { (0..n).map(|_| self.next() % 2 == 0).collect() }
    fn utf8(&mut self, n: usize) -> String {
        let mut s = String::new();
        for _ in 0..n {
            let k = self.next() % 6;
            let cp: u32 = if k < 3 {
                (self.next() % 128) as u32
            } else if k == 3 {
                0x80 + (self.next() % (0x800 - 0x80)) as u32
            } else if k == 4 {
                let mut c = 0x800 + (self.next() % 0xF000) as u32;
                if c >= 0xD800 { c += 0x800; }
                c
            } else {
                0x10000 + (self.next() % (0x110000 - 0x10000)) as u32
            };
            s.push(char::from_u32(cp).unwrap());
        }
        s
    }
}
fn check<T: std::fmt::Debug>(t: &T, f: &dyn Fn(&T) -> String, g: &dyn Fn(&T) -> String) -> Option<String> {
    let want = g(t);
    match std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| f(t))) {
        Ok(got) if got == want => None,
        Ok(got) => Some(format!("input {:.200} want {:.200} got {:.200}", format!("{:?}", t), want, got)),
        Err(_) => Some(format!("input {:.200} want {:.200} got PANIC", format!("{:?}", t), want)),
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
                       capture_output=True, encoding="utf-8", errors="replace")
    if c.returncode != 0:
        return [], "clang (gen.ll): " + c.stderr[-1500:]
    c = subprocess.run([CLANG, "-O2", cpu, "-std=c11", "-DPRUV_RUST_ALLOCATOR", "-c",
                        os.path.join(ROOT, "pruvc/runtime.c"), "-o", rt_o],
                       capture_output=True, encoding="utf-8", errors="replace")
    if c.returncode != 0:
        return [], "clang (runtime.c): " + c.stderr[-1500:]
    return ["-C", "link-arg=" + gen_o, "-C", "link-arg=" + rt_o], None


def compile_pruv(compiler, src, workdir, backend="rust", flags=()):
    """Compile only. compiler: "py" | "rs". Returns
    {"rc", "errors" (JSON error dicts), "rs" (path), "ll" (path or None), "stderr" (last 500 chars)}.
    rc == -1 on timeout (600 s); rc == -2 if the compiler could not be started."""
    stem = os.path.splitext(os.path.basename(src))[0]
    rs = os.path.join(workdir, stem + "_gen.rs")
    ll = None
    base = list(COMPILERS[compiler])
    if backend == "llvm":
        ll = os.path.join(workdir, stem + "_gen.ll")
        cmd = base + [src, "-o", ll, "--backend", "llvm", "--rust-bindings", rs] + list(flags)
    else:
        cmd = base + [src, "-o", rs] + list(flags)
    try:
        c = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=600)
    except subprocess.TimeoutExpired:
        return {"rc": -1, "errors": [], "rs": rs, "ll": ll, "stderr": "timeout"}
    except OSError as e:
        return {"rc": -2, "errors": [], "rs": rs, "ll": ll, "stderr": str(e)[-500:]}
    errs = []
    for l in c.stdout.splitlines():
        if l.startswith("{"):
            try:
                errs.append(json.loads(l))
            except ValueError:
                errs.append({"raw": l})
    return {"rc": c.returncode, "errors": errs, "rs": rs, "ll": ll, "stderr": (c.stdout + c.stderr)[-500:]}


def build_and_run(sol_path, pid, workdir, llvm_path=None):
    fn, gen, call = P[pid]
    edges = "\n    ".join("inputs.push(%s);" % e for e in EDGE[pid])
    src = (TEMPLATE.replace("@SOL@", sol_path).replace("@REF@", os.path.join(HERE, "reference.rs"))
           .replace("@EDGES@", edges).replace("@GEN@", gen)
           .replace("@CALL_SOL@", call.replace("M::", "sol::"))
           .replace("@CALL_REF@", call.replace("M::", "reference::")))
    main = os.path.join(workdir, pid + "_main.rs")
    exe = os.path.join(workdir, pid + "_bin")
    with open(main, "w", encoding="utf-8") as f:
        f.write(src)
    extra = []
    if llvm_path:
        extra, err = build_llvm_objects(os.path.abspath(llvm_path), pid, workdir)
        if err:
            return {"status": "compile_error", "compile_error": err[:2000]}
    c = subprocess.run([RUSTC, "-O", "--edition", "2021", "-C", "target-cpu=native", main, "-o", exe] + extra,
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


USAGE = ("usage: run.py <solutions_dir> <out.json> [--backend rust|llvm] [--compiler py|rs] "
         "[--no-verify] [--trust-callers] [qNN ...]")


def main():
    args = sys.argv[1:]
    backend = "rust"
    compiler = "py"
    for opt in ("--backend", "--compiler"):
        if opt in args:
            bi = args.index(opt)
            val = args[bi + 1] if bi + 1 < len(args) else ""
            del args[bi:bi + 2]
            if opt == "--backend":
                if val not in ("rust", "llvm"):
                    print(USAGE); sys.exit(2)
                backend = val
            else:
                if val not in ("py", "rs"):
                    print(USAGE); sys.exit(2)
                compiler = val
    flags = [f for f in ("--no-verify", "--trust-callers") if f in args]
    args = [a for a in args if not a.startswith("--")]
    if len(args) < 2:
        print(USAGE); sys.exit(2)
    sdir, outp = os.path.abspath(args[0]), args[1]
    only = [a for a in args[2:] if a in P]
    res = {}
    work = tempfile.mkdtemp(prefix="pruvg2_")
    for pid in sorted(P):
        if only and pid not in only:
            continue
        src = os.path.join(sdir, pid + ".pruv")
        if not os.path.exists(src):
            res[pid] = {"status": "missing"}; continue
        c = compile_pruv(compiler, src, work, backend, flags)
        if c["rc"] != 0:
            res[pid] = {"status": "pruv_error", "pruv_errors": c["errors"]}
            if not c["errors"]:
                res[pid]["stderr"] = c["stderr"]
            continue
        res[pid] = build_and_run(c["rs"], pid, work, llvm_path=c["ll"])
    with open(outp, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1, ensure_ascii=False)
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
