# -*- coding: utf-8 -*-
"""G5 performance (G5_SPEC section 14 item 7): reversal of 1,000,000 i64 elements, in-place inout vs copy-and-return.

  python bench/g5/perf.py [out.json] [--compiler py|rs] [--backend rust|llvm|both] [--repeat N] [--n N] [--inner K]
                          [--no-verify] [--keep]

Programs: bench/g5/perf/inout_rev.pruv and bench/g5/perf/copy_rev.pruv (same pointwise reversal contract, same host
entries rev_once / rev_n), host driver bench/g5/perf/driver.rs (counting global allocator, checksum-checked outputs).
Defaults: compiler rs (pruvc-rs/target/release/pruvc; `--compiler py` = pruvc/pruvc.py), both back ends, --repeat 10,
--n 1000000, --inner 20, verification on (the contracts are proved), out = bench/g5/results/perf.json.

Per (variant, backend) one driver process runs REPEAT repetitions of
  once   rev_once(a)       setup (one copy of the input) + one reversal
  zero   rev_n(a, 0)       setup alone
  many   rev_n(a, INNER)   setup + INNER reversals
and the repeated-operation time is (many - zero) / INNER per repetition. Allocation counts and bytes come from the
driver's counting global allocator (llvm arrays go through the Rust allocator, runtime.c -DPRUV_RUST_ALLOCATOR).
Peak RSS is that of the whole driver process (/usr/bin/time -l on macOS, -v on Linux). The generated Rust / LLVM IR is
scanned for copy/alloc calls in the inout reversal functions (`rev`, `swap_at`); algorithm-level expectation: 0.
No speedup threshold is applied; the numbers are only recorded (exit 1 only on build/run/check failures or when the
inout reversal body still contains copy/alloc calls)."""
import json
import os
import platform
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
PERF = os.path.join(HERE, "perf")
RUSTC = shutil.which("rustc") or os.path.expanduser("~/.cargo/bin/rustc")
CLANG = shutil.which("clang") or "/usr/bin/clang"
PRUVC_RS = os.path.join(ROOT, "pruvc-rs/target/release/pruvc")
PRUVC_PY = os.path.join(ROOT, "pruvc/pruvc.py")
VENV_PY = os.path.join(ROOT, ".venv/bin/python")
RUNTIME_C = os.path.join(ROOT, "pruvc/runtime.c")
CPU_FLAG = "-mcpu=native" if platform.machine().lower() in ("arm64", "aarch64") else "-march=native"
RUSTC_FLAGS = ["-O", "--edition", "2021", "-C", "target-cpu=native"]
CLANG_FLAGS = ["-O2", CPU_FLAG, "-Wno-override-module"]
RUNTIME_FLAGS = ["-O2", CPU_FLAG, "-std=c11", "-DPRUV_RUST_ALLOCATOR"]
VARIANTS = [("inout", "inout_rev.pruv"), ("copy", "copy_rev.pruv")]
# functions of the inout reversal (names may be mangled with a prefix ending in "_")
INOUT_FNS = ["rev", "swap_at"]
LLVM_COPY_ALLOC = ["@pruv_copy(", "@pruv_alloc(", "@pruv_free(", "@llvm.memcpy", "@memcpy", "@malloc(", "@calloc(",
                   "@free("]
RUST_COPY_ALLOC = [".to_vec()", ".clone()", "vec!", "Vec::", "Box::", "copy_from_slice", ".to_owned()", "alloc"]

USAGE = ("usage: perf.py [out.json] [--compiler py|rs] [--backend rust|llvm|both] [--repeat N] [--n N] [--inner K] "
         "[--no-verify] [--keep]")


def stats(xs):
    xs = list(xs)
    if not xs:
        return None
    s = sorted(xs)
    med = statistics.median(s)
    return {"median": med, "min": s[0], "max": s[-1], "mean": statistics.fmean(s),
            "stdev": statistics.pstdev(s) if len(s) > 1 else 0.0, "runs": len(s)}


def run(cmd, timeout=900, **kw):
    try:
        c = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=timeout, **kw)
        return c.returncode, c.stdout, c.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except OSError as e:
        return -2, "", "cannot execute %s: %s" % (cmd[0], e)


def first_line(s):
    for l in s.splitlines():
        if l.strip():
            return l.strip()
    return None


def compiler_cmd(which):
    if which == "rs":
        return [PRUVC_RS]
    return [VENV_PY if os.path.exists(VENV_PY) else sys.executable, PRUVC_PY]


def git_rev():
    rc, out, _ = run(["git", "-C", ROOT, "rev-parse", "HEAD"], timeout=30)
    return out.strip() if rc == 0 else None


def versions(which):
    v = {"python": sys.version.split()[0], "platform": platform.platform(), "machine": platform.machine(),
         "git_rev": git_rev()}
    rc, out, err = run([RUSTC, "-vV"], timeout=60)
    v["rustc"] = out.strip().splitlines() if rc == 0 else err[-200:]
    m = re.search(r"^host: (\S+)", out, re.M)
    v["rust_host_triple"] = m.group(1) if m else None
    rc, out, err = run([CLANG, "--version"], timeout=60)
    v["clang"] = out.strip().splitlines() if rc == 0 else err[-200:]
    rc, out, _ = run([CLANG, "-dumpmachine"], timeout=60)
    v["clang_target"] = out.strip() if rc == 0 else None
    cmd = compiler_cmd(which)
    rc, out, err = run(cmd + ["--version"], timeout=60)
    v["pruvc"] = {"which": which, "cmd": cmd, "version": first_line(out) if rc == 0 else None}
    return v


def name_matches(sym, names):
    """sym is one of names, maybe mangled (prefix ending in "_") and maybe an internal __pruv_body/__pruv_entry."""
    for suf in ("__pruv_body", "__pruv_entry"):
        if sym.endswith(suf):
            sym = sym[:-len(suf)]
    return any(sym == n or sym.endswith("_" + n) for n in names)


def extract_llvm(text, names):
    """{defined symbol: body text} for functions whose name is one of names or ends with _<name>."""
    out = {}
    for m in re.finditer(r"^define [^\n]*@([\w.$]+)\(", text, re.M):
        sym = m.group(1)
        if name_matches(sym, names):
            end = text.find("\n}", m.end())
            out[sym] = text[m.start():end + 2 if end >= 0 else len(text)]
    return out


def extract_rust(text, names):
    out = {}
    for m in re.finditer(r"\bfn\s+([\w]+)\s*[<(]", text):
        sym = m.group(1)
        if name_matches(sym, names):
            i = text.find("{", m.end())
            if i < 0:
                continue
            depth, j = 0, i
            while j < len(text):
                if text[j] == "{":
                    depth += 1
                elif text[j] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            out[sym] = text[m.start():j + 1]
    return out


def count_calls(bodies, needles):
    counts = {n: sum(b.count(n) for b in bodies.values()) for n in needles}
    return {k: v for k, v in counts.items() if v}, sum(counts.values())


def scan_generated(backend, rs_text, ll_text):
    """Copy/alloc calls remaining in the inout reversal functions (inout variant) and the reversal function (copy)."""
    res = {}
    for variant, _ in VARIANTS:
        names = INOUT_FNS if variant == "inout" else ["rev"]
        if backend == "llvm":
            bodies, needles = extract_llvm(ll_text[variant], names), LLVM_COPY_ALLOC
        else:
            bodies, needles = extract_rust(rs_text[variant], names), RUST_COPY_ALLOC
        found, total = count_calls(bodies, needles)
        res[variant] = {"functions": sorted(bodies), "found": bool(bodies), "calls": found, "total": total,
                        "lines": sum(b.count("\n") + 1 for b in bodies.values()),
                        "excerpt": "\n".join(bodies[k] for k in sorted(bodies))[:6000]}
    return res


def peak_rss(stderr):
    """Peak resident set size in bytes from /usr/bin/time output, or None."""
    m = re.search(r"^\s*(\d+)\s+maximum resident set size", stderr, re.M)       # macOS: bytes
    if m:
        return int(m.group(1))
    m = re.search(r"Maximum resident set size \(kbytes\): (\d+)", stderr)       # GNU time -v
    return int(m.group(1)) * 1024 if m else None


def time_wrapper():
    if os.path.exists("/usr/bin/time"):
        return ["/usr/bin/time", "-l" if sys.platform == "darwin" else "-v"]
    return []


def build_runtime(work):
    rt = os.path.join(work, "runtime.o")
    rc, out, err = run([CLANG] + RUNTIME_FLAGS + ["-c", RUNTIME_C, "-o", rt], timeout=300)
    return (rt, None) if rc == 0 else (None, "clang (runtime.c): " + (err or out)[-600:])


def measure(which, variant, pfile, backend, work, args, rt_o, keep_texts):
    stem = "%s_%s_%s" % (which, variant, backend)
    gen = os.path.join(work, stem + "_gen.rs")
    ll = os.path.join(work, stem + ".ll")
    src = os.path.join(PERF, pfile)
    flags = ["--no-verify"] if args["no_verify"] else []
    cmd = compiler_cmd(which) + [src, "-o", ll if backend == "llvm" else gen]
    if backend == "llvm":
        cmd += ["--backend", "llvm", "--rust-bindings", gen]
    else:
        cmd += ["--backend", "rust"]
    cmd += flags
    row = {"variant": variant, "backend": backend, "pruvc_cmd": cmd, "status": "ok"}
    t0 = time.perf_counter()
    rc, out, err = run(cmd, timeout=900)
    row["compile_s"] = round(time.perf_counter() - t0, 3)
    if rc != 0:
        row.update(status="pruv_error", error=(out + err)[-800:])
        return row
    keep_texts[0][variant] = open(gen, encoding="utf-8").read()
    keep_texts[1][variant] = open(ll, encoding="utf-8").read() if backend == "llvm" else ""
    link = []
    if backend == "llvm":
        gen_o = os.path.join(work, stem + "_gen.o")
        ccmd = [CLANG] + CLANG_FLAGS + ["-c", ll, "-o", gen_o]
        rc, out, err = run(ccmd, timeout=300)
        row["clang_cmd"] = ccmd
        if rc != 0:
            row.update(status="compile_error", error="clang (gen.ll): " + (err or out)[-800:])
            return row
        link = ["-C", "link-arg=" + gen_o, "-C", "link-arg=" + rt_o]
    main = os.path.join(work, stem + "_main.rs")
    with open(main, "w", encoding="utf-8") as fh:
        fh.write('#![allow(dead_code, unused_imports)]\n#[path = "%s"] mod sol;\n' % gen)
        fh.write(open(os.path.join(PERF, "driver.rs"), encoding="utf-8").read())
    exe = os.path.join(work, stem + "_bin")
    rcmd = [RUSTC] + RUSTC_FLAGS + [main, "-o", exe] + link
    row["rustc_cmd"] = rcmd
    rc, out, err = run(rcmd, timeout=900)
    if rc != 0:
        row.update(status="compile_error", error="rustc: " + (err or out)[-800:])
        return row
    rc, out, err = run(time_wrapper() + [exe, str(args["n"]), str(args["repeat"]), str(args["inner"])], timeout=3600)
    if rc != 0:
        row.update(status="run_error", error="exit %d: %s" % (rc, err[-600:]))
        return row
    try:
        d = json.loads(out.strip().splitlines()[-1])
    except (ValueError, IndexError):
        row.update(status="run_error", error="no driver JSON in %r" % out[-300:])
        return row
    if not d.get("ok"):
        row.update(status="check_failed")
        return row
    k = args["inner"]
    ms = lambda xs: [x / 1e6 for x in xs]
    op_ms = [(m - z) / 1e6 / k for m, z in zip(d["many_ns"], d["zero_ns"])]
    row["peak_rss_bytes"] = peak_rss(err)
    row["driver"] = {"n": d["n"], "reps": d["reps"], "inner": d["inner"], "checksum_id": d["checksum_id"],
                     "checksum_rev": d["checksum_rev"], "checksums_checked": True}
    row["time_ms"] = {"setup_inclusive_once": stats(ms(d["once_ns"])), "setup_alone": stats(ms(d["zero_ns"])),
                      "setup_plus_inner": stats(ms(d["many_ns"])), "repeated_op_per_reversal": stats(op_ms)}
    row["raw_ms"] = {"once": ms(d["once_ns"]), "zero": ms(d["zero_ns"]), "many": ms(d["many_ns"]),
                     "repeated_op": op_ms}

    def per_op(key):
        diffs = [m - z for m, z in zip(d["many_" + key], d["zero_" + key])]
        return {"per_reversal": stats([x / k for x in diffs]), "exact": all(x % k == 0 for x in diffs)}

    row["alloc"] = {
        "once": {"allocs": stats(d["once_allocs"]), "frees": stats(d["once_frees"]), "bytes": stats(d["once_bytes"])},
        "setup_alone": {"allocs": stats(d["zero_allocs"]), "frees": stats(d["zero_frees"]),
                        "bytes": stats(d["zero_bytes"])},
        "setup_plus_inner": {"allocs": stats(d["many_allocs"]), "frees": stats(d["many_frees"]),
                             "bytes": stats(d["many_bytes"])},
        "repeated_op": {"allocs": per_op("allocs"), "frees": per_op("frees"), "bytes": per_op("bytes")},
        "note": "counting global allocator in driver.rs; llvm arrays use the Rust allocator (PRUV_RUST_ALLOCATOR)"}
    return row


def parse_args(argv):
    args = {"compiler": "rs", "backend": "both", "repeat": 10, "n": 1000000, "inner": 20, "no_verify": False,
            "keep": False, "out": None}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--compiler", "--backend", "--repeat", "--n", "--inner"):
            if i + 1 >= len(argv):
                return None
            v = argv[i + 1]
            key = a[2:]
            if key in ("repeat", "n", "inner"):
                if not v.isdigit() or int(v) < 1:
                    return None
                v = int(v)
            args[key] = v
            i += 2
        elif a == "--no-verify":
            args["no_verify"] = True
            i += 1
        elif a == "--keep":
            args["keep"] = True
            i += 1
        elif a.startswith("--"):
            return None
        elif args["out"] is None:
            args["out"] = a
            i += 1
        else:
            return None
    if args["compiler"] not in ("py", "rs") or args["backend"] not in ("rust", "llvm", "both"):
        return None
    return args


def ratio(a, b):
    return round(a / b, 4) if a is not None and b else None


def main():
    args = parse_args(sys.argv[1:])
    if args is None:
        print(USAGE)
        return 2
    which = args["compiler"]
    if which == "rs" and not os.path.exists(PRUVC_RS):
        print("missing %s (build pruvc-rs, or use --compiler py)" % PRUVC_RS)
        return 2
    outp = args["out"] or os.path.join(HERE, "results", "perf.json")
    backends = ["rust", "llvm"] if args["backend"] == "both" else [args["backend"]]
    work = tempfile.mkdtemp(prefix="pruvg5_perf_")
    rt_o = None
    if "llvm" in backends:
        rt_o, err = build_runtime(work)
        if err:
            print(err)
            return 1
    rows, scans, failures = [], {}, []
    for backend in backends:
        texts = ({}, {})
        for variant, pfile in VARIANTS:
            row = measure(which, variant, pfile, backend, work, args, rt_o, texts)
            rows.append(row)
            if row["status"] != "ok":
                failures.append("%s/%s: %s %s" % (variant, backend, row["status"], row.get("error", "")[:200]))
        if len(texts[0]) == len(VARIANTS):
            scans[backend] = scan_generated(backend, texts[0], texts[1])
            body = scans[backend]["inout"]
            if not body["found"]:
                failures.append("inout reversal function not found in generated %s code" % backend)
            elif body["total"] != 0:
                failures.append("inout reversal body has %d copy/alloc calls (%s): %s" % (
                    body["total"], backend, body["calls"]))
    comparison = {}
    for backend in backends:
        by = {r["variant"]: r for r in rows if r["backend"] == backend and r["status"] == "ok"}
        if "inout" in by and "copy" in by:
            def med(r, k):
                return r["time_ms"][k]["median"]
            comparison[backend] = {
                "note": "ratios inout/copy of medians, recorded only (no threshold); <1 means inout is faster",
                "setup_inclusive_once": ratio(med(by["inout"], "setup_inclusive_once"),
                                              med(by["copy"], "setup_inclusive_once")),
                "repeated_op_per_reversal": ratio(med(by["inout"], "repeated_op_per_reversal"),
                                                  med(by["copy"], "repeated_op_per_reversal")),
                "peak_rss_ratio": ratio(by["inout"].get("peak_rss_bytes"), by["copy"].get("peak_rss_bytes"))}
    result = {
        "spec": "G5_SPEC 14.7", "task": "reverse %d i64 elements" % args["n"],
        "config": {"n": args["n"], "repeat": args["repeat"], "inner": args["inner"], "compiler": which,
                   "backends": backends, "verify": not args["no_verify"],
                   "meets_min_10_repetitions": args["repeat"] >= 10,
                   "input": "deterministic LCG in driver.rs (seed 0x9E3779B97F4A7C15)",
                   "programs": {v: "bench/g5/perf/" + f for v, f in VARIANTS}, "driver": "bench/g5/perf/driver.rs",
                   "rustc_flags": RUSTC_FLAGS, "clang_flags": CLANG_FLAGS, "runtime_flags": RUNTIME_FLAGS,
                   "optimization": "rustc -O (opt-level 2) / clang -O2, target-cpu native on both"},
        "versions": versions(which),
        "rows": rows, "generated_code_scan": scans, "comparison": comparison,
        "notes": ["timings are in-process Instant around one host call; peak RSS covers the whole driver process "
                  "(input + checks + outputs included)",
                  "repeated-op time = (rev_n(a, inner) - rev_n(a, 0)) / inner per repetition; setup alone = rev_n(a, 0)",
                  "one unrecorded warm-up rev_once precedes the repetitions"],
        "failures": failures}
    od = os.path.dirname(os.path.abspath(outp))
    if not os.path.isdir(od):
        os.makedirs(od)
    with open(outp, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1)
    print("%-6s %-5s %-12s %12s %12s %10s %10s %12s" % ("var", "back", "status", "once ms med", "op ms med",
                                                        "op allocs", "op bytes", "rss MB"))
    for r in rows:
        if r["status"] != "ok":
            print("%-6s %-5s %s" % (r["variant"], r["backend"], r["status"]))
            continue
        t, a = r["time_ms"], r["alloc"]["repeated_op"]
        rss = r.get("peak_rss_bytes")
        print("%-6s %-5s %-12s %12.3f %12.3f %10s %10s %12s" % (
            r["variant"], r["backend"], r["status"], t["setup_inclusive_once"]["median"],
            t["repeated_op_per_reversal"]["median"], a["allocs"]["per_reversal"]["median"],
            a["bytes"]["per_reversal"]["median"], "%.1f" % (rss / 1e6) if rss else "n/a"))
    for b, s in scans.items():
        print("%s: inout reversal copy/alloc calls = %d in %s; copy-variant rev = %d" % (
            b, s["inout"]["total"], s["inout"]["functions"], s["copy"]["total"]))
    for fmsg in failures:
        print("FAIL", fmsg)
    print("wrote %s" % outp)
    if args["keep"]:
        print("kept %s" % work)
    else:
        shutil.rmtree(work, ignore_errors=True)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
