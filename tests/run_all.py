"""Run all regression tests.
python tests/run_all.py [--only must_reject|examples|runtime] [--backend rust|llvm|both]"""
import glob, json, os, platform, re, shutil, subprocess, sys, tempfile

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

results = []


def report(name, ok, detail=""):
    results.append(ok)
    line = "%s %s" % ("PASS" if ok else "FAIL", name)
    if not ok and detail:
        line += "  -- " + detail.strip().replace("\n", " ")[:400]
    print(line)


def vowc(src, out, flags=()):
    return subprocess.run([PY, VOWC, src, "-o", out] + list(flags), capture_output=True, text=True, timeout=300)


def vowc_llvm(src, ll, rs, flags=()):
    """LLVM backend: writes IR to ll and Rust bindings to rs."""
    return vowc(src, ll, ["--backend", "llvm", "--rust-bindings", rs] + list(flags))


def llvm_objects(ll, stem, work, count_allocs=False):
    """clang gen.ll and runtime.c to objects in work. Returns (rustc link args, error or None)."""
    gen_o = os.path.join(work, stem + "_gen.o")
    rt_o = os.path.join(work, stem + "_rt.o")
    c = subprocess.run([CLANG, "-O2", CPU_FLAG, "-Wno-override-module", "-c", ll, "-o", gen_o],
                       capture_output=True, text=True, timeout=300)
    if c.returncode != 0:
        return [], "clang (gen.ll): " + c.stderr[-400:]
    extra = ["-DVOW_COUNT_ALLOCS"] if count_allocs else []
    c = subprocess.run([CLANG, "-O2", CPU_FLAG, "-std=c11", "-DVOW_RUST_ALLOCATOR"] + extra + ["-c", RUNTIME_C, "-o", rt_o],
                       capture_output=True, text=True, timeout=300)
    if c.returncode != 0:
        return [], "clang (runtime.c): " + c.stderr[-400:]
    return ["-C", "link-arg=" + gen_o, "-C", "link-arg=" + rt_o], None


def run_must_reject(work):
    for f in sorted(glob.glob(os.path.join(ROOT, "tests/must_reject/*.vow"))):
        name = "must_reject/" + os.path.basename(f)
        try:
            c = vowc(f, os.path.join(work, "mr.rs"))
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
            report(name, ok, detail)
        except subprocess.TimeoutExpired:
            report(name, False, "timeout")
        except Exception as e:
            report(name, False, repr(e))


EXAMPLE_MODES = [("default", []), ("no-verify", ["--no-verify"]), ("trust-callers", ["--trust-callers"])]
ARITH_OR_INDEX = re.compile(r"\b(add|sub|mul|getelementptr)\b")


def run_examples(work, backend):
    llvm = backend == "llvm"
    tag = " [llvm]" if llvm else ""
    for f in sorted(glob.glob(os.path.join(ROOT, "examples/*.vow"))):
        base = os.path.basename(f)
        stem = os.path.splitext(base)[0]
        if base == "bad_index.vow":
            name = "examples/" + base + tag
            try:
                if llvm:
                    c = vowc_llvm(f, os.path.join(work, stem + "_bad.ll"), os.path.join(work, stem + "_bad_llvm.rs"))
                else:
                    c = vowc(f, os.path.join(work, stem + ".rs"))
                report(name, c.returncode == 1, "exit %d (expected rejection) %s" % (c.returncode, c.stdout + c.stderr))
            except subprocess.TimeoutExpired:
                report(name, False, "timeout")
            except Exception as e:
                report(name, False, repr(e))
            continue
        for mode, flags in EXAMPLE_MODES:
            name = "examples/%s [%s]%s" % (base, mode, tag)
            try:
                if llvm:
                    key = "%s_%s_llvm" % (stem, mode)
                    ll = os.path.join(work, key + ".ll")
                    rs = os.path.join(work, key + ".rs")
                    c = vowc_llvm(f, ll, rs, flags)
                    if c.returncode != 0:
                        report(name, False, "vowc exit %d %s" % (c.returncode, c.stdout + c.stderr))
                        continue
                    text = open(ll).read()
                    bodies = body_functions(text)
                    if not bodies:
                        report(name, False, "no @..__vow_body( definitions found in .ll")
                        continue
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
                        report(name, False, bad)
                        continue
                    link, err = llvm_objects(ll, key, work)
                    if err:
                        report(name, False, err)
                        continue
                    main = os.path.join(work, key + "_main.rs")
                    with open(main, "w") as fh:
                        fh.write('#![allow(dead_code, unused_imports)]\n#[path = "%s"] mod sol;\nfn main() {}\n' % rs)
                    r = subprocess.run([RUSTC, "-O", "--edition", "2021", main, "-o", os.path.join(work, key + "_bin")] + link,
                                       capture_output=True, text=True, timeout=300)
                    report(name, r.returncode == 0, "rustc link: " + r.stderr[-400:])
                    continue
                out = os.path.join(work, "%s_%s.rs" % (stem, mode))
                c = vowc(f, out, flags)
                if c.returncode != 0:
                    report(name, False, "vowc exit %d %s" % (c.returncode, c.stdout + c.stderr))
                    continue
                if mode == "no-verify":
                    text = open(out).read()
                    bad = [s for s in ("unsafe", "get_unchecked") if s in text]
                    if bad:
                        report(name, False, "--no-verify output contains %s" % bad)
                        continue
                r = subprocess.run([RUSTC, "--crate-type=lib", "-O", "--edition", "2021", out,
                                    "--crate-name", stem, "-o", os.path.join(work, "lib%s_%s.rlib" % (stem, mode))],
                                   capture_output=True, text=True, timeout=300)
                report(name, r.returncode == 0, "rustc: " + r.stderr[-400:])
            except subprocess.TimeoutExpired:
                report(name, False, "timeout")
            except Exception as e:
                report(name, False, repr(e))


def run_runtime(work, backend):
    llvm = backend == "llvm"
    tag = " [llvm]" if llvm else ""
    jobs = []
    for j in sorted(glob.glob(os.path.join(ROOT, "tests/runtime/*.json"))):
        t = os.path.splitext(os.path.basename(j))[0]
        try:
            spec = json.load(open(j))
        except Exception as e:
            report("runtime/" + t + tag, False, repr(e))
            continue
        matrix = spec.get("flags_matrix")
        if matrix:
            for n, fl in enumerate(matrix):
                jobs.append((j, t, spec, list(fl), "[%s]" % (" ".join(fl) or "default"), "_m%d" % n))
        else:
            jobs.append((j, t, spec, spec.get("flags", []), "", ""))
    for j, t, spec, flags, label, suffix in jobs:
        name = "runtime/" + t + (" " + label if label else "") + tag
        d = os.path.dirname(j)
        try:
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
                report(name, False, "vowc exit %d %s" % (c.returncode, c.stdout + c.stderr))
                continue
            if llvm:
                link, err = llvm_objects(ll, key, work, bool(spec.get("alloc_balance")))
                if err:
                    report(name, False, err)
                    continue
            main = os.path.join(work, key + "_main.rs")
            with open(main, "w") as fh:
                fh.write('#![allow(dead_code, unused_imports)]\n#[path = "%s"] mod sol;\n' % gen)
                fh.write(open(drv).read())
            exe = os.path.join(work, key + "_bin")
            r = subprocess.run([RUSTC, "-O", "--edition", "2021", main, "-o", exe] + link,
                               capture_output=True, text=True, timeout=300)
            if r.returncode != 0:
                report(name, False, "rustc: " + r.stderr[-400:])
                continue
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
                bodies = body_functions(open(ll).read())
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
            report(name, not problems, "; ".join(problems))
        except subprocess.TimeoutExpired:
            report(name, False, "timeout")
        except Exception as e:  # malformed test files etc.
            report(name, False, repr(e))


USAGE = "usage: run_all.py [--only must_reject|examples|runtime] [--backend rust|llvm|both]"


def main():
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
    work = tempfile.mkdtemp(prefix="vowtests_")
    try:
        if only in (None, "must_reject"):
            run_must_reject(work)
        for b in backends:
            if only in (None, "examples"):
                run_examples(work, b)
            if only in (None, "runtime"):
                run_runtime(work, b)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    passed = sum(results)
    print("TOTAL %d/%d" % (passed, len(results)))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
