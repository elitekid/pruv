"""Run all regression tests.
python tests/run_all.py [--only must_reject|examples|runtime] [--backend rust|llvm|both]

Every test case is an independent job (name, ok, detail) run in a thread pool
(os.cpu_count() workers); results are printed in the fixed original order as soon
as each one and all earlier ones are finished. runtime.c is compiled once per
variant and reused; every job uses its own work file names.

Optional runtime json field "contract_budget": N appends
["--contract-budget", str(N)] to the vowc flags of every matrix row (labels unchanged).
Optional runtime json field "ll_contains": [strings] (llvm backend only) must each occur in
the WHOLE generated .ll text (not just __vow_body functions)."""
import concurrent.futures, glob, json, os, platform, re, shutil, subprocess, sys, tempfile, threading

CPU_FLAG = "-mcpu=native" if platform.machine().lower() in ("arm64", "aarch64") else "-march=native"
BODY_DEF = re.compile(r"^define internal [^\n]*@([A-Za-z0-9_.$]+?)__vow_body\(", re.M)


def body_functions(text):
    """{mangled name: text of the `@name__vow_body(` definition} from an .ll text."""
    out = {}
    for m in BODY_DEF.finditer(text):
        end = text.find("\n}", m.start())
        out[m.group(1)] = text[m.start(): end + 2 if end >= 0 else len(text)]
    return out

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
VENV_PY = os.path.join(ROOT, ".venv/bin/python")
PY = VENV_PY if os.path.exists(VENV_PY) else sys.executable
RUSTC = shutil.which("rustc") or os.path.expanduser("~/.cargo/bin/rustc")
CLANG = shutil.which("clang") or "/usr/bin/clang"
VOWC = os.path.join(ROOT, "vowc/vowc.py")
RUNTIME_C = os.path.join(ROOT, "vowc/runtime.c")

WORK = None  # temp dir, set in main()
_rt_cache = {}  # count_allocs -> (object path or None, error or None)
_rt_lock = threading.Lock()


def vowc(src, out, flags=()):
    return subprocess.run([PY, VOWC, src, "-o", out] + list(flags), capture_output=True, text=True, timeout=300)


def vowc_llvm(src, ll, rs, flags=()):
    """LLVM backend: writes IR to ll and Rust bindings to rs."""
    return vowc(src, ll, ["--backend", "llvm", "--rust-bindings", rs] + list(flags))


def runtime_object(count_allocs):
    """runtime.c object for the variant, compiled once (thread-safe). Returns (path, error)."""
    with _rt_lock:
        if count_allocs not in _rt_cache:
            rt_o = os.path.join(WORK, "runtime%s.o" % ("_count" if count_allocs else ""))
            extra = ["-DVOW_COUNT_ALLOCS"] if count_allocs else []
            try:
                c = subprocess.run([CLANG, "-O2", CPU_FLAG, "-std=c11", "-DVOW_RUST_ALLOCATOR"] + extra + ["-c", RUNTIME_C, "-o", rt_o],
                                   capture_output=True, text=True, timeout=300)
                if c.returncode != 0:
                    _rt_cache[count_allocs] = (None, "clang (runtime.c): " + c.stderr[-400:])
                else:
                    _rt_cache[count_allocs] = (rt_o, None)
            except subprocess.TimeoutExpired:
                _rt_cache[count_allocs] = (None, "clang (runtime.c): timeout")
        return _rt_cache[count_allocs]


def llvm_objects(ll, stem, work, count_allocs=False):
    """clang gen.ll to an object in work; runtime.c object is shared. Returns (rustc link args, error or None)."""
    gen_o = os.path.join(work, stem + "_gen.o")
    c = subprocess.run([CLANG, "-O2", CPU_FLAG, "-Wno-override-module", "-c", ll, "-o", gen_o],
                       capture_output=True, text=True, timeout=300)
    if c.returncode != 0:
        return [], "clang (gen.ll): " + c.stderr[-400:]
    rt_o, err = runtime_object(count_allocs)
    if err:
        return [], err
    return ["-C", "link-arg=" + gen_o, "-C", "link-arg=" + rt_o], None


def safe(name, fn):
    """Wrap a job body so that it always returns (name, ok, detail)."""
    def job():
        try:
            ok, detail = fn()
            return (name, ok, detail)
        except subprocess.TimeoutExpired:
            return (name, False, "timeout")
        except Exception as e:
            return (name, False, repr(e))
    return job


def must_reject_jobs():
    jobs = []
    for f in sorted(glob.glob(os.path.join(ROOT, "tests/must_reject/*.vow"))):
        name = "must_reject/" + os.path.basename(f)

        def fn(f=f):
            c = vowc(f, os.path.join(WORK, "mr_%s.rs" % os.path.splitext(os.path.basename(f))[0]))
            ok = c.returncode == 1
            detail = "exit %d (expected 1) %s" % (c.returncode, c.stdout + c.stderr)
            jf = os.path.splitext(f)[0] + ".json"
            if ok and os.path.exists(jf):
                want = json.load(open(jf))
                diags = []
                for line in c.stdout.splitlines():
                    try:
                        d = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(d, dict):
                        diags.append(d)
                ok = any(d.get("stage") == want.get("stage") and d.get("code") == want.get("code") for d in diags)
                detail = "expected stage=%s code=%s; got %s" % (
                    want.get("stage"), want.get("code"),
                    [(d.get("stage"), d.get("code")) for d in diags])
            return ok, detail
        jobs.append(safe(name, fn))
    return jobs


EXAMPLE_MODES = [("default", []), ("no-verify", ["--no-verify"]), ("trust-callers", ["--trust-callers"])]
ARITH_OR_INDEX = re.compile(r"\b(add|sub|mul|getelementptr)\b")


def example_job(f, mode, flags, llvm, name):
    base = os.path.basename(f)
    stem = os.path.splitext(base)[0]
    work = WORK

    def fn():
        if base == "bad_index.vow":
            if llvm:
                c = vowc_llvm(f, os.path.join(work, stem + "_bad.ll"), os.path.join(work, stem + "_bad_llvm.rs"))
            else:
                c = vowc(f, os.path.join(work, stem + ".rs"))
            return c.returncode == 1, "exit %d (expected rejection) %s" % (c.returncode, c.stdout + c.stderr)
        if llvm:
            key = "%s_%s_llvm" % (stem, mode)
            ll = os.path.join(work, key + ".ll")
            rs = os.path.join(work, key + ".rs")
            c = vowc_llvm(f, ll, rs, flags)
            if c.returncode != 0:
                return False, "vowc exit %d %s" % (c.returncode, c.stdout + c.stderr)
            text = open(ll).read()
            bodies = body_functions(text)
            if not bodies:
                return False, "no @..__vow_body( definitions found in .ll"
            bad = None
            for fname, btxt in bodies.items():
                if mode == "no-verify":
                    if " nsw " in btxt:
                        bad = "--no-verify body %s contains nsw" % fname
                elif mode == "default":
                    if ARITH_OR_INDEX.search(btxt) and "nsw" not in btxt and "inbounds" not in btxt:
                        bad = "proof-mode body %s has neither nsw nor inbounds" % fname
                if bad:
                    break
            if bad:
                return False, bad
            link, err = llvm_objects(ll, key, work)
            if err:
                return False, err
            main = os.path.join(work, key + "_main.rs")
            with open(main, "w") as fh:
                fh.write('#![allow(dead_code, unused_imports)]\n#[path = "%s"] mod sol;\nfn main() {}\n' % rs)
            r = subprocess.run([RUSTC, "-O", "--edition", "2021", main, "-o", os.path.join(work, key + "_bin")] + link,
                               capture_output=True, text=True, timeout=300)
            return r.returncode == 0, "rustc link: " + r.stderr[-400:]
        out = os.path.join(work, "%s_%s.rs" % (stem, mode))
        c = vowc(f, out, flags)
        if c.returncode != 0:
            return False, "vowc exit %d %s" % (c.returncode, c.stdout + c.stderr)
        if mode == "no-verify":
            text = open(out).read()
            bad = [s for s in ("unsafe", "get_unchecked") if s in text]
            if bad:
                return False, "--no-verify output contains %s" % bad
        r = subprocess.run([RUSTC, "--crate-type=lib", "-O", "--edition", "2021", out,
                            "--crate-name", stem, "-o", os.path.join(work, "lib%s_%s.rlib" % (stem, mode))],
                           capture_output=True, text=True, timeout=300)
        return r.returncode == 0, "rustc: " + r.stderr[-400:]
    return safe(name, fn)


def examples_jobs(backend):
    llvm = backend == "llvm"
    tag = " [llvm]" if llvm else ""
    jobs = []
    for f in sorted(glob.glob(os.path.join(ROOT, "examples/*.vow"))):
        base = os.path.basename(f)
        if base == "bad_index.vow":
            jobs.append(example_job(f, "bad", [], llvm, "examples/" + base + tag))
            continue
        for mode, flags in EXAMPLE_MODES:
            jobs.append(example_job(f, mode, flags, llvm, "examples/%s [%s]%s" % (base, mode, tag)))
    return jobs


def runtime_job(j, t, spec, flags, name, suffix, llvm):
    work = WORK

    def fn():
        d = os.path.dirname(j)
        vow, drv = os.path.join(d, t + ".vow"), os.path.join(d, t + ".rs")
        link = []
        if llvm:
            key = t + suffix + "_llvm"
            ll = os.path.join(work, key + ".ll")
            gen = os.path.join(work, key + "_gen.rs")
            c = vowc_llvm(vow, ll, gen, flags)
        else:
            key = t + suffix
            gen = os.path.join(work, key + "_gen.rs")
            c = vowc(vow, gen, flags)
        if c.returncode != 0:
            return False, "vowc exit %d %s" % (c.returncode, c.stdout + c.stderr)
        if llvm:
            link, err = llvm_objects(ll, key, work, bool(spec.get("alloc_balance")))
            if err:
                return False, err
        main = os.path.join(work, key + "_main.rs")
        with open(main, "w") as fh:
            fh.write('#![allow(dead_code, unused_imports)]\n#[path = "%s"] mod sol;\n' % gen)
            fh.write(open(drv).read())
        exe = os.path.join(work, key + "_bin")
        r = subprocess.run([RUSTC, "-O", "--edition", "2021", main, "-o", exe] + link,
                           capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            return False, "rustc: " + r.stderr[-400:]
        p = subprocess.run([exe], capture_output=True, text=True, timeout=60)
        problems = []
        if p.returncode != spec["exit"]:
            problems.append("exit %d (expected %d)" % (p.returncode, spec["exit"]))
        so, se = spec.get("stdout_contains"), spec.get("stderr_contains")
        if so is not None and so not in p.stdout:
            problems.append("stdout %r lacks %r" % (p.stdout[:150], so))
        if se is not None and se not in p.stderr:
            problems.append("stderr %r lacks %r" % (p.stderr[:150], se))
        sa = spec.get("stderr_absent")
        if sa is not None and sa in p.stderr:
            problems.append("stderr %r contains forbidden %r" % (p.stderr[:150], sa))
        sl = spec.get("stdout_lines")
        if sl is not None and p.stdout.splitlines() != sl:
            problems.append("stdout lines %r != %r" % (p.stdout.splitlines(), sl))
        if llvm:
            if spec.get("alloc_balance"):
                m = re.search(r"vow-alloc-balance: (\d+) (\d+)", p.stderr)
                if not m:
                    problems.append("no vow-alloc-balance line in stderr %r" % p.stderr[-150:])
                else:
                    a, fr = int(m.group(1)), int(m.group(2))
                    if a != fr or a <= 0:
                        problems.append("alloc balance %d allocs / %d frees" % (a, fr))
            ll_text = open(ll).read()
            for s in spec.get("ll_contains") or []:
                if s not in ll_text:
                    problems.append("ll lacks %r" % s)
            bodies = body_functions(ll_text)
            for field, want in (("llvm_fn_contains", True), ("llvm_fn_absent", False)):
                for fn_name, pats in (spec.get(field) or {}).items():
                    btxt = bodies.get(fn_name)
                    if btxt is None:
                        problems.append("%s: no @%s__vow_body( definition" % (field, fn_name))
                        continue
                    for s in pats:
                        if (s in btxt) != want:
                            problems.append("body of %s %s %r" % (fn_name, "lacks" if want else "contains", s))
        else:
            gc = spec.get("gen_contains")
            if gc:
                gen_text = open(gen).read()
                for s in gc:
                    if s not in gen_text:
                        problems.append("generated rs lacks %r" % s)
        return not problems, "; ".join(problems)
    return safe(name, fn)


def runtime_jobs(backend):
    llvm = backend == "llvm"
    tag = " [llvm]" if llvm else ""
    jobs = []
    for j in sorted(glob.glob(os.path.join(ROOT, "tests/runtime/*.json"))):
        t = os.path.splitext(os.path.basename(j))[0]
        try:
            spec = json.load(open(j))
            budget = spec.get("contract_budget")
            extra = ["--contract-budget", str(budget)] if budget is not None else []
            rows = []
            matrix = spec.get("flags_matrix")
            if matrix:
                for n, fl in enumerate(matrix):
                    rows.append((list(fl), "[%s]" % (" ".join(fl) or "default"), "_m%d" % n))
            else:
                rows.append((list(spec.get("flags", [])), "", ""))
        except Exception as e:
            err = repr(e)
            jobs.append(safe("runtime/" + t + tag, lambda err=err: (False, err)))
            continue
        for flags, label, suffix in rows:
            name = "runtime/" + t + (" " + label if label else "") + tag
            jobs.append(runtime_job(j, t, spec, flags + extra, name, suffix, llvm))
    return jobs


USAGE = "usage: run_all.py [--only must_reject|examples|runtime] [--backend rust|llvm|both]"


def main():
    global WORK
    only = None
    if "--only" in sys.argv:
        i = sys.argv.index("--only")
        only = sys.argv[i + 1] if i + 1 < len(sys.argv) else None
        if only not in ("must_reject", "examples", "runtime"):
            print(USAGE)
            return 2
    backend = "rust"
    if "--backend" in sys.argv:
        i = sys.argv.index("--backend")
        backend = sys.argv[i + 1] if i + 1 < len(sys.argv) else None
        if backend not in ("rust", "llvm", "both"):
            print(USAGE)
            return 2
    backends = ["rust", "llvm"] if backend == "both" else [backend]
    WORK = tempfile.mkdtemp(prefix="vowtests_")
    passed = total = 0
    try:
        jobs = []
        if only in (None, "must_reject"):
            jobs += must_reject_jobs()
        for b in backends:
            if only in (None, "examples"):
                jobs += examples_jobs(b)
            if only in (None, "runtime"):
                jobs += runtime_jobs(b)
        with concurrent.futures.ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as pool:
            futures = [pool.submit(job) for job in jobs]
            try:
                for fut in futures:  # original order, streamed
                    name, ok, detail = fut.result()
                    total += 1
                    passed += 1 if ok else 0
                    line = "%s %s" % ("PASS" if ok else "FAIL", name)
                    if not ok and detail:
                        line += "  -- " + detail.strip().replace("\n", " ")[:400]
                    print(line, flush=True)
            except KeyboardInterrupt:
                pool.shutdown(wait=False, cancel_futures=True)
                raise
    finally:
        shutil.rmtree(WORK, ignore_errors=True)
    print("TOTAL %d/%d" % (passed, total))
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
