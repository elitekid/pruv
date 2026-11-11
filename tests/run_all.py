"""Run all regression tests.
python tests/run_all.py [--only must_reject|examples|runtime] [--backend rust|llvm|both]
                        [--compiler py|rs] [--compiler-path PATH] [--ir-tool PATH]
                        [--list-rows [FILE]] [--compare-rows FILE]

--list-rows [FILE]: build the job list, run nothing, and write one JSON row per line (sort_keys, sorted) to FILE
(stdout if omitted); exit code 0. A row is {"sample", "backend", "flags", "mode", "group", "compiler"[, "name"][, "dup"]};
the row key is json.dumps(row, sort_keys=True). "group" is must_reject|examples|runtime (the --only value).
"mode" is default/no-verify/trust-callers/bad for examples rows, "spec_error" for a runtime row whose json
spec could not be read (flags null), and null otherwise (runtime rows are told apart by "flags" alone).
must_reject rows have "backend" null (the work does not depend on the backend). "name" is added only to rows
whose key would otherwise collide (and "dup" if even that collides).
--compare-rows FILE: run everything as usual, then compare FILE (a --list-rows output) with this run, using only
the saved rows whose (group, backend) pair occurs among this run's rows. Prints MISSING/EXTRA/FAIL row lines and
`rows: N saved (K outside this run's scope), M run, missing X, extra Y, failed Z`; exit code 1 if any
row is missing, extra or failed. If the saved compiler differs from this run's, the "compiler" field is ignored.
--list-rows and --compare-rows together: prints USAGE, exit code 2.

--compiler/--compiler-path pick the compiler under test (tests/compiler_driver.py; default rs).
--ir-tool PATH: make .ll objects with `PATH obj IN.ll -o OUT.o -mcpu=native` and the runtime object with
`PATH runtime -o OUT.o --variant rust [--count-allocs]` instead of clang (default: clang as before).

Every test case is an independent job (name, ok, detail) run in a thread pool
(os.cpu_count() workers); results are printed in the fixed original order as soon
as each one and all earlier ones are finished. runtime.c is compiled once per
variant and reused; every job uses its own work file names.

Optional runtime json field "contract_budget": N appends
["--contract-budget", str(N)] to the pruvc flags of every matrix row (labels unchanged).
Optional runtime json field "ll_contains": [strings] (llvm backend only) must each occur in
the WHOLE generated .ll text (not just __pruv_body functions).
tests/llvm_pending.txt (one repo-relative sample path per line, # comments): the llvm rows of the listed examples and
runtime samples expect pruvc exit 1 with a codegen/unsupported_type diagnostic (nothing is linked or run)."""
import concurrent.futures, glob, json, os, platform, re, shutil, subprocess, sys, tempfile, threading

CPU_FLAG = "-mcpu=native" if platform.machine().lower() in ("arm64", "aarch64") else "-march=native"
BODY_DEF = re.compile(r"^define internal [^\n]*@([A-Za-z0-9_.$]+?)__pruv_body\(", re.M)


def body_functions(text):
    """{mangled name: text of the `@name__pruv_body(` definition} from an .ll text."""
    out = {}
    for m in BODY_DEF.finditer(text):
        end = text.find("\n}", m.start())
        out[m.group(1)] = text[m.start(): end + 2 if end >= 0 else len(text)]
    return out

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.append(HERE)
import compiler_driver as CD  # noqa: E402

RUSTC = shutil.which("rustc") or os.path.expanduser("~/.cargo/bin/rustc")
CLANG = shutil.which("clang") or "/usr/bin/clang"
RUNTIME_C = os.path.join(ROOT, "pruvc/runtime.c")

DRIVER = None    # compiler_driver.Driver, set in main() (--compiler/--compiler-path)
IR_TOOL = None   # --ir-tool PATH: pruvc-ir-tool for .ll -> object and runtime object (None: clang)
WORK = None  # temp dir, set in main()
_rt_cache = {}  # count_allocs -> (object path or None, error or None)
_rt_lock = threading.Lock()


def _driver():
    global DRIVER
    if DRIVER is None:
        DRIVER = CD.default_driver()
    return DRIVER


def pruvc(src, out, flags=(), backend="rust"):
    """Always passes --backend explicitly (pruvc.py default is rust, so this equals the old omitted form)."""
    d = _driver()
    return d.run(d.argv(src, out, flags, backend), timeout=300).raise_if_timeout()


def pruvc_llvm(src, ll, rs, flags=()):
    """LLVM backend: writes IR to ll and Rust bindings to rs."""
    return pruvc(src, ll, ["--rust-bindings", rs] + list(flags), "llvm")


def runtime_object(count_allocs):
    """runtime.c object for the variant, compiled once (thread-safe). Returns (path, error).
    With --ir-tool: `IR_TOOL runtime -o OUT.o --variant rust [--count-allocs]`; else clang."""
    with _rt_lock:
        if count_allocs not in _rt_cache:
            rt_o = os.path.join(WORK, "runtime%s.o" % ("_count" if count_allocs else ""))
            if IR_TOOL:
                cmd = [IR_TOOL, "runtime", "-o", rt_o, "--variant", "rust"] + (["--count-allocs"] if count_allocs else [])
                label = "pruvc-ir-tool (runtime)"
            else:
                extra = ["-DPRUV_COUNT_ALLOCS"] if count_allocs else []
                cmd = [CLANG, "-O2", CPU_FLAG, "-std=c11", "-DPRUV_RUST_ALLOCATOR"] + extra + ["-c", RUNTIME_C, "-o", rt_o]
                label = "clang (runtime.c)"
            try:
                c = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
                if c.returncode != 0:
                    _rt_cache[count_allocs] = (None, label + ": " + (c.stderr or c.stdout)[-400:])
                else:
                    _rt_cache[count_allocs] = (rt_o, None)
            except subprocess.TimeoutExpired:
                _rt_cache[count_allocs] = (None, label + ": timeout")
            except OSError as e:
                _rt_cache[count_allocs] = (None, label + ": cannot execute: %s" % e)
        return _rt_cache[count_allocs]


def llvm_objects(ll, stem, work, count_allocs=False):
    """gen.ll to an object in work (clang, or `IR_TOOL obj IN.ll -o OUT.o -mcpu=native` with --ir-tool);
    runtime object is shared. Returns (rustc link args, error or None)."""
    gen_o = os.path.join(work, stem + "_gen.o")
    if IR_TOOL:
        cmd, label = [IR_TOOL, "obj", ll, "-o", gen_o, "-mcpu=native"], "pruvc-ir-tool (gen.ll)"
    else:
        cmd, label = [CLANG, "-O2", CPU_FLAG, "-Wno-override-module", "-c", ll, "-o", gen_o], "clang (gen.ll)"
    try:
        c = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except OSError as e:
        return [], label + ": cannot execute: %s" % e
    if c.returncode != 0:
        return [], label + ": " + (c.stderr or c.stdout)[-400:]
    rt_o, err = runtime_object(count_allocs)
    if err:
        return [], err
    return ["-C", "link-arg=" + gen_o, "-C", "link-arg=" + rt_o], None


def rel_sample(p):
    return os.path.relpath(p, ROOT).replace(os.sep, "/")


_pending = None  # set of repo-relative sample paths from tests/llvm_pending.txt (read once)


def llvm_pending():
    """Sample paths whose llvm rows expect a codegen/unsupported_type rejection (empty set if the file is missing)."""
    global _pending
    if _pending is None:
        found = set()
        try:
            with open(os.path.join(HERE, "llvm_pending.txt"), encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        found.add(line)
        except OSError:
            pass
        missing = sorted(x for x in found if not os.path.exists(os.path.join(ROOT, x)))
        if missing:  # a stale or misspelled entry must not be ignored silently
            raise RuntimeError("tests/llvm_pending.txt lists missing files: %s" % missing)
        _pending = found  # assigned only when complete (jobs run in threads)
    return _pending


def pending_result(c):
    """(ok, detail) for a pruvc run of a pending sample: exit 1 and a stage=codegen code=unsupported_type diagnostic."""
    diags = []
    layer_ok = False   # the message must name the llvm codegen layer (driver guard, not some other rejection)
    for line in c.stdout.splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if isinstance(d, dict):
            diags.append((d.get("stage"), d.get("code")))
            if d.get("code") == "unsupported_type" and "the llvm codegen layer" in (d.get("message") or ""):
                layer_ok = True
    ok = c.returncode == 1 and ("codegen", "unsupported_type") in diags and layer_ok
    return ok, "pending: exit %d (expected 1), diagnostics %s (expected codegen/unsupported_type) %s" % (
        c.returncode, diags, c.stderr)


def safe(name, fn, row=None):
    """Wrap a job body so that it always returns (name, ok, detail).
    row: {"sample", "backend", "flags", "mode"} describing this test row (stored as job.row)."""
    def job():
        try:
            ok, detail = fn()
            return (name, ok, detail)
        except subprocess.TimeoutExpired:
            return (name, False, "timeout")
        except Exception as e:
            return (name, False, repr(e))
    job.row = dict(row) if row else None
    job.name = name
    return job


def must_reject_jobs():
    jobs = []
    for f in sorted(glob.glob(os.path.join(ROOT, "tests/must_reject/*.pruv"))):
        name = "must_reject/" + os.path.basename(f)

        jf0 = os.path.splitext(f)[0] + ".json"
        flags = []
        if os.path.exists(jf0):
            try:
                fl = json.load(open(jf0)).get("flags")
            except (OSError, ValueError, AttributeError):
                fl = None
            if isinstance(fl, list) and all(isinstance(x, str) for x in fl):
                flags = list(fl)

        def fn(f=f, flags=flags):
            c = pruvc(f, os.path.join(WORK, "mr_%s.rs" % os.path.splitext(os.path.basename(f))[0]), flags)
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
        jobs.append(safe(name, fn, {"sample": rel_sample(f), "backend": None, "flags": list(flags), "mode": None,
                                     "group": "must_reject"}))
    return jobs


EXAMPLE_MODES = [("default", []), ("no-verify", ["--no-verify"]), ("trust-callers", ["--trust-callers"])]
ARITH_OR_INDEX = re.compile(r"\b(add|sub|mul|getelementptr)\b")


def example_job(f, mode, flags, llvm, name):
    base = os.path.basename(f)
    stem = os.path.splitext(base)[0]
    work = WORK

    def fn():
        if base == "bad_index.pruv":
            if llvm:
                c = pruvc_llvm(f, os.path.join(work, stem + "_bad.ll"), os.path.join(work, stem + "_bad_llvm.rs"))
            else:
                c = pruvc(f, os.path.join(work, stem + ".rs"))
            return c.returncode == 1, "exit %d (expected rejection) %s" % (c.returncode, c.stdout + c.stderr)
        if llvm:
            key = "%s_%s_llvm" % (stem, mode)
            ll = os.path.join(work, key + ".ll")
            rs = os.path.join(work, key + ".rs")
            c = pruvc_llvm(f, ll, rs, flags)
            if rel_sample(f) in llvm_pending():
                return pending_result(c)
            if c.returncode != 0:
                return False, "pruvc exit %d %s" % (c.returncode, c.stdout + c.stderr)
            text = open(ll).read()
            bodies = body_functions(text)
            if not bodies:
                return False, "no @..__pruv_body( definitions found in .ll"
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
        c = pruvc(f, out, flags)
        if c.returncode != 0:
            return False, "pruvc exit %d %s" % (c.returncode, c.stdout + c.stderr)
        if mode == "no-verify":
            text = open(out).read()
            bad = [s for s in ("unsafe", "get_unchecked") if s in text]
            if bad:
                return False, "--no-verify output contains %s" % bad
        r = subprocess.run([RUSTC, "--crate-type=lib", "-O", "--edition", "2021", out,
                            "--crate-name", stem, "-o", os.path.join(work, "lib%s_%s.rlib" % (stem, mode))],
                           capture_output=True, text=True, timeout=300)
        return r.returncode == 0, "rustc: " + r.stderr[-400:]
    return safe(name, fn, {"sample": rel_sample(f), "backend": "llvm" if llvm else "rust",
                           "flags": list(flags), "mode": mode, "group": "examples"})


def examples_jobs(backend):
    llvm = backend == "llvm"
    tag = " [llvm]" if llvm else ""
    jobs = []
    for f in sorted(glob.glob(os.path.join(ROOT, "examples/*.pruv"))):
        base = os.path.basename(f)
        if base == "bad_index.pruv":
            jobs.append(example_job(f, "bad", [], llvm, "examples/" + base + tag))
            continue
        for mode, flags in EXAMPLE_MODES:
            jobs.append(example_job(f, mode, flags, llvm, "examples/%s [%s]%s" % (base, mode, tag)))
    return jobs


def runtime_job(j, t, spec, flags, name, suffix, llvm):
    work = WORK

    def fn():
        d = os.path.dirname(j)
        pruv, drv = os.path.join(d, t + ".pruv"), os.path.join(d, t + ".rs")
        link = []
        if llvm:
            key = t + suffix + "_llvm"
            ll = os.path.join(work, key + ".ll")
            gen = os.path.join(work, key + "_gen.rs")
            c = pruvc_llvm(pruv, ll, gen, flags)
            if rel_sample(pruv) in llvm_pending():
                return pending_result(c)
        else:
            key = t + suffix
            gen = os.path.join(work, key + "_gen.rs")
            c = pruvc(pruv, gen, flags)
        if c.returncode != 0:
            return False, "pruvc exit %d %s" % (c.returncode, c.stdout + c.stderr)
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
                m = re.search(r"pruv-alloc-balance: (\d+) (\d+)", p.stderr)
                if not m:
                    problems.append("no pruv-alloc-balance line in stderr %r" % p.stderr[-150:])
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
                        problems.append("%s: no @%s__pruv_body( definition" % (field, fn_name))
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
    return safe(name, fn, {"sample": rel_sample(os.path.join(os.path.dirname(j), t + ".pruv")),
                           "backend": "llvm" if llvm else "rust", "flags": list(flags), "mode": None, "group": "runtime"})


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
            jobs.append(safe("runtime/" + t + tag, lambda err=err: (False, err),
                             {"sample": rel_sample(os.path.join(os.path.dirname(j), t + ".pruv")),
                              "backend": backend, "flags": None, "mode": "spec_error",
                              "group": "runtime"}))
            continue
        for flags, label, suffix in rows:
            name = "runtime/" + t + (" " + label if label else "") + tag
            jobs.append(runtime_job(j, t, spec, flags + extra, name, suffix, llvm))
    return jobs


USAGE = ("usage: run_all.py [--only must_reject|examples|runtime] [--backend rust|llvm|both] "
         "[--compiler py|rs] [--compiler-path PATH] [--ir-tool PATH] [--list-rows [FILE]] [--compare-rows FILE]")


def row_key(row, with_compiler=True):
    r = dict(row)
    if not with_compiler:
        r.pop("compiler", None)
    return json.dumps(r, sort_keys=True)


def build_rows(jobs):
    """One row dict per job (compiler added; name added only where keys would collide). Returns list parallel to jobs."""
    rows = []
    for job in jobs:
        r = dict(job.row) if job.row else {"sample": None, "backend": None, "flags": None, "mode": None, "group": None}
        r["compiler"] = DRIVER.name
        rows.append(r)
    count = {}
    for r in rows:
        count[row_key(r)] = count.get(row_key(r), 0) + 1
    for job, r in zip(jobs, rows):
        if count[row_key(r)] > 1 or r["sample"] is None:
            r["name"] = job.name
    # name may still collide if two jobs share a name; make it unique with an index
    seen = {}
    for r in rows:
        k = row_key(r)
        seen[k] = seen.get(k, 0) + 1
        if seen[k] > 1:
            r["dup"] = seen[k]
    return rows


def main():
    global WORK, DRIVER, IR_TOOL
    argv = sys.argv
    DRIVER = CD.from_argv(argv)  # removes --compiler/--compiler-path from sys.argv in place
    if "--list-rows" in argv and "--compare-rows" in argv:
        print(USAGE)
        return 2
    list_rows = False
    list_file = None
    if "--list-rows" in argv:
        i = argv.index("--list-rows")
        list_rows = True
        if i + 1 < len(argv) and not argv[i + 1].startswith("--"):
            list_file = argv[i + 1]
            del argv[i:i + 2]
        else:
            del argv[i:i + 1]
    compare_file = None
    saved_rows = None
    if "--compare-rows" in argv:
        i = argv.index("--compare-rows")
        compare_file = argv[i + 1] if i + 1 < len(argv) else None
        if not compare_file or compare_file.startswith("--"):
            print(USAGE)
            return 2
        del argv[i:i + 2]
        try:
            with open(compare_file, encoding="utf-8") as fh:
                saved_rows = [json.loads(l) for l in fh.read().splitlines() if l.strip()]
        except (OSError, ValueError) as e:
            print("--compare-rows: cannot read %s: %r" % (compare_file, e))
            return 2
        old = [r for r in saved_rows if not isinstance(r, dict) or "group" not in r]
        if old:
            print("--compare-rows: %d row(s) in %s have no \"group\" key (old format); regenerate it with --list-rows" % (
                len(old), compare_file))
            return 2
    if "--ir-tool" in argv:
        i = argv.index("--ir-tool")
        tool = argv[i + 1] if i + 1 < len(argv) else None
        if not tool:
            print(USAGE)
            return 2
        tool = os.path.abspath(tool)
        if not (os.path.isfile(tool) and os.access(tool, os.X_OK)):
            print("--ir-tool: not an executable file: %s" % tool)
            return 2
        IR_TOOL = tool
        del argv[i:i + 2]
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
    WORK = tempfile.mkdtemp(prefix="pruvtests_")
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
        rows = build_rows(jobs)
        if list_rows:
            lines = sorted(row_key(r) for r in rows)
            text = "".join(l + "\n" for l in lines)
            if list_file:
                with open(list_file, "w", encoding="utf-8") as fh:
                    fh.write(text)
            else:
                sys.stdout.write(text)
                sys.stdout.flush()
            return 0
        failed_rows = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as pool:
            futures = [pool.submit(job) for job in jobs]
            try:
                for idx, fut in enumerate(futures):  # original order, streamed
                    name, ok, detail = fut.result()
                    total += 1
                    passed += 1 if ok else 0
                    if not ok:
                        failed_rows.append(rows[idx])
                    line = "%s %s" % ("PASS" if ok else "FAIL", name)
                    if not ok and detail:
                        line += "  -- " + detail.strip().replace("\n", " ")[:400]
                    print(line, flush=True)
            except KeyboardInterrupt:
                pool.shutdown(wait=False, cancel_futures=True)
                raise
    finally:
        shutil.rmtree(WORK, ignore_errors=True)
    print("compiler: %s" % DRIVER.name)
    print("object path: %s" % ("pruvc-ir-tool (%s)" % IR_TOOL if IR_TOOL else "clang"))
    print("TOTAL %d/%d" % (passed, total))
    rc = 0 if passed == total else 1
    if saved_rows is not None:
        # scope comes from the arguments (--only/--backend), not from the rows that actually ran
        scope = set()
        for g in ("must_reject", "examples", "runtime"):
            if only in (None, g):
                for b in ([None] if g == "must_reject" else backends):
                    scope.add((g, b))
        in_scope = [r for r in saved_rows if (r.get("group"), r.get("backend")) in scope]
        outside = len(saved_rows) - len(in_scope)
        saved_compilers = set(r.get("compiler") for r in in_scope)
        with_c = saved_compilers == {DRIVER.name}
        saved_keys = [row_key(r, with_c) for r in in_scope]
        run_keys = [row_key(r, with_c) for r in rows]
        saved_set, run_set = set(saved_keys), set(run_keys)
        missing = sorted(saved_set - run_set)
        extra = sorted(run_set - saved_set)
        failed = sorted(set(row_key(r, with_c) for r in failed_rows))
        if not with_c and in_scope:
            print("note: saved compiler %s != this run's %s; compiler field ignored" % (
                sorted(str(c) for c in saved_compilers), DRIVER.name))
        for k in missing:
            print("MISSING row %s" % k)
        for k in extra:
            print("EXTRA row %s" % k)
        for k in failed:
            print("FAIL row %s" % k)
        print("rows: %d saved (%d outside this run's scope), %d run, missing %d, extra %d, failed %d" % (
            len(saved_rows), outside, len(run_keys), len(missing), len(extra), len(failed)))
        if missing or extra or failed:
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
