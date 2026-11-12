"""Run all regression tests.
python tests/run_all.py [--only must_reject|examples|runtime|g3_proof|g6_frontend|g6_proof|g9_frontend|g9_proof|g4_frontend|g4_proof|g5_frontend|g5_reject|g5_proof]
                        [--backend rust|llvm|both]

groups g5_frontend / g5_reject (G5 A0, inventory tests/g5/fixtures.json; rows have backend null): g5_frontend runs the roots of
tests/g5/frontend (flat files and <name>/root.pruv projects, copied to a new directory first) in modes no-verify and default.
Since A2 (G5_GUARD False) every fixture ("guard" and the G5-free compatibility fixture "ok") passes when pruvc exits 0 on the
Rust backend (in default mode the program must also verify); with G5_GUARD True a "guard" fixture expected exit 1 with the
staging guard codegen/unsupported_type instead (the guard now applies only to the llvm backend / --also-llvm until A3,
and the llvm rows of the G5 runtime samples and examples are listed in tests/llvm_pending.txt). The G5 rejection roots tests/must_reject/g5_*.pruv
(sibling .json = stage/code) and tests/must_reject/g5_*/root.pruv are ordinary must_reject rows (default mode); group
g5_reject repeats every G5 rejection with --no-verify and --trust-callers (exclusivity is static in all modes).

group g5_proof (G5 A1; backend null rows): the "proof" roots of tests/g5/fixtures.json (tests/g5/proof/*.pruv and
<name>/root.pruv projects, copied first) in default mode, and with --infer where the entry says "infer": true; a row passes
when verification succeeds completely and pruvc then generates the Rust source (exit 0, no verify diagnostic; before A2 it
stopped at the G5 staging guard). The verification rejections tests/must_reject/g5p_*.pruv ("proof_reject", sibling .json = stage/code)
are ordinary must_reject rows (default mode); g5_proof adds a --infer row for each one marked "infer": true.

group g4_proof (G4 A1): tests/g4/proof/*/root.pruv from tests/g4/fixtures.json (default mode, backend null rows, each project
copied to a new directory first). Since A2 (G4_GUARD False) a row passes when pruvc exits 0 (verification and Rust generation);
with G4_GUARD True it expected the staging guard codegen/unsupported_type instead.

group g4_frontend (G4 A0): tests/g4/frontend/*/root.pruv from tests/g4/fixtures.json (mode no-verify, backend null rows,
each project copied to a new directory first). Since A2 (G4_GUARD False) a row passes when pruvc exits 0. The
tests/must_reject/g4_*/root.pruv projects are rows of the must_reject group (sample = the project's root.pruv; expected
stage/code in the sibling root.json).

G4 A2 projects: tests/runtime/g4_*/ (listed in tests/g4/fixtures.json group "runtime") are runtime rows of project form:
root.pruv + companion modules, main.rs (the host driver, appended after `mod sol;` like tests/runtime/X.rs) and spec.json
(the fields of tests/runtime/X.json plus the optional "gen_absent": [strings] that must NOT occur in the generated Rust,
rust backend only). The project is copied to a new work directory before it is compiled; the row sample is its root.pruv.
examples/g4_*/root.pruv (+ companions) are examples rows (default / no-verify / trust-callers). G4 A3: their llvm rows run
for real (the guard is gone); every G4 llvm row also checks the exported symbols of the .ll: the defined external symbols
must be exactly the host-entry `pruv_abi_*` symbols (runtime projects: spec.json "llvm_exports"; project examples: the
root `pub fn` names).
                        [--compiler py|rs] [--compiler-path PATH] [--ir-tool PATH]
                        [--list-rows [FILE]] [--compare-rows FILE]

groups g9_frontend / g9_proof (G9 A0): tests/g9/frontend/*.pruv (mode no-verify, --no-verify) and tests/g9/proof/*.pruv
(mode default); rows have backend null. While G9_GUARD is True (until batch A2) a g9_frontend row passes when pruvc
exits 1 with the downstream guard unsupported_type / "rust codegen layer"; g9_proof rows expect verification to pass and then the same guard.

group g3_proof (G3 A2): tests/g3/proof/*.pruv must verify; they run through tests/g3/verify_only.py (Python verifier,
no code generation, whatever --compiler says) because the code generators still reject generics. Rows have
group "g3_proof", mode "verify_only", backend null.

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
G4 A3 spec.json fields (llvm backend only unless stated): "llvm_exports" [symbols] (required for every G4 project: the exact
defined external symbols of the .ll), "bindings_contains" / "bindings_absent" [strings] (the generated Rust bindings), "llvm"
{fields} (overrides top-level fields of the llvm rows), and an optional main_llvm.rs next to main.rs (the llvm host driver).
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


# G4 A3 (docs/G4_SPEC.md 7, 13): defined symbols with external linkage of an .ll text (function definitions and global
# definitions without internal/private linkage; declarations and llvm.* metadata globals are not definitions).
EXT_FN_DEF = re.compile(r"^define (?!internal\b|private\b)[^\n@]*@([A-Za-z0-9_.$]+)\(", re.M)
EXT_GLOBAL_DEF = re.compile(r"^@([A-Za-z0-9_.$]+) = (?!internal\b|private\b|external\b|appending\b)", re.M)


def exported_symbols(text):
    """sorted names of the symbols an .ll text defines with external linkage"""
    names = set(EXT_FN_DEF.findall(text)) | set(EXT_GLOBAL_DEF.findall(text))
    return sorted(n for n in names if not n.startswith("llvm."))


def exports_problems(text, expected):
    """problems of the exported-symbol check: the defined external symbols must be exactly `expected` (a list of names,
    all `pruv_abi_*`: the host entries and their typed variants). Checked for every G4 llvm row (explicit expectations,
    not only compiler parity)."""
    got = exported_symbols(text)
    out = []
    stray = [n for n in got if not n.startswith("pruv_abi_")]
    if stray:
        out.append("non-entry external symbols %s" % stray)
    if got != sorted(expected):
        out.append("exported symbols %s != expected %s" % (got, sorted(expected)))
    return out


ROOT_PUB_FN = re.compile(r"^pub\s+fn\s+([A-Za-z_][A-Za-z0-9_]*)\s*(<)?", re.M)


def root_entry_exports(root_text, got):
    """expected exports of a project example (no spec.json): one `pruv_abi_<name>` per root `pub fn <name>(` without type
    parameters; a `pruv_abi_<name>__typed` is also allowed when the entry has a [bool]/str parameter (taken from `got`)."""
    names = ["pruv_abi_" + m.group(1) for m in ROOT_PUB_FN.finditer(root_text) if not m.group(2)]
    return names + [g for g in got if g.endswith("__typed") and g[:-len("__typed")] in names]


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
                cex = want.get("cex_contains")  # optional: every string must appear in the diagnostic output text
                if ok and isinstance(cex, list):
                    text = c.stdout + c.stderr
                    missing = [s for s in cex if isinstance(s, str) and s not in text]
                    if missing:
                        ok = False
                        detail = "cex_contains missing %s in %s" % (missing, text[-600:])
            return ok, detail
        jobs.append(safe(name, fn, {"sample": rel_sample(f), "backend": None, "flags": list(flags), "mode": None,
                                     "group": "must_reject"}))
    return jobs + g4_reject_jobs()


def _g4():
    """tests/g4/projects.py (project fixtures); imported lazily"""
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    import importlib
    return importlib.import_module("g4.projects")


def g4_reject_jobs():
    """G4 A0: tests/must_reject/g4_*/root.pruv (project directories; companion modules are not roots). The project is
    copied to a new work directory first, so the run also shows that nothing depends on the original location; the
    expected stage/code come from the project's root.json."""
    jobs = []
    P = _g4()
    # G5 A0: the G5 project rejections (tests/must_reject/g5_*/root.pruv) follow the same convention
    for f in sorted(glob.glob(os.path.join(ROOT, "tests/must_reject/g[45]_*/root.pruv"))):
        rel = rel_sample(f)
        name = "must_reject/" + rel[len("tests/must_reject/"):]
        proj = os.path.basename(os.path.dirname(f))
        jf = os.path.join(os.path.dirname(f), "root.json")
        flags = []
        want = {}
        if os.path.exists(jf):
            try:
                want = json.load(open(jf))
            except (OSError, ValueError):
                want = {}
            fl = want.get("flags") if isinstance(want, dict) else None
            if isinstance(fl, list) and all(isinstance(x, str) for x in fl):
                flags = list(fl)

        def fn(f=f, proj=proj, want=want, flags=flags):
            root = P.copy_project(f, os.path.join(WORK, "g4mr_" + proj))
            c = pruvc(root, os.path.join(WORK, "g4mr_%s.rs" % proj), flags)
            if c.returncode != 1:
                return False, "exit %d (expected 1) %s" % (c.returncode, c.stdout + c.stderr)
            diags = []
            for line in c.stdout.splitlines():
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if isinstance(d, dict):
                    diags.append(d)
            ok = any(d.get("stage") == want.get("stage") and d.get("code") == want.get("code")
                     and ("file" not in want or d.get("file") == want["file"]) for d in diags)
            return ok, "expected stage=%s code=%s file=%s; got %s" % (
                want.get("stage"), want.get("code"), want.get("file"),
                [(d.get("stage"), d.get("code"), d.get("file")) for d in diags])
        jobs.append(safe(name, fn, {"sample": rel, "backend": None, "flags": list(flags), "mode": None,
                                     "group": "must_reject"}))
    return jobs


# G4 A0 (docs/G4_SPEC.md 10): explicit-mode programs were frontend-only until A2. While G4_GUARD is True a g4_frontend row
# passes when pruvc exits 1 with the staging guard codegen/unsupported_type naming G4 modules (which also shows that
# loading, resolution, visibility and entry checks all accepted the project). A2 generates Rust source for them, so the
# rows (Rust backend) expect exit 0; the guard text below is what the LLVM backend still reports until A3.
G4_GUARD = False
G4_GUARD_CODE = "unsupported_type"
G4_GUARD_LAYER = "G4 modules and visibility"


def g4_frontend_jobs(group="g4_frontend", modes=(("no-verify", ["--no-verify"]),)):
    """tests/g4/frontend/*/root.pruv (listed in tests/g4/fixtures.json); rows have backend null. Each project is copied
    to a new directory first (relocation: the relative tree and the root basename must be all that matters)."""
    jobs = []
    P = _g4()
    for e in P.frontend():
        f = os.path.join(ROOT, *e["root"].split("/"))
        for mode, flags in modes:
            name = "%s/%s [%s]" % (group, e["name"], mode)

            def fn(f=f, flags=flags, mode=mode, nm=e["name"]):
                root = P.copy_project(f, os.path.join(WORK, "g4fe_%s_%s" % (nm, mode)))
                c = pruvc(root, os.path.join(WORK, "g4fe_%s_%s.rs" % (nm, mode)), flags)
                text = c.stdout + c.stderr
                if G4_GUARD:
                    ok = c.returncode == 1 and G4_GUARD_CODE in text and G4_GUARD_LAYER in text
                    return ok, "pruvc exit %d (expected 1 with the G4 guard %s / %r) %s" % (
                        c.returncode, G4_GUARD_CODE, G4_GUARD_LAYER, text[-400:])
                return c.returncode == 0, "pruvc exit %d (expected 0) %s" % (c.returncode, text[-400:])
            jobs.append(safe(name, fn, {"sample": e["root"], "backend": None, "flags": flags, "mode": mode,
                                         "group": group}))
    return jobs


def g4_proof_jobs():
    """G4 A1: tests/g4/proof/*/root.pruv (listed in tests/g4/fixtures.json) must verify completely in the default mode
    (rows have backend null). While G4_GUARD is True the run then stops at the staging guard (exit 1); a verification
    error is a different diagnostic and fails the row. The project is copied to a new directory first."""
    jobs = []
    P = _g4()
    for e in P.proof():
        f = os.path.join(ROOT, *e["root"].split("/"))
        name = "g4_proof/%s [default]" % e["name"]

        def fn(f=f, nm=e["name"]):
            root = P.copy_project(f, os.path.join(WORK, "g4pr_" + nm))
            c = pruvc(root, os.path.join(WORK, "g4pr_%s.rs" % nm), [])
            text = c.stdout + c.stderr
            if G4_GUARD:
                ok = c.returncode == 1 and G4_GUARD_CODE in text and G4_GUARD_LAYER in text
                return ok, "pruvc exit %d (expected 1 with the G4 guard %s / %r after verification) %s" % (
                    c.returncode, G4_GUARD_CODE, G4_GUARD_LAYER, text[-400:])
            return c.returncode == 0, "pruvc exit %d (expected 0) %s" % (c.returncode, text[-400:])
        jobs.append(safe(name, fn, {"sample": e["root"], "backend": None, "flags": [], "mode": "default",
                                     "group": "g4_proof"}))
    return jobs


def g3_proof_jobs():
    """G3 A2: tests/g3/proof/*.pruv must type-check and verify completely. The code generators still reject
    generics (unsupported_type), so these run through tests/g3/verify_only.py (Python verifier, no code
    generation) in their own process; the compiler under test (--compiler) is not involved."""
    jobs = []
    script = os.path.join(ROOT, "tests/g3/verify_only.py")
    for f in sorted(glob.glob(os.path.join(ROOT, "tests/g3/proof/*.pruv"))):
        name = "g3_proof/" + os.path.basename(f)

        def fn(f=f):
            c = subprocess.run([CD.pinned_python(), script, f], capture_output=True, text=True, timeout=300)
            return c.returncode == 0, "exit %d (expected 0) %s" % (c.returncode, (c.stdout + c.stderr)[-600:])
        jobs.append(safe(name, fn, {"sample": rel_sample(f), "backend": None, "flags": [], "mode": "verify_only",
                                     "group": "g3_proof"}))
    return jobs


def g6_frontend_jobs(group="g6_frontend", sub="frontend", modes=(("no-verify", ["--no-verify"]),)):
    """G6 (docs/G6_SPEC.md 11.1, 12): the Rust source backend lowers G6 since A2, so the compiler under test must
    succeed (exit 0, Rust backend). The samples name Rust paths that need not exist, so the output is not compiled
    here; the runtime fixtures (tests/runtime/g6_*) compile and run generated code.
    g6_frontend: tests/g6/frontend/*.pruv are well-typed and pass the ownership rules (--no-verify only).
    g6_proof: tests/g6/proof/*.pruv must also verify completely (default mode). Rows have backend null."""
    jobs = []
    for f in sorted(glob.glob(os.path.join(ROOT, "tests/g6", sub, "*.pruv"))):
        for mode, flags in modes:
            name = "%s/%s [%s]" % (group, os.path.basename(f), mode)

            def fn(f=f, flags=flags, mode=mode):
                stem = "g6_%s_%s_%s" % (sub, os.path.splitext(os.path.basename(f))[0], mode)
                out = os.path.join(WORK, stem + ".rs")
                c = pruvc(f, out, flags)
                return c.returncode == 0, "pruvc exit %d (expected 0) %s" % (c.returncode, (c.stdout + c.stderr)[-400:])
            jobs.append(safe(name, fn, {"sample": rel_sample(f), "backend": None, "flags": flags, "mode": mode,
                                         "group": group}))
    return jobs

# G9 A0 (docs/G9_SPEC.md 9, 10): until the Rust backend lowers G9 (batch A2) the driver stops every program that uses a
# G9 feature at the downstream guard. While G9_GUARD is True a g9_frontend row passes when pruvc exits 1 and reports
# the guard (code unsupported_type, message naming the rust codegen layer), which also shows that the program
# was accepted by parsing and checking. Batch A2 flips G9_GUARD to False: the rows then expect exit 0.
G9_GUARD = False   # G9 A2: the Rust backend lowers G9 programs
G9_GUARD_CODE = "unsupported_type"
G9_GUARD_LAYER = "rust codegen layer"


def g9_frontend_jobs(group="g9_frontend", sub="frontend", modes=(("no-verify", ["--no-verify"]),)):
    """G9 A0: tests/g9/frontend/*.pruv are well-typed and pass checking (--no-verify only, Rust backend, rows have
    backend null). With G9_GUARD the expected outcome is the downstream guard (see above); without it exit 0."""
    jobs = []
    for f in sorted(glob.glob(os.path.join(ROOT, "tests/g9", sub, "*.pruv"))):
        for mode, flags in modes:
            name = "%s/%s [%s]" % (group, os.path.basename(f), mode)

            def fn(f=f, flags=flags, mode=mode):
                stem = "g9_%s_%s_%s" % (sub, os.path.splitext(os.path.basename(f))[0], mode)
                out = os.path.join(WORK, stem + ".rs")
                c = pruvc(f, out, flags)
                text = c.stdout + c.stderr
                if G9_GUARD:
                    ok = c.returncode == 1 and G9_GUARD_CODE in text and G9_GUARD_LAYER in text
                    return ok, "pruvc exit %d (expected 1 with the G9 guard %s / %r) %s" % (
                        c.returncode, G9_GUARD_CODE, G9_GUARD_LAYER, text[-400:])
                return c.returncode == 0, "pruvc exit %d (expected 0) %s" % (c.returncode, text[-400:])
            jobs.append(safe(name, fn, {"sample": rel_sample(f), "backend": None, "flags": flags, "mode": mode,
                                         "group": group}))
    return jobs


def g9_proof_jobs(group="g9_proof", sub="proof", modes=(("default", []),)):
    """G9 A1: tests/g9/proof/*.pruv must verify completely (default mode, backend null rows). While G9_GUARD is True
    the run then stops at the codegen guard (exit 1, "rust codegen layer"); a verification error fails the row."""
    jobs = []
    for f in sorted(glob.glob(os.path.join(ROOT, "tests/g9", sub, "*.pruv"))):
        for mode, flags in modes:
            name = "%s/%s [%s]" % (group, os.path.basename(f), mode)

            def fn(f=f, flags=flags, mode=mode):
                stem = "g9_%s_%s_%s" % (sub, os.path.splitext(os.path.basename(f))[0], mode)
                out = os.path.join(WORK, stem + ".rs")
                c = pruvc(f, out, flags)
                text = c.stdout + c.stderr
                if G9_GUARD:   # G9 A1: verification runs first; only the downstream codegen guard may stop it
                    ok = c.returncode == 1 and G9_GUARD_CODE in text and G9_GUARD_LAYER in text
                    return ok, "pruvc exit %d (expected 1 with the G9 guard %s / %r after verification) %s" % (
                        c.returncode, G9_GUARD_CODE, G9_GUARD_LAYER, text[-400:])
                return c.returncode == 0, "pruvc exit %d (expected 0) %s" % (c.returncode, text[-400:])
            jobs.append(safe(name, fn, {"sample": rel_sample(f), "backend": None, "flags": flags, "mode": mode,
                                         "group": group}))
    return jobs


# G5 (docs/G5_SPEC.md 9, 10, 11, 12): since A2 the Rust source backend lowers inout programs, so on the Rust backend
# every g5_frontend fixture ("guard" and "ok") and every g5_proof root must make pruvc exit 0 (a proof root must also
# have no verify diagnostic). The staging guard (codegen/unsupported_type, "G5 inout parameters are not implemented by
# the llvm codegen layer yet") now applies only to the llvm backend / --also-llvm until A3; the llvm rows of the G5
# runtime samples and examples are listed in tests/llvm_pending.txt. The static rejections hold in every mode (group
# g5_reject rows).
G5_GUARD = False
G5_GUARD_CODE = "unsupported_type"
G5_GUARD_LAYER = "G5 inout parameters are not implemented"


def _g5_rows(group):
    """tests/g5/fixtures.json entries of one group -> [(entry, absolute root, project dir or None)]"""
    P = _g4()
    return [(e, os.path.join(ROOT, *e["root"].split("/")), bool(e.get("project"))) for e in P.g5_entries(group)]


def g5_frontend_jobs(group="g5_frontend", modes=(("no-verify", ["--no-verify"]), ("default", []))):
    """G5 A0: tests/g5/frontend roots (flat files, or tests/g5/frontend/<name>/root.pruv projects copied to a new directory
    first); rows have backend null and run in --no-verify and default mode."""
    jobs = []
    P = _g4()
    for e, f, proj in _g5_rows("frontend"):
        for mode, flags in modes:
            name = "%s/%s [%s]" % (group, e["name"], mode)

            def fn(e=e, f=f, proj=proj, flags=flags, mode=mode):
                stem = "g5fe_%s_%s" % (e["name"], mode)
                src = P.copy_project(f, os.path.join(WORK, stem)) if proj else f
                c = pruvc(src, os.path.join(WORK, stem + ".rs"), flags)
                text = c.stdout + c.stderr
                if G5_GUARD and e.get("expect") == "guard":
                    ok = c.returncode == 1 and G5_GUARD_CODE in text and G5_GUARD_LAYER in text
                    return ok, "pruvc exit %d (expected 1 with the G5 guard %s / %r) %s" % (
                        c.returncode, G5_GUARD_CODE, G5_GUARD_LAYER, text[-400:])
                return c.returncode == 0, "pruvc exit %d (expected 0) %s" % (c.returncode, text[-400:])
            jobs.append(safe(name, fn, {"sample": e["root"], "backend": None, "flags": list(flags), "mode": mode,
                                         "group": group}))
    return jobs


def g5_reject_jobs(group="g5_reject", modes=(("no-verify", ["--no-verify"]), ("trust-callers", ["--trust-callers"]))):
    """G5 A0: every G5 rejection root (tests/g5/fixtures.json) is static: it must be rejected with the recorded stage/code
    also with --no-verify and --trust-callers (the default-mode rows are the ordinary must_reject rows)."""
    jobs = []
    P = _g4()
    for e, f, proj in _g5_rows("reject"):
        for mode, flags in modes:
            name = "%s/%s [%s]" % (group, e["name"], mode)

            def fn(e=e, f=f, proj=proj, flags=flags, mode=mode):
                stem = "g5rj_%s_%s" % (e["name"], mode)
                src = P.copy_project(f, os.path.join(WORK, stem)) if proj else f
                c = pruvc(src, os.path.join(WORK, stem + ".rs"), flags)
                if c.returncode != 1:
                    return False, "exit %d (expected 1) %s" % (c.returncode, c.stdout + c.stderr)
                diags = []
                for line in c.stdout.splitlines():
                    try:
                        d = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(d, dict):
                        diags.append(d)
                ok = any(d.get("stage") == e["stage"] and d.get("code") == e["code"] for d in diags)
                return ok, "expected stage=%s code=%s; got %s" % (
                    e["stage"], e["code"], [(d.get("stage"), d.get("code")) for d in diags])
            jobs.append(safe(name, fn, {"sample": e["root"], "backend": None, "flags": list(flags), "mode": mode,
                                         "group": group}))
    return jobs


def g5_proof_jobs(group="g5_proof"):
    """G5 A1 (tests/g5/fixtures.json "proof" and "proof_reject"; rows have backend null).
    Positive roots (project roots are copied to a new directory first) run in default mode and, where the entry says
    "infer": true, also with --infer. Since A2 the Rust backend generates the program, so a passing row exits 0 with NO
    verify diagnostic; a verification error (or a timeout/unknown) fails it.
    Negative roots (tests/must_reject/g5p_*.pruv, "proof_reject") are ordinary must_reject rows in default mode; here
    only their --infer rows (entries marked "infer": true) are added: the recorded stage/code must hold there too."""
    jobs = []
    P = _g4()
    for e, f, proj in _g5_rows("proof"):
        modes = [("default", [])] + ([("infer", ["--infer"])] if e.get("infer") else [])
        for mode, flags in modes:
            name = "%s/%s [%s]" % (group, e["name"], mode)

            def fn(e=e, f=f, proj=proj, flags=flags, mode=mode):
                stem = "g5pf_%s_%s" % (e["name"], mode)
                src = P.copy_project(f, os.path.join(WORK, stem)) if proj else f
                c = pruvc(src, os.path.join(WORK, stem + ".rs"), flags)
                text = c.stdout + c.stderr
                diags = []
                for line in c.stdout.splitlines():
                    try:
                        d = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(d, dict):
                        diags.append(d)
                verify_errs = [(d.get("stage"), d.get("code")) for d in diags if d.get("stage") == "verify"]
                ok = c.returncode == 0 and not verify_errs
                return ok, "pruvc exit %d (expected 0 after a complete proof); verify errors %s: %s" % (
                    c.returncode, verify_errs, text[-400:])
            jobs.append(safe(name, fn, {"sample": e["root"], "backend": None, "flags": list(flags), "mode": mode,
                                         "group": group}))
    for e, f, proj in _g5_rows("proof_reject"):
        if not e.get("infer"):
            continue
        name = "%s/%s [infer]" % (group, e["name"])

        def fn(e=e, f=f):
            stem = "g5pf_%s_infer" % e["name"]
            c = pruvc(f, os.path.join(WORK, stem + ".rs"), ["--infer"])
            if c.returncode != 1:
                return False, "exit %d (expected 1) %s" % (c.returncode, c.stdout + c.stderr)
            diags = []
            for line in c.stdout.splitlines():
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if isinstance(d, dict):
                    diags.append(d)
            ok = any(d.get("stage") == e["stage"] and d.get("code") == e["code"] for d in diags)
            return ok, "expected stage=%s code=%s; got %s" % (
                e["stage"], e["code"], [(d.get("stage"), d.get("code")) for d in diags])
        jobs.append(safe(name, fn, {"sample": e["root"], "backend": None, "flags": ["--infer"], "mode": "infer",
                                     "group": group}))
    return jobs


EXAMPLE_MODES = [("default", []), ("no-verify", ["--no-verify"]), ("trust-callers", ["--trust-callers"])]
ARITH_OR_INDEX = re.compile(r"\b(add|sub|mul|getelementptr)\b")


def example_job(f, mode, flags, llvm, name):
    base = os.path.basename(f)
    stem = os.path.splitext(base)[0]
    if base == "root.pruv":      # G4 project example (examples/g4_NAME/root.pruv): work files are named by the project
        stem = os.path.basename(os.path.dirname(f))
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
            if base == "root.pruv":   # G4 A3: only the root `pub fn` entries are exported (bodies and wrappers are internal)
                ps = exports_problems(text, root_entry_exports(open(f, encoding="utf-8").read(), exported_symbols(text)))
                if ps:
                    return False, "; ".join(ps)
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
    for f in sorted(glob.glob(os.path.join(ROOT, "examples/*.pruv"))):   # top level only: project companions are not examples
        base = os.path.basename(f)
        if base == "bad_index.pruv":
            jobs.append(example_job(f, "bad", [], llvm, "examples/" + base + tag))
            continue
        for mode, flags in EXAMPLE_MODES:
            jobs.append(example_job(f, mode, flags, llvm, "examples/%s [%s]%s" % (base, mode, tag)))
    # G4 A2: project examples; the root is the only input, the companion modules are loaded by the compiler
    for f in sorted(glob.glob(os.path.join(ROOT, "examples/g4_*/root.pruv"))):
        proj = os.path.basename(os.path.dirname(f))
        for mode, flags in EXAMPLE_MODES:
            jobs.append(example_job(f, mode, flags, llvm, "examples/%s/root.pruv [%s]%s" % (proj, mode, tag)))
    return jobs


def runtime_src(j, t):
    """the compiler input of a runtime spec: tests/runtime/T.pruv, or root.pruv of a G4 project (spec.json)"""
    d = os.path.dirname(j)
    return os.path.join(d, "root.pruv") if os.path.basename(j) == "spec.json" else os.path.join(d, t + ".pruv")


def runtime_job(j, t, spec, flags, name, suffix, llvm):
    work = WORK

    def fn():
        d = os.path.dirname(j)
        proj = os.path.basename(j) == "spec.json"      # G4 A2 project: root.pruv + modules + main.rs + spec.json
        pruv, drv = (os.path.join(d, "root.pruv"), os.path.join(d, "main.rs")) if proj else \
            (os.path.join(d, t + ".pruv"), os.path.join(d, t + ".rs"))
        if llvm and proj and os.path.exists(os.path.join(d, "main_llvm.rs")):
            # G4 A3: a project may need a llvm-only host driver (raw `pruv_abi_*` calls with invalid representations)
            drv = os.path.join(d, "main_llvm.rs")
        link = []
        # G6 A2 (G6_SPEC 12.5): "rust_externs": {"NAME": "tests/runtime/FILE.rs"} -> an rlib per job, passed to
        # pruvc as --rust-extern NAME=RLIB and to the final rustc as --extern NAME=RLIB
        xflags, xlink = [], []
        for xname, xsrc in sorted((spec.get("rust_externs") or {}).items()):
            rlib = os.path.join(work, "lib%s_%s%s%s.rlib" % (xname, t, suffix, "_llvm" if llvm else ""))
            r = subprocess.run([RUSTC, "-O", "--edition", "2021", "--crate-type", "rlib", "--crate-name", xname,
                                os.path.join(ROOT, xsrc), "-o", rlib], capture_output=True, text=True, timeout=300)
            if r.returncode != 0:
                return False, "rustc (extern %s): %s" % (xname, r.stderr[-400:])
            xflags += ["--rust-extern", "%s=%s" % (xname, rlib)]
            xlink += ["--extern", "%s=%s" % (xname, rlib)]
        if llvm:
            key = t + suffix + "_llvm"
            ll = os.path.join(work, key + ".ll")
            gen = os.path.join(work, key + "_gen.rs")
            src = _g4().copy_project(pruv, os.path.join(work, "g4rt_" + key)) if proj else pruv
            c = pruvc_llvm(src, ll, gen, list(flags) + xflags)
            if rel_sample(pruv) in llvm_pending():
                return pending_result(c)
        else:
            key = t + suffix
            gen = os.path.join(work, key + "_gen.rs")
            src = _g4().copy_project(pruv, os.path.join(work, "g4rt_" + key)) if proj else pruv
            c = pruvc(src, gen, list(flags) + xflags)
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
        r = subprocess.run([RUSTC, "-O", "--edition", "2021", main, "-o", exe] + link + xlink,
                           capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            return False, "rustc: " + r.stderr[-400:]
        g6_count = bool(llvm and spec.get("g6_drop_balance"))   # G6 A3 (G6_SPEC 13.4)
        env = dict(os.environ, PRUV_G6_COUNT="1") if g6_count else None
        p = subprocess.run([exe], capture_output=True, text=True, timeout=60, env=env)
        problems = []
        if g6_count:
            m = re.search(r"pruv-g6-live: (-?\d+)", p.stderr)
            if m is None or m.group(1) != "0":
                problems.append("g6 live boxes at exit: %s (expected 0)" % (m.group(1) if m else "no report"))
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
            if proj:   # G4 A3: the exported-symbol check; spec.json "llvm_exports" lists the expected defined externals
                if "llvm_exports" not in spec:
                    problems.append("spec.json has no llvm_exports")
                else:
                    problems += exports_problems(ll_text, spec["llvm_exports"])
            for s in spec.get("ll_contains") or []:
                if s not in ll_text:
                    problems.append("ll lacks %r" % s)
            if spec.get("bindings_contains") or spec.get("bindings_absent"):   # G4 A3: the generated Rust bindings (gen)
                bind_text = open(gen).read()
                for s in spec.get("bindings_contains") or []:
                    if s not in bind_text:
                        problems.append("bindings lack %r" % s)
                for s in spec.get("bindings_absent") or []:
                    if s in bind_text:
                        problems.append("bindings contain forbidden %r" % s)
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
            gc, ga = spec.get("gen_contains"), spec.get("gen_absent")   # gen_absent: G4 A2 (strings that must not occur)
            if gc or ga:
                gen_text = open(gen).read()
                for s in gc or []:
                    if s not in gen_text:
                        problems.append("generated rs lacks %r" % s)
                for s in ga or []:
                    if s in gen_text:
                        problems.append("generated rs contains forbidden %r" % s)
        return not problems, "; ".join(problems)
    return safe(name, fn, {"sample": rel_sample(runtime_src(j, t)),
                           "backend": "llvm" if llvm else "rust", "flags": list(flags), "mode": None, "group": "runtime"})


def runtime_jobs(backend):
    llvm = backend == "llvm"
    tag = " [llvm]" if llvm else ""
    jobs = []
    specs = [(j, os.path.splitext(os.path.basename(j))[0]) for j in sorted(glob.glob(os.path.join(ROOT, "tests/runtime/*.json")))]
    # G4 A2: project directories tests/runtime/g4_*/ (spec.json next to root.pruv and main.rs)
    specs += [(j, os.path.basename(os.path.dirname(j)))
              for j in sorted(glob.glob(os.path.join(ROOT, "tests/runtime/g4_*/spec.json")))]
    # G5 A2: project directories tests/runtime/g5_*/ follow the same convention
    specs += [(j, os.path.basename(os.path.dirname(j)))
              for j in sorted(glob.glob(os.path.join(ROOT, "tests/runtime/g5_*/spec.json")))]
    for j, t in specs:
        try:
            spec = json.load(open(j))
            if llvm and isinstance(spec.get("llvm"), dict):   # G4 A3: "llvm": {...} overrides fields on the llvm backend
                spec = dict(spec, **spec["llvm"])
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
                             {"sample": rel_sample(runtime_src(j, t)),
                              "backend": backend, "flags": None, "mode": "spec_error",
                              "group": "runtime"}))
            continue
        for flags, label, suffix in rows:
            name = "runtime/" + t + (" " + label if label else "") + tag
            jobs.append(runtime_job(j, t, spec, flags + extra, name, suffix, llvm))
    return jobs


USAGE = ("usage: run_all.py [--only must_reject|examples|runtime|g3_proof|g6_frontend|g6_proof|g9_frontend|g9_proof|g4_frontend|g4_proof|g5_frontend|g5_reject|g5_proof] [--backend rust|llvm|both] "
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
        if only not in ("must_reject", "examples", "runtime", "g3_proof", "g6_frontend", "g6_proof", "g9_frontend",
                        "g9_proof", "g4_frontend", "g4_proof", "g5_frontend", "g5_reject", "g5_proof"):
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
        if only in (None, "g3_proof"):
            jobs += g3_proof_jobs()
        if only in (None, "g6_frontend"):
            jobs += g6_frontend_jobs()
        if only in (None, "g6_proof"):
            jobs += g6_frontend_jobs("g6_proof", "proof", (("default", []),))
        if only in (None, "g9_frontend"):
            jobs += g9_frontend_jobs()
        if only in (None, "g9_proof"):
            jobs += g9_proof_jobs()
        if only in (None, "g4_frontend"):
            jobs += g4_frontend_jobs()
        if only in (None, "g4_proof"):
            jobs += g4_proof_jobs()
        if only in (None, "g5_frontend"):
            jobs += g5_frontend_jobs()
        if only in (None, "g5_reject"):
            jobs += g5_reject_jobs()
        if only in (None, "g5_proof"):
            jobs += g5_proof_jobs()
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
        null_backend = ("must_reject", "g3_proof", "g6_frontend", "g6_proof", "g9_frontend", "g9_proof", "g4_frontend",
                        "g4_proof", "g5_frontend", "g5_reject", "g5_proof")
        for g in null_backend + ("examples", "runtime"):
            if only in (None, g):
                for b in ([None] if g in null_backend else backends):
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
